# -*- coding: utf-8 -*-
"""
klimatos_ehs_worker.py
=======================
Picklable worker for the EHS-evolution module of Klimatos.ClimateShift.

Kept as its own module, importing NOTHING from Klimatos_ClimateShift, for two
reasons:

 1. ProcessPoolExecutor re-imports the module a worker function lives in. If
    that were Klimatos_ClimateShift, every worker would drag in matplotlib,
    pvlib and the whole plotting layer -- and it would be a circular import,
    since Klimatos_ClimateShift is what dispatches these tasks.
 2. It keeps the expensive-but-narrow part (the HESTIA physiology call) cleanly
    separable, so the weather shifting and re-processing stay in the parent
    process where the Klimatos pipeline already lives.

Consequently the parent hands over weather that is ALREADY shifted and ALREADY
run through the Klimatos thermal pipeline; this module only evaluates it.
"""

from __future__ import annotations

import contextlib
import io
import random

import numpy as np
import pandas as pd

# How many (T_rect, CO_reserve) pairs a single day-realisation may contribute
# to the scatter-plot data. Every participant contributes one pair per
# timestep, so a full population/race easily produces tens of thousands of
# points per call -- fine for the risk calculations, far more than a scatter
# plot needs and needlessly expensive to pickle back through the process
# pool. Subsampled here, once, close to the source, rather than in the
# parent after collecting everything.
SCATTER_PAIRS_PER_DAY_CAP = 150


def evaluate_scenario_day(weather_df: pd.DataFrame, lat: float, lon: float, tz: str,
                          event_date: pd.Timestamp, start_hour: int, start_minute: int,
                          duration_minutes: float, met_value: float, clo_value: float,
                          n_simulations: int, random_seed: int,
                          collapse_endpoint: str | None = None) -> dict | None:
    """Run one day-realisation through the HESTIA population ensemble.

    hestia_bridge is imported lazily, inside the call, so that merely importing
    this module (which the parent does) does not pull in the whole HESTIA stack
    -- and so a missing HESTIA install fails here, where it can be reported per
    task, rather than at import time of the whole script.
    """
    from hestia_bridge import run_quick_estimate
    import hestia_bridge as _hb

    # CRITICAL: disable HESTIA's own internal parallelism inside this worker.
    #
    # We are already parallel at the year-task level (one ProcessPoolExecutor
    # worker per task). hestia_bridge passes use_parallel=(_capped_workers() > 1)
    # down to hestia_model, which then opens a pool sized by
    # multiprocessing.cpu_count() -- NOT by hestia_bridge.MAX_WORKERS. So on an
    # 8-core machine with 4 outer workers that is 4 x 8 = 32 processes competing
    # for 8 cores, per task.
    #
    # On Linux/fork that is merely wasteful. On Windows/spawn it is severe: every
    # nested process re-imports the entire stack (numpy, pandas, pvlib,
    # pythermalcomfort, streamlit, matplotlib) before doing any work, repeated
    # for every task -- observed at ~35x slower than the serial-inner estimate,
    # and prone to stalling near the end of a run as processes contend.
    #
    # Setting MAX_WORKERS = 1 makes _capped_workers() return 1, so
    # use_parallel becomes False and no nested pool is created at all. The outer
    # pool keeps all cores busy; the inner one only ever got in its way.
    #
    # This is set per worker process (module state is not shared across
    # processes) and deliberately not restored: the worker exists only to run
    # these tasks.
    _hb.MAX_WORKERS = 1

    # Select which COLLAPSE_ENDPOINTS entry the calibrated collapse-risk model
    # uses. Passed through as an explicit run_quick_estimate parameter (not
    # set directly as a bare hestia_model global) so hestia_bridge's own
    # caching keys on it correctly -- see run_quick_estimate's docstring for
    # why a global mutated outside the cached function is invisible to it and
    # was confirmed, by direct test, to silently return a stale endpoint's
    # cached result otherwise.

    start_naive = pd.Timestamp(year=event_date.year, month=event_date.month,
                               day=event_date.day, hour=start_hour, minute=start_minute)
    try:
        start = start_naive.tz_localize(tz, nonexistent="shift_forward", ambiguous=True)
    except Exception:
        return None
    finish = start + pd.Timedelta(minutes=duration_minutes)
    if start < weather_df.index.min() or finish > weather_df.index.max():
        return None

    # run_quick_estimate is chatty (tqdm bars, population notes). In a worker
    # that output interleaves unreadably with the parent's progress line, so it
    # is captured and dropped rather than printed.
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            return run_quick_estimate(
                weather_df, lat, lon, tz, start, finish,
                met_value=met_value, clo_value=clo_value,
                n_simulations=n_simulations, random_seed=random_seed,
                active_endpoint=collapse_endpoint,
            )
    except Exception:
        return None


def evaluate_scenario_year(task: dict) -> dict:
    """Evaluate every offset-day of one (scenario, historical year) pair.

    One task per year rather than per day: the weather DataFrame is pickled once
    per year instead of once per day, which dominates the inter-process cost.

    `task` carries: weather_df (already shifted + processed), lat, lon, tz,
    year, month, day, offsets, start_hour, start_minute, duration_minutes,
    met_value, clo_value, n_simulations, label, and optionally
    collapse_endpoint (str) and collect_scatter (bool).
    """
    ehs_vals: list[float] = []
    ehe_vals: list[float] = []
    clinical_vals: list[float] = []
    collapse_vals: list[float] = []
    scatter_pairs: list[tuple[float, float]] = []
    n_failed = 0
    collapse_endpoint = task.get("collapse_endpoint")
    collect_scatter = task.get("collect_scatter", False)
    rng = random.Random(task.get("year", 0))

    for off in task["offsets"]:
        try:
            centre = pd.Timestamp(year=task["year"], month=task["month"], day=task["day"])
        except ValueError:
            centre = pd.Timestamp(year=task["year"], month=2, day=28)
        day = centre + pd.Timedelta(days=off)
        res = evaluate_scenario_day(
            task["weather_df"], task["lat"], task["lon"], task["tz"], day,
            task["start_hour"], task["start_minute"], task["duration_minutes"],
            task["met_value"], task["clo_value"], task["n_simulations"],
            random_seed=42 + off, collapse_endpoint=collapse_endpoint,
        )
        if res is None:
            n_failed += 1
            continue
        ehs = res.get("falmouth_ehs_per_1000", np.nan)
        if np.isfinite(ehs):
            ehs_vals.append(float(ehs))
        ehe = res.get("pct_true_ehe_criterion", np.nan)
        if np.isfinite(ehe):
            ehe_vals.append(float(ehe))
        # hestia_bridge.py's own field name for this is "pct_true_ehs_criterion"
        # -- confusingly reusing "EHS", though it has nothing to do with the
        # Falmouth-calibrated falmouth_ehs_per_1000 reported as EHS
        # everywhere else. Kept as "clinical" here (T_rect>=40.5 AND
        # CO_reserve<=0, the stricter of the two mechanistic criteria) to
        # avoid perpetuating that collision in Klimatos' own output.
        clinical = res.get("pct_true_ehs_criterion", np.nan)
        if np.isfinite(clinical):
            clinical_vals.append(float(clinical))
        collapse = res.get("expected_collapses_per_1000", np.nan)
        if np.isfinite(collapse):
            collapse_vals.append(float(collapse))
        if collect_scatter:
            pairs = res.get("t_rect_co_reserve_pairs") or []
            if len(pairs) > SCATTER_PAIRS_PER_DAY_CAP:
                pairs = rng.sample(pairs, SCATTER_PAIRS_PER_DAY_CAP)
            scatter_pairs.extend(pairs)

    return {
        "label": task["label"],
        "year": task["year"],
        "ehs_per_1000": ehs_vals,
        "ehe_pct": ehe_vals,
        "clinical_pct": clinical_vals,
        "collapse_per_1000": collapse_vals,
        "scatter_pairs": scatter_pairs,
        "n_failed": n_failed,
    }
