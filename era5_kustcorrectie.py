# -*- coding: utf-8 -*-
"""
era5_kustcorrectie.py -- ERA5 land-sea correction for hourly air temperature
============================================================================

What it corrects
----------------
An ERA5-Land grid cell (0.1 degree, about 11 x 7 km in the Netherlands) that
contains sea or lake water has a damped diurnal cycle: on hot afternoons it
reads too cool, at night often too warm. ERA5 is also too warm at night
inland. At KNMI stations directly on the water the hottest hour of the summer
(TXx) was on average 3.5 C too low (26 stations, May-September 2018-2022).

The model (frozen on 2026-11-19, see era5_kustcorrectie_params.json):

    T = T_cel + w(F) * (T_land + f_land - T_cel) + c * G

  T_cel   the ERA5 hourly temperature the suite already uses
          (era5_seamless, cell_selection=land).
  T_land  mean of the "land cells" within 30 km: ERA5 cells (cell_selection=
          nearest) whose mean summer diurnal amplitude is at least 90% of the
          largest amplitude within 30 km (D = 1 - A/A_ref < 0.10). Each cell
          is brought to the site elevation with 6.5 C/km.
  F       km of land the air has crossed before reaching the site: from the
          site against the ERA5 wind direction to the first water
          (global-land-mask, about 1 km), at most 40 km. A site that lies on
          water in the mask first skips up to 2 km of water.
  w(F)    wmax * (1 - exp(-F / L)): sea air (F = 0) gets no mixing, land air
          gets almost the full land value.
  f_land  hourly standard correction (MOS) of the land reference, fitted on
          inland stations: per UTC hour a linear regression on clearness
          (1 - cloud/100), ln(1 + wind10), the heat of the day and its square,
          clearness x heat, and the deviation of T_land from its UTC-day mean.
          Applied by day (GHI > 10 W/m2) everywhere; at night only at inland
          sites (at least 90% land in the 0.1-degree cell). At the coast the
          night wind is often a land breeze and the inland night correction
          does not fit there.
  G       island term for narrow islands (site on land, less than 50% land in
          the cell, and the island narrower than the cell north-south or
          east-west): GHI/100 * (1 - land fraction of the cell), only for
          GHI > 50 W/m2. Without a land cell T_land = T_cel and only f_land
          and the island term remain.

The correction is applied in full on hot days: UTC days on which the daily
maximum of T_land is at least 24 C, the range the model was fitted on.
[2026-11-27] Below that it fades out linearly: a day weight from 0 at 20 C
to 1 at 24 C multiplies the whole correction, so that there is no sudden
jump at 24 C; on those days the heat of the day in f_land is taken as 0 (as
at 24 C), so the hourly regression is not extrapolated. On days of 20 C or
less, on hours filled from the forecast API, and wherever a required
input is missing the hour is left as ERA5 delivered it, and the column
coastal_correction_applied says so.

How good it is (strict test: station and all stations within 50 km left out
of the fit; groups as in the analysis plan)
  water group (8 stations)  hot afternoons 1.99 -> 1.35 C mean |error|,
                            TXx -3.51 -> -1.91 C (|TXx| 3.51 -> 2.13),
                            nights 1.31 -> 1.05 C
  inland (18 stations)      afternoons 0.66 -> 0.37, nights 1.40 -> 0.59,
                            TXx -1.18 -> -0.58 C
The night error at the coast moved between stations rather than
disappearing (Schiphol -1.4 C, Stavoren +2.1 C). Not yet tested on stations
outside the Netherlands; that test is planned (analysis plan of 18-11-2026,
DWD/DMI stations, and NC State data expected in January 2027). Outside the
North Sea area the model is an extrapolation.

Cost of the data
----------------
Per site, once: the temperatures of all ERA5 cells within 30 km (about 30-45)
for May-September 2018-2022, to determine which cells are land. That is about
2,000 Open-Meteo call units, a fifth of the free daily limit, and is kept in
a cache (ERA5_KUST_CACHE, default ~/.cache/thermopoulos/era5_kust or
%LOCALAPPDATA%\\Thermopoulos\\era5_kust). Per period: the land cells and the
site wind direction for that period only.

If the land-sea mask (pip install global-land-mask) or the network is not
available, nothing is corrected and a warning is given. ERA5_KUST_OFFLINE=1
forbids network requests (cached land cells are still read; used by the
golden-output test).

Source: buurcel_toets.py (Koos de Boer, with a little bit of help from
Claude, Anthropic), version of 18-11-2026; parameters from the run of
19-11-2026. Research software, partially validated.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
PARAMS_FILE = HERE / "era5_kustcorrectie_params.json"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
PAUSE_S = 1.0                     # pause between requests to the archive
# Fit area of the frozen model (KNMI stations); outside it a note is printed.
FIT_AREA = dict(lat=(50.6, 53.6), lon=(3.3, 7.3))


def _laad_parameters(pad: Path = PARAMS_FILE) -> dict:
    with open(pad, encoding="utf-8") as fh:
        P = json.load(fh)
    co = P["f_land"]["coefficients_by_utc_hour"]
    P["_mos"] = {int(u): np.asarray(c, dtype=float) for u, c in co.items()}
    return P


PARAMS = _laad_parameters()
S = PARAMS["settings"]


def cache_map() -> Path:
    eigen = os.environ.get("ERA5_KUST_CACHE")
    if eigen:
        return Path(eigen)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "Thermopoulos" / "era5_kust"
    return Path.home() / ".cache" / "thermopoulos" / "era5_kust"


# ---------------------------------------------------------------- geometry
def km(la1, lo1, la2, lo2) -> float:
    p1, p2 = math.radians(la1), math.radians(la2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def _globe():
    """global-land-mask, or None when the package is not installed."""
    try:
        from global_land_mask import globe
        return globe
    except ImportError:
        return None


def landdeel(lat: float, lon: float, cel: float = 0.10) -> Optional[float]:
    """Fraction of land in the grid cell of size `cel` (degrees) around the
    nearest grid point, sampled on 20 x 20 points. None without the mask."""
    g = _globe()
    if g is None:
        return None
    c0, l0 = round(lat / cel) * cel, round(lon / cel) * cel
    ofs = (np.arange(20) + 0.5) / 20 * cel - cel / 2
    la, lo = np.meshgrid(c0 + ofs, l0 + ofs, indexing="ij")
    return float(g.is_land(la, lo).mean())


def land_tegen_wind(lat: float, lon: float, richting: float,
                    max_km: float = S["fetch_max_km"], stap: float = S["fetch_step_km"],
                    aanloop_km: float = S["fetch_water_lead_in_km"]) -> float:
    """Km of land the air crosses before it reaches the site: from the site
    against the wind (richting = where the wind comes from) to the first water.
    A site on water in the mask first skips up to aanloop_km of water to the
    first land; if there is none, the distance is 0. Same as buurcel_toets.py."""
    g = _globe()
    ks = np.arange(stap, max_km + aanloop_km + stap, stap)
    b = math.radians(richting)
    la = lat + ks * math.cos(b) / 111.2
    lo = lon + ks * math.sin(b) / (111.2 * math.cos(math.radians(lat)))
    land = np.r_[bool(g.is_land(lat, lon)), g.is_land(la, lo)]
    ks = np.r_[0.0, ks]
    start = 0
    if not land[0]:
        eerste = int(np.argmax(land))
        if not land[eerste] or ks[eerste] > aanloop_km:
            return 0.0
        start = eerste
    rest = land[start:]
    if rest.all():
        return float(max_km)
    return float(min(ks[start + np.argmax(~rest)] - ks[start], max_km))


def land_tabel(lat: float, lon: float) -> np.ndarray:
    """Land against the wind for every whole degree of wind direction (0-359)."""
    return np.array([land_tegen_wind(lat, lon, r) for r in range(360)])


def eiland_info(lat: float, lon: float) -> dict:
    """Is the site on an island narrower than the 0.1-degree cell in at least
    one direction? Site on land, less than 50% land in the cell, and width
    north-south < 11.1 km or east-west < 11.1 * cos(lat) km, measured through
    the site in the mask."""
    g = _globe()
    nz = land_tegen_wind(lat, lon, 0, aanloop_km=0) + land_tegen_wind(lat, lon, 180, aanloop_km=0)
    ow = land_tegen_wind(lat, lon, 90, aanloop_km=0) + land_tegen_wind(lat, lon, 270, aanloop_km=0)
    ld = landdeel(lat, lon, S["grid_deg"])
    eiland = (bool(g.is_land(lat, lon)) and ld < S["island_max_land_fraction"]
              and (nz < 11.1 or ow < 11.1 * math.cos(math.radians(lat))))
    return dict(eiland=bool(eiland), breedte_nz_km=nz, breedte_ow_km=ow, landdeel_cel=ld)


# ---------------------------------------------------------------- Open-Meteo
class ArchiefFout(Exception):
    """The archive did not deliver (daily limit, network, unexpected answer)."""


def _vraag(params: dict) -> list:
    """One archive request; returns a list of location answers. Waits on a
    per-minute/per-hour limit, stops on the daily limit."""
    if os.environ.get("ERA5_KUST_OFFLINE") == "1":
        raise ArchiefFout("offline (ERA5_KUST_OFFLINE=1)")
    import requests
    for poging in range(4):
        try:
            r = requests.get(ARCHIVE_URL, params=params, timeout=180)
        except Exception as e:                      # network
            raise ArchiefFout(f"network: {e}") from e
        if r.status_code == 200:
            js = r.json()
            return js if isinstance(js, list) else [js]
        tekst = str(getattr(r, "text", ""))[:300]
        if r.status_code == 429 or "limit" in tekst.lower():
            if "daily" in tekst.lower() or poging == 3:
                raise ArchiefFout(f"Open-Meteo limit: {tekst[:120]}")
            logger.warning("Open-Meteo per-minute/hour limit; waiting 65 s")
            time.sleep(65)
            continue
        raise ArchiefFout(f"Open-Meteo {r.status_code}: {tekst[:120]}")
    raise ArchiefFout("refused repeatedly")


def _rasterpunten(lat: float, lon: float) -> list:
    """0.1-degree grid points whose cell may lie within the land radius."""
    g, rmax = S["grid_deg"], S["land_radius_km"] + 8.0
    c0, l0 = round(lat / g) * g, round(lon / g) * g
    n_la = int(math.ceil(rmax / 111.2 / g)) + 1
    n_lo = int(math.ceil(rmax / (111.2 * math.cos(math.radians(lat))) / g)) + 1
    pts = []
    for i in range(-n_la, n_la + 1):
        for j in range(-n_lo, n_lo + 1):
            la, lo = round(c0 + i * g, 2), round(l0 + j * g, 2)
            if km(lat, lon, la, lo) <= rmax:
                pts.append((la, lo))
    return pts


def _reeksen(antw: list, var: str) -> list:
    uit = []
    for j in antw:
        h = j.get("hourly") or {}
        t, v = h.get("time"), h.get(var)
        if not isinstance(t, list) or not isinstance(v, list) or len(t) != len(v):
            raise ArchiefFout("unexpected answer from the archive")
        s = pd.Series(pd.to_numeric(pd.Series(v), errors="coerce").to_numpy(),
                      index=pd.to_datetime(t))
        uit.append(dict(lat=float(j["latitude"]), lon=float(j["longitude"]),
                        elev=float(j.get("elevation", np.nan)), T=s[~s.index.duplicated()]))
    return uit


def _amplitude(s: pd.Series) -> float:
    s = s.dropna()
    g = s.groupby(s.index.date)
    a = g.max() - g.min()
    return float(a[g.count() >= S["amplitude_min_hours"]].mean())


def _sleutel(lat, lon) -> str:
    return f"{lat:.3f}_{lon:.3f}"


def land_cellen(lat: float, lon: float, ververs: bool = False) -> dict:
    """Which ERA5 cells within 30 km are land (D < 0.10), from their mean
    diurnal amplitude over the reference summers (May-September 2018-2022,
    the fit period). Fetched once per site and kept in the cache."""
    pad = cache_map() / f"landcellen_{_sleutel(lat, lon)}.json"
    if pad.exists() and not ververs:
        return json.loads(pad.read_text(encoding="utf-8"))
    pts = _rasterpunten(lat, lon)
    m0, m1 = S["reference_months"]
    per_cel = {}
    for jaar in S["reference_years"]:
        params = dict(latitude=",".join(f"{p[0]:.2f}" for p in pts),
                      longitude=",".join(f"{p[1]:.2f}" for p in pts),
                      start_date=f"{jaar}-{m0:02d}-01",
                      end_date=f"{jaar}-{m1:02d}-{30 if m1 in (4, 6, 9, 11) else 31}",
                      hourly="temperature_2m", models="era5_seamless",
                      cell_selection="nearest", timezone="GMT")
        antw = _reeksen(_vraag(params), "temperature_2m")
        if len(antw) != len(pts):
            raise ArchiefFout("archive returned a different number of cells")
        for p, a in zip(pts, antw):
            k = (round(a["lat"], 3), round(a["lon"], 3))
            if k in per_cel:
                per_cel[k]["T"] = pd.concat([per_cel[k]["T"], a["T"]])
            else:
                per_cel[k] = dict(req=p, elev=a["elev"], T=a["T"])
        time.sleep(PAUSE_S)
    cellen = []
    for (la, lo), v in per_cel.items():
        d = km(lat, lon, la, lo)
        if d <= S["land_radius_km"]:
            cellen.append(dict(lat=la, lon=lo, req_lat=v["req"][0], req_lon=v["req"][1],
                               elev=v["elev"], afstand_km=d, A=_amplitude(v["T"])))
    if not cellen:
        raise ArchiefFout("no ERA5 cell within 30 km")
    A_ref = max(c["A"] for c in cellen if np.isfinite(c["A"]))
    for c in cellen:
        c["D"] = 1 - c["A"] / A_ref
    uit = dict(lat=lat, lon=lon, A_ref=A_ref, cellen=cellen,
               land=[c for c in cellen if c["D"] < S["land_D_max"]],
               gemaakt=pd.Timestamp.now().isoformat(timespec="seconds"))
    pad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pad.with_suffix(".tmp")
    tmp.write_text(json.dumps(uit), encoding="utf-8")
    tmp.replace(pad)
    return uit


def haal_periode(lat: float, lon: float, land: list, start, eind) -> tuple:
    """T of the land cells and wind direction and elevation at the site, in UTC,
    for the UTC days start-1 .. eind+1 (whole UTC days for the day maximum)."""
    d0 = (pd.Timestamp(start) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    d1 = (pd.Timestamp(eind) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    T_land = None
    if land:
        params = dict(latitude=",".join(f"{c['req_lat']:.2f}" for c in land),
                      longitude=",".join(f"{c['req_lon']:.2f}" for c in land),
                      start_date=d0, end_date=d1, hourly="temperature_2m",
                      models="era5_seamless", cell_selection="nearest", timezone="GMT")
        antw = _reeksen(_vraag(params), "temperature_2m")
        if len(antw) != len(land):
            raise ArchiefFout("archive returned a different number of land cells")
        T_land = antw
    params = dict(latitude=f"{lat}", longitude=f"{lon}", start_date=d0, end_date=d1,
                  hourly="wind_direction_10m", models="era5_seamless",
                  cell_selection="land", timezone="GMT")
    site = _reeksen(_vraag(params), "wind_direction_10m")[0]
    return T_land, site["T"], site["elev"]


# ---------------------------------------------------------------- the model
def w_van_F(F: np.ndarray) -> np.ndarray:
    w = PARAMS["w"]
    return w["wmax"] * (1 - np.exp(-np.asarray(F, dtype=float) / w["L_km"]))


def f_land(uur: np.ndarray, helder, lw, tlev, e_land) -> np.ndarray:
    """Standard correction of the land reference per UTC hour (D = 0)."""
    X = np.c_[np.ones(len(uur)), helder, lw, tlev, tlev ** 2, helder * tlev,
              np.zeros(len(uur)), np.zeros(len(uur)), e_land, np.zeros(len(uur))]
    f = np.zeros(len(uur))
    for u, c in PARAMS["_mos"].items():
        e = uur == u
        if e.any():
            f[e] = X[e] @ c
    return f


def ramp_gewicht(dagmax):
    """Day weight of the correction from the day maximum of T_land (C):
    0 at or below ramp_start_C (20 C), 1 at or above hot_day_T_land_max_C
    (24 C), linear in between. [2026-11-27]"""
    t0, t1 = S["ramp_start_C"], S["hot_day_T_land_max_C"]
    return ((dagmax - t0) / (t1 - t0)).clip(0.0, 1.0)


def correctie(T_cel: pd.Series, T_land: Optional[pd.Series], ghi: pd.Series,
              bewolking: pd.Series, wind10: pd.Series, windrichting: pd.Series,
              tabel_F: np.ndarray, kust: bool, eiland: dict) -> pd.DataFrame:
    """The frozen model on UTC-indexed hourly series. Returns per hour the
    correction in C (0 where not applied) and why. All series in C, W/m2, %,
    m/s and degrees, on the same UTC index as T_cel.

    T_land None: no land cell within 30 km. Then only an island gets a
    correction (T_land = T_cel), as in the fit; other sites get none."""
    idx = T_cel.index
    uit = pd.DataFrame(index=idx)
    uit["correctie"] = 0.0
    uit["reden"] = "not a hot day"
    if T_land is None:
        if not eiland.get("eiland"):
            uit["reden"] = "no land cell within 30 km"
            return uit
        T_land = T_cel.copy()
    T_land = T_land.reindex(idx)
    datum = idx.date
    dagmax = T_land.groupby(datum).transform("max")
    # [2026-11-27] Gradual transition instead of a hard switch at 24 C: the
    # correction is multiplied by a day weight that rises linearly from 0 at a
    # day maximum of T_land of 20 C to 1 at 24 C. From 24 C up (the range the
    # model was fitted and tested on) nothing changes.
    g_dag = ramp_gewicht(dagmax).to_numpy()
    heet = g_dag > 0
    e_land = (T_land - T_land.groupby(datum).transform("mean")).to_numpy()
    helder = (1 - bewolking.reindex(idx) / 100)
    helder = helder.fillna(helder.mean()).to_numpy()
    lw = np.log1p(wind10.reindex(idx).fillna(wind10.mean())).to_numpy()
    # In the transition (20-24 C) the heat of the day is taken as 0, as on a day
    # of exactly 24 C: the hourly regression was fitted on hot days only and is
    # not extrapolated to cooler days.
    tlev = (dagmax - S["hot_day_T_land_max_C"]).clip(0.0, S["tlev_clip_C"]).to_numpy()
    zon = ghi.reindex(idx).fillna(0.0).clip(lower=0).to_numpy()
    uur = idx.hour.to_numpy()

    f = f_land(uur, helder, lw, tlev, e_land)
    dag = zon > S["day_ghi_Wm2"]
    f = np.where(dag | (not kust), f, 0.0)                 # night rule
    dd = windrichting.reindex(idx).to_numpy(dtype=float)
    i = np.nan_to_num(np.round(dd), nan=0.0).astype(int) % 360
    F = np.where(np.isfinite(dd), tabel_F[i], np.median(tabel_F))
    if eiland.get("eiland"):
        G = np.where(zon > S["island_min_ghi_Wm2"],
                     zon / 100 * (1 - (eiland.get("landdeel_cel") or 0.0)), 0.0)
    else:
        G = np.zeros(len(idx))
    corr = (w_van_F(F) * (T_land.to_numpy() + f - T_cel.to_numpy())
            + PARAMS["c_island_per_100Wm2"] * G)
    corr = g_dag * corr
    ok = heet & np.isfinite(corr)
    uit["correctie"] = np.where(ok, corr, 0.0)
    uit["reden"] = np.where(ok, "applied", np.where(heet, "input missing", "not a hot day"))
    uit["F_km"], uit["w"], uit["f_land"], uit["G"] = F, w_van_F(F), f, G
    uit["T_land"] = T_land.to_numpy()
    uit["dag_gewicht"] = g_dag
    return uit


def corrigeer_dataframe(df: pd.DataFrame, lat: float, lon: float,
                        overslaan: Optional[pd.Series] = None) -> tuple:
    """Correct T_air_rural of a Data Engine ERA5 frame (tz-aware index; columns
    T_air_rural, solar_radiation, cloud_cover, wind_10m). Fetches what it
    needs. Returns (correction in C per row as a Series on df.index, info dict).
    Never raises: on any problem the correction is 0 and info['melding'] says
    why. `overslaan`: rows that must not be corrected (forecast-API hours)."""
    nul = pd.Series(0.0, index=df.index)
    info = dict(toegepast=False, melding="", uren=0)
    if _globe() is None:
        info["melding"] = ("ERA5 land-sea correction not applied: package global-land-mask "
                           "is missing (pip install global-land-mask).")
        return nul, info
    if df.empty or "T_air_rural" not in df.columns:
        info["melding"] = "ERA5 land-sea correction not applied: no temperature."
        return nul, info
    try:
        utc = df.index.tz_convert("UTC") if df.index.tz is not None else df.index
        L = land_cellen(lat, lon)
        land = L["land"]
        T_l, dd, elev_site = haal_periode(lat, lon, land, utc.min().date(), utc.max().date())
        uidx = pd.DatetimeIndex(utc).tz_localize(None) if utc.tz is not None else pd.DatetimeIndex(utc)
        T_land = None
        if T_l:
            reeksen = [a["T"] + S["lapse_C_per_m"] * (a["elev"] - elev_site) for a in T_l]
            T_land = pd.concat(reeksen, axis=1).mean(axis=1)
        kust_ld = landdeel(lat, lon, S["grid_deg"])
        kust = kust_ld < S["inland_land_fraction"]
        eil = eiland_info(lat, lon)
        tabel = land_tabel(lat, lon)

        # Work on the full UTC range of the fetched land data, so that the day
        # maximum and day mean of T_land use whole UTC days, also at the ends of
        # the period. Hours outside the frame have no T_cel and stay uncorrected.
        vol = T_land.index if T_land is not None else uidx

        def ser(kol):
            return pd.Series(df[kol].to_numpy(dtype=float), index=uidx).reindex(vol)

        res = correctie(ser("T_air_rural"), T_land, ser("solar_radiation"), ser("cloud_cover"),
                        ser("wind_10m"), dd.reindex(vol), tabel, kust, eil)
        corr = res["correctie"].reindex(uidx).fillna(0.0).to_numpy()
        reden = res["reden"].reindex(uidx).fillna("input missing").to_numpy()
        if overslaan is not None:
            sl = overslaan.reindex(df.index).fillna(False).astype(bool).to_numpy()
            corr = np.where(sl, 0.0, corr)
            reden = np.where(sl, "forecast-API hour", reden)
        n = int((reden == "applied").sum())
        info.update(toegepast=n > 0, uren=n, kust=bool(kust), landdeel_cel=kust_ld,
                    eiland=eil["eiland"], n_landcellen=len(land),
                    reden=pd.Series(reden, index=df.index),
                    melding=(f"ERA5 land-sea correction: {n} hours corrected "
                             f"({len(land)} land cells within 30 km, "
                             f"{'coast' if kust else 'inland'}"
                             f"{', narrow island' if eil['eiland'] else ''})."))
        if not (FIT_AREA["lat"][0] <= lat <= FIT_AREA["lat"][1]
                and FIT_AREA["lon"][0] <= lon <= FIT_AREA["lon"][1]):
            info["melding"] += (" Note: fitted on Dutch stations only; at this location "
                                "the correction has not been tested.")
        return pd.Series(corr, index=df.index), info
    except ArchiefFout as e:
        info["melding"] = f"ERA5 land-sea correction not applied: {e}"
    except Exception as e:                           # never break the pipeline
        logger.exception("ERA5 land-sea correction failed")
        info["melding"] = f"ERA5 land-sea correction not applied (error: {e})."
    return nul, info
