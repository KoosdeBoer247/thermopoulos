# -*- coding: utf-8 -*-
"""
HESTIA plots
================================================================================
Plotting for the HESTIA half of the suite, in the same spirit as
pyrox_plots.py: functions return a matplotlib Figure, callers save it with
`.savefig()`. Reuses hestia_model.py's own plotting functions where they
already do the job (they are unchanged, imported as-is), and adds the plots
that were missing: CVR-specific population distributions, the conjunctive
risk scatter (T_rect x CO_reserve -- the actual decision boundary the CVR
model is built around), and a single-participant time series for individual
runs (hestia_model.py's own plot functions are Monte-Carlo-shaped and don't
cover the single-run case).

Usage (programmatic, from run_hestia.py):
    from hestia_plots import generate_population_plots, generate_individual_plots
    generate_population_plots(all_results, results_df, stats, city, start_time, duration_hours)
    generate_individual_plots(results, city, start_time)

Usage (standalone menu):
    python hestia_plots.py
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

import hestia_model as hestia


# ============================================================================
# reused directly from hestia_model.py (not reimplemented)
# ============================================================================
# hestia.plot_adult_results(all_results, stats, city_name, start_time, duration_hours)
#   -> 4-panel: T_rect (with P97.5/P99 + vulnerable-tail overlay), RPE,
#      environmental UTCI/WBGT, % participants at risk over time.
# hestia.plot_adult_boxplots(results_df)
#   -> max_t_rect / max_rpe / max_water_loss_perc by age_group x gender.
# Both now return their Figure explicitly (a small additive fix to
# hestia_model.py -- they used to end in plt.show(block=False) with no
# return, and grabbing plt.gcf() right after was unreliable on backends
# where show() invalidates/clears the "current figure", e.g. some Spyder
# inline-plotting configurations, producing blank saved PNGs).


# ============================================================================
# new: CVR-specific population plots
# ============================================================================

def plot_co_reserve_distribution(results_df: pd.DataFrame, title: str) -> plt.Figure:
    """Histogram of each participant's minimum CO_reserve (cardiac output
    reserve). Below 2.0 L/min is the decompensation-risk zone used elsewhere
    in the suite's console reporting; below 0 is the conjunctive trigger's
    CO_reserve condition.
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    vals = results_df['cvr_co_reserve_min'].dropna()
    ax.hist(vals, bins=30, color='steelblue', alpha=0.75, edgecolor='white')
    ax.axvline(2.0, color='darkorange', linestyle='--', linewidth=2,
               label='Decompensation risk threshold (2.0 L/min)')
    ax.axvline(0.0, color='red', linestyle='-', linewidth=2,
               label='CO_reserve = 0 (conjunctive trigger)')
    ax.set_xlabel("Minimum CO_reserve (L/min)")
    ax.set_ylabel("Number of participants")
    ax.set_title(f"CO_reserve distribution — {title}")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_collapse_risk_distribution(stats: Dict, title: str) -> Optional[plt.Figure]:
    """Histogram of per-participant collapse probability (two-phase logistic
    model, calibrated intercept). Uses `stats['p_collapse_per_sim']`, which
    the model computes but does not otherwise expose outside the aggregate
    percentiles printed to console.
    """
    if 'p_collapse_per_sim' not in stats:
        return None
    p = np.asarray(stats['p_collapse_per_sim']) * 100
    if not np.any(np.isfinite(p)):
        # [fix 2026-09] Mild/short scenarios can leave every participant's
        # per-sim collapse probability NaN (same root cause as the
        # dehydration-percentile NaN already handled in
        # HESTIA_CVR_Console.py's _bar() -- an empty/all-NaN slice
        # upstream in hestia_model.py, not a defect). matplotlib's hist()
        # cannot autodetect a range from an all-NaN array and raises
        # ValueError instead of drawing an empty plot; skip this plot
        # entirely here, same as the already-existing missing-key case
        # just above.
        return None
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(p, bins=30, color='firebrick', alpha=0.75, edgecolor='white')
    ax.axvline(np.nanmean(p), color='black', linestyle='-', linewidth=2,
               label=f"Mean: {np.nanmean(p):.2f}%")
    ax.axvline(np.nanpercentile(p, 95), color='darkorange', linestyle='--', linewidth=2,
               label=f"P95: {np.nanpercentile(p, 95):.2f}%")
    ax.set_xlabel("Individual collapse probability (%)")
    ax.set_ylabel("Number of participants")
    ep_label = stats.get('active_endpoint_label', '')
    ax.set_title(f"Collapse-risk distribution — {title}\n"
                 f"(intercept_kal={stats.get('collapse_intercept_kal', float('nan')):.3f}"
                 + (f", {ep_label}" if ep_label else "") + ")")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_conjunctive_risk_scatter(results_df: pd.DataFrame, title: str) -> plt.Figure:
    """Scatter of peak T_rect vs. minimum CO_reserve per participant, coloured
    by collapse probability -- a direct visualisation of the conjunctive
    triggers the CVR module is built around: EHE (T_rect > 39.5 AND
    CO_reserve <= 0, mechanistic, uncalibrated) and the stricter clinical
    criterion (T_rect > 40.5 AND CO_reserve <= 0), not just the marginal
    distributions separately.

    [2026-09] The shaded zones (position) and the colour (collapse
    probability) answer two different questions -- "did this participant
    cross a threshold at all" (binary) vs. "how far past it, and how
    severe is that judged by the calibrated risk model" (continuous,
    graded) -- so a participant can sit just inside a zone yet still show
    up green. Real, observed case: three participants all inside the
    clinical zone showed 0.5%, 8.3% and 55.8% collapse probability
    respectively, because the underlying risk score weighs T_rect over
    the CLINICAL 40.5 degC line four times as heavily as T_rect over the
    EHE 39.5 degC line -- a participant only marginally past a threshold
    barely engages that term, while one well past it does.

    [2026-09, follow-up] The EHE threshold (39.5 degC) feeds that same
    weighted score (see the explanatory table below) but, in the first
    version of this fix, was invisible on the chart itself -- only the
    stricter clinical line/zone (40.5 degC) was drawn, so there was no way
    to see where EHE-only participants (past 39.5 but not 40.5) actually
    sit. Added a second threshold line and a separate, lighter-shaded EHE
    zone alongside the existing clinical one.
    """
    # [2026-09] Height increased 9.6 -> 12.5 in: the medical_text box below
    # grew by 8 lines (causal EHS/CO_reserve explanation + >42 degC
    # thermal-only pathway) and would otherwise overlap the weight_text
    # box beneath it. Verified by direct render (no overlap at 12.5in,
    # confirmed against 9.6in which did overlap).
    fig, ax = plt.subplots(figsize=(10, 12.5))
    c = results_df.get('cvr_p_collapse_pct', pd.Series(np.zeros(len(results_df))))
    sc = ax.scatter(results_df['cvr_co_reserve_min'], results_df['max_t_rect'],
                     c=c, cmap='RdYlGn_r', s=60, alpha=0.85, edgecolor='black', linewidth=0.4,
                     zorder=3)
    ax.axvline(0.0, color='red', linestyle='-', linewidth=1.5, alpha=0.7, zorder=2)
    ax.axhline(40.5, color='red', linestyle='-', linewidth=1.5, alpha=0.7, zorder=2,
               label='Klinische drempel (40,5°C)')
    ax.axhline(39.5, color='darkorange', linestyle='--', linewidth=1.5, alpha=0.8, zorder=2,
               label='EHE-drempel (39,5°C)')
    y_top = ax.get_ylim()[1] if ax.get_ylim()[1] > 40.5 else 43
    ax.axhspan(40.5, y_top, xmin=0, xmax=0.5, color='red', alpha=0.08, zorder=1,
               label='Klinische zone')
    ax.axhspan(39.5, 40.5, xmin=0, xmax=0.5, color='darkorange', alpha=0.08, zorder=1,
               label='EHE-zone (niet ook klinisch)')
    ax.legend(loc='lower right', fontsize=9, framealpha=0.9)
    ax.set_xlabel("Minimum CO_reserve (L/min)")
    ax.set_ylabel("Peak T_rect (°C)")
    ax.set_title(f"Conjunctive risk zones — {title}\n"
                 f"EHE: T_rect > 39,5°C EN CO_reserve ≤ 0  --  "
                 f"Klinisch: T_rect > 40,5°C EN CO_reserve ≤ 0")
    cbar = fig.colorbar(sc, ax=ax)
    cbar.set_label("Individual collapse probability (%)")
    ax.grid(True, alpha=0.3)

    # Two explanatory boxes, stacked vertically and fixed in figure-fraction
    # coordinates (not data coordinates), so they land in the same safe
    # spot below the plot regardless of where any given run's own data
    # happens to fall: top = what EHE/EHS mean medically and why they
    # matter, bottom = how the weighted collapse-probability score works.
    # Every line below is manually broken short enough to fit a 10-inch
    # canvas at this font size -- fig.text()'s own wrap=True was tried and
    # rejected: it does not reliably wrap long lines in practice, letting
    # text run past the canvas edge instead (confirmed by direct visual
    # check), so every line here is deliberately kept short instead of
    # relying on it.
    fig.subplots_adjust(bottom=0.58)
    medical_text = (
        "Wat betekenen deze twee criteria medisch?\n"
        "\n"
        "EHE (hitte-uitputting): vermoeidheid, duizeligheid, misselijkheid\n"
        "door cardiovasculaire overbelasting -- bewustzijn blijft helder.\n"
        "Reageert meestal goed op rust, koeling en vocht; zelden blijvende\n"
        "schade bij tijdige herkenning.\n"
        "\n"
        "EHS / 'klinisch criterium' (hitteberoerte): kerntemperatuur >40,5°C\n"
        "MÉT verstoord bewustzijn (verwardheid, coördinatieverlies,\n"
        "black-out) -- een medisch spoedgeval. Onbehandeld risico op\n"
        "orgaanschade en overlijden. Snelheid van koelen (bij voorkeur\n"
        "ijswaterbad, vóór vervoer) is bepalend voor de uitkomst.\n"
        "\n"
        "Het model toetst niet direct bewustzijn: CO_reserve≤0 is een\n"
        "oorzakelijke schakel via cerebrale onderperfusie bij falende\n"
        "cardiac output (Starling's-Law-cascade; Périard et al. 2021).\n"
        "Boven ~42°C kan T_rect zelf, los van CO_reserve, ook direct\n"
        "hersenweefsel beschadigen (Hubbard: kritieke grens 41,6-42,0°C;\n"
        "Gähwiler 1972: onomkeerbare neuronale schade vanaf 42-43°C).\n"
        "Dit conjunctieve criterium dekt vooral het cardiovasculaire pad;\n"
        "zie pct_thermal_only_critical voor het thermische pad apart.\n"
        "\n"
        "(Hier 'klinisch criterium' genoemd i.p.v. 'EHS', om verwarring te\n"
        "voorkomen met de aparte Falmouth-EHS-schatting elders in de suite\n"
        "-- medisch is dit wél de EHS-definitie.)"
    )
    fig.text(0.5, 0.565, medical_text, ha='center', va='top', fontsize=8.5,
             linespacing=1.5,
             bbox=dict(boxstyle='round,pad=0.5', facecolor='#FFF7ED', edgecolor='#C97A2B'))

    weight_text = (
        "Waarom een groen punt tóch in de oranje of rode zone kan liggen\n"
        "De zones (positie) zijn JA/NEE-grenzen: wel of niet overschreden.\n"
        "De kleur is een GEWOGEN risicoscore -- hoe ver overschreden weegt mee, niet alleen óf.\n"
        "\n"
        "Onderdeel van de score            Gewicht   Betekenis\n"
        "T_rect boven 39,5 degC (EHE)        x 1,0   per graad erboven\n"
        "T_rect boven 40,5 degC (klinisch)    x 4,0   per graad erboven -- zwaarst gewogen\n"
        "CO_reserve onder 2,0 L/min           x 0,8   per L/min tekort\n"
        "Dehydratie boven 3%                  x 0,5   per % erboven\n"
        "\n"
        "Een lichte overschrijding (bv. 40,6 degC) draagt weinig bij aan deze score --\n"
        "vandaar een lage (groene) kans, ook al ligt het punt binnen een zone."
    )
    fig.text(0.5, 0.01, weight_text, ha='center', va='bottom', fontsize=8.5,
             family='monospace', linespacing=1.5,
             bbox=dict(boxstyle='round,pad=0.5', facecolor='#F7F7FA', edgecolor='#999999'))
    return fig


def plot_age_vs_collapse_risk(results_df: pd.DataFrame, title: str) -> plt.Figure:
    """Collapse probability by age, split by gender -- shows whether risk is
    concentrated in specific age bands rather than spread uniformly.
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    for gender, color in [("male", "steelblue"), ("female", "salmon")]:
        sub = results_df[results_df['gender'] == gender]
        ax.scatter(sub['age'], sub.get('cvr_p_collapse_pct', 0), color=color,
                   alpha=0.7, label=gender.capitalize(), s=50, edgecolor='black', linewidth=0.3)
    ax.set_xlabel("Age (years)")
    ax.set_ylabel("Individual collapse probability (%)")
    ax.set_title(f"Collapse risk by age — {title}")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


# ============================================================================
# new: single-participant time series (individual-run mode)
# ============================================================================

def _combined_series_with_postfinish(sim: List[Dict], value_key: str):
    """Race-time series + post-finish series for one field, on one time axis.
    Reused by both the extreme-cohort plot and the conjunctive-criterion plot
    so the two stay consistent."""
    race_times = [pd.to_datetime(r["time"]) for r in sim]
    race_vals = [r.get(value_key) for r in sim]
    last = sim[-1]
    times, vals = list(race_times), list(race_vals)
    if value_key == "co_reserve" and "co_reserve_series_postfinish" in last:
        for t_min, v in zip(last["time_min_series_postfinish"][1:],
                           last["co_reserve_series_postfinish"][1:]):
            times.append(race_times[-1] + pd.Timedelta(minutes=t_min))
            vals.append(v)
    elif value_key == "t_rect" and "t_rect_series_postfinish" in last:
        for t_min, v in zip(last["time_min_series_postfinish"][1:],
                           last["t_rect_series_postfinish"][1:]):
            times.append(race_times[-1] + pd.Timedelta(minutes=t_min))
            vals.append(v)
    return times, vals


def _conjunctive_series(times: List, t_rect_vals: List[float], co_reserve_vals: List[float]):
    """Instantaneous TCF integrand and cumulative dose over an arbitrary time
    axis, using hestia_model's own control_failure_increment() (the same
    function that computes the official `control_failure_dose_total` field),
    not a re-implementation -- so this always matches the official dose."""
    from HESTIA_ControlFailure_Module import thermal_excess, co_deficit, DEFAULT_CONFIG
    rate, cumulative = [0.0], [0.0]
    dose = 0.0
    for i in range(1, len(times)):
        dt_min = (times[i] - times[i - 1]).total_seconds() / 60.0
        t_rect = t_rect_vals[i]
        co_res = co_reserve_vals[i]
        r = thermal_excess(t_rect, DEFAULT_CONFIG) * co_deficit(co_res, DEFAULT_CONFIG) \
            if (t_rect is not None and co_res is not None) else 0.0
        rate.append(r)
        dose += r * max(0.0, dt_min)
        cumulative.append(dose)
    return rate, cumulative


def plot_conjunctive_criterion_individual(results: List[Dict], title: str) -> plt.Figure:
    """Conjunctive criterion (T_rect > 40.5 AND CO_reserve <= 0) shown as a
    time course for one participant: the instantaneous TCF "rate"
    (max(0, T_rect-40.5) x max(0, -CO_reserve)) and its running time
    integral -- the control-failure dose building up over the race and the
    10-minute post-finish window. Uses the same official formula as
    `control_failure_dose_total` (via HESTIA_ControlFailure_Module), not the
    raw T_rect x CO_reserve product (which isn't physically meaningful: T_rect
    in Celsius has an arbitrary zero point, so a direct product isn't
    interpretable, and would give a different number in Fahrenheit).
    """
    times, t_rect_vals = _combined_series_with_postfinish(results, "t_rect")
    _, co_reserve_vals = _combined_series_with_postfinish(results, "co_reserve")
    rate, cumulative = _conjunctive_series(times, t_rect_vals, co_reserve_vals)
    race_end = pd.to_datetime(results[-1]["time"])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9), gridspec_kw={'hspace': 0.35})
    fig.suptitle(f"Conjunctive criterion time course — {title}", fontsize=14, weight='bold')

    ax1.plot(times, rate, color='darkred', linewidth=2)
    ax1.fill_between(times, 0, rate, color='darkred', alpha=0.15)
    ax1.axvline(race_end, color='black', linestyle='--', linewidth=1.2, label='Race end / finish')
    ax1.set_title("Instantaneous rate: max(0, T_rect-40.5) × max(0, -CO_reserve)")
    ax1.set_ylabel("°C · L/min")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    ax2.plot(times, cumulative, color='black', linewidth=2.2)
    ax2.fill_between(times, 0, cumulative, color='firebrick', alpha=0.15)
    ax2.axvline(race_end, color='black', linestyle='--', linewidth=1.2, label='Race end / finish')
    ax2.set_title(f"Cumulative dose (time integral) -- final: {cumulative[-1]:.3f} °C·L")
    ax2.set_ylabel("°C · L (cumulative)")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    for ax in (ax1, ax2):
        ax.set_xlabel("Time")
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.tick_params(axis='x', rotation=45)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig


def _count_violation_episodes(mask_1d: np.ndarray):
    """Number of separate contiguous True-runs, and their total count, in a
    boolean 1-D array. A simple diff-based run-length count: episodes are
    places a False->True transition occurs (plus one if the series starts
    True). Used to turn a conjunctive-criterion rate series into an
    'N episodes' figure -- a runner can cross out of and back into the
    violated state more than once over a race, so a single peak/cumulative
    number does not by itself say how many separate times it happened."""
    if mask_1d.size == 0:
        return 0, 0
    starts = np.flatnonzero(np.diff(np.concatenate(([0], mask_1d.astype(int)))) == 1)
    return len(starts), int(np.sum(mask_1d))


def plot_conjunctive_dose_extreme_cohorts(all_results: List[List[Dict]], results_df: pd.DataFrame,
                                          title: str, n: int = 10) -> plt.Figure:
    """Cumulative conjunctive-criterion dose (time integral) over the race +
    post-finish window, for the same two extreme cohorts as
    plot_extreme_cohorts_timeseries: the n participants with the highest peak
    T_rect, and the n with the lowest minimum CO_reserve. Directly answers
    "which of these already-flagged individuals actually accumulate
    meaningful conjunctive risk over time, and when".

    Each legend entry also reports how many separate episodes the runner's
    OWN conjunctive criterion (T_rect > t_rect_crit AND CO_reserve <=
    co_reserve_limit -- see HESTIA_ControlFailure_Module's ControlFailureConfig,
    currently 40.5 degC / 0 L/min) was actually met, and the total time spent
    in that state -- a runner can cross out of and back into it more than
    once, which a single cumulative-dose number does not by itself convey.
    Reuses the `rate` series _conjunctive_series() already computes (nonzero
    exactly when both conditions hold simultaneously) rather than
    recomputing the condition separately, so this can never drift from the
    officially reported dose it is annotating."""
    top_t_rect = results_df.nlargest(n, 'max_t_rect')
    bottom_co_reserve = results_df.nsmallest(n, 'cvr_co_reserve_min') \
        if 'cvr_co_reserve_min' in results_df.columns else results_df.iloc[0:0]
    cohort = pd.concat([top_t_rect, bottom_co_reserve]).drop_duplicates(subset='participant_id')

    fig, ax = plt.subplots(figsize=(13, 7))
    race_end = None
    cmap = plt.get_cmap('plasma')
    n_lines = max(1, len(cohort) - 1)
    for rank, (_, row) in enumerate(cohort.iterrows()):
        idx = int(row['participant_id']) - 1
        sim = all_results[idx]
        times, t_rect_vals = _combined_series_with_postfinish(sim, "t_rect")
        _, co_reserve_vals = _combined_series_with_postfinish(sim, "co_reserve")
        rate, cumulative = _conjunctive_series(times, t_rect_vals, co_reserve_vals)
        if race_end is None:
            race_end = pd.to_datetime(sim[-1]["time"])
        n_episodes, n_steps = _count_violation_episodes(np.asarray(rate) > 0.0)
        if n_steps > 0 and len(times) > 1:
            # Mean step width in minutes -- times are not always uniformly
            # spaced once the post-finish window is appended, so this is an
            # average rather than a fixed step size.
            total_span_min = (times[-1] - times[0]).total_seconds() / 60.0
            step_min = total_span_min / max(1, len(times) - 1)
            dur_min = n_steps * step_min
            episode_note = f" -- {n_episodes} episode(s), {dur_min:.0f} min"
        else:
            episode_note = " -- no episode"
        ax.plot(times, cumulative, color=cmap(rank / n_lines), linewidth=1.6, alpha=0.85,
               label=f"#{int(row['participant_id'])} ({row['age']}y {row['gender']})"
                     f"{episode_note}")

    if race_end is not None:
        ax.axvline(race_end, color='black', linestyle='--', linewidth=1.5, label='Race end / finish')
    ax.set_title(f"Conjunctive-criterion cumulative dose — {title}\n"
                f"(top {n} by peak T_rect + bottom {n} by min CO_reserve)")
    ax.set_xlabel("Time")
    ax.set_ylabel("Cumulative dose (°C · L)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.tick_params(axis='x', rotation=45)
    ax.legend(fontsize=7, ncol=2, loc='upper left')
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_auc_klinisch_extreme_cohorts(all_results: List[List[Dict]], results_df: pd.DataFrame,
                                      title: str, n: int = 10) -> plt.Figure:
    """Cumulative AUC_klinisch (Roberts 2007 clinical dose, T_rect > 40.5°C
    integrated over time) for the n participants with the highest final
    AUC_klinisch. Same visual pattern as plot_conjunctive_dose_extreme_cohorts
    (cumulative-dose-over-time, one line per participant), but for AUC rather
    than the conjunctive TCF dose, and with a single-criterion cohort (AUC
    only depends on T_rect, not CO_reserve, so no second cohort is needed).

    Shows the race-time build-up as a line (auc_klinisch is tracked per
    timestep during the race); the post-finish contribution is NOT broken
    down per-minute in the underlying data (only a final total exists), so
    it is shown as a single marker at the final auc_klinisch_totaal value
    rather than an invented intermediate curve.
    """
    cohort = results_df.nlargest(n, 'auc_klinisch_totaal') \
        if 'auc_klinisch_totaal' in results_df.columns \
        else results_df.nlargest(n, 'auc_thermisch_deg_min')

    fig, ax = plt.subplots(figsize=(13, 7))
    race_end = None
    cmap = plt.get_cmap('viridis')
    n_lines = max(1, len(cohort) - 1)
    for rank, (_, row) in enumerate(cohort.iterrows()):
        idx = int(row['participant_id']) - 1
        sim = all_results[idx]
        times = [pd.to_datetime(r["time"]) for r in sim]
        auc_kl_race = [r.get("auc_klinisch", 0.0) for r in sim]
        if race_end is None:
            race_end = times[-1]
        color = cmap(rank / n_lines)
        label = f"#{int(row['participant_id'])} ({row['age']}y {row['gender']})"
        ax.plot(times, auc_kl_race, color=color, linewidth=1.6, alpha=0.85, label=label)
        total = row.get('auc_klinisch_totaal', auc_kl_race[-1])
        if total is not None and total > auc_kl_race[-1] + 1e-6:
            # Post-finish adds further dose, but without an intermediate
            # time series -- show that explicitly as a standalone endpoint,
            # not a fabricated curve in between.
            post_finish_time = times[-1] + pd.Timedelta(minutes=10)
            ax.plot([times[-1], post_finish_time], [auc_kl_race[-1], total],
                   color=color, linewidth=1.6, alpha=0.85, linestyle=':')
            ax.scatter([post_finish_time], [total], color=color, s=25, zorder=5)

    if race_end is not None:
        ax.axvline(race_end, color='black', linestyle='--', linewidth=1.5, label='Race end / finish')
    ax.axhline(60, color='red', linestyle='--', linewidth=1.3,
              label='Roberts clinical threshold (60 degC*min)')
    ax.set_title(f"AUC_klinisch cumulative dose — {title}\n"
                f"(top {n} by final AUC_klinisch; dotted line/dot = post-finish total, no interim series)")
    ax.set_xlabel("Time")
    ax.set_ylabel("AUC_klinisch (°C · min)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.tick_params(axis='x', rotation=45)
    ax.legend(fontsize=7, ncol=2, loc='upper left')
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_co_deficit_dose_extreme_cohorts(all_results: List[List[Dict]],
                                         title: str, n: int = 10,
                                         co_ref: float = 2.0) -> plt.Figure:
    """Cumulative CO_reserve-deficit dose over time:
        dose(t) = integral_0^t max(0, co_ref - CO_reserve(s)) ds   [L/min * min]

    Deliberately NOT coupled to T_rect -- this isolates the cardiovascular
    pathway on its own (Rowell's competing-demands framework: muscle blood
    flow demand alone can exhaust cardiac reserve in cardiac-limited
    individuals before thermoregulatory demand becomes significant;
    Gonzalez-Alonso 2008, J Physiol, doi:10.1113/jphysiol.2007.142158). This
    is the counterpart to the existing T_rect-driven AUC plots and the
    conjunctive TCF dose -- together the three give T-only, CO-only, and
    T-AND-CO-together views of accumulating strain.

    Unlike auc_klinisch/auc_thermisch, this dose is not tracked as a running
    sum inside the simulation loop -- it's computed here directly from the
    already-stored per-timestep co_reserve series (CO_reserve is filled in
    post-loop by the CVR module, see hestia_model.calculate_indices_jos3_
    adult), so no change to the core simulation was needed for this plot.

    [not yet clinically calibrated] Like TCF, this dose has no established
    numeric action threshold in the literature -- there is nothing published
    saying "X L*min is dangerous" for this specific, new quantity. Following
    the same approach already used for auc_thermisch, this plot shows the
    population's own P95 AND P99 (this run) as relative reference lines
    rather than a borrowed or invented absolute cutoff. Revisit once hindcast
    data against known outcomes is available (same open item as TCF itself,
    per HESTIA's own console note: "not a clinical EHS diagnosis; calibrate
    against event medical data before converting to EHS probability").
    """
    def _cum_co_deficit_series(sim):
        times = [pd.to_datetime(r["time"]) for r in sim]
        co_vals = [r.get("co_reserve", float('nan')) for r in sim]
        dose = [0.0]
        for i in range(1, len(times)):
            dt_min = (times[i] - times[i - 1]).total_seconds() / 60.0
            deficit = max(0.0, co_ref - co_vals[i]) if not pd.isna(co_vals[i]) else 0.0
            dose.append(dose[-1] + deficit * dt_min)
        return times, dose

    all_final = []
    all_series = []
    for sim in all_results:
        times, dose = _cum_co_deficit_series(sim)
        all_series.append((times, dose))
        all_final.append(dose[-1])
    all_final = np.array(all_final)
    order = np.argsort(all_final)[::-1][:n]

    p95 = float(np.percentile(all_final, 95))
    p99 = float(np.percentile(all_final, 99))

    fig, ax = plt.subplots(figsize=(13, 7))
    race_end = None
    cmap = plt.get_cmap('viridis')
    n_lines = max(1, len(order) - 1)
    for rank, idx in enumerate(order):
        times, dose = all_series[idx]
        if race_end is None:
            race_end = times[-1]
        ax.plot(times, dose, color=cmap(rank / n_lines), linewidth=1.6, alpha=0.85,
               label=f"#{idx + 1}")

    if race_end is not None:
        ax.axvline(race_end, color='black', linestyle='--', linewidth=1.5, label='Race end / finish')
    ax.axhline(p95, color='gray', linestyle=':', linewidth=1.3,
              label=f'Population P95 this run ({p95:.2f} L*min)')
    ax.axhline(p99, color='dimgray', linestyle='-.', linewidth=1.3,
              label=f'Population P99 this run ({p99:.2f} L*min)')
    ax.set_title(f"CO_reserve deficit dose cumulative — {title}\n"
                f"(top {n} by final dose; T_rect-independent; NOT clinically calibrated, see docstring)")
    ax.set_xlabel("Time")
    ax.set_ylabel(f"CO deficit dose (L/min * min, reference {co_ref} L/min)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.tick_params(axis='x', rotation=45)
    ax.legend(fontsize=7, ncol=2, loc='upper left')
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_auc_thermisch_extreme_cohorts(all_results: List[List[Dict]], results_df: pd.DataFrame,
                                       stats: Dict, title: str, n: int = 10) -> plt.Figure:
    """Cumulative AUC_thermisch (Breslow-style time-integrated thermal dose,
    T_rect > 39.0°C integrated over time) for the n participants with the
    highest final AUC_thermisch. Same pattern as plot_auc_klinisch_extreme_
    cohorts, but for the lower, 'diagnostic' threshold (39.0°C, module
    comment: "AUC_thermisch (diagnostic)") rather than the Roberts clinical
    one (40.5°C). Because AUC_thermisch has no single established clinical
    action threshold the way AUC_klinisch does (Roberts 2007's 60 °C·min),
    this plot does NOT draw a borrowed/invented threshold line -- instead it
    shows the population's own P95 as an honest, relative reference ("how far
    above this run's own typical tail are these individuals"), not a claimed
    clinical cutoff.
    """
    cohort = results_df.nlargest(n, 'auc_thermisch_deg_min')

    fig, ax = plt.subplots(figsize=(13, 7))
    race_end = None
    cmap = plt.get_cmap('viridis')
    n_lines = max(1, len(cohort) - 1)
    for rank, (_, row) in enumerate(cohort.iterrows()):
        idx = int(row['participant_id']) - 1
        sim = all_results[idx]
        times = [pd.to_datetime(r["time"]) for r in sim]
        auc_th = [r.get("auc_thermisch", 0.0) for r in sim]
        if race_end is None:
            race_end = times[-1]
        ax.plot(times, auc_th, color=cmap(rank / n_lines), linewidth=1.6, alpha=0.85,
               label=f"#{int(row['participant_id'])} ({row['age']}y {row['gender']})")

    if race_end is not None:
        ax.axvline(race_end, color='black', linestyle='--', linewidth=1.5, label='Race end / finish')
    p95 = stats.get('auc_thermisch_p95')
    if p95 is not None:
        ax.axhline(p95, color='gray', linestyle=':', linewidth=1.3,
                  label=f'Population P95 this run ({p95:.1f} degC*min)')
    ax.set_title(f"AUC_thermisch cumulative dose — {title}\n"
                f"(top {n} by final AUC_thermisch; diagnostic measure, 39.0degC threshold, no clinical cutoff)")
    ax.set_xlabel("Time")
    ax.set_ylabel("AUC_thermisch (°C · min)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.tick_params(axis='x', rotation=45)
    ax.legend(fontsize=7, ncol=2, loc='upper left')
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_individual_timeseries(results: List[Dict], title: str) -> plt.Figure:
    """4-panel time series for one participant: core temperature, cardiac
    output reserve, estimated heart rate, and RPE / hydration. hestia_model's
    own plot_adult_results is Monte-Carlo-shaped (expects `all_results` +
    population `stats`), so this covers the single-run case it doesn't.
    """
    times_dt = [pd.to_datetime(r["time"]) for r in results]
    fig, axs = plt.subplots(2, 2, figsize=(16, 10), gridspec_kw={'hspace': 0.35, 'wspace': 0.3})
    fig.suptitle(title, fontsize=15, weight='bold')

    ax1 = axs[0, 0]
    ax1.plot(times_dt, [r.get("t_rect") for r in results], color='blue', linewidth=2)
    ax1.axhline(39.0, color='gold', linestyle='--', label='Heat stress (39°C)')
    ax1.axhline(40.5, color='red', linestyle='--', label='Conjunctive trigger (40.5°C)')
    ax1.set_title("Core temperature (T_rect)")
    ax1.set_ylabel("°C")
    ax1.legend(fontsize=8)

    ax2 = axs[0, 1]
    co_res = [r.get("co_reserve") for r in results]
    if any(v is not None for v in co_res):
        ax2.plot(times_dt, co_res, color='darkred', linewidth=2)
        ax2.axhline(2.0, color='darkorange', linestyle='--', label='Decompensation risk (2.0 L/min)')
        ax2.axhline(0.0, color='red', linestyle='-', label='CO_reserve = 0')
        ax2.legend(fontsize=8)
    else:
        ax2.text(0.5, 0.5, "CVR module not available", ha='center', va='center', transform=ax2.transAxes)
    ax2.set_title("Cardiac output reserve")
    ax2.set_ylabel("L/min")

    ax3 = axs[1, 0]
    hr_vals = [r.get("hr_geschat") for r in results]
    if any(v is not None for v in hr_vals):
        ax3.plot(times_dt, hr_vals, color='darkgreen', linewidth=2)
    ax3.set_title("Estimated heart rate")
    ax3.set_ylabel("bpm")

    ax4 = axs[1, 1]
    rpe = [r.get("rpe_total") for r in results]
    ax4.plot(times_dt, rpe, color='purple', linewidth=2, label='RPE')
    ax4.axhline(17, color='purple', linestyle=':', label='Exhaustion (RPE 17)')
    ax4.set_ylabel("RPE (6-20)", color='purple')
    ax4b = ax4.twinx()
    water = [r.get("water") for r in results]
    if any(v is not None for v in water):
        ax4b.plot(times_dt, water, color='teal', linestyle='--', label='Cumulative water loss (g)')
        ax4b.set_ylabel("Water loss (g)", color='teal')
    ax4.set_title("Perceived exertion & hydration")
    ax4.legend(fontsize=8, loc='upper left')

    for ax in axs.flat:
        ax.set_xlabel("Time")
        ax.grid(True, linestyle='--', alpha=0.5)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.tick_params(axis='x', rotation=45)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    return fig


def plot_extreme_cohorts_timeseries(all_results: List[List[Dict]], results_df: pd.DataFrame,
                                    title: str, n: int = 10) -> plt.Figure:
    """Time course (race start -> race end -> 10 min post-finish) for the two
    most at-risk cohorts: the `n` participants with the highest peak T_rect,
    and the `n` with the lowest minimum CO_reserve. Uses the post-finish
    trajectory hestia_model.py's simulate_post_finish() already computes
    internally (t_rect_series_postfinish / co_reserve_series_postfinish /
    time_min_series_postfinish, attached to each participant's last race-time
    record) rather than only the single peak/end summary values it exposed
    before.

    `results_df['participant_id']` is 1-indexed and matches `all_results`
    order (participant_id - 1 == index into all_results).
    """
    top_t_rect = results_df.nlargest(n, 'max_t_rect')
    bottom_co_reserve = results_df.nsmallest(n, 'cvr_co_reserve_min') \
        if 'cvr_co_reserve_min' in results_df.columns else results_df.iloc[0:0]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 12), gridspec_kw={'hspace': 0.35})
    fig.suptitle(f"Extreme-cohort time course — {title}", fontsize=15, weight='bold')

    # [2026-09-19, fix requested by Koos] race_end_time used to be set once,
    # from the FIRST participant encountered in the sorted top-N loop, then
    # reused as a single shared vline for every other line in BOTH panels --
    # meaningless once sample_pace=True gives each participant their own
    # finish time (each line's own post-finish "kink" already marks that
    # person's own finish correctly; only this shared reference line was
    # wrong). Replaced with one small per-participant finish marker, in that
    # line's own colour, at that participant's own race_times[-1].
    cmap1 = plt.get_cmap('autumn')
    for rank, (_, row) in enumerate(top_t_rect.iterrows()):
        idx = int(row['participant_id']) - 1
        sim = all_results[idx]
        race_times = [pd.to_datetime(r["time"]) for r in sim]
        race_trect = [r["t_rect"] for r in sim]
        color = cmap1(rank / max(1, n - 1))
        last = sim[-1]
        combined_times = list(race_times)
        combined_trect = list(race_trect)
        if 'time_min_series_postfinish' in last:
            for t_min, t_rect_val in zip(last['time_min_series_postfinish'][1:],
                                         last['t_rect_series_postfinish'][1:]):
                combined_times.append(race_times[-1] + pd.Timedelta(minutes=t_min))
                combined_trect.append(t_rect_val)
        ax1.plot(combined_times, combined_trect, color=color,
                 linewidth=1.6, alpha=0.85,
                 label=f"#{int(row['participant_id'])} ({row['age']}y {row['gender']})")
        ax1.plot(race_times[-1], race_trect[-1], marker='o', markersize=5,
                 color=color, markeredgecolor='black', markeredgewidth=0.6, zorder=5)

    ax1.plot([], [], marker='o', markersize=5, color='0.4', markeredgecolor='black',
             markeredgewidth=0.6, linestyle='none', label="Eigen finish (per deelnemer)")
    ax1.axhline(40.5, color='red', linestyle=':', linewidth=1.2, label='Conjunctive trigger (40.5°C)')
    ax1.set_title(f"Top {n} by peak T_rect — race + {int(hestia.PF_DUUR_MIN)} min post-finish")
    ax1.set_ylabel("T_rect (°C)")
    ax1.legend(fontsize=7, ncol=2, loc='lower right')
    ax1.grid(True, alpha=0.3)

    cmap2 = plt.get_cmap('winter')
    for rank, (_, row) in enumerate(bottom_co_reserve.iterrows()):
        idx = int(row['participant_id']) - 1
        sim = all_results[idx]
        race_times = [pd.to_datetime(r["time"]) for r in sim]
        race_co = [r.get("co_reserve") for r in sim]
        color = cmap2(rank / max(1, n - 1))
        last = sim[-1]
        combined_times = list(race_times)
        combined_co = list(race_co)
        if 'time_min_series_postfinish' in last:
            for t_min, co_val in zip(last['time_min_series_postfinish'][1:],
                                     last['co_reserve_series_postfinish'][1:]):
                combined_times.append(race_times[-1] + pd.Timedelta(minutes=t_min))
                combined_co.append(co_val)
        ax2.plot(combined_times, combined_co, color=color,
                 linewidth=1.6, alpha=0.85,
                 label=f"#{int(row['participant_id'])} ({row['age']}y {row['gender']})")
        ax2.plot(race_times[-1], race_co[-1], marker='o', markersize=5,
                 color=color, markeredgecolor='black', markeredgewidth=0.6, zorder=5)

    ax2.plot([], [], marker='o', markersize=5, color='0.4', markeredgecolor='black',
             markeredgewidth=0.6, linestyle='none', label="Eigen finish (per deelnemer)")
    ax2.axhline(2.0, color='darkorange', linestyle=':', linewidth=1.2, label='Decompensation risk (2.0 L/min)')
    ax2.axhline(0.0, color='red', linestyle=':', linewidth=1.2, label='CO_reserve = 0')
    ax2.set_title(f"Bottom {n} by minimum CO_reserve — race + {int(hestia.PF_DUUR_MIN)} min post-finish")
    ax2.set_ylabel("CO_reserve (L/min)")
    ax2.legend(fontsize=7, ncol=2, loc='lower left')
    ax2.grid(True, alpha=0.3)

    for ax in (ax1, ax2):
        ax.set_xlabel("Time")
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.tick_params(axis='x', rotation=45)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    return fig


# ============================================================================
# batch generation, called from run_hestia.py
# ============================================================================

def generate_population_plots(all_results, results_df, stats, city, start_time,
                              duration_hours, out_dir: Optional[str] = None) -> List[str]:
    """Generate every relevant population/Monte-Carlo plot and save as PNG.
    Returns the list of saved file paths."""
    if out_dir is None:
        out_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    label = f"{city}_{pd.to_datetime(start_time).date()}_n{len(all_results)}"
    saved = []

    fig1 = hestia.plot_adult_results(all_results, stats, city, start_time, duration_hours)
    p = os.path.join(out_dir, f"HESTIA_plot1_timeseries_tailplot_{label}.png")
    fig1.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig1)
    saved.append(p)

    fig2 = hestia.plot_adult_boxplots(results_df)
    p = os.path.join(out_dir, f"HESTIA_plot2_boxplots_age_gender_{label}.png")
    fig2.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig2)
    saved.append(p)

    fig = plot_co_reserve_distribution(results_df, f"{city}, {start_time}")
    p = os.path.join(out_dir, f"HESTIA_plot3_co_reserve_dist_{label}.png")
    fig.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    fig = plot_collapse_risk_distribution(stats, f"{city}, {start_time}")
    if fig is not None:
        p = os.path.join(out_dir, f"HESTIA_plot4_collapse_risk_dist_{label}.png")
        fig.savefig(p, dpi=140, bbox_inches="tight")
        plt.close(fig)
        saved.append(p)

    fig = plot_conjunctive_risk_scatter(results_df, f"{city}, {start_time}")
    p = os.path.join(out_dir, f"HESTIA_plot5_conjunctive_risk_scatter_{label}.png")
    fig.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    fig = plot_age_vs_collapse_risk(results_df, f"{city}, {start_time}")
    p = os.path.join(out_dir, f"HESTIA_plot6_age_vs_collapse_risk_{label}.png")
    fig.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    fig = plot_extreme_cohorts_timeseries(all_results, results_df, f"{city}, {start_time}")
    p = os.path.join(out_dir, f"HESTIA_plot7_extreme_cohorts_timeseries_{label}.png")
    fig.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    fig = plot_conjunctive_dose_extreme_cohorts(all_results, results_df, f"{city}, {start_time}")
    p = os.path.join(out_dir, f"HESTIA_plot8_conjunctive_dose_extreme_cohorts_{label}.png")
    fig.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    fig = plot_auc_klinisch_extreme_cohorts(all_results, results_df, f"{city}, {start_time}")
    p = os.path.join(out_dir, f"HESTIA_plot9_auc_klinisch_extreme_cohorts_{label}.png")
    fig.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    fig = plot_auc_thermisch_extreme_cohorts(all_results, results_df, stats, f"{city}, {start_time}")
    p = os.path.join(out_dir, f"HESTIA_plot10_auc_thermisch_extreme_cohorts_{label}.png")
    fig.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    fig = plot_co_deficit_dose_extreme_cohorts(all_results, f"{city}, {start_time}")
    p = os.path.join(out_dir, f"HESTIA_plot11_co_deficit_dose_extreme_cohorts_{label}.png")
    fig.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig)
    saved.append(p)

    return saved


def generate_individual_plots(results, city, start_time, age=None, gender=None,
                              out_dir: Optional[str] = None) -> List[str]:
    """Generate the single-participant time-series plot and save as PNG."""
    if out_dir is None:
        out_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)
    who = f"{age}-year-old {gender}" if age and gender else "participant"
    title = f"HESTIA individual simulation — {who}, {city}, {start_time}"
    label = f"{city}_{pd.to_datetime(start_time).date()}_individual"

    fig = plot_individual_timeseries(results, title)
    p = os.path.join(out_dir, f"HESTIA_plot_individual_timeseries_{label}.png")
    fig.savefig(p, dpi=140, bbox_inches="tight")
    plt.close(fig)

    fig2 = plot_conjunctive_criterion_individual(results, title)
    p2 = os.path.join(out_dir, f"HESTIA_plot_individual_conjunctive_dose_{label}.png")
    fig2.savefig(p2, dpi=140, bbox_inches="tight")
    plt.close(fig2)

    return [p, p2]


if __name__ == "__main__":
    print("hestia_plots.py provides functions used by run_hestia.py's CLI "
          "('Generate plots?' prompt after a run). Run `python run_hestia.py` "
          "instead of this file directly.")
