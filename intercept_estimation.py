# -*- coding: utf-8 -*-
"""
intercept_estimation.py
=======================
HESTIA rev13 — Standalone intercept calibration script.

PURPOSE
-------
After any architectural change that shifts the T_rect distribution
(rev13: causal pct_vo2max fix P3 + dynamic pacing P4), the intercept_kal
values in COLLAPSE_ENDPOINTS must be recalibrated so that the mean
population collapse probability matches the observed incidence rates.

This script runs Newton iteration on a large fixed population (N=50.000)
under reference meteorological conditions, and prints the three calibrated
intercepts ready to paste into HESTIA_Data_Engine_CVR_v8.py.

USAGE
-----
    python intercept_estimation.py

No command-line arguments needed. Edit the CONFIGURATION block below
to match your event or change reference conditions.

REQUIREMENTS
------------
Same dependencies as HESTIA_Data_Engine_CVR_v8.py. The engine file must
be importable from the same directory (or on sys.path).

RUNTIME
-------
N=50.000, single-threaded: ~20-60 min depending on hardware.
N=10.000 (fast check): ~4-12 min (less accurate, CI wider).

OUTPUTS
-------
- Console: iteration log + final intercepts per endpoint.
- intercept_estimation_results.json: machine-readable results including
  population statistics, convergence diagnostics, and timestamp.
- intercept_estimation_population.pkl: the fixed calibration population
  (reusable across runs to eliminate sampling noise from comparisons).

REFERENCES
----------
Breslow RG et al. (2021) Am J Sports Med 49(10):2696-2703.
  [Boston Marathon EHS 2012-2019: EP1 calibration source]
GHOR Noord-Holland Noord, DtD 2024.
  [50 / 35.000 hospitalisations: EP2 calibration source]

Author : HESTIA project / Koos de Boer, Apr-2026 (rev13)
"""

import sys
import os
import json
import time
import pickle
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from colorama import init, Fore, Style

init(autoreset=True)

# =============================================================================
#  CONFIGURATION
#  Edit this block for each calibration run.
# =============================================================================

# --- Population parameters ---
N_POPULATION   = 200      # [temp] Reduced for a single-core feasibility run;
                          # re-run at 10,000-50,000 in a multi-core environment
                          # for the production COLLAPSE_ENDPOINTS values.
RANDOM_SEED    = 42        # Fixed seed for reproducibility

# --- Simulation parameters ---
# [2026-07, RESTRUCTURED] Generalizable principle: every calibration target
# must be fit against the reference conditions under which THAT target's
# incidence was actually observed -- never a borrowed scenario from a
# different event. Previously all three endpoints below shared a single
# global REF_CONDITIONS (Boston's own scenario), even though
# 'hospitalisation' and 'ehbo' are DtD-observed numbers -- so those two were
# being fit against Boston's 4-hour, cooler conditions while targeting a
# rate that actually occurred under DtD's ~1.63-hour Amsterdam conditions.
# Verified this was not a harmless simplification: intercept minus
# logit(p_target) was nearly constant across all three endpoints
# (-1.915 / -1.791 / -1.787) purely because they shared one z-distribution
# -- an artifact of the shared reference scenario, not a real finding about
# how incidence scales with duration between events.
#
# Fix: each endpoint now names a `ref_conditions_key`, pointing at its own
# matched reference-conditions block. Endpoints whose target genuinely came
# from the same real event (hospitalisation and ehbo both from DtD 2024)
# correctly still share a block -- that's not the bug; sharing a scenario
# ACROSS different originating events was the bug. Adding a new calibration
# point later just means adding one more reference-conditions block plus an
# ENDPOINTS entry naming it -- no other code changes needed, which is what
# makes this generalizable rather than a one-off DtD-specific patch.

REF_CONDITIONS_BOSTON = {
    # Meteorological -- Boston 2017 (Breslow 2021 reference year): moderate
    # WBGT ~18degC, temperature rising during the race.
    'tdb_start'  : 18.0,   # °C dry-bulb at race start
    'tdb_end'    : 22.0,   # °C dry-bulb at race finish (rising trend)
    'rh'         : 55.0,   # % relative humidity (constant approximation)
    'wind_ms'    : 2.5,    # m/s wind at 1.5m height
    'cloud_cover': 30,     # % cloud cover
    'pressure'   : 1013.0, # hPa
    # Race parameters
    'duration_h' : 4.0,    # hours (covers slow finishers)
    'interval_min': 10,    # weather interpolation step (minutes)
    'lat'        : 42.36,  # Boston, MA
    'lon'        : -71.06,
    'start_time' : '2017-04-17 10:00:00',  # Boston 2017 start
    'timezone'   : 'America/New_York',
    # Activity
    'met_value'  : 11.0,   # MET reference (event pace; individual MET via VO2max)
    'clo_value'  : 0.2,    # summer running kit
    # Adaptation (Boston 2017 field: moderately trained)
    'training_factor'       : 0.30,
    'acclimatization_factor': 0.35,
}

# [2026-07, new] DtD 2024's own reference conditions -- approximate, in the
# same spirit as Boston's block above (a synthetic linear-ramp
# approximation, not a literal replay of the fetched Thermopoulos weather
# file for that day), built from the values seen in the actual DtD 2024
# Amsterdam simulation runs earlier this project (T_air ~19.5-21.5degC,
# WBGT ~20-21degC over the race window). Flagged PROVISIONAL, same as the
# endpoints that use it -- refine against the real fetched weather file if
# more precision is needed.
REF_CONDITIONS_DTD = {
    'tdb_start'  : 19.5,   # °C dry-bulb at race start
    'tdb_end'    : 21.5,   # °C dry-bulb at race finish (rising trend)
    'rh'         : 68.0,   # % relative humidity (approximate, Sept Amsterdam)
    'wind_ms'    : 1.5,    # m/s wind at 1.5m height (approximate)
    'cloud_cover': 40,     # % cloud cover
    'pressure'   : 1015.0, # hPa
    # Race parameters
    'duration_h' : 1.63,   # hours (matches the DtD scenarios run this project)
    'interval_min': 10,
    'lat'        : 52.37,  # Amsterdam, NL
    'lon'        : 4.90,
    'start_time' : '2024-09-22 11:30:00',
    'timezone'   : 'Europe/Amsterdam',
    # Activity
    'met_value'  : 9.8,    # MET reference (matches the DtD scenarios run this project)
    'clo_value'  : 0.2,
    # Adaptation (matches the "Average/Well-acclimatized" profile used in
    # this project's DtD test runs)
    'training_factor'       : 0.50,
    'acclimatization_factor': 0.60,
}

REF_CONDITIONS_BY_KEY = {
    'boston': REF_CONDITIONS_BOSTON,
    'dtd'   : REF_CONDITIONS_DTD,
}

# --- Calibration targets ---
# Each endpoint has a target P_obs (observed incidence rate) AND a
# ref_conditions_key naming which reference-conditions block above matches
# the event that target was actually observed at.
# Status controls what is printed in the output report.
ENDPOINTS = {
    'ehs': {
        'label'   : 'EHS klinisch (Boston 2012-2019 gepoold)',
        'p_target': 9.0 / 10_000,          # 0.00090  Breslow 2021
        'source'  : 'Breslow RG et al. (2021) Am J Sports Med 49(10):2696-2703',
        'status'  : 'PRIMARY',             # most trustworthy calibration point
        'ref_conditions_key': 'boston',
    },
    'hospitalisation': {
        'label'   : 'Hospital admission (DtD 2024)',
        'p_target': 50.0 / 35_000,         # 0.001429  GHOR NHN
        'source'  : 'GHOR Noord-Holland Noord, Dam tot Damloop 2024',
        'status'  : 'PROVISIONAL',
        'ref_conditions_key': 'dtd',
    },
    'ehbo': {
        'label'   : 'First-aid contact, all incidents (DtD 2024 estimate)',
        'p_target': 150.0 / 35_000,        # 0.004286  centrale schatting
        'source'  : 'Schatting GHOR NHN / DtD 2024 (ongepubliceerd)',
        'status'  : 'PROVISIONAL',
        'ref_conditions_key': 'dtd',
    },
}

# --- Newton iteration parameters ---
INTERCEPT_INIT  = -8.0    # starting point (safely above expected answer)
MAX_ITER        = 40      # maximum Newton steps
TOL_ABS         = 1e-9    # convergence: |p_mean - p_target| < TOL_ABS
TOL_REL         = 1e-7    # convergence: |delta_intercept| < TOL_REL

# --- Collapse risk model weights (must match HESTIA_Data_Engine_CVR_v8.py) ---
W_T1 = 1.0   # T_rect above 39.5°C
W_T2 = 4.0   # T_rect above 40.5°C (steep second phase)
W_C  = 0.8   # CO_reserve below 2.0
W_D  = 0.5   # dehydration above 3% body weight

# --- Output files ---
RESULTS_JSON = 'intercept_estimation_results.json'
# [2026-07] POP_PKL is now built per ref_conditions_key inside get_population()
# -- see that function's docstring for why.


# =============================================================================
#  IMPORT HESTIA ENGINE
# =============================================================================

def _import_engine():
    """Import generate_base_population and run_monte_carlo_adult from the engine."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # [fix] Post-rev17 integration renamed the engine file to hestia_model.py
    # (see MANIFEST.md). Try that first; keep the old v8/v7 names as a
    # fallback only for anyone still on a pre-integration snapshot.
    for module_name in ('hestia_model', 'HESTIA_Data_Engine_CVR_v8', 'HESTIA_Data_Engine_CVR_v7'):
        try:
            import importlib
            engine = importlib.import_module(module_name)
            print(f"{Fore.GREEN}Engine loaded: {module_name}{Style.RESET_ALL}")
            if module_name != 'hestia_model':
                print(f"{Fore.YELLOW}WARNING: this is a pre-rev17 file name. "
                      f"The calibration applies to that version, NOT to the current "
                      f"hestia_model.py snapshot.{Style.RESET_ALL}")
            return engine
        except ImportError:
            continue

    print(f"{Fore.RED}ERROR: No HESTIA engine found in {script_dir}.{Style.RESET_ALL}")
    print("Make sure hestia_model.py is in the same directory.")
    sys.exit(1)


# =============================================================================
#  REFERENCE WEATHER BUILDER
#  Constructs a synthetic interp_data list (same format as interpolate_weather)
#  that represents the reference meteorological conditions without needing
#  an API call.  Temperature rises linearly from tdb_start to tdb_end.
# =============================================================================

def build_reference_interp(cfg: dict) -> list:
    """
    Build a synthetic interp_data list from the REF_CONDITIONS dict.

    Returns a list of dicts with keys:
        time, temp, rh, wind, clouds, pressure, twb
    in the same format as interpolate_weather() output.
    """
    import pytz
    from pythermalcomfort.utilities import wet_bulb_tmp

    tz       = pytz.timezone(cfg['timezone'])
    start_dt = pd.Timestamp(cfg['start_time']).tz_localize(tz)
    end_dt   = start_dt + pd.Timedelta(hours=cfg['duration_h'])
    times    = pd.date_range(start=start_dt, end=end_dt,
                              freq=f"{cfg['interval_min']}min")

    n_steps  = len(times)
    # Linear temperature ramp
    temps    = np.linspace(cfg['tdb_start'], cfg['tdb_end'], n_steps)

    interp_data = []
    for i, t in enumerate(times):
        tdb = float(temps[i])
        rh  = float(cfg['rh'])
        interp_data.append({
            'time'    : t,
            'temp'    : tdb,
            'rh'      : rh,
            'wind'    : float(cfg['wind_ms']),
            'clouds'  : float(cfg['cloud_cover']),
            'pressure': float(cfg['pressure']),
            'twb'     : float(wet_bulb_tmp(tdb=tdb, rh=rh)),
        })

    print(f"  Referentie-interp gebouwd: {n_steps} tijdstappen, "
          f"{cfg['tdb_start']}→{cfg['tdb_end']}°C, "
          f"RH={cfg['rh']}%, wind={cfg['wind_ms']} m/s")
    return interp_data


# =============================================================================
#  POPULATION LOADER / GENERATOR
# =============================================================================

def get_population(engine, ref_key: str, cfg: dict) -> list:
    """Load existing calibration population or generate a fresh one.

    [2026-07] Takes ref_key/cfg explicitly now that different endpoints can
    use different reference conditions (different training/acclimatization
    factors change the generated population itself) -- the cache filename
    is keyed by ref_key so a Boston-conditions population is never
    accidentally reused for a DtD-conditions calibration or vice versa.
    """
    pop_pkl = f'intercept_estimation_population_{ref_key}_N{N_POPULATION}_seed{RANDOM_SEED}.pkl'
    if os.path.isfile(pop_pkl):
        ans = input(f"\nCalibration population '{pop_pkl}' found. Load it? (y/n, recommended=y): ").strip().lower()
        if ans in ('y', 'yes', ''):
            try:
                population = engine.load_population(pop_pkl)
                if len(population) >= N_POPULATION:
                    print(f"{Fore.GREEN}Population loaded: {len(population)} profiles.{Style.RESET_ALL}")
                    return population[:N_POPULATION]
                else:
                    print(f"{Fore.YELLOW}Population has {len(population)} profiles; "
                          f"{N_POPULATION} needed. Regenerating.{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.YELLOW}Loading failed ({e}). Regenerating.{Style.RESET_ALL}")

    print(f"\nGenerating calibration population N={N_POPULATION}, seed={RANDOM_SEED} "
          f"(ref_conditions='{ref_key}')...")
    t0 = time.time()
    population = engine.generate_base_population(
        n_simulations          = N_POPULATION,
        training_factor        = cfg['training_factor'],
        acclimatization_factor = cfg['acclimatization_factor'],
        random_seed            = RANDOM_SEED,
    )
    print(f"  Generation: {time.time()-t0:.1f}s, {len(population)} valid profiles.")

    engine.save_population(population, pop_pkl)
    return population


# =============================================================================
#  SIMULATION RUNNER
# =============================================================================

def _detect_parallel_safe() -> bool:
    """
    Return True only if multiprocessing is safe in this environment.

    On Windows, multiprocessing uses 'spawn' as start method.  When the
    script is run from Spyder / IPython / Jupyter, child worker processes
    cannot re-import the interactive __main__ module and crash silently
    (IndexError: pop from empty deque).  This function detects that
    situation and forces serial execution.

    On Linux / macOS ('fork' start method) parallel is always safe.
    """
    if os.name != 'nt':
        return True   # fork-based: always safe

    # Windows: check for interactive / IDE environment
    in_ipython = (
        hasattr(sys, 'ps1') or
        any(k in sys.modules for k in ('IPython', 'ipykernel', 'spyder',
                                        'spyder_kernels'))
    )
    if in_ipython:
        print("  [INFO] Spyder/IPython/Jupyter detected on Windows -- "
              "use_parallel=False (avoids a multiprocessing crash).\n"
              "  Tip: for ~5x speed, start from a plain terminal instead:\n"
              "       python intercept_estimation.py")
        return False

    return True


def run_calibration_simulation(engine, population: list, interp_data: list, cfg: dict) -> dict:
    """
    Run the Monte Carlo simulation on the calibration population and
    extract the three outcome vectors needed for Newton iteration.

    Returns
    -------
    dict with arrays (all shape (N,)):
        't_rect_max' : maximum T_rect per participant over the race
        'co_res_min' : minimum CO_reserve per participant
        'dehy_end'   : final dehydration % per participant

    Notes on parallel execution
    ---------------------------
    On Windows + Spyder/IPython, use_parallel is forced to False.
    Single-threaded throughput is ~0.7 sim/s; N=10.000 ≈ 4 h.
    For production (N=50.000) use a standalone Windows terminal,
    which enables the multiprocessing pool safely.
    """
    parallel = _detect_parallel_safe()
    mode_str = "parallel" if parallel else "serial (single-threaded)"

    n = len(population)
    print(f"\nSimulating {n} participants under reference conditions ({mode_str})...")
    if not parallel:
        mins_est = n * 0.72 / 60
        print(f"  Geschatte looptijd: {mins_est:.0f}–{mins_est*1.5:.0f} min.")

    t0 = time.time()

    all_results, stats, results_df = engine.run_monte_carlo_adult(
        interp_data            = interp_data,
        lat                    = cfg['lat'],
        lon                    = cfg['lon'],
        met_value              = cfg['met_value'],
        clo_value              = cfg['clo_value'],
        n_simulations          = n,
        age_configuration      = 'standard',
        training_factor        = cfg['training_factor'],
        acclimatization_factor = cfg['acclimatization_factor'],
        use_parallel           = parallel,
        base_population        = population,
        random_seed            = None,  # population already fixed
    )

    elapsed = time.time() - t0
    print(f"  Simulatie gereed: {elapsed/60:.1f} min ({elapsed:.0f}s)")

    if all_results is None:
        print(f"{Fore.RED}Simulatie mislukt — all_results is None.{Style.RESET_ALL}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Extraheer uitkomstvectoren
    # ------------------------------------------------------------------
    t_rect_max = np.array([
        max((r['t_rect'] for r in sim if not np.isnan(r['t_rect'])), default=np.nan)
        for sim in all_results
    ])

    # CO_reserve: use a nan-robust min; fall back to 2.0 if entirely nan
    # 2.0 = physiologically neutral (no stress, no contribution to the Z-score)
    co_res_raw = np.array([
        np.nanmin([r.get('co_reserve', np.nan) for r in sim])
        for sim in all_results
    ])
    n_co_nan   = int(np.sum(np.isnan(co_res_raw)))
    n_co_valid = int(np.sum(~np.isnan(co_res_raw)))

    if n_co_nan > 0:
        pct_nan = n_co_nan / len(co_res_raw) * 100
        if pct_nan == 100.0:
            print(f"\n{Fore.YELLOW}[WARNING] CO_reserve is 100% NaN -- the CVR module "
                  f"did not write any valid values.{Style.RESET_ALL}")
            print(f"  Cause: link_cvr_to_jos3() returned empty output, or "
                  f"CVR_AVAILABLE=False in the engine despite a successful import.")
            print(f"  Action: CO_reserve is replaced with a neutral fallback of 2.0 "
                  f"(no cardiovascular contribution to the Z-score).")
            print(f"  Consequence: the intercept is calibrated WITHOUT the CO_reserve term.")
            print(f"          Recalibrate as soon as the CVR module produces correct output.\n")
        else:
            print(f"\n{Fore.YELLOW}[WARNING] CO_reserve: {n_co_nan} of {len(co_res_raw)} "
                  f"participants ({pct_nan:.1f}%) has NaN. "
                  f"Falling back to 2.0 for those participants.{Style.RESET_ALL}\n")

    # Replace nan with 2.0 (neutral value -- no CV contribution to Z)
    co_res_min = np.where(np.isnan(co_res_raw), 2.0, co_res_raw)

    dehy_end = np.array([
        sim[-1]['water'] / 1000.0 / max(1.0, population[i].weight) * 100.0
        for i, sim in enumerate(all_results)
    ])
    # Dehydration nan guard
    n_dehy_nan = int(np.sum(np.isnan(dehy_end)))
    if n_dehy_nan > 0:
        print(f"{Fore.YELLOW}[WARNING] Dehydration: {n_dehy_nan} NaN values -- "
              f"replaced with 0.0.{Style.RESET_ALL}")
        dehy_end = np.where(np.isnan(dehy_end), 0.0, dehy_end)

    # T_rect nan guard
    n_trect_nan = int(np.sum(np.isnan(t_rect_max)))
    if n_trect_nan > 0:
        print(f"{Fore.YELLOW}[WARNING] T_rect_max: {n_trect_nan} NaN values -- "
              f"replaced with the population median.{Style.RESET_ALL}")
        median_t = float(np.nanmedian(t_rect_max))
        t_rect_max = np.where(np.isnan(t_rect_max), median_t, t_rect_max)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    print(f"\n  T_rect distribution (population):")
    for pct in (5, 25, 50, 75, 90, 95, 99):
        print(f"    P{pct:2d}: {np.percentile(t_rect_max, pct):.3f}degC")
    print(f"    % > 39.5degC : {np.mean(t_rect_max > 39.5)*100:.2f}%")
    print(f"    % > 40.5degC : {np.mean(t_rect_max > 40.5)*100:.2f}%")
    print(f"\n  CO_reserve diagnostics:")
    print(f"    Valid (non-NaN)  : {n_co_valid} / {len(co_res_raw)}")
    if n_co_valid > 0:
        print(f"    P50 (valid)      : {float(np.nanpercentile(co_res_raw[~np.isnan(co_res_raw)], 50)):.3f}")
        print(f"    % < 2.0          : {np.mean(co_res_min < 2.0)*100:.1f}%")
        print(f"    % <= 0           : {np.mean(co_res_min <= 0)*100:.2f}%")
    else:
        print(f"    ALL NaN -- calibrating without the CV term (see warning above)")
    print(f"\n  End dehydration P50: {np.percentile(dehy_end, 50):.2f}%")
    print(f"  End dehydration P95: {np.percentile(dehy_end, 95):.2f}%")

    # ------------------------------------------------------------------
    # Warn if the T_rect distribution is unsuitable for calibration
    # ------------------------------------------------------------------
    pct_above_395 = np.mean(t_rect_max > 39.5) * 100
    if pct_above_395 < 0.5:
        print(f"\n{Fore.YELLOW}[WARNING] Only {pct_above_395:.2f}% of the population "
              f"exceeds 39.5degC.{Style.RESET_ALL}")
        print(f"  The Z-score is dominated by the intercept term; Newton iteration "
              f"is numerically unstable with this little activation.")
        print(f"  Consider a higher reference temperature (raise tdb_start/end) or "
              f"a higher MET_value in REF_CONDITIONS.\n")

    return {
        't_rect_max'  : t_rect_max,
        'co_res_min'  : co_res_min,
        'dehy_end'    : dehy_end,
        'stats'       : stats,
        'elapsed_s'   : elapsed,
        'n_co_nan'    : n_co_nan,
        'n_co_valid'  : n_co_valid,
    }

    elapsed = time.time() - t0
    print(f"  Simulatie gereed: {elapsed/60:.1f} min ({elapsed:.0f}s)")

    if all_results is None:
        print(f"{Fore.RED}Simulatie mislukt.{Style.RESET_ALL}")
        sys.exit(1)

    # Extract outcome vectors
    t_rect_max = np.array([
        max(r['t_rect'] for r in sim) for sim in all_results
    ])
    co_res_min = np.array([
        min((r.get('co_reserve', 2.0) for r in sim), default=2.0)
        for sim in all_results
    ])
    dehy_end = np.array([
        sim[-1]['water'] / 1000.0 / max(1.0, population[i].weight) * 100.0
        for i, sim in enumerate(all_results)
    ])

    # Summary statistics for the report
    print(f"\n  T_rect distribution (population):")
    for pct in (5, 25, 50, 75, 90, 95, 99):
        print(f"    P{pct:2d}: {np.percentile(t_rect_max, pct):.3f}°C")
    print(f"    % > 39.5°C : {np.mean(t_rect_max > 39.5)*100:.2f}%")
    print(f"    % > 40.5°C : {np.mean(t_rect_max > 40.5)*100:.2f}%")
    print(f"  CO_reserve min P50: {np.percentile(co_res_min, 50):.3f}")
    print(f"  Dehydratie eind P50: {np.percentile(dehy_end, 50):.2f}%")

    return {
        't_rect_max': t_rect_max,
        'co_res_min': co_res_min,
        'dehy_end'  : dehy_end,
        'stats'     : stats,
        'elapsed_s' : elapsed,
    }


# =============================================================================
#  COLLAPSE PROBABILITY CALCULATOR
#  This is the core function that Newton calls repeatedly.
# =============================================================================

def compute_z_vector(sim_out: dict, intercept: float) -> np.ndarray:
    """Compute the Z-score vector for all N participants at a given intercept."""
    if not np.isfinite(intercept):
        raise ValueError(f"intercept is not finite: {intercept}")

    t   = sim_out['t_rect_max']
    co  = sim_out['co_res_min']
    deh = sim_out['dehy_end']

    # Nan guard: replace any remaining nan with neutral values
    t   = np.where(np.isfinite(t),   t,   38.9)   # below the 39.5degC threshold
    co  = np.where(np.isfinite(co),  co,  2.0)    # no CV contribution
    deh = np.where(np.isfinite(deh), deh, 0.0)    # no dehydration contribution

    z = (intercept
         + W_T1 * np.clip(t   - 39.5, 0.0, None)
         + W_T2 * np.clip(t   - 40.5, 0.0, None)
         + W_C  * np.clip(2.0 - co,   0.0, None)
         + W_D  * np.clip(deh - 3.0,  0.0, None))
    return z


def mean_p_and_deriv(sim_out: dict, intercept: float):
    """
    Return (mean_p_collapse, d_mean_p/d_intercept) for Newton step.

    The derivative of mean(p_i) with respect to the intercept is:
        mean(p_i * (1 - p_i))
    This follows from the logistic function: dp_i/d_intercept = p_i*(1-p_i).
    """
    z      = compute_z_vector(sim_out, intercept)
    # Clip z to avoid overflow in exp (sigmoid is 0 or 1 outside [-500,500])
    z      = np.clip(z, -500, 500)
    p_vec  = 1.0 / (1.0 + np.exp(-z))
    p_mean = float(p_vec.mean())
    dp_di  = float((p_vec * (1.0 - p_vec)).mean())
    return p_mean, dp_di


def bisection_intercept(sim_out: dict, p_target: float,
                         lo: float = -30.0, hi: float = 5.0,
                         tol: float = 1e-7, max_iter: int = 80) -> dict:
    """
    Bisection as a robust fallback for Newton iteration.

    Searches for an intercept in [lo, hi] such that mean_p_collapse(intercept) = p_target.
    Always converges if p_target is reachable within the interval.
    Typically 50-60 iterations for tol=1e-7.
    """
    print(f"\n  [Bisection] Searching in [{lo}, {hi}], target={p_target:.8f}")

    p_lo, _ = mean_p_and_deriv(sim_out, lo)
    p_hi, _ = mean_p_and_deriv(sim_out, hi)

    if p_lo > p_target:
        print(f"  [Bisectie] FOUT: p(lo={lo}) = {p_lo:.6f} > target. "
              f"Verklein lo (meer negatief).")
        return {'converged': False, 'intercept': float('nan')}
    if p_hi < p_target:
        print(f"  [Bisectie] FOUT: p(hi={hi}) = {p_hi:.6f} < target. "
              f"Vergroot hi (minder negatief).")
        return {'converged': False, 'intercept': float('nan')}

    history = []
    for i in range(1, max_iter + 1):
        mid    = (lo + hi) / 2.0
        p_mid, _ = mean_p_and_deriv(sim_out, mid)
        error  = p_mid - p_target
        history.append({'iter': i, 'intercept': mid, 'p_mean': p_mid, 'error': error})

        if i <= 5 or i % 10 == 0:
            print(f"  [Bisectie] iter {i:3d}: intercept={mid:.6f}, "
                  f"p_mean={p_mid:.8f}, error={error:+.3e}")

        if abs(hi - lo) < tol:
            print(f"  [Bisectie] Geconvergeerd na {i} iteraties.")
            return {
                'intercept'  : mid,
                'p_final'    : p_mid,
                'p_target'   : p_target,
                'error_final': error,
                'n_iter'     : i,
                'converged'  : True,
                'history'    : history,
                'method'     : 'bisection',
            }

        if p_mid < p_target:
            lo = mid
        else:
            hi = mid

    mid = (lo + hi) / 2.0
    p_mid, _ = mean_p_and_deriv(sim_out, mid)
    return {
        'intercept'  : mid,
        'p_final'    : p_mid,
        'p_target'   : p_target,
        'error_final': p_mid - p_target,
        'n_iter'     : max_iter,
        'converged'  : abs(hi - lo) < tol * 10,
        'history'    : history,
        'method'     : 'bisection',
    }


# =============================================================================
#  NEWTON ITERATION
# =============================================================================

def calibrate_intercept(sim_out: dict, p_target: float,
                         label: str = '') -> dict:
    """
    Find intercept_kal such that mean(p_collapse) == p_target using Newton iteration.

    Parameters
    ----------
    sim_out   : dict from run_calibration_simulation()
    p_target  : float -- target mean collapse probability
    label     : str   -- endpoint name for printing

    Returns
    -------
    dict with keys:
        'intercept'    : float  -- calibrated intercept
        'p_final'      : float  -- achieved mean p_collapse
        'error_final'  : float  -- p_final - p_target
        'n_iter'       : int    -- Newton iterations used
        'converged'    : bool
        'history'      : list of dicts (intercept, p_mean, error per iteration)
    """
    intercept = INTERCEPT_INIT
    history   = []

    print(f"\n{'='*60}")
    print(f"Newton-iteratie: {label}")
    print(f"  Target P_obs = {p_target:.8f}  ({p_target*10_000:.4f} / 10.000)")
    print(f"  Startpunt intercept = {INTERCEPT_INIT}")
    print(f"  Tolerantie: |error| < {TOL_ABS:.0e}  |  |Δintercept| < {TOL_REL:.0e}")
    print(f"{'='*60}")
    print(f"  {'Iter':>4}  {'Intercept':>12}  {'p_mean':>12}  {'Error':>12}  {'|Δintercept|':>14}")
    print(f"  {'-'*60}")

    converged       = False
    delta_intercept = float('inf')

    for i in range(1, MAX_ITER + 1):
        p_mean, dp_di = mean_p_and_deriv(sim_out, intercept)
        error         = p_mean - p_target

        history.append({
            'iter'           : i,
            'intercept'      : intercept,
            'p_mean'         : p_mean,
            'error'          : error,
            'delta_intercept': delta_intercept,
        })

        # Colour the error for readability
        err_str = f"{error:+.3e}"
        if abs(error) < TOL_ABS * 10:
            err_col = Fore.GREEN
        elif abs(error) < p_target * 0.01:
            err_col = Fore.CYAN
        else:
            err_col = Fore.YELLOW

        print(f"  {i:4d}  {intercept:12.6f}  {p_mean:12.8f}  "
              f"{err_col}{err_str}{Style.RESET_ALL}  {delta_intercept:14.3e}")

        # Convergence check
        if abs(error) < TOL_ABS and abs(delta_intercept) < TOL_REL:
            converged = True
            break

        # Guard against zero derivative (pathological case)
        if abs(dp_di) < 1e-15:
            print(f"{Fore.YELLOW}  Derivative ~= 0 at iter {i} "
                  f"(p_mean={p_mean:.3e}, intercept={intercept:.3f}). "
                  f"Switching to bisection.{Style.RESET_ALL}")
            break

        # Guard against nan (propagated from simulation output)
        if not np.isfinite(p_mean) or not np.isfinite(dp_di):
            print(f"{Fore.RED}  NaN detected at iter {i}. "
                  f"Switching to bisection.{Style.RESET_ALL}")
            break

        # Newton step
        delta_intercept = error / dp_di
        intercept      -= delta_intercept

        # Safety rail: intercept should stay in [-20, 5]
        if intercept < -20 or intercept > 5:
            print(f"{Fore.YELLOW}  WAARSCHUWING: intercept {intercept:.3f} buiten bereik. "
                  f"Controleer startpunt en target.{Style.RESET_ALL}")
            intercept = max(-20.0, min(5.0, intercept))

    # Final evaluation at converged intercept
    if np.isfinite(intercept):
        p_final, _ = mean_p_and_deriv(sim_out, intercept)
        error_final = p_final - p_target
    else:
        p_final     = float('nan')
        error_final = float('nan')

    if not converged or not np.isfinite(intercept):
        print(f"\n{Fore.YELLOW}  Newton did not converge -- switching to bisection.{Style.RESET_ALL}")
        bis = bisection_intercept(sim_out, p_target)
        if bis['converged']:
            print(f"{Fore.GREEN}  Bisection converged: intercept={bis['intercept']:.6f}{Style.RESET_ALL}")
            return {**bis, 'label': label}
        else:
            print(f"{Fore.RED}  Bisection also did not converge. "
                  f"Check the T_rect distribution and target P_obs.{Style.RESET_ALL}")
            return {
                'intercept'   : float('nan'),
                'p_final'     : float('nan'),
                'p_target'    : p_target,
                'error_final' : float('nan'),
                'n_iter'      : i,
                'converged'   : False,
                'history'     : history,
                'method'      : 'failed',
                'label'       : label,
            }

    status_str = f"{Fore.GREEN}GECONVERGEERD{Style.RESET_ALL}" if converged \
                 else f"{Fore.RED}NIET GECONVERGEERD na {MAX_ITER} iteraties{Style.RESET_ALL}"
    print(f"\n  Status     : {status_str}")
    print(f"  Intercept  : {intercept:.6f}")
    print(f"  p_final    : {p_final:.8f}")
    print(f"  p_target   : {p_target:.8f}")
    print(f"  |Error|    : {abs(error_final):.3e}  ({abs(error_final)/p_target*100:.4f}%)")

    return {
        'intercept'   : intercept,
        'p_final'     : p_final,
        'p_target'    : p_target,
        'error_final' : error_final,
        'n_iter'      : i,
        'converged'   : converged,
        'history'     : history,
    }


# =============================================================================
#  SENSITIVITY ANALYSIS
#  For EHBO (EP3) where P_obs is uncertain, run calibration over the
#  plausible range of N_obs and tabulate the resulting intercepts.
# =============================================================================

def sensitivity_analysis_ehbo(sim_out: dict) -> dict:
    """
    Calibrate EP3 for N_EHBO in [100, 125, 150, 175, 200, 250] / 35.000.
    Returns dict {n_ehbo: intercept}.
    """
    print(f"\n{'='*60}")
    print("Sensitivity analysis EP3 (first-aid contact, DtD 2024)")
    print(f"{'='*60}")

    n_range    = [100, 125, 150, 175, 200, 225, 250]
    n_total    = 35_000
    results    = {}

    print(f"  {'N_EHBO':>8}  {'P_obs/10k':>12}  {'Intercept':>12}  {'p_final':>12}")
    print(f"  {'-'*50}")

    for n_ehbo in n_range:
        p_t = n_ehbo / n_total
        res = calibrate_intercept(sim_out, p_t,
                                   label=f"EP3 sensitivity N={n_ehbo}")
        results[n_ehbo] = res['intercept']
        status = "OK" if res['converged'] else "WARN"
        print(f"  {n_ehbo:8d}  {p_t*10_000:12.4f}  "
              f"{res['intercept']:12.6f}  {res['p_final']:12.8f}  {status}")

    return results


# =============================================================================
#  CONFIDENCE INTERVAL ESTIMATION
#  Bootstrap uncertainty on the intercept due to finite N.
#  Only run if explicitly requested (slow).
# =============================================================================

def bootstrap_ci(sim_out: dict, p_target: float,
                  intercept_cal: float,
                  n_boot: int = 500) -> tuple:
    """
    Estimate 95% CI on intercept_cal via non-parametric bootstrap.

    Resamples the N-participant outcome vectors with replacement,
    runs a quick Newton iteration on each resample, and returns
    (ci_lower, ci_upper) at the 2.5th and 97.5th percentiles.

    Parameters
    ----------
    n_boot : int -- number of bootstrap resamples (500 sufficient for CI)
    """
    N     = len(sim_out['t_rect_max'])
    boots = []

    print(f"\n  Bootstrap CI ({n_boot} resamples, N={N})...")
    t0 = time.time()

    for b in range(n_boot):
        idx  = np.random.randint(0, N, size=N)
        boot = {
            't_rect_max': sim_out['t_rect_max'][idx],
            'co_res_min': sim_out['co_res_min'][idx],
            'dehy_end'  : sim_out['dehy_end'][idx],
        }
        # Fast Newton (fewer iterations, looser tolerance)
        intercept = intercept_cal  # warm start from calibrated value
        for _ in range(15):
            p_mean, dp_di = mean_p_and_deriv(boot, intercept)
            error = p_mean - p_target
            if abs(error) < 1e-7 or abs(dp_di) < 1e-15:
                break
            intercept -= error / dp_di
        boots.append(intercept)

        if (b + 1) % 100 == 0:
            print(f"    {b+1}/{n_boot}  elapsed: {time.time()-t0:.0f}s")

    ci_lo = float(np.percentile(boots, 2.5))
    ci_hi = float(np.percentile(boots, 97.5))
    print(f"  Bootstrap 95% CI: [{ci_lo:.6f}, {ci_hi:.6f}]  "
          f"(±{(ci_hi-ci_lo)/2:.6f})")
    return ci_lo, ci_hi


# =============================================================================
#  REPORT GENERATOR
# =============================================================================

def print_final_report(calibration_results: dict, sensitivity: dict,
                        sim_meta: dict) -> None:
    """Print the full calibration report and paste-ready intercept block."""
    print(f"\n\n{'#'*72}")
    print("# HESTIA rev13 -- CALIBRATION REPORT")
    print(f"# Generated  : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"# N_population: {sim_meta['n_population']}")
    print(f"# Seed        : {sim_meta['random_seed']}")
    # [2026-07] Each endpoint may use its own reference conditions now
    # (see ENDPOINTS[*]['ref_conditions_key']) -- list all of them rather
    # than assuming one shared block.
    for ref_key, cfg in REF_CONDITIONS_BY_KEY.items():
        print(f"# Conditions [{ref_key}]: T={cfg['tdb_start']}->{cfg['tdb_end']}°C, "
              f"RH={cfg['rh']}%, wind={cfg['wind_ms']} m/s, duration={cfg['duration_h']}h")
    print(f"# Simulation time: {sim_meta['elapsed_s']/60:.1f} min")
    print(f"{'#'*72}")

    print(f"\n{'='*72}")
    print("INTERCEPT SUMMARY")
    print(f"{'='*72}")
    fmt = "  {:<22}  {:>12}  {:>10}  {:>8}  {:>6}  {:>8}"
    print(fmt.format('Endpoint', 'Intercept', 'p_obs/10k', 'Conv.iter', 'Status', 'RefCond'))
    print("  " + "-"*68)

    for ep_key, res in calibration_results.items():
        ep    = ENDPOINTS[ep_key]
        conv  = f"yes ({res['n_iter']})" if res['converged'] else f"NO ({res['n_iter']})"
        p10k  = res['p_target'] * 10_000
        print(fmt.format(
            ep_key, f"{res['intercept']:.6f}", f"{p10k:.4f}", conv, ep['status'],
            ep['ref_conditions_key']
        ))

    # Sensitivity for EP3
    if sensitivity:
        print(f"\n  EP3 sensitivity range (EHBO, N/35,000):")
        for n_ehbo, ic in sorted(sensitivity.items()):
            p10k = n_ehbo / 35_000 * 10_000
            print(f"    N={n_ehbo:4d} ({p10k:.1f}/10k) -> intercept: {ic:.6f}")

    # Paste-ready COLLAPSE_ENDPOINTS block
    print(f"\n{'='*72}")
    print("PASTE-READY: replace COLLAPSE_ENDPOINTS in hestia_model.py")
    print(f"{'='*72}")

    ep_map = {
        'ehs'            : 'ehs',
        'hospitalisation': 'hospitalisation',
        'ehbo'           : 'ehbo',
    }
    label_map = {
        'ehs'            : 'EHS (clinical, Boston Marathon pooled)',
        'hospitalisation': 'Hospital admission (DtD 2024)',
        'ehbo'           : 'First-aid contact, all incidents (DtD 2024 estimate)',
    }
    p_obs_map = {
        'ehs'            : '9.0 / 10_000',
        'hospitalisation': '50.0 / 35_000',
        'ehbo'           : '150.0 / 35_000',
    }
    source_map = {
        'ehs'            : 'Breslow RG et al. (2021) Am J Sports Med 49(10):2696-2703',
        'hospitalisation': 'GHOR Noord-Holland Noord, Dam tot Damloop 2024',
        'ehbo'           : 'Estimate GHOR NHN / DtD 2024 (unpublished)',
    }
    status_map = {
        'ehs'            : 'VALIDATED',
        'hospitalisation': 'PROVISIONAL',
        'ehbo'           : 'PROVISIONAL',
    }

    cal_ts = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    print(f"\nCOLLAPSE_ENDPOINTS = {{")
    for ep_key in ('ehs', 'hospitalisation', 'ehbo'):
        res = calibration_results[ep_key]
        ep  = ENDPOINTS[ep_key]
        ic  = res['intercept']
        print(f"    '{ep_map[ep_key]}': {{")
        print(f"        'label'        : '{label_map[ep_key]}',")
        print(f"        'p_obs'        : {p_obs_map[ep_key]},")
        print(f"        'n_obs'        : {ep['p_target'] * (35_000 if ep_key != 'ehs' else 10_000):.1f},")
        print(f"        'n_participants': {35_000 if ep_key != 'ehs' else 10_000},")
        print(f"        'intercept_kal': {ic:.6f},   # rev13 calibrated {cal_ts} "
              f"N={sim_meta['n_population']} seed={sim_meta['random_seed']}")
        print(f"        'source'       : '{source_map[ep_key]}',")
        print(f"        'status'       : '{status_map[ep_key]}',")
        if ep_key == 'ehbo' and sensitivity:
            print(f"        'sensitivity'  : {{")
            for n_ehbo, ic_s in sorted(sensitivity.items()):
                print(f"            {n_ehbo}: {ic_s:.6f},")
            print(f"        }},")
        print(f"    }},")
    print(f"}}")

    print(f"\n{'='*72}")
    print("VALIDATION CHECK")
    print(f"{'='*72}")
    print("Verify after pasting into the engine:")
    print("  1. Start hestia_model.py")
    print("  2. Choose mode 'adult', Boston conditions, N=5000")
    print("  3. Check in the CVR summary:")
    for ep_key, res in calibration_results.items():
        p10k = res['p_target'] * 10_000
        print(f"     {ep_key:<22}: expected ~{p10k:.4f}/10k, "
              f"i.e. ~{p10k/10:.2f} per 1000 participants")
    print(f"\n  IMPORTANT: intercept_kal = -10.071 (rev12) is now SUPERSEDED.")
    print(f"  Use only the rev13 values above for GHOR reports.")


# =============================================================================
#  JSON SAVER
# =============================================================================

def save_results_json(calibration_results: dict, sensitivity: dict,
                       sim_metas: dict, sim_outs: dict) -> None:
    """Save calibration results to JSON for audit trail.

    [2026-07] sim_metas/sim_outs are now dicts keyed by ref_conditions_key
    (one entry per distinct reference scenario used), not a single shared
    one -- see the ENDPOINTS/REF_CONDITIONS_BY_KEY restructuring above.
    """
    payload = {
        'metadata': {
            'hestia_version'      : 'rev13',
            'script'              : 'intercept_estimation.py',
            'generated_utc'       : datetime.now(timezone.utc).isoformat(),
            'ref_conditions'      : REF_CONDITIONS_BY_KEY,
            'per_ref_condition'   : {
                ref_key: {
                    'n_population'        : meta['n_population'],
                    'random_seed'         : meta['random_seed'],
                    'simulation_elapsed_s': meta['elapsed_s'],
                    't_rect_max_mean' : float(sim_outs[ref_key]['t_rect_max'].mean()),
                    't_rect_max_p50'  : float(np.percentile(sim_outs[ref_key]['t_rect_max'], 50)),
                    't_rect_max_p90'  : float(np.percentile(sim_outs[ref_key]['t_rect_max'], 90)),
                    't_rect_max_p95'  : float(np.percentile(sim_outs[ref_key]['t_rect_max'], 95)),
                    't_rect_max_p99'  : float(np.percentile(sim_outs[ref_key]['t_rect_max'], 99)),
                    'pct_above_39_5'  : float(np.mean(sim_outs[ref_key]['t_rect_max'] > 39.5) * 100),
                    'pct_above_40_5'  : float(np.mean(sim_outs[ref_key]['t_rect_max'] > 40.5) * 100),
                    'co_res_min_p50'  : float(np.percentile(sim_outs[ref_key]['co_res_min'], 50)),
                    'dehy_end_p50'    : float(np.percentile(sim_outs[ref_key]['dehy_end'], 50)),
                }
                for ref_key, meta in sim_metas.items()
            },
            'model_weights'       : {
                'W_T1': W_T1, 'W_T2': W_T2, 'W_C': W_C, 'W_D': W_D,
            },
        },
        'calibration_results': {
            ep: {
                'intercept'  : res['intercept'],
                'p_target'   : res['p_target'],
                'p_final'    : res['p_final'],
                'error_final': res['error_final'],
                'n_iter'     : res['n_iter'],
                'converged'  : res['converged'],
                'label'      : ENDPOINTS[ep]['label'],
                'source'     : ENDPOINTS[ep]['source'],
                'status'     : ENDPOINTS[ep]['status'],
                'ref_conditions_key': ENDPOINTS[ep]['ref_conditions_key'],
            }
            for ep, res in calibration_results.items()
        },
        'sensitivity_ep3': {
            str(n): ic for n, ic in sensitivity.items()
        },
    }

    with open(RESULTS_JSON, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\n{Fore.GREEN}Resultaten opgeslagen: {RESULTS_JSON}{Style.RESET_ALL}")


# =============================================================================
#  MAIN
# =============================================================================

def main():
    print(f"{Style.BRIGHT}HESTIA intercept_estimation.py (rev13){Style.RESET_ALL}")
    print(f"Newton calibration of collapse-risk intercepts")
    print(f"N={N_POPULATION:,}, seed={RANDOM_SEED}\n")

    # ------------------------------------------------------------------ #
    #  1. Import engine                                                    #
    # ------------------------------------------------------------------ #
    engine = _import_engine()

    # ------------------------------------------------------------------ #
    #  2-4. Build weather, population, and run the simulation ONCE per     #
    #        DISTINCT reference-conditions key actually needed by the      #
    #        endpoints below -- not once globally. [2026-07, restructured] #
    #        This is the generalizable fix: endpoints whose target came    #
    #        from the same real event correctly share one simulation       #
    #        (e.g. hospitalisation + ehbo, both DtD 2024); endpoints from   #
    #        different events never do (ehs no longer borrows DtD's        #
    #        conditions or vice versa). Adding a future calibration point   #
    #        just means adding one more REF_CONDITIONS_* block and an      #
    #        ENDPOINTS entry naming it via ref_conditions_key -- this loop  #
    #        picks it up automatically.                                    #
    # ------------------------------------------------------------------ #
    needed_keys = sorted(set(ep['ref_conditions_key'] for ep in ENDPOINTS.values()))
    print(f"Distinct reference-conditions scenarios needed: {needed_keys}\n")

    sim_outs  = {}
    sim_metas = {}
    for ref_key in needed_keys:
        cfg = REF_CONDITIONS_BY_KEY[ref_key]
        print(f"{'='*72}")
        print(f"Reference scenario '{ref_key}': {cfg['duration_h']}h, "
              f"{cfg['tdb_start']}->{cfg['tdb_end']}degC, MET={cfg['met_value']}")
        print(f"{'='*72}")

        interp_data = build_reference_interp(cfg)
        population  = get_population(engine, ref_key, cfg)
        n_pop       = len(population)

        sim_out = run_calibration_simulation(engine, population, interp_data, cfg)
        sim_metas[ref_key] = {
            'n_population': n_pop,
            'random_seed' : RANDOM_SEED,
            'elapsed_s'   : sim_out.pop('elapsed_s'),
        }
        sim_out.pop('stats', None)   # not needed for Newton, don't serialise
        sim_outs[ref_key] = sim_out

    # ------------------------------------------------------------------ #
    #  5. Newton iteration for all endpoints, each against its OWN         #
    #     matched sim_out                                                  #
    # ------------------------------------------------------------------ #
    calibration_results = {}
    for ep_key, ep_cfg in ENDPOINTS.items():
        ref_key = ep_cfg['ref_conditions_key']
        res = calibrate_intercept(
            sim_out  = sim_outs[ref_key],
            p_target = ep_cfg['p_target'],
            label    = f"{ep_cfg['label']} [ref: {ref_key}]",
        )
        calibration_results[ep_key] = res

    # ------------------------------------------------------------------ #
    #  6. Sensitivity analysis EP3 (ehbo) -- against ehbo's own ref_out     #
    # ------------------------------------------------------------------ #
    sensitivity = sensitivity_analysis_ehbo(sim_outs[ENDPOINTS['ehbo']['ref_conditions_key']])

    # ------------------------------------------------------------------ #
    #  7. Optional: bootstrap CI on EP1 (ehs) -- against ehs's own ref_out #
    # ------------------------------------------------------------------ #
    run_boot = input("\nCompute a bootstrap 95% CI for EP1? "
                     "(takes ~2-5 extra min, y/n, default=n): ").strip().lower()
    if run_boot in ('y', 'yes'):
        ci_lo, ci_hi = bootstrap_ci(
            sim_out        = sim_outs[ENDPOINTS['ehs']['ref_conditions_key']],
            p_target       = ENDPOINTS['ehs']['p_target'],
            intercept_cal  = calibration_results['ehs']['intercept'],
            n_boot         = 500,
        )
        calibration_results['ehs']['ci_95_lower'] = ci_lo
        calibration_results['ehs']['ci_95_upper'] = ci_hi

    # ------------------------------------------------------------------ #
    #  8. Report and JSON save                                              #
    # ------------------------------------------------------------------ #
    # Use the largest sim_meta (by n_population) as the headline "N/seed"
    # in the printed report header -- they're identical (same N_POPULATION,
    # same RANDOM_SEED) across ref_keys anyway, this just picks one.
    headline_meta = next(iter(sim_metas.values()))
    print_final_report(calibration_results, sensitivity, headline_meta)
    save_results_json(calibration_results, sensitivity, sim_metas, sim_outs)

    print(f"\n{Fore.GREEN}Calibration complete.{Style.RESET_ALL}")
    print(f"Paste the COLLAPSE_ENDPOINTS block (see above) into "
          f"hestia_model.py and change the status from "
          f"REQUIRES_RECALIBRATION to VALIDATED (EP1) / PROVISIONAL (EP2, EP3).")


if __name__ == '__main__':
    main()
