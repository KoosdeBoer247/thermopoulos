"""Test of the liveability-hours trend and the rest floor (2026-10-26).

Checks, on synthetic yearly data:
  1. rest_floor_met() equals HEAT-Lim's resting rate (1.8 W/kg / 1.225 = 1.469 MET);
  2. liveability_hours_trend(): a series that is zero in most years with a few
     growing spikes gives a positive slope and a non-zero projection (Theil-Sen
     would give 0 here); a series that is always zero gives exactly 0;
     projections and band edges are never negative;
  3. plot_liveability_timeseries() and plot_liveability_hours() write files;
  4. the Klimatos report section 9 shows the hours table and the projection;
  5. the temperature-shift projection: unwarmed mean equals the observed mean,
     low <= central <= high, constant water vapour gives no more hours than
     constant relative humidity.
Writes only to a temporary folder.
"""
import atexit
import os
import shutil
import sys
import tempfile

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("MPLBACKEND", "Agg")

import Klimatos_ClimateShift as K  # noqa: E402

TMP = tempfile.mkdtemp(prefix="test_leefb_")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

fails = []


def check(name, ok):
    print(("  ok    " if ok else "  FOUT  ") + name)
    if not ok:
        fails.append(name)


# 1. floor
fl = K.rest_floor_met(K.LIVEABILITY_PROFILES["old"])
check("rest floor = 1.8/1.225 MET", abs(fl - 1.8 / 1.225) < 1e-9)

# synthetic annual data 1951-2025
yrs = np.arange(1951, 2026)
rng = np.random.default_rng(1)
spikes = np.zeros(len(yrs))
for i, y in enumerate(yrs):
    if y >= 1990 and rng.random() < 0.35:
        spikes[i] = (y - 1985) * 0.5
annual = pd.DataFrame({
    "minMmax_young": 3.3 - 0.015 * (yrs - 1951) + rng.normal(0, 0.4, len(yrs)),
    "minMmax_old": np.maximum(1.95 - 0.008 * (yrs - 1951) + rng.normal(0, 0.3, len(yrs)), fl),
    "hrsBelow_young": np.maximum(0, 0.3 * (yrs - 1951) + rng.normal(0, 4, len(yrs))).round(),
    "hrsNonLiv_young": np.zeros(len(yrs)),
    "hrsNonSurv_young": np.zeros(len(yrs)),
    "hrsBelow_old": np.maximum(0, 1.0 * (yrs - 1951) + rng.normal(0, 20, len(yrs))).round(),
    "hrsNonLiv_old": spikes.round(),
    "hrsNonSurv_old": np.zeros(len(yrs)),
}, index=pd.Index(yrs, name="year"))

# 2. trend
t = K.liveability_hours_trend(annual, ref_window=(1951, 1980))
r_nl = t[(t.profile == "old") & (t.metric == "hrsNonLiv")].iloc[0]
r_y0 = t[(t.profile == "young") & (t.metric == "hrsNonLiv")].iloc[0]
check("zero-inflated series: slope > 0", r_nl.slope_hours_per_yr > 0)
check("zero-inflated series: projection 2040 > 0", r_nl.proj_2040 > 0)
check("always-zero series: projection exactly 0",
      r_y0.proj_2030 == 0 and r_y0.proj_2040 == 0 and r_y0.slope_hours_per_yr == 0)
proj_cols = [c for c in t.columns if c.startswith("proj_")]
check("no negative projections or band edges", bool((t[proj_cols] >= 0).all().all()))
check("projection lies within its band",
      bool(((t.proj_2040 >= t.proj_2040_lo - 1e-9) & (t.proj_2040 <= t.proj_2040_hi + 1e-9)).all()))

# 3. plots
p1 = os.path.join(TMP, "ts.png")
p2 = os.path.join(TMP, "hours.png")
K.plot_liveability_timeseries(annual, (1951, 1980), "Test", p1)
K.plot_liveability_hours(annual, (1951, 1980), "Test", p2, t)
check("worst-hour plot written", os.path.exists(p1))
check("hours plot written", os.path.exists(p2))

# 4. report section
try:
    from generate_klimatos_report import generate_klimatos_report
    windows = [(1951, 1980), (1996, 2025)]
    ldf = K.analyze_liveability_windows(annual, windows, (1951, 1980))
    meta = {"city": "Test", "latitude": 52.0, "longitude": 5.0,
            "reference_period": "1951-1980", "analysis_period": "1951-2025"}
    out = os.path.join(TMP, "rapport.md")
    txt = generate_klimatos_report("Test", meta, annual, (1951, 1980), (1996, 2025), out,
                                   liveability_df=ldf, liveability_hours_df=t,
                                   plot_paths=[p2])
    check("report: hours table present", "Oudere: zelfs rust niet volhoudbaar" in txt)
    check("report: projection table present", "Doorgetrokken trend 1995-2025" in txt)
    check("report: floor note present", "rustniveau" in txt)
except Exception as exc:  # pragma: no cover
    check(f"report generation ({type(exc).__name__}: {exc})", False)

# 5. temperature-shift projection on synthetic summers (UHI on)
city = {"name": "Testa", "population": 800000}
lat, lon, tz = 52.37, 4.9, "Europe/Amsterdam"
rng2 = np.random.default_rng(3)


def raw_year(y, warm):
    idx = pd.date_range(f"{y}-06-01", f"{y}-08-31 23:00", freq="h", tz=tz)
    h = idx.hour.values
    d = np.arange(len(idx)) / 24
    heat = np.where(rng2.random(len(idx) // 24 + 1) < 0.12, rng2.uniform(4, 10), 0)[d.astype(int)]
    T = 19 + 4 * np.sin(np.pi * d / 92) + warm + heat + 6 * np.sin((h - 9) / 24 * 2 * np.pi)
    return pd.DataFrame({"T_air_rural": T, "RH": np.clip(75 - 1.5 * (T - 18), 25, 95),
                         "pressure": 1013.0, "wind_10m": rng2.uniform(1, 5, len(idx)),
                         "solar_radiation": np.clip(800 * np.sin((h - 6) / 14 * np.pi), 0, None),
                         "cloud_cover": 30.0}, index=idx)


recs, raws = [], {}
for y in range(2000, 2012):
    r = raw_year(y, 0.08 * (y - 2000))
    p = K.process_weather_data(r.copy(), city, lat, lon, tz)
    recs.append({"year": y, **K.liveability_year_metrics(p),
                 "T_air_warm_season": K.warm_season_tmax(p["T_air_rural"])})
    raws[y] = r[r.T_air_rural >= K.LIVEABILITY_TA_MIN - K.LIVEABILITY_PROJ_UHI_MAX
                - K.LIVEABILITY_PROJ_STORE_MARGIN].copy()
ann2 = pd.DataFrame(recs).set_index("year")
P = K.run_liveability_projection(ann2, raws, city, lat, lon, tz, trend_period=(2000, 2011),
                                 humidity="constant_rh")
refm = P[P.target_year == "reference"].set_index(["profile", "metric"]).mean_hours
obs = {(p, m): ann2[f"{m}_{p}"].mean() for p in K.LIVEABILITY_PROFILES
       for m in K.LIVEABILITY_HOURS_METRICS}
check("projection reference = observed mean hours (stored rows complete)",
      all(abs(refm[k] - v) < 1e-9 for k, v in obs.items()))
T1 = K.liveability_projection_table(P)
if P.attrs["slope"] > 0:
    check("positive warming: 2040 >= reference",
          bool((T1["2040"] >= T1["reference_mean"] - 1e-9).all()))
check("low <= central <= high", bool(((T1["2040_lo"] <= T1["2040"] + 1e-9) &
                                      (T1["2040"] <= T1["2040_hi"] + 1e-9)).all()))
P2 = K.run_liveability_projection(ann2, raws, city, lat, lon, tz, trend_period=(2000, 2011),
                                  humidity="constant_vapour")
T2 = K.liveability_projection_table(P2)
check("constant water vapour gives no more hours than constant RH",
      bool((T2["2040"] <= T1["2040"] + 1e-9).all()))
p3 = os.path.join(TMP, "hours_proj.png")
K.plot_liveability_hours(ann2, (2000, 2004), "Testa", p3,
                         K.liveability_hours_trend(ann2, trend_period=(2000, 2011),
                                                   ref_window=(2000, 2004)), T1)
check("hours plot with projection written", os.path.exists(p3))
try:
    txt2 = generate_klimatos_report("Test", {"city": "Testa"}, ann2, (2000, 2004), (2005, 2011),
                                    os.path.join(TMP, "r2.md"),
                                    liveability_df=K.analyze_liveability_windows(
                                        ann2, [(2000, 2004), (2005, 2011)], (2000, 2004)),
                                    liveability_proj_df=T1, plot_paths=[p3])
    check("report: temperature-shift projection described", "opgewarmd naar het doeljaar" in txt2)
except Exception as exc:  # pragma: no cover
    check(f"report with projection ({type(exc).__name__}: {exc})", False)

print()
print("ALLE CONTROLES GESLAAGD" if not fails else f"{len(fails)} CONTROLE(S) MISLUKT")
sys.exit(1 if fails else 0)
