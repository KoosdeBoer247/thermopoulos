# -*- coding: utf-8 -*-
"""
PYROX — dynamic heat-risk model (readable reference implementation)
================================================================================
A control-theoretic model of multi-day heat strain, implemented so that every
variable name says what it means and every equation is traceable to the paper:

    de Boer, K. (2026). "A Control-Theoretic Framework for Dynamic Heat Risk
    Assessment: Modeling Acclimatization, Cumulative Strain, and Stability
    Thresholds During Multi-Day Heat Exposure." Research Square.
    https://doi.org/10.21203/rs.3.rs-8626369/v1

--------------------------------------------------------------------------------
THE PRINCIPLE BEING MODELLED (plain language)
--------------------------------------------------------------------------------
[2026-09] Corrected from an earlier "two competing loops" description (a
protective loop racing an undermining loop). That is not what the equations
do, and the correction matters enough to state plainly here, not only in the
plotting code: acclimatization is a straight-through DAMPING PATH driven by
the external forcing, not a loop -- it does not itself respond to strain.
There is exactly ONE closed feedback loop in this model. What follows
describes that structure.

Heat strain is driven by two things: a direct forcing effect, and a single
feedback loop that can undermine the body's response to that forcing.

  * THE FORCING'S DIRECT EFFECT, and a DAMPING PATH it also drives.
    Heat exposure (baseline_heat_load) raises cumulative strain directly.
    It also drives acclimatization: repeated exposure builds up short-term
    adaptation, which lowers the load the body actually experiences, which
    slows strain accumulation. This damping path has a START-UP DELAY --
    adaptation is driven by a memory of the PAST ~10 days, so it cannot act
    on day one of a heatwave -- but it is not itself a loop: nothing here
    yet depends on strain. On its own, this would be an ordinary stable
    system (more exposure, more damping, no instability).

  * THE ONE REINFORCING LOOP — strain erodes the net benefit of
    acclimatization. Once load exceeds a recovery threshold, strain
    accumulates. As accumulated strain rises, the NET PROTECTIVE BENEFIT of
    acclimatization declines (the coupling term 1 - kappa*Sigma), which
    raises the experienced load again, which makes strain grow faster.
    Trace the polarity around this one cycle -- strain (+ on suppression)
    -> suppression (\u2212 on effective acclimatization) -> acclimatization
    (\u2212 on strain) -- and the product of three negatives-and-positives is
    positive: a self-reinforcing loop, not a balancing one. This loop acts
    from day one and is the only closed cycle in the model.

    NOTE — net effect, not mechanism: the term (1 - kappa*Sigma) is an effective
    description, NOT a claim that strain physiologically blocks the manufacture
    of adaptation. Physiology is regime-dependent — mild recoverable strain can
    ENHANCE adaptation (permissive dehydration), while acclimatization decays
    when unmaintained (~1 day lost per 2 days without exposure; Daanen, Racinais
    & Periard 2018, doi:10.1007/s40279-017-0808-x). This model's domain is
    sustained, uncompensable heat in vulnerable groups, where accumulated strain
    coincides with eroding net protection.

Because the damping path starts late and the reinforcing loop acts from day
one, the outcome depends on which wins first. At a constant load there are
three regimes [2026-11-24, corrected]:
  * low load: strain dies out to 0 from any starting point ("safe");
  * middle band: BISTABLE. equilibrium_strain() returns an interior root,
    but that root is UNSTABLE -- a tipping point, not a resting level.
    Around it the daily change has slope L*P*kappa - 0.1*b (= feedback_gain),
    which is positive for every group; a stable root would need
    L*P*kappa < 0.1*b. Below the root strain dies out; above it strain runs
    to critical_strain and stays there until the load falls below the lower
    edge of the band, r + b*(1 + 0.1/kappa) (hysteresis);
  * high load: strain runs away to critical_strain from any starting point
    ("runaway").
There is no stable intermediate level below critical. (Until 2026-11-24 this
docstring said that under a mild load "strain stabilises safely (an
equilibrium_strain exists below critical)"; the numbers were never affected.)

The critical level is not a tuned threshold — it falls out of the algebra of the
suppression term (see CRITICAL_STRAIN below). A population group is "vulnerable"
precisely when its damping path is too weak to get ahead of the reinforcing loop
under the same heat that a resilient group would ride out safely.

--------------------------------------------------------------------------------
NAMING NOTE (old symbol -> readable name)
--------------------------------------------------------------------------------
    R1        -> baseline_heat_load            (Tier-1 input)
    R2        -> final_risk                     (Tier-3 output)
    alpha     -> acclimatization
    alpha_max -> max_acclimatization_capacity
    Sigma     -> cumulative_strain
    Sigma_crit-> critical_strain
    kappa     -> strain_suppression_strength
    theta_rec -> recovery_threshold
    rho       -> base_recovery_rate
    gamma     -> strain_amplification
    u(t)      -> exposure_signal
    s(t)      -> acclimatization_stimulus
    h[k]      -> exposure_memory_weights        (FIR kernel)
    Delta     -> net_strain_input
--------------------------------------------------------------------------------
KEY REFERENCES (see REFERENCES.md for full list and scope notes)
--------------------------------------------------------------------------------
  * Périard, Racinais & Sawka (2015), doi:10.1111/sms.12408 — heat-acclimatization
    timescale (~10-14 days) and the protective, strain-attenuating direction of
    the acclimatization loop. Grounds ACCLIMATIZATION_MEMORY_DAYS and the
    protective loop's form (NOT the specific parameter values).
  * Fouillet et al. (2006), doi:10.1007/s00420-006-0089-4 — the August-2003
    French heatwave showed excess mortality building over successive days and
    rising steeply with age (none below 35 y). This cumulative, age-graded
    pattern is what PYROX's divergent group trajectories reproduce.

  Parameter values (kappa, gamma, per-group capacities/thresholds) are
  physiological-plausibility estimates per the whitepaper, NOT measured
  constants. No citation is given for the exact numbers because none exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional

import numpy as np


# ============================================================================
# LITERAL MODEL CONSTANTS (fixed by the paper, named so they are not "magic")
# ============================================================================

ACCLIMATIZATION_MEMORY_DAYS: int = 10
"""Length of the exposure memory (FIR filter), paper Sec 2.2 Step 1.

Scientific basis: short-term heat acclimatization develops over roughly one to
two weeks, with the major adaptations (plasma-volume expansion, reduced exercise
heart rate, earlier and increased sweating, lower core/skin temperature)
appearing substantially within the first week and over a ~10-14 day course
(Périard, Racinais & Sawka 2015, Scand J Med Sci Sports 25(S1):20-38,
doi:10.1111/sms.12408). A 10-day memory captures that window. NOTE: this
reference justifies the timescale and the protective DIRECTION of the loop, not
the specific kernel weights, which are a modelling choice.
"""

EXPOSURE_SIGNAL_CENTER: float = 1.0
"""Center of the sigmoid that maps heat load to a bounded exposure signal,
paper Sec 2.2 Step 1: exposure_signal = 1 / (1 + exp(-(load - 1))).

This is the published constant. (An earlier code base used the group's recovery
threshold here instead; this implementation follows the paper.)
"""

HOMEOSTATIC_DRIVE_COEFFICIENT: float = 0.1
"""Slope of the "the more strained, the harder the body tries to recover" term,
paper Sec 2.2 Step 4: recovery is scaled by (1 + 0.1 * cumulative_strain).

Scientific basis: a modest, monotone increase in recovery drive with strain. The
0.1 value is a modelling choice (paper: "physiological plausibility"), kept here
exactly as published.
"""


# ============================================================================
# POPULATION GROUP PARAMETERS
# ============================================================================

@dataclass
class GroupParameters:
    """
    The physiological parameters that distinguish one population group from
    another. Every field is named for what it does in the dynamics.

    THE FOUR PROTECTIVE / VULNERABILITY KNOBS
    -----------------------------------------
    For the model to be internally coherent, every parameter that PROTECTS a
    group must move together along the resilient -> vulnerable axis. A resilient
    group has:
        - HIGH max_acclimatization_capacity  (strong protective loop)
        - HIGH recovery_threshold            (tolerates more load before straining)
        - HIGH base_recovery_rate            (clears strain faster each day)
        - a STEEP exposure_memory (recent days weighted more, faster adaptation)
    A vulnerable group has all of these low. (This is exactly why the published
    parameter table had to be corrected — see pyrox_groups.py.)

    strain_suppression_strength is the odd one out: it is not a "protective" knob
    but the coupling gain of the undermining loop, and it sets the critical
    threshold (critical_strain = 1 / strain_suppression_strength).
    """

    # identity
    name: str
    display_name: str

    # --- protective capacity --------------------------------------------------
    max_acclimatization_capacity: float
    """Ceiling on adaptation (old: alpha_max). The most the protective loop can
    ever reduce the experienced load by, as a fraction in [0, 1]. Higher = a
    stronger protective loop. (paper Sec 2.2 Step 1)"""

    recovery_threshold: float = 1.0
    """Load level below which NO strain accumulates (old: theta_rec). A higher
    threshold means the group tolerates more heat before exhaustion begins.
    (paper Sec 2.2 Step 3)"""

    base_recovery_rate: float = 0.3
    """Strain cleared per day under ideal sleep at zero strain (old: rho).
    Higher = faster daily recovery. (paper Sec 2.2 Step 4)"""

    # --- coupling / amplification --------------------------------------------
    strain_suppression_strength: float = 0.5
    """How strongly accumulated strain suppresses adaptation (old: kappa). This
    is the gain of the bidirectional feedback. It also fixes the instability
    point: critical_strain = 1 / strain_suppression_strength (paper Sec 3.3).
    The default 0.5 gives critical_strain = 2.0."""

    strain_amplification: float = 0.3
    """How much accumulated strain inflates the final risk score (old: gamma),
    paper Sec 2.2 Step 5. Published table value is 0.3 for all groups."""

    # --- exposure memory ------------------------------------------------------
    exposure_memory_weights: np.ndarray = field(
        default_factory=lambda: _normalize_to_unit_sum(
            np.arange(1, ACCLIMATIZATION_MEMORY_DAYS + 1, dtype=float)
        )
    )
    """Normalised FIR kernel over the last ACCLIMATIZATION_MEMORY_DAYS days
    (old: h[k]), ordered OLDEST -> NEWEST and summing to 1 (paper Sec 2.2
    Step 1). A steep kernel (recent days weighted heavily) means fast-adapting
    physiology; a flat kernel means slow, weak adaptation."""

    # optional metadata, not used by the dynamics
    age_range: tuple = (0, 120)
    evidence_status: str = "extrapolated"
    """One of 'paper' (the three prototype groups, with documented correction)
    or 'extrapolated' (the other 16 groups: physiologically ordered but not
    independently validated)."""

    def __post_init__(self):
        weights = np.asarray(self.exposure_memory_weights, dtype=float)
        if weights.shape[0] != ACCLIMATIZATION_MEMORY_DAYS:
            raise ValueError(
                f"{self.name}: exposure_memory_weights must have length "
                f"{ACCLIMATIZATION_MEMORY_DAYS}, got {weights.shape[0]}"
            )
        self.exposure_memory_weights = _normalize_to_unit_sum(weights)

    @property
    def critical_strain(self) -> float:
        """The instability threshold, derived (not tuned): paper Sec 3.3,
        critical_strain = 1 / strain_suppression_strength.

        Beyond this strain level the suppression term zeroes out adaptation and
        the system can no longer protect itself."""
        return 1.0 / self.strain_suppression_strength


# ============================================================================
# MODEL STATE
# ============================================================================

@dataclass
class DailyState:
    """
    The system state at the end of a given day.

        cumulative_strain          accumulated physiological exhaustion (old: Sigma)
        effective_acclimatization  protective adaptation currently in effect (old: alpha_eff)
        exposure_memory            last N daily exposure signals, OLDEST -> NEWEST
        day_index                  how many days have been simulated
    """
    cumulative_strain: float = 0.0
    effective_acclimatization: float = 0.0
    exposure_memory: List[float] = field(
        default_factory=lambda: [0.0] * ACCLIMATIZATION_MEMORY_DAYS
    )
    day_index: int = 0


def make_equilibrium_initial_state(
    pre_heatwave_heat_load: float,
    initial_strain: float = 0.1,
) -> DailyState:
    """
    Build the starting state for a forecast-style run, in THERMAL EQUILIBRIUM
    with the conditions the population experienced just before the heatwave.

    WHY THIS IS THE RIGHT DEFAULT
    -----------------------------
    The exposure memory is not a free parameter: it stores the exposure signals
    of the days BEFORE the simulation window. For "what is the risk during an
    expected heatwave?", the population enters the heatwave already acclimatized
    to the recent baseline weather. We model that by filling the whole memory
    with the exposure signal of a representative pre-heatwave load:

        exposure_memory = [ exposure_signal(pre_heatwave_heat_load) ] * N

    This uses the SAME exposure_signal() transform as the dynamics, so the start
    can never drift from the model. It is the most neutral self-consistent start:
    it assumes only "the population was in equilibrium with recent conditions",
    no hidden scenario about the wider world.

    Special cases expressible through the one argument:
        * cold-climate arrival (legacy cold start): pre_heatwave_heat_load -> very
          low, giving a near-zero memory;
        * pre-acclimatization study (paper Sec 4.3): raise pre_heatwave_heat_load.
    """
    baseline_signal = exposure_signal(pre_heatwave_heat_load)
    return DailyState(
        cumulative_strain=initial_strain,
        effective_acclimatization=0.0,  # recomputed on day 1 from the (warm) memory
        exposure_memory=[baseline_signal] * ACCLIMATIZATION_MEMORY_DAYS,
        day_index=0,
    )


# ============================================================================
# THE EXPOSURE SIGNAL (paper Sec 2.2 Step 1)
# ============================================================================

def exposure_signal(baseline_heat_load: float) -> float:
    """
    Map an unbounded daily heat load to a bounded exposure signal in (0, 1).

        exposure_signal = 1 / (1 + exp(-(baseline_heat_load - 1)))   [paper Step 1]

    The signal is what the acclimatization memory stores. Centred at
    EXPOSURE_SIGNAL_CENTER = 1.0, so a load of 1.0 gives a signal of exactly 0.5.
    Implemented via tanh for numerical stability at extreme loads.
    """
    return float(0.5 * (1.0 + np.tanh(0.5 * (baseline_heat_load - EXPOSURE_SIGNAL_CENTER))))


# ============================================================================
# THE MODEL
# ============================================================================

class PyroxModel:
    """
    Simulates one population group's daily heat-strain dynamics.

    The public methods are:
        advance_one_day(...)  -> run a single day's five update steps
        simulate(...)         -> run a full heat-load series, return trajectories
        time_to_critical(...) -> analytic estimate from paper Sec 3.4

    All five update steps below correspond one-to-one to paper Section 2.2 and
    are executed in the paper's order to preserve temporal causality.
    """

    def __init__(self, group: GroupParameters):
        self.group = group

    # ---- Step 1a: how strongly is the protective loop currently driven? ----
    def acclimatization_stimulus(self, exposure_memory: List[float]) -> float:
        """
        Memory-weighted sum of PAST exposure signals (paper Sec 2.2 Step 1):

            acclimatization_stimulus = sum_k  memory_weight[k] * exposure_signal[t-k]

        CAUSALITY: this uses only days strictly before today. Today's exposure is
        added to the memory AFTER the day is computed (see advance_one_day), so
        today's heat can only raise adaptation tomorrow — never instantly. This is
        the start-up delay that makes the protective loop a late starter.
        """
        return float(np.dot(self.group.exposure_memory_weights, exposure_memory))

    # ---- Step 1b: turn that drive into a potential adaptation level ---------
    def acclimatization_potential(self, stimulus: float) -> float:
        """Adaptation the group COULD reach from recent exposure, before any
        suppression (paper Sec 2.2 Step 1):

            acclimatization_potential = max_acclimatization_capacity * stimulus
        """
        return self.group.max_acclimatization_capacity * stimulus

    # ---- Step 2: the undermining loop suppresses the protective loop --------
    def suppression_factor(self, cumulative_strain: float) -> float:
        """The gate through which strain shuts down adaptation (paper Sec 2.2
        Step 2):

            suppression_factor = max(0, 1 - strain_suppression_strength * strain)

        It reaches exactly 0 when strain = critical_strain (= 1/strength). That
        zero is the mathematical origin of the instability threshold (Sec 3.3).
        """
        gate = 1.0 - self.group.strain_suppression_strength * cumulative_strain
        return max(0.0, gate)

    def effective_acclimatization(self, potential: float, cumulative_strain: float) -> float:
        """Adaptation actually in effect = potential after suppression
        (paper Sec 2.2 Step 2)."""
        return potential * self.suppression_factor(cumulative_strain)

    # ---- Step 3: net load that actually feeds the strain accumulator --------
    def net_strain_input(self, baseline_heat_load: float,
                         effective_acclimatization: float) -> float:
        """Load remaining after adaptation, above the recovery threshold
        (paper Sec 2.2 Step 3):

            net_strain_input = max(0,
                baseline_heat_load * (1 - effective_acclimatization) - recovery_threshold)

        This is where the undermining loop closes: lower effective adaptation ->
        a larger surviving load -> more strain.
        """
        experienced_load = baseline_heat_load * (1.0 - effective_acclimatization)
        return max(0.0, experienced_load - self.group.recovery_threshold)

    # ---- Step 4: update the strain accumulator ------------------------------
    def daily_recovery(self, cumulative_strain: float, sleep_quality: float) -> float:
        """Strain cleared today (paper Sec 2.2 Step 4):

            daily_recovery = base_recovery_rate * sleep_quality
                             * (1 + HOMEOSTATIC_DRIVE_COEFFICIENT * strain)

        Poor sleep scales recovery down; higher strain scales it up slightly
        (homeostatic drive).
        """
        homeostatic_drive = 1.0 + HOMEOSTATIC_DRIVE_COEFFICIENT * cumulative_strain
        return self.group.base_recovery_rate * sleep_quality * homeostatic_drive

    def update_strain(self, cumulative_strain: float, net_strain_input: float,
                      sleep_quality: float) -> float:
        """New cumulative strain, bounded to [0, critical_strain]
        (paper Sec 2.2 Step 4):

            strain <- strain + net_strain_input - daily_recovery,  clipped.

        The upper clip at critical_strain is paper-specified ("strain is bounded
        between 0 and Sigma_critical"): once at the ceiling the group has lost all
        adaptive capacity and is in runaway decompensation.
        """
        recovery = self.daily_recovery(cumulative_strain, sleep_quality)
        updated = cumulative_strain + net_strain_input - recovery
        return float(np.clip(updated, 0.0, self.group.critical_strain))

    # ---- Step 5: final risk score -------------------------------------------
    def final_risk(self, baseline_heat_load: float,
                   effective_acclimatization: float,
                   cumulative_strain: float) -> float:
        """Tier-3 risk, combining acute load (reduced by adaptation) with the
        amplifying effect of accumulated strain (paper Sec 2.2 Step 5):

            final_risk = baseline_heat_load * (1 - effective_acclimatization)
                         * (1 + strain_amplification * cumulative_strain)
        """
        acute = baseline_heat_load * (1.0 - effective_acclimatization)
        amplification = 1.0 + self.group.strain_amplification * cumulative_strain
        return acute * amplification

    # ---- one full day -------------------------------------------------------
    def advance_one_day(self, state: DailyState, baseline_heat_load: float,
                        sleep_quality: float = 1.0) -> tuple:
        """
        Run one day's five update steps in the paper's causal order and return
        (new_state, diagnostics). `diagnostics` is a dict of every intermediate
        quantity, with readable keys, for inspection and plotting.
        """
        # Step 1 — protective loop (uses PAST exposure only)
        todays_signal = exposure_signal(baseline_heat_load)
        stimulus = self.acclimatization_stimulus(state.exposure_memory)
        potential = self.acclimatization_potential(stimulus)

        # Step 2 — undermining loop suppresses it, using YESTERDAY's strain
        gate = self.suppression_factor(state.cumulative_strain)
        eff_acclim = potential * gate

        # Step 3 — net load into the strain accumulator
        net_input = self.net_strain_input(baseline_heat_load, eff_acclim)

        # Step 4 — strain update with recovery (bounded)
        recovery = self.daily_recovery(state.cumulative_strain, sleep_quality)
        new_strain = self.update_strain(state.cumulative_strain, net_input, sleep_quality)

        # Step 5 — final risk for the day
        risk = self.final_risk(baseline_heat_load, eff_acclim, new_strain)

        # Step 6 — append TODAY's signal to memory AFTER the convolution (causality)
        new_memory = state.exposure_memory[1:] + [todays_signal]

        new_state = DailyState(
            cumulative_strain=new_strain,
            effective_acclimatization=eff_acclim,
            exposure_memory=new_memory,
            day_index=state.day_index + 1,
        )

        diagnostics = {
            "day": state.day_index + 1,
            "baseline_heat_load": baseline_heat_load,
            "exposure_signal": todays_signal,
            "acclimatization_stimulus": stimulus,
            "acclimatization_potential": potential,
            "suppression_factor": gate,
            "effective_acclimatization": eff_acclim,
            "net_strain_input": net_input,
            "daily_recovery": recovery,
            "cumulative_strain": new_strain,
            "final_risk": risk,
        }
        return new_state, diagnostics

    # ---- multi-day ----------------------------------------------------------
    def simulate(self, heat_load_series: List[float],
                 sleep_quality_series: Optional[List[float]] = None,
                 pre_heatwave_heat_load: Optional[float] = None,
                 initial_strain: float = 0.1,
                 initial_state: Optional[DailyState] = None) -> Dict:
        """
        Run the model over a full daily heat-load series.

        STARTING CONDITION (in priority order):
          1. an explicit `initial_state`, if you pass one;
          2. otherwise thermal equilibrium at `pre_heatwave_heat_load` (the
             default and recommended choice). If that argument is None it
             defaults to the first day's load, i.e. the population is taken to be
             acclimatized to the conditions it enters the window with.

        Returns a dict of trajectories plus the intervention-zone crossing days
        defined in paper Sec 4.2 (thresholds are fractions of critical_strain):
            caution_day   : strain first reaches 0.50 * critical_strain
            danger_day    : strain first reaches 0.75 * critical_strain
            emergency_day : strain first reaches 0.90 * critical_strain
        """
        n_days = len(heat_load_series)
        if sleep_quality_series is None:
            sleep_quality_series = [1.0] * n_days
        if len(sleep_quality_series) != n_days:
            raise ValueError("sleep_quality_series must match heat_load_series length")

        if initial_state is not None:
            state = initial_state
        else:
            baseline = (pre_heatwave_heat_load
                        if pre_heatwave_heat_load is not None
                        else heat_load_series[0])
            state = make_equilibrium_initial_state(baseline, initial_strain)

        states = [state]
        diagnostics = []
        for day in range(n_days):
            state, diag = self.advance_one_day(
                state, heat_load_series[day], sleep_quality_series[day]
            )
            states.append(state)
            diagnostics.append(diag)

        strain_trajectory = np.array([s.cumulative_strain for s in states])
        acclim_trajectory = np.array([s.effective_acclimatization for s in states])
        risk_trajectory = np.array([d["final_risk"] for d in diagnostics])
        critical = self.group.critical_strain

        return {
            "group": self.group,
            "critical_strain": critical,
            "cumulative_strain": strain_trajectory,
            "effective_acclimatization": acclim_trajectory,
            "final_risk": risk_trajectory,
            "diagnostics": diagnostics,
            "peak_strain": float(strain_trajectory.max()),
            "caution_day": _first_day_at_or_above(strain_trajectory, 0.50 * critical),
            "danger_day": _first_day_at_or_above(strain_trajectory, 0.75 * critical),
            "emergency_day": _first_day_at_or_above(strain_trajectory, 0.90 * critical),
        }

    # ---- analytic time-to-critical (paper Sec 3.4) --------------------------
    def time_to_critical(self, current_strain: float, baseline_heat_load: float,
                         acclimatization_potential: float) -> float:
        """Approximate days to reach critical_strain under constant forcing,
        recovery neglected (paper Sec 3.4):

            t_critical ~= (critical_strain - current_strain)
                          / (baseline_heat_load * acclim_potential * suppression_strength)

        Returns inf when the denominator is non-positive (no runaway).
        """
        rate = (baseline_heat_load * acclimatization_potential
                * self.group.strain_suppression_strength)
        if rate <= 0:
            return float("inf")
        return (self.group.critical_strain - current_strain) / rate


# ============================================================================
# POPULATION LAYER: heterogeneity within a group (option B, 2026-11-23)
# ============================================================================
# Why. A single representative member makes every group an on/off switch:
# below its recovery_threshold nothing accumulates, above it the feedback
# loop runs to critical_strain within days. For Paris 2003 that gave 5 % of
# critical for 18-45 and 45-65 and 100 % for 65-85 and 85+, while the measured
# excess mortality rose gradually with age (O/E 1.1-1.2, 1.3, 1.4-1.6, 1.8-2.0;
# Fouillet et al. 2006, table 1). Softening the threshold alone does not help:
# the feedback loop turns a soft input back into a switch.
#
# What. A real group consists of people who differ in heat tolerance
# (inter-individual variation in the core-temperature response at equal heat
# production is up to 1.1-1.9 degC; Cramer & Jay 2015, PMC4628991). Each group
# is therefore simulated as an ensemble of members. Member i has one
# resilience factor f_i that multiplies the three protective parameters
# together (capacity, recovery_threshold, base_recovery_rate), so that they
# keep moving together, as the group table requires. f is lognormal with
# median 1 and coefficient of variation POPULATION_HETEROGENEITY_CV; the
# members sit on the mid-quantiles of that distribution (deterministic, no
# random numbers). Capacity is capped at MEMBER_CAPACITY_CAP.
#
# Output. The group trajectory is the ensemble MEAN of the member strains;
# the zone days are read from that mean, as before. In addition the fraction
# of members in the emergency zone (>= 90 % of critical) is returned per day.
# The median member (f = 1) is exactly the group as tabulated; PyroxModel
# itself is unchanged and still describes that typical member (verify.py,
# regime and tipping-point analyses).
#
# Test. Pre-registered in toetsplan_pyrox_leeftijdsgradient_2026-11-23.md
# (age gradient of Paris 2003); result in TECHNICAL_REFERENCE.md.

POPULATION_HETEROGENEITY_CV: float = 0.30
POPULATION_ENSEMBLE_SIZE: int = 41
MEMBER_CAPACITY_CAP: float = 0.95


def resilience_multipliers(cv: float = POPULATION_HETEROGENEITY_CV,
                           n: int = POPULATION_ENSEMBLE_SIZE) -> np.ndarray:
    """Resilience factors f_i on the n mid-quantiles of a lognormal
    distribution with median 1 and coefficient of variation cv.
    cv = 0 (or n = 1) gives the single typical member [1.0]."""
    from statistics import NormalDist
    if cv <= 0 or n <= 1:
        return np.array([1.0])
    sd = float(np.sqrt(np.log(1.0 + cv * cv)))
    z = np.array([NormalDist().inv_cdf((i + 0.5) / n) for i in range(n)])
    return np.exp(sd * z)


def member_group(group: GroupParameters, factor: float) -> GroupParameters:
    """The group as one member with resilience factor `factor` (1 = typical)."""
    from dataclasses import replace
    if factor == 1.0:
        return group
    return replace(
        group,
        max_acclimatization_capacity=min(MEMBER_CAPACITY_CAP,
                                         group.max_acclimatization_capacity * factor),
        recovery_threshold=group.recovery_threshold * factor,
        base_recovery_rate=group.base_recovery_rate * factor,
    )


class PyroxPopulation:
    """
    A population group as an ensemble of members that differ in heat
    tolerance (see the block comment above). `simulate()` takes the same
    arguments as PyroxModel.simulate() and returns the same keys, where
    cumulative_strain, effective_acclimatization and final_risk are ensemble
    means, and adds:

        fraction_emergency  per state (incl. the initial one): share of members
                            at or above 90 % of critical_strain
        fraction_caution    idem, at or above 50 %
        member_peak_strain  peak strain per member (array, in member order)
        resilience_factors  the f_i used
        heterogeneity_cv    the cv used
        diagnostics         those of the typical (median) member
    """

    def __init__(self, group: GroupParameters,
                 cv: float = POPULATION_HETEROGENEITY_CV,
                 n_members: int = POPULATION_ENSEMBLE_SIZE):
        self.group = group
        self.cv = cv
        self.factors = resilience_multipliers(cv, n_members)

    def simulate(self, heat_load_series: List[float],
                 sleep_quality_series: Optional[List[float]] = None,
                 pre_heatwave_heat_load: Optional[float] = None,
                 initial_strain: float = 0.1,
                 initial_state: Optional[DailyState] = None) -> Dict:
        runs = [PyroxModel(member_group(self.group, f)).simulate(
                    heat_load_series, sleep_quality_series=sleep_quality_series,
                    pre_heatwave_heat_load=pre_heatwave_heat_load,
                    initial_strain=initial_strain, initial_state=initial_state)
                for f in self.factors]
        strain = np.array([r["cumulative_strain"] for r in runs])
        critical = self.group.critical_strain
        mean_strain = strain.mean(axis=0)
        mid = int(np.argmin(np.abs(np.log(self.factors))))
        return {
            "group": self.group,
            "critical_strain": critical,
            "cumulative_strain": mean_strain,
            "effective_acclimatization": np.mean([r["effective_acclimatization"] for r in runs], axis=0),
            "final_risk": np.mean([r["final_risk"] for r in runs], axis=0),
            "diagnostics": runs[mid]["diagnostics"],
            "peak_strain": float(mean_strain.max()),
            "caution_day": _first_day_at_or_above(mean_strain, 0.50 * critical),
            "danger_day": _first_day_at_or_above(mean_strain, 0.75 * critical),
            "emergency_day": _first_day_at_or_above(mean_strain, 0.90 * critical),
            "fraction_emergency": (strain >= 0.90 * critical).mean(axis=0),
            "fraction_caution": (strain >= 0.50 * critical).mean(axis=0),
            "member_peak_strain": strain.max(axis=1),
            "resilience_factors": self.factors.copy(),
            "heterogeneity_cv": self.cv,
        }


# ============================================================================
# STABILITY ANALYSIS HELPERS (paper Section 3, group-independent)
# ============================================================================

def feedback_gain(group: GroupParameters, baseline_heat_load: float,
                  acclimatization_potential: float) -> float:
    """Linearised strain feedback gain (paper Sec 3.2):

        gain = baseline_heat_load * acclim_potential * suppression_strength
               - HOMEOSTATIC_DRIVE_COEFFICIENT * base_recovery_rate

    Positive -> strain amplifies its own growth (destabilising);
    negative -> daily recovery dominates (stable).
    """
    destabilising = (baseline_heat_load * acclimatization_potential
                     * group.strain_suppression_strength)
    stabilising = HOMEOSTATIC_DRIVE_COEFFICIENT * group.base_recovery_rate
    return destabilising - stabilising


def equilibrium_strain(group: GroupParameters, baseline_heat_load: float,
                       acclimatization_potential: float,
                       sleep_quality: float = 1.0) -> tuple:
    """Solve for the steady-state strain where daily change is zero
    (paper Sec 3.1), by bisection on [0, critical_strain].

    [2026-09] Return type changed from `Optional[float]` to `(state, value)`.
    The old version returned None whenever daily_change(strain) had the same
    sign at both ends of [0, critical_strain] -- but that happens in two
    OPPOSITE situations that were previously indistinguishable to any
    caller: daily_change negative everywhere (strain always shrinks toward
    0 -- SAFE, no equilibrium needed because none is needed) and
    daily_change positive everywhere (strain always grows toward critical
    -- RUNAWAY, the genuinely dangerous case the old docstring's "None =
    runaway" was describing, incorrectly, for both). Confirmed numerically:
    very_elderly_85plus at baseline_heat_load=0.5 has daily_change(0)=-0.12
    and daily_change(critical)=-0.14 (safe) vs. at load=3.0,
    daily_change(0)=+1.63 and daily_change(critical)=+2.36 (runaway) -- the
    old code returned the identical `None` for both.

    Returns
    -------
    (state, value) : tuple[str, Optional[float]]
        state is one of:
          "safe"        -- daily_change < 0 throughout; strain decays to 0
                           regardless of starting point. value is None.
          "runaway"     -- daily_change > 0 throughout; strain grows to
                           critical_strain regardless of starting point
                           (no stable equilibrium exists below critical).
                           value is None.
          "equilibrium" -- an interior fixed point exists. value is that
                           strain (float). [2026-11-24] For every group
                           this root is UNSTABLE: a tipping point between
                           recovery (below) and runaway (above), not a
                           resting level. See the module docstring.
    """
    def daily_change(strain: float) -> float:
        gate = max(0.0, 1.0 - group.strain_suppression_strength * strain)
        eff_acclim = acclimatization_potential * gate
        net_input = max(0.0,
                        baseline_heat_load * (1.0 - eff_acclim) - group.recovery_threshold)
        recovery = (group.base_recovery_rate * sleep_quality
                    * (1.0 + HOMEOSTATIC_DRIVE_COEFFICIENT * strain))
        return net_input - recovery

    low, high = 0.0, group.critical_strain
    f_low, f_high = daily_change(low), daily_change(high)
    if f_low == 0:
        return ("equilibrium", low)
    if f_high == 0:
        return ("equilibrium", high)
    if np.sign(f_low) == np.sign(f_high):
        return ("safe", None) if f_low < 0 else ("runaway", None)
    for _ in range(100):
        mid = 0.5 * (low + high)
        f_mid = daily_change(mid)
        if abs(f_mid) < 1e-12:
            return ("equilibrium", mid)
        if np.sign(f_mid) == np.sign(f_low):
            low, f_low = mid, f_mid
        else:
            high, f_high = mid, f_mid
    return ("equilibrium", 0.5 * (low + high))


# ============================================================================
# small internal helpers
# ============================================================================

def _normalize_to_unit_sum(weights: np.ndarray) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    total = weights.sum()
    return weights / total if total != 0 else weights


def _first_day_at_or_above(trajectory: np.ndarray, threshold: float) -> Optional[int]:
    """Day index of the first time the trajectory reaches `threshold`, else None.
    Index 0 is the initial state; a return >= 1 is a genuine in-simulation crossing.
    """
    hits = np.where(trajectory >= threshold)[0]
    return int(hits[0]) if hits.size > 0 else None
