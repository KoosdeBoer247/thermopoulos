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
actual result every time): PYROX's own 19 groups cannot all fit legibly on
one trajectory/heatmap/regime plot, so a representative subset is chosen
from the DATA itself -- the most-affected groups (by margin to critical
strain, tie-broken by earliest emergency_day) plus the least-affected
group for contrast, capped at `n_representative_groups` (default 6). This
adapts to whatever groups/run are actually being reported, rather than a
fixed hard-coded list of names.
"""

from taal import vt, getal


from datetime import datetime, timezone
import os
import numpy as np


def _fmt(x, decimals=2, suffix=""):
    if x is None:
        return vt("n.b.", "n/a")
    try:
        if np.isnan(x):
            return vt("n.b.", "n/a")
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

    A(vt(f"# PYROX-rapport — {event_name}", f"# PYROX report — {event_name}"))
    A("")
    A(vt(f"*Automatisch gegenereerd op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"door generate_pyrox_report.py (HESTIA-PYROX-Klimatos suite).*",
         f"*Automatically generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"by generate_pyrox_report.py (HESTIA-PYROX-Klimatos suite).*"))
    A("")
    A(vt("**Dit rapport bevat uitsluitend feitelijke, door het model berekende "
      "waarden en hun herkomst. Er zijn geen aanbevelingen of adviezen "
      "toegevoegd.**",
         "**This report contains only factual values calculated by the model "
      "and their provenance. No recommendations or advice "
      "have been added.**"))
    A("")
    A("---")
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 1. Gesimuleerd scenario", "## 1. Simulated scenario"))
    A("")
    A("| | |")
    A("|---|---|")
    A(vt(f"| Plaats | {city} |", f"| Location | {city} |"))
    A(vt(f"| Databron (sheet) | {sheet} |", f"| Data source (sheet) | {sheet} |"))
    A(vt(f"| Aantal dagen | {len(heat_loads)} |", f"| Number of days | {len(heat_loads)} |"))
    A(vt(f"| Aantal populatiegroepen | {n_groups_total} |", f"| Number of population groups | {n_groups_total} |"))
    A(vt(f"| Hitteblootstelling per dag | {', '.join(f'{x:.2f}' for x in heat_loads)} |", f"| Heat exposure per day | {', '.join(f'{x:.2f}' for x in heat_loads)} |"))
    _nr = pyrox_report.get("nocturnal_recovery", False)
    A(vt(f"| Nachtelijk herstel | "
      f"{'telt mee: herstel volgens het minimum van de nacht na elke dag (zie sectie 2b)' if _nr else 'NIET meegeteld (volledig herstel elke nacht; alleen voor vergelijking met de paper)'} |",
         f"| Night-time recovery | "
      f"{'counted: recovery according to the minimum of the night after each day (see section 2b)' if _nr else 'NOT counted (full recovery every night; only for comparison with the paper)'} |"))
    if documented_reference:
        A(vt(f"| Gedocumenteerd referentiecijfer | {documented_reference} |", f"| Documented reference figure | {documented_reference} |"))
    A("")
    A(vt("Model: PYROX, een control-theoretisch (geen fysiologisch) model van "
      "meerdaagse hitteopbouw per populatiegroep -- zie TECHNICAL_REFERENCE.md "
      "sectie 3 voor de volledige methodologie.",
         "Model: PYROX, a control-theoretic (not physiological) model of "
      "multi-day heat build-up per population group -- see TECHNICAL_REFERENCE.md "
      "section 3 for the full methodology."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 2. Samenvatting per groep", "## 2. Summary per group"))
    A("")
    A(vt("| Groep | Piekbelasting | Kritieke grens | Waarschuwing | Gevaar | Noodgeval |", "| Group | Peak strain | Critical limit | Caution | Danger | Emergency |"))
    A("|---|---|---|---|---|---|")
    for name, res in groups.items():
        A(f"| {res['group'].display_name} | {_fmt(res['peak_strain'], 3)} | "
          f"{_fmt(res['critical_strain'], 1)} | {res['caution_day'] if res['caution_day'] is not None else '-'} | "
          f"{res['danger_day'] if res['danger_day'] is not None else '-'} | "
          f"{res['emergency_day'] if res['emergency_day'] is not None else '-'} |")
    A("")
    A(vt("Waarschuwing/gevaar/noodgeval: de dag waarop de cumulatieve belasting van "
      "die groep respectievelijk 50%, 75% en 90% van haar eigen kritieke grens "
      "overschrijdt (zie sectie 3 voor wat 'kritieke grens' hier concreet betekent). "
      "'-' betekent: deze grens werd in de gesimuleerde periode niet bereikt.",
         "Caution/danger/emergency: the day on which the cumulative strain of "
      "that group exceeds 50%, 75% and 90% of its own critical limit respectively "
      "(see section 3 for what 'critical limit' concretely means here). "
      "'-' means: this limit was not reached in the simulated period."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 2b. Nachten", "## 2b. Nights"))
    A("")
    A(vt("Het herstel na elke dag hangt af van het minimum van de nacht erna "
      "(18:00–08:00 lokale tijd): slaapkwaliteit 1,0 bij 18 °C of koeler, lineair "
      "dalend tot 0,4 bij 26 °C of warmer (thermopoulos_loader.night_sleep_quality). "
      "Warme nachten remmen dus het herstel; dit telt in alle resultaten en grafieken mee.",
         "The recovery after each day depends on the minimum of the night after "
      "(18:00–08:00 local time): sleep quality 1.0 at 18 °C or cooler, decreasing "
      "linearly to 0.4 at 26 °C or warmer (thermopoulos_loader.night_sleep_quality). "
      "Warm nights thus hamper recovery; this counts in all results and charts."))
    A("")
    _tn = pyrox_report.get("t_night_min") or [None] * len(heat_loads)
    _q = pyrox_report.get("sleep_quality") or [1.0] * len(heat_loads)
    _days = dates if dates else [str(i + 1) for i in range(len(heat_loads))]
    A(vt("| Dag | Nachtminimum erna (°C) | Slaapkwaliteit |", "| Day | Night minimum after (°C) | Sleep quality |"))
    A("|---|---|---|")
    for d, tn, q in zip(_days, _tn, _q):
        A(f"| {d} | {_fmt(tn, 1) if tn is not None and tn == tn else vt('n.b. (laatste dag: eigen dagminimum)', 'n/a (last day: own day minimum)')} | {_fmt(q, 2)} |")
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 3. Divergentie tussen groepen", "## 3. Divergence between groups"))
    A("")
    _sq = pyrox_report.get("sleep_quality")
    fig = plot_strain_trajectories(heat_loads, selected,
                                   f"PYROX — {event_name}",
                                   dates=dates, forecast_start=forecast_start, sleep_quality=_sq)
    path = os.path.join(plot_dir, "pyrox_1_trajectories.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    A(vt(f"![Belastingtrajecten per groep]({os.path.basename(path)})", f"![Strain trajectories per group]({os.path.basename(path)})"))
    A("")
    A(vt("*Elke lijn is de opgebouwde belasting van één groep over de gesimuleerde "
      "periode, tegen dezelfde blootstelling (het grijze vlak op de achtergrond). "
      "Groepen met een zwakkere aanpassingscapaciteit lopen sneller op en komen "
      "dichter bij (of over) hun eigen kritieke grens -- terwijl een veerkrachtige "
      "groep bij precies dezelfde blootstelling stabiel blijft. Dat uiteenlopen "
      "zelf, niet een vast getal, is waar dit model om draait.*",
         "*Each line is the accumulated strain of one group over the simulated "
      "period, against the same exposure (the grey area in the background). "
      "Groups with a weaker adaptive capacity rise faster and come "
      "closer to (or over) their own critical limit -- while a resilient "
      "group stays stable at exactly the same exposure. That divergence "
      "itself, not a fixed number, is what this model is about.*"))
    A("")

    # ------------------------------------------------------------------ #
    A(vt(f"## 4. Kwetsbaarste traject in detail — {groups[most_vulnerable]['group'].display_name}", f"## 4. Most vulnerable trajectory in detail — {groups[most_vulnerable]['group'].display_name}"))
    A("")
    fig = plot_feedback_race(heat_loads, most_vulnerable, f"PYROX — {event_name}",
                             dates=dates, forecast_start=forecast_start, sleep_quality=_sq)
    path = os.path.join(plot_dir, "pyrox_2_feedback_race.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    A(vt(f"![De ene terugkoppelingslus voor de meest kwetsbare groep]({os.path.basename(path)})", f"![The single feedback loop for the most vulnerable group]({os.path.basename(path)})"))
    A("")
    A(vt("*Voor de groep die in deze run het dichtst bij haar eigen kritieke grens "
      "kwam. Hitteblootstelling werkt op twee manieren in: rechtstreeks op de "
      "opgebouwde belasting, en vertraagd via de acclimatisatie -- een dempend "
      "pad, geen lus op zichzelf. Er zit precies één gesloten lus in dit model: "
      "opgebouwde belasting onderdrukt de acclimatisatie, wat de belasting verder "
      "opjaagt -- een zichzelf-versterkende spiraal, geen wedloop tussen twee "
      "gelijkwaardige processen. De gearceerde kloof tussen het gestippelde "
      "acclimatisatiepotentieel en de doorgetrokken effectieve acclimatisatie is "
      "die lus in actie: waar die kloof toeneemt, wint de belasting terrein.*",
         "*For the group that came closest to its own critical limit in this run. "
      "Heat exposure acts in two ways: directly on the "
      "accumulated strain, and delayed via acclimatisation -- a damping "
      "path, not a loop of its own. There is exactly one closed loop in this model: "
      "accumulated strain suppresses acclimatisation, which drives the strain further "
      "up -- a self-reinforcing spiral, not a race between two "
      "equal processes. The shaded gap between the dotted "
      "acclimatisation potential and the solid effective acclimatisation is "
      "that loop in action: where the gap widens, strain gains ground.*"))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 5. Risico-overzicht per dag", "## 5. Risk overview per day"))
    A("")
    fig = plot_risk_heatmap(heat_loads, selected, f"PYROX — {event_name}",
                            dates=dates, forecast_start=forecast_start, sleep_quality=_sq)
    path = os.path.join(plot_dir, "pyrox_3_heatmap.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    A(vt(f"![Risicozones per groep per dag]({os.path.basename(path)})", f"![Risk zones per group per day]({os.path.basename(path)})"))
    A("")
    A(vt("*Elke rij is een groep, elke kolom een dag; de kleur toont in welke zone "
      "die groep die dag zit (veilig / waarschuwing / gevaar / noodgeval -- "
      "dezelfde grenzen als in sectie 2's tabel). Groepen zijn geordend van "
      "veerkrachtig naar kwetsbaar, zodat in één oogopslag zichtbaar is wie "
      "wanneer risico loopt, zonder de losse lijnen van sectie 3 te hoeven "
      "ontwarren.*",
         "*Each row is a group, each column a day; the colour shows which zone "
      "that group is in that day (safe / caution / danger / emergency -- "
      "the same limits as in the table of section 2). Groups are ordered from "
      "resilient to vulnerable, so that at a glance it is visible who "
      "is at risk when, without having to untangle the separate lines of section 3.*"))
    A("")

    # ------------------------------------------------------------------ #
    if forecast_start is not None:
        A(vt("## 6. Onzekerheid in de voorspelling", "## 6. Uncertainty in the forecast"))
        A("")
        fig = plot_forecast_uncertainty(heat_loads, selected, f"PYROX — {event_name}",
                                        dates=dates, forecast_start=forecast_start, sleep_quality=_sq)
        path = os.path.join(plot_dir, "pyrox_4_uncertainty.png")
        fig.savefig(path, dpi=140, bbox_inches="tight")
        plt.close(fig)
        A(vt(f"![Belastingtrajecten met onzekerheidsband]({os.path.basename(path)})", f"![Strain trajectories with uncertainty band]({os.path.basename(path)})"))
        A("")
        A(vt("*Een weersvoorspelling een paar dagen vooruit draagt een reële "
          "temperatuuronzekerheid (hier ±2 graden). Dit vertaalt zich naar een "
          "band rond elk traject: waar de band smal is, staat de uitkomst "
          "redelijk vast; waar de band breed is, hangt het resultaat sterk af "
          "van hoe het weer zich daadwerkelijk ontwikkelt -- precies het "
          "onderscheid dat relevant is voor een besluit vooraf. Deze band geldt "
          "alleen voor het voorspelde deel; eventuele reeds waargenomen dagen "
          "hebben geen band.*",
             "*A weather forecast a few days ahead carries a real "
          "temperature uncertainty (here ±2 degrees). This translates into a "
          "band around each trajectory: where the band is narrow, the outcome is "
          "fairly certain; where the band is wide, the result depends strongly "
          "on how the weather actually develops -- exactly the "
          "distinction that matters for a decision in advance. This band applies "
          "only to the forecast part; any days already observed "
          "have no band.*"))
        A("")

    # ------------------------------------------------------------------ #
    A(vt("## 7. De drie gedragsregimes", "## 7. The three behavioural regimes"))
    A("")
    regime_groups = selected[:3] if len(selected) >= 3 else selected
    fig = plot_three_regimes(regime_groups)
    path = os.path.join(plot_dir, "pyrox_5_regimes.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    A(vt(f"![De drie regimes: dode zone, stabiele opbouw, op hol]({os.path.basename(path)})", f"![The three regimes: dead zone, stable build-up, runaway]({os.path.basename(path)})"))
    A("")
    A(vt("*Dit toont, los van de specifieke dagen uit dit rapport, hoe elke groep "
      "zich in theorie gedraagt bij een constante hitteblootstelling: bij een "
      "lage belasting stabiliseert de belasting vanzelf (de 'dode zone'); bij "
      "een hogere belasting blijft de belasting oplopen maar bereikt een stabiel "
      "evenwicht; voorbij een bepaalde drempel loopt de belasting ongecontroleerd "
      "op ('op hol'). Een kwetsbaardere groep heeft die omslagdrempel al bij een "
      "lagere belasting liggen dan een veerkrachtige groep -- dat verschil in "
      "drempel, niet in absolute waarde, is wat kwetsbaarheid in dit model betekent.*",
         "*This shows, apart from the specific days of this report, how each group "
      "behaves in theory at a constant heat exposure: at a "
      "low load the strain stabilises by itself (the 'dead zone'); at "
      "a higher load the strain keeps rising but reaches a stable "
      "equilibrium; beyond a certain threshold the strain rises uncontrolled "
      "('runaway'). A more vulnerable group has that tipping threshold at a "
      "lower load than a resilient group -- that difference in "
      "threshold, not in absolute value, is what vulnerability means in this model.*"))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 8. Modelvalidatie (Parijs, augustus 2003)", "## 8. Model validation (Paris, August 2003)"))
    A("")
    fig = plot_paris_validation()
    path = os.path.join(plot_dir, "pyrox_6_paris_validation.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    A(vt(f"![PYROX tegen de waargenomen Franse oversterfte, augustus 2003]({os.path.basename(path)})", f"![PYROX against the observed French excess mortality, August 2003]({os.path.basename(path)})"))
    A("")
    A(vt("*Dit is geen resultaat van de hierboven gesimuleerde periode, maar een "
      "vast referentiepunt: hoe PYROX's belastingopbouw voor oudere groepen "
      "zich verhoudt tot de daadwerkelijk waargenomen, dagelijkse oversterfte "
      "tijdens de Franse hittegolf van augustus 2003 (Fouillet et al. 2006). "
      "Volgt de vorm en timing van de opbouw de waargenomen curve, dan reproduceert "
      "het model dat concrete, historische evenement. Doorgetrokken lijnen: met "
      "nachtelijk herstel volgens de gemeten nachtminima van Paris-Montsouris (nacht na "
      "elke dag), zoals in alle resultaten van de suite; gestippeld: zonder, de aanname "
      "van de oorspronkelijke paper. Met nachtelijk herstel bereikt de groep 65-85 jaar "
      "de kritieke grens op dag 9 in plaats van 10; de groep 85+ blijft op dag 5. De vorm "
      "van de opbouw verandert nauwelijks (correlatie met de oversterfte 0,83 in beide "
      "gevallen).*",
         "*This is not a result of the period simulated above, but a "
      "fixed reference point: how PYROX's strain build-up for older groups "
      "compares with the actually observed daily excess mortality "
      "during the French heatwave of August 2003 (Fouillet et al. 2006). "
      "If the shape and timing of the build-up follow the observed curve, the "
      "model reproduces that concrete, historical event. Solid lines: with "
      "night-time recovery according to the measured night minima of Paris-Montsouris (night after "
      "each day), as in all results of the suite; dotted: without, the assumption "
      "of the original paper. With night-time recovery the 65-85 group reaches "
      "the critical limit on day 9 instead of 10; the 85+ group stays at day 5. The shape "
      "of the build-up hardly changes (correlation with excess mortality 0.83 in both "
      "cases).*"))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 9. Herkomst en status van dit model", "## 9. Provenance and status of this model"))
    A("")
    A("| | |")
    A("|---|---|")
    A(vt("| Model | PYROX (control-theoretisch, geen fysiologische simulatie) |", "| Model | PYROX (control-theoretic, not a physiological simulation) |"))
    A(vt("| Bron | de Boer, K. (2026), Research Square, "
      "https://doi.org/10.21203/rs.3.rs-8626369/v1 |",
         "| Source | de Boer, K. (2026), Research Square, "
      "https://doi.org/10.21203/rs.3.rs-8626369/v1 |"))
    A(vt(f"| Aantal populatiegroepen in deze suite | {n_groups_total} |", f"| Number of population groups in this suite | {n_groups_total} |"))
    A("")
    A(vt("**Beperkingen, expliciet:** de meeste van de 19 groepen zijn in de "
      "broncode zelf gelabeld als illustratieve, niet-gevalideerde "
      "parameterschattingen -- geen gemeten constanten. Alleen de "
      "onderliggende twee-lussen-structuur is empirisch getoetst (tegen het "
      "leeftijdsgegradeerde patroon van de Franse hittegolf 2003, sectie 8). "
      "Geen onafhankelijke, externe peer review van dit specifieke traject.",
         "**Limitations, explicitly:** most of the 19 groups are labelled in the "
      "source code itself as illustrative, non-validated "
      "parameter estimates -- not measured constants. Only the "
      "underlying two-loop structure has been tested empirically (against the "
      "age-graded pattern of the French heatwave 2003, section 8). "
      "No independent, external peer review of this specific trajectory."))
    A("")
    A(vt("*Einde rapport.*", "*End of report.*"))

    text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    return text
