# -*- coding: utf-8 -*-
"""
gevoeligheid.py -- sensitivity of the suite's results to the ERA5 input
=======================================================================

[2026-11-07] Author's decision: Klimatos first. Klimatos rests entirely on
ERA5 (no local anchor that absorbs a systematic error), so it is the module
where a sensitivity analysis matters most.

What this module does
---------------------
It applies a CONTROLLED, HYPOTHETICAL disturbance to the raw hourly weather
(the columns straight from the archive: T_air_rural, RH, pressure, wind_10m,
solar_radiation, cloud_cover), BEFORE the thermal pipeline. The caller then
runs its own unchanged process_weather_data() on the result, so UHI, RH_urban,
wind at 1.5 m, globe temperature, MRT, wet-bulb temperature, WBGT and UTCI all
follow consistently. Nothing downstream is disturbed in isolation.

What it does NOT do
-------------------
- It corrects nothing. Every scenario is a "what if ERA5 were off by this
  much" question; the neutral scenario is the model's own answer.
- It changes no physiology, no calibration and no thresholds.

Disturbance per hour t (all parameters neutral = no change)
------------------------------------------------------------
    dT(t) = dT_night + (dT_day - dT_night) * s(t) + coastal_peak * sin(h(t))

    s(t) = max(0, sin h(t)) / max over that local day of sin h
           -> 1 at that day's solar noon, 0 with the sun below the horizon
    h(t) = solar elevation (pvlib, via thermal_env.calculate_solar_parameters)

The last term has exactly the shape of the Data Engine's coastal correction
(Thermopoulos_Data_Engine.process_weather_data: COASTAL_CORRECTION_PEAK_C *
sin(clipped solar elevation)), NOT normalised per day, so the scenario
"coastal correction as in the Data Engine" reproduces that correction
literally (peak 3.0 C), and its variants only change the peak.

Humidity (humidity = 'constant_dewpoint', the default): the dew point is
taken from the ORIGINAL T and RH, raised by dTd, and RH is recomputed at the
disturbed T (Magnus, a=17.62, b=243.12 -- the same constants as the Data
Engine's dew_point_from_rh / rh_from_dew_point). This is the same physics the
Data Engine uses for its coastal correction and UHI. With humidity =
'constant_rh', RH is left as it is (dTd must then be 0).

Wind and radiation are multiplied by f_wind and f_solar (floored at 0).
Pressure and cloud cover are never changed.

Scenario sets
-------------
STANDARD_SET: neutral; uniform -1, +1, +2, +3 C; day +2 / night -1 C;
dew point +2 C; wind x0.5; solar x1.2.
COASTAL_SET (only for coastal sites): the Data Engine's coastal correction
(peak 3.0 C) and peaks 2, 4 and 6 C. Kept as SCENARIOS, not as a default
(author's decision, 2026-11-07): the 3.0 C peak is validated against one
station on one day (Falmouth KFMH, 2024-08-10), while README Known issue 14
reports 4-6 C at Den Helder. The KNMI station comparison decides later
whether, and with which value, a coastal correction becomes standard.

Author: Koos de Boer. Sole developer of the suite; written with the help of
Claude (Anthropic) as an assistant.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

RAW_COLUMNS = ["T_air_rural", "RH", "pressure", "wind_10m", "solar_radiation", "cloud_cover"]

# Magnus constants -- identical to Thermopoulos_Data_Engine.dew_point_from_rh
_MAGNUS_A, _MAGNUS_B = 17.62, 243.12

# The Data Engine's coastal-correction peak, repeated here (not imported) so
# that Klimatos does not have to import the Data Engine. test_gevoeligheid.py
# checks that the two stay equal.
DATA_ENGINE_COASTAL_PEAK_C = 3.0


def dew_point_from_rh(t_air, rh):
    """Dew point [C] from T [C] and RH [%] (Magnus, same constants as the Data Engine)."""
    t_air = np.asarray(t_air, dtype=float)
    rh = np.clip(np.asarray(rh, dtype=float), 1e-6, 100.0)
    gamma = (_MAGNUS_A * t_air) / (_MAGNUS_B + t_air) + np.log(rh / 100.0)
    return (_MAGNUS_B * gamma) / (_MAGNUS_A - gamma)


def rh_from_dew_point(t_air, dew_point):
    """RH [%] from T and dew point; inverse of dew_point_from_rh, clipped to 0-100."""
    t_air = np.asarray(t_air, dtype=float)
    dew_point = np.asarray(dew_point, dtype=float)
    num = np.exp((_MAGNUS_A * dew_point) / (_MAGNUS_B + dew_point))
    den = np.exp((_MAGNUS_A * t_air) / (_MAGNUS_B + t_air))
    return np.clip(100.0 * num / den, 0.0, 100.0)


@dataclass(frozen=True)
class Scenario:
    """One hypothetical disturbance of the raw ERA5 weather. Defaults = neutral."""
    name: str
    description: str = ""
    dT_day: float = 0.0          # C, at that day's solar noon (shape s(t))
    dT_night: float = 0.0        # C, sun below the horizon
    coastal_peak: float = 0.0    # C, Data Engine coastal shape: peak * sin(solar elevation)
    dTd: float = 0.0             # C, dew-point shift (humidity bias independent of T)
    f_wind: float = 1.0          # factor on wind_10m
    f_solar: float = 1.0         # factor on solar_radiation (GHI)
    humidity: str = "constant_dewpoint"   # or "constant_rh"

    def is_neutral(self) -> bool:
        return (self.dT_day == 0 and self.dT_night == 0 and self.coastal_peak == 0
                and self.dTd == 0 and self.f_wind == 1 and self.f_solar == 1)

    def validate(self) -> None:
        if self.humidity not in ("constant_dewpoint", "constant_rh"):
            raise ValueError(f"Scenario {self.name!r}: humidity must be 'constant_dewpoint' "
                             f"or 'constant_rh', not {self.humidity!r}")
        if self.humidity == "constant_rh" and self.dTd != 0:
            raise ValueError(f"Scenario {self.name!r}: dTd needs humidity='constant_dewpoint'")
        if self.f_wind < 0 or self.f_solar < 0:
            raise ValueError(f"Scenario {self.name!r}: factors must be >= 0")
        for k in ("dT_day", "dT_night", "coastal_peak", "dTd", "f_wind", "f_solar"):
            if not math.isfinite(getattr(self, k)):
                raise ValueError(f"Scenario {self.name!r}: {k} is not a finite number")

    def as_row(self) -> Dict:
        return asdict(self)


NEUTRAL = Scenario("neutral", "ERA5 as delivered (the model's own answer)")

STANDARD_SET: List[Scenario] = [
    NEUTRAL,
    Scenario("T-1", "uniform -1 C", dT_day=-1, dT_night=-1),
    Scenario("T+1", "uniform +1 C", dT_day=1, dT_night=1),
    Scenario("T+2", "uniform +2 C", dT_day=2, dT_night=2),
    Scenario("T+3", "uniform +3 C", dT_day=3, dT_night=3),
    Scenario("day+2/night-1", "ERA5 too cool by day, too warm at night", dT_day=2, dT_night=-1),
    Scenario("Td+2", "dew point +2 C (more humid air, same T)", dTd=2),
    Scenario("wind x0.5", "wind speed halved", f_wind=0.5),
    Scenario("solar x1.2", "solar radiation +20 %", f_solar=1.2),
]

COASTAL_SET: List[Scenario] = [
    Scenario("coastal DE (3.0)", "coastal correction exactly as in the Data Engine",
             coastal_peak=DATA_ENGINE_COASTAL_PEAK_C),
    Scenario("coastal 2", "coastal shape, peak 2 C", coastal_peak=2.0),
    Scenario("coastal 4", "coastal shape, peak 4 C", coastal_peak=4.0),
    Scenario("coastal 6", "coastal shape, peak 6 C", coastal_peak=6.0),
]


# Dutch descriptions for the Klimatos report (which is written in Dutch);
# own scenarios without an entry keep their own description.
DESCRIPTION_NL = {
    "neutral": "ERA5 zoals geleverd (het eigen antwoord van het model)",
    "T-1": "overal -1 °C", "T+1": "overal +1 °C", "T+2": "overal +2 °C", "T+3": "overal +3 °C",
    "day+2/night-1": "ERA5 overdag te koel, 's nachts te warm",
    "Td+2": "dauwpunt +2 °C (vochtiger lucht, zelfde T)",
    "wind x0.5": "windsnelheid gehalveerd", "solar x1.2": "zonnestraling +20 %",
    "coastal DE (3.0)": "kustcorrectie precies als in de Data Engine",
    "coastal 2": "kustvorm, piek 2 °C", "coastal 4": "kustvorm, piek 4 °C", "coastal 6": "kustvorm, piek 6 °C",
}


def scenario_set(coastal: bool = False) -> List[Scenario]:
    """The standard set, plus the coastal scenarios for a coastal site."""
    return list(STANDARD_SET) + (list(COASTAL_SET) if coastal else [])


def load_scenarios(path) -> List[Scenario]:
    """Own scenario list from a JSON file: a list of objects with the Scenario
    fields (only 'name' is required). The neutral scenario is always added
    first if the file does not contain one, because every comparison needs it."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = [Scenario(**d) for d in data]
    for sc in out:
        sc.validate()
    if not any(sc.is_neutral() for sc in out):
        out.insert(0, NEUTRAL)
    names = [sc.name for sc in out]
    if len(set(names)) != len(names):
        raise ValueError("Scenario names must be unique")
    return out


def _solar_elevation(df: pd.DataFrame, lat: float, lon: float, tz: str) -> np.ndarray:
    """Solar elevation [deg, >= 0] per row: taken from the frame when present,
    otherwise computed exactly as the pipeline does (thermal_env)."""
    if "solar_elevation" in df.columns:
        return np.clip(df["solar_elevation"].to_numpy(dtype=float), 0.0, 90.0)
    from thermal_env import calculate_solar_parameters
    tmp = calculate_solar_parameters(pd.DataFrame(index=df.index), lat, lon, tz)
    return np.clip(tmp["solar_elevation"].to_numpy(dtype=float), 0.0, 90.0)


def day_shape(index: pd.DatetimeIndex, elevation_deg: np.ndarray) -> np.ndarray:
    """s(t): sin(elevation) divided by that LOCAL day's maximum; 0 at night."""
    s = np.sin(np.radians(np.clip(elevation_deg, 0.0, 90.0)))
    dates = index.tz_localize(None).normalize() if index.tz is not None else index.normalize()
    day_max = pd.Series(s, index=np.arange(len(s))).groupby(np.asarray(dates)).transform("max").to_numpy()
    return np.divide(s, day_max, out=np.zeros_like(s), where=day_max > 0)


def delta_t(df: pd.DataFrame, sc: Scenario, lat: float, lon: float, tz: str) -> np.ndarray:
    """The temperature disturbance dT(t) [C] of scenario `sc` for every row of `df`."""
    n = len(df)
    if sc.dT_day == 0 and sc.dT_night == 0 and sc.coastal_peak == 0:
        return np.zeros(n)
    elev = _solar_elevation(df, lat, lon, tz)
    dT = np.full(n, float(sc.dT_night))
    if sc.dT_day != sc.dT_night:
        dT = dT + (sc.dT_day - sc.dT_night) * day_shape(df.index, elev)
    if sc.coastal_peak != 0:
        dT = dT + sc.coastal_peak * np.sin(np.radians(elev))
    return dT


def disturb_raw(raw: pd.DataFrame, sc: Scenario, lat: float, lon: float, tz: str) -> pd.DataFrame:
    """Return a NEW frame with only the raw columns, disturbed per scenario `sc`.

    The input frame is not modified. The result is meant to go straight into
    the caller's own process_weather_data(). Extra columns:
        scenario_dT      the temperature disturbance per hour [C]
        scenario_rh_clip True where RH hit 100 % (dew point could not be kept)
    """
    sc.validate()
    missing = [c for c in RAW_COLUMNS if c not in raw.columns]
    if missing:
        raise KeyError(f"raw weather lacks columns {missing}")
    out = raw[RAW_COLUMNS].copy()
    out.attrs = dict(raw.attrs)
    n = len(out)
    if sc.is_neutral():
        out["scenario_dT"] = 0.0
        out["scenario_rh_clip"] = False
        return out

    t0 = out["T_air_rural"].to_numpy(dtype=float)
    rh0 = out["RH"].to_numpy(dtype=float)
    dT = delta_t(raw, sc, lat, lon, tz)
    t1 = t0 + dT
    if sc.humidity == "constant_dewpoint":
        if sc.dTd != 0 or np.any(dT != 0):
            td = dew_point_from_rh(t0, rh0) + sc.dTd
            rh1 = rh_from_dew_point(t1, td)
            clip = rh1 >= 100.0
            # rows with NaN in T or RH stay NaN (the pipeline's nanmax handles them)
            rh1 = np.where(np.isfinite(t0) & np.isfinite(rh0), rh1, np.nan)
        else:
            rh1, clip = rh0, np.zeros(n, dtype=bool)
    else:
        rh1, clip = rh0, np.zeros(n, dtype=bool)

    out["T_air_rural"] = t1
    out["RH"] = rh1
    if sc.f_wind != 1:
        out["wind_10m"] = np.maximum(0.0, out["wind_10m"].to_numpy(dtype=float) * sc.f_wind)
    if sc.f_solar != 1:
        out["solar_radiation"] = np.maximum(0.0, out["solar_radiation"].to_numpy(dtype=float) * sc.f_solar)
    out["scenario_dT"] = dT
    out["scenario_rh_clip"] = clip
    return out


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance [km] (same formula as the Data Engine's _haversine_km)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def scenario_table(scenarios: Iterable[Scenario]) -> pd.DataFrame:
    """The scenarios with all their parameters, for the Excel sheet."""
    return pd.DataFrame([sc.as_row() for sc in scenarios])


# =============================================================================
# [2026-11-08] Data Engine files (HESTIA and PYROX) and backends (HeatLens)
# =============================================================================
# A Data Engine sheet keeps its raw columns (T_air_rural already coastal-
# corrected when the course was declared coastal, RH, pressure, wind_10m,
# solar_radiation, cloud_cover) next to the derived ones, plus the sun
# elevation. disturb_engine_sheet() disturbs the raw columns and runs the
# Data Engine's own process_weather_data() again with coastal_active=False
# (the correction is already in T_air_rural, so it is not applied twice).
# Everything derived -- UHI, RH_urban, wind at 1.5 m, globe, MRT, wet bulb,
# WBGT, UTCI -- is recomputed consistently. HESTIA and PYROX then read the
# scenario file exactly as they read any Data Engine file.

ENGINE_KEEP_COLUMNS = ("coastal_correction_applied", "coastal_correction_degrees")
SCENARIO_FILE_TYPE = "hypothetical, not a correction"


def disturb_engine_sheet(sheet: pd.DataFrame, meta, sc: Scenario) -> pd.DataFrame:
    """Disturb one Data Engine sheet and recompute every derived column.

    sheet : a processed Data Engine frame -- as read from the Excel file
            (local time, no zone) or as held in memory by a backend (zoned).
    meta  : dict or Series with city, population, latitude, longitude,
            timezone and roughness_z0 (the file's Metadata row).
    Returns a frame with the same columns as `sheet` (same order, same index
    form), plus 'scenario_dT'. The neutral scenario returns the sheet as the
    current Data Engine would compute it from its own raw columns.
    """
    import Thermopoulos_Data_Engine as DE
    meta = dict(meta)
    lat, lon, tz = float(meta["latitude"]), float(meta["longitude"]), str(meta["timezone"])
    z0 = meta.get("roughness_z0")
    z0 = 0.5 if z0 is None or (isinstance(z0, float) and not math.isfinite(z0)) else float(z0)
    city = {"name": str(meta.get("city", "?")), "population": int(meta.get("population", 0) or 0)}

    idx = pd.DatetimeIndex(sheet.index)
    zoned = idx.tz is not None
    raw = sheet[RAW_COLUMNS].copy()
    raw.index = idx if zoned else DE._lokaliseer(idx, tz)
    if "solar_elevation" in sheet.columns:
        raw["solar_elevation"] = sheet["solar_elevation"].to_numpy(dtype=float)
    d = disturb_raw(raw, sc, lat, lon, tz)
    dT = d["scenario_dT"].to_numpy()
    out = DE.process_weather_data(d[RAW_COLUMNS].copy(), city, lat, lon, tz,
                                  coastal_active=False, roughness_z0=z0)
    if not zoned:
        out.index = out.index.tz_localize(None)
    for c in ENGINE_KEEP_COLUMNS:
        if c in sheet.columns:
            out[c] = sheet[c].to_numpy()
    for c in sheet.columns:            # a column the pipeline does not make: keep it
        if c not in out.columns:
            out[c] = sheet[c].to_numpy()
    out = out[list(sheet.columns)].copy()
    out["scenario_dT"] = dT
    out.index.name = sheet.index.name
    return out


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-+._" else "_" for ch in name)


def scenario_folder(base_path) -> Path:
    """scenarios/<base file stem>/ next to the base file. A sub-folder, so the
    suite's searches for the newest Thermopoulos_*.xlsx never pick a scenario."""
    base_path = Path(base_path)
    return base_path.parent / "scenarios" / base_path.stem


def make_scenario_file(base_path, sc: Scenario, out_dir=None) -> Path:
    """Write the Data Engine file `base_path` again with every weather sheet
    disturbed per `sc`. Metadata: as the base file, plus scenario name,
    parameters, base file and 'hypothetical, not a correction'."""
    from thermal_env import GLOBE_MODEL
    base_path = Path(base_path)
    out_dir = Path(out_dir) if out_dir else scenario_folder(base_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    with pd.ExcelFile(base_path) as xls:
        sheets = [s for s in xls.sheet_names if s != "Metadata"]
        meta = pd.read_excel(xls, sheet_name="Metadata").iloc[0].to_dict()
        frames = {s: pd.read_excel(xls, sheet_name=s, index_col=0) for s in sheets}
    out = {}
    for s, df in frames.items():
        df.index = pd.to_datetime(df.index)
        out[s] = disturb_engine_sheet(df, meta, sc)
    meta_out = dict(meta)
    meta_out.update({
        "globe_model": GLOBE_MODEL,          # recomputed now, with the current globe model
        "scenario_name": sc.name,
        "scenario_description": sc.description,
        "scenario_parameters": json.dumps(sc.as_row(), ensure_ascii=False),
        "scenario_type": SCENARIO_FILE_TYPE,
        "scenario_base_file": base_path.name,
    })
    path = out_dir / f"Thermopoulos_SCEN_{_safe(sc.name)}_{base_path.stem}.xlsx"
    with pd.ExcelWriter(path, engine="xlsxwriter") as w:
        for s, df in out.items():
            df.to_excel(w, sheet_name=s)
        pd.DataFrame([meta_out]).to_excel(w, sheet_name="Metadata", index=False)
    return path


def make_scenario_files(base_path, scenarios: Iterable[Scenario], out_dir=None) -> Dict[str, Path]:
    """make_scenario_file() for every scenario; {name: path}."""
    return {sc.name: make_scenario_file(base_path, sc, out_dir) for sc in scenarios}


def compare_to_neutral(rows: List[Dict], neutral_name: str = "neutral") -> pd.DataFrame:
    """rows: dicts with scenario, group, outcome, unit, value. Adds the neutral
    value, the difference and the difference in %."""
    df = pd.DataFrame(rows)
    base = df[df["scenario"] == neutral_name][["group", "outcome", "value"]].rename(
        columns={"value": "neutral"})
    df = df.merge(base, on=["group", "outcome"], how="left")
    df["difference"] = df["value"] - df["neutral"]
    with np.errstate(divide="ignore", invalid="ignore"):
        df["difference_pct"] = np.where(np.abs(df["neutral"]) > 0,
                                        100.0 * df["difference"] / np.abs(df["neutral"]), np.nan)
    return df


def plot_dots(table: pd.DataFrame, keys: List, title: str, outpath) -> Optional[str]:
    """Small multiples: per (group, outcome) one dot per scenario, the neutral
    value as a dashed line. `table` in the long form of compare_to_neutral()."""
    import textwrap
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # only outcomes with at least one value (a trend over too few years is all NaN)
    valid = table.dropna(subset=["value"])
    present = set(zip(valid["group"], valid["outcome"]))
    keys = [k for k in keys if k in present]
    if not keys:
        return None
    names = list(dict.fromkeys(table["scenario"]))
    ncol = 2
    nrow = int(np.ceil(len(keys) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(12, 2.0 + 0.32 * len(names) * nrow), squeeze=False)
    y = np.arange(len(names))[::-1]
    for ax, (g, o) in zip(axes.ravel(), keys):
        d = table[(table["group"] == g) & (table["outcome"] == o)].set_index("scenario").reindex(names)
        unit = d["unit"].dropna().iloc[0] if d["unit"].notna().any() else ""
        scale, u = (100.0, "%") if unit == "fraction" else (1.0, unit)
        v = d["value"].to_numpy(dtype=float) * scale
        nv = d["neutral"].dropna()
        if len(nv):
            ax.axvline(float(nv.iloc[0]) * scale, color="0.35", lw=1.0, ls="--", zorder=1)
        ax.scatter(v, y, s=28, color="#1f6fb2", zorder=2)
        ax.set_yticks(y)
        ax.set_yticklabels(names, fontsize=8)
        ax.set_title("\n".join(textwrap.wrap(f"{g}: {o}", 58)), fontsize=9, loc="left")
        ax.set_xlabel(u, fontsize=8)
        ax.tick_params(axis="x", labelsize=8)
        ax.grid(axis="x", color="0.9")
    for ax in axes.ravel()[len(keys):]:
        ax.axis("off")
    fig.suptitle(title, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(outpath, dpi=150)
    plt.close(fig)
    return str(outpath)
