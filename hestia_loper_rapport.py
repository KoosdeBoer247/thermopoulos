# -*- coding: utf-8 -*-
"""
hestia_loper_rapport.py -- persoonlijk Word-rapport (Nederlands, 14 pt).

maak_rapport(resultaat, plots, pad) schrijft een .docx met: samenvatting en
modelsignaal, invoer en afgeleide fitheid, weer, kerntemperatuur, hart en
bloedsomloop, vocht, tempo, gecombineerde maten (Roberts, TCF, punt van geen
terugkeer, collapsekans), wat-als langzamer, niet-gemodelleerde factoren,
wat het model wel en niet kan, en een technische bijlage.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from hestia_loper import (LoperResultaat, NIET_GEMODELLEERD, SIGNAAL_TEKST,
                          min_naar_tempo, nl, COLLAPSE_ENDPOINTS, ACTIVE_ENDPOINT,
                          AUC_ROBERTS_GRENS, TCF_CFG)

SIGNAAL_KLEUR = {"groen": "0CA30C", "geel": "FAB219", "oranje": "EC835A", "rood": "D03B3B"}
SIGNAAL_SYMBOOL = {"groen": "●", "geel": "▲", "oranje": "◆", "rood": "■"}
BASIS_PT = 14


def _stijl(doc):
    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(BASIS_PT)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    st.paragraph_format.space_after = Pt(6)
    st.paragraph_format.line_spacing = 1.15
    for naam, grootte in (("Heading 1", 22), ("Heading 2", 18), ("Heading 3", 16), ("Title", 30)):
        h = doc.styles[naam]
        h.font.name = "Calibri"
        h.font.size = Pt(grootte)
        h.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
        rpr = h.element.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.append(rf)
        for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
            rf.set(qn(a), "Calibri")
    for naam in ("List Bullet",):
        doc.styles[naam].font.size = Pt(BASIS_PT)
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.0)
    sec.top_margin = sec.bottom_margin = Cm(2.0)


def _arcering(cel, hexkleur):
    tcPr = cel._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexkleur)
    tcPr.append(shd)


def _tabel(doc, rijen, kop=True, breedtes=None, pt=12):
    t = doc.add_table(rows=len(rijen), cols=len(rijen[0]))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, rij in enumerate(rijen):
        for j, waarde in enumerate(rij):
            cel = t.cell(i, j)
            cel.text = ""
            run = cel.paragraphs[0].add_run(str(waarde))
            run.font.size = Pt(pt)
            if kop and i == 0:
                run.bold = True
                _arcering(cel, "DCE6F0")
            if breedtes:
                cel.width = Cm(breedtes[j])
    doc.add_paragraph()
    return t


def _p(doc, tekst, vet=False, cursief=False, pt=None):
    par = doc.add_paragraph()
    run = par.add_run(tekst)
    run.bold, run.italic = vet, cursief
    if pt:
        run.font.size = Pt(pt)
    return par


def _bullets(doc, items):
    for it in items:
        doc.add_paragraph(it, style="List Bullet")


def _figuur(doc, pad, onderschrift):
    if pad is None:
        return
    doc.add_picture(str(pad), width=Cm(16.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    _p(doc, onderschrift, cursief=True, pt=12)


def _pct(x):
    return f"{x * 100:.0f}%" if x >= 0.01 or x == 0 else f"{x * 100:.1f}%".replace(".", ",")


def _frac_tekst(f):
    return (f"{_pct(f['frac'])} ({f['k']} van {f['n']} runs; 95%-interval "
            f"{_pct(f['lo'])}–{_pct(f['hi'])})")


def _uur(minuten):
    """Duur in minuten -> 'u:mm'."""
    totaal = int(round(minuten))
    return f"{totaal // 60}:{totaal % 60:02d}"


def _km(x):
    return f"{x:g}".replace(".", ",")


def _per1000(p):
    v = p * 1000
    return nl(v, 1) if v < 10 else f"{v:.0f}"


def maak_rapport(r: LoperResultaat, plots: dict, pad: str | Path) -> Path:
    inv, af, a = r.invoer, r.afgeleid, r.assessment
    s = r.samenvatting()
    sig = r.signaal
    doc = Document()
    _stijl(doc)

    # ------------------------------------------------------------ titel
    doc.add_paragraph(f"Persoonlijke hitte-analyse", style="Title")
    _p(doc, f"{inv.evenement} – {_km(inv.afstand_km)} km – "
            f"{datetime.strptime(inv.datum, '%Y-%m-%d'):%d-%m-%Y}, start {inv.starttijd} – "
            f"{a.city_name}", vet=True, pt=16)
    if inv.naam:
        _p(doc, f"Voor: {inv.naam}")
    _p(doc, f"Gemaakt met HESTIA (Thermopoulos-suite) op {datetime.now():%d-%m-%Y %H:%M}. "
            f"Weerbron: {r.weer_sheet}.", pt=12)
    _p(doc, "Dit rapport is een modelberekening, geen medisch advies. Het model kan "
            "zich vergissen. Luister tijdens de loop altijd naar je lichaam en naar de "
            "medische hulpverleners.", cursief=True)

    # ------------------------------------------------------------ samenvatting
    doc.add_heading("1. Samenvatting", level=1)
    t = doc.add_table(rows=1, cols=1)
    cel = t.cell(0, 0)
    _arcering(cel, SIGNAAL_KLEUR[sig["kleur"]])
    run = cel.paragraphs[0].add_run(f"{SIGNAAL_SYMBOOL[sig['kleur']]}  {SIGNAAL_TEKST[sig['kleur']]} "
                                    f"({sig['kleur']})")
    run.bold = True
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if sig["kleur"] in ("rood", "oranje", "groen") else RGBColor(0, 0, 0)
    doc.add_paragraph()
    if af.pct_geklemd:
        par = _p(doc, "Belangrijk: je opgegeven tempo is hoger dan het model voor jou haalbaar "
                      "acht. De uitkomsten hieronder gelden voor een loper op de grens van zijn "
                      "vermogen en niet voor het tempo dat je opgaf. Zie 'Let op bij de invoer'.",
                 vet=True)
        for run in par.runs:
            run.font.color.rgb = RGBColor(0xD0, 0x3B, 0x3B)
    _p(doc, "Waarom dit signaal:", vet=True)
    _bullets(doc, sig["redenen"])

    _p(doc, "De belangrijkste uitkomsten:", vet=True)
    tm, cm = s["t_rect_max"], s["co_min"]
    kern = [
        f"Je kerntemperatuur loopt tijdens de loop op tot ongeveer {nl(tm['med'])} °C "
        f"(in de ongunstigste runs {nl(tm['hi'])} °C).",
        f"Je hart houdt een reserve over van minimaal ongeveer {nl(cm['med'])} L/min "
        f"(in de ongunstigste runs {nl(cm['lo'])} L/min). Onder 2 L/min is de marge klein, "
        f"onder 0 is de reserve op.",
        f"Je verliest naar verwachting {nl(s['dehyd']['med'])}% van je lichaamsgewicht aan vocht.",
        f"Je hartslag komt naar verwachting tot ongeveer {s['hr_piek']['med']:.0f} slagen/min "
        f"(je maximum in het model: {af.hr_max:.0f}).",
        (f"Het model verwacht dat je tempo met ongeveer {nl(s['tempo_daling']['med'], 0)}% daalt; "
         if s['tempo_daling']['med'] >= 1 else "Het model verwacht nauwelijks vertraging; ")
        + f"geschatte finishtijd {_uur(s['finish']['med'])} (u:mm) "
        f"bij gepland {_uur(inv.duur_min)}.",
    ]
    _bullets(doc, kern)
    if af.waarschuwingen:
        _p(doc, "Let op bij de invoer:", vet=True)
        _bullets(doc, af.waarschuwingen)

    _p(doc, "Wat je kunt doen:", vet=True)
    advies = [
        "Drink volgens plan, bij voorkeur bij elke drankpost een paar slokken; niet "
        "veel meer drinken dan je zweet.",
        "Begin rustiger dan je van plan was als het warm is; het model laat bij "
        "'Wat als je langzamer loopt' zien wat dat oplevert.",
        "Zoek schaduw op en koel af met water over hoofd en nek waar dat kan.",
        "Stop en vraag direct hulp bij verwardheid, wankelen, vreemd gedrag, hevige "
        "hoofdpijn, misselijkheid of als je je plotseling slecht voelt. Bij een "
        "hitteberoerte merk je dat zelf vaak niet; let ook op elkaar.",
    ]
    if any(getattr(inv, k) for k in NIET_GEMODELLEERD):
        advies.insert(0, "Je hebt een of meer risicofactoren opgegeven die het model niet "
                         "meeneemt (hoofdstuk 9). Je werkelijke risico kan daardoor hoger zijn "
                         "dan hier berekend.")
    _bullets(doc, advies)

    # ------------------------------------------------------------ invoer
    doc.add_heading("2. Jouw gegevens", level=1)
    rijen = [["Gegeven", "Waarde"],
             ["Lengte / gewicht", f"{inv.lengte_cm:.0f} cm / {nl(inv.gewicht_kg)} kg"],
             ["Leeftijd / geslacht", f"{inv.leeftijd} jaar / {inv.geslacht}"],
             ["Afstand / gepland tempo", f"{_km(inv.afstand_km)} km / {min_naar_tempo(inv.tempo)} min/km "
                                         f"(looptijd {_uur(inv.duur_min)})"],
             ["Trainingsomvang", f"{inv.trainingskm_per_week:g} km per week"],
             ["Hitte-gewend", "ja" if inv.hitte_geacclimatiseerd else "nee"],
             ["Drinkt bij elke post", "ja" if inv.drinkt_bij_elke_post else "nee, pas bij dorst"],
             ["Pijnstillers (NSAID)", "ja" if inv.nsaid_voor_of_tijdens else "nee"],
             ["Kleding", f"{inv.kleding} (clo {nl(af.clo)})"]]
    _tabel(doc, rijen, breedtes=[6.5, 10])
    _p(doc, "Afgeleid door het model:", vet=True)
    rijen = [["Grootheid", "Waarde", "Bron"],
             ["VO2max", f"{nl(af.vo2max)} mL/kg/min", af.vo2max_bron],
             ["Zuurstofvraag bij je tempo", f"{nl(af.vo2_bij_tempo)} mL/kg/min "
                                            f"({_pct(af.vo2_bij_tempo / af.vo2max)} van VO2max)",
              "Daniels & Gilbert"],
             ["Inspanning", f"{nl(af.met_tempo)} MET", "1 MET = 3,5 mL/kg/min"],
             ["Maximale hartslag", f"{af.hr_max:.0f} /min", af.hr_max_bron],
             ["Rusthartslag", f"{af.hr_rust:.0f} /min" if af.hr_rust else "uit VO2max (Lloyd 2022)",
              "zelf opgegeven" if af.hr_rust else "modelvergelijking"]]
    _tabel(doc, rijen, breedtes=[5, 5, 6.5])

    # ------------------------------------------------------------ weer
    doc.add_heading("3. Het weer tijdens je loop", level=1)
    m = a.meteo
    _p(doc, f"Gemiddelde luchttemperatuur {nl(a.mean_t_air_c)} °C; WBGT van "
            f"{nl(np.nanmin(m['wbgt']))} tot {nl(np.nanmax(m['wbgt']))} °C; "
            f"stralingstemperatuur tot {nl(np.nanmax(m['mrt']))} °C. Het model rekent niet "
            f"met WBGT of UTCI maar met de onderliggende metingen (temperatuur, vocht, wind, "
            f"zon); de indices staan hier ter vergelijking.")
    _figuur(doc, plots.get("weer"), "Figuur 1. Weer langs het tijdvenster van je loop (stadsklimaat meegerekend).")

    # ------------------------------------------------------------ temperatuur
    doc.add_heading("4. Je kerntemperatuur", level=1)
    _p(doc, f"Het lichaamsmodel JOS-3 berekent per 10 minuten je rectale temperatuur uit je "
            f"warmteproductie en het weer. Voor sport is JOS-3 goed gevalideerd (gemiddeld "
            f"ongeveer 0,2 °C te hoog). Na de finish rekent het model nog 10 minuten door: "
            f"de temperatuur stijgt dan eerst nog, omdat je lichaam nawarmte afgeeft terwijl "
            f"de rijwind wegvalt.")
    _p(doc, f"Piek tijdens de loop: {nl(tm['med'])} °C (95% van de runs tussen {nl(tm['lo'])} en "
            f"{nl(tm['hi'])} °C). Piek inclusief de eerste 10 minuten na de finish: "
            f"{nl(s['t_rect_max_pf']['med'])} °C (tot {nl(s['t_rect_max_pf']['hi'])} °C).")
    _figuur(doc, plots.get("kerntemperatuur"),
            "Figuur 2. Rectale temperatuur. De band toont 95% van je runs; de stippellijn markeert de finish.")
    _figuur(doc, plots.get("verdeling"),
            "Figuur 3. Hoe de piektemperatuur en de laagste hartreserve over je runs verdeeld zijn.")

    # ------------------------------------------------------------ hart
    doc.add_heading("5. Je hart en bloedsomloop", level=1)
    _p(doc, "Je hart moet tegelijk je spieren van bloed voorzien en warmte naar je huid "
            "brengen. De hartreserve is wat het hart daarbovenop nog kan pompen. Het CVR-model "
            "(Lloyd e.a. 2022) berekent die uit je VO2max, leeftijd, kerntemperatuur, "
            "huidtemperatuur en vochtverlies. Het model is gevalideerd op hartslag. Zolang de "
            "reserve boven nul blijft is het resultaat goed onderbouwd; de waarde onder nul is "
            "een doorgetrokken lijn die nog niet gevalideerd is.")
    _figuur(doc, plots.get("hartreserve"),
            "Figuur 4. Hartreserve. Onder 2 L/min is er weinig marge voor een extra inspanning; "
            "onder 0 vraagt het lichaam meer dan het hart kan leveren.")
    _p(doc, "De voorspelde hartslag kun je na de loop naast de gegevens van je sporthorloge "
            "leggen. Een hartslag die lange tijd tegen je maximum blijft hangen, past bij een "
            "hartreserve rond nul.")
    _figuur(doc, plots.get("hartslag"), "Figuur 5. Voorspelde hartslag.")

    # ------------------------------------------------------------ vocht en tempo
    doc.add_heading("6. Vocht en tempo", level=1)
    _p(doc, f"Vochtverlies aan het eind: {nl(s['dehyd']['med'])}% van je gewicht "
            f"(95% van de runs tot {nl(s['dehyd']['hi'])}%). Weeg jezelf voor en na de loop "
            f"(zonder kleding, na plassen) om dit te controleren; 1 kg is ongeveer 1 liter.")
    _figuur(doc, plots.get("vocht"), "Figuur 6. Vochtverlies tijdens de loop.")
    _p(doc, "Het model laat je vanzelf langzamer lopen als je kerntemperatuur boven 38,5 °C "
            "komt of je hartreserve onder 2 L/min zakt, zoals lopers dat in de praktijk ook doen. "
            "Hoe sterk iemand dat doet verschilt per persoon; die spreiding zit in de band.")
    _figuur(doc, plots.get("tempo"), "Figuur 7. Tempo volgens het model.")
    if s["f_gestopt"]["k"]:
        _p(doc, f"In {_frac_tekst(s['f_gestopt'])} stop je in het model voor de finish omdat "
                f"de ervaren inspanning te hoog wordt.")

    # ------------------------------------------------------------ gecombineerd
    doc.add_heading("7. Hitte en hart samen", level=1)
    _p(doc, "Een hoge kerntemperatuur alleen is nog geen hitteberoerte, en een hart dat op zijn "
            "maximum werkt evenmin. Gevaarlijk wordt het als beide tegelijk gebeuren: dan kan "
            "het lichaam de warmte niet meer kwijt omdat er geen bloed over is om die naar de huid "
            "te brengen. Het fasediagram laat zien welke route je runs door dit vlak nemen.")
    _figuur(doc, plots.get("fasediagram"),
            "Figuur 8. Kerntemperatuur tegen hartreserve voor enkele representatieve runs.")
    p_ = s["p_collapse"]
    rijen = [["Maat", "Uitkomst", "Toelichting"],
             ["Roberts-dosis (hitte boven 40,5 °C)",
              f"mediaan {nl(s['roberts']['med'])}, ongunstig {nl(s['roberts']['hi'])} °C·min; "
              f"boven {AUC_ROBERTS_GRENS:.0f}: {_frac_tekst(s['f_roberts'])}",
              "Klinische grens 60 °C·min (Roberts 2007/2010)"],
             ["Gelijktijdig ≥ 40,5 °C en reserve op",
              _frac_tekst(s["f_conjunctie"]),
              f"Waarvan in het model hersteld: {s['f_hersteld']}"],
             ["TCF-dosis (hitte × tekort × tijd)",
              f"ongunstig {nl(s['tcf']['hi'])} °C·L; ≥ {TCF_CFG.relevant_dose:g}: "
              f"{_frac_tekst(s['f_tcf_relevant'])}",
              "Klassen 5/20/60 zijn niet gevalideerd"],
             ["Hitte-uitputting (EHE: > 39,5 °C en reserve < 0)",
              _frac_tekst(s["f_ehe"]), "Signaal, niet gekalibreerd"],
             ["Collaps na de finish (EAC)", _frac_tekst(s["f_eac"]), "Signaal, niet gekalibreerd"],
             ["Collapsekans (model)",
              f"{_per1000(p_['mean'])} per 1000 lopers zoals jij "
              f"(runs: {_per1000(p_['lo'])}–{_per1000(p_['hi'])})",
              "Voorlopig, zie hoofdstuk 10"]]
    _tabel(doc, rijen, breedtes=[5.2, 6.3, 5.0], pt=11)

    # ------------------------------------------------------------ wat als
    if r.gevoeligheid is not None:
        doc.add_heading("8. Wat als je langzamer loopt?", level=1)
        g = r.gevoeligheid
        _p(doc, "Langzamer lopen betekent minder warmteproductie, maar ook langer in de zon. "
                "Het model rekent beide mee. Hieronder dezelfde berekening bij een tempo dat 30 en "
                "60 seconden per kilometer langzamer is (met een kleiner aantal runs). "
                "Kijk vooral naar temperatuur en hartreserve. De collapsekans in de laatste kolom "
                "wordt bepaald door enkele runs in de staart en springt daardoor heen en weer; "
                "kleine verschillen daarin betekenen niets.")
        rijen = [["Tempo", "Looptijd", "Piektemp. mediaan (10% ongunstig)",
                  "Laagste reserve mediaan (10% ongunstig)", "Vochtverlies", "Collapsekans per 1000"]]
        for _, rr in g.iterrows():
            rijen.append([f"{rr['tempo']} min/km" + (" *" if rr.get("begrensd", False) else ""),
                          _uur(rr["duur_min"]),
                          f"{nl(rr['t_rect_max_med'])} ({nl(rr['t_rect_max_p90'])}) \u00b0C",
                          f"{nl(rr['co_min_med'])} ({nl(rr['co_min_p10'])}) L/min",
                          f"{nl(rr['dehyd_med'])}%", _per1000(rr["p_collapse_mean"])])
        _tabel(doc, rijen, pt=11)
        if "begrensd" in g.columns and g["begrensd"].any():
            _p(doc, "* Dit tempo vraagt meer dan 95% van je VO2max. Het model begrenst dan op "
                    "95%, waardoor deze rijen hetzelfde gesimuleerde tempo hebben en weinig "
                    "van elkaar verschillen.", cursief=True, pt=12)
        _figuur(doc, plots.get("tempo_watals"),
                "Figuur 9. Effect van een langzamer tempo. Staaf = mediaan; streepje = grens van de 10% "
                "ongunstigste runs.")

    # ------------------------------------------------------------ niet gemodelleerd
    doc.add_heading("9. Wat het model niet meeneemt", level=1)
    opgegeven = [k for k in NIET_GEMODELLEERD if getattr(inv, k)]
    if opgegeven:
        _p(doc, "Je hebt het volgende opgegeven. Dit zit niet in de berekening, maar is wel van "
                "belang:", vet=True)
        for k in opgegeven:
            titel, uitleg = NIET_GEMODELLEERD[k]
            doc.add_paragraph(f"{titel}. {uitleg}", style="List Bullet")
    else:
        _p(doc, "Je hebt geen van de onderstaande risicofactoren opgegeven. Ter informatie, het "
                "model neemt ze niet mee:")
    _bullets(doc, [NIET_GEMODELLEERD[k][0] for k in NIET_GEMODELLEERD if k not in opgegeven])
    _p(doc, "Verder: een opwarming voor de start, het tempo van een eindsprint, de kleur van je "
            "kleding, schaduw langs het parcours en drukte rond de start zitten niet in het model.")

    # ------------------------------------------------------------ beperkingen
    doc.add_heading("10. Wat het model wel en niet kan", level=1)
    _bullets(doc, [
        f"De band in de figuren bestaat uit {s['n']} runs van jou, steeds met andere aannames "
        f"over wat niemand vooraf weet: hoe sterk je vertraagt, de windrichting, je zweetsnelheid "
        f"en het lokale microklimaat. Het is geen vergelijking met andere lopers.",
        "Kerntemperatuur en huidtemperatuur (JOS-3) en de hartslag uit het CVR-model zijn "
        "gevalideerd. De hartreserve onder nul, de TCF-klassen en de EHE/EAC-criteria zijn dat nog niet.",
        f"De collapsekans gebruikt een voorlopige kalibratie ({COLLAPSE_ENDPOINTS[ACTIVE_ENDPOINT]['label']}), "
        f"gemaakt op gesimuleerde populaties met de CVR-module van voor 4 oktober 2026. Die moet "
        f"opnieuw gekalibreerd worden. Lees het getal als orde van grootte voor 1000 lopers "
        f"zoals jij, niet als jouw persoonlijke kans.",
        "Het model rekent op tijd, niet op afstand: het simuleert de geplande looptijd. Als je "
        "door vertraging later finisht, is de extra tijd in de warmte niet meegerekend.",
        "Na de finish rekent het model 10 minuten door met een vaste nawarmte. Hoe groot die "
        "nawarmte werkelijk is, is een open vraag in de suite.",
        "Het model gaat uit van een gezond lichaam, normaal uitgerust en goed gehydrateerd aan de start.",
    ])

    # ------------------------------------------------------------ bijlage
    doc.add_heading("Bijlage: kerngetallen", level=1)
    d = r.per_run
    rijen = [["Maat", "Mediaan", "2,5%", "97,5%"]]
    for kol, naam, dec in (("t_rect_max_race", "Piek T_rect loop (°C)", 2),
                           ("t_rect_max", "Piek T_rect incl. na finish (°C)", 2),
                           ("co_reserve_min", "Laagste CO-reserve (L/min)", 2),
                           ("hr_piek", "Hoogste hartslag (/min)", 0),
                           ("dehydratie_eind_pct", "Vochtverlies eind (%)", 2),
                           ("tempo_daling_pct", "Daling inspanning (%)", 1),
                           ("finish_min_geschat", "Geschatte finishtijd (min)", 0),
                           ("roberts_auc", "Roberts-dosis (°C·min)", 1),
                           ("tcf_dosis", "TCF-dosis (°C·L)", 2),
                           ("ehe_dosis", "EHE-dosis (L)", 2),
                           ("p_collapse", "Collapsekans (fractie)", 5)):
        v = d[kol].astype(float)
        rijen.append([naam] + [nl(float(np.nanpercentile(v, q)), dec) for q in (50, 2.5, 97.5)])
    _tabel(doc, rijen, pt=11)
    _p(doc, f"Ensemble: {s['n']} runs, seed {r.seed}. Locatie {nl(r.lat, 3)}, {nl(r.lon, 3)}. "
            f"Training factor {nl(af.training_factor)}. Alle getallen per run staan in het "
            f"bijbehorende Excel-bestand.", pt=12)

    pad = Path(pad)
    doc.save(pad)
    return pad


if __name__ == "__main__":
    print(f"{__file__} is een hulpmodule; start het programma met run_loper.py.")
