"""
test_straling.py -- HESTIA uses measured / forecast solar radiation (2026-10-24).

Checks the three-tier order of hestia_model.radiation_series(), the DtD 2024
calibration reference (real Data Engine weather, measured radiation), the
console Excel loader and the Open-Meteo forecast entries.

Run:  python test_straling.py      (~10 s)
"""
import io
import contextlib
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from pathlib import Path
HERE = Path(__file__).resolve().parent
with contextlib.redirect_stdout(io.StringIO()):
    import hestia_model as H
    import intercept_estimation as IE

FAILS = []


def check(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILS.append(name)


LAT, LON = 52.374, 4.889
tz = "Europe/Amsterdam"
times = list(pd.date_range("2024-09-22 12:00", periods=4, freq="h", tz=tz))
temps = [21.1, 22.3, 23.2, 23.6]
w15 = [1.0] * 4
press = [1013.0] * 4
clouds = [89.0, 95.0, 97.0, 99.0]
ghi_meas = [449.0, 526.0, 553.0, 489.0]
base = [{"time": t, "temp": T, "clouds": c} for t, T, c in zip(times, temps, clouds)]

print("\n1. Order of preference in radiation_series()")
full = [dict(b, ghi=g, solar_elevation=30.0, globe_temp=30.0 + i, mrt=40.0 + i)
        for i, (b, g) in enumerate(zip(base, ghi_meas))]
r1 = H.radiation_series(full, times, temps, w15, press, clouds, LAT, LON, 1)
check("tier 1: Data Engine values used unchanged", r1[4] == "data_engine" and r1[3] == [40.0, 41.0, 42.0, 43.0])
only_ghi = [dict(b, ghi=g) for b, g in zip(base, ghi_meas)]
r2 = H.radiation_series(only_ghi, times, temps, w15, press, clouds, LAT, LON, 1)
check("tier 2: measured ghi used", r2[4] == "gemeten_ghi" and np.allclose(r2[0], ghi_meas), str(r2[0]))
none = [dict(b, ghi=None) for b in base]
r3 = H.radiation_series(none, times, temps, w15, press, clouds, LAT, LON, 1)
check("tier 3: cloud estimate only without radiation", r3[4] == "bewolking")
check("cloud estimate is far below the measured sun here (thin high cloud)",
      np.mean(r3[0]) < 0.5 * np.mean(ghi_meas), f"{np.mean(r3[0]):.0f} vs {np.mean(ghi_meas):.0f} W/m2")
check("MRT from measured ghi > MRT from cloud estimate", np.mean(r2[3]) > np.mean(r3[3]) + 3,
      f"{np.mean(r2[3]):.1f} vs {np.mean(r3[3]):.1f} degC")
night = [dict(b, ghi=300.0) for b in base]
tn = list(pd.date_range("2024-09-22 23:00", periods=4, freq="h", tz=tz))
rn = H.radiation_series(night, tn, temps, w15, press, clouds, LAT, LON, 1)
check("tier 2: no sun below the horizon", max(rn[0]) == 0.0)

print("\n2. DtD 2024 calibration reference = real Data Engine weather")
cfg = dict(IE.REF_CONDITIONS_DTD)
cfg["duration_h"] = max(cfg["duration_h"], H.race_window_hours(16.1))
with contextlib.redirect_stdout(io.StringIO()):
    ref = IE.build_reference_interp(cfg)
f = pd.read_excel(HERE / cfg["weather_excel"], "Historical_Custom", index_col=0)
f.index = pd.to_datetime(f.index)
e12 = next(e for e in ref if e["time"].hour == 12 and e["time"].minute == 0)
check("reference carries measured radiation", e12["ghi"] == float(f.loc["2024-09-22 12:00", "solar_radiation"]), str(e12["ghi"]))
check("reference carries Data Engine MRT", abs(e12["mrt"] - float(f.loc["2024-09-22 12:00", "MRT"])) < 1e-9)
check("reference uses urban air temperature", e12["temp"] == float(f.loc["2024-09-22 12:00", "T_air_urban"]))
check("reference starts 11:30 local", ref[0]["time"] == pd.Timestamp("2024-09-22 11:30", tz=tz))

print("\n3. Console Excel loader and forecast carry radiation")
import inspect
with contextlib.redirect_stdout(io.StringIO()):
    wd, _ = H.load_weather_from_thermopoulos_excel(str(HERE / cfg["weather_excel"]), "Historical_Custom")
check("Excel loader carries solar_radiation", wd is not None and wd[12]["solar"]["ghi"] == 449.0)
check("Excel loader carries MRT", wd is not None and wd[12]["radiant"]["mrt"] is not None)
interp = H.interpolate_weather(wd, times[0], times[-1], interval_minutes=60)
check("interpolate_weather keeps the measured radiation", interp[0]["ghi"] == 449.0)
check("forecast asks Open-Meteo for radiation", "shortwave_radiation_instant" in inspect.getsource(H.get_weather_forecast))
bare = [{"dt": int(t.timestamp()), "main": {"temp": 20, "humidity": 60, "pressure": 1013},
         "wind": {"speed": 3}, "clouds": {"all": 50}} for t in times]
ib = H.interpolate_weather(bare, times[0], times[-1], interval_minutes=60)
check("entries without radiation still work (fall back)", ib[0]["ghi"] is None)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)}"); raise SystemExit(1)
print("All radiation checks passed.")
