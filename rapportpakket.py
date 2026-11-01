# -*- coding: utf-8 -*-
"""
rapportpakket.py -- een rapport later (opnieuw) maken
=====================================================

[2026-10-27] Elke berekening van de suite (HESTIA-evenement, persoonlijke
loperanalyse, PYROX, Klimatos, een FIT-loop) bewaart na afloop een
*rapportpakket*: een klein bestand ``*_rapportpakket.pkl`` met precies de
gegevens die de rapportgenerator nodig heeft. Zo kan het rapport ook later
gemaakt worden, als je na de berekening "nee" zei, of opnieuw na een
verbetering van de rapportgenerator, zonder opnieuw te rekenen.

Het startmenu (start_thermopoulos.py, keuze R) zoekt deze pakketten en maakt
het rapport met ``maak(pad)``.

Veiligheid: een .pkl-bestand is een Python-pickle. Open alleen pakketten die
je zelf hebt gemaakt (laden kan code uitvoeren).
"""
from __future__ import annotations

import os
import pickle
from datetime import datetime
from pathlib import Path

VERSIE = 1
ACHTERVOEGSEL = "_rapportpakket.pkl"

SOORTEN = {
    "hestia": "HESTIA-evenement (Monte Carlo)",
    "loper": "Persoonlijke loperanalyse",
    "pyrox": "PYROX bevolkingsgroepen",
    "klimatos": "Klimatos klimaattrend",
    "fitloop": "FIT-loop nagerekend met HESTIA",
    "groep": "Groep lopers in een gekozen loop (wat-als)",
}


def bewaar(soort: str, gegevens: dict, rapport_stam: str | os.PathLike) -> Path | None:
    """Bewaar een rapportpakket naast het (toekomstige) rapport.
    rapport_stam: pad van het rapport zonder extensie. Geeft het pad terug,
    of None als bewaren mislukt (de berekening zelf gaat dan gewoon door)."""
    if soort not in SOORTEN:
        raise ValueError(f"onbekende soort {soort!r}")
    pad = Path(str(rapport_stam) + ACHTERVOEGSEL)
    try:
        with open(pad, "wb") as f:
            pickle.dump({"versie": VERSIE, "soort": soort, "gemaakt": datetime.now().isoformat(timespec="seconds"),
                         "rapport_stam": str(rapport_stam), "gegevens": gegevens}, f,
                        protocol=pickle.HIGHEST_PROTOCOL)
        return pad
    except Exception as e:   # bijv. een niet-pickelbaar object: niet fataal
        print(f"  (rapportpakket niet bewaard: {type(e).__name__}: {e})")
        try:
            pad.unlink()
        except OSError:
            pass
        return None


def laad(pad: str | os.PathLike) -> dict:
    with open(pad, "rb") as f:
        p = pickle.load(f)
    if not isinstance(p, dict) or p.get("soort") not in SOORTEN:
        raise ValueError(f"{pad} is geen rapportpakket van de suite")
    return p


def vind(*mappen) -> list[Path]:
    """Alle rapportpakketten in de opgegeven mappen, nieuwste eerst."""
    gevonden = []
    for m in mappen:
        if m and Path(m).exists():
            gevonden += list(Path(m).glob("*" + ACHTERVOEGSEL))
    uniek = {p.resolve(): p for p in gevonden}
    return sorted(uniek.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def omschrijving(pad: Path) -> str:
    try:
        p = laad(pad)
        return f"{SOORTEN[p['soort']]}, {p['gemaakt'].replace('T', ' ')}: {pad.name}"
    except Exception as e:
        return f"{pad.name} (onleesbaar: {e})"


def _word(md_tekst: str, md_pad: str, naam: str, vraag_word: bool) -> None:
    """Optionele Word-export van een Markdown-rapport (report_to_docx, Node.js)."""
    if vraag_word:
        try:
            a = input("  Ook als Word (.docx)? (j/n, standaard j): ").strip().lower()
        except EOFError:
            a = "j"
        if a.startswith("n"):
            return
    try:
        from report_to_docx import export_report_docx
        docx = md_pad[:-3] + ".docx"
        export_report_docx(md_tekst, docx, report_kind="facts", event_name=naam)
        print(f"  Word-rapport: {docx}")
    except Exception as e:
        print(f"  Word-export lukte niet ({e}); het Markdown-rapport staat er wel.")


def maak(bron, vraag_word: bool = True) -> list[str]:
    """Maak het rapport uit een rapportpakket (pad of al geladen dict).
    Geeft de paden van de gemaakte bestanden terug."""
    p = laad(bron) if not isinstance(bron, dict) else bron
    g = p["gegevens"]
    soort = p["soort"]
    stam = p["rapport_stam"]
    uit = []
    if soort == "hestia":
        from generate_event_report import generate_report
        md = stam + ".md"
        tekst = generate_report(output_path=md, **g)
        print(f"  Rapport: {md}")
        uit.append(md)
        _word(tekst, md, g.get("event_name", "HESTIA"), vraag_word)
    elif soort == "pyrox":
        from generate_pyrox_report import generate_pyrox_report
        md = stam + ".md"
        tekst = generate_pyrox_report(output_path=md, **g)
        print(f"  Rapport: {md}")
        uit.append(md)
        _word(tekst, md, g.get("event_name", "PYROX"), vraag_word)
    elif soort == "klimatos":
        from generate_klimatos_report import generate_klimatos_report
        md = stam + ".md"
        tekst = generate_klimatos_report(output_path=md, **g)
        print(f"  Rapport: {md}")
        uit.append(md)
        _word(tekst, md, g.get("event_name", "Klimatos"), vraag_word)
    elif soort == "loper":
        from hestia_loper_plots import maak_alle_plots
        from hestia_loper_rapport import maak_rapport
        from hestia_loper import exporteer_excel
        r = g["resultaat"]
        plots = maak_alle_plots(r, Path(stam + "_figuren"))
        docx = maak_rapport(r, plots, Path(stam + ".docx"))
        xlsx = exporteer_excel(r, Path(stam + ".xlsx"))
        print(f"  Rapport: {docx}\n  Gegevens: {xlsx}")
        uit += [str(docx), str(xlsx)]
    elif soort == "groep":
        import groep_lopers
        per = False
        if vraag_word:
            try:
                per = input("  Ook per loper een eigen rapport? (j/n, standaard n): ").strip().lower().startswith("j")
            except EOFError:
                per = False
        for x in groep_lopers.maak_uitvoer(g, Path(stam), per_loper=per):
            print(f"  {x}")
            uit.append(str(x))
    elif soort == "fitloop":
        import fit_loop
        docx = fit_loop.maak_rapport(g, Path(stam + ".docx"))
        print(f"  Rapport: {docx}")
        uit.append(str(docx))
    return uit
