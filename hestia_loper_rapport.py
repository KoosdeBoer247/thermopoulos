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

from taal import vt, getal, datum

KLEUR_WOORD = {"groen": vt("groen", "green"), "geel": vt("geel", "yellow"),
               "oranje": vt("oranje", "orange"), "rood": vt("rood", "red")}


def _geslacht(g):
    return {"man": "male", "vrouw": "female"}.get(g, g)


def _kleding(k):
    return {"licht": "light (singlet, shorts)", "normaal": "normal (T-shirt, shorts)",
            "lang": "long (long sleeves and/or trousers)"}.get(k, k)

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
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
    return f"{x * 100:.0f}%" if x >= 0.01 or x == 0 else f"{x * 100:.1f}%".replace(".", vt(",", "."))


def _frac_tekst(f):
    return (vt(f"{_pct(f['frac'])} ({f['k']} van {f['n']} runs; 95%-interval "
            f"{_pct(f['lo'])}–{_pct(f['hi'])})",
               f"{_pct(f['frac'])} ({f['k']} of {f['n']} runs; 95% interval "
            f"{_pct(f['lo'])}–{_pct(f['hi'])})"))


def _uur(minuten):
    """Duur in minuten -> 'u:mm'."""
    totaal = int(round(minuten))
    return f"{totaal // 60}:{totaal % 60:02d}"


def _km(x):
    return f"{x:g}".replace(".", vt(",", "."))


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
    doc.add_paragraph(vt(f"Persoonlijke hitte-analyse", f"Personal heat analysis"), style="Title")
    _p(doc, vt(f"{inv.evenement} – {_km(inv.afstand_km)} km – "
            f"{datetime.strptime(inv.datum, '%Y-%m-%d'):%d-%m-%Y}, start {inv.starttijd} – "
            f"{a.city_name}",
               f"{inv.evenement} – {_km(inv.afstand_km)} km – "
            f"{datum(datetime.strptime(inv.datum, '%Y-%m-%d'))}, start {inv.starttijd} – "
            f"{a.city_name}"), vet=True, pt=16)
    if inv.naam:
        _p(doc, vt(f"Voor: {inv.naam}", f"For: {inv.naam}"))
    _p(doc, vt(f"Gemaakt met HESTIA (Thermopoulos-suite) op {datetime.now():%d-%m-%Y %H:%M}. "
            f"Weerbron: {r.weer_sheet}.",
               f"Made with HESTIA (Thermopoulos suite) on {datum(datetime.now())} {datetime.now():%H:%M}. "
            f"Weather source: {r.weer_sheet}."), pt=12)
    # [2026-11-25] status on the first page (independent review, recommendation 1)
    _p(doc, vt("Onderzoekssoftware, niet gevalideerd. Dit rapport is een modelberekening, geen "
            "medisch advies en geen toestemming om te lopen. Het model kan zich vergissen. "
            "Luister tijdens de loop altijd naar je lichaam en naar de medische hulpverleners.",
               "Research software, not validated. This report is a model calculation, not "
            "medical advice and not a clearance to run. The model can be wrong. "
            "During the run, always listen to your body and to the medical staff."),
       cursief=True)

    # ------------------------------------------------------------ samenvatting
    doc.add_heading(vt("1. Samenvatting", "1. Summary"), level=1)
    t = doc.add_table(rows=1, cols=1)
    cel = t.cell(0, 0)
    _arcering(cel, SIGNAAL_KLEUR[sig["kleur"]])
    run = cel.paragraphs[0].add_run(f"{SIGNAAL_SYMBOOL[sig['kleur']]}  {SIGNAAL_TEKST[sig['kleur']]} "
                                    f"({KLEUR_WOORD.get(sig['kleur'], sig['kleur'])})")
    run.bold = True
    run.font.size = Pt(20)
    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF) if sig["kleur"] in ("rood", "oranje", "groen") else RGBColor(0, 0, 0)
    doc.add_paragraph()
    if af.pct_geklemd:
        par = _p(doc, vt("Belangrijk: je opgegeven tempo is hoger dan het model voor jou haalbaar "
                      "acht. De uitkomsten hieronder gelden voor een loper op de grens van zijn "
                      "vermogen en niet voor het tempo dat je opgaf. Zie 'Let op bij de invoer'.",
                         "Important: the pace you entered is higher than the model considers achievable "
                      "for you. The results below apply to a runner at the limit of their "
                      "capacity, not to the pace you entered. See 'Check your input'."),
                 vet=True)
        for run in par.runs:
            run.font.color.rgb = RGBColor(0xD0, 0x3B, 0x3B)
    _p(doc, vt("Waarom dit signaal:", "Why this signal:"), vet=True)
    _bullets(doc, sig["redenen"])

    _p(doc, vt("De belangrijkste uitkomsten:", "The main results:"), vet=True)
    tm, cm = s["t_rect_max"], s["co_min"]
    kern = [
        vt(f"Je kerntemperatuur loopt tijdens de loop op tot ongeveer {nl(tm['med'])} °C "
        f"(in de ongunstigste runs {nl(tm['hi'])} °C).",
           f"Your core temperature rises during the run to about {nl(tm['med'])} °C "
        f"(in the least favourable runs {nl(tm['hi'])} °C)."),
        vt(f"Je hart houdt een reserve over van minimaal ongeveer {nl(cm['med'])} L/min "
        f"(in de ongunstigste runs {nl(cm['lo'])} L/min). Onder 2 L/min is de marge klein, "
        f"onder 0 is de reserve op.",
           f"Your heart keeps a reserve of at least about {nl(cm['med'])} L/min "
        f"(in the least favourable runs {nl(cm['lo'])} L/min). Below 2 L/min the margin is small; "
        f"below 0 the reserve is used up."),
        vt(f"Je verliest naar verwachting {nl(s['dehyd']['med'])}% van je lichaamsgewicht aan vocht.", f"You are expected to lose {nl(s['dehyd']['med'])}% of your body mass as fluid."),
        vt(f"Je hartslag komt naar verwachting tot ongeveer {s['hr_piek']['med']:.0f} slagen/min "
        f"(je maximum in het model: {af.hr_max:.0f}).",
           f"Your heart rate is expected to reach about {s['hr_piek']['med']:.0f} beats/min "
        f"(your maximum in the model: {af.hr_max:.0f})."),
        (vt(f"Het model verwacht dat je tempo met ongeveer {nl(s['tempo_daling']['med'], 0)}% daalt; ", f"The model expects your pace to drop by about {nl(s['tempo_daling']['med'], 0)}%; ")
         if s['tempo_daling']['med'] >= 1 else vt("Het model verwacht nauwelijks vertraging; ", "The model expects hardly any slowing; "))
        + vt(f"geschatte finishtijd {_uur(s['finish']['med'])} (u:mm) "
        f"bij gepland {_uur(inv.duur_min)}.",
             f"estimated finish time {_uur(s['finish']['med'])} (h:mm) "
        f"against a planned {_uur(inv.duur_min)}."),
    ]
    _bullets(doc, kern)
    if af.waarschuwingen:
        _p(doc, vt("Let op bij de invoer:", "Check your input:"), vet=True)
        _bullets(doc, af.waarschuwingen)

    _p(doc, vt("Wat je kunt doen:", "What you can do:"), vet=True)
    advies = [
        vt("Drink volgens plan, bij voorkeur bij elke drankpost een paar slokken; niet "
        "veel meer drinken dan je zweet.",
           "Drink to plan, preferably a few sips at every drinks station; do not "
        "drink much more than you sweat."),
        vt("Begin rustiger dan je van plan was als het warm is; het model laat bij "
        "'Wat als je langzamer loopt' zien wat dat oplevert.",
           "Start slower than you planned if it is warm; the model shows what that "
        "gains under 'What if you run slower'."),
        vt("Zoek schaduw op en koel af met water over hoofd en nek waar dat kan.", "Seek shade and cool down with water over your head and neck where possible."),
        vt("Stop en vraag direct hulp bij verwardheid, wankelen, vreemd gedrag, hevige "
        "hoofdpijn, misselijkheid of als je je plotseling slecht voelt. Bij een "
        "hitteberoerte merk je dat zelf vaak niet; let ook op elkaar.",
           "Stop and ask for help at once if you notice confusion, unsteadiness, odd behaviour, "
        "severe headache, nausea, or if you suddenly feel unwell. With heat stroke you "
        "often do not notice it yourself; look out for each other."),
    ]
    if any(getattr(inv, k) for k in NIET_GEMODELLEERD):
        advies.insert(0, vt("Je hebt een of meer risicofactoren opgegeven die het model niet "
                         "meeneemt (hoofdstuk 9). Je werkelijke risico kan daardoor hoger zijn "
                         "dan hier berekend.",
                            "You entered one or more risk factors that the model does not "
                         "include (section 9). Your real risk may therefore be higher "
                         "than calculated here."))
    _bullets(doc, advies)

    # ------------------------------------------------------------ invoer
    doc.add_heading(vt("2. Jouw gegevens", "2. Your details"), level=1)
    rijen = [[vt("Gegeven", "Item"), vt("Waarde", "Value")],
             [vt("Lengte / gewicht", "Height / weight"), vt(f"{inv.lengte_cm:.0f} cm / {nl(inv.gewicht_kg)} kg", f"{inv.lengte_cm:.0f} cm / {nl(inv.gewicht_kg)} kg")],
             [vt("Leeftijd / geslacht", "Age / sex"), vt(f"{inv.leeftijd} jaar / {inv.geslacht}", f"{inv.leeftijd} years / {_geslacht(inv.geslacht)}")],
             [vt("Afstand / gepland tempo", "Distance / planned pace"), vt(f"{_km(inv.afstand_km)} km / {min_naar_tempo(inv.tempo)} min/km "
                                         f"(looptijd {_uur(inv.duur_min)})",
                                            f"{_km(inv.afstand_km)} km / {min_naar_tempo(inv.tempo)} min/km "
                                         f"(running time {_uur(inv.duur_min)})")],
             [vt("Trainingsomvang", "Training volume"), vt(f"{inv.trainingskm_per_week:g} km per week", f"{inv.trainingskm_per_week:g} km per week")],
             [vt("Hitte-gewend", "Heat-acclimatised"), vt("ja", "yes") if inv.hitte_geacclimatiseerd else vt("nee", "no")],
             [vt("Drinkt bij elke post", "Drinks at every station"), vt("ja", "yes") if inv.drinkt_bij_elke_post else vt("nee, pas bij dorst", "no, only when thirsty")],
             [vt("Pijnstillers (NSAID)", "Painkillers (NSAIDs)"), (vt("ja (geen effect op de berekende temperatuur; wel extra "
                                       "belasting voor darm en nieren en kans op een te laag "
                                       "natriumgehalte)",
                                          "yes (no effect on the calculated temperature, but extra "
                                       "strain on gut and kidneys and a risk of low "
                                       "blood sodium)")) if inv.nsaid_voor_of_tijdens else vt("nee", "no")],
             [vt("Kleding", "Clothing"), vt(f"{inv.kleding} (clo {nl(af.clo)})", f"{_kleding(inv.kleding)} (clo {nl(af.clo)})")]]
    _tabel(doc, rijen, breedtes=[6.5, 10])
    _p(doc, vt("Afgeleid door het model:", "Derived by the model:"), vet=True)
    rijen = [[vt("Grootheid", "Quantity"), vt("Waarde", "Value"), vt("Bron", "Source")],
             ["VO2max", vt(f"{nl(af.vo2max)} mL/kg/min", f"{nl(af.vo2max)} mL/kg/min"), af.vo2max_bron],
             [vt("Zuurstofvraag bij je tempo", "Oxygen demand at your pace"), vt(f"{nl(af.vo2_bij_tempo)} mL/kg/min "
                                            f"({_pct(af.vo2_bij_tempo / af.vo2max)} van VO2max)",
                                               f"{nl(af.vo2_bij_tempo)} mL/kg/min "
                                            f"({_pct(af.vo2_bij_tempo / af.vo2max)} of VO2max)"),
              "Daniels & Gilbert"],
             [vt("Inspanning", "Effort"), f"{nl(af.met_tempo)} MET", vt("1 MET = 3,5 mL/kg/min", "1 MET = 3.5 mL/kg/min")],
             [vt("Maximale hartslag", "Maximum heart rate"), f"{af.hr_max:.0f} /min", af.hr_max_bron],
             [vt("Rusthartslag", "Resting heart rate"), f"{af.hr_rust:.0f} /min" if af.hr_rust else vt("uit VO2max (Lloyd 2022)", "from VO2max (Lloyd 2022)"),
              vt("zelf opgegeven", "entered by you") if af.hr_rust else vt("modelvergelijking", "model equation")]]
    _tabel(doc, rijen, breedtes=[5, 5, 6.5])

    # ------------------------------------------------------------ weer
    doc.add_heading(vt("3. Het weer tijdens je loop", "3. The weather during your run"), level=1)
    m = a.meteo
    _p(doc, vt(f"Gemiddelde luchttemperatuur {nl(a.mean_t_air_c)} °C; WBGT van "
            f"{nl(np.nanmin(m['wbgt']))} tot {nl(np.nanmax(m['wbgt']))} °C; "
            f"stralingstemperatuur tot {nl(np.nanmax(m['mrt']))} °C. Het model rekent niet "
            f"met WBGT of UTCI maar met de onderliggende metingen (temperatuur, vocht, wind, "
            f"zon); de indices staan hier ter vergelijking.",
               f"Mean air temperature {nl(a.mean_t_air_c)} °C; WBGT from "
            f"{nl(np.nanmin(m['wbgt']))} to {nl(np.nanmax(m['wbgt']))} °C; "
            f"radiant temperature up to {nl(np.nanmax(m['mrt']))} °C. The model does not calculate "
            f"with WBGT or UTCI but with the underlying measurements (temperature, humidity, wind, "
            f"sun); the indices are shown here for comparison."))
    _figuur(doc, plots.get("weer"), vt("Figuur 1. Weer tijdens je loop: temperaturen (boven), vocht en wind "
            "(midden), zon en bewolking (onder); stadsklimaat meegerekend.",
                                       "Figure 1. Weather during your run: temperatures (top), humidity and wind "
            "(middle), sun and cloud (bottom); urban climate included."))
    # [2026-10-31] het weer over de hele dag en de meetwaarden in een tabel
    if plots.get("weer_dag"):
        _figuur(doc, plots.get("weer_dag"), vt("Figuur 1b. Het weer over de hele dag; de blauwe band is de loop.", "Figure 1b. The weather over the whole day; the blue band is the run."))
    from hestia_loper import weer_tabellen
    wl, wd = weer_tabellen(r)
    if wl is not None and len(wl):
        stap = max(1, int(round(len(wl) / 14)))
        sel = wl.iloc[::stap]
        if sel.index[-1] != wl.index[-1]:
            sel = pd.concat([sel, wl.iloc[[-1]]])
        kols = [c for c in (vt("Lucht (°C)", "Air (°C)"), vt("RV (%)", "RH (%)"), vt("Wind 1,5 m (m/s)", "Wind 1.5 m (m/s)"), vt("Zon (W/m²)", "Sun (W/m²)"), vt("Bewolking (%)", "Cloud cover (%)"),
                            vt("Natte bol (°C)", "Wet bulb (°C)"), "MRT (°C)", "WBGT (°C)", "UTCI (°C)") if c in sel]
        rijen = [[vt("Tijd", "Time")] + [k.replace(" (", "\n(") for k in kols]]
        for _, rw in sel.iterrows():
            rijen.append([f"{rw['tijd']:%H:%M}"] + [nl(float(rw[k]), 0 if k in (vt("Zon (W/m²)", "Sun (W/m²)"), vt("Bewolking (%)", "Cloud cover (%)"), vt("RV (%)", "RH (%)")) else 1)
                                                    for k in kols])
        _p(doc, vt("Tabel 1. Het weer tijdens de loop (uit het weerbestand, stadsklimaat meegerekend). "
                "Alle waarden per 10 minuten en per uur over de hele dag staan in het Excel-bestand "
                "(tabbladen Weer_loop en Weer_dag).",
                   "Table 1. The weather during the run (from the weather file, urban climate included). "
                "All values per 10 minutes, and per hour over the whole day, are in the Excel file "
                "(sheets Weer_loop and Weer_dag)."), cursief=True, pt=11)
        _tabel(doc, rijen, pt=9)
    k_lucht, k_zon = vt("Lucht (°C)", "Air (°C)"), vt("Zon (W/m²)", "Sun (W/m²)")
    if wd is not None and len(wd) and k_lucht in wd:
        t_lo, t_hi = nl(float(wd[k_lucht].min())), nl(float(wd[k_lucht].max()))
        _p(doc, vt(f"Over de hele dag: luchttemperatuur {t_lo} tot {t_hi} °C",
                   f"Over the whole day: air temperature {t_lo} to {t_hi} °C")
                + (vt(", WBGT tot ", ", WBGT up to ") + f"{nl(float(wd['WBGT (°C)'].max()))} °C" if "WBGT (°C)" in wd else "")
                + (vt(", zon tot ", ", sun up to ") + f"{nl(float(wd[k_zon].max()), 0)} W/m²" if k_zon in wd else "")
                + ".")

    # ------------------------------------------------------------ temperatuur
    doc.add_heading(vt("4. Je kerntemperatuur", "4. Your core temperature"), level=1)
    _p(doc, vt(f"Het lichaamsmodel JOS-3 berekent per 10 minuten je rectale temperatuur uit je "
            f"warmteproductie en het weer. JOS-3 is ontwikkeld en getoetst voor rust en lichte "
            f"activiteit. Voor hardlopen is het in deze suite alleen vergeleken met metingen van "
            f"tien lopers op één koele dag, en deels daarop aangepast; bij warm weer nog niet. "
            f"Bij koel weer kan de berekende kerntemperatuur enkele tienden te hoog uitvallen. Na de finish rekent het model nog 30 minuten door (uitlopen, staan, zitten): "
            f"de temperatuur stijgt dan eerst nog, omdat je lichaam nawarmte afgeeft terwijl "
            f"de rijwind wegvalt.",
               f"The body model JOS-3 calculates your rectal temperature every 10 minutes from your "
            f"heat production and the weather. JOS-3 was developed and tested for rest and light "
            f"activity. For running, this suite has only compared it with measurements of "
            f"ten runners on one cool day, and partly adjusted it to them; not yet in warm weather. "
            f"In cool weather the calculated core temperature may be a few tenths too high. After the finish the model calculates 30 more minutes (walking out, standing, sitting): "
            f"the temperature first keeps rising, because your body releases stored heat while "
            f"the air flow from running stops."))
    _p(doc, vt(f"Piek tijdens de loop: {nl(tm['med'])} °C (95% van de runs tussen {nl(tm['lo'])} en "
            f"{nl(tm['hi'])} °C). Piek inclusief de 30 minuten na de finish: "
            f"{nl(s['t_rect_max_pf']['med'])} °C (tot {nl(s['t_rect_max_pf']['hi'])} °C).",
               f"Peak during the run: {nl(tm['med'])} °C (95% of runs between {nl(tm['lo'])} and "
            f"{nl(tm['hi'])} °C). Peak including the 30 minutes after the finish: "
            f"{nl(s['t_rect_max_pf']['med'])} °C (up to {nl(s['t_rect_max_pf']['hi'])} °C)."))
    _figuur(doc, plots.get("kerntemperatuur"),
            vt("Figuur 2. Rectale temperatuur. De band toont 95% van je runs; de stippellijn markeert de finish.", "Figure 2. Rectal temperature. The band shows 95% of your runs; the dotted line marks the finish."))
    _figuur(doc, plots.get("verdeling"),
            vt("Figuur 3. Hoe de piektemperatuur en de laagste hartreserve over je runs verdeeld zijn.", "Figure 3. How the peak temperature and the lowest cardiac reserve are distributed over your runs."))

    # ------------------------------------------------------------ hart
    doc.add_heading(vt("5. Je hart en bloedsomloop", "5. Your heart and circulation"), level=1)
    _p(doc, vt("Je hart moet tegelijk je spieren van bloed voorzien en warmte naar je huid "
            "brengen. De hartreserve is wat het hart daarbovenop nog kan pompen. Het CVR-model "
            "(Lloyd e.a. 2022) berekent die uit je VO2max, leeftijd, kerntemperatuur, "
            "huidtemperatuur en vochtverlies. De hartslag is vergeleken met metingen van tien lopers "
            "op één koele dag. Zolang de reserve boven nul blijft, ligt het resultaat binnen het "
            "bereik van het gepubliceerde model; de waarde onder nul is een doorgetrokken lijn die "
            "niet met metingen is vergeleken.",
               "Your heart must supply your muscles with blood and carry heat to your skin at the "
            "same time. The cardiac reserve is what the heart can still pump on top of that. The CVR model "
            "(Lloyd et al. 2022) calculates it from your VO2max, age, core temperature, "
            "skin temperature and fluid loss. The heart rate has been compared with measurements of ten runners "
            "on one cool day. As long as the reserve stays above zero, the result lies within the "
            "range of the published model; the value below zero is an extrapolation that has "
            "not been compared with measurements."))
    _figuur(doc, plots.get("hartreserve"),
            vt("Figuur 4. Hartreserve. Onder 2 L/min is er weinig marge voor een extra inspanning; "
            "onder 0 vraagt het lichaam meer dan het hart kan leveren.",
               "Figure 4. Cardiac reserve. Below 2 L/min there is little margin for extra effort; "
            "below 0 the body asks more than the heart can deliver."))
    _p(doc, vt("De voorspelde hartslag kun je na de loop naast de gegevens van je sporthorloge "
            "leggen. Een hartslag die lange tijd tegen je maximum blijft hangen, past bij een "
            "hartreserve rond nul.",
               "After the run you can compare the predicted heart rate with the data from your sports "
            "watch. A heart rate that stays close to your maximum for a long time fits a "
            "cardiac reserve around zero."))
    _figuur(doc, plots.get("hartslag"), vt("Figuur 5. Voorspelde hartslag.", "Figure 5. Predicted heart rate."))

    # ------------------------------------------------------------ vocht en tempo
    doc.add_heading(vt("6. Vocht en tempo", "6. Fluid and pace"), level=1)
    _p(doc, vt(f"Vochtverlies aan het eind: {nl(s['dehyd']['med'])}% van je gewicht "
            f"(95% van de runs tot {nl(s['dehyd']['hi'])}%). Weeg jezelf voor en na de loop "
            f"(zonder kleding, na plassen) om dit te controleren; 1 kg is ongeveer 1 liter.",
               f"Fluid loss at the end: {nl(s['dehyd']['med'])}% of your body mass "
            f"(95% of runs up to {nl(s['dehyd']['hi'])}%). Weigh yourself before and after the run "
            f"(without clothes, after passing urine) to check this; 1 kg is about 1 litre."))
    _figuur(doc, plots.get("vocht"), vt("Figuur 6. Vochtverlies tijdens de loop.", "Figure 6. Fluid loss during the run."))
    _p(doc, vt("Het model laat je vanzelf langzamer lopen als je kerntemperatuur boven 38,5 °C "
            "komt of je hartreserve onder 2 L/min zakt, zoals lopers dat in de praktijk ook doen. "
            "Hoe sterk iemand dat doet verschilt per persoon; die spreiding zit in de band.",
               "The model makes you slow down by itself when your core temperature rises above 38.5 °C "
            "or your cardiac reserve drops below 2 L/min, as runners also do in practice. "
            "How strongly people do this differs; that spread is in the band."))
    _figuur(doc, plots.get("tempo"), vt("Figuur 7. Tempo volgens het model.", "Figure 7. Pace according to the model."))
    if s["f_gestopt"]["k"]:
        _p(doc, vt(f"In {_frac_tekst(s['f_gestopt'])} stop je in het model voor de finish omdat "
                f"de ervaren inspanning te hoog wordt.",
                   f"In {_frac_tekst(s['f_gestopt'])} you stop before the finish in the model because "
                f"the perceived effort becomes too high."))

    # ------------------------------------------------------------ gecombineerd
    doc.add_heading(vt("7. Hitte en hart samen", "7. Heat and heart together"), level=1)
    _p(doc, vt("Een hoge kerntemperatuur alleen is nog geen hitteberoerte, en een hart dat op zijn "
            "maximum werkt evenmin. Gevaarlijk wordt het als beide tegelijk gebeuren: dan kan "
            "het lichaam de warmte niet meer kwijt omdat er geen bloed over is om die naar de huid "
            "te brengen. Het fasediagram laat zien welke route je runs door dit vlak nemen.",
               "A high core temperature alone is not yet heat stroke, and neither is a heart working "
            "at its maximum. It becomes dangerous when both happen at once: then the "
            "body can no longer lose its heat because there is no blood left to carry it to the skin. "
            "The phase diagram shows which route your runs take through this plane."))
    _figuur(doc, plots.get("fasediagram"),
            vt("Figuur 8. Kerntemperatuur tegen hartreserve voor enkele representatieve runs.", "Figure 8. Core temperature against cardiac reserve for a few representative runs."))
    p_ = s["p_collapse"]
    rijen = [[vt("Maat", "Measure"), vt("Uitkomst", "Result"), vt("Toelichting", "Explanation")],
             [vt("Roberts-dosis (hitte boven 40,5 °C)", "Roberts dose (heat above 40.5 °C)"),
              vt(f"mediaan {nl(s['roberts']['med'])}, ongunstig {nl(s['roberts']['hi'])} °C·min; "
              f"boven {AUC_ROBERTS_GRENS:.0f}: {_frac_tekst(s['f_roberts'])}",
                 f"median {nl(s['roberts']['med'])}, unfavourable {nl(s['roberts']['hi'])} °C·min; "
              f"above {AUC_ROBERTS_GRENS:.0f}: {_frac_tekst(s['f_roberts'])}"),
              vt("Klinische grens 60 °C·min (Roberts 2007/2010)", "Clinical limit 60 °C·min (Roberts 2007/2010)")],
             [vt("EHS-criterium tijdens de loop: > 40,5 °C én hartreserve op (≤ 0,05 L/min) op hetzelfde moment", "EHS criterion during the run: > 40.5 °C and cardiac reserve used up (≤ 0.05 L/min) at the same moment"),
              _frac_tekst(s["f_conjunctie"]),
              vt(f"Waarvan in het model hersteld: {s['f_hersteld']}", f"Of which recovered in the model: {s['f_hersteld']}")],
             [vt("TCF-dosis (hitte × tekort × tijd): > 40,5 °C én hartreserve onder 0 L/min; strenger dan het EHS-criterium (≤ 0,05 L/min)", "TCF dose (heat × deficit × time): > 40.5 °C and cardiac reserve below 0 L/min; stricter than the EHS criterion (≤ 0.05 L/min)"),
              vt(f"ongunstig {nl(s['tcf']['hi'])} °C·L; ≥ {TCF_CFG.relevant_dose:g}: "
              f"{_frac_tekst(s['f_tcf_relevant'])}",
                 f"unfavourable {nl(s['tcf']['hi'])} °C·L; ≥ {TCF_CFG.relevant_dose:g}: "
              f"{_frac_tekst(s['f_tcf_relevant'])}"),
              vt("Klassen 5/20/60 zijn niet gevalideerd", "Classes 5/20/60 are not validated")],
             [vt("EHE-criterium (hitte-uitputting): > 39,5 °C én hartreserve op (≤ 0,05 L/min), tijdens de loop", "EHE criterion (heat exhaustion): > 39.5 °C and cardiac reserve used up (≤ 0.05 L/min), during the run"),
              _frac_tekst(s["f_ehe"]), vt("Signaal, niet gekalibreerd", "Signal, not calibrated")],
             [vt("Collaps na de finish (EAC)", "Collapse after the finish (EAC)"), _frac_tekst(s["f_eac"]), vt("Voorlopig: gekalibreerd op één punt (1,5 per 1000), niet gevalideerd", "Provisional: calibrated on one point (1.5 per 1000), not validated")],
             [vt("Collapsekans (model)", "Collapse probability (model)"),
              vt(f"{_per1000(p_['mean'])} per 1000 lopers zoals jij "
              f"(runs: {_per1000(p_['lo'])}–{_per1000(p_['hi'])})",
                 f"{_per1000(p_['mean'])} per 1000 runners like you "
              f"(runs: {_per1000(p_['lo'])}–{_per1000(p_['hi'])})"),
              vt("Voorlopig, zie hoofdstuk 10", "Provisional, see section 10")]]
    _tabel(doc, rijen, breedtes=[5.2, 6.3, 5.0], pt=11)

    # ------------------------------------------------------------ wat als
    if r.gevoeligheid is not None:
        doc.add_heading(vt("8. Wat als je langzamer loopt?", "8. What if you run slower?"), level=1)
        g = r.gevoeligheid
        _p(doc, vt("Langzamer lopen betekent minder warmteproductie, maar ook langer in de zon. "
                "Het model rekent beide mee. Hieronder dezelfde berekening bij een tempo dat 30 en "
                "60 seconden per kilometer langzamer is (met een kleiner aantal runs). "
                "Kijk vooral naar temperatuur en hartreserve. De collapsekans in de laatste kolom "
                "wordt bepaald door enkele runs in de staart en springt daardoor heen en weer; "
                "kleine verschillen daarin betekenen niets.",
                   "Running slower means less heat production, but also longer in the sun. "
                "The model includes both. Below is the same calculation at a pace 30 and "
                "60 seconds per kilometre slower (with a smaller number of runs). "
                "Look mainly at temperature and cardiac reserve. The collapse probability in the last column "
                "is set by a few runs in the tail and therefore jumps around; "
                "small differences in it mean nothing."))
        rijen = [[vt("Tempo", "Pace"), vt("Looptijd", "Running time"), vt("Piektemp. mediaan (10% ongunstig)", "Peak temp. median (10% unfavourable)"),
                  vt("Laagste reserve mediaan (10% ongunstig)", "Lowest reserve median (10% unfavourable)"), vt("Vochtverlies", "Fluid loss"), vt("Collapsekans per 1000", "Collapse probability per 1000")]]
        for _, rr in g.iterrows():
            rijen.append([f"{rr['tempo']} min/km" + (" *" if rr.get("begrensd", False) else ""),
                          _uur(rr["duur_min"]),
                          f"{nl(rr['t_rect_max_med'])} ({nl(rr['t_rect_max_p90'])}) \u00b0C",
                          f"{nl(rr['co_min_med'])} ({nl(rr['co_min_p10'])}) L/min",
                          f"{nl(rr['dehyd_med'])}%", _per1000(rr["p_collapse_mean"])])
        _tabel(doc, rijen, pt=11)
        if "begrensd" in g.columns and g["begrensd"].any():
            _p(doc, vt("* Dit tempo vraagt meer dan 95% van je VO2max. Het model begrenst dan op "
                    "95%, waardoor deze rijen hetzelfde gesimuleerde tempo hebben en weinig "
                    "van elkaar verschillen.",
                       "* This pace asks more than 95% of your VO2max. The model then caps it at "
                    "95%, so these rows have the same simulated pace and differ little "
                    "from each other."), cursief=True, pt=12)
        _figuur(doc, plots.get("tempo_watals"),
                vt("Figuur 9. Effect van een langzamer tempo. Staaf = mediaan; streepje = grens van de 10% "
                "ongunstigste runs.",
                   "Figure 9. Effect of a slower pace. Bar = median; tick = limit of the 10% "
                "least favourable runs."))

    # ------------------------------------------------------------ niet gemodelleerd
    doc.add_heading(vt("9. Wat het model niet meeneemt", "9. What the model does not include"), level=1)
    opgegeven = [k for k in NIET_GEMODELLEERD if getattr(inv, k)]
    if opgegeven:
        _p(doc, vt("Je hebt het volgende opgegeven. Dit zit niet in de berekening, maar is wel van "
                "belang:",
                   "You entered the following. It is not in the calculation, but it does "
                "matter:"), vet=True)
        for k in opgegeven:
            titel, uitleg = NIET_GEMODELLEERD[k]
            doc.add_paragraph(f"{titel}. {uitleg}", style="List Bullet")
    else:
        _p(doc, vt("Je hebt geen van de onderstaande risicofactoren opgegeven. Ter informatie, het "
                "model neemt ze niet mee:",
                   "You did not enter any of the risk factors below. For information, the "
                "model does not include them:"))
    _bullets(doc, [NIET_GEMODELLEERD[k][0] for k in NIET_GEMODELLEERD if k not in opgegeven])
    _p(doc, vt("Verder: een opwarming voor de start, het tempo van een eindsprint, de kleur van je "
            "kleding, schaduw langs het parcours en drukte rond de start zitten niet in het model.",
               "Also not in the model: a warm-up before the start, the pace of a final sprint, the colour of your "
            "clothing, shade along the course and crowding at the start."))

    # ------------------------------------------------------------ beperkingen
    doc.add_heading(vt("10. Wat het model wel en niet kan", "10. What the model can and cannot do"), level=1)
    _bullets(doc, [
        vt(f"De band in de figuren bestaat uit {s['n']} runs van jou, steeds met andere aannames "
        f"over wat niemand vooraf weet: hoe sterk je vertraagt, de windrichting, je zweetsnelheid "
        f"en het lokale microklimaat. Het is geen vergelijking met andere lopers.",
           f"The band in the figures consists of {s['n']} runs of you, each with different assumptions "
        f"about what nobody knows in advance: how strongly you slow down, the wind direction, your sweat rate "
        f"and the local microclimate. It is not a comparison with other runners."),
        vt("Geen van de uitkomsten is onafhankelijk gevalideerd. Kerntemperatuur, hartslag en "
        "vochtverlies zijn vergeleken met metingen van tien lopers op één koele dag; het model is "
        "daarna deels op die metingen aangepast. De hartreserve onder nul, de TCF-klassen en de "
        "EHE/EAC-criteria zijn niet met metingen vergeleken.",
           "None of the results is independently validated. Core temperature, heart rate and "
        "fluid loss have been compared with measurements of ten runners on one cool day; the model was "
        "then partly adjusted to those measurements. The cardiac reserve below zero, the TCF classes and the "
        "EHE/EAC criteria have not been compared with measurements."),
        vt(f"De collapsekans gebruikt een voorlopige kalibratie ({COLLAPSE_ENDPOINTS[ACTIVE_ENDPOINT]['label']}): "
        f"alleen het basisniveau is afgesteld op één referentie-evenement; hoe de kans meestijgt "
        f"met kerntemperatuur, hartreserve en uitdroging is een expertoordeel en niet getoetst. "
        f"Lees het getal als orde van grootte voor 1000 lopers zoals jij, niet als jouw "
        f"persoonlijke kans.",
           f"The collapse probability uses a provisional calibration ({COLLAPSE_ENDPOINTS[ACTIVE_ENDPOINT]['label']}): "
        f"only the base level is set on one reference event; how the probability rises "
        f"with core temperature, cardiac reserve and dehydration is expert judgement and untested. "
        f"Read the number as an order of magnitude for 1000 runners like you, not as your "
        f"personal probability."),
        vt("Het model rekent op tijd, niet op afstand: het simuleert de geplande looptijd. Als je "
        "door vertraging later finisht, is de extra tijd in de warmte niet meegerekend.",
           "The model calculates on time, not distance: it simulates the planned running time. If you "
        "finish later because you slowed down, the extra time in the heat is not included."),
        vt("Na de finish rekent het model 30 minuten door met een vaste nawarmte. Hoe groot die "
        "nawarmte werkelijk is, is een open vraag in de suite.",
           "After the finish the model calculates 30 more minutes with a fixed after-heat. How large that "
        "after-heat really is, is an open question in the suite."),
        vt("Het model gaat uit van een gezond lichaam, normaal uitgerust en goed gehydrateerd aan de start.", "The model assumes a healthy body, normally rested and well hydrated at the start."),
    ])

    # ------------------------------------------------------------ [2026-10-31] alle grafieken
    if any(plots.get(k) for k in ("dashboard", "alle_runs", "uitkomsten", "samenhang")):
        doc.add_heading(vt("Bijlage: alle gegevens in grafieken", "Appendix: all data in charts"), level=1)
        _p(doc, vt("Deze bijlage laat zoveel mogelijk van de berekening zien. Blauw is steeds de mediaan "
                f"met de band waarin 95 % van de {s['n']} runs valt; de stippellijnen zijn dezelfde "
                "grenzen als in de rest van het rapport.",
                   "This appendix shows as much of the calculation as possible. Blue is always the median "
                f"with the band containing 95 % of the {s['n']} runs; the dotted lines are the same "
                "limits as in the rest of the report."))
        for k, onder in (("dashboard", vt("Figuur B1. Alle modelwaarden in de tijd, met de WBGT (oranje) als achtergrond.", "Figure B1. All model values over time, with the WBGT (orange) as background.")),
                         ("alle_runs", vt("Figuur B2. Elke afzonderlijke run als dunne lijn: zo is te zien hoe ver de runs uiteenlopen.", "Figure B2. Each separate run as a thin line: this shows how far the runs diverge.")),
                         ("uitkomsten", vt("Figuur B3. Verdeling van de belangrijkste uitkomsten over alle runs.", "Figure B3. Distribution of the main results over all runs.")),
                         ("samenhang", vt("Figuur B4. Per run de hoogste kerntemperatuur tegen de laagste hartreserve.", "Figure B4. Per run the highest core temperature against the lowest cardiac reserve."))):
            if plots.get(k):
                _figuur(doc, plots.get(k), onder)

    # ------------------------------------------------------------ bijlage
    doc.add_heading(vt("Bijlage: kerngetallen", "Appendix: key figures"), level=1)
    d = r.per_run
    rijen = [[vt("Maat", "Measure"), vt("Mediaan", "Median"), "2,5%", "97,5%"]]
    for kol, naam, dec in (("t_rect_max_race", vt("Piek T_rect loop (°C)", "Peak T_rect run (°C)"), 2),
                           ("t_rect_max", vt("Piek T_rect incl. na finish (°C)", "Peak T_rect incl. after finish (°C)"), 2),
                           ("co_reserve_min", vt("Laagste CO-reserve (L/min)", "Lowest CO reserve (L/min)"), 2),
                           ("hr_piek", vt("Hoogste hartslag (/min)", "Highest heart rate (/min)"), 0),
                           ("dehydratie_eind_pct", vt("Vochtverlies eind (%)", "Fluid loss at end (%)"), 2),
                           ("tempo_daling_pct", vt("Daling inspanning (%)", "Drop in effort (%)"), 1),
                           ("finish_min_geschat", vt("Geschatte finishtijd (min)", "Estimated finish time (min)"), 0),
                           ("roberts_auc", vt("Roberts-dosis (°C·min)", "Roberts dose (°C·min)"), 1),
                           ("tcf_dosis", vt("TCF-dosis (°C·L)", "TCF dose (°C·L)"), 2),
                           ("ehe_dosis", vt("EHE-dosis (L)", "EHE dose (L)"), 2),
                           ("p_collapse", vt("Collapsekans (fractie)", "Collapse probability (fraction)"), 5)):
        v = d[kol].astype(float)
        rijen.append([naam] + [nl(float(np.nanpercentile(v, q)), dec) for q in (50, 2.5, 97.5)])
    _tabel(doc, rijen, pt=11)
    _p(doc, vt(f"Ensemble: {s['n']} runs, seed {r.seed}. Locatie {nl(r.lat, 3)}, {nl(r.lon, 3)}. "
            f"Training factor {nl(af.training_factor)}. Alle getallen per run staan in het "
            f"bijbehorende Excel-bestand.",
               f"Ensemble: {s['n']} runs, seed {r.seed}. Location {nl(r.lat, 3)}, {nl(r.lon, 3)}. "
            f"Training factor {nl(af.training_factor)}. All numbers per run are in the "
            f"accompanying Excel file."), pt=12)

    pad = Path(pad)
    doc.save(pad)
    return pad


if __name__ == "__main__":
    print(f"{__file__} is een hulpmodule; start het programma met run_loper.py.")
