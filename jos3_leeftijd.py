"""
jos3_leeftijd.py -- gradual age decrement for JOS-3 (variant C, 2026-10-16)

WHY
---
JOS-3 (Takahashi et al. 2020, Energy & Buildings, in pythermalcomfort)
applies the age effect on heat loss as STEPS:
  * sweat signal per segment x 0.40-0.75        from exactly age 60
  * skin vasodilation signal x 0.31-0.91        from exactly age 60
  * basal blood flow (cardiac index) x 1.00 / 0.85 / 0.75 / 0.70
    for ages <50 / 50-59 / 60-69 / >=70
Measured with this suite (pythermalcomfort 4.6.2; one runner 1.78 m / 72 kg,
3 h at 11 MET, 12 degC): T_rect 39.42 degC at 59 y -> 40.41 degC at 60 y,
i.e. +1.0 degC for one birthday, plus +0.3 degC between 45 and 50 y.
In the Amsterdam 2026-10-18 run 7 of the 12 participants aged 60+ fell in
the hottest 2.5% although their finish times were mid-field.

The physiology is gradual (Radboudumc, pers. comm. 2026-10-16):
  * Larose et al. 2013, PLoS ONE 8(12):e83148 -- heat-loss decrements
    during exercise from age 40-44 onward.
  * Bongers et al. 2014, Age 36(6) -- further decline 80 vs 60 y
    (exercise-induced core temperature rise 1.2 vs 0.7 degC, 30-km march).

WHAT THIS DOES (variant C, chosen by the author 2026-10-16)
--------------------------------------------------------------
  * sweat and vasodilation decrement:  sd(age) = 1 - w(age) * (1 - sd_JOS3)
    with w = 0 at <= 40 y, rising linearly to 1 at >= 75 y.
    The MAGNITUDE stays JOS-3's own (no new calibration); only the onset and
    shape change. The end age 75 is an own choice between the two age groups of Bongers et al. (2014).
  * cardiac index: linear interpolation through the JOS-3 group values at the
    group mid-points (45 y: 1.00, 55: 0.85, 65: 0.75, 75: 0.70).
  * vasoconstriction, shivering, non-shivering thermogenesis: unchanged.

[2026-10-23] UPDATE: for trained runners the decrement turned out too LARGE,
not too small (ThermoClinic Emmen 17-10: model 1.0 degC too hot at the peak
for 9 runners aged 49-67). It is now scaled by fitness and heat
acclimatisation -- see FITNESS AND HEAT CURVE below and TECHNICAL_REFERENCE
4.1.3. The note that follows applies to untrained, unacclimatised people.

KNOWN LIMITATION (documented, not fixed): the age effect is probably still
too SMALL -- JOS-3 never lowers heat loss beyond its single >=60 factor, so it
reproduces neither the 35-42% extra heat storage at 40-55 y (Larose) nor the
clearly larger rise in 80- vs 60-year-olds (Bongers et al. 2014). A variant that continues
the decline past 75 needs own measurement data first.

HOW
---
pythermalcomfort's files on disk are not modified, but at activation three of
its functions are REPLACED IN MEMORY for the running Python process: the
JOS-3 functions `thermoregulation.evaporation` and
`thermoregulation.skin_blood_flow` are rebuilt from their own source with the
age branch replaced, and `construction.bfb_rate` is wrapped. This is only
verified for pythermalcomfort REQUIRED_PTC_VERSION (4.6.2). With any other
version the import stops with an ImportError, because a silently unpatched or
differently patched JOS-3 would change every result; set the environment
variable HESTIA_ALLOW_OTHER_PYTHERMALCOMFORT=1 to try anyway (the source
anchors are still checked and a failed patch then also stops with an error).
Set ENABLED = False (or call disable()) to get JOS-3's original behaviour.
"""
import inspect
import os
import textwrap
import warnings
from importlib.metadata import version as _pkg_version

import numpy as np
from pythermalcomfort.jos3_functions import construction as _cons
from pythermalcomfort.jos3_functions import thermoregulation as _threg

ENABLED = True
REQUIRED_PTC_VERSION = "4.6.2"
_PTC_VERSION = _pkg_version("pythermalcomfort")
_ALLOW_OTHER = bool(os.environ.get("HESTIA_ALLOW_OTHER_PYTHERMALCOMFORT"))
if _PTC_VERSION != REQUIRED_PTC_VERSION and not _ALLOW_OTHER:
    raise ImportError(
        f"HESTIA needs pythermalcomfort=={REQUIRED_PTC_VERSION} (found {_PTC_VERSION}). "
        f"Install it with: pip install pythermalcomfort=={REQUIRED_PTC_VERSION} -- "
        "or set HESTIA_ALLOW_OTHER_PYTHERMALCOMFORT=1 to try another version at your own risk.")
AGE_START = 40.0   # no decrement at or below this age
AGE_FULL = 75.0    # full JOS-3 decrement at or above this age
CI_AGE_POINTS = (45.0, 55.0, 65.0, 75.0)
CI_FACTORS = (1.00, 0.85, 0.75, 0.70)   # JOS-3's own group values (construction.bfb_rate)

# -----------------------------------------------------------------------------
# [2026-10-23] FITNESS AND HEAT CURVE (author's decision, ThermoClinic Emmen
# 17-10; second core analysis 23-10).
# The age decrement is now multiplied by a per-person factor
#     person = g_fit(VO2max / VO2max_norm(age, sex)) x g_heat(acclimatisation)
#   g_fit   1 at a ratio <= FIT_FULL_DECREMENT, 0 at >= FIT_NO_DECREMENT,
#           linear between (model choice 0.80 / 1.00).
#   g_heat  1 - HEAT_ACCLIM_REDUCTION x acclimatisation (0..1), model choice 0.5.
# VO2max_norm is the suite's own runner mean (generate_base_population step 3,
# individual_engine._default_vo2max): 52 (men) / 44 (women) - 0.5 x (age - 35).
# Why: with the full decrement the model ran 1.0 degC too hot for 9 trained
# runners aged 49-67; the fit improved monotonically down to no decrement.
# Kenney (GSSI SSE 44): in fit older athletes heat storage does not depend on
# age once VO2max is accounted for; Roberts et al. 1977 (J Appl Physiol
# 43:133): training and acclimation shift the sweating and vasodilation
# thresholds down. Untrained, unacclimatised older people keep JOS-3's own
# decrement. The skin-blood-flow, sweat and cardiac-index decrements are all
# scaled with the same person factor.
# The factor is module state: set_person() is called right before a person's
# JOS-3 model is built and stays valid until the next person (one simulation
# at a time per process). reset_person() restores factor 1 (JOS-3 as before).
# -----------------------------------------------------------------------------
# [2026-10-27] COLD-SKIN LIMIT (author's decision: available as a setting,
# OFF by default until a clinic with a reference measurement decides).
# In JOS-3 (Stolwijk) a skin colder than its set point suppresses skin blood
# flow (factor 2**(err_sk/6) plus the cold signal in vasoconstriction) and
# sweating (2**(err_sk/10) and the cold signal in the sweat drive). During
# running in cool weather the model skin ends up ~9 K below set point and the
# core runs too hot (no "prescriptive zone"); JOS-3 itself was validated only
# at rest (Takahashi et al. 2020). In Emmen 17-10 the model chest skin was
# 2.9 degC colder than the CORE skin reading; with a limit of 2 K it was
# 0.5 degC colder. COLD_SKIN_LIMIT_K = x limits err_sk to >= -x K in the
# skin-blood-flow and sweating functions only (shivering etc. untouched).
# None = JOS-3 unchanged (bit-identical). Diagnostic value 2.0 K, not fitted.
# Override per process with the environment variable HESTIA_COLD_SKIN_LIMIT_K
# (needed for worker processes, which import this module afresh).
COLD_SKIN_LIMIT_K = None
_COLD = {"limit": (float(os.environ["HESTIA_COLD_SKIN_LIMIT_K"])
                   if os.environ.get("HESTIA_COLD_SKIN_LIMIT_K", "").strip() not in ("", "none", "None")
                   else COLD_SKIN_LIMIT_K)}


def set_cold_skin_limit(limit_k=None) -> None:
    """Set the cold-skin limit for this process (None = off)."""
    _COLD["limit"] = None if limit_k is None else float(limit_k)


def cold_skin_limit():
    return _COLD["limit"]


def _cold_wrap(fn):
    """Wrap a JOS-3 thermoregulation function (err_cr, err_sk, ...) so that
    err_sk is limited to >= -limit when a limit is set. JOS-3 calls these
    functions with keywords; positional calls are handled too."""
    def wrapped(*args, **kwargs):
        lim = _COLD["limit"]
        if lim is not None:
            if "err_sk" in kwargs:
                kwargs["err_sk"] = np.maximum(np.asarray(kwargs["err_sk"], dtype=float), -lim)
            elif len(args) >= 2:
                args = list(args)
                args[1] = np.maximum(np.asarray(args[1], dtype=float), -lim)
        return fn(*args, **kwargs)
    wrapped.__name__ = getattr(fn, "__name__", "wrapped")
    wrapped.__wrapped__ = fn
    return wrapped


FITNESS_CURVE_ENABLED = True
FIT_FULL_DECREMENT = 0.80
FIT_NO_DECREMENT = 1.00
HEAT_ACCLIM_REDUCTION = 0.5
_PERSON = {"factor": 1.0}


def vo2max_norm(age: float, sex: str) -> float:
    mu = 52.0 if str(sex).lower() in ("male", "man", "m") else 44.0
    return mu - 0.5 * max(0.0, float(age) - 35.0)


def person_factor(vo2max, age, sex, acclimatisation=0.0) -> float:
    """Fraction of the age decrement for this person (0..1)."""
    if not FITNESS_CURVE_ENABLED:
        return 1.0
    if vo2max is None or not np.isfinite(float(vo2max)) or float(vo2max) <= 0:
        g_fit = 1.0
    else:
        r = float(vo2max) / vo2max_norm(age, sex)
        span = max(1e-6, FIT_NO_DECREMENT - FIT_FULL_DECREMENT)
        g_fit = float(np.clip((FIT_NO_DECREMENT - r) / span, 0.0, 1.0))
    acc = float(np.clip(acclimatisation or 0.0, 0.0, 1.0))
    return g_fit * (1.0 - HEAT_ACCLIM_REDUCTION * acc)


def set_person(vo2max, age, sex, acclimatisation=0.0) -> float:
    _PERSON["factor"] = person_factor(vo2max, age, sex, acclimatisation)
    return _PERSON["factor"]


def reset_person() -> None:
    _PERSON["factor"] = 1.0


def current_person_factor() -> float:
    return _PERSON["factor"]

# [2026-10-30] The originals are kept on the pythermalcomfort module itself, so
# that re-importing this module (Spyder reloads changed user modules between
# runs) still finds JOS-3's own functions and not the already patched ones.
# Without this the second run failed with "could not get source code" and the
# cardiac-index factor could have been applied twice.
_ORIG = getattr(_threg, "_hestia_jos3_orig", None)
if _ORIG is None:
    _ORIG = {
        "evaporation": _threg.evaporation,
        "skin_blood_flow": _threg.skin_blood_flow,
        "bfb_rate": _cons.bfb_rate,
    }
    _threg._hestia_jos3_orig = _ORIG
_STATE = {"active": False, "reason": ""}


def weight(age: float) -> float:
    """Fraction of JOS-3's >=60 decrement applied at this age (0..1)."""
    if AGE_FULL <= AGE_START:
        w = 1.0 if age >= AGE_START else 0.0
    else:
        w = float(np.clip((float(age) - AGE_START) / (AGE_FULL - AGE_START), 0.0, 1.0))
    return w * _PERSON["factor"]


def ci_factor(age: float) -> float:
    """Cardiac-index age factor, linear between JOS-3's group values."""
    ci_age = float(np.interp(float(age), CI_AGE_POINTS, CI_FACTORS))
    return 1.0 - _PERSON["factor"] * (1.0 - ci_age)


def _rebuild(fn, var, anchor):
    src = textwrap.dedent(inspect.getsource(fn))
    if src.count("if age < 60:") != 1 or src.count(anchor) != 1:
        raise RuntimeError(f"{fn.__name__}: source layout differs from pythermalcomfort 4.6.x")
    # Always build the >=60 array, then scale it by the age weight.
    src = src.replace("if age < 60:", "if False:  # jos3_leeftijd: gradual decrement below")
    src = src.replace(
        anchor,
        f"    {var} = 1.0 - _JOS3_AGE_WEIGHT(age) * (1.0 - np.asarray({var}))\n" + anchor,
        1,
    )
    ns = dict(_threg.__dict__)
    ns["_JOS3_AGE_WEIGHT"] = weight
    exec(compile(src, f"<jos3_leeftijd.{fn.__name__}>", "exec"), ns)
    return ns[fn.__name__]


def _bfb_rate(height, weight, bsa_equation, age, ci):
    # Same signature as construction.bfb_rate (JOS-3 calls it with keywords).
    # JOS-3's own result for an age without CI adjustment (<50), times the
    # interpolated factor -- identical to JOS-3 at the group mid-points.
    return _ORIG["bfb_rate"](height=height, weight=weight, bsa_equation=bsa_equation,
                             age=30, ci=ci) * ci_factor(age)


try:
    _EVAP = _rebuild(_ORIG["evaporation"], "sd_sweat", "    e_sweat = skin_sweat")
    _SBF = _rebuild(_ORIG["skin_blood_flow"], "sd_dilat", "    # Skin blood flow [L/h]")
    _BUILD_OK = True
except Exception as _e:   # pragma: no cover -- only on an incompatible pythermalcomfort
    _BUILD_OK = False
    _STATE["reason"] = str(_e)


def enable() -> bool:
    """Install the gradual age decrement. Returns True when active."""
    if not _BUILD_OK:
        raise RuntimeError("jos3_leeftijd: the JOS-3 age patch could not be built -- "
                           + _STATE["reason"] + f" (pythermalcomfort {_PTC_VERSION}). "
                           "Install pythermalcomfort==" + REQUIRED_PTC_VERSION + ".")
    _threg.evaporation = _cold_wrap(_EVAP)
    _threg.skin_blood_flow = _cold_wrap(_SBF)
    _cons.bfb_rate = _bfb_rate
    _STATE["active"] = True
    return True


def disable() -> None:
    """Restore JOS-3's original age steps."""
    _threg.evaporation = _cold_wrap(_ORIG["evaporation"])
    _threg.skin_blood_flow = _cold_wrap(_ORIG["skin_blood_flow"])
    _cons.bfb_rate = _ORIG["bfb_rate"]
    _STATE["active"] = False


def is_active() -> bool:
    return _STATE["active"]


if ENABLED:
    enable()
