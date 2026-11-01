# -*- coding: utf-8 -*-
"""
fit_loop.py -- een losse loop uit een FIT-bestand narekenen met HESTIA
======================================================================

[2026-10-27] Voor één loper en één loop, zonder deelnemerslijst en zonder
vooraf vastgelegde voorspelling (daarvoor is de Thermo Clinic-keten in
clinic_validatie.py). Gebruikt dezelfde, geteste bouwstenen:

  FIT-bestand  -> fit_lezer (alleen toegestane velden, code i.p.v. naam)
               -> inspanning_uit_fit (inspanning per minuut uit de gemeten snelheid)
               -> hestia_reconstructie (JOS-3 + CVR met het gemeten tempo en
                  het weer van de Data Engine), varianten:
                    B3  HESTIA zoals de suite rekent (bekkenkern)
                    B4  idem met begrensd koude-huidsignaal (2 K; verkennend)
               -> clinic_validatie._kern_maten e.a. (zelfde maten als de clinic)
  en maakt een kort Word-rapport, een Excel-bestand en een figuur.

Een rapportpakket (rapportpakket.py) wordt altijd bewaard, zodat het rapport
ook later gemaakt kan worden (startmenu, keuze R).

Gebruik: via het startmenu (start_thermopoulos.py, keuze 4 -> 1), of
    python fit_loop.py
"""
from __future__ import annotations

import shutil
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

VARIANTEN = ("B3", "B4")
N_ENSEMBLE = 30
SEED = 42
WBGT_KOUDE_HUID = 18.0   # onder deze WBGT rekent JOS-3 bij hardlopen de kern vermoedelijk te warm


# -----------------------------------------------------------------------------
# Rekenen
# -----------------------------------------------------------------------------
def bereken(bron: str | Path, persoon: dict, weerbestand: str | Path, uitmap: str | Path,
            plaats: str = "", n: int = N_ENSEMBLE, seed: int = SEED) -> dict:
    """Reken één loop na. bron = .fit-bestand of een FIT-export (.xlsx van fit_lezer).

    persoon: code, geslacht ('man'/'vrouw'), leeftijd, lengte_cm, gewicht_kg,
             kleding ('licht'/'normaal'/'lang'), hitte_gewend (bool),
             optioneel hr_max, hr_rust, vo2max, gewicht_na_kg, drank_ml.
    Geeft de rapportgegevens terug (dict) en schrijft Excel en figuur in uitmap.
    """
    import clinic_invoer as ci
    import clinic_validatie as cv
    import clinic_rapport as cr
    import inspanning_uit_fit as iuf
    import fit_lezer as fl

    bron = Path(bron)
    uitmap = Path(uitmap)
    fit_map = uitmap / "fit_uitvoer"
    fit_map.mkdir(parents=True, exist_ok=True)
    code = "".join(c for c in str(persoon["code"]) if c.isalnum() or c in "-_") or "L01"
    if bron.suffix.lower() == ".fit":
        rit = fl.lees_fit(bron, code)
        export = fl.exporteer(rit, fit_map)["xlsx"]
    elif bron.suffix.lower() == ".xlsx":
        export = fit_map / bron.name
        if bron.resolve() != export.resolve():
            shutil.copy2(bron, export)
    else:
        raise ValueError("Kies een .fit-bestand of een FIT-export (.xlsx).")
    m = iuf.lees_export(export)
    hd = iuf.hoofddeel(m)
    if hd is None:
        raise ValueError("In dit bestand is geen loopdeel gevonden (te kort of geen snelheid).")

    d = ci.Deelnemer(code=code, geslacht=persoon["geslacht"], leeftijd=int(persoon["leeftijd"]),
                     lengte_cm=float(persoon["lengte_cm"]), gewicht_voor_kg=float(persoon["gewicht_kg"]),
                     verwacht_tempo=f"{int(hd.tempo_min_km)}:{round((hd.tempo_min_km % 1) * 60):02d}",
                     kleding=persoon["kleding"], hitte_gewend=bool(persoon["hitte_gewend"]),
                     gewicht_na_kg=persoon.get("gewicht_na_kg"), drank_ml=persoon.get("drank_ml"),
                     vo2max=persoon.get("vo2max"), hr_max=persoon.get("hr_max"),
                     hr_rust=persoon.get("hr_rust"))
    clinic = ci.Clinic(datum=str(m.start_lokaal.date()), starttijd=m.start_lokaal.strftime("%H:%M"),
                       plaats=plaats or "", afstand_km=float(hd.afstand_km),
                       weerbestand=str(weerbestand))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lv = cv.vergelijk_loper(d, clinic, fit_map, None, {}, n, seed, varianten=VARIANTEN,
                                weerbestand=str(weerbestand))
    if not lv.recon:
        raise RuntimeError("De reconstructie lukte niet: " +
                           "; ".join(f"{k}: {v[1]}" for k, v in lv.inclusie.items()))

    # weer tijdens het loopdeel
    from hestia_loper import weer_uit_excel
    start = m.start_lokaal + pd.Timedelta(minutes=hd.start_min)
    eind = m.start_lokaal + pd.Timedelta(minutes=hd.eind_min)
    w = weer_uit_excel(weerbestand, start, eind)[0]
    idx = w.index.tz_localize(None) if getattr(w.index, "tz", None) is not None else w.index
    venster = w[(idx >= start.floor("h")) & (idx <= eind.ceil("h"))]
    weer = {k: float(venster[c].mean()) for k, c in
            (("t_lucht", "T_air_urban"), ("rv", "RH"), ("wbgt", "WBGT"), ("wind", "wind_10m"),
             ("zon", "solar_radiation")) if c in venster.columns}

    pm = m.per_minuut
    kern_ok = bool(lv.inclusie.get("kern", (False,))[0])
    meting = {
        "duur_min": float(hd.duur_min), "afstand_km": float(hd.afstand_km),
        "tempo_min_km": float(hd.tempo_min_km),
        "hr_gem": float(pm["hartslag"].reindex(hd.minuten).mean()),
        "hr_max": float(pm["hartslag"].reindex(hd.minuten).max()),
        "kern_max": float(pm["kern_temp"].reindex(np.arange(hd.start_min, hd.eind_min + 21)).max())
        if kern_ok else float("nan"),
        "kern_ok": kern_ok, "kern_reden": lv.inclusie.get("kern", (False, ""))[1],
        "vocht_pct": persoon_vocht(d),
    }
    model = {}
    for v in VARIANTEN:
        rc = lv.recon[v]
        t = rc.centraal["t_rect"]
        mt = lv.maten.get(v, {})
        model[v] = {
            "kern_max": float(t.reindex(np.arange(hd.start_min, hd.eind_min + 21)).max()),
            "kern_max_lo": float(rc.band["t_rect_lo"].reindex(hd.minuten).max()),
            "kern_max_hi": float(rc.band["t_rect_hi"].reindex(hd.minuten).max()),
            "kern_bias": mt.get("kern_bias", float("nan")),
            "huid_borst_bias": mt.get("huid_borst_bias", float("nan")),
            "vocht_pct": mt.get("vocht_model_pct", float("nan")),
            "hr_bias": next((mt[k] for k in ("hr_bias_gemeten", "hr_bias_hestia", "hr_bias_populatie")
                             if k in mt and np.isfinite(mt[k])), float("nan")),
        }
    stam = uitmap / f"FITloop_{code}_{clinic.datum}"
    fig = cr.figuur_loper(lv, Path(str(stam) + "_figuur.png"))
    # Excel: tijdreeks per minuut
    t = pd.DataFrame(index=lv.recon[VARIANTEN[0]].centraal.index)
    t.index.name = "minuut"
    for k in ("snelheid_ms", "met", "hartslag", "kern_temp", "huid_temp"):
        if k in pm:
            t[f"meting_{k}"] = pm[k].reindex(t.index)
    for v, rc in lv.recon.items():
        t[f"{v}_kern"] = rc.centraal["t_rect"]
        t[f"{v}_kern_lo"] = rc.band["t_rect_lo"]
        t[f"{v}_kern_hi"] = rc.band["t_rect_hi"]
        t[f"{v}_huid_borst"] = rc.centraal["huid_borst"]
        for b, h in rc.hr.items():
            t[f"{v}_hartslag_{b}"] = h["hr"]
    xlsx = Path(str(stam) + ".xlsx")
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        pd.DataFrame([{"code": code, **{k: v for k, v in persoon.items() if k != "code"}}]).to_excel(
            xw, sheet_name="Loper", index=False)
        pd.DataFrame([{**meting, **{f"weer_{k}": v for k, v in weer.items()}}]).to_excel(
            xw, sheet_name="Meting", index=False)
        pd.DataFrame([{"variant": v, **x} for v, x in model.items()]).to_excel(
            xw, sheet_name="Model", index=False)
        t.round(3).to_excel(xw, sheet_name="Tijdreeks")
    return {"code": code, "datum": clinic.datum, "starttijd": start.strftime("%H:%M"),
            "plaats": plaats, "weerbestand": Path(weerbestand).name, "persoon": persoon,
            "weer": weer, "meting": meting, "model": model, "vo2max": lv.vo2max,
            "figuur": str(fig) if fig else None, "excel": str(xlsx), "stam": str(stam)}


def persoon_vocht(d) -> float:
    v = d.vochtverlies_gemeten_pct()
    return float(v) if v is not None else float("nan")


# -----------------------------------------------------------------------------
# Rapport
# -----------------------------------------------------------------------------
def _k(x, n=2, teken=False):
    if x is None or not np.isfinite(x):
        return "–"
    s = f"{x:+.{n}f}" if teken else f"{x:.{n}f}"
    return s.replace(".", ",")


def maak_rapport(g: dict, pad: str | Path) -> Path:
    from docx import Document
    from docx.shared import Pt, Cm
    pad = Path(pad)
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(12)
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = Cm(2.0)

    def P(t, i=False, b=False):
        p = doc.add_paragraph(); r = p.add_run(t); r.italic = i; r.bold = b; return p

    def T(rows, head):
        tb = doc.add_table(rows=1, cols=len(head)); tb.style = "Light Grid Accent 1"
        for i, h in enumerate(head):
            tb.rows[0].cells[i].text = h
        for row in rows:
            cs = tb.add_row().cells
            for i, v in enumerate(row):
                cs[i].text = str(v)
        doc.add_paragraph()

    me, mo, w, ps = g["meting"], g["model"], g["weer"], g["persoon"]
    doc.add_heading(f"Loop {g['code']} van {g['datum']}, nagerekend met HESTIA", 0)
    P(f"Gemaakt met de HESTIA-PYROX-Klimatos-suite op {datetime.now():%d-%m-%Y}. "
      f"Weerbestand: {g['weerbestand']}. De loper staat onder een code; namen worden niet gebruikt.", i=True)

    doc.add_heading("1. De loop", 1)
    tempo = me["tempo_min_km"]
    T([["Start loopdeel", g["starttijd"]], ["Duur", f"{_k(me['duur_min'], 0)} min"],
       ["Afstand", f"{_k(me['afstand_km'], 2)} km"],
       ["Gemiddeld tempo", f"{int(tempo)}:{round((tempo % 1) * 60):02d} min/km"],
       ["Hartslag gemiddeld / hoogste", f"{_k(me['hr_gem'], 0)} / {_k(me['hr_max'], 0)} /min"],
       ["Luchttemperatuur, luchtvochtigheid", f"{_k(w.get('t_lucht', np.nan), 1)} °C, {_k(w.get('rv', np.nan), 0)} %"],
       ["Hittebelasting (WBGT)", _k(w.get("wbgt", np.nan), 1)],
       ["Loper", f"{ps['geslacht']}, {ps['leeftijd']} jaar, {ps['lengte_cm']} cm, {ps['gewicht_kg']} kg, "
                 f"kleding {ps['kleding']}, {'aan warmte gewend' if ps['hitte_gewend'] else 'niet aan warmte gewend'}"]],
      ["", ""])

    doc.add_heading("2. Kerntemperatuur", 1)
    rows = [["HESTIA (B3)", _k(mo["B3"]["kern_max"]), f"{_k(mo['B3']['kern_max_lo'])} – {_k(mo['B3']['kern_max_hi'])}",
             _k(mo["B3"]["kern_bias"], 2, True)]]
    if "B4" in mo:
        rows.append(["HESTIA met koude-huidgrens (B4, verkennend)", _k(mo["B4"]["kern_max"]),
                     f"{_k(mo['B4']['kern_max_lo'])} – {_k(mo['B4']['kern_max_hi'])}",
                     _k(mo["B4"]["kern_bias"], 2, True)])
    rows.append(["Gemeten (CORE-sensor)", _k(me["kern_max"]) if me["kern_ok"] else "niet bruikbaar", "", ""])
    T(rows, ["", "Hoogste kern (°C)", "Spreiding 95 % (°C)", "Model min sensor, gemiddeld (°C)"])
    if not me["kern_ok"]:
        P(f"De CORE-meting is niet gebruikt: {me['kern_reden']}.")
    P("Kanttekeningen bij de vergelijking:")
    for t in [
        "De CORE-sensor meet de kerntemperatuur niet direct maar schat die uit de warmtestroom door "
        "de huid en de hartslag. Bij hardlopen meet hij in onderzoek meestal 0,1 tot 0,5 °C lager dan "
        "een temperatuurpil, en meer naarmate de kern warmer is.",
        "B3 is HESTIA zoals de suite standaard rekent. B4 begrenst het effect van een koude huid in "
        "JOS-3; dat is een verkennende variant, nog niet getoetst.",
    ] + ([f"Deze loop was bij WBGT {_k(w['wbgt'], 1)}. Onder ongeveer WBGT {WBGT_KOUDE_HUID:.0f} "
          "rekent HESTIA bij hardlopen de kern vermoedelijk enkele tienden te warm, doordat JOS-3 de huid "
          "te sterk laat afkoelen; B4 laat zien hoe groot dat effect hier is."]
         if np.isfinite(w.get("wbgt", np.nan)) and w["wbgt"] < WBGT_KOUDE_HUID else []):
        doc.add_paragraph(t, style="List Bullet")

    doc.add_heading("3. Hartslag en vochtverlies", 1)
    T([["Hartslag, model min meting (gemiddeld)", f"{_k(mo['B3']['hr_bias'], 1, True)} /min"],
       ["Vochtverlies model (B3)", f"{_k(mo['B3']['vocht_pct'], 1)} % van het lichaamsgewicht"],
       ["Vochtverlies gemeten", f"{_k(me['vocht_pct'], 1)} %" if np.isfinite(me["vocht_pct"])
        else "niet gemeten (weging voor en na en drank nodig)"],
       ["Huid borst, model min sensor (B3)", f"{_k(mo['B3']['huid_borst_bias'], 1, True)} °C"]],
      ["", ""])
    vo = g.get("vo2max", {})
    P("VO2max gebruikt voor de hartslag: " + ", ".join(f"{k} {_k(v, 1)}" for k, v in vo.items() if v) +
      " mL/kg/min ('hestia' = afgeleid uit hartslag en snelheid van deze loop).", i=True)

    if g.get("figuur") and Path(g["figuur"]).exists():
        doc.add_heading("4. Verloop", 1)
        doc.add_picture(g["figuur"], width=Cm(16))
        P("Boven: kerntemperatuur (gekleurd het model met spreiding, zwart de sensor). Daaronder hartslag, "
          "huidtemperatuur op de borst en inspanning. Het grijze vlak is het loopdeel.", i=True)

    doc.add_heading("Waar deze uitkomst voor geldt", 1)
    for t in ["HESTIA is onderzoekssoftware en niet gevalideerd voor beslissingen over iemands veiligheid.",
              "Het model krijgt het gemeten tempo en het uurweer van de Data Engine; wind, zon en "
              "kleding zijn benaderingen.",
              "Eén loop zegt weinig over de nauwkeurigheid. Voor een toetsing van het model: de Thermo "
              "Clinic-keten met vooraf vastgelegde voorspelling."]:
        doc.add_paragraph(t, style="List Bullet")
    doc.save(pad)
    return pad


# -----------------------------------------------------------------------------
# Interactief
# -----------------------------------------------------------------------------
def _vraag(tekst, standaard=None, soort=str, leeg_mag=False):
    extra = f" [{standaard}]" if standaard not in (None, "") else (" [leeg = onbekend]" if leeg_mag else "")
    while True:
        a = input(f"  {tekst}{extra}: ").strip().strip('"')
        if a == "":
            if standaard not in (None, ""):
                a = str(standaard)
            elif leeg_mag:
                return None
            else:
                print("    Dit veld is verplicht.")
                continue
        try:
            if soort is bool:
                return a.lower() in ("j", "ja", "y", "yes", "1")
            return soort(a.replace(",", ".")) if soort in (int, float) else soort(a)
        except ValueError:
            print("    Ongeldige invoer.")


def _kies(lijst, tekst):
    for i, p in enumerate(lijst, 1):
        print(f"    {i}  {p.name}")
    k = input(f"  {tekst} (nummer, of een pad): ").strip().strip('"')
    if k.isdigit() and 1 <= int(k) <= len(lijst):
        return lijst[int(k) - 1]
    return Path(k) if k else None


def interactief(werkmap: str | Path = ".") -> int:
    werkmap = Path(werkmap)
    print("\nEén loop narekenen met HESTIA (FIT-bestand van horloge en eventueel CORE-sensor)")
    fits = sorted(list(werkmap.glob("*.fit")) + list((werkmap / "fit_invoer").glob("*.fit")))
    if fits:
        print("  FIT-bestanden in de werkmap:")
    bron = _kies(fits, "FIT-bestand")
    if not bron or not bron.exists():
        print("  Geen bestand gekozen.")
        return 1
    weer = sorted(werkmap.glob("Thermopoulos*.xlsx"))
    print("  Weerbestanden (Data Engine) in de werkmap:" if weer else
          "  Geen weerbestand in de werkmap. Haal eerst het weer op (startmenu 5, archief/hindcast "
          "voor de dag van de loop) of geef een pad.")
    wb = _kies(weer, "Weerbestand")
    if not wb or not wb.exists():
        print("  Geen weerbestand gekozen.")
        return 1
    print("  Gegevens van de loper (geen naam):")
    persoon = {
        "code": _vraag("Code", "L01"),
        "geslacht": "man" if _vraag("Geslacht (m/v)", "m").lower().startswith("m") else "vrouw",
        "leeftijd": _vraag("Leeftijd (jaren)", soort=int),
        "lengte_cm": _vraag("Lengte (cm)", soort=float),
        "gewicht_kg": _vraag("Gewicht vóór de loop (kg)", soort=float),
        "kleding": _vraag("Kleding (licht/normaal/lang)", "licht"),
        "hitte_gewend": _vraag("Aan warmte gewend? (j/n)", "n", bool),
        "hr_max": _vraag("Maximale hartslag, gemeten", soort=float, leeg_mag=True),
        "hr_rust": _vraag("Rusthartslag 's ochtends", soort=float, leeg_mag=True),
        "gewicht_na_kg": _vraag("Gewicht na de loop (kg)", soort=float, leeg_mag=True),
        "drank_ml": _vraag("Gedronken tussen de wegingen (ml)", soort=float, leeg_mag=True),
    }
    if persoon["kleding"] not in ("licht", "normaal", "lang"):
        persoon["kleding"] = "licht"
    plaats = _vraag("Plaats (voor het rapport)", wb.stem.replace("Thermopoulos_DataEngine_", "").split("_")[0])
    uit = werkmap / f"FITloop_{persoon['code']}_{datetime.now():%Y%m%d_%H%M}"
    print("  Rekenen (ongeveer een minuut)...")
    try:
        g = bereken(bron, persoon, wb, uit, plaats=plaats)
    except Exception as e:
        print(f"\n  Kan de loop niet narekenen: {e}")
        return 1
    import rapportpakket
    pk = rapportpakket.bewaar("fitloop", g, g["stam"])
    print(f"  Klaar. Excel: {g['excel']}")
    if pk:
        print(f"  Rapportgegevens bewaard: {pk.name} (startmenu R = rapport later maken)")
    if _vraag("Rapport nu maken? (j/n)", "j", bool):
        print(f"  Rapport: {maak_rapport(g, Path(g['stam'] + '.docx'))}")
    return 0


if __name__ == "__main__":
    _rc = interactief(Path.cwd())
    if _rc and not (hasattr(sys, "ps1") or "spyder_kernels" in sys.modules):
        sys.exit(_rc)
