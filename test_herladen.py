"""Test (2026-10-30): de suite blijft werken als modules opnieuw worden geladen,
zoals Spyder doet tussen twee runs ("Reloaded modules"). Eerder gaf de tweede
run 'the JOS-3 age patch could not be built -- could not get source code'.
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pythermalcomfort.models import JOS3
import jos3_leeftijd as j

fails = []


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


def run():
    m = JOS3(height=1.75, weight=70, age=65)
    m.tdb, m.tr, m.rh, m.v, m.par = 30, 30, 50, 0.5, 4
    m.simulate(30)
    return float(m.t_core[4])


a = run()
for _ in range(3):
    j = importlib.reload(j)
check("patch actief na herladen", j.is_active())
b = run()
check("zelfde uitkomst na herladen (geen dubbele correctie)", abs(a - b) < 1e-9, f"{a:.4f} / {b:.4f}")
import hestia_model
importlib.reload(hestia_model)
check("hestia_model opnieuw te laden", j.is_active() and abs(run() - a) < 1e-9)
print()
print("ALLE CONTROLES GESLAAGD" if not fails else f"{len(fails)} CONTROLE(S) MISLUKT")
sys.exit(1 if fails else 0)
