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
        output_path="rapport_utrecht_2026.md",
    )

Het sjabloon is vast (dezelfde secties, dezelfde volgorde, ongeacht
evenement) zodat rapporten van verschillende evenementen direct naast
elkaar te leggen zijn.
"""

from taal import vt, getal

NB = vt("n.b.", "n/a")   # not available


from datetime import datetime, timezone
import numpy as np

import hestia_model as hestia
from thermopoulos_loader import ThermopoulosData
from hestia_bridge import margin_to_threshold_stats, format_margin_lines


def _sig(x, n=2):
    """[2026-10-25] Round to n significant digits, Dutch decimal comma.
    Absolute model probabilities carry far less precision than 3-4 decimals
    suggest (one reference event per endpoint), so they are shown rounded."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return NB
    if not np.isfinite(x):
        return NB
    if x == 0:
        return "0"
    from math import floor, log10
    d = max(0, n - 1 - int(floor(log10(abs(x)))))
    return f"{round(x, d):.{d}f}".replace(".", vt(",", "."))


def _sig_band(x, lo, hi, scale=1.0, suffix=""):
    """'value (band lo-hi)' with significant-digit rounding; the band is the
    intercept-calibration uncertainty from hestia_model._intercept_sensitivity."""
    v = _sig(None if x is None else float(x) * scale)
    if lo is None or hi is None or v == NB:
        return v + suffix if v != NB else v
    return vt(f"{v}{suffix} (bandbreedte {_sig(float(lo) * scale)}–{_sig(float(hi) * scale)}{suffix})", f"{v}{suffix} (range {_sig(float(lo) * scale)}–{_sig(float(hi) * scale)}{suffix})")


def _fmt(x, decimals=2, suffix=""):
    """Format a scalar, or the final value of a time series, as text.
    Returns 'n.b.' (niet beschikbaar) if the value is missing/NaN/empty."""
    if x is None:
        return NB
    arr = np.asarray(x)
    if arr.size == 0:
        return NB
    if arr.ndim > 0:
        x = arr[-1]  # final value of the time series (end of simulated window)
    try:
        if np.isnan(x):
            return NB
    except TypeError:
        return NB
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
                     sample_pace: bool = False,
                     event_dist_km: float = None,
                     training_factor: float = None,
                     acclimatization_factor: float = None,
                     population: str = None) -> str:
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
        voor dit evenement, indien bekend (bijv. "Gedocumenteerd: 3,7 per
        10.000 starters (EHS, Boston 2015-2019, Breslow et al. 2021)"). Puur ter feitelijke vermelding
        naast de modeluitkomst -- geen vergelijking of oordeel wordt
        toegevoegd; dat blijft aan de lezer.
    bridge_summary : dict, optional
        [2026-08-26] Uitvoer van hestia_bridge._summarize_results(all_results)
        voor dezelfde run (falmouth_ehs_per_1000, pct_true_ehe_criterion,
        pct_true_ehs_criterion, t_rect_co_reserve_pairs, ...) -- een analyse-
        laag die niet native in monte_carlo_adult()'s eigen stats-dict zit.
        None (de standaard) betekent: deze laag was niet beschikbaar voor
        deze run, en sectie 11 vermeldt dat expliciet in plaats van de
        cijfers te verzinnen of over te slaan zonder uitleg.
    plot_paths : list, optional
        [2026-09-01] Padnamen van al gegenereerde PNG-bestanden, zoals
        hestia_plots.generate_population_plots() teruggeeft (run_hestia.py's
        eigen "Generate plots?"-vraag, VÓÓR de rapportvraag zelf, roept die
        al aan). Elke bekende HESTIA_plotN_...-naam krijgt een eigen,
        toegankelijke verklaring in sectie 12; een pad dat niet bij een
        bekend patroon past, wordt overgeslagen. None of een lege lijst laat
        sectie 12 een "niet gegenereerd voor deze run"-vermelding tonen.
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
    ep_label  = stats.get('active_endpoint_label', vt('onbekend', 'unknown'))
    ep_status = stats.get('active_endpoint_status', vt('onbekend', 'unknown'))
    ep_source = stats.get('active_endpoint_source', vt('onbekend', 'unknown'))
    ep_pobs   = stats.get('active_endpoint_p_obs', None)
    intercept = stats.get('collapse_intercept_kal', None)

    lines = []
    A = lines.append

    A(vt(f"# HESTIA-rapport — {event_name}", f"# HESTIA report — {event_name}"))
    A("")
    A(vt(f"*Automatisch gegenereerd op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"door generate_event_report.py (HESTIA-PYROX suite).*",
         f"*Generated automatically on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"by generate_event_report.py (HESTIA-PYROX suite).*"))
    A("")
    A(vt("**Dit rapport bevat uitsluitend feitelijke, door het model berekende "
      "waarden en hun herkomst. Er zijn geen aanbevelingen of adviezen "
      "toegevoegd.**",
         "**This report contains only factual values calculated by the model "
      "and their provenance. No recommendations or advice have been "
      "added.**"))
    A("")
    A("---")
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 1. Gesimuleerd scenario", "## 1. Simulated scenario"))
    A("")
    A(f"| | |")
    A(f"|---|---|")
    A(vt(f"| Evenement | {event_name} |", f"| Event | {event_name} |"))
    A(vt(f"| Plaats | {meta['city']} ({meta['latitude']:.4f}, {meta['longitude']:.4f}) |", f"| Location | {meta['city']} ({meta['latitude']:.4f}, {meta['longitude']:.4f}) |"))
    A(vt(f"| Starttijd simulatie | {start_time} |", f"| Simulation start time | {start_time} |"))
    # [2026-10-14] Distance was missing from the report, and with
    # sample_pace=True the displayed duration was the user-entered value,
    # not the window actually simulated (run_hestia widens it to
    # PACE_MIN_PER_KM_CEILING * event_dist_km so the slowest runner fits).
    if event_dist_km:
        A(vt(f"| Afstand | {event_dist_km:g} km |", f"| Distance | {event_dist_km:g} km |"))
    _eff_hours = duration_hours
    if sample_pace and event_dist_km:
        _eff_hours = max(duration_hours, hestia.race_window_hours(event_dist_km))
    if abs(_eff_hours - duration_hours) > 1e-6:
        A(vt(f"| Duur simulatie | {_eff_hours:.2f} uur (opgegeven {duration_hours:.2f} uur; "
          f"verlengd zodat de langzaamste gesamplede deelnemer binnen het venster valt",
             f"| Simulation duration | {_eff_hours:.2f} h (entered {duration_hours:.2f} h; "
          f"extended so that the slowest sampled participant falls within the window")
          + (vt(f", plus ruimte voor vertragen tot de bezemwagen (×{hestia.RACE_SWEEP_FACTOR:g})", f", plus room for slowing down until the sweeper bus (×{hestia.RACE_SWEEP_FACTOR:g})")
             if hestia.RACE_DISTANCE_MODE else "") + ") |")
    else:
        A(vt(f"| Duur simulatie | {duration_hours:.2f} uur |", f"| Simulation duration | {duration_hours:.2f} h |"))
    A(vt(f"| Activiteit | {activity_description} |", f"| Activity | {activity_description} |"))
    # [2026-09] Previously absent from the report entirely: whether
    # sample_pace was used changes the collapse-risk/CVS-index/EHE
    # figures below by a factor of 2-10x on some metrics (confirmed this
    # session comparing Amsterdam 2024-09-22 with and without it), yet a
    # reader had no way to tell which mode produced a given report short
    # of comparing its numbers against other runs by hand. Made explicit.
    pace_note = (vt("Ja -- elke deelnemer heeft een eigen gesamplede pace/MET/"
                "blootstellingsduur (zie hestia_model.py's sample_recreational_"
                "pace_min_per_km(); TECHNICAL_REFERENCE.md \u00a74.6)",
                    "Yes -- each participant has their own sampled pace/MET/"
                "exposure duration (see hestia_model.py's sample_recreational_"
                "pace_min_per_km(); TECHNICAL_REFERENCE.md \u00a74.6)")
                if sample_pace else
                vt("Nee -- alle deelnemers delen de MET/duur hierboven", "No -- all participants share the MET/duration above"))
    A(vt(f"| Per-persoon pace/MET/duur (`sample_pace`) | {pace_note} |", f"| Per-person pace/MET/duration (`sample_pace`) | {pace_note} |"))
    if population:   # [2026-11-02]
        A(vt("| Populatie | ", "| Population | ") + (vt("wandelaars (Vierdaagse-type: leeftijd, BMI en VO2max van "
                              "wandelaars, zie TECHNICAL_REFERENCE \u00a74.6.3)",
                                 "walkers (Vierdaagse type: age, BMI and VO2max of "
                              "walkers, see TECHNICAL_REFERENCE \u00a74.6.3)")
                              if str(population).lower().startswith("w") else
                              vt("recreatieve hardlopers", "recreational runners")) + " |")
    # [2026-10-14] With sample_pace the header MET above is nominal only;
    # show the distribution that was actually simulated.
    if results_df is not None and 'pct_vo2max' in getattr(results_df, 'columns', []):
        _pv = results_df['pct_vo2max'].astype(float)
        _met = results_df['implied_met_initial'].astype(float) if 'implied_met_initial' in results_df.columns else None
        _txt = (vt(f"mediaan {_pv.median()*100:.0f}% (P05-P95: {_pv.quantile(.05)*100:.0f}-"
                f"{_pv.quantile(.95)*100:.0f}%)",
                   f"median {_pv.median()*100:.0f}% (P05-P95: {_pv.quantile(.05)*100:.0f}-"
                f"{_pv.quantile(.95)*100:.0f}%)"))
        if _met is not None:
            _txt += vt(f"; MET mediaan {_met.median():.1f} (P05-P95: {_met.quantile(.05):.1f}-{_met.quantile(.95):.1f})", f"; MET median {_met.median():.1f} (P05-P95: {_met.quantile(.05):.1f}-{_met.quantile(.95):.1f})")
        A(vt(f"| Gesimuleerde intensiteit (% VO2max; MET) | {_txt} |", f"| Simulated intensity (% VO2max; MET) | {_txt} |"))
        if 'finish_time_h' in results_df.columns and (results_df['finish_time_h'] > 0).any():
            _ft = results_df['finish_time_h'].astype(float)
            def _hm(h):
                return f"{int(h)}:{int(round((h - int(h)) * 60)):02d}"
            _line = vt(f"mediaan {_hm(_ft.median())} (P05-P95: {_hm(_ft.quantile(.05))}-{_hm(_ft.quantile(.95))})", f"median {_hm(_ft.median())} (P05-P95: {_hm(_ft.quantile(.05))}-{_hm(_ft.quantile(.95))})")
            if 'gender' in results_df.columns:
                _parts = []
                for _g, _lab in (('male', vt('mannen', 'men')), ('female', vt('vrouwen', 'women'))):
                    _sub = _ft[results_df['gender'] == _g]
                    if len(_sub):
                        _parts.append(f"{_lab} {_hm(_sub.median())}")
                if _parts:
                    _line += "; " + ", ".join(_parts)
            A(vt(f"| Gesimuleerde finishtijd (uu:mm) | {_line} |", f"| Simulated finish time (hh:mm) | {_line} |"))
    # [2026-10-15] Both shift MET, RPE and sweat response noticeably
    # (training_offset = training_factor x 5% of MET) but were not shown,
    # so two reports could not be compared on the same footing.
    if training_factor is not None or acclimatization_factor is not None:
        A(vt(f"| Training / acclimatisatie (factor 0-1) | "
          f"{_fmt(training_factor, 2)} / {_fmt(acclimatization_factor, 2)} |",
             f"| Training / acclimatisation (factor 0-1) | "
          f"{_fmt(training_factor, 2)} / {_fmt(acclimatization_factor, 2)} |"))
    A(vt(f"| Aantal gesimuleerde deelnemers | {n_simulations:,} |", f"| Number of simulated participants | {n_simulations:,} |"))
    A(vt(f"| Gebruikt collapse-risico-eindpunt | {ep_label} |", f"| Collapse-risk endpoint used | {ep_label} |"))
    A(vt(f"| Kalibratiestatus van dit eindpunt | {ep_status} |", f"| Calibration status of this endpoint | {ep_status} |"))
    A(vt(f"| Bron van het kalibratiedoel | {ep_source} |", f"| Source of the calibration target | {ep_source} |"))
    if ep_pobs is not None:
        A(vt(f"| Kalibratiedoel (P_obs) | {ep_pobs*10000:.2f} per 10.000 |", f"| Calibration target (P_obs) | {ep_pobs*10000:.2f} per 10,000 |"))
    A(vt(f"| Gekalibreerde intercept | {_fmt(intercept, 6)} |", f"| Calibrated intercept | {_fmt(intercept, 6)} |"))
    if documented_reference:
        A(vt(f"| Gedocumenteerd referentiecijfer voor dit evenement | {documented_reference} |", f"| Documented reference figure for this event | {documented_reference} |"))
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
        A(vt("> **Let op -- mogelijke circulariteit.** Het kalibratiedoel van "
          f"dit eindpunt komt uit *{ep_source}*, hetzelfde jaar als het "
          "hier gesimuleerde evenement. Als dit een simulatie van "
          "datzelfde evenement betreft, is een vergelijking tussen de "
          "hieronder berekende collapse-risicocijfers en dat "
          "kalibratiedoel geen onafhankelijke toets -- de intercept is "
          "juist zo vastgezet dat het (geaggregeerde) model dat getal "
          "benadert. Overeenkomst bevestigt dan dat de kalibratiestap "
          "werkte, niet dat het model een niet-eerder-geziene uitkomst "
          "correct heeft voorspeld.",
             "> **Note -- possible circularity.** The calibration target of "
          f"this endpoint comes from *{ep_source}*, the same year as the "
          "event simulated here. If this is a simulation of that same "
          "event, a comparison between the collapse-risk figures "
          "calculated below and that calibration target is not an "
          "independent test -- the intercept was set precisely so that the "
          "(aggregated) model approaches that number. Agreement then "
          "confirms that the calibration step worked, not that the model "
          "correctly predicted an outcome it had not seen."))
        A("")

    # ------------------------------------------------------------------ #
    A(vt("## 2. Meteorologische omstandigheden tijdens het evenement", "## 2. Meteorological conditions during the event"))
    A("")
    if interp_data:
        def _stat_row(label, key, unit, precision=1):
            vals = [e.get(key) for e in interp_data if e.get(key) is not None]
            if not vals:
                A(f"| {label} | {NB} | {NB} | {NB} |")
                return
            A(f"| {label} | {min(vals):.{precision}f}{unit} | "
              f"{(sum(vals)/len(vals)):.{precision}f}{unit} | {max(vals):.{precision}f}{unit} |")
        A(vt("| Grootheid | Minimum | Gemiddelde | Maximum |", "| Quantity | Minimum | Mean | Maximum |"))
        A("|---|---|---|---|")
        _stat_row(vt("Luchttemperatuur, ruraal (T_air)", "Air temperature, rural (T_air)"), "temp_rural", " degC")
        _stat_row(vt("Luchttemperatuur, stedelijk (T_air, incl. UHI)", "Air temperature, urban (T_air, incl. UHI)"), "temp", " degC")
        _stat_row(vt("Relatieve luchtvochtigheid", "Relative humidity"), "rh", "%", 0)
        _stat_row(vt("Windsnelheid", "Wind speed"), "wind", " m/s", 1)
        _stat_row(vt("Globetemperatuur, ruraal", "Globe temperature, rural"), "globe_temp_rural", " degC")
        _stat_row(vt("Globetemperatuur, stedelijk", "Globe temperature, urban"), "globe_temp", " degC")
        _stat_row(vt("Stralingstemperatuur (MRT), ruraal", "Radiant temperature (MRT), rural"), "mrt_rural", " degC")
        _stat_row(vt("Stralingstemperatuur (MRT), stedelijk", "Radiant temperature (MRT), urban"), "mrt", " degC")
        _stat_row(vt("WBGT, ruraal", "WBGT, rural"), "wbgt_rural", " degC")
        _stat_row(vt("WBGT, stedelijk", "WBGT, urban"), "wbgt_precomputed", " degC")
        _stat_row(vt("UTCI, ruraal", "UTCI, rural"), "utci_rural", " degC")
        _stat_row(vt("UTCI, stedelijk", "UTCI, urban"), "utci_precomputed", " degC")
        A("")
        A(vt(f"Gebaseerd op {len(interp_data)} geïnterpoleerde tijdstappen over de volledige "
          f"gesimuleerde periode ({start_time}, {_eff_hours:.2f} uur). De simulatie zelf "
          f"gebruikt de stedelijke waarden als invoer. \"n.b.\" betekent dat de brondata dit "
          f"veld niet meegaf; HESTIA valt in dat geval voor de simulatie zelf intern terug op "
          f"een eigen berekening die hier niet apart gerapporteerd wordt.",
             f"Based on {len(interp_data)} interpolated time steps over the full "
          f"simulated period ({start_time}, {_eff_hours:.2f} h). The simulation itself "
          f"uses the urban values as input. \"n/a\" means that the source data did not "
          f"provide this field; in that case HESTIA falls back internally on its own "
          f"calculation for the simulation, which is not reported separately here."))
    else:
        A(vt("Niet beschikbaar voor deze run (geen weerdata meegegeven aan generate_report()).", "Not available for this run (no weather data passed to generate_report())."))
    A("")

    # ------------------------------------------------------------------ #
    # [2026-10-14] Was "aan het einde van de gesimuleerde periode": with
    # sample_pace=True the final timestep only contains the slowest
    # runners still on course, so those values described a small,
    # unrepresentative subgroup. Now: each participant's own PEAK value
    # (finish-independent), from the per-participant export.
    A(vt("## 3. Thermische uitkomsten (populatie, per deelnemer de eigen piekwaarde)", "## 3. Thermal outcomes (population, each participant's own peak value)"))
    A("")
    A(vt("| Grootheid | Waarde |", "| Quantity | Value |"))
    A("|---|---|")
    _has_df = results_df is not None and 'max_t_rect' in getattr(results_df, 'columns', [])
    if _has_df:
        _pk = results_df['max_t_rect'].astype(float)
        A(vt(f"| Piek T_rect tijdens de race, gemiddelde | {_pk.mean():.2f} °C |", f"| Peak T_rect during the race, mean | {_pk.mean():.2f} °C |"))
        A(vt(f"| Piek T_rect, P05 – P95 | {_pk.quantile(.05):.2f} – {_pk.quantile(.95):.2f} °C |", f"| Peak T_rect, P05 – P95 | {_pk.quantile(.05):.2f} – {_pk.quantile(.95):.2f} °C |"))
        A(vt(f"| Piek T_rect, P97,5 | {_pk.quantile(.975):.2f} °C |", f"| Peak T_rect, P97.5 | {_pk.quantile(.975):.2f} °C |"))
        A(vt(f"| Piek T_rect, P99 | {_pk.quantile(.99):.2f} °C |", f"| Peak T_rect, P99 | {_pk.quantile(.99):.2f} °C |"))
        if 'max_t_rect_incl_postfinish' in results_df.columns:
            _pk2 = results_df['max_t_rect_incl_postfinish'].astype(float)
            A(vt(f"| Piek T_rect incl. 10 min na de finish, gemiddelde / P99 | "
              f"{_pk2.mean():.2f} / {_pk2.quantile(.99):.2f} °C |",
                 f"| Peak T_rect incl. 10 min after the finish, mean / P99 | "
              f"{_pk2.mean():.2f} / {_pk2.quantile(.99):.2f} °C |"))
        if 'max_rpe' in results_df.columns:
            A(vt(f"| Piek ervaren inspanning (RPE, Borg 6-20), gemiddelde | {results_df['max_rpe'].astype(float).mean():.1f} |", f"| Peak perceived exertion (RPE, Borg 6-20), mean | {results_df['max_rpe'].astype(float).mean():.1f} |"))
        if 'pacing_reductie_pct' in results_df.columns:
            _pr = results_df['pacing_reductie_pct'].astype(float)
            A(vt(f"| Tempo-aanpassing door de pacing-regelkring (max. MET-reductie), mediaan / P95 | "
              f"{_pr.median():.1f}% / {_pr.quantile(.95):.1f}% |",
                 f"| Pace adjustment by the pacing control loop (max. MET reduction), median / P95 | "
              f"{_pr.median():.1f}% / {_pr.quantile(.95):.1f}% |"))
    else:
        A(vt(f"| Gemiddelde kern-temperatuur (T_rect), laatste tijdstap | {_fmt(stats.get('mean_t_rect'), 2, ' °C')} |", f"| Mean core temperature (T_rect), last time step | {_fmt(stats.get('mean_t_rect'), 2, ' °C')} |"))
    _stopped = stats.get('percent_stopped')
    _stopped_max = (float(np.nanmax(np.asarray(_stopped, dtype=float)))
                    if _stopped is not None and np.size(_stopped) and not np.all(np.isnan(np.asarray(_stopped, dtype=float)))
                    else None)
    A(vt(f"| % deelnemers gestopt (RPE-drempel), hoogste waarde over de tijd | {_fmt(_stopped_max, 1, '%')} |", f"| % participants stopped (RPE threshold), highest value over time | {_fmt(_stopped_max, 1, '%')} |"))
    # [2026-10-14] 'percent_ehbo' never existed in stats (always "n.b."),
    # while plot 1 showed a "% First Aid" curve up to ~80%. That curve is
    # hestia_model's broad screening flag (T_rect>=40.5 OR water loss>=2%
    # OR RPE>=17), NOT a first-aid prediction. Reported under its real name.
    _fa = stats.get('percent_first_aid')
    _fa_max = (float(np.nanmax(np.asarray(_fa, dtype=float)))
               if _fa is not None and np.size(_fa) and not np.all(np.isnan(np.asarray(_fa, dtype=float)))
               else None)
    A(vt(f"| Screeningsvlag (T_rect≥40,5°C óf vochtverlies≥2% óf RPE≥17), hoogste aandeel van nog actieve deelnemers | "
      f"{_fmt(_fa_max, 1, '%')} |",
         f"| Screening flag (T_rect≥40.5°C or fluid loss≥2% or RPE≥17), highest share of participants still active | "
      f"{_fmt(_fa_max, 1, '%')} |"))
    A(vt(f"| % deelnemers in fysiologisch niet-vol te houden toestand | {_fmt(stats.get('percent_unliveable'), 1, '%')} |", f"| % participants in a physiologically unsustainable state | {_fmt(stats.get('percent_unliveable'), 1, '%')} |"))
    A("")
    A(vt("De screeningsvlag is een bewust ruime signaleringsgrens, geen voorspelling "
      "van EHBO-contacten; een vochtverlies van 2% komt bij een lange inspanning "
      "bij een groot deel van de deelnemers voor.",
         "The screening flag is a deliberately wide signalling limit, not a prediction "
      "of first-aid contacts; a fluid loss of 2% occurs in a large share of participants "
      "during a long exertion."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 4. Cardiovasculaire uitkomsten (populatie)", "## 4. Cardiovascular outcomes (population)"))
    A("")
    A(vt("| Grootheid | Waarde |", "| Quantity | Value |"))
    A("|---|---|")
    A(vt(f"| % deelnemers met CVS-index (CO/CO_max) > 90% | {_fmt(stats.get('pct_cvs_above_90'), 1, '%')} |", f"| % participants with CVS index (CO/CO_max) > 90% | {_fmt(stats.get('pct_cvs_above_90'), 1, '%')} |"))
    A(vt(f"| % deelnemers met decompensatierisico (CO_reserve < 2,0 L/min) | {_fmt(stats.get('pct_decompensation'), 1, '%')} |", f"| % participants at risk of decompensation (CO_reserve < 2.0 L/min) | {_fmt(stats.get('pct_decompensation'), 1, '%')} |"))
    A(vt(f"| Minimale CO_reserve, mediaan (P50) | {_fmt(stats.get('co_reserve_min_p50'), 2, ' L/min')} |", f"| Minimum CO_reserve, median (P50) | {_fmt(stats.get('co_reserve_min_p50'), 2, ' L/min')} |"))
    A(vt(f"| Minimale CO_reserve, P05 | {_fmt(stats.get('co_reserve_min_p05'), 2, ' L/min')} |", f"| Minimum CO_reserve, P05 | {_fmt(stats.get('co_reserve_min_p05'), 2, ' L/min')} |"))
    A(vt(f"| Piek hartslag, mediaan (P50) | {_fmt(stats.get('hr_peak_p50'), 0, ' bpm')} |", f"| Peak heart rate, median (P50) | {_fmt(stats.get('hr_peak_p50'), 0, ' bpm')} |"))
    A(vt(f"| Piek hartslag, P95 | {_fmt(stats.get('hr_peak_p95'), 0, ' bpm')} |", f"| Peak heart rate, P95 | {_fmt(stats.get('hr_peak_p95'), 0, ' bpm')} |"))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 5. Collapse-risico", "## 5. Collapse risk"))
    A("")
    # [2026-10-17] Make explicit that this is a model quantity, not a
    # diagnosis (external review 2026-10-17, point 4.1).
    A(vt("De collapse-kans is een **berekende modelkans**, geen klinische diagnose. "
      "Ze volgt uit kerntemperatuur, cardiovasculaire reserve en vochtverlies van "
      "elke gesimuleerde deelnemer, met een intercept die zo is gekalibreerd dat "
      "het gemiddelde onder de referentieomstandigheden gelijk is aan het "
      "waargenomen aantal gevallen van het gekozen eindpunt (zie sectie 1). "
      "De drempelcriteria in sectie 6 en 11 zijn screeningscriteria, ook geen diagnose.",
         "The collapse probability is a **calculated model probability**, not a clinical diagnosis. "
      "It follows from core temperature, cardiovascular reserve and fluid loss of "
      "each simulated participant, with an intercept calibrated so that "
      "the mean under the reference conditions equals the "
      "observed number of cases of the chosen endpoint (see section 1). "
      "The threshold criteria in sections 6 and 11 are screening criteria, not a diagnosis either."))
    A("")
    A(vt("| Grootheid | Waarde |", "| Quantity | Value |"))
    A("|---|---|")
    # [2026-10-25] Rounded to 2 significant digits, with the calibration band.
    _lo, _hi = stats.get('p_collapse_mean_lo'), stats.get('p_collapse_mean_hi')
    A(vt(f"| Gemiddelde individuele collapse-kans | {_sig_band(stats.get('p_collapse_mean'), _lo, _hi, 1.0, ' %')} |", f"| Mean individual collapse probability | {_sig_band(stats.get('p_collapse_mean'), _lo, _hi, 1.0, ' %')} |"))
    A(vt(f"| Collapse-kans, P95 | {_sig(stats.get('p_collapse_p95'))} % |", f"| Collapse probability, P95 | {_sig(stats.get('p_collapse_p95'))} % |"))
    A(vt(f"| % deelnemers met individuele collapse-kans > 50% | {_fmt(stats.get('pct_high_collapse_risk'), 1, '%')} |", f"| % participants with individual collapse probability > 50% | {_fmt(stats.get('pct_high_collapse_risk'), 1, '%')} |"))
    A(vt(f"| Verwacht aantal per 1.000 deelnemers | {_sig_band(stats.get('p_collapse_mean'), _lo, _hi, 10.0)} |", f"| Expected number per 1,000 participants | {_sig_band(stats.get('p_collapse_mean'), _lo, _hi, 10.0)} |"))
    A("")
    A(vt("Deze absolute getallen zijn onzeker: elk eindpunt is gekalibreerd op één "
      "referentie-evenement. Gebruik ze vooral om scenario's onderling te "
      "vergelijken (dag tegen dag, starttijd tegen starttijd).",
         "These absolute numbers are uncertain: each endpoint is calibrated on one "
      "reference event. Use them mainly to compare scenarios with each other "
      "(day against day, start time against start time)."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 6. Post-finish uitkomsten (30 minuten na de finish)", "## 6. Post-finish outcomes (30 minutes after the finish)"))
    A("")
    A(vt("| Grootheid | Waarde |", "| Quantity | Value |"))
    A("|---|---|")
    A(vt(f"| % deelnemers dat de conjunctieve grens (T_rect>40,5°C ÉN CO_reserve≤0) bereikt na de finish | {_fmt(stats.get('pct_ehs_postfinish'), 2, '%')} |", f"| % participants reaching the conjunctive limit (T_rect>40.5°C AND CO_reserve≤0) after the finish | {_fmt(stats.get('pct_ehs_postfinish'), 2, '%')} |"))
    # [2026-10-20 late] EAC-staan; above WBGT 28 degC no number, only "zeer hoog".
    if stats.get('eac_buiten_bereik'):
        _eac = (vt(f"zeer hoog (WBGT {_fmt(stats.get('wbgt_race_max_p50'), 1)} °C; boven 28 °C "
                f"bestaan geen praktijkgegevens, daarom geen getal)",
                   f"very high (WBGT {_fmt(stats.get('wbgt_race_max_p50'), 1)} °C; above 28 °C "
                f"there are no field data, so no number)"))
    else:
        _eac = _sig(stats.get('eac_per_1000'))
        if _eac != NB:
            _eac += vt(" (voorlopig: gekalibreerd op één referentiepunt, Dam tot Dam / Naidoo 2022; niet gevalideerd)", " (provisional: calibrated on one reference point, Dam tot Dam / Naidoo 2022; not validated)")
    A(vt(f"| Collaps bij staan na de finish (EAC), verwacht per 1.000 deelnemers | {_eac} |", f"| Collapse when standing after the finish (EAC), expected per 1,000 participants | {_eac} |"))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 7. Thermoregulatoir regelfalen (experimentele mechanistische maat)", "## 7. Thermoregulatory control failure (experimental mechanistic measure)"))
    A("")
    A(vt("| Grootheid | Waarde |", "| Quantity | Value |"))
    A("|---|---|")
    A(vt(f"| % deelnemers boven Roberts' klinische drempel (AUC_klinisch > 60 °C·min) | {_fmt(stats.get('pct_roberts_kritiek'), 2, '%')} |", f"| % participants above Roberts' clinical threshold (AUC_clinical > 60 °C·min) | {_fmt(stats.get('pct_roberts_kritiek'), 2, '%')} |"))
    A(vt(f"| AUC_klinisch, mediaan (P50) | {_fmt(stats.get('auc_klinisch_p50'), 2, ' °C·min')} |", f"| AUC_clinical, median (P50) | {_fmt(stats.get('auc_klinisch_p50'), 2, ' °C·min')} |"))
    A(vt(f"| AUC_klinisch, P95 | {_fmt(stats.get('auc_klinisch_p95'), 2, ' °C·min')} |", f"| AUC_clinical, P95 | {_fmt(stats.get('auc_klinisch_p95'), 2, ' °C·min')} |"))
    A(vt(f"| % deelnemers boven thermisch-kritische grens (piek T_rect > 42,0°C, los van CO_reserve) | "
      f"{_fmt(stats.get('pct_thermal_only_critical'), 2, '%')} |",
         f"| % participants above the thermally critical limit (peak T_rect > 42.0°C, regardless of CO_reserve) | "
      f"{_fmt(stats.get('pct_thermal_only_critical'), 2, '%')} |"))
    A("")
    A(vt("De laatste regel hierboven staat los van het conjunctieve klinische "
      "criterium in sectie 11 (dat CO_reserve≤0 vereist naast T_rect>40,5°C). "
      "Bij piek-kerntemperatuur boven ~42°C kan directe thermische celschade "
      "aan hersenweefsel optreden ongeacht cardiovasculaire status (Hubbard: "
      "humane kritieke-temperatuurgrens 41,6-42,0°C; Gähwiler et al. 1972: "
      "onomkeerbare neuronale schade vanaf 42-43°C) -- een tweede, van "
      "CO_reserve onafhankelijk pad naar CZS-uitval.",
         "The last row above is separate from the conjunctive clinical "
      "criterion in section 11 (which requires CO_reserve≤0 as well as T_rect>40.5°C). "
      "At a peak core temperature above ~42°C, direct thermal cell damage "
      "to brain tissue can occur regardless of cardiovascular status (Hubbard: "
      "human critical temperature limit 41.6-42.0°C; Gähwiler et al. 1972: "
      "irreversible neuronal damage from 42-43°C) -- a second path to CNS "
      "failure, independent of CO_reserve."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 8. Kwetsbare-staartgroep (top 2,5% naar piek T_rect)", "## 8. Vulnerable tail group (top 2.5% by peak T_rect)"))
    A("")
    A(vt("| Grootheid | Waarde |", "| Quantity | Value |"))
    A("|---|---|")
    A(vt(f"| Aantal deelnemers in deze groep | {stats.get('vulnerable_tail_n', 'n.b.')} |", f"| Number of participants in this group | {stats.get('vulnerable_tail_n', 'n/a')} |"))
    A(vt(f"| Gemiddelde leeftijd in deze groep | {_fmt(stats.get('vulnerable_tail_age_mean'), 1, ' jaar')} |", f"| Mean age in this group | {_fmt(stats.get('vulnerable_tail_age_mean'), 1, ' years')} |"))
    # [2026-10-14] Was _fmt(stats['vulnerable_tail_mean_t_rect']): that is
    # a TIME SERIES whose last value is NaN once the whole tail group has
    # finished -> always "n.b.". Now the mean of each member's own peak.
    _tail_peak = None
    if (results_df is not None and 'vulnerable_tail_top_2_5pct' in results_df.columns
            and 'max_t_rect' in results_df.columns):
        _sel = results_df['vulnerable_tail_top_2_5pct'] == 1
        if _sel.any():
            _tail_peak = float(results_df.loc[_sel, 'max_t_rect'].astype(float).mean())
    A(vt(f"| Gemiddelde piek T_rect in deze groep | {_fmt(_tail_peak, 2, ' °C')} |", f"| Mean peak T_rect in this group | {_fmt(_tail_peak, 2, ' °C')} |"))
    A(vt(f"| Minimale CO_reserve, mediaan, in deze groep | {_fmt(stats.get('vulnerable_tail_co_reserve_min_p50'), 2, ' L/min')} |", f"| Minimum CO_reserve, median, in this group | {_fmt(stats.get('vulnerable_tail_co_reserve_min_p50'), 2, ' L/min')} |"))
    # [2026-10-16] Row "% NSAID-gebruik in deze groep" removed: NSAID has no
    # thermal effect in the model (K_P_NSAID_FACTOR = 1.0), so the share in a
    # 2.5% group is pure sampling noise (12-44% across 20 seeds at n=1000).
    A("")

    # ------------------------------------------------------------------ #
    # [2026-09-27, gevonden via onderzoek met de auteur] collapse-kans, EHE en
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
    A(vt(f"## 9. Eenzijdig-extreme profielen (niet gevangen door bestaande criteria)", f"## 9. One-sided extreme profiles (not caught by existing criteria)"))
    A("")
    A(vt(f"Deelnemers die op minstens één van de twee onderliggende, continue "
      f"assen (piek-T_rect of cvs_index_max) op of boven het "
      f"{EENZIJDIG_EXTREEM_PERCENTIEL:g}e percentiel van déze run zitten, "
      f"maar niet al worden gesignaleerd door het EHE- of klinisch "
      f"criterium (die vereisen dat T_rect ÉN CO_reserve allebei over hun "
      f"grens gaan). Dit is een diagnostische aanvulling, geen apart "
      f"risicocijfer -- zie sectie 11 voor de bestaande (conjunctieve) "
      f"criteria.",
         f"Participants who are at or above the "
      f"{EENZIJDIG_EXTREEM_PERCENTIEL:g}th percentile of this run on at least one of the two "
      f"underlying continuous axes (peak T_rect or cvs_index_max), "
      f"but are not already flagged by the EHE or clinical "
      f"criterion (which require T_rect AND CO_reserve both to cross their "
      f"limit). This is a diagnostic addition, not a separate "
      f"risk figure -- see section 11 for the existing (conjunctive) "
      f"criteria."))
    A("")
    if heeft_kolommen:
        n_gemist = int(results_df['gemist_door_bestaande_criteria'].sum())
        A(vt(f"| Grootheid | Waarde |", f"| Quantity | Value |"))
        A(f"|---|---|")
        A(vt(f"| Drempel voor 'eenzijdig extreem' | {EENZIJDIG_EXTREEM_PERCENTIEL:g}e percentiel |", f"| Threshold for 'one-sided extreme' | {EENZIJDIG_EXTREEM_PERCENTIEL:g}th percentile |"))
        A(vt(f"| Aantal eenzijdig extreem, totaal | {int(results_df['eenzijdig_extreem'].sum())} |", f"| Number one-sided extreme, total | {int(results_df['eenzijdig_extreem'].sum())} |"))
        A(vt(f"| Waarvan niet al gevangen door EHE/klinisch | {n_gemist} |", f"| Of which not already caught by EHE/clinical | {n_gemist} |"))
        A("")
        if n_gemist > 0:
            gemist_df = results_df[results_df['gemist_door_bestaande_criteria'] == 1].sort_values(
                'thermisch_percentiel', ascending=False)
            A(vt("| Deelnemer-ID | Piek T_rect (°C) | Min. CO_reserve (L/min) | "
              "Thermisch percentiel | Cardiovasculair percentiel |",
                 "| Participant ID | Peak T_rect (°C) | Min. CO_reserve (L/min) | "
              "Thermal percentile | Cardiovascular percentile |"))
            A("|---|---|---|---|---|")
            for _, r in gemist_df.head(30).iterrows():
                A(f"| {int(r['participant_id'])} | {r['max_t_rect']:.2f} | "
                  f"{r['cvr_co_reserve_min']:.2f} | {r['thermisch_percentiel']:.1f} | "
                  f"{r['cardiovasculair_percentiel']:.1f} |")
            if n_gemist > 30:
                A(f"")
                A(vt(f"*(eerste 30 van {n_gemist} getoond, gesorteerd op thermisch percentiel; "
                  f"volledige lijst in de Excel-export.)*",
                     f"*(first 30 of {n_gemist} shown, sorted by thermal percentile; "
                  f"full list in the Excel export.)*"))
    else:
        A(vt("*(Deze kolommen zijn niet aanwezig in deze run -- vereist een "
          "suite-versie van 2026-09-27 of later.)*",
             "*(These columns are not present in this run -- requires a "
          "suite version of 2026-09-27 or later.)*"))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 10. Herkomst en status van dit model", "## 10. Provenance and status of this model"))
    A("")
    A(vt("Feitelijke stand van zaken van het model op het moment van deze run "
      "(HESTIA-PYROX suite):",
         "Factual state of the model at the time of this run "
      "(HESTIA-PYROX suite):"))
    A("")
    A(vt("- De cardiovasculaire respons (CO_max, CO_demand, HR) is berekend "
      "volgens Lloyd et al. (2022, J Appl Physiol 133:247-261), Eq. 12-31.",
         "- The cardiovascular response (CO_max, CO_demand, HR) is calculated "
      "following Lloyd et al. (2022, J Appl Physiol 133:247-261), Eq. 12-31."))
    A(vt("- De kernlichaamstemperatuur is berekend met het JOS-3-model "
      "(Takahashi et al. 2021).",
         "- The core body temperature is calculated with the JOS-3 model "
      "(Takahashi et al. 2021)."))
    A(vt(f"- De collapse-risico-intercept voor het gebruikte eindpunt "
      f"('{ep_label}') heeft de status '{ep_status}' "
      f"(zie COLLAPSE_ENDPOINTS in hestia_model.py voor de volledige "
      f"kalibratiegeschiedenis en -steekproefgrootte van dit eindpunt).",
         f"- The collapse-risk intercept for the endpoint used "
      f"('{ep_label}') has the status '{ep_status}' "
      f"(see COLLAPSE_ENDPOINTS in hestia_model.py for the full "
      f"calibration history and sample size of this endpoint)."))
    A(vt("- Windrichting wordt niet gemeten in de brondata; de relatieve wind "
      "die een deelnemer ondervindt (eigen voortbewegingssnelheid "
      "gecombineerd met omgevingswind) wordt per deelnemer met een "
      "willekeurige hoek gesimuleerd.",
         "- Wind direction is not measured in the source data; the relative wind "
      "a participant experiences (own speed of movement "
      "combined with ambient wind) is simulated per participant with a "
      "random angle."))
    A(vt(f"- Deze run gebruikte {n_simulations:,} gesimuleerde deelnemers.", f"- This run used {n_simulations:,} simulated participants."))
    A("")

    # ------------------------------------------------------------------ #
    A(vt("## 11. Falmouth-EHS / EHE / klinisch criterium", "## 11. Falmouth EHS / EHE / clinical criterion"))
    A("")
    if bridge_summary is None:
        A(vt("Deze laag was niet beschikbaar voor deze run (geen `bridge_summary` "
          "meegegeven aan `generate_report()` -- vereist een aanroep van "
          "`hestia_bridge._summarize_results(all_results)` op dezelfde "
          "`all_results` als deze run).",
             "This layer was not available for this run (no `bridge_summary` "
          "passed to `generate_report()` -- requires a call of "
          "`hestia_bridge._summarize_results(all_results)` on the same "
          "`all_results` as this run)."))
        A("")
    else:
        A(vt("| Grootheid | Waarde |", "| Quantity | Value |"))
        A("|---|---|")
        A(vt(f"| Falmouth-EHS (epidemiologisch, temperatuur-alleen; DeMartini et al. 2014), per 1.000 | "
          f"{_sig(bridge_summary.get('falmouth_ehs_per_1000'))} |",
             f"| Falmouth EHS (epidemiological, temperature only; DeMartini et al. 2014), per 1,000 | "
          f"{_sig(bridge_summary.get('falmouth_ehs_per_1000'))} |"))
        n_ehe = bridge_summary.get('n_true_ehe_hits')
        n_ehs = bridge_summary.get('n_true_ehs_hits')
        A(vt(f"| EHE-criterium (T_rect>39,5°C ÉN CO_reserve<0), % deelnemers | "
          f"{_fmt(bridge_summary.get('pct_true_ehe_criterion'), 2, '%')} "
          f"({n_ehe if n_ehe is not None else '?'}/{n_simulations:,}) |",
             f"| EHE criterion (T_rect>39.5°C AND CO_reserve<0), % participants | "
          f"{_fmt(bridge_summary.get('pct_true_ehe_criterion'), 2, '%')} "
          f"({n_ehe if n_ehe is not None else '?'}/{n_simulations:,}) |"))
        A(vt(f"| Klinisch criterium (T_rect≥40,5°C ÉN CO_reserve≤0), % deelnemers | "
          f"{_fmt(bridge_summary.get('pct_true_ehs_criterion'), 2, '%')} "
          f"({n_ehs if n_ehs is not None else '?'}/{n_simulations:,}) |",
             f"| Clinical criterion (T_rect≥40.5°C AND CO_reserve≤0), % participants | "
          f"{_fmt(bridge_summary.get('pct_true_ehs_criterion'), 2, '%')} "
          f"({n_ehs if n_ehs is not None else '?'}/{n_simulations:,}) |"))
        A("")
        # [2026-10-14] Definitions made explicit: both criteria require the
        # two conditions at the SAME moment; EHE counts the race only, the
        # clinical criterion the race plus the 10-min post-finish window.
        A(vt("Beide criteria vereisen dat de twee voorwaarden op hetzelfde moment "
          "gelden. Het EHE-criterium telt alleen de race; het klinisch "
          "criterium telt de race én de 10 minuten na de finish.",
             "Both criteria require the two conditions to hold at the same "
          "moment. The EHE criterion counts only the race; the clinical "
          "criterion counts the race and the 10 minutes after the finish."))
        A("")
        if not n_ehe or not n_ehs:
            A(vt("Een uitkomst van 0% op een van beide criteria hierboven betekent niet "
              "vanzelfsprekend dat de drempel ver weg was -- zie de marge-analyse "
              "hieronder, gebaseerd op dezelfde onderliggende steekproefmomenten "
              "(T_rect, CO_reserve), voor hoe dichtbij het daadwerkelijk kwam. "
              "Omdat een conjunctief criterium BEIDE grenzen tegelijk vereist, is "
              "de bepalende marge steeds de as die als laatst zou sluiten, niet "
              "een van beide assen los.",
                 "An outcome of 0% on either criterion above does not "
              "necessarily mean that the threshold was far away -- see the margin analysis "
              "below, based on the same underlying sample moments "
              "(T_rect, CO_reserve), for how close it actually came. "
              "Because a conjunctive criterion requires BOTH limits at the same time, "
              "the deciding margin is always the axis that would close last, not "
              "either axis on its own."))
        else:
            A(vt("De marge-analyse hieronder laat zien hoe de onderliggende "
              "steekproefmomenten (T_rect, CO_reserve) zich tot beide drempels "
              "verhouden.",
                 "The margin analysis below shows how the underlying "
              "sample moments (T_rect, CO_reserve) relate to both "
              "thresholds."))
        A("")
        pairs = bridge_summary.get('t_rect_co_reserve_pairs') or []
        for label, tt, ct in ((vt("EHE-drempel", "EHE threshold"), 39.5, 0.0), (vt("Klinische drempel", "Clinical threshold"), 40.5, 0.0)):
            margin_lines = format_margin_lines(label, margin_to_threshold_stats(pairs, tt, ct))
            if margin_lines:
                A(f"- {margin_lines[0]}")
                for line in margin_lines[1:]:
                    A(f"  {line}")
            A("")

    # ------------------------------------------------------------------ #
    A(vt("## 12. Grafieken", "## 12. Charts"))
    A("")
    # [2026-09-01] Elke naam volgt hestia_plots.generate_population_plots()'s
    # eigen, vaste naamgeving (HESTIA_plotN_<label>_<stad>_<datum>_n<N>.png)
    # -- matchen op het "plotN_"-substring is dus onafhankelijk van stad,
    # datum of deelnemersaantal, en werkt voor elke run.
    PLOT_CAPTIONS = [
        ("plot1_", vt("Kerntemperatuur, hartslag/cardiovasculaire belasting en "
         "uitdroging/stopfrequentie van de hele gesimuleerde groep, over de "
         "tijd heen. De kerntemperatuur-lijn toont ook het gemiddelde traject "
         "van de kwetsbaarste 2,5% (naar piek-kerntemperatuur) apart, naast "
         "het populatiegemiddelde. Dat staartgemiddelde wordt per tijdstap "
         "berekend over de groepsleden die op dat moment nog onderweg zijn; "
         "als de groep uitstroomt, rust het op steeds minder deelnemers. De "
         "magenta lijn rechtsonder is de ruime screeningsvlag uit sectie 3 "
         "(T_rect≥40,5°C óf vochtverlies≥2% óf RPE≥17), geen voorspelling van "
         "EHBO-contacten.",
                      "Core temperature, heart rate/cardiovascular strain and "
         "dehydration/stopping rate of the whole simulated group, over "
         "time. The core-temperature line also shows the mean trajectory "
         "of the most vulnerable 2.5% (by peak core temperature) separately, next to "
         "the population mean. That tail mean is calculated per time step "
         "over the group members still on course at that moment; "
         "as the group finishes, it rests on fewer and fewer participants. The "
         "magenta line at bottom right is the wide screening flag from section 3 "
         "(T_rect≥40.5°C or fluid loss≥2% or RPE≥17), not a prediction of "
         "first-aid contacts.")),
        ("plot2_", vt("Spreiding in piekwaarden (kerntemperatuur, ervaren "
         "inspanning, vochtverlies) per leeftijdsgroep en geslacht -- laat "
         "zien of bepaalde groepen structureel hoger uitkomen dan andere, "
         "niet alleen het populatiegemiddelde uit sectie 3.",
                      "Spread in peak values (core temperature, perceived "
         "exertion, fluid loss) per age group and sex -- shows "
         "whether certain groups come out structurally higher than others, "
         "not only the population mean from section 3.")),
        ("plot3_", vt("Histogram van de laagste hartminuutvolume-reserve die "
         "elke deelnemer tijdens de race bereikte. De oranje lijn markeert "
         "de drempel voor decompensatierisico (2,0 L/min), de rode lijn het "
         "punt waarop de reserve daadwerkelijk op is (0 L/min, onderdeel van "
         "het EHE/klinisch-criterium uit sectie 11).",
                      "Histogram of the lowest cardiac-output reserve that "
         "each participant reached during the race. The orange line marks "
         "the threshold for risk of decompensation (2.0 L/min), the red line the "
         "point at which the reserve is actually used up (0 L/min, part of "
         "the EHE/clinical criterion from section 11).")),
        ("plot4_", vt("Histogram van de individueel berekende collapse-kans per "
         "deelnemer (het gekalibreerde model uit sectie 5) -- laat zien of "
         "het risico geconcentreerd is bij een kleine groep met een hoge "
         "kans, of breed verspreid is over de hele populatie met overal een "
         "laag risico.",
                      "Histogram of the individually calculated collapse probability per "
         "participant (the calibrated model from section 5) -- shows whether "
         "the risk is concentrated in a small group with a high "
         "probability, or spread widely over the whole population with a low "
         "risk everywhere.")),
        ("plot5_", vt("Elke stip is één deelnemer: piek-kerntemperatuur tegen de "
         "laagste hartminuutvolume-reserve, gekleurd naar individuele "
         "collapse-kans. De rode lijnen markeren het klinische criterium "
         "(T_rect>40,5°C ÉN CO_reserve≤0) -- de rechtsonder-hoek toont in "
         "één oogopslag wie zowel warm ÁLS cardiovasculair belast tegelijk "
         "was, in plaats van de twee losse verdelingen uit de vorige twee "
         "grafieken.",
                      "Each dot is one participant: peak core temperature against the "
         "lowest cardiac-output reserve, coloured by individual "
         "collapse probability. The red lines mark the clinical criterion "
         "(T_rect>40.5°C AND CO_reserve≤0) -- the bottom-right corner shows "
         "at a glance who was both hot AND cardiovascularly strained at the same time, "
         "instead of the two separate distributions from the previous two "
         "charts.")),
        ("plot6_", vt("Individuele collapse-kans uitgezet tegen leeftijd, apart "
         "voor mannen en vrouwen -- laat zien of het risico geconcentreerd "
         "is in specifieke leeftijdsgroepen, of gelijkmatig verdeeld is over "
         "de hele leeftijdsrange.",
                      "Individual collapse probability plotted against age, separately "
         "for men and women -- shows whether the risk is concentrated "
         "in specific age groups, or spread evenly over "
         "the whole age range.")),
        ("plot7_", vt("Het volledige tijdsverloop (start tot 10 minuten na de "
         "finish) van kerntemperatuur en hartminuutvolume-reserve voor de "
         "tien deelnemers met de hoogste piektemperatuur, plus de tien met "
         "de laagste reserve -- laat zien wannéér in de race deze twee "
         "groepen risico begonnen te lopen, en of dat vóór of ná de finish "
         "gebeurde.",
                      "The full time course (start to 10 minutes after the "
         "finish) of core temperature and cardiac-output reserve for the "
         "ten participants with the highest peak temperature, plus the ten with "
         "the lowest reserve -- shows when in the race these two "
         "groups began to be at risk, and whether that happened before or after the finish.")),
        ("plot8_", vt("De cumulatieve 'conjunctieve dosis' (hoe lang en hoe ver "
         "iemand tegelijk boven de temperatuur- én onder de reserve-drempel "
         "zat, opgeteld over de tijd) voor dezelfde twee groepen als "
         "hierboven. Elke lijn vermeldt ook hoeveel aparte keren (episodes) "
         "en hoeveel minuten die deelnemer daadwerkelijk aan beide "
         "voorwaarden tegelijk voldeed -- een enkel eindgetal verbergt of "
         "dat één aanhoudende periode was of meerdere korte.",
                      "The cumulative 'conjunctive dose' (how long and how far "
         "someone was above the temperature threshold and below the reserve threshold at the same time, "
         "summed over time) for the same two groups as "
         "above. Each line also states how many separate times (episodes) "
         "and how many minutes that participant actually met both "
         "conditions at once -- a single final number hides whether "
         "that was one sustained period or several short ones.")),
        ("plot9_", vt("De cumulatieve tijd-gewogen oppervlakte onder de curve "
         "boven 40,5°C (Roberts 2007's klinische dosis-maat) voor de "
         "deelnemers met de hoogste eindwaarde. In tegenstelling tot de "
         "vorige grafiek telt deze maat alleen temperatuur, niet de "
         "cardiovasculaire reserve -- een tweede, onafhankelijke blik op "
         "dezelfde vraag.",
                      "The cumulative time-weighted area under the curve "
         "above 40.5°C (Roberts 2007's clinical dose measure) for the "
         "participants with the highest final value. Unlike the "
         "previous chart, this measure counts only temperature, not the "
         "cardiovascular reserve -- a second, independent view of "
         "the same question.")),
        ("plot10_", vt("Dezelfde soort maat als hierboven, maar met een lagere, "
         "diagnostische drempel (39,0°C in plaats van 40,5°C) die geen "
         "vastgestelde klinische betekenis heeft. De grafiek toont daarom "
         "het 95e-percentiel van déze steekproef zelf als referentielijn, "
         "niet een geleende klinische grens.",
                       "The same kind of measure as above, but with a lower, "
         "diagnostic threshold (39.0°C instead of 40.5°C) that has no "
         "established clinical meaning. The chart therefore shows "
         "the 95th percentile of this sample itself as the reference line, "
         "not a borrowed clinical limit.")),
        ("plot11_", vt("De cumulatieve tekort-dosis van de hartminuutvolume-"
         "reserve alleen, los van de temperatuur -- isoleert het "
         "cardiovasculaire spoor van het thermische spoor: bij sommige "
         "deelnemers kan de bloedvraag van de spieren de hartreserve al "
         "uitputten vóórdat de temperatuur zelf een probleem wordt.",
                       "The cumulative deficit dose of the cardiac-output "
         "reserve alone, separate from temperature -- isolates the "
         "cardiovascular track from the thermal track: in some "
         "participants the blood demand of the muscles can exhaust the cardiac reserve "
         "before the temperature itself becomes a problem.")),
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
            A(vt("Geen van de verwachte HESTIA-plotbestanden werd herkend in de "
              "meegegeven lijst -- zie generate_report()'s plot_paths-parameter.",
                 "None of the expected HESTIA plot files was recognised in the "
              "list passed -- see generate_report()'s plot_paths parameter."))
    else:
        A(vt("Niet gegenereerd voor deze run (geen plot_paths meegegeven aan "
          "generate_report() -- run_hestia.py's eigen \"Generate plots?\"-"
          "vraag, vóór de rapportvraag, moet daarvoor bevestigend zijn "
          "beantwoord).",
             "Not generated for this run (no plot_paths passed to "
          "generate_report() -- run_hestia.py's own \"Generate plots?\" "
          "question, before the report question, must be answered "
          "yes for that)."))
        A("")

    A(vt("*Einde rapport.*", "*End of report.*"))

    report_text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    return report_text
