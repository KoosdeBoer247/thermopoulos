# -*- coding: utf-8 -*-
"""
Suite smoke test
================================================================================
Exercises the whole integrated suite through REAL IMPORTS, end to end:

    Thermopoulos Excel
        -> thermopoulos_loader  (shared data source)
        -> run_pyrox            (population strain trajectories)
        -> run_hestia           (individual JOS-3 simulation)

Run with:   python suite_smoke_test.py
Needs a Thermopoulos_*.xlsx in the working directory. If none is present it
builds a small synthetic one so the test is self-contained.

This is NOT a scientific validation (that is verify.py for PYROX). It only
proves the plumbing is sound: real imports, no exec, no live API calls, both
models driven from one data source.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from thermopoulos_loader import ThermopoulosData, find_latest_thermopoulos_file


def build_synthetic_excel(path: str = "Thermopoulos_SmokeTest.xlsx") -> str:
    """Create a minimal Thermopoulos file matching the documented schema."""
    hours = pd.date_range("2026-08-01", periods=24 * 7, freq="h")
    day_peak = np.repeat(np.array([28, 30, 33, 36, 38, 37, 34]), 24)[:len(hours)]
    diurnal = 5 * np.sin(2 * np.pi * (hours.hour - 6) / 24)
    t_air = day_peak + diurnal - 5
    df = pd.DataFrame({
        "T_air_urban": t_air,
        "T_air_rural": t_air - 1.5,
        "RH": np.clip(70 - (t_air - 25) * 1.5, 25, 90),
        "pressure": 1013.0,
        "wind_10m": 2.5,
        "solar_radiation": np.clip(600 * np.sin(np.pi * (hours.hour - 6) / 12), 0, None),
        "cloud_cover": 20,
    }, index=hours)
    meta = pd.DataFrame([{
        "city": "SmokeTest", "country": "NL", "latitude": 52.0, "longitude": 5.0,
        "timezone": "Europe/Amsterdam", "population": 800000, "roughness_z0": 0.1,
        "model_version": "test", "processing_timestamp": "2026-08-01",
    }])
    with pd.ExcelWriter(path) as writer:
        df.to_excel(writer, sheet_name="Forecast_7d")
        meta.to_excel(writer, sheet_name="Metadata", index=False)
    return path


def main():
    print("=" * 70)
    print("SUITE SMOKE TEST — Thermopoulos -> PYROX + HESTIA (real imports)")
    print("=" * 70)

    latest = find_latest_thermopoulos_file()
    if latest is None:
        print("\nNo Thermopoulos file found; building a synthetic one.")
        latest = build_synthetic_excel()

    data = ThermopoulosData(latest)
    sheet = "Forecast_7d" if "Forecast_7d" in data.available_sheets else data.available_sheets[0]
    print(f"\nData source: {data.city}  (sheet '{sheet}')")

    # ---- PYROX half -------------------------------------------------------
    print("\n[1/2] PYROX population assessment")
    from run_pyrox import assess_population, print_report
    report = assess_population(data, sheet=sheet,
                               group_names=["adults_18_45", "elderly_65_85",
                                            "very_elderly_85plus"])
    print_report(report)

    # ---- HESTIA half (individual) -----------------------------------------
    print("\n[2/3] HESTIA individual simulation (JOS-3 + CVR)")
    from run_hestia import simulate_individual_adult, summarize_individual
    daily = data.get_daily_heat_loads(sheet)
    start = f"{daily['date'].iloc[3]} 09:00"   # a hot day, late morning
    results = simulate_individual_adult(
        data, start_time=start, duration_hours=3.0,
        met_value=6.0, clo_value=0.4, age=70, sheet=sheet,
    )
    summary = summarize_individual(results)
    print(f"  70-year-old, 3 h at MET 6, start {start}:")
    for k, v in summary.items():
        vv = f"{v:.2f}" if isinstance(v, float) else v
        print(f"    {k:<22}: {vv}")

    # ---- HESTIA half (Monte Carlo) -----------------------------------------
    # [regression guard] The previous suite snapshot never exercised this path;
    # its monte_carlo_adult() wrapper was missing a required argument
    # (age_configuration) and raised TypeError on every call. This step exists
    # specifically so that class of bug cannot silently reappear. Kept small
    # (n=10, use_parallel=False) so the smoke test stays fast and deterministic
    # in constrained/sandboxed environments.
    print("\n[3/3] HESTIA Monte Carlo population (JOS-3 + CVR + control-failure)")
    from run_hestia import monte_carlo_adult
    all_results, mc_stats, results_df = monte_carlo_adult(
        data, start_time=start, duration_hours=3.0,
        met_value=6.0, clo_value=0.4, n_simulations=10,
        use_parallel=False, random_seed=42, sheet=sheet,
    )
    assert all_results is not None, "monte_carlo_adult returned None (population generation failed)"
    print(f"  n participants simulated : {len(all_results)}")
    print(f"  percent unliveable       : {mc_stats['percent_unliveable'][-1]:.1f}%")
    if 'collapse_intercept_kal' in mc_stats:
        print(f"  collapse intercept_kal   : {mc_stats['collapse_intercept_kal']:.3f}")
    if 'pct_control_failure_any' in mc_stats:
        print(f"  pct control-failure any  : {mc_stats['pct_control_failure_any']:.1f}%")

    print("\n" + "=" * 70)
    print("SMOKE TEST PASSED — PYROX + HESTIA (individual & Monte Carlo) ran")
    print("from one source, no exec, no API.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
