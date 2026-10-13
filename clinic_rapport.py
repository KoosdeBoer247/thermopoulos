# -*- coding: utf-8 -*-
"""
clinic_rapport.py -- Excel, figuren en Word-rapport voor clinic_validatie.py

  schrijf_excel(...)  validatie.xlsx: vastlegging, inclusie, maten per
                      variant, groep, VO2max, modus A, nawarmte, criteria,
                      tijdreeks per loper
  figuren(...)        per loper model tegen meting; Bland-Altman per variant
  maak_rapport(...)   Word, Nederlands, 14 pt
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from docx import Document
from docx.shared import Pt, RGBColor

from hestia_loper_rapport import _stijl, _tabel, _p, _bullets, _figuur
from hestia_reconstructie import VARIANTEN

KLEUR = {"B1": "#2a78d6", "B2": "#eb6834", "B3": "#1baf7a", "meting": "#222222", "A": "#9a9a9a"}
FONT = 15
VERGELIJKINGEN = ("kern", "hartslag", "vocht", "nawarmte")


def _n(x, d=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "–"
    if not np.isfinite(x):
        return "–"
    return f"{x:.{d}f}".replace(".", ",")


# =============================================================================
# Excel
# =============================================================================
def schrijf_excel(lopers, g: pd.DataFrame, criteria: dict, vast, controles, pad: Path,
                  weer_info: str = "") -> Path:
    pad = Path(pad)
    with pd.ExcelWriter(pad, engine="openpyxl") as xw:
        rij = [("gemaakt", datetime.now().isoformat(timespec="seconds"))]
        if vast:
            rij += [("voorspelling vastgelegd", vast["aangemaakt"]),
                    ("ensemble modus A", vast["n_ensemble"]), ("seed", vast["seed"])]
            rij += [(f"vingerafdruk {k}", v) for k, v in vast["suite_vingerafdruk"].items()]
        else:
            rij += [("voorspelling", "GEEN (ontwikkelrun zonder modus A)")]
        if weer_info:
            rij += [("weer modus B", weer_info)]
        rij += [("controle", c) for c in (controles or ["geen bijzonderheden"])]
        pd.DataFrame(rij, columns=["gegeven", "waarde"]).to_excel(xw, sheet_name="Vastlegging", index=False)

        inc = []
        for lv in lopers:
            r = {"code": lv.code}
            for k in VERGELIJKINGEN:
                ok, reden = lv.inclusie.get(k, (False, "–"))
                r[f"{k}_mee"] = "ja" if ok else "nee"
                r[f"{k}_reden"] = reden
            r["opmerking"] = lv.opmerking
            inc.append(r)
        pd.DataFrame(inc).to_excel(xw, sheet_name="Inclusie", index=False)

        for v in VARIANTEN:
            rows = []
            for lv in lopers:
                if v in lv.maten:
                    rows.append({"code": lv.code, **lv.algemeen, **lv.maten[v]})
            if rows:
                pd.DataFrame(rows).to_excel(xw, sheet_name=f"Maten_{v}", index=False)
        g.to_excel(xw, sheet_name="Groep", index=False)

        vo = []
        for lv in lopers:
            s = lv.vo2_schatting
            vo.append({"code": lv.code, **{f"vo2max_{k}": x for k, x in lv.vo2max.items()},
                       "verschil_hestia_garmin_pct": lv.algemeen.get("vo2max_verschil_pct"),
                       "venster_minuten": f"{s.venster[0]}-{s.venster[1]}" if s else "",
                       "snelheid_ms": s.snelheid_ms if s else None, "hartslag": s.hartslag if s else None,
                       "hr_rust": s.hr_rust if s else None, "hr_rust_bron": s.hr_rust_bron if s else "",
                       "hr_max": s.hr_max if s else None, "pct_hrr": s.pct_hrr if s else None,
                       "opmerking": s.opmerking if s else "geen schatting"})
        pd.DataFrame(vo).to_excel(xw, sheet_name="VO2max", index=False)

        na = [{"code": lv.code, "mee": lv.inclusie.get("nawarmte", (False,))[0],
               "gemeten": lv.algemeen.get("nawarmte_meting"),
               "modus_A_mediaan": lv.algemeen.get("A_nawarmte_med"),
               **{f"modus_{v}": lv.maten[v].get("nawarmte_model_B") for v in lv.maten}}
              for lv in lopers]
        pd.DataFrame(na).to_excel(xw, sheet_name="Nawarmte", index=False)

        ma = [{"code": lv.code, **{k: x for k, x in lv.algemeen.items() if k.startswith(("A_", "meting_"))}}
              for lv in lopers]
        pd.DataFrame(ma).to_excel(xw, sheet_name="ModusA", index=False)

        pd.DataFrame([{"maat": k, **c} for k, c in criteria["maten"].items()]).to_excel(xw, sheet_name="Criteria", index=False)

        for lv in lopers:
            if lv.meting is None or not lv.recon:
                continue
            pm = lv.meting.per_minuut
            idx = lv.recon[next(iter(lv.recon))].centraal.index
            t = pd.DataFrame(index=idx)
            t.index.name = "minuut"
            for k in ("snelheid_ms", "met", "hartslag", "kern_temp", "huid_temp"):
                t[f"meting_{k}"] = pm[k].reindex(idx)
            if lv.hoofddeel:
                t["hoofddeel"] = [lv.hoofddeel.start_min <= i <= lv.hoofddeel.eind_min for i in idx]
            for v, rc in lv.recon.items():
                t[f"{v}_t_rect"] = rc.centraal["t_rect"]
                t[f"{v}_t_rect_lo"] = rc.band["t_rect_lo"]
                t[f"{v}_t_rect_hi"] = rc.band["t_rect_hi"]
                t[f"{v}_bekken"] = rc.centraal["t_bekken"]
                t[f"{v}_gem17_05"] = rc.centraal["t_gem17_05"]
                t[f"{v}_huid_borst"] = rc.centraal["huid_borst"]
                t[f"{v}_par"] = rc.centraal["par"]
                for b, h in rc.hr.items():
                    t[f"{v}_hr_{b}"] = h["hr"]
            t.round(3).to_excel(xw, sheet_name=f"Tijdreeks_{lv.code}"[:31])
    return pad


# =============================================================================
# Figuren
# =============================================================================
def figuur_loper(lv, pad: Path):
    if lv.meting is None or lv.hoofddeel is None or not lv.recon:
        return None
    plt.rcParams.update({"font.size": FONT})
    pm = lv.meting.per_minuut
    hd = lv.hoofddeel
    fig, ax = plt.subplots(4, 1, figsize=(13, 15), sharex=True,
                           gridspec_kw={"height_ratios": [3, 2, 1.6, 1]})
    for a in ax:
        a.axvspan(hd.start_min, hd.eind_min, color="#e9e8e3", zorder=0)
        a.grid(alpha=.3)
    # kern
    for v, rc in lv.recon.items():
        x = rc.centraal.index
        ax[0].fill_between(x, rc.band["t_rect_lo"], rc.band["t_rect_hi"], color=KLEUR[v], alpha=.15, lw=0)
        ax[0].plot(x, rc.centraal["t_rect"], color=KLEUR[v], lw=2, label=VARIANTEN[v]["label"])
    band = lv.modus_a.get("_band")
    if band is not None:
        xa = band["minuut"].to_numpy() + hd.start_min
        ax[0].fill_between(xa, band["t_rect_lo"], band["t_rect_hi"], color=KLEUR["A"], alpha=.25, lw=0,
                           label="Modus A (voorspelling, 95%)")
    ax[0].plot(pm.index, pm["kern_temp"], color=KLEUR["meting"], lw=2.5, label="Gemeten (CORE)")
    ax[0].set_ylabel("Kerntemperatuur (°C)")
    lo = np.nanmin([np.nanmin(rc.band["t_rect_lo"]) for rc in lv.recon.values()] + [np.nanmin(pm["kern_temp"])])
    ax[0].set_ylim(max(33.5, lo - 0.2), None)
    # hartslag: band populatie-Garmin per variant (B1 en B3)
    for v in ("B1", "B3"):
        if v not in lv.recon:
            continue
        hrs = [h["hr"] for h in lv.recon[v].hr.values()]
        if len(hrs) >= 2:
            ax[1].fill_between(hrs[0].index, np.minimum(hrs[0], hrs[1]), np.maximum(hrs[0], hrs[1]),
                               color=KLEUR[v], alpha=.3, lw=0, label=f"{v}: VO2max populatie–Garmin")
        else:
            ax[1].plot(hrs[0].index, hrs[0], color=KLEUR[v], lw=2, label=f"{v}")
    ax[1].plot(pm.index, pm["hartslag"], color=KLEUR["meting"], lw=2, label="Gemeten")
    ax[1].set_ylabel("Hartslag (/min)")
    # huid borst
    for v in ("B1", "B3"):
        if v in lv.recon:
            ax[2].plot(lv.recon[v].centraal.index, lv.recon[v].centraal["huid_borst"], color=KLEUR[v], lw=2,
                       label=f"{v} JOS-3 borst")
    ax[2].plot(pm.index, pm["huid_temp"], color=KLEUR["meting"], lw=2, label="Gemeten (CORE, borst)")
    ax[2].set_ylabel("Huid (°C)")
    ax[3].plot(pm.index, pm["met"], color="#555", lw=2)
    ax[3].set_ylabel("MET")
    ax[3].set_xlabel("Minuten na start registratie")
    ax[0].set_title(f"{lv.code}: model tegen meting (grijs vlak = hoofddeel)", pad=10)
    for a in ax[:3]:
        a.legend(loc="upper left", fontsize=11, frameon=False)
    fig.tight_layout()
    fig.savefig(pad, dpi=110)
    plt.close(fig)
    return pad


def figuur_bland_altman(lopers, pad: Path):
    plt.rcParams.update({"font.size": FONT})
    vs = list(VARIANTEN)
    fig, ax = plt.subplots(1, len(vs), figsize=(15, 5.5), sharey=True)
    leeg = True
    for a, v in zip(ax, vs):
        xs, ys, labels = [], [], []
        for lv in lopers:
            if lv.inclusie.get("kern", (False,))[0] and v in lv.maten:
                mm, mt = lv.maten[v]["kern_gem_model"], lv.maten[v]["kern_gem_meting"]
                xs.append((mm + mt) / 2)
                ys.append(mm - mt)
                labels.append(lv.code)
        a.axhline(0, color="#999", lw=1)
        if xs:
            leeg = False
            a.scatter(xs, ys, s=70, color=KLEUR[v], edgecolor="white", linewidth=1.5, zorder=3)
            for x, y, l in zip(xs, ys, labels):
                a.annotate(l, (x, y), xytext=(5, 4), textcoords="offset points", fontsize=11)
            m = float(np.mean(ys))
            a.axhline(m, color=KLEUR[v], lw=2)
            if len(ys) >= 3:
                sd = float(np.std(ys, ddof=1))
                for s in (-1.96, 1.96):
                    a.axhline(m + s * sd, color=KLEUR[v], lw=1.2, ls="--")
        a.set_title(v)
        a.set_xlabel("Gemiddelde model en meting (°C)")
        a.grid(alpha=.3)
    ax[0].set_ylabel("Model − meting (°C)")
    fig.suptitle("Bland-Altman, kerntemperatuur per loper (gemiddelde over het hoofddeel)")
    fig.tight_layout()
    fig.savefig(pad, dpi=110)
    plt.close(fig)
    return None if leeg else pad


def figuren(lopers, g, criteria, uit: Path) -> dict:
    out = {}
    for lv in lopers:
        p = figuur_loper(lv, Path(uit) / f"{lv.code}_modusB.png")
        if p:
            out[lv.code] = p
    ba = figuur_bland_altman(lopers, Path(uit) / "groep_bland_altman.png")
    if ba:
        out["_bland_altman"] = ba
    return out


# =============================================================================
# Word
# =============================================================================
def _groepswaarde(g, maat, v, bron=""):
    r = g[(g.maat == maat) & (g.variant == v) & (g.vo2max_bron == bron)]
    return None if r.empty else r.iloc[0]


def maak_rapport(lopers, g, criteria, clinic, vast, controles, figs, pad: Path,
                 weer_info: str = "") -> Path:
    doc = Document()
    _stijl(doc)
    doc.add_heading(f"Validatierapport HESTIA – Thermo Clinic {clinic.datum}", 0)
    _p(doc, f"Gemaakt {datetime.now():%d-%m-%Y %H:%M}. Criteria: {criteria['bron']} "
            f"(versie {criteria['versie']}).", cursief=True, pt=12)

    n_tot = len(lopers)
    n_mee = {k: sum(1 for lv in lopers if lv.inclusie.get(k, (False,))[0]) for k in VERGELIJKINGEN}
    nmin = criteria["min_lopers_groepsoordeel"]

    doc.add_heading("1. Samenvatting", 1)
    _p(doc, f"{n_tot} lopers in deelnemers.xlsx. Bruikbaar voor de kerntemperatuur: {n_mee['kern']}, "
            f"hartslag: {n_mee['hartslag']}, vochtverlies: {n_mee['vocht']}, nawarmte: {n_mee['nawarmte']}.")
    if n_mee["kern"] < nmin:
        _p(doc, f"Minder dan {nmin} bruikbare lopers: volgens het schema alleen beschrijvend, "
                f"geen groepsoordeel. Het oordeel tussen haakjes laat zien waar het groepsgemiddelde "
                f"zou vallen.", vet=True)
    rijen = [["Maat (groep)", "B1 (primair)", "B2", "B3"]]
    for maat in ("kern_bias", "kern_rmse", "kern_opwarming_verschil", "kern_dekking", "vocht_verschil"):
        c = criteria["maten"][maat]
        r = [f"{c['label']} ({c['eenheid']})"]
        for v in VARIANTEN:
            x = _groepswaarde(g, maat, v)
            r.append("–" if x is None else f"{_n(x.groepswaarde, 2 if c['eenheid'] != '%' else 0)}  {x.oordeel}")
        rijen.append(r)
    _tabel(doc, rijen, breedtes=[5.5, 4, 3.8, 3.8], pt=11)
    _p(doc, "B1 rekent zoals de suite nu (JOS-3 krijgt MET als activiteitsfactor; kerntemperatuur = "
            "gemiddelde van de 17 kernsegmenten + 0,5 °C). B2 en B3 rekenen de inspanning om naar "
            "een veelvoud van de eigen rustverbranding, wat JOS-3 verwacht; B3 gebruikt daarbij de "
            "bekkenkern. Alle drie zijn vóór de clinic vastgelegd.", pt=12)

    doc.add_heading("2. Vastlegging en controles", 1)
    if vast:
        _p(doc, f"Voorspelling (modus A) vastgelegd op {vast['aangemaakt'].replace('T', ' ')}, "
                f"ensemble {vast['n_ensemble']}, seed {vast['seed']}.")
    else:
        _p(doc, "Ontwikkelrun zonder vastgelegde voorspelling (geen modus A).", vet=True)
    if weer_info:
        _p(doc, f"Weer voor de reconstructie (modus B): {weer_info}.")
    if controles:
        for c in controles:
            par = _p(doc, "Let op: " + c, vet=True)
            par.runs[0].font.color.rgb = RGBColor(0xD0, 0x3B, 0x3B)
    else:
        _p(doc, "Geen bijzonderheden: de FIT-gegevens zijn na de voorspelling omgezet en de suite "
                "en deelnemers.xlsx zijn sindsdien niet veranderd.")

    doc.add_heading("3. Werkwijze", 1)
    _bullets(doc, [
        "Modus A: de loper-module met lichaamskenmerken, verwacht tempo en het weer; "
        "start op de starttijd van het hoofddeel.",
        "Modus B: per minuut de gemeten snelheid als inspanning (Daniels & Gilbert voor lopen, "
        "ACSM voor wandelen, 1,5 MET stilstaan), eigen rugwind uit de gemeten snelheid, geen "
        "pacingwet, geen stop, drinken volgens de opgave; vanaf het begin van de registratie.",
        "Onzekerheid in modus B: luchttemperatuur ±1 °C, luchtvochtigheid ±5 %-punt, schaduw tot "
        "zon, windrichting, extra kleding voor de start, zweetfactor. De 95%-band is de spreiding "
        "over 50 runs.",
        "Hartslag: CVR-module met VO2max uit het populatiegemiddelde en uit de Garmin-schatting.",
        "Eenheid van analyse is de loper: eerst een getal per loper, dan het groepsgemiddelde.",
    ])

    doc.add_heading("4. Wie telt mee", 1)
    rijen = [["Code", "Kern", "Hartslag", "Vocht", "Nawarmte"]]
    for lv in lopers:
        rijen.append([lv.code] + ["ja" if lv.inclusie.get(k, (False,))[0] else "nee"
                                  for k in ("kern", "hartslag", "vocht", "nawarmte")])
    _tabel(doc, rijen, pt=11)
    afv = [(lv.code, k, lv.inclusie[k][1]) for lv in lopers for k in VERGELIJKINGEN
           if k in lv.inclusie and not lv.inclusie[k][0]]
    if afv:
        _p(doc, "Afgevallen, met reden:", vet=True)
        _tabel(doc, [["Code", "Vergelijking", "Reden"]] + [list(x) for x in afv], breedtes=[2, 3, 12], pt=10)

    doc.add_heading("5. Resultaten per maat", 1)
    kort = {"kern_bias": "Kern bias (°C)", "kern_rmse": "Kern RMSE (°C)",
            "kern_opwarming_verschil": "Kern opwarming, verschil (°C)", "kern_dekking": "Kern dekking (%)",
            "vocht_verschil": "Vochtverlies, verschil (%-punt)", "hr_bias": "Hartslag bias (/min)",
            "hr_drift_verschil": "Hartslagdrift, verschil (/min per 10 min)",
            "vo2max_verschil_pct": "VO2max HESTIA–Garmin (|%|)",
            "kern_max_verschil": "Kern maximum, verschil (°C)", "dyn_K_verhouding": "Versterking K, CORE/model",
            "dyn_dode_tijd_verschil": "Dode tijd, CORE − model (min)", "dyn_tau_verschil": "τ, CORE − model (min)",
            "dyn_hr_tau_verschil": "τ hartslag, gemeten − model (min)",
            "dyn_hr_na_model_verschil": "Hartslag na hoofddeel, gemeten − model (/min)"}
    rijen = [["Maat", "Variant", "n", "Groep (95%-BI)", "Oordeel"]]
    for _, r in g.iterrows():
        d = 0 if r.eenheid == "%" else (1 if ("/min" in r.eenheid or r.eenheid == "min") else 2)
        var = r.variant + (f", VO2max {r.vo2max_bron}" if isinstance(r.vo2max_bron, str) and r.vo2max_bron else "")
        bi = f" ({_n(r.bi95_lo, d)} – {_n(r.bi95_hi, d)})" if np.isfinite(r.bi95_lo) else ""
        rijen.append([kort.get(r.maat, r.label), var, int(r.n_lopers), _n(r.groepswaarde, d) + bi, r.oordeel])
    _tabel(doc, rijen, breedtes=[5.5, 3.5, 1, 3.2, 4], pt=10)
    _p(doc, "De hartslagmaten zijn verkennend: zonder gemeten VO2max geen oordeel (schema, hoofdstuk 6).",
       cursief=True, pt=12)

    doc.add_heading("6. Per loper", 1)
    for lv in lopers:
        doc.add_heading(lv.code, 2)
        if not lv.maten:
            _p(doc, "Geen modelvergelijking: " + "; ".join(r for _, r in lv.inclusie.values()))
            continue
        hd = lv.hoofddeel
        niet = [k for k in VERGELIJKINGEN if not lv.inclusie.get(k, (False,))[0]]
        if niet:
            _p(doc, "Telt niet mee voor: " + ", ".join(niet) + ". De getallen hieronder staan er "
                    "alleen ter informatie.", vet=True, pt=12)
        if lv.opmerking:
            _p(doc, "Opmerking: " + lv.opmerking, cursief=True, pt=12)
        _p(doc, f"Hoofddeel: {_n(hd.duur_min, 0)} min, {_n(hd.afstand_km, 2)} km, "
                f"{_n(hd.tempo_min_km, 2)} min/km. CORE: {lv.inclusie['kern'][1]}.", pt=12)
        rijen = [["Maat", "B1", "B2", "B3"]]
        for k, lab, d in [("kern_bias", "Bias kern (°C)", 2), ("kern_rmse", "RMSE kern (°C)", 2),
                          ("kern_opwarming_model", "Opwarming model (°C)", 2),
                          ("kern_opwarming_meting", "Opwarming meting (°C)", 2),
                          ("kern_dekking", "Dekking 95%-band (%)", 0),
                          ("hr_bias_populatie", "Bias hartslag, VO2max pop. (/min)", 1),
                          ("hr_bias_garmin", "Bias hartslag, VO2max Garmin (/min)", 1),
                          ("hr_drift_meting_populatie", "Drift gemeten (/min per 10 min)", 1),
                          ("hr_drift_model_populatie", "Drift model, VO2max pop. (/min per 10 min)", 1),
                          ("vocht_model_pct", "Vochtverlies model (%)", 2),
                          ("vocht_meting_pct", "Vochtverlies gemeten (%)", 2),
                          ("kern_max_verschil", "Maximum kern, model − meting (°C)", 2),
                          ("dyn_K_model", "Versterking K model (°C/MET)", 3),
                          ("dyn_dode_tijd_model", "Dode tijd model (min)", 0),
                          ("dyn_tau_model", "τ model (min)", 0)]:
            rijen.append([lab] + [_n(lv.maten[v].get(k), d) if v in lv.maten else "–" for v in VARIANTEN])
        _tabel(doc, rijen, breedtes=[7.5, 3, 3, 3], pt=10)
        if lv.code in figs:
            _figuur(doc, figs[lv.code], f"{lv.code}: lijnen = centrale run, banden = 95% over 50 runs; "
                                        f"grijze band boven = modus A. Hartslag: band tussen VO2max "
                                        f"populatie en Garmin.")

    if "_bland_altman" in figs:
        doc.add_heading("7. Bland-Altman", 1)
        _figuur(doc, figs["_bland_altman"], "Per loper het gemiddelde verschil over het hoofddeel. "
                                            "Doorgetrokken lijn = gemiddelde; stippellijnen = ±1,96 sd (vanaf 3 lopers).")

    doc.add_heading("8. Nawarmte", 1)
    gm = [lv.algemeen.get("nawarmte_meting") for lv in lopers if lv.inclusie.get("nawarmte", (False,))[0]]
    am = [lv.algemeen.get("A_nawarmte_med") for lv in lopers if lv.inclusie.get("nawarmte", (False,))[0]]
    gm = [x for x in gm if x is not None and np.isfinite(x)]
    am = [x for x in am if x is not None and np.isfinite(x)]
    if gm:
        _p(doc, f"Gemeten stijging in de 10 min na het stoppen: gemiddeld {_n(np.mean(gm))} °C "
                f"(n = {len(gm)}).")
        if am:
            besl = np.mean(gm) < 0.5 * np.mean(am)
            _p(doc, f"Modus A voorspelde gemiddeld {_n(np.mean(am))} °C. Beslisregel: "
                    + ("de gemeten stijging is kleiner dan de helft van de modelstijging; voorstel "
                       "PF_DELTA_T_NAGLOED te halveren en dat op een volgende clinic te toetsen."
                       if besl else "de gemeten stijging is niet kleiner dan de helft; geen voorstel."))
    else:
        _p(doc, "Geen bruikbare nawarmtemetingen.")
    _p(doc, "Let op: 'stoppen' is hier het einde van het hoofddeel; wie daarna uitloopt of wandelt, "
            "stopt niet echt. Een trage CORE (zie hoofdstuk 10) laat de gemeten temperatuur na het "
            "stoppen nog oplopen; een deel van de gemeten nawarmte kan dus van de sensor komen.",
       cursief=True, pt=12)

    doc.add_heading("9. VO2max", 1)
    rijen = [["Code", "Populatie", "Garmin", "HESTIA (loop)", "Verschil HESTIA–Garmin"]]
    for lv in lopers:
        rijen.append([lv.code, _n(lv.vo2max.get("populatie", lv.vo2max.get("gemeten")), 1),
                      _n(lv.vo2max.get("garmin"), 1), _n(lv.vo2max.get("hestia"), 1),
                      _n(lv.algemeen.get("vo2max_verschil_pct"), 0) + " %"])
    _tabel(doc, rijen, pt=11)
    _p(doc, "Beide schattingen gebruiken dezelfde hartslag en snelheid en een aangenomen maximale "
            "hartslag; overeenstemming betekent dat de methodes hetzelfde doen, niet dat de waarde "
            "juist is. Het horlogeprofiel (leeftijd, HRmax) is mogelijk niet ingesteld.", cursief=True, pt=12)

    doc.add_heading("10. Verkennend: niveau en dynamica", 1)
    _p(doc, "Bias en RMSE per minuut mengen niveau en timing. Daarom is per signaal een eerste-orde "
            "systeem met dode tijd gefit, met de inspanning (MET uit de gemeten snelheid) als invoer: "
            "K = eindwaarde per MET (niveau), dode tijd en τ = snelheid (dynamica). Het maximum wordt "
            "gezocht in het hoofddeel plus 20 minuten, zodat het niet afhangt van de timing. Zonder "
            "oordeel; vooraf vastgelegd als verkennend.")
    rijen = [["Code", "K CORE", "K B1", "K B3", "L CORE", "L B3", "τ CORE", "τ B3",
              "τ CORE stijg/daal", "max CORE", "max B1", "max B3", "HR ontk. %"]]
    for lv in lopers:
        if not lv.maten or not lv.inclusie.get("kern", (False,))[0]:
            continue
        a = lv.algemeen
        b1, b3 = lv.maten.get("B1", {}), lv.maten.get("B3", {})
        rijen.append([lv.code, _n(a.get("dyn_K_CORE"), 3), _n(b1.get("dyn_K_model"), 3), _n(b3.get("dyn_K_model"), 3),
                      _n(a.get("dyn_dode_tijd_CORE"), 0), _n(b3.get("dyn_dode_tijd_model"), 0),
                      _n(a.get("dyn_tau_CORE"), 0), _n(b3.get("dyn_tau_model"), 0),
                      f"{_n(a.get('dyn_tau_stijgen_CORE'), 0)}/{_n(a.get('dyn_tau_dalen_CORE'), 0)}",
                      _n(a.get("dyn_piek_CORE")), _n(b1.get("dyn_piek_model")), _n(b3.get("dyn_piek_model")),
                      _n(a.get("hartslag_ontkoppeld_pct"), 0)])
    if len(rijen) > 1:
        _tabel(doc, rijen, pt=8)
    rijen = [["Code", "τ HR gemeten", "τ HR model B3", "K HR gemeten", "K HR model B3",
              "HR boven eigen fit na hoofddeel", "HR gemeten − model na hoofddeel"]]
    for lv in lopers:
        b3 = lv.maten.get("B3", {})
        if not b3 or not lv.inclusie.get("hartslag", (False,))[0]:
            continue
        rijen.append([lv.code, _n(b3.get("dyn_hr_tau"), 1), _n(b3.get("dyn_hr_tau_model"), 1),
                      _n(b3.get("dyn_hr_K"), 1), _n(b3.get("dyn_hr_K_model"), 1),
                      _n(b3.get("dyn_hr_na_extra"), 0), _n(b3.get("dyn_hr_na_model_verschil"), 0)])
    if len(rijen) > 1:
        _p(doc, "Hartslag (borstband, zonder rekenregel) als maat voor de dynamica van de "
                "hartreserve. K in slagen per MET, τ in minuten, VO2max populatie.", pt=12)
        _tabel(doc, rijen, pt=9)
    _bullets(doc, [
        "K gelijk en τ verschillend: het model bereikt de goede temperatuur, maar sneller of trager.",
        "τ CORE groter dan τ model kan uit de sensor komen (rekenregel, pil-referentie) of uit het "
        "lichaam (trager dan JOS-3). Zonder pil of rectale meting niet te scheiden. Een ongeveer "
        "gelijk verschil bij alle lopers wijst eerder op de sensor.",
        "Een zuivere sensorvertraging verlaagt het gemeten maximum. Is het gemeten maximum niet lager "
        "dan het model, dan pleit dat tegen alleen sensorvertraging.",
        "Hartslag ontkoppeld: minuten waarin de inspanning ≥ 20% daalt en de hartslag ≥ 95% blijft. "
        "De CORE rekent met de hartslag; in die minuten is de CORE minder onafhankelijk.",
        "Hartslag: de CVR-module rekent de hartslag direct uit inspanning en temperatuur (τ model "
        "< 1 min). Een grotere gemeten τ en een hartslag die na het hoofddeel hoog blijft, wijzen "
        "op een hartreserve die trager herstelt dan het model.",
    ])
    _p(doc, "Huidtemperatuur (borst) staat per loper in validatie.xlsx; alleen beschrijvend.")

    doc.add_heading("11. Kanttekeningen", 1)
    _bullets(doc, [
        "De CORE-sensor berekent de kerntemperatuur; een verschil kan van het model of van de sensor komen.",
        "Het weer is stadsweer per uur van de Data Engine; schaduw, bos en wind van de groep zitten er niet in.",
        "De starttijd in de FIT-export is afgerond op 10 minuten (privacy); voor het uurweer verwaarloosbaar.",
        "Vochtverlies uit wegen bevat ook ademhaling en zweet in de kleding; wie plaste, telt niet mee.",
        "Deze data worden niet gebruikt om het model bij te stellen; een aanpassing toetsen we op een volgende clinic.",
    ])
    doc.save(pad)
    return Path(pad)
