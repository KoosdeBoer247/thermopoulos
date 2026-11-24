# -*- coding: utf-8 -*-
"""
hestia_werk_rapport.py
======================
Word-rapport voor HESTIA-werk (buitenwerkers over een werkdag). Gebruikt de
opmaak van hestia_loper_rapport (stijl, tabellen, figuren) en uitsluitend de
uitkomst van hestia_werk.afronden().

Status: research software. Niet voor operationele beslissingen.
"""
from __future__ import annotations

from taal import datum, vt, getal

import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from docx import Document

import hestia_werk as hw
from hestia_loper_rapport import _bullets, _figuur, _p, _stijl, _tabel


def nl(x, d=1):
    return getal(x, d)


def _fi(f):
    return vt(f"{f['point']:.0%} ({f['k']} van {f['n']}; 95%: {f['lo']:.0%}–{f['hi']:.0%})", f"{f['point']:.0%} ({f['k']} of {f['n']}; 95%: {f['lo']:.0%}–{f['hi']:.0%})")


def _figuren(r: dict, map_: Path) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    s = r["samen"]
    tijden = [pd.Timestamp(x["time"]).tz_localize(None) for x in r["interp"]]
    sporen = r["sporen"]
    uit = {}

    def rust(ax):
        f = r["fase"]
        for i in range(1, len(f)):
            if f[i] != "werk":
                ax.axvspan(tijden[i - 1], tijden[i], color="#dddddd", alpha=0.5, lw=0, zorder=0)

    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=130)
    ax.fill_between(tijden, s["p5"], s["p95"], color="#1f5fa8", alpha=0.18, lw=0, label="p5–p95")
    ax.plot(tijden, s["gem"], color="#1f5fa8", lw=2, label=vt("groepsgemiddelde (HESTIA)", "group mean (HESTIA)"))
    ax.plot(tijden, r["phs"]["t_re"], color="#27ae60", lw=1.6, ls="--", label="ISO 7933 PHS")
    ax.axhline(38.0, color="#e67e22", ls=":", lw=1.2, label=vt("38,0 °C", "38.0 °C"))
    ax.axhline(38.5, color="#c0392b", ls=":", lw=1.2, label=vt("38,5 °C", "38.5 °C"))
    rust(ax)
    ax.set_ylabel(vt("kerntemperatuur (°C)", "core temperature (°C)"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    uit["kern"] = map_ / "kern.png"
    fig.savefig(uit["kern"])
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 3.6), dpi=130)
    u = s["uren"]
    x = np.arange(len(u))
    ax.bar(x - 0.2, [v["wbgt_twa"] for v in u], width=0.4, color="#e67e22", label=vt("WBGT tijdgewogen", "WBGT time-weighted"))
    ax.bar(x + 0.2, [v["grens"] for v in u], width=0.4, color="#7f8c8d", label=vt("ISO 7243-grens", "ISO 7243 limit"))
    ax.set_xticks(x, [v["uur"].strftime("%H:00") for v in u])
    ax.set_ylabel("°C")
    ax.grid(alpha=0.3, axis="y")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    uit["wbgt"] = map_ / "wbgt.png"
    fig.savefig(uit["wbgt"])
    plt.close(fig)
    return uit


def maak_rapport(r: dict, weer_label: str, pad, profiel_tekst: str = "") -> Path:
    inv = r["invoer"]
    s = r["samen"]
    sch = inv.schema
    doc = Document()
    _stijl(doc)
    doc.add_heading(vt("HESTIA-werk: hittebelasting van buitenwerkers", "HESTIA work: heat strain of outdoor workers"), 0)
    _p(doc, f"{inv.werk_label} · {inv.plaats} · {inv.datum} · {sch.begin}–{sch.einde}", vet=True)
    _p(doc, vt(f"Gemaakt {datetime.now():%d-%m-%Y %H:%M}. Research software, niet voor operationele beslissingen.", f"Made {datum(datetime.now())} {datetime.now():%H:%M}. Research software, not for operational decisions."),
       cursief=True, pt=11)

    doc.add_heading(vt("Uitkomst", "Result"), 1)
    g = s["grens_hoofd"]
    boven = s["gem_max"] >= g
    _p(doc, vt(f"De gemiddelde kerntemperatuur van de groep komt maximaal op {nl(s['gem_max'], 2)} °C. De grens voor "
            f"deze groep is {nl(g)} °C; die wordt {'overschreden' if boven else 'niet overschreden'}.",
               f"The mean core temperature of the group reaches at most {nl(s['gem_max'], 2)} °C. The limit for "
            f"this group is {nl(g)} °C; it is {'exceeded' if boven else 'not exceeded'}."), vet=True)
    tijd = lambda x: x.strftime("%H:%M") if x is not None else vt("niet bereikt", "not reached")   # noqa: E731
    _tabel(doc, [
        [vt("Maat", "Measure"), vt("Uitkomst", "Result"), vt("Grens (bron)", "Limit (source)")],
        [vt("Groepsgemiddelde kerntemperatuur, maximum", "Group-mean core temperature, maximum"), f"{nl(s['gem_max'], 2)} °C",
         vt("38,0 °C niet geacclimatiseerd; 38,5 °C geacclimatiseerd (ACGIH)", "38.0 °C not acclimatised; 38.5 °C acclimatised (ACGIH)")],
        [vt("Tijdstip groepsgemiddelde ≥ 38,0 / 38,5 °C", "Time group mean ≥ 38.0 / 38.5 °C"), f"{tijd(s['gem_tijd_380'])} / {tijd(s['gem_tijd_385'])}", ""],
        [vt("Werkers ooit ≥ 38,0 °C", "Workers ever ≥ 38.0 °C"), _fi(s["fi_380"]), vt("aanvullend, geen grenswaarde", "additional, not a limit value")],
        [vt("Werkers ooit ≥ 38,5 °C", "Workers ever ≥ 38.5 °C"), _fi(s["fi_385"]), vt("aanvullend, geen grenswaarde", "additional, not a limit value")],
        [vt(f"Werkers boven {nl(s['t_kritiek'], 0)} °C (model buiten getoetst gebied)", f"Workers above {nl(s['t_kritiek'], 0)} °C (model outside its tested range)"), _fi(s["fi_42"]),
         vt("geen voorspelling; het model laat niemand stoppen", "not a prediction; the model lets nobody stop")],
        [vt("Netto vochtverlies ≥ 1,5 %", "Net fluid loss ≥ 1.5 %"), _fi(s["fi_dehyd"]), vt("1,5 % (ACGIH)", "1.5 % (ACGIH)")],
        [vt("Hartslag, daggemiddelde", "Heart rate, day mean"), f"{nl(s['hr_dag_gem'], 0)}/min", vt("ongeveer 110/min (NIOSH 2016)", "about 110/min (NIOSH 2016)")],
        [vt("Hartslag > 180 − leeftijd (≥ 5 min)", "Heart rate > 180 − age (≥ 5 min)"), _fi(s["fi_hr"]), "ACGIH"],
        [vt("Uren WBGT boven ISO 7243", "Hours WBGT above ISO 7243"), vt(f"{sum(u['boven'] for u in s['uren'])} van {len(s['uren'])}", f"{sum(u['boven'] for u in s['uren'])} of {len(s['uren'])}"),
         vt("ISO 7243 via Gezondheidsraad 2011", "ISO 7243 via the Health Council of the Netherlands 2011")],
    ], breedtes=[6.0, 5.0, 6.0], pt=11)
    _p(doc, vt("De Gezondheidsraad (2011) bedoelt de grens van 38 °C voor het gemiddelde van een groep, niet voor één "
            "persoon: de kerntemperatuur schommelt over de dag en fitte mensen gaan er zonder klachten overheen. "
            "Het aandeel werkers boven een grens is daarom een aanvullende modeluitkomst.",
               "The Health Council of the Netherlands (2011) intends the 38 °C limit for the mean of a group, not for one "
            "person: core temperature varies over the day and fit people exceed it without complaints. "
            "The share of workers above a limit is therefore an additional model outcome."))

    with tempfile.TemporaryDirectory() as tmp:
        fig = _figuren(r, Path(tmp))
        _figuur(doc, fig["kern"], vt("Kerntemperatuur over de werkdag: groepsgemiddelde met p5–p95 (HESTIA) en de "
                                  "gemiddelde werker volgens ISO 7933 (PHS). Grijs: rust en pauze.",
                                     "Core temperature over the working day: group mean with p5–p95 (HESTIA) and the "
                                  "average worker according to ISO 7933 (PHS). Grey: rest and breaks."))
        _figuur(doc, fig["wbgt"], vt("WBGT per klokuur (tijdgewogen over werk en rust, met kledingcorrectie) tegen "
                                  "de ISO 7243-grens bij de gemiddelde stofwisseling van dat uur.",
                                     "WBGT per clock hour (time-weighted over work and rest, with clothing correction) against "
                                  "the ISO 7243 limit at the mean metabolic rate of that hour."))

        doc.add_heading(vt("Opzet", "Set-up"), 1)
        _tabel(doc, [
            [vt("Onderdeel", "Part"), vt("Invoer", "Input")],
            [vt("Werk", "Work"), vt(f"{inv.werk_label}; werk-MET {nl(inv.werk_met)} ({nl(hw.w_m2_uit_met(inv.werk_met), 0)} W/m²)", f"{inv.werk_label}; work MET {nl(inv.werk_met)} ({nl(hw.w_m2_uit_met(inv.werk_met), 0)} W/m²)")],
            [vt("Werkdag", "Working day"), vt(f"{sch.begin}–{sch.einde}; cyclus {sch.werk_min} min werk / {sch.rust_min} min rust", f"{sch.begin}–{sch.einde}; cycle {sch.werk_min} min work / {sch.rust_min} min rest")],
            [vt("Pauzes", "Breaks"), ", ".join(f"{a} ({d} min)" for a, d in sch.pauzes) or vt("geen", "none")],
            [vt("Rust", "Rest"), vt(f"rust-MET {nl(sch.rust_met)}; {'in de schaduw' if sch.schaduw else 'op de werkplek'}", f"rest MET {nl(sch.rust_met)}; {'in the shade' if sch.schaduw else 'at the workplace'}")],
            [vt("Kleding", "Clothing"), f"{hw.KLEDING[inv.kleding][0]} ({nl(hw.KLEDING[inv.kleding][1])} clo)"],
            [vt("Werkers", "Workers"), vt(f"n = {r['n']}; aandeel mannen {nl(inv.man_aandeel, 2)}; {profiel_tekst}", f"n = {r['n']}; share of men {nl(inv.man_aandeel, 2)}; {profiel_tekst}")],
            [vt("Weer", "Weather"), weer_label],
        ], breedtes=[4.0, 13.0], pt=11)

        doc.add_heading(vt("Werkwijze", "Method"), 1)
        _bullets(doc, [
            vt("Groep werkers: leeftijd 18–67 jaar uit de CBS-verdeling van de werkzame beroepsbevolking; lengte, BMI, "
            "vetpercentage en VO2max zoals de wandelaars in HESTIA.",
               "Group of workers: age 18–67 years from the CBS distribution of the employed labour force; height, BMI, "
            "body fat and VO2max as the walkers in HESTIA."),
            vt("Werk-MET uit het 2024 Adult Compendium (beroep) of ISO 8996 (klasse); rust-MET in rust en pauze. "
            "Geen vrijwillige tempo-regeling; het fysieke hartplafond blijft.",
               "Work MET from the 2024 Adult Compendium (occupation) or ISO 8996 (class); rest MET in rest and breaks. "
            "No voluntary pacing; the physical cardiovascular ceiling stays."),
            vt("Per werker het JOS-3-lichaamsmodel en het hart- en bloedsomloopmodel van HESTIA, in stappen van 5 min, "
            "met drinken naar dorst.",
               "For each worker the HESTIA JOS-3 body model and cardiovascular model, in 5-min steps, "
            "with drinking to thirst."),
            vt("Controle met het PHS-model van ISO 7933:2023 voor een gemiddelde werker.", "Check with the PHS model of ISO 7933:2023 for an average worker."),
        ])
        _p(doc, vt("Niet gemodelleerd: dampdichte beschermende kleding, vrijwillig langzamer werken, nagloei bij het "
                "stoppen en een EHS-kans (de collaps-kalibratie van HESTIA geldt voor lopers).",
                   "Not modelled: vapour-barrier protective clothing, voluntary slowing down, after-glow on "
                "stopping and an EHS probability (the HESTIA collapse calibration applies to runners)."), cursief=True)
        ph = r["phs"]
        if ph["stappen_buiten"]:
            _p(doc, vt(f"PHS valt in {ph['stappen_buiten']} van {ph['stappen']} stappen buiten het geldigheidsgebied "
                    f"van ISO 7933.",
                       f"PHS falls outside the validity range of ISO 7933 in {ph['stappen_buiten']} of {ph['stappen']} "
                    f"steps."), cursief=True, pt=11)
        pad = Path(pad)
        doc.save(pad)
    return pad
