# -*- coding: utf-8 -*-
"""
PYROX — verification against the paper, and Section 4 reproduction
================================================================================
Run with:   python verify.py

Two jobs:
  1. Re-derive every update step by hand and assert the model agrees
     -> proves the code matches paper Section 2.2 / 3.
  2. Reproduce the qualitative Section 4 trajectory ordering with the corrected
     parameters and the thermal-equilibrium start
     -> proves the behaviour matches the paper's narrative.

Only dependency is numpy.
"""

from __future__ import annotations

import math
import numpy as np

from pyrox_model import (
    PyroxModel, DailyState, make_equilibrium_initial_state, exposure_signal,
    feedback_gain, equilibrium_strain,
    ACCLIMATIZATION_MEMORY_DAYS, EXPOSURE_SIGNAL_CENTER, HOMEOSTATIC_DRIVE_COEFFICIENT,
)
from pyrox_groups import TARGET_GROUPS, PAPER_PROTOTYPES, get_group


_failures = []


def check(name, condition, detail=""):
    tag = "  [PASS]" if condition else "  [FAIL]"
    print(f"{tag} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        _failures.append(name)


# ============================================================================
# PART 1 — the five update steps (paper Section 2.2)
# ============================================================================
def test_exposure_signal():
    """Step 1: exposure_signal = 1/(1+exp(-(load-1))), centred at 1.0."""
    for load in [0.0, 1.0, 3.0, 5.0]:
        expected = 1.0 / (1.0 + math.exp(-(load - EXPOSURE_SIGNAL_CENTER)))
        check(f"exposure_signal(load={load})",
              abs(exposure_signal(load) - expected) < 1e-9)
    check("exposure_signal centred at 1.0 (-> 0.5)",
          abs(exposure_signal(1.0) - 0.5) < 1e-12)


def test_causal_memory():
    """Step 1 + Step 6: stimulus uses PAST exposure only; today's signal is
    appended afterwards, so day-1 adaptation is zero from a cold memory."""
    model = PyroxModel(get_group('elderly_65_85'))
    state = DailyState(exposure_memory=[0.0] * ACCLIMATIZATION_MEMORY_DAYS)
    new_state, diag = model.advance_one_day(state, baseline_heat_load=5.0)
    check("day-1 acclimatization_potential = 0 (cold memory)",
          abs(diag["acclimatization_potential"]) < 1e-12)
    check("today's signal appended to memory tail",
          abs(new_state.exposure_memory[-1] - diag["exposure_signal"]) < 1e-12)


def test_suppression():
    """Step 2: suppression_factor = max(0, 1 - strength*strain), zero at critical."""
    g = get_group('elderly_65_85')
    model = PyroxModel(g)
    check("suppression at strain=1.0",
          abs(model.suppression_factor(1.0) - (1 - g.strain_suppression_strength)) < 1e-12)
    check("suppression = 0 at critical_strain",
          abs(model.suppression_factor(g.critical_strain)) < 1e-12)


def test_net_strain_input():
    """Step 3: net_strain_input = max(0, load*(1-acclim) - recovery_threshold)."""
    g = get_group('elderly_65_85')
    model = PyroxModel(g)
    expected = max(0.0, 3.0 * (1 - 0.2) - g.recovery_threshold)
    check("net_strain_input",
          abs(model.net_strain_input(3.0, 0.2) - expected) < 1e-12)
    check("net_strain_input floored at 0",
          model.net_strain_input(0.1, 0.9) == 0.0)


def test_strain_update():
    """Step 4: strain += net_input - recovery, bounded [0, critical]."""
    g = get_group('elderly_65_85')
    model = PyroxModel(g)
    strain_prev = 0.5
    expected_recovery = (g.base_recovery_rate * 1.0
                         * (1.0 + HOMEOSTATIC_DRIVE_COEFFICIENT * strain_prev))
    expected_strain = np.clip(strain_prev + 1.0 - expected_recovery, 0.0, g.critical_strain)
    check("daily_recovery",
          abs(model.daily_recovery(strain_prev, 1.0) - expected_recovery) < 1e-12)
    check("strain update",
          abs(model.update_strain(strain_prev, 1.0, 1.0) - expected_strain) < 1e-12)
    check("strain upper bound = critical_strain",
          abs(model.update_strain(g.critical_strain, 10.0, 0.0) - g.critical_strain) < 1e-12)


def test_final_risk():
    """Step 5: final_risk = load*(1-acclim)*(1 + amplification*strain)."""
    g = get_group('elderly_65_85')
    model = PyroxModel(g)
    expected = 3.0 * (1 - 0.2) * (1 + g.strain_amplification * 1.0)
    check("final_risk", abs(model.final_risk(3.0, 0.2, 1.0) - expected) < 1e-12)


# ============================================================================
# PART 2 — stability analysis (paper Section 3)
# ============================================================================
def test_critical_strain():
    """Sec 3.3: critical_strain = 1/strength; default 0.5 -> 2.0."""
    for name in PAPER_PROTOTYPES:
        g = TARGET_GROUPS[name]
        check(f"critical_strain {name}",
              abs(g.critical_strain - 1.0 / g.strain_suppression_strength) < 1e-12,
              f"= {g.critical_strain:.2f}")


def test_feedback_gain_sign():
    """Sec 3.2: gain sign governs stability."""
    g = get_group('very_elderly_85plus')
    hot = feedback_gain(g, 3.0, g.max_acclimatization_capacity)
    cold = feedback_gain(g, 0.0, 0.0)
    check("feedback gain positive under strong forcing", hot > 0, f"{hot:.3f}")
    check("feedback gain negative without forcing", cold < 0, f"{cold:.3f}")


# ============================================================================
# PART 3 — corrected parameter table (validation anchor)
# ============================================================================
def test_corrected_table():
    """Sec 2.3 with documented capacity/threshold correction; other columns verbatim."""
    table = {
        'adults_18_45':        dict(max_acclimatization_capacity=0.80, recovery_threshold=1.5,
                                    base_recovery_rate=0.30, strain_suppression_strength=0.5,
                                    strain_amplification=0.3),
        'elderly_65_85':       dict(max_acclimatization_capacity=0.45, recovery_threshold=0.8,
                                    base_recovery_rate=0.18, strain_suppression_strength=0.5,
                                    strain_amplification=0.3),
        'very_elderly_85plus': dict(max_acclimatization_capacity=0.25, recovery_threshold=0.5,
                                    base_recovery_rate=0.12, strain_suppression_strength=0.5,
                                    strain_amplification=0.3),
    }
    for name, expected in table.items():
        g = TARGET_GROUPS[name]
        for fld, val in expected.items():
            check(f"{name}.{fld}", abs(getattr(g, fld) - val) < 1e-9,
                  f"got {getattr(g, fld)}, expected {val}")


def test_protective_monotonicity():
    """The whole point of the correction: all protective parameters descend
    together along young -> older -> vulnerable."""
    young = TARGET_GROUPS['adults_18_45']
    older = TARGET_GROUPS['elderly_65_85']
    vuln = TARGET_GROUPS['very_elderly_85plus']
    check("capacity descends with frailty",
          young.max_acclimatization_capacity > older.max_acclimatization_capacity
          > vuln.max_acclimatization_capacity)
    check("recovery_threshold descends with frailty",
          young.recovery_threshold > older.recovery_threshold > vuln.recovery_threshold)
    check("recovery_rate descends with frailty",
          young.base_recovery_rate > older.base_recovery_rate > vuln.base_recovery_rate)


# ============================================================================
# PART 4 — Section 4 behaviour (qualitative reproduction)
# ============================================================================
def test_section4(heatwave_load=1.3, pre_heatwave_load=1.0):
    """
    14-day heatwave, ideal sleep, initial strain 0.1.

    Deviations from the paper's literal Section 4 setup, both forced by analysis
    and agreed with the author:
      - heat load lowered from 3.0 (at 3.0 the day-1 net input alone exceeds
        critical_strain for every group, so no group can stabilise). A load of
        ~1.3 reproduces the paper's three divergent trajectories: young
        stabilises, older accumulates but stays below critical, vulnerable
        approaches critical.
      - thermal-equilibrium start at pre_heatwave_load (not a cold start).

    Checks the qualitative claims (the paper reports approximate days):
      young stabilises safely; vulnerable is most strained and enters danger;
      older sits in between.
    """
    loads = [heatwave_load] * 14
    results = {}
    for name in PAPER_PROTOTYPES:
        model = PyroxModel(TARGET_GROUPS[name])
        results[name] = model.simulate(loads, pre_heatwave_heat_load=pre_heatwave_load)

    young = results['adults_18_45']
    older = results['elderly_65_85']
    vuln = results['very_elderly_85plus']

    check("young stabilises below half-critical",
          young['peak_strain'] < 0.5 * young['critical_strain'],
          f"peak={young['peak_strain']:.3f}, critical={young['critical_strain']:.1f}")
    check("strain ordering vulnerable >= older >= young",
          vuln['peak_strain'] >= older['peak_strain'] >= young['peak_strain'],
          f"{vuln['peak_strain']:.3f} >= {older['peak_strain']:.3f} >= {young['peak_strain']:.3f}")
    check("vulnerable enters danger zone",
          vuln['danger_day'] is not None, f"danger_day={vuln['danger_day']}")

    return results


# ============================================================================
# PART 5 — invariants for all 23 groups
# ============================================================================
def test_all_groups():
    loads = [2.0] * 20
    kernels_ok = bounds_ok = acclim_ok = True
    for g in TARGET_GROUPS.values():
        if abs(g.exposure_memory_weights.sum() - 1.0) > 1e-9:
            kernels_ok = False
        res = PyroxModel(g).simulate(loads, pre_heatwave_heat_load=1.0)
        if res['cumulative_strain'].min() < -1e-9 or res['cumulative_strain'].max() > g.critical_strain + 1e-9:
            bounds_ok = False
        if res['effective_acclimatization'].max() > g.max_acclimatization_capacity + 1e-9:
            acclim_ok = False
    check("all 23 memory kernels normalised", kernels_ok)
    check("all 23 strain trajectories within [0, critical]", bounds_ok)
    check("all 23 effective acclimatization <= capacity", acclim_ok)


# ============================================================================
def main():
    print("=" * 72)
    print("PYROX verification vs de Boer (2026) DOI 10.21203/rs.3.rs-8626369/v1")
    print("=" * 72)

    print("\n--- Part 1: update steps (Section 2.2) ---")
    test_exposure_signal(); test_causal_memory(); test_suppression()
    test_net_strain_input(); test_strain_update(); test_final_risk()

    print("\n--- Part 2: stability analysis (Section 3) ---")
    test_critical_strain(); test_feedback_gain_sign()

    print("\n--- Part 3: corrected parameter table (Section 2.3) ---")
    test_corrected_table(); test_protective_monotonicity()

    print("\n--- Part 4: Section 4 behaviour ---")
    results = test_section4()

    print("\n--- Part 5: invariants across all 23 groups ---")
    test_all_groups()

    print("\n" + "=" * 72)
    if _failures:
        print(f"RESULT: {len(_failures)} FAILED -> {_failures}")
    else:
        print("RESULT: all checks passed. Code matches the (corrected) paper.")
    print("=" * 72)

    print("\nSection 4 reproduction (14-day heatwave, load=1.3, pre-load=1.0):")
    print(f"{'group':<30}{'peak strain':>12}{'critical':>9}{'caution':>9}{'danger':>8}{'emerg':>7}")
    for name in PAPER_PROTOTYPES:
        r = results[name]
        print(f"{r['group'].display_name:<30}{r['peak_strain']:>12.3f}"
              f"{r['critical_strain']:>9.1f}{str(r['caution_day']):>9}"
              f"{str(r['danger_day']):>8}{str(r['emergency_day']):>7}")

    return 1 if _failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
