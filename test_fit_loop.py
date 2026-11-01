"""Test van fit_loop.py, rapportpakket.py en het startmenu (2026-10-27).

  1. een synthetische FIT-export + synthetisch weer -> fit_loop.bereken():
     varianten B3 en B4, Excel en figuur;
  2. rapportpakket: bewaren, terugvinden, rapport maken (Word);
  3. het startmenu doorlopen via standaardinvoer (hoofdmenu, submenu's, R)
     zonder fout.
Schrijft alleen in een tijdelijke map.
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("MPLBACKEND", "Agg")
import test_clinic as tc   # hulpfuncties voor synthetische gegevens
import fit_loop
import rapportpakket as rp

TMP = Path(tempfile.mkdtemp(prefix="test_fitloop_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
fails = []


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


exp = tc._synthetische_export(TMP / "T01_2026-07-01.xlsx")
weer = tc._synthetisch_weer(TMP / "weer.xlsx")
persoon = dict(code="T01", geslacht="man", leeftijd=45, lengte_cm=180, gewicht_kg=75,
               kleding="licht", hitte_gewend=False, hr_max=None, hr_rust=50,
               gewicht_na_kg=None, drank_ml=None)
g = fit_loop.bereken(exp, persoon, weer, TMP / "uit", plaats="Test", n=3)
check("varianten B3 en B4", set(g["model"]) == {"B3", "B4"})
check("Excel gemaakt", Path(g["excel"]).exists())
check("figuur gemaakt", g["figuur"] is not None and Path(g["figuur"]).exists())
check("kerntemperatuur model plausibel", 37.0 < g["model"]["B3"]["kern_max"] < 41.5,
      f"{g['model']['B3']['kern_max']:.2f}")
pk = rp.bewaar("fitloop", g, g["stam"])
check("rapportpakket bewaard", pk is not None and pk.exists())
check("rapportpakket gevonden", pk in rp.vind(TMP / "uit"))
uit = rp.maak(pk, vraag_word=False)
check("rapport gemaakt", len(uit) == 1 and Path(uit[0]).exists())

# startmenu: hoofdmenu -> HESTIA -> terug -> FIT -> terug -> R -> terug -> stop
env = dict(os.environ, HOME=str(TMP), USERPROFILE=str(TMP))
invoer = f"w\n{TMP / 'uit'}\n1\n0\n4\n0\nr\n\n0\n"
r = subprocess.run([sys.executable, str(HERE / "start_thermopoulos.py")], input=invoer,
                   capture_output=True, text=True, cwd=str(TMP), env=env, timeout=300)
check("startmenu zonder fout", r.returncode == 0 and "Traceback" not in r.stdout + r.stderr,
      (r.stderr or "")[-200:])
check("R toont het pakket", "FIT-loop nagerekend met HESTIA" in r.stdout)

print()
print("ALLE CONTROLES GESLAAGD" if not fails else f"{len(fails)} CONTROLE(S) MISLUKT")
sys.exit(1 if fails else 0)
