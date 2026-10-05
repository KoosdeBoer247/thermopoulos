# -*- coding: utf-8 -*-
"""
Paris August 2003 — reference data for PYROX validation
================================================================================
Two series for the August-2003 French heatwave, used as PYROX's validation
anchor. Sources are cited per series; the distinction between RECONSTRUCTED
(weather) and OBSERVED (mortality) is kept explicit.

WEATHER (reconstructed daily Tmax)
----------------------------------
Reconstructed from the descriptions in Fouillet et al. (2006) and the AJPH 13-
cities study (Vandentorren et al. 2004): maxima rose from ~25 C (1 Aug, near
normal) to ~37 C by 5 Aug, held 36-37 C through 13 Aug (nine-day plateau), then
fell (28 C by 16 Aug). Paris ran slightly hotter and, crucially, nights stayed
> 23 C. These are representative daily maxima, NOT a station record; they are
adequate to drive PYROX but should not be quoted as measured values.

MORTALITY (observed daily excess deaths, France)
------------------------------------------------
From Fouillet et al. (2006), doi:10.1007/s00420-006-0089-4. Daily national
excess deaths: first significant deviation 4 Aug; 1193 on 8 Aug; peak 2200 on
12 Aug; 1943 on 13 Aug; 988 on 14 Aug; back to normal by 19 Aug. Cumulative
excess 1-20 Aug ~14,729 (+55%). The values between the cited anchor days are
linearly interpolated and marked as such — only the anchor days are reported
figures.
"""

from __future__ import annotations

import numpy as np

# Day index 1..16 corresponds to 1..16 August 2003.
PARIS_2003_DATES = list(range(1, 17))

# --- reconstructed daily maximum temperature (deg C) ------------------------
PARIS_2003_TMAX = [25, 30, 33, 37, 37, 37, 36, 37, 37, 37, 36, 37, 37, 33, 30, 28]

# representative summer values during the heatwave (dry, light wind)
PARIS_2003_RH = [50] * 16
PARIS_2003_WIND = [2.0] * 16

# --- observed daily excess deaths (France), Fouillet 2006 -------------------
# Anchor days with REPORTED figures (others interpolated):
#   4 Aug  -> first significant deviation (small, ~ a few hundred)
#   8 Aug  -> 1193
#   12 Aug -> 2200 (peak)
#   13 Aug -> 1943
#   14 Aug -> 988
#   >=19 Aug -> ~0 (back to normal)
_ANCHOR_DEATHS = {1: 0, 2: 0, 3: 0, 4: 300, 8: 1193, 12: 2200,
                  13: 1943, 14: 988, 16: 300, 19: 0}


def paris_2003_excess_deaths() -> np.ndarray:
    """Daily excess-death series for days 1..16, linearly interpolated between
    the Fouillet anchor days. Only the anchor days are reported figures; the
    rest are interpolation for curve-shape comparison, not data points."""
    days = np.array(PARIS_2003_DATES, dtype=float)
    anchor_days = np.array(sorted(_ANCHOR_DEATHS))
    anchor_vals = np.array([_ANCHOR_DEATHS[d] for d in anchor_days], dtype=float)
    return np.interp(days, anchor_days, anchor_vals)


def paris_2003_heat_loads(per_degree: float = 0.10,
                          reference_temp: float = 22.0) -> list:
    """Reconstructed Paris-2003 daily baseline_heat_load series, using the same
    bridge as thermopoulos_loader (apparent temp from Tmax/RH/wind)."""
    loads = []
    for t, rh, wind in zip(PARIS_2003_TMAX, PARIS_2003_RH, PARIS_2003_WIND):
        humidity_load = 0.05 * max(0.0, rh - 40.0)
        wind_relief = 0.3 * max(0.0, wind - 1.0)
        apparent = t + humidity_load - wind_relief
        loads.append(max(0.0, (apparent - reference_temp) * per_degree))
    return loads
