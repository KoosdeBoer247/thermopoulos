# -*- coding: utf-8 -*-
"""
test_loper.py -- tests voor de persoonlijke loper-module
(hestia_loper.py, hestia_loper_plots.py, hestia_loper_rapport.py, run_loper.py).

Zonder netwerk. De end-to-end test gebruikt een Thermopoulos Data Engine-
bestand; geef het pad mee via de omgevingsvariabele LOPER_TEST_XLSX, anders
wordt een synthetisch weerbestand gemaakt.

    PYTHONPATH=. python3 test_loper.py
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

import hestia_loper as hl
from HESTIA_CVR_Module_v2 import CVRModel, RunnerProfile
from hestia_model import AdultParticipantProfile, COLLAPSE_ENDPOINTS, ACTIVE_ENDPOINT

FOUT = []


def check(naam, ok, info=""):
    print(f"[{'OK ' if ok else 'FOUT'}] {naam}" + (f"  ({info})" if info else ""))
    if not ok:
        FOUT.append(naam)


def _synthetisch_weer(pad: Path, datum="2026-07-01", t=28.0, gaten_op=None):
    idx = pd.date_range(f"{datum} 00:00", periods=48, freq="h")
    uur = idx.hour.to_numpy()
    zon = np.clip(np.sin((uur - 6) / 12 * np.pi), 0, None)
    df = pd.DataFrame({
        "T_air_rural": t - 4 + 6 * zon, "RH": 55 - 15 * zon, "pressure": 1013.0,
        "wind_10m": 3.0, "solar_radiation": 750 * zon, "cloud_cover": 20.0,
        "solar_elevation": 55 * zon, "T_air_urban": t - 3 + 6 * zon, "RH_urban": 50.0,
        "wind_1.5m": 1.5, "T_globe": t + 8 * zon, "MRT": t + 18 * zon,
        "T_wetbulb": t - 7, "WBGT": t - 4 + 3 * zon, "UTCI": t + 4 * zon, "UTCI_valid": True,
    }, index=idx)
    df.index.name = "time"
    if gaten_op is not None:
        df.loc[gaten_op:, ["T_air_urban", "MRT", "RH"]] = np.nan
    meta = pd.DataFrame([{"city": "Testdorp", "country": "NL", "latitude": 52.0,
                          "longitude": 5.0, "timezone": "Europe/Amsterdam"}])
    with pd.ExcelWriter(pad) as xw:
        df.to_excel(xw, sheet_name="Forecast_7d")
        meta.to_excel(xw, sheet_name="Metadata", index=False)
    return pad


def test_tempo():
    check("tempo '5:30' -> 5.5", abs(hl.tempo_naar_min("5:30") - 5.5) < 1e-9)
    check("tempo '5,5' -> 5.5", abs(hl.tempo_naar_min("5,5") - 5.5) < 1e-9)
    check("min_naar_tempo 5.5 -> '5:30'", hl.min_naar_tempo(5.5) == "5:30")
    check("min_naar_tempo 5.999 -> '6:00'", hl.min_naar_tempo(5.999) == "6:00")


def test_vdot():
    # Daniels' tabel: VDOT 40 <-> 10 km in ca. 50:03; VDOT 50 <-> ca. 41:21
    v40 = hl.vo2max_uit_wedstrijd(10, "50:03")
    v50 = hl.vo2max_uit_wedstrijd(10, "41:21")
    check("VDOT 10 km 50:03 ~ 40", abs(v40 - 40) < 0.6, f"{v40:.2f}")
    check("VDOT 10 km 41:21 ~ 50", abs(v50 - 50) < 0.6, f"{v50:.2f}")
    v = 0.000104 * 200 ** 2 + 0.182258 * 200 - 4.60
    check("inverse Daniels-Gilbert", abs(hl._dg_snelheid_uit_vo2(v) - 200) < 1e-6)


def test_begrenzing():
    vo2max = 31.0
    check("anker = gepland tempo als haalbaar", hl.vo2_anker(25.0, vo2max) == 25.0)
    check("anker = 95% VO2max bij te snel tempo", abs(hl.vo2_anker(36.0, vo2max) - 0.95 * vo2max) < 1e-12)
    t = hl.haalbaar_tempo(vo2max, 21.0975)
    # Daniels: VDOT 31 -> halve marathon ca. 2:17 (6:30 min/km)
    check("haalbaar tempo VDOT 31 halve marathon ~6:30", abs(t - 6.5) < 0.1, hl.min_naar_tempo(t))


def test_jos3_setpoint():
    """[2026-10-08] JOS-3 setpoint-instorting bij lage BMR/m2 (ouderen)."""
    import warnings
    warnings.filterwarnings("ignore")
    from pythermalcomfort.models import JOS3
    from hestia_model import maak_jos3
    ruw = JOS3(height=1.94, weight=82, age=75, fat=18, sex="male")
    hersteld = maak_jos3(height=1.94, weight=82, age=75, fat=18, sex="male")
    # [2026-10-16] pythermalcomfort 4.6.2 lost de fout zelf op (issue #435,
    # pythermalcomfort maintainers). Op oudere versies moet de fout zichtbaar zijn, op 4.6.2+
    # moet ook de ruwe JOS-3 een correct setpoint geven.
    import pythermalcomfort as _ptc
    _v = tuple(int(x) for x in _ptc.__version__.split(".")[:3])
    if _v >= (4, 6, 2):
        check("JOS-3 >= 4.6.2: setpoint ook zonder herstel correct", 37.0 < ruw.cr_set_point[4] < 38.0,
              f"{ruw.cr_set_point[4]:.2f} (v{_ptc.__version__})")
    else:
        check("JOS-3 zonder herstel: setpoint te laag (bekende fout)", ruw.cr_set_point[4] < 36.5,
              f"{ruw.cr_set_point[4]:.2f}")
    # [2026-10-23] maak_jos3 zet de kern in rust op JOS3_REST_CORE_C (37,0) en schuift de
    # kern-instelwaarden mee (besluit van de auteur, ThermoClinic Emmen). De oude controles gelden
    # met JOS3_REST_CORE_SHIFT = False.
    import hestia_model as _H
    check("maak_jos3: bekkenkern en instelwaarde in rust 37,0",
          abs(hersteld.cr_set_point[4] - _H.JOS3_REST_CORE_C) < 1e-9 and abs(hersteld.t_core[4] - _H.JOS3_REST_CORE_C) < 1e-9,
          f"{hersteld.cr_set_point[4]:.2f} / {hersteld.t_core[4]:.2f}")
    _H.JOS3_REST_CORE_SHIFT = False
    try:
        a = JOS3(height=1.80, weight=75, age=45, fat=18, sex="male")
        b = maak_jos3(height=1.80, weight=75, age=45, fat=18, sex="male")
        check("maak_jos3 zonder rustverschuiving ongewijzigd waar JOS-3 al klopte",
              np.allclose(a.cr_set_point, b.cr_set_point) and np.allclose(a.sk_set_point, b.sk_set_point))
    finally:
        _H.JOS3_REST_CORE_SHIFT = True
    c = maak_jos3(height=1.80, weight=75, age=45, fat=18, sex="male")
    _d = c.cr_set_point - a.cr_set_point
    check("rustverschuiving: alle kern-instelwaarden even ver, huid-instelwaarden ongewijzigd",
          np.allclose(_d, _d[0]) and np.allclose(a.sk_set_point, c.sk_set_point), f"{_d[0]:+.3f} C")
    for m in (hersteld,):
        m.tdb, m.tr, m.rh, m.v, m.clo, m.par = 14.5, 24, 70, 3.0, 0.2, 7.36
        m.simulate(times=60, dtime=60)
    check("75 j, 60 min hardlopen bij 14,5 C: kern boven 38,5 C", hersteld.t_core[4] > 38.5,
          f"{hersteld.t_core[4]:.2f}")


def _basis(**kw):
    d = dict(lengte_cm=180, gewicht_kg=75, leeftijd=45, geslacht="man", evenement="T",
             datum="2026-07-01", starttijd="13:00", plaats="Testdorp", afstand_km=10,
             tempo_min_per_km="5:30", weer_excel="x.xlsx")
    d.update(kw)
    return hl.LoperInvoer(**d)


def test_validatie():
    for naam, kw in (("geslacht", dict(geslacht="m")), ("tempo", dict(tempo_min_per_km="1:00")),
                     ("leeftijd", dict(leeftijd=12)), ("wedstrijd half", dict(wedstrijd_afstand_km=10)),
                     ("weerbron", dict(weerbron="satelliet"))):
        try:
            _basis(**kw).valideer()
            check(f"validatie weigert {naam}", False)
        except ValueError:
            check(f"validatie weigert {naam}", True)
    af = hl.afleiden(_basis(tempo_min_per_km="3:00"))
    check("te snel tempo -> waarschuwing en klem", af.pct_geklemd and af.waarschuwingen)
    af = hl.afleiden(_basis(vo2max_bekend=55, hr_max_bekend=188))
    check("bekende VO2max en HRmax overgenomen", af.vo2max == 55 and af.hr_max == 188)


def test_json_rondgang():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.json"
        a = _basis(hr_max_bekend=185, alcohol_dag_ervoor=True)
        a.opslaan(p)
        b = hl.LoperInvoer.laden(p)
        check("JSON opslaan/laden", a == b)


def test_hr_override():
    m0 = CVRModel(RunnerProfile(mass=75, height=180, age=45, sex="male", vo2max=45))
    m1 = CVRModel(RunnerProfile(mass=75, height=180, age=45, sex="male", vo2max=45,
                                hr_max=190, hr_rest=50))
    check("CVR zonder override = Tanaka", abs(m0.HR_max - (208 - 0.7 * 45)) < 1e-9)
    check("CVR HR_max override", m1.HR_max == 190 and m1.HR_rest == 50)
    check("CO_max schaalt met HR_max", m1.CO_max > m0.CO_max)
    p = AdultParticipantProfile(1.8, 75, 45, "male", 18, 45, 0.7, 0, 0, 0.5, 0.8, 1.5, 0.1, False, 0.0)
    check("populatieprofiel standaard zonder HR-override", p.hr_max_known == 0.0 and p.hr_rest_known == 0.0)


def test_collapse():
    ic = COLLAPSE_ENDPOINTS[ACTIVE_ENDPOINT]["intercept_kal"]
    check("collapse zonder triggers = intercept", abs(hl.collapse_p(39.0, 3.0, 1.0) - 1 / (1 + math.exp(-ic))) < 1e-12)
    z = ic + 1.0 * 1.5 + 4.0 * 0.5 + 0.8 * 2.5 + 0.5 * 1.0
    check("collapse formule", abs(hl.collapse_p(41.0, -0.5, 4.0) - 1 / (1 + math.exp(-z))) < 1e-12)


def test_weer_excel():
    with tempfile.TemporaryDirectory() as d:
        p = _synthetisch_weer(Path(d) / "w.xlsx", gaten_op="2026-07-01 14:00")
        try:
            hl.weer_uit_excel(p, pd.Timestamp("2026-07-01 13:00"), pd.Timestamp("2026-07-01 14:30"))
            check("NaN in venster wordt geweigerd", False)
        except ValueError as e:
            check("NaN in venster wordt geweigerd", "Geen tabblad" in str(e))
        w = hl.weer_uit_excel(p, pd.Timestamp("2026-07-01 09:00"), pd.Timestamp("2026-07-01 11:00"))
        check("volledig venster gevonden", w[5] == "Forecast_7d" and str(w[0].index.tz) == "Europe/Amsterdam")


def test_end_to_end():
    from hestia_loper_plots import maak_alle_plots
    from hestia_loper_rapport import maak_rapport
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        xlsx = os.environ.get("LOPER_TEST_XLSX")
        if xlsx:
            datum = "2026-09-27"
        else:
            xlsx = str(_synthetisch_weer(d / "w.xlsx", t=30.0))
            datum = "2026-07-01"
        inv = _basis(datum=datum, starttijd="13:00", weer_excel=xlsx, afstand_km=10,
                     hr_max_bekend=182, wedstrijd_afstand_km=10, wedstrijd_tijd="48:00",
                     koorts_of_ziekte_recent=True)
        r = hl.analyseer_loper(inv, n_ensemble=8, seed=7, gevoeligheid=True)
        d1 = r.per_run
        check("ensemble 8 runs", len(d1) == 8)
        sleutel = ["t_rect_max_race", "co_reserve_min", "hr_piek", "dehydratie_eind_pct",
                   "finish_min_geschat", "p_collapse"]
        check("kernmaten zonder NaN", not d1[sleutel].isna().any().any(),
              str(d1[sleutel].isna().sum().to_dict()))
        check("hartslag niet boven HRmax", (d1["hr_piek"] <= 182 + 1e-6).all())
        check("signaal heeft kleur en redenen", r.signaal["kleur"] in hl.SIGNAAL_TEKST and r.signaal["redenen"])
        check("tempo-gevoeligheid 3 rijen", r.gevoeligheid is not None and len(r.gevoeligheid) == 3)
        check("langzamer -> lagere mediane piektemperatuur",
              r.gevoeligheid["t_rect_max_med"].iloc[-1] <= r.gevoeligheid["t_rect_max_med"].iloc[0] + 0.05,
              str(r.gevoeligheid["t_rect_max_med"].round(2).tolist()))
        r2 = hl.analyseer_loper(inv, n_ensemble=8, seed=7, gevoeligheid=False)
        check("reproduceerbaar met dezelfde seed",
              np.allclose(r2.per_run["t_rect_max"], d1["t_rect_max"]))
        plots = maak_alle_plots(r, d / "fig")
        verwacht = {"weer", "weer_dag", "dashboard", "alle_runs", "uitkomsten", "samenhang", "kerntemperatuur",
                    "hartreserve", "hartslag", "tempo", "vocht", "fasediagram", "verdeling", "tempo_watals"}
        check("14 figuren (incl. weer over de dag, dashboard, alle runs, uitkomsten, samenhang)",
              set(plots) == verwacht and all(p.exists() for p in plots.values()), str(sorted(verwacht - set(plots))))
        doc = maak_rapport(r, plots, d / "r.docx")
        from docx import Document
        tekst = "\n".join(p.text for p in Document(doc).paragraphs)
        check("rapport geschreven", doc.exists() and "Samenvatting" in tekst)
        check("niet-gemodelleerde factor in rapport", "infectie" in tekst)
        xl = hl.exporteer_excel(r, d / "r.xlsx")
        check("Excel met 8 bladen (incl. Weer_loop en Weer_dag)", {"Weer_loop", "Weer_dag"} <= set(pd.ExcelFile(xl).sheet_names) and len(pd.ExcelFile(xl).sheet_names) == 8, str(pd.ExcelFile(xl).sheet_names))


if __name__ == "__main__":
    for f in (test_tempo, test_vdot, test_begrenzing, test_jos3_setpoint, test_validatie, test_json_rondgang, test_hr_override,
              test_collapse, test_weer_excel, test_end_to_end):
        f()
    print(f"\n{'ALLES OK' if not FOUT else str(len(FOUT)) + ' FOUT(EN): ' + ', '.join(FOUT)}")
    sys.exit(1 if FOUT else 0)
