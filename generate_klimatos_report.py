"""
generate_klimatos_report.py -- Klimatos.ClimateShift event report generator
(rev1, 2026-08-27)

Genereert een vast, feitelijk rapport uit de uitkomst van een Klimatos-run
(Klimatos_ClimateShift.main()'s eigen resultaat-DataFrames -- dezelfde
DataFrames die save_results() al naar Excel schrijft). Zelfde doel en
dezelfde stijlregels als generate_event_report.py (het HESTIA-rapport):
organisaties en hulpverlening kunnen zelf conclusies trekken uit de cijfers
-- dit rapport bevat daarom uitsluitend feitelijke, door het model
berekende waarden en hun herkomst, geen aanbevelingen, adviezen of
interpretatie van wat er "zou moeten" gebeuren.

Waar het HESTIA-rapport één specifieke populatie-Monte-Carlo-run beschrijft
(thermische/cardiovasculaire uitkomsten op één moment), beschrijft dit
rapport een KLIMAATTREND: jaarlijkse extremen over decennia, een
evenement-venster met projecties, en (indien ingeschakeld) de EHS/EHE/
klinisch-criterium-evolutie daarvan. Andere inhoud, dezelfde vaste
structuur en toon.

Gebruik
-------
    from generate_klimatos_report import generate_klimatos_report

    generate_klimatos_report(
        event_name="Utrecht Marathon",
        meta=meta, annual=annual, ref_window=ref_window,
        latest_window=windows[-1] if windows else ref_window,
        event_df=event_df, ehs_df=ehs_df,
        admissions_df=admissions_df, liveability_df=liveability_df,
        accel_df=accel_df, ehs_evolution_res=ehs_res,
        output_path="rapport_utrecht_marathon.md",
    )

Het sjabloon is vast (dezelfde secties, dezelfde volgorde, ongeacht stad of
evenement) zodat rapporten van verschillende steden/evenementen direct
naast elkaar te leggen zijn -- en naast een HESTIA-rapport, gezien beide
generators dezelfde opmaakconventies delen.
"""

from taal import vt, getal, duizend


def _sg(x, d=2) -> str:
    """Getal met teken (+/-) en de decimale komma van de taal."""
    return ("+" if x >= 0 else "") + getal(x, d)


from datetime import datetime, timezone
import numpy as np
import pandas as pd


def _fmt(x, decimals=2, suffix=""):
    """Format a scalar as text. Returns 'n.b.' (niet beschikbaar) if the
    value is missing/NaN. Identical convention to generate_event_report.py's
    own _fmt(), so numbers read the same way across both report types."""
    if x is None:
        return vt("n.b.", "n/a")
    try:
        if pd.isna(x):
            return vt("n.b.", "n/a")
    except (TypeError, ValueError):
        pass
    try:
        return f"{getal(float(x), decimals)}{suffix}"
    except (TypeError, ValueError):
        return str(x)


def _window_row(df: pd.DataFrame, window_label: str):
    """Pick the row for a given 'YYYY-YYYY' window label out of a windowed
    summary DataFrame (admissions_df / liveability_df share this shape).
    Returns None if the window or the DataFrame itself is absent."""
    if df is None or df.empty or "window" not in df.columns:
        return None
    match = df[df["window"] == window_label]
    return match.iloc[0] if not match.empty else None


def _embed_plot(A, plot_paths, filename, caption):
    """
    Insert one plot + caption if a path ending in `filename` is present in
    plot_paths; do nothing (no placeholder, no "missing" note) if not --
    the caller's own per-section "not generated for this run" fallback
    (see generate_klimatos_report()'s own pattern) already covers absence
    at the section level, so a per-plot miss inside an otherwise-present
    section should just be silently skipped rather than duplicating that
    message plot-by-plot.
    """
    import os as _os
    match = next((p for p in plot_paths if _os.path.basename(p) == filename), None)
    if match is None:
        return False
    A(f"![{filename}]({filename})")
    A("")
    A(f"*{caption}*")
    A("")
    return True


def generate_klimatos_report(event_name: str,
                              meta: dict,
                              annual: pd.DataFrame,
                              ref_window: tuple,
                              latest_window: tuple,
                              output_path: str,
                              event_df: pd.DataFrame = None,
                              ehs_df: pd.DataFrame = None,
                              admissions_df: pd.DataFrame = None,
                              liveability_df: pd.DataFrame = None,
                              liveability_hours_df: pd.DataFrame = None,
                              liveability_proj_df: pd.DataFrame = None,
                              accel_df: pd.DataFrame = None,
                              ehs_evolution_res: dict = None,
                              documented_reference: str = None,
                              plot_paths: list = None) -> str:
    """
    Genereer een vast, feitelijk rapport uit een Klimatos-klimaattrendrun en
    schrijf het weg als Markdown.

    Parameters
    ----------
    event_name : str
        Vrije naam voor dit rapport (bijv. "Utrecht Marathon" of gewoon de
        stadsnaam voor een rapport zonder specifiek evenement).
    meta : dict
        Metadata-dict zoals Klimatos_ClimateShift.main() die zelf al
        opbouwt vlak voor save_results() (stad, coördinaten, UHI-status,
        referentieperiode, analyseperiode, event_window-beschrijving, ...).
    annual : pd.DataFrame
        De jaarlijkse-extremen-DataFrame (index = jaar), dezelfde die naar
        het 'Annual_Maxima'-Excel-tabblad gaat.
    ref_window, latest_window : tuple
        (start, eind) van de referentieperiode resp. het meest recente
        schuifvenster, voor de "referentie vs recent"-vergelijking in
        sectie 2.
    output_path : str
        Waar het rapport als .md-bestand wordt weggeschreven.
    event_df, ehs_df, admissions_df, liveability_df, accel_df : pd.DataFrame, optional
        Dezelfde optionele DataFrames als save_results() accepteert. Elke
        ontbrekende (None of leeg) DataFrame laat de bijbehorende sectie
        expliciet "niet beschikbaar voor deze run" vermelden, in plaats van
        de sectie stilzwijgend over te slaan of cijfers te verzinnen.
    ehs_evolution_res : dict, optional
        De ruwe resultaat-dict van run_ehs_evolution() (niet ehs_df zelf),
        nodig voor de marge-tot-drempel-analyse in sectie 7 -- dezelfde
        margin_to_threshold_stats()-achtige berekening als sectie 9 van het
        HESTIA-rapport, hier lokaal herberekend (zie de docstring van
        _local_margin_stats hieronder voor waarom dit een eigen kopie is in
        plaats van een import: Klimatos moet blijven werken zonder HESTIA
        aanwezig, dus kan niet hard uit hestia_bridge importeren).
    documented_reference : str, optional
        Vrije tekst met een gedocumenteerd, werkelijk incidentiecijfer voor
        dit evenement, indien bekend. Puur ter feitelijke vermelding naast
        de modeluitkomst -- geen vergelijking of oordeel wordt toegevoegd.
    plot_paths : list, optional
        [2026-09-01] Padnamen van al gegenereerde PNG-bestanden, zoals
        Klimatos_ClimateShift.py's eigen main() teruggeeft (dezelfde lijst
        die de "Plots:"-regel in de consoleuitvoer al gebruikt). Klimatos
        genereert er potentieel 40+ per run (6 plots x 4 variabelen alleen al
        voor sectie 2) -- te veel om allemaal 1-op-1 in te sluiten zoals bij
        het HESTIA-rapport. In plaats daarvan wordt bewust EEN, het meest
        informatieve plottype per relevante sectie gekozen (zie
        _match_plot()'s eigen patronen hieronder): de tijdreeks-plot per
        variabele in sectie 2, de versnellingscheck in sectie 3, de
        evenement-venster-trend per variabele in sectie 4, de EHS-evolutie
        in sectie 5, de T_rect/CO_reserve-spreidingsplot in sectie 7, de
        ziekenhuisopnames-verhouding in sectie 8, en de leefbaarheidsbalk in
        sectie 9. None of een lege lijst laat elke sectie een "niet
        gegenereerd voor deze run"-vermelding tonen, net als bij het
        HESTIA-rapport.

    Returns
    -------
    str
        Het volledige rapport als tekst (ook weggeschreven naar output_path).
    """
    ref_label = f"{ref_window[0]}-{ref_window[1]}"
    latest_label = f"{latest_window[0]}-{latest_window[1]}"

    lines = []
    A = lines.append

    A(vt(f"# Klimatos-rapport — {event_name}", f"# Klimatos report — {event_name}"))
    A("")
    A(vt(f"*Automatisch gegenereerd op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"door generate_klimatos_report.py (HESTIA-PYROX suite).*",
         f"*Automatically generated on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"by generate_klimatos_report.py (HESTIA-PYROX suite).*"))
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
    A(vt(f"| Naam | {event_name} |", f"| Name | {event_name} |"))
    A(vt(f"| Plaats | {meta.get('city', 'n.b.')} ({_fmt(meta.get('latitude'), 4)}, "
      f"{_fmt(meta.get('longitude'), 4)}) |",
         f"| Location | {meta.get('city', 'n/a')} ({_fmt(meta.get('latitude'), 4)}, "
      f"{_fmt(meta.get('longitude'), 4)}) |"))
    if meta.get("population"):
        A(vt(f"| Inwonertal | {duizend(meta['population'])} |", f"| Population | {duizend(meta['population'])} |"))
    A(vt(f"| Stedelijk hitte-eiland (UHI) | {'aan' if meta.get('apply_uhi') else 'uit'} |", f"| Urban heat island (UHI) | {'on' if meta.get('apply_uhi') else 'off'} |"))
    A(vt(f"| Referentieperiode | {meta.get('reference_period', ref_label)} |", f"| Reference period | {meta.get('reference_period', ref_label)} |"))
    A(vt(f"| Analyseperiode | {meta.get('analysis_start', 'n.b.')}-{meta.get('analysis_end', 'n.b.')} |", f"| Analysis period | {meta.get('analysis_start', 'n/a')}-{meta.get('analysis_end', 'n/a')} |"))
    A(vt(f"| Schuifvenster | {meta.get('window_length', 'n.b.')} jaar, "
      f"stap {meta.get('window_step', 'n.b.')} jaar |",
         f"| Sliding window | {meta.get('window_length', 'n/a')} years, "
      f"step {meta.get('window_step', 'n/a')} years |"))
    if meta.get("event_window"):
        A(vt(f"| Evenement-venster | {meta['event_window']} |", f"| Event window | {meta['event_window']} |"))
    if documented_reference:
        A(vt(f"| Gedocumenteerd referentiecijfer voor dit evenement | {documented_reference} |", f"| Documented reference figure for this event | {documented_reference} |"))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 2. Jaarlijkse extremen (referentie vs recent)", "## 2. Annual extremes (reference vs recent)"))
    A("")
    A(vt(f"Vergelijking tussen de referentieperiode ({ref_label}) en het meest "
      f"recente schuifvenster ({latest_label}), per variabele.",
         f"Comparison between the reference period ({ref_label}) and the most "
      f"recent sliding window ({latest_label}), per variable."))
    A("")
    var_labels = {
        "T_air_max": vt("Luchttemperatuur (T_air_max)", "Air temperature (T_air_max)"),
        "WBT_max": vt("Natte-boltemperatuur (WBT_max)", "Wet-bulb temperature (WBT_max)"),
        "WBGT_max": "WBGT (WBGT_max)",
        "UTCI_max": "UTCI (UTCI_max)",
    }
    if annual is not None and not annual.empty:
        A(vt("| Variabele | Referentie-gemiddelde | Recent-gemiddelde | Verschil |", "| Variable | Reference mean | Recent mean | Difference |"))
        A("|---|---|---|---|")
        for col, label in var_labels.items():
            if col not in annual.columns:
                continue
            s = annual[col]
            ref_mean = s[(s.index >= ref_window[0]) & (s.index <= ref_window[1])].dropna().mean()
            lat_mean = s[(s.index >= latest_window[0]) & (s.index <= latest_window[1])].dropna().mean()
            diff = lat_mean - ref_mean if pd.notna(ref_mean) and pd.notna(lat_mean) else np.nan
            A(f"| {label} | {_fmt(ref_mean, 2, ' °C')} | {_fmt(lat_mean, 2, ' °C')} | "
              f"{_fmt(diff, 2, ' °C') if pd.isna(diff) else f'{_sg(diff, 2)} °C'} |")
        A("")
        if plot_paths:
            any_shown = False
            for col, label in var_labels.items():
                shown = _embed_plot(
                    A, plot_paths, f"plot_{col}_timeseries_trend.png",
                    vt(f"Jaarlijkse extreemwaarde van {label} per jaar (punten), met de "
                    f"Theil-Sen-trendlijn en of die trend statistisch significant is "
                    f"(Mann-Kendall-toets), plus de referentieperiode "
                    f"({ref_label}) als vergelijkingsband.",
                       f"Annual extreme value of {label} per year (points), with the "
                    f"Theil-Sen trend line and whether that trend is statistically significant "
                    f"(Mann-Kendall test), plus the reference period "
                    f"({ref_label}) as comparison band."))
                any_shown = any_shown or shown
    else:
        A(vt("Niet beschikbaar voor deze run.", "Not available for this run."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 3. Trendversnelling", "## 3. Trend acceleration"))
    A("")
    if accel_df is not None and not accel_df.empty:
        # accel_df bevat, bewust, één rij per GETESTE kandidaat-breekpunt (de
        # volledige scan die ook de plot laat zien) -- de tabel hieronder
        # toont uitsluitend elke variabele se eigen best-passende kandidaat
        # (is_best==True), anders zou hier de volledige scan (tientallen
        # bijna-identieke rijen) verschijnen in plaats van één samenvattende
        # regel per variabele.
        best_rows = accel_df[accel_df.get("is_best", False) == True] if "is_best" in accel_df.columns else accel_df
        A(vt("| Variabele | Breekpunt | Helling voor | Helling na | Significant? |", "| Variable | Breakpoint | Slope before | Slope after | Significant? |"))
        A("|---|---|---|---|---|")
        for _, row in best_rows.iterrows():
            sig = "ja" if row.get("significant", False) else "nee"
            A(f"| {row.get('variable', 'n.b.')} | {row.get('breakpoint', 'n.b.')} | "
              f"{_fmt(row.get('slope_before'), 4, ' °C/jr')} | "
              f"{_fmt(row.get('slope_after'), 4, ' °C/jr')} | {sig} |")
        A("")
        A(vt("Generieke statistische toets; zie check_trend_acceleration()'s docstring "
          "in Klimatos_ClimateShift.py voordat een gevonden breekpunt buiten "
          "Europa/Noord-Amerika aan aerosol-uitfasering wordt toegeschreven.",
             "Generic statistical test; see the docstring of check_trend_acceleration() "
          "in Klimatos_ClimateShift.py before attributing a breakpoint found outside "
          "Europe/North America to aerosol phase-out."))
        A("")
        if plot_paths:
            for var in accel_df["variable"].dropna().unique():
                _embed_plot(
                    A, plot_paths, f"plot_trend_acceleration_{var}.png",
                    vt("De volledige reeks met de trendlijn apart getekend vóór en ná het "
                    "beste kandidaat-omslagpunt; bij meerdere geteste omslagjaren ook "
                    "hoe gevoelig de uitkomst is voor de exacte keuze -- een diffuus "
                    "signaal over veel kandidaten is reden voor terughoudendheid, ook "
                    "als er één 'beste' omslagpunt uit rolt.",
                       "The full series with the trend line drawn separately before and after the "
                    "best candidate breakpoint; with several tested break years also "
                    "how sensitive the outcome is to the exact choice -- a diffuse "
                    "signal over many candidates is a reason for restraint, even "
                    "if one 'best' breakpoint comes out."))
    else:
        A(vt("Niet beschikbaar voor deze run (ENABLE_ACCELERATION_CHECK uitgeschakeld, "
          "of geen enkele kandidaat-breekpunt haalde significantie).",
             "Not available for this run (ENABLE_ACCELERATION_CHECK switched off, "
          "or no candidate breakpoint reached significance)."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 4. Evenement-venster", "## 4. Event window"))
    A("")
    if event_df is not None and not event_df.empty:
        A(vt("| Variabele | Baseline | Referentie | Trend | 2030 | 2035 | 2040 |", "| Variable | Baseline | Reference | Trend | 2030 | 2035 | 2040 |"))
        A("|---|---|---|---|---|---|---|")
        for _, row in event_df.iterrows():
            A(f"| {row.get('variable', 'n.b.')} | "
              f"{_fmt(row.get('baseline_mean'), 2, ' °C')} | "
              f"{_fmt(row.get('trend_mean'), 2, ' °C')} | "
              f"{_fmt(row.get('slope_°C_per_yr'), 4, ' °C/jr')} | "
              f"{_fmt(row.get('projected_2030'), 2, ' °C')} | "
              f"{_fmt(row.get('projected_2035'), 2, ' °C')} | "
              f"{_fmt(row.get('projected_2040'), 2, ' °C')} |")
        A("")
        A(vt("Projecties zijn een naïeve lineaire extrapolatie van de "
          "waargenomen trend, geen fysisch klimaatmodel en geen voorspelling "
          "voor een specifiek jaar.",
             "Projections are a naive linear extrapolation of the "
          "observed trend, not a physical climate model and not a forecast "
          "for a specific year."))
        A("")
        if plot_paths:
            for var in event_df["variable"].dropna().unique():
                _embed_plot(
                    A, plot_paths, f"plot_event_{var}_trend.png",
                    vt("Het evenement-venster-gemiddelde per jaar, met de trendlijn en een "
                    "projectie-waaier naar de toekomst; de baseline-periode staat als "
                    "gestippelde referentielijn met een onzekerheidsband. De losse "
                    "jaarpunten zijn bewust ondergeschikt getekend -- de trend is de "
                    "boodschap, niet een individueel jaar.",
                       "The event-window mean per year, with the trend line and a "
                    "projection fan into the future; the baseline period is shown as a "
                    "dotted reference line with an uncertainty band. The individual "
                    "year points are deliberately drawn subdued -- the trend is the "
                    "message, not an individual year."))
    else:
        A(vt("Niet beschikbaar voor deze run (geen evenement-venster ingesteld, "
          "of ENABLE_EVENT_WINDOW uitgeschakeld).",
             "Not available for this run (no event window set, "
          "or ENABLE_EVENT_WINDOW switched off)."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 5. EHS-evolutie (Falmouth, epidemiologisch)", "## 5. EHS evolution (Falmouth, epidemiological)"))
    A("")
    if ehs_df is not None and not ehs_df.empty and "ehs_per_1000" in ehs_df.columns:
        ref_ehs = ehs_df["reference_ehs_per_1000"].iloc[0] if "reference_ehs_per_1000" in ehs_df.columns else np.nan
        A(vt(f"Referentiewaarde: {_fmt(ref_ehs, 2)} EHS per 1.000 deelnemers. "
          f"EHS/1000 is een zuivere functie van de omgevingstemperatuur "
          f"tijdens het evenement-venster (Falmouth-regressie, DeMartini et "
          f"al. 2014) -- beweegt niet mee met tempo/MET.",
             f"Reference value: {_fmt(ref_ehs, 2)} EHS per 1,000 participants. "
          f"EHS/1000 is a pure function of the ambient temperature "
          f"during the event window (Falmouth regression, DeMartini et "
          f"al. 2014) -- it does not move with pace/MET."))
        A("")
        A(vt("| Doeljaar | EHS/1000 | x referentie | Vroege start |", "| Target year | EHS/1000 | x reference | Early start |"))
        A("|---|---|---|---|")
        for _, row in ehs_df.iterrows():
            A(f"| {int(row['target_year'])} | {_fmt(row.get('ehs_per_1000'), 2)} | "
              f"{_fmt(row.get('ratio_vs_reference'), 2, 'x')} | "
              f"{_fmt(row.get('ehs_per_1000_early_start'), 2)} |")
        A("")
        if plot_paths:
            _embed_plot(
                A, plot_paths, "plot_ehs_evolution.png",
                vt("Links: de absolute EHS-schatting met onzekerheidsband en het "
                "vroege-start-scenario ernaast. Rechts: dezelfde uitkomst als "
                "verhouding tot de referentieperiode -- de verhouding is de "
                "robuustere van de twee, omdat een systematische kalibratiefout "
                "daar grotendeels uit wegvalt.",
                   "Left: the absolute EHS estimate with uncertainty band and the "
                "early-start scenario next to it. Right: the same outcome as "
                "ratio to the reference period -- the ratio is the "
                "more robust of the two, because a systematic calibration error "
                "largely cancels out of it."))
    else:
        A(vt("Niet beschikbaar voor deze run (ENABLE_EHS_EVOLUTION uitgeschakeld, "
          "of geen HESTIA-omgeving aanwezig).",
             "Not available for this run (ENABLE_EHS_EVOLUTION switched off, "
          "or no HESTIA environment present)."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 6. Collapse-risico", "## 6. Collapse risk"))
    A("")
    if ehs_df is not None and not ehs_df.empty and "collapse_per_1000" in ehs_df.columns:
        ref_collapse = (ehs_df["reference_collapse_per_1000"].iloc[0]
                        if "reference_collapse_per_1000" in ehs_df.columns else np.nan)
        A(vt(f"Referentiewaarde: {_fmt(ref_collapse, 2)} per 1.000 deelnemers.", f"Reference value: {_fmt(ref_collapse, 2)} per 1,000 participants."))
        A("")
        A(vt("Anders dan EHE heeft dit een gekalibreerde basiswaarde: ook een "
          "scenario waarin niemand in de steekproef een fysiologische "
          "drempel overschrijdt, geeft het geijkte achtergrondniveau, niet "
          "nul. Status: **PROVISIONAL** (geijkt op één referentie-evenement, N=5000; zie "
          "hestia_model.py's COLLAPSE_ENDPOINTS-tabel).",
             "Unlike EHE this has a calibrated baseline: even a "
          "scenario in which nobody in the sample exceeds a physiological "
          "threshold gives the calibrated background level, not "
          "zero. Status: **PROVISIONAL** (calibrated on one reference event, N=5000; see "
          "the COLLAPSE_ENDPOINTS table in hestia_model.py)."))
        A("")
        A(vt("| Doeljaar | per 1.000 | x referentie | Vroege start |", "| Target year | per 1,000 | x reference | Early start |"))
        A("|---|---|---|---|")
        for _, row in ehs_df.iterrows():
            A(f"| {int(row['target_year'])} | {_fmt(row.get('collapse_per_1000'), 2)} | "
              f"{_fmt(row.get('collapse_ratio_vs_reference'), 2, 'x')} | "
              f"{_fmt(row.get('collapse_per_1000_early_start'), 2)} |")
    else:
        A(vt("Niet beschikbaar voor deze run.", "Not available for this run."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 7. EHE / klinisch criterium en marge-tot-drempel", "## 7. EHE / clinical criterion and margin to threshold"))
    A("")
    A(vt("De EHE- en klinische drempel worden hieronder tegen dezelfde onderliggende "
      "steekproef (T_rect, CO_reserve) getoetst -- de mediaan- en "
      "dichtstbijzijnde-punt-waarden kunnen daardoor in beide subsecties "
      "identiek zijn (het is dezelfde data); de afstand tot elke drempel "
      "('t.o.v. de X-drempel') verschilt wél, en is het cijfer dat aangeeft "
      "hoe dicht deze specifieke drempel werd genaderd.",
         "The EHE and clinical thresholds are tested below against the same underlying "
      "sample (T_rect, CO_reserve) -- the median and "
      "closest-point values can therefore be identical in both subsections "
      "(it is the same data); the distance to each threshold "
      "('vs the X threshold') does differ, and is the figure that shows "
      "how closely this specific threshold was approached."))
    A("")
    if ehs_evolution_res is not None:
        scen = ehs_evolution_res.get("scenarios", {})
        ref_pairs = scen.get("ref_current", {}).get("scatter_pairs", [])
        proj_key = ehs_evolution_res.get("_report_proj_key")  # e.g. "proj_2030_central"
        proj_pairs = scen.get(proj_key, {}).get("scatter_pairs", []) if proj_key else []
        for label, tt, ct in ((vt("EHE-drempel (T_rect>39,5 EN COr<0)", "EHE threshold (T_rect>39.5 AND COr<0)"), 39.5, 0.0),
                              (vt("Klinische drempel (T_rect>=40,5 EN COr<=0)", "Clinical threshold (T_rect>=40.5 AND COr<=0)"), 40.5, 0.0)):
            A(f"**{label}:**")
            A("")
            for scen_label, pairs in (("Referentieperiode", ref_pairs),
                                      (vt(f"Projectie {proj_key.split('_')[1]} (centrale helling)", f"Projection {proj_key.split('_')[1]} (central slope)")
                                       if proj_key else "Projectie", proj_pairs)):
                if not pairs:
                    continue
                stats = _local_margin_stats(pairs, tt, ct)
                if stats is None:
                    continue
                A(vt(f"- {scen_label} (n={stats['n']} steekproefmomenten): "
                  f"T_rect mediaan {getal(stats['t_p50'], 2)} °C "
                  f"({_sg(tt - stats['t_p50'], 2)} t.o.v. de {getal(tt, 1)} °C-drempel), "
                  f"CO-reserve mediaan {getal(stats['c_p50'], 2)} L/min "
                  f"({_sg(stats['c_p50'] - ct, 2)} t.o.v. de {getal(ct, 1)} L/min-drempel)",
                     f"- {scen_label} (n={stats['n']} sample moments): "
                  f"T_rect median {getal(stats['t_p50'], 2)} °C "
                  f"({_sg(tt - stats['t_p50'], 2)} vs the {getal(tt, 1)} °C threshold), "
                  f"CO reserve median {getal(stats['c_p50'], 2)} L/min "
                  f"({_sg(stats['c_p50'] - ct, 2)} vs the {getal(ct, 1)} L/min threshold)"))
                bn = stats["closest_bottleneck"]
                if bn > 0:
                    A(vt(f"  dichtstbijzijnde waargenomen combinatie: "
                      f"T_rect={getal(stats['closest_t'], 2)} °C, "
                      f"CO_reserve={getal(stats['closest_c'], 2)} L/min "
                      f"-> {getal(bn, 2)} verwijderd van de moeilijkst te sluiten drempel",
                         f"  closest observed combination: "
                      f"T_rect={getal(stats['closest_t'], 2)} °C, "
                      f"CO_reserve={getal(stats['closest_c'], 2)} L/min "
                      f"-> {getal(bn, 2)} away from the hardest threshold to close"))
                else:
                    A(vt(f"  dichtstbijzijnde waargenomen combinatie: "
                      f"T_rect={getal(stats['closest_t'], 2)} °C, "
                      f"CO_reserve={getal(stats['closest_c'], 2)} L/min "
                      f"-> beide drempels op dit moment overschreden "
                      f"(momentopname, niet per se een aanhoudende treffer)",
                         f"  closest observed combination: "
                      f"T_rect={getal(stats['closest_t'], 2)} °C, "
                      f"CO_reserve={getal(stats['closest_c'], 2)} L/min "
                      f"-> both thresholds exceeded at this moment "
                      f"(snapshot, not necessarily a sustained hit)"))
            A("")
        if plot_paths:
            _embed_plot(
                A, plot_paths, "plot_trect_co_reserve_scatter.png",
                vt("Elk punt is één gesimuleerd steekproefmoment (kerntemperatuur tegen "
                "hartminuutvolume-reserve), referentieperiode naast de projectie voor "
                "het gekozen doeljaar, met de EHE- en klinische-criteriumdrempel als "
                "horizontale zones -- dezelfde onderliggende data als de "
                "marge-tot-drempel-cijfers hierboven, nu visueel in plaats van in getallen.",
                   "Each point is one simulated sample moment (core temperature against "
                "cardiac output reserve), reference period next to the projection for "
                "the chosen target year, with the EHE and clinical criterion thresholds as "
                "horizontal zones -- the same underlying data as the "
                "margin-to-threshold figures above, now visual instead of in numbers."))
    else:
        A(vt("Niet beschikbaar voor deze run (geen ehs_evolution_res meegegeven "
          "aan generate_klimatos_report()).",
             "Not available for this run (no ehs_evolution_res passed "
          "to generate_klimatos_report())."))
        A("")

    # ------------------------------------------------------------------ #
    A(vt("## 8. Hitte-gerelateerde ziekenhuisopnames (van Loenhout ERF)", "## 8. Heat-related hospital admissions (van Loenhout ERF)"))
    A("")
    latest_row = _window_row(admissions_df, latest_label)
    if latest_row is not None:
        A(vt("| | Ratio t.o.v. referentie |", "| | Ratio vs reference |"))
        A("|---|---|")
        A(vt(f"| ERF-index (beta-afhankelijk) | {_fmt(latest_row.get('ratio_ERF_vs_ref'), 2, 'x')} |", f"| ERF index (beta-dependent) | {_fmt(latest_row.get('ratio_ERF_vs_ref'), 2, 'x')} |"))
        A(vt(f"| Hitte-graaddagen (beta-vrij) | {_fmt(latest_row.get('ratio_HDD_vs_ref'), 2, 'x')} |", f"| Heat degree days (beta-free) | {_fmt(latest_row.get('ratio_HDD_vs_ref'), 2, 'x')} |"))
        A("")
        A(vt("Klimaat-only contrast: ERF en populatie worden constant gehouden -- "
          "NIET de waargenomen opnametrend, die ook van vergrijzing/adaptatie afhangt.",
             "Climate-only contrast: ERF and population are held constant -- "
          "NOT the observed admissions trend, which also depends on ageing/adaptation."))
        A("")
        if plot_paths:
            _embed_plot(
                A, plot_paths, "plot_admissions_window_ratio.png",
                vt("Per venster de verhouding tot de referentieperiode, zowel via de "
                "temperatuurafhankelijke ERF-schatting als via de beta-vrije "
                "hitte-graaddagen-controle ernaast -- komen de twee staven met elkaar "
                "overeen, dan hangt de uitkomst niet louter af van de gekozen "
                "beta-waarde in het ERF-model.",
                   "Per window the ratio to the reference period, both via the "
                "temperature-dependent ERF estimate and via the beta-free "
                "heat-degree-day check next to it -- if the two bars "
                "agree, the outcome does not depend purely on the chosen "
                "beta value in the ERF model."))
    else:
        A(vt("Niet beschikbaar voor deze run.", "Not available for this run."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 9. Fysiologische leefbaarheid (HEAT-Lim)", "## 9. Physiological liveability (HEAT-Lim)"))
    A("")
    latest_liv = _window_row(liveability_df, latest_label)
    ref_liv = _window_row(liveability_df, ref_label)
    if latest_liv is not None and ref_liv is not None:
        A(vt("| Profiel | Min. Mmax referentie | Min. Mmax recent | Verschil |", "| Profile | Min. Mmax reference | Min. Mmax recent | Difference |"))
        A("|---|---|---|---|")
        for prof, label in (("young", vt("Jongvolwassene (18-40)", "Young adult (18-40)")), ("old", vt("Oudere (65+)", "Older adult (65+)"))):
            col = f"minMmax_{prof}"
            if col in latest_liv.index:
                r = ref_liv[col]
                l = latest_liv[col]
                A(f"| {label} | {_fmt(r, 2, ' MET')} | {_fmt(l, 2, ' MET')} | "
                  f"{_sg((l - r), 2)} MET |" if pd.notna(r) and pd.notna(l)
                  else f"| {label} | n.b. | n.b. | n.b. |")
        A("")
        if plot_paths:
            _embed_plot(
                A, plot_paths, "plot_liveability_window_bar.png",
                vt("Per venster het gemiddelde slechtste-uur-Mmax voor beide "
                "leeftijdsprofielen naast elkaar -- een dalende balk betekent minder "
                "fysiologische marge over tijdens het heetste uur van een gemiddelde "
                "dag in dat venster.",
                   "Per window the mean worst-hour Mmax for both "
                "age profiles side by side -- a falling bar means less "
                "physiological margin left during the hottest hour of an average "
                "day in that window."))
        A("")
        A(vt("**Let op bij het slechtste-uur-Mmax:** Mmax kan niet onder het "
          "rustniveau komen (ongeveer 1,5 MET). Een uur dat nog zwaarder is, "
          "telt als 'niet leefbaar' en valt buiten dit minimum. Zodra een "
          "profiel tegen die bodem zit, toont deze maat geen verdere "
          "verslechtering meer; daarvoor dient het aantal uren hieronder.",
             "**Note on the worst-hour Mmax:** Mmax cannot fall below the "
          "resting level (about 1.5 MET). An hour that is even harder "
          "counts as 'not liveable' and falls outside this minimum. Once a "
          "profile sits against that floor, this measure shows no further "
          "deterioration; the number of hours below serves that purpose."))
        A("")
        cols = ("hrsBelow_young", "hrsNonLiv_young", "hrsBelow_old", "hrsNonLiv_old")
        if all(c in latest_liv.index for c in cols):
            A(vt("| Uren per jaar | Referentie | Recent |", "| Hours per year | Reference | Recent |"))
            A("|---|---|---|")
            for c, lab in (("hrsBelow_young", vt("Jongvolwassene: onder 3 MET", "Young adult: below 3 MET")),
                           ("hrsNonLiv_young", vt("Jongvolwassene: zelfs rust niet volhoudbaar", "Young adult: even rest not sustainable")),
                           ("hrsBelow_old", vt("Oudere: onder 3 MET", "Older adult: below 3 MET")),
                           ("hrsNonLiv_old", vt("Oudere: zelfs rust niet volhoudbaar", "Older adult: even rest not sustainable"))):
                A(f"| {lab} | {_fmt(ref_liv[c], 1)} | {_fmt(latest_liv[c], 1)} |")
            A("")
        names = {"hrsBelow": vt("onder 3 MET", "below 3 MET"), "hrsNonLiv": vt("zelfs rust niet volhoudbaar", "even rest not sustainable")}
        profs = {"young": vt("Jongvolwassene", "Young adult"), "old": vt("Oudere", "Older adult")}
        if liveability_proj_df is not None and len(liveability_proj_df):
            P = liveability_proj_df
            tys = sorted(int(c) for c in P.columns if str(c).isdigit())
            a = P.iloc[0]
            hum = {"constant_rh": vt("de relatieve vochtigheid blijft gelijk (de hoeveelheid "
                                  "waterdamp stijgt mee)",
                                     "the relative humidity stays the same (the amount of "
                                  "water vapour rises with it)"),
                   "constant_vapour": vt("de hoeveelheid waterdamp blijft gelijk (de relatieve "
                                      "vochtigheid daalt)",
                                         "the amount of water vapour stays the same (the relative "
                                      "humidity falls)")}.get(a["humidity"], a["humidity"])
            A(vt(f"**Vooruitblik.** Elk jaar uit {a['trend_period']} is opgewarmd naar het doeljaar "
              f"met de trend van de zomerse dagmaximumtemperatuur ({a['shift_var']}: "
              f"{_sg(a['slope'] * 10, 2)} °C per tien jaar, 95%-band {_sg(a['slope_lo'] * 10, 2)} tot "
              f"{_sg(a['slope_hi'] * 10, 2)}; Mann-Kendall p = {_fmt(a['mk_p'], 3)}); daarbij {hum}. "
              "Daarna zijn de uren met HEAT-Lim opnieuw berekend en over de jaren gemiddeld. "
              "Rechte voortzetting van de waargenomen opwarming, geen klimaatscenario. Tussen "
              "haakjes: lage en hoge helling.",
                 f"**Outlook.** Each year from {a['trend_period']} has been warmed to the target year "
              f"with the trend of the summer daily maximum temperature ({a['shift_var']}: "
              f"{_sg(a['slope'] * 10, 2)} °C per ten years, 95% band {_sg(a['slope_lo'] * 10, 2)} to "
              f"{_sg(a['slope_hi'] * 10, 2)}; Mann-Kendall p = {_fmt(a['mk_p'], 3)}); {hum}. "
              "Then the hours have been recalculated with HEAT-Lim and averaged over the years. "
              "Straight continuation of the observed warming, not a climate scenario. In "
              "brackets: low and high slope."))
            A("")
            A(vt("| Profiel en maat | Gemiddeld ", "| Profile and measure | Mean ") + str(a["trend_period"]) + " | "
              + " | ".join(str(t) for t in tys) + " |")
            A("|---|---|" + "---|" * len(tys))
            for _, r in P.iterrows():
                cells = [f"{getal(r[str(t)], 1)} ({getal(r[f'{t}_lo'], 1)}–{getal(r[f'{t}_hi'], 1)})" for t in tys]
                A(f"| {profs.get(r.profile, r.profile)}: {names.get(r.metric, r.metric)} | "
                  f"{getal(r.reference_mean, 1)} | " + " | ".join(cells) + " |")
            A("")
        elif liveability_hours_df is not None and len(liveability_hours_df):
            tys = sorted(int(c.split("_")[1]) for c in liveability_hours_df.columns
                         if c.startswith("proj_") and c.count("_") == 1)
            tp = liveability_hours_df["trend_period"].iloc[0]
            A(vt(f"Doorgetrokken trend {tp}: kleinste-kwadratenlijn door het gemiddelde "
              "van die periode, rechte lijn, geen klimaatscenario; tussen haakjes de "
              "95%-band van de helling. (Theil-Sen is hier niet bruikbaar: de uren "
              "'niet leefbaar' zijn de meeste jaren nul.)",
                 f"Extended trend {tp}: least-squares line through the mean "
              "of that period, straight line, not a climate scenario; in brackets the "
              "95% band of the slope. (Theil-Sen cannot be used here: the hours "
              "'not liveable' are zero in most years.)"))
            A("")
            A(vt("| Profiel en maat | Trend (uur/jaar per jaar) | Mann-Kendall p | ", "| Profile and measure | Trend (hours/year per year) | Mann-Kendall p | ")
              + " | ".join(str(t) for t in tys) + " |")
            A("|---|---|---|" + "---|" * len(tys))
            for _, r in liveability_hours_df.iterrows():
                cells = [f"{getal(r[f'proj_{t}'], 1)} ({getal(r[f'proj_{t}_lo'], 1)}–{getal(r[f'proj_{t}_hi'], 1)})"
                         for t in tys]
                A(f"| {profs.get(r.profile, r.profile)}: {names.get(r.metric, r.metric)} | "
                  f"{_sg(r.slope_hours_per_yr, 2)} | {_fmt(r.mk_p, 3)} | " + " | ".join(cells) + " |")
            A("")
        if plot_paths:
            _embed_plot(
                A, plot_paths, "plot_liveability_hours.png",
                vt("Aantal uren per jaar waarin lichte activiteit (boven) of zelfs rust "
                "(onder) in de zon niet volhoudbaar is, per leeftijdsprofiel, met de "
                "trend en de doorgetrokken lijn naar de doeljaren.",
                   "Number of hours per year in which light activity (top) or even rest "
                "(bottom) in the sun cannot be sustained, per age profile, with the "
                "trend and the extended line to the target years."))
    else:
        A(vt("Niet beschikbaar voor deze run.", "Not available for this run."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 10. Herkomst en status van dit model", "## 10. Provenance and status of this model"))
    A("")
    A("| | |")
    A("|---|---|")
    A("| Model | Klimatos.ClimateShift |")
    A(vt("| Databron | ERA5 historisch archief (Open-Meteo archive-api) |", "| Data source | ERA5 historical archive (Open-Meteo archive-api) |"))
    A(vt("| ERA5-correctie | geen: de land-zeecorrectie van de Data Engine wordt in Klimatos niet "
      "toegepast; aan de kust kunnen absolute waarden te gunstig zijn |",
         "| ERA5 correction | none: the Data Engine land–sea correction is not applied "
      "in Klimatos; on the coast absolute values may be too favourable |"))
    if meta.get("admissions_erf"):
        A(vt(f"| Ziekenhuisopnames-methode | {meta['admissions_erf']} |", f"| Hospital admissions method | {meta['admissions_erf']} |"))
    if meta.get("liveability"):
        A(vt(f"| Leefbaarheids-methode | {meta['liveability']} |", f"| Liveability method | {meta['liveability']} |"))
    A("")
    A(vt("**Beperkingen, expliciet:** projecties zijn een lineaire "
      "extrapolatie van de waargenomen trend, geen fysisch klimaatmodel. "
      "Het `hospitalisation`-eindpunt is PROVISIONAL (geijkt op één referentie-evenement, "
      "de Dam tot Damloop 2024; wachtend op nadere klinische onderbouwing). Geen onafhankelijke, "
      "externe peer review van dit specifieke traject.",
         "**Limitations, explicitly:** projections are a linear "
      "extrapolation of the observed trend, not a physical climate model. "
      "The `hospitalisation` endpoint is PROVISIONAL (calibrated on one reference event, "
      "the Dam tot Damloop 2024; awaiting further clinical substantiation). No independent, "
      "external peer review of this specific trajectory."))
    A("")
    A(vt("*Einde rapport.*", "*End of report.*"))

    text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    return text


def _local_margin_stats(pairs, t_threshold: float = 39.5, c_threshold: float = 0.0):
    """
    Same calculation as hestia_bridge.margin_to_threshold_stats() (and
    Klimatos_ClimateShift.py's own _ehe_margin_stats) -- deliberately a
    third, small, standalone copy here rather than an import from either:
    this report generator needs to work whenever Klimatos itself works,
    including without HESTIA present (HESTIA_AVAILABLE == False), so it
    cannot hard-depend on hestia_bridge; and it is meant to be usable
    without importing the whole of Klimatos_ClimateShift.py just for one
    small function. Kept in sync manually across all three copies.
    """
    if not pairs:
        return None
    t = np.array([p[0] for p in pairs])
    c = np.array([p[1] for p in pairs])
    margin_t = t_threshold - t
    margin_c = c - c_threshold
    bottleneck = np.maximum(margin_t, margin_c)
    idx = int(np.argmin(bottleneck))
    return {
        "n": len(pairs), "t_threshold": t_threshold, "c_threshold": c_threshold,
        "t_p50": float(np.median(t)), "c_p50": float(np.median(c)),
        "closest_t": float(t[idx]), "closest_c": float(c[idx]),
        "closest_bottleneck": float(bottleneck[idx]),
    }
