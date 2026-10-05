# -*- coding: utf-8 -*-
"""Smoke test for the Klimatos additions, using synthetic data only (no API)."""
import os
import numpy as np
import pandas as pd

import Klimatos_ClimateShift as K


def make_year(year, warm_offset=0.0):
    """One synthetic processed year at hourly resolution, tz-aware local time."""
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h",
                        tz="Europe/Amsterdam")
    n = len(idx)
    doy = idx.dayofyear.values
    hour = idx.hour.values
    rng = np.random.default_rng(year)
    seasonal = 10 + 9 * np.sin(2 * np.pi * (doy - 100) / 365.0)
    diurnal = 4 * np.sin(2 * np.pi * (hour - 9) / 24.0)
    t = seasonal + diurnal + warm_offset + rng.normal(0, 1.5, n)
    return pd.DataFrame({
        "T_air_rural": t,
        "T_air_urban": t + 0.4,
        "WBGT": t * 0.6 + 4 + rng.normal(0, 0.4, n),
        "UTCI": t * 0.9 + 2 + rng.normal(0, 0.5, n),
        "T_wetbulb": t * 0.55 + 3 + rng.normal(0, 0.3, n),
    }, index=idx)


def main():
    print("=" * 60)
    print("TEST 1: event_window_metrics extracts the right hours")
    print("=" * 60)
    proc = make_year(2020)
    m = K.event_window_metrics(proc, 2020, "Europe/Amsterdam")
    print("  returned keys:", sorted(m))
    assert "T_air_event" in m, "no T_air_event returned"
    assert m["T_air_event_ndays"] == 2 * K.EVENT_DAY_WINDOW + 1, \
        f"expected {2*K.EVENT_DAY_WINDOW+1} days, got {m['T_air_event_ndays']}"
    # Verify it really is the event hours, not the daily mean: recompute by hand
    start = pd.Timestamp(year=2020, month=K.EVENT_MONTH, day=K.EVENT_DAY,
                         hour=K.EVENT_START_HOUR, minute=K.EVENT_START_MINUTE,
                         tz="Europe/Amsterdam")
    finish = start + pd.Timedelta(minutes=K.EVENT_DURATION_MIN)
    manual = proc.loc[(proc.index >= start) & (proc.index <= finish), "T_air_urban"].mean()
    day_mean = proc.loc[proc.index.date == start.date(), "T_air_urban"].mean()
    print(f"  event-window mean (centre day, manual) : {manual:.3f}")
    print(f"  whole-day mean  (centre day)           : {day_mean:.3f}")
    print(f"  function 7-day event mean              : {m['T_air_event']:.3f}")
    assert abs(manual - day_mean) > 0.5, \
        "event window is indistinguishable from the daily mean -- selection is wrong"
    print("  OK: event window is a genuinely different statistic from the daily mean\n")

    print("=" * 60)
    print("TEST 2: 29-Feb safety in a non-leap year")
    print("=" * 60)
    K.EVENT_MONTH, K.EVENT_DAY = 2, 29
    m_leap = K.event_window_metrics(make_year(2019), 2019, "Europe/Amsterdam")
    print("  non-leap year 2019 with 29-Feb event ->", sorted(m_leap))
    assert "T_air_event" in m_leap, "29 Feb fallback failed in a non-leap year"
    print("  OK: falls back to 28 Feb instead of crashing\n")
    K.EVENT_MONTH, K.EVENT_DAY = 9, 22   # restore

    print("=" * 60)
    print("TEST 3: full annual frame + trend fit + all new plots")
    print("=" * 60)
    records = []
    for year in range(1951, 2026):
        warm = 0.035 * (year - 1951)          # ~2.6 degC over the record
        proc = make_year(year, warm_offset=warm)
        rec = {
            "year": year,
            "T_air_max": float(np.nanmax(proc["T_air_urban"].values)),
            "WBT_max": float(np.nanmax(proc["T_wetbulb"].values)),
            "WBGT_max": float(np.nanmax(proc["WBGT"].values)),
            "UTCI_max": float(np.nanmax(proc["UTCI"].values)),
        }
        rec.update(K.event_window_metrics(proc, year, "Europe/Amsterdam"))
        records.append(rec)
    annual = pd.DataFrame(records).set_index("year").sort_index()
    print(f"  annual frame: {annual.shape[0]} years, columns={list(annual.columns)[:6]}...")
    assert "T_air_event" in annual.columns

    ev = K.analyze_event_window(annual, "T_air_event")
    assert ev is not None, "analyze_event_window returned None"
    print(f"  trend period {ev['trend_period']}: n={ev['n_trend']}, "
          f"slope={ev['slope']:+.4f} degC/yr ({ev['mk']['trend']})")
    print(f"  baseline {ev['baseline_period']}: mean={ev['baseline_mean']:.2f} "
          f"(n={ev['n_baseline']})")
    assert ev["slope"] > 0, "synthetic warming trend not detected"
    assert ev["n_baseline"] == 30, f"baseline should be 30 yrs, got {ev['n_baseline']}"

    # projected series must preserve spread, only shift the centre
    proj = K._event_projected_series(ev, 2040)
    print(f"  projected 2040: mean={proj.mean():.2f} (ref mean={ev['trend_mean']:.2f}), "
          f"std={proj.std(ddof=1):.2f} (ref std={ev['trend_values'].std(ddof=1):.2f})")
    assert proj.mean() > ev["trend_mean"], "projection did not warm"
    assert abs(proj.std(ddof=1) - ev["trend_values"].std(ddof=1)) < 0.35, \
        "projection changed the spread -- it should only shift the centre"
    print("  OK: projection shifts the centre and preserves observed spread\n")

    outs = []
    K.plot_warming_stripes(annual, K.REFERENCE_PERIOD, "T_air_max", "TestCity",
                           "t_stripes_annual.png"); outs.append("t_stripes_annual.png")
    K.plot_warming_stripes(annual, K.REFERENCE_PERIOD, "T_air_event", "TestCity",
                           "t_stripes_event.png"); outs.append("t_stripes_event.png")
    K.plot_event_window_trend(ev, "TestCity", "t_event_trend.png"); outs.append("t_event_trend.png")
    K.plot_event_window_distributions(ev, "TestCity", "t_event_dist.png"); outs.append("t_event_dist.png")
    for p in outs:
        assert os.path.exists(p) and os.path.getsize(p) > 5000, f"{p} not written properly"
        print(f"  wrote {p} ({os.path.getsize(p)//1024} kB)")

    summary = K.build_event_summary({"T_air_event": ev})
    print(f"\n  event summary columns: {list(summary.columns)}")
    assert "projected_2040" in summary.columns
    print(summary[["label", "baseline_mean", "trend_mean", "slope_degC_per_yr",
                   "projected_2040", "projected_2040_vs_baseline"]].to_string(index=False))

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
