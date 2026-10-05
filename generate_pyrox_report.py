"""
generate_pyrox_report.py -- PYROX population-strain event report generator
(rev1, 2026-08-30)

Same "facts only" philosophy as generate_event_report.py (one HESTIA run)
and generate_klimatos_report.py (one Klimatos climate-trend run): fixed
section order, no recommendations. This one covers PYROX's own output --
run_pyrox.py's assess_population() result -- and, unlike the other two,
embeds all six of PYROX's own plotting functions (pyrox_plots.py), each
with a plain-language caption explaining what it shows and how to read it.

Usage
-----
    from run_pyrox import assess_population
    from generate_pyrox_report import generate_pyrox_report

    report = assess_population(data, sheet="Forecast_7d",
                               group_names=list(TARGET_GROUPS.keys()))
    generate_pyrox_report(event_name="Amsterdam heatwave", pyrox_report=report,
                          output_path="pyrox_report.md", plot_dir="pyrox_plots_out")

Group selection for the plots (not run-specific config, computed from the
actual result every time): PYROX's own 23 groups cannot all fit legibly on
one trajectory/heatmap/regime plot, so a representative subset is chosen
from the DATA itself -- the most-affected groups (by margin to critical
strain, tie-broken by earliest emergency_day) plus the least-affected
group for contrast, capped at `n_representative_groups` (default 6). This
adapts to whatever groups/run are actually being reported, rather than a
fixed hard-coded list of names.
"""

from datetime import datetime, timezone
import os
import numpy as np


def _fmt(x, decimals=2, suffix=""):
    if x is None:
        return "n.b."
    try:
        if np.isnan(x):
            return "n.b."
    except (TypeError, ValueError):
        pass
    try:
        return f"{float(x):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(x)


def _select_representative_groups(groups: dict, n: int = 6):
    """
    Pick a legible subset of groups for the plots, computed from THIS run's
    actual results (not a fixed name list): rank every group by how close
    it came to its own critical_strain (smaller margin = more affected;
    an emergency_day that fired counts as the closest possible), take the
    n-1 most-affected, and add the single least-affected group for
    contrast -- so a reader always sees both ends of the spectrum, not
    just whichever groups happen to be alphabetically first.
    """
    def margin(res):
        if res.get("emergency_day") is not None:
            return -1000 + res["emergency_day"]  # emergency always ranks "closest"
        return res["critical_strain"] - res["peak_strain"]

    ranked = sorted(groups.items(), key=lambda kv: margin(kv[1]))
    most_affected = [name for name, _ in ranked[:max(1, n - 1)]]
    least_affected = ranked[-1][0]
    if least_affected not in most_affected:
        selected = most_affected + [least_affected]
    else:
        selected = most_affected
    return selected[:n]


def _most_vulnerable_group(groups: dict) -> str:
    """The single group with the smallest margin to its own critical_strain
    (an emergency_day counts as the smallest possible margin) -- used to
    pick which one group gets the detailed feedback-race plot."""
    def margin(res):
        if res.get("emergency_day") is not None:
            return -1000 + res["emergency_day"]
        return res["critical_strain"] - res["peak_strain"]
    return min(groups.items(), key=lambda kv: margin(kv[1]))[0]


def generate_pyrox_report(event_name: str,
                          pyrox_report: dict,
                          output_path: str,
                          plot_dir: str = None,
                          n_representative_groups: int = 6,
                          documented_reference: str = None) -> str:
    """
    Genereer een vast, feitelijk rapport uit een PYROX-populatierun
    (assess_population()'s eigen resultaat-dict) en schrijf het weg als
    Markdown, met alle zes PYROX-plots als losse PNG-bestanden ernaast en
    als `![...](...)`-referenties in de tekst (zichtbaar wanneer dit via
    report_to_docx.py naar Word wordt geëxporteerd).

    Parameters
    ----------
    event_name : str
    pyrox_report : dict
        Exact de dict die run_pyrox.assess_population() teruggeeft:
        {'city', 'sheet', 'dates', 'heat_loads', 'groups': {name: ...}}.
    output_path : str
        Waar het rapport als .md-bestand wordt weggeschreven.
    plot_dir : str, optional
        Map voor de PNG-bestanden. Standaard: dezelfde map als output_path.
    n_representative_groups : int
        Hoeveel groepen getoond worden in de trajectory/heatmap/regime-
        plots (zie _select_representative_groups()'s docstring voor de
        selectielogica -- niet vast, wordt per run herberekend).
    documented_reference : str, optional

    Returns
    -------
    str
        Het volledige rapport als tekst (ook weggeschreven naar output_path).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pyrox_plots import (plot_strain_trajectories, plot_feedback_race,
                             plot_paris_validation, plot_risk_heatmap,
                             plot_three_regimes, plot_forecast_uncertainty)

    if plot_dir is None:
        plot_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    os.makedirs(plot_dir, exist_ok=True)

    city = pyrox_report["city"]
    sheet = pyrox_report["sheet"]
    dates = pyrox_report.get("dates")
    heat_loads = pyrox_report["heat_loads"]
    groups = pyrox_report["groups"]
    n_groups_total = len(groups)

    forecast_start = None
    if sheet and "forecast" in sheet.lower():
        forecast_start = 0  # whole sheet is forecast -- no observed hindcast portion

    selected = _select_representative_groups(groups, n_representative_groups)
    most_vulnerable = _most_vulnerable_group(groups)

    lines = []
    A = lines.append

    A(f"# PYROX-rapport — {event_name}")
    A("")
    A(f"*Automatisch gegenereerd op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"door generate_pyrox_report.py (HESTIA-PYROX-Klimatos suite).*")
    A("")
    A("**Dit rapport bevat uitsluitend feitelijke, door het model berekende "
      "waarden en hun herkomst. Er zijn geen aanbevelingen of adviezen "
      "toegevoegd.**")
    A("")
    A("---")
    A("")

    # ------------------------------------------------------------------ #
    A("## 1. Gesimuleerd scenario")
    A("")
    A("| | |")
    A("|---|---|")
    A(f"| Plaats | {city} |")
    A(f"| Databron (sheet) | {sheet} |")
    A(f"| Aantal dagen | {len(heat_loads)} |")
    A(f"| Aantal populatiegroepen | {n_groups_total} |")
    A(f"| Hitteblootstelling per dag | {', '.join(f'{x:.2f}' for x in heat_loads)} |")
    if documented_reference:
        A(f"| Gedocumenteerd referentiecijfer | {documented_reference} |")
    A("")
    A("Model: PYROX, een control-theoretisch (geen fysiologisch) model van "
      "meerdaagse hitteopbouw per populatiegroep -- zie TECHNICAL_REFERENCE.md "
      "sectie 3 voor de volledige methodologie.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 2. Samenvatting per groep")
    A("")
    A("| Groep | Piekbelasting | Kritieke grens | Waarschuwing | Gevaar | Noodgeval |")
    A("|---|---|---|---|---|---|")
    for name, res in groups.items():
        A(f"| {res['group'].display_name} | {_fmt(res['peak_strain'], 3)} | "
          f"{_fmt(res['critical_strain'], 1)} | {res['caution_day'] if res['caution_day'] is not None else '-'} | "
          f"{res['danger_day'] if res['danger_day'] is not None else '-'} | "
          f"{res['emergency_day'] if res['emergency_day'] is not None else '-'} |")
    A("")
    A("Waarschuwing/gevaar/noodgeval: de dag waarop de cumulatieve belasting van "
      "die groep respectievelijk 50%, 75% en 95% van haar eigen kritieke grens "
      "overschrijdt (zie sectie 3 voor wat 'kritieke grens' hier concreet betekent). "
      "'-' betekent: deze grens werd in de gesimuleerde periode niet bereikt.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 3. Divergentie tussen groepen")
    A("")
    fig = plot_strain_trajectories(heat_loads, selected,
                                   f"PYROX — {event_name}",
                                   dates=dates, forecast_start=forecast_start)
    path = os.path.join(plot_dir, "pyrox_1_trajectories.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    A(f"![Belastingtrajecten per groep]({os.path.basename(path)})")
    A("")
    A("*Elke lijn is de opgebouwde belasting van één groep over de gesimuleerde "
      "periode, tegen dezelfde blootstelling (het grijze vlak op de achtergrond). "
      "Groepen met een zwakkere aanpassingscapaciteit lopen sneller op en komen "
      "dichter bij (of over) hun eigen kritieke grens -- terwijl een veerkrachtige "
      "groep bij precies dezelfde blootstelling stabiel blijft. Dat uiteenlopen "
      "zelf, niet een vast getal, is waar dit model om draait.*")
    A("")

    # ------------------------------------------------------------------ #
    A(f"## 4. Kwetsbaarste traject in detail — {groups[most_vulnerable]['group'].display_name}")
    A("")
    fig = plot_feedback_race(heat_loads, most_vulnerable, f"PYROX — {event_name}",
                             dates=dates, forecast_start=forecast_start)
    path = os.path.join(plot_dir, "pyrox_2_feedback_race.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    A(f"![De ene terugkoppelingslus voor de meest kwetsbare groep]({os.path.basename(path)})")
    A("")
    A("*Voor de groep die in deze run het dichtst bij haar eigen kritieke grens "
      "kwam. Hitteblootstelling werkt op twee manieren in: rechtstreeks op de "
      "opgebouwde belasting, en vertraagd via de acclimatisatie -- een dempend "
      "pad, geen lus op zichzelf. Er zit precies één gesloten lus in dit model: "
      "opgebouwde belasting onderdrukt de acclimatisatie, wat de belasting verder "
      "opjaagt -- een zichzelf-versterkende spiraal, geen wedloop tussen twee "
      "gelijkwaardige processen. De gearceerde kloof tussen het gestippelde "
      "acclimatisatiepotentieel en de doorgetrokken effectieve acclimatisatie is "
      "die lus in actie: waar die kloof toeneemt, wint de belasting terrein.*")
    A("")

    # ------------------------------------------------------------------ #
    A("## 5. Risico-overzicht per dag")
    A("")
    fig = plot_risk_heatmap(heat_loads, selected, f"PYROX — {event_name}",
                            dates=dates, forecast_start=forecast_start)
    path = os.path.join(plot_dir, "pyrox_3_heatmap.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    A(f"![Risicozones per groep per dag]({os.path.basename(path)})")
    A("")
    A("*Elke rij is een groep, elke kolom een dag; de kleur toont in welke zone "
      "die groep die dag zit (veilig / waarschuwing / gevaar / noodgeval -- "
      "dezelfde grenzen als in sectie 2's tabel). Groepen zijn geordend van "
      "veerkrachtig naar kwetsbaar, zodat in één oogopslag zichtbaar is wie "
      "wanneer risico loopt, zonder de losse lijnen van sectie 3 te hoeven "
      "ontwarren.*")
    A("")

    # ------------------------------------------------------------------ #
    if forecast_start is not None:
        A("## 6. Onzekerheid in de voorspelling")
        A("")
        fig = plot_forecast_uncertainty(heat_loads, selected, f"PYROX — {event_name}",
                                        dates=dates, forecast_start=forecast_start)
        path = os.path.join(plot_dir, "pyrox_4_uncertainty.png")
        fig.savefig(path, dpi=140, bbox_inches="tight")
        plt.close(fig)
        A(f"![Belastingtrajecten met onzekerheidsband]({os.path.basename(path)})")
        A("")
        A("*Een weersvoorspelling een paar dagen vooruit draagt een reële "
          "temperatuuronzekerheid (hier ±2 graden). Dit vertaalt zich naar een "
          "band rond elk traject: waar de band smal is, staat de uitkomst "
          "redelijk vast; waar de band breed is, hangt het resultaat sterk af "
          "van hoe het weer zich daadwerkelijk ontwikkelt -- precies het "
          "onderscheid dat relevant is voor een besluit vooraf. Deze band geldt "
          "alleen voor het voorspelde deel; eventuele reeds waargenomen dagen "
          "hebben geen band.*")
        A("")

    # ------------------------------------------------------------------ #
    A("## 7. De drie gedragsregimes")
    A("")
    regime_groups = selected[:3] if len(selected) >= 3 else selected
    fig = plot_three_regimes(regime_groups)
    path = os.path.join(plot_dir, "pyrox_5_regimes.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    A(f"![De drie regimes: dode zone, stabiele opbouw, op hol]({os.path.basename(path)})")
    A("")
    A("*Dit toont, los van de specifieke dagen uit dit rapport, hoe elke groep "
      "zich in theorie gedraagt bij een constante hitteblootstelling: bij een "
      "lage belasting stabiliseert de belasting vanzelf (de 'dode zone'); bij "
      "een hogere belasting blijft de belasting oplopen maar bereikt een stabiel "
      "evenwicht; voorbij een bepaalde drempel loopt de belasting ongecontroleerd "
      "op ('op hol'). Een kwetsbaardere groep heeft die omslagdrempel al bij een "
      "lagere belasting liggen dan een veerkrachtige groep -- dat verschil in "
      "drempel, niet in absolute waarde, is wat kwetsbaarheid in dit model betekent.*")
    A("")

    # ------------------------------------------------------------------ #
    A("## 8. Modelvalidatie (Parijs, augustus 2003)")
    A("")
    fig = plot_paris_validation()
    path = os.path.join(plot_dir, "pyrox_6_paris_validation.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    A(f"![PYROX tegen de waargenomen Franse oversterfte, augustus 2003]({os.path.basename(path)})")
    A("")
    A("*Dit is geen resultaat van de hierboven gesimuleerde periode, maar een "
      "vast referentiepunt: hoe PYROX's belastingopbouw voor oudere groepen "
      "zich verhoudt tot de daadwerkelijk waargenomen, dagelijkse oversterfte "
      "tijdens de Franse hittegolf van augustus 2003 (Fouillet et al. 2006). "
      "Volgt de vorm en timing van de opbouw de waargenomen curve, dan reproduceert "
      "het model dat concrete, historische evenement.*")
    A("")

    # ------------------------------------------------------------------ #
    A("## 9. Herkomst en status van dit model")
    A("")
    A("| | |")
    A("|---|---|")
    A("| Model | PYROX (control-theoretisch, geen fysiologische simulatie) |")
    A("| Bron | de Boer, K. (2026), Research Square, "
      "https://doi.org/10.21203/rs.3.rs-8626369/v1 |")
    A(f"| Aantal populatiegroepen in deze suite | {n_groups_total} |")
    A("")
    A("**Beperkingen, expliciet:** de meeste van de 23 groepen zijn in de "
      "broncode zelf gelabeld als illustratieve, niet-gevalideerde "
      "parameterschattingen -- geen gemeten constanten. Alleen de "
      "onderliggende twee-lussen-structuur is empirisch getoetst (tegen het "
      "leeftijdsgegradeerde patroon van de Franse hittegolf 2003, sectie 8). "
      "Geen onafhankelijke, externe peer review van dit specifieke traject.")
    A("")
    A("*Einde rapport.*")

    text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    return text
