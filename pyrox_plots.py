# -*- coding: utf-8 -*-
"""
PYROX plots
================================================================================
The four diagnostic / publication plots for PYROX, each runnable on any
heat-load series (real Thermopoulos data or the Paris-2003 reconstruction):

    1. plot_strain_trajectories  — the signature plot: Σ(t) per group + zones
    2. plot_feedback_race        — the uniqueness plot: the one reinforcing loop vs. time
    3. plot_paris_validation     — Σ(t) vs. observed Fouillet mortality
    4. plot_risk_heatmap         — operational: group × day strain-zone grid
    5. plot_three_regimes        — control-theory: dead-zone / stable / runaway
    6. plot_forecast_uncertainty — strain with a ±2°C forecast-uncertainty band

Each function takes already-computed data and returns a matplotlib Figure, so
they can be saved to file or shown. The __main__ block builds all four for both
the Maastricht data (if present) and the Paris-2003 reconstruction.
"""

from __future__ import annotations

from typing import List, Dict, Optional

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm

from pyrox_model import PyroxModel
import pyrox_model as pm
from pyrox_groups import TARGET_GROUPS


# zone colours (consistent across all plots)
ZONE_COLOURS = {
    "safe": "#1a8a4a",       # green     — clearly safe
    "caution": "#2563c9",    # blue      — first concern, far from danger hue
    "danger": "#f4c20d",     # vivid amber-yellow — strong, holds against white
    "emergency": "#d11414",  # red       — critical
}


def _format_date_axis(ax, dates, n_ticks=10):
    """Put real calendar dates on the x-axis instead of integer indices.
    `dates` is a list of date-like values aligned with day positions 1..N."""
    import matplotlib.dates as mdates
    if dates is None:
        return
    n = len(dates)
    step = max(1, n // n_ticks)
    positions = list(range(1, n + 1, step))
    labels = [str(dates[p - 1])[:10] for p in positions]  # YYYY-MM-DD
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)


def _strain_zone(value: float, critical: float) -> str:
    frac = value / critical
    if frac >= 0.90:
        return "emergency"
    if frac >= 0.75:
        return "danger"
    if frac >= 0.50:
        return "caution"
    return "safe"


# ============================================================================
# 1. SIGNATURE: strain trajectories over time
# ============================================================================

def plot_strain_trajectories(heat_loads: List[float],
                             group_names: List[str],
                             title: str,
                             pre_heatwave_load: Optional[float] = None,
                             dates: Optional[list] = None,
                             forecast_start: Optional[int] = None) -> plt.Figure:
    """Σ(t) for several groups on one axis, with zone thresholds and the heat
    load shown as a background band. This is the plot that shows divergence.

    If `dates` is given, the x-axis shows calendar dates. If `forecast_start`
    is given (the day index where forecast begins), a vertical line marks the
    hindcast→forecast transition."""
    fig, ax = plt.subplots(figsize=(11, 6))

    # background: heat load (secondary axis)
    ax2 = ax.twinx()
    days = np.arange(0, len(heat_loads) + 1)
    load_padded = [heat_loads[0]] + list(heat_loads)
    ax2.fill_between(days, 0, load_padded, color="#cccccc", alpha=0.35, step="pre",
                     zorder=0, label="heat load")
    ax2.set_ylabel("baseline heat load", color="#888888")
    ax2.tick_params(axis="y", labelcolor="#888888")
    ax2.set_ylim(0, max(3.0, max(heat_loads) * 1.3))

    # one critical value (groups with kappa=0.5 share critical=2.0)
    critical = TARGET_GROUPS[group_names[0]].critical_strain
    for frac, name, col in [(0.50, "caution", ZONE_COLOURS["caution"]),
                            (0.75, "danger", ZONE_COLOURS["danger"]),
                            (0.90, "emergency", ZONE_COLOURS["emergency"])]:
        ax.axhline(frac * critical, ls="--", lw=1, color=col, alpha=0.7, zorder=1)
        ax.text(len(heat_loads), frac * critical, f" {name}", va="center",
                ha="left", fontsize=8, color=col)

    # forecast transition marker
    if forecast_start is not None:
        ax.axvline(forecast_start, color="#333333", lw=1.5, ls="-", alpha=0.6, zorder=2)
        ax.text(forecast_start, critical * 1.02, "forecast →", fontsize=8,
                ha="left", va="bottom", color="#333333")
        ax.text(forecast_start, critical * 1.02, "← hindcast ", fontsize=8,
                ha="right", va="bottom", color="#333333")

    cmap = plt.cm.viridis(np.linspace(0, 0.92, len(group_names)))
    for colour, name in zip(cmap, group_names):
        g = TARGET_GROUPS[name]
        res = PyroxModel(g).simulate(heat_loads, pre_heatwave_heat_load=pre_heatwave_load)
        ax.plot(np.arange(len(res["cumulative_strain"])), res["cumulative_strain"],
                lw=2, color=colour, label=g.display_name, zorder=3)

    ax.set_xlabel("date" if dates is not None else "day")
    ax.set_ylabel("cumulative strain  Σ")
    ax.set_title(title)
    ax.set_xlim(0, len(heat_loads))
    ax.set_ylim(0, critical * 1.05)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)
    _format_date_axis(ax, dates)
    fig.tight_layout()
    return fig


# ============================================================================
# 2. UNIQUENESS: the two feedback loops racing
# ============================================================================

def plot_feedback_race(heat_loads: List[float],
                       group_name: str,
                       title: str,
                       pre_heatwave_load: Optional[float] = None,
                       dates: Optional[list] = None,
                       forecast_start: Optional[int] = None) -> plt.Figure:
    """For one (usually vulnerable) group, show the forcing's two effects
    (a direct path into strain, and a delayed one via acclimatization) and
    the single feedback loop that can undermine the acclimatization path.

    [2026-09] Previously labelled this as "two competing loops" (a
    protective loop vs. an undermining loop racing each other). That is not
    what the equations do: acclimatization is a straight-through DAMPING
    PATH driven by the external forcing, not a loop (it does not itself
    respond to strain). There is exactly one closed loop in this model:
    strain -> suppression_factor -> (dampens) effective_acclimatization ->
    (would otherwise dampen) strain. Sign check: (+)(-)(-) = + -- a single
    REINFORCING loop, not two loops in a race. This is the model's actual
    principled foundation (see the explanatory text block below the plot),
    and the labels/shading here now match it: acclimatization_potential
    (the undiminished damping the group's memory of exposure would
    otherwise provide) is now plotted explicitly as a dashed line, with the
    gap down to effective_acclimatization shaded -- that gap *is* the one
    reinforcing loop's visible footprint."""
    g = TARGET_GROUPS[group_name]
    res = PyroxModel(g).simulate(
        heat_loads,
        pre_heatwave_heat_load=pre_heatwave_load if pre_heatwave_load else heat_loads[0],
    )
    diags = res["diagnostics"]
    days = np.arange(1, len(diags) + 1)

    strain = np.array([d["cumulative_strain"] for d in diags])
    acclim_eff = np.array([d["effective_acclimatization"] for d in diags])
    acclim_pot = np.array([d["acclimatization_potential"] for d in diags])
    suppression = np.array([d["suppression_factor"] for d in diags])

    fig, ax = plt.subplots(figsize=(11, 6.6))
    ax.plot(days, strain, lw=3, color=ZONE_COLOURS["emergency"], zorder=4,
            label="cumulatieve strain Σ  —  DIT is de hittestress-ontwikkeling")
    ax.plot(days, acclim_pot, lw=1.5, ls="--", color=ZONE_COLOURS["safe"],
            label="acclimatization potential  (zonder onderdrukking)")
    ax.plot(days, acclim_eff, lw=2.5, color=ZONE_COLOURS["safe"],
            label="effective acclimatization  (mét onderdrukking)")
    ax.fill_between(days, acclim_eff, acclim_pot, color=ZONE_COLOURS["safe"],
                    alpha=0.15, zorder=1,
                    label="voetafdruk van de terugkoppelingslus")
    ax.plot(days, suppression, lw=1.5, ls=":", color="#4063d8",
            label="suppression factor  (1 \u2212 \u03baΣ)")

    # [2026-09] Fixed after testing against several scenarios (short 3-day
    # series, a group that never approaches critical): a data-relative
    # anchor (e.g. "1/4 of the way through") drifts into the legend's
    # bounding box whenever the series is short, and can sit anywhere
    # vertically depending on how fast strain rises. Anchoring the LABEL at
    # a fixed axes-fraction corner (independent of day count and of the
    # legend, which always sits centre-right) removes that failure mode
    # entirely; only the arrow's target point still follows the data
    # (always the first day, so the arrow is always on the left, clear of
    # the centre-right legend).
    # [2026-09] Second fix from the same scenario testing: anchoring the
    # label at a fixed axes-fraction corner kept it clear of the legend,
    # but when the first data point sits far below that corner (a
    # resilient group that starts low), the connecting arrow becomes a
    # long diagonal that visually reads as a second, steep red curve --
    # exactly the ambiguity this callout exists to remove. Fixed by
    # keeping the arrow SHORT: a small fixed offset in points from the
    # actual point, not a swing to a distant corner. Still anchored to
    # day[0] (always the leftmost point, clear of the centre-right
    # legend); flips above/below depending on how close that point
    # already is to the top, so the label itself never clips the axes.
    y0 = strain[0]
    near_top = y0 > g.critical_strain * 0.7
    ax.annotate(
        "Dit is de hittestress-\nontwikkeling",
        xy=(days[0], y0), xycoords="data",
        xytext=(55, -45 if near_top else 45), textcoords="offset points",
        fontsize=10, fontweight="bold", color=ZONE_COLOURS["emergency"],
        ha="left", va="center",
        arrowprops=dict(arrowstyle="->", color=ZONE_COLOURS["emergency"], lw=1.5),
        zorder=5,
    )

    # [2026-09] Clearance above the critical line is now an explicit offset
    # (3% of the y-range) instead of anchoring the text block's edge
    # exactly ON the axhline -- va='bottom' at y=critical put the text's
    # bottom edge flush against the dotted line, which was invisible in
    # early tests only because the strain curve happened to plateau at
    # critical too (hiding the line behind the thick red stroke). A
    # scenario where a group never approaches critical exposed it: the
    # dotted line ran straight through the middle of the label text.
    y_top = g.critical_strain * 1.22
    clearance = 0.03 * y_top
    ax.axhline(g.critical_strain, ls=":", color="grey", lw=1.2)
    ax.text(len(days), g.critical_strain + clearance, "100% = kritieke grens\n"
            "(bescherming volledig overmeesterd)", va="bottom",
            ha="right", fontsize=7.5, color="grey", linespacing=1.6)

    # [2026-09] A bare number like "critical Sigma = 1.75" means nothing to a
    # non-specialist -- it is an internal model unit, not something anyone
    # has an intuition for. Two fixes: (1) reuse the same caution/danger/
    # emergency reference fractions (50/75/90% of critical) that
    # plot_strain_trajectories already uses elsewhere in this suite, so the
    # vocabulary is consistent across the whole report; (2) state in plain
    # language what "critical" physically IS -- not an arbitrary cutoff, but
    # the exact point where suppression_factor = 1 - kappa*Sigma hits zero,
    # i.e. where the acclimatization path's effect is fully cancelled.
    for frac, name, col in [(0.50, "caution", ZONE_COLOURS["caution"]),
                            (0.75, "danger", ZONE_COLOURS["danger"]),
                            (0.90, "emergency", ZONE_COLOURS["emergency"])]:
        level = frac * g.critical_strain
        ax.axhline(level, ls="--", lw=1, color=col, alpha=0.6, zorder=1)
        ax.text(len(days), level, f" {int(frac*100)}% {name}", va="center",
                ha="left", fontsize=7.5, color=col)

    # forecast transition marker
    if forecast_start is not None:
        ax.axvline(forecast_start, color="#333333", lw=1.5, alpha=0.6)
        ax.text(forecast_start, g.critical_strain * 0.97, " forecast →",
                fontsize=8, ha="left", va="top", color="#333333")
        ax.text(forecast_start, g.critical_strain * 0.97, "← hindcast ",
                fontsize=8, ha="right", va="top", color="#333333")

    ax.set_xlabel("date" if dates is not None else "day")
    ax.set_ylabel("value")
    ax.set_title(f"{title}\nDe ene terugkoppelingslus in actie — {g.display_name}")
    ax.set_xlim(1, len(days))
    ax.set_ylim(0, g.critical_strain * 1.22)
    leg = ax.legend(loc="center right", fontsize=8, framealpha=0.9)
    leg.get_texts()[0].set_fontweight("bold")
    _format_date_axis(ax, dates)

    principle_text = (
        "Wat dit laat zien: het principiële fundament van PYROX\n"
        "\n"
        "De rode lijn (cumulatieve strain Σ) is het eindresultaat -- de\n"
        "hittestress-ontwikkeling die dit hele model probeert te voorspellen.\n"
        "De andere drie lijnen verklaren WAAROM die rode lijn doet wat hij\n"
        "doet; ze zijn geen aparte uitkomsten op zichzelf.\n"
        "\n"
        "Hitteblootstelling (forcing) werkt op twee manieren in: rechtstreeks\n"
        "op de cumulatieve strain, én vertraagd via de acclimatisatie -- die\n"
        "pas na eerdere blootstelling opbouwt (het geheugen-kernel).\n"
        "\n"
        "De acclimatisatie zelf is GEEN lus: het is een dempend pad,\n"
        "aangedreven door de externe blootstelling, niet door de strain zelf.\n"
        "Zou het daarbij blijven, dan was dit een gewoon stabiel systeem --\n"
        "meer blootstelling geeft meer demping, geen instabiliteit.\n"
        "\n"
        "Er is precies ÉÉN gesloten lus: cumulatieve strain -> onderdrukking\n"
        "-> (remt) acclimatisatie -> (zou remmen op) strain. Polariteit:\n"
        "(+)(\u2212)(\u2212) = +. Dat is een zichzelf-versterkende lus -- geen\n"
        "tegenwicht, een neerwaartse spiraal.\n"
        "\n"
        "Het omslagpunt waar PYROX naar zoekt is niet een vast getal, maar\n"
        "het moment waarop die ene lus het rechtstreekse dempingspad\n"
        "overmeestert: de onderdrukkingsfactor zakt richting nul, en de\n"
        "gearceerde kloof tussen het gestippelde potentieel en de\n"
        "doorgetrokken effectieve acclimatisatie is de zichtbare voetafdruk\n"
        "van die ene lus, niet van een tweede, concurrerende lus.\n"
        "\n"
        "Een getal als 'kritieke grens = 1,75' zegt op zichzelf niets -- het is\n"
        "een interne modeleenheid, geen fysiologische maat. Wat het WEL is:\n"
        "exact het punt waar de onderdrukkingsfactor (1 \u2212 \u03baΣ) nul wordt, dus\n"
        "waar de bescherming volledig is overmeesterd. Vandaar de 50/75/90%-\n"
        "lijnen (caution/danger/emergency) -- dezelfde schaalverdeling als\n"
        "elders in de suite: niet de absolute waarde telt, wel het percentage\n"
        "van deze ene, groep-specifieke grens."
    )

    # [2026-09] Figure height/positions computed from the actual text length
    # instead of hand-tuned constants -- this box has grown three times as
    # the explanation was extended, and each time required re-guessing a
    # figsize/y-position pair by trial and render. Computing it directly
    # from the text means future edits to principle_text (adding a
    # paragraph, translating it, etc.) auto-size correctly instead of
    # silently clipping the last lines again.
    CHART_H_IN = 6.6      # fixed height for the chart itself, unaffected by text length
    GAP_H_IN = 0.55        # clearance between the x-axis label and the text box
    FONT_PT = 8.5
    LINESPACING = 1.5
    n_lines = principle_text.count("\n") + 1
    text_h_in = n_lines * (FONT_PT * LINESPACING / 72.0) + 0.55  # + bbox padding
    total_h_in = CHART_H_IN + GAP_H_IN + text_h_in

    fig.set_size_inches(11, total_h_in)
    bottom_frac = (GAP_H_IN + text_h_in) / total_h_in
    text_top_frac = text_h_in / total_h_in
    fig.subplots_adjust(bottom=bottom_frac)
    fig.text(0.5, text_top_frac, principle_text, ha='center', va='top', fontsize=FONT_PT,
             linespacing=LINESPACING,
             bbox=dict(boxstyle='round,pad=0.5', facecolor='#EAF3DE', edgecolor='#639922'))
    return fig


# ============================================================================
# 3. VALIDATION: Paris-2003 strain vs. observed mortality
# ============================================================================

def plot_paris_validation(title: str = "PYROX validation — Paris August 2003") -> plt.Figure:
    """Overlay PYROX strain for older groups on the observed Fouillet daily
    excess-death curve. If the strain build-up tracks the mortality curve in
    shape and timing, the model reproduces the real event."""
    from paris2003 import (paris_2003_heat_loads, paris_2003_excess_deaths,
                           PARIS_2003_DATES)

    loads = paris_2003_heat_loads(per_degree=0.10)
    deaths = paris_2003_excess_deaths()
    days = np.array(PARIS_2003_DATES)

    fig, ax = plt.subplots(figsize=(10, 6))

    # observed mortality (bars, right axis)
    ax2 = ax.twinx()
    ax2.bar(days, deaths, width=0.7, color="#c1272d", alpha=0.25,
            label="observed excess deaths (Fouillet 2006)", zorder=0)
    ax2.set_ylabel("daily excess deaths, France", color="#c1272d")
    ax2.tick_params(axis="y", labelcolor="#c1272d")

    # PYROX strain for older groups (left axis)
    for name, colour in [("elderly_65_85", "#2e8b57"),
                         ("very_elderly_85plus", "#e8702a")]:
        g = TARGET_GROUPS[name]
        res = PyroxModel(g).simulate(loads, pre_heatwave_heat_load=loads[0])
        ax.plot(np.arange(len(res["cumulative_strain"])) + 1,
                res["cumulative_strain"], lw=2.5, color=colour,
                label=f"PYROX Σ — {g.display_name}", zorder=3)

    ax.set_xlabel("day of August 2003")
    ax.set_ylabel("cumulative strain  Σ")
    ax.set_title(title)
    ax.set_xlim(1, 16)
    ax.set_ylim(0, 2.1)
    # combined legend
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8)
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)
    fig.tight_layout()
    return fig


# ============================================================================
# 4. OPERATIONAL: group × day strain-zone heatmap
# ============================================================================

def plot_risk_heatmap(heat_loads: List[float],
                      group_names: List[str],
                      title: str,
                      pre_heatwave_load: Optional[float] = None,
                      dates: Optional[list] = None,
                      forecast_start: Optional[int] = None) -> plt.Figure:
    """Grid of group (y, ordered resilient→vulnerable) × day (x), coloured by
    strain zone. The at-a-glance operational picture: who is at risk when."""
    zone_index = {"safe": 0, "caution": 1, "danger": 2, "emergency": 3}
    n_days = len(heat_loads)
    grid = np.zeros((len(group_names), n_days))

    labels = []
    for row, name in enumerate(group_names):
        g = TARGET_GROUPS[name]
        labels.append(g.display_name)
        res = PyroxModel(g).simulate(heat_loads, pre_heatwave_heat_load=pre_heatwave_load)
        traj = res["cumulative_strain"][1:]  # drop initial state, align with days
        for col in range(n_days):
            grid[row, col] = zone_index[_strain_zone(traj[col], g.critical_strain)]

    cmap = ListedColormap([ZONE_COLOURS["safe"], ZONE_COLOURS["caution"],
                           ZONE_COLOURS["danger"], ZONE_COLOURS["emergency"]])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], cmap.N)

    fig, ax = plt.subplots(figsize=(13, max(6, len(group_names) * 0.34)))
    ax.imshow(grid, aspect="auto", cmap=cmap, norm=norm,
              extent=[0.5, n_days + 0.5, len(group_names) - 0.5, -0.5])

    ax.set_yticks(range(len(group_names)))
    ax.set_yticklabels(labels, fontsize=7)

    # repeat the group labels on the RIGHT so the eye never has to travel far
    ax_right = ax.twinx()
    ax_right.set_ylim(ax.get_ylim())
    ax_right.set_yticks(range(len(group_names)))
    ax_right.set_yticklabels(labels, fontsize=7)

    # thin gridlines: vertical between days, horizontal between groups
    for x in np.arange(0.5, n_days + 1.5, 1.0):
        ax.axvline(x, color="white", lw=0.6, alpha=0.55, zorder=2)
    for y in np.arange(0.5, len(group_names) - 0.5, 1.0):
        ax.axhline(y, color="white", lw=0.6, alpha=0.55, zorder=2)

    if dates is not None:
        step = max(1, n_days // 12)
        positions = list(range(1, n_days + 1, step))
        ax.set_xticks(positions)
        ax.set_xticklabels([str(dates[p - 1])[:10] for p in positions],
                           rotation=45, ha="right", fontsize=7)
        ax.set_xlabel("date")
    else:
        ax.set_xticks(range(1, n_days + 1))
        ax.set_xlabel("day")

    # forecast transition marker (between hindcast day N and forecast day N+1)
    if forecast_start is not None:
        ax.axvline(forecast_start + 0.5, color="white", lw=2.8, zorder=3)
        ax.axvline(forecast_start + 0.5, color="#222222", lw=1.2, ls="--", zorder=3)
        ax.annotate("forecast →", xy=(forecast_start + 0.5, 0.3),
                    xytext=(4, 0), textcoords="offset points",
                    fontsize=8, ha="left", va="center", color="white",
                    fontweight="bold", zorder=4)

    ax.set_title(title, pad=14)

    # legend along the bottom, so it clears the repeated right-hand labels
    from matplotlib.patches import Patch
    handles = [Patch(color=ZONE_COLOURS[z], label=z) for z in
               ["safe", "caution", "danger", "emergency"]]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.12),
              ncol=4, fontsize=9, title="zone", frameon=True)
    fig.tight_layout()
    return fig


# ============================================================================
# 5. CONTROL THEORY: the three operating regimes
# ============================================================================

def plot_three_regimes(group_names: List[str],
                       load_max: float = 2.5,
                       days_to_equilibrium: int = 80) -> plt.Figure:
    """Show PYROX's three operating regimes (dead-zone / stable accumulation /
    runaway) for one or more groups.

    [2026-09] days_to_equilibrium is now unused -- kept only so existing
    calls that pass it don't break. The steady-state curve is computed
    analytically via equilibrium_strain() instead of approximating it by
    brute-force simulation for this many days, see the inline note below.

    For each group, two panels side by side:
      left  — steady-state equilibrium strain Σ* vs constant heat load R₁,
               with the dead-zone (safe) and runaway zones shaded and the
               transition load marked;
      right — three example time-courses (one per regime).

    Multiple groups are stacked vertically so their transition loads can be
    compared — a vulnerable group's knife-edge sits at a lower load than a
    resilient group's. This is the control-theoretic companion to the stability
    analysis: the regimes are derived analytically and verified here against the
    running simulation.
    """
    n = len(group_names)
    fig, axes = plt.subplots(n, 2, figsize=(15, 5.2 * n),
                             squeeze=False)

    loads = np.arange(0.1, load_max + 0.05, 0.02)

    for row, name in enumerate(group_names):
        g = TARGET_GROUPS[name]
        crit = g.critical_strain
        ax1, ax2 = axes[row, 0], axes[row, 1]

        # [2026-09] Was a brute-force approximation: simulate 80 days at each
        # constant load and read off the last value as "the equilibrium".
        # Slow (n_loads x 80-day simulations) and imprecise -- the "edge"
        # was found via `sigstar > 0.9*critical`, a heuristic that mislabels
        # any load with a genuine but sub-90%-of-critical equilibrium (e.g.
        # outdoor_workers at load=2.5 has a real equilibrium at 82% of
        # critical -- not "dead-zone safe", but the old threshold would
        # still call it pre-edge). Now uses equilibrium_strain() directly
        # (fixed this session to distinguish safe/equilibrium/runaway
        # instead of collapsing the first and third into the same `None`),
        # which is both exact and much faster (bisection, not simulation).
        states = [pm.equilibrium_strain(g, R1, g.max_acclimatization_capacity)
                 for R1 in loads]
        sigstar = np.array([0.0 if s == "safe" else (v if v is not None else np.nan)
                            for s, v in states])
        runaway_mask = np.array([s == "runaway" for s, v in states])
        no_runaway_found = not runaway_mask.any()
        edge = loads[np.argmax(runaway_mask)] if not no_runaway_found else load_max

        # left panel — steady state
        # [2026-09] When no runaway state occurs anywhere in the tested load
        # range (found for outdoor_workers and elite_athletes at the default
        # load_max=2.5 -- 0/123 tested loads), the old code still drew a red
        # "RUNAWAY" zone starting exactly at load_max, implying that load_max
        # itself is a real transition point. It is not -- it is simply where
        # testing stopped. Now shown as an explicit "not reached" note
        # instead of a false transition line and false-positive red zone.
        if no_runaway_found:
            ax1.axvspan(0, load_max, color=ZONE_COLOURS["safe"], alpha=0.15)
        else:
            ax1.axvspan(0, edge, color=ZONE_COLOURS["safe"], alpha=0.15)
            ax1.axvspan(edge, load_max, color=ZONE_COLOURS["emergency"], alpha=0.15)
        ax1.plot(loads, sigstar, color="#222", lw=2.6, zorder=5)
        ax1.axhline(crit, ls=":", color="grey", lw=1.1)
        ax1.text(0.13, crit - 0.06 * crit, "Σ_critical = 1/κ", fontsize=8.5,
                 color="grey", va="top")
        if no_runaway_found:
            ax1.text(load_max / 2, crit * 0.86,
                     f"Geen runaway gevonden tot R\u2081={load_max:g}\n"
                     "(mogelijk pas bij hogere belasting, of nooit)",
                     ha="center", va="center", fontsize=8.5, color="#7a5b00",
                     fontweight="bold")
            ax1.text(load_max * 0.3, crit * 0.5, "1. DEAD-ZONE\n(safe)\nΣ* = 0",
                     ha="center", va="center", fontsize=9, color="#155e35",
                     fontweight="bold")
            nz = np.where(sigstar > 1e-9)[0]
            if len(nz):
                ax1.annotate("2. STABLE ACCUMULATION\n(nonzero, still safe)",
                            xy=(loads[nz[0]], sigstar[nz[-1]] * 0.6),
                            xytext=(loads[nz[0]] - 0.5, crit * 0.25),
                            fontsize=8, color="#7a5b00", fontweight="bold", ha="center",
                            arrowprops=dict(arrowstyle="->", color="#7a5b00", lw=1.2))
        else:
            ax1.axvline(edge, color="#7a5b00", lw=1.5, ls="--", zorder=6)
            ax1.text(edge + 0.03, crit * 0.86, f"transition R₁ ≈ {edge:.2f}",
                     ha="left", va="center", fontsize=8, color="#7a5b00",
                     fontweight="bold", rotation=90)
            ax1.text(edge / 2, crit * 0.66, "1. DEAD-ZONE\n(safe)\nΣ* = 0",
                     ha="center", va="center", fontsize=9, color="#155e35",
                     fontweight="bold")
            ax1.text((edge + load_max) / 2, crit * 0.5,
                     "3. RUNAWAY\nΣ* → Σ_critical\nnet gain > 0",
                     ha="center", va="center", fontsize=9, color="#8a1010",
                     fontweight="bold")
            ax1.annotate("2. STABLE ACCUMULATION\n(narrow knife-edge)",
                        xy=(edge, crit * 0.25), xytext=(max(0.15, edge - 0.6), crit * 0.14),
                        fontsize=8, color="#7a5b00", fontweight="bold", ha="center",
                        arrowprops=dict(arrowstyle="->", color="#7a5b00", lw=1.2))
        ax1.set_xlabel("constant heat load  R₁", fontsize=10)
        ax1.set_ylabel("equilibrium strain  Σ*", fontsize=10)
        ax1.set_title(f"{g.display_name} — steady state", fontsize=11)
        ax1.set_xlim(0.1, load_max)
        ax1.set_ylim(-0.05, crit * 1.08)

        # right panel — time courses, one per regime
        # pick representative loads relative to this group's transition `edge`,
        # but cap at load_max so high-threshold groups still show a spread
        safe_load = max(0.4, edge * 0.6)
        edge_load = min(edge + 0.02, load_max)
        over_load = min(edge + 0.5, load_max + 0.4)
        # [2026-09] When no runaway was found within the tested range, don't
        # assert "-> runaway to Sigma_crit" for over_load either -- it was
        # never actually confirmed to runaway, only that it's the highest
        # load examined. Let the trajectory itself show what it does instead
        # of a label that could be wrong.
        over_label = ("runaway to Σ_crit" if not no_runaway_found
                     else "hoogste geteste belasting (geen runaway bevestigd)")
        ex = [
            (safe_load, ZONE_COLOURS["safe"], "dead-zone (Σ stays 0)"),
            (edge_load, ZONE_COLOURS["danger"], "knife-edge (slow climb)"),
            (over_load, ZONE_COLOURS["emergency"], over_label),
        ]
        for R1, col, lab in ex:
            traj = PyroxModel(g).simulate([R1] * 22,
                                          pre_heatwave_heat_load=R1)["cumulative_strain"]
            ax2.plot(range(len(traj)), traj, color=col, lw=2.6,
                     label=f"R₁={R1:.2f}  → {lab}", marker="o", ms=3)
        ax2.axhline(crit, ls=":", color="grey", lw=1.1)
        ax2.text(0.3, crit - 0.06 * crit, "Σ_critical", fontsize=8.5,
                 color="grey", va="top")
        ax2.set_xlabel("day (constant load held fixed)", fontsize=10)
        ax2.set_ylabel("cumulative strain  Σ(t)", fontsize=10)
        ax2.set_title(f"{g.display_name} — time course", fontsize=11)
        ax2.set_ylim(-0.05, crit * 1.08)
        ax2.legend(loc="center right", fontsize=8, framealpha=0.95)

    fig.suptitle("PYROX — the three operating regimes",
                 fontsize=14, fontweight="bold", y=1.0)
    fig.text(0.5, 0.005,
             "Regime 2 (stable accumulation) is intrinsically narrow: once strain starts, the suppression gate amplifies it almost immediately. "
             "The model is near-binary (safe ↔ critical) — the sharp group separation seen in real heatwave data.",
             ha="center", fontsize=8, color="#555", style="italic")
    fig.tight_layout(rect=[0, 0.02, 1, 0.99])
    return fig


# ============================================================================
# 6. FORECAST UNCERTAINTY: strain with a ±temperature band
# ============================================================================

def plot_forecast_uncertainty(heat_loads: List[float],
                              group_names: List[str],
                              title: str,
                              dates: Optional[list] = None,
                              forecast_start: Optional[int] = None,
                              temp_uncertainty_c: float = 2.0,
                              pre_heatwave_load: Optional[float] = None) -> plt.Figure:
    """Strain trajectories with a forecast-uncertainty band.

    A forecast a few days out carries a temperature uncertainty of roughly
    ±2 °C. Because the weather→load bridge scales at HEAT_LOAD_PER_DEGREE per °C,
    that maps to a load uncertainty of ±(temp_uncertainty_c · 0.10). For each
    group this function runs three simulations — central, −Δ and +Δ — and shows
    the central strain with a shaded band between the low and high runs.

    Crucially, the uncertainty is applied ONLY to the forecast days
    (from `forecast_start` onward); the hindcast portion is observed data and
    carries no band. Where the band is narrow the warning is robust; where it is
    wide the outcome hinges on how the forecast resolves — exactly the
    distinction a decision-maker needs.
    """
    from thermopoulos_loader import HEAT_LOAD_PER_DEGREE

    loads = np.array(heat_loads, dtype=float)
    delta = temp_uncertainty_c * HEAT_LOAD_PER_DEGREE
    fc = forecast_start if forecast_start is not None else 0
    pre = pre_heatwave_load if pre_heatwave_load is not None else loads[0]

    def shifted(sign):
        out = loads.copy()
        out[fc:] = np.clip(out[fc:] + sign * delta, 0, None)
        return out.tolist()

    fig, ax = plt.subplots(figsize=(13, 6.5))

    # spread distinct colours across the chosen groups
    palette = ["#2563c9", "#e8702a", "#8a1010", "#1a8a4a", "#7a3fb0",
               "#c44d00", "#0d7d7d", "#a01010"]
    for i, name in enumerate(group_names):
        g = TARGET_GROUPS[name]
        col = palette[i % len(palette)]
        central = PyroxModel(g).simulate(shifted(0), pre_heatwave_heat_load=pre)["cumulative_strain"]
        low = PyroxModel(g).simulate(shifted(-1), pre_heatwave_heat_load=pre)["cumulative_strain"]
        high = PyroxModel(g).simulate(shifted(+1), pre_heatwave_heat_load=pre)["cumulative_strain"]
        x = np.arange(len(central))
        ax.fill_between(x, low, high, color=col, alpha=0.18)
        ax.plot(x, central, color=col, lw=2.3, label=g.display_name)

    # zone reference lines
    for y, key in [(1.0, "caution"), (1.5, "danger"), (1.8, "emergency")]:
        ax.axhline(y, ls="--", color=ZONE_COLOURS[key], lw=1, alpha=0.6)
        ax.text(len(loads) - 1, y, " " + key, color=ZONE_COLOURS[key],
                fontsize=8, va="bottom", ha="right")

    # forecast transition
    if forecast_start is not None:
        ax.axvline(forecast_start, color="#333", lw=1.4, alpha=0.7)
        ax.text(forecast_start, 2.05, " forecast →", fontsize=8, ha="left", color="#333")
        ax.text(forecast_start, 2.05, "← observed ", fontsize=8, ha="right", color="#333")

    # x-axis: real dates
    if dates is not None:
        step = max(1, len(dates) // 11)
        pos = list(range(0, len(dates), step))
        ax.set_xticks(pos)
        ax.set_xticklabels([str(dates[p])[:10] for p in pos],
                           rotation=45, ha="right", fontsize=8)
        ax.set_xlabel("date")
    else:
        ax.set_xlabel("day")

    ax.set_ylabel("cumulative strain  Σ")
    ax.set_title(f"{title}\nshaded band = ±{temp_uncertainty_c:.0f}°C forecast uncertainty; "
                 f"narrow = robust warning, wide = forecast-dependent")
    ax.set_ylim(-0.05, 2.15)
    ax.set_xlim(0, len(loads) - 1)
    ax.legend(loc="center left", fontsize=9, framealpha=0.95)
    fig.tight_layout()
    return fig


# ============================================================================
# build all four for both datasets
# ============================================================================

def _all_groups_resilient_to_vulnerable():
    return list(TARGET_GROUPS.keys())  # already ordered in pyrox_groups


def choose_groups_interactive(prompt: str = "regime plot") -> List[str]:
    """Interactive menu: list all groups and let the user pick one or several.

    Accepts comma/space separated numbers (e.g. "1,4,7"), "all", or blank to
    take a sensible default spread of groups. Returns a list of group keys.
    """
    keys = list(TARGET_GROUPS.keys())
    print(f"\nGroups available for the {prompt}:")
    print("-" * 56)
    for i, k in enumerate(keys, 1):
        print(f"  {i:>2}. {TARGET_GROUPS[k].display_name}")
    print("-" * 56)
    print("  Pick one or more (e.g. '1,4,7'), 'all', or ENTER for a default spread.")

    raw = input("Your choice: ").strip().lower()
    if raw == "all":
        return keys
    if raw == "":
        # default spread: resilient, mid, vulnerable
        default = ["adults_18_45", "elderly_65_85", "very_elderly_85plus"]
        return [d for d in default if d in TARGET_GROUPS]

    chosen = []
    for tok in raw.replace(",", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= len(keys):
            chosen.append(keys[int(tok) - 1])
    if not chosen:
        print("  No valid selection; using default spread.")
        return ["adults_18_45", "elderly_65_85", "very_elderly_85plus"]
    return chosen


def main():
    import os
    out = "plots"
    os.makedirs(out, exist_ok=True)

    # a representative subset for the line plots (too many lines is unreadable)
    subset = ["adults_18_45", "middle_aged_45_65", "elderly_65_85",
              "very_elderly_85plus", "dementia"]
    all_groups = _all_groups_resilient_to_vulnerable()

    from thermopoulos_loader import (ThermopoulosData, find_all_thermopoulos_files,
                                     choose_thermopoulos_file)

    datasets = {}

    # menu of cities present in the directory
    files = find_all_thermopoulos_files()
    if not files:
        print("No Thermopoulos_*.xlsx files found in this directory.")
        print("Generating only the Paris-2003 validation reference.\n")
    else:
        chosen = choose_thermopoulos_file()
        if chosen is not None:
            data = ThermopoulosData(chosen)
            city_key = data.city.lower().replace(" ", "_")
            if "Hindcast_14d" in data.available_sheets:
                combined = data.get_combined_window(hindcast_days=14, forecast_days=7)
                datasets[city_key] = {
                    "loads": combined["baseline_heat_load"].tolist(),
                    "label": f"{data.city} (14d hindcast + 7d forecast)",
                    "dates": [str(d) for d in combined["date"].tolist()],
                    "forecast_start": data.forecast_start_index(combined),
                }
            else:
                sheet = "Forecast_7d" if "Forecast_7d" in data.available_sheets else data.available_sheets[0]
                daily = data.get_daily_heat_loads(sheet)
                datasets[city_key] = {
                    "loads": daily["baseline_heat_load"].tolist(),
                    "label": f"{data.city} ({sheet})",
                    "dates": [str(d) for d in daily["date"].tolist()],
                    "forecast_start": None,
                }

    for key, d in datasets.items():
        loads, label = d["loads"], d["label"]
        dates, fc_start = d["dates"], d["forecast_start"]
        plot_strain_trajectories(loads, subset, f"Strain trajectories — {label}",
                                 dates=dates, forecast_start=fc_start
                                 ).savefig(f"{out}/1_strain_{key}.png", dpi=140)
        plot_feedback_race(loads, "very_elderly_85plus", label,
                           dates=dates, forecast_start=fc_start
                           ).savefig(f"{out}/2_feedback_{key}.png", dpi=140)
        plot_risk_heatmap(loads, all_groups, f"Risk timeline — {label}",
                          dates=dates, forecast_start=fc_start
                          ).savefig(f"{out}/4_heatmap_{key}.png", dpi=140)
        plt.close("all")
        print(f"  wrote 1_strain_{key}.png, 2_feedback_{key}.png, 4_heatmap_{key}.png")

    # validation plot (Paris reconstruction) — always available as a reference
    plot_paris_validation().savefig(f"{out}/3_validation_paris.png", dpi=140)
    plt.close("all")
    print(f"  wrote 3_validation_paris.png (Paris-2003 validation reference)")

    # control-theory regime plot — interactive group choice (one or more)
    print("\n--- Three-regimes plot ---")
    ans = input("Generate the three-regimes plot? [Y/n]: ").strip().lower()
    if ans in ("", "y", "yes"):
        groups = choose_groups_interactive("three-regimes plot")
        fname = "5_regimes_" + ("_".join(groups) if len(groups) <= 3
                                else f"{len(groups)}groups")
        plot_three_regimes(groups).savefig(f"{out}/{fname}.png", dpi=140,
                                           bbox_inches="tight")
        plt.close("all")
        print(f"  wrote {fname}.png  ({len(groups)} group(s))")

    # forecast-uncertainty plot — interactive group choice (one or more)
    # uses a dataset that has a forecast_start (i.e. a combined hindcast+forecast
    # window), since the band is applied to the forecast portion.
    unc_datasets = {k: d for k, d in datasets.items()
                    if d.get("forecast_start") is not None}
    if unc_datasets:
        print("\n--- Forecast-uncertainty plot ---")
        ans = input("Generate the forecast-uncertainty plot? [Y/n]: ").strip().lower()
        if ans in ("", "y", "yes"):
            # if several cities, pick one; otherwise take the only one
            if len(unc_datasets) == 1:
                ukey = next(iter(unc_datasets))
            else:
                keys = list(unc_datasets)
                print("Which city?")
                for i, k in enumerate(keys, 1):
                    print(f"  {i}. {unc_datasets[k]['label']}")
                sel = input(f"Choose (1-{len(keys)}): ").strip()
                ukey = keys[int(sel) - 1] if sel.isdigit() and 1 <= int(sel) <= len(keys) else keys[0]
            ud = unc_datasets[ukey]
            groups = choose_groups_interactive("forecast-uncertainty plot")
            fname = "6_uncertainty_" + ukey
            plot_forecast_uncertainty(
                ud["loads"], groups, f"Strain with forecast uncertainty — {ud['label']}",
                dates=ud["dates"], forecast_start=ud["forecast_start"],
                temp_uncertainty_c=2.0,
            ).savefig(f"{out}/{fname}.png", dpi=140, bbox_inches="tight")
            plt.close("all")
            print(f"  wrote {fname}.png  ({len(groups)} group(s), ±2°C band)")

    print(f"\nAll plots written to {out}/")


if __name__ == "__main__":
    main()
