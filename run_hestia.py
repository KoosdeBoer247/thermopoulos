# -*- coding: utf-8 -*-
"""
Run HESTIA on Thermopoulos data
================================================================================
The HESTIA half of the suite, wired with REAL IMPORTS (no exec, no subprocess,
no API calls). `hestia_model.py` is the CVR/tailplot-calibrated model (rev17:
JOS-3 + Cardiovascular Response module (Lloyd et al. 2022) + Thermoregulatory
Control Failure metric + Boston-Marathon-calibrated collapse-risk model),
imported unchanged except one marked edit (a stray `print` removed). This
adapter only replaces its weather SOURCE: instead of fetching from Open-Meteo,
it feeds hourly weather from the shared Thermopoulos Excel produced once by
the data engine.

================================================================================
[integration note] PARTICIPANT CONTRACT CHANGE (rev04 -> rev10)
================================================================================
Older HESTIA revisions took `participant_params` as a plain tuple. From rev10
onward, `calculate_indices_jos3_adult()` expects an `AdultParticipantProfile`
dataclass instance instead (fields accessed by name: height, weight, age,
gender, vo2max, pct_vo2max, temp_variation, rh_variation, mf_score,
sweat_factor, thirst_threshold, kp_pacing, nsaid_gebruik). This adapter has
been updated to build that dataclass; anything importing the OLD tuple-based
adapter functions from a previous suite snapshot will break against this
hestia_model.py, by design (the contracts are genuinely incompatible, not
just renamed).

================================================================================
[integration note] MET IS NO LONGER A DIRECT SIMULATION INPUT -- FLAG FOR REVIEW
================================================================================
From rev10 onward, an individual participant's actual simulated MET is NOT
`met_value` directly. It is derived from the profile:

    base_met_from_vo2max = vo2max * pct_vo2max / VO2MAX_TO_MET_FACTOR
    current_met           = base_met_from_vo2max * (1 - 0.05 * training_factor)

`met_value` is only used for the liveability check (Vanos et al. 2023), not
as the individual's simulated activity level. This is a deliberate rev13
causal-correctness fix upstream (prevents %VO2max from exceeding 100% by
construction) -- but it changes what `simulate_individual_adult(met_value=...)`
actually does to the runner's physiology.

For `simulate_individual_adult()` (a single deterministic "representative
adult", not a population draw), this adapter back-solves `pct_vo2max` from
the requested `met_value` and a representative `vo2max` for the given
age/gender (same deterministic Tanaka-2001-based mean formula
`generate_base_population()` uses for its distribution mean, just without the
stochastic draw), so that current_met ~= met_value as before, unless the
caller passes `vo2max=`/`pct_vo2max=` explicitly. **This back-solving choice
is an engineering bridge, not a validated scientific decision -- flagging it
explicitly for review.** For Monte Carlo (`monte_carlo_adult()`), MET is never
back-solved: every participant's MET emerges from their own sampled VO2max and
pace, which is the model's intended (and causally corrected) behaviour.

================================================================================
[integration note] MONTE CARLO WRAPPER WAS BROKEN IN THE PREVIOUS SNAPSHOT
================================================================================
The previous `monte_carlo_adult()` did not accept or pass `age_configuration`,
a required positional argument of `hestia.run_monte_carlo_adult()` (no
default) -- every call raised `TypeError` immediately. This was never caught
by `suite_smoke_test.py`, which only exercised `simulate_individual_adult()`.
Both are fixed here: the wrapper now passes `age_configuration="standard"`
(kept only for backward compatibility -- rev10 embeds age directly in each
sampled profile and ignores this flag with a printed deprecation notice), and
`suite_smoke_test.py` now also calls `monte_carlo_adult()` so this class of
bug cannot silently reappear.

Pipeline:
    Thermopoulos Excel
        -> thermopoulos_loader.get_hourly_weather(window)
        -> hestia_model.interpolate_weather(...)
        -> hestia_model.calculate_indices_jos3_adult(...) / run_monte_carlo_adult(...)
        -> per-participant core temp, sweat loss, RPE, CO_reserve, control-failure dose, risk
"""

from __future__ import annotations

import os
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

import hestia_model as hestia
from hestia_model import (
    AdultParticipantProfile, VO2MAX_TO_MET_FACTOR, K_P_PACING,
    MET_ACTIVITIES_ADULT, CLO_OPTIONS_ADULT,
    select_met_activity, select_clo_value, get_adaptation_profile,
)
from thermopoulos_loader import ThermopoulosData
from generate_event_report import generate_report

try:
    from HESTIA_ControlFailure_Module import analyse_participant as _tcf_analyse_participant
    _TCF_AVAILABLE = True
except ImportError:
    _TCF_AVAILABLE = False


# ============================================================================
# make HESTIA fully offline when driven by Thermopoulos
# ============================================================================
# HESTIA reaches out to Open-Meteo's air-quality API directly (get_air_quality).
# When we drive HESTIA from a pre-fetched Thermopoulos Excel we want NO live
# calls, for reproducibility and offline runs. We override that one function
# with a constant. AQI only feeds a minor solar-attenuation term, so a fixed
# "Good" (1) value is a sensible, documented default; raise DEFAULT_AQI if you
# want to model hazier skies.

DEFAULT_AQI = 1  # 1=Good ... 5=Hazardous (HESTIA's 1-5 scale)


def _offline_air_quality(lat, lon):
    return DEFAULT_AQI


# install the override at import time so every HESTIA code path sees it
hestia.get_air_quality = _offline_air_quality


# ============================================================================
# weather bridge
# ============================================================================

def build_interpolated_weather(data: ThermopoulosData,
                               start_time: str,
                               duration_hours: float,
                               sheet: str = "Forecast_7d",
                               interval_minutes: int = 10) -> List[Dict]:
    """Produce HESTIA's interpolated-weather list for a simulation window,
    sourced entirely from the Thermopoulos Excel.

    This wraps loader.get_hourly_weather() + hestia.interpolate_weather() so the
    rest of HESTIA sees exactly what it expects.
    """
    hourly = data.get_hourly_weather(sheet=sheet,
                                     start_time=start_time,
                                     duration_hours=duration_hours + 1)
    if not hourly:
        raise ValueError(
            f"No weather rows in window starting {start_time} "
            f"({duration_hours} h) on sheet '{sheet}'."
        )

    # [fix 2026-09] Real, reproduced case: Open-Meteo's forecast API
    # advertises up to 16 forecast days, and a run using exactly that
    # maximum (days=16, to reach an event 15+ days out) returned hourly
    # rows with real timestamps for every hour of the requested window --
    # but with the core raw fields (temp, humidity, wind) NaN for the
    # entire final day (2026-09-20, from 05:00 onward), while every
    # earlier day in the same 16-day fetch was complete. This is
    # Open-Meteo's own behaviour at the edge of its advertised range, not
    # a bug in this suite's own fetch/parsing code -- but a HESTIA run fed
    # these rows anyway, ran the full multi-minute Monte Carlo simulation
    # on undefined inputs, and only surfaced the problem afterwards as an
    # all-NaN population time series (empty plots, "n.b." in the report)
    # -- costing the multi-minute run for nothing. This check catches it
    # upfront instead, before that cost is spent.
    #
    # Deliberately narrow to main.temp/humidity + wind.speed: these three
    # are read in get_hourly_weather() as plain float(row[...]) with no
    # optional/fallback handling, so a missing value here cannot be
    # absorbed downstream. solar/radiant/indices fields are excluded on
    # purpose -- get_hourly_weather()'s own docstring documents these as
    # optional, with HESTIA falling back to its own internal calculation
    # when they're None (confirmed by suite_smoke_test.py's own minimal
    # synthetic weather, which never sets solar_elevation/globe_temp/mrt
    # at all and is expected to run correctly regardless).
    _bad_hours = []
    for _row in hourly:
        _missing = [f"{grp}.{key}" for grp, key in (("main", "temp"), ("main", "humidity"), ("wind", "speed"))
                    if pd.isna(_row.get(grp, {}).get(key))]
        if _missing:
            _bad_hours.append((pd.to_datetime(_row["dt"], unit="s", utc=True)
                               .tz_convert(data.timezone), _missing))
    if _bad_hours:
        _example_dt, _example_fields = _bad_hours[0]
        raise ValueError(
            f"{len(_bad_hours)} of {len(hourly)} hours in the requested "
            f"event window ({start_time}, {duration_hours} h, sheet "
            f"'{sheet}') have missing weather data -- e.g. "
            f"{_example_dt.strftime('%Y-%m-%d %H:%M')} is missing "
            f"{', '.join(_example_fields)}. This is a known Open-Meteo "
            f"behaviour at the edge of its forecast range (commonly the "
            f"final day when fetched with days=16) -- not a bug in this "
            f"suite. Re-fetch closer to the event date (a shorter forecast "
            f"horizon covers the target day more reliably), or choose a "
            f"start_time within the window that does have complete data."
        )

    tz = data.timezone
    start_dt = pd.Timestamp(start_time, tz=tz)
    end_dt = start_dt + pd.Timedelta(hours=duration_hours)
    return hestia.interpolate_weather(hourly, start_dt, end_dt,
                                      interval_minutes=interval_minutes)


# ============================================================================
# representative-participant helper (single-run, deterministic)
# ============================================================================

def _representative_vo2max(age: int, gender: str) -> float:
    """Deterministic mean VO2max for age/gender, same formula
    `generate_base_population()` uses for its distribution mean (Tanaka et al.
    2001 age correction; Scharhag-Rosenberger et al. 2010 base values), just
    without the stochastic draw. Used only to construct a single
    "representative adult" for `simulate_individual_adult()`.
    """
    if gender == "male":
        base_mu = 52.0
    else:
        base_mu = 44.0
    age_correction = 0.5 * max(0, age - 35)
    return base_mu - age_correction


def _build_representative_profile(height: float, weight: float, age: int,
                                  gender: str, met_value: float,
                                  training_factor: float,
                                  mf_score: float = 0.5,
                                  sweat_factor: float = 1.0,
                                  thirst_threshold: float = 2.0,
                                  vo2max: Optional[float] = None,
                                  pct_vo2max: Optional[float] = None,
                                  body_fat_pct: Optional[float] = None,
                                  kp_pacing: float = K_P_PACING,
                                  nsaid_gebruik: bool = False) -> AdultParticipantProfile:
    """Build a single deterministic AdultParticipantProfile.

    If `vo2max`/`pct_vo2max` are not given, back-solve `pct_vo2max` from the
    requested `met_value` so the simulated MET matches it (see module
    docstring [integration note] above for why this is needed and why it is
    flagged as an engineering bridge rather than a validated choice).

    If `body_fat_pct` is not given, uses the population mean for the given
    gender (17.7% male / 19.6% female -- Nikolaidis et al. 2021, BioMed
    Research International 2021:3717562, recreational marathon runners,
    BIA-measured -- see generate_base_population(), which samples individual
    variation around these same means for Monte Carlo runs; a single
    deterministic run uses the mean, no noise, consistent with how the other
    representative-participant fields are handled here).
    """
    if vo2max is None:
        vo2max = _representative_vo2max(age, gender)

    if body_fat_pct is None:
        body_fat_pct = 17.7 if gender == "male" else 19.6

    if pct_vo2max is None:
        target_base_met = met_value / max(1e-6, (1.0 - 0.05 * training_factor))
        pct_vo2max = (target_base_met * VO2MAX_TO_MET_FACTOR) / vo2max
        if not (0.3 <= pct_vo2max <= 1.3):
            print(f"[run_hestia] WARNING: back-solved pct_vo2max={pct_vo2max:.2f} "
                  f"for met_value={met_value}, vo2max={vo2max:.1f} is outside the "
                  f"physiologically typical [0.55, 0.95] range used in population "
                  f"sampling. Result is still computed, but review before trusting it.")
        pct_vo2max = float(np.clip(pct_vo2max, 0.05, 2.0))

    return AdultParticipantProfile(
        height=height, weight=weight, age=age, gender=gender,
        body_fat_pct=body_fat_pct,
        vo2max=vo2max, pct_vo2max=pct_vo2max,
        temp_variation=0.0, rh_variation=0.0,
        mf_score=mf_score, sweat_factor=sweat_factor,
        thirst_threshold=thirst_threshold,
        kp_pacing=kp_pacing, nsaid_gebruik=nsaid_gebruik,
        # [2026-07] pi/2 (cos=0) is the deterministic default for a single
        # representative run: it makes compute_relative_wind() reduce to
        # sqrt(v_run^2 + v_wind^2), which is exactly E[v_rel^2] under the
        # Uniform[0, 2*pi) sampling used for Monte Carlo populations -- see
        # compute_relative_wind()'s docstring in hestia_model.py. A single
        # deterministic run has no population to sample across, so this
        # matches the Monte Carlo population *mean* rather than picking an
        # arbitrary headwind or tailwind assumption.
        wind_angle_rad=np.pi / 2,
    )


# ============================================================================
# single-individual convenience wrappers
# ============================================================================

def simulate_individual_adult(data: ThermopoulosData,
                              start_time: str,
                              duration_hours: float,
                              met_value: float,
                              clo_value: float,
                              *,
                              height: float = 1.75,
                              weight: float = 75.0,
                              age: int = 35,
                              gender: str = "male",
                              training_factor: float = 0.0,
                              acclimatization_factor: float = 0.0,
                              vo2max: Optional[float] = None,
                              pct_vo2max: Optional[float] = None,
                              sheet: str = "Forecast_7d") -> List[Dict]:
    """Simulate one representative adult over a heat-exposure window.

    Returns HESTIA's per-time-step result dicts: core temp, RPE, water loss,
    and (when the CVR module is available) cardiac output, CO_reserve,
    decompensation flag, and post-finish EHS propagation.
    """
    interp = build_interpolated_weather(data, start_time, duration_hours, sheet)

    profile = _build_representative_profile(
        height=height, weight=weight, age=age, gender=gender,
        met_value=met_value, training_factor=training_factor,
        vo2max=vo2max, pct_vo2max=pct_vo2max,
    )

    return hestia.calculate_indices_jos3_adult(
        interp,
        data.latitude, data.longitude,
        met_value, clo_value,
        profile,
        training_factor, acclimatization_factor,
    )


def summarize_individual(results: List[Dict]) -> Dict:
    """Reduce a per-time-step HESTIA result list to headline numbers.

    Includes the thermal-only fields (as before) plus, when present, the CVR
    fields (co_reserve, decompensation) and post-finish / control-failure
    fields the CVR-integrated model now produces.
    """
    if not results:
        return {}
    core_temps = [r.get("t_rect") for r in results if r.get("t_rect") is not None]
    rpes = [r.get("rpe_total") for r in results if r.get("rpe_total") is not None]
    water = [r.get("water") for r in results if r.get("water") is not None]
    unliveable = any(r.get("is_unliveable") for r in results)

    summary = {
        "n_steps": len(results),
        "peak_core_temp": max(core_temps) if core_temps else None,
        "final_core_temp": core_temps[-1] if core_temps else None,
        "peak_rpe_total": max(rpes) if rpes else None,
        "total_water_loss_g": max(water) if water else None,
        "entered_unliveable": unliveable,
    }

    co_reserves = [r.get("co_reserve") for r in results
                   if r.get("co_reserve") is not None and not np.isnan(r.get("co_reserve", np.nan))]
    if co_reserves:
        summary["min_co_reserve"] = min(co_reserves)
        summary["decompensation_occurred"] = any(r.get("decompensating") for r in results)

    last = results[-1]
    if "ehs_postfinish" in last:
        summary["ehs_postfinish"] = last["ehs_postfinish"]
        summary["t_rect_peak_postfinish"] = last.get("t_rect_piek_postfinish")
        summary["auc_klinisch_totaal"] = last.get("auc_klinisch_totaal")

    if _TCF_AVAILABLE:
        tcf = _tcf_analyse_participant(results)
        summary["control_failure_dose_total"] = tcf["control_failure_dose_total"]
        summary["control_failure_class"] = tcf["control_failure_class"]

    return summary


# ============================================================================
# Monte Carlo over a population (delegates to HESTIA's own machinery)
# ============================================================================

def monte_carlo_adult(data: ThermopoulosData,
                      start_time: str,
                      duration_hours: float,
                      met_value: float,
                      clo_value: float,
                      n_simulations: int = 200,
                      training_factor: float = 0.0,
                      acclimatization_factor: float = 0.0,
                      sheet: str = "Forecast_7d",
                      *,
                      use_parallel: bool = True,
                      base_population: Optional[list] = None,
                      random_seed: Optional[int] = None,
                      run_control_failure: bool = True,
                      sample_pace: bool = False,
                      event_dist_km: float = 16.1) -> Tuple:
    """Run HESTIA's adult Monte Carlo over a virtual population for the window,
    using Thermopoulos weather.

    [fixed] The previous version of this wrapper did not accept or pass
    `age_configuration`, a required argument of `hestia.run_monte_carlo_adult`
    with no default -- every call raised TypeError. Age is embedded per-profile
    by `generate_base_population()` from rev10 onward, so `age_configuration`
    is passed as "standard" purely for backward-compatible signature matching;
    it has no effect unless you are relying on old (pre-rev10) behaviour.

    `run_control_failure=True` by default: this is the whole point of wiring
    in the CVR-tailplot model, so the Thermoregulatory Control Failure dose
    (and the CO_reserve / collapse-risk population statistics, which run
    whenever the CVR module is available regardless of this flag) are
    computed by default rather than opt-in.

    sample_pace : bool
        [2026-09] When True, individual participants get their own pace/MET/
        exposure duration (hestia.generate_base_population(sample_pace=True)
        and hestia.run_monte_carlo_adult(sample_pace=True) -- see both
        docstrings) instead of everyone sharing met_value and duration_hours.
        Because of this, the weather window fetched here is widened to
        PACE_MIN_PER_KM_CEILING * event_dist_km (the slowest participant the
        pace sampler can produce, ~2h for the 16.1km default) REGARDLESS of
        the duration_hours argument, so every participant's own slice
        (built inside hestia.run_monte_carlo_adult) has real weather data to
        draw on -- a fast participant still starts at start_time, they just
        use a shorter prefix of the same fetched window. duration_hours
        itself is otherwise unused when sample_pace=True.

    Returns whatever `hestia.run_monte_carlo_adult` returns:
    (all_results, stats, results_df).
    """
    if sample_pace:
        widened_hours = hestia.PACE_MIN_PER_KM_CEILING * event_dist_km / 60.0
        duration_hours = max(duration_hours, widened_hours)
    interp = build_interpolated_weather(data, start_time, duration_hours, sheet)
    return hestia.run_monte_carlo_adult(
        interp, data.latitude, data.longitude,
        met_value, clo_value,
        n_simulations=n_simulations,
        age_configuration="standard",
        training_factor=training_factor,
        acclimatization_factor=acclimatization_factor,
        use_parallel=use_parallel,
        base_population=base_population,
        random_seed=random_seed,
        run_control_failure=run_control_failure,
        sample_pace=sample_pace,
        event_dist_km=event_dist_km,
    )


def _prompt(msg: str, default):
    """Prompt with a default; falls back silently to the default when input
    isn't available (e.g. run non-interactively) rather than crashing."""
    try:
        raw = input(f"{msg} [{default}]: ").strip()
    except EOFError:
        raw = ""
    return raw if raw else default


def _prompt_typed(msg: str, default, cast=str):
    raw = _prompt(msg, default)
    if raw == default:
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        print(f"  Could not parse '{raw}' as {cast.__name__}; using default {default}.")
        return default


def _run_cli():
    """Full interactive HESTIA run: choose the Thermopoulos file/sheet, choose
    individual vs. population (Monte Carlo) mode, configure every parameter
    (with sensible defaults, just press Enter to accept), run the CVR-integrated
    model at real scale (population default n=1000, not a small demo), print
    the full CVR/collapse-risk/control-failure report, and export results to
    Excel.
    """
    import glob
    from thermopoulos_loader import find_latest_thermopoulos_file
    from HESTIA_CVR_Console import print_cvr_population_summary
    try:
        from HESTIA_ControlFailure_Module import format_population_summary
    except ImportError:
        format_population_summary = None
    from colorama import Fore, Style, init as _colorama_init
    _colorama_init()

    # ---- 1. pick the Thermopoulos data file --------------------------------
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _found = (glob.glob(os.path.join(_script_dir, "Thermopoulos_*.xlsx"))
             + glob.glob("Thermopoulos_*.xlsx"))
    # Dedup by normcase(abspath): on Windows the filesystem is case-insensitive
    # but plain string comparison isn't, so the same file reached via the
    # script directory vs. the current working directory (which can differ
    # only in casing, e.g. C:\... vs c:\...) was showing up twice.
    _by_key = {}
    for p in _found:
        key = os.path.normcase(os.path.abspath(p))
        _by_key.setdefault(key, os.path.abspath(p))
    candidates = sorted(_by_key.values())
    if not candidates:
        print("No Thermopoulos_*.xlsx found in the working directory. "
              "Run Thermopoulos_Data_Engine.py first.")
        raise SystemExit(1)
    if len(candidates) == 1:
        chosen_file = candidates[0]
    else:
        print("Available Thermopoulos data files:")
        for i, f in enumerate(candidates, 1):
            print(f"  {i}. {f}")
        default_idx = len(candidates)  # newest, assuming lexicographic == chronological
        idx = _prompt_typed("Pick a file (number)", default_idx, int)
        idx = min(max(idx, 1), len(candidates))
        chosen_file = candidates[idx - 1]
    data = ThermopoulosData(chosen_file)
    print(f"\nUsing: {chosen_file}  (city: {data.city})")

    # ---- 2. pick the sheet --------------------------------------------------
    print(f"Available sheets: {data.available_sheets}")
    default_sheet = "Forecast_7d" if "Forecast_7d" in data.available_sheets else data.available_sheets[0]
    sheet = _prompt("Sheet", default_sheet)
    if sheet not in data.available_sheets:
        print(f"  '{sheet}' not found; using {default_sheet}.")
        sheet = default_sheet

    daily = data.get_daily_heat_loads(sheet)
    date_min, date_max = str(daily["date"].iloc[0]), str(daily["date"].iloc[-1])
    print(f"Available date range on this sheet: {date_min} .. {date_max}")

    # ---- 3. mode --------------------------------------------------------------
    mode = _prompt("Mode: (i)ndividual or (p)opulation Monte Carlo", "p").lower()

    # ---- 3b. collapse-risk endpoint selection ---------------------------------
    # [2026-07] This mirrors hestia_model.py's own main()/CLI, which has the
    # same prompt -- but that entry point is not the one actually run from
    # here (_run_cli() is its own, separate CLI). Without this block,
    # ACTIVE_ENDPOINT silently stayed at its hard-coded default ('ehs') no
    # matter what, with no way to select 'hospitalisation' or 'ehbo' from
    # the CLI a user actually runs.
    print(f"\nCollapse risk endpoint selection:")
    _ep_keys = list(hestia.COLLAPSE_ENDPOINTS.keys())
    for _i, _k in enumerate(_ep_keys, 1):
        _ep = hestia.COLLAPSE_ENDPOINTS[_k]
        _status_color = Fore.GREEN if _ep['status'] == 'VALIDATED' else Fore.YELLOW
        print(f"  {_i}. {_ep['label']}")
        print(f"     P_obs: {_ep['p_obs']*10000:.1f}/10,000  |  "
              f"intercept: {_ep['intercept_kal']:.3f}  |  "
              f"{_status_color}{_ep['status']}{Style.RESET_ALL}")
    print(f"  (default: 1 = EHS, most conservative)")
    _ep_choice = _prompt("Select endpoint (1/2/3)", "1")
    if _ep_choice in [str(_n) for _n in range(2, len(_ep_keys) + 1)]:
        _chosen_key = _ep_keys[int(_ep_choice) - 1]
        hestia.ACTIVE_ENDPOINT = _chosen_key
        print(f"{Fore.CYAN}Active endpoint set to: "
              f"'{hestia.COLLAPSE_ENDPOINTS[_chosen_key]['label']}'{Style.RESET_ALL}")
        if hestia.COLLAPSE_ENDPOINTS[_chosen_key]['status'] in ('PROVISIONAL', 'REQUIRES_RECALIBRATION'):
            print(f"{Fore.YELLOW}WARNING: this endpoint is PROVISIONAL "
                  f"(see COLLAPSE_ENDPOINTS notes in hestia_model.py).{Style.RESET_ALL}")
    else:
        print(f"{Fore.CYAN}Using default endpoint: "
              f"'{hestia.COLLAPSE_ENDPOINTS['ehs']['label']}'{Style.RESET_ALL}")

    # ---- 4. shared parameters ---------------------------------------------
    start_date = _prompt("Start date (YYYY-MM-DD)", date_min)
    start_hour = _prompt("Start time (HH:MM)", "09:00")
    start_time = f"{start_date} {start_hour}"
    print()
    # [2026-09] Event distance is now an explicit, adjustable console input
    # instead of duration_hours being typed in isolation with no link to pace
    # or distance. This decouples the suite from any one event (marathon,
    # DtD's 16.1 km, or anything else) -- duration is now derived from
    # distance / pace by default, though it can still be overridden manually
    # below (e.g. to model only part of a course). Mirrors the same fix
    # applied to Klimatos_ClimateShift.py's EVENT_DIST_KM/EVENT_DURATION_MIN.
    event_dist_km = _prompt_typed("Event distance (km)", 16.1, float)
    try:
        activity_choice, met_value, speed_ms = select_met_activity(MET_ACTIVITIES_ADULT)
        speed_kmh = speed_ms * 3.6
        implied_duration_hours = round(event_dist_km / speed_kmh, 2) if speed_kmh > 0 else 4.0
    except EOFError:
        activity_choice, met_value = 13, 8.0
        implied_duration_hours = 4.0
        print(f"  (no input available; defaulting to MET {met_value})")
    duration_hours = _prompt_typed(
        f"Duration (hours) [implied by {event_dist_km:g} km at this pace: "
        f"{implied_duration_hours:.2f}h]",
        implied_duration_hours, float,
    )
    try:
        clo_value = select_clo_value(CLO_OPTIONS_ADULT)
    except EOFError:
        clo_value = 0.3
        print(f"  (no input available; defaulting to clo {clo_value})")
    try:
        adaptation = get_adaptation_profile(activity_choice)
        training_factor = adaptation["training"]
        acclimatization_factor = adaptation["acclimatization"]
        print(f"  Using: {adaptation['name']} "
              f"(training={training_factor}, acclimatization={acclimatization_factor})")
    except EOFError:
        training_factor, acclimatization_factor = 0.0, 0.0
        print("  (no input available; defaulting to Beginner / Not acclimatized)")

    if mode.startswith("i"):
        age = _prompt_typed("Age", 45, int)
        gender = _prompt("Gender (male/female)", "male")
        print(f"\nRunning single representative adult — {data.city}, {start_time}, "
              f"MET {met_value}, {duration_hours}h...")
        results = simulate_individual_adult(
            data, start_time, duration_hours, met_value=met_value, clo_value=clo_value,
            age=age, gender=gender, training_factor=training_factor,
            acclimatization_factor=acclimatization_factor, sheet=sheet,
        )
        summary = summarize_individual(results)
        print(f"\n{Style.BRIGHT}Result — {age}-year-old {gender}, {duration_hours}h at MET {met_value}:{Style.RESET_ALL}")
        for k, v in summary.items():
            vv = f"{v:.3f}" if isinstance(v, float) else v
            print(f"  {k:<26}: {vv}")

        _script_dir = os.path.dirname(os.path.abspath(__file__))
        out_name = os.path.join(_script_dir, f"HESTIA_Individual_{data.city}_{start_date}.xlsx")
        pd.DataFrame(results).to_excel(out_name, index=False)
        print(f"\nFull per-time-step results written to: {out_name}")

        if _prompt("Generate plot? (y/n)", "y").lower().startswith("y"):
            from hestia_plots import generate_individual_plots
            paths = generate_individual_plots(results, data.city, start_time, age, gender, _script_dir)
            for p in paths:
                print(f"  Plot written to: {p}")

    else:
        n_simulations = _prompt_typed("Number of simulated participants", 1000, int)
        use_parallel = _prompt("Use multiprocessing? (y/n)", "y").lower().startswith("y")
        run_control_failure = _prompt("Run Thermoregulatory Control Failure analysis? (y/n)", "y").lower().startswith("y")
        # [2026-09] sample_pace=True: each participant gets their own pace/
        # MET/exposure duration (see monte_carlo_adult's own docstring)
        # instead of everyone sharing met_value/duration_hours. Off by
        # default -- this changes population results relative to every run
        # so far this season (a faster participant now genuinely finishes
        # sooner, not just "feels it less hard"), so it's an explicit
        # opt-in, not a silent behaviour change.
        sample_pace = _prompt(
            "Sample individual pace/MET/duration per participant instead of "
            f"sharing MET {met_value}/{duration_hours}h for everyone? (y/n)",
            "n",
        ).lower().startswith("y")
        seed_raw = _prompt("Random seed (blank = different each run)", "")
        random_seed = int(seed_raw) if seed_raw else None

        print(f"\nRunning Monte Carlo population (n={n_simulations}) — {data.city}, "
              f"{start_time}, MET {met_value}, {duration_hours}h. This can take a while "
              f"at full scale...")
        all_results, stats, results_df = monte_carlo_adult(
            data, start_time, duration_hours, met_value=met_value, clo_value=clo_value,
            n_simulations=n_simulations, training_factor=training_factor,
            acclimatization_factor=acclimatization_factor, sheet=sheet,
            use_parallel=use_parallel, random_seed=random_seed,
            run_control_failure=run_control_failure,
            sample_pace=sample_pace, event_dist_km=event_dist_km,
        )
        if all_results is None:
            print(f"{Fore.RED}Population generation failed (0 valid profiles). "
                  f"Try again or check parameters.{Style.RESET_ALL}")
            return

        print_cvr_population_summary(
            stats, start_group_label=f"{start_time}, MET {met_value}",
            n_participants=len(all_results), edition=data.city,
        )
        if run_control_failure and format_population_summary is not None:
            for line in format_population_summary(stats):
                print(line)

        _script_dir = os.path.dirname(os.path.abspath(__file__))
        out_name = os.path.join(_script_dir, f"HESTIA_MonteCarlo_{data.city}_{start_date}_n{len(all_results)}.xlsx")
        results_df.to_excel(out_name, index=False)
        print(f"\nPer-participant results written to: {out_name}")

        paths = []
        if _prompt("Generate plots? (y/n)", "y").lower().startswith("y"):
            from hestia_plots import generate_population_plots
            paths = generate_population_plots(all_results, results_df, stats, data.city,
                                              start_time, duration_hours, _script_dir)
            for p in paths:
                print(f"  Plot written to: {p}")

        if _prompt("Generate event report (Markdown)? (y/n)", "y").lower().startswith("y"):
            # [2026-08-26] build_bridge_summary needs interp_data, which
            # monte_carlo_adult() builds internally but does not return (its
            # return signature is a 3-tuple relied on elsewhere, e.g.
            # suite_smoke_test.py -- changing it to a 4-tuple would break
            # that caller). Recomputed here instead: build_interpolated_
            # weather() is a pure function of the same (data, start_time,
            # duration_hours, sheet) already used above, so this costs one
            # redundant interpolation pass rather than risking a signature
            # change to a function other code already depends on.
            from hestia_bridge import build_bridge_summary
            interp_for_bridge = build_interpolated_weather(data, start_time, duration_hours, sheet)
            bridge_summary = build_bridge_summary(all_results, interp_for_bridge)
            report_name = os.path.join(
                _script_dir, f"HESTIA_Report_{data.city}_{start_date}_n{len(all_results)}.md")
            activity_desc = f"MET {met_value}, clo {clo_value}"
            report_text = generate_report(
                event_name=f"{data.city} {start_date}",
                data=data, stats=stats, results_df=results_df,
                start_time=start_time, duration_hours=duration_hours,
                activity_description=activity_desc, n_simulations=len(all_results),
                output_path=report_name, bridge_summary=bridge_summary,
                plot_paths=paths, interp_data=interp_for_bridge,
                sample_pace=sample_pace,
            )
            print(f"  Report written to: {report_name}")

            # [2026-08-30] Optional Word (.docx) export -- see
            # report_to_docx.py's own docstring for why this is a shared
            # module rather than duplicated per report generator.
            if _prompt("Also export as Word (.docx)? (y/n)", "y").lower().startswith("y"):
                try:
                    from report_to_docx import export_report_docx
                    docx_name = report_name[:-3] + ".docx"
                    export_report_docx(report_text, docx_name, report_kind="facts",
                                       event_name=f"{data.city} {start_date}")
                    print(f"  Word report written to: {docx_name}")
                except Exception as e:
                    print(f"  Word export failed ({e}) -- the Markdown report above is unaffected.")

        # [2026-09] Optional per-participant dose-buildup export -- shows,
        # for chosen participant_id(s), the time-resolved build-up of
        # auc_thermisch/auc_klinisch (degree-minutes above 39.0/40.5 degC)
        # in a separate Excel workbook. Independent of the report/plot
        # prompts above, so it's available even if those were skipped.
        from participant_dose_analysis import maybe_run_participant_analysis
        maybe_run_participant_analysis(
            all_results, results_df=results_df, city=data.city,
            start_date=start_date, script_dir=_script_dir, prompt_fn=_prompt,
        )


if __name__ == "__main__":
    _run_cli()
