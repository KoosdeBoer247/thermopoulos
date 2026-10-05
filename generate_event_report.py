"""
generate_event_report.py -- HESTIA event report generator (rev1, 2026-07)

Genereert een vast, feitelijk rapport uit de uitkomst van een HESTIA Monte
Carlo-run (run_hestia.monte_carlo_adult). Doel: organisaties en hulpverlening
kunnen zelf conclusies trekken uit de cijfers -- dit rapport bevat daarom
uitsluitend feitelijke, door het model berekende waarden en hun herkomst,
geen aanbevelingen, adviezen of interpretatie van wat er "zou moeten"
gebeuren.

Gebruik
-------
    from thermopoulos_loader import ThermopoulosData
    from run_hestia import monte_carlo_adult
    from generate_event_report import generate_report

    data = ThermopoulosData("Thermopoulos_DataEngine_Utrecht_....xlsx")
    all_results, stats, df = monte_carlo_adult(
        data, start_time="2026-04-19 09:00", duration_hours=3.5,
        met_value=11.0, clo_value=0.2, n_simulations=1000,
        training_factor=0.4, acclimatization_factor=0.4,
        sheet="Historical_Custom", random_seed=42,
    )
    generate_report(
        event_name="Marathon Utrecht 2026",
        data=data, stats=stats, results_df=df,
        start_time="2026-04-19 09:00", duration_hours=3.5,
        activity_description="Marathon, wedstrijdtempo (MET 11.0)",
        n_simulations=1000,
        output_path="/mnt/user-data/outputs/rapport_utrecht_2026.md",
    )

Het sjabloon is vast (dezelfde secties, dezelfde volgorde, ongeacht
evenement) zodat rapporten van verschillende evenementen direct naast
elkaar te leggen zijn.
"""

from datetime import datetime, timezone
import numpy as np

import hestia_model as hestia
from thermopoulos_loader import ThermopoulosData
from hestia_bridge import margin_to_threshold_stats, format_margin_lines


def _fmt(x, decimals=2, suffix=""):
    """Format a scalar, or the final value of a time series, as text.
    Returns 'n.b.' (niet beschikbaar) if the value is missing/NaN/empty."""
    if x is None:
        return "n.b."
    arr = np.asarray(x)
    if arr.size == 0:
        return "n.b."
    if arr.ndim > 0:
        x = arr[-1]  # final value of the time series (end of simulated window)
    try:
        if np.isnan(x):
            return "n.b."
    except TypeError:
        return "n.b."
    return f"{float(x):.{decimals}f}{suffix}"


def generate_report(event_name: str,
                     data: ThermopoulosData,
                     stats: dict,
                     results_df,
                     start_time: str,
                     duration_hours: float,
                     activity_description: str,
                     n_simulations: int,
                     output_path: str,
                     documented_reference: str = None,
                     bridge_summary: dict = None,
                     plot_paths: list = None,
                     interp_data: list = None,
                     sample_pace: bool = False) -> str:
    """
    Genereer een vast, feitelijk rapport en schrijf het weg als Markdown.

    Parameters
    ----------
    event_name : str
        Naam van het evenement, zoals het in het rapport moet verschijnen
        (bijv. "Marathon Utrecht 2026").
    data : ThermopoulosData
        De ingeladen weerdata voor deze locatie/dag (voor plaats/coördinaten
        in de kop van het rapport).
    stats : dict
        De stats-dict zoals geretourneerd door monte_carlo_adult().
    results_df : pandas.DataFrame
        De resultaten-dataframe zoals geretourneerd door monte_carlo_adult().
    start_time : str
        De starttijd zoals doorgegeven aan monte_carlo_adult() (voor de kop).
    duration_hours : float
        De simulatieduur in uren (voor de kop).
    activity_description : str
        Vrije tekstbeschrijving van de gekozen activiteit/tempo (bijv.
        "Marathon, wedstrijdtempo (MET 11.0)") -- puur voor leesbaarheid in
        de kop, geen invloed op de berekening zelf.
    n_simulations : int
        Aantal gesimuleerde deelnemers in deze run (voor de kop en de
        beperkingen-sectie).
    output_path : str
        Pad waar het rapport (.md) wordt weggeschreven.
    documented_reference : str, optional
        Vrije tekst met het gedocumenteerde, werkelijke incidentiecijfer
        voor dit evenement, indien bekend (bijv. "Gedocumenteerd: 9,0 per
        10.000 (EHS, Breslow et al. 2021)"). Puur ter feitelijke vermelding
        naast de modeluitkomst -- geen vergelijking of oordeel wordt
        toegevoegd; dat blijft aan de lezer.
    bridge_summary : dict, optional
        [2026-08-26] Uitvoer van hestia_bridge._summarize_results(all_results)
        voor dezelfde run (falmouth_ehs_per_1000, pct_true_ehe_criterion,
        pct_true_ehs_criterion, t_rect_co_reserve_pairs, ...) -- een analyse-
        laag die niet native in monte_carlo_adult()'s eigen stats-dict zit.
        None (de standaard) betekent: deze laag was niet beschikbaar voor
        deze run, en sectie 10 vermeldt dat expliciet in plaats van de
        cijfers te verzinnen of over te slaan zonder uitleg.
    plot_paths : list, optional
        [2026-09-01] Padnamen van al gegenereerde PNG-bestanden, zoals
        hestia_plots.generate_population_plots() teruggeeft (run_hestia.py's
        eigen "Generate plots?"-vraag, VÓÓR de rapportvraag zelf, roept die
        al aan). Elke bekende HESTIA_plotN_...-naam krijgt een eigen,
        toegankelijke verklaring in sectie 11; een pad dat niet bij een
        bekend patroon past, wordt overgeslagen. None of een lege lijst laat
        sectie 11 een "niet gegenereerd voor deze run"-vermelding tonen.
    interp_data : list, optional
        [2026-09] De geïnterpoleerde weerreeks voor het evenement-venster,
        zoals run_hestia.py's build_interpolated_weather() teruggeeft
        (dezelfde data die de fysiologische simulatie zelf als invoer
        gebruikt). Gebruikt voor sectie 2 (Meteorologische omstandigheden)
        -- min/gemiddelde/max van temperatuur, luchtvochtigheid, wind,
        globetemperatuur, MRT, en WBGT/UTCI (indien vooraf berekend
        meegegeven). None (de standaard) laat sectie 2 een "niet
        beschikbaar"-vermelding tonen in plaats van de sectie stilzwijgend
        over te slaan.
    sample_pace : bool
        [2026-09] Of deze run met per-persoon gesamplede pace/MET/duur is
        gedraaid (zie hestia_model.py's generate_base_population()/
        run_monte_carlo_adult()). Puur voor weergave in sectie 1 -- heeft
        zelf geen invloed op de berekening (die vindt al plaats vóórdat
        dit rapport wordt gegenereerd).

    Returns
    -------
    str
        Het volledige rapport als tekst (ook weggeschreven naar output_path).
    """
    meta = data.metadata()
    ep_label  = stats.get('active_endpoint_label', 'onbekend')
    ep_status = stats.get('active_endpoint_status', 'onbekend')
    ep_source = stats.get('active_endpoint_source', 'onbekend')
    ep_pobs   = stats.get('active_endpoint_p_obs', None)
    intercept = stats.get('collapse_intercept_kal', None)

    lines = []
    A = lines.append

    A(f"# HESTIA-rapport — {event_name}")
    A("")
    A(f"*Automatisch gegenereerd op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"door generate_event_report.py (HESTIA-PYROX suite).*")
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
    A(f"| | |")
    A(f"|---|---|")
    A(f"| Evenement | {event_name} |")
    A(f"| Plaats | {meta['city']} ({meta['latitude']:.4f}, {meta['longitude']:.4f}) |")
    A(f"| Starttijd simulatie | {start_time} |")
    A(f"| Duur simulatie | {duration_hours:.2f} uur |")
    A(f"| Activiteit | {activity_description} |")
    # [2026-09] Previously absent from the report entirely: whether
    # sample_pace was used changes the collapse-risk/CVS-index/EHE
    # figures below by a factor of 2-10x on some metrics (confirmed this
    # session comparing Amsterdam 2024-09-22 with and without it), yet a
    # reader had no way to tell which mode produced a given report short
    # of comparing its numbers against other runs by hand. Made explicit.
    pace_note = ("Ja -- elke deelnemer heeft een eigen gesamplede pace/MET/"
                "blootstellingsduur (zie hestia_model.py's sample_recreational_"
                "pace_min_per_km(); TECHNICAL_REFERENCE.md \u00a74.6)"
                if sample_pace else
                "Nee -- alle deelnemers delen de MET/duur hierboven")
    A(f"| Per-persoon pace/MET/duur (`sample_pace`) | {pace_note} |")
    A(f"| Aantal gesimuleerde deelnemers | {n_simulations:,} |")
    A(f"| Gebruikt collapse-risico-eindpunt | {ep_label} |")
    A(f"| Kalibratiestatus van dit eindpunt | {ep_status} |")
    A(f"| Bron van het kalibratiedoel | {ep_source} |")
    if ep_pobs is not None:
        A(f"| Kalibratiedoel (P_obs) | {ep_pobs*10000:.2f} per 10.000 |")
    A(f"| Gekalibreerde intercept | {_fmt(intercept, 6)} |")
    if documented_reference:
        A(f"| Gedocumenteerd referentiecijfer voor dit evenement | {documented_reference} |")
    A("")

    # [2026-09] Circularity warning: some endpoints (hospitalisation,
    # first_aid) are calibrated directly FROM a specific real event's own
    # observed outcome (e.g. "GHOR Noord-Holland Noord, Dam tot Damloop
    # 2024" for the 50/35,000 hospitalisation rate). If THIS run simulates
    # that same event, comparing its collapse-risk output back against
    # that same observed rate is not an independent check -- the
    # intercept was fit to reproduce (an aggregate version of) exactly
    # that number by construction, so approximate agreement confirms the
    # fitting procedure worked, not that the model correctly predicted an
    # unseen outcome. Detected here by a shared 4-digit year between the
    # endpoint's source string and the simulated start_time, rather than
    # hardcoding "Dam tot Damloop 2024" specifically, so this also fires
    # correctly for any future self-referential endpoint added the same
    # way.
    import re as _re
    _source_years = set(_re.findall(r"\b(?:19|20)\d{2}\b", ep_source))
    _event_years = set(_re.findall(r"\b(?:19|20)\d{2}\b", str(start_time)))
    if _source_years and _event_years and (_source_years & _event_years):
        A("> **Let op -- mogelijke circulariteit.** Het kalibratiedoel van "
          f"dit eindpunt komt uit *{ep_source}*, hetzelfde jaar als het "
          "hier gesimuleerde evenement. Als dit een simulatie van "
          "datzelfde evenement betreft, is een vergelijking tussen de "
          "hieronder berekende collapse-risicocijfers en dat "
          "kalibratiedoel geen onafhankelijke toets -- de intercept is "
          "juist zo vastgezet dat het (geaggregeerde) model dat getal "
          "benadert. Overeenkomst bevestigt dan dat de kalibratiestap "
          "werkte, niet dat het model een niet-eerder-geziene uitkomst "
          "correct heeft voorspeld.")
        A("")

    # ------------------------------------------------------------------ #
    A("## 2. Meteorologische omstandigheden tijdens het evenement")
    A("")
    if interp_data:
        def _stat_row(label, key, unit, precision=1):
            vals = [e.get(key) for e in interp_data if e.get(key) is not None]
            if not vals:
                A(f"| {label} | n.b. | n.b. | n.b. |")
                return
            A(f"| {label} | {min(vals):.{precision}f}{unit} | "
              f"{(sum(vals)/len(vals)):.{precision}f}{unit} | {max(vals):.{precision}f}{unit} |")
        A("| Grootheid | Minimum | Gemiddelde | Maximum |")
        A("|---|---|---|---|")
        _stat_row("Luchttemperatuur, ruraal (T_air)", "temp_rural", " degC")
        _stat_row("Luchttemperatuur, stedelijk (T_air, incl. UHI)", "temp", " degC")
        _stat_row("Relatieve luchtvochtigheid", "rh", "%", 0)
        _stat_row("Windsnelheid", "wind", " m/s", 1)
        _stat_row("Globetemperatuur, ruraal", "globe_temp_rural", " degC")
        _stat_row("Globetemperatuur, stedelijk", "globe_temp", " degC")
        _stat_row("Stralingstemperatuur (MRT), ruraal", "mrt_rural", " degC")
        _stat_row("Stralingstemperatuur (MRT), stedelijk", "mrt", " degC")
        _stat_row("WBGT, ruraal", "wbgt_rural", " degC")
        _stat_row("WBGT, stedelijk", "wbgt_precomputed", " degC")
        _stat_row("UTCI, ruraal", "utci_rural", " degC")
        _stat_row("UTCI, stedelijk", "utci_precomputed", " degC")
        A("")
        A(f"Gebaseerd op {len(interp_data)} geïnterpoleerde tijdstappen over de volledige "
          f"gesimuleerde periode ({start_time}, {duration_hours:.2f} uur). De simulatie zelf "
          f"gebruikt de stedelijke waarden als invoer. \"n.b.\" betekent dat de brondata dit "
          f"veld niet meegaf; HESTIA valt in dat geval voor de simulatie zelf intern terug op "
          f"een eigen berekening die hier niet apart gerapporteerd wordt.")
    else:
        A("Niet beschikbaar voor deze run (geen weerdata meegegeven aan generate_report()).")
    A("")

    # ------------------------------------------------------------------ #
    A("## 3. Thermische uitkomsten (populatie, aan het einde van de gesimuleerde periode)")
    A("")
    A("| Grootheid | Waarde |")
    A("|---|---|")
    A(f"| Gemiddelde kern-temperatuur (T_rect) | {_fmt(stats.get('mean_t_rect'), 2, ' °C')} |")
    A(f"| T_rect, onder-/bovengrens 90%-interval | {_fmt(stats.get('lower_t_rect'), 2)} – {_fmt(stats.get('upper_t_rect'), 2, ' °C')} |")
    A(f"| T_rect, P97,5 | {_fmt(stats.get('t_rect_p975'), 2, ' °C')} |")
    A(f"| T_rect, P99 | {_fmt(stats.get('t_rect_p99'), 2, ' °C')} |")
    A(f"| Gemiddelde ervaren inspanning (RPE, Borg 6-20) | {_fmt(stats.get('mean_rpe'), 1)} |")
    A(f"| % deelnemers gestopt (RPE-drempel) | {_fmt(stats.get('percent_stopped'), 1, '%')} |")
    A(f"| % deelnemers met EHBO-contact | {_fmt(stats.get('percent_ehbo'), 1, '%')} |")
    A(f"| % deelnemers in fysiologisch niet-vol te houden toestand | {_fmt(stats.get('percent_unliveable'), 1, '%')} |")
    A("")

    # ------------------------------------------------------------------ #
    A("## 4. Cardiovasculaire uitkomsten (populatie)")
    A("")
    A("| Grootheid | Waarde |")
    A("|---|---|")
    A(f"| % deelnemers met CVS-index (CO/CO_max) > 90% | {_fmt(stats.get('pct_cvs_above_90'), 1, '%')} |")
    A(f"| % deelnemers met decompensatierisico (CO_reserve < 2,0 L/min) | {_fmt(stats.get('pct_decompensation'), 1, '%')} |")
    A(f"| Minimale CO_reserve, mediaan (P50) | {_fmt(stats.get('co_reserve_min_p50'), 2, ' L/min')} |")
    A(f"| Minimale CO_reserve, P05 | {_fmt(stats.get('co_reserve_min_p05'), 2, ' L/min')} |")
    A(f"| Piek hartslag, mediaan (P50) | {_fmt(stats.get('hr_peak_p50'), 0, ' bpm')} |")
    A(f"| Piek hartslag, P95 | {_fmt(stats.get('hr_peak_p95'), 0, ' bpm')} |")
    A("")

    # ------------------------------------------------------------------ #
    A("## 5. Collapse-risico")
    A("")
    A("| Grootheid | Waarde |")
    A("|---|---|")
    A(f"| Gemiddelde individuele collapse-kans | {_fmt(stats.get('p_collapse_mean'), 4, '%')} |")
    A(f"| Collapse-kans, P95 | {_fmt(stats.get('p_collapse_p95'), 4, '%')} |")
    A(f"| % deelnemers met individuele collapse-kans > 50% | {_fmt(stats.get('pct_high_collapse_risk'), 2, '%')} |")
    A(f"| Verwacht aantal per 1.000 deelnemers | {_fmt(stats.get('expected_collapses_per_1000'), 3)} |")
    A("")

    # ------------------------------------------------------------------ #
    A("## 6. Post-finish uitkomsten (tot 10 minuten na de finish)")
    A("")
    A("| Grootheid | Waarde |")
    A("|---|---|")
    A(f"| % deelnemers dat de conjunctieve grens (T_rect>40,5°C ÉN CO_reserve≤0) bereikt na de finish | {_fmt(stats.get('pct_ehs_postfinish'), 2, '%')} |")
    A("")

    # ------------------------------------------------------------------ #
    A("## 7. Thermoregulatoir regelfalen (experimentele mechanistische maat)")
    A("")
    A("| Grootheid | Waarde |")
    A("|---|---|")
    A(f"| % deelnemers boven Roberts' klinische drempel (AUC_klinisch > 60 °C·min) | {_fmt(stats.get('pct_roberts_kritiek'), 2, '%')} |")
    A(f"| AUC_klinisch, mediaan (P50) | {_fmt(stats.get('auc_klinisch_p50'), 2, ' °C·min')} |")
    A(f"| AUC_klinisch, P95 | {_fmt(stats.get('auc_klinisch_p95'), 2, ' °C·min')} |")
    A(f"| % deelnemers boven thermisch-kritische grens (piek T_rect > 42,0°C, los van CO_reserve) | "
      f"{_fmt(stats.get('pct_thermal_only_critical'), 2, '%')} |")
    A("")
    A("De laatste regel hierboven staat los van het conjunctieve klinische "
      "criterium in sectie 10 (dat CO_reserve≤0 vereist naast T_rect>40,5°C). "
      "Bij piek-kerntemperatuur boven ~42°C kan directe thermische celschade "
      "aan hersenweefsel optreden ongeacht cardiovasculaire status (Hubbard: "
      "humane kritieke-temperatuurgrens 41,6-42,0°C; Gähwiler et al. 1972: "
      "onomkeerbare neuronale schade vanaf 42-43°C) -- een tweede, van "
      "CO_reserve onafhankelijk pad naar CZS-uitval.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 8. Kwetsbare-staartgroep (top 2,5% naar piek T_rect)")
    A("")
    A("| Grootheid | Waarde |")
    A("|---|---|")
    A(f"| Aantal deelnemers in deze groep | {stats.get('vulnerable_tail_n', 'n.b.')} |")
    A(f"| Gemiddelde leeftijd in deze groep | {_fmt(stats.get('vulnerable_tail_age_mean'), 1, ' jaar')} |")
    A(f"| Gemiddelde piek T_rect in deze groep | {_fmt(stats.get('vulnerable_tail_mean_t_rect'), 2, ' °C')} |")
    A(f"| Minimale CO_reserve, mediaan, in deze groep | {_fmt(stats.get('vulnerable_tail_co_reserve_min_p50'), 2, ' L/min')} |")
    A(f"| % NSAID-gebruik in deze groep | {_fmt(stats.get('vulnerable_tail_nsaid_pct'), 1, '%')} |")
    A("")

    # ------------------------------------------------------------------ #
    # [2026-09-27, gevonden via onderzoek met Koos] collapse-kans, EHE en
    # het klinisch criterium zijn stuk voor stuk gebouwd rond een CONJUNCTIE
    # (thermisch EN cardiovasculair moeten allebei over hun grens gaan) of
    # een GEWOGEN SOM daarvan. Een deelnemer die op precies één van de twee
    # assen extreem scoort, maar op de andere normaal blijft, kan daardoor
    # onopvallend blijven in alle drie die cijfers -- empirisch bevestigd
    # met een deelnemer op het 99,8e T_rect-percentiel wiens collapse-kans
    # toch op een onopvallend 78e percentiel uitkwam. Deze sectie toont die
    # groep apart, puur op basis van twee al-bestaande, continue kolommen
    # (max_t_rect, cvr_cvs_index_max) -- geen nieuwe berekening. Dit is
    # een DIAGNOSTISCHE lijst, geen aanbeveling en geen aanvullend
    # risico-oordeel: of dit klinisch relevant is, is een vraag voor een
    # arts, niet voor dit model.
    EENZIJDIG_EXTREEM_PERCENTIEL = 97.5
    heeft_kolommen = all(c in results_df.columns for c in
                          ['thermisch_percentiel', 'cardiovasculair_percentiel',
                           'gemist_door_bestaande_criteria'])
    A(f"## 9. Eenzijdig-extreme profielen (niet gevangen door bestaande criteria)")
    A("")
    A(f"Deelnemers die op minstens één van de twee onderliggende, continue "
      f"assen (piek-T_rect of cvs_index_max) op of boven het "
      f"{EENZIJDIG_EXTREEM_PERCENTIEL:g}e percentiel van déze run zitten, "
      f"maar niet al worden gesignaleerd door het EHE- of klinisch "
      f"criterium (die vereisen dat T_rect ÉN CO_reserve allebei over hun "
      f"grens gaan). Dit is een diagnostische aanvulling, geen apart "
      f"risicocijfer -- zie sectie 10 voor de reeds bestaande, gevalideerde "
      f"criteria.")
    A("")
    if heeft_kolommen:
        n_gemist = int(results_df['gemist_door_bestaande_criteria'].sum())
        A(f"| Grootheid | Waarde |")
        A(f"|---|---|")
        A(f"| Drempel voor 'eenzijdig extreem' | {EENZIJDIG_EXTREEM_PERCENTIEL:g}e percentiel |")
        A(f"| Aantal eenzijdig extreem, totaal | {int(results_df['eenzijdig_extreem'].sum())} |")
        A(f"| Waarvan niet al gevangen door EHE/klinisch | {n_gemist} |")
        A("")
        if n_gemist > 0:
            gemist_df = results_df[results_df['gemist_door_bestaande_criteria'] == 1].sort_values(
                'thermisch_percentiel', ascending=False)
            A("| Deelnemer-ID | Piek T_rect (°C) | Min. CO_reserve (L/min) | "
              "Thermisch percentiel | Cardiovasculair percentiel |")
            A("|---|---|---|---|---|")
            for _, r in gemist_df.head(30).iterrows():
                A(f"| {int(r['participant_id'])} | {r['max_t_rect']:.2f} | "
                  f"{r['cvr_co_reserve_min']:.2f} | {r['thermisch_percentiel']:.1f} | "
                  f"{r['cardiovasculair_percentiel']:.1f} |")
            if n_gemist > 30:
                A(f"")
                A(f"*(eerste 30 van {n_gemist} getoond, gesorteerd op thermisch percentiel; "
                  f"volledige lijst in de Excel-export.)*")
    else:
        A("*(Deze kolommen zijn niet aanwezig in deze run -- vereist een "
          "suite-versie van 2026-09-27 of later.)*")
    A("")

    # ------------------------------------------------------------------ #
    A("## 10. Herkomst en status van dit model")
    A("")
    A("Feitelijke stand van zaken van het model op het moment van deze run "
      "(HESTIA-PYROX suite):")
    A("")
    A("- De cardiovasculaire respons (CO_max, CO_demand, HR) is berekend "
      "volgens Lloyd et al. (2022, J Appl Physiol 133:247-261), Eq. 12-31.")
    A("- De kernlichaamstemperatuur is berekend met het JOS-3-model "
      "(Takahashi et al. 2021).")
    A(f"- De collapse-risico-intercept voor het gebruikte eindpunt "
      f"('{ep_label}') heeft de status '{ep_status}' "
      f"(zie COLLAPSE_ENDPOINTS in hestia_model.py voor de volledige "
      f"kalibratiegeschiedenis en -steekproefgrootte van dit eindpunt).")
    A("- Windrichting wordt niet gemeten in de brondata; de relatieve wind "
      "die een deelnemer ondervindt (eigen voortbewegingssnelheid "
      "gecombineerd met omgevingswind) wordt per deelnemer met een "
      "willekeurige hoek gesimuleerd.")
    A(f"- Deze run gebruikte {n_simulations:,} gesimuleerde deelnemers.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 11. Falmouth-EHS / EHE / klinisch criterium")
    A("")
    if bridge_summary is None:
        A("Deze laag was niet beschikbaar voor deze run (geen `bridge_summary` "
          "meegegeven aan `generate_report()` -- vereist een aanroep van "
          "`hestia_bridge._summarize_results(all_results)` op dezelfde "
          "`all_results` als deze run).")
        A("")
    else:
        A("| Grootheid | Waarde |")
        A("|---|---|")
        A(f"| Falmouth-EHS (epidemiologisch, temperatuur-alleen; DeMartini et al. 2014), per 1.000 | "
          f"{_fmt(bridge_summary.get('falmouth_ehs_per_1000'), 3)} |")
        n_ehe = bridge_summary.get('n_true_ehe_hits')
        n_ehs = bridge_summary.get('n_true_ehs_hits')
        A(f"| EHE-criterium (T_rect>39,5°C ÉN CO_reserve<0), % deelnemers | "
          f"{_fmt(bridge_summary.get('pct_true_ehe_criterion'), 2, '%')} "
          f"({n_ehe if n_ehe is not None else '?'}/{n_simulations:,}) |")
        A(f"| Klinisch criterium (T_rect≥40,5°C ÉN CO_reserve≤0), % deelnemers | "
          f"{_fmt(bridge_summary.get('pct_true_ehs_criterion'), 2, '%')} "
          f"({n_ehs if n_ehs is not None else '?'}/{n_simulations:,}) |")
        A("")
        A("Een uitkomst van 0% op een van beide criteria hierboven betekent niet "
          "vanzelfsprekend dat de drempel ver weg was -- zie de marge-analyse "
          "hieronder, gebaseerd op dezelfde onderliggende steekproefmomenten "
          "(T_rect, CO_reserve), voor hoe dichtbij het daadwerkelijk kwam. "
          "Omdat een conjunctief criterium BEIDE grenzen tegelijk vereist, is "
          "de bepalende marge steeds de as die als laatst zou sluiten, niet "
          "een van beide assen los.")
        A("")
        pairs = bridge_summary.get('t_rect_co_reserve_pairs') or []
        for label, tt, ct in (("EHE-drempel", 39.5, 0.0), ("Klinische drempel", 40.5, 0.0)):
            margin_lines = format_margin_lines(label, margin_to_threshold_stats(pairs, tt, ct))
            if margin_lines:
                A(f"- {margin_lines[0]}")
                for line in margin_lines[1:]:
                    A(f"  {line}")
            A("")

    # ------------------------------------------------------------------ #
    A("## 12. Grafieken")
    A("")
    # [2026-09-01] Elke naam volgt hestia_plots.generate_population_plots()'s
    # eigen, vaste naamgeving (HESTIA_plotN_<label>_<stad>_<datum>_n<N>.png)
    # -- matchen op het "plotN_"-substring is dus onafhankelijk van stad,
    # datum of deelnemersaantal, en werkt voor elke run.
    PLOT_CAPTIONS = [
        ("plot1_", "Kerntemperatuur, hartslag/cardiovasculaire belasting en "
         "uitdroging/stopfrequentie van de hele gesimuleerde groep, over de "
         "tijd heen. De kerntemperatuur-lijn toont ook het gemiddelde traject "
         "van de kwetsbaarste 2,5% (naar piek-kerntemperatuur) apart, naast "
         "het populatiegemiddelde."),
        ("plot2_", "Spreiding in piekwaarden (kerntemperatuur, ervaren "
         "inspanning, vochtverlies) per leeftijdsgroep en geslacht -- laat "
         "zien of bepaalde groepen structureel hoger uitkomen dan andere, "
         "niet alleen het populatiegemiddelde uit sectie 3."),
        ("plot3_", "Histogram van de laagste hartminuutvolume-reserve die "
         "elke deelnemer tijdens de race bereikte. De oranje lijn markeert "
         "de drempel voor decompensatierisico (2,0 L/min), de rode lijn het "
         "punt waarop de reserve daadwerkelijk op is (0 L/min, onderdeel van "
         "het EHE/klinisch-criterium uit sectie 10)."),
        ("plot4_", "Histogram van de individueel berekende collapse-kans per "
         "deelnemer (het gekalibreerde model uit sectie 5) -- laat zien of "
         "het risico geconcentreerd is bij een kleine groep met een hoge "
         "kans, of breed verspreid is over de hele populatie met overal een "
         "laag risico."),
        ("plot5_", "Elke stip is één deelnemer: piek-kerntemperatuur tegen de "
         "laagste hartminuutvolume-reserve, gekleurd naar individuele "
         "collapse-kans. De rode lijnen markeren het klinische criterium "
         "(T_rect>40,5°C ÉN CO_reserve≤0) -- de rechtsonder-hoek toont in "
         "één oogopslag wie zowel warm ÁLS cardiovasculair belast tegelijk "
         "was, in plaats van de twee losse verdelingen uit de vorige twee "
         "grafieken."),
        ("plot6_", "Individuele collapse-kans uitgezet tegen leeftijd, apart "
         "voor mannen en vrouwen -- laat zien of het risico geconcentreerd "
         "is in specifieke leeftijdsgroepen, of gelijkmatig verdeeld is over "
         "de hele leeftijdsrange."),
        ("plot7_", "Het volledige tijdsverloop (start tot 10 minuten na de "
         "finish) van kerntemperatuur en hartminuutvolume-reserve voor de "
         "tien deelnemers met de hoogste piektemperatuur, plus de tien met "
         "de laagste reserve -- laat zien wannéér in de race deze twee "
         "groepen risico begonnen te lopen, en of dat vóór of ná de finish "
         "gebeurde."),
        ("plot8_", "De cumulatieve 'conjunctieve dosis' (hoe lang en hoe ver "
         "iemand tegelijk boven de temperatuur- én onder de reserve-drempel "
         "zat, opgeteld over de tijd) voor dezelfde twee groepen als "
         "hierboven. Elke lijn vermeldt ook hoeveel aparte keren (episodes) "
         "en hoeveel minuten die deelnemer daadwerkelijk aan beide "
         "voorwaarden tegelijk voldeed -- een enkel eindgetal verbergt of "
         "dat één aanhoudende periode was of meerdere korte."),
        ("plot9_", "De cumulatieve tijd-gewogen oppervlakte onder de curve "
         "boven 40,5°C (Roberts 2007's klinische dosis-maat) voor de "
         "deelnemers met de hoogste eindwaarde. In tegenstelling tot de "
         "vorige grafiek telt deze maat alleen temperatuur, niet de "
         "cardiovasculaire reserve -- een tweede, onafhankelijke blik op "
         "dezelfde vraag."),
        ("plot10_", "Dezelfde soort maat als hierboven, maar met een lagere, "
         "diagnostische drempel (39,0°C in plaats van 40,5°C) die geen "
         "vastgestelde klinische betekenis heeft. De grafiek toont daarom "
         "het 95e-percentiel van déze steekproef zelf als referentielijn, "
         "niet een geleende klinische grens."),
        ("plot11_", "De cumulatieve tekort-dosis van de hartminuutvolume-"
         "reserve alleen, los van de temperatuur -- isoleert het "
         "cardiovasculaire spoor van het thermische spoor: bij sommige "
         "deelnemers kan de bloedvraag van de spieren de hartreserve al "
         "uitputten vóórdat de temperatuur zelf een probleem wordt."),
    ]
    if plot_paths:
        import os as _os
        shown = 0
        for prefix, caption in PLOT_CAPTIONS:
            match = next((p for p in plot_paths if prefix in _os.path.basename(p)), None)
            if match is None:
                continue
            shown += 1
            A(f"![{prefix.rstrip('_')}]({_os.path.basename(match)})")
            A("")
            A(f"*{caption}*")
            A("")
        if shown == 0:
            A("Geen van de verwachte HESTIA-plotbestanden werd herkend in de "
              "meegegeven lijst -- zie generate_report()'s plot_paths-parameter.")
    else:
        A("Niet gegenereerd voor deze run (geen plot_paths meegegeven aan "
          "generate_report() -- run_hestia.py's eigen \"Generate plots?\"-"
          "vraag, vóór de rapportvraag, moet daarvoor bevestigend zijn "
          "beantwoord).")
        A("")

    A("*Einde rapport.*")

    report_text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    return report_text
