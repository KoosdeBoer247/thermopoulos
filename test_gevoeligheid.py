"""[2026-11-07] ERA5 sensitivity analysis (gevoeligheid.py + Klimatos).

Runs offline: the archive download is replaced by synthetic ERA5-like years.
Checks
  1. a neutral scenario changes nothing, in the raw weather and in Klimatos;
  2. Klimatos gives exactly the same annual table with and without scenarios;
  3. a uniform shift moves T_air_max by exactly that shift and leaves its
     Theil-Sen trend unchanged;
  4. the dew point is kept (constant_dewpoint) and RH falls when T rises;
  5. the day/night shape: dT_night at night, dT_day at each day's solar noon;
  6. the coastal scenario reproduces the Data Engine's coastal correction
     (same peak, same shape, same RH) exactly;
  7. the grid cell of the archive reply is kept and its distance reported;
  8. own scenario files: neutral added, duplicate names refused;
  9. Excel sheets and report section are written;
 10. Data Engine scenario files (HESTIA, PYROX): neutral equals the base
     file, a shift moves every derived column, file labelled, in-memory form;
 11. PYROX and HESTIA under scenarios; HESTIA repeats exactly with one seed.
"""
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
logging.disable(logging.WARNING)

import gevoeligheid as gv           # noqa: E402
import Klimatos_ClimateShift as K   # noqa: E402

fails = []
LAT, LON, TZ = 52.37, 4.89, "Europe/Amsterdam"


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


def synth_year(lat, lon, tz, year):
    """Synthetic ERA5-like year: seasons, a daily cycle, warm spells, a slow trend."""
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h", tz="UTC").tz_convert(tz)
    rng = np.random.default_rng(year)
    d, h = idx.dayofyear.values, idx.hour.values
    seas = np.sin((d - 110) / 365.25 * 2 * np.pi)
    diur = np.sin((h - 9) / 24 * 2 * np.pi)
    daynoise = np.repeat(rng.normal(0, 3, 400), 24)[: len(idx)]
    T = 11 + 11 * seas + 5.5 * diur + daynoise + 0.04 * (year - 1980)
    RH = np.clip(72 - 18 * diur + rng.normal(0, 5, len(idx)), 15, 100)
    sol = np.clip(np.sin((h - 6) / 12 * np.pi), 0, None) * (520 + 330 * seas) * rng.uniform(0.4, 1.0, len(idx))
    df = pd.DataFrame({"T_air_rural": T, "RH": RH, "pressure": 1012.0 + rng.normal(0, 6, len(idx)),
                       "wind_10m": np.abs(rng.normal(4.0, 1.8, len(idx))), "solar_radiation": sol,
                       "cloud_cover": rng.uniform(0, 100, len(idx))}, index=idx)
    df.index.name = "time"
    df.attrs.update({"grid_latitude": lat + 0.03, "grid_longitude": lon - 0.04, "grid_elevation": 2.0})
    return df


K.fetch_hourly_year = synth_year
K.REQUEST_PAUSE_S = 0
CITY = {"name": "Synth", "population": 741636}
Y0, Y1 = 1993, 2002

# ---------------------------------------------------------------- 1, 4, 5
print("Raw weather")
raw = synth_year(LAT, LON, TZ, 1995)
n = gv.disturb_raw(raw, gv.NEUTRAL, LAT, LON, TZ)
check("neutral: raw columns unchanged", n[gv.RAW_COLUMNS].equals(raw[gv.RAW_COLUMNS]))
check("neutral: input frame not modified", list(raw.columns) == gv.RAW_COLUMNS)

p2 = gv.disturb_raw(raw, gv.Scenario("T+2", dT_day=2, dT_night=2), LAT, LON, TZ)
check("T+2: temperature +2 everywhere",
      np.allclose(p2["T_air_rural"] - raw["T_air_rural"], 2.0, atol=1e-12))
td0 = gv.dew_point_from_rh(raw["T_air_rural"], raw["RH"])
td1 = gv.dew_point_from_rh(p2["T_air_rural"], p2["RH"])
ok = ~p2["scenario_rh_clip"].to_numpy()
check("T+2: dew point kept", np.nanmax(np.abs(td1[ok] - td0[ok])) < 1e-6,
      f"max {np.nanmax(np.abs(td1[ok] - td0[ok])):.1e} C")
check("T+2: RH falls", bool((p2["RH"] <= raw["RH"] + 1e-9).all()))
prh = gv.disturb_raw(raw, gv.Scenario("rh", dT_day=2, dT_night=2, humidity="constant_rh"), LAT, LON, TZ)
check("constant_rh: RH unchanged", prh["RH"].equals(raw["RH"]))
ptd = gv.disturb_raw(raw, gv.Scenario("Td+2", dTd=2), LAT, LON, TZ)
dtd = gv.dew_point_from_rh(ptd["T_air_rural"], ptd["RH"]) - td0
okd = ~ptd["scenario_rh_clip"].to_numpy()
check("Td+2: dew point +2, T unchanged",
      np.allclose(dtd[okd], 2.0, atol=1e-6) and ptd["T_air_rural"].equals(raw["T_air_rural"]))

dn = gv.disturb_raw(raw, gv.Scenario("dn", dT_day=2, dT_night=-1), LAT, LON, TZ)
elev = gv._solar_elevation(raw, LAT, LON, TZ)
night = elev <= 0
dT = dn["scenario_dT"].to_numpy()
check("day/night: -1 with the sun below the horizon", np.allclose(dT[night], -1.0))
daily_max = pd.Series(dT, index=raw.index).groupby(raw.index.date).max()
sun_days = pd.Series(elev > 0, index=raw.index).groupby(raw.index.date).any()
# (the year requested in GMT ends with one local night hour of the next day)
check("day/night: +2 at each day's solar noon", np.allclose(daily_max[sun_days].values, 2.0),
      f"{int(sun_days.sum())} days with sun")
pw = gv.disturb_raw(raw, gv.Scenario("w", f_wind=0.5, f_solar=1.2), LAT, LON, TZ)
check("factors on wind and radiation",
      np.allclose(pw["wind_10m"], raw["wind_10m"] * 0.5)
      and np.allclose(pw["solar_radiation"], raw["solar_radiation"] * 1.2))
try:
    gv.Scenario("x", dTd=1, humidity="constant_rh").validate()
    check("dTd with constant_rh refused", False)
except ValueError:
    check("dTd with constant_rh refused", True)

# ---------------------------------------------------------------- 6
print("Coastal scenario vs the Data Engine's coastal correction")
import Thermopoulos_Data_Engine as DE   # noqa: E402
check("same peak value as the Data Engine",
      gv.DATA_ENGINE_COASTAL_PEAK_C == DE.COASTAL_CORRECTION_PEAK_C,
      f"{gv.DATA_ENGINE_COASTAL_PEAK_C} vs {DE.COASTAL_CORRECTION_PEAK_C}")
sl = raw.loc["1995-07-01":"1995-07-10"].copy()
de = DE.process_weather_data(sl.copy(), CITY, LAT, LON, TZ, coastal_active=True, roughness_z0=0.5)
co = gv.disturb_raw(sl, gv.COASTAL_SET[0], LAT, LON, TZ)
check("coastal: same temperature as the Data Engine",
      np.allclose(co["T_air_rural"].values, de["T_air_rural"].values, atol=1e-9),
      f"max diff {np.max(np.abs(co['T_air_rural'].values - de['T_air_rural'].values)):.1e}")
check("coastal: same RH as the Data Engine",
      np.allclose(co["RH"].values, de["RH"].values, atol=1e-9))

# ---------------------------------------------------------------- 2, 3, 7
print("Klimatos with scenarios (synthetic years, takes about a minute)")
plain = K.build_annual_maxima(LAT, LON, TZ, CITY, Y0, Y1, apply_uhi=False)
scen = [gv.NEUTRAL, gv.STANDARD_SET[1], gv.STANDARD_SET[3], gv.STANDARD_SET[5], gv.COASTAL_SET[0]]
recs, grid = {}, {}
with_s = K.build_annual_maxima(LAT, LON, TZ, CITY, Y0, Y1, apply_uhi=False,
                               scenarios=scen, scenario_records=recs, grid_info=grid)
same = True
try:
    pd.testing.assert_frame_equal(plain, with_s, check_exact=True)
except AssertionError:
    same = False
check("annual table identical with and without scenarios", same)
sa = {k: pd.DataFrame(v).set_index("year").sort_index() for k, v in recs.items()}
neu = sa["neutral"].drop(columns=[c for c in sa["neutral"].columns if c not in plain.columns])
check("neutral scenario equals the main run", neu[plain.columns].equals(plain))
check("every scenario has every year", all(len(v) == Y1 - Y0 + 1 for v in sa.values()))
d2 = sa["T+2"]["T_air_max"] - plain["T_air_max"]
check("T+2: T_air_max exactly +2 (UHI off)", np.allclose(d2, 2.0, atol=1e-9), f"{d2.min():.6f}..{d2.max():.6f}")
win = (Y0, Y1)
sens = K.analyze_sensitivity(sa, scen, ref_window=(Y0, 1997), latest_window=(1998, Y1), trend_period=win)
tr = sens[(sens["group"] == "T_air_max") & sens["outcome"].str.startswith("trend")].set_index("scenario")
check("uniform shift leaves the T_air_max trend unchanged",
      abs(tr.loc["T+2", "difference"]) < 1e-9 and abs(tr.loc["T-1", "difference"]) < 1e-9,
      f"T+2 {tr.loc['T+2', 'difference']:.1e}, T-1 {tr.loc['T-1', 'difference']:.1e}")
check("neutral differences are zero", np.nanmax(np.abs(sens.loc[sens.scenario == "neutral", "difference"])) == 0)
check("grid cell reported", grid.get("grid_latitude") == LAT + 0.03 and grid.get("grid_distance_km", 0) > 0,
      f"{grid.get('grid_distance_km')} km")

# ---------------------------------------------------------------- 8
print("Own scenario file")
with tempfile.TemporaryDirectory() as tmp:
    f = Path(tmp) / "s.json"
    f.write_text(json.dumps([{"name": "warm", "dT_day": 1.5, "dT_night": 0.5}]), encoding="utf-8")
    ls = gv.load_scenarios(f)
    check("neutral added in front", ls[0].is_neutral() and ls[1].name == "warm")
    f.write_text(json.dumps([{"name": "a"}, {"name": "a", "dT_day": 1}]), encoding="utf-8")
    try:
        gv.load_scenarios(f)
        check("duplicate names refused", False)
    except ValueError:
        check("duplicate names refused", True)

# ---------------------------------------------------------------- 9
print("Excel and report")
with tempfile.TemporaryDirectory() as tmp:
    old = os.getcwd()
    os.chdir(tmp)
    try:
        rng_df = K.sensitivity_range_table(sens)
        meta = {"city": "Synth", "latitude": LAT, "longitude": LON, **grid}
        path = K.save_results(plain, {}, [], meta,
                              sensitivity={"Sensitivity": sens, "Sensitivity_Range": rng_df,
                                           "Sensitivity_Scenarios": gv.scenario_table(scen)})
        sheets = pd.ExcelFile(path).sheet_names
        check("Excel sheets written", {"Sensitivity", "Sensitivity_Range", "Sensitivity_Scenarios"} <= set(sheets))
        from generate_klimatos_report import generate_klimatos_report
        txt = generate_klimatos_report("Synth", meta, plain, (Y0, 1997), (1998, Y1), "r.md",
                                       sensitivity_df=sens, sensitivity_range_df=rng_df,
                                       sensitivity_scenarios_df=gv.scenario_table(scen))
        check("report: sensitivity section and grid cell",
              "## 10. Gevoeligheid voor de ERA5-invoer" in txt and "## 11. Herkomst" in txt
              and "Gebruikte rastercel" in txt)
        txt0 = generate_klimatos_report("Synth", {"city": "Synth"}, plain, (Y0, 1997), (1998, Y1), "r0.md")
        check("report without sensitivity still works", "Niet uitgevoerd voor deze run." in txt0)
    finally:
        os.chdir(old)

# ---------------------------------------------------------------- 10, 11
print("Data Engine files (HESTIA / PYROX): scenario weather files")
import run_gevoeligheid as rg   # noqa: E402
from thermopoulos_loader import ThermopoulosData   # noqa: E402
BASE = HERE / "DtD2024_Amsterdam_hindcast.xlsx"
with tempfile.TemporaryDirectory() as tmp:
    files = gv.make_scenario_files(BASE, [gv.NEUTRAL, gv.STANDARD_SET[3], gv.COASTAL_SET[0]], out_dir=tmp)
    o = pd.read_excel(BASE, "Historical_Custom", index_col=0)
    nn = pd.read_excel(files["neutral"], "Historical_Custom", index_col=0)
    p2 = pd.read_excel(files["T+2"], "Historical_Custom", index_col=0)
    num = [c for c in o.columns if o[c].dtype != bool and c not in ("T_wetbulb", "WBGT")]
    check("neutral file: same columns, same order, plus scenario_dT",
          list(nn.columns) == list(o.columns) + ["scenario_dT"])
    check("neutral file equals the base file (except stored wet-bulb rounding)",
          float((nn[num] - o[num]).abs().max().max()) < 1e-9,
          f"max {float((nn[num] - o[num]).abs().max().max()):.1e}")
    check("neutral file: wet bulb and WBGT within the stored rounding",
          float((nn["T_wetbulb"] - o["T_wetbulb"]).abs().max()) <= 0.051
          and float((nn["WBGT"] - o["WBGT"]).abs().max()) <= 0.101)
    check("T+2 file: urban air temperature +2 everywhere",
          np.allclose(p2["T_air_urban"] - nn["T_air_urban"], 2.0, atol=1e-9))
    check("T+2 file: globe, MRT, WBGT, UTCI all higher",
          all(bool((p2[c] > nn[c]).all()) for c in ("T_globe", "MRT", "WBGT", "UTCI")))
    m = pd.read_excel(files["T+2"], "Metadata").iloc[0]
    check("scenario file labelled hypothetical, base file named",
          m["scenario_type"] == gv.SCENARIO_FILE_TYPE and m["scenario_base_file"] == BASE.name)
    check("scenario file opens in the loader", "Historical_Custom" in ThermopoulosData(files["T+2"]).available_sheets)
    check("scenario folder is a sub-folder (never found as newest file)",
          gv.scenario_folder(BASE).parent.name == "scenarios")

    # in memory, zoned index (what a backend such as HeatLens holds)
    meta = pd.read_excel(BASE, "Metadata").iloc[0].to_dict()
    z = o.copy()
    z.index = pd.DatetimeIndex(pd.to_datetime(z.index)).tz_localize(meta["timezone"], ambiguous="infer")
    zm = gv.disturb_engine_sheet(z, meta, gv.STANDARD_SET[3])
    check("in memory: zoned index kept, same result as the file",
          zm.index.tz is not None and np.allclose(zm["T_air_urban"].values, p2["T_air_urban"].values))

    print("PYROX and HESTIA under scenarios (small runs)")
    scen = [gv.NEUTRAL, gv.STANDARD_SET[3]]
    tf = rg.run_pyrox_scenarios(BASE, scen, "Historical_Custom", out_dir=tmp, progress=lambda m: None)
    hl = tf[tf.outcome == "heat load, highest day"].set_index("scenario")["value"]
    check("PYROX: heat load higher under T+2", hl["T+2"] > hl["neutral"])
    check("PYROX: neutral differences zero",
          np.nanmax(np.abs(tf.loc[tf.scenario == "neutral", "difference"].fillna(0))) == 0)
    settings = dict(sheet="Historical_Custom", start_time="2024-09-22 11:00", duration_hours=1.6,
                    met_value=10.0, clo_value=0.2, n_simulations=4, use_parallel=False,
                    random_seed=42, event_dist_km=16.1)
    th = rg.run_hestia_scenarios(BASE, scen, settings, out_dir=tmp, progress=lambda m: None)
    w = th[(th.group == "Weather") & (th.outcome == "WBGT max")].set_index("scenario")["value"]
    check("HESTIA: event-window WBGT higher under T+2", w["T+2"] > w["neutral"])
    th2 = rg.run_hestia_scenarios(BASE, [gv.NEUTRAL], settings, out_dir=tmp, progress=lambda m: None)
    a1 = th[th.scenario == "neutral"].set_index(["group", "outcome"])["value"]
    a2 = th2.set_index(["group", "outcome"])["value"]
    check("HESTIA: same seed gives the same participants (neutral repeats exactly)",
          np.allclose(a1.loc[a2.index].values, a2.values, equal_nan=True))
    try:
        rg.run_hestia_scenarios(BASE, scen, {**settings, "random_seed": None}, out_dir=tmp)
        check("HESTIA: random seed refused", False)
    except ValueError:
        check("HESTIA: random seed refused", True)

print()
if fails:
    print(f"FOUT: {len(fails)} check(s): {fails}")
    sys.exit(1)
print("Alle checks ok.")
