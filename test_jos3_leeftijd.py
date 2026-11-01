"""
test_jos3_leeftijd.py -- tests for the gradual JOS-3 age decrement (variant C).

Run:  python test_jos3_leeftijd.py      (~1-2 min)
"""
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import hestia_model as H
import jos3_leeftijd as J
from pythermalcomfort.models import JOS3

FAILS = []


def check(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILS.append(name)


def marathon_trect(age, height=1.78, weight=72):
    m = JOS3(height=height, weight=weight, age=age, sex="male")
    m.tdb = 12; m.tr = 20; m.rh = 75; m.v = 4.0; m.clo = 0.2; m.par = 11.0
    m.simulate(times=180, dtime=60)
    return float(m.t_core.mean() + 0.5)


print("\n1. Module state and weights")
check("active after importing hestia_model", J.is_active() and H.JOS3_AGE_GRADUAL)
check("weight 0 at <= 40, 1 at >= 75", J.weight(30) == 0 and J.weight(40) == 0
      and J.weight(75) == 1 and J.weight(90) == 1)
check("weight 0.57 at 60", abs(J.weight(60) - 20 / 35) < 1e-9, f"{J.weight(60):.3f}")
check("cardiac-index factor equals JOS-3 group values at mid-points",
      [J.ci_factor(a) for a in (45, 55, 65, 75)] == [1.00, 0.85, 0.75, 0.70])

print("\n2. No step: one runner, ages 30-85 year by year (3 h, 11 MET, 12 degC)")
ages = list(range(30, 86))
t = np.array([marathon_trect(a) for a in ages])
jumps = np.abs(np.diff(t))
i = int(np.argmax(jumps))
check("largest change between consecutive years < 0.15 degC", jumps.max() < 0.15,
      f"{jumps.max():.3f} degC between {ages[i]} and {ages[i+1]}")
check("59 -> 60 change < 0.10 degC (was +0.99)", abs(t[ages.index(60)] - t[ages.index(59)]) < 0.10,
      f"{t[ages.index(59)]:.2f} -> {t[ages.index(60)]:.2f}")
check("75-year-old warmer than 40-year-old", t[ages.index(75)] > t[ages.index(40)] + 0.5,
      f"{t[ages.index(40)]:.2f} vs {t[ages.index(75)]:.2f}")

print("\n3. Unchanged where JOS-3 already agreed")
J.disable()
t35_orig, t80_orig = marathon_trect(35), marathon_trect(80)
J.enable()
check("age 35 identical to original JOS-3", abs(marathon_trect(35) - t35_orig) < 1e-9)
check("age 80 identical to original JOS-3", abs(marathon_trect(80) - t80_orig) < 1e-9,
      f"{t80_orig:.3f}")

print("\n4. HESTIA single runner (calculate_indices_jos3_adult) at 59 / 60 / 61")
import run_hestia
from thermopoulos_loader import ThermopoulosData
d = ThermopoulosData("Thermopoulos_SmokeTest.xlsx")
interp = run_hestia.build_interpolated_weather(d, "2026-08-01 10:00", 2.0)
base = H.generate_base_population(1, random_seed=7)[0]
peaks = {}
for age in (59, 60, 61):
    p = base.__class__(**{**base.__dict__, "age": age})
    res = H.worker_monte_carlo_adult((interp, d.latitude, d.longitude, 9.8, 0.2, p, 0.0, 0.0))
    peaks[age] = max(r["t_rect"] for r in res)
check("peak T_rect 59 -> 60 differs < 0.10 degC", abs(peaks[60] - peaks[59]) < 0.10,
      " / ".join(f"{a}: {v:.2f}" for a, v in peaks.items()))
check("peak T_rect rises (weakly) with age 59 -> 61", peaks[61] >= peaks[59] - 0.01)

print("\n5. Fitness and heat curve (2026-10-23)")
import jos3_leeftijd as JL5
check("norm VO2max = suite runner mean", abs(JL5.vo2max_norm(65, "male") - 37.0) < 1e-9 and abs(JL5.vo2max_norm(30, "female") - 44.0) < 1e-9)
check("ratio <= 0.80: full decrement", abs(JL5.person_factor(0.80 * 37.0, 65, "male", 0.0) - 1.0) < 1e-9)
check("ratio >= 1.00: no decrement", JL5.person_factor(1.00 * 37.0, 65, "male", 0.0) == 0.0)
check("ratio 0.90: half", abs(JL5.person_factor(0.90 * 37.0, 65, "male", 0.0) - 0.5) < 1e-9)
check("acclimatised halves the decrement", abs(JL5.person_factor(0.80 * 37.0, 65, "male", 1.0) - 0.5) < 1e-9)
check("unknown VO2max: full decrement (JOS-3 as before)", JL5.person_factor(None, 65, "male", 0.0) == 1.0)
JL5.reset_person()          # the engine runs in section 4 left a runner's factor behind
_w_full = JL5.weight(65)
JL5.set_person(0.90 * 37.0, 65, "male", 0.0)
check("weight and cardiac index scale with the person factor",
      abs(JL5.weight(65) - 0.5 * _w_full) < 1e-9 and abs(JL5.ci_factor(65) - (1 - 0.5 * (1 - 0.75))) < 1e-9)
JL5.reset_person()
check("reset_person restores factor 1", JL5.current_person_factor() == 1.0 and abs(JL5.weight(65) - _w_full) < 1e-12)

print()
if FAILS:
    print(f"FAILED: {FAILS}")
    raise SystemExit(1)
print("ALL CHECKS PASSED")
