# -*- coding: utf-8 -*-
"""
test_clinic.py -- tests voor de clinic-validatie (modus B)
(clinic_invoer.py, inspanning_uit_fit.py, hestia_reconstructie.py,
clinic_validatie.py, clinic_rapport.py).

Zonder netwerk en zonder deelnemersdata: alles synthetisch.

    PYTHONPATH=. python3 test_clinic.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import clinic_invoer as ci
import inspanning_uit_fit as iuf
import hestia_reconstructie as hr_
import clinic_validatie as cv
from test_loper import _synthetisch_weer

FOUT = []


def check(naam, ok, info=""):
    print(f"[{'OK ' if ok else 'FOUT'}] {naam}" + (f"  ({info})" if info else ""))
    if not ok:
        FOUT.append(naam)


def _synthetische_export(pad: Path, code="T01", datum="2026-07-01", start="11:00",
                         stil_min=30, loop_min=30, na_min=12, v=3.0, core_hr=1, core_niveau=4):
    n = (stil_min + loop_min + na_min) * 60
    t = np.arange(n)
    loopt = (t >= stil_min * 60) & (t < (stil_min + loop_min) * 60)
    snel = np.where(loopt, v, 0.0)
    tl = np.clip(t - stil_min * 60, 0, None) / 60.0
    # hartslag loopt in ~2 min op (zoals in echte data; geen sprong > 30 binnen 5 s)
    hr = np.where(t >= stil_min * 60, 70 + (70 + 0.3 * np.minimum(tl, loop_min)) * np.clip(tl / 2.0, 0, 1), 70.0)
    hr = np.where(t >= (stil_min + loop_min) * 60, 70 + (hr - 70) * np.exp(-(t - (stil_min + loop_min) * 60) / 120), hr)
    kern = 37.0 + np.where(t >= stil_min * 60, 1.2 * (1 - np.exp(-np.minimum(tl, loop_min) / 15.0)), 0.0)
    ps = pd.DataFrame({"t_s": t, "afstand_m": np.cumsum(snel), "snelheid_ms": snel, "hartslag": hr,
                       "cadans": np.where(loopt, 85, 0), "kern_temp": kern, "huid_temp": 33.0,
                       "core_kwaliteit": core_niveau + 16 * core_hr, "core_hsi": 0.0,
                       "hoogteverschil_m": 0.0, "core_niveau": core_niveau,
                       "core_hartslag_gebruikt": core_hr, "t_min": t / 60.0})
    meta = {"code": code, "datum": datum, "starttijd_lokaal_afgerond": start, "utc_offset_uur": 2.0,
            "duur_min": n / 60, "afstand_km": snel.sum() / 1000, "vo2max_garmin_schatting": 50.0}
    delen = pd.DataFrame([{"deel": 1, "start_s": stil_min * 60, "eind_s": (stil_min + loop_min) * 60,
                           "duur_min": float(loop_min), "afstand_km": v * loop_min * 60 / 1000,
                           "tempo_min_km": 1000 / v / 60}])
    with pd.ExcelWriter(pad) as xw:
        pd.DataFrame(list(meta.items()), columns=["gegeven", "waarde"]).astype(str).to_excel(
            xw, sheet_name="Meta", index=False)
        ps.to_excel(xw, sheet_name="Per_seconde", index=False)
        delen.to_excel(xw, sheet_name="Inspanning", index=False)
    return pad


def _deelnemers(pad: Path, weer: Path, rijen: list[dict]):
    ci.maak_sjabloon(pad, voorbeeld=False)
    import openpyxl
    wb = openpyxl.load_workbook(pad)
    vals = {"datum": "2026-07-01", "starttijd": "11:30", "plaats": "Testdorp", "afstand_km": "9",
            "weerbestand": str(weer), "terrein": "open"}
    for r in wb["Clinic"].iter_rows():
        if r[0].value in vals:
            r[1].value = vals[r[0].value]
    ws = wb["Deelnemers"]
    kol = [c.value for c in ws[1]]
    for rij in rijen:
        ws.append([rij.get(k) for k in kol])
    wb.save(pad)
    return pad


BASIS = dict(code="T01", geslacht="m", leeftijd=35, lengte_cm=178, gewicht_voor_kg=72,
             gewicht_na_kg=71.2, verwacht_tempo="5:30", kleding="licht", hitte_gewend="n",
             drank_ml=300, geplast="n")


# -----------------------------------------------------------------------------
def test_invoer(tmp: Path):
    weer = _synthetisch_weer(tmp / "weer.xlsx")
    p = _deelnemers(tmp / "d1.xlsx", weer, [BASIS, {**BASIS, "code": "T02", "verwacht_tempo": dt.time(6, 15)}])
    c, d, m = ci.lees_deelnemers(p)
    check("clinic gelezen", c.datum == "2026-07-01" and c.starttijd == "11:30" and c.afstand_km == 9)
    check("twee deelnemers", [x.code for x in d] == ["T01", "T02"])
    check("tempo als Excel-tijd -> '6:15'", d[1].verwacht_tempo == "6:15", d[1].verwacht_tempo)
    vp = d[0].vochtverlies_gemeten_pct()
    check("vochtverlies (72-71,2+0,3)/72", abs(vp - (0.8 + 0.3) / 72 * 100) < 1e-9, f"{vp:.3f}")
    d[0].geplast = True
    check("geplast -> geen vochtverlies", d[0].vochtverlies_gemeten_pct() is None)
    li = ci.naar_loperinvoer(d[1], c)
    check("naar LoperInvoer", li.tempo_min_per_km == "6:15" and li.weer_excel == str(weer)
          and li.geslacht == "man" and li.afstand_km == 9)
    li.valideer()
    for naam, fout in [("geslacht x", {**BASIS, "geslacht": "x"}), ("dubbele code", None),
                       ("gewicht na onmogelijk", {**BASIS, "gewicht_na_kg": 60})]:
        rijen = [BASIS, BASIS] if fout is None else [fout]
        try:
            ci.lees_deelnemers(_deelnemers(tmp / f"f_{naam}.xlsx", weer, rijen))
            check(f"fout geweigerd: {naam}", False)
        except ValueError:
            check(f"fout geweigerd: {naam}", True)


def test_inspanning(tmp: Path):
    check("MET stilstaan 1,5", iuf.met_uit_snelheid(0.0) == 1.5)
    check("MET wandelen 1,2 m/s (ACSM)", abs(iuf.met_uit_snelheid(1.2) - (0.1 * 72 + 3.5) / 3.5) < 1e-9)
    vm = 180.0
    dg = (-4.60 + 0.182258 * vm + 0.000104 * vm ** 2) / 3.5
    check("MET lopen 3 m/s (Daniels-Gilbert)", abs(iuf.met_uit_snelheid(3.0) - dg) < 1e-9, f"{dg:.2f}")
    m = iuf.lees_export(_synthetische_export(tmp / "T01_2026-07-01.xlsx"))
    hd = iuf.hoofddeel(m)
    check("hoofddeel gevonden", hd is not None and hd.start_min == 30 and hd.eind_min == 59, str(hd))
    k = iuf.kwaliteit(m, hd)
    check("kwaliteit alles ok", all(v[0] for v in k.values()), str(k))
    s = iuf.vo2max_uit_loop(m, hd, leeftijd=35)
    hrmax = 208 - 0.7 * 35
    hr = float(m.per_minuut.loc[35:44, "hartslag"].mean())
    verwacht = 3.5 + (iuf.vo2_uit_snelheid(3.0) - 3.5) / ((hr - 70) / (hrmax - 70))
    check("VO2max uit loop (Swain)", abs(s.vo2max - verwacht) < 0.05, f"{s.vo2max:.1f} vs {verwacht:.1f}")
    m2 = iuf.lees_export(_synthetische_export(tmp / "T09_2026-07-01.xlsx", core_hr=0))
    check("CORE zonder hartslag -> kern valt af", not iuf.kwaliteit(m2, iuf.hoofddeel(m2))["kern"][0])
    m3 = iuf.lees_export(_synthetische_export(tmp / "T08_2026-07-01.xlsx", na_min=3))
    check("te kort na stoppen -> nawarmte valt af", not iuf.kwaliteit(m3, iuf.hoofddeel(m3))["nawarmte"][0])
    check("nawarmte gemeten berekend", np.isfinite(iuf.nawarmte_gemeten(m, hd)))


def test_reconstructie(tmp: Path):
    weer = pd.read_excel(_synthetisch_weer(tmp / "weer2.xlsx"), sheet_name="Forecast_7d", index_col=0)
    m = iuf.lees_export(_synthetische_export(tmp / "R01_2026-07-01.xlsx"))
    minuten = m.per_minuut[["snelheid_ms", "met"]].reset_index(drop=True)
    p = hr_.Persoon("man", 35, 178, 72, 0.2, False, 300)
    t0 = time.time()
    r = hr_.reconstrueer_varianten(p, minuten, weer, m.start_lokaal, ("B1", "B2", "B3"),
                                   {"populatie": 49.0, "garmin": 50.0}, n_ensemble=4, seed=1)
    check("drie varianten", set(r) == {"B1", "B2", "B3"}, f"{time.time() - t0:.1f} s")
    bmr = r["B2"].centraal.attrs["bmr_w_m2"]
    i = 45
    check("B1 par = MET", abs(r["B1"].centraal["par"].iat[i] - minuten["met"].iat[i]) < 1e-9)
    check("B2 par = MET x 58,2 / BMR", abs(r["B2"].centraal["par"].iat[i] - minuten["met"].iat[i] * 58.2 / bmr) < 1e-9)
    check("B3 = bekkenkern", np.allclose(r["B3"].centraal["t_rect"], r["B3"].centraal["t_bekken"]))
    check("B2 = gem17 + 0,5", np.allclose(r["B2"].centraal["t_rect"], r["B2"].centraal["t_gem17_05"]))
    check("B2 en B3 delen JOS-3", np.allclose(r["B2"].centraal["t_bekken"], r["B3"].centraal["t_bekken"]))
    check("B2 warmer dan B1 tijdens lopen", r["B2"].centraal["t_bekken"].iat[59] > r["B1"].centraal["t_bekken"].iat[59])
    check("band omsluit mediaan", bool((r["B1"].band["t_rect_lo"] <= r["B1"].band["t_rect_hi"]).all()))
    check("hartslag voor twee VO2max-bronnen", set(r["B1"].hr) == {"populatie", "garmin"})
    hrp = r["B1"].hr["populatie"]["hr"]
    check("hartslag hoger bij lopen dan in rust", hrp.iat[50] > hrp.iat[10] + 30, f"{hrp.iat[10]:.0f} -> {hrp.iat[50]:.0f}")
    check("lagere VO2max -> hogere hartslag", r["B1"].hr["populatie"]["hr"].iat[50] > r["B1"].hr["garmin"]["hr"].iat[50])
    r2 = hr_.reconstrueer(p, minuten, weer, m.start_lokaal, "B1", {"populatie": 49.0}, n_ensemble=4, seed=1)
    check("reproduceerbaar (seed)", np.allclose(r2.band["t_rect_hi"], r["B1"].band["t_rect_hi"]))
    try:
        hr_.weer_per_minuut(weer, pd.Timestamp("2026-07-05 10:00"), 60)
        check("weer buiten bereik geweigerd", False)
    except ValueError:
        check("weer buiten bereik geweigerd", True)


def test_dynamiek():
    import dynamiek as dyn
    u = np.r_[np.full(30, 1.5), np.full(45, 9.5), np.full(40, 3.0)]
    y = dyn.simuleer(u, 37.0, 0.28, 4, 18.0) + np.random.default_rng(3).normal(0, 0.01, len(u))
    r = dyn.analyse(u, y, 30, 74)
    check("identificatie K", abs(r["K"] - 0.28) < 0.01, f"{r['K']:.3f}")
    check("identificatie dode tijd", r["dode_tijd"] == 4, str(r["dode_tijd"]))
    check("identificatie tau", abs(r["tau"] - 18.0) < 1.0, f"{r['tau']:.1f}")
    check("tau stijgen ~ tau dalen bij lineair systeem", abs(r["tau_stijgen"] - r["tau_dalen"]) < 2.0,
          f"{r['tau_stijgen']:.1f}/{r['tau_dalen']:.1f}")
    # trage sensor achter hetzelfde systeem: grotere tau, lager maximum
    a = 1 - np.exp(-1 / 8.0)
    z = [y[0]]
    for v in y[1:]:
        z.append(z[-1] + a * (v - z[-1]))
    rz = dyn.analyse(u, np.array(z), 30, 74)
    check("trage sensor -> grotere tau", rz["tau"] > r["tau"] + 4, f"{rz['tau']:.1f} vs {r['tau']:.1f}")
    check("trage sensor -> lager maximum", rz["piek"] < r["piek"], f"{rz['piek']:.2f} vs {r['piek']:.2f}")
    hr = np.r_[np.full(30, 70.0), np.full(45, 150.0), np.full(40, 148.0)]
    o = dyn.hartslag_ontkoppeld(u, hr, 30, 74)
    check("hartslag ontkoppeld: 20 van 65 minuten", abs(o - 20 / 65 * 100) < 0.5, f"{o:.1f}%")
    hrs = dyn.simuleer(u, 70.0, 9.0, 0, 5.0)
    rh = dyn.hartslag_dynamiek(u, hrs, 30, 74, dyn.simuleer(u, 70.0, 9.0, 0, 0.6))
    check("hartslag: tau gemeten 5 / model 0,6", abs(rh["hr_tau"] - 5.0) < 0.3 and rh["hr_tau_model"] < 1.2,
          f"{rh['hr_tau']:.1f}/{rh['hr_tau_model']:.1f}")
    check("hartslag: geen extra boven eigen fit", abs(rh["hr_na_extra"]) < 0.5, f"{rh['hr_na_extra']:.2f}")
    check("hartslag: trager herstel -> positief verschil met model", rh["hr_na_model_verschil"] > 3,
          f"{rh['hr_na_model_verschil']:.1f}")
    hr2 = np.r_[np.full(30, 70.0), np.full(45, 150.0), np.full(40, 110.0)]
    check("hartslag volgt inspanning: 0%", dyn.hartslag_ontkoppeld(u, hr2, 30, 74) == 0)


def test_keten(tmp: Path):
    weer = _synthetisch_weer(tmp / "weer3.xlsx")
    map_ = tmp / "clinic"
    map_.mkdir()
    _deelnemers(map_ / "deelnemers.xlsx", weer, [BASIS, {**BASIS, "code": "T02"}])
    try:
        cv.vergelijk(map_, n=3)
        check("vergelijk zonder voorspelling geweigerd", False)
    except FileNotFoundError:
        check("vergelijk zonder voorspelling geweigerd", True)
    vast = cv.voorspel(map_, n=6)
    v = json.loads(vast.read_text(encoding="utf-8"))
    check("voorspelling vastgelegd", set(v["voorspellingen"]) == {"T01", "T02"} and not v["fouten"], str(v["fouten"]))
    check("vingerafdruk aanwezig", "hestia_model.py" in v["suite_vingerafdruk"])
    try:
        cv.voorspel(map_, n=6)
        check("vastlegging niet overschreven", False)
    except FileExistsError:
        check("vastlegging niet overschreven", True)
    time.sleep(1.1)
    (map_ / "fit_uitvoer").mkdir()
    _synthetische_export(map_ / "fit_uitvoer" / "T01_2026-07-01.xlsx", code="T01")
    _synthetische_export(map_ / "fit_uitvoer" / "T02_2026-07-01.xlsx", code="T02", core_hr=0)
    out = cv.vergelijk(map_, n=3)
    check("Excel gemaakt", Path(out["excel"]).exists())
    check("rapport gemaakt", Path(out["rapport"]).exists())
    check("figuur per loper", "T01" in out["figuren"] and "T02" in out["figuren"])
    x = pd.ExcelFile(out["excel"])
    inc = pd.read_excel(x, "Inclusie")
    check("T02 valt af voor kern", inc.set_index("code").loc["T02", "kern_mee"] == "nee")
    g = pd.read_excel(x, "Groep")
    kb = g[(g.maat == "kern_bias") & (g.variant == "B1")].iloc[0]
    check("groep: n=1, beschrijvend", kb.n_lopers == 1 and kb.oordeel.startswith("beschrijvend"), kb.oordeel)
    vl = pd.read_excel(x, "Vastlegging")
    check("geen controlemeldingen", (vl.waarde == "geen bijzonderheden").any(), "; ".join(vl.waarde.astype(str)))
    m = pd.read_excel(x, "Maten_B1").set_index("code")
    check("vochtverlies gemeten in maten", abs(m.loc["T01", "vocht_meting_pct"] - 1.1 / 72 * 100) < 1e-6)
    check("modus A gekoppeld", np.isfinite(m.loc["T01", "A_t_op_meetduur_med"]))
    check("dynamica in maten", np.isfinite(m.loc["T01", "dyn_tau_model"]) and np.isfinite(m.loc["T01", "kern_max_verschil"]))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        test_invoer(tmp)
        test_inspanning(tmp)
        test_reconstructie(tmp)
        test_dynamiek()
        test_keten(tmp)
    print()
    if FOUT:
        print(f"{len(FOUT)} FOUT(EN): " + ", ".join(FOUT))
        raise SystemExit(1)
    print("Alle clinic-tests geslaagd.")
