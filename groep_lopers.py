# -*- coding: utf-8 -*-
"""
groep_lopers.py -- een groep bekende lopers door een gekozen loop sturen
========================================================================

[2026-10-27] "Wat als deze lopers die loop hadden gelopen?" Voor elke loper
uit een lijst (tabblad Deelnemers in het formaat van een Thermo Clinic,
deelnemers.xlsx) rekent de persoonlijke loperanalyse (hestia_loper) dezelfde
loop door: zelfde plaats, datum, starttijd, afstand en weer, maar met de
eigen lichaamskenmerken, het eigen tempo en de eigen fitheid.

Fitheid (VO2max), in deze volgorde:
  1. vo2max in de lijst (uit een inspanningstest);
  2. afgeleid uit hartslag en snelheid van een eerdere loop van die loper
     (FIT-export <code>_*.xlsx in een opgegeven map, bijv. fit_uitvoer van
     een clinic), zoals in het rapport over Emmen en de Dam tot Damloop;
  3. anders de schatting van de loperanalyse zelf.

Uitvoer: een overzicht (Excel en Word) van alle lopers samen, desgewenst per
loper het gewone loperrapport, en een rapportpakket (startmenu R).

Het weer komt uit een Data Engine-bestand: archief (verleden, vanaf 1940;
de laatste ~5 dagen nog niet) of verwachting (tot ~16 dagen vooruit).
"""
from __future__ import annotations

import contextlib
import io
import re
import sys
import time
import warnings
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

N_ENSEMBLE = 100
SEED = 42


def lees_lopers(pad: str | Path) -> list:
    """Lopers uit het tabblad Deelnemers (het tabblad Clinic is hier niet nodig)."""
    import clinic_invoer as ci
    pad = Path(pad)
    with pd.ExcelFile(pad) as xl:
        blad = "Deelnemers" if "Deelnemers" in xl.sheet_names else xl.sheet_names[0]
        dn = pd.read_excel(xl, blad, dtype=object)
    dn.columns = [str(c).strip() for c in dn.columns]
    mist = [k for k, verplicht, _ in ci.KOLOMMEN if verplicht and k not in dn.columns]
    if mist:
        raise ValueError(f"{pad.name}: kolommen ontbreken: " + ", ".join(mist))
    lopers, fouten = [], []
    for rij in dn.to_dict("records"):
        if all(ci._leeg(v) for v in rij.values()):
            continue
        try:
            lopers.append(ci._deelnemer_uit_rij(rij))
        except ValueError as e:
            fouten.append(str(e))
    if fouten:
        raise ValueError("De lijst klopt niet:\n  - " + "\n  - ".join(fouten))
    return lopers


def vo2max_uit_fit(code: str, fit_map: Path | None, d) -> tuple[float | None, str]:
    """VO2max uit een eerdere loop (FIT-export), of None."""
    if not fit_map or not Path(fit_map).exists():
        return None, ""
    kand = sorted(Path(fit_map).glob(f"{code}_*.xlsx"))
    if not kand:
        return None, ""
    try:
        import inspanning_uit_fit as iuf
        m = iuf.lees_export(kand[-1])
        hd = iuf.hoofddeel(m)
        s = iuf.vo2max_uit_loop(m, hd, d.leeftijd, d.hr_max, d.hr_rust) if hd else None
        if s is not None and np.isfinite(s.vo2max):
            return float(s.vo2max), f"uit loop {kand[-1].stem}"
    except Exception:
        pass
    return None, ""


def bereken(lopers: list, loop: dict, weerbestand: str | Path, fit_map: Path | None = None,
            drinkt: bool = True, n: int = N_ENSEMBLE, seed: int = SEED, progress=print) -> dict:
    """loop: evenement, datum (JJJJ-MM-DD), starttijd (UU:MM), plaats, afstand_km."""
    import hestia_loper as hl
    rijen, resultaten = [], {}
    for i, d in enumerate(lopers, 1):
        t0 = time.time()
        vo2, bron = (d.vo2max, "test (lijst)") if d.vo2max else vo2max_uit_fit(d.code, fit_map, d)
        inv = hl.LoperInvoer(
            lengte_cm=d.lengte_cm, gewicht_kg=d.gewicht_voor_kg, leeftijd=int(d.leeftijd),
            geslacht=d.geslacht, evenement=loop["evenement"], datum=loop["datum"],
            starttijd=d.starttijd or loop["starttijd"], plaats=loop["plaats"],
            afstand_km=float(loop["afstand_km"]), tempo_min_per_km=d.verwacht_tempo,
            drinkt_bij_elke_post=drinkt, hitte_geacclimatiseerd=d.hitte_gewend, kleding=d.kleding,
            vo2max_bekend=round(vo2, 1) if vo2 else None, hr_max_bekend=d.hr_max,
            hr_rust_bekend=d.hr_rust, weerbron="excel", weer_excel=str(weerbestand), naam=d.code)
        try:
            with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = hl.analyseer_loper(inv, n_ensemble=n, seed=seed, gevoeligheid=False)
        except Exception as e:
            progress(f"  {d.code}: kan niet worden doorgerekend ({e})")
            rijen.append({"code": d.code, "fout": str(e)})
            continue
        s = r.samenvatting()
        resultaten[d.code] = r
        rijen.append({
            "code": d.code, "geslacht": d.geslacht, "leeftijd": d.leeftijd, "tempo": d.verwacht_tempo,
            "vo2max": float(r.afgeleid.vo2max), "vo2max_bron": bron or "schatting loperanalyse",
            "kern_max": s["t_rect_max"]["med"], "kern_max_lo": s["t_rect_max"]["lo"],
            "kern_max_hi": s["t_rect_max"]["hi"], "kern_max_na_finish": s["t_rect_max_pf"]["med"],
            "co_min": s["co_min"]["med"], "co_min_lo": s["co_min"]["lo"],
            "hr_piek": s["hr_piek"]["med"], "vocht_pct": s["dehyd"]["med"],
            "finish_min": s["finish"]["med"], "vertraging_pct": s["tempo_daling"]["med"],
            "vertraging_pct_hi": s["tempo_daling"]["hi"], "p_collapse_10000": s["p_collapse"]["med"] * 1e4,
            "ehe_pct": s["f_ehe"]["frac"] * 100, "gestopt_pct": s["f_gestopt"]["frac"] * 100,
            "signaal": r.signaal.get("kleur", ""),
        })
        progress(f"  {i}/{len(lopers)} {d.code}: hoogste kern {s['t_rect_max']['med']:.2f} °C, "
                 f"signaal {r.signaal.get('kleur', '')}  ({time.time() - t0:.0f} s)")
    return {"loop": dict(loop), "weerbestand": Path(weerbestand).name, "n": n, "seed": seed,
            "drinkt": drinkt, "tabel": pd.DataFrame(rijen), "resultaten": resultaten}


def figuur(g: dict, pad: Path) -> Path | None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = g["tabel"].dropna(subset=["kern_max"]) if "kern_max" in g["tabel"] else pd.DataFrame()
    if t.empty:
        return None
    plt.rcParams.update({"font.size": 12})
    fig, ax = plt.subplots(1, 2, figsize=(13, 0.45 * len(t) + 2.5), sharey=True)
    y = np.arange(len(t))
    ax[0].errorbar(t.kern_max, y, xerr=[t.kern_max - t.kern_max_lo, t.kern_max_hi - t.kern_max],
                   fmt="o", color="#c0392b", capsize=3)
    for x, c in ((39.5, "#e67e22"), (40.5, "#c0392b")):
        ax[0].axvline(x, color=c, ls="--", lw=1)
    ax[0].set_xlabel("Hoogste kerntemperatuur (°C), mediaan en 95 %")
    ax[1].errorbar(t.co_min, y, xerr=[t.co_min - t.co_min_lo, np.zeros(len(t))], fmt="o",
                   color="#2e86c1", capsize=3)
    ax[1].axvline(0, color="#c0392b", ls="--", lw=1)
    ax[1].set_xlabel("Laagste hartreserve (L/min), mediaan en ongunstigste 2,5 %")
    ax[0].set_yticks(y)
    ax[0].set_yticklabels(t.code)
    for a in ax:
        a.grid(alpha=.3)
    lp = g["loop"]
    fig.suptitle(f"{lp['evenement']}, {lp['plaats']} {lp['datum']} {lp['starttijd']}, {lp['afstand_km']} km")
    fig.tight_layout()
    fig.savefig(pad, dpi=120)
    plt.close(fig)
    return pad


def _k(x, n=2):
    try:
        return f"{float(x):.{n}f}".replace(".", ",") if np.isfinite(float(x)) else "–"
    except (TypeError, ValueError):
        return "–"


def maak_rapport(g: dict, pad: str | Path) -> Path:
    from docx import Document
    from docx.shared import Pt, Cm
    pad = Path(pad)
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(12)
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = Cm(1.8)
    lp, t = g["loop"], g["tabel"]
    doc.add_heading(f"Wat als deze lopers {lp['evenement']} hadden gelopen?", 0)
    p = doc.add_paragraph()
    p.add_run(f"{lp['plaats']}, {lp['datum']}, start {lp['starttijd']}, {lp['afstand_km']} km. "
              f"Weer: {g['weerbestand']}. Per loper {g['n']} berekeningen (seed {g['seed']}); "
              f"drinken bij elke post: {'ja' if g['drinkt'] else 'nee'}. Gemaakt {datetime.now():%d-%m-%Y} "
              f"met de HESTIA-PYROX-Klimatos-suite. Lopers staan onder een code.").italic = True
    # [2026-10-31] het weer
    doc.add_heading("Het weer", 1)
    for i, fp in enumerate(g.get("weer_figuren", [])):
        if fp and Path(fp).exists():
            doc.add_picture(fp, width=Cm(17))
            doc.add_paragraph(["Het weer tijdens de loop (tot de laatste finisher): temperaturen, vocht en "
                               "wind, zon en bewolking.", "Het weer over de hele dag; de blauwe band is de "
                               "loop."][min(i, 1)]).runs[0].italic = True
    wl = g.get("weer_tabel")
    if wl is not None and len(wl):
        stap = max(1, int(round(len(wl) / 16)))
        sel = wl.iloc[::stap]
        kols = [c for c in ("Lucht (°C)", "RV (%)", "Wind 1,5 m (m/s)", "Zon (W/m²)", "Bewolking (%)",
                            "Natte bol (°C)", "MRT (°C)", "WBGT (°C)", "UTCI (°C)") if c in sel]
        tb = doc.add_table(rows=1, cols=len(kols) + 1)
        tb.style = "Light Grid Accent 1"
        for i, h in enumerate(["Tijd"] + kols):
            tb.rows[0].cells[i].text = h
        for _, rw in sel.iterrows():
            cs = tb.add_row().cells
            cs[0].text = f"{rw['tijd']:%H:%M}"
            for i, k in enumerate(kols, 1):
                cs[i].text = _k(rw[k], 0 if k in ("RV (%)", "Zon (W/m²)", "Bewolking (%)") else 1)
        for row in tb.rows:
            for c in row.cells:
                for par in c.paragraphs:
                    for run in par.runs:
                        run.font.size = Pt(9)
        doc.add_paragraph("Alle weerwaarden per 10 minuten en per uur staan in het Excel-bestand "
                          "(tabbladen Weer_loop en Weer_dag).").runs[0].italic = True
    doc.add_heading("Overzicht", 1)
    kol = ["Code", "Leeftijd", "Tempo", "VO2max", "Kern max (°C)", "95 %", "Hartreserve min (L/min)",
           "Vocht (%)", "Vertraging eind (%)", "Collaps /10.000", "Signaal"]
    tb = doc.add_table(rows=1, cols=len(kol))
    tb.style = "Light Grid Accent 1"
    for i, h in enumerate(kol):
        tb.rows[0].cells[i].text = h
    for _, r in t.iterrows():
        if "fout" in t.columns and isinstance(r.get("fout"), str):
            cs = tb.add_row().cells
            cs[0].text = str(r["code"])
            cs[1].text = "niet doorgerekend: " + r["fout"][:80]
            continue
        vals = [r["code"], f"{int(r['leeftijd'])}", r["tempo"], _k(r["vo2max"], 1), _k(r["kern_max"]),
                f"{_k(r['kern_max_lo'])} – {_k(r['kern_max_hi'])}", _k(r["co_min"], 1), _k(r["vocht_pct"], 1),
                _k(r.get("vertraging_pct", float("nan")), 0), _k(r["p_collapse_10000"], 1), r["signaal"]]
        cs = tb.add_row().cells
        for i, v in enumerate(vals):
            cs[i].text = str(v)
    for row in tb.rows:
        for c in row.cells:
            for par in c.paragraphs:
                for run in par.runs:
                    run.font.size = Pt(9)
    doc.add_paragraph()
    fig = g.get("figuur")
    if fig and Path(fig).exists():
        doc.add_picture(fig, width=Cm(17))
        doc.add_paragraph("Links de hoogste kerntemperatuur tijdens de loop, rechts de laagste reserve van "
                          "het hart. De stippellijnen: 39,5 °C (grens hitte-uitputting), 40,5 °C (klinische "
                          "grens) en een hartreserve van nul.").runs[0].italic = True
    ft = g.get("figuur_tijd")
    if ft and Path(ft).exists():
        doc.add_picture(ft, width=Cm(17))
        doc.add_paragraph("Per loper de mediaan van alle runs in de tijd. Stippellijnen: dezelfde grenzen "
                          "als in de tabel.").runs[0].italic = True
    doc.add_heading("Hoe is gerekend?", 1)
    for x in ["Elke loper start op het tempo uit de lijst, met de eigen lengte, het eigen gewicht, "
              "leeftijd, geslacht, kleding en hittegewenning.",
              "Onderweg past het model het tempo aan zoals een loper dat doet: het vertraagt als de "
              "kerntemperatuur boven 38,5 °C komt en als de reserve van het hart onder 2 L/min zakt "
              "(met een opbouwend effect als die reserve laag blijft), en een loper kan stoppen bij een "
              "zeer hoge inspanningsbeleving. 'Vertraging eind' is hoeveel langzamer de loper aan het "
              "eind loopt dan bij de start (mediaan).",
              "Fitheid (VO2max): uit een test als die in de lijst staat, anders afgeleid uit hartslag en "
              "snelheid van een eerdere loop van die loper (kolom 'VO2max-bron' in de Excel), anders een "
              "schatting op basis van leeftijd, geslacht en tempo.",
              "Het weer is het uurweer uit het Data Engine-bestand; elke berekening varieert binnen de "
              "onzekerheid van weer, loopeconomie, zweten, drinken en tempo.",
              "Het risicosignaal en de kans op collaps zijn dezelfde maten als in het persoonlijke "
              "loperrapport."]:
        doc.add_paragraph(x, style="List Bullet")
    doc.add_heading("Waar dit voor geldt", 1)
    for x in ["Een wat-als-berekening, geen voorspelling. De tempo-aanpassing in het model is een "
              "regelkring met gekozen versterkingen (niet getoetst aan metingen); een echte loper kan "
              "ook al vooraf langzamer starten bij warm weer, en dat zit niet in het model.",
              "Onder ongeveer WBGT 18 rekent HESTIA bij hardlopen de kerntemperatuur vermoedelijk enkele "
              "tienden te hoog (koude-huidfout van JOS-3).",
              "HESTIA is onderzoekssoftware en niet gevalideerd voor beslissingen over iemands veiligheid."]:
        doc.add_paragraph(x, style="List Bullet")
    doc.save(pad)
    return pad


def _langste(g: dict):
    """Resultaat van de loper die het langst onderweg is (dekt het hele weervenster)."""
    res = [r for r in g.get("resultaten", {}).values() if r is not None]
    return max(res, key=lambda r: len(r.assessment.meteo["time"])) if res else None


def figuur_tijd(g: dict, pad: Path) -> Path | None:
    """[2026-10-31] Per loper de mediaan in de tijd: kern, hartslag, hartreserve, tempo, vocht, WBGT."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    res = g.get("resultaten", {})
    if not res:
        return None
    plt.rcParams.update({"font.size": 12})
    panelen = [("t_rect", "Kerntemperatuur (°C)", (39.5, 40.5)), ("hr", "Hartslag (/min)", ()),
               ("co", "Hartreserve (L/min)", (2.0, 0.0)), ("tempo", "Tempo (min/km)", ()),
               ("dehyd", "Vochtverlies (% lichaamsgewicht)", (2.0, 3.0)), ("met", "Inspanning (MET)", ())]
    fig, axs = plt.subplots(3, 2, figsize=(15, 14), sharex=True)
    kleuren = plt.cm.tab10.colors
    for ax, (k, titel, lijnen) in zip(axs.flat, panelen):
        for i, (code, r) in enumerate(res.items()):
            b = r.banden.get(k)
            if b is None:
                continue
            ax.plot(b["minuten"], b["med"], color=kleuren[i % 10], lw=1.8, label=code)
        for y in lijnen:
            ax.axhline(y, color="#d03b3b" if y in (40.5, 0.0, 3.0) else "#ec835a", ls="--", lw=1.2)
        if k == "tempo":
            ax.invert_yaxis()
        ax.set_title(titel)
        ax.grid(alpha=.3)
    for ax in axs[-1]:
        ax.set_xlabel("Minuten na de start")
    h, l = axs[0][0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=min(10, len(l)), frameon=False)
    fig.suptitle("Per loper de mediaan van alle runs in de tijd", fontsize=15)
    fig.tight_layout(rect=(0, 0.04, 1, 0.97))
    fig.savefig(pad, dpi=150)
    plt.close(fig)
    return pad


def maak_uitvoer(g: dict, stam: Path, per_loper: bool = False) -> list[Path]:
    """Excel, figuren, groepsrapport en desgewenst per loper het loperrapport en Excel."""
    from hestia_loper import weer_tabellen, exporteer_excel
    import hestia_loper_plots as hp
    uit = []
    xlsx = Path(str(stam) + ".xlsx")
    r_l = _langste(g)
    wl, wd = weer_tabellen(r_l) if r_l is not None else (None, None)
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        g["tabel"].to_excel(xw, sheet_name="Overzicht", index=False)
        pd.DataFrame([{**g["loop"], "weerbestand": g["weerbestand"], "n": g["n"], "seed": g["seed"],
                       "drinkt_bij_elke_post": g["drinkt"]}]).to_excel(xw, sheet_name="Loop", index=False)
        if wl is not None:
            wl.to_excel(xw, sheet_name="Weer_loop", index=False)
        if wd is not None:
            wd.to_excel(xw, sheet_name="Weer_dag", index=False)
    uit.append(xlsx)
    g["figuur"] = str(figuur(g, Path(str(stam) + "_figuur.png")) or "")
    g["figuur_tijd"] = str(figuur_tijd(g, Path(str(stam) + "_tijd.png")) or "")
    g["weer_figuren"] = []
    if r_l is not None:
        for naam, fn in (("weer", hp.plot_weer), ("weer_dag", hp.plot_weer_dag)):
            try:
                p = fn(r_l, Path(f"{stam}_{naam}.png"))
                if p:
                    g["weer_figuren"].append(str(p))
            except Exception:
                pass
    g["weer_tabel"] = wl
    uit.append(maak_rapport(g, Path(str(stam) + ".docx")))
    if per_loper:
        from hestia_loper_plots import maak_alle_plots
        from hestia_loper_rapport import maak_rapport as loper_rapport
        for code, r in g["resultaten"].items():
            s2 = Path(f"{stam}_{code}")
            plots = maak_alle_plots(r, Path(str(s2) + "_figuren"))
            uit.append(loper_rapport(r, plots, Path(str(s2) + ".docx")))
            uit.append(exporteer_excel(r, Path(str(s2) + ".xlsx")))
    return uit


# -----------------------------------------------------------------------------
# Interactief
# -----------------------------------------------------------------------------
def _vraag(tekst, standaard=None):
    a = input(f"  {tekst}" + (f" [{standaard}]" if standaard not in (None, "") else "") + ": ").strip().strip('"')
    return a if a else (standaard if standaard is not None else "")


def _kies(lijst, tekst):
    for i, p in enumerate(lijst, 1):
        print(f"    {i}  {p}")
    k = _vraag(f"{tekst} (nummer of pad)")
    if k.isdigit() and 1 <= int(k) <= len(lijst):
        return Path(lijst[int(k) - 1])
    return Path(k) if k else None


def _is_lijst(p: Path) -> bool:
    """Lopers-lijst (tabblad Deelnemers met kolom code) of een aanmeldlijst."""
    try:
        import aanmelding
        if aanmelding.is_aanmeldlijst(p):
            return True
        with pd.ExcelFile(p) as xl:
            blad = "Deelnemers" if "Deelnemers" in xl.sheet_names else xl.sheet_names[0]
            kop = [str(c).strip() for c in pd.read_excel(xl, blad, nrows=0).columns]
        return "code" in kop
    except Exception:
        return False


def tempo_uit_fit(code: str, fit_map: Path | None) -> Optional[str]:
    """[2026-10-30] Gemeten tempo (m:ss per km) van het hoofddeel van de eerdere loop."""
    if not fit_map or not Path(fit_map).exists():
        return None
    kand = sorted(Path(fit_map).glob(f"{code}_*.xlsx"))
    if not kand:
        return None
    try:
        import inspanning_uit_fit as iuf
        hd = iuf.hoofddeel(iuf.lees_export(kand[-1]))
        t = float(hd.tempo_min_km) if hd else float("nan")
        if np.isfinite(t) and 2.5 <= t <= 15:
            sec = int(round(t * 60))
            return f"{sec // 60}:{sec % 60:02d}"
    except Exception:
        pass
    return None


def _tempo_aanpassen(lopers: list, invoer: str, fit_map: Path | None = None) -> list:
    """'' = ongewijzigd; '6:30' = iedereen dit tempo; '+15%' = 15 % langzamer dan de lijst;
    'm' = gemeten tempo uit de eerdere loop (fit_uitvoer); 'm+25%' = gemeten + 25 %."""
    invoer = (invoer or "").strip().replace(",", ".").lower()
    if not invoer:
        return lopers
    import clinic_invoer as ci
    if invoer.startswith("m"):
        rest = invoer[1:].strip()
        basis = []
        for d in lopers:
            t = tempo_uit_fit(d.code, fit_map)
            basis.append(replace(d, verwacht_tempo=t, opmerking=(d.opmerking + "; tempo gemeten").strip("; "))
                         if t else replace(d, opmerking=(d.opmerking + "; tempo uit de lijst (geen meting)").strip("; ")))
        return _tempo_aanpassen(basis, rest) if rest else basis
    # [2026-10-30] '+25', '+25%', '25%' en '-10' = percentage; '6:30' of '6.5' = tempo
    m = (re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*%", invoer)
         or re.fullmatch(r"([+-]\d+(?:\.\d+)?)", invoer))
    uit = []
    for d in lopers:
        if m:
            mm, ss = d.verwacht_tempo.split(":")
            sec = int(round((int(mm) * 60 + int(ss)) * (1 + float(m.group(1)) / 100)))
            nieuw = f"{sec // 60}:{sec % 60:02d}"
        else:
            try:
                nieuw = ci._tempo(float(invoer)) if re.fullmatch(r"\d+(?:\.\d+)?", invoer) else ci._tempo(invoer)
                mm, ss = nieuw.split(":")
                int(mm), int(ss)
            except (ValueError, TypeError):
                raise ValueError(f"'{invoer}' is geen tempo of percentage; gebruik bijv. 6:30 of +25%")
            if not 2.5 <= int(mm) + int(ss) / 60 <= 15:
                raise ValueError(f"tempo {nieuw} buiten 2:30-15:00")
        uit.append(replace(d, verwacht_tempo=nieuw))
    return uit


def interactief(werkmap: str | Path = ".") -> int:
    werkmap = Path(werkmap)
    print("\nGroep lopers door een gekozen loop sturen (wat-als, verleden of nabije toekomst)")
    import aanmelding
    lijsten = sorted({p for p in list(werkmap.glob("*.xlsx")) + list(werkmap.glob("*/deelnemers*.xlsx"))
                      if not p.name.startswith(("Thermopoulos", "~$", "GroepLopers", "PRIVE_"))
                      and _is_lijst(p)})
    print("  Lijst met lopers (tabblad Deelnemers zoals in een clinic-deelnemers.xlsx):")
    lijst = _kies(lijsten, "Lijst")
    if not lijst or not lijst.exists():
        print("  Geen lijst gekozen. Een leeg sjabloon maak je met het FIT-menu, keuze a.")
        return 1
    if aanmelding.is_aanmeldlijst(lijst):
        # [2026-10-29] aanmeldlijst met namen/e-mail: automatisch naar codes
        print("  Dit is een aanmeldlijst met e-mailadressen. De suite zet hem om naar codes:\n"
              "  elk FIT-bestand wordt via het e-mailadres in de bestandsnaam gekoppeld, de code\n"
              "  hoort bij de Garmin-set (Garmin001 -> G001), en namen en e-mailadressen komen\n"
              "  alleen in PRIVE_koppeltabel.xlsx, nooit in een rapport.")
        try:
            bron = aanmelding.bewaar_aanmeldlijst(lijst, vraag=input)
            res = aanmelding.omzetten(bron, vraag=input)
        except ValueError as e:
            print(f"  {e}")
            return 1
        print("\n" + aanmelding.samenvatting(res))
        if res.nog_invullen:
            print(f"\n  Vul de ontbrekende waarden in {res.deelnemers_xlsx.name} in en kies daarna "
                  "opnieuw 1 -> 3.")
            return 1
        lijst = res.deelnemers_xlsx
    try:
        lopers = lees_lopers(lijst)
    except ValueError as e:
        print(f"  {e}")
        return 1
    print(f"  {len(lopers)} lopers: " + ", ".join(d.code for d in lopers))
    fm = lijst.parent / "fit_uitvoer"
    fit_map = None
    if fm.exists() and _vraag(f"Fitheid afleiden uit eerdere lopen in {fm.name}? (j/n)", "j").lower().startswith("j"):
        fit_map = fm
    weer = sorted(werkmap.glob("Thermopoulos*.xlsx"))
    print("  Weerbestand van de loopdag (Data Engine; archief voor het verleden, verwachting voor de "
          "komende ~16 dagen):")
    wb = _kies(weer, "Weerbestand")
    if not wb or not wb.exists():
        print("  Geen weerbestand. Haal het weer eerst op met keuze 5 van het hoofdmenu.")
        return 1
    loop = {"evenement": _vraag("Naam van de loop", "Wat-als-loop"),
            "plaats": _vraag("Plaats"),
            "datum": _vraag("Datum (JJJJ-MM-DD)"),
            "starttijd": _vraag("Starttijd (UU:MM)", "12:00"),
            "afstand_km": float(_vraag("Afstand (km)", "10").replace(",", "."))}
    # [2026-10-29] tempo en hitte-gewenning voor DEZE loop (de lijst komt vaak van een clinic)
    while True:
        t = _vraag("Tempo voor deze loop: Enter = uit de lijst; m = gemeten in de eerdere loop; "
                   "m+25% = gemeten en 25 % langzamer; +25% = lijst en 25 % langzamer; "
                   "6:30 = iedereen hetzelfde", "")
        try:
            lopers = _tempo_aanpassen(lopers, t, fit_map or (fm if fm.exists() else None))
            break
        except ValueError as e:
            print(f"  {e}")
    if t:
        print("  Tempo per loper: " + ", ".join(
            f"{d.code} {d.verwacht_tempo}" + (" (lijst)" if "tempo uit de lijst" in d.opmerking else "")
            for d in lopers))
    h = _vraag("Hitte-gewend: Enter = per loper uit de lijst; j = iedereen; n = niemand", "")
    if h.lower() in ("j", "n"):
        lopers = [replace(d, hitte_gewend=h.lower() == "j") for d in lopers]
    drinkt = _vraag("Drinken bij elke drankpost? (j/n)", "j").lower().startswith("j")
    n = int(_vraag("Berekeningen per loper (meer = nauwkeuriger, langzamer)", str(N_ENSEMBLE)))
    # [2026-10-30] rekentijd groeit met de afstand (45 km, n=100: ~5 min per loper)
    sec = len(lopers) * n * max(0.4, 0.068 * float(loop["afstand_km"]))
    print(f"  Rekenen: {len(lopers)} lopers, ongeveer {sec / 60:.0f} minuten...")
    g = bereken(lopers, loop, wb, fit_map=fit_map, drinkt=drinkt, n=n)
    veilig = "".join(c for c in loop["evenement"] if c.isalnum() or c in "-_ ").strip().replace(" ", "_")
    stam = werkmap / f"GroepLopers_{veilig}_{loop['datum']}_{datetime.now():%H%M}"
    import rapportpakket
    pk = rapportpakket.bewaar("groep", g, stam)
    if pk:
        print(f"  Rapportgegevens bewaard: {pk.name} (startmenu R = rapport later maken)")
    if _vraag("Overzicht (Excel + Word) nu maken? (j/n)", "j").lower().startswith("j"):
        per = _vraag("Ook per loper een eigen rapport? (j/n)", "n").lower().startswith("j")
        for p in maak_uitvoer(g, stam, per_loper=per):
            print(f"  {p}")
    return 0


if __name__ == "__main__":
    _rc = interactief(Path.cwd())
    if _rc and not (hasattr(sys, "ps1") or "spyder_kernels" in sys.modules):
        sys.exit(_rc)
