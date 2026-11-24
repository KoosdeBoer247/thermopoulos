"""Engelse versie (2026-11-24): taalkeuze, en dat de berekeningen in beide
talen gelijk zijn. Elke Engelse controle draait in een eigen proces met
THERMOPOULOS_TAAL=en, zoals het startscherm de vensters start."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _draai(code: str, taal: str) -> str:
    env = dict(os.environ, THERMOPOULOS_TAAL=taal, MPLBACKEND="Agg", HESTIA_NONINTERACTIVE="1")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=900)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-3000:]
    return r.stdout.strip().splitlines()[-1]


def test_taal_functies():
    import taal
    oud = taal.TAAL
    try:
        taal.zet_taal("nl")
        assert taal.vt("ja", "yes") == "ja" and taal.getal(38.5, 1) == "38,5"
        assert taal.duizend(12345) == "12.345"
        taal.zet_taal("en")
        assert taal.vt("ja", "yes") == "yes" and taal.getal(1.5, 1) == "1.5"
        assert taal.duizend(12345) == "12,345"
        assert taal.datum("2024-09-22") == "22 Sep 2024"
    finally:
        taal.zet_taal(oud)


def test_standaard_nederlands_en_argument():
    uit = _draai("import taal; print(taal.TAAL)", "nl")
    assert uit == "nl"
    env = dict(os.environ)
    env.pop("THERMOPOULOS_TAAL", None)
    r = subprocess.run([sys.executable, "-c", "import taal; print(taal.TAAL)", "--lang", "en"], cwd=ROOT,
                       env=env, capture_output=True, text=True)
    assert r.stdout.strip() == "en"


def test_teksten_engels():
    code = ("import hestia_werk as hw, ui_gemeen as ug, thermopoulos_ui as t; "
            "print(hw.KLEDING[1][0], '|', ug.SOORT['verplicht'][0], '|', t.keuzes()[2]['label'])")
    assert _draai(code, "en") == "Work trousers, T-shirt | REQUIRED | HESTIA  ·  WORK"
    assert _draai(code, "nl") == "Werkbroek, T-shirt | VERPLICHT | HESTIA  ·  WERK"


_WERKDAG = r'''
import json, pandas as pd, hestia_bridge as hb, hestia_loper_ui as hlu, hestia_werk as hw
hb._patch_air_quality(1)
w = hlu.WeerBron().excel("DtD2024_Amsterdam_hindcast.xlsx", pd.Timestamp("2024-09-22 11:00"),
                         pd.Timestamp("2024-09-22 13:00"), "stad")
inv = hw.WerkInvoer("A", "2024-09-22", hw.WerkSchema(begin="11:00", einde="12:00", pauzes=[]), 4.0, "t", 0.9, 1, 1)
r = hw.bereken(inv, w.df, w.lat, w.lon, w.tz, n=2, seed=3, tf=0.25, af=0.3, aqi=1)
print(json.dumps([round(float(x), 10) for x in r["samen"]["gem"]] + [r["samen"]["fi_380"]["k"]]))
'''


def test_werkdag_rekent_in_beide_talen_gelijk():
    assert json.loads(_draai(_WERKDAG, "nl")) == json.loads(_draai(_WERKDAG, "en"))


_PYROX = r'''
import os, tempfile, warnings; warnings.filterwarnings("ignore")
from suite_smoke_test import build_synthetic_excel
from thermopoulos_loader import ThermopoulosData
from run_pyrox import assess_population
from generate_pyrox_report import generate_pyrox_report
d = tempfile.mkdtemp()
data = ThermopoulosData(build_synthetic_excel(os.path.join(d, "t.xlsx")))
sheet = "Forecast_7d" if "Forecast_7d" in data.available_sheets else data.available_sheets[0]
rep = assess_population(data, sheet=sheet, group_names=["adults_18_45", "elderly_65_85"])
tekst = generate_pyrox_report(event_name="T", pyrox_report=rep, output_path=os.path.join(d, "r.md"), plot_dir=d)
print(tekst.splitlines()[0], "|", round(float(rep["groups"]["elderly_65_85"]["peak_strain"]), 12))
'''


def test_pyrox_rapport_engels_en_zelfde_uitkomst():
    nl, en = _draai(_PYROX, "nl"), _draai(_PYROX, "en")
    assert nl.startswith("# PYROX-rapport") and en.startswith("# PYROX report")
    assert nl.split("|")[1] == en.split("|")[1]
