"""Test of the cold-skin limit (jos3_leeftijd.COLD_SKIN_LIMIT_K, 2026-10-27).

Checks:
  1. default off: JOS-3 results are identical with the limit unset;
  2. with a 2 K limit, a run at 5 degC gives a lower core and a warmer skin
     than without; at 30 degC (warm skin) the result is unchanged;
  3. set_cold_skin_limit(None) restores the original behaviour exactly;
  4. the clinic reconstruction variant B4 runs and restores the setting.
"""
import io
import contextlib
import sys
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
with contextlib.redirect_stdout(io.StringIO()):
    import hestia_model as hm
import jos3_leeftijd as jl

fails = []


def check(name, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + name + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(name)


def run(T, minutes=30):
    m = hm.maak_jos3(height=1.78, weight=75, age=60, sex="male")
    m.tdb = T; m.tr = T; m.rh = 50; m.v = 3.0; m.clo = 0.2
    m.par = hm.jos3_par(m, 9.0)
    m.simulate(times=minutes, dtime=60)
    return hm.jos3_t_rect(m), float(m.dict_results()["t_skin_mean"][-1])


check("standaard uit", jl.cold_skin_limit() is None)
base5 = run(5); base30 = run(30)
jl.set_cold_skin_limit(2.0)
lim5 = run(5); lim30 = run(30)
jl.set_cold_skin_limit(None)
again5 = run(5)
check("5 °C: kern lager met grens", lim5[0] < base5[0] - 0.2, f"{base5[0]:.2f} -> {lim5[0]:.2f}")
check("5 °C: huid warmer met grens", lim5[1] > base5[1] + 0.5, f"{base5[1]:.1f} -> {lim5[1]:.1f}")
check("30 °C: geen verschil", abs(lim30[0] - base30[0]) < 1e-9, f"{base30[0]:.4f} / {lim30[0]:.4f}")
check("uitzetten herstelt exact", again5 == base5)

# reconstruction variant B4 on a synthetic cool run
import pandas as pd
import hestia_reconstructie as hr_
p = hr_.Persoon(geslacht="man", leeftijd=60, lengte_cm=178, gewicht_kg=75, clo=0.2)
if True:
    idx = pd.date_range("2026-10-17 09:00", periods=4, freq="h")
    weer = pd.DataFrame({"T_air_urban": 10.0, "RH": 70.0, "pressure": 1013.0, "wind_10m": 3.0,
                         "cloud_cover": 50.0, "solar_radiation": 0.0, "MRT": 10.0}, index=idx)
    n = 40
    minuten = pd.DataFrame({"snelheid_ms": [0.0] * 5 + [3.0] * (n - 5),
                            "met": [1.5] * 5 + [10.0] * (n - 5)})
    r = hr_.reconstrueer_varianten(p, minuten, weer, idx[1], ("B3", "B4"),
                                   {"populatie": 40.0}, n_ensemble=2, seed=1)
    d = float(r["B3"].centraal["t_rect"].iloc[-1] - r["B4"].centraal["t_rect"].iloc[-1])
    check("B4 rekent koeler dan B3 bij 10 °C", d > 0.05, f"verschil {d:.2f} °C")
    check("instelling na B4 weer uit", jl.cold_skin_limit() is None)

print()
print("ALLE CONTROLES GESLAAGD" if not fails else f"{len(fails)} CONTROLE(S) MISLUKT")
sys.exit(1 if fails else 0)
