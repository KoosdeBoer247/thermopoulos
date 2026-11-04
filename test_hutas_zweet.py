"""Test of maximum skin wettedness and dripping sweat as in HUTAS (2026-11-04).

1. w_max 0.72 / 0.84 / 1.0 for acclimatisation 0 / 0.5 / 1, interpolated.
2. Whole-body cap: sum(w E_max)/sum(E_max) is limited to w_max; below the
   cap nothing changes.
3. Sweating efficiency and dripping sweat: eta = 1 - w^2/2 (w < 1),
   (2 - w)^2/2 above; the drip is >= 0 and does not cool.
4. JOS-3: no core change in cool or dry heat; humid heat makes the
   unacclimatised hotter, not the fully acclimatised; switched off gives
   JOS-3 as before.
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jos3_leeftijd as jl
from hestia_model import maak_jos3

fails = []


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


print("1. Maximum wettedness")
for acc, w in ((0.0, 0.72), (0.5, 0.84), (1.0, 1.0), (0.25, 0.78)):
    jl.set_person(45, 35, "male", acc)
    check(f"w_max at acclimatisation {acc}", abs(jl.wettedness_max() - w) < 1e-9, f"{jl.wettedness_max():.3f}")
jl.reset_person()

print("\n2. Whole-body cap")
jl.set_person(45, 35, "male", 0.0)
e = np.array([10.0, 20.0, 30.0])
low = np.array([0.3, 0.4, 0.5])
check("below the cap unchanged", np.allclose(jl._wmax_apply(low, e), low))
high = np.array([0.9, 1.0, 1.0])
capped = jl._wmax_apply(high, e)
check("above the cap: whole-body wettedness = 0.72", abs(float((capped * e).sum() / e.sum()) - 0.72) < 1e-9)
check("segments scaled, never above 1", (capped <= high + 1e-12).all() and (capped >= 0.06 - 1e-12).all())
jl.reset_person()

print("\n3. Sweating efficiency and drip")
jl.set_person(45, 35, "male", 0.0)
jl.drip_reset()
jl._drip(raw_sweat=np.array([50.0]), w_seg_uncapped=np.array([0.5]), e_max=np.array([100.0]),
         e_sweat_eff=np.array([50.0]), bsa=np.array([1.9]))
check("w 0.5: drip = 50/0.875 - 50", abs(jl._DRIP["w"] - (50 / 0.875 - 50)) < 1e-9, f"{jl._DRIP['w']:.3f}")
jl.drip_reset()
jl._drip(np.array([120.0]), np.array([1.2]), np.array([100.0]), np.array([72.0]), np.array([1.9]))
check("w 1.2: required sweat 120/0.32", abs(jl._DRIP["w"] - (120 / 0.32 - 72)) < 1e-9, f"{jl._DRIP['w']:.1f}")
g = jl.drip_take_rate(2)
check("drip_take_rate in g/s and resets", abs(g - (120 / 0.32 - 72) / 2418 / 2) < 1e-12 and jl._DRIP["w"] == 0.0)
jl.reset_person()


def run(acc, tdb, rh, v, on=True, minutes=60):
    jl.HUTAS_SWEAT_ENABLED = on
    jl.set_person(45, 35, "male", acc)
    m = maak_jos3(height=1.80, weight=75, age=35, fat=15, sex="male")
    m.tdb, m.tr, m.rh, m.v, m.par, m.clo = tdb, tdb + 20, rh, v, 9.0, 0.2
    drip = 0.0
    for _ in range(minutes):
        m.simulate(times=1, dtime=60)
        drip += jl.drip_take_rate(1) * 60
    jl.HUTAS_SWEAT_ENABLED = True
    jl.reset_person()
    return float(m.t_core[4]), drip


print("\n4. JOS-3")
k0, _ = run(0.0, 20, 50, 3.0, on=False)
k1, d1 = run(0.0, 20, 50, 3.0)
check("cool: core unchanged", abs(k1 - k0) < 0.01, f"{k0:.2f} / {k1:.2f}")
check("cool: some dripping sweat", d1 > 0, f"{d1:.0f} g")
k0, _ = run(0.0, 30, 30, 3.0, on=False)
k1, _ = run(0.0, 30, 30, 3.0)
check("dry heat: core unchanged", abs(k1 - k0) < 0.02, f"{k0:.2f} / {k1:.2f}")
k0, d0 = run(0.0, 30, 80, 1.0, on=False)
k1, d1 = run(0.0, 30, 80, 1.0)
check("humid heat, unacclimatised: hotter", k1 > k0 + 0.3, f"{k0:.2f} -> {k1:.2f}")
check("switched off: no drip", d0 == 0.0)
k0, _ = run(1.0, 30, 80, 1.0, on=False)
k1, _ = run(1.0, 30, 80, 1.0)
check("humid heat, acclimatised: core unchanged", abs(k1 - k0) < 0.01, f"{k0:.2f} / {k1:.2f}")

print()
print("ALLE CONTROLES GESLAAGD" if not fails else f"{len(fails)} CONTROLE(S) MISLUKT")
sys.exit(1 if fails else 0)
