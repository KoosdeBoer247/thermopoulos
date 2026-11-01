"""Test van groep_lopers.py (2026-10-27): lijst inlezen, twee lopers door een
synthetische loop, overzicht (Excel, figuur, Word) en rapportpakket.
Schrijft alleen in een tijdelijke map."""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("MPLBACKEND", "Agg")
import test_clinic as tc
import groep_lopers as gl
import rapportpakket as rp

TMP = Path(tempfile.mkdtemp(prefix="test_groep_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
fails = []


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


lijst = TMP / "lopers.xlsx"
pd.DataFrame([
    {"code": "G01", "geslacht": "m", "leeftijd": 40, "lengte_cm": 180, "gewicht_voor_kg": 75,
     "verwacht_tempo": "5:30", "kleding": "licht", "hitte_gewend": "n", "vo2max": 50},
    {"code": "G02", "geslacht": "v", "leeftijd": 55, "lengte_cm": 166, "gewicht_voor_kg": 60,
     "verwacht_tempo": "6:30", "kleding": "normaal", "hitte_gewend": "j"},
]).to_excel(lijst, sheet_name="Deelnemers", index=False)
lopers = gl.lees_lopers(lijst)
check("lijst ingelezen", [d.code for d in lopers] == ["G01", "G02"])
weer = tc._synthetisch_weer(TMP / "weer.xlsx")
loop = dict(evenement="Testloop", plaats="Testdorp", datum="2026-07-01", starttijd="10:00", afstand_km=5)
g = gl.bereken(lopers, loop, weer, n=5, progress=print)
t = g["tabel"]
check("twee lopers doorgerekend", len(g["resultaten"]) == 2, ", ".join(t.columns[:4]))
check("kerntemperatuur plausibel", t.kern_max.between(37.0, 41.5).all(), t.kern_max.round(2).tolist())
check("VO2max uit de lijst gebruikt", abs(t.loc[t.code == "G01", "vo2max"].iat[0] - 50) < 0.5)
pk = rp.bewaar("groep", g, TMP / "GroepLopers_test")
check("rapportpakket bewaard", pk is not None and pk.exists())
uit = gl.maak_uitvoer(rp.laad(pk)["gegevens"], TMP / "GroepLopers_test", per_loper=True)
check("Excel, groepsrapport en per loper rapport + Excel", len(uit) == 6 and all(Path(p).exists() for p in uit), str(len(uit)))
import pandas as _pd
check("groeps-Excel met weerbladen", {"Weer_loop", "Weer_dag"} <= set(_pd.ExcelFile(uit[0]).sheet_names))
from docx import Document as _D
_t = " ".join(p.text for p in _D(str(uit[1])).paragraphs)
check("groepsrapport heeft een weerhoofdstuk", "Het weer" in _t)

print()
print("ALLE CONTROLES GESLAAGD" if not fails else f"{len(fails)} CONTROLE(S) MISLUKT")
sys.exit(1 if fails else 0)
