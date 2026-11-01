# -*- coding: utf-8 -*-
"""
HESTIA_Data_Engine_CVR.py
=========================
Heat Exposure Stress & Thermophysiology Integrated Assessment -- Data Engine
with Cardiovascular Response (CVR) integration.

This script combines two specialised simulation models:
  1. Adults  -- JOS-3 thermoregulation + CVR module + collapse risk model.
  2. Children / adolescents -- JOS-3 thermoregulation (no CVR).

The user selects the simulation mode at startup; the script then automatically
adjusts physiological parameters, activity levels (MET), and perception models.

=============================================================================
COMMON FEATURES
=============================================================================
- JOS-3 thermoregulation model (Takahashi et al. 2021, Energy & Buildings).
- Monte Carlo simulation for population-based risk analysis (default N=5000).
- Environmental modelling: Open-Meteo weather API, pvlib solar radiation,
  Urban Heat Island effect (Oke 1973).
- Vanos et al. (2023) survivability / liveability limits.

=============================================================================
ADULT MODE
=============================================================================
- Borg RPE scale (6-20), piecewise-linear psychobiological model.
- Adaptation profiles: training and heat acclimatisation affect running
  economy, sweat response, and thirst threshold.
- Ad-libitum drinking strategy.
- CVR module (Lloyd et al. 2022, J Appl Physiol):
  cardiac output, heart rate (CO/SV), CO reserve, decompensation flag.
- Collapse risk model: two-phase logistic function calibrated on observed
    Boston Marathon EHS incidence (Breslow et al. 2021, Med Sci Sports Exerc).
    DtD 2024 (50 / 35,000 participants) serves as prospective validation.

=============================================================================
CHILDREN MODE
=============================================================================
- Higher surface-to-mass ratio, lower sweat capacity, higher metabolic cost.
- OMNI RPE scale (0-10).  Blunted thirst response ("voluntary dehydration").
- Simplified fitness factor.

=============================================================================
VERSION HISTORY
=============================================================================
rev01  2025-10-28  Initial combined adult + pediatric version.
rev02  2025-10-28  Advanced RPE models. Full English translation.
rev03  2026-03     CVR module integrated (Lloyd et al. 2022).
                   cardiac_output from JOS-3 used directly as CO demand.
                   HR estimated via CO / SV (Lloyd Eq. 2).
rev04  2026-03     AdultParticipantProfile dataclass replaces anonymous tuple.
                   Fixes critical bug: vo2max and age were swapped in
                   calculate_indices_jos3_adult() due to index confusion.
                   All participant fields now accessed by name, not position.
rev05  2026-03     AVA closure indicator removed. At exercise intensity in
                   warm conditions AVA blood flow is elevated (open state),
                   never closes -- indicator had no diagnostic value.
rev06  2026-03     Collapse risk model added (two-phase logistic function):
                     Z = intercept
                         + 1.0 * max(0, T_rect - 39.5)
                         + 4.0 * max(0, T_rect - 40.5)
                         + 0.8 * max(0, 2.0 - CO_reserve)
                         + 0.5 * max(0, dehy_pct - 3.0)
                   Intercept auto-calibrated via Newton iteration to reproduce
                   observed Dam tot Damloop 2024 hospital admission rate
                   (50/35,000). [Superseded by rev11: Boston Marathon pooled
                   2012-2019 (Breslow 2021) is now the calibration reference;
                   [2026-10-17: Breslow 2021 covers 2015-2019, see correction
                   under rev11 A]
                   DtD 2024 is a prospective validation target.]
                   Calibration constants moved to module level.
                   Individual collapse probability added to Excel export.
rev07  2026-03     Debug print statements removed.
                   Stale 40.0 deg C comment block removed.
                   All Dutch inline comments and docstrings translated to
                   English. simulate_runner and calculate_indices_jos3_adult
                   docstrings updated to reflect AdultParticipantProfile.
                   _calculate_threshold_stats: Wald CI documented as known
                   limitation; Clopper-Pearson recommended for tail props.
rev08  2026-03     Line 1920-1930-Commented
                   Line 1935  intercept_kal = -9.637 This represents the
                   calibration value of the 2024 DtD run 50 incidents per
                   35000 participants.
                   [Superseded by rev11: Boston Marathon (Breslow 2021)
                   is now the calibration reference; DtD 2024 is a
                   prospective validation target; intercept_kal = -10.071.]
rev09  2026-04     Monte Carlo distribution corrections (simulate_runner,
                   simulate_child_participant, run_monte_carlo_adult):
                   1. MET loc corrected to 0.0 (was -training_factor*met*0.15).
                      Training effect now applied as separate deterministic
                      mean shift, eliminating systematic negative bias
                      (empirical mean was -0.75 MET instead of 0.0).
                   2. MET sigma widened: 0.05 -> 0.15 * met_value.
                      Captures running-economy CV (~5-8%, Barnes & Kilding
                      2015) plus pace spread across population (~7-10%).
                   3. MET upper clip added: final_met capped at
                      1.25 * met_value (symmetric with lower bound).
                   4. VO2max loc corrected 45 -> 50 mL/kg/min for
                      recreational runners self-selecting into mass events.
                      Ref: Scharhag-Rosenberger et al. (2010).
                   5. sweat_factor (adults) clipped to [0.4, 1.5].
                   6. Age sigma widened: 10 -> 12 years for better
                      representation of 55-65 age group.
                   7. Height loc corrected: 1.75 -> 1.71 m for 50/50
                      gender-mixed runner population (M~1.78, V~1.65).
                      Ref: RIVM NL data; Tolfrey & Pilcher (2013).
                   8. Weight scale widened: 10 -> 12 kg; lower clip
                      50 -> 45 kg (accommodates lighter female runners).
                   Known limitation: rejection sampling introduces <0.3
                   MET bias at training_factor=0.5 (bias +0.6 at tf=1.0);
                   scipy.truncnorm recommended for future revision.

rev12  2026-04     THREE-ENDPOINT CALIBRATION ARCHITECTURE (this revision)
                   See detailed entry below.

rev11  2026-04     BOSTON MARATHON REFERENCE CONSOLIDATION (this revision)
                   See detailed entry below.

rev10  2026-04     POPULATION ARCHITECTURE OVERHAUL
                   =================================================
                   Replaces simulate_runner() with generate_base_population(),
                   which implements a causally correct sampling order and
                   eliminates physiologically impossible parameter combinations.

                   KEY CHANGES:
                   A) Sampling order is now causally correct:
                      gender -> age -> VO2max(age,gender) -> height(gender)
                      -> weight(height,gender) -> %VO2max_at_race_pace
                      -> sweat_factor -> thirst_threshold -> perceptual vars
                      This prevents impossible combinations such as a 65-year-
                      old with VO2max=75 or a 105kg runner with VO2max=70.

                   B) MET is no longer sampled as an absolute value.
                      Instead, pct_vo2max (dimensionless, [0.60, 0.92]) is
                      sampled and stored in the population DataFrame.
                      The actual MET for each scenario is computed on-the-fly
                      in calculate_indices_jos3_adult() as:
                        final_met = vo2max * pct_vo2max / VO2MAX_TO_MET_FACTOR
                      This makes it impossible to exceed 100% VO2max by
                      construction (was ~18.7% of population in rev09).

                   C) VO2max is conditioned on age and gender:
                      - Gender effect: females ~10% lower (Cohen's d ~0.8).
                        Ref: Scharhag-Rosenberger et al. (2010).
                      - Age effect: -0.5 mL/kg/min per year after age 35.
                        Ref: Tanaka et al. (2001) J Am Coll Cardiol 37:153.
                      This replaces the flat N(50,10) distribution.

                   D) Fixed seed support: generate_base_population() accepts
                      a random_seed parameter. Using the same seed always
                      produces the same population, making scenario comparisons
                      (e.g. MET 8.3 vs 11.8, DtD 2024 vs 2025) fully
                      reproducible and scientifically valid.

                   E) Population persistence: the generated population can be
                      saved to / loaded from a .pkl file, so it need not be
                      regenerated for each simulation run. This eliminates the
                      rejection-sampling bias noted in rev09 and reduces
                      run-to-run stochastic variance in scenario comparisons.

                   F) NEW: validate_population() function checks:
                      1. Marginal distributions vs. empirical references
                         (Scharhag-Rosenberger 2010, Tanda & Knechtle 2013,
                          RunRepeat European marathon statistics 2023).
                      2. Correlation matrix vs. physiologically expected values
                         (VO2max-age: r~-0.40; VO2max-gender: Cohen's d~0.80).
                      3. Implied finish-time distribution vs. Amsterdam/
                         Rotterdam marathon results using Daniels & Gilbert
                         (1979) VO2max-performance formula. If the simulated
                         median finish time falls outside [3h30m, 4h30m] for
                         a recreational marathon field, a warning is issued.

                   G) AdultParticipantProfile dataclass extended:
                      - pct_vo2max field added (replaces met_variation).
                      - met_variation field REMOVED to prevent accidental use.
                      NOTE: met_variation in the stored DataFrame column is
                      retained as a computed diagnostic only (never sampled).

                   BACKWARD COMPATIBILITY:
                   - run_monte_carlo_adult() now accepts an optional
                     base_population argument (DataFrame from
                     generate_base_population()). If None, a fresh population
                     is generated. Existing call sites are unchanged.
                   - All downstream code (CVR, collapse risk, Excel export)
                     is unchanged; only the population generation pathway
                     and the MET computation in calculate_indices_jos3_adult
                     are affected.

                   KNOWN REMAINING ISSUES (addressed in rev11):
                   - training_offset duplication: see rev11 notes below.
                   - intercept_kal calibration source: see rev11 notes below.
                   - scipy.truncnorm not yet used for pct_vo2max; simple
                     np.clip is applied. Tail behavior acceptable for
                     recreational marathon population (deferred to rev12).

=============================================================================
rev11  2026-04     BOSTON MARATHON REFERENCE CONSOLIDATION
=============================================================================
                   This revision makes the Boston Marathon the single
                   authoritative calibration reference for the collapse risk
                   model, resolves the training_factor double-correction
                   ambiguity, cleans up BMI filter logic, and adds population
                   file version-safety.

                   A) CALIBRATION SOURCE -- Boston Marathon (Breslow 2021)
                   ---------------------------------------------------------
                   Previous revisions mixed DtD 2024 and Boston 2017 data
                   in different parts of the code, creating inconsistency.
                   Rev11 consolidates on the Boston Marathon as the primary
                   reference because it is the best-documented mass running
                   event in the peer-reviewed literature for EHS incidence.

                   [2026-10-17 CORRECTION] The reference and numbers in this
                   block are wrong. The real paper is Breslow et al. (2021)
                   Med Sci Sports Exerc 53(9):1818-1825 (doi:10.1249/MSS.
                   0000000000002652): Boston 2015-2019 (5 editions), 50 EHS
                   in 136,161 starters = 3.7/10,000; no 2012 data. "Am J
                   Sports Med 49(10):2696-2703" does not exist (Crossref).
                   The 9.0/10,000 has no source. Target now 4.5/10,000
                   (author's choice) -- see COLLAPSE_ENDPOINTS['ehs'].
                   Reference: Breslow RG et al. (2021) Am J Sports Med 49(10).
                   Dataset: Boston Marathon 2012--2019 (8 editions).
                   Observed EHS rate: approximately 9.0 per 10,000 finishers
                   (pooled across 8 editions, varying by year and temperature).
                   Conservative reference year chosen: 2017 (cool conditions,
                   low incidence) gives a lower-bound intercept; 2012 (warm
                   conditions) gives an upper bound.

                   Calibration anchor used here (rev11):
                     N_OBS_COLLAPSE_ADMISSIONS = 9.0   (per 10,000; pooled)
                     N_OBS_PARTICIPANTS        = 10_000
                     P_OBS_COLLAPSE            = 9.0 / 10_000 = 0.00090

                   intercept_kal recalibrated to: -10.071
                   (Newton iteration, see MODULE_CALIBRATION_NOTES below)

                   All DtD 2024 references in module-level comments have been
                   updated. DtD 2024 (50 / 35,000 = 0.00143) will serve as a
                   prospective validation point once the training_offset
                   calibration is settled (clinical data needed).

                   B) TRAINING_FACTOR DOUBLE-CORRECTION -- RESOLVED
                   -------------------------------------------------
                   Rev10 applied training_factor in two places:
                     1. generate_base_population(): mu of pct_vo2max shifted
                        down by training_factor * 0.08 (population sampling).
                     2. calculate_indices_jos3_adult(): MET further reduced by
                        training_factor * base_met * 0.15 (economy offset).

                   This caused a compounded reduction in effective %VO2max for
                   trained runners. Quantified effect at tf=1.0:
                     Step 1 alone: mu_pct = 0.80 - 0.08 = 0.72 VO2max
                     Step 2 alone: MET *= (1 - 0.15) -> effective pct = 0.72
                     Combined:     effective pct = 0.72 * 0.85 = 0.61 VO2max

                   At 0.61 VO2max for a tf=1.0 runner the simulated effort is
                   physiologically inconsistent with a competitive marathon
                   pace (literature: elite runners sustain ~85-90% VO2max).

                   RESOLUTION (rev11):
                   The step-2 training_offset in calculate_indices_jos3_adult
                   is RETAINED but its coefficient is reduced from 0.15 to
                   0.05, limiting the economy correction to a 5% MET reduction
                   at tf=1.0. This gives:
                     tf=0.0: effective pct = mu(0.80) * 1.00 = 0.80
                     tf=0.5: effective pct = mu(0.76) * 0.975 = 0.74
                     tf=1.0: effective pct = mu(0.72) * 0.95  = 0.68

                   These values are physiologically defensible for a
                   recreational mass-event population. Clinical calibration
                   from clinical data remains needed for precise coefficient values.
                   The coefficient value (0.05) and its rationale are now
                   explicitly documented at the point of use.

                   C) BMI FILTER LOGIC -- CLARIFIED
                   ----------------------------------
                   In rev10, bmi_target was sampled and then clipped to
                   [18,32] before weight was computed. The subsequent hard
                   rejection `if not (18 <= bmi <= 32): continue` could only
                   be triggered by the weight clip (45--105 kg), not by
                   bmi_target itself. This was a silent logic inconsistency.

                   Rev11: the hard BMI rejection is kept (it correctly catches
                   weight-clip distortions) but is now explicitly commented to
                   explain which path triggers it. The bmi_target clip range
                   is unchanged.

                   D) POPULATION FILE VERSION SAFETY
                   -----------------------------------
                   save_population() now saves a dict with keys:
                     'hestia_version': 'rev11'
                     'population':     list of AdultParticipantProfile
                   load_population() checks the version key and warns if the
                   file was created by a different revision. Backward-
                   compatible: files without a version key are loaded with a
                   deprecation warning.

                   E) MODULE-LEVEL DOCUMENTATION CONSISTENCY
                   ------------------------------------------
                   All references to DtD 2024 as the *calibration* source
                   have been replaced by Boston Marathon (Breslow 2021).
                   DtD 2024 is now correctly described as a *validation* target.
                   The module docstring, collapse-risk comments, and the main()
                   startup banner are updated to reflect rev11.

                   KNOWN REMAINING ISSUES (to be addressed in rev12):
                   - training_offset coefficient (0.05) requires clinical
                     calibration. Radboudumc clinical data needed.
                   - intercept_kal = -10.071 requires recalibration against
                     DtD 2024 after training_offset is clinically settled.
                   - scipy.truncnorm not yet used for pct_vo2max (np.clip
                     remains; tail bias <0.3 pct-point, acceptable for now).

MODULE_CALIBRATION_NOTES (rev11)
=================================
Boston Marathon pooled EHS rate: 9.0 / 10,000 = 0.00090 (Breslow 2021).
[2026-10-17] Wrong -- Breslow 2021 reports 3.7/10,000 (2015-2019); target is
now 4.5/10,000, see COLLAPSE_ENDPOINTS['ehs'].
Collapse risk model:
  Z = intercept_kal
      + 1.0 * max(0, T_rect - 39.5)
      + 4.0 * max(0, T_rect - 40.5)
      + 0.8 * max(0, 2.0 - CO_reserve)
      + 0.5 * max(0, dehy_pct - 3.0)

For a population running under Boston-typical conditions (T_rect ~38.8 mean,
CO_reserve ~2.5 mean, dehy ~2% mean), the dominant term is the intercept.
Newton iteration was run offline to find intercept_kal such that the mean
p_collapse across a standard N=5000 population equals 0.00090.
Result: intercept_kal = -10.071

=============================================================================
rev12  2026-04     THREE-ENDPOINT CALIBRATION ARCHITECTURE
=============================================================================
                   A) ENDPOINT MISMATCH RESOLVED
                   --------------------------------
                   Rev11 calibrated the collapse model against the Boston EHS
                   rate (9/10,000, Breslow 2021). But the collapse model
                   measures a COMPOSITE endpoint that is broader than
                   clinical EHS:
                     - the T_rect > 39.5 degC term also catches sub-clinical
                       cases
                     - the CO_reserve term adds cardiovascular collapse that
                       is independent of core temperature
                     - the dehydration term catches incidents without
                       hyperthermia

                   The composite endpoint is therefore closer to "all
                   heat-related medical incidents" than to "EHS alone".
                   EHS is empirically ~10-20% of all heat incidents at
                   marathons (Ronneberg et al. 2021, Br J Sports Med).
                   [2026-10-17: reference NOT verified -- not found in a
                   literature search; no number in the code depends on it.]

                   B) THREE-TIER INTERCEPT TABLE
                   --------------------------------
                   Rev12 introduces COLLAPSE_ENDPOINTS: a table of three
                   calibrated intercepts, each for a different endpoint.
                   The active intercept is chosen via ACTIVE_ENDPOINT.

                   Endpoint 1 -- EHS (clinical)
                     Definition : T_rect >= 40.0 degC + CNS dysfunction
                     Source     : Breslow RG et al. (2021) Am J Sports Med
                                  Boston Marathon 2012-2019, pooled
                     P_obs      : 9.0 / 10,000 = 0.00090
                     [2026-10-17] Corrected: Med Sci Sports Exerc 53(9):
                     1818-1825, 2015-2019, 3.7/10,000; target 4.5/10,000.
                     intercept  : -10.071  (Newton, JOS-3 calibrated, rev11)

                   Endpoint 2 -- Hospital admission
                     Definition : Medical admission after the race (EHS +
                                  severe exhaustion + cardiovascular incidents)
                     Source     : GHOR Noord-Holland Noord, DtD 2024
                                  50 admissions / 35,000 participants
                     P_obs      : 50 / 35,000 = 0.00143 (14.3 / 10,000)
                     intercept  : -9.569  (see INTERCEPT_DERIVATION_NOTES rev12)
                     Status     : PROVISIONAL -- requires recalibration after
                                  clinical validation of training_offset (Radboudumc)

                   Endpoint 3 -- First-aid contact (all incidents)
                     Definition : Any contact with on-site medical staff,
                                  including mild hyperthermia, exhaustion,
                                  cramps, hyponatremia
                     Source     : Estimate based on DtD 2024 data provided by
                                  GHOR NHN and Le Champion; assumes ~3x hospital admission
                     P_obs      : ~150 / 35,000 = 0.00429 (42.9 / 10,000)
                     intercept  : -8.364  (see INTERCEPT_DERIVATION_NOTES rev12)
                     Status     : PROVISIONAL -- wide uncertainty on P_obs
                                  (sensitivity analysis: range -7.40 to -8.40
                                  for 100-250 first-aid contacts / 35,000)

                   C) INTERCEPT_DERIVATION_NOTES (rev12)
                   ----------------------------------------
                   The intercepts for endpoints 2 and 3 were derived via
                   Newton iteration on the analytical population
                   distributions (N=50,000, see intercept_estimation.py).
                   The analytical approximation gives T_rect P50 ~39.1 degC,
                   whereas JOS-3 gives P50 ~38.5 degC under moderate heat.
                   This introduces a systematic shift of ~1.9 units in
                   the intercept.

                   Correction procedure:
                     analytical_intercept(EP1) = -8.160
                     JOS3_intercept(EP1)       = -10.071  (rev11, validated)
                     correction                = -10.071 - (-8.160) = -1.911

                   Corrected intercepts:
                     EP2 (hospital admission): -7.657 + (-1.911) = -9.568 ~= -9.569
                     EP3 (first-aid contact):  -6.453 + (-1.911) = -8.364 ~= -8.364
                     EP3 sensitivity range:    -8.81 to -7.81

                   VALIDATION STATUS:
                     EP1: calibrated on Boston (Breslow 2021) -- a calibration
                          target, not an independent validation
                     EP2: provisional -- DtD 2024 is the validation target
                          once training_offset is clinically calibrated (Radboudumc)
                     EP3: provisional -- P_obs from DtD 2024 data provided by GHOR NHN and Le Champion
                          (to be requested from GHOR NHN)

                   D) ACTIVE_ENDPOINT CONFIGURATION
                   ----------------------------------
                   Default active: 'ehs' (most conservative, best documented)
                   Change via the ACTIVE_ENDPOINT constant or via the
                   user prompt in main() (new prompt added).

                   E) OUTPUT LABELLING
                   --------------------
                   The stats dict and Excel export now contain:
                     'active_endpoint':       str  (name of the active endpoint)
                     'active_endpoint_p_obs': float (calibrated P_obs)
                     'active_intercept_kal':  float
                   so reports are always traceable back to the endpoint.

                   KNOWN REMAINING ISSUES (rev13):
                   - the training_offset coefficient (0.05) requires clinical
                     calibration. Radboudumc clinical data needed.
                   - EP2 and EP3 intercepts require recalibration via direct
                     JOS-3 Newton iteration (instead of the analytical
                     correction) once DtD first-aid counts are available.
                   - causal conditioning of pct_vo2max on pace (rev12 analysis)
                     is planned for rev13.
                   - scipy.truncnorm for pct_vo2max (deferred, rev13).

=============================================================================
REFERENCES
=============================================================================
Takahashi Y et al. (2021) Energy & Buildings 231:110575.
Lloyd A et al. (2022) J Appl Physiol 133:247-261.
Tanaka H et al. (2001) J Am Coll Cardiol 37:153-156.
Gonzalez-Alonso J et al. (2008) J Physiol 586:45-49.
Rae DE et al. (2008) Br J Sports Med 42:849-851.
Roberts WO (1994) Med Sci Sports Exerc 26:S197.
Rae DE & Noakes TD (2002) Sports Med 32:591-601.
Buller MJ et al. (2022) PubMed 35022161.
Vanos JK et al. (2023) Nature Communications 14:3405.
Scharhag-Rosenberger F et al. (2010) J Sci Med Sport 13:167-172.
Tanda G & Knechtle B (2013) J Hum Kinet 38:169-177.
Oke TR (1973) Boundary-Layer Meteorol 7:213-220.
Joyner MJ (1991) J Appl Physiol 70:683-687.
Jones AM & Carter H (2000) Sports Med 29:373-386.
Daniels J & Gilbert J (1979) Oxygen Power. Tempe, AZ: published by authors.
Barnes KR & Kilding AE (2015) Sports Med 45:1419-1432.
Breslow RG, Collins JE, Troyanos C, Cohen MC, d'Hemecourt P, Dyer KS,
  Baggish A (2021) Med Sci Sports Exerc 53(9):1818-1825.
  doi:10.1249/MSS.0000000000002652
  [Primary calibration reference: Boston Marathon EHS 2015-2019, 50 cases in
   136,161 starters = 3.7/10,000; all cases at mean WBGT 17-20 degC.
   2026-10-17: was cited as Am J Sports Med 49(10):2696-2703, 2012-2019,
   9.0/10,000 -- that reference does not exist.]
Ronneberg K et al. (2021) Br J Sports Med 55(1):9-16.  [2026-10-17: NOT verified; not found]
  [EHS vs. all heat illness ratio at mass running events]

Author  : HESTIA project / Koos de Boer Apr-2026  (rev14)

=============================================================================
rev17  2026-05     THERMOREGULATORY CONTROL FAILURE MODULE
=============================================================================
                   Adds optional Thermoregulatory Control Failure (TCF)
                   analysis via HESTIA_ControlFailure_Module.py.

                   The new Thermal-CVR deficit dose is:
                     integral max(0, T_rect - 40.5) *
                              max(0, -CO_reserve) dt

                   Units: deg C * L/min * min = deg C * L.

                   This is explicitly an experimental mechanistic marker for
                   loss of thermoregulatory control reserve. It is not a
                   clinical EHS diagnosis and must be calibrated against event
                   medical data before conversion to EHS probability.

=============================================================================
rev16  2026-05     VULNERABLE T_RECT TAIL PLOTTING
=============================================================================
                   Adds explicit handling of the upper 2.5% T_rect tail.
                   The vulnerable cohort is defined by each participant's
                   personal peak T_rect across the whole event, not by the
                   highest values at each time point. This keeps the plotted
                   line tied to the same high-risk runners over time.

                   Adult output now includes:
                   - P97.5 and P99 T_rect reference curves in the plot.
                   - Mean trajectory of the fixed top-2.5% vulnerable cohort.
                   - Console summary of cohort size, peak cutoff, age, VO2max,
                     K_p, NSAID prevalence, CO reserve, and dehydration.
                   - Excel export flags for participants in the vulnerable
                     top-2.5% cohort.

=============================================================================
rev15  2026-05     CALIBRATION UNCERTAINTY BANDS
=============================================================================
                   PROBLEM (rev14 and earlier):
                   Percentage outputs such as pct_decompensation,
                   pct_roberts_kritiek, pct_ehs_postfinish, and
                   pct_kp_onder_002 were reported as single point estimates.
                   The existing Wald CI in _calculate_threshold_stats covers
                   only Monte Carlo sampling variance (~±0.5 pct-point at
                   N=5000) and conveys a false sense of precision: the
                   dominant uncertainty is calibration transfer, not N.

                   Specifically:
                   1. intercept_kal was derived via Newton iteration on a
                      single reference dataset (Boston Marathon pooled,
                      Breslow 2021). The transfer to DtD conditions
                      introduces a systematic uncertainty estimated at ±0.5
                      in log-odds units (conservative; based on between-event
                      EHS rate variation in the literature).
                   2. The Z-function coefficients (W_T1=1.0, W_T2=4.0,
                      W_C=0.8, W_D=0.5) are expert judgement values, not
                      regression estimates. No confidence interval exists for
                      these parameters pending Radboudumc clinical
                      calibration data.

                   SOLUTION (rev15):
                   A) _intercept_sensitivity(z_zonder_intercept, n_sim,
                      intercept_nominal, delta=0.5) computes each key
                      percentage at intercept_kal ± delta (default ±0.5).
                      This gives a calibration uncertainty band that
                      dominates the Wald MC-band at all realistic N.

                   B) _format_pct_with_band(value, lo, hi) formats output as
                      "X.X% (~Y.Y–Z.Z%)" where the tilde signals that the
                      band reflects model calibration uncertainty, not a
                      classical 95% CI.

                   C) GHOR-output (print statements in main()) is updated for
                      pct_decompensation, pct_roberts_kritiek,
                      pct_ehs_postfinish, pct_kp_onder_002, and
                      p_collapse_mean to use _format_pct_with_band().
                      The Wald MC-CI from _calculate_threshold_stats is
                      retained unchanged (it is scientifically correct for
                      its purpose -- temperature threshold statistics).

                   D) stats dict is extended with sensitivity band fields:
                      'pct_decompensation_lo', 'pct_decompensation_hi'
                      'pct_roberts_kritiek_lo', 'pct_roberts_kritiek_hi'
                      'pct_ehs_postfinish_lo', 'pct_ehs_postfinish_hi'
                      'p_collapse_mean_lo', 'p_collapse_mean_hi'
                      These are available for downstream reporting and Excel
                      export without requiring a re-run.

                   EPISTEMOLOGICAL NOTE (for GHOR and clinical reports):
                   The band "~Y–Z%" does NOT imply a 95% CI.  It means:
                   "if the calibration intercept shifts by ±0.5 log-odds
                   (a plausible range given the Boston→DtD transfer), the
                   model output moves between Y% and Z%."  The clinical
                   clinical dataset will reduce this band by constraining the
                   Z-function coefficients directly.

=============================================================================
rev14  2026-04     THREE OPERATIONAL RELIABILITY IMPROVEMENTS
=============================================================================
                   Addresses the three structural reliability risks identified
                   in the GHOR-readiness analysis (Apr-2026):

                   A) K_p AS POPULATION VARIABLE  [reliability risk 3]
                   ---------------------------------------------------
                   PROBLEM (rev13 and earlier):
                   The pacing gain K_P_PACING = 0.10 MET/°C was a fixed
                   constant identical for all participants. The interoception
                   literature (Flouris 2024) shows that ~5-10% of endurance
                   athletes have near-zero pacing response to thermal overload
                   due to low interoceptive awareness and/or high motivation.
                   These participants continue at race pace while T_rect
                   escalates -- they are the highest EHS risk group but were
                   indistinguishable from the average population in rev13.
                   Additionally, NSAID use (~25% prevalence in recreational
                   runners) further reduces effective K_p via PGE2 suppression
                   in the brain (Garcia et al. 2019).
                   [2026-10-16] Withdrawn: K_P_NSAID_FACTOR = 1.0 (no thermal
                   effect); mechanism not supported in humans.

                   SOLUTION (rev14):
                   kp_pacing is now a per-participant field in
                   AdultParticipantProfile, sampled from:
                     kp_base ~ N(0.10, 0.04), clipped [0.00, 0.25]
                   NSAID modifier applied to 25% of population:
                     kp_pacing = kp_base * K_P_NSAID_FACTOR  (1.0 since 2026-10-16)
                   nsaid_gebruik (bool) stored in profile for export.
                   kp_pacing replaces the module constant K_P_PACING in
                   calculate_indices_jos3_adult().
                   The K_P_PACING constant is retained as the population
                   mean reference for documentation purposes.

                   CONSEQUENCE: intercept_kal must be recalibrated after
                   this change (K_p distribution shifts T_rect P95 upward
                   for the low-K_p subpopulation). Recommended reference
                   conditions: tdb 22->26 deg C (activates W_T2 term better).

                   References:
                   Flouris AD et al. (2024) [interoception and EHS]
                   Garcia CK et al. (2019) FASEB J [IBU and EHS in mice]
                   Nieman DC et al. (2006) Brain Behav Immun [IBU endotoxemia]

                   B) AUC_KLINISCH (ROBERTS THRESHOLD)  [reliability risk 1]
                   -----------------------------------------------------------
                   PROBLEM (rev13):
                   AUC_thermisch used a 39.0 deg C integration floor.
                   Roberts (Sports Medicine 2007) defines the clinical
                   intervention target as keeping the area under the
                   temperature-time curve above 40.5 deg C below 60
                   degree-minutes. The 39.0 deg C AUC is not a validated
                   clinical metric.

                   SOLUTION (rev14):
                   A second AUC accumulator is added:
                     AUC_klinisch += max(0, T_rect - 40.5) * dt_min
                   Clinical threshold: AUC_klinisch > 60 deg-min (Roberts)
                   Both AUCs are stored in results and exported.
                   GHOR output now includes:
                     - auc_klinisch_p95 (population P95)
                     - pct_roberts_kritiek (% with AUC_klinisch > 60)

                   Reference:
                   Roberts WO (2007) Sports Med 37(4-5):309-312.

                   C) POST-FINISH MODULE  [reliability risk 2]
                   -------------------------------------------
                   PROBLEM (rev13 and earlier):
                   Simulation stopped at the finish line. Clinical and
                   epidemiological evidence shows that 30-40% of EHS cases
                   at mass running events occur in the finish zone, not
                   during the race (Roberts 1998; Rae et al. 2008).
                   Two mechanisms drive post-finish T_rect escalation:
                     1. Metabolic after-glow: residual heat production
                        decays exponentially (tau ~ 2 min, delta ~ 0.4 deg C)
                     2. Venous pooling: muscle pump stops, CO drops acutely,
                        cutaneous heat dissipation falls
                   The pacing controller (K_p) is no longer active post-finish.
                   This creates an open-loop instability that HESTIA did not
                   model.

                   SOLUTION (rev14):
                   simulate_post_finish() propagates T_rect and CO_reserve
                   for 10 minutes after the race ends, without pacing control.
                   Called from calculate_indices_jos3_adult() after the main
                   loop. Returns:
                     t_rect_piek_postfinish   : peak T_rect in finish zone
                     co_reserve_postfinish    : CO_reserve at finish + 10 min
                     auc_klinisch_postfinish  : additional AUC_klinisch
                     ehs_postfinish           : bool -- EHS criterion met
                     t_ehs_postfinish_min     : minutes post-finish at EHS
                   Population aggregate: pct_ehs_postfinish added to stats.
                   GHOR output includes separate finish-zone risk estimate.

                   References:
                   Roberts WO (1998) [post-finish T_rect rise]
                   Rowell LB (1974) [venous pooling post-exercise]

                   RECALIBRATION REQUIREMENT
                   --------------------------
                   All three changes shift the T_rect distribution.
                   intercept_kal is marked REQUIRES_RECALIBRATION.
                   Recommended: run intercept_estimation.py with
                   tdb_start=22, tdb_end=26 (activates W_T2 term).

"""
import requests
import pandas as pd
import warnings
from datetime import datetime, UTC, timedelta
import pytz
# OPTIONAL, defensive import -- see get_timezone() below. No cp312 wheel
# exists for timezonefinder as of this writing, which would otherwise block
# the whole module import on Streamlit Cloud (Python 3.12). The app's own
# bridge (hestia_bridge.py) monkey-patches get_timezone() to use the
# already-known IANA timezone from the geocoding step (more reliable than a
# lat/lon lookup anyway), so TimezoneFinder's actual functionality is not
# needed in that context -- only a successful import.
try:
    from timezonefinder import TimezoneFinder
except ImportError:
    TimezoneFinder = None
import pvlib
import math
from pythermalcomfort.models import JOS3
# [2026-10-16] Gradual age decrement for JOS-3 (variant C) instead of its
# step at exactly 60 y (+1.0 degC for one birthday at marathon effort).
# See jos3_leeftijd.py for sources, method and the known limitation.
import jos3_leeftijd
JOS3_AGE_GRADUAL = jos3_leeftijd.is_active()
from pythermalcomfort.models import pmv_ppd_iso as _pmv_ppd_iso
from pythermalcomfort.utilities import met_to_w_m2 as _MET_TO_W_M2


# =============================================================================
#  [2026-10-08] JOS-3 SET-POINT REPAIR (pythermalcomfort 4.6.0)
#
#  JOS3.__init__() derives its thermoregulatory set points from a steady
#  state at the operative temperature where PMV = 0 for the person's resting
#  metabolism (BMR x 1.25). For people with a low BMR per m2 (older, or tall
#  and light) that temperature lies above 30 C. pmv_ppd_iso() then returns
#  NaN (ISO 7730 applicability limit, limit_inputs=True), the solver in
#  JOS3._calculate_operative_temp_when_pmv_is_zero() falls back to a wrong
#  value, and the core set point collapses to ~35.5 C (or NaN from ~86 y).
#  The whole simulation then regulates around a core ~2 C too low.
#  Found 2026-10-08 in test runs for an older, tall, light runner profile
#  (T_rect stayed at 37.0 C during a 1:45 run). Threshold roughly 73 y for a
#  tall, light profile and ~70 y for 1.75 m / 70 kg. Population runs (age clipped 18-65) are hardly
#  affected (only tall, light 65-year-old men in a grid check).
#
#  Repair: if the core set point of the pelvis is implausible (< 36.5 C or
#  NaN), redo the same steady-state calculation with the PMV = 0 temperature
#  found by bisection with limit_inputs=False. Identical to JOS-3's own
#  procedure otherwise (verified: unchanged set points where JOS-3 was
#  already correct). Uses JOS3._run (private API) -- recheck on a
#  pythermalcomfort upgrade.
#
#  NB: the lines 'jos3_model.t_core[:] = 37.0' were a no-op (JOS3.t_core
#  returns a copy); removed from the adult engine 2026-10-19. The initial
#  state is JOS-3's own set-point state (pelvis core ~37.1-37.6 C).
# =============================================================================
JOS3_SETPOINT_MIN = 36.5   # degC -- plausibility floor for the pelvis core set point

# =============================================================================
#  [2026-10-19, night] FOUNDATION REPAIR (author's decision)
#
#  Three linked faults that partly cancelled each other (README issues 1-2):
#  1. MET was passed as JOS-3's `par`. JOS-3 computes heat production as
#     par x its own BMR (~40-45 W/m2), not par x 1 MET (58.2 W/m2), so heat
#     production during exercise was 24-33 % too low.
#  2. T_rect was the mean of the 17 JOS-3 core segments + 0.5 degC. The mean
#     includes the hand and foot cores (34-35 degC at rest) and falls far
#     below the real core during standing; the +0.5 offset partly hid fault 1.
#  3. 'jos3_model.t_core[:] = 37.0' never did anything (JOS3.t_core returns a
#     copy). Removed.
#  Repair = the pre-registered clinic variant B3 (hestia_reconstructie.py),
#  the best of the three on both data sets: pilot 18 Sept bias +0.21 degC /
#  RMSE 0.24; Thermo Clinic 11 Oct (6 runners) bias +0.05 / RMSE 0.18 degC
#  (B1, the old definition: -1.18 degC over the whole session).
#      par    = MET x 58.2 / BMR_JOS3          (JOS3_PAR_FROM_BMR)
#      T_rect = JOS-3 pelvis core, segment 4  (T_RECT_FROM_PELVIS)
#  The CVR module's core temperature (CHSI, Lloyd 2022 Eq. 22) uses the same
#  pelvis core instead of the 17-segment mean (CHSI_CORE_FROM_PELVIS): Lloyd's
#  T_core is a rectal/oesophageal core temperature, not a limb average. This
#  last part goes beyond B3 (the clinic reconstruction used the mean) and is
#  flagged as such. The starting state is JOS-3's own set-point state (pelvis
#  core ~37.1 degC).
#  Not changed: the pediatric path (simulate_child_participant), which has
#  its own RPE/OMNI scale and no validation data.
# =============================================================================
JOS3_PAR_FROM_BMR     = True
T_RECT_FROM_PELVIS    = True
CHSI_CORE_FROM_PELVIS = True
JOS3_SEG_PELVIS       = 4
# [2026-10-23] REST CORE 37.0 degC (author's decision, ThermoClinic Emmen
# 17-10). JOS-3's set points are the passive steady state of a nude person at
# PMV = 0 (models/jos3.py _reset_setpt); for the clinic runners that put the
# pelvis core at rest at 37.2-37.7 degC, against 36.8-37.0 measured (CORE) and
# rectal norms of 36.7-37.5 (men) / 36.8-37.1 (women) (Sund-Levander et al.
# 2002, Scand J Caring Sci 16:122). maak_jos3() now shifts every deep node
# (artery, vein, core, muscle, fat) AND the core set points by the same amount
# so that the pelvis core at rest is JOS3_REST_CORE_C. Shifting only the
# initial state does not work: the regulator steers back to its own set
# point (clinic test: peak +0.99 vs +1.02 degC; with the set points moved
# along +0.80). Skin nodes and skin set points are unchanged.
JOS3_REST_CORE_SHIFT  = True
JOS3_REST_CORE_C      = 37.0
DRINK_EVERY_STEP_WHEN_THIRSTY = True   # [2026-10-19] drinking bug fix, see the engine loop
RPE_FROM_CVR_HR       = True   # [2026-10-19] RPE from CVR heart rate, see calculate_adult_rpe_from_hr()
# [2026-10-19] Motivation-dependent stop limit (author's decision; DOMAIN
# CHOICE for the span). Perceived effort near the cardiovascular ceiling goes
# to RPE 19.5-20, so a fixed limit made EVERY runner who approached the
# ceiling stop before the forced slowing could act. Now the limit is
#     19.5 + RPE_STOP_MOTIVATION_SPAN x max(0, mf_score - 0.5)
# i.e. 19.5 up to mf 0.5 (as before), rising to 20.5 at mf 1: runners with
# mf_score above 0.75 never quit on effort alone and are slowed by the
# ceiling instead. (A symmetric version that LOWERED the limit to 18.5 for
# unmotivated runners was tried: 11 % stopped in Amsterdam, rejected.)
# [2026-10-20] HEART-RATE / CARDIAC-OUTPUT DYNAMICS (author's decision;
# README issue 3, plan in TECHNICAL_REFERENCE 'Planned after the clinic').
# The CVR module (Lloyd 2022) is algebraic: HR and CO_demand follow the MET
# of the same step instantly, so CO_reserve recovered almost at once when a
# runner slowed or stopped. Measured: heart-rate time constant 5.6 min
# (pilot 18 Sept) and about 3 min (Thermo Clinic 11 Oct, 6 runners) against
# 0.3-0.6 min in the model; after the main segment measured HR stayed
# 22 /min above the model. Now the MET that drives the CVR module is a
# first-order lag of the real MET:
#     MET_cv(t+dt) = MET + (MET_cv(t) - MET) * exp(-dt / tau)
# with tau = CV_TAU_RISE_MIN when the load rises and CV_TAU_FALL_MIN when it
# falls (exact discretisation, valid at 10-min race steps and 0.5-min
# post-finish steps). Start: MET_cv = PF_MET_RUST (standing at the start).
# Post-finish: MET_cv decays from its value at the finish (or RPE stop)
# towards PF_MET_RUST instead of jumping to rest. HR (and so RPE) lags too.
# The forced ceiling still compares the REAL MET with met_at_ceiling(): the
# lag is in the heart's response, not in the oxygen the muscles need.
# Both taus = 3.0 min (clinic median, 6 runners); 5.6 min (pilot) is the
# sensitivity value. Rise and fall are kept separate for when the clinic
# data allow them to be estimated apart.
CV_LAG_ENABLED   = True
CV_TAU_RISE_MIN  = 3.0
CV_TAU_FALL_MIN  = 3.0


def cv_met_lag(met_cv_prev: float, met_now: float, dt_min: float) -> float:
    """First-order lag of the MET seen by the cardiovascular module."""
    if not CV_LAG_ENABLED or met_cv_prev is None or dt_min <= 0:
        return float(met_now)
    tau = CV_TAU_RISE_MIN if met_now > met_cv_prev else CV_TAU_FALL_MIN
    return float(met_now + (met_cv_prev - met_now) * np.exp(-dt_min / max(1e-6, tau)))


# [2026-10-20] Collapse risk also counts the finish zone (author's decision).
# The two-phase logistic read the maximum T_rect and the minimum CO_reserve
# of the RACE only, so the finish-zone dynamics (after-glow, venous pooling,
# the lagged cardiac recovery of CV_LAG_ENABLED) never reached the collapse
# probability -- only the conjunctive criteria. Now both extremes are taken
# over race + post-finish window (collapse_extremes()). Used identically by
# the engine statistics and by intercept_estimation.py.
COLLAPSE_INCLUDES_POSTFINISH = True


def collapse_extremes(res: list) -> tuple:
    """(max T_rect, min CO_reserve) for the collapse logistic: race steps
    plus, when COLLAPSE_INCLUDES_POSTFINISH, the post-finish series."""
    t_vals = [r.get('t_rect') for r in res]
    c_vals = [r.get('co_reserve') for r in res]
    if COLLAPSE_INCLUDES_POSTFINISH and res:
        t_vals += list(res[-1].get('t_rect_series_postfinish') or [])
        c_vals += list(res[-1].get('co_reserve_series_postfinish') or [])
    t_arr = np.array([v for v in t_vals if v is not None], dtype=float)
    c_arr = np.array([v for v in c_vals if v is not None], dtype=float)
    t_max = float(np.nanmax(t_arr)) if t_arr.size and np.any(~np.isnan(t_arr)) else float('nan')
    c_min = float(np.nanmin(c_arr)) if c_arr.size and np.any(~np.isnan(c_arr)) else float('nan')
    return t_max, c_min


RPE_STOP_THRESHOLD       = 19.5
RPE_STOP_MOTIVATION_SPAN = 2.0


def rpe_stop_threshold(mf_score: float) -> float:
    return RPE_STOP_THRESHOLD + RPE_STOP_MOTIVATION_SPAN * max(0.0, float(mf_score) - 0.5)
MET_W_M2              = 58.2    # W/m2 per MET, as in hestia_reconstructie.py


def jos3_par(model, met: float) -> float:
    """JOS-3 activity ratio for a metabolic rate in MET."""
    if JOS3_PAR_FROM_BMR:
        return max(1.0, float(met) * MET_W_M2 / float(model.bmr))
    return float(met)


def jos3_t_rect(model) -> float:
    """Rectal temperature from a JOS-3 model."""
    tc = model.t_core
    if T_RECT_FROM_PELVIS:
        return float(tc[JOS3_SEG_PELVIS])
    return float(tc.mean()) + 0.5


def jos3_core_for_chsi(model) -> float:
    """Core temperature handed to the CVR module (CHSI)."""
    tc = model.t_core
    return float(tc[JOS3_SEG_PELVIS]) if CHSI_CORE_FROM_PELVIS else float(tc.mean())


_PMV_MODEL = None   # '7730-2025' (pythermalcomfort >= 4) of '7730-2005' (3.x)


def _pmv_onbegrensd(t, v, rh, met, clo):
    """PMV zonder ISO-domeingrens, met hetzelfde ISO 7730-model dat de
    geinstalleerde JOS-3 zelf gebruikt: pythermalcomfort 4.x rekent met
    7730-2025, 3.x kent alleen 7730-2005 (gevonden 2026-10-08 op de
    Windows-installatie van de auteur: 'PMV calculations can only be performed in
    compliance with ISO 7730-2005')."""
    global _PMV_MODEL
    kandidaten = [_PMV_MODEL] if _PMV_MODEL else ["7730-2025", "7730-2005"]
    laatste_fout = None
    for mdl in kandidaten:
        try:
            uit = _pmv_ppd_iso(t, t, v, rh, met, clo, model=mdl,
                               limit_inputs=False, round_output=False).pmv
            _PMV_MODEL = mdl
            return uit
        except ValueError as e:
            laatste_fout = e
    raise laatste_fout


def _to_bij_pmv_nul(met: float, v: float = 0.1, rh: float = 50.0, clo: float = 0.0) -> float:
    def f(t):
        return _pmv_onbegrensd(t, v, rh, met, clo)
    lo, hi = 10.0, 45.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def maak_jos3(**kwargs) -> JOS3:
    """JOS3(**kwargs) with the set-point repair described above."""
    model = JOS3(**kwargs)
    sp = float(model.cr_set_point[4])
    if not (sp >= JOS3_SETPOINT_MIN):
        met = model.bmr * 1.25 / _MET_TO_W_M2
        model.to = _to_bij_pmv_nul(met)
        model.rh, model.v, model.clo, model.par = 50, 0.1, 0, 1.25
        model.options["ava_zero"] = True
        for _ in range(10):
            model._run(dtime=60000, passive=True)
        model.cr_set_point = model.t_core
        model.sk_set_point = model.t_skin
        model.options["ava_zero"] = False
    if JOS3_REST_CORE_SHIFT:
        _shift_rest_core(model, JOS3_REST_CORE_C)
    return model


def _shift_rest_core(model, target_c: float) -> float:
    """Move the deep nodes and the core set points so that the pelvis core
    at rest equals target_c. Returns the applied shift (degC)."""
    from pythermalcomfort.jos3_functions.matrix import INDEX as _IDX
    d = float(target_c) - float(model.t_core[JOS3_SEG_PELVIS])
    deep = [i for k in ("artery", "vein", "core", "muscle", "fat")
            for i in np.atleast_1d(_IDX[k])]
    tb = model._t_body.copy()
    tb[deep] += d
    model._t_body = tb
    model.cr_set_point = np.asarray(model.cr_set_point, dtype=float) + d
    return d
from pythermalcomfort.models import utci, wbgt
from pythermalcomfort.utilities import wet_bulb_tmp
from Thermopoulos_Data_Engine import calculate_globe_vectorized, calculate_mrt_vectorized, wind_speed_at_height
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from functools import lru_cache
import multiprocessing
from multiprocessing import Pool
from tqdm import tqdm
from colorama import init, Fore, Style
import seaborn as sns
import random
import os
import pickle

try:
    from openpyxl import load_workbook
except ImportError:
    print(f"{Fore.YELLOW}Warning: 'openpyxl' is not installed. Excel export/import will not work.{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}Install it with: pip install openpyxl{Style.RESET_ALL}")

# [suite-integration] Removed stray `print("Script started")` that fired on
# every import (harmless standalone, but noisy when imported as a library by
# run_hestia.py / the suite).

# =============================================================================
#  PARTICIPANT PROFILE DATACLASS  (rev04, extended rev10)
#
#  Fields vs. rev09:
#    - met_variation  REMOVED  (was absolute MET offset; caused VO2max
#                               exceedance bug; replaced by pct_vo2max)
#    - pct_vo2max     ADDED    (dimensionless fraction [0.60, 0.92];
#                               MET is computed on-the-fly per scenario)
#
#  All other fields unchanged. No positional indexing anywhere.
# =============================================================================
from dataclasses import dataclass as _dataclass

@_dataclass
class AdultParticipantProfile:
    """
    Complete profile of a single simulated adult participant.

    Created by generate_base_population() and used by
    calculate_indices_jos3_adult(). All fields are mandatory.

    Changes vs rev09 (rev10):
    - met_variation removed; pct_vo2max added. MET is now derived as
      vo2max * pct_vo2max / VO2MAX_TO_MET_FACTOR, guaranteeing that
      %VO2max cannot exceed the sampled value by construction.
    - age field is now set during generate_base_population() (not a
      placeholder 0 that must be filled later). The age is sampled
      immediately after gender, so VO2max can be conditioned on it.
    """
    # Anthropometrics
    height:            float   # m
    weight:            float   # kg
    age:               int     # years -- sampled within generate_base_population()
    gender:            str     # 'male' | 'female'
    body_fat_pct:      float   # % body fat -- sampled per individual (was a fixed
                               # 25%/15% by sex; see generate_base_population())
    # Physiology
    vo2max:            float   # mL/kg/min -- conditioned on age and gender (rev10)
    pct_vo2max:        float   # fraction of VO2max at race pace [0.60, 0.92] (rev10)
    # Environmental perception (individual)
    temp_variation:    float   # deg C offset
    rh_variation:      float   # % RH offset
    # Behavioural parameters
    mf_score:          float   # motivational factor [0-1]
    sweat_factor:      float   # sweat rate multiplier (acclimatisation effect)
    thirst_threshold:  float   # body mass loss (%) triggering drinking
    # [rev14-A] Individual pacing gain and NSAID status
    kp_pacing:         float   # MET/°C pacing gain -- population variable (rev14)
    nsaid_gebruik:     bool    # NSAID use flag (export only; no thermal effect since 2026-10-16)
    # [2026-07] Relative wind angle (individual, unknown-direction proxy)
    wind_angle_rad:    float   # radians [0, 2*pi); see compute_relative_wind()
    # [2026-09] Per-person pace and exposure duration -- only meaningfully
    # individual when generate_base_population(sample_pace=True) was used;
    # otherwise both are filled from the single shared met_value/duration
    # for backward compatibility (every participant gets the same value,
    # matching the suite's previous behaviour exactly). Defaulted to 0.0
    # (not made mandatory) after real breakage was found in three other
    # construction sites (run_hestia.py, individual_engine.py,
    # test_cvr_freeze_fix.py) that build AdultParticipantProfile directly
    # without going through generate_base_population() at all -- none of
    # them have any notion of pace, so 0.0 there is correct, not a
    # placeholder standing in for a real value.
    pace_min_per_km:   float = 0.0   # min/km -- see sample_recreational_pace_min_per_km()
    duration_hours:    float = 0.0   # this participant's own exposure duration
    # [2026-10-06] Measured HR_max / HR_rest (0.0 = unknown -> CVR uses its
    # population equations, identical to previous behaviour). Only set by
    # the single-runner module hestia_loper.py.
    hr_max_known:      float = 0.0
    hr_rest_known:     float = 0.0


# =============================================================================
#  PHYSIOLOGICAL CONSTANTS
#
#  VO2MAX_TO_MET_FACTOR: converts VO2max (mL/kg/min) to MET.
#  1 MET = 3.5 mL/kg/min (ACSM standard).
#  This factor is the bridge between the VO2max-based population model and
#  the MET-based JOS-3 / RPE computations.
#
#  Example: VO2max=50, pct_vo2max=0.77 ->
#    final_met = 50 * 0.77 / 3.5 = 11.0 MET  (consistent with a ~11 km/h pace)
# =============================================================================
VO2MAX_TO_MET_FACTOR = 3.5   # mL/kg/min per MET (ACSM standard)

# [2026-09] Canonical version of the pace<->MET conversion -- previously
# only existed in Klimatos_ClimateShift.py, duplicated here so the
# population Monte Carlo can give each participant their own MET from
# their own sampled pace instead of one shared met_value for everyone
# (see sample_recreational_pace_min_per_km below and its use in
# generate_base_population's new sample_pace=True path).
def _acsm_met_from_pace(pace_min_per_km: float) -> float:
    """Convert a running pace [min/km] to METs via the ACSM equations.
    Running (>=8 km/h): VO2 = 0.2*speed(m/min) + 3.5. Walking (slower,
    back-of-field pace): VO2 = 0.1*speed(m/min) + 3.5. MET = VO2/3.5."""
    speed_kmh = 60.0 / pace_min_per_km
    speed_m_min = speed_kmh * 1000.0 / 60.0
    if speed_kmh >= 8.0:
        vo2 = 0.2 * speed_m_min + 3.5
    else:
        vo2 = 0.1 * speed_m_min + 3.5
    met = vo2 / 3.5
    return round(max(2.0, min(16.0, met)), 2)


# [2026-09] Real Dam tot Damloop (16.1 km) finish-time anchors researched
# this session: men avg 84-89 min (all4running.nl; runners.nl TomTom
# 2015/16 data), women avg 97-101 min (same sources), 2-hour course limit.
# Converted to pace (min/km) medians, with a lognormal spread capturing
# the field's real right skew (fast recreational tail down to a
# competitive-but-not-elite ~3.3 min/km floor; slow tail approaching but
# clipped at the 2h/16.1km=7.45 min/km course limit). This is a
# recreational-field distribution, not a true-elite one -- course-record
# paces (~2.7 min/km) are deliberately outside this sampler's range.
PACE_MEDIAN_MIN_PER_KM = {"male": 5.35, "female": 6.15}
PACE_LOGNORMAL_SIGMA = 0.18
PACE_MIN_PER_KM_FLOOR = 3.3
PACE_MIN_PER_KM_CEILING = 7.45   # 2h / 16.1km course limit

# [2026-09] The medians above were anchored at ONE specific distance (Dam
# tot Damloop, 16.1 km) -- applying them unchanged to any other event_dist_km
# would silently reuse a 16.1km pace for a 5K or a marathon, which is wrong:
# runners genuinely run slower per km as distance increases (accumulated
# fatigue), not just for longer in total. Scaled here using Riegel's
# fatigue-exponent formula (Riegel, P.S. "Athletic records and human
# endurance." American Scientist 69(3), 1981; originally Runner's World,
# 1977): T2 = T1 * (D2/D1)^1.06, which for pace (time/distance) means
# pace2 = pace1 * (D2/D1)^(1.06-1). Well-validated 5K-through-half-marathon.
# [flagged for review] For marathon-distance events specifically, Vickers &
# Vertosick's 2016 study of 2,303 recreational runners found Riegel's
# marathon predictions came in at least 10 minutes too fast for about half
# of runners -- recreational marathon slowdown is empirically larger than
# 1.06 captures. This function still uses 1.06 uniformly (no separate
# marathon-specific exponent implemented), so treat sample_pace results for
# event_dist_km well beyond half-marathon (21.1 km) with that in mind.
PACE_REFERENCE_DIST_KM = 16.1   # the distance PACE_MEDIAN_MIN_PER_KM was anchored at
RIEGEL_FATIGUE_EXPONENT = 1.06  # Riegel (1977/1981); see caveat above for marathon+

# [2026-09] Fixes a real, empirically-confirmed defect: pace and vo2max were
# previously sampled fully independently (see sample_pace's use in
# generate_base_population below), producing a measured correlation of only
# r=-0.158 between them in a 1000-person test population -- physiologically
# backwards, since real race pace is substantially determined by fitness.
# Literature grounding for the target value: a classic ACSM study (marathon
# performance, N=50 recreational male runners, Medicine & Science in Sports &
# Exercise 1981) found marathon time inversely correlated with VO2max at
# r=-0.63. Consistent with two supporting figures: VO2max is commonly cited
# as explaining ~70% of inter-individual race-performance variance (R^2=0.70
# -> r=0.84; e.g. TrainingPeaks, summarising the broader literature), and a
# recreational-marathon study (Gordon et al. 2017; race speed vs. lactate-
# threshold markers, a closer determinant of sustainable pace than VO2max
# alone) found r=0.72-0.79. -0.63 is the most direct, peer-reviewed match
# (VO2max specifically, not a related threshold measure) and is used as-is,
# not rounded up toward the stronger figures.
PACE_VO2MAX_CORRELATION = -0.63

# [2026-09] See the long citation note next to its use in
# generate_base_population() (event-specific vo2max floor). Kept as a
# module-level constant, like the other pace/fitness parameters above, so
# it is one place to revise if better duration-specific recreational data
# turns up.
SUSTAINABLE_VO2MAX_FRACTION_LONG_EVENT = 0.72

# [2026-10-14] Duration-dependent sustainable-intensity ceiling.
# -----------------------------------------------------------------------------
# PROBLEM (found reviewing the Amsterdam 2026-10-18 marathon run, n=5000,
# seed 42): with sample_pace=True the only upper bound on pct_vo2max was a
# fixed 0.95, independent of how LONG the participant runs. For a marathon
# that let 28.5% of the population run at >=85% VO2max and 13.8% at >=90%
# for 3-5 hours -- not sustainable even for elite marathoners (~80-85%),
# let alone recreational runners. pct_vo2max correlated r=-0.85 with the
# minimum CO_reserve (the strongest single driver in that run), so this one
# unrealistic tail produced most of the "76.9% decompensation risk", the
# 8.3% EHE and the 3.8x-above-target collapse rate at WBGT ~10 degC.
#
# FIX: the maximum fraction of VO2max that can be sustained for a given race
# duration follows the Daniels & Gilbert (1979) "drop-dead" curve -- the
# SAME source this module already uses for the VO2-pace relation
# (_daniels_gilbert_vo2_at_pace):
#     f(t) = 0.8 + 0.1894393*exp(-0.012778*t) + 0.2989558*exp(-0.1932605*t)
#     (t in minutes; ~0.86 at 90 min, ~0.83 at 3 h, ~0.81 at 4 h)
# This curve describes an ALL-OUT race effort of a trained runner, so it is
# used as an upper bound (ceiling), not as a target: recreational runners
# typically sit below it. A draw whose required intensity exceeds the
# ceiling is rejected and redrawn (same rejection mechanism as the existing
# >0.95 check), so the accepted vo2max/pace distributions keep a smooth shape.
# Only applied where the participant's own duration is known
# (sample_pace=True). Set USE_DURATION_INTENSITY_CEILING = False to restore
# the previous fixed-0.95 behaviour for comparison.
# [flagged for author review] Domain choice: Daniels-Gilbert as the ceiling.
USE_DURATION_INTENSITY_CEILING = True

# [2026-10-16] Pace follows ABSOLUTE fitness, not fitness relative to peers.
# -----------------------------------------------------------------------------
# PROBLEM: the pace-vo2max copula (PACE_VO2MAX_CORRELATION) used each runner's
# vo2max z-score WITHIN their own age group (vo2max_mu already includes the
# Tanaka age correction). A fit 61-year-old therefore got the same pace as an
# equally "fit-for-their-age" 31-year-old. Measured in the Amsterdam
# 2026-10-18 run: corr(age, finish time) = 0.10; 60+ were OVER-represented
# among the 2:30-3:30 finishers (2.2% vs 1.2% of the field). a Radboudumc exercise physiologist
# (Radboudumc, 2026-10-16) expects the opposite: fewer 60+ in that group.
#
# FIX: the z-score is taken against the field's overall vo2max distribution
# for that sex -- mean = base mean minus the population-average age
# correction, sd = sqrt(sigma^2 + var(age correction)) -- so an older runner
# with a lower absolute vo2max gets a slower pace, while the field's overall
# pace distribution (calibrated to real finish times) stays the same.
# Constants derived from the age distribution in generate_base_population
# (N(40, 10) clipped 18-65, correction 0.5 mL/kg/min per year after 35):
# mean 3.31, sd 3.62 mL/kg/min. Set PACE_FITNESS_ABSOLUTE = False for the
# previous (age-relative) behaviour.
PACE_FITNESS_ABSOLUTE = True
AGE_VO2_CORRECTION_MEAN = 3.31   # mL/kg/min, population mean of 0.5*max(0, age-35)
AGE_VO2_CORRECTION_SD = 3.62     # mL/kg/min, its standard deviation


def _pace_fitness_z(vo2max: float, vo2max_base_mu: float, vo2max_mu: float,
                    vo2max_sigma: float) -> float:
    """z-score that drives the pace copula (see PACE_FITNESS_ABSOLUTE)."""
    if PACE_FITNESS_ABSOLUTE:
        mu = vo2max_base_mu - AGE_VO2_CORRECTION_MEAN
        sd = float(np.sqrt(vo2max_sigma ** 2 + AGE_VO2_CORRECTION_SD ** 2))
        return (vo2max - mu) / sd
    return (vo2max - vo2max_mu) / vo2max_sigma


def sustainable_vo2max_fraction(duration_min: float) -> float:
    """Daniels & Gilbert (1979) maximum sustainable fraction of VO2max for an
    all-out effort lasting `duration_min` minutes, capped at 0.95."""
    t = max(1.0, float(duration_min))
    f = (0.8 + 0.1894393 * np.exp(-0.012778 * t)
             + 0.2989558 * np.exp(-0.1932605 * t))
    return float(min(0.95, f))


def sample_recreational_pace_min_per_km(gender: str,
                                        event_dist_km: float = PACE_REFERENCE_DIST_KM,
                                        vo2max_z: float = None,
                                        correlation: float = PACE_VO2MAX_CORRELATION) -> float:
    """Sample one recreational runner's pace [min/km] for a mass event of
    the given distance. Gender-conditioned median (see
    PACE_MEDIAN_MIN_PER_KM), Riegel-scaled to event_dist_km when it differs
    from the 16.1km anchor distance (see the module-level note above),
    lognormal spread, clipped to [PACE_MIN_PER_KM_FLOOR,
    PACE_MIN_PER_KM_CEILING]. Call generate_base_population(sample_pace=True,
    event_dist_km=...) rather than calling this directly in normal use.

    [2026-09] vo2max_z : float, optional
        This participant's own vo2max expressed as a z-score against the
        SAME normal distribution generate_base_population() drew it from
        ((vo2max - vo2max_mu) / vo2max_sigma). When given, pace is drawn
        via a Gaussian copula correlated with it at `correlation` (default
        PACE_VO2MAX_CORRELATION, see that constant's literature note) --
        pace's own marginal distribution (the lognormal above) is
        UNCHANGED by this; only which pace value a given person's vo2max
        tends to pair with shifts. When None (the default, and the only
        behaviour before this parameter existed), pace is independent of
        fitness, as before -- kept for any caller that ssamples pace
        without already knowing a vo2max z-score.
    """
    base_median = PACE_MEDIAN_MIN_PER_KM.get(gender, PACE_MEDIAN_MIN_PER_KM["male"])
    scale = (event_dist_km / PACE_REFERENCE_DIST_KM) ** (RIEGEL_FATIGUE_EXPONENT - 1.0)
    median = base_median * scale
    if vo2max_z is None:
        pace = float(np.random.lognormal(mean=np.log(median), sigma=PACE_LOGNORMAL_SIGMA))
    else:
        # Standard bivariate-normal construction: z_pace has the target
        # correlation with vo2max_z by construction (independent of the
        # marginal distribution of either variable), then pace is
        # recovered through its own lognormal marginal (exp of a normal
        # with the same mean/sigma the independent branch above uses) --
        # this is exactly a Gaussian copula, without needing scipy's
        # norm.cdf/ppf: for two variables that are each (log-)normal, the
        # correlated z-score IS the copula step.
        rho = float(np.clip(correlation, -0.999, 0.999))
        z_pace = rho * vo2max_z + np.sqrt(1.0 - rho**2) * np.random.normal()
        pace = float(np.exp(np.log(median) + PACE_LOGNORMAL_SIGMA * z_pace))
    return float(np.clip(pace, PACE_MIN_PER_KM_FLOOR, PACE_MIN_PER_KM_CEILING))


# =============================================================================
#  CVR MODULE IMPORTS
# =============================================================================
try:
    from HESTIA_CVR_Module_v2 import (
        RunnerProfile, JOS3Outputs,
        link_cvr_to_jos3, CVRModel,   # [fix] CVRModel needed for live in-loop
                                          # cardiovascular pacing (see below)
    )
    from HESTIA_CVR_Console import (
        print_cvr_population_summary,
        print_cvr_time_series,
        print_cvr_comparison,
        calculate_cvr_risk_score,
    )
    CVR_AVAILABLE = True
    print(f"{Fore.GREEN}CVR module loaded (Lloyd et al. 2022).{Style.RESET_ALL}")
except ImportError as _cvr_err:
    CVR_AVAILABLE = False
    print(f"{Fore.YELLOW}CVR module not found ({_cvr_err}). "
          f"Simulation runs without cardiovascular analysis.{Style.RESET_ALL}")


# =============================================================================
#  THERMOREGULATORY CONTROL FAILURE MODULE IMPORTS  (rev17)
# =============================================================================
try:
    from HESTIA_ControlFailure_Module import (
        DEFAULT_CONFIG as TCF_CONFIG,
        analyse_population as analyse_control_failure_population,
        control_failure_increment,
        format_population_summary as format_control_failure_summary,
    )
    TCF_AVAILABLE = True
    print(f"{Fore.GREEN}Thermoregulatory Control Failure module loaded "
          f"(experimental mechanistic metric).{Style.RESET_ALL}")
except ImportError as _tcf_err:
    TCF_AVAILABLE = False
    print(f"{Fore.YELLOW}Control Failure module not found ({_tcf_err}). "
          f"TCF analysis is not available.{Style.RESET_ALL}")


# =============================================================================
#  COLLAPSE RISK CALIBRATION CONSTANTS  (rev12 -- THREE-ENDPOINT ARCHITECTURE)
#
#  Rev12 introduces a calibration table with three outcome endpoints.
#  Each endpoint has its own intercept_kal, P_obs, and documentation.
#  The active endpoint is selected via ACTIVE_ENDPOINT (default: 'ehs').
#
#  See full derivation in MODULE_CALIBRATION_NOTES / INTERCEPT_DERIVATION_NOTES
#  in the module docstring above.
#
#  ENDPOINT DEFINITIONS
#  --------------------
#  'ehs'          : Clinical EHS (T_rect >= 40°C + CNS dysfunction)
#                   Source: Breslow et al. 2021, Med Sci Sports Exerc 53(9):
#                   1818-1825, Boston Marathon 2015-2019 (3.7/10,000 pooled)
#                   Target: 4.5/10,000, author's choice (2026-10-17)
#                   Status: PROVISIONAL
#
#  'hospitalisation': Hospital admission after event (EHS + severe exhaustion
#                   + cardiovascular incidents requiring overnight care)
#                   Source: GHOR Noord-Holland Noord, DtD 2024
#                   Status: PROVISIONAL -- pending clinical calibration
#
#  'first_aid'         : Any on-site medical contact (incl. mild hyperthermia,
#                   exhaustion, cramps, hyponatraemia)
#                   Source: Estimated from DtD 2024 data provided by GHOR Noord-Holland Noord and Le Champion
#                   P_obs range: 100-250/35.000; central estimate 150/35.000
#                   Status: PROVISIONAL -- P_obs requires GHOR NHN data
#
#  INTERCEPT DERIVATION SUMMARY
#  -----------------------------
#  Analytical Newton iteration (N=50.000, intercept_estimation.py):
#    EP1 analytic:  -8.160  ->  JOS-3 corrected: -10.071  (delta = -1.911)
#    EP2 analytic:  -7.657  ->  JOS-3 corrected:  -9.568
#    EP3 analytic:  -6.453  ->  JOS-3 corrected:  -8.364
#  JOS-3 correction applied uniformly (T_rect offset between analytic
#  approximation and JOS-3 output at moderate heat: ~1.9 units).
# =============================================================================

COLLAPSE_ENDPOINTS = {
    'ehs': {
        'label':        'Model risk calibrated on clinical EHS (Boston Marathon, Breslow 2021)',
        # [2026-10-17] Author's choice 4.5/10,000 (was 9.0/10,000, which had no
        # source). Breslow 2021: 50 EHS / 136,161 starters = 3.7/10,000 pooled
        # over 2015-2019 (95% CI 2.7-4.8); all cases at mean WBGT 17-20 degC.
        # The reference scenario is ONE warm edition (2017), so the rate under
        # those conditions is above the pooled mean: ~6/10,000 if all cases
        # fell in 3 of 5 editions (95% CI 4.5-8.1). 4.5 lies between both.
        # Replace by the 2017 rate when the per-year table is available.
        'p_obs':        4.5 / 10_000,           # 0.00045
        'n_obs':        4.5,
        'n_participants': 10_000,
        'intercept_kal': -9.130380,  # [2026-11-01] heat acclimation in JOS-3 sweating + plasma volume; N=5000 seed 42 (was -9.567524)
                                       # [2026-10-31]: -9.567524; Liljegren globe + RH_urban; mean of seeds 42/43 (was -8.892508)
                                       # [2026-10-23]: -8.892508; rest core 37.0 + fitness/heat age curve; N=5000 seed 42 (was -9.210416)
                                       # [2026-10-20 evening]: -9.210416; JOS-3 finish zone (5 min walk + 5 min standing), no standing deficit; N=5000 seed 42 (was -9.428980)
                                       # [2026-10-20] + heart lag, collapse extremes over race + finish zone; N=5000 seed 42: -9.428980 (was -9.151532)
                                       # [2026-10-16 late] K_P_NSAID_FACTOR=1.0, N=5000 seed 42: -8.795967; was -8.790142 (N=1000)
                                       # [2026-10-16] with gradual JOS-3 age decrement (jos3_leeftijd), N=1000 seed 42: -8.790142; was -8.809350
                                       # [2026-10-15] control run, final code, N=1000 seed 42 (2026-10-14: -8.808083;
                                       # seeds 43/44: -8.778/-8.784). [2026-10-14] re-calibrated N=1000, seed=42 (was -8.803572,
                                       # 2026-07-27, N=200) -- see the 2026-10-14 note at the end
        'source':       "Breslow RG, Collins JE, Troyanos C, Cohen MC, d'Hemecourt P, Dyer KS, Baggish A (2021) Med Sci Sports Exerc 53(9):1818-1825, doi:10.1249/MSS.0000000000002652",
        'status':       'PROVISIONAL',   # [2026-07] see note -- needs production-scale reconfirmation
        'notes':        ('[2026-10-17] Target 4.5/10,000 (author\'s choice); Breslow 2021 '
                         'reports 3.7/10,000 for Boston 2015-2019. Earlier text below says '
                         '"2012-2019 pooled" and 9/10,000: both wrong, kept for history. '
                         'Boston Marathon 2012-2019 pooled. Clinical EHS: '
                         'T_rect >= 40 degC + CNS dysfunction. Narrowest endpoint. '
                         '[2026-07] Recalibrated after rebuilding HESTIA_CVR_Module_v2.py '
                         'to implement Lloyd et al. (2022) Eq. 12-31 (workload response + '
                         'Cardiac Heat Strain Index) directly, instead of reading JOS-3\'s '
                         'own cardiac_output -- which was shown, by direct test, to overstate '
                         'the heat-driven CO increase during exercise by roughly 5-25x '
                         'relative to the measured literature this project cites (Lloyd 2022 '
                         'Fig. 2D: -3% to +15% during exercise in heat; JOS-3 own '
                         'cardiac_output: +80% at fixed MET, tdb 20->38 degC). See '
                         'HESTIA_CVR_Module_v2.py compute_step() docstring and '
                         'CHANGELOG.md for the full trace, including two '
                         'same-day dead ends (intensity-dependent a-vO2diff; a MET-only '
                         'VO2 calculation that silently discarded the heat-driven CO signal) '
                         'that were tried, diagnosed as wrong, and reverted before this fix. '
                         '[2026-07, second recalibration] Further updated after adding the '
                         'runner\'s own self-generated relative wind (compute_relative_wind(), '
                         'law-of-cosines apparent-wind, individual angle sampled Uniform[0,2pi) '
                         'per participant since wind direction and course heading are not '
                         'tracked anywhere in this pipeline). This resolved most of a large '
                         'Falmouth-2003-vs-2015 asymmetry: ambient wind alone had made 2015 '
                         '(calm) 35x more severe than 2003 (windy) in this model, versus a '
                         'documented ~1.7x difference in the opposite direction; with the '
                         'runner\'s own speed included, the model\'s 2015-vs-2003 gap narrowed '
                         'to ~1.5x (still the reverse direction of the documented EHS-specific '
                         'figures, plausibly attributable to EHS/EHI definitional differences '
                         'and non-overlapping source studies for the two years -- see '
                         'CHANGELOG.md). '
                         'THIS VALUE WAS FIT AT A REDUCED N=200 (single-core '
                         'feasibility run, not the usual 10,000-50,000) -- re-run '
                         'intercept_estimation.py at full production N before treating '
                         'this as final. '
                         '[2026-10-14] Re-calibrated all three endpoints with '
                         'intercept_estimation.py at N=1000, seed=42. Step 1 (snapshot '
                         '2026-10-10 model, unchanged): ehs -9.554, hospitalisation '
                         '-8.061, first_aid -6.909 -- i.e. the stored values were already '
                         'stale (the CVR below-zero change of 2026-10-04 and the sweat fix '
                         'of 2026-10-09 post-date them); the old ehs value overstated risk '
                         'by ~2x in odds (exp(0.75)). Step 2 (current model: Daniels-Gilbert '
                         'duration ceiling also in the fixed-pace calibration path, '
                         'integral pacing term K_I_PACING_CV=0.02, post-finish after-glow '
                         'fix -- the last does not enter z): ehs -8.808, hospitalisation '
                         '-7.482, first_aid -6.317. The ehs value landing next to the old '
                         '-8.804 is a coincidence of two opposite shifts, not confirmation. '
                         'Also fixed: intercept_estimation.py did not pass sample_pace / '
                         'event_dist_km for the DtD block although the 2026-09 values were '
                         'documented as sample_pace=True. Still PROVISIONAL: N=1000 is not '
                         'production scale (10,000-50,000), and the ehs calibration '
                         'population still uses the fixed 5:00/6:00 min/km marathon pace, '
                         'not a Boston-specific pace model. '
                         '[2026-10-15] Control round. (1) Reproducibility: two identical '
                         'seed-42 runs differed by 0.001 because drink sizes were drawn '
                         'from the worker processes\' inherited RNG in scheduling order; '
                         'fixed in worker_monte_carlo_adult (per-participant seed), now '
                         'bit-identical. (2) Seed spread at N=1000 (seeds 42/43/44): ehs '
                         '-8.809/-8.778/-8.784 (range 0.03 -- stable); hospitalisation '
                         '-7.483/-7.257/-7.929 (range 0.67, factor ~2 in odds); first_aid '
                         '-6.318/-6.152/-6.502 (range 0.35). The DtD endpoints rest on the '
                         'few participants above 40.5 degC (0.3-1.1% of N), hence unstable '
                         'at N=1000. (3) DtD at N=5000, seeds 42/43: hospitalisation '
                         '-7.557/-7.339, first_aid -6.370/-6.219; stored value = mean of '
                         'the two logits (approximation of a pooled N=10,000 fit). Residual '
                         'uncertainty of the DtD intercepts ~+/-0.1-0.2 (odds factor '
                         '~1.1-1.25); ehs final-code value -8.809350. '
                         '[2026-10-16] Recalibrated after replacing JOS-3\'s age step at '
                         '60 y by a gradual decrement (jos3_leeftijd.py, variant C). ehs '
                         '-8.809 -> -8.790 (within seed spread); hospitalisation -7.448 -> '
                         '-7.280; first_aid -6.295 -> -6.176. Notably the two DtD seeds now '
                         'agree within 0.012 (were 0.22 apart): much of the earlier seed '
                         'spread came from the few 60-65-year-olds that the step pushed '
                         'into the tail.'),
    },
    'hospitalisation': {
        'label':        'Hospital admission (DtD 2024)',
        'p_obs':        50.0 / 35_000,          # 0.00143
        'n_obs':        50.0,
        'n_participants': 35_000,
        'intercept_kal': -8.490417,  # [2026-11-01] heat acclimation in JOS-3 sweating + plasma volume; mean of N=5000 seeds 42/43 (-8.429063/-8.551770; was -8.677948)
                                       # [2026-10-31]: -8.677948; Liljegren globe + RH_urban (was -7.922109)
                                       # [2026-10-23] rest core 37.0 + fitness/heat age curve; mean of N=5000 seeds 42/43 (-7.506197/-7.514014; was -8.080096)
                                       # [2026-10-20 evening]: -8.080096; JOS-3 finish zone + EAC-staan; fresh mean of N=5000 seeds 42/43 (was -8.553130)
                                       # [2026-10-16 evening] -7.266031, PACE_FITNESS_ABSOLUTE + jos3_leeftijd, mean of N=5000 seeds 42/43 (-7.2688/-7.2632); was -7.279916
                                       # [2026-10-15] mean of two N=5000 runs (seeds 42/43: -7.557/-7.339),
                                       # ~N=10,000. Seed spread at N=1000 was 0.67 -- see ehs note 2026-10-15.
                                       # [2026-10-14] re-calibrated N=1000, seed=42, sample_pace=True
                                       # (was -7.829262, 2026-09, N=800) -- see ehs note 2026-10-14.
                                       # [2026-09] sample_pace=True recalibration
                                       # (N=800, seed=42) -- see note. Previous
                                       # value -7.282445 (N=200, sample_pace=False,
                                       # 2026-07-28) is kept below for reference.
        'source':       'Data provided by GHOR Noord-Holland Noord and Le Champion (Dam tot Damloop 2024)',
        'status':       'PROVISIONAL',
        'notes':        ('50 hospital admissions / 35,000 Dam tot Damloop 2024 '
                         'participants. [2026-07, third recalibration] Previously '
                         'this intercept (like first_aid below) was calibrated against '
                         'Boston\'s own reference conditions (4h, 18-22 degC, MET '
                         '11.0) -- the SAME scenario used for the ehs endpoint -- '
                         'even though this target is a DtD-observed number under '
                         'DtD\'s own, quite different conditions (~1.63h, Amsterdam '
                         'Sept 2024). Verified this was not harmless: '
                         '(intercept - logit(p_obs)) was nearly constant across all '
                         'three endpoints purely because they shared one reference '
                         'z-distribution, not because of any real relationship '
                         'between duration and incidence. Fixed by giving '
                         'intercept_estimation.py a generalizable per-endpoint '
                         'reference-conditions architecture (REF_CONDITIONS_BY_KEY, '
                         'ENDPOINTS[*][\'ref_conditions_key\']): this endpoint (and '
                         'first_aid, correctly, since they share the same real DtD 2024 '
                         'origin) is now calibrated against its own DtD-matched '
                         'reference conditions (REF_CONDITIONS_DTD: 1.63h, '
                         '19.5-21.5 degC, MET 9.8 -- itself an approximation, same '
                         'spirit as Boston\'s own synthetic reference block, not a '
                         'literal replay of the fetched weather file). Confirmed the '
                         'fix worked: (intercept - logit(p_obs)) for hospitalisation '
                         'and first_aid now match each other (-0.732, -0.731, correctly, '
                         'same real event) while differing from ehs (-1.791, '
                         'correctly, a different real event). '
                         '[2026-09, fourth recalibration] The 2026-07-28 value above '
                         '(-7.282445) was calibrated with sample_pace=False -- i.e. '
                         'every simulated participant shared one fixed MET/duration, '
                         'not the per-person pace/MET/duration sampling that '
                         'generate_base_population(sample_pace=True) added this same '
                         'month. Verified this mismatch is not harmless: applying the '
                         'old (sample_pace=False-fit) intercept unchanged to a '
                         'sample_pace=True population (N=800, seed=42, same DtD '
                         'reference conditions) inflates mean collapse probability to '
                         '2.446 per 1,000 vs. the calibration target of 1.429 per '
                         '1,000 -- a 1.71x overshoot from calibration mismatch alone, '
                         'no physiological change. Re-ran the Newton iteration '
                         '(intercept_estimation.py) with sample_pace=True and '
                         'event_dist_km=16.1 (PACE_REFERENCE_DIST_KM) and the '
                         'reference window widened to '
                         'PACE_MIN_PER_KM_CEILING * event_dist_km, matching the '
                         'widening run_hestia.py already applies for real event runs; '
                         'this converged to -7.829262 (N=800). Cross-check: the '
                         'first_aid endpoint below needed an almost identical shift '
                         '(-0.608 vs. this endpoint\'s -0.627), consistent with a '
                         'structural sample_pace effect rather than endpoint-specific '
                         'noise. N=800 is still well short of production scale '
                         '(10,000-50,000); treat this as a better-than-N=200 interim '
                         'value, not a final one. The sensitivity table on the '
                         'first_aid endpoint below is unchanged and therefore now '
                         'stale relative to this intercept -- it still reflects '
                         'sample_pace=False and needs its own sample_pace=True re-run. '
                         'Does NOT touch the ehs/Boston endpoint above: '
                         'sample_pace\'s pace-sampling curve (PACE_MEDIAN_MIN_PER_KM, '
                         'PACE_MIN_PER_KM_CEILING) was researched specifically for '
                         'DtD\'s own recreational field and should not be silently '
                         'reused for Boston\'s BQ-qualified, narrower field -- ehs '
                         'would need its own pace-sampling model built first. Still '
                         'pending recalibration against clinical data '
                         '(Radboudumc), and at production-scale N.'),
    },
    'first_aid': {
        'label':        'First-aid contact, all incidents (DtD 2024 estimate)',
        'p_obs':        150.0 / 35_000,         # 0.00429; central estimate
        'n_obs':        150.0,                   # uncertain: range 100-250
        'n_participants': 35_000,
        'intercept_kal': -7.262350,  # [2026-11-01] heat acclimation in JOS-3 sweating + plasma volume; mean of N=5000 seeds 42/43 (-7.231262/-7.293437; was -7.471756)
                                       # [2026-10-31]: -7.471756; Liljegren globe + RH_urban (was -6.771391)
                                       # [2026-10-23] rest core 37.0 + fitness/heat age curve; mean of N=5000 seeds 42/43 (-6.398324/-6.405754; was -6.926663)
                                       # [2026-10-20 evening]: -6.926663; JOS-3 finish zone + EAC-staan; fresh mean of N=5000 seeds 42/43 (was -7.355230)
                                       # [2026-10-16 evening] -6.162057, PACE_FITNESS_ABSOLUTE + jos3_leeftijd, mean of N=5000 seeds 42/43 (-6.1643/-6.1598); was -6.175971
                                       # [2026-10-15] mean of two N=5000 runs (seeds 42/43: -6.370/-6.219).
                                       # [2026-10-14] re-calibrated N=1000, seed=42, sample_pace=True
                                       # (was -6.707273, 2026-09, N=800) -- see ehs note 2026-10-14.
                                       # [2026-09] sample_pace=True recalibration
                                       # (N=800, seed=42) -- see note. Previous
                                       # value -6.179056 (N=200, sample_pace=False,
                                       # 2026-07-28) kept below for reference; the
                                       # sensitivity table further below is still
                                       # computed under that old sample_pace=False
                                       # regime and is now stale -- needs its own
                                       # sample_pace=True re-run before it's used.
        'source':       'Data provided by GHOR Noord-Holland Noord and Le Champion (Dam tot Damloop 2024; first-aid count is an estimate)',
        'status':       'PROVISIONAL',
        'notes':        ('Central estimate: ~150 first-aid contacts / 35,000. '
                         '[2026-07, third recalibration] Same fix as the '
                         'hospitalisation endpoint above: now calibrated against '
                         'DtD\'s own reference conditions (REF_CONDITIONS_DTD in '
                         'intercept_estimation.py) instead of Boston\'s borrowed '
                         'scenario -- see the hospitalisation endpoint\'s notes for '
                         'the full rationale and verification. Sensitivity table '
                         'below is likewise reduced-N (N=200) and needs a '
                         'production-scale re-run. P_obs itself still requires '
                         'confirmation from GHOR NHN. '
                         '[2026-09, fourth recalibration] Same sample_pace=True fix '
                         'as hospitalisation above, same DtD reference conditions and '
                         'N=800/seed=42 run -- see that endpoint\'s notes for the '
                         'full rationale. Old (sample_pace=False-fit) intercept '
                         '-6.179056 applied unchanged to a sample_pace=True '
                         'population inflates mean risk to 7.137 per 1,000 vs. the '
                         '4.286 per 1,000 target -- a 1.67x overshoot, matching the '
                         'hospitalisation endpoint\'s 1.71x almost exactly, which is '
                         'the main reason to trust this as a structural sample_pace '
                         'effect and not noise. Re-calibrated intercept: -6.707273 '
                         '(N=800). The sensitivity table below has NOT been '
                         're-run under sample_pace=True and should not be trusted '
                         'until it is.'),
        'sensitivity': {   # [2026-11-01] heat acclimation (JOS-3 sweating + plasma volume): mean of N=5000 seeds 42/43, sample_pace=True (whole table refreshed)
            100: -7.718354,
            125: -7.467810,
            150: -7.262350,
            175: -7.088052,
            200: -6.936592,
            225: -6.802597,
            250: -6.682398,
        },
    },
}

# Active endpoint -- change here or via user prompt in main()
# Options: 'ehs' | 'hospitalisation' | 'first_aid'
ACTIVE_ENDPOINT = 'ehs'

# Convenience aliases (backward compatible with code that uses P_OBS_COLLAPSE)
_ep                       = COLLAPSE_ENDPOINTS[ACTIVE_ENDPOINT]
P_OBS_COLLAPSE            = _ep['p_obs']
N_OBS_COLLAPSE_ADMISSIONS = _ep['n_obs']
N_OBS_PARTICIPANTS        = _ep['n_participants']

HESTIA_VERSION            = 'rev15'   # population file schema version-safety; rev16 changes output only

# =============================================================================
#  REV14 CONFIGURATION CONSTANTS
# =============================================================================

EVENT_PACE_MIN_PER_KM    = 5.47    # min/km  -- override per event (5,47 mediaan Leiden marathon)
K_P_PACING               = 0.10   # MET/°C  -- population MEAN reference. [2026-09-28 correctie:
                                    # de eerder hier vermelde bron ("Ely et al. 2007, Med Sci
                                    # Sports Exerc 39:1949-1955") bestaat niet -- die combinatie
                                    # van jaar/volume/paginanummers is bij geen van beide
                                    # onderzoekers met de achternaam Ely te vinden. Het artikel dat
                                    # qua bevinding EN qua getal (38,5°C) het best aansluit is:
                                    # Ely BR, Cheuvront SN, Kenefick RW, Sawka MN (2010). "Aerobic
                                    # performance is degraded, despite modest hyperthermia, in hot
                                    # environments." Med Sci Sports Exerc 42(1):135-141 -- Brett R.
                                    # Ely, NIET Matthew R. Ely (die schreef de bekendere 2007/2008
                                    # marathon-weer-papers; vermoedelijk verwisseld). Kanttekening:
                                    # dat is een kort (15 min) fietslab-experiment met milde
                                    # oververhitting (piek Tc 38,1-38,4°C) -- het bevestigt het
                                    # kwalitatieve verschijnsel, niet per se deze exacte
                                    # kwantitatieve waarden voor een marathon-achtig scenario.
K_P_PACING_CV            = 0.10   # MET/(L/min) -- [NOT VALIDATED, see docstring
                                    # below] population MEAN reference for
                                    # cardiovascular-driven pacing. No direct
                                    # literature source found for this specific
                                    # gain (searched explicitly; general RPE/
                                    # pacing literature supports the MECHANISM
                                    # -- Borg 1982's original RPE scale was a
                                    # linear transform of heart rate; "Cognitive
                                    # Control of Pacing" lit review: "perceived
                                    # exertion is primarily based on cardiac
                                    # output" -- but not this exact numeric
                                    # gain. Same value as K_P_PACING chosen as a
                                    # plausible starting point, not because the
                                    # two gains are known to be equal. Revisit
                                    # once hindcast data against known outcomes
                                    # is available (same open item as TCF/AUC
                                    # calibration elsewhere in this project).
                                   # [rev14] individual kp_pacing replaces this in sim
                                   # [2026-09-28] Mechanism has real but CONTESTED literature
                                   # support: Periard et al. (2011, Exp Physiol 96(2):134-144)
                                   # conclude cardiovascular strain impairs prolonged self-paced
                                   # exercise in the heat -- but a published rebuttal in the same
                                   # journal (2011, 96(4):476-8, with authors' reply) argues the
                                   # data instead support anticipatory/central regulation, not a
                                   # hard cardiovascular ceiling. Given that dispute, and per
                                   # the author's explicit preference (control-engineering framing: a
                                   # proportional response is the more natural choice than a
                                   # discrete on/off switch), this term was changed from a hard
                                   # zero-crossing gate to a gradual overshoot below
                                   # CO_RESERVE_PACING_THRESHOLD -- see that constant below, and
                                   # the updated cv_overshoot computation further down this file.
                                   # This does NOT resolve the literature dispute; it is a design
                                   # choice consistent with one side of it, matching how the
                                   # thermal term already works.
K_P_SIGMA                = 0.04   # std dev of K_p population distribution
K_P_NSAID_FACTOR         = 1.00   # [2026-10-16] was 0.50 ("NSAID halves K_p via PGE2"). Set to 1.0 =
                                   # no thermal effect, by decision of the author. Literature review:
                                   # ibuprofen/naproxen/aspirin alone do not change core temperature
                                   # during exercise (Emerson et al. 2021, J Exerc Sci Fit, systematic
                                   # review, 7 of 9 studies; Emerson et al. 2021, Sports Med Health Sci,
                                   # naproxen at 35.7 degC); no RPE or thermal-sensation difference
                                   # (Veltmeijer et al. 2016, IJSPP; Nieman 2006). A lower core
                                   # temperature (~0.3 degC, consistent with a lower set point) is only
                                   # shown for a COX-2 selective drug (Bradford 2007) and ibuprofen +
                                   # paracetamol combined (Veltmeijer 2016). The real NSAID risks are
                                   # non-thermal and not modelled: gut barrier (van Wijck 2012) and
                                   # hyponatraemia (Wharam 2006). In the Amsterdam run the old 0.50
                                   # changed peak T_rect of NSAID users by only 0.008 degC on average.
                                   # Keep 0.50 only as a sensitivity scenario.
NSAID_PREVALENTIE        = 0.25   # 25% of recreational runners use NSAID (estimate)
T_RECT_PACING_THRESHOLD  = 38.5   # °C -- onset of voluntary pacing reduction
# [2026-10-14] Integral (I) action on the cardiovascular pacing loop
# (ON since 2026-10-14; set 0.0 for the previous P-only behaviour).
# Background: the existing CV term is proportional on met_initial only
# (MET reduction = kp_cv * (2.0 - CO_reserve)), recomputed from scratch
# every step. With the model's own sensitivity dCO/dMET ~1.1-1.2 L/min per
# MET (Lloyd 2022 g0 x 0.245 L O2/min per MET for 70 kg), kp_cv = 0.10
# gives a loop gain of only ~0.12: a runner starting at CO_reserve -3 L/min
# settles at about -2.5 L/min and keeps running at VO2 above their own
# heat-reduced VO2max. A pure P-loop always leaves a steady-state error;
# an I-term removes it. When CO_reserve < 0 the integral grows by
# K_I_PACING_CV * |CO_reserve| per minute; above CO_RESERVE_PACING_THRESHOLD
# it decays with PACING_CV_INTEGRAL_RELEASE_MIN (runner may pick up pace
# again); capped at PACING_CV_INTEGRAL_MAX_FRAC of met_initial (anti-windup).
# [2026-10-14] Switched ON at the author's decision (0.02 MET/(L/min)/min, the
# value tested in CHANGELOG.md 2026-10-14). Not validated
# against field data; 0.0 restores the previous P-only behaviour.
K_I_PACING_CV                 = 0.02   # MET per (L/min * min); 0.0 = off
PACING_CV_INTEGRAL_RELEASE_MIN = 30.0  # min -- decay of the integral when reserve recovers
PACING_CV_INTEGRAL_MAX_FRAC   = 0.40   # max. integral reduction as fraction of met_initial
# [2026-10-19] FORCED pace reduction at the cardiovascular ceiling (author's
# decision). CO_reserve has a hard physical limit at 0: delivered cardiac
# output cannot exceed the heat-reduced maximum, so a runner whose voluntary
# pace would demand more slows down whether he wants to or not (Gonzalez-
# Alonso & Calbet 2003, Circulation 107:824: CO, leg blood flow and O2 delivery
# fall 5-11% before exhaustion; Periard et al. 2011, Exp Physiol 96:134:
# self-paced power -13% in 35 vs 20 degC). Each step the MET is capped at
# CVRModel.met_at_ceiling() of the previous step's state; the voluntary P/I
# pacing terms above act on top. Within one 10-min step the heat can still
# push CO_reserve slightly below 0 (the step in which the ceiling was hit);
# the next step is then forced down. The conjunctive criterion
# (T_rect > 40.5 AND CO_reserve <= 0) therefore now means "hot AND at the
# cardiovascular ceiling". Switch off only for comparison with earlier runs.
CV_CEILING_FORCED = True
CV_CEILING_ANTICIPATE = True   # feed-forward: anticipate the ceiling's fall during the next step
# [2026-10-19] "At the ceiling" tolerance (DOMAIN CHOICE, flagged to the author).
# With the forced ceiling the race-window CO_reserve settles at ~0 (+/- a few
# hundredths of a L/min of numerical noise) instead of going clearly negative.
# A literal "<= 0" test then fires at random and a strict "< 0" test hardly
# ever. Every conjunctive criterion (EHS, EHE, the 'already flagged' check,
# Klimatos) therefore reads CO_reserve <= CO_RESERVE_CEILING_TOL as "at the
# cardiovascular ceiling". 0.05 L/min is ~0.25% of a typical CO_max (20 L/min):
# below the resolution of any cardiac-output measurement, so it cannot be told
# apart from 0 physiologically. The deficit doses measure depth from this same
# line (ceiling_depth), so a runner held at the ceiling while hot accumulates
# dose in proportion to the TIME spent there. EAC (post-finish, postural) and
# the post-finish TCF dose are NOT changed: the ceiling is not applied after
# the finish. Set to 0.0 to restore the literal test.
CO_RESERVE_CEILING_TOL = 0.05   # L/min

# [2026-10-19, evening] Three follow-ups to the forced ceiling (author's
# decision: "alles bij elkaar een realistische modellering").
#
# 1. RACE_DISTANCE_MODE -- the race is a DISTANCE, not a duration. When the
#    profile carries a planned pace and duration (sample_pace runs), speed
#    follows the current MET through Daniels & Gilbert (1979), anchored so
#    that the planned MET gives exactly the planned pace. A runner who slows
#    (voluntarily or forced) covers less ground per step and stays out longer
#    in the weather. The last step is shortened to the minutes actually
#    needed. The race can last until the end of the weather window the caller
#    supplies (run_monte_carlo_adult: the course limit,
#    PACE_MIN_PER_KM_CEILING x distance); a runner still short of the
#    distance then is flagged dnf_cutoff (swept from the course). Runs without
#    a planned pace (individual engine, bridge, fixed-pace calibration) keep
#    the fixed duration.
#
# 2. RPE_STOP_ENDS_RACE -- a runner who stops on RPE >= 19.5 was frozen
#    (state copied unchanged to the end of the race). Now the race ends at
#    the stop and the post-finish module follows him/her from that moment:
#    after-glow, venous pooling and recovery of CO_reserve, exactly as after
#    a finish. The stop time and the distance covered are exported.
#
# 3. SLOWDOWN_AFTERGLOW -- T_rect overshoot after slowing (the author's
#    "delicaat evenwicht"). JOS-3 switches heat production to the new MET
#    instantly. In reality heat already produced in the working muscles is
#    still carried to the core, while heat loss falls (less self-generated
#    air flow, less skin blood flow). After a full stop the suite already
#    adds an after-glow of PF_DELTA_T_NAGLOED (0.40 degC, author's choice;
#    clinic 11 Oct measured 0.23 degC). The same after-glow is now applied to
#    every MET DROP during the race, scaled to the size of the drop:
#        dT = PF_DELTA_T_NAGLOED * dMET / (MET_initial - PF_MET_RUST)
#    so a drop from race pace to rest gives the full 0.40 degC and a 1-MET
#    drop of a 10-MET runner about 0.05 degC. The heat is added to the JOS-3
#    core compartments at the start of the step, so JOS-3's own
#    thermoregulation removes it again and the CVR module sees it in CHSI.
#    Only drops count (no undershoot when speeding up). MODEL CHOICE, NOT
#    VALIDATED: the evidence is for stopping (Kenny & Niedre 2002; Journeay,
#    Carter & Kenny 2006), the scaling to partial slowing is an assumption.
RACE_DISTANCE_MODE = True
RPE_STOP_ENDS_RACE = True
SLOWDOWN_AFTERGLOW = True
# Sweep ("bezemwagen") for RACE_DISTANCE_MODE -- DOMAIN CHOICE, flagged to the
# author. The pace sampler's slowest runner (PACE_MIN_PER_KM_CEILING) needs
# exactly the course limit; without extra room every runner at that limit
# (138 of 1000 in Amsterdam, a clipping pile-up) was swept as soon as he
# slowed at all. The weather window and therefore the sweep is set at 1.25 x
# the slowest planned time (Dam tot Damloop 2.0 -> 2.5 h, marathon 5.2 ->
# 6.6 h). Real closing times differ per event.
RACE_SWEEP_FACTOR = 1.25


def race_window_hours(event_dist_km: float) -> float:
    """Weather window a sample_pace run needs: the slowest planned runner
    plus room to slow down (RACE_SWEEP_FACTOR) when RACE_DISTANCE_MODE."""
    base = PACE_MIN_PER_KM_CEILING * event_dist_km / 60.0
    return base * (RACE_SWEEP_FACTOR if RACE_DISTANCE_MODE else 1.0)


def at_cv_ceiling(co_reserve) -> bool:
    """True when CO_reserve is at (or below) the cardiovascular ceiling."""
    return co_reserve is not None and not np.isnan(co_reserve) and co_reserve <= CO_RESERVE_CEILING_TOL


def ceiling_depth(co_reserve) -> float:
    """Depth below the 'at ceiling' line in L/min (0 when above it)."""
    if co_reserve is None or np.isnan(co_reserve):
        return 0.0
    return max(0.0, CO_RESERVE_CEILING_TOL - co_reserve)

CO_RESERVE_PACING_THRESHOLD = 2.0  # L/min -- [2026-09-28] onset of cardiovascular-driven pacing
                                    # reduction. Reuses the same 2.0 L/min 'decompensation risk'
                                    # reference already used elsewhere in this model (the
                                    # collapse-kans z-score's CV term, and the CO_reserve charts)
                                    # -- not a new, independently-chosen number. Replaces the
                                    # previous zero-crossing gate (see K_P_PACING_CV docstring).
T_AUC_THRESHOLD          = 39.0   # °C -- integration floor AUC_thermisch (diagnostic)
T_AUC_KLINISCH           = 40.5   # °C -- Roberts (2007) clinical threshold
AUC_ROBERTS_GRENS        = 60.0   # °C·min -- Roberts clinical intervention limit
# [2026-09] Thermal-only critical threshold, independent of CO_reserve.
# The conjunctive clinical criterion (T_rect>40.5 AND CO_reserve<=0)
# captures CNS dysfunction via the cardiovascular-perfusion pathway
# (falling cardiac output -> falling BP -> reduced cerebral perfusion;
# Starling's-Law heatstroke cascade, cf. Periard et al. 2021). That is
# a real causal pathway, but not the only one: above the human critical
# thermal maximum, direct thermal cytotoxicity to brain tissue can cause
# CNS dysfunction on its own, regardless of CO_reserve status.
#   - Hubbard: human critical thermal maximum (CTM) estimated 41.6-42.0
#     degC (unacclimatized, well-hydrated men, controlled heating).
#   - Gaehwiler et al. (1972): spontaneous neuronal activity in culture
#     stops irreversibly between 42-43 degC -- direct cell-level injury.
# T_THERMAL_ONLY_CRITICAL flags this thermal-only pathway as a separate,
# non-conjunctive stat (pct_thermal_only_critical, see stats dict below),
# analogous to the existing Roberts AUC_klinisch measure. Not currently
# reached in any calibration scenario run to date (peak T_rect stayed
# below 40 degC in the DtD/Amsterdam 2026 runs) -- relevant for hotter
# scenarios (e.g. Klimatos_ClimateShift projections to warmer years).
T_THERMAL_ONLY_CRITICAL  = 42.0   # °C -- CTM (Hubbard); irreversible neuronal
                                   # injury onset (Gaehwiler et al. 1972)
# Post-finish module constants (Roberts 1998; Rowell 1974)
PF_DELTA_T_NAGLOED       = 0.40   # °C  -- metabolic after-glow peak amplitude
PF_TAU_NAGLOED           = 2.0    # min -- exponential decay time constant
# [2026-07, REVISED] Was: PF_DELTA_CO_POOLING = 0.30, a *fraction of the
# shrinking co_res itself* (pooling_rate = 0.30 * co_res * exp(-t/tau)).
# That has a dead zone: since the decrement is proportional to co_res, a
# positive co_res decays asymptotically toward zero but can never actually
# cross it (same shape as radioactive decay -- always positive for finite
# time). Before the CVR module rebuild, co_reserve_finish was often already
# negative or near-zero at the finish line, so this was rarely visible.
# After the rebuild (healthier baseline, medians +1 to +6 L/min at finish),
# verified directly that starting values of +0.2/+1.0/+3.0/+6.0 L/min never
# cross zero within the 10-min window (end values +0.12/+0.58/+1.73/+3.45)
# -- meaning the well-documented post-finish collapse phenomenon (Roberts
# 1998: someone looks fine crossing the line, then decompensates minutes
# later) could no longer be captured for the majority of participants.
# Fixed by rescaling to a fraction of CO_max (an absolute quantity tied to
# the person's own cardiovascular ceiling, not to their shrinking reserve),
# so the pooling effect no longer vanishes as co_res approaches zero.
# 0.06 is a provisional magnitude (not literature-derived) chosen after
# testing a range (0.04-0.18) for the best differentiation across starting
# reserves: modest finishers (+0.2 to +1.0 L/min) tip into deficit within
# 0.5-1 min and settle moderately negative (not instantly floored);
# borderline-healthy finishers (~+3 L/min) sit right at the edge; clearly
# healthy finishers (+6 to +10 L/min) stay positive but visibly reduced.
# Flagged for review, same as other provisional constants in this project.
PF_POOLING_FRAC_OF_COMAX = 0.06   # fraction of CO_max (at finish) lost to
                                   # venous pooling at its peak (t=0)
PF_TAU_POOLING           = 1.5    # min -- pooling time constant
PF_KOELING_PER_MIN       = 0.03   # °C/min -- passive cooling without running
PF_DUUR_MIN              = 10.0   # min -- post-finish simulation window
PF_DT_MIN                = 0.5    # min -- time step post-finish
# [2026-07] Resting MET fed into CVRModel.compute_step() post-finish, now
# that CO_demand is recomputed each step instead of frozen at the finish
# line. 1.5 (light standing/walking) rather than 1.0 (true rest): finishers
# are rarely fully motionless in the finish zone (walking, being assisted,
# mild residual movement).
PF_MET_RUST              = 1.5
# [2026-10-20] FINISH ZONE WITH JOS-3 (author's decision). The simple
# post-finish model above let everything settle within ~5 min (after-glow
# tau 2 min, pooling tau 1.5 min, early stop once T_rect < 39 degC), so a
# longer window changed nothing -- while most endurance-event collapses
# happen AFTER the finish. simulate_post_finish_jos3() continues the runner's
# own JOS-3 model in the finish-zone weather instead:
#   * Heat: JOS-3 keeps exchanging heat with the real air temperature, sun
#     (MRT) and the ambient wind only (no running air flow). In a hot, sunny,
#     windless finish zone T_rect can keep rising; in cool weather it falls.
#   * After-glow: the same rule as SLOWDOWN_AFTERGLOW -- 0.40 degC x dMET /
#     (MET_start - PF_MET_RUST) per drop in load, released into the core with
#     tau PF_TAU_NAGLOED -- for the drop at the finish and again when walking
#     stops.
#   * Activity: PF_WALK_MIN minutes of slow walking through the finish zone
#     (PF_MET_WALK), then standing (PF_MET_RUST). A runner who stopped on RPE
#     does not walk.
#   * Standing: the acute venous-pooling dip (PF_POOLING_FRAC_OF_COMAX, tau
#     PF_TAU_POOLING) starts when the muscle pump stops (end of walking).
#     [2026-10-20, author's decision] Standing lasts PF_STAND_MIN, then the
#     runner sits or lies down. The sustained 3 % standing deficit on
#     CO_reserve was removed: CO_reserve measures pump capacity, while
#     collapse on standing is a filling/blood-pressure problem. That is now
#     the EAC-staan endpoint below.
#   * Heart: lagged MET (CV_LAG_ENABLED) and the CVR module on the JOS-3 core
#     and skin temperatures and the running dehydration (sweat continues,
#     drinking as in the race).
#   * Window PF_JOS3_DUUR_MIN (30 min), no early stop.
# PF_JOS3 = False restores simulate_post_finish().
PF_JOS3                  = True
PF_JOS3_DUUR_MIN         = 30.0   # min
PF_JOS3_DT_MIN           = 0.5    # min
PF_WALK_MIN              = 5.0    # min walking through the finish zone
PF_MET_WALK              = 2.8    # MET, slow walking (~3 km/h; Ainsworth Compendium)
PF_STAND_MIN             = 5.0    # min standing after the walk, then sitting/lying (author's decision)

# [2026-10-20] EAC-STAAN: exercise-associated collapse on standing (author's
# decision, option B of the finish-zone study "Collaps na de finish").
# Replaces the old EAC endpoint (sustained CO_reserve deficit), which measured
# pump capacity where collapse after the finish is a filling / blood-pressure
# problem (Asplund, O'Connor & Noakes 2011, Br J Sports Med 45:1157).
# Orthostatic tolerance relative to normal, each minute while standing:
#     tol = exp(-K_SKIN*(Tskin-34.3)+) * exp(-K_CORE*(Trect-36.8)+) * exp(-K_DEHY*dehy%)
#   K_SKIN, K_CORE from Pearson e.a. 2017 (Exp Physiol 102:255): skin +3.3 degC
#     and core +1.5 degC each left ~56 % of LBNP tolerance; together (skin
#     +4.5, core +1.3) 25 % measured vs 27 % predicted by the product.
#   K_DEHY from Schlader e.a. 2015 (Exp Physiol 100:926): 0.9 % and 1.9 % body
#     mass loss left 81 % and 69 % of tolerance (0.23 and 0.20 per %).
# Standing load: R = integral over standing minutes of 1/tol (min). Walking
# (muscle pump) and sitting/lying add nothing.
# Individual tolerance varies: LBNP tolerance CV 0.24 (Pearson 2017, n=9) and
# ~0.43 (Keller e.a. 2009, SD from s.e.m., n=7). A runner collapses when R
# exceeds his own limit, lognormal with spread EAC_SIGMA = 0.35 (midpoint;
# model choice) around exp(EAC_LN_K):
#     P(EAC) = Phi((ln R - EAC_LN_K) / EAC_SIGMA)
# EAC_LN_K is the one calibrated value: 1.5 EAC per 1000 starters (Naidoo,
# Sewry e.a. 2022, Two Oceans 21/56 km, cool), on the Dam tot Damloop
# reference population (intercept_estimation.py, key dtd -> intercept_estimation_eac.json). Not modelled: the post-exercise
# vasodilation and weaker baroreflex as a separate factor (folded into
# EAC_LN_K), sex differences (women 2.25x on 21 km in Naidoo 2022).
EAC_STAND_ENABLED = True
EAC_K_SKIN   = 0.176   # per degC mean skin temperature above 34.3
EAC_K_CORE   = 0.387   # per degC T_rect above 36.8
EAC_K_DEHY   = 0.20    # per % body-mass loss
EAC_SIGMA    = 0.35    # spread of individual tolerance (log units), model choice (0.24-0.43 in LBNP studies)
# [2026-10-20 late] Author's decision after the second EAC analysis:
#  - The core term counts only up to 38.3 degC, the highest core temperature
#    tested by Pearson 2017 (passive heating at rest). Runners stand at
#    39-41 degC, far outside that range; extrapolating the exponential made
#    the EAC curve 5-10x too steep against field data.
#  - A heat-independent base share: EAC is principally postural hypotension
#    after the muscle pump stops (Asplund 2011); heat aggravates it. Naidoo
#    2022 found no WBGT effect within 12-18. Of the 1.5/1000 at the DtD
#    reference, EAC_BASE_P (1.0/1000, model choice) does not depend on heat.
EAC_CORE_CAP = 38.3    # degC, upper end of the tested core range (Pearson 2017)
EAC_BASE_P   = 0.0010  # heat-independent EAC probability per standing runner (model choice)
EAC_WBGT_VALID_MAX = 28.0  # degC; above this (ACSM black flag, no field data) EAC is reported as "zeer hoog", not as a number. Name kept for compatibility: nothing below it is validated either.
EAC_LN_K     = 3.891821  # [2026-11-01] heat acclimation (JOS-3 sweating + plasma volume), seeds 42 (3.891628) / 43 (3.892014); was 3.970524
# [2026-10-31]: 3.970524; Liljegren globe + RH_urban (was 3.803705)
# [2026-10-23] was 3.786865 = rest core 37.0 + fitness/heat age curve, seeds 42 (3.786517) / 43 (3.787212); was 3.808518
# previous: 3.808518 calibrated 2026-10-20 late (core cap 38.3, base 1.0/1000): 1.5/1000 on the DtD reference, N=5000, mean of seeds 42 (3.808401) and 43 (3.808634); was 4.234274 without cap/base


def eac_tolerance(t_skin: float, t_rect: float, dehy_pct: float) -> float:
    """Orthostatic tolerance relative to normal (1.0 = normothermic, hydrated)."""
    t_core = min(t_rect, EAC_CORE_CAP) if EAC_CORE_CAP is not None else t_rect
    return float(np.exp(-EAC_K_SKIN * max(0.0, t_skin - 34.3)
                        - EAC_K_CORE * max(0.0, t_core - 36.8)
                        - EAC_K_DEHY * max(0.0, dehy_pct)))


def eac_probability(stand_load_min: float) -> float:
    """P(exercise-associated collapse) for a standing load R (min)."""
    if not EAC_STAND_ENABLED or stand_load_min is None or stand_load_min <= 0:
        return 0.0
    from math import erf, sqrt, log
    zz = (log(stand_load_min) - EAC_LN_K) / EAC_SIGMA
    p_heat = 0.5 * (1.0 + erf(zz / sqrt(2.0)))
    return float(EAC_BASE_P + (1.0 - EAC_BASE_P) * p_heat)


# =============================================================================
#  UTILITY FUNCTIONS (unchanged from rev09)
# =============================================================================

def wind_speed_at_height(v_ref, z_ref, z_target, z0=0.1):
    """Converts wind speed from reference height to target height (log profile)."""
    if z_ref <= 0 or z_target <= 0 or z0 <= 0:
        raise ValueError("Heights and roughness length must be positive.")
    return v_ref * (np.log(z_target / z0) / np.log(z_ref / z0))


# [2026-10-19, night] Heading-averaged relative wind (found during the
# foundation repair; MODEL CHOICE, flagged to the author). Each runner had ONE
# fixed wind angle for the whole race. A runner with a near-perfect tailwind
# equal to his own speed then had ~0.1 m/s air flow for hours. With the
# repaired heat production this gave runaway core temperatures in COOL
# weather (Amsterdam 2026-10-18, 13 degC: one runner 40.1 -> 42.9 degC in
# 70 min at constant pace, air flow 0.82 -> 0.10 m/s), and made Amsterdam's
# hot tail four times larger than Boston's at 18-22 degC. Real courses turn;
# and runners on one course share its heading, so a per-runner random angle
# never represented anything real. Now the convective effect is averaged over
# all headings: v_eff = (mean over angles of v_rel^0.62)^(1/0.62), with
# JOS-3's exponent 0.62. The per-runner angle is kept for WIND_ANGLE_AVERAGED
# = False (e.g. a straight point-to-point course with known heading).
WIND_ANGLE_AVERAGED = True
_WIND_ANGLES = np.linspace(0.0, 2.0 * np.pi, 72, endpoint=False)


def compute_relative_wind(v_ambient: float, v_running: float, angle_rad: float) -> float:
    """
    Relative ("apparent") wind speed experienced by a moving runner.

    [2026-07] Previously HESTIA fed JOS-3 ambient wind alone
    (max(0.1, wind_1_5m)), discarding the runner's own forward speed
    entirely -- select_met_activity() computed it but the caller threw it
    away (`_`). Verified this created a large, direction-dependent
    asymmetry between calm-wind and windy race days (Falmouth 2003 vs.
    2015): with ambient wind alone, JOS-3's convective coefficient
    differed by ~47% between the two days; once the runner's own speed is
    included, that gap narrows to 8-19% depending on assumed wind
    direction, more consistent with the two days' documented relative
    EHS severity.

    Direction is not tracked anywhere in this pipeline (no wind-direction
    field is fetched by Thermopoulos_Data_Engine.py, and course heading
    is not modelled) -- so the true headwind/tailwind component for a
    specific participant on a specific day is fundamentally unknown here.
    Rather than pick one deterministic assumption (which can flip the
    sign of a comparison -- verified: assuming a pure tailwind for both
    2003 and 2015 reverses which day looks worse relative to assuming a
    pure headwind), each participant is given their own sampled relative
    angle (AdultParticipantProfile.wind_angle_rad, Uniform[0, 2*pi)), and
    the full law-of-cosines apparent-wind formula is used:

        v_rel = sqrt(v_run^2 + v_wind^2 - 2*v_run*v_wind*cos(angle))

    This is standard sailing/aerodynamics practice (see e.g. the Pugh
    1971 / Davies 1980 treadmill-in-wind-tunnel running studies, which
    established that a runner's own forward motion generates a
    self-induced relative airflow even in still air, and that the true
    relative airflow for a moving body in wind is the vector combination
    of the two). Averaged over a Uniform[0, 2*pi) angle, E[v_rel^2] =
    v_run^2 + v_wind^2 exactly (since E[cos(angle)] = 0), so the
    population mean recovers the simpler Pythagorean estimate used
    during initial testing, while individual participants now span the
    full headwind-to-tailwind range -- representing the real uncertainty
    as population spread instead of a single, arbitrarily chosen point
    estimate. This also matches Air speed and direction affect metabolic
    and thermoregulatory responses during walking and running (J Appl
    Physiol, 2024), which found wind-direction effects on metabolic cost
    fall within ordinary inter-individual variation below ~4 m/s ambient
    wind -- exactly the regime both Falmouth race days are in.

    Caveat carried over from that same paper: the asymmetry Davies (1980)
    found between headwind cost and tailwind benefit applies to
    aerodynamic drag (which scales with v^2); it has NOT been separately
    established for JOS-3's convective heat transfer coefficient (which
    scales with v^0.62) -- so no such asymmetry correction is applied
    here beyond what the law-of-cosines formula itself gives.

    Parameters
    ----------
    v_ambient : float
        Ambient wind speed at body height (m/s), e.g. wind_1_5m.
    v_running : float
        The participant's own forward speed (m/s).
    angle_rad : float
        Angle between the ambient wind direction and the participant's
        heading (radians). 0 = pure tailwind, pi = pure headwind.

    Returns
    -------
    float
        Relative (apparent) wind speed (m/s), floored at 0.1 for
        numerical safety (matches the previous minimum floor).
    """
    if WIND_ANGLE_AVERAGED:
        # [2026-10-19, night] Course heading is not constant: average JOS-3's
        # convective effect (h_c ~ v^0.62) over all headings instead of using
        # one fixed angle per runner for the whole race. See
        # WIND_ANGLE_AVERAGED for why.
        th = _WIND_ANGLES
        v = np.sqrt(np.maximum(0.0, v_running**2 + v_ambient**2 - 2 * v_running * v_ambient * np.cos(th)))
        v_eff = float(np.mean(v ** 0.62)) ** (1.0 / 0.62)
        return max(0.1, v_eff)
    v_rel_sq = v_running**2 + v_ambient**2 - 2 * v_running * v_ambient * np.cos(angle_rad)
    return max(0.1, float(np.sqrt(max(0.0, v_rel_sq))))


# =============================================================================
#  ACTIVITY / CLOTHING LOOKUP TABLES (unchanged from rev09)
# =============================================================================

MET_ACTIVITIES_ADULT = {
    1:  {"description": "Jogging, 8 km/h (recreational)",             "met": 8.3,  "speed_kmh": 8.0},
    2:  {"description": "Running, 9.6 km/h (recreational)",           "met": 9.8,  "speed_kmh": 9.6},
    3:  {"description": "Running, 11.2 km/h (recreational)",          "met": 11.0, "speed_kmh": 11.2},
    4:  {"description": "Running, 12.8 km/h (recreational)",          "met": 11.8, "speed_kmh": 12.8},
    5:  {"description": "Trail running, moderate pace (recreational)", "met": 9.0,  "speed_kmh": 9.0},
    6:  {"description": "Running, 13.8 km/h (professional)",          "met": 12.3, "speed_kmh": 13.8},
    7:  {"description": "Running, 16 km/h (professional)",            "met": 14.5, "speed_kmh": 16.0},
    8:  {"description": "Running, 19.2 km/h (professional)",          "met": 16.0, "speed_kmh": 19.2},
    9:  {"description": "Interval sprints, high intensity (professional)", "met": 18.0, "speed_kmh": 20.0},
    10: {"description": "Marathon, competition pace (professional)",   "met": 13.5, "speed_kmh": 15.0},
    11: {"description": "Running, average (general)",                  "met": 10.0, "speed_kmh": 10.0},
    12: {"description": "Walking, 3.2 km/h (slow, recreational)",     "met": 2.8,  "speed_kmh": 3.2},
    13: {"description": "Walking, 4.0 km/h (moderate, recreational)", "met": 3.5,  "speed_kmh": 4.0},
    14: {"description": "Walking, 4.8 km/h (brisk, recreational)",    "met": 4.3,  "speed_kmh": 4.8},
    15: {"description": "Walking, 5.6 km/h (fast, fitness)",          "met": 5.0,  "speed_kmh": 5.6},
    16: {"description": "Walking, 6.4 km/h (very fast, fitness)",     "met": 6.0,  "speed_kmh": 6.4},
    17: {"description": "Walking uphill, 4.0 km/h (3-5% incline)",   "met": 5.3,  "speed_kmh": 4.0},
    18: {"description": "Walking with backpack, 4.0 km/h (moderate)", "met": 4.5,  "speed_kmh": 4.0},
    19: {"description": "Sitting outdoors",                            "met": 1.2,  "speed_kmh": 0.0},
}

MET_ACTIVITIES_CHILD = {
    1:  {"description": "Sitting quietly (e.g., classroom)",            "met": 1.3, "speed_kmh": 0.0},
    2:  {"description": "Walking slowly (e.g., to school)",             "met": 2.5, "speed_kmh": 3.0},
    3:  {"description": "Light play (e.g., sandbox, standing activity)","met": 3.0, "speed_kmh": 1.0},
    4:  {"description": "Active play / General gymnastics",             "met": 4.0, "speed_kmh": 2.0},
    5:  {"description": "Running / Very active play (e.g., tag)",       "met": 6.0, "speed_kmh": 6.0},
    6:  {"description": "Walking, brisk pace",                          "met": 3.8, "speed_kmh": 5.0},
    7:  {"description": "Cycling, leisurely pace",                      "met": 4.0, "speed_kmh": 12.0},
    8:  {"description": "Soccer, casual / kickabout",                   "met": 7.0, "speed_kmh": 7.0},
    9:  {"description": "Basketball, shooting baskets",                  "met": 4.5, "speed_kmh": 3.0},
    10: {"description": "Jogging, moderate pace",                       "met": 8.0, "speed_kmh": 9.0},
}

CLO_OPTIONS_ADULT = {
    1: {"description": "Shorts and T-shirt (summer)",              "clo": 0.2},
    2: {"description": "Shorts and tank top (very light)",         "clo": 0.1},
    3: {"description": "Long pants and T-shirt (mild weather)",    "clo": 0.4},
    4: {"description": "Long pants and long sleeves (cool)",       "clo": 0.6},
    5: {"description": "Running jacket and long pants (cold)",     "clo": 0.8},
    6: {"description": "Thermal underwear and jacket (winter)",    "clo": 1.0},
}

CLO_OPTIONS_CHILD = {
    1: {"description": "Shorts and T-shirt (summer)",              "clo": 0.2},
    2: {"description": "Shorts and tank top (very light)",         "clo": 0.1},
    3: {"description": "School uniform (trousers/skirt, polo)",    "clo": 0.4},
    4: {"description": "Tracksuit / long sleeves (cool weather)",  "clo": 0.6},
    5: {"description": "Light jacket and long pants (cold)",       "clo": 0.8},
}

LIVEABILITY_LIMITS = {
    'young_adult_shaded': {
        (25, 90): 5.0, (25, 50): 7.0, (25, 20): 8.4,
        (30, 90): 3.5, (30, 50): 5.5, (30, 20): 7.0,
        (35, 90): 1.5, (35, 50): 4.0, (35, 20): 5.8,
        (40, 70): 1.5, (40, 40): 3.0, (40, 10): 5.0,
        (45, 40): 1.5, (45, 10): 3.8,
        (50, 20): 2.0, (50, 10): 3.0,
    },
    'older_adult_shaded': {
        (25, 90): 4.2, (25, 50): 5.9, (25, 20): 6.8,
        (30, 90): 2.8, (30, 50): 4.5, (30, 20): 5.5,
        (35, 90): 1.5, (35, 50): 3.0, (35, 20): 4.2,
        (40, 60): 1.5, (40, 30): 2.2, (40, 10): 3.4,
        (45, 25): 1.5, (45, 10): 2.5,
        (50, 10): 1.8,
    },
}


def get_liveability_threshold(temp, rh, age):
    """Gets M_max (maximum safe MET) from Vanos et al. (2023) lookup table.

    [fix] LIVEABILITY_LIMITS' lowest documented temperature is 25C -- this is
    a HEAT-specific liveability table, not a general fitness/fatigue limit,
    so it has no meaningful entries below that. The original nearest-
    neighbour lookup silently extrapolated any temp<25C to the (25, X) row
    regardless of how far below 25C the actual temperature was -- e.g. at
    ~20C (an entirely ordinary mild race day) this returned M_max as low as
    ~5-7, well below common MET choices, flagging ~100% of a population
    "unliveable" for perfectly safe activity. Verified against a real case:
    Amsterdam 2024-09-22, air temp 19.9-23.9C throughout, MET~10 requested
    -> every timestep fell below 25C and got silently clamped to the
    coldest row, producing percent_unliveable~100% despite individually
    unremarkable simulated T_rect (mean 39.3C) and collapse risk (mean
    0.15%). Below 25C there is no heat-driven ceiling in this table's
    domain, so return a high, effectively non-binding M_max (any ordinary
    exercise MET, including the highest CLI option of 18.0, stays well
    under it) instead of extrapolating.
    """
    if temp < 25.0:
        return 20.0
    profile = 'older_adult_shaded' if age > 65 else 'young_adult_shaded'
    data = LIVEABILITY_LIMITS[profile]
    closest_point = min(data.keys(), key=lambda k: abs(k[0] - temp) + abs(k[1] - rh) / 5)
    return data[closest_point]


def calculate_uhi_effect(population, wind_speed, is_daytime):
    """UHI effect (Oke 1973). Returns delta-T in °C."""
    if population < 1000:
        return 0.0
    uhi_base = 2.0 * math.log10(population) - 4.0
    uhi_base = max(0.0, min(8.0, uhi_base))
    wind_factor = max(0.0, 1.0 - 0.1 * wind_speed)
    time_factor = 0.5 if is_daytime else 1.0
    return round(uhi_base * wind_factor * time_factor, 2)


# =============================================================================
#  POPULATION GENERATION (rev10 -- replaces simulate_runner)
#
#  DESIGN RATIONALE
#  ----------------
#  The previous simulate_runner() sampled VO2max and MET independently, which
#  produced physiologically impossible combinations: a runner with VO2max=25
#  assigned a MET implying 120% VO2max. About 18.7% of the simulated
#  population exceeded 100% VO2max (identified in rev09 analysis).
#
#  The new generate_base_population() uses a CAUSAL SAMPLING ORDER:
#
#    Step 1  gender          -- independent; 58% male / 42% female
#                              (Western-European major running events, RunRepeat 2023)
#    Step 2  age             -- N(40, 10), clipped [18, 65]
#                              (median age of recreational marathon runners, NL)
#    Step 3  VO2max          -- conditioned on age AND gender
#                              Base values: male N(52,8), female N(44,7)
#                              Age correction: -0.5 mL/kg/min per year > 35
#                              Ref: Scharhag-Rosenberger (2010); Tanaka (2001)
#    Step 4  height          -- conditioned on gender
#                              male N(1.78, 0.07), female N(1.65, 0.06)
#                              Ref: RIVM NL anthropometric data
#    Step 5  weight          -- conditioned on height + gender
#                              BMI filter [18.0, 32.0] active
#                              Ref: Tanda & Knechtle (2013)
#    Step 6  pct_vo2max      -- [rev13] CAUSAL: fraction of VO2max at event pace.
#                              Deterministic via Daniels-Gilbert inversion:
#                                pct = VO2_at_event_pace / vo2max_i + noise(0.04)
#                              Resolves the Pearl causal Markov violation from rev10-rev12.
#                              EVENT_PACE_MIN_PER_KM is the driving parameter.
#    Step 7  sweat_factor    -- conditioned on acclimatization_factor
#    Step 8  thirst_threshold-- conditioned on acclimatization_factor
#    Step 9  temp/rh_var     -- independent (perceptual noise)
#    Step 10 mf_score        -- independent (motivation)
#
#  MET COMPUTATION (on-the-fly, not stored as a population parameter)
#  ----------------------------------------------------------------------
#  final_met = vo2max * pct_vo2max / VO2MAX_TO_MET_FACTOR
#
#  This guarantees, by construction, that %VO2max == pct_vo2max (clipped
#  to [0.60, 0.92]), so physiologically impossible combinations cannot
#  occur. training_factor deterministically shifts the mean of pct_vo2max
#  downward (better-trained runners = lower fraction), consistent with
#  the literature (Joyner 1991).
#
#  FIXED SEED SUPPORT
#  ------------------
#  Use random_seed for reproducible scenario comparisons.
#  The same seed always yields the same N runners. Save the population
#  as a .pkl with save_population() for reuse without re-sampling.
# =============================================================================

def generate_base_population(
    n_simulations: int = 5000,
    training_factor: float = 0.0,
    acclimatization_factor: float = 0.0,
    random_seed: int = None,
    met_value: float = None,
    sample_pace: bool = False,
    event_dist_km: float = 16.1,
) -> list:
    """
    Generate a fixed base population of adult marathon runners for Monte Carlo
    simulation.

    This function replaces simulate_runner() (rev09) with a causally correct
    sampling architecture. See module docstring (rev10) for full design
    rationale.

    The critical difference from rev09 is that MET is NOT sampled here.
    Instead, pct_vo2max (the fraction of VO2max at race pace) is sampled and
    stored. The actual MET is computed on-the-fly in
    calculate_indices_jos3_adult() as:
        final_met = vo2max * pct_vo2max / VO2MAX_TO_MET_FACTOR

    This guarantees that no participant can exceed their own VO2max by
    construction (was ~18.7% of population in rev09 due to independent
    VO2max and MET sampling).

    Parameters
    ----------
    n_simulations : int
        Target number of valid participants to generate.
    training_factor : float in [0.0, 1.0]
        Training status. Shifts mu of pct_vo2max downward (trained runners
        sustain a lower %VO2max at race pace for the same absolute pace).
        Effect: mu_pct -= training_factor * 0.08 (max 8 percentage points).
    acclimatization_factor : float in [0.0, 1.0]
        Heat acclimatization. Shifts sweat_factor up and thirst_threshold down.
    random_seed : int or None
        If provided, np.random and random are seeded before sampling.
        Use the same seed for reproducible scenario comparisons.
    met_value : float or None
        [suite-integration fix] The absolute MET of the chosen activity
        (e.g. 3.5 for a moderate walk, 8.3 for recreational running -- see
        MET_ACTIVITIES_ADULT). When given, each participant's %VO2max is
        derived from THIS activity's VO2 demand relative to their own
        VO2max:
            vo2_at_event_pace = met_value * VO2MAX_TO_MET_FACTOR
            pct_vo2max_det    = vo2_at_event_pace / vo2max
        This makes the population's simulated intensity match whatever
        activity was actually selected (walking, jogging, ...), for any
        `duration_hours`, instead of always assuming a fixed marathon-race
        pace regardless of the chosen activity or event length (the previous
        behaviour, kept below as a fallback when met_value is None).
        [flagged for review] The pct_vo2max clip range below (was [0.55,
        0.95], calibrated for marathon-race effort) is widened to [0.15,
        0.95] so that light activities (e.g. walking) aren't artificially
        floored into a marathon-race effort band. This widening is an
        engineering consequence of generalising the same mechanism beyond
        running, not an independently validated number -- please review it,
        the author, especially the lower bound.
    sample_pace : bool
        [2026-09] When True, each participant gets their OWN pace (via
        sample_recreational_pace_min_per_km(), gender-conditioned) instead
        of the single shared met_value -- their own MET (derived from that
        pace via _acsm_met_from_pace()) and their own duration_hours
        (pace * event_dist_km) follow from it. This is what makes exposure
        DURATION vary with who someone is, not just how hard the shared
        pace feels to them (which pct_vo2max already did on its own).
        When False (default), behaviour is unchanged from before this
        parameter existed: every participant shares met_value, and
        duration_hours is filled with a placeholder (see run_monte_carlo_
        adult(), which only slices interp_data per-person when sample_pace
        was actually used to generate the population).
    event_dist_km : float
        Event distance in km, used only when sample_pace=True to convert
        each participant's own pace into their own duration_hours. Default
        16.1 km (Dam tot Damloop) -- matches Klimatos_ClimateShift.py's and
        run_hestia.py's own EVENT_DIST_KM/event distance default.

    Returns
    -------
    list of AdultParticipantProfile
        Successfully generated profiles (may be fewer than n_simulations
        if BMI filter rejects many candidates; max 30 attempts per profile).

    References
    ----------
    Scharhag-Rosenberger F et al. (2010) J Sci Med Sport 13:167-172.
    Tanaka H et al. (2001) J Am Coll Cardiol 37:153-156.
    Tanda G & Knechtle B (2013) J Hum Kinet 38:169-177.
    Joyner MJ (1991) J Appl Physiol 70:683-687.
    Jones AM & Carter H (2000) Sports Med 29:373-386.
    RunRepeat European marathon statistics (2023).
    """
    if random_seed is not None:
        np.random.seed(random_seed)
        random.seed(random_seed)

    valid_simulations = []
    attempts = 0
    max_attempts = n_simulations * 30  # generous budget for BMI filter

    print(f"\nGenerating base population (N={n_simulations}, seed={random_seed}, "
          f"training_factor={training_factor:.2f}, "
          f"acclimatization_factor={acclimatization_factor:.2f})...")

    while len(valid_simulations) < n_simulations and attempts < max_attempts:
        attempts += 1

        # ------------------------------------------------------------------
        # STEP 1: Gender
        # ------------------------------------------------------------------
        # West-European large running events: ~58% male, ~42% female.
        # Source: RunRepeat European marathon statistics (2023).
        gender = np.random.choice(["male", "female"], p=[0.58, 0.42])

        # ------------------------------------------------------------------
        # STEP 1b: Body fat percentage -- sampled per individual (fix)
        # ------------------------------------------------------------------
        # [suite-integration fix] Previously a fixed 25% (female) / 15% (male)
        # applied identically to every participant of that sex, with zero
        # individual variation. Verified in isolation (identical height/
        # weight/MET/environment, JOS-3 only) that this alone produces a
        # ~0.22°C higher core temperature for the female value -- i.e. most
        # of the population-level sex gap in T_rect traced back to this fixed
        # split, not to the %VO2max mechanism. Real populations show
        # substantial spread and overlap between sexes.
        #
        # [correction] The means below were first carried over unchanged from
        # the old fixed values (15%/25%, a 10-point sex gap) -- that gap was
        # never itself literature-checked. Cross-checked against published
        # recreational-marathon-runner body-fat data (Nikolaidis, Vancini,
        # Andrade, de Lira & Knechtle 2021, BioMed Research International
        # 2021:3717562, BIA-measured, n=32 women/134 men; consistent with an
        # independent sample in Knechtle & Tanda 2013, 16.3±5.6% men): the
        # real sex gap is only ~2 percentage points (19.6% women, 17.7% men),
        # not 10. The SD used here (4%/5%) already matched the published SD
        # (4.7%/4.0%) closely, so only the means are corrected.
        # [flagged for review] This reference population is marathon-runner-
        # specific; HESTIA's modelled population is broader (VO2max down to
        # ~24 mL/kg/min, well below typical marathon finishers), so the true
        # mean may sit somewhat higher for a general recreational/event
        # population -- but the sex GAP itself should stay far smaller than
        # the original 10-point assumption. Please review.
        if gender == "male":
            body_fat_pct = float(np.clip(np.random.normal(loc=17.7, scale=4.0), 6.0, 32.0))
        else:
            body_fat_pct = float(np.clip(np.random.normal(loc=19.6, scale=4.7), 8.0, 36.0))

        # ------------------------------------------------------------------
        # STEP 2: Age
        # ------------------------------------------------------------------
        # Recreational marathon runners: median ~40, skewed right (more older
        # runners than younger). N(40, 10) clipped [18, 65] approximates the
        # observed finish-start age distribution for NL events (DtD, AMS, RTD).
        age = int(np.clip(np.random.normal(loc=40.0, scale=10.0), 18, 65))

        # ------------------------------------------------------------------
        # STEP 3: VO2max -- conditioned on age AND gender
        # ------------------------------------------------------------------
        # Base values for recreational marathon finishers:
        #   Male:   N(52, 8) mL/kg/min
        #   Female: N(44, 7) mL/kg/min
        # These reflect self-selected mass-event runners, not general population.
        # Ref: Scharhag-Rosenberger et al. (2010).
        #
        # Age correction: -0.5 mL/kg/min per year after age 35.
        # Ref: Tanaka et al. (2001) J Am Coll Cardiol 37:153.
        # The correction is applied to the distribution mean, not post-hoc,
        # so the variance is preserved across age groups.
        if gender == "male":
            vo2max_base_mu = 52.0
            vo2max_sigma   = 8.0
            vo2max_clip    = (28.0, 78.0)
        else:
            vo2max_base_mu = 44.0
            vo2max_sigma   = 7.0
            vo2max_clip    = (24.0, 68.0)

        # [2026-09] An earlier version of this fix raised vo2max_clip's
        # floor here (derived from the event's own time limit) when
        # sample_pace was active. Superseded: clipping vo2max to a fixed
        # floor pushed every below-floor draw to exactly the same value --
        # for women specifically, whose mean (44.0) sits only 0.27 SD above
        # the derived floor (~42.1), this clipped 56.7% of the female
        # population to one identical vo2max, replacing a smooth
        # distribution tail with an artificial spike. Replaced by rejecting
        # the (age, gender, vo2max, pace) combination outright when it
        # would require an implausible effort (see the pct_vo2max_det
        # check below, after pace is sampled) -- this discards implausible
        # draws rather than distorting the accepted ones, so the accepted
        # vo2max distribution keeps its original smooth shape, merely
        # truncated by the SAME mechanism (rejection) already used
        # throughout this loop for other implausible combinations (see
        # e.g. the BMI check above).

        # Deterministic age correction (Tanaka 2001)
        age_correction = 0.5 * max(0, age - 35)
        vo2max_mu = vo2max_base_mu - age_correction

        vo2max = float(np.clip(
            np.random.normal(loc=vo2max_mu, scale=vo2max_sigma),
            vo2max_clip[0], vo2max_clip[1]
        ))

        # ------------------------------------------------------------------
        # STEP 4: Height -- conditioned on gender
        # ------------------------------------------------------------------
        # Reference: RIVM NL antropometrische data; Tolfrey & Pilcher (2013).
        if gender == "male":
            height = float(np.clip(np.random.normal(loc=1.78, scale=0.07), 1.60, 2.00))
        else:
            height = float(np.clip(np.random.normal(loc=1.65, scale=0.06), 1.48, 1.85))

        # ------------------------------------------------------------------
        # STEP 5: Weight -- conditioned on height and gender (BMI target)
        # ------------------------------------------------------------------
        # Recreational marathon runners have lower BMI than general population.
        # Target BMI range: [18.0, 30.0] (active runner population).
        # Ref: Tanda & Knechtle (2013) J Hum Kinet 38:169-177.
        # BMI target mu: 23.0 (male), 21.5 (female).
        if gender == "male":
            bmi_target = np.clip(np.random.normal(loc=23.0, scale=2.0), 18.0, 30.0)
        else:
            bmi_target = np.clip(np.random.normal(loc=21.5, scale=2.0), 18.0, 28.0)

        weight = float(np.clip(bmi_target * height ** 2, 45.0, 105.0))

        # BMI filter: hard rejection for implausible combinations.
        # NOTE (rev11): bmi_target is already clipped to [18,30]/[18,28], so
        # the weight derived from it will also satisfy BMI [18,30] in the
        # absence of the weight clip. The weight clip (45--105 kg) can
        # distort BMI for extreme height values (very tall/very light runners),
        # which is the actual path that triggers this rejection. The check is
        # retained to guard against such edge cases.
        bmi = weight / (height ** 2)
        if not (18.0 <= bmi <= 32.0):
            continue

        # ------------------------------------------------------------------
        # STEP 6: %VO2max at race pace -- conditioned on VO2max via event pace
        # ------------------------------------------------------------------
        # [rev13] CAUSAL FIX (P3): pct_vo2max is now derived deterministically
        # from the participant's own VO2max and the event pace, resolving the
        # Pearl Causal Markov violation present in rev10-rev12.
        #
        # Architecture:
        #   1. Compute the VO2 demand at the event pace using Daniels-Gilbert.
        #   2. Divide by this participant's VO2max to get their individual %VO2max.
        #   3. Add Gaussian noise (sigma=0.04) to represent hardloopeconomie
        #      variability (Barnes & Kilding 2015: CV ~4-6% in homogeneous groups).
        #
        # The training_factor mu-shift from rev10-rev12 (-0.08 * tf) is REMOVED
        # here. Economy effects remain via the step-2 training_offset in
        # calculate_indices_jos3_adult() (coefficient 0.05, rev11 unchanged).
        #
        # EVENT_PACE_MIN_PER_KM is a module-level constant (default 6.0 min/km).
        # Override it before calling generate_base_population() for event-specific
        # calibration (e.g., Boston: 5.8 min/km; DtD: 6.5 min/km).
        #
        # Ref: Joyner (1991); Jones & Carter (2000); Barnes & Kilding (2015).
        #vo2_at_event_pace     = _daniels_gilbert_vo2_at_pace(EVENT_PACE_MIN_PER_KM)
        #pct_vo2max_det        = vo2_at_event_pace / vo2max   # physiologically conditioned

        if sample_pace and USE_DURATION_INTENSITY_CEILING:
            # [2026-10-14] Demographics-preserving redraw. Previously any
            # (vo2max, pace) combination that was too hard for this person
            # rejected the WHOLE draw (gender, age, height, weight too).
            # Because older and female participants are rejected more
            # often, that silently shifted the field's demographics
            # (verified, marathon n=5000 seed 42: male share 58% -> 62%,
            # median age 40 -> 37; with the new duration ceiling it would
            # have become 68% / 36). Here only the fitness/pace pair is
            # redrawn for the SAME person (same gender/age/body), so the
            # field composition stays at its documented targets; the
            # accepted runners simply pair with a fitness that can sustain
            # their pace. Whole-draw rejection remains as fallback only.
            _ok = False
            for _try in range(50):
                if _try > 0:
                    vo2max = float(np.clip(
                        np.random.normal(loc=vo2max_mu, scale=vo2max_sigma),
                        vo2max_clip[0], vo2max_clip[1]))
                vo2max_z = _pace_fitness_z(vo2max, vo2max_base_mu, vo2max_mu, vo2max_sigma)
                pace_this_runner = sample_recreational_pace_min_per_km(
                    gender, event_dist_km, vo2max_z=vo2max_z)
                individual_met = _acsm_met_from_pace(pace_this_runner)
                duration_hours_this_runner = pace_this_runner * event_dist_km / 60.0
                vo2_at_event_pace = individual_met * VO2MAX_TO_MET_FACTOR
                if (vo2_at_event_pace / vo2max) <= min(
                        0.95, sustainable_vo2max_fraction(duration_hours_this_runner * 60.0)):
                    _ok = True
                    break
            if not _ok:
                continue
        elif sample_pace:
            # [2026-09] Full per-person pace: own MET AND own exposure
            # duration, instead of a shared met_value that only let
            # pct_vo2max (perceived relative effort) vary by person while
            # everyone ran the same absolute pace for the same duration.
            # [2026-09, correlation fix] vo2max_z uses the CLIPPED vo2max
            # value above, not the pre-clip draw -- a minor approximation
            # (the z-score is nominally off for anyone actually clipped at
            # the vo2max_clip bounds), accepted because clipping is rare
            # here and preserving the pre-clip draw across this function
            # would need a larger restructure for a negligible gain.
            vo2max_z = _pace_fitness_z(vo2max, vo2max_base_mu, vo2max_mu, vo2max_sigma)
            pace_this_runner = sample_recreational_pace_min_per_km(
                gender, event_dist_km, vo2max_z=vo2max_z)
            individual_met = _acsm_met_from_pace(pace_this_runner)
            duration_hours_this_runner = pace_this_runner * event_dist_km / 60.0
            vo2_at_event_pace = individual_met * VO2MAX_TO_MET_FACTOR
        elif met_value is not None:
            # [fix] Derive the VO2 demand directly from the chosen activity's
            # absolute MET, instead of assuming a fixed marathon-race pace
            # regardless of what activity was actually selected. This is the
            # same relationship calculate_indices_jos3_adult() uses in
            # reverse (final_met = vo2max * pct_vo2max / VO2MAX_TO_MET_FACTOR),
            # so a participant sampled this way who then gets pct_vo2max_det
            # exactly (no noise) would simulate at exactly met_value.
            vo2_at_event_pace = met_value * VO2MAX_TO_MET_FACTOR
            pace_this_runner = None
            duration_hours_this_runner = None
        else:
            # Backward-compatible fallback: fixed marathon-pace assumption
            # (unchanged from rev13/rev14), used only when no activity/MET
            # was specified by the caller.
            EVENT_PACE_M = 5  # was 4.97 min/km  → pct_det mediaan mannen ~0.74
            EVENT_PACE_F = 6  # was 5.68min/km  → pct_det mediaan vrouwen ~0.74
            pace_this_runner = EVENT_PACE_M if gender == "male" else EVENT_PACE_F
            vo2_at_event_pace = _daniels_gilbert_vo2_at_pace(pace_this_runner)
            duration_hours_this_runner = None
            if USE_DURATION_INTENSITY_CEILING:
                # [2026-10-14] Same duration ceiling for this fixed-marathon-
                # pace path, which is the one intercept_estimation.py uses for
                # the Boston (ehs) calibration population. Without it that
                # population still had 13.5% of runners at >=85% VO2max for
                # 3.5-4.2 h. Duration = this runner's fixed pace over a
                # marathon; only vo2max is redrawn (same person).
                _fixed_dur_h = pace_this_runner * _MARATHON_DIST_KM / 60.0
                _ceil_fixed = sustainable_vo2max_fraction(_fixed_dur_h * 60.0)
                for _try in range(50):
                    if vo2_at_event_pace / vo2max <= _ceil_fixed:
                        break
                    vo2max = float(np.clip(
                        np.random.normal(loc=vo2max_mu, scale=vo2max_sigma),
                        vo2max_clip[0], vo2max_clip[1]))
                else:
                    continue
        pct_vo2max_det = vo2_at_event_pace / vo2max

        # [2026-09] Reject rather than clip: a deterministic requirement
        # above 95% of this person's OWN vo2max is not "very hard", it is
        # implausible to actually sustain for the ~100+ minute durations
        # this suite models (see TECHNICAL_REFERENCE.md Sec 4.6.2's
        # duration/%VO2max literature review -- even highly trained
        # athletes sustain closer to 78-92% over comparable durations, let
        # alone recreational ones). Previously this was silently clipped
        # to 0.95 downstream, which (a) let physiologically impossible
        # combinations (some exceeded 100% of the person's own maximum)
        # into the accepted population under a falsely-plausible-looking
        # number, and (b) silently changed which MET was actually
        # simulated for that person to whatever 95% of THEIR vo2max
        # implies, inconsistent with their own recorded pace_min_per_km.
        # Rejecting the whole (age, gender, vo2max, pace) draw and letting
        # the surrounding while-loop redraw fresh values -- the same
        # mechanism already used for e.g. the BMI check above -- avoids
        # both problems: no impossible combination is ever accepted, and
        # the accepted vo2max distribution keeps its natural smooth shape
        # (merely truncated by rejection) instead of the artificial spike
        # a hard floor clip produced (was 56.7% of women at one identical
        # value; see TECHNICAL_REFERENCE.md Sec 4.6.2).
        if pct_vo2max_det > 0.95:
            continue

        # [2026-10-14] Duration-dependent ceiling (see
        # sustainable_vo2max_fraction()). Only when this participant's own
        # duration is known (sample_pace=True).
        pct_ceiling = 0.95
        if (USE_DURATION_INTENSITY_CEILING and sample_pace
                and duration_hours_this_runner):
            pct_ceiling = sustainable_vo2max_fraction(duration_hours_this_runner * 60.0)
            if pct_vo2max_det > pct_ceiling:
                continue
        elif (USE_DURATION_INTENSITY_CEILING and not sample_pace
                and met_value is None):
            pct_ceiling = _ceil_fixed   # fixed-marathon-pace path (see above)

        pct_vo2max_sigma      = 0.04   # economy variability (narrower than rev12's 0.05)
        pct_vo2max = float(np.random.normal(loc=pct_vo2max_det, scale=pct_vo2max_sigma))
        if pct_ceiling < 0.95:
            # [2026-10-14] Truncated (not clipped) noise: redraw the economy
            # noise when it pushes the effective intensity above the
            # ceiling, so no artificial pile-up forms at the ceiling value.
            for _ in range(20):
                if pct_vo2max <= pct_ceiling:
                    break
                pct_vo2max = float(np.random.normal(loc=pct_vo2max_det, scale=pct_vo2max_sigma))
        pct_vo2max = float(np.clip(pct_vo2max, 0.15, pct_ceiling))

        # ------------------------------------------------------------------
        # STEP 7: Sweat factor -- conditioned on acclimatization_factor
        # ------------------------------------------------------------------
        # Acclimatized runners sweat earlier and at higher rates (higher factor).
        # Ref: Periard et al. (2016) Comprehensive Physiology.
        # [2026-11-01] The acclimation effect on sweating now sits in JOS-3
        # itself (jos3_leeftijd.ACCLIM_SWEAT_GAIN, +20 %, with cooling); here it
        # was +37.5 % water loss without cooling (was 0.8 + 0.3 x acclimatisation).
        sweat_loc = 0.8
        sweat_factor = float(np.clip(
            np.random.normal(loc=sweat_loc, scale=0.15),
            0.4, 1.5
        ))

        # ------------------------------------------------------------------
        # STEP 8: Thirst threshold -- conditioned on acclimatization_factor
        # ------------------------------------------------------------------
        # Acclimatized runners drink at lower body-weight-loss thresholds.
        thirst_upper_bound = 2.5 - (acclimatization_factor * 1.0)  # range [1.5, 2.5]
        thirst_threshold = float(np.random.uniform(1.0, max(1.1, thirst_upper_bound)))

        # ------------------------------------------------------------------
        # STEP 9: Environmental perception (individual noise)
        # ------------------------------------------------------------------
        temp_variation = float(np.random.normal(loc=0.0, scale=1.5))
        rh_variation   = float(np.random.normal(loc=0.0, scale=3.0))

        # ------------------------------------------------------------------
        # STEP 10: Motivational factor (independent)
        # ------------------------------------------------------------------
        mf_score = float(np.random.uniform(0.0, 1.0))

        # ------------------------------------------------------------------
        # STEP 11: Individual pacing gain K_p  [rev14-A]
        # ------------------------------------------------------------------
        # K_p is the proportional gain of the voluntary pacing feedback loop:
        # MET reduction = K_p * max(0, T_rect - T_RECT_PACING_THRESHOLD).
        # In rev13, K_p was fixed at 0.10 for all participants.
        # In rev14, K_p is normally distributed across the population to
        # reflect individual variation in interoceptive awareness and
        # motivation (Flouris 2024).
        #
        # K_p ~ N(0.10, 0.04), clipped [0.00, 0.25]
        # Participants with K_p ≈ 0 are the highest EHS risk group:
        # they do not reduce pace despite rising T_rect.
        #
        # NSAID flag: ~25% of recreational marathon runners use NSAID before
        # or during the race (Joslin 2013: 26% during; Kuster 2013: 49%
        # analgesics before the start). [2026-10-16] K_P_NSAID_FACTOR = 1.0:
        # the flag no longer changes pacing -- the earlier "halved pacing via
        # PGE2 suppression" mechanism is not supported in humans (see the
        # K_P_NSAID_FACTOR comment). The flag is kept for export. The binomial
        # draw is kept so the random stream (and thus every population) is
        # unchanged.
        nsaid_gebruik = bool(np.random.binomial(1, NSAID_PREVALENTIE))
        kp_base       = float(np.clip(
            np.random.normal(loc=K_P_PACING, scale=K_P_SIGMA),
            0.0, 0.25
        ))
        kp_pacing = kp_base * (K_P_NSAID_FACTOR if nsaid_gebruik else 1.0)

        # [2026-07] Individual relative wind angle -- see compute_relative_wind()
        # docstring for the full rationale. Wind direction and course heading
        # are not tracked anywhere in this pipeline, so the true headwind/
        # tailwind component for any given participant is unknown; sampled
        # per participant so the population spread reflects that unknown
        # direction as spread rather than as a single arbitrary point estimate.
        wind_angle_rad = float(np.random.uniform(0.0, 2 * np.pi))

        # Append valid profile
        valid_simulations.append(AdultParticipantProfile(
            height           = height,
            weight           = weight,
            age              = age,
            gender           = gender,
            body_fat_pct     = body_fat_pct,
            vo2max           = vo2max,
            pct_vo2max       = pct_vo2max,
            temp_variation   = temp_variation,
            rh_variation     = rh_variation,
            mf_score         = mf_score,
            sweat_factor     = sweat_factor,
            thirst_threshold = thirst_threshold,
            kp_pacing        = kp_pacing,        # [rev14-A] individual pacing gain
            nsaid_gebruik    = nsaid_gebruik,    # [rev14-A] NSAID flag
            wind_angle_rad   = wind_angle_rad,   # [2026-07] individual relative wind angle
            # [2026-09] Only individually meaningful when sample_pace=True;
            # 0.0 otherwise -- run_monte_carlo_adult() checks sample_pace
            # (not these fields) before treating duration as per-person.
            pace_min_per_km  = pace_this_runner if pace_this_runner is not None else 0.0,
            duration_hours   = duration_hours_this_runner if duration_hours_this_runner is not None else 0.0,
        ))

    if len(valid_simulations) < n_simulations:
        print(f"{Fore.YELLOW}Warning: generated {len(valid_simulations)}/{n_simulations} "
              f"valid profiles ({attempts} attempts).{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}Generated {len(valid_simulations)} valid profiles "
              f"({attempts} attempts).{Style.RESET_ALL}")

    # [suite-integration addition] Plausibility check: if a large share of the
    # population is pinned at the pct_vo2max ceiling (0.95), the effort level
    # implied is not sustainable for much of this population -- e.g.
    # selecting "Marathon, competition pace" (MET 13.5) for a general
    # recreational-fitness sample pins ~70% of participants at their
    # physiological ceiling rather than at the intensity actually requested.
    # This also breaks statistical realism (an artificial pile-up at one
    # value) and means results may not match whatever calibration (e.g. the
    # Boston-Marathon-pooled collapse-risk intercept) assumed a population
    # with pct_vo2max centred well below the ceiling.
    #
    # [2026-09] This check itself (pct_vo2max >= ceiling) is valid either
    # way -- it reads each participant's own computed value, regardless of
    # how it was derived. Only the MESSAGE was wrong under sample_pace=True:
    # it always blamed "the chosen MET (met_value)", but when sample_pace is
    # on, met_value is never actually used (see the sample_pace branch
    # above) -- participants are pinned by their OWN sampled pace outrunning
    # their OWN VO2max, not by one shared MET. Reproduced directly: a real
    # run with sample_pace=True still printed "for the chosen MET (9.8)",
    # which is simply false in that mode and points the reader at the wrong
    # variable to reconsider.
    if valid_simulations and (met_value is not None or sample_pace):
        pct_at_ceiling = np.mean([p.pct_vo2max >= 0.9499 for p in valid_simulations])
        if pct_at_ceiling > 0.20:
            if sample_pace:
                mean_pace = np.mean([p.pace_min_per_km for p in valid_simulations])
                print(f"{Fore.YELLOW}Warning: {pct_at_ceiling*100:.0f}% of this population is "
                      f"pinned at the maximum sustainable effort (95% VO2max). The sampled pace "
                      f"distribution (mean {mean_pace:.2f} min/km over {event_dist_km:g} km) "
                      f"outruns a large share of this population's own fitness -- interpret "
                      f"collapse-risk/TCF results with extra caution, since the calibration "
                      f"reference population was not built at this effort "
                      f"level.{Style.RESET_ALL}")
            else:
                print(f"{Fore.YELLOW}Warning: {pct_at_ceiling*100:.0f}% of this population is "
                      f"pinned at the maximum sustainable effort (95% VO2max) for the chosen "
                      f"MET ({met_value}). This activity/pace may not be realistic for a large "
                      f"share of this population's fitness distribution -- consider a lower MET, "
                      f"or interpret collapse-risk/TCF results with extra caution, since the "
                      f"calibration reference population was not built at this effort "
                      f"level.{Style.RESET_ALL}")

    return valid_simulations


# =============================================================================
#  POPULATION PERSISTENCE (rev10)
#
#  A base population can be saved to disk and reloaded for reproducible
#  scenario comparisons. This avoids re-generating and re-seeding for each run.
# =============================================================================

def save_population(population: list, filepath: str) -> None:
    """
    Save a base population to a pickle file with version metadata.

    Parameters
    ----------
    population : list of AdultParticipantProfile
    filepath   : str -- path to .pkl file (e.g. 'base_population_N5000_seed42.pkl')

    [rev11] The file now stores a dict with keys 'hestia_version' and
    'population'. load_population() checks the version and warns on mismatch.
    """
    payload = {
        'hestia_version': HESTIA_VERSION,
        'population':     population,
    }
    with open(filepath, 'wb') as f:
        pickle.dump(payload, f)
    print(f"{Fore.GREEN}Population saved to '{filepath}' "
          f"({len(population)} profiles, version={HESTIA_VERSION}).{Style.RESET_ALL}")


def load_population(filepath: str) -> list:
    """
    Load a base population from a pickle file.

    SECURITY: pickle can execute code while loading. Only load .pkl files
    that this suite wrote on your own computer, never files from others.

    Parameters
    ----------
    filepath : str -- path to .pkl file

    Returns
    -------
    list of AdultParticipantProfile

    [rev11] Version safety: files saved by rev11+ contain a dict with key
    'hestia_version'. Files saved by earlier revisions contain a bare list.
    A deprecation warning is printed for pre-rev11 files or version mismatches.
    """
    with open(filepath, 'rb') as f:
        payload = pickle.load(f)

    if isinstance(payload, dict):
        # rev11+ format
        file_version = payload.get('hestia_version', 'unknown')
        population   = payload['population']
        if file_version != HESTIA_VERSION:
            print(f"{Fore.YELLOW}[rev11] WARNING: population file was created by "
                  f"'{file_version}', current version is '{HESTIA_VERSION}'. "
                  f"Schema changes between versions may cause AttributeErrors. "
                  f"Regenerate the population if errors occur.{Style.RESET_ALL}")
        else:
            print(f"{Fore.GREEN}Population loaded from '{filepath}' "
                  f"({len(population)} profiles, version={file_version}).{Style.RESET_ALL}")
    else:
        # Pre-rev11 bare list
        population = payload
        print(f"{Fore.YELLOW}[rev11] WARNING: population file has no version tag "
              f"(pre-rev11 format). Consider regenerating with rev11 to ensure "
              f"schema compatibility.{Style.RESET_ALL}")
        print(f"{Fore.GREEN}Loaded {len(population)} profiles (version=pre-rev11).{Style.RESET_ALL}")

    return population


# =============================================================================
#  POPULATION VALIDATION (rev10 -- NEW)
#
#  validate_population() performs three levels of validation:
#
#  1. MARGINAL VALIDATION
#     Compares distribution statistics (mean, SD, percentiles) of each
#     population parameter against published empirical references.
#     A WARNING is printed for any parameter where the simulated mean
#     deviates by more than 1 SD from the reference value.
#
#  2. CORRELATION VALIDATION
#     Checks physiologically expected correlations in the generated population:
#       - VO2max vs age:    expected r in [-0.50, -0.25]
#       - VO2max vs gender: expected Cohen's d in [0.70, 1.00]
#         (coded as 0/1 for female/male)
#     Values outside these ranges trigger a WARNING.
#
#  3. FINISH-TIME VALIDATION (afgeleide validatie)
#     Uses the Daniels & Gilbert (1979) VO2max-performance formula to compute
#     an implied marathon finish time for each participant based on their
#     VO2max and pct_vo2max. The population finish-time distribution is then
#     compared to the reference range for a recreational Dutch marathon field:
#       - Median finish time: expected [3h30m, 4h30m]
#       - P5 (fast tail):     expected [2h45m, 3h30m]
#       - P95 (slow tail):    expected [4h30m, 5h30m]
#     This is the strongest test: if the simulated population finishes
#     collectively in a realistic time range, the joint distribution of
#     VO2max, %VO2max, and age is empirically anchored.
#
#  OUTPUT
#     A summary table is printed to console and a 3-panel validation figure
#     is displayed (marginals + correlation matrix + finish-time histogram).
#
#  REFERENCES
#     Scharhag-Rosenberger F et al. (2010) J Sci Med Sport 13:167-172.
#     Tanda G & Knechtle B (2013) J Hum Kinet 38:169-177.
#     Tanaka H et al. (2001) J Am Coll Cardiol 37:153-156.
#     Daniels J & Gilbert J (1979) Oxygen Power. Tempe, AZ.
#     RunRepeat European marathon statistics (2023).
# =============================================================================

# Daniels-Gilbert VO2max <-> performance constants (marathon distance)
_MARATHON_DIST_KM = 42.195

def _daniels_gilbert_vo2_at_pace(pace_min_per_km: float) -> float:
    """
    Estimate VO2 (mL/kg/min) from marathon pace using Daniels & Gilbert (1979).
    pace_min_per_km: pace in minutes per kilometer.
    Returns VO2 in mL/kg/min.
    """
    # Velocity in m/min
    v = 1000.0 / pace_min_per_km
    # Daniels & Gilbert oxygen cost formula:
    # VO2 = -4.60 + 0.182258*v + 0.000104*v^2  (v in m/min)
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v ** 2
    return max(1.0, vo2)


def _daniels_gilbert_pace_from_vo2max(vo2max: float, pct_vo2max: float) -> float:
    """
    Estimate marathon pace (min/km) from VO2max and fraction sustained.

    The sustained VO2 at race pace is vo2max * pct_vo2max. We invert the
    Daniels-Gilbert formula to find the velocity v (m/min) that corresponds
    to that VO2, then convert to pace.

    The quadratic 0.000104*v^2 + 0.182258*v - (VO2 + 4.60) = 0 is solved
    analytically.
    """
    vo2_race = vo2max * pct_vo2max
    a = 0.000104
    b = 0.182258
    c = -(vo2_race + 4.60)
    discriminant = b ** 2 - 4 * a * c
    if discriminant < 0:
        return 999.0  # physiologically impossible
    v = (-b + math.sqrt(discriminant)) / (2 * a)   # m/min
    if v <= 0:
        return 999.0
    pace_min_per_km = 1000.0 / v  # min/km
    return pace_min_per_km


def _finish_time_hours(vo2max: float, pct_vo2max: float,
                        dist_km: float = None) -> float:
    """Returns implied finish time in hours over `dist_km` (default: marathon).

    [2026-09] dist_km added so this isn't tied to the marathon distance --
    any event (DtD's 16.1 km, a half marathon, etc.) can now be checked
    directly instead of only via a marathon-equivalent proxy.
    """
    if dist_km is None:
        dist_km = _MARATHON_DIST_KM
    pace = _daniels_gilbert_pace_from_vo2max(vo2max, pct_vo2max)
    finish_h = pace * dist_km / 60.0
    return finish_h


def validate_population(
    population: list,
    show_plots: bool = True,
    event_dist_km: float = None,
) -> dict:
    """
    Validate a generated base population against empirical references.

    Performs three validation levels:
      1. Marginal distribution checks (mean, SD) vs. published references.
      2. Correlation checks (VO2max-age, VO2max-gender).
      3. Implied finish-time distribution vs. reference data for the given
         event distance (defaults to marathon, 42.195 km, if not given).

    Parameters
    ----------
    population : list of AdultParticipantProfile
        Output of generate_base_population().
    show_plots : bool
        If True, display a 3-panel validation figure.
    event_dist_km : float, optional
        [2026-09] Event distance in km for the finish-time check (level 3).
        Defaults to the marathon distance (42.195 km) if not given, which
        matches this function's previous, marathon-only behaviour exactly --
        existing callers are unaffected. Pass e.g. 16.1 for Dam tot Damloop,
        21.1 for a half marathon, etc. The expected P5/P50/P95 reference
        bounds (fit to Dutch recreational MARATHON data) are scaled
        proportionally to event_dist_km / 42.195 km when this differs from
        the marathon distance -- a linear approximation (real pacing slows
        somewhat at longer distances due to fatigue, so this is not exact),
        good enough for a plausibility check but not a precision reference.
        The pass/fail gate is skipped (informational only) for non-marathon
        distances, so a legitimately different event is never reported as a
        validation "FAIL" against marathon-shaped expectations.

    Returns
    -------
    dict
        Summary statistics and pass/fail flags for each check.
        Keys: 'marginal', 'correlation', 'finish_time', 'all_pass'.
    """
    # ------------------------------------------------------------------ #
    #  Extract arrays from population                                      #
    # ------------------------------------------------------------------ #
    heights     = np.array([p.height     for p in population])
    weights     = np.array([p.weight     for p in population])
    ages        = np.array([p.age        for p in population])
    genders     = np.array([p.gender     for p in population])
    vo2maxen    = np.array([p.vo2max     for p in population])
    pct_vo2max_arr= np.array([p.pct_vo2max for p in population])
    bmis        = weights / heights ** 2
    gender_bin  = (genders == "male").astype(float)  # 1=male, 0=female

    n = len(population)
    pct_male = 100 * gender_bin.mean()

    # [2026-09] finish_times_h is now computed further below, inside the
    # FINISH-TIME VALIDATION section, using the configurable event_dist_km
    # (defaults to marathon) -- see that section for the up-to-date array.

    # ------------------------------------------------------------------ #
    #  1. MARGINAL VALIDATION                                              #
    # ------------------------------------------------------------------ #
    # Reference values from literature (see module docstring).
    # Format: {parameter: (sim_mean, sim_sd, ref_mean, ref_sd, ref_source)}
    MARGINAL_REFS = {
        "VO2max male (mL/kg/min)": (
            vo2maxen[genders == "male"].mean(),
            vo2maxen[genders == "male"].std(),
            52.0, 8.0,
            "Scharhag-Rosenberger (2010)"
        ),
        "VO2max female (mL/kg/min)": (
            vo2maxen[genders == "female"].mean(),
            vo2maxen[genders == "female"].std(),
            44.0, 7.0,
            "Scharhag-Rosenberger (2010)"
        ),
        "Age (years)": (
            ages.mean(), ages.std(),
            40.0, 10.0,
            "RunRepeat EU marathon stats (2023)"
        ),
        "% male": (
            pct_male, 0.0,   # SD not applicable for proportion
            58.0, 5.0,
            "RunRepeat EU marathon stats (2023)"
        ),
        "Height male (m)": (
            heights[genders == "male"].mean(),
            heights[genders == "male"].std(),
            1.78, 0.07,
            "RIVM NL antropometrische data"
        ),
        "Height female (m)": (
            heights[genders == "female"].mean(),
            heights[genders == "female"].std(),
            1.65, 0.06,
            "RIVM NL antropometrische data"
        ),
        "BMI (kg/m^2)": (
            bmis.mean(), bmis.std(),
            22.5, 2.5,
            "Tanda & Knechtle (2013)"
        ),
        "pct_VO2max at pace": (
            pct_vo2max_arr.mean(), pct_vo2max_arr.std(),
            # [rev13] Expected mean is now event-pace dependent, not fixed at 0.78.
            # For EVENT_PACE_MIN_PER_KM=6.5: VO2 demand ~45 mL/kg/min.
            # For population VO2max mean ~49 (mixed M/F): expected mean ~0.92 -> clipped lower.
            # Reference: Joyner (1991); Jones & Carter (2000).
            # Tolerance is wider (0.10) to accommodate event-pace variability.
            _daniels_gilbert_vo2_at_pace(EVENT_PACE_MIN_PER_KM) / 49.0, 0.10,
            "Daniels-Gilbert inversion at EVENT_PACE_MIN_PER_KM [rev13]"
        ),
    }

    marginal_results = {}
    print(f"\n{'='*72}")
    print(f"POPULATION VALIDATION  (N={n})")
    print(f"{'='*72}")
    print(f"{'Parameter':<35} {'Sim mean':>9} {'Sim SD':>8} {'Ref mean':>9} {'Ref SD':>8} {'Pass?':>6}")
    print(f"{'-'*72}")

    for param, (sim_m, sim_s, ref_m, ref_s, source) in MARGINAL_REFS.items():
        # Pass if simulated mean within 1 SD of reference mean
        deviation = abs(sim_m - ref_m)
        tolerance = ref_s if ref_s > 0 else ref_m * 0.10
        passed = deviation <= tolerance
        flag = f"{Fore.GREEN}OK{Style.RESET_ALL}" if passed else f"{Fore.RED}WARN{Style.RESET_ALL}"
        print(f"  {param:<33} {sim_m:>9.2f} {sim_s:>8.2f} {ref_m:>9.2f} {ref_s:>8.2f} {flag}")
        marginal_results[param] = {
            'sim_mean': sim_m, 'sim_sd': sim_s,
            'ref_mean': ref_m, 'ref_sd': ref_s,
            'passed': passed, 'source': source,
        }

    # ------------------------------------------------------------------ #
    #  2. CORRELATION VALIDATION                                           #
    # ------------------------------------------------------------------ #
    r_vo2_age    = float(np.corrcoef(vo2maxen, ages)[0, 1])
    r_vo2_gender = float(np.corrcoef(vo2maxen, gender_bin)[0, 1])
    cohens_d     = (
        (vo2maxen[gender_bin == 1].mean() - vo2maxen[gender_bin == 0].mean())
        / np.sqrt(
            ((vo2maxen[gender_bin == 1].std() ** 2) +
             (vo2maxen[gender_bin == 0].std() ** 2)) / 2
        )
    )

    # Expected: r(VO2max, age) in [-0.50, -0.25]; Cohen's d in [0.70, 1.00]
    corr_age_ok    = -0.50 <= r_vo2_age    <= -0.25
    cohens_d_ok    = 0.70  <= cohens_d     <= 1.00

    print(f"\n  Correlation checks:")
    print(f"  {'r(VO2max, age)':<30} {r_vo2_age:>8.3f}  "
          f"[expected: -0.50 to -0.25]  "
          f"{Fore.GREEN+'OK'+Style.RESET_ALL if corr_age_ok else Fore.RED+'WARN'+Style.RESET_ALL}")
    print(f"  {'Cohen d (VO2max, M vs F)':<30} {cohens_d:>8.3f}  "
          f"[expected:  0.70 to  1.00]  "
          f"{Fore.GREEN+'OK'+Style.RESET_ALL if cohens_d_ok else Fore.RED+'WARN'+Style.RESET_ALL}")

    correlation_results = {
        'r_vo2max_age':    {'value': r_vo2_age,  'passed': corr_age_ok},
        'cohens_d_gender': {'value': cohens_d,   'passed': cohens_d_ok},
    }

    # ------------------------------------------------------------------ #
    #  3. FINISH-TIME VALIDATION                                           #
    # ------------------------------------------------------------------ #
    # Reference: Dutch recreational marathon (Amsterdam, Rotterdam).
    # Expected finish-time distribution for self-selected mass events:
    #   Median:    [3h30m, 4h30m]  -> [3.50h, 4.50h]
    #   P5 (fast): [2h45m, 3h30m]  -> [2.75h, 3.50h]
    #   P95 (slow):[4h30m, 5h30m]  -> [4.50h, 5.50h]
    # [2026-09] These bounds are marathon-specific. When event_dist_km is
    # given and differs from the marathon distance, they are scaled
    # proportionally (a linear approximation -- see validate_population's
    # docstring) and the pass/fail gate is skipped, since marathon-shaped
    # expectations should never fail a legitimately different event.
    _dist_for_check = event_dist_km if event_dist_km is not None else _MARATHON_DIST_KM
    _is_marathon_check = abs(_dist_for_check - _MARATHON_DIST_KM) < 0.01
    _scale = _dist_for_check / _MARATHON_DIST_KM

    finish_times_h = np.array([
        _finish_time_hours(p.vo2max, p.pct_vo2max, dist_km=_dist_for_check)
        for p in population
    ])

    ft_p5   = float(np.percentile(finish_times_h, 5))
    ft_p50  = float(np.percentile(finish_times_h, 50))
    ft_p95  = float(np.percentile(finish_times_h, 95))
    ft_mean = float(finish_times_h.mean())

    ft_p50_lo, ft_p50_hi = 3.50 * _scale, 4.50 * _scale
    ft_p5_lo,  ft_p5_hi  = 2.75 * _scale, 3.50 * _scale
    ft_p95_lo, ft_p95_hi = 4.50 * _scale, 5.50 * _scale

    ft_p50_ok = ft_p50_lo <= ft_p50 <= ft_p50_hi
    ft_p5_ok  = ft_p5_lo  <= ft_p5  <= ft_p5_hi
    ft_p95_ok = ft_p95_lo <= ft_p95 <= ft_p95_hi

    def _h_to_hhmm(h: float) -> str:
        hh = int(h)
        mm = int(round((h - hh) * 60))
        return f"{hh}h{mm:02d}m"

    _dist_label = f"{_dist_for_check:g} km" + ("" if _is_marathon_check else " (scaled from marathon reference)")
    print(f"\n  Implied finish times over {_dist_label} (Daniels & Gilbert 1979):")
    print(f"  {'P5  (fast tail)':<30} {_h_to_hhmm(ft_p5):>8}  "
          f"[expected: {_h_to_hhmm(ft_p5_lo)} - {_h_to_hhmm(ft_p5_hi)}]  "
          f"{Fore.GREEN+'OK'+Style.RESET_ALL if ft_p5_ok else Fore.RED+'WARN'+Style.RESET_ALL}")
    print(f"  {'Median (P50)':<30} {_h_to_hhmm(ft_p50):>8}  "
          f"[expected: {_h_to_hhmm(ft_p50_lo)} - {_h_to_hhmm(ft_p50_hi)}]  "
          f"{Fore.GREEN+'OK'+Style.RESET_ALL if ft_p50_ok else Fore.RED+'WARN'+Style.RESET_ALL}")
    print(f"  {'P95 (slow tail)':<30} {_h_to_hhmm(ft_p95):>8}  "
          f"[expected: {_h_to_hhmm(ft_p95_lo)} - {_h_to_hhmm(ft_p95_hi)}]  "
          f"{Fore.GREEN+'OK'+Style.RESET_ALL if ft_p95_ok else Fore.RED+'WARN'+Style.RESET_ALL}")
    if not _is_marathon_check:
        print(f"  (non-marathon distance: bounds are a linear scaling of the "
              f"marathon reference, informational only -- not gated below)")

    finish_time_results = {
        'ft_p5_h':  {'value': ft_p5,  'passed': ft_p5_ok  if _is_marathon_check else True},
        'ft_p50_h': {'value': ft_p50, 'passed': ft_p50_ok if _is_marathon_check else True},
        'ft_p95_h': {'value': ft_p95, 'passed': ft_p95_ok if _is_marathon_check else True},
    }

    all_marginal_ok     = all(v['passed'] for v in marginal_results.values())
    all_correlation_ok  = all(v['passed'] for v in correlation_results.values())
    all_finish_time_ok  = all(v['passed'] for v in finish_time_results.values())
    all_pass            = all_marginal_ok and all_correlation_ok and all_finish_time_ok

    print(f"\n  Overall: {'ALL CHECKS PASSED' if all_pass else 'ONE OR MORE CHECKS FAILED -- see warnings above'}")
    print(f"{'='*72}\n")

    # ------------------------------------------------------------------ #
    #  VALIDATION PLOTS (3-panel figure)                                   #
    # ------------------------------------------------------------------ #
    if show_plots:
        fig, axes = plt.subplots(1, 3, figsize=(18, 5))
        fig.suptitle(f"Population Validation (N={n})", fontsize=14, weight='bold')

        # Panel 1: VO2max by gender
        ax = axes[0]
        for g, color in [("male", "steelblue"), ("female", "salmon")]:
            data = vo2maxen[genders == g]
            ax.hist(data, bins=30, alpha=0.6, color=color, label=g.capitalize(),
                    density=True)
        ax.axvline(52, color='steelblue', linestyle='--', alpha=0.8, label='Ref male (52)')
        ax.axvline(44, color='salmon',    linestyle='--', alpha=0.8, label='Ref female (44)')
        ax.set_xlabel("VO2max (mL/kg/min)")
        ax.set_ylabel("Density")
        ax.set_title("VO2max Distribution by Gender")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        # Panel 2: Correlation matrix (VO2max, age, BMI, pct_vo2max)
        ax = axes[1]
        corr_df = pd.DataFrame({
            'VO2max':      vo2maxen,
            'Age':         ages,
            'BMI':         bmis,
            '%VO2max':     pct_vo2max_arr,
            'Male(0/1)':   gender_bin,
        })
        corr_matrix = corr_df.corr()
        im = ax.imshow(corr_matrix.values, cmap='RdBu_r', vmin=-1, vmax=1)
        ax.set_xticks(range(len(corr_matrix.columns)))
        ax.set_yticks(range(len(corr_matrix.columns)))
        ax.set_xticklabels(corr_matrix.columns, rotation=45, ha='right', fontsize=8)
        ax.set_yticklabels(corr_matrix.columns, fontsize=8)
        for i in range(len(corr_matrix)):
            for j in range(len(corr_matrix)):
                ax.text(j, i, f"{corr_matrix.values[i, j]:.2f}",
                        ha='center', va='center', fontsize=7,
                        color='black' if abs(corr_matrix.values[i, j]) < 0.5 else 'white')
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        ax.set_title("Correlation Matrix")

        # Panel 3: Implied finish-time distribution
        ax = axes[2]
        ax.hist(finish_times_h, bins=40, color='forestgreen', alpha=0.7, density=True)
        ax.axvline(ft_p50, color='black', linestyle='-',  linewidth=2,
                   label=f'Median: {_h_to_hhmm(ft_p50)}')
        ax.axvline(ft_p5,  color='blue',  linestyle='--', linewidth=1.5,
                   label=f'P5: {_h_to_hhmm(ft_p5)}')
        ax.axvline(ft_p95, color='red',   linestyle='--', linewidth=1.5,
                   label=f'P95: {_h_to_hhmm(ft_p95)}')
        # Reference window shading -- scaled to event_dist_km (see docstring)
        ax.axvspan(ft_p50_lo, ft_p50_hi, alpha=0.12, color='green', label='Ref median window')
        ax.set_xlabel("Implied finish time (hours)")
        ax.set_ylabel("Density")
        ax.set_title(f"Implied Finish Times over {_dist_label}\n(Daniels & Gilbert 1979)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        plt.show(block=False)

    return {
        'marginal':     marginal_results,
        'correlation':  correlation_results,
        'finish_time':  finish_time_results,
        'all_pass':     all_pass,
    }


# =============================================================================
#  CHILDREN SIMULATION (unchanged from rev09)
# =============================================================================

def simulate_child_participant(n_simulations=200, met_value=None, age_group="11-20", fitness_factor=0.5):
    """
    Generates realistic variations for pediatric participants for Monte Carlo simulation.
    (Unchanged from rev09 -- pediatric population architecture not affected by rev10.)
    """
    valid_simulations = []
    attempts = 0
    max_attempts = n_simulations * 25

    if age_group == "0-10":
        height_mean, height_sd = 1.22, 0.08
        weight_mean, weight_sd = 23.0, 4.0
    else:
        height_mean, height_sd = 1.65, 0.1
        weight_mean, weight_sd = 55.0, 10.0

    print(f"\nGenerating realistic pediatric participant profiles for age group {age_group}...")
    while len(valid_simulations) < n_simulations and attempts < max_attempts:
        attempts += 1
        height = float(np.clip(np.random.normal(loc=height_mean, scale=height_sd),
                                height_mean - 0.3, height_mean + 0.3))
        weight = float(np.clip(np.random.normal(loc=weight_mean, scale=weight_sd),
                                weight_mean - 15.0, weight_mean + 15.0))
        bmi = weight / (height ** 2)
        if not (14.0 <= bmi <= 30.0):
            continue

        temp_variation = float(np.random.normal(loc=0, scale=1.0))
        rh_variation   = float(np.random.normal(loc=0, scale=8.0))

        met_efficiency_offset = (1 - fitness_factor) * met_value * 0.10
        met_variation = float(np.random.normal(loc=met_efficiency_offset,
                                                scale=0.15 * met_value))
        mf_score = float(np.random.uniform(0.0, 1.0))

        sweat_loc    = 0.5 + (fitness_factor * 0.2)
        sweat_factor = float(np.clip(np.random.normal(loc=sweat_loc, scale=0.1), 0.3, 0.9))

        thirst_upper_bound = 3.5 - (fitness_factor * 1.0)
        thirst_threshold   = float(np.random.uniform(2.0, max(2.1, thirst_upper_bound)))

        valid_simulations.append((height, weight, temp_variation, rh_variation,
                                   met_variation, mf_score, sweat_factor, thirst_threshold))

    if len(valid_simulations) < n_simulations:
        print(f"{Fore.YELLOW}Warning: Could only generate {len(valid_simulations)}/{n_simulations} "
              f"realistic simulations.{Style.RESET_ALL}")
    else:
        print(f"{Fore.GREEN}Successfully generated {len(valid_simulations)} realistic simulations.{Style.RESET_ALL}")
    return valid_simulations


# =============================================================================
#  COMMON ENVIRONMENTAL FUNCTIONS (unchanged from rev09)
# =============================================================================

@lru_cache(maxsize=128)
def get_lat_lon(city_name):
    """Retrieves lat/lon for a given city using Open-Meteo Geocoding API."""
    try:
        geo_url = (f"https://geocoding-api.open-meteo.com/v1/search"
                   f"?name={city_name}&count=1&format=json")
        response = requests.get(geo_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data and "results" in data and len(data["results"]) > 0:
            return data["results"][0]["latitude"], data["results"][0]["longitude"]
        return None, None
    except requests.RequestException as e:
        print(f"Error fetching location: {e}")
        return None, None


@lru_cache(maxsize=128)
def get_timezone(lat, lon):
    """Determines the IANA timezone for a given lat/lon."""
    tf = TimezoneFinder()
    timezone_name = tf.timezone_at(lat=lat, lng=lon)
    return pytz.timezone(timezone_name) if timezone_name else pytz.UTC


@lru_cache(maxsize=128)
def get_weather_forecast(lat, lon):
    """Retrieves a 7-day hourly weather forecast from Open-Meteo API."""
    try:
        forecast_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,cloud_cover,surface_pressure"
            ",shortwave_radiation_instant"   # [2026-10-24] forecast radiation (W/m2 at the indicated time)
            "&forecast_days=15&timezone=UTC"
        )
        response = requests.get(forecast_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data or "hourly" not in data:
            return None
        hourly = data["hourly"]
        owm_like_list = []
        for i in range(len(hourly["time"])):
            dt_str  = hourly["time"][i]
            dt_obj  = datetime.fromisoformat(dt_str).replace(tzinfo=UTC)
            dt_ts   = int(dt_obj.timestamp())
            wind_ms = hourly["wind_speed_10m"][i] / 3.6
            owm_like_list.append({
                "dt":   dt_ts,
                "main": {
                    "temp":     hourly["temperature_2m"][i],
                    "humidity": hourly["relative_humidity_2m"][i],
                    "pressure": hourly["surface_pressure"][i],
                },
                "wind":   {"speed": wind_ms},
                "clouds": {"all": hourly["cloud_cover"][i]},
                # [2026-10-24] forecast global radiation; None -> cloud estimate
                "solar":  {"ghi": (hourly.get("shortwave_radiation_instant") or [None] * len(hourly["time"]))[i]},
            })
        return owm_like_list
    except requests.RequestException as e:
        print(f"Error fetching weather data: {e}")
        return None


def _map_us_aqi_to_owm_scale(us_aqi):
    if us_aqi <= 50:   return 1
    if us_aqi <= 100:  return 2
    if us_aqi <= 150:  return 3
    if us_aqi <= 200:  return 4
    return 5


@lru_cache(maxsize=128)
@lru_cache(maxsize=256)
def get_air_quality(lat, lon):
    """Retrieves current AQI using Open-Meteo (mapped to 1-5 scale).

    CACHED, deliberately -- see the profiling note in hestia_bridge.py.
    This function is called once per Monte Carlo draw inside
    calculate_indices_jos3_adult(), but (lat, lon) are identical across
    every draw in a single run (same event, same location). Uncached, a
    5000-draw run made up to 5000 live HTTP requests for an answer that
    never changes within that run -- compounding both wall-clock time and
    the exact shared-IP rate-limit risk already documented for the
    weather API elsewhere in this suite. lru_cache is per-process, so
    under multiprocessing.Pool this still costs one request per worker
    process (its first call) rather than one per draw -- a large
    reduction on its own, and hestia_bridge.py's monkey-patch removes the
    live call entirely when the value is already known.
    """
    try:
        air_url = (f"https://air-quality-api.open-meteo.com/v1/air-quality"
                   f"?latitude={lat}&longitude={lon}&current=us_aqi&timezone=UTC")
        response = requests.get(air_url, timeout=10)
        response.raise_for_status()
        data   = response.json()
        us_aqi = data["current"]["us_aqi"]
        return _map_us_aqi_to_owm_scale(us_aqi)
    except requests.RequestException:
        return 1


@lru_cache(maxsize=256)
def calculate_solar_radiance(lat, lon, local_datetime_str, cloud_cover, aqi):
    """Calculates GHI, DNI, DHI and solar position using pvlib."""
    try:
        local_timezone  = get_timezone(lat, lon)
        local_datetime  = pd.to_datetime(local_datetime_str).tz_convert(local_timezone.zone)
        location        = pvlib.location.Location(lat, lon, tz=local_timezone.zone, altitude=0)
        solar_position  = location.get_solarposition(pd.DatetimeIndex([local_datetime]))
        elevation       = solar_position['elevation'].iloc[0]
        zenith          = solar_position['apparent_zenith'].iloc[0]
        azimuth         = solar_position['azimuth'].iloc[0]
        linke_turbidity = 2.5 if aqi <= 2 else 4.0 if aqi <= 4 else 6.0
        clear_sky       = location.get_clearsky(local_datetime, model='ineichen',
                                                linke_turbidity=linke_turbidity)
        cloud_factor    = max(0.1, 1 - cloud_cover / 100)
        dni             = clear_sky['dni'].iloc[0] * cloud_factor
        dhi             = clear_sky['dhi'].iloc[0] * (1 + (1 - cloud_factor) * 0.5)
        ghi             = dni * pvlib.irradiance.aoi_projection(0, 0, zenith, azimuth) + dhi
        return {'ghi': max(0, ghi), 'dni': max(0, dni), 'dhi': max(0, dhi),
                'solar_elevation': elevation, 'zenith': zenith}
    except Exception as e:
        if "year is out of range" in str(e):
            return {'ghi': 0, 'dni': 0, 'dhi': 0, 'solar_elevation': 0, 'zenith': 90}
        print(f"Error calculating solar radiance for {local_datetime_str}: {e}")
        return {'ghi': 0, 'dni': 0, 'dhi': 0, 'solar_elevation': 0, 'zenith': 90}


def radiation_series(interp_data, times, temps, wind_1_5m, pressures, clouds,
                     lat, lon, aqi, rhs=None):
    """[2026-10-24] Radiation inputs for one simulation, in order of preference:

    1. Data Engine values complete (ghi, solar_elevation, globe_temp, mrt):
       used as they are (unchanged behaviour).
    2. Measured or forecast global radiation (ghi) present but no globe/MRT
       (e.g. a calibration reference or an Open-Meteo forecast): the sun
       position comes from pvlib, globe temperature and MRT are computed
       from the MEASURED/FORECAST ghi. Cloud cover is then only used inside
       the globe model, never to estimate the amount of sunshine.
    3. No radiation at all: the old clear-sky x cloud-attenuation estimate.
       That estimate underestimates GHI badly under thin high cloud (DtD
       2024-09-22: ERA5 89-99 % cloud, measured 450-550 W/m2, estimate
       ~145 W/m2), so it is a last resort only.
    Returns (ghi, solar_elevations, globe_temps, mrts, bron).
    rhs [%] (2026-10-31): humidity for the sky emissivity in the Liljegren
    globe model (options 2 and 3); 50 % when not given.
    """
    if all(interp_data[0].get(k) is not None
           for k in ('ghi', 'solar_elevation', 'globe_temp', 'mrt')):
        return ([e['ghi'] for e in interp_data],
                [e['solar_elevation'] for e in interp_data],
                [e['globe_temp'] for e in interp_data],
                [e['mrt'] for e in interp_data], 'data_engine')
    radiances = [calculate_solar_radiance(lat, lon, str(t), c, aqi)
                 for t, c in zip(times, clouds)]
    solar_elevations = [rad['solar_elevation'] for rad in radiances]
    if all(e.get('ghi') is not None for e in interp_data):
        ghi  = [max(0.0, float(e['ghi'])) if se > 0 else 0.0
                for e, se in zip(interp_data, solar_elevations)]
        bron = 'gemeten_ghi'
    else:
        ghi  = [rad['ghi'] for rad in radiances]
        bron = 'bewolking'
    if rhs is None:
        rhs = [50.0] * len(temps)
    globe_temps = [calculate_globe_temperature(t, g, w, se, p, c, aqi, rh=r)
                   for t, g, w, se, p, c, r in zip(
                       temps, ghi, wind_1_5m, solar_elevations, pressures, clouds, rhs)]
    mrts        = [calculate_mrt(gt, t, w, g, se)
                   for gt, t, w, g, se in zip(
                       globe_temps, temps, wind_1_5m, ghi, solar_elevations)]
    return ghi, solar_elevations, globe_temps, mrts, bron


def calculate_globe_temperature(dry_bulb_temp, ghi, wind_speed, solar_elevation,
                                pressure, cloud_cover, aqi, rh=50.0):
    """Black globe temperature (0.15 m) [degC].

    [2026-10-31] Delegates to thermal_env._calculate_globe_scalar, so HESTIA
    and the Data Engine use one globe model (daytime: Liljegren et al. 2008
    energy balance with direct/diffuse split and ground reflection; night
    unchanged). Until 2026-10-30 this function carried its own copy of the
    older 0.95*GHI/4 model.
    """
    from thermal_env import _calculate_globe_scalar
    return _calculate_globe_scalar(dry_bulb_temp, ghi, wind_speed, solar_elevation,
                                   pressure, cloud_cover, aqi, rh=rh)


def calculate_mrt(globe_temp, dry_bulb_temp, wind_speed, ghi, solar_elevation):
    """Calculates Mean Radiant Temperature from globe temperature (ISO 7726)."""
    GLOBE_DIAMETER   = 0.15
    GLOBE_EMISSIVITY = 0.95
    STEFAN_BOLTZMANN = 5.67e-8
    t_globe_k  = globe_temp + 273.15
    t_air_k    = dry_bulb_temp + 273.15
    eff_wind   = max(0.1, wind_speed)
    h_c        = 6.3 * (eff_wind ** 0.6) / (GLOBE_DIAMETER ** 0.4)
    conv_term  = (h_c / (GLOBE_EMISSIVITY * STEFAN_BOLTZMANN)) * (t_globe_k - t_air_k)
    mrt_k4     = (t_globe_k ** 4) + conv_term
    if mrt_k4 < 0:
        return globe_temp
    mrt_c = mrt_k4 ** 0.25 - 273.15
    # [2026-10-31] Sun clip tg+30 and plausibility limit 90 degC (were tg+15
    # and 70): with the Liljegren globe, MRT of 70-80 degC in desert sun is
    # physical and must not fall back to the globe temperature.
    if ghi > 0 and solar_elevation > 0:
        mrt_c = np.clip(mrt_c, globe_temp - 2, globe_temp + 30)
    else:
        mrt_c = np.clip(mrt_c, dry_bulb_temp - 15, dry_bulb_temp + 3)
    if mrt_c > 90 or mrt_c < -50:
        return dry_bulb_temp if ghi <= 0 else globe_temp
    return mrt_c


def interpolate_weather(weather_data, start_dt, end_dt, interval_minutes=10):
    """Interpolates raw hourly weather data to a consistent time-step.

    [fix] Now also interpolates Thermopoulos/Klimatos's own precomputed
    solar radiation, solar elevation, globe temperature and MRT when present
    (see get_hourly_weather docstring for why). Falls back to None per-field
    if the source sheet lacks these columns (older files), so the caller can
    fall back to the internal reconstruction only where genuinely needed.
    """
    times = pd.date_range(start=start_dt, end=end_dt, freq=f"{interval_minutes}min")
    times_ts        = np.array([t.timestamp() for t in times])
    weather_ts      = np.array([e["dt"]                for e in weather_data])
    temps           = np.array([e["main"]["temp"]      for e in weather_data])
    rhs             = np.array([e["main"]["humidity"]  for e in weather_data])
    winds           = np.array([e["wind"]["speed"]     for e in weather_data])
    clouds          = np.array([e["clouds"]["all"]     for e in weather_data])
    pressures       = np.array([e["main"]["pressure"]  for e in weather_data])
    interp_temps    = np.interp(times_ts, weather_ts, temps)
    interp_rhs      = np.interp(times_ts, weather_ts, rhs)
    interp_winds    = np.interp(times_ts, weather_ts, winds)
    interp_clouds   = np.interp(times_ts, weather_ts, clouds)
    interp_pressures= np.interp(times_ts, weather_ts, pressures)

    def _interp_optional(key_path):
        vals = [(e.get(key_path[0]) or {}).get(key_path[1]) for e in weather_data]
        if any(v is None for v in vals):
            return [None] * len(times_ts)
        return np.interp(times_ts, weather_ts, np.array(vals, dtype=float))

    interp_ghi       = _interp_optional(("solar", "ghi"))
    interp_solar_el  = _interp_optional(("solar", "elevation"))
    interp_globe     = _interp_optional(("radiant", "globe_temp"))
    interp_mrt       = _interp_optional(("radiant", "mrt"))
    interp_twb_pre   = _interp_optional(("radiant", "twb"))
    interp_wbgt_pre  = _interp_optional(("indices", "wbgt"))
    interp_utci_pre  = _interp_optional(("indices", "utci"))
    interp_temps_rural = _interp_optional(("main", "temp_rural"))
    # [2026-10-31] "humidity" is the RH that belongs to the urban temperature
    # (RH_urban); the rural chain below needs the rural RH when it is known.
    _rh_rur = _interp_optional(("main", "humidity_rural"))
    interp_rhs_rural = interp_rhs if any(v is None for v in _rh_rur) else np.asarray(_rh_rur, dtype=float)

    # [2026-09] Rural-equivalent WBGT/UTCI, alongside the existing urban
    # ones above -- requested after showing rural-vs-urban air temperature
    # side by side made clear that WBGT/UTCI (both derived FROM air
    # temperature) needed the same treatment for consistency, not just
    # T_air alone. Mirrors Thermopoulos_Data_Engine.py's own urban chain
    # exactly (same functions, same call order), substituting T_air_rural
    # for T_air_urban throughout -- including re-deriving the 1.5m wind
    # via the same log-profile height correction (rural roughness,
    # z0=0.1), since the urban chain's own wind_1.5m was never itself
    # carried through to this loader/interpolation layer, only its
    # downstream globe/MRT results were.
    rural_globe = rural_mrt = rural_wbgt = rural_utci = [None] * len(times_ts)
    if not any(v is None for v in interp_temps_rural) and \
       not any(v is None for v in interp_ghi) and \
       not any(v is None for v in interp_solar_el):
        _ta_r = np.array(interp_temps_rural, dtype=float)
        _wind_1_5m_rural = wind_speed_at_height(interp_winds, 10.0, 1.5, z0=0.1)
        rural_globe = calculate_globe_vectorized(
            _ta_r, interp_ghi, _wind_1_5m_rural, interp_solar_el,
            interp_pressures, interp_clouds, 1, rh=interp_rhs_rural)
        rural_mrt = calculate_mrt_vectorized(
            rural_globe, _ta_r, _wind_1_5m_rural, interp_ghi, interp_solar_el)
        rural_twb = wet_bulb_tmp(tdb=_ta_r, rh=interp_rhs_rural)
        rural_wbgt_res = wbgt(twb=rural_twb, tg=rural_globe, tdb=_ta_r, with_solar_load=True)
        rural_wbgt = rural_wbgt_res.wbgt if hasattr(rural_wbgt_res, 'wbgt') else rural_wbgt_res
        _wind_utci_rural = np.clip(interp_winds, 0.5, 17.0)
        rural_utci_res = utci(tdb=_ta_r, tr=rural_mrt, v=_wind_utci_rural, rh=interp_rhs_rural)
        rural_utci = rural_utci_res.utci if hasattr(rural_utci_res, 'utci') else rural_utci_res

    return [
        {
            "time":     pd.Timestamp.fromtimestamp(ts, tz=start_dt.tz),
            "temp":     temp,
            "temp_rural": temp_rural,
            "rh":       rh,
            "wind":     wind,
            "clouds":   cloud,
            "pressure": pressure,
            "twb":      wet_bulb_tmp(tdb=temp, rh=rh),
            "ghi":            ghi,
            "solar_elevation": solar_el,
            "globe_temp":      globe,
            "mrt":             mrt,
            "twb_precomputed": twb_pre,
            "wbgt_precomputed": wbgt_pre,
            "utci_precomputed": utci_pre,
            "globe_temp_rural": g_rur,
            "mrt_rural":        m_rur,
            "wbgt_rural":       w_rur,
            "utci_rural":       u_rur,
        }
        for ts, temp, temp_rural, rh, wind, cloud, pressure, ghi, solar_el, globe, mrt, twb_pre, wbgt_pre, utci_pre, g_rur, m_rur, w_rur, u_rur in zip(
            times_ts, interp_temps, interp_temps_rural, interp_rhs, interp_winds,
            interp_clouds, interp_pressures,
            interp_ghi, interp_solar_el, interp_globe, interp_mrt, interp_twb_pre,
            interp_wbgt_pre, interp_utci_pre,
            rural_globe, rural_mrt, rural_wbgt, rural_utci,
        )
    ]


# =============================================================================
#  RPE MODELS (unchanged from rev09)
# =============================================================================

def simulate_post_finish_jos3(jos3_model, cvr_model, weather_steps, *, t_rect_finish,
                              co_reserve_finish, auc_klinisch_race, met_finish,
                              met_initial, met_cv_finish, cumulative_water_loss_g,
                              weight_kg, sweat_factor, thirst_threshold, clo_value,
                              walked=True):
    """[2026-10-20] Finish zone with the runner's own JOS-3 model. See the
    PF_JOS3 block for the mechanisms. weather_steps: list of (tdb, mrt, rh,
    wind_1_5m) covering the window (one entry per minute or repeated)."""
    dt = PF_JOS3_DT_MIN
    n = int(round(PF_JOS3_DUUR_MIN / dt))
    walk_min = PF_WALK_MIN if walked else 0.0
    t_rect = t_rect_finish
    co_res = co_reserve_finish
    t_hist, c_hist, time_hist = [t_rect_finish], [co_reserve_finish], [0.0]
    t_piek = t_rect_finish
    auc_kl_pf = 0.0
    ehs_pf, t_ehs_pf = False, float('nan')
    tcf_dose_pf, tcf_time_pf, t_tcf_pf = 0.0, 0.0, float('nan')
    met_cv = met_cv_finish if met_cv_finish is not None else met_finish
    water = float(cumulative_water_loss_g)
    can_drink = True
    co_max_ref = None
    eac_load, eac_tol_min = 0.0, 1.0
    # after-glow impulses: (start minute, amount degC)
    denom = max(0.5, met_initial - PF_MET_RUST)
    met_after_finish = PF_MET_WALK if walk_min > 0 else PF_MET_RUST
    impulses = [(0.0, PF_DELTA_T_NAGLOED * max(0.0, met_finish - met_after_finish) / denom)]
    if walk_min > 0:
        impulses.append((walk_min, PF_DELTA_T_NAGLOED * max(0.0, PF_MET_WALK - PF_MET_RUST) / denom))
    try:
        from pythermalcomfort.jos3_functions.matrix import INDEX as _IDX
        core_idx = _IDX["core"]
    except Exception:
        core_idx = None
    for k in range(n):
        t = k * dt
        walking = t < walk_min
        standing = (not walking) and (t < walk_min + PF_STAND_MIN)
        met_now = PF_MET_WALK if walking else PF_MET_RUST
        tdb, mrt, rh, wind = weather_steps[min(len(weather_steps) - 1, int(t))]
        # after-glow into the core
        q = 0.0
        for t0, amt in impulses:
            if t >= t0:
                q += amt * (np.exp(-(t - t0) / PF_TAU_NAGLOED) - np.exp(-(t + dt - t0) / PF_TAU_NAGLOED))
        if q > 0 and core_idx is not None:
            jos3_model._t_body[core_idx] += q
        jos3_model.par = jos3_par(jos3_model, met_now)
        jos3_model.tdb, jos3_model.tr, jos3_model.rh = tdb, mrt, rh
        jos3_model.v = max(0.1, float(wind) + (0.8 if walking else 0.0))
        jos3_model.clo = clo_value
        jos3_model.simulate(times=1, dtime=int(round(dt * 60)))
        t_rect = jos3_t_rect(jos3_model)
        # fluid: sweat continues, drinking as in the race
        try:                                    # last step only (dict_results() rebuilds the whole history)
            g_s = float(np.sum(np.asarray(getattr(jos3_model._history[-1],
                                                    'weight_loss_by_evap_and_res'), dtype=float)))
        except Exception:
            _wl = np.asarray(jos3_model.dict_results().get('weight_loss_by_evap_and_res', [0.0]), dtype=float).ravel()
            g_s = float(_wl[-1]) if _wl.size else 0.0
        water += g_s * 60.0 * dt * sweat_factor
        if (water / 1000.0) / weight_kg * 100.0 >= thirst_threshold and can_drink:
            water = max(0.0, water - np.random.uniform(120, 180))
            can_drink = False
        if k % int(round(5.0 / dt)) == 0:
            can_drink = True                       # at most one drink per 5 min
        # heart
        met_cv = cv_met_lag(met_cv, met_now, dt)
        if cvr_model is not None:
            snap = JOS3Outputs(
                t_min=t, cardiac_output=0.0, t_core_mean=jos3_core_for_chsi(jos3_model),
                t_cb=t_rect, weight_loss_g_s=water / 1000.0, bf_skin_total=0.0,
                bf_ava_hand=0.6, bf_ava_foot=0.6, current_met=met_cv,
                t_skin_mean=float(jos3_model.t_skin.mean()))
            st = cvr_model.compute_step(snap)
            if co_max_ref is None:
                co_max_ref = float(st.CO_max)
            pool = 0.0
            if not walking:
                ts = t - walk_min
                pool = PF_POOLING_FRAC_OF_COMAX * co_max_ref * np.exp(-ts / PF_TAU_POOLING)
            co_res = max(-5.0, float(st.CO_reserve) - pool)
        if standing:                               # [2026-10-20] EAC-staan load
            _tol = eac_tolerance(float(jos3_model.t_skin.mean()), t_rect,
                                 (water / 1000.0) / weight_kg * 100.0)
            eac_load += dt / max(1e-6, _tol)
            eac_tol_min = min(eac_tol_min, _tol)
        t_piek = max(t_piek, t_rect)
        t_hist.append(t_rect); c_hist.append(co_res); time_hist.append(t + dt)
        auc_kl_pf += max(0.0, t_rect - T_AUC_KLINISCH) * dt
        if TCF_AVAILABLE:
            inc = control_failure_increment(t_rect, co_res, dt, TCF_CONFIG)
            tcf_dose_pf += inc
            if inc > 0:
                tcf_time_pf += dt
                if np.isnan(t_tcf_pf):
                    t_tcf_pf = t + dt
        if t_rect > 40.5 and co_res <= CO_RESERVE_CEILING_TOL and not ehs_pf:
            ehs_pf, t_ehs_pf = True, t + dt
    return {
        't_rect_piek_postfinish'  : round(t_piek, 4),
        'co_reserve_postfinish'   : round(co_res, 4),
        'auc_klinisch_postfinish' : round(auc_kl_pf, 3),
        'auc_klinisch_totaal'     : round(auc_klinisch_race + auc_kl_pf, 3),
        'ehs_postfinish'          : ehs_pf,
        't_ehs_postfinish_min'    : t_ehs_pf,
        'control_failure_dose_postfinish'     : round(tcf_dose_pf, 4),
        'control_failure_time_postfinish_min' : round(tcf_time_pf, 3),
        't_control_failure_postfinish_min'    : t_tcf_pf,
        't_rect_series_postfinish'    : t_hist,
        'co_reserve_series_postfinish': c_hist,
        'time_min_series_postfinish'  : time_hist,
        'eac_staanbelasting'          : round(eac_load, 4),
        'eac_tolerantie_min'          : round(eac_tol_min, 4),
        'eac_kans'                    : eac_probability(eac_load),
    }


def calculate_adult_rpe_from_hr(hr, hr_rest, hr_max, training_factor, mf_score):
    """[2026-10-19] Borg 6-20 RPE from the CVR model's heart rate (author's
    decision, RPE_FROM_CVR_HR).

    Borg designed the 6-20 scale to run linearly with heart rate from rest
    (~60/min -> 6) to maximum (~200/min -> 20). Applied per person:
        RPE = 6 + 14 x (HR - HR_rest) / (HR_max - HR_rest)
    HR is the CVR model's own heart rate (Lloyd 2022), which already rises
    with heat strain and dehydration (CHSI) and reaches HR_max at the
    cardiovascular ceiling. The separate heat penalty of the old formula
    (1.8 per degC above 38) is therefore dropped: keeping it counted heat
    twice (tested on 100 Amsterdam runners: with half the penalty, 38 %
    'stopped'; without it, 6 %, late in the race). Training and motivation
    modifiers as in calculate_adult_rpe_improved (motivation sign fixed).
    """
    hrr = float(np.clip((hr - hr_rest) / max(1.0, hr_max - hr_rest), 0.0, 1.0))
    base_rpe = 6.0 + 14.0 * hrr
    rpe_physical = float(np.clip(base_rpe * (1.0 - training_factor * 0.15), 6.0, 20.0))
    motivation_effect = (mf_score - 0.5) * 2.0 * (20.0 - rpe_physical) * 0.15
    rpe_total = float(np.clip(rpe_physical - motivation_effect, 6.0, 20.0))
    return rpe_physical, rpe_total


def calculate_adult_rpe_improved(current_met, t_rect, training_factor,
                                  acclimatization_factor, mf_score,
                                  pct_vo2max=None, runner_age=None):
    """
    Borg 6-20 RPE for adults.

    [2026-07, REBUILT] Previously a piecewise-linear function of ABSOLUTE
    MET alone (unchanged from rev09) -- found via an unrelated
    investigation (why % first-aid-contact was implausibly high for a
    marathon) that this was inconsistent with how the rest of this model
    treats effort: `AdultParticipantProfile.pct_vo2max` (the rev13 "causal"
    MET assignment) already exists specifically because *relative*
    intensity, not absolute MET, is what should drive individual response
    -- two people at the same absolute MET but very different fitness do
    not find it equally hard. The old RPE formula ignored pct_vo2max
    entirely and used only a flat, fitness-independent `training_factor`
    discount on top of absolute MET.

    Checked whether this was already implicitly handled by cross-checking
    RPE against this model's own independently-computed heart rate
    (Borg's own design principle: RPE*10 approx. HR in bpm). Population-
    pooled correlation was misleadingly near zero (0.066, diluted by
    between-person differences in baseline fitness); the more meaningful
    within-participant correlation over time was strong (median 0.913,
    100% of participants >0.7) -- so the OLD formula's time-course
    behaviour was not broken. The absolute-MET-vs-relative-intensity gap
    was a separate, valid structural point, not evidence the old formula
    was wrong in itself.

    New formula, grounded in two established equations rather than
    hand-tuned breakpoints:
        %HRmax = 0.64 * %VO2max + 37        (Swain DP et al., 1994,
                                              Med Sci Sports Exerc 26:112-6)
        HR_max = 208 - 0.7 * age             (Tanaka H et al., 2001,
                                              J Am Coll Cardiol 37:153-6 --
                                              same formula already used in
                                              HESTIA_CVR_Module_v2.py, for
                                              consistency across the suite)
        RPE (Borg 6-20) approx. HR / 10      (Borg's own original scale
                                              design principle)
    combined: base_rpe = (0.64*pct_vo2max*100 + 37) / 100 * HR_max / 10

    Falls back to the old absolute-MET formula if `pct_vo2max` or
    `runner_age` is not supplied (backward compatible with any caller
    that does not have these, e.g. a future pediatric/simplified path).

    Parameters
    ----------
    current_met : float
        Current metabolic rate (MET) -- only used by the legacy fallback
        path now, kept for backward-compatible call signatures.
    pct_vo2max : float, optional
        Current fraction of VO2max (0-1). Drives the new relative-
        intensity RPE calculation.
    runner_age : float, optional
        Age in years, for HR_max (Tanaka 2001).
    """
    if pct_vo2max is not None and runner_age is not None:
        hr_max        = 208.0 - 0.7 * runner_age
        pct_hrmax      = np.clip(0.64 * (pct_vo2max * 100.0) + 37.0, 0.0, 100.0)
        hr_predicted   = (pct_hrmax / 100.0) * hr_max
        base_rpe       = hr_predicted / 10.0
    else:
        # Legacy fallback: original rev09 piecewise-linear absolute-MET formula.
        if current_met <= 2.0:
            base_rpe = 6.0 + (current_met - 1.0) * 2.0
        elif current_met <= 6.0:
            base_rpe = 8.0 + (current_met - 2.0) * 1.0
        elif current_met <= 10.0:
            base_rpe = 12.0 + (current_met - 6.0) * 0.75
        elif current_met <= 14.0:
            base_rpe = 15.0 + (current_met - 10.0) * 0.75
        else:
            base_rpe = 18.0 + min((current_met - 14.0) * 0.4, 2.0)

    training_reduction = training_factor * 0.15
    adjusted_base      = base_rpe * (1.0 - training_reduction)
    if t_rect > 38.0:
        heat_penalty = (t_rect - 38.0) * 1.8 * (1.0 - acclimatization_factor * 0.4)
    else:
        heat_penalty = 0.0
    rpe_physical       = np.clip(adjusted_base + heat_penalty, 6.0, 20.0)
    motivation_modifier= (mf_score - 0.5) * 2.0
    motivation_effect  = motivation_modifier * (20.0 - rpe_physical) * 0.15
    # [2026-10-19, BUG FIX, author's decision] Was '+': a MORE motivated
    # runner got a HIGHER rpe_total and so stopped EARLIER on RPE >= 19.5 --
    # the opposite of what mf_score means elsewhere in the suite (motivation
    # keeps runners going; Flouris 2024, see K_p notes). Now '-'.
    rpe_total          = np.clip(rpe_physical - motivation_effect, 6.0, 20.0)
    return rpe_physical, rpe_total


def calculate_pediatric_rpe_improved(current_met, t_core, fitness_factor,
                                      mf_score, age_group):
    """OMNI 0-10 RPE for children. Unchanged from rev09."""
    if age_group == "0-10":
        max_met_capacity  = 10.5
        thermal_threshold = 38.3
    else:
        max_met_capacity  = 13.0
        thermal_threshold = 38.2
    rel = np.clip(current_met / max_met_capacity, 0.0, 1.0)
    if rel <= 0.3:
        base_rpe = rel * 10.0
    elif rel <= 0.6:
        base_rpe = 3.0 + (rel - 0.3) * 11.0
    elif rel <= 0.85:
        base_rpe = 6.3 + (rel - 0.6) * 10.8
    else:
        base_rpe = 9.0 + (rel - 0.85) * 6.7
    fitness_reduction = fitness_factor * 0.20
    adjusted_base     = base_rpe * (1.0 - fitness_reduction)
    heat_penalty      = (t_core - thermal_threshold) * 1.2 if t_core > thermal_threshold else 0.0
    rpe_physical      = np.clip(adjusted_base + heat_penalty, 0.0, 10.0)
    motivation_modifier = (mf_score - 0.5) * 2.0
    motivation_effect   = motivation_modifier * (10.0 - rpe_physical) * 0.25
    rpe_total           = np.clip(rpe_physical - motivation_effect, 0.0, 10.0)   # [2026-10-19] sign fixed, see adult RPE
    return rpe_physical, rpe_total


# =============================================================================
#  CORE ADULT SIMULATION WORKER (rev10 changes marked [rev10]; rev11 marked [rev11];
#                                  rev13 changes marked [rev13])
#
#  CHANGE SUMMARY vs rev12
#  -----------------------
#  [rev13-P4] Dynamic pacing: current_met is updated each time step based on
#  the previous T_rect (closed pacing loop). The open-loop constant-MET
#  assumption is replaced by a proportional controller:
#
#    thermal_overshoot  = max(0, T_rect[t-1] - T_RECT_PACING_THRESHOLD)
#    met_reduction      = K_P_PACING * thermal_overshoot
#    current_met[t]     = max(1.5, met_initial - training_offset - met_reduction)
#
#  met_initial = base_met_from_vo2max (unchanged from rev12 pre-loop computation)
#  training_offset = training_factor * base_met_from_vo2max * 0.05 (rev11, unchanged)
#  K_P_PACING = 0.10 MET/°C (Ely BR et al. 2010, Med Sci Sports Exerc 42(1):135-141; module constant)
#  T_RECT_PACING_THRESHOLD = 38.5°C (module constant)
#
#  The training_offset represents running economy and is kept outside the
#  thermal feedback term -- economy and voluntary pacing are orthogonal.
#  current_met is stored per time step in results for diagnostics.
#
#  [rev13-P5] AUC_thermisch: cumulative integral of T_rect > 39.0°C (°C·min)
#  is accumulated in the loop and stored in results. This implements
#  a time-integrated thermal dose concept. [2026-10-17: earlier attributed
#  to Breslow; not found in Breslow 2021.] T_AUC_THRESHOLD = 39.0°C
#  (module constant).
#
#  CHANGE SUMMARY vs rev09-rev12 (retained from earlier revisions)
#  ----------------------------------------------------------------
#  The met_variation field has been removed from AdultParticipantProfile.
#  MET is now computed from VO2max and pct_vo2max:
#
#    base_met_from_vo2max = participant.vo2max * participant.pct_vo2max
#                           / VO2MAX_TO_MET_FACTOR
#
#  A training_factor deterministic shift is then applied  [rev11: REVISED]:
#    training_offset = training_factor * base_met_from_vo2max * 0.05
#    final_met       = base_met_from_vo2max - training_offset
#
#  TRAINING_FACTOR DOUBLE-CORRECTION (rev11 resolution)
#  -----------------------------------------------------
#  Rev10 applied training_factor in two independent places:
#    1. generate_base_population(): mu of pct_vo2max -= training_factor * 0.08
#    2. here: MET further reduced by training_factor * base_met * 0.15
#
#  Combined effect at tf=1.0 was:
#    effective %VO2max = (0.80 - 0.08) * (1 - 0.15) = 0.72 * 0.85 = 0.61
#
#  This is too low for a competitive marathon population. Rev11 reduces the
#  step-2 coefficient from 0.15 to 0.05, giving:
#    tf=0.0: effective pct ≈ 0.80 * 1.00 = 0.80
#    tf=0.5: effective pct ≈ 0.76 * 0.975 = 0.74
#    tf=1.0: effective pct ≈ 0.72 * 0.95  = 0.68
#
#  These values are consistent with the physiological literature for
#  recreational marathon runners (Joyner 1991; Jones & Carter 2000).
#  Clinical calibration (Radboudumc) is still needed to
#  determine the precise coefficient value.
#
#  The base_met parameter (user-selected activity MET) is NO LONGER used
#  to drive the individual simulation. It is retained as a reference value
#  for the population mean validation and for the MET threshold analysis
#  (unchanged). Each participant's MET is now fully determined by their
#  own VO2max and pct_vo2max, making cross-scenario comparisons valid.
# =============================================================================

def simulate_post_finish(t_rect_finish: float,
                          co_reserve_finish: float,
                          auc_klinisch_race: float,
                          wbgt_finish: float,
                          co_max_finish: float = None,
                          cvr_model=None,
                          t_skin_finish: float = None,
                          dehydration_kg_finish: float = 0.0,
                          met_cv_finish: float = None) -> dict:
    """
    Propagate T_rect and CO_reserve for PF_DUUR_MIN minutes after the finish.

    After crossing the finish line:
      1. The pacing controller (K_p) is no longer active -- open loop.
      2. Metabolic after-glow: residual heat production decays exponentially.
         Peak amplitude PF_DELTA_T_NAGLOED, time constant PF_TAU_NAGLOED.
      3. Venous pooling: muscle pump stops abruptly, causing an acute,
         short-lived drop in venous return/CO on top of whatever the
         steady-state cardiovascular balance would otherwise give.
      4. Passive cooling from sweating continues but at reduced rate because
         cutaneous blood flow is compromised by pooling.

    [2026-07, REBUILT] Previously CO_reserve only ever decreased after the
    finish (`co_res -= pooling_rate * dt`, with pooling_rate >= 0 always) --
    mathematically incapable of recovery no matter how long the simulated
    window was (verified: extending the window from 10 to 30 min just
    scaled the reported "duration" proportionally, the signature of
    right-censoring, not a real recovery process). This was inconsistent
    with the same-day CVR rebuild on Lloyd et al. (2022): T_rect declining
    after the finish should let the Cardiac Heat Strain Index (CHSI) fall,
    which raises CO_max back up, and MET dropping to resting level should
    sharply cut CO_demand -- both push CO_reserve to recover, given enough
    time, exactly as it does during a real recovery.

    Fixed by recomputing CO_max/CO_demand at every post-finish step via the
    SAME `CVRModel.compute_step()` used during the race, fed the (already
    computed, unchanged) declining T_rect and a resting MET
    (`PF_MET_RUST`), instead of reading a single value frozen at the finish
    line. The acute venous-pooling term is kept as an *additional*,
    separately-decaying perturbation on top of this recomputed baseline --
    it represents a real, short-lived phenomenon (the muscle pump stopping
    abruptly) distinct from the steady-state cardiovascular rebalancing
    Lloyd's equations describe, and removing it entirely would lose the
    validated acute dip (30.7% of positive-finish-CO_reserve participants
    crossing zero within the window, confirmed against Falmouth 2015 data
    when this term was first added).

    T_skin is not independently modelled post-finish (no detailed model
    available); approximated by holding the T_core-T_skin gap observed at
    the finish line constant as T_core declines. Dehydration is held
    constant post-finish (no further sweat loss modelled).

    EHS criterion post-finish:
        T_rect > 40.5 deg C  AND  CO_reserve <= 0

    Parameters
    ----------
    t_rect_finish      : float  -- T_rect at moment of finishing (deg C)
    co_reserve_finish  : float  -- CO_reserve at moment of finishing
    auc_klinisch_race  : float  -- AUC_klinisch accumulated during race
    wbgt_finish        : float  -- WBGT at finish (deg C), used for passive cooling
    co_max_finish      : float, optional -- heat-adjusted CO_max at finish
        (L/min). Drives the *absolute* magnitude of the acute venous-pooling
        perturbation (see PF_POOLING_FRAC_OF_COMAX) -- falls back to a
        population-typical 20.0 L/min if not supplied.
    cvr_model          : CVRModel, optional -- if supplied, CO_max/CO_demand
        are recomputed each step via compute_step(), enabling recovery. If
        None, falls back to the old one-way pooling-only formula (backward
        compatible with any caller that does not have a CVRModel instance).
    t_skin_finish      : float, optional -- mean skin temperature at finish
        (deg C), for the CHSI calculation. Falls back to t_rect_finish - 4.0
        (matches CVRModel.compute_step()'s own fallback) if not supplied.
    dehydration_kg_finish : float -- cumulative body-water loss at finish
        (kg), held constant through the post-finish window.

    Returns
    -------
    dict with keys:
        t_rect_piek_postfinish   : float  -- peak T_rect in finish zone
        co_reserve_postfinish    : float  -- CO_reserve at end of window
        auc_klinisch_postfinish  : float  -- additional AUC_klinisch post-finish
        auc_klinisch_totaal      : float  -- race + post-finish combined
        ehs_postfinish           : bool   -- EHS criterion met in finish zone
        t_ehs_postfinish_min     : float  -- minutes after finish at EHS (nan if not)

    References
    ----------
    Roberts WO (1998) Exertional heat stroke during a cool weather marathon.
    Rowell LB (1974) Human cardiovascular adjustments to exercise and heat stress.
    Lloyd A, Fiala D, Heyde C, Havenith G (2022) J Appl Physiol 133:247-261.
    """
    if co_max_finish is None or not np.isfinite(co_max_finish):
        co_max_finish = 20.0  # population-typical fallback (L/min)

    # T_core-T_skin gap at finish, held constant as a simple approximation
    # for T_skin's post-finish evolution (no detailed model available).
    if t_skin_finish is None or not np.isfinite(t_skin_finish):
        t_skin_finish = t_rect_finish - 4.0  # matches compute_step()'s own fallback
    t_core_skin_gap = t_rect_finish - t_skin_finish

    # Passive cooling rate depends on WBGT -- higher WBGT means less cooling
    # At WBGT=25 the passive cooling is negligible; at WBGT=15 it is ~0.05 deg C/min
    koeling = max(0.0, PF_KOELING_PER_MIN * (1.0 - (wbgt_finish - 15.0) / 20.0))

    t_rect    = t_rect_finish
    co_res    = co_reserve_finish
    auc_kl_pf = 0.0
    t_rect_piek = t_rect_finish
    ehs_pf    = False
    t_ehs_pf  = float('nan')
    tcf_dose_pf = 0.0
    tcf_time_pf = 0.0
    t_tcf_pf = float('nan')

    n_stappen = int(PF_DUUR_MIN / PF_DT_MIN)

    # [suite-integration addition] Track the per-step trajectory. The physics
    # here are unchanged -- these lists just record the same t_rect/co_res
    # values the loop already computes at each step, for plotting. t=0 is the
    # finish line itself.
    t_rect_history = [t_rect_finish]
    co_res_history = [co_reserve_finish]
    time_history   = [0.0]

    for stap in range(n_stappen):
        t = stap * PF_DT_MIN   # minutes after finish

        # Metabolic after-glow: exponential decay
        # [2026-10-14 FIX, units] Was:
        #   warmte_in = PF_DELTA_T_NAGLOED * exp(-t/tau) * dt
        # i.e. 0.40 used as a RATE (degC/min). Its time integral is
        # PF_DELTA_T_NAGLOED * PF_TAU_NAGLOED = 0.80 degC -- twice the
        # documented "peak amplitude 0.40 degC" -- and the Euler sum at
        # dt=0.5 min added ~13% more. Verified on the Amsterdam 2026-10-18
        # run: post-finish peak exceeded the race peak for 99.2% of
        # participants, by +0.53 degC on average (+0.65 in the tail),
        # raising the >42 degC count from 2 to 7. Now the exact integral
        # of the exponential over each step, so the total after-glow
        # equals PF_DELTA_T_NAGLOED (0.40 degC) as documented.
        warmte_in  = PF_DELTA_T_NAGLOED * (np.exp(-t / PF_TAU_NAGLOED)
                                           - np.exp(-(t + PF_DT_MIN) / PF_TAU_NAGLOED))

        # Net temperature change
        t_rect += warmte_in - koeling * PF_DT_MIN
        t_rect  = max(36.5, t_rect)   # floor: cannot drop below resting

        # Venous pooling: an acute, short-lived perturbation on top of
        # whatever the recomputed steady-state CO_reserve gives below.
        # [2026-07, REVISED again] Previously this WAS the entire
        # CO_reserve update (co_res -= pooling_rate*dt, monotonically
        # decreasing forever -- verified this made "recovery" mathematically
        # impossible regardless of window length). Kept as an additive
        # perturbation, not the whole story, because it represents a real,
        # distinct, short-duration phenomenon (the muscle pump stopping
        # abruptly) that Lloyd's steady-state CO_max/CO_demand relationship
        # does not itself capture -- removing it entirely would lose the
        # validated acute dip (30.7% of positive-finish-CO_reserve
        # participants crossing zero within the window when this term was
        # first added and tested against Falmouth 2015 data).
        pooling_rate = (PF_POOLING_FRAC_OF_COMAX * co_max_finish *
                        np.exp(-t / PF_TAU_POOLING))
        pooling_deficit = pooling_rate * PF_DT_MIN

        if cvr_model is not None:
            # [2026-07] Recompute CO_max/CO_demand via the same Lloyd-based
            # compute_step() used during the race, fed the now-declining
            # T_rect and a resting MET -- this is what actually enables
            # recovery: as T_rect falls, CHSI falls, CO_max rises back up;
            # and CO_demand drops sharply once MET is at rest instead of
            # race pace.
            t_skin_now = t_rect - t_core_skin_gap
            jos3_step = JOS3Outputs(
                t_min=t, cardiac_output=0.0,  # unused: current_met drives demand instead
                t_core_mean=t_rect, t_cb=t_rect,
                weight_loss_g_s=dehydration_kg_finish,
                bf_skin_total=0.0, bf_ava_hand=0.6, bf_ava_foot=0.6,
                t_skin_mean=t_skin_now,
                current_met=(PF_MET_RUST if (met_cv_finish is None or not CV_LAG_ENABLED)
                             else PF_MET_RUST + (met_cv_finish - PF_MET_RUST)
                             * np.exp(-(t + PF_DT_MIN) / CV_TAU_FALL_MIN)),   # [2026-10-20] lagged recovery
            )
            cvr_state_pf = cvr_model.compute_step(jos3_step)
            co_res = cvr_state_pf.CO_reserve - pooling_deficit
        else:
            # Legacy fallback (no CVRModel supplied): old pooling-only
            # formula, kept for backward compatibility.
            co_res -= pooling_deficit
        co_res = max(-5.0, co_res)   # numeric floor only, not a recovery cap

        # Track peak T_rect
        if t_rect > t_rect_piek:
            t_rect_piek = t_rect

        t_rect_history.append(t_rect)
        co_res_history.append(co_res)
        time_history.append(t + PF_DT_MIN)

        # AUC_klinisch accumulation post-finish
        auc_kl_pf += max(0.0, t_rect - T_AUC_KLINISCH) * PF_DT_MIN

        # [rev17] Thermoregulatory Control Failure dose post-finish.
        # This is a mechanistic risk marker, not a clinical EHS diagnosis:
        # max(0, T_rect - 40.5) * max(0, -CO_reserve) * dt.
        if TCF_AVAILABLE:
            tcf_inc = control_failure_increment(t_rect, co_res, PF_DT_MIN, TCF_CONFIG)
            tcf_dose_pf += tcf_inc
            if tcf_inc > 0:
                tcf_time_pf += PF_DT_MIN
                if np.isnan(t_tcf_pf):
                    t_tcf_pf = t + PF_DT_MIN

        # EHS criterion check
        if t_rect > 40.5 and co_res <= CO_RESERVE_CEILING_TOL and not ehs_pf:
            
        #if t_rect > 40.5 and co_res <= 0 and co_reserve_finish > 0 and not ehs_pf:    
            ehs_pf   = True
            t_ehs_pf = t + PF_DT_MIN

        # Early termination if T_rect safely below threshold
        if t_rect < 39.0 and t > 3.0:
            break

    return {
        't_rect_piek_postfinish'  : round(t_rect_piek, 4),
        'co_reserve_postfinish'   : round(co_res, 4),
        'auc_klinisch_postfinish' : round(auc_kl_pf, 3),
        'auc_klinisch_totaal'     : round(auc_klinisch_race + auc_kl_pf, 3),
        'ehs_postfinish'          : ehs_pf,
        't_ehs_postfinish_min'    : t_ehs_pf,
        'control_failure_dose_postfinish'     : round(tcf_dose_pf, 4),
        'control_failure_time_postfinish_min' : round(tcf_time_pf, 3),
        't_control_failure_postfinish_min'    : t_tcf_pf,
        # [suite-integration addition] full per-step trajectory, for plotting
        't_rect_series_postfinish'    : t_rect_history,
        'co_reserve_series_postfinish': co_res_history,
        'time_min_series_postfinish'  : time_history,
    }


def calculate_indices_jos3_adult(interp_data, lat, lon, met_value, clo_value,
                                  participant_params, training_factor,
                                  acclimatization_factor):
    """
    Run the core JOS-3 simulation for a single virtual adult participant.

    [rev10] MET computation change:
    MET is no longer taken from participant_params.met_variation (removed).
    Instead it is derived from VO2max and pct_vo2max:
        base_met = vo2max * pct_vo2max / VO2MAX_TO_MET_FACTOR
        final_met = base_met * (1 - training_factor * 0.05)  [rev11: was 0.15]

    [rev11] training_offset coefficient reduced from 0.15 to 0.05.
    See CORE ADULT SIMULATION WORKER block above for full rationale.
    The effective %VO2max at the simulation MET level is now:
        tf=0.0 -> ~0.80; tf=0.5 -> ~0.74; tf=1.0 -> ~0.68.

    The met_value argument is retained for backward compatibility but is
    only used by the liveability check (Vanos et al. 2023), not as the
    individual simulation MET. This is intentional: liveability limits are
    defined for the EVENT pace (user-selected MET), not the individual.

    Parameters
    ----------
    interp_data : list of dicts
    lat, lon : float
    met_value : float
        Base MET of the chosen activity (reference only; individual MET
        is derived from vo2max * pct_vo2max / VO2MAX_TO_MET_FACTOR).
    clo_value : float
    participant_params : AdultParticipantProfile
    training_factor : float
    acclimatization_factor : float

    Returns
    -------
    list of dicts -- one per time step
    """
    # Extract fields (all by name -- no positional indexing)
    height           = participant_params.height
    weight           = participant_params.weight
    runner_age       = participant_params.age
    gender           = participant_params.gender
    vo2max           = participant_params.vo2max
    pct_vo2max       = participant_params.pct_vo2max   # [rev10] replaces met_variation
    temp_var         = participant_params.temp_variation
    rh_var           = participant_params.rh_variation
    mf_score         = participant_params.mf_score
    sweat_factor     = participant_params.sweat_factor
    thirst_threshold = participant_params.thirst_threshold

    # ------------------------------------------------------------------
    # [rev10] INDIVIDUAL MET -- derived from VO2max and pct_vo2max
    #
    # This guarantees %VO2max == pct_vo2max by construction.
    # The training_offset shifts MET downward for better-trained runners
    # (improved economy: same %VO2max, lower absolute energy cost per kg).
    #
    # [rev11] Coefficient reduced from 0.15 to 0.05 to avoid compounding
    # with the pct_vo2max mu-shift already applied in generate_base_population().
    # Net effective %VO2max: tf=0.0 -> ~0.80; tf=0.5 -> ~0.74; tf=1.0 -> ~0.68.
    # ------------------------------------------------------------------
    base_met_from_vo2max = vo2max * pct_vo2max / VO2MAX_TO_MET_FACTOR
    training_offset      = training_factor * base_met_from_vo2max * 0.05
    current_met          = max(1.5, base_met_from_vo2max - training_offset)

    # [rev13-P4] Store initial MET for dynamic pacing reference.
    met_initial = current_met

    # [rev14-A] Individual pacing gain from participant profile.
    # Falls back to module constant K_P_PACING if field absent (backwards compat).
    kp_ind = getattr(participant_params, 'kp_pacing', K_P_PACING)
    # [fix] Individual cardiovascular pacing gain, sampled the same way as
    # the thermal one (getattr with a fallback default) -- see K_P_PACING_CV
    # definition above for the validation caveat.
    kp_ind_cv = getattr(participant_params, 'kp_pacing_cv', K_P_PACING_CV)

    # [rev13-P5] Initialise AUC_thermisch accumulator (°C·min, diagnostic).
    auc_thermisch = 0.0
    # [rev14-B] Initialise AUC_klinisch accumulator (Roberts 2007, clinical).
    auc_klinisch  = 0.0

    # Environment
    times      = [entry["time"] for entry in interp_data]
    temps      = [entry["temp"] + temp_var for entry in interp_data]
    wind_10m   = [entry["wind"] for entry in interp_data]
    wind_1_5m  = [wind_speed_at_height(w, 10, 1.5) for w in wind_10m]
    rhs        = [np.clip(entry["rh"] + rh_var, 10, 95) for entry in interp_data]
    clouds     = [entry["clouds"] for entry in interp_data]
    pressures  = [entry["pressure"] for entry in interp_data]

    aqi             = get_air_quality(lat, lon)
    # [fix] Prefer Thermopoulos/Klimatos's own precomputed solar radiation,
    # solar elevation, globe temperature and MRT (now carried through by
    # interpolate_weather/get_hourly_weather) over HESTIA's own internal
    # clear-sky + linear-cloud-attenuation reconstruction. The internal
    # model was found to underestimate GHI by ~2.5-3x at high cloud cover
    # (verified: Amsterdam DtD hindcast, 2024-09-22, 97% cloud cover ->
    # internal 132 W/m^2 vs Thermopoulos' own 350-400 W/m^2), which fed
    # directly into jos3_model.tr and so affected simulated T_rect, not
    # just a display value. Falls back to the internal calculation only
    # when the source sheet predates these columns (all-None).
    # [2026-10-24] Measured/forecast radiation preferred, see radiation_series().
    ghi, solar_elevations, globe_temps, mrts, _rad_bron = radiation_series(
        interp_data, times, temps, wind_1_5m, pressures, clouds, lat, lon, aqi, rhs=rhs)
    # [fix] Same precomputed-preferred approach for wet-bulb temperature --
    # checked independently since a file could have T_wetbulb without the
    # solar/globe columns above, or vice versa. Klimatos can generate
    # T_wetbulb via a fuller, pressure-aware psychrometric model
    # (pythermalcomfort.models.wet_bulb_temperature) as well as the simpler
    # Stull approximation HESTIA always used internally
    # (pythermalcomfort.utilities.wet_bulb_tmp) -- using the precomputed
    # column when present avoids that mismatch.
    if interp_data[0].get('twb_precomputed') is not None:
        twbs = [entry['twb_precomputed'] for entry in interp_data]
    else:
        twbs = [wet_bulb_tmp(tdb=t, rh=r) for t, r in zip(temps, rhs)]
    # [fix] Same precomputed-preferred approach for the final WBGT/UTCI
    # values themselves -- verified that even with correct twb/tg/mrt
    # inputs, HESTIA's own wbgt()/utci() recalculation left a small
    # (~0.2-1.6C) residual gap vs. Thermopoulos' own WBGT/UTCI columns
    # (Amsterdam DtD hindcast, 2024-09-22). Checked per-timestep (not
    # all-or-nothing) since these are independent of the other fields.
    wbgts_pre = [entry.get('wbgt_precomputed') for entry in interp_data]
    utcis_pre = [entry.get('utci_precomputed') for entry in interp_data]
    # JOS-3 setup
    # [fix] Use the per-individual sampled body_fat_pct (see
    # generate_base_population()) instead of a fixed 25%/15% split by sex.
    # getattr() keeps this backward-compatible with any caller still passing
    # a plain object/tuple without the field.
    fat_percentage = getattr(participant_params, 'body_fat_pct', 25 if gender == "female" else 15)
    # [2026-10-23] age decrement scaled by fitness and heat acclimatisation (jos3_leeftijd)
    jos3_leeftijd.set_person(vo2max, runner_age, gender, acclimatization_factor)
    jos3_model     = maak_jos3(height=height, weight=weight, age=runner_age,
                          fat=fat_percentage, sex=gender)
    # [2026-10-19] removed the no-op 'jos3_model.t_core[:] = 37.0' (see FOUNDATION REPAIR)

    time_steps_minutes = [(times[i+1] - times[i]).total_seconds() / 60.0
                           for i in range(len(times) - 1)]
    time_steps_minutes.insert(0, 0)

    # CVR initialisation
    if CVR_AVAILABLE:
        cvr_runner = RunnerProfile(
            mass=weight, height=height * 100,
            age=runner_age, sex=gender, vo2max=vo2max,
            hr_max=(getattr(participant_params, 'hr_max_known', 0.0) or None),
            hr_rest=(getattr(participant_params, 'hr_rest_known', 0.0) or None),
            acclimatisation=float(acclimatization_factor or 0.0),   # [2026-11-01] plasma volume
        )
        jos3_cvr_series          = []
        cvr_water_loss_kg        = 0.0
        # [fix] Live CVRModel instance for in-loop, cardiovascular-driven
        # pacing (see dynamic pacing block below). Uses the SAME
        # CVRModel.compute_step() method as the final post-loop batch pass
        # (link_cvr_to_jos3) -- not a separate/simplified approximation,
        # so there is no risk of the live pacing signal drifting from the
        # final reported CO_reserve, unlike the earlier weather-duplication
        # bugs found and fixed elsewhere in this project.
        cvr_model_live = CVRModel(cvr_runner)
    else:
        cvr_model_live = None

    results                 = []
    cumulative_water_loss   = 0
    runner_stopped          = False
    # [fix] Tracks the live, in-loop CO_reserve estimate for cardiovascular-
    # driven pacing (see dynamic pacing block below). None until the first
    # live CVR step has run (i==0 has no previous step to base pacing on,
    # same as prev_t_rect).
    prev_co_reserve_live     = None
    jos3_snapshot_prev       = None  # [2026-10-19] state for the forced CV ceiling
    cv_cap_last              = None  # [2026-10-19] ceiling (MET) one step earlier
    cv_integral_met          = 0.0   # [2026-10-14] optional integral pacing term (MET)
    hr_live                  = None  # [2026-10-19] CVR heart rate of this step (RPE)
    met_cv                   = PF_MET_RUST   # [2026-10-20] lagged MET for the CVR module (standing at the start)
    can_drink_again         = True

    # [2026-10-19] Distance-based race (RACE_DISTANCE_MODE), see the constants.
    _pace_plan = float(getattr(participant_params, 'pace_min_per_km', 0.0) or 0.0)
    _dur_plan  = float(getattr(participant_params, 'duration_hours', 0.0) or 0.0)
    _dt_nom    = float(time_steps_minutes[1]) if len(times) > 1 else 10.0
    distance_mode = (RACE_DISTANCE_MODE and _pace_plan > 0 and _dur_plan > 0
                     and len(times) > 1 and _dt_nom > 0)
    if distance_mode:
        _planned_steps = max(2, int(round(_dur_plan * 60.0 / _dt_nom)) + 1)
        _v_plan   = 1000.0 / _pace_plan                       # m/min
        _vo2_plan = _daniels_gilbert_vo2_at_pace(_pace_plan)  # mL/kg/min
        # Exact planned distance and time (the old fixed-duration slice was
        # rounded to whole 10-min steps, up to 5 min off).
        race_target_m    = _v_plan * _dur_plan * 60.0
        race_planned_min = _dur_plan * 60.0
    else:
        race_target_m = race_planned_min = None
    race_dist_m      = 0.0
    race_elapsed_min = 0.0
    race_finished    = False
    stop_min         = None

    def _speed_m_per_min(met_now: float) -> float:
        """Daniels & Gilbert speed for the VO2 that met_now represents,
        scaled so that met_initial gives exactly the planned pace."""
        vo2 = _vo2_plan * met_now / max(1e-6, met_initial)
        a, b, c = 0.000104, 0.182258, -(vo2 + 4.60)
        return max(0.0, (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a))

    # [2026-10-19] After-glow on slowing (SLOWDOWN_AFTERGLOW).
    met_prev_used        = None
    afterglow_total_c    = 0.0
    afterglow_max_step_c = 0.0
    try:
        from pythermalcomfort.jos3_functions.matrix import INDEX as _JOS3_INDEX
        _core_idx = _JOS3_INDEX["core"]
    except Exception:
        _core_idx = None

    for i in range(len(times)):
        if runner_stopped and i > 0 and RPE_STOP_ENDS_RACE:
            # [2026-10-19] The race ends at the RPE stop; the post-finish
            # module below follows the runner from here (not frozen).
            break
        if runner_stopped and i > 0:
            results.append({**results[-1],
                            'time': times[i].strftime('%Y-%m-%d %H:%M'),
                            'stopped': True})
            # [fix, 2026-08-16] jos3_cvr_series must stay in lockstep with
            # `results`, or the post-loop link_cvr_to_jos3() call below
            # produces a CO_reserve series shorter than the race itself --
            # co_reserve silently goes to NaN for every step after the
            # freeze, even though t_rect correctly freezes (copied via
            # {**results[-1], ...} above). Confirmed directly: with this
            # append missing, a participant reaching RPE>=19.5 partway
            # through the race has valid co_reserve up to that point, then
            # NaN for the rest -- which makes cumulative_deficit_dose()
            # silently exclude them from the conjunctive criterion for the
            # remainder of the race REGARDLESS of their true T_rect/
            # CO_reserve state, even if t_rect was frozen above 40.5C.
            # There is already a documented partial fix for the ANALOGOUS
            # symptom at the post-finish boundary (co_reserve_finish
            # fallback, below) -- this is the same root cause, one level
            # up: keep the CVR input series itself from truncating early,
            # rather than patching each place that reads a
            # possibly-truncated result afterward.
            # jos3_snapshot_this_step is still in scope from the last
            # non-frozen iteration (Python for-loop variables persist
            # across iterations); re-appending it is exactly the same
            # "freeze the last known state" semantics results.append()
            # already uses above, just applied to the CVR input series too.
            if CVR_AVAILABLE and jos3_cvr_series:
                jos3_cvr_series.append(jos3_snapshot_this_step)
            continue

        # Liveability check uses the EVENT MET (met_value), not individual
        m_max_threshold = get_liveability_threshold(temps[i], rhs[i], runner_age)
        is_unliveable   = met_value > m_max_threshold

        # [rev13-P4] DYNAMIC PACING: update current_met based on previous T_rect.
        # At i==0 (initialisation step) no T_rect is available yet; use met_initial.
        # From i==1 onward, the previous step's t_rect drives voluntary pace reduction.
        # Ref: Ely BR et al. (2010) Med Sci Sports Exerc 42(1):135-141 (see
        # K_P_PACING docstring for the 2026-09-28 citation correction).
        #
        # [2026-09-28, gewijzigd op expliciet verzoek van de auteur] Cardiovascular
        # pacing term: was een harde knik bij CO_reserve=0 ("reserve is
        # reserve"); is nu, net als de thermische term, een GELEIDELIJKE
        # overschrijding onder CO_RESERVE_PACING_THRESHOLD (2.0 L/min, dezelfde
        # 'decompensation risk'-referentie als elders in dit model) in plaats
        # van pas bij de nuldoorgang. Regeltechnische motivatie: een
        # proportionele respons is consistenter met hoe de thermische term al
        # werkt dan een discrete aan/uit-schakelaar. Zie K_P_PACING_CV
        # docstring voor de onderliggende, nog onopgeloste literatuurdiscussie
        # (Periard 2011 vs. de weerlegging erop) -- deze wijziging kiest een
        # kant in dat debat, lost het niet op.
        #
        # Gevolg om in de gaten te houden: omdat deze term nu al vanaf 2.0 L/min
        # (i.p.v. pas onder 0) meetelt, is hij voor meer deelnemers en een groter
        # deel van de race actief dan voorheen -- bij een ongewijzigde
        # K_P_PACING_CV (nog steeds [NOT VALIDATED]) betekent dat een groter
        # gemiddeld tempoverlies door dit mechanisme dan in de vorige versie.
        if i > 0:
            prev_t_rect       = results[-1]['t_rect']
            thermal_overshoot = max(0.0, prev_t_rect - T_RECT_PACING_THRESHOLD)
            cv_overshoot      = (max(0.0, CO_RESERVE_PACING_THRESHOLD - prev_co_reserve_live)
                                  if prev_co_reserve_live is not None else 0.0)
            # [2026-10-14, standaard AAN] Integrerende term op
            # het onhoudbare deel (CO_reserve < 0 = VO2 boven het door hitte
            # verlaagde VO2max). Zie K_I_PACING_CV bij de constanten.
            if K_I_PACING_CV > 0.0 and prev_co_reserve_live is not None:
                _dt = float(time_steps_minutes[i])
                if prev_co_reserve_live < 0.0:
                    cv_integral_met += K_I_PACING_CV * (-prev_co_reserve_live) * _dt
                elif prev_co_reserve_live > CO_RESERVE_PACING_THRESHOLD:
                    cv_integral_met *= float(np.exp(-_dt / PACING_CV_INTEGRAL_RELEASE_MIN))
                cv_integral_met = min(cv_integral_met, PACING_CV_INTEGRAL_MAX_FRAC * met_initial)
            met_reduction     = (kp_ind * thermal_overshoot        # [rev14-A] individual K_p
                                  + kp_ind_cv * cv_overshoot
                                  + cv_integral_met)
            current_met       = max(1.5, met_initial - met_reduction)

        # [2026-10-19] Forced reduction at the cardiovascular ceiling (see
        # CV_CEILING_FORCED). Based on the state at the end of the previous
        # step, the same timing as the voluntary terms.
        met_forced_reduction = 0.0
        if (CV_CEILING_FORCED and i > 0 and cvr_model_live is not None
                and jos3_snapshot_prev is not None):
            _cap_now = cvr_model_live.met_at_ceiling(jos3_snapshot_prev)
            # Feed-forward on the trend: the ceiling keeps falling while the
            # body heats up, so a cap from the end of the previous step is
            # already too high by the end of this one. Anticipate the same
            # fall as in the last step (only when it is falling).
            _met_cap = _cap_now - (max(0.0, cv_cap_last - _cap_now) if CV_CEILING_ANTICIPATE and cv_cap_last is not None else 0.0)
            cv_cap_last = _cap_now
            if current_met > _met_cap:
                met_forced_reduction = current_met - max(1.5, _met_cap)
                current_met = max(1.5, _met_cap)

        # [2026-10-19] Length of this step. In distance mode the last step is
        # shortened to the whole minutes still needed to reach the distance.
        dt_i = float(time_steps_minutes[i])
        is_last_step = False
        if distance_mode and i > 0:
            _v_now = _speed_m_per_min(current_met)
            _remaining = race_target_m - race_dist_m
            _need = _remaining / _v_now if _v_now > 0 else float('inf')
            if _need <= dt_i + 1e-6:
                dt_i = float(min(dt_i, max(1, math.ceil(_need - 1e-6))))
                is_last_step = True
            race_dist_m = min(race_target_m, race_dist_m + _v_now * dt_i)
        if i > 0:
            race_elapsed_min += dt_i

        # [2026-10-19] After-glow on a MET drop (SLOWDOWN_AFTERGLOW): heat
        # added to the JOS-3 core compartments at the start of the step.
        afterglow_step_c = 0.0
        if (SLOWDOWN_AFTERGLOW and i > 0 and met_prev_used is not None
                and current_met < met_prev_used and _core_idx is not None):
            _drop = met_prev_used - current_met
            afterglow_step_c = PF_DELTA_T_NAGLOED * _drop / max(0.5, met_initial - PF_MET_RUST)
            jos3_model._t_body[_core_idx] += afterglow_step_c
            afterglow_total_c += afterglow_step_c
            afterglow_max_step_c = max(afterglow_max_step_c, afterglow_step_c)
        met_prev_used = current_met

        # JOS-3 step
        jos3_model.par = jos3_par(jos3_model, current_met)   # [2026-10-19] FOUNDATION REPAIR
        jos3_model.tdb = temps[i]
        jos3_model.tr  = mrts[i]
        jos3_model.rh  = rhs[i]
        # [2026-07] Combine ambient wind with the runner's own self-generated
        # relative airflow -- see compute_relative_wind() docstring. Running
        # speed is derived from the *current* (possibly pacing-reduced) MET
        # via the standard ACSM running-speed relationship (VO2 = 0.2*speed
        # + 3.5, speed in m/min), so a participant who slows down under
        # thermal/CV strain is also correctly modelled as generating less
        # self-wind -- not decoupled from pacing.
        v_running_ms = max(0.0, 17.5 * (current_met - 1.0) / 60.0)
        jos3_model.v   = compute_relative_wind(
            v_ambient=wind_1_5m[i],
            v_running=v_running_ms,
            angle_rad=participant_params.wind_angle_rad,
        )
        jos3_model.clo = clo_value
        if i > 0:
            jos3_model.simulate(times=int(round(dt_i)), dtime=60)

        t_rect = jos3_t_rect(jos3_model)  # [2026-10-19] pelvis core (was mean of 17 + 0.5)

        # [rev13-P5] AUC_thermisch: accumulate time-integrated T_rect exceedance.
        # Integration floor T_AUC_THRESHOLD = 39.0°C (module constant).
        # dt_min = 0 at i==0 (initialisation step, no elapsed time).
        if i > 0:
            dt_min         = dt_i
            auc_thermisch += max(0.0, t_rect - T_AUC_THRESHOLD)  * dt_min
            auc_klinisch  += max(0.0, t_rect - T_AUC_KLINISCH)   * dt_min  # [rev14-B]

        results_jos3 = jos3_model.dict_results()

        if 'weight_loss_by_evap_and_res' in results_jos3:
            # [fix 2026-10-09] Rate of THIS step only. dict_results() returns
            # the whole history (one entry per simulated minute); the mean
            # over all of it is the average rate since the start, which lags
            # a rising sweat rate. Verified (35 y, par 9, 25 C, 10-min
            # steps): accumulated loss was 26-28 % too low in the first hour
            # and 19 % after two hours. Now: mean over the minutes simulated
            # in this step (time_steps_minutes[i] entries).
            _wl = np.asarray(results_jos3['weight_loss_by_evap_and_res'], dtype=float).ravel()
            _n_stap = max(1, int(round(dt_i))) if i > 0 else 1
            water_loss_rate_g_per_s = float(np.mean(_wl[-_n_stap:])) if _wl.size else 0.0
        else:
            metabolic_heat_flux     = jos3_model.par * 58.2
            evap_fraction           = 0.6
            bsa                     = float(np.mean(jos3_model.bsa))
            water_loss_rate_g_per_s = (metabolic_heat_flux * bsa * evap_fraction) / 2418.0

        # [fix, 2026-08-09] Moved ahead of the CVR block below (was after
        # it). This is the model's own correctly-implemented ad-libitum
        # drinking simulation (thirst_threshold, random 120-180g intake
        # per drink) -- it needs to run BEFORE the CVR snapshot is built
        # for this timestep, not after, so the CVR module sees a
        # drinking-corrected value for THIS step rather than being fed a
        # separate, never-decremented accumulator (cvr_water_loss_kg) that
        # was silently assuming zero fluid intake for the entire event.
        # See the investigation note in HESTIA_CVR_Module_v2.py above
        # CVRModel for the full diagnosis: CO_demand stayed flat but
        # CO_max eroded steadily over a 2h test at a mild, CONSTANT 22degC
        # (no heat escalation at all) purely because the old
        # cvr_water_loss_kg kept climbing with no drinking ever applied,
        # while dehydration_pct's actual values were modest/realistic --
        # the bug was the missing rehydration, not the dehydration model.
        sweat_rate     = water_loss_rate_g_per_s * 60.0 * sweat_factor
        water_loss     = sweat_rate * dt_i if i > 0 else 0
        cumulative_water_loss += water_loss
        water_loss_pct = (cumulative_water_loss / 1000) / weight * 100
        is_thirsty     = water_loss_pct >= thirst_threshold

        # [2026-10-19, BUG FIX] Drinking. can_drink_again was meant as "one
        # drink per thirst episode" but only reset once the runner was no
        # longer thirsty -- and one 120-180 g drink never brings a sweating
        # runner back under the threshold, so after the first drink nobody
        # ever drank again. Measured (Amsterdam 2026-10-18, 20 runners): 1.2
        # drinks per runner, 0.04 L/h, net loss 4.2 % after the foundation
        # repair. Field data: recreational marathon finishers lose 2.3 % body
        # weight on average (Zouhal et al. 2011, Br J Sports Med 45:1101, 643
        # runners); elite marathoners drink 0.55 L/h, range 0.03-1.09 (Beis et
        # al. 2012, Clin J Sport Med 22:254). Now: a thirsty runner drinks
        # 120-180 g every step (up to ~0.9 L/h), so net loss hovers near the
        # personal thirst threshold (1.0-2.5 %), as in ad-libitum drinking.
        if is_thirsty and (can_drink_again or DRINK_EVERY_STEP_WHEN_THIRSTY):
            cumulative_water_loss = max(0, cumulative_water_loss - np.random.uniform(120, 180))
            can_drink_again       = False
        if not is_thirsty:
            can_drink_again = True

        if CVR_AVAILABLE and i > 0:
            # [fix, 2026-08-09] Was: cvr_water_loss_kg += ... (a pure,
            # never-decremented accumulator). Now: reuse
            # cumulative_water_loss, which already has drinking correctly
            # subtracted above, converted g -> kg to match this variable's
            # expected unit (see its other call site,
            # `dehydration_kg_finish = cvr_water_loss_kg`, which is
            # unchanged and now automatically gets the corrected value too).
            cvr_water_loss_kg = cumulative_water_loss / 1000.0
            met_cv = cv_met_lag(met_cv, current_met, dt_i)   # [2026-10-20] heart lags the load

            co_lh = float(np.array(results_jos3['cardiac_output']).flat[-1]) \
                if 'cardiac_output' in results_jos3 else 900.0

            if 'bf_skin' in results_jos3:
                bfsk_arr = np.array(results_jos3['bf_skin'])
                bf_skin_tot = float(bfsk_arr[-1].sum() if bfsk_arr.ndim == 2
                                    else bfsk_arr.sum())
            else:
                bf_skin_tot = co_lh * 0.25

            bf_ava_h = float(np.array(results_jos3['bf_ava_hand']).flat[-1]) \
                if 'bf_ava_hand' in results_jos3 else 0.5
            bf_ava_f = float(np.array(results_jos3['bf_ava_foot']).flat[-1]) \
                if 'bf_ava_foot' in results_jos3 else 0.5
            t_cb_val = float(np.array(results_jos3['t_cb']).flat[-1]) \
                if 't_cb' in results_jos3 else jos3_core_for_chsi(jos3_model)

            jos3_snapshot_this_step = JOS3Outputs(
                t_min          = i,
                cardiac_output = co_lh,
                t_core_mean    = jos3_core_for_chsi(jos3_model),   # [2026-10-19] pelvis core
                t_cb           = t_cb_val,
                weight_loss_g_s= cvr_water_loss_kg,
                bf_skin_total  = bf_skin_tot,
                bf_ava_hand    = bf_ava_h,
                bf_ava_foot    = bf_ava_f,
                current_met    = met_cv,       # [2026-10-20] lagged MET (CV_LAG_ENABLED); [2026-07] enables workload-
                                               # based CO/HR via Lloyd 2022
                                               # Eq. 12-31 instead of reading
                                               # JOS-3's own cardiac_output
                t_skin_mean    = jos3_model.t_skin.mean(),  # [2026-07] for
                                               # the Cardiac Heat Strain Index
                                               # (mean body temperature term)
            )
            jos3_cvr_series.append(jos3_snapshot_this_step)
            # [fix] Live CO_reserve for the cardiovascular pacing term next
            # iteration -- reuses the SAME snapshot and the SAME
            # CVRModel.compute_step() method as the final post-loop batch
            # pass, so this cannot drift from the officially reported
            # CO_reserve (same precision, just also evaluated in-step).
            _cvr_live_state = cvr_model_live.compute_step(jos3_snapshot_this_step)
            prev_co_reserve_live = _cvr_live_state.CO_reserve
            hr_live = float(_cvr_live_state.HR)   # [2026-10-19] for RPE_FROM_CVR_HR
            jos3_snapshot_prev = jos3_snapshot_this_step

        if utcis_pre[i] is not None:
            utci_val = utcis_pre[i]
        else:
            utci_val = utci(tdb=temps[i], tr=mrts[i], v=wind_10m[i], rh=rhs[i]).utci
        if wbgts_pre[i] is not None:
            wbgt_val = wbgts_pre[i]
        else:
            with_solar = bool(ghi[i] > 0 and solar_elevations[i] > 0)
            wbgt_args = {"twb": twbs[i],
                         "tg": globe_temps[i],
                         "with_solar_load": with_solar,
                         "round_output": True}
            if with_solar:
                wbgt_args["tdb"] = temps[i]
            wbgt_val = float(wbgt(**wbgt_args).wbgt)

        # [2026-07] pct_vo2max as sampled represents the fraction of VO2max
        # at the TARGET event pace (met_value) -- if dynamic pacing (K_p)
        # has reduced current_met below that target, the runner's current
        # relative intensity is correspondingly lower, and RPE should
        # reflect that real-time change, not the static target value.
        current_pct_vo2max = pct_vo2max * (current_met / met_value) if met_value > 0 else pct_vo2max

        if RPE_FROM_CVR_HR and cvr_model_live is not None and hr_live is not None:
            # [2026-10-19] RPE from this step's CVR heart rate (author's decision).
            rpe_physical, rpe_total = calculate_adult_rpe_from_hr(
                hr=hr_live, hr_rest=cvr_model_live.HR_rest, hr_max=cvr_model_live.HR_max,
                training_factor=training_factor, mf_score=mf_score)
        else:
            rpe_physical, rpe_total = calculate_adult_rpe_improved(
                current_met=current_met,
                t_rect=t_rect,
                training_factor=training_factor,
                acclimatization_factor=acclimatization_factor,
                mf_score=mf_score,
                pct_vo2max=current_pct_vo2max,
                runner_age=runner_age,
            )

        # [2026-10-19] Stop decision. With RPE from the CVR heart rate the
        # perceived effort (rpe_physical) is compared with a personal limit
        # set by motivation (rpe_stop_threshold): a low-motivation runner
        # quits near maximal effort, a highly motivated runner keeps going
        # and is slowed by the cardiovascular ceiling instead. Legacy path:
        # rpe_total >= 19.5 as before.
        if RPE_FROM_CVR_HR and hr_live is not None:
            if rpe_physical >= rpe_stop_threshold(mf_score):
                runner_stopped = True
        elif rpe_total >= 19.5:
            runner_stopped = True

        first_aid_visit = (t_rect >= 40.5) or (water_loss_pct >= 2.0) or (rpe_total >= 17)

        _t_stamp = (times[i - 1] + pd.Timedelta(minutes=dt_i)) if (i > 0 and is_last_step) else times[i]
        results.append({
            "time":           _t_stamp.strftime('%Y-%m-%d %H:%M'),
            "utci":           utci_val,
            "wbgt":           wbgt_val,
            "t_rect":         t_rect,
            "water":          cumulative_water_loss,
            "mrt":            mrts[i],
            "t_air":          temps[i],
            "rpe_physical":   rpe_physical,
            "rpe_total":      rpe_total,
            "stopped":        runner_stopped,
            "first_aid_visit":     first_aid_visit,
            "is_unliveable":  is_unliveable,
            "current_met":    current_met,        # [rev13-P4] dynamic MET
            "met_forced_reduction": met_forced_reduction,  # [2026-10-19] MET cut by the CV ceiling
            "afterglow_c":    afterglow_step_c,   # [2026-10-19] after-glow added on slowing (degC)
            "distance_km":    (race_dist_m / 1000.0) if distance_mode else float('nan'),
            "dt_min":         dt_i,               # [2026-10-19] length of this step (last step can be shorter)
            "auc_thermisch":  auc_thermisch,      # [rev13-P5] °C·min above 39.0°C
            "auc_klinisch":   auc_klinisch,       # [rev14-B] °C·min above 40.5°C
            "kp_ind":         kp_ind,             # [rev14-A] individual pacing gain
            # CVR fields (filled post-loop)
            "hr_geschat":     float('nan'),
            "cvs_index":      float('nan'),
            "co_reserve":     float('nan'),
            "decompensating":  False,
        })
        if runner_stopped and stop_min is None:
            stop_min = race_elapsed_min
        if is_last_step:
            race_finished = True
            break

    # [2026-10-19] Race-length bookkeeping (RACE_DISTANCE_MODE / RPE_STOP_ENDS_RACE).
    if len(results) > 0:
        results[-1].update({
            'race_planned_min':   race_planned_min,
            'race_actual_min':    race_elapsed_min,
            'race_extension_min': (race_elapsed_min - race_planned_min) if (distance_mode and race_finished) else float('nan'),
            'race_distance_km':   (race_dist_m / 1000.0) if distance_mode else float('nan'),
            'race_finished':      bool(race_finished) if distance_mode else (not runner_stopped),
            'dnf_cutoff':         bool(distance_mode and not race_finished and not runner_stopped),
            'stop_min':           stop_min,
            'afterglow_total_c':  afterglow_total_c,
            'afterglow_max_step_c': afterglow_max_step_c,
        })

    if CVR_AVAILABLE and len(jos3_cvr_series) > 0:
        cvr_ts = link_cvr_to_jos3(cvr_runner, jos3_cvr_series)
        for j, cvr_state in enumerate(cvr_ts.states):
            idx = j + 1
            if idx < len(results):
                results[idx]['hr_geschat']    = cvr_state.HR
                results[idx]['cvs_index']     = cvr_state.CVS_index
                results[idx]['co_reserve']    = cvr_state.CO_reserve
                results[idx]['decompensating'] = cvr_state.decompensating

    # [2026-09-29, op verzoek van de auteur] 'Punt-van-geen-terugkeer': het eerste
    # tijdstip waarop T_rect>40.5 EN CO_reserve<=0 werkelijk GELIJKTIJDIG
    # gelden -- berekend hier, NA de koppeling hierboven, zodat dezelfde
    # co_reserve-waarden worden gebruikt als overal elders in de rapportage
    # (klinisch/EHE-momentopname, Roberts). Toetst of de conjunctie, eenmaal
    # bereikt, later in dezelfde race ooit weer NIET geldt (herstel) of niet.
    conjunctie_ooit_bereikt  = False
    conjunctie_eerste_min    = None
    conjunctie_ooit_hersteld = False
    _elapsed_min = 0.0
    for _idx in range(1, len(results)):
        _elapsed_min += time_steps_minutes[_idx - 1] if _idx - 1 < len(time_steps_minutes) else 0.0
        _co = results[_idx].get('co_reserve', float('nan'))
        if np.isnan(_co):
            continue
        _conj_nu = (results[_idx]['t_rect'] > T_AUC_KLINISCH) and (_co <= CO_RESERVE_CEILING_TOL)
        if _conj_nu and not conjunctie_ooit_bereikt:
            conjunctie_ooit_bereikt = True
            conjunctie_eerste_min   = round(_elapsed_min, 1)
        elif conjunctie_ooit_bereikt and not _conj_nu:
            conjunctie_ooit_hersteld = True
    if len(results) > 0:
        results[-1]['conjunctie_ooit_bereikt']  = conjunctie_ooit_bereikt
        results[-1]['conjunctie_eerste_min']    = conjunctie_eerste_min
        results[-1]['conjunctie_ooit_hersteld'] = conjunctie_ooit_hersteld

    # [rev14-C] POST-FINISH MODULE
    # Propagate T_rect and CO_reserve for PF_DUUR_MIN minutes after finish.
    # Uses final simulation state as starting point.
    t_rect_finish    = results[-1]['t_rect']
    co_reserve_finish = results[-1].get('co_reserve', 2.0)
    if np.isnan(co_reserve_finish):
        # [app fix, documented] The CVR-linked series (jos3_cvr_series) can
        # end before the full race duration -- observed directly: a 100-min
        # simulation with co_reserve populated for steps 1-4 only, NaN for
        # steps 5-9, with t_rect frozen at its step-4 value for the
        # remainder (the signature of the per-step loop halting rather than
        # genuinely converging). The ORIGINAL fallback here was a hardcoded
        # 2.0 ("healthy") regardless of what happened during the race --
        # which, for a participant whose last VALID co_reserve was already
        # negative (observed: -0.2), silently overwrites a collapse state
        # with an assumed-healthy one before propagating into
        # simulate_post_finish(). Any 'percent of participants reaching
        # zero/negative capacity during or after the race' statistic
        # computed from co_reserve_postfinish would then systematically
        # undercount exactly the participants most at risk.
        #
        # Fix: fall back to the last VALID (non-NaN) co_reserve observed
        # during the race, not a constant. This carries forward whatever
        # state the participant was actually last known to be in --
        # including a negative one -- rather than assuming health. If no
        # valid value exists at all (CVR never linked for this draw), the
        # constant 2.0 remains the final fallback, unchanged from before.
        valid_prior = [r.get('co_reserve') for r in results[:-1]
                       if r.get('co_reserve') is not None and not np.isnan(r.get('co_reserve'))]
        co_reserve_finish = valid_prior[-1] if valid_prior else 2.0
    wbgt_finish       = results[-1]['wbgt']
    auc_klinisch_race = results[-1]['auc_klinisch']
    # [2026-07] CO_max at finish, for the absolute-magnitude pooling formula
    co_max_finish = (cvr_ts.states[-1].CO_max
                      if CVR_AVAILABLE and len(jos3_cvr_series) > 0 and cvr_ts.states
                      else None)

    if PF_JOS3 and CVR_AVAILABLE and len(jos3_cvr_series) > 0:
        # [2026-10-20] Finish zone with the runner's own JOS-3 model.
        _i_end = min(i, len(times) - 1)
        _steps = []
        for _m in range(int(PF_JOS3_DUUR_MIN) + 1):
            _j = min(len(times) - 1, _i_end + int(_m // max(1.0, _dt_nom)))
            _steps.append((temps[_j], mrts[_j], rhs[_j], wind_1_5m[_j]))
        pf = simulate_post_finish_jos3(
            jos3_model, cvr_model_live, _steps,
            t_rect_finish=t_rect_finish, co_reserve_finish=co_reserve_finish,
            auc_klinisch_race=auc_klinisch_race, met_finish=current_met,
            met_initial=met_initial, met_cv_finish=met_cv,
            cumulative_water_loss_g=cumulative_water_loss, weight_kg=weight,
            sweat_factor=sweat_factor, thirst_threshold=thirst_threshold,
            clo_value=clo_value, walked=not runner_stopped)
    else:
      pf = simulate_post_finish(
        t_rect_finish     = t_rect_finish,
        co_reserve_finish = co_reserve_finish,
        auc_klinisch_race = auc_klinisch_race,
        wbgt_finish       = wbgt_finish,
        co_max_finish     = co_max_finish,
        cvr_model         = cvr_model_live if CVR_AVAILABLE else None,
        t_skin_finish     = (jos3_model.t_skin.mean()
                              if CVR_AVAILABLE and len(jos3_cvr_series) > 0
                              else None),
        dehydration_kg_finish = cvr_water_loss_kg if CVR_AVAILABLE else 0.0,
        met_cv_finish     = met_cv if CVR_AVAILABLE else None,   # [2026-10-20]
    )
    # Attach post-finish results to last entry for easy extraction
    results[-1].update({
        't_rect_piek_postfinish'  : pf['t_rect_piek_postfinish'],
        'co_reserve_postfinish'   : pf['co_reserve_postfinish'],
        'auc_klinisch_postfinish' : pf['auc_klinisch_postfinish'],
        'auc_klinisch_totaal'     : pf['auc_klinisch_totaal'],
        'ehs_postfinish'          : pf['ehs_postfinish'],
        't_ehs_postfinish_min'    : pf['t_ehs_postfinish_min'],
        't_rect_series_postfinish'    : pf['t_rect_series_postfinish'],
        'co_reserve_series_postfinish': pf['co_reserve_series_postfinish'],
        'time_min_series_postfinish'  : pf['time_min_series_postfinish'],
        # [bug fix -- suite integration] these three were computed by
        # simulate_post_finish() but never propagated here, so
        # analyse_participant()'s `last.get('control_failure_dose_postfinish',
        # 0.0)` always fell back to 0.0 -- silently zeroing out the
        # post-finish contribution to the TCF dose for every participant,
        # in both individual and Monte Carlo runs, in every report produced
        # with this model so far.
        'control_failure_dose_postfinish'     : pf['control_failure_dose_postfinish'],
        # [2026-10-20] EAC-staan (0 on the legacy post-finish path)
        'eac_staanbelasting'  : pf.get('eac_staanbelasting', 0.0),
        'eac_tolerantie_min'  : pf.get('eac_tolerantie_min', 1.0),
        'eac_kans'            : pf.get('eac_kans', 0.0),
        'control_failure_time_postfinish_min' : pf['control_failure_time_postfinish_min'],
        't_control_failure_postfinish_min'    : pf['t_control_failure_postfinish_min'],
    })

    return results


# =============================================================================
#  PEDIATRIC SIMULATION WORKER (unchanged from rev09)
# =============================================================================

def run_pediatric_simulation(interp_data, lat, lon, met_value, clo_value,
                              participant_params, age_group="11-20", fitness_factor=0.5):
    """Single pediatric participant simulation. Unchanged from rev09."""
    height, weight, temp_var, rh_var, met_var, mf_score, sweat_factor, thirst_threshold = participant_params

    if age_group == "0-10":
        age            = 7
        fat_percentage = 18
        gender         = 'male'
    else:
        age            = 15
        gender         = np.random.choice(["male", "female"])
        fat_percentage = 22 if gender == 'female' else 15

    times      = [entry["time"] for entry in interp_data]
    temps      = [entry["temp"] + temp_var for entry in interp_data]
    wind_10m   = [entry["wind"] for entry in interp_data]
    wind_1_5m  = [wind_speed_at_height(w, 10, 1.0) for w in wind_10m]
    rhs        = [np.clip(entry["rh"] + rh_var, 10, 95) for entry in interp_data]
    clouds     = [entry["clouds"] for entry in interp_data]
    pressures  = [entry["pressure"] for entry in interp_data]

    aqi             = get_air_quality(lat, lon)
    # [fix] Same precomputed-values-preferred approach as the adult path
    # above -- see that comment for the full rationale and verification.
    # [2026-10-24] Measured/forecast radiation preferred, see radiation_series().
    ghi, solar_elevations, globe_temps, mrts, _rad_bron = radiation_series(
        interp_data, times, temps, wind_1_5m, pressures, clouds, lat, lon, aqi, rhs=rhs)

    if interp_data[0].get('twb_precomputed') is not None:
        twbs = [entry['twb_precomputed'] for entry in interp_data]
    else:
        twbs = [wet_bulb_tmp(tdb=t, rh=r) for t, r in zip(temps, rhs)]
    wbgts_pre = [entry.get('wbgt_precomputed') for entry in interp_data]
    utcis_pre = [entry.get('utci_precomputed') for entry in interp_data]
    jos3_leeftijd.reset_person()   # [2026-10-23] children: no age decrement anyway; no stale factor
    jos3_model = maak_jos3(height=height, weight=weight, age=age,
                       fat=fat_percentage, sex=gender)
    jos3_model.t_core[:] = 37.0
    time_steps_minutes = [(times[i+1] - times[i]).total_seconds() / 60.0
                           for i in range(len(times) - 1)]
    time_steps_minutes.insert(0, 0)

    results               = []
    cumulative_water_loss = 0
    participant_stopped   = False
    can_drink_again       = True
    current_met           = met_value + met_var

    for i in range(len(times)):
        if participant_stopped and i > 0:
            results.append({**results[-1],
                            'time': times[i].strftime('%Y-%m-%d %H:%M'),
                            'stopped': True})
            continue

        jos3_model.par = current_met
        jos3_model.tdb = temps[i]
        jos3_model.tr  = mrts[i]
        jos3_model.rh  = rhs[i]
        # [2026-07] NOT extended here: the adult path's compute_relative_wind()
        # fix (self-generated wind + individual angle sampling, see that
        # function's docstring) was not carried over to the child path -- the
        # child profile has no sampled wind_angle_rad and this investigation
        # was scoped to adult road-race scenarios (Falmouth, DtD). Flagged so
        # this doesn't look like an oversight if the child path is revisited.
        jos3_model.v   = max(0.1, wind_1_5m[i])
        jos3_model.clo = clo_value
        if i > 0:
            jos3_model.simulate(times=int(round(time_steps_minutes[i])), dtime=60)
        t_core_avg = jos3_model.t_core.mean()

        sweat_rate_ml = sweat_factor * (jos3_model.par * 58.2 * float(np.mean(jos3_model.bsa))) / 2418 * 1000 / 60
        water_loss    = sweat_rate_ml * time_steps_minutes[i] if i > 0 else 0
        cumulative_water_loss += water_loss
        water_loss_pct = (cumulative_water_loss / 1000) / weight * 100
        is_thirsty     = water_loss_pct >= thirst_threshold

        if is_thirsty and can_drink_again:
            cumulative_water_loss = max(0, cumulative_water_loss - np.random.uniform(100, 150))
            can_drink_again       = False
        if not is_thirsty:
            can_drink_again = True

        if utcis_pre[i] is not None:
            utci_val = utcis_pre[i]
        else:
            utci_val = utci(tdb=temps[i], tr=mrts[i], v=wind_10m[i], rh=rhs[i]).utci
        if wbgts_pre[i] is not None:
            wbgt_val = wbgts_pre[i]
        else:
            with_solar = bool(ghi[i] > 0 and solar_elevations[i] > 0)
            wbgt_args  = {"twb": twbs[i],
                          "tg": globe_temps[i],
                          "with_solar_load": with_solar,
                          "round_output": True}
            if with_solar:
                wbgt_args["tdb"] = temps[i]
            wbgt_val = float(wbgt(**wbgt_args).wbgt)

        rpe_physical, rpe_total = calculate_pediatric_rpe_improved(
            current_met=current_met, t_core=t_core_avg,
            fitness_factor=fitness_factor, mf_score=mf_score, age_group=age_group)

        if rpe_total >= 9.5:
            participant_stopped = True

        first_aid = (t_core_avg >= 38.8) or (water_loss_pct >= 3.0) or (rpe_total >= 8.5)

        results.append({
            "time": times[i].strftime('%Y-%m-%d %H:%M'), "utci": utci_val, "wbgt": wbgt_val,
            "t_core": t_core_avg, "water_loss_ml": cumulative_water_loss, "mrt": mrts[i],
            "t_air": temps[i],
            "rpe_physical": rpe_physical, "rpe_total": rpe_total,
            "stopped": participant_stopped, "first_aid_visit": first_aid,
        })
    return results


# =============================================================================
#  PARALLEL WORKER WRAPPERS (unchanged)
# =============================================================================

def worker_monte_carlo_adult(args):
    """Worker for a single adult Monte Carlo simulation in parallel."""
    import sys, os
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    if _script_dir not in sys.path:
        sys.path.insert(0, _script_dir)
    interp_data, lat, lon, met_value, clo_value, params, training, acclimatization = args
    # [2026-10-15] Reproducibility fix. The only random draw inside a
    # participant's simulation is the drink size (np.random.uniform(120,
    # 180) g). In a Pool, each worker inherits the parent's RNG state and
    # draws in whatever order the scheduler hands it participants, so the
    # same seed gave slightly different results run to run (measured:
    # ehs intercept -8.8081 vs -8.8091 for two identical seed-42
    # calibrations). Seeding per participant from the participant's own
    # (already seeded) profile makes each simulation independent of
    # scheduling and of serial vs. parallel execution.
    _key = (round(float(params.height), 6), round(float(params.weight), 6), int(params.age),
            round(float(params.vo2max), 6), round(float(params.pct_vo2max), 6),
            round(float(getattr(params, 'wind_angle_rad', 0.0)), 9))
    import zlib
    np.random.seed(zlib.crc32(repr(_key).encode()) & 0xFFFFFFFF)
    return calculate_indices_jos3_adult(
        interp_data, lat, lon, met_value, clo_value, params, training, acclimatization
    )


def worker_monte_carlo_pediatric(args):
    """Worker for a single pediatric Monte Carlo simulation in parallel."""
    interp_data, lat, lon, met_value, clo_value, params, age_group, fitness_factor = args
    return run_pediatric_simulation(
        interp_data, lat, lon, met_value, clo_value, params, age_group, fitness_factor
    )


# =============================================================================
#  MONTE CARLO MANAGERS
# =============================================================================

def _calculate_threshold_stats(temp_sims, n_simulations):
    """Calculates mean % exceeding each T_rect threshold with 95% CI (Wald).

    [2026-09] Fixed a real, silent bug exposed by sample_pace=True (ragged
    per-person durations, NaN-padded to a common length -- see
    run_monte_carlo_adult()): this used to divide by the fixed n_simulations
    at every timestep. temp_sims > t evaluates NaN as False (not NaN), so a
    participant who already finished was silently counted as "not exceeding
    the threshold" rather than excluded -- the reported percentage quietly
    drifted downward at later timesteps as more (typically faster, often
    less-strained) participants finished and diluted the denominator, even
    though the people still actually running hadn't changed. Now divides by
    the number of participants still active (non-NaN) at each timestep
    instead of the fixed population size.
    """
    thresholds = [38.0, 38.5, 39.0, 39.5, 40.0, 40.5, 41.0]
    stats = {}
    active_n = np.sum(~np.isnan(temp_sims), axis=0)
    active_n_safe = np.maximum(active_n, 1)  # avoid div-by-zero once everyone has finished
    for t in thresholds:
        exceed_count = np.sum(temp_sims > t, axis=0)  # NaN > t is False, never miscounted as exceeding
        p          = exceed_count / active_n_safe
        se         = np.sqrt(p * (1 - p) / active_n_safe)
        ci_margin  = 1.96 * se
        stats[f"{t:.1f}"] = {
            'mean':     p * 100,
            'ci_lower': np.maximum(0, p - ci_margin) * 100,
            'ci_upper': np.minimum(1, p + ci_margin) * 100,
            'n_active': active_n,  # [2026-09] exposed so callers/plots can show shrinking N
        }
    return stats


# =============================================================================
#  [rev15] CALIBRATION UNCERTAINTY FUNCTIONS
# =============================================================================

def _intercept_sensitivity(z_zonder_intercept: np.ndarray,
                            intercept_nominal: float,
                            delta: float = 0.5) -> dict:
    """
    Computes key population percentages at intercept_nominal ± delta.

    The delta of 0.5 log-odds units is a conservative estimate of the
    calibration transfer uncertainty from Boston Marathon (Breslow 2021)
    to DtD conditions.  It covers:
      - Between-event EHS rate variation (~2-fold in the literature).
      - JOS-3 systematic T_rect offset vs. field measurements (~0.3°C).
      - training_offset coefficient uncertainty (±0.05, pending clinical calibration).

    Parameters
    ----------
    z_zonder_intercept : np.ndarray, shape (n_sim,)
        Logistic Z-score per participant WITHOUT intercept term.
    intercept_nominal : float
        The calibrated intercept for the active endpoint.
    delta : float
        Half-width of the intercept uncertainty band (default 0.5).

    Returns
    -------
    dict with keys:
        'p_collapse_mean_lo'  : float  -- mean collapse probability (%), lower bound
        'p_collapse_mean_hi'  : float  -- mean collapse probability (%), upper bound
        'pct_hoog_risico_lo'  : float  -- % individuals p_collapse > 50%, lower bound
        'pct_hoog_risico_hi'  : float  -- % individuals p_collapse > 50%, upper bound
    """
    results = {}
    for suffix, intercept in (('lo', intercept_nominal - delta),
                               ('hi', intercept_nominal + delta)):
        z       = intercept + z_zonder_intercept
        p_ind   = 1.0 / (1.0 + np.exp(-z))
        results[f'p_collapse_mean_{suffix}']  = float(np.nanmean(p_ind)) * 100
        results[f'pct_hoog_risico_{suffix}']  = float(np.nanmean(p_ind > 0.50)) * 100
    return results


def _pct_sensitivity_from_flag(flag_array: np.ndarray,
                                z_zonder_intercept: np.ndarray,
                                intercept_nominal: float,
                                delta: float = 0.5) -> tuple:
    """
    Estimates the calibration sensitivity band for a binary population
    fraction (e.g. pct_decompensation, pct_roberts_kritiek) that depends
    indirectly on the same Z-logistic threshold.

    Because pct_decompensation and pct_roberts_kritiek are derived from
    physiological thresholds (CO_reserve, AUC_klinisch) that are NOT
    directly controlled by intercept_kal, the intercept sensitivity does
    NOT apply to them.  Their dominant uncertainty is instead the ±0.3°C
    JOS-3 T_rect systematic offset.

    For those metrics we use a different approach: we shift the effective
    T_rect threshold by ±0.3°C and recompute the fraction.  However,
    this requires the raw arrays, which are not all available here.

    As a pragmatic approximation this function propagates the RELATIVE
    sensitivity of the logistic collapse probability to bound the
    physiological fraction:

        relative_sensitivity = (p_hi - p_lo) / p_nominal

    and applies it symmetrically to the flag-based fraction:

        lo = flag_fraction * (1 - relative_sensitivity / 2)
        hi = flag_fraction * (1 + relative_sensitivity / 2)
        (both clipped to [0, 100])

    This is explicitly an approximation.  The band is labelled '~' in
    output to signal model-based rather than statistical uncertainty.

    Parameters
    ----------
    flag_array : np.ndarray, shape (n_sim,)  -- boolean or 0/1
    z_zonder_intercept : np.ndarray, shape (n_sim,)
    intercept_nominal : float
    delta : float

    Returns
    -------
    (lo, hi) : tuple of float  -- lower and upper band values in %
    """
    flag_pct = float(np.mean(flag_array)) * 100
    if flag_pct == 0.0:
        return 0.0, 0.0

    # Relative sensitivity via logistic band
    z_nom = intercept_nominal + z_zonder_intercept
    p_nom = float(np.nanmean(1.0 / (1.0 + np.exp(-z_nom)))) * 100
    if p_nom == 0.0:
        return flag_pct, flag_pct

    s_lo = _intercept_sensitivity(z_zonder_intercept, intercept_nominal, delta)
    s_hi = s_lo  # same call returns both
    rel  = abs(s_lo['p_collapse_mean_hi'] - s_lo['p_collapse_mean_lo']) / (2.0 * p_nom)

    lo = max(0.0,   flag_pct * (1.0 - rel))
    hi = min(100.0, flag_pct * (1.0 + rel))
    return lo, hi


def _format_pct_with_band(value: float, lo: float, hi: float,
                           decimals: int = 1) -> str:
    """
    Formats a percentage with its calibration uncertainty band.

    Output: "X.X% (~Y.Y–Z.Z%)"

    The tilde signals that the band reflects model calibration uncertainty
    (intercept ± 0.5 log-odds), NOT a classical 95% confidence interval.
    For GHOR reporting this distinction is important: the band should be
    read as "plausible range given calibration source uncertainty".

    Parameters
    ----------
    value    : point estimate (%)
    lo, hi   : lower and upper band (%)
    decimals : decimal places (default 1)

    Returns
    -------
    str, e.g. "7.8% (~5.2–11.4%)"
    """
    fmt = f".{decimals}f"
    return f"{value:{fmt}}% (~{lo:{fmt}}–{hi:{fmt}}%)"


def get_age_group(age):
    """Categorises age into a predefined group string."""
    if 18 <= age <= 29:  return "18-29"
    if 30 <= age <= 39:  return "30-39"
    if 40 <= age <= 49:  return "40-49"
    if 50 <= age <= 59:  return "50-59"
    return "60-65"


# [2026-10-25] Reproducible default for the user-facing entry points
# (console, run_hestia). Pass random_seed=None explicitly for a fresh draw.
DEFAULT_RANDOM_SEED = 42


def run_monte_carlo_adult(interp_data, lat, lon, met_value, clo_value,
                           n_simulations, age_configuration,
                           training_factor, acclimatization_factor,
                           use_parallel=True,
                           base_population=None,
                           random_seed=None,
                           run_control_failure=False,
                           sample_pace=False,
                           event_dist_km=16.1):
    """
    Manages the entire adult Monte Carlo simulation process.

    [rev10] New parameter: base_population (optional)
    --------------------------------------------------
    If base_population is provided (list of AdultParticipantProfile from
    generate_base_population()), it is used directly without re-sampling.
    This enables reproducible scenario comparisons: the SAME population
    experiences different meteorological conditions or MET values.

    If base_population is None, a fresh population is generated with
    generate_base_population() using the given random_seed.

    The age_configuration parameter is IGNORED when base_population is
    provided (age is already embedded in each profile from rev10 onward).
    A deprecation note is printed if age_configuration != 'standard' and
    a base_population is supplied.

    Parameters
    ----------
    interp_data : list of dicts
    lat, lon : float
    met_value : float
        Base MET of the activity (used for liveability check and reference).
    clo_value : float
    n_simulations : int
        Target number of participants. Ignored if base_population is provided.
    age_configuration : str or tuple
        "standard" or (min_age, max_age). Ignored if base_population provided.
    training_factor : float
    acclimatization_factor : float
    use_parallel : bool
    base_population : list of AdultParticipantProfile or None [rev10]
    random_seed : int or None [rev10]
    sample_pace : bool
        [2026-09] When True (and base_population is None, so a fresh
        population is generated here), each participant gets their own
        pace/MET/duration_hours instead of the shared met_value/interp_data
        window -- see generate_base_population()'s sample_pace docstring.
        interp_data must then cover AT LEAST the slowest sampled
        participant's duration; the caller (run_hestia.py's
        monte_carlo_adult()) widens the requested window accordingly before
        calling this function. Each participant's own worker_args slices
        interp_data down to their own duration and uses their own MET, so
        a fast participant does not simply share a longer, slower
        participant's exposure window truncated early -- they get their
        own window from the same start time.
    event_dist_km : float
        Passed through to generate_base_population() when sample_pace=True.

    Returns
    -------
    tuple : (all_results, stats, results_df)
    """
    # ------------------------------------------------------------------
    # [rev10] Population source selection
    # ------------------------------------------------------------------
    if base_population is not None:
        # Use the provided fixed population
        simulations_params_base = base_population
        if age_configuration != "standard":
            print(f"{Fore.YELLOW}[rev10] age_configuration is ignored when "
                  f"base_population is provided.{Style.RESET_ALL}")
        print(f"{Fore.CYAN}[rev10] Using provided fixed population "
              f"({len(simulations_params_base)} profiles).{Style.RESET_ALL}")
    else:
        # Generate a fresh population (backward-compatible path)
        simulations_params_base = generate_base_population(
            n_simulations      = n_simulations,
            training_factor    = training_factor,
            acclimatization_factor = acclimatization_factor,
            random_seed        = random_seed,
            met_value          = met_value,
            sample_pace        = sample_pace,
            event_dist_km      = event_dist_km,
        )

    n_simulations = len(simulations_params_base)
    if n_simulations == 0:
        print(f"{Fore.RED}Failed to generate any valid participant profiles. Aborting.{Style.RESET_ALL}")
        return None, None, None

    # ------------------------------------------------------------------
    # [rev10] Note on age_configuration when NOT using base_population
    # ------------------------------------------------------------------
    # In rev10, age is assigned during generate_base_population(), so the
    # age_configuration option below is a no-op for the fixed-population path.
    # For the fresh-population path, age is already embedded in each profile.
    # The block below is retained for backward compatibility only and has no
    # effect on the profile.age field (which was set during generation).

    participant_demographics = []
    worker_args = []

    # [2026-09] Precompute the interval between interp_data entries from its
    # own timestamps (robust to whatever interval_minutes the caller used to
    # build it, rather than assuming a hardcoded 10) -- only needed when
    # sample_pace requires per-person slicing below.
    if sample_pace and len(interp_data) >= 2:
        _step_minutes = (interp_data[1]["time"] - interp_data[0]["time"]).total_seconds() / 60.0
    else:
        _step_minutes = None

    for params in simulations_params_base:
        # Age is already embedded in the profile from generate_base_population().
        # The age_configuration override from rev09 is removed here.
        # [rev10] If using a fresh population with age_configuration != 'standard',
        # a warning is shown but the profile age is NOT overridden.
        gender = params.gender
        if sample_pace and _step_minutes and params.duration_hours > 0:
            # [2026-09] This is the actual fix: each participant now gets
            # their OWN slice of interp_data (their own exposure duration,
            # not everyone truncated to the same shared window) and their
            # OWN MET (derived from their own sampled pace), instead of the
            # single shared met_value/interp_data used for every participant
            # regardless of how fast or slow they are. Without this, pace
            # variation from generate_base_population(sample_pace=True) only
            # changed perceived relative effort (pct_vo2max), not actual
            # exposure time -- see this session's discussion of exactly that
            # gap.
            n_steps = max(2, int(round(params.duration_hours * 60.0 / _step_minutes)) + 1)
            # [2026-10-19] RACE_DISTANCE_MODE: the engine ends the race when
            # the distance is covered, so it gets the whole window (up to the
            # course limit) and can run longer than planned if it slows down.
            person_interp = interp_data if RACE_DISTANCE_MODE else interp_data[:n_steps]
            person_met = _acsm_met_from_pace(params.pace_min_per_km)
            worker_args.append((person_interp, lat, lon, person_met, clo_value, params,
                                training_factor, acclimatization_factor))
        else:
            worker_args.append((interp_data, lat, lon, met_value, clo_value, params,
                                training_factor, acclimatization_factor))
        participant_demographics.append({
            'age':       params.age,
            'age_group': get_age_group(params.age),
            'gender':    gender,
        })

    # Parallel execution
    if use_parallel:
        with Pool(multiprocessing.cpu_count()) as pool:
            all_results = list(tqdm(
                pool.imap(worker_monte_carlo_adult, worker_args),
                total=len(worker_args),
                desc="Monte Carlo Adult Sims", unit="sim",
            ))
    else:
        all_results = [worker_monte_carlo_adult(args)
                       for args in tqdm(worker_args, desc="Monte Carlo Adult Sims")]

    # [2026-09] With sample_pace=True, each person's `res` list is only as
    # long as THEIR OWN duration_hours -- shorter than others who ran
    # longer. The np.array(...) calls below need every row the same length
    # (a rectangular array), so a PADDED COPY is built for that purpose
    # only -- `all_results` itself stays unpadded, because the res[-1]...
    # "final value" extractions further below (auc_per_sim, kp_per_sim,
    # etc.) must read each person's own real last entry, not a NaN filler
    # row. (First version of this fix padded all_results in place and broke
    # exactly those final-value reads -- caught by testing before this
    # shipped, not by inspection.) NaN, not zero-padding or repeating the
    # last value, for the padding itself, so downstream aggregation must
    # use nan-aware functions (nanmean, nanpercentile, etc.) to correctly
    # treat "already finished" as no data rather than as a real zero or a
    # frozen final reading -- ordinary mean/percentile calls elsewhere in
    # this function or in the plotting code have NOT all been individually
    # re-audited for this; treat any existing non-nan-aware aggregation
    # over these six arrays as suspect until checked.
    max_len = max((len(res) for res in all_results), default=0)
    if any(len(res) != max_len for res in all_results):
        _nan_step = {"t_rect": np.nan, "water": np.nan, "rpe_total": np.nan,
                    "stopped": np.nan, "first_aid_visit": np.nan,
                    "is_unliveable": np.nan, "current_met": np.nan}
        all_results_padded = [
            res + [_nan_step] * (max_len - len(res)) if len(res) < max_len else res
            for res in all_results
        ]
    else:
        all_results_padded = all_results

    # Aggregate results
    t_rect_sims    = np.array([[r["t_rect"]       for r in res] for res in all_results_padded])
    water_sims     = np.array([[r["water"]         for r in res] for res in all_results_padded])
    rpe_sims       = np.array([[r["rpe_total"]     for r in res] for res in all_results_padded])
    stopped_sims   = np.array([[r["stopped"]       for r in res] for res in all_results_padded])
    first_aid_sims      = np.array([[r["first_aid_visit"]    for r in res] for res in all_results_padded])
    unlive_sims    = np.array([[r["is_unliveable"] for r in res] for res in all_results_padded])
    met_sims       = np.array([[r.get("current_met", float('nan')) for r in res] for res in all_results_padded])
    auc_per_sim    = np.array([res[-1].get("auc_thermisch", 0.0) for res in all_results])
    # [rev14-B] AUC_klinisch (Roberts threshold 40.5 deg C)
    auc_kl_per_sim = np.array([res[-1].get("auc_klinisch", 0.0) for res in all_results])
    # [rev14-C] Post-finish outcomes
    ehs_pf_per_sim = np.array([res[-1].get("ehs_postfinish", False) for res in all_results])
    t_rect_pf_sim  = np.array([res[-1].get("t_rect_piek_postfinish", res[-1]["t_rect"])
                                for res in all_results])
    auc_kl_tot_sim = np.array([res[-1].get("auc_klinisch_totaal", auc_kl_per_sim[i])
                                for i, res in enumerate(all_results)])
    # [rev14-A] K_p population distribution
    kp_per_sim     = np.array([res[-1].get("kp_ind", K_P_PACING) for res in all_results])

    # [rev16] Vulnerable upper-tail cohort for operational plotting.
    # This is NOT a confidence interval. It is a fixed subgroup: participants
    # whose personal peak T_rect over the full event lies in the hottest 2.5%
    # of the simulated population. Keeping the cohort fixed makes the plot
    # interpretable as "the most vulnerable runners" rather than the highest
    # value at each separate time point.
    vulnerable_tail_pct_target = 2.5
    peak_t_rect_per_sim = np.nanmax(t_rect_sims, axis=1)
    vulnerable_tail_cutoff = float(np.nanpercentile(
        peak_t_rect_per_sim, 100.0 - vulnerable_tail_pct_target
    ))
    vulnerable_tail_mask = peak_t_rect_per_sim >= vulnerable_tail_cutoff
    if not np.any(vulnerable_tail_mask):
        vulnerable_tail_mask[int(np.nanargmax(peak_t_rect_per_sim))] = True
    vulnerable_tail_n = int(np.sum(vulnerable_tail_mask))
    vulnerable_tail_pct_actual = float(vulnerable_tail_n / n_simulations * 100)
    vulnerable_tail_t_rect_sims = t_rect_sims[vulnerable_tail_mask, :]
    vulnerable_tail_profiles = [
        p for p, selected in zip(simulations_params_base, vulnerable_tail_mask)
        if selected
    ]

    # [2026-09] With sample_pace=True, the vulnerable-tail SUBSET can finish
    # (in wall-clock terms) before the population's overall longest
    # duration if the longest-duration participant doesn't happen to be in
    # the tail -- so the last few timesteps of this subset can be entirely
    # NaN, which is a legitimate "no one left in this subgroup is still
    # running" result, not an error. numpy's nanmean/nanpercentile warn
    # ("Mean of empty slice" / "All-NaN slice encountered") on exactly this
    # case; suppressed locally here since the resulting NaN is the correct
    # answer, not a sign something went wrong.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Mean of empty slice")
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        vulnerable_tail_mean_t_rect = np.nanmean(vulnerable_tail_t_rect_sims, axis=0)
        vulnerable_tail_p50_t_rect  = np.nanpercentile(vulnerable_tail_t_rect_sims, 50, axis=0)
        vulnerable_tail_p95_t_rect  = np.nanpercentile(vulnerable_tail_t_rect_sims, 95, axis=0)

    # [fix 2026-09] Population-level aggregates below use the nan-safe
    # numpy variants (nanmean/nanpercentile), not plain mean/percentile.
    # Real, reproduced case: a single participant (out of 1000) with a NaN
    # t_rect at some timestep -- e.g. an edge-case simulation failure for
    # that one profile -- silently poisoned np.mean()/np.percentile() for
    # that ENTIRE timestep across all 1000 participants, even though 999
    # of them had perfectly valid values. This made mean_t_rect (and the
    # other lines below) come out fully NaN for the whole run, which
    # cascaded into "n.b." in the report and empty population plots --
    # while per-participant summaries computed elsewhere with nanmax/
    # nanpercentile (see peak_t_rect_per_sim above, used for the
    # vulnerable-tail cohort) were correctly unaffected. Matching that
    # already-correct pattern here.
    stats = {
        'mean_t_rect':        np.nanmean(t_rect_sims, axis=0),
        'lower_t_rect':       np.nanpercentile(t_rect_sims,  5, axis=0),
        'upper_t_rect':       np.nanpercentile(t_rect_sims, 95, axis=0),
        't_rect_p975':        np.nanpercentile(t_rect_sims, 97.5, axis=0),
        't_rect_p99':         np.nanpercentile(t_rect_sims, 99, axis=0),
        'vulnerable_tail_pct_target': vulnerable_tail_pct_target,
        'vulnerable_tail_pct_actual': vulnerable_tail_pct_actual,
        'vulnerable_tail_n':          vulnerable_tail_n,
        'vulnerable_tail_peak_cutoff': vulnerable_tail_cutoff,
        'vulnerable_tail_mean_t_rect': vulnerable_tail_mean_t_rect,
        'vulnerable_tail_p50_t_rect':  vulnerable_tail_p50_t_rect,
        'vulnerable_tail_p95_t_rect':  vulnerable_tail_p95_t_rect,
        'vulnerable_tail_age_mean':    float(np.mean([p.age for p in vulnerable_tail_profiles])),
        'vulnerable_tail_vo2max_mean': float(np.mean([p.vo2max for p in vulnerable_tail_profiles])),
        'vulnerable_tail_kp_mean':     float(np.mean([
            getattr(p, 'kp_pacing', K_P_PACING) for p in vulnerable_tail_profiles
        ])),
        'vulnerable_tail_nsaid_pct':   float(np.mean([
            getattr(p, 'nsaid_gebruik', False) for p in vulnerable_tail_profiles
        ]) * 100),
        'mean_water':         np.nanmean(water_sims, axis=0),
        'lower_water':        np.nanpercentile(water_sims,  5, axis=0),
        'upper_water':        np.nanpercentile(water_sims, 95, axis=0),
        'mean_rpe':           np.nanmean(rpe_sims, axis=0),
        'lower_rpe':          np.nanpercentile(rpe_sims,  5, axis=0),
        'upper_rpe':          np.nanpercentile(rpe_sims, 95, axis=0),
        'percent_stopped':    np.nanmean(stopped_sims, axis=0) * 100,
        'percent_first_aid':       np.nanmean(first_aid_sims, axis=0) * 100,
        'percent_unliveable': np.nanmean(unlive_sims, axis=0) * 100,
        'temp_threshold_stats': _calculate_threshold_stats(t_rect_sims, n_simulations),
        'mean_current_met':   np.nanmean(met_sims, axis=0),
        'lower_current_met':  np.nanpercentile(met_sims,  5, axis=0),
        'upper_current_met':  np.nanpercentile(met_sims, 95, axis=0),
        'auc_thermisch_p50':  float(np.percentile(auc_per_sim, 50)),
        'auc_thermisch_p95':  float(np.percentile(auc_per_sim, 95)),
        'auc_thermisch_mean': float(np.mean(auc_per_sim)),
        'pct_auc_above_5':    float(np.mean(auc_per_sim > 5.0) * 100),
        # [rev14-A] K_p population statistics
        'kp_mean':            float(np.mean(kp_per_sim)),
        'kp_p05':             float(np.percentile(kp_per_sim,  5)),
        'pct_kp_onder_002':   float(np.mean(kp_per_sim < 0.02) * 100),  # overmotivated
        'pct_nsaid':          float(np.mean([getattr(p, 'nsaid_gebruik', False)
                               for p in simulations_params_base]) * 100),
        # [rev14-B] AUC_klinisch (Roberts 2007)
        'auc_klinisch_p50':   float(np.percentile(auc_kl_per_sim, 50)),
        'auc_klinisch_p95':   float(np.percentile(auc_kl_per_sim, 95)),
        'auc_klinisch_totaal_p95': float(np.percentile(auc_kl_tot_sim, 95)),
        'pct_roberts_kritiek': float(np.mean(auc_kl_tot_sim > AUC_ROBERTS_GRENS) * 100),
        # [2026-09] Thermal-only critical threshold (T_THERMAL_ONLY_CRITICAL,
        # 42.0 degC) -- direct thermal CNS injury pathway, independent of
        # CO_reserve. Distinct from and complementary to the conjunctive
        # clinical criterion (T_rect>40.5 AND CO_reserve<=0), which captures
        # the cardiovascular-perfusion pathway only. Reuses peak_t_rect_per_sim
        # (already computed above for the vulnerable-tail cohort).
        'pct_thermal_only_critical': float(np.mean(
            peak_t_rect_per_sim > T_THERMAL_ONLY_CRITICAL) * 100),
        # [rev14-C] Post-finish
        'pct_ehs_postfinish': float(np.mean(ehs_pf_per_sim) * 100),
        # [2026-10-20] EAC-staan: expected collapses on standing per 1000 starters
        'eac_per_1000':       float(np.mean([res[-1].get('eac_kans', 0.0) for res in all_results]) * 1000),
        # [2026-10-20 late] Median over runners of each runner's highest race WBGT;
        # above EAC_WBGT_VALID_MAX no field data exist, so no EAC figure is shown.
        # Below it the figure is provisional: calibrated at one point, not validated.
        'wbgt_race_max_p50':  float(np.nanmedian([np.nanmax([r.get('wbgt', np.nan) for r in res
                                                             if r.get('wbgt') is not None] or [np.nan])
                                                  for res in all_results])),
        't_rect_pf_p95':      float(np.percentile(t_rect_pf_sim, 95)),
    }
    stats['eac_buiten_bereik'] = bool(np.isfinite(stats['wbgt_race_max_p50'])
                                      and stats['wbgt_race_max_p50'] > EAC_WBGT_VALID_MAX)

    control_failure_per_sim = None
    if run_control_failure and TCF_AVAILABLE:
        # [rev17] Optional Thermoregulatory Control Failure analysis.
        # This is an experimental mechanistic metric, not a clinical EHS
        # diagnosis. It combines critical T_rect excess, CO-reserve deficit,
        # and duration into a dose with units deg C * L.
        tcf_result = analyse_control_failure_population(all_results, TCF_CONFIG)
        control_failure_per_sim = tcf_result.get('per_participant', [])
        stats.update(tcf_result.get('summary', {}))

    # CVR population statistics
    if CVR_AVAILABLE:
        # [2026-09] Same padding fix as the main aggregation block above --
        # this block builds rectangular arrays too and crashed the same way
        # on a sample_pace=True population before this used the padded copy.
        hr_sims  = np.array([[r.get('hr_geschat',   float('nan')) for r in res] for res in all_results_padded])
        cvs_sims = np.array([[r.get('cvs_index',    float('nan')) for r in res] for res in all_results_padded])
        res_sims = np.array([[r.get('co_reserve',   float('nan')) for r in res] for res in all_results_padded])
        dec_sims = np.array([[r.get('decompensating', False)       for r in res] for res in all_results_padded])

        hr_piek  = np.nanmax(hr_sims,  axis=1)
        cvs_piek = np.nanmax(cvs_sims, axis=1)
        res_min  = np.nanmin(res_sims, axis=1)
        dec_ooit = np.any(dec_sims, axis=1)

        # [2026-09] Was building a full [n_sims x n_steps] array just to take
        # its last column (dehy_sims[:, -1]) -- with ragged per-person
        # lengths (sample_pace=True) that crashed the same way the other
        # blocks did, and using all_results_padded here would have hit the
        # same wrong-final-value bug those needed all_results (unpadded)
        # to avoid (a short person's last real reading, not a padded NaN/0
        # in the last column of the full-width array). Computing the one
        # value actually used directly, per person, from their own real
        # last entry, sidesteps both problems at once.
        dehy_eind = np.array([
            res[-1].get('water', 0) / 1000 / max(1, simulations_params_base[i].weight) * 100
            for i, res in enumerate(all_results)
        ])
        vulnerable_tail_res_min = res_min[vulnerable_tail_mask]
        vulnerable_tail_dehy_eind = dehy_eind[vulnerable_tail_mask]
        hr_maxen  = [208 - 0.7 * p.age for p in simulations_params_base]

        # Collapse risk (two-phase logistic)
        # [rev12] intercept_kal and P_OBS now come from COLLAPSE_ENDPOINTS table.
        # The active endpoint is set by ACTIVE_ENDPOINT (module-level constant)
        # or overridden by the endpoint_key argument passed to this function.
        W_T1 = 1.0
        W_T2 = 4.0
        W_C  = 0.8
        W_D  = 0.5
        P_OBS = P_OBS_COLLAPSE

        t_rect_max_per_sim = np.nanmax(t_rect_sims, axis=1)
        # [2026-10-20] Race + finish zone (COLLAPSE_INCLUDES_POSTFINISH).
        _extremes = [collapse_extremes(res) for res in all_results]
        t_rect_max_collapse = np.array([e[0] for e in _extremes])
        res_min_collapse    = np.array([e[1] for e in _extremes])
        res_min_collapse    = np.where(np.isnan(res_min_collapse), 2.0, res_min_collapse)
        z_zonder_intercept = (
              W_T1 * np.clip(t_rect_max_collapse - 39.5, 0.0, None)
            + W_T2 * np.clip(t_rect_max_collapse - 40.5, 0.0, None)
            + W_C  * np.clip(2.0 - res_min_collapse,  0.0, None)
            + W_D  * np.clip(dehy_eind - 3.0,          0.0, None)
        )

        # [rev12] Read intercept from active endpoint in COLLAPSE_ENDPOINTS table
        active_ep         = COLLAPSE_ENDPOINTS[ACTIVE_ENDPOINT]
        intercept_kal     = active_ep['intercept_kal']  # [rev12: was hardcoded -10.071]

        z_collapse          = intercept_kal + z_zonder_intercept
        p_collapse_per_sim  = 1.0 / (1.0 + np.exp(-z_collapse))

        p_collapse_mediaan  = float(np.nanpercentile(p_collapse_per_sim, 50)) * 100
        p_collapse_p95      = float(np.nanpercentile(p_collapse_per_sim, 95)) * 100
        p_collapse_mean= float(np.nanmean(p_collapse_per_sim)) * 100
        pct_hoog_risico     = float(np.nanmean(p_collapse_per_sim > 0.50)) * 100
        verwacht_per_1000   = p_collapse_mean * 10

        # [suite-integration addition] The collapse-risk term is threshold-
        # gated (each of the four contributions is max(0, ...)): if NOBODY in
        # the population crosses ANY of the four trigger conditions (T_rect >
        # 39.5/40.5, CO_reserve < 2.0, dehydration > 3%), z_zonder_intercept is
        # exactly 0 for every participant, so p_collapse collapses to the
        # calibrated baseline intercept alone -- identical for the whole
        # population, regardless of age/sex/individual physiology. This is
        # mathematically correct, not a bug, but it means the reported risk
        # has zero discriminative power for this scenario (typically light
        # activity in cool conditions) -- it is not an individual estimate,
        # just the population base rate. Flag this explicitly so it isn't
        # mistaken for broken output.
        pct_any_trigger = float(np.mean(z_zonder_intercept > 0.0) * 100)
        if pct_any_trigger == 0.0:
            print(f"{Fore.YELLOW}Note: 0% of participants crossed any collapse-risk "
                  f"trigger condition (T_rect>39.5/40.5°C, CO_reserve<2.0 L/min, "
                  f"dehydration>3%) in this scenario. The collapse-risk value reported "
                  f"below is therefore the calibrated baseline rate applied uniformly to "
                  f"everyone, not an individually differentiated estimate -- expected for "
                  f"light activity / mild conditions, not a defect.{Style.RESET_ALL}")

        stats.update({
            'hr_peak_p50':        float(np.nanpercentile(hr_piek,  50)),
            'hr_peak_p95':        float(np.nanpercentile(hr_piek,  95)),
            'cvs_peak_p50':       float(np.nanpercentile(cvs_piek, 50)),
            'cvs_peak_p95':       float(np.nanpercentile(cvs_piek, 95)),
            'pct_cvs_above_90':   float(np.nanmean(cvs_piek > 0.90) * 100),
            'pct_decompensation':  float(np.mean(dec_ooit) * 100),
            'co_reserve_min_p50': float(np.nanpercentile(res_min,   50)),
            'co_reserve_min_p05': float(np.nanpercentile(res_min,    5)),
            'dehy_pct_p50':       float(np.nanpercentile(dehy_eind, 50)),
            'dehy_pct_p95':       float(np.nanpercentile(dehy_eind, 95)),
            'vulnerable_tail_co_reserve_min_p50': float(np.nanpercentile(vulnerable_tail_res_min, 50)),
            'vulnerable_tail_co_reserve_min_p05': float(np.nanpercentile(vulnerable_tail_res_min, 5)),
            'vulnerable_tail_dehy_pct_p50':       float(np.nanpercentile(vulnerable_tail_dehy_eind, 50)),
            'vulnerable_tail_dehy_pct_p95':       float(np.nanpercentile(vulnerable_tail_dehy_eind, 95)),
            'hr_max_population':   float(np.mean(hr_maxen)),
            'p_collapse_mediaan':           p_collapse_mediaan,
            'p_collapse_p95':               p_collapse_p95,
            'p_collapse_mean':         p_collapse_mean,
            'pct_high_collapse_risk':       pct_hoog_risico,
            'p_collapse_per_sim':           p_collapse_per_sim,
            'collapse_intercept_kal':       float(intercept_kal),
            'collapse_p_obs_pct':           P_OBS * 100,
            'expected_collapses_per_1000':  verwacht_per_1000,
            # [rev12] Endpoint traceability
            'active_endpoint':              ACTIVE_ENDPOINT,
            'active_endpoint_label':        active_ep['label'],
            'active_endpoint_status':       active_ep['status'],
            'active_endpoint_source':       active_ep['source'],
            'active_endpoint_p_obs':        active_ep['p_obs'],
        })

        # [rev15] Calibration uncertainty bands (intercept ± 0.5 log-odds)
        _sens = _intercept_sensitivity(z_zonder_intercept, intercept_kal, delta=0.5)
        dec_lo, dec_hi = _pct_sensitivity_from_flag(
            dec_ooit, z_zonder_intercept, intercept_kal, delta=0.5)
        rob_lo, rob_hi = _pct_sensitivity_from_flag(
            (auc_kl_tot_sim > AUC_ROBERTS_GRENS), z_zonder_intercept, intercept_kal, delta=0.5)
        pf_lo, pf_hi   = _pct_sensitivity_from_flag(
            ehs_pf_per_sim, z_zonder_intercept, intercept_kal, delta=0.5)
        stats.update({
            # Collapse probability band
            'p_collapse_mean_lo':   _sens['p_collapse_mean_lo'],
            'p_collapse_mean_hi':   _sens['p_collapse_mean_hi'],
            'pct_high_collapse_risk_lo': _sens['pct_hoog_risico_lo'],
            'pct_high_collapse_risk_hi': _sens['pct_hoog_risico_hi'],
            # Physiological fraction bands (approximate; see docstring)
            'pct_decompensation_lo':      dec_lo,
            'pct_decompensation_hi':      dec_hi,
            'pct_roberts_kritiek_lo':    rob_lo,
            'pct_roberts_kritiek_hi':    rob_hi,
            'pct_ehs_postfinish_lo':     pf_lo,
            'pct_ehs_postfinish_hi':     pf_hi,
        })

    # Build Excel export DataFrame
    detailed_export_data = []
    for i, sim_result in enumerate(all_results):
        p           = simulations_params_base[i]
        demographics= participant_demographics[i]
        max_t_rect  = max(r["t_rect"] for r in sim_result)
        max_rpe     = max(r["rpe_total"] for r in sim_result)
        max_dehy    = max(r["water"] / 1000 / p.weight * 100 for r in sim_result) if p.weight > 0 else 0

        # [rev10] Include pct_vo2max and implied MET in export
        implied_met = p.vo2max * p.pct_vo2max / VO2MAX_TO_MET_FACTOR
        final_auc   = sim_result[-1].get('auc_thermisch', 0.0)
        final_auc_kl= sim_result[-1].get('auc_klinisch', 0.0)
        auc_kl_tot  = sim_result[-1].get('auc_klinisch_totaal', final_auc_kl)
        min_met     = min((r.get('current_met', implied_met) for r in sim_result), default=implied_met)
        ehs_pf      = sim_result[-1].get('ehs_postfinish', False)
        t_rect_pf   = sim_result[-1].get('t_rect_piek_postfinish', sim_result[-1]['t_rect'])
        tcf_row     = control_failure_per_sim[i] if control_failure_per_sim is not None else {}
        conj_bereikt  = sim_result[-1].get('conjunctie_ooit_bereikt', False)
        conj_eerste   = sim_result[-1].get('conjunctie_eerste_min', None)
        conj_hersteld = sim_result[-1].get('conjunctie_ooit_hersteld', False)

        row = {
            'participant_id':        i + 1,
            'age':                   p.age,
            'gender':                p.gender,
            'age_group':             demographics['age_group'],
            'height_m':              round(p.height, 2),
            'weight_kg':             round(p.weight, 1),
            'vo2max_ml_kg_min':      round(p.vo2max, 1),
            'pct_vo2max':            round(p.pct_vo2max, 3),
            'implied_met_initial':   round(implied_met, 2),
            'met_min_dynamic':       round(min_met, 2),
            # [2026-10-14] Pace/finish-time and pacing-response columns:
            # needed to check the simulated field against real finish
            # times and to see how much each runner actually slowed down.
            'pace_min_per_km':       round(getattr(p, 'pace_min_per_km', 0.0), 3),
            'finish_time_h':         round(getattr(p, 'duration_hours', 0.0), 3),   # planned
            # [2026-10-19] Actual race: longer when slowed (RACE_DISTANCE_MODE),
            # shorter when stopped on RPE (RPE_STOP_ENDS_RACE).
            'race_actual_h':         round(sim_result[-1].get('race_actual_min', float('nan')) / 60.0, 3),
            'race_extension_min':    round(sim_result[-1].get('race_extension_min', float('nan')), 1),
            'race_distance_km':      round(sim_result[-1].get('race_distance_km', float('nan')), 2),
            'race_finished':         int(bool(sim_result[-1].get('race_finished', True))),
            'dnf_cutoff':            int(bool(sim_result[-1].get('dnf_cutoff', False))),
            'gestopt_rpe':           int(any(bool(r.get('stopped', False)) for r in sim_result)),
            'stop_min':              sim_result[-1].get('stop_min'),
            'nagloei_vertraging_totaal_c': round(sim_result[-1].get('afterglow_total_c', 0.0), 3),
            'nagloei_vertraging_max_c':    round(sim_result[-1].get('afterglow_max_step_c', 0.0), 3),
            'pct_vo2max_ceiling':    (round(sustainable_vo2max_fraction(p.duration_hours * 60.0), 3)
                                      if getattr(p, 'duration_hours', 0.0) else None),
            # [2026-10-15] Relative to this runner's own START MET (first
            # step), not to implied_met: implied_met is before the
            # training_offset (training_factor * 5%), so with training_factor
            # 0.5 every runner showed a spurious ~2.5% "pacing reduction".
            'pacing_reductie_pct':   (round(100.0 * (1.0 - min_met / _met_start), 1)
                                      if (_met_start := float(sim_result[0].get('current_met', implied_met) or implied_met)) > 0
                                      else None),
            # [2026-10-19] Forced pace reduction at the cardiovascular ceiling:
            # number of 10-min steps capped, and the largest MET cut.
            'cv_plafond_stappen':    int(sum(1 for r in sim_result if r.get('met_forced_reduction', 0.0) > 1e-9
                                             and not r.get('stopped', False))),
            'cv_plafond_max_met':    round(max((r.get('met_forced_reduction', 0.0) for r in sim_result), default=0.0), 2),
            'kp_pacing':            round(getattr(p, 'kp_pacing', K_P_PACING), 4),  # [rev14-A]
            'nsaid_gebruik':         int(getattr(p, 'nsaid_gebruik', False)),          # [rev14-A]
            'auc_thermisch_deg_min': round(final_auc, 2),
            'auc_klinisch_deg_min':  round(final_auc_kl, 2),                          # [rev14-B]
            'auc_klinisch_totaal':   round(auc_kl_tot, 2),                            # [rev14-C]
            'conjunctie_ooit_bereikt':  int(conj_bereikt),                            # [2026-09-29]
            'conjunctie_eerste_min':    conj_eerste,                                  # [2026-09-29]
            'conjunctie_ooit_hersteld': int(conj_hersteld),                           # [2026-09-29]
            'roberts_kritiek':       int(auc_kl_tot > AUC_ROBERTS_GRENS),             # [rev14-B]
            'ehs_postfinish':        int(ehs_pf),                                     # [rev14-C]
            't_rect_piek_postfinish':round(t_rect_pf, 3),                            # [rev14-C]
            'vulnerable_tail_top_2_5pct': int(bool(vulnerable_tail_mask[i])),          # [rev16]
            'vulnerable_tail_peak_cutoff': round(vulnerable_tail_cutoff, 3),           # [rev16]
            'tcf_dose_total_degC_L':  round(tcf_row.get('control_failure_dose_total', float('nan')), 4),
            'tcf_dose_race_degC_L':   round(tcf_row.get('control_failure_dose_race', float('nan')), 4),
            'tcf_dose_postfinish_degC_L': round(tcf_row.get('control_failure_dose_postfinish', float('nan')), 4),
            'tcf_time_total_min':     round(tcf_row.get('control_failure_time_total_min', float('nan')), 3),
            'tcf_class':              tcf_row.get('control_failure_class', ''),
            'tcf_relevant':           int(tcf_row.get('control_failure_relevant', False)),
            'tcf_severe':             int(tcf_row.get('control_failure_severe', False)),
            'temp_variation_C':      round(p.temp_variation, 2),
            'rh_variation_perc':     round(p.rh_variation, 1),
            'mf_score':              round(p.mf_score, 2),
            'sweat_factor':          round(p.sweat_factor, 2),
            'thirst_threshold_perc': round(p.thirst_threshold, 2),
            'max_t_rect':            round(max_t_rect, 4),
            # [2026-10-14] Peak over race AND 10-min post-finish window.
            'max_t_rect_incl_postfinish': round(max(max_t_rect, t_rect_pf), 4),
            'max_rpe':               round(max_rpe, 2),
            'max_water_loss_perc':   round(max_dehy, 2),
        }

        if CVR_AVAILABLE:
            hr_vals  = [r.get('hr_geschat',  float('nan')) for r in sim_result]
            cvs_vals = [r.get('cvs_index',   float('nan')) for r in sim_result]
            res_vals = [r.get('co_reserve',  float('nan')) for r in sim_result]
            row.update({
                'cvr_hr_piek':        round(float(np.nanmax(hr_vals)),  1),
                'cvr_cvs_index_max':  round(float(np.nanmax(cvs_vals)), 3),
                'cvr_co_reserve_min': round(float(np.nanmin(res_vals)), 2),
                # [2026-10-20] What the collapse logistic reads (race + finish zone).
                'cvr_co_reserve_min_incl_postfinish': round(collapse_extremes(sim_result)[1], 2),
                # [2026-10-20] EAC-staan
                'eac_kans':           round(float(sim_result[-1].get('eac_kans', 0.0)), 6),
                'eac_staanbelasting': round(float(sim_result[-1].get('eac_staanbelasting', 0.0)), 3),
                'eac_tolerantie_min': round(float(sim_result[-1].get('eac_tolerantie_min', 1.0)), 3),
                'cvr_decompensating':  any(r.get('decompensating', False) for r in sim_result),
                'cvr_p_collapse_pct': round(
                    float(stats['p_collapse_per_sim'][i]) * 100, 4
                ) if 'p_collapse_per_sim' in stats else float('nan'),
                # [rev12] Endpoint traceability columns
                'collapse_endpoint':        stats.get('active_endpoint', 'ehs'),
                'collapse_endpoint_label':  stats.get('active_endpoint_label', ''),
                'collapse_endpoint_status': stats.get('active_endpoint_status', ''),
                'collapse_p_obs_per_10k':   round(
                    stats.get('active_endpoint_p_obs', float('nan')) * 10_000, 2),
                'collapse_intercept_kal':   stats.get('collapse_intercept_kal', float('nan')),
            })
        detailed_export_data.append(row)

    results_df = pd.DataFrame(detailed_export_data)

    # [2026-09-27, gevonden via participant_dose_analysis-onderzoek met de auteur]
    # collapse-kans is een GEWOGEN SOM van een thermische en een cardiovasculaire
    # gedrempelde term; een deelnemer die op precies één van de twee assen
    # extreem scoort maar op de andere normaal blijft, gaat in die optelling
    # verloren (empirisch bevestigd: deelnemer met T_rect op het 99,8e
    # percentiel maar cvs_index_max op het 24e percentiel landde op een
    # onopvallend 78e-percentiel collapse-kans, en werd door geen van de
    # bestaande gedrempelde criteria -- EHE/klinisch/Roberts -- gevangen).
    # Dit voegt geen nieuwe fysiologische berekening toe -- alleen de twee
    # al-bestaande, continue assen (max_t_rect, cvr_cvs_index_max) worden
    # hier als percentiel naast elkaar gezet, met een vlag voor wie op
    # minstens één van de twee in de staart zit terwijl de bestaande
    # gedrempelde criteria hem/haar niet al vingen. Een grondig geteste,
    # eenvoudigere formulering (COr x T_rect-producten, in twee varianten)
    # bleek op volledige-populatieschaal grotendeels redundant met
    # max_t_rect resp. cvr_cvs_index_max zelf (Spearman rho 0,99 / 0,996)
    # en is daarom bewust NIET gebruikt.
    if CVR_AVAILABLE and 'cvr_cvs_index_max' in results_df.columns and len(results_df) > 1:
        EENZIJDIG_EXTREEM_PERCENTIEL = 97.5  # zie het gesprek: 90-99 getest, 97.5 is een redelijk midden
        results_df['thermisch_percentiel'] = results_df['max_t_rect'].rank(pct=True) * 100
        results_df['cardiovasculair_percentiel'] = results_df['cvr_cvs_index_max'].rank(pct=True) * 100
        already_flagged = (
            ((results_df['max_t_rect'] > 40.5) & (results_df['cvr_co_reserve_min'] <= CO_RESERVE_CEILING_TOL)) |
            ((results_df['max_t_rect'] > 39.5) & (results_df['cvr_co_reserve_min'] <= CO_RESERVE_CEILING_TOL))
        )
        eenzijdig = (
            (results_df['thermisch_percentiel'] >= EENZIJDIG_EXTREEM_PERCENTIEL) |
            (results_df['cardiovasculair_percentiel'] >= EENZIJDIG_EXTREEM_PERCENTIEL)
        )
        results_df['eenzijdig_extreem'] = eenzijdig.astype(int)
        results_df['gemist_door_bestaande_criteria'] = (eenzijdig & ~already_flagged).astype(int)

    return all_results, stats, results_df


def run_monte_carlo_pediatric(interp_data, lat, lon, met_value, clo_value,
                               n_simulations=200, age_group="11-20",
                               fitness_factor=0.5, use_parallel=True):
    """Manages the pediatric Monte Carlo simulation process. Unchanged from rev09."""
    participant_params_list = simulate_child_participant(
        n_simulations, met_value, age_group, fitness_factor)

    n_simulations = len(participant_params_list)
    if n_simulations == 0:
        print(f"{Fore.RED}Failed to generate any valid profiles. Aborting.{Style.RESET_ALL}")
        return None, None

    worker_args = [(interp_data, lat, lon, met_value, clo_value, params, age_group, fitness_factor)
                   for params in participant_params_list]

    if use_parallel:
        with Pool(multiprocessing.cpu_count()) as pool:
            all_results = list(tqdm(
                pool.imap(worker_monte_carlo_pediatric, worker_args),
                total=len(worker_args), desc="Monte Carlo Pediatric Sims"))
    else:
        all_results = [worker_monte_carlo_pediatric(args)
                       for args in tqdm(worker_args, desc="Monte Carlo Pediatric Sims")]

    t_core_sims   = np.array([[r["t_core"]        for r in res] for res in all_results])
    water_sims    = np.array([[r["water_loss_ml"]  for r in res] for res in all_results])
    rpe_sims      = np.array([[r["rpe_total"]      for r in res] for res in all_results])
    stopped_sims  = np.array([[r["stopped"]        for r in res] for res in all_results])
    first_aid_sims= np.array([[r["first_aid_visit"]for r in res] for res in all_results])

    stats = {
        'mean_t_core':      np.mean(t_core_sims, axis=0),
        'lower_t_core':     np.percentile(t_core_sims,  5, axis=0),
        'upper_t_core':     np.percentile(t_core_sims, 95, axis=0),
        'mean_water':       np.mean(water_sims, axis=0),
        'lower_water':      np.percentile(water_sims,  5, axis=0),
        'upper_water':      np.percentile(water_sims, 95, axis=0),
        'mean_rpe':         np.mean(rpe_sims, axis=0),
        'lower_rpe':        np.percentile(rpe_sims,  5, axis=0),
        'upper_rpe':        np.percentile(rpe_sims, 95, axis=0),
        'percent_stopped':  np.mean(stopped_sims, axis=0) * 100,
        'percent_first_aid':np.mean(first_aid_sims, axis=0) * 100,
        'temp_threshold_stats': _calculate_threshold_stats(t_core_sims, n_simulations),
    }
    return all_results, stats


# =============================================================================
#  RISK CLASSIFICATION (unchanged from rev09)
# =============================================================================

def calculate_adult_risk_classification(utci_val, wbgt_val, t_rect, rpe_total):
    scores = {
        'utci':  0 if utci_val <= 26 else 1 if utci_val <= 32 else 2 if utci_val <= 38 else 3 if utci_val <= 46 else 4,
        'wbgt':  0 if wbgt_val <  25 else 1 if wbgt_val <  28 else 2 if wbgt_val <  31 else 3 if wbgt_val <  33 else 4,
        't_rect':0 if t_rect   <  38 else 1 if t_rect   <  39 else 2 if t_rect   < 39.5 else 3 if t_rect < 40 else 4,
        'rpe':   0 if rpe_total< 12  else 1 if rpe_total< 15  else 2 if rpe_total< 17   else 3 if rpe_total < 19 else 4,
    }
    s = max(scores.values())
    lvl = {0: ("No risk", Fore.WHITE), 1: ("Low risk", Fore.GREEN),
           2: ("Moderate risk", Fore.YELLOW), 3: ("High risk", Fore.MAGENTA),
           4: ("Extreme risk", Fore.RED)}
    text, color = lvl[s]
    return {"risk_color": color,
            "detailed_risk": f"{text} (U:{scores['utci']}/W:{scores['wbgt']}/T:{scores['t_rect']}/RPE:{scores['rpe']})"}


def calculate_pediatric_risk_classification(utci_val, wbgt_val, t_core, rpe_total):
    scores = {
        'utci':  0 if utci_val <= 26 else 1 if utci_val <= 32 else 2 if utci_val <= 38 else 3 if utci_val <= 46 else 4,
        'wbgt':  0 if wbgt_val <  23 else 1 if wbgt_val <  26 else 2 if wbgt_val <  29 else 3 if wbgt_val <  31 else 4,
        't_core':0 if t_core   < 38.2 else 1 if t_core  < 38.8 else 2 if t_core  < 39.2 else 3 if t_core < 39.8 else 4,
        'rpe':   0 if rpe_total<  4   else 1 if rpe_total< 6    else 2 if rpe_total< 8    else 3 if rpe_total < 9  else 4,
    }
    s = max(scores.values())
    lvl = {0: ("No risk", Fore.WHITE), 1: ("Low risk", Fore.GREEN),
           2: ("Moderate risk", Fore.YELLOW), 3: ("High risk", Fore.MAGENTA),
           4: ("Extreme risk", Fore.RED)}
    text, color = lvl[s]
    return {"risk_color": color,
            "detailed_risk": f"{text} (U:{scores['utci']}/W:{scores['wbgt']}/T:{scores['t_core']}/RPE:{scores['rpe']})"}


# =============================================================================
#  PLOTTING
#  [rev16] Adult T_rect panel separates distribution percentiles from a fixed
#  vulnerable tail cohort. The cohort is defined once by each runner's peak
#  T_rect over the full event, so the plotted tail line follows the same
#  high-risk runners over time instead of changing membership at every step.
# =============================================================================







# =============================================================================
#  MET THRESHOLD ANALYSIS (unchanged from rev09)
# =============================================================================

def get_representative_participant(age, gender):
    if gender == 'male':
        return {'height': 1.80, 'weight': 78, 'age': age, 'fat': 15, 'sex': gender}
    return {'height': 1.67, 'weight': 65, 'age': age, 'fat': 25, 'sex': gender}


def run_single_simulation_for_temp(met_value, env_conditions, participant, clo_value, duration_minutes):
    jos3 = maak_jos3(height=participant['height'], weight=participant['weight'],
                age=participant['age'], fat=participant['fat'], sex=participant['sex'])
    jos3.par = jos3_par(jos3, met_value)   # [2026-10-19] FOUNDATION REPAIR
    jos3.clo = clo_value
    jos3.tdb = env_conditions['tdb']
    jos3.tr  = env_conditions['mrt']
    jos3.v   = env_conditions['v']
    jos3.rh  = env_conditions['rh']
    jos3.simulate(times=int(duration_minutes))
    return jos3_t_rect(jos3)


def find_met_for_target_temp(target_temp, env_conditions, participant, clo_value, duration_minutes):
    met_low, met_high = 1.0, 20.0
    if run_single_simulation_for_temp(met_high, env_conditions, participant, clo_value, duration_minutes) < target_temp:
        return met_high
    if run_single_simulation_for_temp(met_low,  env_conditions, participant, clo_value, duration_minutes) > target_temp:
        return met_low
    for _ in range(5):
        met_guess = (met_low + met_high) / 2
        t_guess   = run_single_simulation_for_temp(met_guess, env_conditions, participant, clo_value, duration_minutes)
        if t_guess < target_temp:
            met_low  = met_guess
        else:
            met_high = met_guess
    return (met_low + met_high) / 2


def analyze_met_thresholds(interp_data, lat, lon, clo_value):
    print("\nStarting analysis of safe MET thresholds...")
    age_groups      = {"18-29": 25, "30-39": 35, "40-49": 45, "50-59": 55, "60-65": 62}
    genders         = ['male', 'female']
    temp_thresholds = [39.0, 39.5, 40.0, 41.0]
    results         = []
    aqi             = get_air_quality(lat, lon)
    detailed_env    = []
    _w15s = [wind_speed_at_height(en['wind'], 10, 1.5) for en in interp_data]
    _rs = radiation_series(interp_data, [en['time'] for en in interp_data],
                           [en['temp'] for en in interp_data], _w15s,
                           [en['pressure'] for en in interp_data],
                           [en['clouds'] for en in interp_data], lat, lon, aqi,
                           rhs=[en['rh'] for en in interp_data])
    for _i, entry in enumerate(interp_data):
        w15      = _w15s[_i]
        gt       = _rs[2][_i]
        mrt      = _rs[3][_i]
        detailed_env.append({'time': entry['time'], 'tdb': entry['temp'],
                              'mrt': mrt, 'v': max(0.1, w15), 'rh': entry['rh']})

    total = len(detailed_env) * len(age_groups) * len(genders) * len(temp_thresholds)
    with tqdm(total=total, desc="Calculating MET Thresholds") as pbar:
        for i, env_step in enumerate(detailed_env):
            duration_minutes = max(1, (env_step['time'] - detailed_env[0]['time']).total_seconds() / 60)
            for age_label, age_val in age_groups.items():
                for gender in genders:
                    participant = get_representative_participant(age_val, gender)
                    for target_temp in temp_thresholds:
                        results.append({
                            'time':            env_step['time'],
                            'age_group':       age_label,
                            'gender':          gender,
                            'temp_threshold':  target_temp,
                            'permissible_met': find_met_for_target_temp(
                                target_temp, env_step, participant, clo_value, duration_minutes),
                        })
                        pbar.update(1)
    return pd.DataFrame(results)




# =============================================================================
#  THERMOPOULOS EXCEL LOADER (unchanged from rev09)
# =============================================================================

def _num(row, col):
    """Float value of an optional Data Engine column, None when absent/empty."""
    try:
        v = row[col]
    except (KeyError, IndexError):
        return None
    return None if pd.isna(v) else float(v)


def load_weather_from_thermopoulos_excel(filepath, sheet_name, timezone=None):
    """Load weather data from a Thermopoulos Excel file.

    The time zone is read from the Metadata sheet; pass `timezone` when the
    file has none (2026-10-25: no longer asked interactively; the console
    asks for it in hestia_console.main when needed)."""
    try:
        df = pd.read_excel(filepath, sheet_name=sheet_name, index_col=0)
    except Exception as e:
        print(f"{Fore.RED}Error reading Excel file: {e}{Style.RESET_ALL}")
        return None, None

    required = ['T_air_urban', 'RH', 'pressure', 'wind_10m', 'cloud_cover']
    missing  = [col for col in required if col not in df.columns]
    if missing:
        print(f"{Fore.RED}Missing columns: {missing}{Style.RESET_ALL}")
        return None, None

    tz_str = timezone
    try:
        meta_df = pd.read_excel(filepath, sheet_name='Metadata', header=0)
        meta_df.columns = meta_df.columns.str.strip().str.lower()
        if 'timezone' in meta_df.columns and timezone is None:
            tz_str = str(meta_df.iloc[0]['timezone']).strip()
    except Exception as e:
        print(f"{Fore.YELLOW}Could not read Metadata sheet: {e}{Style.RESET_ALL}")

    if not tz_str:
        print(f"{Fore.RED}No time zone in the Metadata sheet; pass timezone=...{Style.RESET_ALL}")
        return None, None

    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except:
            print(f"{Fore.RED}Index could not be converted to datetime.{Style.RESET_ALL}")
            return None, None

    # [2026-10-31] Older Data Engine file: recompute globe/MRT/WBGT/UTCI with
    # the current globe model (thermal_env.actualiseer_straling).
    try:
        _meta = pd.read_excel(filepath, sheet_name='Metadata', header=0).iloc[0].to_dict()
    except Exception:
        _meta = None
    from thermal_env import actualiseer_straling
    df, _herb = actualiseer_straling(df, _meta)
    if _herb:
        print(f"{Fore.YELLOW}{sheet_name}: made by an older Data Engine; globe temperature, MRT, "
              f"WBGT and UTCI recomputed with the current globe model.{Style.RESET_ALL}")

    if df.index.tz is None:
        df.index = df.index.tz_localize(tz_str)

    weather_data = []
    for idx, row in df.iterrows():
        weather_data.append({
            "dt":   int(idx.timestamp()),
            # [2026-10-31] RH_urban belongs to T_air_urban (same dew point);
            # the rural RH is kept as humidity_rural for the rural chain.
            "main": {"temp": row["T_air_urban"],
                     "humidity": _num(row, "RH_urban") if _num(row, "RH_urban") is not None else row["RH"],
                     "humidity_rural": row["RH"],
                     "pressure": row["pressure"]},
            "wind": {"speed": row["wind_10m"]},
            "clouds": {"all": row["cloud_cover"]},
            # [2026-10-24] carry the Data Engine's measured/forecast radiation,
            # globe temperature and MRT, as thermopoulos_loader does.
            "solar": {"ghi": _num(row, "solar_radiation"), "elevation": _num(row, "solar_elevation")},
            "radiant": {"globe_temp": _num(row, "T_globe"), "mrt": _num(row, "MRT"),
                        "twb": _num(row, "T_wetbulb")},
            "indices": {"wbgt": _num(row, "WBGT"), "utci": _num(row, "UTCI")},
        })
    print(f"{Fore.GREEN}Loaded {len(weather_data)} hours from {sheet_name}.{Style.RESET_ALL}")
    return weather_data, tz_str


# =============================================================================
#  WBGT 5-DAY EXPORT (unchanged)
# =============================================================================

def calculate_and_export_wbgt(city_name, lat, lon, apply_uhi=False, population=None):
    """Calculates WBGT for the next 5 days and saves to Excel. Unchanged."""
    print(f"\n--- Calculating WBGT for {city_name} for the next 5 days ---")
    current_date   = datetime.now().strftime('%Y-%m-%d')
    sheet_name     = f"{city_name.replace(' ', '_')}_{current_date}"
    excel_filename = "HESTIA_Simulation_Results.xlsx"
    weather_data   = get_weather_forecast(lat, lon)
    if not weather_data:
        return
    start_dt    = pd.Timestamp.now(tz=UTC)
    end_dt      = start_dt + timedelta(days=5)
    interp_data = interpolate_weather(weather_data, start_dt, end_dt, interval_minutes=60)
    if apply_uhi:
        for entry in interp_data:
            entry["temp"] += calculate_uhi_effect(population, entry["wind"],
                                                   6 <= entry["time"].hour < 18)
    wbgt_results = []
    aqi = get_air_quality(lat, lon)
    _w15s = [wind_speed_at_height(en["wind"], 10, 1.5) for en in interp_data]
    _rs = radiation_series(interp_data, [en["time"] for en in interp_data],
                           [en["temp"] for en in interp_data], _w15s,
                           [en["pressure"] for en in interp_data],
                           [en["clouds"] for en in interp_data], lat, lon, aqi,
                           rhs=[en["rh"] for en in interp_data])
    for _i, entry in enumerate(interp_data):
        wind_1_5m  = _w15s[_i]
        globe_temp = _rs[2][_i]
        mrt        = _rs[3][_i]
        with_solar = bool(_rs[0][_i] > 0 and _rs[1][_i] > 0)
        wbgt_args  = {"twb": entry["twb"], "tg": globe_temp,
                      "with_solar_load": with_solar, "round_output": True}
        if with_solar:
            wbgt_args["tdb"] = entry["temp"]
        wbgt_val   = float(wbgt(**wbgt_args).wbgt)
        uhi_effect = calculate_uhi_effect(population, entry["wind"],
                                           6 <= entry["time"].hour < 18) if apply_uhi else 0.0
        wbgt_results.append({
            "time": entry["time"].strftime('%Y-%m-%d %H:%M'), "temperature": entry["temp"],
            "relative_humidity": entry["rh"], "wind_speed": entry["wind"],
            "cloud_cover": entry["clouds"], "pressure": entry["pressure"],
            "wet_bulb_temp": entry["twb"], "globe_temp": globe_temp, "mrt": mrt,
            "wbgt": wbgt_val, "uhi_effect_applied": uhi_effect,
        })
    try:
        if os.path.exists(excel_filename):
            with pd.ExcelWriter(excel_filename, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                pd.DataFrame(wbgt_results).to_excel(writer, sheet_name=sheet_name, index=False)
        else:
            with pd.ExcelWriter(excel_filename, engine='openpyxl', mode='w') as writer:
                pd.DataFrame(wbgt_results).to_excel(writer, sheet_name=sheet_name, index=False)
        print(f"{Fore.GREEN}[SUCCESS] WBGT data exported.{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] Could not export to Excel: {e}{Style.RESET_ALL}")


# =============================================================================
#  USER INPUT FUNCTIONS (unchanged)
# =============================================================================









def clear_all_caches():
    get_lat_lon.cache_clear()
    get_timezone.cache_clear()
    get_weather_forecast.cache_clear()
    get_air_quality.cache_clear()
    calculate_solar_radiance.cache_clear()
    print("All function caches cleared.")


# =============================================================================
#  MAIN (rev10 changes: population generation, validation, and persistence)
# =============================================================================




# =============================================================================
#  Moved names (2026-10-25): the interactive console lives in hestia_console.py
#  and the console figures in hestia_model_plots.py. Old imports keep working.
# =============================================================================
_MOVED = {
    **{n: "hestia_console" for n in ("select_met_activity", "select_clo_value",
                                      "select_age_configuration", "get_adaptation_profile", "main")},
    **{n: "hestia_model_plots" for n in ("plot_adult_results", "plot_pediatric_results",
                                          "plot_adult_boxplots", "plot_met_thresholds")},
}


def __getattr__(name):
    if name in _MOVED:
        import importlib
        return getattr(importlib.import_module(_MOVED[name]), name)
    raise AttributeError(f"module 'hestia_model' has no attribute '{name}'")


if __name__ == "__main__":
    from hestia_console import main as _console_main
    _console_main()
