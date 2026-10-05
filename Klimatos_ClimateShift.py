# -*- coding: utf-8 -*-
"""
Klimatos.ClimateShift v1.5 - Climate-Shift Engine
==================================================

NEW IN v1.1
-----------
1. WARMING STRIPES ("streepjescode", plot_warming_stripes). One coloured bar
   per year, colour = anomaly vs the 1951-1980 baseline, no axes to read.
   Projected years are hatched and separated by a vertical rule so a naive
   extrapolation can never be mistaken for observed data.

2. EVENT WINDOW (ENABLE_EVENT_WINDOW). Answers a different question from the
   rest of this script: not "how hot did it get that year" but "is this fixed
   annual date still defensible" -- for a recurring event held on the same
   calendar date and start time each year. Per year it takes the MEAN over the
   event's own hours (start -> finish) across a +/-N day window, fits a
   Theil-Sen trend anchored on EVENT_TREND_PERIOD (default 1995-2025, kept
   separate from the 1951-1980 comparison baseline), and projects that trend to
   chosen target years. Costs NO extra API calls: it is extracted from the very
   same processed hourly years the annual-maxima analysis already fetches.

   Why the trend is fitted on the event's own hours rather than on daily or
   annual means: diurnal warming is not uniform (nights warm faster than
   afternoons in many temperate climates), so a whole-day trend can
   mis-estimate the warming that actually applies to, say, an afternoon start.

   NORMAL FITS ONLY in the event module, unlike everywhere else in this script,
   and that difference is deliberate rather than an inconsistency. The rest of
   the script analyses ANNUAL MAXIMA -- block maxima, for which GEV is the
   theoretically correct family and a normal fit is biased in exactly the tail
   that matters (see the epistemic note below). The event module analyses a
   MEAN over the event's hours, a sum-like statistic that the central limit
   theorem pushes toward normality, so the normal fit is appropriate there.
   Applying "normal only" to the annual maxima would be a step backwards; the
   two modules analyse genuinely different statistics.

NEW IN v1.2
-----------
3. EHS EVOLUTION (ENABLE_EHS_EVOLUTION, requires the HESTIA/PYROX suite
   alongside this script -- optional, degrades cleanly like HEATLim above if
   absent). Projects exertional-heat-stroke incidence for the event across
   target years, reported BOTH as an absolute Falmouth-calibrated rate per
   1000 participants AND as a ratio to the reference period (the ratio is the
   robust one: a systematic calibration error largely cancels in the
   quotient). Runs three trend variants (Sen's slope low/central/high) for an
   honest uncertainty band, and an EARLIER-START adaptation scenario at the
   same target years -- the actionable comparison: how much of the projected
   increase an organiser can remove with a measure that costs nothing.

   EHS, not EHE, and that is a measured finding, not a preference: at
   NW-European autumn event conditions the EHE criterion fires for zero
   participants in every scenario tested (reference and projected alike), so
   a ratio for it would be 0/0. EHS is continuous, calibrated, and steeply
   non-linear across exactly the range this kind of event lives in. EHE is
   still computed and reported, with an explicit "too rare to resolve" note
   when that is what the numbers say -- for events in hotter climates, where
   EHE may fire at non-trivial rates, the ratio and band would become
   meaningful and should be reported alongside EHS rather than omitted.

4. TREND ACCELERATION CHECK (ENABLE_ACCELERATION_CHECK, check_trend_
   acceleration). Tests whether the warming trend within the analysis period
   is one straight line or two lines with different slopes either side of a
   breakpoint, via Theil-Sen fits on each segment and a bootstrap confidence
   interval on the slope difference (no Gaussian-residual assumption, unlike a
   classical Chow test -- consistent with using Theil-Sen everywhere else in
   this script). Two modes: a FIXED breakpoint (when a location-specific prior
   motivates one -- e.g. the European aerosol dimming/brightening transition
   used for this Amsterdam analysis, breakpoint ~1980-2000) or a SCAN across
   every candidate breakpoint, for locations without that specific prior.

   WORKS ANYWHERE, BUT THE MECHANISM DOES NOT TRANSFER. The statistical test
   itself has no location-specific assumptions built in. The reason to expect
   a breakpoint around 1980-2000 is regional: aerosol pollution suppressed
   observed warming across Europe and North America until roughly 1980, then
   declining aerosols post-1980 (clean-air legislation) unmasked more of the
   underlying GHG signal (Wild et al.'s dimming/brightening literature). East
   and South Asia followed a different, later, still-ongoing trajectory
   (Chinese aerosols did not start declining until around 2013; Indian aerosol
   loading remains high); remote, maritime, or low-industrial locations may
   show no such signature at all, though a genuine slope change could still be
   present there for other reasons (ENSO/decadal-oscillation phase, local
   land-use change, urban heat island growth as a city expands). For other
   cities, leave ACCEL_BREAKPOINT_YEAR as None and let the scan look for
   whatever the data itself supports, rather than assuming this timeline.
   Scan mode is explicitly flagged as exploratory (multiple comparisons: the
   winning breakpoint's significance is optimistic relative to one chosen in
   advance) -- see the function's own docstring.

NEW IN v1.3
-----------
5. UHI HUMIDITY FIX (adjust_rh_for_uhi). Every UHI-on run before this version
   computed wet-bulb temperature, WBGT and UTCI from the UHI-elevated urban
   air temperature paired with the UNCHANGED rural relative humidity. Since
   saturation vapor pressure rises with temperature, "same RH% at a higher
   temperature" silently means more actual water vapor in the air -- exactly
   backwards from how a real urban heat island behaves (reduced vegetation
   and evapotranspiration push cities toward hotter AND relatively DRIER, not
   hotter at unchanged RH%). Found by inspecting an implausible WBT_max
   result (28.2 degC, UHI on) in a real Amsterdam run: a 25 degC/55% rural
   reading with a +5 degC nighttime UHI bump gave a wet-bulb temperature 2.5
   degC too high under the old approach.

   Fixed by holding the rural air's actual water vapor content (vapor
   pressure) fixed instead of its RH%, and deriving the correspondingly lower
   RH_urban at the elevated temperature -- itself a simplification (a real UHI
   often reduces absolute humidity somewhat further, since less
   evapotranspiration also means less moisture entering the urban air to
   begin with), but no longer backwards. Affects every UHI-on run's WBT_max,
   WBGT_max, UTCI_max, event-window WBGT/UTCI, and the HEAT-Lim liveability
   module -- NOT the EHS-evolution module (Falmouth's regression uses only
   air temperature, never humidity) and NOT any UHI-off run (RH_urban ==
   RH exactly when UHI is off, verified).

NEW IN v1.4
-----------
6. CALIBRATED COLLAPSE-RISK ENDPOINT (COLLAPSE_ENDPOINT, default
   'hospitalisation'). EHE is a hard threshold (T_rect>39.5 AND CO_reserve<0):
   once nobody in a small ensemble crosses it, it reports exactly zero --
   indistinguishable from "truly impossible" even when the true underlying
   probability is small but real. hestia_model.py separately implements a
   calibrated two-phase logistic collapse-risk model (expected_collapses_
   per_1000 etc.) with a table of endpoints, each fit to reproduce a specific
   observed incidence rate -- including 'hospitalisation', calibrated
   directly against the 2024 Dam tot Damloop's own observed rate (50/35,000
   participants, GHOR Noord-Holland Noord). Unlike EHE, this has a calibrated
   BASELINE floor: even a scenario where nobody crosses a physiological
   trigger still reports that endpoint's calibrated background rate, not
   zero -- which is what let it answer a question EHE structurally cannot at
   mild conditions.

   This existed in hestia_model.py already but was invisible to Klimatos (and
   to every other caller of hestia_bridge.run_quick_estimate): the stats dict
   containing it was computed and then silently discarded. Two fixes were
   needed, not one: (a) hestia_bridge.py now merges those fields into the
   returned summary, and (b) the endpoint selection was threaded through as
   an explicit run_quick_estimate parameter rather than a bare hestia_model
   global -- confirmed by direct test that setting the global alone silently
   returned a STALE cached result, since Streamlit's cache_data keys only on
   a function's own arguments and has no visibility into an external global
   mutated outside of it.

   All COLLAPSE_ENDPOINTS entries are marked PROVISIONAL in hestia_model.py
   (fit at a reduced N=200, pending further clinical calibration) -- treat
   this as the best currently-available estimate for this event specifically,
   not a finished, externally validated number.

7. T_rect vs. CO_reserve RISK-ZONE SCATTER PLOT (plot_trect_co_reserve_
   scatter). Every sampled (T_rect, CO_reserve) pair, reference period vs.
   one target year's central-slope projection, with two shaded zones on the
   T_rect axis (>39.5 degC, EHE's own threshold; >40.5 degC, the stricter
   mechanistic threshold this codebase elsewhere calls clinical EHS) and
   points that meet EHE's actual conjunctive criterion (T_rect>39.5 AND
   CO_reserve<0) coloured separately. Costs no extra simulation: reads a
   field (t_rect_co_reserve_pairs) hestia_bridge.py already computed and
   returned, just never previously plotted here.

NEW IN v1.5
-----------
8. MARGIN-TO-THRESHOLD REPORTING (_ehe_margin_stats). A result of exactly
   zero on a hard threshold like EHE invites the question "how close did it
   actually come" -- unanswerable from the percentage alone. This reuses the
   same (T_rect, CO_reserve) pairs the v1.4 scatter plot collects (no extra
   simulation) and reports, per scenario: population-level percentiles per
   axis, and the single closest observed moment to actually triggering the
   criterion. Because EHE is a conjunctive (AND) criterion, "how close" is
   governed by whichever margin is still furthest from zero, not by either
   axis alone -- both must close simultaneously, so the harder-to-close one
   is the real bottleneck. Shown both in the console text and as an
   annotated marker directly on the scatter plot.

9. THE STRICTER "CLINICAL" CRITERION (T_rect>=40.5 AND CO_reserve<=0) is now
   also aggregated and reported, alongside EHE, with its own margin-to-
   threshold figures and its own marker on the scatter plot. This field
   already existed in hestia_bridge.py as pct_true_ehs_criterion -- note the
   naming collision in that file: it reuses "EHS", though it has nothing to
   do with the Falmouth-calibrated falmouth_ehs_per_1000 reported as EHS
   everywhere else in this script. It was already used as the red zone
   boundary on the v1.4 scatter plot but was never itself aggregated or
   reported as a rate -- referred to as the "clinical" criterion here to
   avoid perpetuating that collision in Klimatos' own output.

Standalone console-executable tool to CAPTURE CLIMATE CHANGE for any city,
expressed through the shifting distribution of ANNUAL MAXIMA of three
thermal variables:

    1. T_air_max   - annual maximum air temperature        [degC]
    2. WBT_max     - annual maximum wet-bulb temperature    [degC]
                     (Tw; thresholds from Vanos et al. 2023)
    3. WBGT_max    - annual maximum Wet-Bulb Globe Temp.    [degC]
    4. UTCI_max    - annual maximum Universal Thermal       [degC]
                     Climate Index

Method
------
For each calendar year (START_YEAR .. END_YEAR) hourly meteorological data is
fetched from the Open-Meteo Archive (ERA5 reanalysis) and run through the SAME
thermal-physics pipeline as the Thermopoulos data engine (solar position ->
globe temperature -> MRT -> wet bulb -> WBGT / UTCI). The annual maximum of
each variable is then taken, producing one value per year per variable.

These annual-maxima series are then analysed in OVERLAPPING 30-year windows
that slide forward in 10-year steps starting at 1980 (configurable), plus a
trailing window ending at the last complete year so the analysis reaches the
present. Per window and per variable we report:

    - mean and standard deviation of the annual maxima
    - the exceedance probability ("terugkeerkans") and return period for a set
      of temperature thresholds, computed TWO ways:
          (a) Normal fit   N(mu, sigma)              <- as requested; used in plots
          (b) GEV fit       genextreme(c, loc, scale) <- statistically correct
                                                         for block maxima

Plots
-----
Per variable: the fitted NORMAL distributions of all windows are overlaid on
one axis, with vertical lines at the thresholds, so the rightward (warming)
shift of the distribution is directly visible. A second figure compares the
Normal vs GEV fit for the most recent window.

IMPORTANT EPISTEMIC NOTE (read this)
------------------------------------
Annual maxima are *block maxima*. By the extreme-value theorem
(Fisher-Tippett-Gnedenko) they converge to a GENERALISED EXTREME VALUE (GEV)
distribution, NOT a normal distribution. The normal fit is provided because it
was explicitly requested and it gives an intuitive picture of the central
shift, but it is biased in the tails -- exactly where the 35 degC / 40 degC
return probabilities live. Always cross-check the GEV columns for tail
quantities. The plots show the normal fit; the GEV comparison figure shows how
much it differs.

URBAN HEAT ISLAND (UHI)
-----------------------
UHI is toggled at run time from the console (prompt after city selection); the
APPLY_UHI constant below only sets the default answer. For climate-change
DETECTION, OFF is the clean choice: a static population-based UHI increment
shifts the whole series up by a roughly constant amount and would conflate
urbanisation with climate change. Turn it ON to reproduce the urban
"lived-environment" values (all indices computed on T_air_urban). If the
location has no population, UHI cannot be applied and OFF is forced.

WET-BULB TEMPERATURE (WBT / Tw) THRESHOLDS
------------------------------------------
The WBT thresholds default to the physiology-based survivability limits of
Vanos et al. (2023, Nature Communications, doi:10.1038/s41467-023-43121-5),
who show the classic 35 degC Tw limit underestimates risk. Their limits are
CONDITION-DEPENDENT (the critical Tw depends on the air-temperature/humidity
split and on age/sun exposure), so representing them as fixed WBT thresholds is
a deliberate simplification - use them as reference markers, not hard cutoffs.

Author: Koos de Boer
Derived from Thermopoulos.Meteodata v3.1 thermal pipeline.
"""

import os
import sys
import time
import logging
from datetime import datetime
from typing import List, Dict, Optional, Tuple

import requests
import numpy as np
import pandas as pd
import pvlib

import matplotlib
matplotlib.use("Agg")          # headless / console-safe backend
import matplotlib.pyplot as plt

from scipy import stats

# Pythermalcomfort imports
from pythermalcomfort.models import wbgt, utci

# [2026-09] Pace -> MET conversion using the ACSM metabolic equations directly,
# replacing an earlier linear approximation (0.733 * speed_kmh) that was fit
# to agree with this file's own EHS_MET_VALUE anchor rather than derived from
# a physiological model -- the file's own prior comment already flagged that
# the ACSM equation gives a "noticeably higher MET" at the same pace, which
# is now resolved by using ACSM directly instead of working around it.
#   Running (ACSM, valid ~>=8 km/h / faster than ~7:30 min/km):
#     VO2 (mL/kg/min) = 0.2 * speed(m/min) + 3.5
#   Walking (ACSM, used as a floor for slower recreational pace inputs):
#     VO2 (mL/kg/min) = 0.1 * speed(m/min) + 3.5
# MET = VO2 / 3.5. Result is clipped to [2.0, 16.0] for numerical safety,
# matching the previous function's bounds.
# [2026-09] matplotlib >=3.8 returns a QuadContourSet from contourf() that no
# longer exposes `.collections` (removed API) -- older versions still return
# a list of PathCollections there. This sets the hatch edge colour either
# way, since contourf(colors="none", hatches=[...]) needs an explicit
# edgecolor or the hatch strokes don't render at all (only the -- here
# intentionally transparent -- fill is drawn).
def _set_hatch_edgecolor(contour_set, color: str) -> None:
    try:
        contour_set.set_edgecolor(color)
        contour_set.set_linewidth(0.0)
    except AttributeError:
        for coll in contour_set.collections:
            coll.set_edgecolor(color)
            coll.set_linewidth(0.0)


def _acsm_met_from_pace(pace_min_per_km: float) -> float:
    """Convert a running pace [min/km] to METs via the ACSM equations."""
    speed_kmh = 60.0 / pace_min_per_km
    speed_m_min = speed_kmh * 1000.0 / 60.0
    if speed_kmh >= 8.0:
        vo2 = 0.2 * speed_m_min + 3.5   # ACSM running equation
    else:
        vo2 = 0.1 * speed_m_min + 3.5   # ACSM walking equation (slow/back-of-field pace)
    met = vo2 / 3.5
    return round(max(2.0, min(16.0, met)), 1)

# Wet bulb: handle different library versions (same logic as Thermopoulos engine)
try:
    from pythermalcomfort.models import wet_bulb_temperature
    WET_BULB_FUNC = 'models'
except ImportError:
    try:
        from pythermalcomfort.utilities import wet_bulb_tmp as wet_bulb_temperature
        WET_BULB_FUNC = 'utilities'
    except ImportError:
        raise ImportError("Could not import a wet bulb temperature function.")

# HEAT-Lim (Vanos et al. 2023) for physiological liveability (Mmax). Optional:
# place HEATLim.py (MIT, from github.com/gguzmane/HEAT-Lim) next to this script.
# If absent, the liveability module is skipped and the rest still runs.
try:
    import HEATLim as HEATLIM
    HEATLIM_AVAILABLE = True
except Exception:
    HEATLIM_AVAILABLE = False

# HESTIA/PYROX (exertional heat-stroke dose-response, Falmouth-calibrated) for
# the EHS-evolution module. Optional, exactly like HEATLim above: place the
# PYROX suite files (hestia_bridge.py, hestia_model.py, HESTIA_CVR_Module_v2.py,
# HESTIA_ControlFailure_Module.py and their dependencies) next to this script.
# If absent, the EHS module is skipped and everything else still runs -- this
# script stays standalone.
try:
    import concurrent.futures as _futures
    from klimatos_ehs_worker import evaluate_scenario_year
    import hestia_bridge as _hestia_probe      # import-check only
    del _hestia_probe
    HESTIA_AVAILABLE = True
except Exception:
    HESTIA_AVAILABLE = False


# =============================================================================
# CONFIGURATION  (edit here)
# =============================================================================

START_YEAR      = 1980          # first year of the SLIDING-window analysis
END_YEAR        = None          # None -> last *complete* calendar year (current year - 1)
WINDOW_LENGTH   = 30            # length of each climate window [years]
WINDOW_STEP     = 5             # step by which the window slides [years]

# Fixed pre-warming reference/baseline period (inclusive), exactly 30 years and
# matching the NASA GISS convention. All sliding windows are reported as
# anomalies relative to this baseline, and it is drawn as a distinct reference
# curve in the plots. ERA5 in the Open-Meteo archive starts in 1940.
REFERENCE_PERIOD = (1951, 1980)

# Add an extra trailing window ending exactly at the last complete year, so the
# analysis reaches the present even when no stepped window lands on it. With a
# 5-yr step this would create a near-duplicate of the last stepped window
# (e.g. 1995-2024 vs 1996-2025), so it defaults to False. Set True to include
# the present-day 30-yr normal as a separate window.
ADD_TRAILING_PRESENT_WINDOW = False

APPLY_UHI       = False         # DEFAULT answer for the console UHI prompt.
                                # False = clean climate signal (recommended for detection)

# Thresholds per variable for the exceedance/return-period analysis [degC].
# T_air uses the 30/35/40 you asked for. WBGT/UTCI defaults use recognised
# heat-stress category boundaries -- change them to whatever you prefer.
THRESHOLDS = {
    "T_air_max": [30.0, 35.0, 40.0],   # as requested
    "WBT_max":   [22.0, 26.0, 35.0],   # Vanos et al. 2023 survivability limits (Tw):
                                       #   22 ~ older-adult lower bound (hot-dry, ~21.9)
                                       #   26 ~ young-adult lower bound (hot-dry, ~25.8)
                                       #   35 = classic theoretical limit (humid upper bound ~34)
                                       # NB: true critical Tw is condition-dependent (see header)
    "WBGT_max":  [23.0, 28.0, 31.0],   # ~ moderate / high / extreme (sport/activity guidance)
    "UTCI_max":  [32.0, 38.0, 46.0],   # official UTCI: strong / very strong / extreme heat stress
}

VARIABLES = ["T_air_max", "WBT_max", "WBGT_max", "UTCI_max"]
VAR_LABEL = {
    "T_air_max": "Annual max air temperature",
    "WBT_max":   "Annual max wet-bulb temperature",
    "WBGT_max":  "Annual max WBGT",
    "UTCI_max":  "Annual max UTCI",
}

MIN_DAYS_PER_YEAR = 330         # a year with fewer valid hourly-day-equivalents is flagged
REQUEST_PAUSE_S   = 1.5         # pause between yearly API requests [s].
                                # Raised from 0.5 s after a real 75-year run hit
                                # HTTP 429 around year 40 and silently lost six
                                # consecutive years. Open-Meteo's limits are
                                # weighted by data volume, and one request here
                                # is a full year x 6 hourly fields (~50k values),
                                # so a "polite" half-second is not polite at this
                                # payload size. At 75 years the extra second per
                                # request costs ~1 minute total -- negligible
                                # against re-running because of a 429 storm.
                                # Backoff (see RATE_LIMIT_* below) is the safety
                                # net; this is the avoidance.

RETURN_PERIODS = [2, 5, 10, 20, 50, 100]   # x-grid for the return-level plot [years]
BOOTSTRAP_N    = 200            # bootstrap resamples for return-level confidence bands

# --- Trend projection (annual-year time series plots only) -------------------
# Extends the Theil-Sen trend line PROJECTION_YEARS beyond the last observed
# year, fanned out with Sen's slope 95% CI. This is a NAIVE LINEAR EXTRAPOLATION
# of the observed statistical trend - not a physical climate model projection
# and not an epidemiological forecast. Labelled as such on every plot it
# appears on. Applies only to true annual-year x-axis plots (timeseries_trend,
# admissions_timeseries, liveability_timeseries) - NOT to the window-based
# trajectory/anomaly plots, whose x-axis (window central year) lags well behind
# the last data year and would make a projection misleading.
ENABLE_TREND_PROJECTION = True
PROJECTION_YEARS        = 10    # years beyond the last observed year
PROJECTION_MIN_YEARS    = 8     # minimum years of data required to attempt it

# --- Warming stripes ("streepjescode") --------------------------------------
# One coloured bar per year, colour = anomaly of the annual maximum relative to
# the REFERENCE_PERIOD mean (Ed Hawkins' #ShowYourStripes idiom). Deliberately
# axis-free: it is the one figure in this script that a non-technical reader can
# take in without reading a scale. Projected years (if ENABLE_TREND_PROJECTION)
# are appended with hatching so they are visually distinguishable from observed
# years -- a projection must never look like data.
ENABLE_WARMING_STRIPES  = True
STRIPES_VARIABLE        = "T_air_max"   # which annual-maxima series to colour by
STRIPES_INCLUDE_PROJECTION = True       # append PROJECTION_YEARS hatched future bars

# --- Event window (fixed annual event: "is this date still defensible?") -----
# Analyses ONE fixed calendar date + start time each year (e.g. a marathon that
# is always held on 22 September at 13:30) instead of the annual maximum. This
# is a different statistic from everything else in this script: the annual
# maximum answers "how hot did it get that year", the event window answers "how
# hot was it during THIS event", which is what an organiser actually needs.
#
# Costs NO extra API calls: it is extracted from the very same processed hourly
# year that build_annual_maxima() already fetches.
#
# The trend is fitted on the mean over the event's OWN hours (start -> finish),
# not on the daily or annual mean, because diurnal warming is not uniform
# (nights warm faster than afternoons in many temperate climates), so a
# whole-day trend can mis-estimate the warming that applies to an afternoon
# start. EVENT_TREND_PERIOD is the anchor for the trend and all projections;
# REFERENCE_PERIOD (1951-1980) is used only as a comparison baseline.
ENABLE_EVENT_WINDOW  = True
EVENT_NAME           = "Dam tot Damloop"   # free text, used in titles/filenames
EVENT_MONTH          = 9
EVENT_DAY            = 22
EVENT_START_HOUR     = 13
EVENT_START_MINUTE   = 30
# [2026-09] Distance added so duration and pace can be derived from each other
# consistently -- previously EVENT_DURATION_MIN (100 min) and EHS_MET_VALUE's
# "~5:30 min/km" comment implied two different durations for the same event
# (5:30/km over 16.1km is 88.5 min, not 100) because the two constants were
# set independently and never cross-checked. Default matches Dam tot Damloop
# (10 Engelse mijl); change this first if repurposing the script for another
# event/distance.
EVENT_DIST_KM        = 16.1       # km -- race distance, start -> finish
EVENT_DURATION_MIN   = round(5.5 * EVENT_DIST_KM)   # = 89 min at the 5:30/km anchor pace below
EVENT_DAY_WINDOW     = 3          # +/- days around the date, to get enough samples
EVENT_TREND_PERIOD   = (1995, 2025)   # anchor for trend + projection (NOT 1951-1980)
EVENT_TARGET_YEARS   = [2030, 2035, 2040]   # projected years shown in the distribution plot
EVENT_VARIABLES      = ["T_air_event", "WBGT_event", "UTCI_event"]
EVENT_VAR_LABEL = {
    "T_air_event": "Event-window mean air temperature",
    "WBGT_event":  "Event-window mean WBGT",
    "UTCI_event":  "Event-window mean UTCI",
}

# --- Trend acceleration / breakpoint check -----------------------------------
# Tests whether the warming trend within the analysis period is a single
# straight line, or whether the slope itself changed partway through (e.g. the
# well-documented European "dimming to brightening" transition: aerosol
# pollution suppressed observed warming until roughly 1980, then declining
# aerosols post-1980 unmasked more of the underlying GHG signal -- Wild et al.).
#
# THE STATISTICAL TEST IS GENERIC; THE MECHANISM IS NOT. Aerosol-driven
# dimming/brightening is strongest for Europe and North America on roughly this
# timeline. East/South Asia followed a different, later, still-ongoing
# trajectory (Chinese aerosols did not start declining until around 2013;
# Indian aerosol loading remains high). Remote, maritime, or low-industrial
# locations may show little or no such signature, though a slope change can
# still be present there for other reasons (ENSO/decadal-oscillation phase,
# local land-use change, urban heat island growth as a city expands). For that
# reason ACCEL_BREAKPOINT_YEAR is not hardcoded to 1980-2000: leave it as None
# to let the data itself be scanned for the best-supported breakpoint, or set
# a specific year if you have a location-specific reason (as with Amsterdam,
# 1980, in this analysis).
ENABLE_ACCELERATION_CHECK = True
ACCEL_BREAKPOINT_YEAR   = None   # None = auto-scan; or an int, e.g. 1998
ACCEL_MIN_SEGMENT_YEARS = 10     # each side of the split needs at least this many years
ACCEL_N_BOOTSTRAP       = 1000   # bootstrap resamples per segment, for the slope-difference CI
ACCEL_VARIABLES         = ["T_air_max"]   # add "T_air_event" too if ENABLE_EVENT_WINDOW

# --- EHS evolution (requires the HESTIA/PYROX suite alongside this script) ---
# Projects how exertional-heat-stroke incidence for the event evolves, using the
# Falmouth-calibrated HESTIA dose-response. Reported BOTH as an absolute rate
# (defensible: EHS is calibrated against observed incidence) AND as a ratio to
# the reference period (robust: a systematic calibration error largely cancels
# in the quotient).
#
# Why EHS and not EHE: measured behaviour, not preference. At NW-European
# September conditions (event-window WBGT ~14-17) the EHE criterion fires for
# exactly zero participants in every year, projected years included, so a
# ratio would be 0/0; and where it does fire it is quantised in steps of 1/n
# because it counts individual participants. EHS is continuous, calibrated, and
# steeply non-linear across precisely the range this event lives in. EHE is
# still computed and reported, with an explicit "too rare to resolve" note when
# that is what the numbers say.
#
# EHS_ENSEMBLE_N is deliberately small: EHS was verified to be invariant to
# ensemble size and seed (identical to 4 decimal places at n=5, 10 and 20) --
# it is determined by the weather through the dose-response, not by the
# population sample. Only EHE uses the ensemble, and EHE cannot be resolved
# here anyway. A larger n therefore buys nothing but runtime.
ENABLE_EHS_EVOLUTION = True
EHS_ENSEMBLE_N       = 5          # see note above; do not raise "for accuracy"
# [2026-09] Was a hardcoded 8.0. Now derived from the same ACSM equation and
# the same 5:30 min/km anchor pace used for EVENT_DURATION_MIN above, so the
# two constants describe one consistent runner instead of two different ones
# (previously MET=8.0 corresponded to ACSM's own ~11.4 MET at that pace --
# see _acsm_met_from_pace's docstring note -- a ~30% discrepancy).
EHS_MET_VALUE        = _acsm_met_from_pace(5.5)   # median participant, ~5:30 min/km running
EHS_CLO_VALUE        = 0.2        # typical race kit
EHS_TARGET_YEARS     = [2030, 2035, 2040]
# Adaptation scenario: the same event, same year, started earlier in the day.
# This is the point of the module -- it shows how much of the projected
# increase an organiser can remove with a measure that costs nothing.
EHS_ADAPT_START_HOUR   = 9
EHS_ADAPT_START_MINUTE = 0
# Trend uncertainty: the projection is run at Sen's slope low / central / high,
# giving a band. The trend is the dominant uncertainty here, so this is the
# honest band to show. The adaptation scenario runs at the central slope only:
# it is there to show the size and direction of the lever, not its CI.
EHS_USE_SLOPE_BAND   = True
EHS_MAX_WORKERS      = None       # None -> cpu_count()//2 (HESTIA parallelises internally)
# Which hestia_model.COLLAPSE_ENDPOINTS entry the calibrated collapse-risk
# model uses (expected_collapses_per_1000 etc.) -- a smooth, individually-
# differentiated probability with a calibrated baseline, unlike EHE (a hard
# threshold that floors at exactly zero once nobody in the ensemble crosses
# it, however small the true underlying probability). 'hospitalisation' is
# the DtD-specific endpoint: calibrated to reproduce the 2024 Dam tot
# Damloop's own observed rate (50/35,000 hospital admissions, GHOR Noord-
# Holland Noord) rather than a different race's data. Every endpoint in the
# table is marked PROVISIONAL in hestia_model.py -- fit at a reduced N=200,
# pending further clinical calibration -- so treat this as the best
# currently-available estimate, not a finished, validated number. See
# hestia_model.py's COLLAPSE_ENDPOINTS table docstring for the full endpoint
# list, sources and status of each.
COLLAPSE_ENDPOINT    = "hospitalisation"

# --- Heat-attributable hospital-admissions ERF -------------------------------
# Exposure-response function from a NW-European (Dutch) population:
#   van Loenhout et al. (2018), BMC Public Health 18:108,
#   doi:10.1186/s12889-017-5021-1  - DLNM of urgent emergency-room admissions vs
#   DAILY MAXIMUM temperature (De Bilt), minimum-morbidity temperature 21 degC.
# The published paper reports spline-based scenario RRs, not the spline itself,
# so we implement a LOG-LINEAR APPROXIMATION anchored to a published point:
#   RR(T) = exp(beta * max(0, T - MMT)),  beta = ln(RR_anchor)/(T_anchor - MMT).
# Default anchor: RR = 1.19 at 32 degC (85+, 'potential heat-related diseases',
# single hot day, cumulative over lag) -> the high-vulnerability end. This is an
# APPROXIMATION of the original DLNM, not a reproduction of it.
ENABLE_ADMISSIONS_ERF = True
ERF_MMT_C   = 21.0                              # minimum-morbidity temperature [degC, daily max]
ERF_BETA_PER_C = np.log(1.19) / (32.0 - 21.0)   # ~0.0158 /degC (see anchor above)
ERF_MONTHS  = (5, 9)                            # apply over May-Sep (study window)
# NOTE: applied to regional/rural daily-max air temperature (matching the De Bilt
# station calibration), independent of APPLY_UHI.

# --- Physiological liveability (HEAT-Lim, Vanos et al. 2023) ------------------
# Mmax = maximum sustainable activity (METs) without net heat storage, computed
# per hour with the ORIGINAL HEAT-Lim biophysical model (validated bit-for-bit
# against the authors' published Mmax matrices). Runs on the URBAN air
# temperature (T_air_urban), so the console UHI toggle directly drives the
# urban-liveability result. Cite: Vanos et al. 2023 (doi:10.1038/s41467-023-43121-5)
# and the code (doi:10.5281/zenodo.10020136, MIT).
ENABLE_LIVEABILITY      = True
LIVEABILITY_EXP_TIME    = 3        # exposure window [h]; HEAT-Lim allows 1, 3, 6
LIVEABILITY_SUN         = "outdoor"  # 'outdoor' = use pipeline MRT (sun); 'shade' = MRT==Ta
LIVEABILITY_TA_MIN      = 25.0     # only evaluate hours with Ta >= this (HEAT-Lim applicability)
LIVEABILITY_MIN_WIND    = 0.5      # floor on 1.5 m air velocity [m/s]
LIVEABILITY_ACTIVITY_MET = 3.0     # 'liveable for normal activity' bar (~brisk walk / light chores)

# Personal profiles embedded verbatim from HEAT-Lim (personal_profiles/*_livability.txt)
LIVEABILITY_PROFILES = {
    "young": {"name": "18-40 years", "Mass": 56.2, "AD": 1.6, "Tsk_C": 35, "A_eff": 0.73,
              "Emm_sk": 0.98, "Icl": 0.36, "Re_cl": 0.01, "M": 1.8, "W": 0,
              "wmax_condition": "YNG_Morris_2021", "smax_rate": 0.75},
    "old":   {"name": "Over 65 years", "Mass": 73.9, "AD": 1.78, "Tsk_C": 35, "A_eff": 0.73,
              "Emm_sk": 0.98, "Icl": 0.36, "Re_cl": 0.01, "M": 1.8, "W": 0,
              "wmax_condition": "OLD_Morris_2021", "smax_rate": 0.51},
}
LIVEABILITY_PROFILE_LABEL = {"young": "Young adult (18-40)", "old": "Older adult (65+)"}

# =============================================================================
# TEST MODE -- one switch to make a full run finish in minutes, not hours
# =============================================================================
# Set TEST_MODE = True to shrink every cost driver at once, for checking that a
# run completes and the output looks sane before committing to a real one.
# Set it back to False for anything you intend to show anyone.
#
# WHAT IT COSTS YOU, honestly:
#   - one target year instead of three  -> no trajectory, just an end point
#   - no uncertainty band               -> a point estimate with no CI
#   - +/-1 day window instead of +/-3   -> 3 realisations per year, not 7:
#                                          noisier per year, still averaged
#                                          over the full trend period
#   - 200 bootstrap resamples, not 1000 -> coarser CI on the slope difference
#   - shorter record (1991 onward)      -> no 1951-1980 baseline comparison,
#                                          and a weaker acceleration check
#
# WHAT IT DELIBERATELY DOES NOT TOUCH, and why:
#   - EVENT_TREND_PERIOD stays at its full length. Shortening it looks like the
#     obvious saving (it is a linear factor on the cost) and it is the one
#     change that can silently invert your result: over ~10 years the Theil-Sen
#     slope is dominated by year-to-year noise rather than by the trend, and a
#     fitted slope of the wrong SIGN projects cooling into a warming climate.
#     This was observed, not assumed -- see the module history. A fast wrong
#     answer is worse than a slow right one.
#   - EHS_ENSEMBLE_N stays at 5. EHS is weather-determined and was verified
#     identical to four decimal places at n=5, 10 and 20, so there is nothing
#     to gain here and nothing to lose by leaving it.
#
# COST MODEL (realisations = the unit of runtime):
#     scenarios    = 2 + (4 if EHS_USE_SLOPE_BAND else 2) * len(EHS_TARGET_YEARS)
#     realisations = scenarios * len(trend period) * (2*EVENT_DAY_WINDOW + 1)
# Defaults: 2 + 4*3 = 14 scenarios * 31 years * 7 days = 3038 realisations.
# TEST_MODE: 2 + 2*1 =  4 scenarios * 31 years * 3 days =  372 realisations.
TEST_MODE = False

if TEST_MODE:
    EHS_TARGET_YEARS   = [2040]
    EHS_USE_SLOPE_BAND = False
    EVENT_DAY_WINDOW   = 1
    EVENT_TARGET_YEARS = [2040]
    ACCEL_N_BOOTSTRAP  = 200
    START_YEAR         = 1991
    REFERENCE_PERIOD   = (1991, 2020)
    print("\n" + "!" * 70)
    print("TEST_MODE IS ON -- reduced settings, results are for checking the run")
    print("completes, NOT for reporting. Set TEST_MODE = False for real output.")
    print("!" * 70)

# =============================================================================
# EHS/EHE STRESS TEST -- one switch to answer a narrower question than the
# main EHS module: under the most unfavourable STILL-PLAUSIBLE combination of
# assumptions, does the mechanistic EHE criterion ever fire at all for this
# event? Not a scenario to report as "the risk" -- a diagnostic to check
# whether EHE is reachable at all before concluding it never will be.
# =============================================================================
# Combines three levers that were each tried separately in this session
# without success (MET 8.0 default: zero; MET 9.8 with the trend band off:
# zero; MET 8.0 with the full band on, every scenario including the
# high-slope one: zero) but never all three together:
#   1. A genuinely fast pace (front-of-pack, not the median participant) --
#      pushed past the 9.8 already tried, since that alone was not enough.
#   2. The full slope-uncertainty band, so the hottest still-plausible trend
#      projection is tested, not just the central one.
#   3. A larger ensemble specifically for EHE. EHS does not need this (it was
#      verified invariant to ensemble size in this session), but EHE is a
#      rare-tail event -- one unlucky individual crossing both thresholds --
#      that a small ensemble can simply fail to sample even when the true
#      population-level probability is nonzero.
#   4. Only the single hottest target year is run (not the full set), since
#      the extra ensemble size already multiplies the cost of each one.
#
# Overrides EHS_MET_VALUE regardless of what the console pace prompt was
# answered -- see the explicit note main() prints when this happens, so an
# overridden answer is never silently different from what was typed.
ENABLE_EHS_STRESS_TEST  = False
STRESS_TEST_MET         = 12.5   # ~3:30/km -- genuinely fast, front-of-pack
STRESS_TEST_ENSEMBLE_N  = 40     # only EHE benefits from this; EHS does not
STRESS_TEST_TARGET_YEAR = None   # None -> the latest year in EHS_TARGET_YEARS

if ENABLE_EHS_STRESS_TEST:
    if STRESS_TEST_TARGET_YEAR is None:
        STRESS_TEST_TARGET_YEAR = max(EHS_TARGET_YEARS) if EHS_TARGET_YEARS else 2040
    EHS_TARGET_YEARS = [STRESS_TEST_TARGET_YEAR]
    EHS_USE_SLOPE_BAND = True
    EHS_ENSEMBLE_N = STRESS_TEST_ENSEMBLE_N
    print("\n" + "~" * 70)
    print("EHS/EHE STRESS TEST IS ON -- MET, ensemble size and target year are")
    print(f"forced to worst-case-but-plausible values (MET={STRESS_TEST_MET}, "
          f"n={STRESS_TEST_ENSEMBLE_N}, year={STRESS_TEST_TARGET_YEAR}).")
    print("This is a diagnostic for whether EHE is reachable AT ALL, not a")
    print("scenario to report as 'the risk'. Set ENABLE_EHS_STRESS_TEST = False")
    print("for real output.")
    print("~" * 70)

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _safe_plot(func, *args, **kwargs):
    """
    Call a plot_*() function defensively.

    [2026-09-05] Added after a real, hard-to-reproduce failure: a full run
    (75 years of archive data, 3+ minutes, not cached -- a re-run repeats
    the whole fetch) crashed with OSError [Errno 22] Invalid argument while
    saving the LAST of several plot files, from a plain, unremarkable
    relative filename. The two plots saved immediately before it, in the
    same directory, in the same loop iteration, succeeded -- pointing to a
    one-off, transient environmental hiccup (most likely antivirus
    real-time scanning or cloud-sync briefly locking that one freshly
    created file) rather than a deterministic bug in this code; the same
    script had already run successfully once before with no changes.

    Whatever the exact cause, a single failed plot should never discard a
    multi-minute run's worth of already-computed results. This wraps any
    plot_*() call so one failure is logged as a skipped plot and main()
    continues -- every other plot, and the underlying data/report
    generation, are unaffected. The existing `if os.path.exists(p):`
    checks after each call already handle "this file wasn't created"
    gracefully; the missing piece was stopping the exception from
    propagating up and aborting the whole run before reaching that check.
    """
    try:
        func(*args, **kwargs)
    except Exception as e:
        logger.warning(f"Plot '{getattr(func, '__name__', str(func))}' failed and was skipped: {e}")

# =============================================================================
# Geocoding  (ported from Thermopoulos engine)
# =============================================================================

def geocode_city_candidates(city: str, max_results: int = 7) -> List[Dict]:
    """Geocode a city name to a list of candidate locations."""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city, "count": max_results, "language": "en", "format": "json"}
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.error(f"Geocoding failed: {e}")
        raise
    if "results" not in data:
        raise ValueError(f"No locations found for '{city}'.")
    return data["results"]


def select_city(candidates: List[Dict]) -> Dict:
    """Interactive selection from multiple geocoding candidates."""
    print("\nMultiple locations found:\n")
    for i, c in enumerate(candidates, start=1):
        print(f"[{i}] {c['name']}, {c.get('country', 'Unknown')} "
              f"({c.get('admin1', '')}) - Pop: {c.get('population', 'unknown')}")
    while True:
        try:
            choice = int(input(f"\nSelect location [1-{len(candidates)}]: "))
            if 1 <= choice <= len(candidates):
                return candidates[choice - 1]
        except ValueError:
            pass
        print("Invalid selection.")

# =============================================================================
# Hourly archive fetch (one calendar year at a time)
# =============================================================================

FETCH_MAX_RETRIES = 3           # retries if the archive returns an incomplete/null field
FETCH_RETRY_PAUSE_S = 2.0       # pause between retries [s]

# --- Rate limiting (HTTP 429) ------------------------------------------------
# A long run asks the archive for one full year of six hourly fields at a time,
# 45-75 times in a row. Open-Meteo enforces short-window rate limits, so a burst
# like that can start returning 429 partway through even when each individual
# request is fine.
#
# This is handled separately from FETCH_MAX_RETRIES above, because the two
# failure modes want opposite treatment. A null/incomplete field is a transient
# backend glitch: retry quickly (2 s) and move on. A 429 means the server is
# explicitly telling us to slow down: retrying quickly makes it strictly worse,
# and in fact a rejected request comes back FASTER than a successful one (no
# payload to transfer), so a naive loop accelerates exactly when it should back
# off. Hence exponential backoff, and Retry-After honoured when the server
# sends it.
#
# Getting this wrong is not a cosmetic problem: before this was added, a 429
# propagated out of fetch_hourly_year(), the caller logged "Year NNNN skipped",
# and the run continued -- silently dropping consecutive years out of the middle
# of the reference period and quietly weakening every trend fitted on it.
RATE_LIMIT_MAX_RETRIES = 4      # attempts after the first 429 before giving up on a year
RATE_LIMIT_BASE_WAIT_S = 60.0   # first backoff wait [s]; doubles each attempt
RATE_LIMIT_MAX_WAIT_S = 900.0   # cap on any single wait [s]

REQUIRED_HOURLY_FIELDS = ["temperature_2m", "relative_humidity_2m", "surface_pressure",
                          "wind_speed_10m", "shortwave_radiation", "cloud_cover"]


# --- Progress output ---------------------------------------------------------
# Progress lines are written with a carriage return so one line is rewritten in
# place -- which is right in a real terminal and wrong almost everywhere else.
# Spyder's console, most IDEs, piped output and log files either swallow the
# rewrite entirely (so a long run looks silent and hung, which is exactly what
# the progress line existed to prevent) or leave stray blanks behind.
#
# So: rewrite in place only when stdout is a real TTY, and otherwise print
# ordinary lines. Verbose is strictly better than invisible for a run measured
# in tens of minutes. IS_TTY is resolved once, at import, because stdout does
# not change identity mid-run and re-checking per update is pure overhead.
try:
    IS_TTY = bool(sys.stdout.isatty())
except Exception:      # some redirected streams have no isatty at all
    IS_TTY = False

# In a non-TTY, printing every single update would flood the log, so updates
# are thinned to roughly this interval instead.
PROGRESS_MIN_INTERVAL_S = 15.0
_last_progress_emit = {"t": 0.0}


def progress(msg: str, force: bool = False) -> None:
    """One progress update. Rewrites the current line on a TTY; prints a plain
    line otherwise (rate-limited, so a long run does not bury the real output).
    `force=True` always emits -- use it for the final update of a phase."""
    if IS_TTY:
        print(f"\r{msg}   ", end="", flush=True)
        return
    now = time.time()
    if force or (now - _last_progress_emit["t"]) >= PROGRESS_MIN_INTERVAL_S:
        _last_progress_emit["t"] = now
        print(msg, flush=True)


def progress_done() -> None:
    """Finish a progress phase: clear the rewritten line on a TTY, no-op
    elsewhere (where each update was already its own line)."""
    if IS_TTY:
        print("\r" + " " * 78 + "\r", end="", flush=True)


def _sleep_with_countdown(seconds: float, reason: str) -> None:
    """Sleep, showing a live countdown on one rewritten line.

    A silent multi-minute wait is indistinguishable from a hung script, and
    these waits are deliberately long -- so the wait is made visible rather
    than leaving the user guessing whether to kill the run."""
    seconds = max(0.0, float(seconds))
    end = time.time() + seconds
    while True:
        left = end - time.time()
        if left <= 0:
            break
        mins, secs = divmod(int(left) + 1, 60)
        progress(f"    {reason} - resuming in {mins:d}:{secs:02d}")
        time.sleep(min(1.0, left))
    progress_done()


def _get_with_rate_limit_retry(url: str, params: Dict, year: int) -> "requests.Response":
    """GET with exponential backoff on HTTP 429, honouring Retry-After.

    Raises the underlying HTTPError if the rate limit persists past
    RATE_LIMIT_MAX_RETRIES, so the caller's existing skip-and-continue path
    still applies as a last resort -- but only after genuinely waiting, rather
    than instead of waiting.
    """
    wait = RATE_LIMIT_BASE_WAIT_S
    for attempt in range(1, RATE_LIMIT_MAX_RETRIES + 2):   # first try + retries
        response = requests.get(url, params=params, timeout=120)
        if response.status_code != 429:
            response.raise_for_status()
            return response

        if attempt > RATE_LIMIT_MAX_RETRIES:
            print(f"\n  [rate limit] Year {year}: still 429 after "
                  f"{RATE_LIMIT_MAX_RETRIES} backoff attempts - giving up on this year "
                  f"(it will be listed as MISSING in the summary below)", flush=True)
            logger.warning(f"Year {year}: still rate-limited after "
                           f"{RATE_LIMIT_MAX_RETRIES} backoff attempts; giving up on this year.")
            response.raise_for_status()   # raises HTTPError, caller handles

        # Retry-After may be seconds or an HTTP-date; only the numeric form is
        # used, since the date form needs clock-skew handling for no real gain.
        retry_after = response.headers.get("Retry-After")
        this_wait = wait
        if retry_after is not None:
            try:
                this_wait = max(float(retry_after), 1.0)
            except (TypeError, ValueError):
                pass
        this_wait = min(this_wait, RATE_LIMIT_MAX_WAIT_S)

        src = "server Retry-After" if retry_after is not None else "exponential backoff"
        print(f"\n  [rate limit] Year {year}: HTTP 429 "
              f"(attempt {attempt}/{RATE_LIMIT_MAX_RETRIES}, {src})", flush=True)
        logger.warning(f"Year {year}: HTTP 429, backing off {this_wait:.0f}s "
                       f"(attempt {attempt}/{RATE_LIMIT_MAX_RETRIES}, {src})")
        _sleep_with_countdown(this_wait, f"rate-limited on {year}")
        wait = min(wait * 2.0, RATE_LIMIT_MAX_WAIT_S)

    raise RuntimeError(f"unreachable rate-limit path for {year}")


def fetch_hourly_year(lat: float, lon: float, tz: str, year: int) -> pd.DataFrame:
    """
    Fetch one calendar year of hourly historical weather from the Open-Meteo
    Archive API. wind_speed_unit='ms' is set explicitly (Open-Meteo default is
    km/h) because the whole downstream pipeline expects m/s.

    Occasionally the archive API returns `null` for an entire field for a given
    year (transient backend/cache issue, not a real ERA5 data gap) instead of an
    hourly array. Left as-is, that field becomes an all-None object column and
    later arithmetic on it fails with a bare TypeError. We defend against this
    in two ways: (1) validate the response and retry a few times if any
    required field is missing/null/wrong-length, and (2) coerce every column to
    numeric (errors='coerce') so remaining scattered nulls become proper NaN
    (which numpy/pandas propagate cleanly) rather than Python None.

    Rate limiting (HTTP 429) is handled separately, in
    _get_with_rate_limit_retry() -- see the note above RATE_LIMIT_MAX_RETRIES
    for why it must not share the fast-retry path used above.
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "hourly": REQUIRED_HOURLY_FIELDS,
        "timezone": "GMT",        # request in GMT/UTC; we convert to local below.
        "wind_speed_unit": "ms",
    }

    last_problem = None
    data = None
    MAX_NULL_FRACTION = 0.5   # >50% null within a field -> treated as a bad fetch (retry).
                              # Scattered gaps of a few % are normal in reanalysis archives
                              # and are already handled safely downstream via NaN coercion +
                              # nanmax; only near-total null contamination is worth retrying for.
    for attempt in range(1, FETCH_MAX_RETRIES + 1):
        response = _get_with_rate_limit_retry(url, params, year)
        candidate = response.json()["hourly"]

        n_time = len(candidate.get("time", []) or [])
        bad_fields = []
        for f in REQUIRED_HOURLY_FIELDS:
            v = candidate.get(f)
            if not isinstance(v, list) or len(v) != n_time or n_time == 0:
                bad_fields.append(f"{f}(missing/wrong-length)")
                continue
            # A structurally valid list can still be mostly/entirely `null` inside -
            # this slips past a length check but silently degrades every derived
            # quantity that depends on it (e.g. wind -> globe temp -> WBGT/UTCI).
            n_null = sum(1 for x in v if x is None)
            if n_null / n_time > MAX_NULL_FRACTION:
                bad_fields.append(f"{f}({n_null}/{n_time} null)")

        if not bad_fields:
            data = candidate
            break
        last_problem = f"fields returned null/incomplete: {bad_fields}"
        logger.warning(f"Year {year}: attempt {attempt}/{FETCH_MAX_RETRIES} - "
                       f"{last_problem}; retrying...")
        time.sleep(FETCH_RETRY_PAUSE_S)

    if data is None:
        raise RuntimeError(f"Archive API kept returning incomplete data for {year} "
                           f"after {FETCH_MAX_RETRIES} attempts ({last_problem}).")

    df = pd.DataFrame(data)
    df["time"] = pd.to_datetime(df["time"])
    df.set_index("time", inplace=True)
    # Coerce every remaining column to numeric so scattered individual nulls
    # (normal in reanalysis archives) become NaN instead of Python None -
    # NaN propagates safely through the numeric pipeline; None does not.
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # The archive returns each local timestamp only once and does NOT duplicate
    # the autumn fall-back hour, so localising directly to a DST zone with
    # ambiguous='infer' fails (pre-1996 EU summer time ended in late September,
    # e.g. the 1980-09-28 02:00 transition). Instead we requested GMT, localise
    # to UTC (unambiguous) and convert to local time -- DST-safe, and annual
    # maxima are unaffected (only the hour labels change).
    df.index = df.index.tz_localize("UTC").tz_convert(tz)

    df.rename(columns={
        "temperature_2m": "T_air_rural",
        "relative_humidity_2m": "RH",
        "surface_pressure": "pressure",
        "wind_speed_10m": "wind_10m",
        "shortwave_radiation": "solar_radiation",
        "cloud_cover": "cloud_cover",
    }, inplace=True)
    return df

# =============================================================================
# Solar & wind physics  (ported verbatim from Thermopoulos engine)
# =============================================================================

def calculate_solar_parameters(df: pd.DataFrame, lat: float, lon: float, tz: str) -> pd.DataFrame:
    """Solar elevation angle via pvlib (clipped at 0)."""
    location = pvlib.location.Location(lat, lon, tz=tz)
    try:
        solar_pos = location.get_solarposition(df.index)
        df['solar_elevation'] = solar_pos['elevation'].clip(lower=0)
    except Exception as e:
        logger.error(f"Solar calculation failed: {e}")
        df['solar_elevation'] = 0
    return df


def wind_speed_at_height(v_ref, z_ref, z_target, z0=0.1):
    """Logarithmic wind-profile correction (neutral surface layer)."""
    if z_ref <= 0 or z_target <= 0 or z0 <= 0:
        return v_ref
    return v_ref * (np.log(z_target / z0) / np.log(z_ref / z0))


def calculate_uhi_oke(population: int, index: pd.DatetimeIndex) -> pd.Series:
    """Oke (1973) population-based UHI with modern correction + diurnal factors."""
    if not population or population <= 0:
        return pd.Series(0.0, index=index)
    base_uhi = 2.01 * np.log10(population) - 4.06
    if population > 1_000_000:
        uhi_max = np.clip(base_uhi * 0.6, 0.0, 6.0)
    else:
        uhi_max = np.clip(base_uhi, 0.0, 5.0)
    hours = index.hour
    factors = np.zeros(len(index))
    factors[(hours >= 0) & (hours <= 5)] = 1.0
    factors[(hours >= 6) & (hours <= 9)] = 0.6
    factors[(hours >= 10) & (hours <= 16)] = 0.2
    factors[(hours >= 17) & (hours <= 20)] = 0.5
    factors[(hours >= 21) & (hours <= 23)] = 0.9
    return pd.Series(uhi_max * factors, index=index)


def _saturation_vapor_pressure_hpa(temp_c) -> np.ndarray:
    """Magnus-formula saturation vapor pressure [hPa]. Standalone here rather
    than imported: this file has no other vapor-pressure calculation to share
    it with, and the Magnus approximation is standard/interchangeable, so a
    small local copy is clearer than a cross-file dependency for one formula."""
    t = np.asarray(temp_c, dtype=float)
    return 6.112 * np.exp(17.67 * t / (t + 243.5))


def adjust_rh_for_uhi(rh_rural, t_rural_c, t_urban_c, rh_floor: float = 15.0) -> np.ndarray:
    """
    Relative humidity at the UHI-elevated urban temperature, holding the
    RURAL air's actual water vapor content (vapor pressure) fixed rather than
    holding RH% fixed.

    Why this matters: process_weather_data() computes T_air_urban =
    T_air_rural + UHI_delta, but until this function existed, every downstream
    humidity-dependent quantity (wet-bulb, WBGT, UTCI) was computed from that
    WARMER temperature paired with the UNCHANGED rural RH%. Since saturation
    vapor pressure rises with temperature, "same RH% at a higher temperature"
    silently means MORE actual water vapor in the air -- exactly backwards
    from how a real urban heat island behaves: reduced vegetation and
    evapotranspiration shift the surface energy balance toward sensible heat,
    so cities run both hotter AND relatively drier than their surroundings at
    comparable absolute humidity, not hotter at the same RH%.

    Holding vapor pressure fixed instead is itself a simplification (a real
    UHI often reduces absolute humidity somewhat further still, since less
    evapotranspiration also means less moisture added to the urban air mass
    to begin with) -- but it removes the backwards direction of the original
    approach and was verified in this session to matter by whole degrees: a
    25 degC/55% rural reading with a +5 degC nighttime UHI bump gave a
    wet-bulb temperature 2.5 degC too high when RH% was held fixed, versus
    holding vapor pressure fixed instead.

    rh_floor guards against runaway low humidity at very large UHI deltas
    (which would otherwise push RH toward zero and destabilize the downstream
    wet-bulb/WBGT root-finding).
    """
    rh_rural = np.clip(np.asarray(rh_rural, dtype=float), 0.0, 100.0)
    e_rural = rh_rural / 100.0 * _saturation_vapor_pressure_hpa(t_rural_c)
    rh_urban = 100.0 * e_rural / _saturation_vapor_pressure_hpa(t_urban_c)
    return np.clip(rh_urban, rh_floor, 100.0)

# =============================================================================
# Globe & MRT  (ported verbatim from Thermopoulos engine)
# =============================================================================

def _calculate_globe_scalar(dry_bulb, ghi, wind, solar_elev, pressure, cloud, aqi=1):
    """ISO 7726 globe temperature (Newton-Raphson).
    NB: Python's built-in max(0.1, x) silently returns 0.1 when x is NaN (NaN
    comparisons are always False), which would otherwise turn a missing wind
    reading into a false "calm" (0.1 m/s) assumption -> an artificially warm
    globe temperature / WBGT on exactly the hours with missing data, with no
    warning. We guard explicitly so any NaN input propagates to a NaN output,
    consistent with how missing data is handled everywhere else in the pipeline
    (nanmax correctly ignores it)."""
    if any(np.isnan(x) for x in (dry_bulb, ghi, wind, solar_elev, pressure, cloud)):
        return np.nan
    GLOBE_DIA = 0.15; EMISSIVITY = 0.95; ABSORPTIVITY = 0.95; SIGMA = 5.67e-8
    t_air_k = dry_bulb + 273.15
    eff_wind = max(0.1, wind)
    h_c = 6.3 * (eff_wind ** 0.6) / (GLOBE_DIA ** 0.4)
    if ghi <= 0 or solar_elev <= 0:
        sky_depression = 10 - (cloud / 100) * 6
        if aqi > 3: sky_depression -= 2
        sky_temp_k = t_air_k - sky_depression
        net_rad = EMISSIVITY * SIGMA * (sky_temp_k ** 4 - t_air_k ** 4)
        t_globe = dry_bulb + (net_rad / h_c)
        return max(dry_bulb - 3, min(dry_bulb + 1, t_globe))
    solar_input = ABSORPTIVITY * ghi / 4.0
    amb_rad = EMISSIVITY * SIGMA * (t_air_k ** 4)
    total_in = solar_input + amb_rad
    t_globe_k = t_air_k + (solar_input / (h_c + 4 * EMISSIVITY * SIGMA * t_air_k ** 3))
    imbalance = 0.0
    for _ in range(10):
        rad_out = EMISSIVITY * SIGMA * (t_globe_k ** 4)
        conv_out = h_c * (t_globe_k - t_air_k)
        imbalance = total_in - (rad_out + conv_out)
        if abs(imbalance) < 0.1:
            break
        deriv = 4 * EMISSIVITY * SIGMA * (t_globe_k ** 3) + h_c
        t_globe_k += 0.7 * (imbalance / deriv)
    t_globe_c = t_globe_k - 273.15
    if np.isnan(t_globe_c):
        return np.nan
    limit = 15 if eff_wind > 2 else 20
    return max(dry_bulb, min(dry_bulb + limit, t_globe_c))


def _calculate_mrt_scalar(tg, ta, v, ghi, elev):
    """ISO 7726 Mean Radiant Temperature. Same NaN-guard rationale as
    _calculate_globe_scalar (see its docstring)."""
    if any(np.isnan(x) for x in (tg, ta, v, ghi, elev)):
        return np.nan
    GLOBE_DIA = 0.15; EMISSIVITY = 0.95; SIGMA = 5.67e-8
    tg_k = tg + 273.15; ta_k = ta + 273.15
    eff_wind = max(0.1, v)
    h_c = 6.3 * (eff_wind ** 0.6) / (GLOBE_DIA ** 0.4)
    conv_term = (h_c / (EMISSIVITY * SIGMA)) * (tg_k - ta_k)
    mrt_k4 = (tg_k ** 4) + conv_term
    if mrt_k4 < 0:
        return tg
    mrt_c = (mrt_k4 ** 0.25) - 273.15
    if ghi > 0 and elev > 0:
        return np.clip(mrt_c, tg - 2, tg + 15)
    return np.clip(mrt_c, ta - 15, ta + 3)


calculate_globe_vectorized = np.vectorize(_calculate_globe_scalar)
calculate_mrt_vectorized = np.vectorize(_calculate_mrt_scalar)

# =============================================================================
# Unified processing pipeline  (ported from Thermopoulos engine)
# =============================================================================

def process_weather_data(df: pd.DataFrame, city: Dict, lat: float, lon: float, tz: str,
                         apply_uhi: bool = APPLY_UHI) -> pd.DataFrame:
    """Full thermal pipeline -> adds T_air_urban, RH_urban, MRT, WBGT, UTCI
    columns. If apply_uhi is True and the city has a population, an Oke UHI
    increment is added to temperature and the humidity is adjusted to match
    (see adjust_rh_for_uhi() -- holding the rural air's actual water vapor
    content fixed rather than its RH%, since a real heat island runs both
    hotter and relatively drier, not hotter at unchanged RH%); otherwise
    T_air_urban == T_air_rural and RH_urban == RH (clean climate signal)."""
    df = calculate_solar_parameters(df, lat, lon, tz)

    pop = city.get("population", 0)
    uhi_on = bool(apply_uhi and pop and pop > 0)
    if uhi_on:
        df["UHI_delta"] = calculate_uhi_oke(pop, df.index)
        df["T_air_urban"] = df["T_air_rural"] + df["UHI_delta"]
        # See adjust_rh_for_uhi()'s docstring: without this, every humidity-
        # dependent quantity below (wet-bulb, WBGT, UTCI) was computed from the
        # UHI-elevated temperature paired with the unchanged rural RH% --
        # backwards from how a real heat island behaves, and verified in this
        # session to inflate wet-bulb temperature by whole degrees.
        df["RH_urban"] = adjust_rh_for_uhi(df["RH"].values, df["T_air_rural"].values,
                                           df["T_air_urban"].values)
        roughness_z0 = 0.8
    else:
        df["UHI_delta"] = 0.0
        df["T_air_urban"] = df["T_air_rural"]
        df["RH_urban"] = df["RH"]
        roughness_z0 = 0.1

    df["wind_1.5m"] = wind_speed_at_height(df["wind_10m"].values, 10.0, 1.5, z0=roughness_z0)

    df["T_globe"] = calculate_globe_vectorized(
        df["T_air_urban"].values, df["solar_radiation"].values, df["wind_1.5m"].values,
        df["solar_elevation"].values, df["pressure"].values, df["cloud_cover"].values)

    df["MRT"] = calculate_mrt_vectorized(
        df["T_globe"].values, df["T_air_urban"].values, df["wind_1.5m"].values,
        df["solar_radiation"].values, df["solar_elevation"].values)

    if WET_BULB_FUNC == 'models':
        df["T_wetbulb"] = wet_bulb_temperature(
            tdb=df["T_air_urban"].values, rh=df["RH_urban"].values, pressure=df["pressure"].values)
    else:
        df["T_wetbulb"] = wet_bulb_temperature(tdb=df["T_air_urban"].values, rh=df["RH_urban"].values)

    wbgt_res = wbgt(twb=df["T_wetbulb"].values, tg=df["T_globe"].values,
                    tdb=df["T_air_urban"].values, with_solar_load=True)
    df["WBGT"] = wbgt_res.wbgt if hasattr(wbgt_res, 'wbgt') else wbgt_res

    wind_clipped = np.clip(df["wind_10m"].values, 0.5, 17.0)
    utci_res = utci(tdb=df["T_air_urban"].values, tr=df["MRT"].values,
                    v=wind_clipped, rh=df["RH_urban"].values)
    df["UTCI"] = utci_res.utci if hasattr(utci_res, 'utci') else utci_res
    return df

# =============================================================================
# Trend acceleration / breakpoint check
# =============================================================================

def _bootstrap_theilsen_slopes(years: np.ndarray, vals: np.ndarray,
                               n_boot: int, seed: int) -> np.ndarray:
    """Bootstrap distribution of the Theil-Sen slope for one segment: resample
    (year, value) pairs with replacement and refit, n_boot times. Used to build
    a slope-difference confidence interval between two segments without
    assuming Gaussian residuals (a Chow test's assumption, which annual heat
    extremes do not reliably satisfy -- consistent with using Theil-Sen instead
    of OLS everywhere else in this script)."""
    rng = np.random.default_rng(seed)
    n = len(years)
    out = np.full(n_boot, np.nan)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        yb, vb = years[idx], vals[idx]
        if len(np.unique(yb)) < 2:
            continue
        try:
            out[i] = stats.theilslopes(vb, yb)[0]
        except Exception:
            continue
    return out[~np.isnan(out)]


def check_trend_acceleration(annual: pd.DataFrame, var_key: str,
                             full_period: Tuple[int, int],
                             breakpoint_year: Optional[int] = None,
                             min_segment_years: int = ACCEL_MIN_SEGMENT_YEARS,
                             n_boot: int = ACCEL_N_BOOTSTRAP) -> Optional[Dict]:
    """
    Tests whether the trend within `full_period` is better described by one
    straight line or by two lines with different slopes.

    breakpoint_year=None scans every candidate split (with >=min_segment_years
    on each side) and returns the one with the largest slope difference, in
    addition to the full scan for inspection. THIS SCAN MODE IS EXPLORATORY:
    testing many candidate breakpoints and reporting the strongest one is a
    multiple-comparisons procedure, so the "significant" flag on the winning
    breakpoint is optimistic relative to a single breakpoint chosen in advance
    (as when the location's own pollution history motivates one, per the
    module docstring). Use a fixed breakpoint_year when you have that kind of
    prior; use the scan to see whether the data suggests looking for one at
    all.

    DETECTION IS MORE RELIABLE THAN LOCALIZATION. Whether a break exists (any
    candidate reaching significance) is a more robust read than exactly WHICH
    year the "best" (largest-difference) candidate lands on -- with ~30-50
    annual points and realistic year-to-year noise, the located year can be
    off by several years even when a real break is correctly detected, and
    more so for noisier variables (an annual maximum) than smoother ones (an
    event-window mean). print_acceleration_check() reports the full span of
    significant candidates for this reason, not just the single best one.

    Returns None if there is not enough data for two meaningful segments.
    """
    if var_key not in annual.columns:
        return None
    s = annual[var_key].dropna()
    s = s[(s.index >= full_period[0]) & (s.index <= full_period[1])]
    years = np.asarray(s.index, dtype=float)
    vals = np.asarray(s.values, dtype=float)
    n = len(years)
    if n < 2 * min_segment_years:
        return None

    if breakpoint_year is not None:
        candidates = [int(breakpoint_year)]
        mode = "fixed"
    else:
        lo_y = int(years[0]) + min_segment_years
        hi_y = int(years[-1]) - min_segment_years
        candidates = list(range(lo_y, hi_y + 1))
        mode = "scan"
    if not candidates:
        return None

    scan = []
    # A full scan is ~n_candidates x 2 segments x n_boot Theil-Sen fits (easily
    # 50k+), which runs for a noticeable time with no natural output. Progress
    # is printed for the scan; a single fixed breakpoint is fast enough not to
    # need it.
    show_progress = (mode == "scan" and len(candidates) > 3)
    t_accel = time.time()
    for i_bp, bp in enumerate(candidates, start=1):
        if show_progress:
            done_frac = i_bp / len(candidates)
            el = time.time() - t_accel
            eta = (el / done_frac - el) if done_frac > 0 else 0.0
            progress(f"    scanning breakpoints {i_bp}/{len(candidates)} (eta {eta:4.0f}s)")
        seg1, seg2 = years <= bp, years > bp
        if seg1.sum() < min_segment_years or seg2.sum() < min_segment_years:
            continue
        slope1, intercept1, lo1, hi1 = stats.theilslopes(vals[seg1], years[seg1])
        slope2, intercept2, lo2, hi2 = stats.theilslopes(vals[seg2], years[seg2])
        boot1 = _bootstrap_theilsen_slopes(years[seg1], vals[seg1], n_boot, seed=bp)
        boot2 = _bootstrap_theilsen_slopes(years[seg2], vals[seg2], n_boot, seed=bp + 100000)
        m = min(len(boot1), len(boot2))
        if m < 20:
            continue
        diff_dist = boot2[:m] - boot1[:m]
        ci_lo, ci_hi = np.percentile(diff_dist, [2.5, 97.5])
        scan.append({
            "breakpoint": bp, "n1": int(seg1.sum()), "n2": int(seg2.sum()),
            "slope1": slope1, "slope1_ci": (lo1, hi1),
            "slope2": slope2, "slope2_ci": (lo2, hi2),
            "diff": slope2 - slope1, "diff_ci": (ci_lo, ci_hi),
            "significant": (ci_lo > 0) or (ci_hi < 0),
        })
    if show_progress:
        progress_done()
    if not scan:
        return None
    best = max(scan, key=lambda r: abs(r["diff"]))
    return {"var_key": var_key, "full_period": full_period, "years": years, "vals": vals,
            "mode": mode, "scan": scan, "best": best}


def plot_trend_acceleration(res: Dict, city_name: str, outpath: str) -> None:
    """Two-panel figure: the full series with the two segment fits either side
    of the (best) breakpoint, and -- in scan mode -- the slope difference as a
    function of candidate breakpoint, so a reader can see whether one
    breakpoint clearly stands out or the signal is diffuse across many
    candidates (the latter is a reason for caution, not a reason to still
    trust the single winning breakpoint)."""
    years, vals, best = res["years"], res["vals"], res["best"]
    bp = best["breakpoint"]
    fig, axes = plt.subplots(1, 2 if res["mode"] == "scan" else 1,
                             figsize=(13, 5) if res["mode"] == "scan" else (8, 5))
    ax0 = axes[0] if res["mode"] == "scan" else axes

    ax0.plot(years, vals, "o", ms=4, color="grey", alpha=0.6, label="Observed")
    seg1, seg2 = years <= bp, years > bp
    for seg, color, lbl in (
        (seg1, "steelblue", f"<= {bp}: {best['slope1']:+.4f} degC/yr"),
        (seg2, "firebrick", f"> {bp}: {best['slope2']:+.4f} degC/yr"),
    ):
        yrs = years[seg]
        sl, ic, _, _ = stats.theilslopes(vals[seg], yrs)
        ax0.plot(yrs, ic + sl * yrs, color=color, lw=2.5, label=lbl)
    ax0.axvline(bp + 0.5, color="black", ls=":", lw=1.2)
    sig = "significant at 95%" if best["significant"] else "not significant at 95%"
    ax0.set_title(f"{city_name} - {res['var_key']}\n"
                  f"breakpoint {bp} ({res['mode']}): slope diff "
                  f"{best['diff']:+.4f} degC/yr ({sig})", fontsize=10)
    ax0.set_xlabel("Year")
    ax0.set_ylabel(res["var_key"])
    ax0.legend(fontsize=8)
    ax0.grid(alpha=0.25)

    if res["mode"] == "scan":
        ax1 = axes[1]
        bps = [r["breakpoint"] for r in res["scan"]]
        diffs = [r["diff"] for r in res["scan"]]
        sigs = [r["significant"] for r in res["scan"]]
        colors = ["firebrick" if sg else "grey" for sg in sigs]
        ax1.bar(bps, diffs, color=colors, width=0.8)
        ax1.axhline(0, color="black", lw=1)
        ax1.set_xlabel("Candidate breakpoint year")
        ax1.set_ylabel("Slope(after) - Slope(before)  [degC/yr]")
        ax1.set_title("Full scan (red = significant at 95%)\n"
                      "exploratory: multiple comparisons, see docstring", fontsize=9)
        ax1.grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def print_acceleration_check(res: Optional[Dict], var_key: str) -> None:
    if res is None:
        print(f"\n[accel] {var_key}: not enough data for a two-segment check "
              f"(need >= {2 * ACCEL_MIN_SEGMENT_YEARS} years).")
        return
    best = res["best"]
    n_scanned = len(res["scan"])
    mode_note = "user-specified" if res["mode"] == "fixed" else f"{n_scanned} candidates scanned"
    print(f"\n[accel] {var_key}  ({res['mode']} mode, {mode_note})")
    print(f"  Best-supported breakpoint: {int(best['breakpoint'])}")
    print(f"    before (n={best['n1']:2d}): {best['slope1']:+.4f} degC/yr "
          f"(95% CI {best['slope1_ci'][0]:+.4f}..{best['slope1_ci'][1]:+.4f})")
    print(f"    after  (n={best['n2']:2d}): {best['slope2']:+.4f} degC/yr "
          f"(95% CI {best['slope2_ci'][0]:+.4f}..{best['slope2_ci'][1]:+.4f})")
    print(f"    difference: {best['diff']:+.4f} degC/yr "
          f"(bootstrap 95% CI {best['diff_ci'][0]:+.4f}..{best['diff_ci'][1]:+.4f}) "
          f"-> {'SIGNIFICANT' if best['significant'] else 'not significant'} at 95%")
    if res["mode"] == "scan":
        n_sig = sum(1 for r in res["scan"] if r["significant"])
        print(f"    ({n_sig}/{n_scanned} candidate breakpoints reached significance -- "
              f"scan mode is exploratory, see check_trend_acceleration()'s docstring)")
        if n_sig > 0:
            sig_years = [r["breakpoint"] for r in res["scan"] if r["significant"]]
            print(f"    significant breakpoints span {int(min(sig_years))}-{int(max(sig_years))}: "
                  f"treat the single 'best' year above as approximate, not precise -- this")
            print("    check is more reliable at detecting THAT a break exists than WHERE it")
            print("    is (localization needs more/less-noisy data than detection does; a")
            print("    smoother variable like an event-window mean localizes tighter than a")
            print("    noisier one like an annual maximum, for the same underlying break).")
        if not best["significant"]:
            print("    -> no breakpoint in this range is statistically supported: a single")
            print("       straight-line trend over the full period is not contradicted by this test.")
    elif not best["significant"]:
        print(f"    -> the specified breakpoint ({int(best['breakpoint'])}) is not statistically")
        print("       supported here: a single straight-line trend is not contradicted.")

# =============================================================================
# Annual maxima
# =============================================================================

def event_window_metrics(proc: pd.DataFrame, year: int, tz: str) -> Dict:
    """
    Extract the mean conditions during ONE fixed annual event, from the year of
    hourly data build_annual_maxima() has already fetched and processed --
    costing no extra API call.

    For each day in [EVENT_DAY -/+ EVENT_DAY_WINDOW] the hours from the event
    start time to start+EVENT_DURATION_MIN are selected, averaged, and the
    (2*EVENT_DAY_WINDOW+1) day-values are then averaged into one value for the
    year. The +/- day window exists purely to get a usable sample size per year
    (7 days instead of 1) without widening the time-of-day selection, which is
    the part that must stay tied to the actual event.

    Returns {} if the event window cannot be resolved for this year (e.g. 29 Feb
    in a non-leap year, or a data gap) -- the caller simply records no event
    value for that year rather than failing the whole run.
    """
    day_means: Dict[str, List[float]] = {"T_air_event": [], "WBGT_event": [], "UTCI_event": []}
    col_for = {"T_air_event": "T_air_urban", "WBGT_event": "WBGT", "UTCI_event": "UTCI"}

    for off in range(-EVENT_DAY_WINDOW, EVENT_DAY_WINDOW + 1):
        try:
            centre = pd.Timestamp(year=year, month=EVENT_MONTH, day=EVENT_DAY)
        except ValueError:
            # 29 Feb in a non-leap year: fall back to the 28th for that year only.
            centre = pd.Timestamp(year=year, month=2, day=28)
        day = centre + pd.Timedelta(days=off)
        start_naive = pd.Timestamp(year=day.year, month=day.month, day=day.day,
                                   hour=EVENT_START_HOUR, minute=EVENT_START_MINUTE)
        try:
            start = start_naive.tz_localize(tz, nonexistent="shift_forward", ambiguous=True)
        except Exception:
            continue
        finish = start + pd.Timedelta(minutes=EVENT_DURATION_MIN)
        mask = (proc.index >= start) & (proc.index <= finish)
        if not mask.any():
            continue
        for key, col in col_for.items():
            if col in proc.columns:
                vals = proc.loc[mask, col].values
                vals = vals[~np.isnan(vals)]
                if len(vals):
                    day_means[key].append(float(np.mean(vals)))

    out = {}
    for key, vals in day_means.items():
        if vals:
            out[key] = float(np.mean(vals))
            out[f"{key}_ndays"] = len(vals)
    return out


def build_annual_maxima(lat: float, lon: float, tz: str, city: Dict,
                        start_year: int, end_year: int,
                        apply_uhi: bool = APPLY_UHI,
                        event_slices: Optional[Dict[int, pd.DataFrame]] = None) -> pd.DataFrame:
    """
    Fetch + process each year and return a DataFrame indexed by year with
    columns T_air_max, WBT_max, WBGT_max, UTCI_max and a validity flag.

    If `event_slices` is given (a dict), it is filled in place with the
    processed hourly data around the event date for each year -- the raw
    material the EHS-evolution module needs to build its shifted scenarios.
    Keeping the slice here rather than re-fetching later is what lets that
    module run at no additional API cost; a slice is a few hundred rows, so
    holding one per year is negligible.
    """
    records = []
    failed_years: List[int] = []
    n_years = end_year - start_year + 1
    t_start = time.time()
    for i, year in enumerate(range(start_year, end_year + 1), start=1):
        # ETA is based on completed years so far. It is deliberately recomputed
        # every iteration rather than fixed up front: a rate-limit backoff can
        # add minutes mid-run, and a stale estimate that ignores that is worse
        # than none.
        if i > 1:
            per_year = (time.time() - t_start) / (i - 1)
            eta_min = per_year * (n_years - i + 1) / 60.0
            eta_txt = f" (eta {eta_min:4.1f} min)"
        else:
            eta_txt = ""
        # On a TTY the year label is printed first and the result appended to the
        # same line. Off-TTY that leaves the label invisible until the fetch
        # returns, so the whole line is assembled and printed once instead --
        # slightly less live, but it actually appears.
        label = f"  [{i:>2}/{n_years}] {year}{eta_txt} ..."
        if IS_TTY:
            print(label, end="", flush=True)
        try:
            raw = fetch_hourly_year(lat, lon, tz, year)
            proc = process_weather_data(raw, city, lat, lon, tz, apply_uhi=apply_uhi)
            n_hours = len(proc)
            rec = {
                "year": year,
                "T_air_max": float(np.nanmax(proc["T_air_urban"].values)),
                "WBT_max":   float(np.nanmax(proc["T_wetbulb"].values)),
                "WBGT_max":  float(np.nanmax(proc["WBGT"].values)),
                "UTCI_max":  float(np.nanmax(proc["UTCI"].values)),
                "n_hours": n_hours,
                "valid": n_hours >= MIN_DAYS_PER_YEAR * 24 * 0.9,
            }
            if ENABLE_ADMISSIONS_ERF:
                # Daily-max air temperature over the ERF months (regional/rural basis,
                # matching the station calibration of the van Loenhout ERF).
                tair = proc["T_air_rural"]
                tair = tair[(tair.index.month >= ERF_MONTHS[0]) &
                            (tair.index.month <= ERF_MONTHS[1])]
                daily_max = tair.resample("D").max().dropna()
                hdd, hai, n_over = heat_admission_indices(daily_max)
                rec["heat_degree_days"] = hdd     # beta-free: sum max(0, Tmax - MMT)
                rec["heat_admit_index"] = hai      # ERF: sum (exp(beta*excess) - 1)
                rec["n_days_over_mmt"] = n_over
            if ENABLE_LIVEABILITY and HEATLIM_AVAILABLE:
                rec.update(liveability_year_metrics(proc))
            if ENABLE_EVENT_WINDOW:
                # Same processed year, no extra fetch -- see event_window_metrics().
                rec.update(event_window_metrics(proc, year, tz))
            if event_slices is not None:
                # A generous margin around the event window: the EHS module may
                # start the event earlier (adaptation scenario) than the
                # configured time, so the slice must cover the whole day, not
                # just the configured start->finish hours.
                try:
                    centre = pd.Timestamp(year=year, month=EVENT_MONTH, day=EVENT_DAY)
                except ValueError:
                    centre = pd.Timestamp(year=year, month=2, day=28)
                lo = (centre - pd.Timedelta(days=EVENT_DAY_WINDOW + 1)).strftime("%Y-%m-%d")
                hi = (centre + pd.Timedelta(days=EVENT_DAY_WINDOW + 1)).strftime("%Y-%m-%d")
                sl = proc.loc[lo:hi]
                if not sl.empty:
                    event_slices[year] = sl.copy()
            records.append(rec)
            tail = (f" Tmax={rec['T_air_max']:5.1f}  WBT={rec['WBT_max']:5.1f}  "
                    f"WBGTmax={rec['WBGT_max']:5.1f}  UTCImax={rec['UTCI_max']:5.1f}")
            print(tail if IS_TTY else label + tail)
        except requests.RequestException as e:
            print((" FETCH FAILED (%s)" % e) if IS_TTY else label + (" FETCH FAILED (%s)" % e))
            logger.warning(f"Year {year} skipped: {e}")
            failed_years.append(year)
        except Exception as e:
            print((" PROCESSING FAILED (%s)" % e) if IS_TTY
                  else label + (" PROCESSING FAILED (%s)" % e))
            logger.warning(f"Year {year} processing failed: {e}")
            failed_years.append(year)
        time.sleep(REQUEST_PAUSE_S)

    if not records:
        raise RuntimeError("No years could be retrieved/processed.")

    elapsed_min = (time.time() - t_start) / 60.0
    print(f"\n  Retrieved {len(records)}/{n_years} years in {elapsed_min:.1f} min.")
    if failed_years:
        # Surfaced loudly, not just left in the log: a gap inside the reference
        # or trend period silently weakens every statistic fitted on it, and the
        # per-year warnings above scroll out of sight during a long run.
        runs = []
        for y in failed_years:
            if runs and y == runs[-1][-1] + 1:
                runs[-1].append(y)
            else:
                runs.append([y])
        spans = ", ".join(f"{r[0]}" if len(r) == 1 else f"{r[0]}-{r[-1]}" for r in runs)
        print(f"  !! {len(failed_years)} year(s) MISSING: {spans}")
        print("     Trends, baselines and return periods below are fitted on the years that")
        print("     did arrive. Consecutive gaps usually mean rate limiting rather than real")
        print("     data gaps -- re-running later normally fills them (results are not cached,")
        print("     so a re-run re-fetches everything).")
    out = pd.DataFrame(records).set_index("year").sort_index()
    return out

# =============================================================================
# Window generation
# =============================================================================

def generate_windows(start_year: int, last_year: int,
                     length: int = WINDOW_LENGTH, step: int = WINDOW_STEP,
                     add_trailing: bool = ADD_TRAILING_PRESENT_WINDOW) -> List[Tuple[int, int]]:
    """
    Generate (start, end) inclusive windows of `length` years stepping by
    `step` from `start_year`, including only full windows that fit within
    `last_year`. If `add_trailing` is True, also append a window ending exactly
    at `last_year` (the present-day normal) when it is not already present.
    """
    windows = []
    s = start_year
    while s + length - 1 <= last_year:
        windows.append((s, s + length - 1))
        s += step
    if add_trailing:
        trailing = (last_year - length + 1, last_year)
        if trailing[0] >= start_year and trailing not in windows:
            windows.append(trailing)
    return windows

# =============================================================================
# Statistics: normal + GEV exceedance and return periods
# =============================================================================

def _return_period(prob: float) -> float:
    """Return period [years] from annual exceedance probability."""
    if prob is None or not np.isfinite(prob) or prob <= 0:
        return float("inf")
    return 1.0 / prob


def analyze_variable_windows(series: pd.Series, windows: List[Tuple[int, int]],
                             thresholds: List[float]) -> pd.DataFrame:
    """
    For one annual-maxima series, compute per-window statistics and, for each
    threshold, the exceedance probability + return period via Normal and GEV.
    """
    rows = []
    for (a, b) in windows:
        data = series.loc[(series.index >= a) & (series.index <= b)].dropna().values
        n = len(data)
        row = {"window": f"{a}-{b}", "start": a, "end": b, "n_years": n}
        if n < 3:
            rows.append(row)
            continue

        mu = float(np.mean(data))
        sigma = float(np.std(data, ddof=1))
        row["mean"] = mu
        row["std"] = sigma

        # GEV fit (block maxima). May fail on small/degenerate samples.
        gev_params = None
        if n >= 10 and sigma > 0:
            try:
                gev_params = stats.genextreme.fit(data)
            except Exception as e:
                logger.debug(f"GEV fit failed for {a}-{b}: {e}")

        for thr in thresholds:
            # Normal exceedance
            if sigma > 0:
                p_norm = float(stats.norm.sf(thr, loc=mu, scale=sigma))
            else:
                p_norm = 1.0 if mu >= thr else 0.0
            row[f"P_norm_{thr:g}"] = p_norm
            row[f"RP_norm_{thr:g}"] = _return_period(p_norm)

            # Empirical exceedance (fraction of years in window above threshold)
            row[f"P_emp_{thr:g}"] = float(np.mean(data >= thr))

            # GEV exceedance
            if gev_params is not None:
                c, loc, scale = gev_params
                p_gev = float(stats.genextreme.sf(thr, c, loc=loc, scale=scale))
                row[f"P_gev_{thr:g}"] = p_gev
                row[f"RP_gev_{thr:g}"] = _return_period(p_gev)
            else:
                row[f"P_gev_{thr:g}"] = np.nan
                row[f"RP_gev_{thr:g}"] = np.nan

        if gev_params is not None:
            row["gev_shape_c"], row["gev_loc"], row["gev_scale"] = gev_params
        rows.append(row)
    return pd.DataFrame(rows)

# =============================================================================
# Plotting
# =============================================================================

def plot_window_normals(stats_df: pd.DataFrame, thresholds: List[float],
                        var_key: str, city_name: str, outpath: str) -> None:
    """Overlay the fitted NORMAL distributions of all windows for one variable.
    A row flagged is_reference is drawn as a distinct black dashed baseline."""
    valid = stats_df.dropna(subset=["mean", "std"])
    valid = valid[valid["std"] > 0]
    if valid.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 6))
    cmap = plt.cm.plasma
    n_win = int((~valid.get("is_reference", pd.Series(False, index=valid.index))).sum())
    lo = min(valid["mean"] - 4 * valid["std"])
    hi = max(valid["mean"] + 4 * valid["std"])
    x = np.linspace(lo, hi, 600)
    win_i = 0
    for _, r in valid.iterrows():
        y = stats.norm.pdf(x, loc=r["mean"], scale=r["std"])
        if bool(r.get("is_reference", False)):
            ax.plot(x, y, color="black", lw=2.6, ls="--",
                    label=f"REF {r['window']}  (mu={r['mean']:.1f}, sd={r['std']:.2f}, n={int(r['n_years'])})")
        else:
            color = cmap(win_i / max(1, n_win - 1))
            win_i += 1
            ax.plot(x, y, color=color, lw=2,
                    label=f"{r['window']}  (mu={r['mean']:.1f}, sd={r['std']:.2f}, n={int(r['n_years'])})")
            ax.fill_between(x, y, color=color, alpha=0.06)
    for thr in thresholds:
        ax.axvline(thr, color="grey", ls="--", lw=1)
        ax.text(thr, ax.get_ylim()[1] * 0.97, f"{thr:g}",
                rotation=90, va="top", ha="right", fontsize=8, color="grey")
    ax.set_title(f"{VAR_LABEL[var_key]} - normal fit per 30-yr window vs {REFERENCE_PERIOD[0]}-{REFERENCE_PERIOD[1]} baseline\n{city_name}")
    ax.set_xlabel("Temperature [degC]")
    ax.set_ylabel("Probability density")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def plot_normal_vs_gev(series: pd.Series, stats_df: pd.DataFrame,
                       thresholds: List[float], var_key: str,
                       city_name: str, outpath: str) -> None:
    """For the most recent window: empirical histogram + Normal + GEV fit."""
    valid = stats_df.dropna(subset=["mean", "std"])
    if valid.empty:
        return
    r = valid.iloc[-1]
    a, b = int(r["start"]), int(r["end"])
    data = series.loc[(series.index >= a) & (series.index <= b)].dropna().values
    if len(data) < 5 or r["std"] <= 0:
        return
    fig, ax = plt.subplots(figsize=(10, 6))
    lo, hi = data.min() - 3, data.max() + 3
    x = np.linspace(lo, hi, 600)
    ax.hist(data, bins=max(6, len(data) // 3), density=True,
            color="lightsteelblue", edgecolor="white", alpha=0.8, label="Empirical")
    ax.plot(x, stats.norm.pdf(x, r["mean"], r["std"]), "b-", lw=2, label="Normal fit")
    if not np.isnan(r.get("gev_shape_c", np.nan)):
        ax.plot(x, stats.genextreme.pdf(x, r["gev_shape_c"], r["gev_loc"], r["gev_scale"]),
                "r-", lw=2, label="GEV fit")
    for thr in thresholds:
        ax.axvline(thr, color="grey", ls="--", lw=1)
    ax.set_title(f"{VAR_LABEL[var_key]} - Normal vs GEV, window {r['window']}\n{city_name}")
    ax.set_xlabel("Temperature [degC]")
    ax.set_ylabel("Probability density")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)

# =============================================================================
# Additional plots (5): trend, return levels, trajectory, std anomaly, QQ
# =============================================================================

def mann_kendall(x: np.ndarray) -> Dict:
    """Non-parametric Mann-Kendall trend test + Theil-Sen slope (per index step),
    including the 95% CI on the slope (Sen's slope CI) for trend projection."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    out = {"n": n, "S": np.nan, "Z": np.nan, "p": np.nan,
           "slope": np.nan, "intercept": np.nan, "slope_lo": np.nan, "slope_hi": np.nan,
           "trend": "n/a"}
    if n < 4:
        return out
    s = 0.0
    for k in range(n - 1):
        s += np.sum(np.sign(x[k + 1:] - x[k]))
    _, counts = np.unique(x, return_counts=True)
    tie = np.sum(counts * (counts - 1) * (2 * counts + 5))
    var_s = (n * (n - 1) * (2 * n + 5) - tie) / 18.0
    if var_s <= 0:
        return out
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    slope, intercept, slope_lo, slope_hi = stats.theilslopes(x, np.arange(n), alpha=0.95)
    if p < 0.05 and z > 0:
        trend = "increasing (p<0.05)"
    elif p < 0.05 and z < 0:
        trend = "decreasing (p<0.05)"
    else:
        trend = "no significant trend"
    out.update(S=s, Z=z, p=p, slope=slope, intercept=intercept,
              slope_lo=slope_lo, slope_hi=slope_hi, trend=trend)
    return out


def add_trend_projection(ax, years: np.ndarray, mk: Dict, color: str = "r",
                         legend: bool = True) -> None:
    """Extend a Theil-Sen trend line PROJECTION_YEARS into the future as a naive
    linear extrapolation, fanned out using Sen's slope 95% CI (slope_lo/slope_hi)
    anchored at the last observed point. This is a STATISTICAL extrapolation of
    the observed trend, NOT a physical climate or epidemiological forecast -
    labelled as such on the plot.
    """
    if not ENABLE_TREND_PROJECTION or PROJECTION_YEARS <= 0:
        return
    n = mk.get("n", 0)
    if n < PROJECTION_MIN_YEARS or not np.isfinite(mk.get("slope", np.nan)):
        return
    last_year = float(years[-1])
    y_last = mk["intercept"] + mk["slope"] * (n - 1)
    t = np.arange(0, PROJECTION_YEARS + 1)
    future_years = last_year + t
    central = y_last + mk["slope"] * t

    proj_label = f"Projection +{PROJECTION_YEARS} yr (naive linear extrapolation)" if legend else None
    ax.plot(future_years, central, color=color, lw=2.0, ls=(0, (5, 3)), alpha=0.85,
            label=proj_label)

    if np.isfinite(mk.get("slope_lo", np.nan)) and np.isfinite(mk.get("slope_hi", np.nan)):
        lo = y_last + mk["slope_lo"] * t
        hi = y_last + mk["slope_hi"] * t
        band_lo = np.minimum(lo, hi)
        band_hi = np.maximum(lo, hi)
        ci_label = "Sen's slope 95% CI (projected)" if legend else None
        ax.fill_between(future_years, band_lo, band_hi, color=color, alpha=0.12, label=ci_label)

    ax.axvline(last_year, color="grey", lw=0.8, ls=":")


def plot_timeseries_trend(annual: pd.DataFrame, var_key: str, thresholds: List[float],
                          ref_window: Tuple[int, int], city_name: str, outpath: str) -> None:
    """Plot 1: annual maxima vs year + Theil-Sen trend (Mann-Kendall significance),
    reference-period mean band and threshold lines."""
    s = annual[var_key].dropna()
    if len(s) < 4:
        return
    years = s.index.values.astype(float)
    vals = s.values
    mk = mann_kendall(vals)

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(years, vals, "o-", color="steelblue", ms=4, lw=1, alpha=0.8, label="Annual maximum")

    # Theil-Sen line (slope is per-step == per-year because index step is 1 yr)
    if np.isfinite(mk["slope"]):
        x0 = np.arange(len(vals))
        fit = mk["intercept"] + mk["slope"] * x0
        ax.plot(years, fit, "r-", lw=2.2,
                label=f"Theil-Sen: {mk['slope']*10:+.2f} degC/decade  ({mk['trend']})")
        add_trend_projection(ax, years, mk, color="r")

    # Reference-period mean band
    ref = s.loc[(s.index >= ref_window[0]) & (s.index <= ref_window[1])]
    if len(ref) > 0:
        rmu, rsd = float(ref.mean()), float(ref.std(ddof=1))
        ax.axhspan(rmu - rsd, rmu + rsd, color="grey", alpha=0.15)
        ax.axhline(rmu, color="black", ls="--", lw=1.3,
                   label=f"Reference {ref_window[0]}-{ref_window[1]} mean = {rmu:.1f}")

    for thr in thresholds:
        ax.axhline(thr, color="darkred", ls=":", lw=1)
        ax.text(years[0], thr, f" {thr:g}", va="bottom", ha="left", fontsize=8, color="darkred")

    proj_note = f" (dashed: naive {PROJECTION_YEARS}-yr linear extrapolation, not a forecast)" \
        if (ENABLE_TREND_PROJECTION and mk.get("n", 0) >= PROJECTION_MIN_YEARS) else ""
    ax.set_title(f"{VAR_LABEL[var_key]} - annual maxima & robust trend\n{city_name}{proj_note}",
                fontsize=11)
    ax.set_xlabel("Year")
    ax.set_ylabel("Temperature [degC]")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def _gev_return_levels(c, loc, scale, periods) -> np.ndarray:
    """Return level (temperature) for each return period T via GEV ppf(1-1/T)."""
    q = 1.0 - 1.0 / np.asarray(periods, dtype=float)
    return stats.genextreme.ppf(q, c, loc=loc, scale=scale)


def _bootstrap_return_band(data: np.ndarray, periods, n_boot=BOOTSTRAP_N):
    """Bootstrap 95% CI for GEV return levels by resampling + refitting."""
    rng = np.random.default_rng(0)
    levels = []
    for _ in range(n_boot):
        sample = rng.choice(data, size=len(data), replace=True)
        try:
            c, loc, scale = stats.genextreme.fit(sample)
            levels.append(_gev_return_levels(c, loc, scale, periods))
        except Exception:
            continue
    if len(levels) < 20:
        return None, None
    arr = np.array(levels)
    return np.nanpercentile(arr, 2.5, axis=0), np.nanpercentile(arr, 97.5, axis=0)


def plot_return_levels(series: pd.Series, stats_df: pd.DataFrame, var_key: str,
                       city_name: str, outpath: str) -> None:
    """Plot 2: GEV return-level curves per window (+ reference), empirical points
    (Gringorten), and bootstrap 95% bands for reference and latest window."""
    valid = stats_df.dropna(subset=["gev_shape_c"])
    if valid.empty:
        return
    fig, ax = plt.subplots(figsize=(11, 6))
    cmap = plt.cm.plasma
    periods = np.array(RETURN_PERIODS, dtype=float)
    xfine = np.logspace(np.log10(2), np.log10(periods.max()), 200)
    n_win = int((~valid.get("is_reference", pd.Series(False, index=valid.index))).sum())
    win_i = 0
    last_idx = valid.index[-1]
    for idx, r in valid.iterrows():
        c, loc, scale = r["gev_shape_c"], r["gev_loc"], r["gev_scale"]
        y = _gev_return_levels(c, loc, scale, xfine)
        is_ref = bool(r.get("is_reference", False))
        if is_ref:
            color = "black"; ls = "--"; lw = 2.4
        else:
            color = cmap(win_i / max(1, n_win - 1)); ls = "-"; lw = 2; win_i += 1
        ax.plot(xfine, y, color=color, ls=ls, lw=lw, label=("REF " if is_ref else "") + str(r["window"]))

        # bootstrap band for reference and latest window only (keep readable)
        if is_ref or idx == last_idx:
            data = series.loc[(series.index >= r["start"]) & (series.index <= r["end"])].dropna().values
            if len(data) >= 10:
                lo, hi = _bootstrap_return_band(data, xfine)
                if lo is not None:
                    ax.fill_between(xfine, lo, hi, color=color, alpha=0.12)
                # Gringorten empirical plotting positions
                d = np.sort(data); m = len(d)
                pp = (np.arange(1, m + 1) - 0.44) / (m + 0.12)
                rp = 1.0 / (1.0 - pp)
                ax.plot(rp, d, "o", color=color, ms=4, alpha=0.7)

    ax.set_xscale("log")
    ax.set_xticks(periods)
    ax.set_xticklabels([f"{int(p)}" for p in periods])
    ax.set_title(f"{VAR_LABEL[var_key]} - GEV return levels (95% bootstrap band: ref & latest)\n{city_name}")
    ax.set_xlabel("Return period [years]")
    ax.set_ylabel("Return level [degC]")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25, which="both")
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def plot_trajectory(stats_df: pd.DataFrame, var_key: str, thresholds: List[float],
                    city_name: str, outpath: str) -> None:
    """Plot 3: two panels vs window central year - (top) mean +/-1sd, (bottom)
    exceedance probability P(>= threshold) per window (normal fit)."""
    valid = stats_df.dropna(subset=["mean", "std"])
    if len(valid) < 2:
        return
    cyear = (valid["start"] + valid["end"]) / 2.0
    is_ref = valid.get("is_reference", pd.Series(False, index=valid.index)).values

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    ax1.errorbar(cyear, valid["mean"], yerr=valid["std"], fmt="-", color="teal",
                 ecolor="lightgray", elinewidth=2, capsize=3, lw=1.5, label="mean +/- 1 sd")
    ax1.scatter(cyear[is_ref], valid["mean"].values[is_ref], color="black", zorder=5, s=60,
                label="reference")
    ax1.set_ylabel("Mean annual max [degC]")
    ax1.set_title(f"{VAR_LABEL[var_key]} - window trajectory\n{city_name}")
    ax1.legend(fontsize=8); ax1.grid(alpha=0.25)

    for thr in thresholds:
        col = f"P_norm_{thr:g}"
        if col in valid:
            ax2.plot(cyear, valid[col], "o-", lw=1.6, label=f">= {thr:g} degC")
    ax2.set_ylabel("Exceedance probability\nP(annual max >= threshold)")
    ax2.set_xlabel("Window central year")
    ax2.legend(fontsize=8); ax2.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def plot_standardized_anomaly(stats_by_var: Dict[str, pd.DataFrame],
                              city_name: str, outpath: str) -> None:
    """Plot 4 (one figure, all variables): standardized shift of the window mean
    relative to the reference, in reference-sigma units, for Tair/WBGT/UTCI."""
    fig, ax = plt.subplots(figsize=(11, 6))
    colors = {"T_air_max": "tab:blue", "WBT_max": "tab:purple",
              "WBGT_max": "tab:green", "UTCI_max": "tab:red"}
    plotted = False
    for var_key, sdf in stats_by_var.items():
        valid = sdf.dropna(subset=["mean", "std"])
        if valid.empty:
            continue
        ref_sd = float(valid.iloc[0]["std"])
        if ref_sd <= 0:
            continue
        cyear = (valid["start"] + valid["end"]) / 2.0
        z = valid["mean_vs_ref"] / ref_sd
        ax.plot(cyear, z, "o-", color=colors.get(var_key, None), lw=1.8, label=VAR_LABEL[var_key])
        plotted = True
    if not plotted:
        plt.close(fig); return
    ax.axhline(0, color="black", lw=1)
    ax.set_title(f"Standardized warming of annual maxima vs reference baseline\n{city_name}")
    ax.set_xlabel("Window central year")
    ax.set_ylabel("Shift in reference-sigma units  (mean_vs_ref / sd_ref)")
    ax.legend(fontsize=9); ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def plot_qq_normal_gev(series: pd.Series, stats_df: pd.DataFrame, var_key: str,
                       city_name: str, outpath: str) -> None:
    """Plot 5: QQ plot (empirical vs fitted quantiles) for Normal and GEV, for the
    reference window and the latest window - shows where the normal fails in the tail."""
    valid = stats_df.dropna(subset=["mean", "std"])
    if len(valid) < 1:
        return
    rows = [("reference", valid.iloc[0])]
    if len(valid) > 1:
        rows.append(("latest", valid.iloc[-1]))

    fig, axes = plt.subplots(1, len(rows), figsize=(6 * len(rows), 5.5), squeeze=False)
    for ax, (label, r) in zip(axes[0], rows):
        data = series.loc[(series.index >= r["start"]) & (series.index <= r["end"])].dropna().values
        d = np.sort(data); n = len(d)
        if n < 5 or r["std"] <= 0:
            ax.set_visible(False); continue
        pp = (np.arange(1, n + 1) - 0.5) / n
        q_norm = stats.norm.ppf(pp, loc=r["mean"], scale=r["std"])
        ax.plot(q_norm, d, "o", color="tab:blue", ms=5, alpha=0.7, label="Normal")
        if np.isfinite(r.get("gev_shape_c", np.nan)):
            q_gev = stats.genextreme.ppf(pp, r["gev_shape_c"], r["gev_loc"], r["gev_scale"])
            ax.plot(q_gev, d, "s", color="tab:red", ms=5, alpha=0.7, label="GEV")
        lo = min(d.min(), q_norm.min()); hi = max(d.max(), q_norm.max())
        ax.plot([lo, hi], [lo, hi], "k--", lw=1)
        ax.set_title(f"{label}: {r['window']}")
        ax.set_xlabel("Theoretical quantile [degC]")
        ax.set_ylabel("Empirical quantile [degC]")
        ax.legend(fontsize=8); ax.grid(alpha=0.25)
    fig.suptitle(f"{VAR_LABEL[var_key]} - QQ: Normal vs GEV\n{city_name}")
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)

# =============================================================================
# Warming stripes ("streepjescode")
# =============================================================================

def plot_warming_stripes(annual: pd.DataFrame, ref_window: Tuple[int, int],
                         var_key: str, city_name: str, outpath: str,
                         include_projection: Optional[bool] = None) -> None:
    """
    One coloured bar per year, colour = anomaly relative to the reference-period
    mean (Ed Hawkins' #ShowYourStripes idiom). No y-axis, no curve to read: the
    single figure in this script aimed at a reader who will not study a scale.

    Projected years are drawn hatched and separated by a vertical line, so a
    naive linear extrapolation can never be mistaken for observed data. The
    colour scale is symmetric around zero (diverging blue-white-red), so "warmer
    than the baseline" and "colder than the baseline" are equally readable.
    """
    if include_projection is None:
        include_projection = STRIPES_INCLUDE_PROJECTION
    s = annual[var_key].dropna()
    if len(s) < 4:
        return
    ref = s[(s.index >= ref_window[0]) & (s.index <= ref_window[1])]
    if len(ref) < 2:
        return
    ref_mean = float(ref.mean())

    years = list(s.index.astype(int))
    anomalies = list((s - ref_mean).values)
    is_proj = [False] * len(years)

    if include_projection and ENABLE_TREND_PROJECTION and PROJECTION_YEARS > 0:
        mk = mann_kendall(s.values)
        if mk["n"] >= PROJECTION_MIN_YEARS and np.isfinite(mk.get("slope", np.nan)):
            y_last = mk["intercept"] + mk["slope"] * (mk["n"] - 1)
            for t in range(1, PROJECTION_YEARS + 1):
                years.append(int(s.index.max()) + t)
                anomalies.append(float(y_last + mk["slope"] * t - ref_mean))
                is_proj.append(True)

    vmax = max(abs(a) for a in anomalies) if anomalies else 1.0
    norm = plt.Normalize(vmin=-vmax, vmax=vmax)
    cmap = plt.get_cmap("RdBu_r")

    fig, ax = plt.subplots(figsize=(13, 2.6))
    for x, a, proj in zip(years, anomalies, is_proj):
        ax.bar(x, 1.0, width=1.0, color=cmap(norm(a)), edgecolor="none",
               hatch="///" if proj else None, alpha=0.85 if proj else 1.0)
    if any(is_proj):
        first_proj = years[is_proj.index(True)]
        ax.axvline(first_proj - 0.5, color="black", lw=1.2, ls=":")
        ax.text(first_proj, 1.04, "projection (naive linear extrapolation)",
                fontsize=7, style="italic", ha="left", va="bottom")

    ax.set_xlim(min(years) - 0.5, max(years) + 0.5)
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_xlabel("Year")
    label = VAR_LABEL.get(var_key, EVENT_VAR_LABEL.get(var_key, var_key))
    ax.set_title(f"{city_name} - {label}\n"
                 f"anomaly vs {ref_window[0]}-{ref_window[1]} baseline", fontsize=10)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, pad=0.01, fraction=0.03)
    cb.set_label(f"degC vs {ref_window[0]}-{ref_window[1]}", fontsize=8)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)

# =============================================================================
# Event window: one fixed annual event ("is this date still defensible?")
# =============================================================================

def analyze_event_window(annual: pd.DataFrame, var_key: str,
                         trend_period: Optional[Tuple[int, int]] = None,
                         baseline_period: Optional[Tuple[int, int]] = None) -> Optional[Dict]:
    """
    Fit the Theil-Sen trend of one event-window variable, anchored on
    `trend_period` (default EVENT_TREND_PERIOD, 1995-2025), and summarise the
    baseline period for comparison. All projections in the event module use
    THIS trend, so that changing the comparison baseline never silently changes
    the forecast.

    The periods default via None sentinels rather than by naming the CONFIG
    constants directly in the signature: Python evaluates default arguments once
    at function-definition time, so a constant used as a default would freeze
    the value the module had at import and silently ignore any later change to
    it (which is exactly the sort of bug that looks like the config is being
    read when it is not).

    Returns None if there is not enough data in the trend period to fit.
    """
    if trend_period is None:
        trend_period = EVENT_TREND_PERIOD
    if baseline_period is None:
        baseline_period = REFERENCE_PERIOD
    if var_key not in annual.columns:
        return None
    s = annual[var_key].dropna()
    trend_s = s[(s.index >= trend_period[0]) & (s.index <= trend_period[1])]
    if len(trend_s) < 4:
        return None

    years = np.asarray(trend_s.index, dtype=float)
    vals = np.asarray(trend_s.values, dtype=float)
    mk = mann_kendall(vals)
    # mann_kendall fits against arange(n); convert the intercept to calendar years
    # so the fit line can be evaluated at any year directly.
    slope = mk["slope"]
    intercept_cal = (mk["intercept"] - slope * years[0]) if np.isfinite(slope) else np.nan

    base_s = s[(s.index >= baseline_period[0]) & (s.index <= baseline_period[1])]
    return {
        "var_key": var_key,
        "trend_period": trend_period,
        "baseline_period": baseline_period,
        "trend_years": years,
        "trend_values": vals,
        "baseline_values": np.asarray(base_s.values, dtype=float),
        "baseline_mean": float(base_s.mean()) if len(base_s) else np.nan,
        "baseline_std": float(base_s.std(ddof=1)) if len(base_s) > 1 else np.nan,
        "trend_mean": float(np.mean(vals)),
        "mk": mk,
        "slope": slope,
        "intercept_cal": intercept_cal,
        "n_trend": len(vals),
        "n_baseline": len(base_s),
    }


def _event_projected_series(ev: Dict, target_year: int) -> np.ndarray:
    """
    The trend-period values, each shifted by slope * (target_year - its own year).

    This detrends the observed series and re-centres it at the target year's
    trend-predicted level. Note precisely what that does to the spread: the
    result carries the DETRENDED residual spread -- genuine year-to-year weather
    variability -- and NOT the raw spread of the observed series, which is wider
    because it also contains the 30-year warming trend itself. That is the
    correct choice here (verified numerically: sigma_shifted^2 ~=
    sigma_observed^2 - slope^2 * var(years)): the distribution of conditions in
    a single future year should be centred on that year's trend level and
    spread by natural interannual variability, not inflated by decades of trend
    that has already been accounted for in the centre.
    """
    return ev["trend_values"] + ev["slope"] * (target_year - ev["trend_years"])


def plot_event_window_trend(ev: Dict, city_name: str, outpath: str) -> None:
    """
    Event-window means per year with the Theil-Sen fit and a projection fan,
    plus the 1951-1980 baseline as a dashed reference line and +/-1 sigma band.

    Deliberate design (carried over from the Streamlit version): the yearly
    scatter is de-emphasised and the fit/projection drawn heavy, because the
    headline is the trend, not any individual year.
    """
    years, vals = ev["trend_years"], ev["trend_values"]
    mk = ev["mk"]
    fig, ax = plt.subplots(figsize=(11, 5))

    if np.isfinite(ev["baseline_mean"]):
        x0 = min(REFERENCE_PERIOD[0], int(years[0]))
        x1 = int(years[-1]) + (PROJECTION_YEARS if ENABLE_TREND_PROJECTION else 0)
        ax.axhline(ev["baseline_mean"], color="grey", lw=1.2, ls=":",
                   label=f"Baseline {ev['baseline_period'][0]}-{ev['baseline_period'][1]} mean")
        if np.isfinite(ev["baseline_std"]):
            ax.fill_between([x0, x1],
                            ev["baseline_mean"] - ev["baseline_std"],
                            ev["baseline_mean"] + ev["baseline_std"],
                            color="grey", alpha=0.10,
                            label="Baseline +/-1 sigma")

    ax.plot(years, vals, "o", ms=4, color="steelblue", alpha=0.55,
            label=f"Yearly event-window mean ({ev['trend_period'][0]}-{ev['trend_period'][1]})")
    if np.isfinite(ev["slope"]):
        fit = ev["intercept_cal"] + ev["slope"] * years
        ax.plot(years, fit, color="firebrick", lw=2.5,
                label=f"Theil-Sen {ev['slope']:+.3f} degC/yr ({mk['trend']})")
        add_trend_projection(ax, years, mk, color="firebrick", legend=True)

    label = EVENT_VAR_LABEL.get(ev["var_key"], ev["var_key"])
    ax.set_title(f"{EVENT_NAME} - {city_name}\n{label} "
                 f"({EVENT_DAY:02d}-{EVENT_MONTH:02d} +/-{EVENT_DAY_WINDOW}d, "
                 f"{EVENT_START_HOUR:02d}:{EVENT_START_MINUTE:02d} +{EVENT_DURATION_MIN}min)",
                 fontsize=11)
    ax.set_xlabel("Year")
    ax.set_ylabel(f"{label} [degC]")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def plot_event_window_distributions(ev: Dict, city_name: str, outpath: str,
                                    target_years: List[int] = None) -> None:
    """
    Normal fits of the event-window mean: baseline period, trend period, and one
    curve per projected target year.

    NORMAL FITS ONLY, on purpose. Elsewhere in this script the analysed quantity
    is an ANNUAL MAXIMUM -- a block maximum, for which GEV is the theoretically
    correct family and a normal fit is biased in exactly the tail that matters
    (see the module header). Here the analysed quantity is a MEAN over the
    event's hours, which is a sum-like statistic that the central limit theorem
    pushes toward normality, so the normal fit is appropriate rather than a
    convenient simplification. The distinction is real, not cosmetic.
    """
    if target_years is None:
        target_years = EVENT_TARGET_YEARS

    curves = []
    if len(ev["baseline_values"]) > 1:
        curves.append((f"Baseline {ev['baseline_period'][0]}-{ev['baseline_period'][1]}",
                       ev["baseline_values"], "grey"))
    curves.append((f"Reference {ev['trend_period'][0]}-{ev['trend_period'][1]}",
                   ev["trend_values"], "steelblue"))
    if np.isfinite(ev["slope"]):
        reds = plt.get_cmap("autumn_r")
        for i, ty in enumerate(sorted(target_years)):
            frac = 0.35 + 0.6 * (i / max(1, len(target_years) - 1))
            curves.append((f"Projected {ty}", _event_projected_series(ev, ty), reds(frac)))

    all_vals = np.concatenate([c[1] for c in curves])
    x = np.linspace(all_vals.min() - 3, all_vals.max() + 3, 400)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for label, vals, color in curves:
        mu = float(np.mean(vals))
        sigma = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
        if sigma <= 0:
            continue
        ax.plot(x, stats.norm.pdf(x, mu, sigma), color=color, lw=2,
                label=f"{label}  (mu={mu:.1f}, sigma={sigma:.1f})")
        ax.plot(vals, np.full(len(vals), 0.0), "|", color=color, ms=8, alpha=0.6)

    label = EVENT_VAR_LABEL.get(ev["var_key"], ev["var_key"])
    ax.set_title(f"{EVENT_NAME} - {city_name}\n{label}: distribution shift (Normal fits)",
                 fontsize=11)
    ax.set_xlabel(f"{label} [degC]")
    ax.set_ylabel("Probability density")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    fig.text(0.01, 0.01,
             "Projected curves are a naive linear extrapolation of the observed "
             f"{ev['trend_period'][0]}-{ev['trend_period'][1]} trend, not a climate model.",
             fontsize=7, style="italic")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def _ehs_build_scenarios(ev: Dict) -> List[Dict]:
    """Enumerate the scenarios to evaluate.

    Reference is run at BOTH start times, so the adaptation comparison has its
    own like-for-like baseline: an earlier start is cooler even today, and
    crediting that pre-existing difference to climate adaptation would overstate
    the lever.
    """
    scen = [
        {"key": "ref_current", "kind": "reference", "target_year": None,
         "slope": 0.0, "start_hour": EVENT_START_HOUR, "start_minute": EVENT_START_MINUTE,
         "label": f"Reference {ev['trend_period'][0]}-{ev['trend_period'][1]} "
                  f"@{EVENT_START_HOUR:02d}:{EVENT_START_MINUTE:02d}"},
    ]
    slopes = {"central": ev["slope"]}
    if EHS_USE_SLOPE_BAND:
        lo, hi = ev["mk"].get("slope_lo", np.nan), ev["mk"].get("slope_hi", np.nan)
        if np.isfinite(lo) and np.isfinite(hi):
            slopes["low"] = lo
            slopes["high"] = hi
    for ty in sorted(EHS_TARGET_YEARS):
        for sname, sval in slopes.items():
            scen.append({"key": f"proj_{ty}_{sname}", "kind": "projection",
                         "target_year": ty, "slope": sval,
                         "start_hour": EVENT_START_HOUR, "start_minute": EVENT_START_MINUTE,
                         "slope_variant": sname,
                         "label": f"{ty} @{EVENT_START_HOUR:02d}:{EVENT_START_MINUTE:02d} ({sname})"})

    adapt_changes_time = (EHS_ADAPT_START_HOUR != EVENT_START_HOUR
                          or EHS_ADAPT_START_MINUTE != EVENT_START_MINUTE)
    if adapt_changes_time:
        scen.append({"key": "ref_adapt", "kind": "reference", "target_year": None,
                     "slope": 0.0, "start_hour": EHS_ADAPT_START_HOUR,
                     "start_minute": EHS_ADAPT_START_MINUTE,
                     "label": f"Reference {ev['trend_period'][0]}-{ev['trend_period'][1]} "
                              f"@{EHS_ADAPT_START_HOUR:02d}:{EHS_ADAPT_START_MINUTE:02d}"})
        for ty in sorted(EHS_TARGET_YEARS):
            scen.append({"key": f"adapt_{ty}", "kind": "adaptation", "target_year": ty,
                         "slope": ev["slope"], "start_hour": EHS_ADAPT_START_HOUR,
                         "start_minute": EHS_ADAPT_START_MINUTE, "slope_variant": "central",
                         "label": f"{ty} @{EHS_ADAPT_START_HOUR:02d}:"
                                  f"{EHS_ADAPT_START_MINUTE:02d} (adaptation)"})
    return scen


def run_ehs_evolution(ev: Dict, event_slices: Dict[int, pd.DataFrame],
                      city: Dict, lat: float, lon: float, tz: str,
                      apply_uhi: bool) -> Optional[Dict]:
    """
    Project EHS (and EHE) for the event across target years, trend-uncertainty
    variants and an earlier-start adaptation scenario.

    For each scenario and each historical year in the trend period, the year's
    raw rural temperature is shifted by slope * (target_year - that year), the
    FULL Klimatos thermal pipeline is re-derived from the shifted value (so UHI,
    globe temperature, MRT, WBGT and UTCI stay mutually consistent -- nothing is
    shifted in isolation), and each day of the +/-window is evaluated through
    the HESTIA population ensemble.

    Averaging is over realisations, not over weather: because the dose-response
    is steeply non-linear, the mean EHS across years is NOT the EHS of the mean
    year -- hot outlier years dominate the expectation, which is exactly the
    effect this module exists to capture.

    Also collects, per realisation: the calibrated collapse-risk rate
    (COLLAPSE_ENDPOINT, default 'hospitalisation' -- the DtD-2024-calibrated
    endpoint, unlike EHE has a nonzero floor even when nobody in the ensemble
    crosses a physiological trigger) and, for the reference period and each
    target year's central-slope scenario only, a subsample of (T_rect,
    CO_reserve) pairs for the risk-zone scatter plot.
    """
    if not HESTIA_AVAILABLE:
        return None
    years = [int(y) for y in ev["trend_years"] if int(y) in event_slices]
    if len(years) < 4:
        return None

    offsets = list(range(-EVENT_DAY_WINDOW, EVENT_DAY_WINDOW + 1))
    scenarios = _ehs_build_scenarios(ev)

    tasks = []
    for sc in scenarios:
        # Scatter data (T_rect/CO_reserve pairs) is only worth collecting for
        # the two groups an organiser would actually compare on a plot: the
        # reference period, and the central-slope projection for each target
        # year -- not the low/high slope variants or the adaptation scenarios,
        # which would just clutter the same two-panel comparison this is for.
        collect_scatter = (sc["kind"] == "reference" and sc["key"] == "ref_current") or \
                          (sc["kind"] == "projection" and sc.get("slope_variant") == "central")
        for y in years:
            base = event_slices[y]
            if sc["kind"] == "reference":
                proc = base
            else:
                shifted = base.copy()
                shifted["T_air_rural"] = shifted["T_air_rural"] + sc["slope"] * (sc["target_year"] - y)
                proc = process_weather_data(shifted, city, lat, lon, tz, apply_uhi=apply_uhi)
            tasks.append({
                "weather_df": proc, "lat": lat, "lon": lon, "tz": tz, "year": y,
                "month": EVENT_MONTH, "day": EVENT_DAY, "offsets": offsets,
                "start_hour": sc["start_hour"], "start_minute": sc["start_minute"],
                "duration_minutes": EVENT_DURATION_MIN, "met_value": EHS_MET_VALUE,
                "clo_value": EHS_CLO_VALUE, "n_simulations": EHS_ENSEMBLE_N,
                "label": sc["key"], "collapse_endpoint": COLLAPSE_ENDPOINT,
                "collect_scatter": collect_scatter,
            })

    workers = EHS_MAX_WORKERS or max(1, (os.cpu_count() or 4) // 2)
    n_realisations = len(tasks) * len(offsets)
    print(f"\n[EHS] {len(scenarios)} scenarios x {len(years)} years x {len(offsets)} days "
          f"= {n_realisations} realisations, on {workers} workers")
    print("[EHS] (EHS is weather-determined, so the ensemble is deliberately small "
          f"at n={EHS_ENSEMBLE_N} -- see the CONFIG note)")
    # A rough upfront estimate, so a many-hour run is visible BEFORE it starts.
    # ~4 s per realisation per worker is a rough middle ground across machines;
    # it was 1.5 s on the (single-core, Linux) box this was developed on, and a
    # Windows machine measured ~13 s until the nested-pool fix in
    # klimatos_ehs_worker.py removed the oversubscription that caused it. Treat
    # this as an order of magnitude, not a promise -- the live ETA below is
    # measured on the run actually happening and supersedes it within a minute.
    rough_min = n_realisations * 4.0 / max(1, workers) / 60.0
    print(f"[EHS] rough estimate: ~{rough_min:.0f} min "
          f"(+/- a factor of ~3 across machines; the live ETA below is authoritative)")
    if rough_min > 90 and not TEST_MODE:
        print("[EHS] That is a long run. TEST_MODE = True at the top of this file cuts it")
        print("[EHS] to roughly an eighth, for checking the run completes before committing.")
    if workers == 1 and (os.cpu_count() or 1) > 2:
        print(f"[EHS] NOTE: running on 1 worker but {os.cpu_count()} cores are available --")
        print("[EHS] set EHS_MAX_WORKERS explicitly to use more of them.")

    collected: Dict[str, Dict[str, List]] = {
        sc["key"]: {"ehs": [], "ehe": [], "clinical": [], "collapse": [], "scatter": []}
        for sc in scenarios}
    done = 0
    t0 = time.time()
    with _futures.ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(evaluate_scenario_year, t) for t in tasks]
        for fut in _futures.as_completed(futures):
            out = fut.result()
            collected[out["label"]]["ehs"].extend(out["ehs_per_1000"])
            collected[out["label"]]["ehe"].extend(out["ehe_pct"])
            collected[out["label"]]["clinical"].extend(out.get("clinical_pct", []))
            collected[out["label"]]["collapse"].extend(out.get("collapse_per_1000", []))
            collected[out["label"]]["scatter"].extend(out.get("scatter_pairs", []))
            done += 1
            if done % 5 == 0 or done == len(tasks):
                el = time.time() - t0
                eta = el / done * (len(tasks) - done)
                progress(f"[EHS] {done}/{len(tasks)} year-tasks  "
                         f"elapsed {el/60:.1f} min  eta {eta/60:.1f} min",
                         force=(done == len(tasks)))
    progress_done()
    print(f"[EHS] done in {(time.time() - t0)/60:.1f} min.")

    results = {}
    for sc in scenarios:
        vals = collected[sc["key"]]
        results[sc["key"]] = {
            **sc,
            "ehs_mean": float(np.mean(vals["ehs"])) if vals["ehs"] else np.nan,
            "ehs_values": np.asarray(vals["ehs"], dtype=float),
            "ehe_mean": float(np.mean(vals["ehe"])) if vals["ehe"] else np.nan,
            "ehe_max": float(np.max(vals["ehe"])) if vals["ehe"] else np.nan,
            "clinical_mean": float(np.mean(vals["clinical"])) if vals["clinical"] else np.nan,
            "clinical_max": float(np.max(vals["clinical"])) if vals["clinical"] else np.nan,
            "collapse_mean": float(np.mean(vals["collapse"])) if vals["collapse"] else np.nan,
            "collapse_values": np.asarray(vals["collapse"], dtype=float),
            "scatter_pairs": vals["scatter"],
            "n": len(vals["ehs"]),
        }
    return {"scenarios": results, "years": years,
            "trend_period": ev["trend_period"], "var_key": ev["var_key"]}


def _ehe_is_resolvable(res: Dict) -> bool:
    """True only if EHE actually fires somewhere. At NW-European autumn
    conditions it does not fire at all, in which case reporting a ratio or a
    trend for it would be reporting the behaviour of zero."""
    return any(np.isfinite(s.get("ehe_max", np.nan)) and s["ehe_max"] > 0
               for s in res["scenarios"].values())


def _clinical_is_resolvable(res: Dict) -> bool:
    """Same check as _ehe_is_resolvable, for the stricter mechanistic
    criterion (T_rect>=40.5 AND CO_reserve<=0 -- hestia_bridge.py's own
    'pct_true_ehs_criterion', confusingly reusing the EHS name for a
    mechanistic threshold that has nothing to do with the Falmouth-
    calibrated falmouth_ehs_per_1000 reported as EHS everywhere else in this
    script). Being stricter than EHE (higher T_rect threshold, <=0 instead
    of <0), it is at least as likely to sit at zero."""
    return any(np.isfinite(s.get("clinical_max", np.nan)) and s["clinical_max"] > 0
               for s in res["scenarios"].values())


def build_ehs_summary(res: Dict) -> pd.DataFrame:
    """Per target year: absolute EHS rate, ratio vs reference, the trend-band
    range, and the adaptation scenario alongside."""
    scen = res["scenarios"]
    ref = scen.get("ref_current", {})
    ref_ehs = ref.get("ehs_mean", np.nan)
    ref_collapse = ref.get("collapse_mean", np.nan)
    ref_adapt = scen.get("ref_adapt", {}).get("ehs_mean", np.nan)
    ref_adapt_collapse = scen.get("ref_adapt", {}).get("collapse_mean", np.nan)
    ehe_ok = _ehe_is_resolvable(res)
    clinical_ok = _clinical_is_resolvable(res)

    rows = []
    for ty in sorted(EHS_TARGET_YEARS):
        central = scen.get(f"proj_{ty}_central", {})
        lo = scen.get(f"proj_{ty}_low", {})
        hi = scen.get(f"proj_{ty}_high", {})
        adapt = scen.get(f"adapt_{ty}", {})
        row = {
            "target_year": ty,
            "ehs_per_1000": central.get("ehs_mean", np.nan),
            "ehs_per_1000_lo": lo.get("ehs_mean", np.nan),
            "ehs_per_1000_hi": hi.get("ehs_mean", np.nan),
            "ratio_vs_reference": (central.get("ehs_mean", np.nan) / ref_ehs
                                   if np.isfinite(ref_ehs) and ref_ehs > 0 else np.nan),
            "ratio_lo": (lo.get("ehs_mean", np.nan) / ref_ehs
                         if np.isfinite(ref_ehs) and ref_ehs > 0 else np.nan),
            "ratio_hi": (hi.get("ehs_mean", np.nan) / ref_ehs
                         if np.isfinite(ref_ehs) and ref_ehs > 0 else np.nan),
            "reference_ehs_per_1000": ref_ehs,
            # Collapse-risk endpoint (COLLAPSE_ENDPOINT, default
            # 'hospitalisation' -- see that CONFIG note): same absolute +
            # ratio structure as EHS, since this metric behaves like EHS
            # (continuous, calibrated floor) rather than like EHE (hard
            # threshold, floors at exactly zero).
            "collapse_per_1000": central.get("collapse_mean", np.nan),
            "collapse_per_1000_lo": lo.get("collapse_mean", np.nan),
            "collapse_per_1000_hi": hi.get("collapse_mean", np.nan),
            "collapse_ratio_vs_reference": (
                central.get("collapse_mean", np.nan) / ref_collapse
                if np.isfinite(ref_collapse) and ref_collapse > 0 else np.nan),
            "reference_collapse_per_1000": ref_collapse,
        }
        if adapt:
            row["ehs_per_1000_early_start"] = adapt.get("ehs_mean", np.nan)
            row["ratio_early_start_vs_reference"] = (
                adapt.get("ehs_mean", np.nan) / ref_ehs
                if np.isfinite(ref_ehs) and ref_ehs > 0 else np.nan)
            # like-for-like: the early start compared with an early start today
            row["ratio_early_start_vs_early_reference"] = (
                adapt.get("ehs_mean", np.nan) / ref_adapt
                if np.isfinite(ref_adapt) and ref_adapt > 0 else np.nan)
            if np.isfinite(central.get("ehs_mean", np.nan)) and central["ehs_mean"] > 0:
                row["reduction_from_early_start_pct"] = 100.0 * (
                    1.0 - adapt.get("ehs_mean", np.nan) / central["ehs_mean"])
            row["collapse_per_1000_early_start"] = adapt.get("collapse_mean", np.nan)
            row["collapse_ratio_early_start_vs_early_reference"] = (
                adapt.get("collapse_mean", np.nan) / ref_adapt_collapse
                if np.isfinite(ref_adapt_collapse) and ref_adapt_collapse > 0 else np.nan)
            if np.isfinite(central.get("collapse_mean", np.nan)) and central["collapse_mean"] > 0:
                row["collapse_reduction_from_early_start_pct"] = 100.0 * (
                    1.0 - adapt.get("collapse_mean", np.nan) / central["collapse_mean"])
        row["ehe_resolvable"] = ehe_ok
        if ehe_ok:
            row["ehe_pct"] = central.get("ehe_mean", np.nan)
            row["ehe_pct_reference"] = ref.get("ehe_mean", np.nan)
        row["clinical_resolvable"] = clinical_ok
        if clinical_ok:
            row["clinical_pct"] = central.get("clinical_mean", np.nan)
            row["clinical_pct_reference"] = ref.get("clinical_mean", np.nan)
        rows.append(row)
    return pd.DataFrame(rows)


def plot_ehs_evolution(res: Dict, summary: pd.DataFrame, city_name: str,
                       outpath: str) -> None:
    """Two panels: absolute EHS rate with the trend-uncertainty band and the
    adaptation scenario (left), and the same as a ratio to the reference period
    (right). The ratio panel is the robust one -- a systematic calibration error
    largely cancels in the quotient -- so both are shown side by side rather
    than choosing one."""
    if summary.empty:
        return
    scen = res["scenarios"]
    ref_ehs = scen.get("ref_current", {}).get("ehs_mean", np.nan)
    if not np.isfinite(ref_ehs) or ref_ehs <= 0:
        return
    years = summary["target_year"].values
    ref_year = int(np.mean(res["trend_period"]))
    has_adapt = "ehs_per_1000_early_start" in summary.columns

    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.2))

    ax = axes[0]
    x = np.concatenate([[ref_year], years])
    y = np.concatenate([[ref_ehs], summary["ehs_per_1000"].values])
    ax.plot(x, y, "o-", color="firebrick", lw=2.2, label="Current start time")
    if summary[["ehs_per_1000_lo", "ehs_per_1000_hi"]].notna().all(axis=None):
        lo = np.concatenate([[ref_ehs], summary["ehs_per_1000_lo"].values])
        hi = np.concatenate([[ref_ehs], summary["ehs_per_1000_hi"].values])
        ax.fill_between(x, np.minimum(lo, hi), np.maximum(lo, hi), color="firebrick",
                        alpha=0.15, label="Sen's slope 95% CI")
    if has_adapt:
        ya = np.concatenate([[scen.get("ref_adapt", {}).get("ehs_mean", np.nan)],
                             summary["ehs_per_1000_early_start"].values])
        ax.plot(x, ya, "s--", color="steelblue", lw=2.2,
                label=f"Start {EHS_ADAPT_START_HOUR:02d}:{EHS_ADAPT_START_MINUTE:02d}")
    ax.axhline(ref_ehs, color="grey", ls=":", lw=1)
    ax.set_xlabel("Year")
    ax.set_ylabel("EHS per 1000 participants")
    ax.set_title("Absolute rate (Falmouth-calibrated)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[1]
    r = np.concatenate([[1.0], summary["ratio_vs_reference"].values])
    ax.plot(x, r, "o-", color="firebrick", lw=2.2, label="Current start time")
    if summary[["ratio_lo", "ratio_hi"]].notna().all(axis=None):
        rlo = np.concatenate([[1.0], summary["ratio_lo"].values])
        rhi = np.concatenate([[1.0], summary["ratio_hi"].values])
        ax.fill_between(x, np.minimum(rlo, rhi), np.maximum(rlo, rhi),
                        color="firebrick", alpha=0.15, label="Sen's slope 95% CI")
    if has_adapt:
        ra = np.concatenate([[scen.get("ref_adapt", {}).get("ehs_mean", np.nan) / ref_ehs],
                             summary["ratio_early_start_vs_reference"].values])
        ax.plot(x, ra, "s--", color="steelblue", lw=2.2,
                label=f"Start {EHS_ADAPT_START_HOUR:02d}:{EHS_ADAPT_START_MINUTE:02d}")
    ax.axhline(1.0, color="grey", ls=":", lw=1)
    ax.set_xlabel("Year")
    ax.set_ylabel(f"x reference ({res['trend_period'][0]}-{res['trend_period'][1]})")
    ax.set_title("Relative to reference period (robust to calibration error)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)

    fig.suptitle(f"{EVENT_NAME} - {city_name}: projected exertional heat stroke\n"
                 f"CONDITIONAL on unchanged start time, participant population and policy",
                 fontsize=11)
    fig.text(0.01, 0.01,
             "Naive linear extrapolation of the observed trend, not a climate model. "
             "The projected scenario is one that adaptation is expected to prevent - "
             "it is an argument for acting, not a forecast.",
             fontsize=7, style="italic")
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def _ehe_margin_stats(pairs: List[Tuple[float, float]],
                      t_threshold: float = 39.5, c_threshold: float = 0.0) -> Optional[Dict]:
    """
    How far the sampled population sat from a conjunctive T_rect/CO_reserve
    threshold, computed from the same (T_rect, CO_reserve) pairs the scatter
    plot uses -- no extra simulation. Defaults to EHE's own threshold
    (T_rect > 39.5 degC AND CO_reserve < 0); pass t_threshold=40.5,
    c_threshold=0.0 for the stricter mechanistic ("clinical") criterion
    instead -- the maths is identical, only the two numbers differ.

    A conjunctive criterion requires BOTH margins to close simultaneously, so
    how close any one point sits to actually triggering it is governed by
    whichever margin is still furthest from zero, not by either axis alone:
    closing only the smaller gap is not enough on its own. That "bottleneck"
    margin (max(t_threshold-T_rect, CO_reserve-c_threshold), minimised across
    all sampled points) is what "closest observed point" reports -- if
    positive, it is exactly how far the harder-to-close axis still has to
    move for that specific sampled moment to become a hit.

    Also reports population-level percentiles per axis (median and the 95th/
    5th percentile -- the tail, since this is a rare-event question, not an
    average-case one), separately from the combined bottleneck.
    """
    if not pairs:
        return None
    t = np.array([p[0] for p in pairs])
    c = np.array([p[1] for p in pairs])
    margin_t = t_threshold - t   # +: still below the T_rect threshold
    margin_c = c - c_threshold   # +: still above the CO_reserve threshold
    bottleneck = np.maximum(margin_t, margin_c)
    idx = int(np.argmin(bottleneck))
    return {
        "n": len(pairs), "t_threshold": t_threshold, "c_threshold": c_threshold,
        "t_p50": float(np.median(t)), "t_p95": float(np.percentile(t, 95)),
        "c_p50": float(np.median(c)), "c_p05": float(np.percentile(c, 5)),
        "closest_t": float(t[idx]), "closest_c": float(c[idx]),
        "closest_bottleneck": float(bottleneck[idx]),
    }


def _format_ehe_margin_line(label: str, stats: Optional[Dict]) -> List[str]:
    """Console lines for one scenario's margin-to-threshold summary."""
    if stats is None:
        return [f"  {label}: no sampled data available."]
    tt, ct = stats["t_threshold"], stats["c_threshold"]
    lines = [
        f"  {label} (n={stats['n']} sampled timesteps):",
        f"    T_rect      median {stats['t_p50']:.2f} degC "
        f"({tt - stats['t_p50']:+.2f} from the {tt:.1f} degC threshold), "
        f"95th pct {stats['t_p95']:.2f} degC "
        f"({tt - stats['t_p95']:+.2f} from threshold)",
        f"    CO reserve  median {stats['c_p50']:.2f} L/min "
        f"({stats['c_p50'] - ct:+.2f} from the {ct:.1f} L/min threshold), "
        f"5th pct {stats['c_p05']:.2f} L/min "
        f"({stats['c_p05'] - ct:+.2f} from threshold)",
    ]
    bn = stats["closest_bottleneck"]
    if bn > 0:
        lines.append(f"    closest observed point: T_rect={stats['closest_t']:.2f} degC, "
                     f"CO_reserve={stats['closest_c']:.2f} L/min "
                     f"-> {bn:.2f} short of the harder-to-close threshold")
    else:
        lines.append(f"    closest observed point: T_rect={stats['closest_t']:.2f} degC, "
                     f"CO_reserve={stats['closest_c']:.2f} L/min "
                     f"-> both thresholds crossed at this moment "
                     f"(momentary, not necessarily a sustained EHE hit -- see EHE's own "
                     f"simultaneity window)")
    return lines


def plot_trect_co_reserve_scatter(res: Dict, city_name: str, outpath: str,
                                  target_year: Optional[int] = None) -> None:
    """
    Scatter of every sampled (T_rect, CO_reserve) pair -- reference period vs.
    one target year's central-slope projection -- with two horizontal risk
    zones shaded on the T_rect axis: T_rect > 39.5 degC (EHE's own threshold)
    and T_rect > 40.5 degC (the stricter mechanistic threshold this codebase
    elsewhere calls clinical EHS, and the collapse-risk model's second-phase
    trigger). Zones span the whole CO_reserve range shown, since the request
    was for each threshold "against CO_reserve", not for the conjunctive
    (T_rect>39.5 AND CO_reserve<0) region EHE actually uses -- that
    conjunction is instead visualised directly: points are coloured by
    whether they fall inside it, which is more informative than a static
    rectangle for how close the population sits to the actual criterion.

    Falls back to whichever target year has scatter data if target_year is
    not given or has none (run_ehs_evolution only collects scatter for the
    reference period and each target year's CENTRAL slope scenario, not the
    low/high variants or the adaptation scenarios -- see its own docstring).
    """
    scen = res["scenarios"]
    ref_pairs = scen.get("ref_current", {}).get("scatter_pairs", [])
    if target_year is None:
        candidates = [k for k in scen if k.startswith("proj_") and k.endswith("_central")
                     and scen[k].get("scatter_pairs")]
        key = candidates[-1] if candidates else None
    else:
        key = f"proj_{target_year}_central"
    proj_pairs = scen.get(key, {}).get("scatter_pairs", []) if key else []
    if not ref_pairs and not proj_pairs:
        return
    resolved_year = key.split("_")[1] if key else "?"

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharex=True, sharey=True)
    all_pairs = (ref_pairs or []) + (proj_pairs or [])
    co_vals = [c for _, c in all_pairs] if all_pairs else [-1, 1]
    t_vals = [t for t, _ in all_pairs] if all_pairs else [37, 41]
    x_lo, x_hi = min(co_vals) - 0.3, max(co_vals) + 0.3
    y_lo, y_hi = min(min(t_vals), 38.5), max(max(t_vals), 41.0)

    for ax, pairs, label in ((axes[0], ref_pairs, f"Reference {res['trend_period'][0]}-"
                              f"{res['trend_period'][1]}"),
                             (axes[1], proj_pairs, f"Projected {resolved_year} (central slope)")):
        # Risk zones, back to front: 39.5-40.5 (amber) then >40.5 (red) drawn
        # over it, both spanning the full CO_reserve range shown.
        ax.axhspan(39.5, 40.5, xmin=0, xmax=1, color="#f0a30a", alpha=0.18,
                  label="T_rect > 39.5 degC (EHE threshold)", zorder=0)
        ax.axhspan(40.5, y_hi, xmin=0, xmax=1, color="#d62728", alpha=0.22,
                  label="T_rect > 40.5 degC (clinical EHS threshold)", zorder=0)
        ax.axvline(0, color="black", lw=1, ls=":", zorder=1)
        if pairs:
            t_arr = np.array([t for t, _ in pairs])
            c_arr = np.array([c for _, c in pairs])
            # EHE's actual conjunctive criterion: T_rect>39.5 AND CO_reserve<0.
            # Coloured directly rather than left to the viewer to infer from
            # the two axes separately.
            in_ehe = (t_arr > 39.5) & (c_arr < 0)
            in_clinical = (t_arr >= 40.5) & (c_arr <= 0)
            ax.scatter(c_arr[~in_ehe], t_arr[~in_ehe], s=10, color="steelblue",
                      alpha=0.5, zorder=2, label="Sampled timestep")
            ax.scatter(c_arr[in_ehe & ~in_clinical], t_arr[in_ehe & ~in_clinical],
                      s=16, color="black", alpha=0.8, zorder=3,
                      label="Meets EHE (T>39.5 AND COr<0)")
            if in_clinical.any():
                ax.scatter(c_arr[in_clinical], t_arr[in_clinical], s=22, marker="X",
                          color="#8B0000", zorder=3,
                          label="Meets clinical criterion (T>=40.5 AND COr<=0)")
            # Closest-approach markers + margin annotations -- see
            # _ehe_margin_stats()'s docstring for why the "bottleneck" margin
            # (not either axis alone) is what determines distance to each
            # threshold. Two thresholds, two markers, colour-matched to the
            # zones they belong to (amber/EHE vs. red/clinical) so the
            # marker and the shaded band it refers to read as one pair.
            for mstats, colour, zone_label, msize, y_off in (
                (_ehe_margin_stats(pairs, 39.5, 0.0), "#c07800", "EHE", 130, 8),
                (_ehe_margin_stats(pairs, 40.5, 0.0), "#8B0000", "clinical", 70, -16),
            ):
                if mstats is None:
                    continue
                ax.scatter([mstats["closest_c"]], [mstats["closest_t"]],
                          s=msize, facecolors="none", edgecolors=colour,
                          linewidths=2, zorder=4,
                          label=f"Closest to {zone_label} threshold")
                bn = mstats["closest_bottleneck"]
                note = (f"{bn:.2f} from {zone_label}" if bn > 0 else f"{zone_label} crossed")
                # y_off staggers the two labels vertically so they stay legible
                # even when the two closest points coincide or sit very close
                # together (observed directly: with a shared xytext offset the
                # two notes rendered on top of each other as unreadable text).
                ax.annotate(note, xy=(mstats["closest_c"], mstats["closest_t"]),
                          xytext=(10, y_off), textcoords="offset points",
                          fontsize=7, color=colour, fontweight="bold")
        ax.set_xlim(x_lo, x_hi)
        ax.set_ylim(y_lo, y_hi)
        ax.set_xlabel("CO reserve (L/min)")
        ax.set_title(f"{label}\n(n={len(pairs)} sampled timesteps)", fontsize=10)
        ax.grid(alpha=0.2)
    axes[0].set_ylabel("T_rect (degC)")
    axes[0].legend(fontsize=7, loc="lower left")
    fig.suptitle(f"{EVENT_NAME} - {city_name}: T_rect vs. CO reserve, risk zones", fontsize=11)
    fig.text(0.01, 0.01,
             "Subsampled per realisation (see SCATTER_PAIRS_PER_DAY_CAP in "
             "klimatos_ehs_worker.py) -- density is indicative, not a full census.",
             fontsize=7, style="italic")
    fig.tight_layout(rect=(0, 0.03, 1, 0.95))
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def build_event_summary(evs: Dict[str, Dict]) -> pd.DataFrame:
    """Tabular summary of the event module: per variable, the baseline mean, the
    trend-period mean, the fitted slope and the projected value per target year."""
    rows = []
    for var_key, ev in evs.items():
        if ev is None:
            continue
        row = {
            "variable": var_key,
            "label": EVENT_VAR_LABEL.get(var_key, var_key),
            "baseline_period": f"{ev['baseline_period'][0]}-{ev['baseline_period'][1]}",
            "baseline_mean": ev["baseline_mean"],
            "baseline_std": ev["baseline_std"],
            "n_baseline": ev["n_baseline"],
            "trend_period": f"{ev['trend_period'][0]}-{ev['trend_period'][1]}",
            "trend_mean": ev["trend_mean"],
            "n_trend": ev["n_trend"],
            "slope_degC_per_yr": ev["slope"],
            "slope_lo": ev["mk"].get("slope_lo", np.nan),
            "slope_hi": ev["mk"].get("slope_hi", np.nan),
            "mk_p": ev["mk"].get("p", np.nan),
            "mk_trend": ev["mk"].get("trend", "n/a"),
            "trend_mean_vs_baseline": (ev["trend_mean"] - ev["baseline_mean"]
                                       if np.isfinite(ev["baseline_mean"]) else np.nan),
        }
        if np.isfinite(ev["slope"]):
            for ty in sorted(EVENT_TARGET_YEARS):
                proj = float(np.mean(_event_projected_series(ev, ty)))
                row[f"projected_{ty}"] = proj
                if np.isfinite(ev["baseline_mean"]):
                    row[f"projected_{ty}_vs_baseline"] = proj - ev["baseline_mean"]
        rows.append(row)
    return pd.DataFrame(rows)

# =============================================================================
# Heat-attributable hospital admissions (ERF: van Loenhout et al. 2018)
# =============================================================================

def heat_admission_indices(daily_max: pd.Series,
                           mmt: float = ERF_MMT_C, beta: float = ERF_BETA_PER_C):
    """From a series of daily-max temperatures, return:
       hdd  - heat degree-days above MMT (beta-free): sum max(0, Tmax - MMT)
       hai  - ERF heat-attributable index: sum (exp(beta*excess) - 1), proportional
              to expected heat-attributable admissions at constant baseline+population
       n    - number of days above MMT.
    """
    x = np.clip(daily_max.values.astype(float) - mmt, 0.0, None)
    hdd = float(np.sum(x))
    hai = float(np.sum(np.exp(beta * x) - 1.0))
    n = int(np.sum(x > 0))
    return hdd, hai, n


def analyze_admissions_windows(annual: pd.DataFrame, windows: List[Tuple[int, int]],
                               ref_window: Tuple[int, int]) -> pd.DataFrame:
    """Per window: mean annual heat-admission index (ERF) and heat degree-days
    (beta-free), each expressed as a RATIO relative to the reference window -
    i.e. 'how many times more heat-attributable admissions than the 1951-1980
    climate, holding the ERF and population constant'."""
    def wmean(a, b, col):
        s = annual[col]
        return float(s[(s.index >= a) & (s.index <= b)].dropna().mean())

    ref_hai = wmean(*ref_window, "heat_admit_index")
    ref_hdd = wmean(*ref_window, "heat_degree_days")
    rows = []
    for (a, b) in [ref_window] + windows:
        s_hai = annual["heat_admit_index"]
        s_hdd = annual["heat_degree_days"]
        s_n = annual["n_days_over_mmt"]
        m_hai = float(s_hai[(s_hai.index >= a) & (s_hai.index <= b)].dropna().mean())
        m_hdd = float(s_hdd[(s_hdd.index >= a) & (s_hdd.index <= b)].dropna().mean())
        m_n = float(s_n[(s_n.index >= a) & (s_n.index <= b)].dropna().mean())
        rows.append({
            "window": f"{a}-{b}", "start": a, "end": b,
            "is_reference": (a, b) == ref_window,
            "mean_days_over_mmt": m_n,
            "mean_heat_degree_days": m_hdd,
            "mean_heat_admit_index": m_hai,
            "ratio_HDD_vs_ref": (m_hdd / ref_hdd) if ref_hdd > 0 else np.nan,
            "ratio_ERF_vs_ref": (m_hai / ref_hai) if ref_hai > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def plot_admissions_timeseries(annual: pd.DataFrame, ref_window: Tuple[int, int],
                               city_name: str, outpath: str) -> None:
    """Annual heat-attributable admission index vs year, with reference-period
    mean and robust (Theil-Sen / Mann-Kendall) trend."""
    if "heat_admit_index" not in annual:
        return
    s = annual["heat_admit_index"].dropna()
    if len(s) < 4:
        return
    years = s.index.values.astype(float)
    vals = s.values
    mk = mann_kendall(vals)

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.bar(years, vals, color="indianred", alpha=0.75, width=0.8, label="Annual heat-admission index (ERF)")
    if np.isfinite(mk["slope"]):
        x0 = np.arange(len(vals))
        ax.plot(years, mk["intercept"] + mk["slope"] * x0, "k-", lw=2.2,
                label=f"Theil-Sen trend ({mk['trend']})")
        add_trend_projection(ax, years, mk, color="black")
    ref = s.loc[(s.index >= ref_window[0]) & (s.index <= ref_window[1])]
    if len(ref) > 0:
        ax.axhline(float(ref.mean()), color="navy", ls="--", lw=1.4,
                   label=f"Reference {ref_window[0]}-{ref_window[1]} mean")
    proj_note = f" (dashed: naive {PROJECTION_YEARS}-yr linear extrapolation, not a forecast)" \
        if (ENABLE_TREND_PROJECTION and mk.get("n", 0) >= PROJECTION_MIN_YEARS) else ""
    ax.set_title(f"Heat-attributable hospital-admission index (van Loenhout ERF)\n{city_name}{proj_note}",
                fontsize=11)
    ax.set_xlabel("Year")
    ax.set_ylabel("Annual index  [sum (RR-1) over May-Sep days]")
    ax.legend(fontsize=8, loc="upper left")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def plot_admissions_window_ratio(adf: pd.DataFrame, city_name: str, outpath: str) -> None:
    """Bar chart of per-window ratio vs reference: ERF-based and beta-free (HDD)."""
    if adf.empty:
        return
    labels = adf["window"].tolist()
    x = np.arange(len(labels))
    w = 0.38
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.bar(x - w / 2, adf["ratio_ERF_vs_ref"], width=w, color="indianred",
           label="ERF (van Loenhout, beta-dependent)")
    ax.bar(x + w / 2, adf["ratio_HDD_vs_ref"], width=w, color="steelblue",
           label="Heat degree-days (beta-free)")
    ax.axhline(1.0, color="black", lw=1)
    for i, (re_, rh) in enumerate(zip(adf["ratio_ERF_vs_ref"], adf["ratio_HDD_vs_ref"])):
        if np.isfinite(re_):
            ax.text(x[i] - w / 2, re_, f"{re_:.2f}", ha="center", va="bottom", fontsize=8)
        if np.isfinite(rh):
            ax.text(x[i] + w / 2, rh, f"{rh:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_title(f"Heat-attributable admissions relative to reference climate\n{city_name}")
    ax.set_ylabel("Ratio vs reference window  (1.0 = reference)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)

# =============================================================================
# Physiological liveability (HEAT-Lim, Vanos et al. 2023) - validated chain
# =============================================================================

def compute_mmax_met(Ta_C, RH, Av_ms, mrt_C, profile, exp_time=LIVEABILITY_EXP_TIME):
    """Per-hour maximum sustainable activity Mmax [METs] via the ORIGINAL HEAT-Lim
    biophysical chain (partitional calorimetry). Returns (Mmax_MET, survivable).
    Mmax is NaN where heat stress is non-compensable or non-survivable.
    This replicates HEAT-Lim's LiveabilityMatrix tutorial exactly (validated to
    < 1e-14 against the authors' published Mmax matrices)."""
    H = HEATLIM
    Ta_C = np.asarray(Ta_C, float); RH = np.asarray(RH, float)
    Av_ms = np.asarray(Av_ms, float); mrt_C = np.asarray(mrt_C, float)
    n = len(Ta_C)
    AD = np.ones(n) * float(profile["AD"])
    Psa = H.Psa_kPa_from_TaC(Ta_C)
    Pv_kPa = H.Pv_kPa_from_Psa_RH(Psa, RH)
    M = np.ones(n) * float(profile["M"]) * float(profile["Mass"])
    Tsk_C = np.ones(n) * float(profile["Tsk_C"])
    Emm = np.ones(n) * float(profile["Emm_sk"])
    Ar_AD = np.ones(n) * float(profile["A_eff"])
    Icl = np.ones(n) * float(profile["Icl"])
    hc = H.hc_cof_from_Av(Av_ms)
    hr = H.hr_cof_from_radiant_features(mrt_C, Tsk_C, Emm, Ar_AD)
    h = H.h_coef_from_hc_hr(hc, hr)
    to = H.to_from_hr_tr_hc_ta(hr, mrt_C, hc, Ta_C)
    Dry = H.Dry_Heat_Loss_c_plus_r(Tsk_C, to, Icl, h, AD)
    Cres = H.Cres_from_M_Ta(M, Ta_C, AD)
    Eres = H.Eres_from_M_Pa(M, Pv_kPa, AD)
    Re_cl = np.ones(n) * float(profile["Re_cl"])
    Ereq = H.Ereq_from_HeatFluxes(M, 0, Dry, Cres, Eres)
    Psk_s = H.Psa_kPa_from_TaC(Tsk_C)
    he = H.he_cof(hc)
    with np.errstate(divide="ignore", invalid="ignore"):
        Emax_env = H.Emax_env(Psk_s, Pv_kPa, Re_cl, he, Icl, AD)
        Emax_env = np.where(Emax_env < 0, 0, Emax_env)
        wmax = np.ones(n) * H.wmax(profile["wmax_condition"])
        Emax_wet = H.Emax_wettedness(wmax, Psk_s, Pv_kPa, Re_cl, he, Icl, AD)
        Emax_wet = np.where(Emax_wet < 0, 0, Emax_wet)
        wreq = H.wreq_HSI_skin_wettedness(Ereq, Emax_env)
        r = H.Sweating_efficiency_r(wreq)
        Sreq = H.Sreq(Ereq, r, H.Lh_vap)
        Smax = np.ones(n) * float(profile["smax_rate"])
        Emax_sweat = H.Emax_sweat_rate(Smax, H.Lh_vap, 1, r)
        surv, _ = H.Survivability(exp_time, Ereq, Emax_wet, Emax_sweat, Sreq, Smax, float(profile["Mass"]))
        Mmax, _ = H.livability_Mmax(surv, Ereq, Emax_wet, Emax_sweat, M, float(profile["Mass"]))
    Mmax = np.asarray(Mmax, float)
    surv = np.asarray(surv, bool)
    Mmax[~surv] = np.nan            # non-survivable -> liveability undefined
    return Mmax, surv


def liveability_year_metrics(proc: pd.DataFrame) -> Dict:
    """For one processed year, compute per-profile liveability + survivability
    metrics over the warm hours (Ta >= LIVEABILITY_TA_MIN):
        min_Mmax    - lowest sustainable activity reached (worst hour) [METs]
        hrs_below   - hours where sustainable activity < LIVEABILITY_ACTIVITY_MET
        hrs_nonliv  - hours survivable but non-compensable (no activity possible)
        hrs_nonsurv - hours NON-survivable (survivability breached)
    Also records the (Ta, RH) of the year's peak-wet-bulb hour, for overlay on
    the survivability matrix.
    """
    out = {}
    Ta = proc["T_air_urban"].values
    # RH_urban (if present) is the UHI-adjusted humidity from process_weather_
    # data() -- see adjust_rh_for_uhi()'s docstring. Same fix as WBGT/UTCI/
    # wet-bulb: Ta here is already UHI-elevated, so pairing it with the raw
    # rural RH would repeat the same "same RH% at a higher temperature"
    # error this session found and corrected there.
    RH = proc["RH_urban"].values if "RH_urban" in proc.columns else proc["RH"].values
    Av = np.clip(proc["wind_1.5m"].values, LIVEABILITY_MIN_WIND, None)
    mrt = proc["MRT"].values if LIVEABILITY_SUN == "outdoor" else Ta.copy()

    # peak physiological-stress hour of the year (highest wet-bulb) for overlay
    wb = proc["T_wetbulb"].values
    if np.isfinite(wb).any():
        ipk = int(np.nanargmax(wb))
        out["peakTa"] = float(Ta[ipk])
        out["peakRH"] = float(RH[ipk])
    else:
        out["peakTa"] = np.nan; out["peakRH"] = np.nan

    warm = Ta >= LIVEABILITY_TA_MIN
    for pkey, prof in LIVEABILITY_PROFILES.items():
        if warm.sum() == 0:
            out[f"minMmax_{pkey}"] = np.nan
            out[f"hrsBelow_{pkey}"] = 0
            out[f"hrsNonLiv_{pkey}"] = 0
            out[f"hrsNonSurv_{pkey}"] = 0
            continue
        mmax, surv = compute_mmax_met(Ta[warm], RH[warm], Av[warm], mrt[warm], prof)
        out[f"minMmax_{pkey}"] = float(np.nanmin(mmax)) if np.isfinite(mmax).any() else np.nan
        below = ~(mmax >= LIVEABILITY_ACTIVITY_MET)          # NaN counts as below
        out[f"hrsBelow_{pkey}"] = int(np.sum(below))
        out[f"hrsNonLiv_{pkey}"] = int(np.sum(np.isnan(mmax) & surv))
        out[f"hrsNonSurv_{pkey}"] = int(np.sum(~surv))       # survivability breached
    return out


def analyze_liveability_windows(annual: pd.DataFrame, windows: List[Tuple[int, int]],
                                ref_window: Tuple[int, int]) -> pd.DataFrame:
    """Per window: mean of each liveability metric per profile, plus the change
    in min-Mmax vs the reference and the ratio of below-activity hours vs ref."""
    def wmean(a, b, col):
        s = annual[col]
        return float(s[(s.index >= a) & (s.index <= b)].dropna().mean())

    ref_below = {p: wmean(*ref_window, f"hrsBelow_{p}") for p in LIVEABILITY_PROFILES}
    ref_minm = {p: wmean(*ref_window, f"minMmax_{p}") for p in LIVEABILITY_PROFILES}
    rows = []
    for (a, b) in [ref_window] + windows:
        row = {"window": f"{a}-{b}", "start": a, "end": b, "is_reference": (a, b) == ref_window}
        for p in LIVEABILITY_PROFILES:
            m_min = wmean(a, b, f"minMmax_{p}")
            m_below = wmean(a, b, f"hrsBelow_{p}")
            m_nonliv = wmean(a, b, f"hrsNonLiv_{p}")
            m_nonsurv = wmean(a, b, f"hrsNonSurv_{p}")
            row[f"minMmax_{p}"] = m_min
            row[f"hrsBelow_{p}"] = m_below
            row[f"hrsNonLiv_{p}"] = m_nonliv
            row[f"hrsNonSurv_{p}"] = m_nonsurv
            row[f"dMinMmax_{p}_vs_ref"] = m_min - ref_minm[p]
            row[f"ratioBelow_{p}_vs_ref"] = (m_below / ref_below[p]) if ref_below[p] > 0 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def plot_liveability_timeseries(annual: pd.DataFrame, ref_window: Tuple[int, int],
                                city_name: str, outpath: str) -> None:
    """Annual worst-hour Mmax vs year for both profiles, with robust trend and
    activity-level reference lines."""
    fig, ax = plt.subplots(figsize=(11, 6))
    colors = {"young": "tab:blue", "old": "tab:red"}
    plotted = False
    any_projected = False
    first_proj_legend = True
    for pkey in LIVEABILITY_PROFILES:
        col = f"minMmax_{pkey}"
        if col not in annual:
            continue
        s = annual[col].dropna()
        if len(s) < 4:
            continue
        years = s.index.values.astype(float)
        ax.plot(years, s.values, "o-", ms=3, lw=1, color=colors[pkey], alpha=0.85,
                label=LIVEABILITY_PROFILE_LABEL[pkey])
        mk = mann_kendall(s.values)
        if np.isfinite(mk["slope"]):
            x0 = np.arange(len(s))
            ax.plot(years, mk["intercept"] + mk["slope"] * x0, "-", lw=2, color=colors[pkey],
                    alpha=0.6)
            add_trend_projection(ax, years, mk, color=colors[pkey], legend=first_proj_legend)
            if mk.get("n", 0) >= PROJECTION_MIN_YEARS:
                any_projected = True
                first_proj_legend = False
        plotted = True
    if not plotted:
        plt.close(fig); return
    for met, lab in [(1.5, "rest"), (2.5, "walking"), (3.3, "light chores"), (7.0, "running")]:
        ax.axhline(met, color="grey", ls=":", lw=0.8)
        ax.text(ax.get_xlim()[0], met, f" {lab} ({met})", va="bottom", ha="left",
                fontsize=7, color="grey")
    ax.axvspan(ref_window[0], ref_window[1], color="grey", alpha=0.10, label="reference period")
    proj_note = f" (dashed: naive {PROJECTION_YEARS}-yr linear extrapolation, not a forecast)" \
        if any_projected else ""
    ax.set_title(f"Worst-hour liveability (max sustainable activity) - HEAT-Lim\n{city_name}"
                 f"  [UHI-sensitive; sun={LIVEABILITY_SUN}]{proj_note}", fontsize=11)
    ax.set_xlabel("Year")
    ax.set_ylabel("Min. annual Mmax  [METs]")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def plot_liveability_window_bar(ldf: pd.DataFrame, city_name: str, outpath: str) -> None:
    """Per-window mean worst-hour Mmax for both profiles (grouped bars)."""
    if ldf.empty:
        return
    labels = ldf["window"].tolist()
    x = np.arange(len(labels))
    w = 0.38
    fig, ax = plt.subplots(figsize=(11, 6))
    if "minMmax_young" in ldf:
        ax.bar(x - w / 2, ldf["minMmax_young"], width=w, color="tab:blue",
               label=LIVEABILITY_PROFILE_LABEL["young"])
    if "minMmax_old" in ldf:
        ax.bar(x + w / 2, ldf["minMmax_old"], width=w, color="tab:red",
               label=LIVEABILITY_PROFILE_LABEL["old"])
    for met, lab in [(2.5, "walking"), (3.3, "light chores")]:
        ax.axhline(met, color="grey", ls="--", lw=1)
        ax.text(x[-1] + 0.4, met, lab, va="center", ha="left", fontsize=8, color="grey")
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax.set_title(f"Mean worst-hour liveability per window (lower = worse)\n{city_name}")
    ax.set_ylabel("Mean min. annual Mmax  [METs]")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def _wetbulb_grid(TA: np.ndarray, RH: np.ndarray) -> np.ndarray:
    """Wet-bulb temperature over a Ta x RH grid (pythermalcomfort), for the
    classic 35 degC Tw survivability isoline."""
    flat_t = TA.ravel(); flat_rh = RH.ravel()
    if WET_BULB_FUNC == 'models':
        tw = wet_bulb_temperature(tdb=flat_t, rh=flat_rh,
                                  pressure=np.full(flat_t.shape, 101325.0))
    else:
        tw = wet_bulb_temperature(tdb=flat_t, rh=flat_rh)
    return np.asarray(tw, float).reshape(TA.shape)


def _matrix_grid_setup():
    """Shared Ta x RH grid + MRT/wind/Tw setup for the HEAT-Lim matrix plots,
    so the survivability and liveability matrices are built on identical grids."""
    ta_range = np.arange(20.0, 50.1, 0.25)
    rh_range = np.arange(2.0, 100.5, 1.0)
    TA, RH = np.meshgrid(ta_range, rh_range)
    mrt = TA + 15.0 if LIVEABILITY_SUN == "outdoor" else TA.copy()
    Av = np.full(TA.size, max(1.0, LIVEABILITY_MIN_WIND))
    tw_grid = _wetbulb_grid(TA, RH)
    return ta_range, rh_range, TA, RH, mrt, Av, tw_grid


def _city_peak_points(annual: pd.DataFrame, win: Tuple[int, int]):
    m = (annual.index >= win[0]) & (annual.index <= win[1])
    sub = annual.loc[m, ["peakTa", "peakRH"]].dropna()
    return sub["peakTa"].values, sub["peakRH"].values


def plot_survivability_matrix(annual: pd.DataFrame, ref_window: Tuple[int, int],
                              latest_window: Tuple[int, int], city_name: str,
                              outpath: str) -> None:
    """HEAT-Lim survivability matrix (Ta x RH) for both profiles, with the classic
    35 degC Tw isoline and the city's annual peak-wet-bulb hours overlaid
    (reference window vs latest window) so the climate shift toward the limits
    is visible. Uses the same validated HEAT-Lim chain."""
    if not (HEATLIM_AVAILABLE and "peakTa" in annual.columns):
        return
    ta_range, rh_range, TA, RH, mrt, Av, tw_grid = _matrix_grid_setup()

    profs = list(LIVEABILITY_PROFILES.items())
    fig, axes = plt.subplots(1, len(profs), figsize=(7 * len(profs), 6), squeeze=False)

    ref_ta, ref_rh = _city_peak_points(annual, ref_window)
    lat_ta, lat_rh = _city_peak_points(annual, latest_window)

    for ax, (pkey, prof) in zip(axes[0], profs):
        mmax, surv = compute_mmax_met(TA.ravel(), RH.ravel(), Av, mrt.ravel(), prof)
        surv = surv.reshape(TA.shape).astype(float)
        mmaxg = mmax.reshape(TA.shape)
        # survivable (green) vs non-survivable (red) zones
        ax.contourf(TA, RH, surv, levels=[-0.5, 0.5, 1.5],
                    colors=["#f2b8b5", "#d7ecd9"], alpha=0.9)
        ax.contour(TA, RH, surv, levels=[0.5], colors="firebrick", linewidths=2)
        # liveability Mmax contours (lighter context)
        with np.errstate(invalid="ignore"):
            cs = ax.contour(TA, RH, mmaxg, levels=[2.5, 3.3, 5.0, 7.0],
                            colors="grey", linewidths=0.8)
            ax.clabel(cs, fmt="%.1f MET", fontsize=7)
        # classic 35 degC Tw survivability isoline
        c35 = ax.contour(TA, RH, tw_grid, levels=[35.0], colors="black",
                         linewidths=2.5, linestyles="--")
        ax.clabel(c35, fmt="Tw=35", fontsize=8)
        # city overlay: annual peak-wet-bulb hours
        ax.scatter(ref_ta, ref_rh, s=20, c="royalblue", edgecolor="white",
                   linewidth=0.3, label=f"peak hour {ref_window[0]}-{ref_window[1]}", zorder=5)
        ax.scatter(lat_ta, lat_rh, s=26, c="darkorange", edgecolor="black",
                   linewidth=0.3, marker="^",
                   label=f"peak hour {latest_window[0]}-{latest_window[1]}", zorder=6)
        ax.set_xlim(ta_range.min(), ta_range.max())
        ax.set_ylim(0, 100)
        ax.set_title(f"{LIVEABILITY_PROFILE_LABEL[pkey]}")
        ax.set_xlabel("Air temperature [degC]")
        ax.set_ylabel("Relative humidity [%]")
        ax.legend(fontsize=7, loc="upper right")
    fig.suptitle(f"HEAT-Lim survivability matrix + city peak-stress hours - {city_name}"
                 f"  [sun={LIVEABILITY_SUN}, {LIVEABILITY_EXP_TIME}h]", fontsize=12)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)


def plot_liveability_matrix(annual: pd.DataFrame, ref_window: Tuple[int, int],
                            latest_window: Tuple[int, int], city_name: str,
                            outpath: str) -> None:
    """HEAT-Lim LIVEABILITY matrix (Ta x RH) for both profiles: Mmax (max
    sustainable activity, METs) as a filled colour scale - matching the style
    of Vanos et al. (2023) Fig. 2/3 - with the survivability boundary and the
    classic 35 degC Tw isoline as line overlays for context, and the city's
    annual peak-wet-bulb hours overlaid (reference vs latest window)."""
    if not (HEATLIM_AVAILABLE and "peakTa" in annual.columns):
        return
    ta_range, rh_range, TA, RH, mrt, Av, tw_grid = _matrix_grid_setup()

    profs = list(LIVEABILITY_PROFILES.items())
    fig, axes = plt.subplots(1, len(profs), figsize=(7.6 * len(profs), 6), squeeze=False)

    ref_ta, ref_rh = _city_peak_points(annual, ref_window)
    lat_ta, lat_rh = _city_peak_points(annual, latest_window)

    levels = np.arange(1.0, 8.5, 0.5)
    for ax, (pkey, prof) in zip(axes[0], profs):
        mmax, surv = compute_mmax_met(TA.ravel(), RH.ravel(), Av, mrt.ravel(), prof)
        surv = surv.reshape(TA.shape).astype(float)
        mmaxg = mmax.reshape(TA.shape)

        with np.errstate(invalid="ignore"):
            cs = ax.contourf(TA, RH, mmaxg, cmap="Spectral_r", levels=levels,
                            extend="both", corner_mask=False)
        cbar = fig.colorbar(cs, ax=ax, pad=0.02)
        cbar.set_label("Max. sustainable activity\n(compensable heat stress) [METs]", fontsize=8)
        cbar.ax.tick_params(labelsize=7)

        # [2026-09] THIRD ZONE, previously left blank/white: livability_Mmax()
        # (HEATLim.py) sets Mmax=NaN wherever heat stress is non-compensable
        # (Ereq >= Emax_constrain) -- even resting metabolism can't be shed,
        # so "how much activity is sustainable" has no defined answer -- and
        # this "compensability" cutoff is STRICTER than (reached before) the
        # broader Survivability() cutoff `surv` used for the red/hatched zone
        # below. The gap between the coloured Mmax fill and the red boundary
        # is exactly that stricter-but-still-survivable band: real physiology
        # ("can survive, but zero activity -- even standing still -- is
        # sustainable without storing heat"), not missing data. Shown here as
        # a distinct grey hatch so it reads as a third zone, not a gap.
        non_compensable_survivable = np.logical_and(surv, np.isnan(mmaxg)).astype(float)
        cs_grey = ax.contourf(TA, RH, non_compensable_survivable, levels=[0.5, 1.5],
                    colors="none", hatches=["..."])
        _set_hatch_edgecolor(cs_grey, "dimgray")

        # non-survivable zone: hatched overlay + boundary line (context, not the focus here)
        # [2026-09] alpha=0 previously made this hatch invisible (it zeroed
        # out the hatch stroke along with the intentionally-transparent
        # fill) -- edgecolor is now set explicitly on the returned collection
        # instead, so the hatch renders while the fill stays transparent.
        cs_nonsurv = ax.contourf(TA, RH, surv, levels=[-0.5, 0.5], colors="none",
                    hatches=["///"])
        _set_hatch_edgecolor(cs_nonsurv, "firebrick")
        ax.contour(TA, RH, surv, levels=[0.5], colors="firebrick", linewidths=2,
                  linestyles="-")
        c35 = ax.contour(TA, RH, tw_grid, levels=[35.0], colors="black",
                         linewidths=2.2, linestyles="--")
        ax.clabel(c35, fmt="Tw=35", fontsize=8)

        ax.scatter(ref_ta, ref_rh, s=20, c="white", edgecolor="black",
                   linewidth=0.6, label=f"peak hour {ref_window[0]}-{ref_window[1]}", zorder=5)
        ax.scatter(lat_ta, lat_rh, s=28, c="black", edgecolor="white",
                   linewidth=0.6, marker="^",
                   label=f"peak hour {latest_window[0]}-{latest_window[1]}", zorder=6)
        # [2026-09] Proxy legend entry for the grey-dotted zone above, since a
        # contourf hatch-only patch doesn't auto-register a legend handle.
        from matplotlib.patches import Patch
        grey_proxy = Patch(facecolor="none", edgecolor="dimgray", hatch="...",
                            label="non-compensable, survivable\n(no activity sustainable)")
        ax.set_xlim(ta_range.min(), ta_range.max())
        ax.set_ylim(0, 100)
        ax.set_title(f"{LIVEABILITY_PROFILE_LABEL[pkey]}"
                    f"  (red = non-survivable; grey-dotted = non-compensable "
                    f"but survivable)")
        ax.set_xlabel("Air temperature [degC]")
        ax.set_ylabel("Relative humidity [%]")
        handles, labels = ax.get_legend_handles_labels()
        handles.append(grey_proxy); labels.append(grey_proxy.get_label())
        ax.legend(handles, labels, fontsize=7, loc="upper right", facecolor="white", framealpha=0.85)
    fig.suptitle(f"HEAT-Lim liveability matrix (Mmax) + city peak-stress hours - {city_name}"
                f"  [sun={LIVEABILITY_SUN}, {LIVEABILITY_EXP_TIME}h]", fontsize=12)
    fig.tight_layout()
    fig.savefig(outpath, dpi=130)
    plt.close(fig)

# =============================================================================
# Excel export
# =============================================================================

def save_results(annual: pd.DataFrame, stats_by_var: Dict[str, pd.DataFrame],
                 plot_paths: List[str], meta: Dict,
                 admissions_df: Optional[pd.DataFrame] = None,
                 liveability_df: Optional[pd.DataFrame] = None,
                 event_df: Optional[pd.DataFrame] = None,
                 ehs_df: Optional[pd.DataFrame] = None,
                 accel_df: Optional[pd.DataFrame] = None) -> str:
    """Write annual maxima, per-variable window stats, metadata and plots to Excel."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    safe_city = "".join(ch for ch in meta["city"] if ch.isalnum() or ch in (" ", "_", "-")).strip()
    filename = f"Klimatos_ClimateShift_{safe_city}_{timestamp}.xlsx"

    with pd.ExcelWriter(filename, engine="xlsxwriter") as writer:
        annual.to_excel(writer, sheet_name="Annual_Maxima")
        for var_key, sdf in stats_by_var.items():
            sheet = f"Win_{var_key.replace('_max','')}"[:31]
            sdf.to_excel(writer, sheet_name=sheet, index=False)
        if admissions_df is not None and not admissions_df.empty:
            admissions_df.to_excel(writer, sheet_name="Heat_Admissions", index=False)
        if liveability_df is not None and not liveability_df.empty:
            liveability_df.to_excel(writer, sheet_name="Heat_Liveability", index=False)
        if event_df is not None and not event_df.empty:
            event_df.to_excel(writer, sheet_name="Event_Window", index=False)
        if ehs_df is not None and not ehs_df.empty:
            ehs_df.to_excel(writer, sheet_name="EHS_Evolution", index=False)
        if accel_df is not None and not accel_df.empty:
            accel_df.to_excel(writer, sheet_name="Trend_Acceleration", index=False)
        pd.DataFrame([meta]).to_excel(writer, sheet_name="Metadata", index=False)

        workbook = writer.book
        ws_plots = workbook.add_worksheet("Plots")
        writer.sheets["Plots"] = ws_plots
        row = 0
        for p in plot_paths:
            if os.path.exists(p):
                ws_plots.write(row, 0, os.path.basename(p))
                ws_plots.insert_image(row + 1, 0, p, {"x_scale": 0.8, "y_scale": 0.8})
                row += 34
    return os.path.abspath(filename)

# =============================================================================
# Console summary
# =============================================================================

def print_summary(stats_by_var: Dict[str, pd.DataFrame],
                  admissions_df: Optional[pd.DataFrame] = None,
                  liveability_df: Optional[pd.DataFrame] = None,
                  event_df: Optional[pd.DataFrame] = None,
                  ehs_df: Optional[pd.DataFrame] = None,
                  ehe_resolvable: bool = False,
                  ehs_res: Optional[Dict] = None) -> None:
    for var_key, sdf in stats_by_var.items():
        print("\n" + "=" * 70)
        print(f"{VAR_LABEL[var_key]}  ({var_key})")
        print("=" * 70)
        valid = sdf.dropna(subset=["mean"])
        if valid.empty:
            print("  (insufficient data)")
            continue
        ref, last = valid.iloc[0], valid.iloc[-1]   # ref = baseline (first row)
        print(f"  Reference {ref['window']}: mean = {ref['mean']:.2f} degC, sd = {ref['std']:.2f}")
        print(f"  Latest    {last['window']}: mean = {last['mean']:.2f} degC "
              f"(anomaly vs reference = {last['mean'] - ref['mean']:+.2f} degC)")
        for thr in THRESHOLDS[var_key]:
            col = f"P_gev_{thr:g}"
            if col in valid and np.isfinite(ref.get(col, np.nan)) and np.isfinite(last.get(col, np.nan)):
                rp0 = _return_period(ref[col]); rp1 = _return_period(last[col])
                print(f"    >= {thr:g} degC  (GEV): return period "
                      f"{rp0:7.1f} yr (ref) -> {rp1:7.1f} yr (latest)")

    if admissions_df is not None and not admissions_df.empty:
        print("\n" + "=" * 70)
        print("Heat-attributable hospital admissions  (van Loenhout et al. 2018 ERF)")
        print("=" * 70)
        last = admissions_df.iloc[-1]
        print(f"  Latest window {last['window']} vs reference "
              f"{admissions_df.iloc[0]['window']}:")
        print(f"    ERF-based index ratio      : {last['ratio_ERF_vs_ref']:.2f}x")
        print(f"    Heat-degree-day ratio (b-free): {last['ratio_HDD_vs_ref']:.2f}x")
        print("  (climate-only contrast: ERF and population held constant; NOT the")
        print("   observed admissions trend, which also depends on ageing/adaptation)")

    if liveability_df is not None and not liveability_df.empty:
        print("\n" + "=" * 70)
        print("Physiological liveability  (HEAT-Lim; Vanos et al. 2023)")
        print("=" * 70)
        ref = liveability_df.iloc[0]; last = liveability_df.iloc[-1]
        print(f"  Worst-hour sustainable activity (min Mmax), {ref['window']} -> {last['window']}:")
        for pkey in LIVEABILITY_PROFILES:
            col = f"minMmax_{pkey}"
            if col in liveability_df:
                print(f"    {LIVEABILITY_PROFILE_LABEL[pkey]:<20}: "
                      f"{ref[col]:5.2f} -> {last[col]:5.2f} MET "
                      f"(delta {last[col]-ref[col]:+.2f})")
        for pkey in LIVEABILITY_PROFILES:
            rc = f"ratioBelow_{pkey}_vs_ref"
            if rc in liveability_df and np.isfinite(last.get(rc, np.nan)):
                print(f"    hours below {LIVEABILITY_ACTIVITY_MET:g} MET, "
                      f"{LIVEABILITY_PROFILE_LABEL[pkey]:<20}: {last[rc]:.2f}x vs reference")
        for pkey in LIVEABILITY_PROFILES:
            nc = f"hrsNonSurv_{pkey}"
            if nc in liveability_df:
                ns_ref = ref.get(nc, 0.0); ns_last = last.get(nc, 0.0)
                print(f"    non-survivable hours/yr, {LIVEABILITY_PROFILE_LABEL[pkey]:<20}: "
                      f"{ns_ref:.1f} (ref) -> {ns_last:.1f} (latest)")
        if all(last.get(f"hrsNonSurv_{p}", 0) == 0 for p in LIVEABILITY_PROFILES):
            print("    (survivability never breached -> liveability degrades well before the")
            print("     survival limit is approached: the survival bar is not the binding one)")

    # --- Event window -------------------------------------------------------
    if event_df is not None and not event_df.empty:
        print("\n" + "=" * 70)
        print(f"EVENT WINDOW: {EVENT_NAME}")
        print("=" * 70)
        print(f"  Date/time : {EVENT_DAY:02d}-{EVENT_MONTH:02d} +/-{EVENT_DAY_WINDOW}d, "
              f"{EVENT_START_HOUR:02d}:{EVENT_START_MINUTE:02d} "
              f"+{EVENT_DURATION_MIN}min (start -> finish)")
        print(f"  Trend     : anchored on {EVENT_TREND_PERIOD[0]}-{EVENT_TREND_PERIOD[1]}")
        print(f"  Baseline  : {REFERENCE_PERIOD[0]}-{REFERENCE_PERIOD[1]} (comparison only)")
        for _, r in event_df.iterrows():
            print(f"\n  {r['label']}")
            if np.isfinite(r.get("baseline_mean", np.nan)):
                print(f"    baseline  {r['baseline_period']}: {r['baseline_mean']:6.2f} degC "
                      f"(n={int(r['n_baseline'])})")
            print(f"    reference {r['trend_period']}: {r['trend_mean']:6.2f} degC "
                  f"(n={int(r['n_trend'])})", end="")
            if np.isfinite(r.get("trend_mean_vs_baseline", np.nan)):
                print(f"   [{r['trend_mean_vs_baseline']:+.2f} vs baseline]")
            else:
                print()
            if np.isfinite(r.get("slope_degC_per_yr", np.nan)):
                print(f"    trend     {r['slope_degC_per_yr']:+.4f} degC/yr "
                      f"(95% CI {r['slope_lo']:+.4f}..{r['slope_hi']:+.4f}) - {r['mk_trend']}")
                for ty in sorted(EVENT_TARGET_YEARS):
                    col = f"projected_{ty}"
                    if col in r and np.isfinite(r[col]):
                        vs = r.get(f"{col}_vs_baseline", np.nan)
                        extra = f"   [{vs:+.2f} vs baseline]" if np.isfinite(vs) else ""
                        print(f"    projected {ty}: {r[col]:6.2f} degC{extra}")
        print("\n  NB: projections are a naive linear extrapolation of the observed trend,")
        print("      not a physical climate model and not a forecast for any single year.")

    # --- EHS evolution ------------------------------------------------------
    if ehs_df is not None and not ehs_df.empty:
        print("\n" + "=" * 70)
        print(f"EHS EVOLUTION: {EVENT_NAME}")
        print("=" * 70)
        ref = ehs_df["reference_ehs_per_1000"].iloc[0]
        print(f"  Reference rate: {ref:.2f} EHS per 1000 participants")
        print("  CONDITIONAL on unchanged start time, participant population and policy.")
        print("  NB: EHS/1000 is a pure function of ambient race-window temperature "
              "(Falmouth's own")
        print(f"  regression, DeMartini et al. 2014) -- it does NOT move with pace/MET "
              f"(currently {EHS_MET_VALUE:.1f}),")
        print("  clo, or any other physiological input. Every EHS number and ratio below "
              "is a temperature")
        print("  effect only. EHE (elsewhere in this output, if resolvable) is the "
              "pace-sensitive one.")
        has_adapt = "ehs_per_1000_early_start" in ehs_df.columns
        print()
        header = f"  {'year':>6}  {'EHS/1000':>18}  {'x reference':>18}"
        if has_adapt:
            header += f"  {'early start':>22}"
        print(header)
        print("  " + "-" * (len(header) - 2))
        for _, r in ehs_df.iterrows():
            abs_s = f"{r['ehs_per_1000']:.2f}"
            if np.isfinite(r.get("ehs_per_1000_lo", np.nan)):
                abs_s += f" [{min(r['ehs_per_1000_lo'], r['ehs_per_1000_hi']):.2f}-" \
                         f"{max(r['ehs_per_1000_lo'], r['ehs_per_1000_hi']):.2f}]"
            rat_s = f"{r['ratio_vs_reference']:.2f}x"
            if np.isfinite(r.get("ratio_lo", np.nan)):
                rat_s += f" [{min(r['ratio_lo'], r['ratio_hi']):.2f}-" \
                         f"{max(r['ratio_lo'], r['ratio_hi']):.2f}]"
            line = f"  {int(r['target_year']):>6}  {abs_s:>18}  {rat_s:>18}"
            if has_adapt:
                red = r.get("reduction_from_early_start_pct", np.nan)
                a = f"{r['ehs_per_1000_early_start']:.2f}"
                if np.isfinite(red):
                    a += f" (-{red:.0f}%)"
                line += f"  {a:>22}"
            print(line)

        # --- Collapse-risk endpoint (DtD-2024-calibrated by default) -------
        ref_collapse = ehs_df["reference_collapse_per_1000"].iloc[0]
        endpoint_label = COLLAPSE_ENDPOINT
        print(f"\n  Collapse-risk endpoint '{endpoint_label}' "
              f"(calibrated, floor never zero; see CONFIG note):")
        print(f"  Reference rate: {ref_collapse:.2f} per 1000 participants")
        print("  Unlike EHE, this has a calibrated baseline: even a scenario where nobody")
        print("  in the ensemble crosses a physiological trigger still reports the")
        print("  endpoint's calibrated background rate, not zero. Status: PROVISIONAL")
        print("  (fit at reduced N=200; see hestia_model.py's COLLAPSE_ENDPOINTS table).")
        print()
        chdr = f"  {'year':>6}  {'per 1000':>18}  {'x reference':>18}"
        if has_adapt:
            chdr += f"  {'early start':>22}"
        print(chdr)
        print("  " + "-" * (len(chdr) - 2))
        for _, r in ehs_df.iterrows():
            c_abs = f"{r['collapse_per_1000']:.2f}"
            if np.isfinite(r.get("collapse_per_1000_lo", np.nan)):
                c_abs += f" [{min(r['collapse_per_1000_lo'], r['collapse_per_1000_hi']):.2f}-" \
                         f"{max(r['collapse_per_1000_lo'], r['collapse_per_1000_hi']):.2f}]"
            c_rat = (f"{r['collapse_ratio_vs_reference']:.2f}x"
                    if np.isfinite(r.get("collapse_ratio_vs_reference", np.nan)) else "n/a")
            cline = f"  {int(r['target_year']):>6}  {c_abs:>18}  {c_rat:>18}"
            if has_adapt:
                cred = r.get("collapse_reduction_from_early_start_pct", np.nan)
                ca = f"{r['collapse_per_1000_early_start']:.2f}"
                if np.isfinite(cred):
                    ca += f" (-{cred:.0f}%)"
                cline += f"  {ca:>22}"
            print(cline)
        if has_adapt:
            print(f"\n  'early start' = same event, same year, started at "
                  f"{EHS_ADAPT_START_HOUR:02d}:{EHS_ADAPT_START_MINUTE:02d} "
                  f"instead of {EVENT_START_HOUR:02d}:{EVENT_START_MINUTE:02d}.")
            print("  That column is the actionable one: it is how much of the projected")
            print("  increase the organiser can remove without changing anything else.")

        # --- Margin to EHE's threshold, from the same data the scatter plot
        # uses -- shown regardless of whether EHE itself resolved, since it
        # answers "how far" rather than "did it fire". See _ehe_margin_stats.
        if ehs_res is not None:
            scen = ehs_res.get("scenarios", {})
            ref_pairs = scen.get("ref_current", {}).get("scatter_pairs", [])
            proj_key = next((k for k in scen if k.startswith("proj_") and k.endswith("_central")
                            and scen[k].get("scatter_pairs")), None)
            if ref_pairs or proj_key:
                print("\n  Distance to EHE's own threshold (T_rect>39.5 degC AND "
                      "CO_reserve<0 L/min),")
                print("  from the same sampled data as the scatter plot -- 'closest observed")
                print("  point' is governed by whichever margin is still furthest from zero,")
                print("  since EHE needs BOTH to close at once:")
                for lbl, pairs in ((f"Reference {ehs_res['trend_period'][0]}-"
                                   f"{ehs_res['trend_period'][1]}", ref_pairs),
                                  (f"Projected {proj_key.split('_')[1] if proj_key else '?'}"
                                   " (central slope)",
                                   scen.get(proj_key, {}).get("scatter_pairs", []) if proj_key else [])):
                    for line in _format_ehe_margin_line(lbl, _ehe_margin_stats(pairs)):
                        print(line)

                print("\n  Distance to the stricter CLINICAL criterion (T_rect>=40.5 degC AND")
                print("  CO_reserve<=0 L/min -- hestia_bridge.py's own 'pct_true_ehs_criterion',")
                print("  confusingly named EHS there though it has nothing to do with the")
                print("  Falmouth-calibrated EHS reported above; called 'clinical' here instead):")
                for lbl, pairs in ((f"Reference {ehs_res['trend_period'][0]}-"
                                   f"{ehs_res['trend_period'][1]}", ref_pairs),
                                  (f"Projected {proj_key.split('_')[1] if proj_key else '?'}"
                                   " (central slope)",
                                   scen.get(proj_key, {}).get("scatter_pairs", []) if proj_key else [])):
                    for line in _format_ehe_margin_line(lbl, _ehe_margin_stats(pairs, 40.5, 0.0)):
                        print(line)

        clinical_ok = _clinical_is_resolvable(ehs_res) if ehs_res is not None else False
        if not clinical_ok:
            print(f"\n  Clinical criterion: not reported at MET={EHS_MET_VALUE:.1f}. Stricter than")
            print("  EHE (40.5 degC vs 39.5, <=0 vs <0), so at least as likely to sit at zero --")
            print("  see the margin figures above for how far away it actually was.")

        if not ehe_resolvable:
            print(f"\n  EHE: not reported at MET={EHS_MET_VALUE:.1f}. The criterion fired for zero")
            print("  participants in every scenario, reference and projected alike, so any rate,")
            print("  ratio or trend for it here would describe the behaviour of zero rather than")
            print("  of the event.")
            if ENABLE_EHS_STRESS_TEST:
                print(f"  This WAS the stress test (MET={STRESS_TEST_MET:.1f}, "
                      f"n={STRESS_TEST_ENSEMBLE_N}, hottest slope, year")
                print(f"  {STRESS_TEST_TARGET_YEAR}) -- the most unfavourable still-plausible "
                      f"combination tried in this")
                print("  session did not reach EHE either. Further pace increases move toward "
                      "genuinely elite")
                print("  paces no longer representative of this event's field.")
            else:
                print("  Unlike EHS, EHE IS pace-sensitive -- rerun with a faster pace at the")
                print("  'Median participant pace' prompt (e.g. a competitive wave), or set")
                print("  ENABLE_EHS_STRESS_TEST = True for the most unfavourable still-plausible")
                print("  combination this session has identified, to check whether it becomes")
                print("  resolvable at all.")
        print("\n  NB: the projected scenario is one that adaptation is expected to prevent.")
        print("      Read it as an argument for acting, not as a forecast.")

# =============================================================================
# Main
# =============================================================================

def main():
    # Declared up front: the banner below reads ENABLE_EVENT_WINDOW, and Python
    # requires the global declaration to precede any use within the function.
    global ENABLE_EVENT_WINDOW, EVENT_NAME, EVENT_MONTH, EVENT_DAY
    global EVENT_START_HOUR, EVENT_START_MINUTE, EVENT_DURATION_MIN, EVENT_DIST_KM
    global EHS_MET_VALUE

    print("\n" + "=" * 70)
    print("  Klimatos.ClimateShift v1.5 - Climate-Shift Engine")
    print("=" * 70)
    print("  Annual maxima of T_air / WBT / WBGT / UTCI in sliding 30-year windows")
    print(f"  Reference baseline = {REFERENCE_PERIOD[0]}-{REFERENCE_PERIOD[1]}")
    print(f"  window = {WINDOW_LENGTH} yr   step = {WINDOW_STEP} yr")
    if ENABLE_WARMING_STRIPES:
        print(f"  + warming stripes ({STRIPES_VARIABLE})")
    if ENABLE_ACCELERATION_CHECK:
        print(f"  + trend acceleration check ({', '.join(ACCEL_VARIABLES)}, "
              f"{'scan' if ACCEL_BREAKPOINT_YEAR is None else f'fixed at {ACCEL_BREAKPOINT_YEAR}'})")
    if ENABLE_EVENT_WINDOW:
        print(f"  + event window: trend anchored on "
              f"{EVENT_TREND_PERIOD[0]}-{EVENT_TREND_PERIOD[1]}, "
              f"targets {', '.join(str(y) for y in EVENT_TARGET_YEARS)}")
    if ENABLE_EHS_EVOLUTION:
        endpoint_note = f"'{COLLAPSE_ENDPOINT}'" if HESTIA_AVAILABLE else "unavailable (no HESTIA)"
        print(f"  + EHS evolution: EHS (Falmouth) + EHE + collapse-risk endpoint "
              f"{endpoint_note}")
    print("=" * 70 + "\n")

    last_complete = (END_YEAR if END_YEAR is not None else datetime.now().year - 1)

    # --- City selection -----------------------------------------------------
    city_name = input("Enter city name: ").strip()
    if not city_name:
        print("No city entered. Exiting.")
        return
    try:
        candidates = geocode_city_candidates(city_name)
        city = candidates[0] if len(candidates) == 1 else select_city(candidates)
    except Exception as e:
        print(f"Error during geocoding: {e}")
        return

    lat, lon, tz = city["latitude"], city["longitude"], city["timezone"]
    print(f"\nSelected: {city['name']}, {city.get('country', 'Unknown')}  "
          f"({lat:.3f}, {lon:.3f})  tz={tz}")

    # --- UHI toggle (console) ----------------------------------------------
    pop = city.get("population", 0)
    default_yn = "y" if APPLY_UHI else "n"
    prompt = (f"Apply urban heat island (UHI)? population={pop or 'unknown'}  "
              f"[y/n, default {default_yn}]: ")
    ans = input(prompt).strip().lower()
    if ans == "":
        apply_uhi = APPLY_UHI
    else:
        apply_uhi = ans.startswith("y")
    if apply_uhi and not (pop and pop > 0):
        print("  (no population available for this location -> UHI cannot be applied; "
              "using clean climate signal)")
        apply_uhi = False
    print(f"  UHI: {'ON (urban lived-environment values)' if apply_uhi else 'OFF (clean climate signal)'}")

    # --- Event window toggle + settings (console) ---------------------------
    if ENABLE_EVENT_WINDOW:
        ans = input("Analyse a fixed annual event as well? "
                    "[y/n, default y]: ").strip().lower()
        ENABLE_EVENT_WINDOW = (ans == "" or ans.startswith("y"))
    if ENABLE_EVENT_WINDOW:
        name = input(f"  Event name [default '{EVENT_NAME}']: ").strip()
        if name:
            EVENT_NAME = name
        d = input(f"  Date as DD-MM [default "
                  f"{EVENT_DAY:02d}-{EVENT_MONTH:02d}]: ").strip()
        if d:
            try:
                dd, mm = (int(x) for x in d.replace("/", "-").split("-")[:2])
                pd.Timestamp(year=2000, month=mm, day=dd)   # validate
                EVENT_DAY, EVENT_MONTH = dd, mm
            except Exception:
                print(f"    (could not parse '{d}' -> keeping "
                      f"{EVENT_DAY:02d}-{EVENT_MONTH:02d})")
        t = input(f"  Start time as HH:MM [default "
                  f"{EVENT_START_HOUR:02d}:{EVENT_START_MINUTE:02d}]: ").strip()
        if t:
            try:
                hh, mi = (int(x) for x in t.replace(".", ":").split(":")[:2])
                if not (0 <= hh <= 23 and 0 <= mi <= 59):
                    raise ValueError
                EVENT_START_HOUR, EVENT_START_MINUTE = hh, mi
            except Exception:
                print(f"    (could not parse '{t}' -> keeping "
                      f"{EVENT_START_HOUR:02d}:{EVENT_START_MINUTE:02d})")
        # [2026-09] Distance is now an explicit console input instead of only
        # a hardcoded default -- decouples this script from any one event
        # (Dam tot Damloop's 16.1 km or otherwise). Asked before duration so
        # that both the duration default just below and any pace entered
        # later use whatever distance is set here.
        dist_ans = input(f"  Event distance in km [default {EVENT_DIST_KM:g}]: ").strip()
        if dist_ans:
            try:
                v = float(dist_ans.replace(",", "."))
                if v <= 0:
                    raise ValueError
                EVENT_DIST_KM = v
            except Exception:
                print(f"    (could not parse '{dist_ans}' -> keeping {EVENT_DIST_KM:g} km)")
        dur = input(f"  Duration in minutes [default {EVENT_DURATION_MIN}]: ").strip()
        if dur:
            try:
                v = int(dur)
                if v <= 0:
                    raise ValueError
                EVENT_DURATION_MIN = v
            except Exception:
                print(f"    (could not parse '{dur}' -> keeping {EVENT_DURATION_MIN})")
        # MET only affects the EHS-evolution module -- see the CONFIG note above
        # EHS_MET_VALUE and this session's own finding: falmouth_ehs_per_1000()
        # is a pure function of ambient temperature (Falmouth's own regression,
        # not HESTIA's physiological simulation), so it does not move with pace
        # at all. MET matters for EHE instead (the physiological criterion),
        # which is exactly why this is worth exposing: a faster pace is what
        # could make EHE non-degenerate for a competitive subgroup where the
        # median-pace figure floors at zero.
        if ENABLE_EHS_EVOLUTION:
            met_ans = input(
                f"  Median participant pace in min/km [default corresponds to "
                f"MET={EHS_MET_VALUE:.1f}, ~5:30/km for running]: ").strip()
            if met_ans:
                try:
                    if ":" in met_ans:
                        # mm:ss notation (e.g. "4:30") -- the natural way most
                        # runners state a pace, so it must be accepted, not
                        # just decimal minutes.
                        mm, ss = met_ans.split(":", 1)
                        pace_min_per_km = float(mm) + float(ss) / 60.0
                    else:
                        pace_min_per_km = float(met_ans.replace(",", "."))
                    if pace_min_per_km <= 0:
                        raise ValueError
                    # [2026-09] Now uses the ACSM running/walking equations
                    # directly (_acsm_met_from_pace, defined near the imports)
                    # instead of a linear scale self-calibrated to agree with
                    # this file's own MET anchor -- see that function's
                    # docstring note for why the old approach was replaced.
                    EHS_MET_VALUE = _acsm_met_from_pace(pace_min_per_km)
                    print(f"    -> MET = {EHS_MET_VALUE:.1f}")
                    # [2026-09] Duration is now derived from the SAME pace
                    # entered here, instead of being left at whatever
                    # EVENT_DURATION_MIN happened to default to or was set to
                    # via the separate duration prompt above -- previously
                    # these two could silently disagree (e.g. a fast pace
                    # entered here with the 100-min default left untouched).
                    # If the person explicitly set a duration above, that
                    # explicit choice is intentional and stays; only the case
                    # where duration is about to be inconsistent with the pace
                    # just entered is corrected here, transparently.
                    implied_duration = round(pace_min_per_km * EVENT_DIST_KM)
                    if implied_duration != EVENT_DURATION_MIN:
                        print(f"    -> duration implied by this pace over "
                              f"{EVENT_DIST_KM:g} km: {implied_duration} min "
                              f"(was {EVENT_DURATION_MIN} min) -- updating "
                              f"EVENT_DURATION_MIN to match.")
                        EVENT_DURATION_MIN = implied_duration
                except Exception:
                    print(f"    (could not parse '{met_ans}' -> keeping MET={EHS_MET_VALUE:.1f})")
            if ENABLE_EHS_STRESS_TEST and EHS_MET_VALUE != STRESS_TEST_MET:
                print(f"    (EHS/EHE stress test is ON -> overriding to MET={STRESS_TEST_MET:.1f}, "
                      f"ignoring the pace just entered/kept above)")
                EHS_MET_VALUE = STRESS_TEST_MET
        print(f"  Event: {EVENT_NAME}, {EVENT_DAY:02d}-{EVENT_MONTH:02d} "
              f"+/-{EVENT_DAY_WINDOW}d, {EVENT_START_HOUR:02d}:{EVENT_START_MINUTE:02d} "
              f"+{EVENT_DURATION_MIN}min"
              + (f", MET={EHS_MET_VALUE:.1f}" if ENABLE_EHS_EVOLUTION else "") +
              f"   (trend anchored on {EVENT_TREND_PERIOD[0]}-{EVENT_TREND_PERIOD[1]})")

    # The event trend period must be inside the fetched range, otherwise the
    # event module silently has nothing to fit on.
    earliest = min(START_YEAR, REFERENCE_PERIOD[0])
    if ENABLE_EVENT_WINDOW:
        earliest = min(earliest, EVENT_TREND_PERIOD[0])
    print(f"Reference baseline: {REFERENCE_PERIOD[0]}-{REFERENCE_PERIOD[1]}")
    print(f"Data fetch period:  {earliest}-{last_complete}\n")

    # --- Annual maxima ------------------------------------------------------
    print("Fetching + processing hourly archive data per year")
    print("(this can take several minutes for a multi-decade run)\n")
    event_slices: Dict[int, pd.DataFrame] = {}
    ehs_summary_df = None
    ehs_ehe_resolvable = False
    ehs_res = None
    annual = build_annual_maxima(lat, lon, tz, city, earliest, last_complete,
                                 apply_uhi=apply_uhi,
                                 event_slices=(event_slices
                                               if (ENABLE_EVENT_WINDOW and
                                                   ENABLE_EHS_EVOLUTION) else None))

    available_first = int(annual.index.min())
    available_last = int(annual.index.max())
    windows = generate_windows(max(START_YEAR, available_first), available_last)
    # Clamp the reference window to the data that was actually retrieved.
    ref_window = (max(REFERENCE_PERIOD[0], available_first),
                  min(REFERENCE_PERIOD[1], available_last))
    print(f"\nReference window: {ref_window[0]}-{ref_window[1]}")
    print(f"Sliding windows ({len(windows)}): " + ", ".join(f"{a}-{b}" for a, b in windows))

    # --- Trend acceleration / breakpoint check ------------------------------
    plot_paths: List[str] = []
    accel_summary_df = None
    if ENABLE_ACCELERATION_CHECK:
        print("\n" + "=" * 70)
        print("TREND ACCELERATION CHECK")
        print("=" * 70)
        print("Generic statistical test; the AEROSOL DIMMING/BRIGHTENING mechanism")
        print("that motivates checking around 1980 is Europe/N.America-specific --")
        print("see check_trend_acceleration()'s docstring before interpreting the")
        print("cause of any breakpoint found elsewhere.")
        full_check_period = (max(START_YEAR, available_first), available_last)
        accel_rows = []
        for var_key in ACCEL_VARIABLES:
            accel_res = check_trend_acceleration(annual, var_key, full_check_period,
                                                 breakpoint_year=ACCEL_BREAKPOINT_YEAR)
            print_acceleration_check(accel_res, var_key)
            if accel_res is not None:
                p_accel = f"plot_trend_acceleration_{var_key}.png"
                _safe_plot(plot_trend_acceleration, accel_res, city["name"], p_accel)
                if os.path.exists(p_accel):
                    plot_paths.append(p_accel)
                for r in accel_res["scan"]:
                    accel_rows.append({
                        "variable": var_key, "mode": accel_res["mode"],
                        "breakpoint": r["breakpoint"], "n_before": r["n1"], "n_after": r["n2"],
                        "slope_before": r["slope1"], "slope_after": r["slope2"],
                        "slope_diff": r["diff"], "diff_ci_lo": r["diff_ci"][0],
                        "diff_ci_hi": r["diff_ci"][1], "significant": r["significant"],
                        "is_best": (r["breakpoint"] == accel_res["best"]["breakpoint"]),
                    })
        if accel_rows:
            accel_summary_df = pd.DataFrame(accel_rows)

    # --- Per-variable analysis + plots --------------------------------------
    # The reference period is prepended as the first window and flagged so that
    # every sliding window can be expressed as an anomaly relative to it.
    stats_by_var: Dict[str, pd.DataFrame] = {}
    for var_key in VARIABLES:
        series = annual[var_key]
        sdf = analyze_variable_windows(series, [ref_window] + windows, THRESHOLDS[var_key])
        sdf.insert(0, "is_reference", False)
        sdf.loc[sdf.index[0], "is_reference"] = True
        ref_mean = sdf.loc[sdf.index[0], "mean"]
        sdf.insert(sdf.columns.get_loc("std") + 1, "mean_vs_ref", sdf["mean"] - ref_mean)
        stats_by_var[var_key] = sdf

        p1 = f"plot_{var_key}_normals.png"
        p2 = f"plot_{var_key}_normal_vs_gev.png"
        _safe_plot(plot_window_normals, sdf, THRESHOLDS[var_key], var_key, city["name"], p1)
        _safe_plot(plot_normal_vs_gev, series, sdf, THRESHOLDS[var_key], var_key, city["name"], p2)
        # additional plots
        p3 = f"plot_{var_key}_timeseries_trend.png"
        p4 = f"plot_{var_key}_return_levels.png"
        p5 = f"plot_{var_key}_trajectory.png"
        p6 = f"plot_{var_key}_qq_normal_gev.png"
        _safe_plot(plot_timeseries_trend, annual, var_key, THRESHOLDS[var_key], ref_window, city["name"], p3)
        _safe_plot(plot_return_levels, series, sdf, var_key, city["name"], p4)
        _safe_plot(plot_trajectory, sdf, var_key, THRESHOLDS[var_key], city["name"], p5)
        _safe_plot(plot_qq_normal_gev, series, sdf, var_key, city["name"], p6)
        for p in (p1, p2, p3, p4, p5, p6):
            if os.path.exists(p):
                plot_paths.append(p)

    # cross-variable standardized-anomaly plot (one figure for all variables)
    p_anom = "plot_standardized_anomaly.png"
    plot_standardized_anomaly(stats_by_var, city["name"], p_anom)
    if os.path.exists(p_anom):
        plot_paths.append(p_anom)

    # --- Warming stripes ("streepjescode") ----------------------------------
    if ENABLE_WARMING_STRIPES and STRIPES_VARIABLE in annual.columns:
        p_str = f"plot_warming_stripes_{STRIPES_VARIABLE}.png"
        _safe_plot(plot_warming_stripes, annual, ref_window, STRIPES_VARIABLE, city["name"], p_str)
        if os.path.exists(p_str):
            plot_paths.append(p_str)

    # --- Event window -------------------------------------------------------
    event_summary_df = None
    if ENABLE_EVENT_WINDOW:
        evs: Dict[str, Dict] = {}
        for var_key in EVENT_VARIABLES:
            # ref_window, not REFERENCE_PERIOD: the rest of the script uses the
            # baseline clamped to the data actually retrieved, and the event
            # module must report against the same one or the two halves of the
            # output would quietly disagree about what "baseline" means.
            ev = analyze_event_window(annual, var_key, baseline_period=ref_window)
            evs[var_key] = ev
            if ev is None:
                continue
            pe1 = f"plot_event_{var_key}_trend.png"
            pe2 = f"plot_event_{var_key}_distributions.png"
            _safe_plot(plot_event_window_trend, ev, city["name"], pe1)
            _safe_plot(plot_event_window_distributions, ev, city["name"], pe2)
            for p in (pe1, pe2):
                if os.path.exists(p):
                    plot_paths.append(p)
            # event-specific warming stripes (same idiom, event hours instead of
            # annual maxima) -- only for the primary variable, to avoid three
            # near-identical stripe figures.
            if var_key == EVENT_VARIABLES[0]:
                pe3 = f"plot_event_warming_stripes_{var_key}.png"
                _safe_plot(plot_warming_stripes, annual, ref_window, var_key, city["name"], pe3)
                if os.path.exists(pe3):
                    plot_paths.append(pe3)
        # --- EHS evolution (optional, needs the HESTIA/PYROX suite) ---------
        primary_ev = evs.get(EVENT_VARIABLES[0])
        if ENABLE_EHS_EVOLUTION and primary_ev is not None:
            if not HESTIA_AVAILABLE:
                print("\n[EHS] HESTIA/PYROX modules not found next to this script -> "
                      "EHS-evolution module skipped (everything else still runs).")
            elif not event_slices:
                print("\n[EHS] no event weather slices retained -> module skipped.")
            else:
                ehs_res = run_ehs_evolution(primary_ev, event_slices, city, lat, lon,
                                            tz, apply_uhi)
                if ehs_res is not None:
                    ehs_summary_df = build_ehs_summary(ehs_res)
                    p_ehs = "plot_ehs_evolution.png"
                    plot_ehs_evolution(ehs_res, ehs_summary_df, city["name"], p_ehs)
                    if os.path.exists(p_ehs):
                        plot_paths.append(p_ehs)
                    p_scatter = "plot_trect_co_reserve_scatter.png"
                    plot_trect_co_reserve_scatter(ehs_res, city["name"], p_scatter)
                    if os.path.exists(p_scatter):
                        plot_paths.append(p_scatter)
                    ehs_ehe_resolvable = _ehe_is_resolvable(ehs_res)

        if any(v is not None for v in evs.values()):
            event_summary_df = build_event_summary(evs)
        else:
            print(f"\n[event] No usable data in the event trend period "
                  f"{EVENT_TREND_PERIOD[0]}-{EVENT_TREND_PERIOD[1]} -> event module skipped.")

    # --- Heat-attributable hospital admissions (ERF) ------------------------
    admissions_df = None
    if ENABLE_ADMISSIONS_ERF and "heat_admit_index" in annual.columns:
        admissions_df = analyze_admissions_windows(annual, windows, ref_window)
        pa1 = "plot_admissions_timeseries.png"
        pa2 = "plot_admissions_window_ratio.png"
        _safe_plot(plot_admissions_timeseries, annual, ref_window, city["name"], pa1)
        _safe_plot(plot_admissions_window_ratio, admissions_df, city["name"], pa2)
        for p in (pa1, pa2):
            if os.path.exists(p):
                plot_paths.append(p)

    # --- Physiological liveability (HEAT-Lim) -------------------------------
    liveability_df = None
    if ENABLE_LIVEABILITY and HEATLIM_AVAILABLE and f"minMmax_young" in annual.columns:
        liveability_df = analyze_liveability_windows(annual, windows, ref_window)
        pl1 = "plot_liveability_timeseries.png"
        pl2 = "plot_liveability_window_bar.png"
        _safe_plot(plot_liveability_timeseries, annual, ref_window, city["name"], pl1)
        _safe_plot(plot_liveability_window_bar, liveability_df, city["name"], pl2)
        pl3 = "plot_survivability_matrix.png"
        pl4 = "plot_liveability_matrix.png"
        latest_window = windows[-1] if windows else ref_window
        _safe_plot(plot_survivability_matrix, annual, ref_window, latest_window, city["name"], pl3)
        _safe_plot(plot_liveability_matrix, annual, ref_window, latest_window, city["name"], pl4)
        for p in (pl1, pl2, pl3, pl4):
            if os.path.exists(p):
                plot_paths.append(p)
    elif ENABLE_LIVEABILITY and not HEATLIM_AVAILABLE:
        print("\n[liveability] HEATLim.py not found next to this script -> "
              "liveability module skipped. Download from github.com/gguzmane/HEAT-Lim.")

    # --- Export -------------------------------------------------------------
    meta = {
        "city": city["name"],
        "country": city.get("country", "Unknown"),
        "latitude": lat, "longitude": lon, "timezone": tz,
        "population": city.get("population", 0),
        "apply_uhi": apply_uhi,
        "reference_period": f"{ref_window[0]}-{ref_window[1]}",
        "analysis_start": START_YEAR,
        "analysis_end": last_complete,
        "window_length": WINDOW_LENGTH,
        "window_step": WINDOW_STEP,
        "admissions_erf": ("van Loenhout et al. 2018 (BMC Public Health 18:108); "
                           f"MMT={ERF_MMT_C}C, beta={ERF_BETA_PER_C:.4f}/C, "
                           f"months={ERF_MONTHS[0]}-{ERF_MONTHS[1]}, log-linear approx"),
        "liveability": (f"HEAT-Lim (Vanos et al. 2023); profiles young+old; "
                        f"sun={LIVEABILITY_SUN}; exp={LIVEABILITY_EXP_TIME}h; "
                        f"activity_bar={LIVEABILITY_ACTIVITY_MET} MET"
                        if (ENABLE_LIVEABILITY and HEATLIM_AVAILABLE) else "disabled"),
        "event_window": ((f"{EVENT_NAME}: {EVENT_DAY:02d}-{EVENT_MONTH:02d} "
                          f"+/-{EVENT_DAY_WINDOW}d, {EVENT_START_HOUR:02d}:"
                          f"{EVENT_START_MINUTE:02d} +{EVENT_DURATION_MIN}min; "
                          f"trend anchored on {EVENT_TREND_PERIOD[0]}-{EVENT_TREND_PERIOD[1]}, "
                          f"baseline {REFERENCE_PERIOD[0]}-{REFERENCE_PERIOD[1]}; "
                          f"Normal fits (event-window MEANS, not block maxima)")
                         if ENABLE_EVENT_WINDOW else "disabled"),
        "model": "Klimatos.ClimateShift v1.5 (Thermopoulos thermal pipeline)",
        "generated": datetime.now().isoformat(timespec="seconds"),
    }
    filepath = save_results(annual, stats_by_var, plot_paths, meta, admissions_df,
                            liveability_df, event_summary_df, ehs_summary_df,
                            accel_summary_df)

    print_summary(stats_by_var, admissions_df, liveability_df, event_summary_df,
                  ehs_summary_df, ehs_ehe_resolvable, ehs_res)
    print("\n" + "=" * 70)
    print(f"Saved: {filepath}")
    print(f"Plots: {', '.join(plot_paths)}")
    print("=" * 70)

    # [2026-08-27] Optional Markdown report, same style/section-order
    # philosophy as generate_event_report.py's HESTIA-side report -- see
    # generate_klimatos_report.py's own docstring for why this is a
    # separate generator (different underlying data: a climate trend +
    # EHS/EHE evolution, not one Monte Carlo population run) rather than a
    # literal reuse of the HESTIA report's section structure.
    try:
        report_answer = input("\nGenerate event report (Markdown)? [y/n, default y]: ").strip().lower()
    except EOFError:
        report_answer = "y"
    if report_answer != "n":
        from generate_klimatos_report import generate_klimatos_report
        safe_city = "".join(ch for ch in meta["city"] if ch.isalnum() or ch in (" ", "_", "-")).strip()
        report_path = f"Klimatos_Rapport_{safe_city}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        event_name = EVENT_NAME if ENABLE_EVENT_WINDOW else meta["city"]
        proj_key = None
        if ehs_res is not None and EHS_TARGET_YEARS:
            proj_key = f"proj_{min(EHS_TARGET_YEARS)}_central"
        if isinstance(ehs_res, dict) and proj_key:
            ehs_res = {**ehs_res, "_report_proj_key": proj_key}
        report_text = generate_klimatos_report(
            event_name=event_name, meta=meta, annual=annual,
            ref_window=ref_window, latest_window=(windows[-1] if windows else ref_window),
            output_path=report_path,
            event_df=event_summary_df, ehs_df=ehs_summary_df,
            admissions_df=admissions_df, liveability_df=liveability_df,
            accel_df=accel_summary_df, ehs_evolution_res=ehs_res,
            plot_paths=plot_paths,
        )
        print(f"Report written to: {report_path}")

        # [2026-08-30] Optional Word (.docx) export of the same report,
        # via report_to_docx.py -- a shared styling layer used by all three
        # of this suite's report generators (see that module's own
        # docstring). Requires Node.js + the 'docx' npm package
        # (package.json in this suite's root); failure here is reported but
        # does not affect the Markdown report already written above.
        try:
            docx_answer = input("Also export as Word (.docx)? [y/n, default y]: ").strip().lower()
        except EOFError:
            docx_answer = "y"
        if docx_answer != "n":
            try:
                from report_to_docx import export_report_docx
                docx_path = report_path[:-3] + ".docx"
                export_report_docx(report_text, docx_path, report_kind="facts",
                                   event_name=event_name)
                print(f"Word report written to: {docx_path}")
            except Exception as e:
                print(f"{Fore.YELLOW}Word export failed ({e}) -- the Markdown "
                      f"report above is unaffected.{Style.RESET_ALL}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting...")
    except Exception as e:
        logger.exception("Fatal error")
        print(f"\nFatal error: {e}")
        sys.exit(1)
