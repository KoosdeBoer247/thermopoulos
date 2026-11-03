"""Test of the walkers' population (2026-11-02, author's decision).

1. Runners' population unchanged (same draws with the default argument).
2. Walkers: sex share, age structure, BMI and VO2max follow the sources
   (Vierdaagse statistics 2019, Terink et al. 2018, LowLands Fitness Registry,
   de Wild et al. 1995); VO2max mean function continuous at 65 y.
3. sample_pace is refused for walkers.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import hestia_model as H

fails = []


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


def df(pop):
    return pd.DataFrame([vars(p) for p in pop])


print("1. Runners unchanged")
a = df(H.generate_base_population(300, random_seed=5, met_value=9.8))
b = df(H.generate_base_population(300, random_seed=5, met_value=9.8, population="lopers"))
check("default equals population='lopers'", a.equals(b))
check("runners stay 18-65 y", a.age.between(18, 65).all())

print("\n2. Walkers")
w = df(H.generate_base_population(4000, random_seed=42, met_value=3.8, population="wandelaars"))
w["bmi"] = w.weight / w.height ** 2
check("men about 58 %", abs((w.gender == "male").mean() - 0.58) < 0.03, f"{(w.gender == 'male').mean():.3f}")
check("about a third over 60", 0.30 < (w.age > 60).mean() < 0.38, f"{(w.age > 60).mean():.3f}")
check("ages 18-90", w.age.between(18, 90).all() and w.age.max() > 80)
m, f = w[w.gender == "male"], w[w.gender == "female"]
check("BMI men about 27.3", abs(m.bmi.mean() - 27.3) < 0.4, f"{m.bmi.mean():.1f}")
check("BMI women about 23.5", abs(f.bmi.mean() - 23.5) < 0.4, f"{f.bmi.mean():.1f}")
m70 = m[m.age.between(69, 87)]
check("men 69-87 VO2max near de Wild (26.8)", abs(m70.vo2max.mean() - 26.8) < 1.5, f"{m70.vo2max.mean():.1f}")
m40 = m[m.age.between(40, 49)]
check("men 40-49 VO2max near LowLands (42.6)", abs(m40.vo2max.mean() - 42.6) < 1.5, f"{m40.vo2max.mean():.1f}")
for g in ("male", "female"):
    jump = abs(H.walker_vo2max_mean(65.0, g) - H.walker_vo2max_mean(65.001, g))
    check(f"VO2max mean continuous at 65 y ({g})", jump < 0.01)
check("VO2max within 15-70", w.vo2max.between(15, 70).all())
for g, sub in (("men", m), ("women", f)):
    s5 = sub[sub.age.between(51, 60)].vo2max
    check(f"spread about 19 % of the mean, {g} 51-60 y", 0.15 < s5.std() / s5.mean() < 0.23,
          f"{s5.std() / s5.mean():.2f}")

print("\n3. sample_pace refused for walkers")
try:
    H.generate_base_population(5, random_seed=1, sample_pace=True, population="wandelaars")
    check("ValueError raised", False)
except ValueError:
    check("ValueError raised", True)

print()
print("ALLE CONTROLES GESLAAGD" if not fails else f"{len(fails)} CONTROLE(S) MISLUKT")
sys.exit(1 if fails else 0)
