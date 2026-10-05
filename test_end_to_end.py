# -*- coding: utf-8 -*-
"""
End-to-end test of Klimatos main(): monkeypatches the two network functions
(geocoding + hourly fetch) with synthetic data, feeds scripted console input,
and verifies the whole run completes and writes the expected artefacts.

Uses a short year range so it finishes quickly; that is enough to exercise the
control flow, the event module, the plots and the Excel export.
"""
import builtins
import os
import sys
import numpy as np
import pandas as pd

import Klimatos_ClimateShift as K

# --- shrink the run so the test is fast -------------------------------------
K.START_YEAR = 1990
K.END_YEAR = 2025
K.REFERENCE_PERIOD = (1990, 1999)      # short stand-in baseline
K.EVENT_TREND_PERIOD = (2000, 2025)
K.EVENT_TARGET_YEARS = [2030, 2040]
K.WINDOW_LENGTH = 10
K.WINDOW_STEP = 10
K.ENABLE_LIVEABILITY = False           # HEAT-Lim is slow; covered separately
K.ENABLE_EHS_EVOLUTION = False         # This test predates the EHS module and is meant to
                                       # stay a fast wiring smoke test. EHS runs thousands
                                       # of physiology simulations and is covered by its own
                                       # tests; leaving it on turns a 30-second check into
                                       # an hour-long one, which defeats the purpose.
K.PROJECTION_YEARS = 10


def fake_geocode(city, max_results=7):
    return [{"name": "TestCity", "country": "NL", "latitude": 52.4,
             "longitude": 4.8, "timezone": "Europe/Amsterdam", "population": 150000}]


def fake_fetch(lat, lon, tz, year):
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h", tz="UTC")
    idx = idx.tz_convert(tz)
    n = len(idx)
    doy = idx.dayofyear.values
    hour = idx.hour.values
    rng = np.random.default_rng(year)
    warm = 0.04 * (year - 1990)
    t = (10 + 9 * np.sin(2 * np.pi * (doy - 100) / 365.0)
         + 4 * np.sin(2 * np.pi * (hour - 9) / 24.0) + warm + rng.normal(0, 1.5, n))
    return pd.DataFrame({
        "T_air_rural": t,
        "RH": np.clip(65 + rng.normal(0, 12, n), 15, 100),
        "pressure": 1013 + rng.normal(0, 4, n),
        "wind_10m": np.clip(rng.gamma(2, 1.6, n), 0.3, 25),
        "solar_radiation": np.clip(600 * np.sin(np.pi * (hour - 6) / 12) *
                                   (0.6 + 0.4 * np.sin(2 * np.pi * (doy - 80) / 365)),
                                   0, None) + rng.normal(0, 15, n),
        "cloud_cover": np.clip(rng.normal(55, 25, n), 0, 100),
    }, index=idx)


K.geocode_city_candidates = fake_geocode
K.fetch_hourly_year = fake_fetch
K.REQUEST_PAUSE_S = 0.0

# scripted console answers: city, UHI, event y/n, name, date, time, duration,
# [MET pace prompt handled elsewhere via default], generate report y/n
answers = iter(["TestCity", "n", "y", "Dam tot Damloop", "22-09", "13:30", "", "100", "n"])
builtins.input = lambda prompt="": (lambda a: (print(f"{prompt}{a}"), a)[1])(next(answers))

os.makedirs("/home/claude/klimatos/e2e", exist_ok=True)
os.chdir("/home/claude/klimatos/e2e")

K.main()

print("\n" + "=" * 70)
print("ARTEFACT CHECK")
print("=" * 70)
files = sorted(os.listdir("."))
xlsx = [f for f in files if f.endswith(".xlsx")]
pngs = [f for f in files if f.endswith(".png")]
print(f"  xlsx : {xlsx}")
print(f"  pngs : {len(pngs)} files")
for want in ("plot_warming_stripes_T_air_max.png",
             "plot_event_T_air_event_trend.png",
             "plot_event_T_air_event_distributions.png",
             "plot_event_warming_stripes_T_air_event.png"):
    status = "OK " if want in pngs else "MISSING"
    print(f"  [{status}] {want}")
    assert want in pngs, f"{want} was not produced"

assert xlsx, "no Excel file written"
sheets = pd.ExcelFile(xlsx[0]).sheet_names
print(f"\n  Excel sheets: {sheets}")
assert "Event_Window" in sheets, "Event_Window sheet missing from the export"
ev_sheet = pd.read_excel(xlsx[0], sheet_name="Event_Window")
print(f"  Event_Window rows: {len(ev_sheet)}, cols include: "
      f"{[c for c in ev_sheet.columns if 'projected' in c]}")
assert len(ev_sheet) == 3, f"expected 3 event variables, got {len(ev_sheet)}"

print("\n" + "=" * 70)
print("END-TO-END TEST PASSED")
print("=" * 70)
