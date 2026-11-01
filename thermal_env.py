"""
thermal_env.py -- shared outdoor thermal-environment physics and location helpers.

One implementation, used by both Thermopoulos_Data_Engine.py and
Klimatos_ClimateShift.py (until 2026-10-25 each module carried its own copy;
the two copies differed only in input guards, verified numerically identical
on valid inputs before merging).

Contents
--------
wind_speed_at_height        logarithmic wind profile (neutral surface layer)
calculate_uhi_oke           Oke (1973) population-based urban heat island
calculate_solar_parameters  solar elevation via pvlib
_calculate_globe_scalar     globe temperature (day: Liljegren et al. 2008)
_calculate_mrt_scalar       ISO 7726 mean radiant temperature
calculate_globe_vectorized / calculate_mrt_vectorized   numpy.vectorize wrappers
geocode_city_candidates     Open-Meteo geocoding (network)
select_city                 pick one candidate (interactive only when asked)

hestia_model.calculate_globe_temperature delegates to _calculate_globe_scalar
(since 2026-10-31); hestia_model.calculate_mrt keeps its own copy of the ISO
7726 conversion with an extra plausibility fallback (MRT outside -50..90 degC).
actualiseer_straling() recomputes globe/MRT/WBGT/UTCI of Data Engine files
written before the 2026-10-31 globe model.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import pvlib
import requests

logger = logging.getLogger(__name__)

GLOBE_DIA = 0.15      # m, standard black globe
EMISSIVITY = 0.95
ABSORPTIVITY = 0.95
SIGMA = 5.67e-8       # W m-2 K-4


def wind_speed_at_height(v_ref, z_ref, z_target, z0=0.1):
    """Logarithmic wind-profile correction.

    Parameters: v_ref reference wind speed [m/s] (scalar or array), z_ref
    reference height [m], z_target target height [m], z0 roughness length [m]
    (0.1 rural ... 1.2 dense urban).

    Neutral stability, no displacement height; valid in the surface layer only.
    The log-law is only physically valid for z0 < z_target < z_ref: at
    z0 == z_target the result would be exactly 0 m/s and above it negative.
    Invalid parameters return the reference wind unchanged, with a warning.
    """
    if z_ref <= 0 or z_target <= 0 or z0 <= 0 or z0 >= z_target or z0 >= z_ref:
        logger.warning(f"Invalid wind profile parameters: z_ref={z_ref}, z_target={z_target}, "
                       f"z0={z0}. Using reference wind.")
        return v_ref
    return v_ref * (np.log(z_target / z0) / np.log(z_ref / z0))


def calculate_uhi_oke(population: int, index: pd.DatetimeIndex) -> pd.Series:
    """Oke (1973) population-based UHI increment [degC] with diurnal factors.

    base = 2.01*log10(population) - 4.06; for cities > 1 million the base is
    reduced by 40 % and capped at 6 degC (modern-city correction; Sydney 99th
    percentile 5.7 degC vs formula 9.4 degC), otherwise capped at 5 degC.
    Diurnal factor: 00-05 h 1.0, 06-09 h 0.6, 10-16 h 0.2, 17-20 h 0.5,
    21-23 h 0.9. No seasonal, climate-zone or green-space dependence.
    References: Oke TR (1973) City size and the urban heat island;
    Stewart & Oke (2012) Local Climate Zones.
    """
    if not population or population <= 0:
        return pd.Series(0.0, index=index)
    base_uhi = 2.01 * np.log10(population) - 4.06
    if population > 1_000_000:
        uhi_max = np.clip(base_uhi * 0.6, 0.0, 6.0)
    else:
        uhi_max = np.clip(base_uhi, 0.0, 5.0)
    hours = index.hour
    factors = np.zeros(len(index))
    factors[(hours >= 0) & (hours <= 5)] = 1.0
    factors[(hours >= 6) & (hours <= 9)] = 0.6
    factors[(hours >= 10) & (hours <= 16)] = 0.2
    factors[(hours >= 17) & (hours <= 20)] = 0.5
    factors[(hours >= 21) & (hours <= 23)] = 0.9
    return pd.Series(uhi_max * factors, index=index)


def calculate_solar_parameters(df: pd.DataFrame, lat: float, lon: float, tz: str) -> pd.DataFrame:
    """Add 'solar_elevation' [deg, clipped at 0] via pvlib."""
    location = pvlib.location.Location(lat, lon, tz=tz)
    try:
        solar_pos = location.get_solarposition(df.index)
        df['solar_elevation'] = solar_pos['elevation'].clip(lower=0)
    except Exception as e:  # noqa: BLE001 -- keep the pipeline running, but say so
        logger.error(f"Solar calculation failed: {e}")
        logger.warning("Setting solar_elevation to 0 - MRT accuracy will be reduced")
        df['solar_elevation'] = 0
    return df


# [2026-10-31] Daytime globe model after Liljegren et al. (2008).
# Source checked: the authors' C code wbgt.c (UChicago Argonne, 2008), as
# distributed in github.com/mdljts/wbgt (src/wbgt.c, wbgt.h): functions
# Tglobe(), calc_solar_parameters(), emis_atm(), esat(). Re-implemented here
# from those equations (no code copied). Constants as in wbgt.h, except the
# convective coefficient: the suite keeps the ISO 7726 h_c for the standard
# 0.15 m globe, the same h_c that converts globe temperature into MRT below,
# so globe and MRT stay consistent (Liljegren: 0.0508 m globe, h from a
# sphere-in-air Nusselt correlation).
GLOBE_MODEL = "liljegren2008_iso7726h"
LJ_ALB_GLOBE = 0.05      # wbgt.h ALB_GLOBE
LJ_ALB_SFC = 0.45        # wbgt.h ALB_SFC (surface albedo, Liljegren default)
LJ_EMIS_SFC = 0.999      # wbgt.h EMIS_SFC
LJ_SOLAR_CONST = 1367.0  # wbgt.h SOLAR_CONST (earth-sun distance not applied: <= 3.4 %)
LJ_CZA_MIN = 0.00873     # wbgt.h CZA_MIN (sun elevation 0.5 deg)
LJ_NORMSOLAR_MAX = 0.85  # wbgt.h NORMSOLAR_MAX


def _esat_hpa(t_c):
    """Saturation vapour pressure over water [hPa], Liljegren wbgt.c esat()
    (Buck 1981 form incl. the 1.004 moist-air factor)."""
    tk = t_c + 273.15
    return 1.004 * 6.1121 * np.exp(17.502 * (tk - 273.15) / (tk - 32.18))


def emis_atm(t_c, rh):
    """Clear-sky atmospheric emissivity, Liljegren wbgt.c emis_atm()
    (Oke 1987): 0.575 * e^0.143, e vapour pressure [hPa], rh in %."""
    return 0.575 * (max(rh, 0.0) / 100.0 * _esat_hpa(t_c)) ** 0.143


def direct_fraction(ghi, solar_elev):
    """Liljegren calc_solar_parameters(): (ghi_used, fdir, cza).

    cza = cos(zenith) = sin(elevation). The irradiance is capped at 0.85 of
    the top-of-atmosphere value (sensor/forecast errors) and the direct-beam
    fraction is exp(3 - 1.34 s - 1.65/s), clipped to 0 .. 0.9.
    """
    cza = np.sin(np.radians(solar_elev))
    toa = LJ_SOLAR_CONST * max(0.0, cza) if cza >= LJ_CZA_MIN else 0.0
    if toa <= 0:
        return ghi, 0.0, cza
    s = min(ghi / toa, LJ_NORMSOLAR_MAX)
    ghi_used = s * toa
    fdir = float(np.clip(np.exp(3.0 - 1.34 * s - 1.65 / s), 0.0, 0.9)) if s > 0 else 0.0
    return ghi_used, fdir, cza


def _globe_liljegren(t_c, ghi, h_c, solar_elev, rh, alb_sfc=LJ_ALB_SFC):
    """Liljegren globe energy balance, solved with Newton's method [degC].

    eps_g*sigma*Tg^4 + h(Tg-Ta) = eps_g*sigma*0.5*(eps_a*Ta^4 + eps_sfc*Ts^4)
        + 0.5*(1-alb_g)*S*[fdir*(1/(2 cza) - 1) + 1 + alb_sfc],  Ts = Ta.
    Equivalent to: direct beam DNI/4, diffuse from the sky (1-fdir)*S/2,
    ground-reflected alb_sfc*S/2, half the long-wave from the sky, half from
    the ground at air temperature.
    """
    ta = t_c + 273.15
    s_used, fdir, cza = direct_fraction(ghi, solar_elev)
    zon = 0.0
    if s_used > 0:
        geom = (fdir * (1.0 / (2.0 * cza) - 1.0) if fdir > 0 else 0.0) + 1.0 + alb_sfc
        zon = 0.5 * (1.0 - LJ_ALB_GLOBE) * s_used * geom
    lw_in = EMISSIVITY * SIGMA * 0.5 * (emis_atm(t_c, rh) * ta ** 4 + LJ_EMIS_SFC * ta ** 4)
    tg = ta
    for _ in range(50):
        f = EMISSIVITY * SIGMA * tg ** 4 + h_c * (tg - ta) - lw_in - zon
        d = 4 * EMISSIVITY * SIGMA * tg ** 3 + h_c
        stap = f / d
        tg -= stap
        if abs(stap) < 1e-4:
            break
    return tg - 273.15


def _calculate_globe_scalar(dry_bulb, ghi, wind, solar_elev, pressure, cloud, aqi=1, rh=50.0):
    """Globe temperature [degC] for a 0.15 m black globe.

    dry_bulb [degC], ghi [W/m2], wind [m/s] at globe height, solar_elev [deg],
    pressure [hPa] (unused, kept for signature compatibility), cloud [%],
    aqi 1-5 (haze reduces the night-sky depression), rh [%] (sky emissivity).

    Day [2026-10-31]: Liljegren et al. (2008) energy balance (see
    _globe_liljegren): direct/diffuse split of the global radiation, ground
    reflection, sky long-wave from humidity. Clipped to air-3 .. air+30
    (sanity bounds only). Until 2026-10-30 the day model took 0.95*GHI/4,
    surroundings at air temperature, clipped at air+15/20; that
    underestimated the globe temperature in strong and low sun.
    Night (unchanged): sky-radiation estimate, clipped to air-3 .. air+1.
    Any NaN input gives NaN (Python's max(0.1, NaN) would otherwise silently
    turn missing wind into 'calm').
    """
    if any(np.isnan(x) for x in (dry_bulb, ghi, wind, solar_elev, pressure, cloud, rh)):
        return np.nan
    t_air_k = dry_bulb + 273.15
    eff_wind = max(0.1, wind)
    h_c = 6.3 * (eff_wind ** 0.6) / (GLOBE_DIA ** 0.4)
    if ghi <= 0 or solar_elev <= 0:
        sky_depression = 10 - (cloud / 100) * 6
        if aqi > 3:
            sky_depression -= 2
        sky_temp_k = t_air_k - sky_depression
        net_rad = EMISSIVITY * SIGMA * (sky_temp_k ** 4 - t_air_k ** 4)
        t_globe = dry_bulb + (net_rad / h_c)
        return max(dry_bulb - 3, min(dry_bulb + 1, t_globe))
    t_globe_c = _globe_liljegren(dry_bulb, ghi, h_c, solar_elev, rh)
    if np.isnan(t_globe_c):
        return np.nan
    return max(dry_bulb - 3, min(dry_bulb + 30, t_globe_c))


def _calculate_mrt_scalar(tg, ta, v, ghi, elev):
    """ISO 7726 mean radiant temperature [degC] from globe temperature tg,
    air temperature ta, wind v [m/s], ghi [W/m2] and solar elevation [deg].
    Clipped to tg-2 .. tg+30 in sunshine (was tg+15 until 2026-10-30; with
    the Liljegren globe the ISO conversion legitimately gives MRT 15-25 degC
    above the globe in strong sun) and ta-15 .. ta+3 otherwise.
    Any NaN input gives NaN."""
    if any(np.isnan(x) for x in (tg, ta, v, ghi, elev)):
        return np.nan
    tg_k = tg + 273.15
    ta_k = ta + 273.15
    eff_wind = max(0.1, v)
    h_c = 6.3 * (eff_wind ** 0.6) / (GLOBE_DIA ** 0.4)
    conv_term = (h_c / (EMISSIVITY * SIGMA)) * (tg_k - ta_k)
    mrt_k4 = (tg_k ** 4) + conv_term
    if mrt_k4 < 0:
        return tg
    mrt_c = (mrt_k4 ** 0.25) - 273.15
    if ghi > 0 and elev > 0:
        return np.clip(mrt_c, tg - 2, tg + 30)
    return np.clip(mrt_c, ta - 15, ta + 3)


calculate_globe_vectorized = np.vectorize(_calculate_globe_scalar)
calculate_mrt_vectorized = np.vectorize(_calculate_mrt_scalar)


_STRALING_NODIG = ("T_air_urban", "solar_radiation", "solar_elevation", "cloud_cover", "pressure", "RH")


def actualiseer_straling(df: pd.DataFrame, meta) -> tuple:
    """[2026-10-31] Bring T_globe, MRT, WBGT and UTCI of a Data Engine sheet
    up to the current globe model.

    Files written before 2026-10-31 carry globe/MRT values from the older
    globe model (no 'globe_model' entry in their Metadata). Their input
    columns (urban air temperature, RH_urban, measured/forecast radiation,
    sun elevation, 1.5 m wind, cloud, pressure) are all stored, so the
    radiation chain can be recomputed exactly as the Data Engine now does it.
    Files that already name the current model, that were not written by the
    Data Engine (no 'model_version' Thermopoulos... in Metadata: hand-made or
    synthetic files keep the values they were given) or that lack an input
    column are returned unchanged.

    meta: dict or pandas Series from the Metadata sheet (may be None).
    Returns (df, recomputed: bool).
    """
    meta = {} if meta is None else dict(meta)
    if str(meta.get("globe_model", "")).strip() == GLOBE_MODEL:
        return df, False
    # only files the Data Engine wrote (its Metadata names the model version);
    # hand-made or synthetic files keep the values they were given
    if not str(meta.get("model_version", "")).strip().lower().startswith("thermopoulos"):
        return df, False
    if not set(_STRALING_NODIG) <= set(df.columns) or not (
            "wind_1.5m" in df.columns or "wind_10m" in df.columns):
        return df, False
    df = df.copy()
    rh = (df["RH_urban"] if "RH_urban" in df.columns else df["RH"]).to_numpy(dtype=float)
    ta = df["T_air_urban"].to_numpy(dtype=float)
    if "wind_1.5m" in df.columns:
        w15 = df["wind_1.5m"].to_numpy(dtype=float)
    else:
        try:
            z0 = float(meta.get("roughness_z0", 0.1))
        except (TypeError, ValueError):
            z0 = 0.1
        w15 = np.asarray(wind_speed_at_height(df["wind_10m"].to_numpy(dtype=float), 10.0, 1.5,
                                              z0=z0 if np.isfinite(z0) else 0.1), dtype=float)
    ghi = df["solar_radiation"].to_numpy(dtype=float)
    el = df["solar_elevation"].to_numpy(dtype=float)
    tg = calculate_globe_vectorized(ta, ghi, w15, el, df["pressure"].to_numpy(dtype=float),
                                    df["cloud_cover"].to_numpy(dtype=float), 1, rh=rh)
    mrt = calculate_mrt_vectorized(tg, ta, w15, ghi, el)
    df["T_globe"], df["MRT"] = tg, mrt
    from pythermalcomfort.models import utci, wbgt
    if "WBGT" in df.columns:
        if "T_wetbulb" in df.columns:
            twb = df["T_wetbulb"].to_numpy(dtype=float)
        else:
            from pythermalcomfort.utilities import wet_bulb_tmp
            twb = wet_bulb_tmp(tdb=ta, rh=rh)
        r = wbgt(twb=twb, tg=tg, tdb=ta, with_solar_load=True)
        df["WBGT"] = r.wbgt if hasattr(r, "wbgt") else r
    if "UTCI" in df.columns and "wind_10m" in df.columns:
        r = utci(tdb=ta, tr=mrt, v=np.clip(df["wind_10m"].to_numpy(dtype=float), 0.5, 17.0), rh=rh)
        df["UTCI"] = r.utci if hasattr(r, "utci") else r
    return df, True


def geocode_city_candidates(city: str, max_results: int = 7) -> List[Dict]:
    """Geocode a place name with the Open-Meteo geocoding API (network)."""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city, "count": max_results, "language": "en", "format": "json"}
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.error(f"Geocoding failed: {e}")
        raise
    if "results" not in data:
        raise ValueError(f"No locations found for '{city}'.")
    return data["results"]


def select_city(candidates: List[Dict], choice: Optional[int] = None,
                interactive: Optional[bool] = None) -> Dict:
    """Pick one geocoding candidate.

    choice      : 1-based index; when given, no prompt is shown.
    interactive : None (default) = ask only when running in a terminal and
                  the environment variable HESTIA_NONINTERACTIVE is not set;
                  False = never ask (take the first, most populous match).
    """
    if not candidates:
        raise ValueError("No candidates to choose from.")
    if choice is not None:
        if not 1 <= int(choice) <= len(candidates):
            raise ValueError(f"choice must be 1..{len(candidates)}")
        return candidates[int(choice) - 1]
    if interactive is None:
        interactive = (os.environ.get("HESTIA_NONINTERACTIVE") is None
                       and hasattr(os.sys.stdin, "isatty") and os.sys.stdin.isatty())
    if len(candidates) == 1 or not interactive:
        return candidates[0]
    print("\nMultiple locations found:\n")
    for i, c in enumerate(candidates, start=1):
        print(f"[{i}] {c['name']}, {c.get('country', 'Unknown')} "
              f"({c.get('admin1', '')}) - Pop: {c.get('population', 'unknown')}")
    while True:
        try:
            pick = int(input(f"\nSelect location [1-{len(candidates)}]: "))
            if 1 <= pick <= len(candidates):
                return candidates[pick - 1]
        except ValueError:
            pass
        print("Invalid selection.")
