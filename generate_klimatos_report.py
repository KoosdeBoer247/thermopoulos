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

from datetime import datetime, timezone
import numpy as np
import pandas as pd


def _fmt(x, decimals=2, suffix=""):
    """Format a scalar as text. Returns 'n.b.' (niet beschikbaar) if the
    value is missing/NaN. Identical convention to generate_event_report.py's
    own _fmt(), so numbers read the same way across both report types."""
    if x is None:
        return "n.b."
    try:
        if pd.isna(x):
            return "n.b."
    except (TypeError, ValueError):
        pass
    try:
        return f"{float(x):.{decimals}f}{suffix}"
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

    A(f"# Klimatos-rapport — {event_name}")
    A("")
    A(f"*Automatisch gegenereerd op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"door generate_klimatos_report.py (HESTIA-PYROX suite).*")
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
    A(f"| Naam | {event_name} |")
    A(f"| Plaats | {meta.get('city', 'n.b.')} ({_fmt(meta.get('latitude'), 4)}, "
      f"{_fmt(meta.get('longitude'), 4)}) |")
    if meta.get("population"):
        A(f"| Inwonertal | {meta['population']:,} |")
    A(f"| Stedelijk hitte-eiland (UHI) | {'aan' if meta.get('apply_uhi') else 'uit'} |")
    A(f"| Referentieperiode | {meta.get('reference_period', ref_label)} |")
    A(f"| Analyseperiode | {meta.get('analysis_start', 'n.b.')}-{meta.get('analysis_end', 'n.b.')} |")
    A(f"| Schuifvenster | {meta.get('window_length', 'n.b.')} jaar, "
      f"stap {meta.get('window_step', 'n.b.')} jaar |")
    if meta.get("event_window"):
        A(f"| Evenement-venster | {meta['event_window']} |")
    if documented_reference:
        A(f"| Gedocumenteerd referentiecijfer voor dit evenement | {documented_reference} |")
    A("")

    # ------------------------------------------------------------------ #
    A("## 2. Jaarlijkse extremen (referentie vs recent)")
    A("")
    A(f"Vergelijking tussen de referentieperiode ({ref_label}) en het meest "
      f"recente schuifvenster ({latest_label}), per variabele.")
    A("")
    var_labels = {
        "T_air_max": "Luchttemperatuur (T_air_max)",
        "WBT_max": "Natte-boltemperatuur (WBT_max)",
        "WBGT_max": "WBGT (WBGT_max)",
        "UTCI_max": "UTCI (UTCI_max)",
    }
    if annual is not None and not annual.empty:
        A("| Variabele | Referentie-gemiddelde | Recent-gemiddelde | Verschil |")
        A("|---|---|---|---|")
        for col, label in var_labels.items():
            if col not in annual.columns:
                continue
            s = annual[col]
            ref_mean = s[(s.index >= ref_window[0]) & (s.index <= ref_window[1])].dropna().mean()
            lat_mean = s[(s.index >= latest_window[0]) & (s.index <= latest_window[1])].dropna().mean()
            diff = lat_mean - ref_mean if pd.notna(ref_mean) and pd.notna(lat_mean) else np.nan
            A(f"| {label} | {_fmt(ref_mean, 2, ' degC')} | {_fmt(lat_mean, 2, ' degC')} | "
              f"{_fmt(diff, 2, ' degC') if pd.isna(diff) else f'{diff:+.2f} degC'} |")
        A("")
        if plot_paths:
            any_shown = False
            for col, label in var_labels.items():
                shown = _embed_plot(
                    A, plot_paths, f"plot_{col}_timeseries_trend.png",
                    f"Jaarlijkse extreemwaarde van {label} per jaar (punten), met de "
                    f"Theil-Sen-trendlijn en of die trend statistisch significant is "
                    f"(Mann-Kendall-toets), plus de referentieperiode "
                    f"({ref_label}) als vergelijkingsband.")
                any_shown = any_shown or shown
    else:
        A("Niet beschikbaar voor deze run.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 3. Trendversnelling")
    A("")
    if accel_df is not None and not accel_df.empty:
        # accel_df bevat, bewust, één rij per GETESTE kandidaat-breekpunt (de
        # volledige scan die ook de plot laat zien) -- de tabel hieronder
        # toont uitsluitend elke variabele se eigen best-passende kandidaat
        # (is_best==True), anders zou hier de volledige scan (tientallen
        # bijna-identieke rijen) verschijnen in plaats van één samenvattende
        # regel per variabele.
        best_rows = accel_df[accel_df.get("is_best", False) == True] if "is_best" in accel_df.columns else accel_df
        A("| Variabele | Breekpunt | Helling voor | Helling na | Significant? |")
        A("|---|---|---|---|---|")
        for _, row in best_rows.iterrows():
            sig = "ja" if row.get("significant", False) else "nee"
            A(f"| {row.get('variable', 'n.b.')} | {row.get('breakpoint', 'n.b.')} | "
              f"{_fmt(row.get('slope_before'), 4, ' degC/jr')} | "
              f"{_fmt(row.get('slope_after'), 4, ' degC/jr')} | {sig} |")
        A("")
        A("Generieke statistische toets; zie check_trend_acceleration()'s docstring "
          "in Klimatos_ClimateShift.py voordat een gevonden breekpunt buiten "
          "Europa/Noord-Amerika aan aerosol-uitfasering wordt toegeschreven.")
        A("")
        if plot_paths:
            for var in accel_df["variable"].dropna().unique():
                _embed_plot(
                    A, plot_paths, f"plot_trend_acceleration_{var}.png",
                    "De volledige reeks met de trendlijn apart getekend vóór en ná het "
                    "beste kandidaat-omslagpunt; bij meerdere geteste omslagjaren ook "
                    "hoe gevoelig de uitkomst is voor de exacte keuze -- een diffuus "
                    "signaal over veel kandidaten is reden voor terughoudendheid, ook "
                    "als er één 'beste' omslagpunt uit rolt.")
    else:
        A("Niet beschikbaar voor deze run (ENABLE_ACCELERATION_CHECK uitgeschakeld, "
          "of geen enkele kandidaat-breekpunt haalde significantie).")
    A("")

    # ------------------------------------------------------------------ #
    A("## 4. Evenement-venster")
    A("")
    if event_df is not None and not event_df.empty:
        A("| Variabele | Baseline | Referentie | Trend | 2030 | 2035 | 2040 |")
        A("|---|---|---|---|---|---|---|")
        for _, row in event_df.iterrows():
            A(f"| {row.get('variable', 'n.b.')} | "
              f"{_fmt(row.get('baseline_mean'), 2, ' degC')} | "
              f"{_fmt(row.get('trend_mean'), 2, ' degC')} | "
              f"{_fmt(row.get('slope_degC_per_yr'), 4, ' degC/jr')} | "
              f"{_fmt(row.get('projected_2030'), 2, ' degC')} | "
              f"{_fmt(row.get('projected_2035'), 2, ' degC')} | "
              f"{_fmt(row.get('projected_2040'), 2, ' degC')} |")
        A("")
        A("Projecties zijn een naïeve lineaire extrapolatie van de "
          "waargenomen trend, geen fysisch klimaatmodel en geen voorspelling "
          "voor een specifiek jaar.")
        A("")
        if plot_paths:
            for var in event_df["variable"].dropna().unique():
                _embed_plot(
                    A, plot_paths, f"plot_event_{var}_trend.png",
                    "Het evenement-venster-gemiddelde per jaar, met de trendlijn en een "
                    "projectie-waaier naar de toekomst; de baseline-periode staat als "
                    "gestippelde referentielijn met een onzekerheidsband. De losse "
                    "jaarpunten zijn bewust ondergeschikt getekend -- de trend is de "
                    "boodschap, niet een individueel jaar.")
    else:
        A("Niet beschikbaar voor deze run (geen evenement-venster ingesteld, "
          "of ENABLE_EVENT_WINDOW uitgeschakeld).")
    A("")

    # ------------------------------------------------------------------ #
    A("## 5. EHS-evolutie (Falmouth, epidemiologisch)")
    A("")
    if ehs_df is not None and not ehs_df.empty and "ehs_per_1000" in ehs_df.columns:
        ref_ehs = ehs_df["reference_ehs_per_1000"].iloc[0] if "reference_ehs_per_1000" in ehs_df.columns else np.nan
        A(f"Referentiewaarde: {_fmt(ref_ehs, 2)} EHS per 1.000 deelnemers. "
          f"EHS/1000 is een zuivere functie van de omgevingstemperatuur "
          f"tijdens het evenement-venster (Falmouth-regressie, DeMartini et "
          f"al. 2014) -- beweegt niet mee met tempo/MET.")
        A("")
        A("| Doeljaar | EHS/1000 | x referentie | Vroege start |")
        A("|---|---|---|---|")
        for _, row in ehs_df.iterrows():
            A(f"| {int(row['target_year'])} | {_fmt(row.get('ehs_per_1000'), 2)} | "
              f"{_fmt(row.get('ratio_vs_reference'), 2, 'x')} | "
              f"{_fmt(row.get('ehs_per_1000_early_start'), 2)} |")
        A("")
        if plot_paths:
            _embed_plot(
                A, plot_paths, "plot_ehs_evolution.png",
                "Links: de absolute EHS-schatting met onzekerheidsband en het "
                "vroege-start-scenario ernaast. Rechts: dezelfde uitkomst als "
                "verhouding tot de referentieperiode -- de verhouding is de "
                "robuustere van de twee, omdat een systematische kalibratiefout "
                "daar grotendeels uit wegvalt.")
    else:
        A("Niet beschikbaar voor deze run (ENABLE_EHS_EVOLUTION uitgeschakeld, "
          "of geen HESTIA-omgeving aanwezig).")
    A("")

    # ------------------------------------------------------------------ #
    A("## 6. Collapse-risico")
    A("")
    if ehs_df is not None and not ehs_df.empty and "collapse_per_1000" in ehs_df.columns:
        ref_collapse = (ehs_df["reference_collapse_per_1000"].iloc[0]
                        if "reference_collapse_per_1000" in ehs_df.columns else np.nan)
        A(f"Referentiewaarde: {_fmt(ref_collapse, 2)} per 1.000 deelnemers.")
        A("")
        A("Anders dan EHE heeft dit een gekalibreerde basiswaarde: ook een "
          "scenario waarin niemand in de steekproef een fysiologische "
          "drempel overschrijdt, geeft het geijkte achtergrondniveau, niet "
          "nul. Status: **PROVISIONAL** (geijkt op gereduceerde N; zie "
          "hestia_model.py's COLLAPSE_ENDPOINTS-tabel).")
        A("")
        A("| Doeljaar | per 1.000 | x referentie | Vroege start |")
        A("|---|---|---|---|")
        for _, row in ehs_df.iterrows():
            A(f"| {int(row['target_year'])} | {_fmt(row.get('collapse_per_1000'), 2)} | "
              f"{_fmt(row.get('collapse_ratio_vs_reference'), 2, 'x')} | "
              f"{_fmt(row.get('collapse_per_1000_early_start'), 2)} |")
    else:
        A("Niet beschikbaar voor deze run.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 7. EHE / klinisch criterium en marge-tot-drempel")
    A("")
    A("De EHE- en klinische drempel worden hieronder tegen dezelfde onderliggende "
      "steekproef (T_rect, CO_reserve) getoetst -- de mediaan- en "
      "dichtstbijzijnde-punt-waarden kunnen daardoor in beide subsecties "
      "identiek zijn (het is dezelfde data); de afstand tot elke drempel "
      "('t.o.v. de X-drempel') verschilt wél, en is het cijfer dat aangeeft "
      "hoe dicht deze specifieke drempel werd genaderd.")
    A("")
    if ehs_evolution_res is not None:
        scen = ehs_evolution_res.get("scenarios", {})
        ref_pairs = scen.get("ref_current", {}).get("scatter_pairs", [])
        proj_key = ehs_evolution_res.get("_report_proj_key")  # e.g. "proj_2030_central"
        proj_pairs = scen.get(proj_key, {}).get("scatter_pairs", []) if proj_key else []
        for label, tt, ct in (("EHE-drempel (T_rect>39,5 EN COr<0)", 39.5, 0.0),
                              ("Klinische drempel (T_rect>=40,5 EN COr<=0)", 40.5, 0.0)):
            A(f"**{label}:**")
            A("")
            for scen_label, pairs in (("Referentieperiode", ref_pairs),
                                      (f"Projectie {proj_key.split('_')[1]} (centrale helling)"
                                       if proj_key else "Projectie", proj_pairs)):
                if not pairs:
                    continue
                stats = _local_margin_stats(pairs, tt, ct)
                if stats is None:
                    continue
                A(f"- {scen_label} (n={stats['n']} steekproefmomenten): "
                  f"T_rect mediaan {stats['t_p50']:.2f} degC "
                  f"({tt - stats['t_p50']:+.2f} t.o.v. de {tt:.1f} degC-drempel), "
                  f"CO-reserve mediaan {stats['c_p50']:.2f} L/min "
                  f"({stats['c_p50'] - ct:+.2f} t.o.v. de {ct:.1f} L/min-drempel)")
                bn = stats["closest_bottleneck"]
                if bn > 0:
                    A(f"  dichtstbijzijnde waargenomen combinatie: "
                      f"T_rect={stats['closest_t']:.2f} degC, "
                      f"CO_reserve={stats['closest_c']:.2f} L/min "
                      f"-> {bn:.2f} verwijderd van de moeilijkst te sluiten drempel")
                else:
                    A(f"  dichtstbijzijnde waargenomen combinatie: "
                      f"T_rect={stats['closest_t']:.2f} degC, "
                      f"CO_reserve={stats['closest_c']:.2f} L/min "
                      f"-> beide drempels op dit moment overschreden "
                      f"(momentopname, niet per se een aanhoudende treffer)")
            A("")
        if plot_paths:
            _embed_plot(
                A, plot_paths, "plot_trect_co_reserve_scatter.png",
                "Elk punt is één gesimuleerd steekproefmoment (kerntemperatuur tegen "
                "hartminuutvolume-reserve), referentieperiode naast de projectie voor "
                "het gekozen doeljaar, met de EHE- en klinische-criteriumdrempel als "
                "horizontale zones -- dezelfde onderliggende data als de "
                "marge-tot-drempel-cijfers hierboven, nu visueel in plaats van in getallen.")
    else:
        A("Niet beschikbaar voor deze run (geen ehs_evolution_res meegegeven "
          "aan generate_klimatos_report()).")
        A("")

    # ------------------------------------------------------------------ #
    A("## 8. Hitte-gerelateerde ziekenhuisopnames (van Loenhout ERF)")
    A("")
    latest_row = _window_row(admissions_df, latest_label)
    if latest_row is not None:
        A("| | Ratio t.o.v. referentie |")
        A("|---|---|")
        A(f"| ERF-index (beta-afhankelijk) | {_fmt(latest_row.get('ratio_ERF_vs_ref'), 2, 'x')} |")
        A(f"| Hitte-graaddagen (beta-vrij) | {_fmt(latest_row.get('ratio_HDD_vs_ref'), 2, 'x')} |")
        A("")
        A("Klimaat-only contrast: ERF en populatie worden constant gehouden -- "
          "NIET de waargenomen opnametrend, die ook van vergrijzing/adaptatie afhangt.")
        A("")
        if plot_paths:
            _embed_plot(
                A, plot_paths, "plot_admissions_window_ratio.png",
                "Per venster de verhouding tot de referentieperiode, zowel via de "
                "temperatuurafhankelijke ERF-schatting als via de beta-vrije "
                "hitte-graaddagen-controle ernaast -- komen de twee staven met elkaar "
                "overeen, dan hangt de uitkomst niet louter af van de gekozen "
                "beta-waarde in het ERF-model.")
    else:
        A("Niet beschikbaar voor deze run.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 9. Fysiologische leefbaarheid (HEAT-Lim)")
    A("")
    latest_liv = _window_row(liveability_df, latest_label)
    ref_liv = _window_row(liveability_df, ref_label)
    if latest_liv is not None and ref_liv is not None:
        A("| Profiel | Min. Mmax referentie | Min. Mmax recent | Verschil |")
        A("|---|---|---|---|")
        for prof, label in (("young", "Jongvolwassene (18-40)"), ("old", "Oudere (65+)")):
            col = f"minMmax_{prof}"
            if col in latest_liv.index:
                r = ref_liv[col]
                l = latest_liv[col]
                A(f"| {label} | {_fmt(r, 2, ' MET')} | {_fmt(l, 2, ' MET')} | "
                  f"{(l - r):+.2f} MET |" if pd.notna(r) and pd.notna(l)
                  else f"| {label} | n.b. | n.b. | n.b. |")
        A("")
        if plot_paths:
            _embed_plot(
                A, plot_paths, "plot_liveability_window_bar.png",
                "Per venster het gemiddelde slechtste-uur-Mmax voor beide "
                "leeftijdsprofielen naast elkaar -- een dalende balk betekent minder "
                "fysiologische marge over tijdens het heetste uur van een gemiddelde "
                "dag in dat venster.")
    else:
        A("Niet beschikbaar voor deze run.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 10. Herkomst en status van dit model")
    A("")
    A("| | |")
    A("|---|---|")
    A("| Model | Klimatos.ClimateShift |")
    A("| Databron | ERA5 historisch archief (Open-Meteo archive-api) |")
    if meta.get("admissions_erf"):
        A(f"| Ziekenhuisopnames-methode | {meta['admissions_erf']} |")
    if meta.get("liveability"):
        A(f"| Leefbaarheids-methode | {meta['liveability']} |")
    A("")
    A("**Beperkingen, expliciet:** projecties zijn een lineaire "
      "extrapolatie van de waargenomen trend, geen fysisch klimaatmodel. "
      "Het `hospitalisation`-eindpunt is PROVISIONAL (gereduceerde N, "
      "wachtend op nadere klinische onderbouwing). Geen onafhankelijke, "
      "externe peer review van dit specifieke traject.")
    A("")
    A("*Einde rapport.*")

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
