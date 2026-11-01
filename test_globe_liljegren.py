"""Test of the globe model and the humidity pairing (2026-10-31).

1. Daytime globe temperature equals the Liljegren et al. (2008) energy
   balance. Reference values: the authors' C code wbgt.c (UChicago Argonne,
   via github.com/mdljts/wbgt), compiled, with its Tglobe() loop and
   calc_solar_parameters(), only h replaced by the ISO 7726 h_c for a
   0.15 m globe (as the suite does). Tolerance 0.01 degC.
2. Night branch unchanged.
3. Older Data Engine files are recomputed on loading; files that name the
   current model, and synthetic files, are left alone.
4. hestia_bridge pairs T_air_urban with RH_urban.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import thermal_env as te
import hestia_bridge as hb

fails = []


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


print("1. Liljegren globe against the compiled C reference")
# ta, rh, v(1.5 m), ghi, elevation -> fdir, Tg from wbgt.c (ISO h, D 0.15 m)
REF = [((33, 25, 2.0, 900, 70), 0.7454, 48.8623),
       ((24, 40, 1.0, 420, 20), 0.9000, 40.0453),
       ((29, 80, 1.5, 600, 45), 0.6127, 43.8342),
       ((22, 60, 3.0, 120, 10), 0.3901, 24.9850),
       ((30, 50, 0.5, 980, 85), 0.7733, 59.7404),
       ((15, 70, 4.0, 60, 3), 0.9000, 21.2682)]
for (ta, rh, v, g, el), fd_c, tg_c in REF:
    _, fd, _ = te.direct_fraction(g, el)
    tg = te._calculate_globe_scalar(ta, g, v, el, 1010, 30, 1, rh=rh)
    check(f"Tg {ta} degC, {g} W/m2, elev {el}", abs(tg - tg_c) < 0.01 and abs(fd - fd_c) < 1e-3,
          f"{tg:.3f} vs {tg_c:.3f}, fdir {fd:.4f}")

print("\n2. Night unchanged, NaN stays NaN")
tn = te._calculate_globe_scalar(15, 0, 2, -5, 1010, 50, 1, rh=70)
h = 6.3 * 2 ** 0.6 / 0.15 ** 0.4
ta_k = 288.15
oud = 15 + 0.95 * 5.67e-8 * ((ta_k - 7) ** 4 - ta_k ** 4) / h
check("night formula", abs(tn - max(12, min(16, oud))) < 1e-9, f"{tn:.3f}")
check("NaN rh gives NaN", np.isnan(te._calculate_globe_scalar(20, 500, 2, 40, 1010, 0, 1, rh=np.nan)))

print("\n3. Recomputing older Data Engine files")
idx = pd.date_range("2026-07-01 08:00", periods=6, freq="h")
df = pd.DataFrame({"T_air_urban": 25.0, "RH": 60.0, "RH_urban": 55.0, "pressure": 1013.0,
                   "wind_10m": 3.0, "wind_1.5m": 2.0, "solar_radiation": 700.0,
                   "solar_elevation": 50.0, "cloud_cover": 10.0, "T_globe": 30.0, "MRT": 35.0,
                   "T_wetbulb": 19.0, "WBGT": 22.0, "UTCI": 27.0}, index=idx)
oud_meta = {"model_version": "Thermopoulos v3.0"}
nieuw, ok = te.actualiseer_straling(df, oud_meta)
tg_v = te._calculate_globe_scalar(25, 700, 2, 50, 1013, 10, 1, rh=55)
check("old file recomputed", ok and abs(nieuw["T_globe"].iloc[0] - tg_v) < 1e-9, f"{nieuw['T_globe'].iloc[0]:.2f}")
check("MRT follows ISO 7726", abs(nieuw["MRT"].iloc[0] - te._calculate_mrt_scalar(tg_v, 25, 2, 700, 50)) < 1e-9)
check("WBGT = 0.7 twb + 0.2 tg + 0.1 ta", abs(nieuw["WBGT"].iloc[0] - (0.7 * 19 + 0.2 * tg_v + 2.5)) < 0.06)   # pythermalcomfort rounds to 0.1
check("original frame untouched", df["T_globe"].iloc[0] == 30.0)
_, ok2 = te.actualiseer_straling(df, dict(oud_meta, globe_model=te.GLOBE_MODEL))
check("current file left alone", not ok2)
_, ok3 = te.actualiseer_straling(df, {"city": "Testdorp"})
check("synthetic file left alone", not ok3)
_, ok4 = te.actualiseer_straling(df.drop(columns="solar_elevation"), oud_meta)
check("file without sun elevation left alone", not ok4)

print("\n4. Humidity belongs to the urban temperature")
w = df.copy()
w.index = w.index.tz_localize("Europe/Amsterdam")
ip = hb.build_interp_data(w, w.index[0], w.index[2], 10)
check("bridge uses RH_urban", abs(ip[0]["rh"] - 55.0) < 1e-9, str(ip[0]["rh"]))
w2 = w.drop(columns="RH_urban")
check("falls back to RH", abs(hb.build_interp_data(w2, w.index[0], w.index[2], 10)[0]["rh"] - 60.0) < 1e-9)

print()
print("ALLE CONTROLES GESLAAGD" if not fails else f"{len(fails)} CONTROLE(S) MISLUKT")
sys.exit(1 if fails else 0)
