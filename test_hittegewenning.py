"""Test of the heat-acclimation effects (2026-11-01, author's decision).

1. JOS-3 sweat signal x (1 + 0.20 x acclimatisation): factor, reset, and the
   effect in dry heat (more cooling) and in humid heat (evaporation already at
   its maximum, so hardly any effect).
2. CVR module: plasma volume +5 % -> stroke volume x 1.05, equation-based
   resting heart rate / 1.05 with the same resting cardiac output; a measured
   resting heart rate is left alone; acclimatisation 0 changes nothing.
3. The sweat_factor of the fluid bookkeeping no longer depends on
   acclimatisation (the effect sits in JOS-3 now).
"""
import inspect
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jos3_leeftijd as jl
from hestia_model import maak_jos3
from HESTIA_CVR_Module_v2 import RunnerProfile, CVRModel

fails = []


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


def jos3_run(acc, tdb, rh, v, minutes=90):
    jl.set_person(45, 35, "male", acc)
    m = maak_jos3(height=1.80, weight=75, age=35, fat=15, sex="male")
    m.tdb, m.tr, m.rh, m.v, m.par, m.clo = tdb, tdb + 20, rh, v, 9.0, 0.2
    m.simulate(times=minutes, dtime=60)
    wl = np.asarray(m.dict_results()["weight_loss_by_evap_and_res"], dtype=float).ravel()
    return float(m.t_core[4]), float(m.t_skin_mean), wl.sum() * 60 / 1000


print("1. JOS-3 sweat gain")
jl.set_person(45, 35, "male", 1.0)
check("gain 1.20 when acclimatised", abs(jl.sweat_gain() - 1.20) < 1e-12)
jl.set_person(45, 35, "male", 0.35)
check("gain 1.07 at factor 0.35", abs(jl.sweat_gain() - 1.07) < 1e-12)
jl.reset_person()
check("reset gives gain 1", jl.sweat_gain() == 1.0)
k0, h0, w0 = jos3_run(0.0, 30, 30, 3.0)
k1, h1, w1 = jos3_run(1.0, 30, 30, 3.0)
check("dry heat: acclimatised core lower", k1 < k0 - 0.05, f"{k0:.2f} -> {k1:.2f}")
check("dry heat: acclimatised skin lower", h1 < h0 - 0.1, f"{h0:.2f} -> {h1:.2f}")
k0h, _, _ = jos3_run(0.0, 30, 80, 1.0)
k1h, _, _ = jos3_run(1.0, 30, 80, 1.0)
check("humid heat: evaporation capped, hardly any effect", abs(k1h - k0h) < 0.05, f"{k0h:.2f} -> {k1h:.2f}")
jl.reset_person()

print("\n2. CVR module: plasma volume")
base = dict(mass=75, height=180, age=35, sex="male", vo2max=45)
c0 = CVRModel(RunnerProfile(**base))
c00 = CVRModel(RunnerProfile(**base, acclimatisation=0.0))
c1 = CVRModel(RunnerProfile(**base, acclimatisation=1.0))
check("acclimatisation 0 identical to default",
      (c0.SV_max, c0.SV_rest, c0.HR_rest, c0.CO_max) == (c00.SV_max, c00.SV_rest, c00.HR_rest, c00.CO_max))
check("SV_max x 1.05", abs(c1.SV_max / c0.SV_max - 1.05) < 1e-12)
check("SV_rest x 1.05", abs(c1.SV_rest / c0.SV_rest - 1.05) < 1e-12)
check("equation HR_rest / 1.05", abs(c0.HR_rest / c1.HR_rest - 1.05) < 1e-12, f"{c0.HR_rest:.1f} -> {c1.HR_rest:.1f}")
check("resting cardiac output unchanged", abs(c1.CO_rest - c0.CO_rest) < 1e-9)
check("CO_max x 1.05", abs(c1.CO_max / c0.CO_max - 1.05) < 1e-12)
m0 = CVRModel(RunnerProfile(**base, hr_rest=50))
m1 = CVRModel(RunnerProfile(**base, hr_rest=50, acclimatisation=1.0))
check("measured HR_rest left alone", m1.HR_rest == m0.HR_rest == 50 and m1.SV_rest == m0.SV_rest)

print("\n3. sweat_factor independent of acclimatisation")
import hestia_model, individual_engine, hestia_reconstructie
src = inspect.getsource(hestia_model) + inspect.getsource(individual_engine) + inspect.getsource(hestia_reconstructie)
check("no acclimation term in sweat_loc",
      "acclimatization_factor * 0.3" not in src and "0.3 if inputs.heat_acclimatized" not in src
      and "0.3 if hitte_gewend" not in src and "0.3 if p.hitte_gewend" not in src)

print()
print("ALLE CONTROLES GESLAAGD" if not fails else f"{len(fails)} CONTROLE(S) MISLUKT")
sys.exit(1 if fails else 0)
