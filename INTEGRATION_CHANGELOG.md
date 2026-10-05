![Thermopoulos](branding/thermopoulos.png){width=1.8in}

# Integration changelog — CVR/tailplot HESTIA into the suite

> **[2026-07] Translation status**: entries from this point down (until the
> horizontal rule marking the pre-2026-07 history) are in English. Everything
> below that rule is the original, unmodified pre-2026-07 history and is
> still in Dutch, pending a dedicated translation pass. If you need something
> from that section translated, ask and it can be done incrementally rather
> than all at once.

## [2026-07] New: generate_event_report.py -- fixed, factual report template

Added at the user's explicit request, ahead of running Utrecht, Enschede,
Leiden, and Maastricht marathon simulations: a standardized report
generator (`generate_event_report.py`, `generate_report()`) that turns any
`monte_carlo_adult()` output into a structured Markdown report with a
FIXED section order, so reports from different events are directly
comparable. Written in Dutch (the target audience -- GHOR, race
organizers -- as with the user's other external-facing documents),
separate from the English-language codebase.

**Deliberately contains facts only, no recommendations or advice** -- per
the user's explicit requirement that organizations and emergency services
must be able to draw their own conclusions. Every line states a computed
value and its source/definition; nothing is phrased as "should" or
"recommended."

Sections (fixed order): (1) simulated scenario metadata (event, location,
start time, duration, activity, N, which collapse-risk endpoint was used
and its calibration status/source, plus an optional free-text field for
the event's own documented reference incidence, stated without comparison
or judgement); (2) thermal outcomes; (3) cardiovascular outcomes; (4)
collapse risk; (5) post-finish outcomes; (6) thermoregulatory control
failure (Roberts AUC); (7) vulnerable-tail cohort; (8) model provenance
and known status (which equations, which endpoint calibration status,
that wind direction is not measured and is Monte-Carlo-sampled per
participant instead) -- stated as facts about the model's current state,
not caveats framed as advice.

**Bug found and fixed during testing:** several `stats` fields
(`mean_t_rect`, `lower_t_rect`, `upper_t_rect`, `t_rect_p975`, `t_rect_p99`,
`mean_rpe`, `percent_stopped`, `percent_ehbo`, `percent_unliveable`) are
time series (one value per simulated time step), not scalars -- the first
version's formatter crashed calling `np.isnan()` on an array. Fixed by
having `_fmt()` take the final value of any array input (end of the
simulated window) and relabelling the relevant table section accordingly
("aan het einde van de gesimuleerde periode" rather than assuming these
represent a peak, which is not necessarily true for every field).

**Verified:** ran end to end on real Amsterdam DtD 2024 weather data
(N=300, `hospitalisation` endpoint) -- all eight sections populated
correctly, `expected_collapses_per_1000` matches the value obtained in
earlier manual testing of the same endpoint/scenario (1.945), confirming
the report generator reads the same `stats` dict correctly rather than
recomputing anything independently.

## [2026-07] intercept_estimation.py restructured to a generalizable, per-endpoint reference-conditions architecture

Found while investigating a duration-scaling question (does the incidence
literature imply a general duration-vs-AUC relationship between events of
different length, e.g. Boston ~4h vs. DtD ~1.63h). Plotting
`intercept - logit(p_target)` for all three endpoints showed it was nearly
constant (-1.915 / -1.791 / -1.787) -- initially mistaken for a real
finding about duration scaling. It wasn't: checked the calibration script
and found all three endpoints (`ehs`, `hospitalisation`, `ehbo`) were being
fit against a single, shared, module-level `REF_CONDITIONS` dict -- Boston's
own reference scenario (4h, 18-22 degC, MET 11.0) -- even though
`hospitalisation` and `ehbo` are DtD-observed numbers from DtD's own,
quite different real conditions (~1.63h, Amsterdam September 2024). The
near-constant offset was a direct, guaranteed consequence of all three
intercepts sharing one z-distribution, not a discovery about how
incidence relates to duration.

**Explicitly generalizable fix (not a DtD-specific patch), per the user's
request:** every calibration target must be fit against the reference
conditions under which that target's real-world incidence was actually
observed -- never a scenario borrowed from a different event.
Restructured `intercept_estimation.py`:
- `REF_CONDITIONS` (single, shared) replaced by `REF_CONDITIONS_BOSTON` and
  a new `REF_CONDITIONS_DTD` (1.63h, 19.5-21.5 degC, MET 9.8, matching the
  DtD scenarios run elsewhere this project -- itself an approximation, in
  the same spirit as Boston's own synthetic reference block, not a literal
  replay of the fetched Thermopoulos weather file for that day), collected
  in `REF_CONDITIONS_BY_KEY`.
- Each `ENDPOINTS[*]` entry gained a `ref_conditions_key` naming which
  block matches its own real origin: `ehs` -> `'boston'`;
  `hospitalisation` and `ehbo` -> `'dtd'` (correctly shared, since both
  genuinely are DtD 2024 numbers -- sharing a scenario across endpoints
  from the SAME real event was never the bug; sharing one ACROSS
  different events was).
- `main()` now loops over the distinct `ref_conditions_key` values actually
  needed, running one population-generation + simulation per distinct
  real scenario (population cache files are now keyed by `ref_key` too,
  since training/acclimatization factors differ between scenarios and
  affect the generated population itself), then calibrates each endpoint
  against its own matched `sim_out`. `get_population()`,
  `run_calibration_simulation()`, `print_final_report()`, and
  `save_results_json()` all updated to take `cfg`/`ref_key` explicitly
  instead of reading the old global.
- Adding a future calibration point (a fourth event, say) means adding one
  `REF_CONDITIONS_*` block and one `ENDPOINTS` entry naming it -- no other
  code changes needed. This is what makes the fix a general architectural
  principle rather than a one-off correction for Boston vs. DtD
  specifically.

**Verified the fix worked as intended:** after recalibration,
`intercept - logit(p_obs)` for `hospitalisation` and `ehbo` now match each
other closely (-0.733, -0.731 -- correctly, since they share one real
event) while clearly differing from `ehs` (-1.791 -- correctly, since it's
a different real event with different reference conditions). The previous
"near-constant across all three" pattern is gone, replaced by consistency
exactly where the underlying events genuinely match and divergence exactly
where they genuinely don't -- the expected signature of a correctly
decoupled calibration.

**New intercepts** (N=200, seed=42, same feasibility-run caveat as every
other calibration this project -- rerun at production scale before
treating as final): `ehs` unchanged (-8.803572, Boston's own conditions
didn't change); `hospitalisation` -8.340358 -> **-7.282445**; `ehbo`
-7.235395 -> **-6.179056**.

**Verified:** `python -m py_compile` on the modified files; `verify.py` and
`suite_smoke_test.py` both pass (smoke test uses the unaffected `ehs`
default, so its output is unchanged); the full calibration script itself
re-run end to end, producing the new intercepts above and the
per-reference-condition sanity check described.

## [2026-07] Post-finish CO_reserve could never recover -- simulate_post_finish() rebuilt to recompute via CVRModel.compute_step()

Found via an exploratory line of investigation into whether "sustained
duration of conjunctive control failure" could be a usable severity marker
(motivated by the user's hypothesis that sudden, hard-to-predict collapses
might be explained by such clustering). That investigation is documented
here in full, including a dead end, because the dead end itself surfaced
the real bug.

**Dead end (documented, not deleted):** an apparent "gap" in the
duration distribution -- almost nobody with a brief (1-5 min) post-finish
episode, most clustering at 5-12 min -- looked like evidence of a
self-sustaining "vicious cycle" (bistability). Checked by extending the
fixed post-finish window from 10 to 30 minutes: the median duration
scaled proportionally (9.0 -> 19.75 min) and the maximum landed exactly on
the new window edge both times -- the classic signature of right-censoring,
not a real fixed-duration process. The apparent "gap" was an artifact of
the window length, not evidence of anything physiological.

**What that dead end surfaced:** the user asked directly why CO_reserve
doesn't recover once T_rect (which can and does decline post-finish) drops
back down. Checked the code: it structurally could not.
`co_res -= pooling_rate * dt` with `pooling_rate >= 0` always -- CO_reserve
was mathematically monotonically non-increasing for the entire post-finish
window, with no mechanism of any kind to raise it again. This was
inconsistent with the same-day CVR rebuild on Lloyd et al. (2022): a
declining T_rect should lower the Cardiac Heat Strain Index, raising
CO_max back up, and MET dropping to resting level post-finish should
sharply cut CO_demand -- both of which should let CO_reserve recover, given
time.

**Fix:** `simulate_post_finish()` now takes an optional `cvr_model`
(the same `CVRModel` instance used during the race), `t_skin_finish`, and
`dehydration_kg_finish`. At each post-finish step, CO_max/CO_demand are
recomputed via the same `CVRModel.compute_step()` used during the race,
fed the (unchanged) declining T_rect and a new `PF_MET_RUST = 1.5`
constant (resting-ish MET, not zero -- finishers are rarely fully
motionless). T_skin is approximated by holding the T_core-T_skin gap
observed at the finish line constant as T_core declines (no detailed
post-finish skin-temperature model exists). The acute venous-pooling term
is kept, unchanged, as an *additive* perturbation on top of this
recomputed baseline rather than being the entire update -- it represents a
real, distinct, short-lived phenomenon (the muscle pump stopping
abruptly) that Lloyd's steady-state relationship does not itself capture,
and removing it would lose the previously-validated acute dip (see the
entry below this one). Falls back to the old pooling-only, non-recovering
formula if no `cvr_model` is supplied (backward compatible).

**Verified three ways:**
1. Individual trajectory inspection (Falmouth 2015 and Amsterdam DtD 2024):
   both show the expected dip-then-recover shape (e.g. Amsterdam: CO_reserve
   -0.18 -> -0.58 by t=6.5min -> -0.50 by t=10min -- recovery clearly
   underway, just not completed within the 10-minute window).
2. Falmouth 2015 (MET 9.8, N=300): % with any post-finish episode dropped
   from 20.7% (old, non-recovering formula) to 0.3% -- most finishers who
   dip now correctly recover within the window instead of being stuck.
3. Re-ran the window-extension falsifiability test that exposed the
   original bug: at PF_DUUR_MIN=60 (MET 11.0, 2h, heavier scenario to get
   enough crossings), most of the 14 crossers recovered within 2-45 min
   (median 29.5 min) rather than all piling up at the window edge --
   though 4/14 (~29%) still reached the 60-min boundary, which may be a
   genuine "does not recover quickly even given an hour" finding for the
   most severe cases, or may still be partially window-bound -- flagged as
   not fully resolved, not claimed as settled.
4. Confirmed consistent (low, physiologically sensible) behaviour on
   Falmouth 2003 (0% any episode) and Amsterdam DtD 2024 (0.3%, one
   participant, recovery clearly underway at window end) -- not just an
   artifact of the one scenario used to build the fix.

`verify.py` and `suite_smoke_test.py` both pass unchanged throughout.

## [2026-07] Collapse-risk endpoint selection was unreachable from the CLI actually run -- added to run_hestia.py's real entry point

Found when the user reported never seeing the endpoint-selection prompt
described earlier the same day, despite it existing in the codebase.

**Root cause:** the prompt lives in `hestia_model.py`'s own `main()` (its
`if __name__ == "__main__":` block) -- but that is not the entry point
users actually run. The real, documented entry point is `run_hestia.py`,
which has its own, completely separate `_run_cli()` function. That
function never referenced `ACTIVE_ENDPOINT` or `COLLAPSE_ENDPOINTS` at
all, so it silently always used the hard-coded default (`'ehs'`) with no
way to select `'hospitalisation'` or `'ehbo'` from the CLI a user actually
interacts with. Two parallel, similarly-named CLI entry points existed;
only one of them had ever received this feature.

**Fix:** added the equivalent endpoint-selection prompt to
`run_hestia.py`'s `_run_cli()`, positioned right after mode selection
(matching where it sits in `hestia_model.py`'s version). Since
`run_hestia.py` already does `import hestia_model as hestia`, the choice
is applied via `hestia.ACTIVE_ENDPOINT = chosen_key` -- confirmed this
correctly propagates to `monte_carlo_adult()`/`simulate_individual_adult()`,
because `hestia_model.py`'s own stats-building code reads
`COLLAPSE_ENDPOINTS[ACTIVE_ENDPOINT]` as a live module-global lookup at
call time (not a value captured once at import time), so mutating the
module attribute from outside works exactly as intended.

**Verified two ways:** (1) called `monte_carlo_adult()` directly, cycling
`hestia.ACTIVE_ENDPOINT` through all three keys (N=30, real Falmouth 2003
weather) -- each run correctly reported its own intercept and label
(ehs: -8.804, hospitalisation: -8.340, ehbo: -7.235); (2) ran
`run_hestia.py` itself with piped stdin through the full prompt sequence
and confirmed the new prompt renders in the correct position with the
correct content. `suite_smoke_test.py` and `verify.py` both still pass
unchanged.

## [2026-07] Thorough re-sweep for remaining Dutch text (requested explicitly, second full pass)

Earlier translation passes this same day covered `hestia_model.py`,
`HESTIA_CVR_Module_v2.py`, `HESTIA_CVR_Console.py`, and `intercept_estimation.py`'s
main body, but this re-sweep found real, previously-missed Dutch text in
two places that hadn't been fully swept:

**`hestia_plots.py` (not touched by any earlier pass):**
- Two console-facing plot labels/titles that appear directly in the PNGs
  the user has been reviewing all day: `plot_co_deficit_dose_extreme_cohorts()`'s
  title/axis labels ("CO_reserve-tekortdosis cumulative", "T_rect-onafhankelijk;
  NIET klinisch geijkt", "CO-tekortdosis... referentie") and
  `plot_auc_thermisch_extreme_cohorts()`'s title ("diagnostische maat,
  39,0°C-drempel, geen klinische cutoff"), plus `plot_auc_klinisch_extreme_cohorts()`'s
  "Roberts klinische drempel" legend label and "stippellijn/punt = postfinish-totaal,
  geen tussenreeks" subtitle. All translated; the `totaal` local variable in the
  first function renamed to `total` (this is a local variable, not a
  dataframe/Excel column name -- `auc_klinisch_totaal` as a column name was
  deliberately left unchanged since renaming a data-contract field now would
  break consistency with already-exported real result files).

**`intercept_estimation.py`'s report generator (`print_final_report()`),
missed by the earlier pass despite being run several times today:**
Full calibration report header ("KALIBRATIERAPPORT", "Gegenereerd",
"N_populatie", "Condities", "duur=", "Simulatietijd"), the "ja"/"NEE"
convergence-status strings, the "EP3 gevoeligheidsrange" sensitivity-table
header, the "PLAK-KLAAR" paste-ready-block header (which also still
referenced the pre-rev17 filename `HESTIA_Data_Engine_CVR_v8.py` --
corrected to `hestia_model.py`, consistent with the earlier import-path fix
to this same script), and the `label_map`/`source_map` dictionaries used to
build the pasteable `COLLAPSE_ENDPOINTS` block. Also two standalone print
statements ("Simuleer N deelnemers...", "Bouw referentie-meteorologie...").

A comprehensive re-scan (broadened Dutch-word list, applied to every `.py`
file in the suite) found no further real matches after these fixes --
remaining hits were verified false positives: "percentage"/"maximum"/"minimum"
(identical in English and Dutch), "met" (either the English past tense of
"meet", or the legitimate `"met"` dict key = MET abbreviation used
throughout the activity tables), and proper-name citations ("Koos de Boer",
"Connie van der Lee", "van de Kamp & Daanen 2025", "Andrade, de Lira &
Knechtle 2021").

**Verified:** `python -m py_compile` on every modified file; `verify.py`,
`suite_smoke_test.py`, and the CVR module's own demo all pass with output
identical to immediately before this sweep (`collapse intercept_kal =
-8.804` unchanged).

## [2026-07] Fresh-eyes cleanup pass -- two code-hygiene issues found and fixed; this snapshot kept as the baseline version

Requested explicitly as an unbiased re-read of the day's cumulative changes,
independent of the iterative process that produced them. Found two real,
if behaviourally harmless, inconsistencies left over from same-day
revert cycles -- exactly the kind of thing that accumulates during rapid
iteration and is easy to miss from inside the process that created it:

1. **Orphaned field with a misleading comment.** `RunnerProfile.pct_vo2max`
   (in `HESTIA_CVR_Module_v2.py`) was added during the same-day
   intensity-dependent a-vO2diff experiment (see the CVR-rebuild entry
   below) and its docstring still referenced `CVRModel._a_v_diff_for_intensity()`
   -- a method that no longer exists, removed during the Lloyd-equation
   rebuild. The field was still being threaded through from
   `hestia_model.py`'s `RunnerProfile(...)` construction, doing nothing.
   Removed the field entirely and the now-pointless argument at the call
   site. (Note: this is distinct from `AdultParticipantProfile.pct_vo2max`,
   which is real and still used for the MET calculation -- only the
   CVR-module-local, unused copy was removed.)

2. **Reintroduced Dutch naming after the translation pass.** `SV_rust`,
   `HR_rust`, `CO_rust` (Dutch "rust" = rest) were written during the later
   CVR rebuild, after the full English translation pass earlier the same
   day had already been completed and reported as done. Renamed to
   `SV_rest`, `HR_rest`, `CO_rest`.

Neither issue affected any computed value -- verified byte-for-byte
identical output before and after (smoke test: `collapse intercept_kal =
-8.804` unchanged; CVR module's own demo unchanged). Both are exactly the
kind of debris that accumulates from same-day iterate-test-revert cycles
and would otherwise confuse a future reader (including the project owner,
months from now) into thinking a mechanism is active when it is not, or
that a translation pass was more complete than it was.

**This snapshot is being kept as the project's baseline version** going
forward -- the point to diff future changes against, not a random
intermediate state in an ongoing session.

**Verified:** `python -m py_compile` on both modified files; `verify.py`,
`suite_smoke_test.py`, and the CVR module's own standalone demo all pass
with output identical to immediately before this cleanup pass.

## [2026-07] Post-finish venous-pooling formula fixed (dead zone for positive CO_reserve)

Found by asking directly: "does CVR data correctly propagate through the
conjunctive step?" Traced the full path (`compute_step()` -> `results[idx]['co_reserve']`
-> `res_min = np.nanmin(res_sims, axis=1)` -> collapse-risk z-function) and
confirmed no propagation bug -- the population-level collapse-risk
calculation correctly reads the rebuilt CVR module's output. But a *separate*
bug was found in `simulate_post_finish()`, made newly relevant by the CVR
rebuild above.

**The bug:** venous pooling after the finish line was modeled as
`pooling_rate = PF_DELTA_CO_POOLING * max(0.0, co_res) * exp(-t/tau)` --
a fraction (30%) of co_res *itself*. Since the decrement is proportional to
the (shrinking) current value, this has the same mathematical shape as
radioactive decay: a positive starting value asymptotically approaches zero
but can never actually cross it. Verified directly: starting values of
+0.2/+1.0/+3.0/+6.0 L/min ended a 10-minute post-finish window at
+0.12/+0.58/+1.73/+3.45 -- never below zero. Before the CVR rebuild above,
`co_reserve_finish` was often already negative or near-zero, so this dead
zone rarely mattered in practice. After the rebuild (healthier baseline,
medians +1 to +6 L/min at finish), it meant the well-documented
"collapses minutes after crossing the line, despite looking fine at the
finish" phenomenon (Roberts 1998, cited in this function's own docstring)
could no longer be captured for the majority of participants.

**Fix:** rescaled the pooling magnitude to a fraction of `CO_max` (an
absolute quantity tied to the person's own cardiovascular ceiling) instead
of a fraction of the shrinking `co_res`, removing the self-referential decay
entirely. `simulate_post_finish()` gained a new `co_max_finish` parameter
(sourced from `cvr_ts.states[-1].CO_max`), and the constant was renamed
`PF_POOLING_FRAC_OF_COMAX`. Tested a range (0.04-0.18) for the best
differentiation across starting reserves; settled on **0.06** (provisional,
not literature-derived): modest finishers (+0.2 to +1.0 L/min) tip into
deficit within 0.5-1 min; borderline-healthy finishers (~+3 L/min) sit right
at the edge; clearly healthy finishers (+6 to +10 L/min) stay positive but
visibly reduced. Higher values (e.g. 0.18) drove most finishers straight to
the -5.0 numeric floor within a minute or two -- the same kind of resolution
loss the earlier co_reserve clip removal (see below) was meant to avoid, so
a lower value was chosen deliberately.

**Verified (Falmouth 2015, MET 9.8, N=300):** 30.7% of participants who
finished with a *positive* CO_reserve were subsequently pushed to <=0 by
pooling within the 10-minute window -- this was 0% (mathematically
impossible) before the fix. Overall post-finish EHS-trigger rate
(T_rect>40.5 AND CO_reserve<=0): 55.0%, versus a rate driven almost
entirely by already-negative-at-finish participants before. Median
CO_reserve moved from +1.15 L/min at finish to -0.64 L/min after 10 minutes
-- a moderate, differentiated decline rather than an all-or-nothing jump to
the floor.

**Also tested in this session:** re-ran Falmouth 2003 and 2015 with matched
terrain-corrected weather data and identical MET (9.8) for a clean
comparison (previous test used mismatched terrain data and different MET
per year). Result: 2003 CVS>90%=48.7%, expected/1000=0.37; 2015
CVS>90%=65.0%, expected/1000=48.46 (at a 10:00 local start time -- a
09:00 start for the same 2015 scenario gave 9.75/1000 in an earlier test,
showing the result is highly sensitive to exact start time, itself a
useful finding). The model's ordering (2015 more severe than 2003) now
matches the documented EHI (all heat-illness) ordering (7.57 -> 9.45 per
1000) but not the narrower EHS-specific ordering (6.58 -> 3.93 per 1000,
i.e. reversed) -- plausibly because the CVR/conjunctive criterion tracks
something closer to broad cardiovascular-heat strain than to narrowly
defined clinical heat stroke, which is the endpoint the calibration
reference (Boston) actually targets. Flagged for further investigation,
not resolved in this session.

**Verified:** `python -m py_compile` on the modified file; `verify.py` and
`suite_smoke_test.py` both pass; a dedicated test script exercising the
post-finish pathway directly on real Falmouth 2015 data, and the isolated
numeric behavior of the pooling formula checked outside the full pipeline
before and after the fix.

## [2026-07] Runner's own forward speed added to the wind fed into JOS-3, with direction uncertainty as a Monte Carlo variable

Follow-up to comparing Falmouth 2003 vs. 2015 with matched terrain-corrected
weather and identical MET (see the CVR-rebuild entry below): even after that
rebuild, the model showed 2015 (calm wind, ~1.0 m/s) as 35x more severe than
2003 (windier, ~1.85 m/s) -- the documented EHS-specific literature shows
the opposite direction, with 2003 about 1.7x more severe than 2015.

**Root cause:** `select_met_activity()` computes each activity's forward
speed (`speed_kmh`) but both call sites discarded it (`_`). `jos3_model.v`
was fed ambient wind alone (`max(0.1, wind_1_5m[i])`), with no contribution
from the runner's own motion through the air. Verified this creates a large
day-to-day asymmetry: JOS-3's convective coefficient (Ichihara et al. 1997,
`hc = 15.0 * v^0.62`) differed ~47% between the two race days on ambient
wind alone (22.0 vs. 15.0 W/m2K); once a representative running speed
(9.6 km/h / 2.67 m/s, matching the MET used) is combined with the ambient
wind, that gap narrows to 8-19% depending on assumed wind direction --
consistent with the much smaller (~1.7x) real-world difference between the
two years.

**Why direction can't just be picked:** wind direction is not fetched
anywhere in `Thermopoulos_Data_Engine.py` (only speed magnitude), and
course heading/heading changes along the route are not modelled. Verified
this matters: assuming a pure headwind for both years gives one ranking;
assuming a pure tailwind for both years *reverses* it entirely (2015 becomes
the calmer-feeling year). Falmouth Road Race is confirmed point-to-point
(Woods Hole to Falmouth Heights, not a loop -- so the "a full loop
samples all headings" simplification does not apply either), so there is
no physical averaging happening within a single race that would justify
picking one deterministic combination rule.

**Fix:** `compute_relative_wind(v_ambient, v_running, angle_rad)` added to
`hestia_model.py`, implementing the standard apparent-wind law-of-cosines
formula (sailing/aerodynamics convention; running-specific precedent in
Pugh 1971 and Davies 1980, classic treadmill-in-wind-tunnel studies that
established a runner's own forward motion generates self-induced relative
airflow even in still air). Rather than pick one deterministic angle,
`AdultParticipantProfile` gained a `wind_angle_rad` field sampled
`Uniform[0, 2*pi)` independently per participant in
`generate_base_population()` -- so the *population* mean recovers the
Pythagorean estimate (`sqrt(v_run^2+v_wind^2)`, which is exactly
`E[v_rel^2]` under a uniform-random angle, since `E[cos(angle)]=0`), while
individual participants span the full headwind-to-tailwind range as
population spread rather than a single hidden assumption. Running speed is
derived from each timestep's *current* MET (via the ACSM running-speed
relationship, `speed_m_min = 17.5*(MET-1)`), so a participant who paces
down under thermal/CV strain is also correctly modelled as generating less
self-wind. Single deterministic (non-Monte-Carlo) individual runs use
`angle_rad = pi/2` (cos=0), matching the population mean exactly since
there is no population to sample across. Not extended to the child
simulation path (out of scope: no `wind_angle_rad` field on the child
profile, and this investigation was scoped to adult road-race scenarios).

Also checked, per a supporting literature search: Air speed and direction
affect metabolic and thermoregulatory responses during walking and running
(J Appl Physiol, 2024) found wind-direction effects on metabolic cost fall
within ordinary inter-individual variation below ~4 m/s ambient wind --
both Falmouth race days are in that regime, which supports representing
the direction uncertainty as population spread rather than a resolved
point estimate. The same paper's finding that outdoor running provides a
higher cooling rate than treadmill running "due to the self-generated
wind" independently corroborates the core mechanism this fix restores.
Note: Davies (1980) found tailwind provides only ~35-45% of the benefit an
equivalent headwind costs for aerodynamic drag (which scales with v^2) --
this asymmetry has NOT been separately established for JOS-3's convective
heat transfer coefficient (v^0.62) and is deliberately not applied here;
only the underlying relative-velocity (law-of-cosines) framework is
carried over, not the drag-specific asymmetry magnitude.

**Result (Falmouth 2003 vs. 2015, MET 9.8, N=300, matched terrain-corrected
weather, identical start time):**

| | 2003 | 2015 | Ratio (2015/2003) |
|---|---|---|---|
| Before this fix | 0.39/1000 | 13.88/1000 | 35.6x |
| After this fix | 0.40/1000 | 0.60/1000 | 1.5x |
| Documented (EHS) | 6.58/1000 | 3.93/1000 | 0.60x (2003 higher) |

The direction of the remaining discrepancy (model still shows 2015
slightly more severe; documented data shows 2003 more severe) is not
resolved by this fix and is plausibly attributable to the EHS/EHI
definitional issues and non-overlapping source studies discussed in the
CVR-rebuild entry below, rather than to wind handling specifically --
the magnitude gap that wind handling *was* responsible for has closed
from 35x to 1.5x.

**`COLLAPSE_ENDPOINTS['*']['intercept_kal']` re-derived a fourth time**
(same `intercept_estimation.py`, N=200 single-core feasibility run,
unchanged script logic): ehs -8.927111 -> -8.803572, hospitalisation
-8.464080 -> -8.340358, ehbo -7.360089 -> -7.235395 (small shifts, all in
the same direction and of similar magnitude -- consistent with a modest,
population-wide change rather than a structural one).

**Verified:** `python -m py_compile` on all modified files; `verify.py`
and `suite_smoke_test.py` both pass; a dedicated test script comparing
Falmouth 2003 vs. 2015 under matched conditions, before and after the fix.

## [2026-07] CVR module rebuilt on Lloyd et al. (2022) Eq. 12-31 -- JOS-3's own cardiac_output is no longer the demand signal

Follow-up to the two entries below (roughness fix, clip removal). After both,
Falmouth 2015 (MET 9.8) still showed implausible population-level strain
(~75% CVS index > 90%, ~74% decompensation, ~10% mean collapse risk --
documented real-world EHS incidence for this event is 0.4-0.9%). Investigated
further at the user's request ("dit is een ingrijpende conclusie... zoek naar
wetenschappelijke artikelen die een oplossing kunnen geven").

**Two same-day attempts were tried and reverted -- kept here as documented
dead ends, not deleted, since both critiques were individually valid:**

1. *Intensity-dependent a-vO2diff.* Real a-vO2diff rises with relative
   exercise intensity rather than being fixed at a fitness-scaled near-
   maximal value. True, but mathematically any correction of this kind can
   only *increase* co_demand relative to the old (optimistic) fixed value --
   tested, made results worse (mean collapse risk 10.00% -> 17.34% linear,
   -> 10.96% concave), reverted.

2. *Direct MET-based VO2 (bypassing jos3.cardiac_output entirely).* Looked
   like a breakthrough in testing (expected collapses/1000: 92.7 -> 4.8) but
   was a misdiagnosis. Verified directly: JOS-3's own cardiac_output rises
   ~80% (712 -> 1285 L/h) between tdb=20degC and tdb=38degC at a FIXED MET --
   a large, genuine heat-driven cardiovascular signal (extra skin blood flow
   for cooling) that a MET-only calculation cannot see. The "improvement"
   came from silently deleting that signal -- dangerous for a project whose
   whole point is characterizing heat-driven cardiovascular risk. Reverted.

**Root cause, found via literature search:** Lloyd A, Fiala D, Heyde C,
Havenith G (2022, J Appl Physiol 133:247-261) -- the SAME paper this module
already cited for Eq. 6-11 -- states explicitly in its introduction that
thermophysiological models like JOS-3 derive cardiac output "from the tissue
oxygen needs... and skin blood flow necessary to regulate body temperature,"
and that "neither of these values account for cardiac strains imposed by...
the heat-induced competitive redistribution of blood flow." Their own
measured exercise-heat data (their Fig. 2D) shows CO changes only -3% to
+15% during exercise in heat -- nothing like JOS-3's +80% at fixed effort.
The paper's whole point is that a thermal model's own cardiac output should
NOT be used as the cardiovascular demand signal; their CVR Model computes
CO/SV/HR independently from workload and environmental strain, validated
against real heart-rate data from 101 individuals (R2=0.82-0.97).

**Fix:** `HESTIA_CVR_Module_v2.py`'s `compute_step()` rebuilt to implement
Lloyd 2022's workload-response and heat-strain equations (Eq. 12-13, 22-32)
directly, instead of reading `jos3.cardiac_output` at all:
- Workload fraction from current MET relative to this person's own
  VO2rest (Mifflin-St Jeor, Eq. 4.1/4.2) and VO2max.
- A Cardiac Heat Strain Index (CHSI, additive form, Eq. 22.2) from mean
  body temperature (0.2*Tskin + 0.8*Tcore) and dehydration %.
- CO_max and SV_max **decrease** with heat (-8.3%/degC CHSI); CO_rest and
  SV_rest **increase** (+31.3%/degC and +2.5%/degC respectively) -- these
  are independently fitted, not mirror images, per Lloyd's own regression.
- Final HR/CO/SV via linear interpolation between heat-adjusted rest and
  max, driven by the workload fraction (Eq. 29-31).
`jos3.cardiac_output` is retained only as a legacy fallback for callers with
no MET signal (the standalone demos in this file and in
`HESTIA_CVR_Console.py`). Added `current_met` and `t_skin_mean` fields to
`JOS3Outputs`; `RunnerProfile` gained an optional `pct_vo2max` field (unused
by the final fix, kept from the reverted a-vO2diff attempt since it's
harmless and may be useful later).

**Result (Falmouth 2015, MET 9.8, N=300, single-core feasibility run):**

| Metric | Before this fix | After | Documented |
|---|---|---|---|
| CVS index > 90% | 74.7% | 60.3% | -- |
| % decompensation | 73.7% | 63.7% | -- |
| Mean collapse risk | 9.27% | 0.97% | -- |
| Expected per 1000 | 92.7 | **9.75** | 3.93-9.45 |

Falmouth 2003 (MET 11.0, N=300) gave 0.72/1000 against a documented 6.58/1000
-- still an order of magnitude low, and the 2003-vs-2015 relative ordering
remains reversed versus the real data. Not fully resolved: the 2003 test run
still uses the pre-terrain-fix weather file (z0=0.8; regenerating it needs
live Open-Meteo access not available in the environment this was tested in)
and a different MET (11.0 vs. 9.8) than the 2015 run, so it is not a clean
like-for-like comparison. The underlying physiological signal did move the
correct direction, though (CVS>90%: 74.3% for 2003 vs. 60.3% for 2015 --
2003 correctly reads as more severe at the per-participant level even though
the calibrated collapse probability does not yet fully reflect that).

**`COLLAPSE_ENDPOINTS['*']['intercept_kal']` re-derived a third time** via
`intercept_estimation.py` (unchanged script -- it uses the same z-function
formula regardless of how the CVR module computes co_reserve underneath, so
no changes were needed there). N=200 (single-core feasibility run) once
again -- rerun at production scale (N=10,000-50,000) before treating these
as final. See the updated `notes` fields in `COLLAPSE_ENDPOINTS` for the
full per-endpoint detail.

**Verified:** `python -m py_compile` on all modified files; `verify.py` and
`suite_smoke_test.py` both pass; the CVR module's own standalone demo run
directly and inspected; Falmouth 2003, Falmouth 2015, and the smoke-test
individual/population scenarios all tested end to end with real weather
data before and after each change described above.

**Open for next session:** production-scale recalibration; the 2003-vs-2015
ordering; whether the "additive" CHSI form (used here) or the "synergistic"
form (Eq. 22.1, fit only on young trained male runners) is more appropriate
for a mixed-age recreational population; and the user's planned validation
runs against DtD 2024, Falmouth 2003, and Falmouth 2015.

## [2026-07] Terrain-roughness and coastal-correction fixes (Thermopoulos_Data_Engine.py)

Found while investigating why a Falmouth Road Race 2015 hindcast produced an
implausible collapse-risk result (mean collapse probability ~43%, versus a
documented real-world incidence on the order of 0.4-0.9%).

**Bug 1 — roughness length chosen from population, not terrain.** The
10m->1.5m wind-speed correction (`wind_speed_at_height()`) used
`roughness_z0 = 0.8 if city.get("population", 0) > 0 else 0.1` — a binary
check that has nothing to do with the actual terrain at the race course.
Virtually any named place has `population > 0`, so open-coast courses (e.g.
Falmouth's beachfront Surf Drive) were treated as suburban/built-up terrain
(z0=0.8) regardless of what the ground actually looks like. Combined with an
already-low reference wind speed for the 2015 date (wind_10m ~1.2-1.8 m/s,
versus ~7.4-8.0 m/s for the 2003 comparison run), this crushed the 1.5m wind
to near-zero (~0.3-0.4 m/s), which in turn pushed UTCI well above WBGT
(a 6-8 degC gap, versus 1-3 degC for the 2003 run) because UTCI's underlying
Fiala model is highly sensitive to near-calm forced convection.

**Fix:** replaced the population-based heuristic with an explicit,
per-run terrain choice. New `ROUGHNESS_Z0_TERRAIN` table (six standard
Davenport/Wieringa categories, from open water at z0=0.0002 to dense urban
at z0=1.5) and a new `select_terrain_roughness()` CLI prompt, in the same
style as the existing `get_custom_historical_period()` prompt. Re-running
Falmouth 2015 with "open coast, beach, short grass" (z0=0.03) instead of the
default 0.8 raised the simulated 1.5m wind from ~0.3-0.4 to ~0.8-1.2 m/s
(reduction factor 10m->1.5m improved from ~0.25 to ~0.67) — much closer to
what open terrain should produce.

**Bug 2 — coastal-correction flag shared across datasets via a module
global.** `COASTAL_CORRECTION_ACTIVE` was set as a side effect inside
`fetch_historical_data()` based on that call's own ERA5 grid-distance check,
then read back inside `process_weather_data()` via
`globals().get('COASTAL_CORRECTION_ACTIVE', False)`. Because `main()` fetches
the forecast first but processes all three datasets (forecast, hindcast,
custom-historical) afterward, the forecast — processed first in that later
step — actually read whatever value the *hindcast or custom-historical*
fetch call had most recently left in the global. The forecast uses a
different, higher-resolution model with no equivalent land/sea dilution
problem, so it should never inherit this correction at all, let alone from
an unrelated dataset's fetch call.

**Fix:** `fetch_historical_data()` and `fetch_hourly_forecast()` now both
return `(df, coastal_active)` as an explicit tuple — no shared global. The
forecast fetch always returns `coastal_active=False` (documented reason: its
model doesn't need the correction). `process_weather_data()` takes
`coastal_active` as a required parameter instead of reading a global, and
`roughness_z0` as a required parameter instead of the removed
population-based branch. `main()` unpacks and threads each dataset's own
flag through to its own `process_weather_data()` call.

**Verified:** `python -m py_compile` on the modified file, and a full
`suite_smoke_test.py` run, both pass unchanged.

## [2026-07] Removed an undocumented hard clip on co_reserve / cvs_index (HESTIA_CVR_Module_v2.py)

Found via the same Falmouth 2015 investigation above, after the roughness
fix alone did not fully explain the implausible collapse-risk result.

**The clip:** `co_reserve = max(-4.0, co_max - co_demand)` and
`cvs_index = clip(co_demand / co_max, 0.0, 1.0)` — with no comment, no cited
source, and no reference to any of this project's other explicitly-sourced
constants (Roberts 2010, Rowell 1974, Gonzalez-Alonso 2008). Confirmed by
running the same population through two structurally different scenarios
(different MET, different duration, different terrain roughness): both
independently produced a spike of participants sitting at exactly
`co_reserve = -4.0` and exactly `cvs_index = 1.0` — the signature of a hard
numeric bound, not a physiological distribution.

**Why it mattered beyond the two clipped fields themselves:** the
collapse-risk z-function (`HESTIA_CVR_Console.py` / `hestia_model.py`)
includes the term `W_C * clip(2.0 - co_reserve, 0, None)`, which is
unbounded on the high side. With `co_reserve` clipped at -4.0, this term
topped out at `0.8 * 6.0 = 4.8` for the most extreme participants; without
the clip, a participant with (for example) `co_reserve = -20` contributes
`0.8 * 22 = 17.6` instead — a much larger, and much better differentiated,
contribution for exactly the extreme-cohort tail this whole project is
built to characterize.

**Design intent, per discussion with the suite owner:** `co_reserve` is
deliberately meant to express a continuous "distance from safe" quantity —
not something that is ever directly observed at -4.0 L/min in the real
world (no one survives long enough for that gap to manifest), but a
relative severity ranking that should differentiate a participant who would
theoretically reach -4.5 L/min from one who would reach -20 L/min. The old
clip made those two indistinguishable, which is the opposite of the
intended purpose.

**Fix:** removed both clips.
`co_reserve = co_max - co_demand` (unbounded);
`cvs_index = co_demand / co_max` (unbounded above 1.0, meaningfully so — a
value like 1.4 now legibly means "40% over capacity" instead of being
silently capped at 100%). A small robustness fix was needed alongside this
in `HESTIA_CVR_Console.py`'s `_bar()` helper (used for the console's ASCII
bar charts): it previously assumed its input was always within a bounded
range (true when the clip existed) and could silently overflow the bar
width for very negative inputs; now explicitly clamped to `[0, width]`.

**Consequence — recalibration required.** `COLLAPSE_ENDPOINTS['*']['intercept_kal']`
in `hestia_model.py` was fit (at some earlier point) using the clipped
version of this z-function term. Applying that old intercept to newly
unclipped (and therefore systematically larger) z-values would have made
collapse-risk estimates *more* wrong, not less, until the intercept itself
was re-derived consistently. `intercept_estimation.py` (previously
referenced in code comments but not included in any prior snapshot — now
added) uses the identical z-function formula and was re-run after the clip
removal. Because this sandbox environment has a single CPU core,
`N_POPULATION` was temporarily reduced from the documented production value
(10,000-50,000) to 200 for a feasibility run; it converged, producing:

| Endpoint | Old intercept (clipped) | New intercept (unclipped, N=200) |
|---|---|---|
| ehs | -7.903186 | -8.396342 |
| hospitalisation | -7.438276 | -7.932990 |
| ehbo | -6.324813 | -6.827266 |

All three shifted by a very similar amount (~-0.49 to -0.50), consistent
with a systematic change in the z-function's distribution rather than
noise. These values are marked **PROVISIONAL** in `COLLAPSE_ENDPOINTS` and
should be treated as a placeholder, not a final calibration — rerun
`intercept_estimation.py` at the documented production N on a multi-core
machine and paste the resulting block over these values before using them
for GHOR reporting or any other decision-relevant output.

`intercept_estimation.py` itself needed one fix before it would run against
this snapshot: `_import_engine()` still looked for the pre-rev17 file names
`HESTIA_Data_Engine_CVR_v8`/`_v7`, which no longer exist under those names
(the engine is `hestia_model.py` in this snapshot). Updated to try
`hestia_model` first, falling back to the old names (with a warning) only
for anyone still running a pre-integration snapshot.

**Verified:** `python -m py_compile` on all modified files;
`suite_smoke_test.py` and `verify.py` both pass unchanged after the clip
removal, after the intercept update, and again after the subsequent
translation pass below.

## [2026-07] Full English translation pass

All Python source files in this snapshot — identifiers (function, method,
and field names), comments, docstrings, and printed console/demo output —
have been translated from Dutch to English. This was a mechanical pass with
manual verification, not a content change:

- Cross-file identifiers (e.g. `co_reserve` field names, `decompensating`,
  `link_cvr_to_jos3`, the `COLLAPSE_ENDPOINTS`-adjacent stats-dict keys like
  `hr_peak_p50`/`pct_high_collapse_risk`) were renamed consistently across
  every file that references them (`hestia_model.py`, `HESTIA_CVR_Module_v2.py`,
  `HESTIA_CVR_Console.py`, `intercept_estimation.py`), not just where they
  were first defined, to avoid breaking the shared data contract between
  modules.
- `HESTIA_CVR_Console.py` keeps its existing backward-compatible Dutch
  function-name aliases (`print_cvr_populatie_samenvatting`, etc.) exactly
  as before — this translation pass did not touch that design choice.
- `PROJECT_INSTRUCTIES.md` was translated and renamed to
  `PROJECT_INSTRUCTIONS.md`.
- This changelog (`INTEGRATION_CHANGELOG.md`) was **not** fully translated:
  only this new top section and the entries above it are in English. The
  pre-2026-07 history below the rule is unmodified Dutch. See the
  translation-status note at the very top of this file.

**Verified:** `python -m py_compile` on every `.py` file in the snapshot;
`suite_smoke_test.py` and `verify.py` both pass unchanged; the CVR
console/demo scripts (`HESTIA_CVR_Module_v2.py`, `HESTIA_CVR_Console.py`)
were each run standalone and their output inspected directly.

---

*What changed relative to the previous suite snapshot, why, and what still
needs your review. Everything below this line is verified by actually
running it (compiling, importing, and executing end to end with real
Thermopoulos data), not just read. This is the original, unmodified
pre-2026-07 history, in Dutch — see the translation-status note at the top
of this file.*

## ⚠️ BELANGRIJK — twee bugs gevonden tijdens de eerste echte hindcast (Dam tot Damloop, Amsterdam, 2024-09-22)

Gevonden bij het analyseren van een echte historische hindcast-run, niet bij
routinematige codereview — precies waarom hindcasten waardevol is los van
kalibratievragen.

**Bug 1 — "% Unliveable" gaf ~100% bij volkomen normaal weer.** De
leefbaarheidstabel (`LIVEABILITY_LIMITS`, Vanos et al. 2023) begint pas bij
25°C. `get_liveability_threshold()` zocht via "dichtstbijzijnde punt" en
extrapoleerde daardoor stilzwijgend naar de kóúdste tabelrij bij elke
temperatuur onder 25°C — ongeacht hoe ver onder de 25°C de werkelijke
temperatuur lag. Geverifieerd tegen een echt geval: Amsterdam 2024-09-22,
luchttemperatuur 19,9-23,9°C gedurende de hele wedstrijd, MET~10 gevraagd —
elke tijdstap viel onder 25°C en werd stilzwijgend naar de koudste rij
geklemd (M_max ~5-7), ruim onder de gevraagde MET, met `percent_unliveable`
~100% als gevolg — terwijl de individuele fysiologie (T_rect gemiddeld
39,3°C, collapsrisico gemiddeld 0,15%) volkomen onopvallend was. Dit is een
hittespecifieke leefbaarheidstabel, geen algemene inspanningslimiet — onder
25°C is er domweg geen tabelwaarde die van toepassing hóórt te zijn.

**Fix:** `get_liveability_threshold()` geeft nu een hoge, feitelijk
niet-beperkende waarde (20,0 MET) terug wanneer temp < 25°C, in plaats van te
extrapoleren. Geverifieerd: bij 20°C nu 20,0 (was ~5); bij exact 25°C
ongewijzigd tabelgedrag (5,0). Op de echte Amsterdam-hindcast opnieuw
gedraaid: `percent_unliveable` daalt van ~100% naar 0,5% — in lijn met de
daadwerkelijke fysiologie.

**Bug 2 — verkeerd consolebijschrift.** `HESTIA_CVR_Console.py` toonde altijd
de vaste tekst `"(DtD 2024 admissions: 50/35,000)"` bij de
collapsrisico-kalibratieregel — een restant van een kalibratie die sinds
rev11 is vervangen door Boston Marathon gepoolde data (intercept_kal=-7,903,
target=0,0900% = 9,0/10.000, Breslow et al. 2021 — het getal zelf klopte al,
alleen het bijschrift niet). **Fix:** het bijschrift gebruikt nu het al
bestaande, correcte `active_endpoint_label`-veld (was al in `stats`
beschikbaar, alleen nog niet gebruikt op deze plek) — dit blijft dus
automatisch kloppen als de actieve kalibratie ooit weer verandert, in plaats
van weer een losse, verouderbare tekststring te zijn. Geverifieerd: console
toont nu `"(EHS (klinisch, Boston Marathon gepoold))"`.

**Geverifieerd:** `verify.py` en `suite_smoke_test.py` slagen ongewijzigd.



## ⚠️ BELANGRIJK — pacing reageert nu ook op cardiovasculaire belasting (CO_reserve<0), niet alleen op temperatuur

Op verzoek, na uitgebreide discussie en literatuuronderzoek. HESTIA's bestaande
pacing-mechaniek (`rev13-P4`, Ely et al. 2007) reageerde uitsluitend op T_rect —
er was géén pad waarlangs cardiovasculaire nood (CO_reserve, hartslag) het
gelopen tempo beïnvloedde, ook al is Borg's oorspronkelijke RPE-schaal
letterlijk een lineaire transformatie van hartslag (Borg 1982), en stelt de
pacing-literatuur expliciet dat "perceived exertion is primarily based on
cardiac output." Dit gold ook voor HESTIA's eigen RPE-berekening zelf (puur
MET+temperatuur) — niet in deze wijziging meegenomen, apart te behandelen.

**Hypothese, expliciet zo geformuleerd:** "reserve is reserve" — pacing
treedt op zodra CO_reserve onder nul zakt, niet bij een willekeurig
percentage van CO_max. Dat heeft als voordeel dat er geen aparte,
te-kalibreren drempelwaarde nodig is (zoals wel het geval is aan de
thermische kant, `T_RECT_PACING_THRESHOLD`) — de nuldoorgang zelf is de
drempel.

**Architectuur — belangrijke bevinding vooraf:** de CVR-berekening
(`koppel_cvr_aan_jos3`) draaide tot nu toe als één verzamelde bewerking ná
de hele simulatielus, niet per tijdstap erbinnen. Bij nader onderzoek bleek
`CVRModel.bereken_stap()` zelf al een per-tijdstap-methode te zijn — alleen
de omringende orkestratie was batch-gewijs. Daardoor kon de exact bestaande
Lloyd 2022-formule live, per stap, binnen de hoofdlus worden hergebruikt
(`cvr_model_live.bereken_stap(jos3_snapshot)`), zonder de bestaande batch-
architectuur aan te raken en zonder een tweede, mogelijk-afwijkende
implementatie te bouwen — precies het soort duplicatierisico dat dit
project al een paar keer bij de weerdata parten heeft gespeeld.

**Formule:**
```python
thermal_overshoot = max(0.0, prev_t_rect - T_RECT_PACING_THRESHOLD)
cv_overshoot       = max(0.0, -prev_co_reserve_live)   # alleen onder nul
met_reduction      = kp_ind * thermal_overshoot + kp_ind_cv * cv_overshoot
current_met        = max(1.5, met_initial - met_reduction)
```
Nieuwe individuele parameter `kp_ind_cv` (cardiovasculaire pacing-gain),
gesampeld analoog aan de bestaande thermische `kp_ind`.

**[NIET GEVALIDEERD — expliciet gevlagd, niet verhuld]** voor `K_P_PACING_CV`
bestaat geen directe literatuurbron — gericht gezocht, niet gevonden.
De algemene RPE/pacing-literatuur onderbouwt het **mechanisme** stevig, niet
deze specifieke numerieke gain. Zelfde waarde als de thermische gain gebruikt
als plausibel uitgangspunt, niet omdat de twee gains gelijk verondersteld
worden. Te herzien zodra hindcastdata tegen bekende uitkomsten beschikbaar is
— zelfde openstaande punt als TCF/AUC-kalibratie elders in dit project.

**Geverifieerd, niet alleen op regressie:** bij een deelnemer wiens
CO_reserve van +0,39 naar -0,87 L/min gaat (stap 2→3), toont `current_met`
op exact dat moment een duidelijk sterkere daling (9,669→9,503) dan de
stappen ervoor — en blijft daarna meebewegen met de verder oplopende
tekortstand. Precies het bedoelde gedrag. `verify.py` en
`suite_smoke_test.py` slagen ongewijzigd.

**Niet in deze wijziging meegenomen, bewust:** de RPE-formule zelf aanpassen
naar een hartslag-gebaseerde variant — apart te beoordelen, niet meeliften
op deze pacing-fix.

## ⚠️ BELANGRIJK — drie nieuwe cumulatieve-dosisplots toegevoegd (AUC_klinisch, AUC_thermisch, CO_reserve-tekortdosis)

Op verzoek: visualisatie van het verloop van AUC en van een losse cardiovasculaire
belastingsmaat, naast de al bestaande conjunctieve TCF-dosisplot (plot 8).

**Plot 9 — AUC_klinisch** (Roberts 2007 klinische drempel, T_rect > 40,5°C):
cumulatieve opbouw tijdens de race voor de top 10 op eindwaarde, met de
Roberts-drempel (60°C·min) als referentielijn. Postfinish-bijdrage bestaat
alleen als eindtotaal (geen tussenliggende tijdreeks in de onderliggende
data), daarom getoond als los eindpunt met stippellijn, geen verzonnen curve.

**Plot 10 — AUC_thermisch** (Breslow-achtige diagnostische dosis, T_rect >
39,0°C): zelfde opzet, maar zonder geleende klinische drempel — die bestaat
niet voor deze maat (in de code expliciet "diagnostic" genoemd). In plaats
daarvan toont de plot het populatie-eigen P95 van déze run als relatieve
referentie.

**Plot 11 — CO_reserve-tekortdosis**, `∫ max(0, 2,0 − CO_reserve) dt`,
bewust NIET aan T_rect gekoppeld. Onderbouwing, na literatuuronderzoek op
uitdrukkelijk verzoek:
- Rowell's "competing demands"-principe (huid- en spierdoorbloeding strijden
  om hetzelfde hartminuutvolume-budget) is stevig, primair-bronmateriaal-
  onderbouwd (González-Alonso 2008, J Physiol, doi:10.1113/
  jphysiol.2007.142158, direct terugvoerend op Rowell 1974) — hetzelfde
  mechanisme dat al aan HESTIA's CVR-module (Lloyd et al. 2022) en de
  cardiovascular_disease-PYROX-groep ten grondslag ligt. Dit ondersteunt dat
  cardiovasculaire uitputting kan optreden vanuit de inspanningsvraag alleen,
  vóórdat de thermoregulatoire vraag serieus meespeelt — vooral bij beperkte
  hartreserve.
- Ter aanvulling gevonden: Moran et al. 1998, *Cumulative Heat Strain Index*
  (PubMed 11482547), een gepubliceerd precedent voor het combineren van
  thermische en cardiovasculaire strain in één index — maar met een andere
  wiskundige structuur (product van twee al-opgetelde totalen, niet een
  integraal van het product per moment zoals TCF). Dat onderscheid is
  toegelicht in de docstring; niet vermengd met deze of de bestaande TCF-maat.
- Empirisch bevestigd tegen de Amsterdam-hindcastdata: slechts 1 van de 10
  deelnemers in de CO-tekort-top-10 komt ook voor in de AUC_thermisch-top-10.
  Deelnemer #176 (max T_rect 39,11°C, AUC_thermisch 3,09 — nauwelijks
  thermisch belast) staat wél in de CO-tekort-top-10 (dosis 262,2) — precies
  het soort geval (cardiovasculaire belasting zonder relevante hyperthermie)
  waarvoor deze losse maat is bedoeld, en dat de T_rect-gedreven AUC-maten
  zouden missen.

**Niet klinisch geijkt, net als TCF zelf:** voor de CO-tekortdosis bestaat
geen gepubliceerd actiepunt. Net als bij AUC_thermisch wordt daarom het
populatie-eigen P95 én (op verzoek) P99 van déze run getoond als relatieve
referentie, niet een geleende of verzonnen klinische grens. Te herzien zodra
hindcastdata tegen bekende uitkomsten beschikbaar is (zelfde openstaande punt
als TCF, vgl. HESTIA's eigen consolenotitie: "not a clinical EHS diagnosis;
calibrate against event medical data before converting to EHS probability").

**Implementatie:** CO_reserve-tekortdosis wordt niet in de simulatielus
bijgehouden (anders dan auc_thermisch/auc_klinisch/TCF) — berekend direct in
de plotfunctie uit de al opgeslagen per-tijdstap `co_reserve`-waarden (die
zelf al na de hoofdlus door de CVR-module worden ingevuld), dus geen wijziging
aan de kernsimulatie nodig.

**Eigen fout gevonden en hersteld tijdens het bouwen:** bij het invoegen van
zowel plot 9 als plot 11 raakte de functiedefinitieregel van de daaropvolgende
functie per ongeluk verwijderd (dezelfde soort fout als eerder bij
plot_individual_timeseries) — beide keren meteen opgemerkt via een
compilatiefout en hersteld vóór verder te gaan.

**Geverifieerd:** `verify.py` en `suite_smoke_test.py` slagen. Alle drie
plots numeriek gecontroleerd (niet alleen visueel) tegen de Amsterdam-
hindcastdata.

## Kleine bijwerking — sterker onderscheidende lijnkleuren in het Environmental Thermal Indices-paneel

Op verzoek: de vier lijnen (T_air, WBGT, UTCI, MRT) gebruikten eerder de
standaard matplotlib-kleuren (tab:blue/green/purple/tab:orange), die te dicht
bij elkaar lagen voor comfortabel onderscheid. Vervangen door sterker
verzadigde, onderling contrastrijkere kleuren (`#0057D9` blauw, `#00A650`
groen, `#B300B3` magenta, `#E8580C` oranjerood), met iets dikkere lijnen
(linewidth 2.2). Toegepast op beide instanties (volwassenen- en kinderplot).
Cosmetische wijziging, geen invloed op berekeningen. `verify.py` en
`suite_smoke_test.py` slagen ongewijzigd.

## ⚠️ BELANGRIJK — "Environmental Thermal Indices"-paneel herbouwd: één gedeelde as, vier lijnen (T_air, WBGT, UTCI, MRT), geen twinx meer

Op verzoek, naar aanleiding van de niet-doorgronde UTCI-weergavekwestie
hierboven. In plaats van verder te zoeken naar een oorzaak die zich niet
liet reproduceren, is het paneel zelf vervangen: geen twee gescheiden y-assen
(`ax3`/`ax4 = ax3.twinx()`) meer, maar één gedeelde as in °C — inhoudelijk
correcter (alle vier grootheden zijn temperaturen, dus één schaal is geen
compromis) en het verwijdert meteen de twinx-constructie die vermoedelijk
bij de matplotlib-waarschuwing en de niet-reproduceerbare weergavebug
betrokken was.

**Toegevoegd:** `t_air` (luchttemperatuur) staat nu ook per tijdstap in de
resultatenstructuur van zowel het volwassenen- als het kinderenpad (`temps[i]`
was al beschikbaar in de simulatielus, alleen nog niet opgeslagen). Het
paneel toont nu vier lijnen: T_air, WBGT, UTCI, MRT — in plaats van eerder
twee (UTCI, WBGT) op gescheiden assen.

**Zijbevinding, niet opgelost maar wel afgebakend:** de matplotlib-
waarschuwing ("Axes that are not compatible with tight_layout") blijft
verschijnen, ook nadat de twinx-as volledig is verwijderd — dus die
waarschuwing was kennelijk niet (alleen) aan deze twinx te wijten, en is
losstaand van de UTCI-kwestie. Niet verder onderzocht, want cosmetisch en
buiten de scope van dit verzoek.

**Geverifieerd:** alle vier reeksen tonen daadwerkelijke, onderscheiden
variatie over de tijd (T_air 18,5→20,4°C, WBGT 19,5→21,0°C, UTCI
23,6→26,4°C, MRT 34,8→40,3°C) — numeriek gecontroleerd, niet alleen visueel,
gezien een eerdere pixel-gebaseerde controle in dit traject een fout-
positief opleverde. `verify.py` en `suite_smoke_test.py` slagen ongewijzigd.



## ⚠️ BELANGRIJK — tijdzonebug in de vorige fix zelf gevonden en hersteld (opnieuw via een echte hindcast)

**Deze bug is door mijzelf geïntroduceerd** bij de WBGT/UTCI-precomputed-waarden-fix hierboven — niet een bestaande HESTIA-fout, maar een fout in mijn eigen oplossing ervoor. Gevonden dankzij een scherpe observatie op de omgevingsgrafiek van een echte hindcast-run (Amsterdam, 2024-09-22 10:30): WBGT en UTCI bleven de hele 1,5 uur durende simulatie **volledig vlak** op 19,5°C/23,6°C, terwijl de ruwe uurdata daadwerkelijke variatie liet zien (WBGT 19,5→21,0°C tussen 11:00 en 12:00).

**Oorzaak:** `get_hourly_weather()` berekende `dt` (de epoch-tijdstempel per uur) met `timestamp.timestamp()` op een naïeve (tijdzone-loze) pandas-tijdstempel, rechtstreeks uit het Excel-bestand. Python interpreteert een naïeve tijdstempel dan via de **systeemtijdzone** van de machine waarop de code draait — op deze sandbox-omgeving is dat UTC, wat elke "11:00 lokale tijd"-meting stilzwijgend liet verschuiven naar het epoch-tijdstip van "11:00 UTC" (2 uur vroeger dan de werkelijke CEST-tijd). `interpolate_weather()`'s eigen tijdstappen zijn daarentegen correct opgebouwd uit tijdzone-bewuste Amsterdam-lokale tijdstempels. Deze twee epoch-schalen kwamen dus niet overeen, waardoor `np.interp()` elke voorberekende waarde (ghi/mrt/twb/wbgt/utci) stilzwijgend vastklemde op één enkele uurwaarde in plaats van er daadwerkelijk tussen te interpoleren.

**Waarom de eerdere verificatie dit niet had gevangen:** bij de eerdere Amsterdam 15:30-test kwam de (foutieve) vastgeklemde waarde toevallig overeen met de juiste waarde, omdat de uren 15:00 én 16:00 in die specifieke dataset toevallig allebei exact 21,0°C WBGT hadden — een test die de bug dus niet kon blootleggen. Deze 10:30-run, met wél verschillende opeenvolgende uurwaarden, was de eerste die het echt op de proef stelde.

**Fix:** de naïeve Excel-tijdstempel wordt nu expliciet gelokaliseerd naar de bekende tijdzone van het weerbestand zelf (`self.timezone`, bijv. 'Europe/Amsterdam') vóór de epoch-berekening — correct ongeacht de systeemtijdzone van de machine waarop het draait.

**Geverifieerd:** opnieuw gedraaid tegen exact Koos's run (Amsterdam, 2024-09-22 10:30, 1,6u) — WBGT loopt nu correct op van 19,5°C naar 21,0°C, UTCI van 23,6°C naar 26,4°C, in lijn met de ruwe uurdata. `verify.py` en `suite_smoke_test.py` slagen ongewijzigd.

## ⚠️ BELANGRIJK — WBGT/UTCI-keten nu volledig gesloten op Thermopoulos/Klimatos's eigen cijfers (T_wetbulb, WBGT, UTCI)

Vervolg op de MRT-fix hierboven. Ook al kwamen `tg`/`mrt` nu uit
Thermopoulos's eigen kolommen, bleef er een klein restverschil (~0,2-1,6°C)
tussen de gesimuleerde WBGT en Thermopoulos's eigen WBGT-kolom. Twee
resterende plekken bleken zelf nog te herberekenen in plaats van de
al-aanwezige kolommen te gebruiken:

1. **Natteboltemperatuur (`twb`)** — HESTIA gebruikte altijd de Stull (2011)
   -benadering (`pythermalcomfort.utilities.wet_bulb_tmp`, alleen temp/RH).
   Klimatos kan zijn eigen `T_wetbulb`-kolom ook via een vollediger,
   drukafhankelijk psychrometrisch model genereren
   (`pythermalcomfort.models.wet_bulb_temperature`) — een andere, mogelijk
   preciezere methode.
2. **WBGT en UTCI zelf** — zelfs met correcte `twb`/`tg`/`mrt`-invoer bleef
   HESTIA de uiteindelijke WBGT/UTCI-waarden zelf herberekenen via
   `wbgt()`/`utci()`, in plaats van Thermopoulos's al-berekende `WBGT`- en
   `UTCI`-kolommen rechtstreeks te gebruiken.

**Fix:** `get_hourly_weather()` en `interpolate_weather()` geven nu ook
`T_wetbulb`, `WBGT` en `UTCI` door. Beide simulatiefuncties gebruiken deze nu
rechtstreeks (per tijdstap gecontroleerd, niet alles-of-niets, aangezien deze
onafhankelijk zijn van de zonnestraling/MRT-velden), met terugval op de oude
interne herberekening alleen wanneer een bestand deze kolommen niet heeft.

**Geverifieerd — nu een exacte match, niet alleen "dichterbij":** opnieuw
gedraaid tegen de Amsterdam-hindcast (15:30): gesimuleerde WBGT = **21,0°C**,
UTCI = **24,6°C** — identiek aan Thermopoulos's eigen kolomwaarden voor
hetzelfde tijdstip (was 18,5°C vóór alle fixes, 20,8°C na de MRT/twb-fix
alleen). `verify.py` en `suite_smoke_test.py` slagen ongewijzigd.

**Blijvende kanttekening, expliciet benoemd en niet weggepoetst:** dit
bevestigt dat HESTIA nu **intern consistent** is met Thermopoulos/Klimatos's
eigen berekeningsmethode — niet dat die methode zelf onafhankelijk tegen een
geautoriseerde meting (bijv. KNMI-uurdata) is geverifieerd. Onderzoek naar
onafhankelijke bronnen voor de DtD-2024-weersomstandigheden leverde
bevestiging op van tijdstip, schaal en het "systeembelasting"-mechanisme,
maar geen exacte officiële temperatuurmeting om tot achter de komma tegen te
toetsen.



## ⚠️ BELANGRIJK — HESTIA gebruikt nu Thermopoulos/Klimatos's eigen zonnestraling/MRT (was: eigen, minder betrouwbare herberekening)

Vervolg op de hindcast-bugs hierboven. Bij het natrekken van een verschil
tussen de omgevingsgrafiek en het ruwe weerbestand bleek HESTIA intern haar
eigen, eenvoudigere zonnestralings-/globetemperatuurmodel te gebruiken
(`calculate_solar_radiance`, lineair wolkenverzwakkingsmodel
`cloud_factor = max(0.1, 1 - cloud_cover/100)`), volledig los van de al
aanwezige, waarschijnlijk betrouwbaardere `solar_radiation`/`solar_elevation`/
`T_globe`/`MRT`-kolommen die Thermopoulos/Klimatos al berekent en in hetzelfde
Excel-bestand opslaat.

**Omvang, geverifieerd met echte cijfers:** bij 97% bewolking (Amsterdam,
2024-09-22) gaf HESTIA's interne model GHI = 132 W/m², tegen ~350-400 W/m² in
Thermopoulos's eigen kolom voor exact dezelfde omstandigheden — een factor
2,5-3x te laag. Dit is geen alleen-weergave-probleem: `mrts[i]` wordt
rechtstreeks aan `jos3_model.tr` toegekend, dus dit beïnvloedde de
daadwerkelijk gesimuleerde T_rect op bewolkte-maar-nog-lichtrijke dagen, in
elke eerdere daytime-simulatie in dit project.

**Fix:** `ThermopoulosData.get_hourly_weather()` en `interpolate_weather()`
geven nu ook de al-berekende `solar_radiation`/`solar_elevation`/`T_globe`/
`MRT`-kolommen door. `calculate_indices_jos3_adult()` (beide instanties,
volwassenen- en kinderpad) gebruikt deze nu rechtstreeks in plaats van ze zelf
te herberekenen — met terugval op de oude interne berekening alleen wanneer
een bestand deze kolommen niet heeft (bijv. het synthetische smoke-testbestand,
dat wél `solar_radiation` maar geen `T_globe`/`MRT`/`solar_elevation` heeft;
de controle is daarom bewust op **alle vier** velden tegelijk, niet alleen
`ghi`, anders zou zo'n gedeeltelijk bestand alsnog `None` doorgeven aan JOS-3
— precies de regressie die de eerste versie van deze fix veroorzaakte en die
`suite_smoke_test.py` meteen ving).

**Niet aangepast, bewust:** `analyze_met_thresholds()` en
`calculate_and_export_wbgt()` hebben dezelfde onderliggende herberekening,
maar zijn niet bereikbaar vanuit `run_hestia.py`/de CLI — buiten scope
gelaten, net als de kinderadapter eerder.

**Geverifieerd:** opnieuw gedraaid tegen de Amsterdam-hindcast (15:30) — de
gesimuleerde WBGT gaat van 18,5°C (bug) naar 19,5°C, dichter bij Thermopoulos's
eigen 21,0-22,4°C. Resterend klein verschil is vermoedelijk een legitiem
formuleverschil (bijv. in de natteboltemperatuur-berekening), geen bug meer.
`verify.py` en `suite_smoke_test.py` slagen (na de hierboven beschreven
tweede fix voor de synthetische-testbestand-regressie).

## ⚠️ BELANGRIJK — PYROX's `medication_impaired`-groep herijkt (derde diepgaande check)

Op verzoek stap voor stap door de resterende groepen, geprioriteerd op
relevantie (volgend op cardiovascular_disease, vanwege de link met HESTIA's
NSAID-modifier).

**Belangrijkste bevinding — heterogeniteit, geen uniform effect:** de beste
beschikbare evidence (systematische review + meta-analyse van
medicatie-effecten op kerntemperatuur tijdens hittestress, eClinicalMedicine/
Lancet 2024, doi:10.1016/j.eclinm.2024.102847) laat zien dat veel medicatie
die publieke gezondheidsrichtlijnen (CDC, WHO) gezamenlijk als "hitterisico"
bestempelen — diuretica, antidepressiva, antipsychotica, anxiolytica — **geen
aangetoond effect op kerntemperatuur** heeft tijdens hittestress, ondanks dat
ze routinematig in één adem worden genoemd. Wél aangetoond, gekwantificeerd:
sterke anticholinergica (+0,42°C bij ≥30°C, 95%-BI 0,04-0,79, via verminderd
zweten), niet-selectieve bètablokkers (+0,11°C, 95%-BI 0,02-0,19, via
verminderde vaatverwijding), en anti-parkinsonmiddelen (+0,13°C). Dat
betekent niet dat diuretica/antipsychotica veilig zijn — ze kunnen het risico
via ándere routes verhogen (uitdroging, sedatie-gedreven verminderd
hitte-vermijdend gedrag) — maar dat zijn andere mechanismen dan directe
thermoregulatoire verstoring, en PYROX's ene `medication_impaired`-categorie
kan dat onderscheid niet maken.

**Gevlagd, niet doorgevoerd:** deze ene groep zet medicatie met een bewezen
thermoregulatoir mechanisme (anticholinergica, niet-selectieve bètablokkers)
op één lijn met medicatie met een onbewezen-maar-plausibel ander-mechanisme-
risico (diuretica, antipsychotica). Het splitsen in aparte groepen zou de
evidence beter recht doen — dat is een structurele wijziging die verder gaat
dan een enkele-groep-herijking, jouw beslissing.

**Kalibratie:** `recovery_threshold` licht verlaagd (0,60 → 0,55), verankerd
aan het sterke-anticholinergica-effect als behoedzame referentie voor een
heterogene categorie. `capacity`, `base_recovery_rate` en
`strain_suppression_strength` **ongewijzigd** — geen directe evidence
gevonden voor acclimatisatiecapaciteit of dag-tot-dag-herstel specifiek bij
medicatiegebruik.

**Geverifieerd:** `verify.py` en `suite_smoke_test.py` slagen ongewijzigd.

## ⚠️ BELANGRIJK — laatste drie PYROX-groepen gecontroleerd: `outdoor_workers`, `indoor_workers`, `middle_aged_45_65` — HELE 23-GROEPEN-REEKS NU AFGEROND

**`outdoor_workers`:** de beroepsmatige hittesterftecijfers zijn schokkend —
landarbeiders 35x zo hoog sterfterisico als de algemene bevolking (NEJM 2023,
doi:10.1056/NEJMp2307850); bouwvakkers 13x (95%-BI 10,1-16,7); landbouw/
bosbouw/visserij 35x (95%-BI 26,3-47,0) t.o.v. het gemiddelde van alle
andere sectoren (Amerikaanse OSHA-regelgeving, Gubernot et al. 2015). **Maar
cruciaal:** deze vermenigvuldigers worden overwegend gedreven door
**niet-geacclimatiseerde, onvoldoende beschermde** arbeiders — vaak
migranten/etnische minderheden zonder waterpauzes/schaduw (PMC11930879).
PYROX's groep is expliciet gelabeld "(heat-exposed, **acclimatized**)" — een
smallere, beter beschermde referentiepopulatie dan de ruwe
beroepsstatistieken. Die cijfers rechtstreeks toepassen zou een
populatie-mismatch zijn. **Geen getalswijziging** — wel expliciet gevlagd
dat een toekomstige groep voor de bredere, gemengde buitenwerkerspopulatie
(inclusief niet-geacclimatiseerden) een veel ernstigere, aparte kalibratie
zou verdienen op basis van deze cijfers.

**`indoor_workers`:** niet-gekoelde binnenwerkplekken (magazijnen, bakkerijen,
gieterijen) zijn een erkende, aparte risicocategorie (NEJM 2023), maar er is
geen specifieke kwantitatieve vermenigvuldiger gevonden los van de
buitenwerkersstatistieken. Bestaande positionering onder outdoor_workers
blijft fysiologisch redelijk (geen acclimatisatievoordeel van herhaalde
blootstelling), maar dit is een aannemelijkheidsoordeel, geen
literatuur-afgeleide correctie. **Geen getalswijziging.**

**`middle_aged_45_65`:** de literatuur raamt risico consequent oplopend met
leeftijd, maar biedt geen aparte, specifiek-gekwantificeerde
middelbare-leeftijd-vermenigvuldiger los van die algemene leeftijdsgradiënt
— de meeste studies groeperen "werkende leeftijd" samen of vergelijken
alleen tegen "ouderen" specifiek. Deze groep blijft een redelijke, monotone
interpolatie tussen de paper-gevalideerde jong-volwassene- en
ouderen-prototypes. **Geen getalswijziging, geen uitdagende bevinding
gevonden.**

**Geverifieerd:** `verify.py` (23/23 groepen) en `suite_smoke_test.py`
slagen ongewijzigd.

---

**STATUS: alle 23 PYROX-groepen nu behandeld** (3 paper-gevalideerde
prototypes ongemoeid gelaten zoals het hoort; 20 geëxtrapoleerde groepen elk
gecontroleerd tegen literatuur, in 14 aparte checks). Uitkomsten: 8 groepen
structureel of numeriek gecorrigeerd (obesity, cardiovascular_disease,
medication_impaired, unacclimatized_travelers, pregnant_t1/t2/t3 [structureel],
children_0_6/6_10, youth_10_18, physical_disabilities), 5 groepen bevestigd
zonder noemenswaardige wijziging (severe_mental_illness, dementia,
chronic_comorbidities, indoor_workers, middle_aged_45_65), en de
atleten-/outdoor_workers-tier gedocumenteerd met expliciete gebruiksvlaggen.
Elke wijziging is getest op het bedoelde gedrag, niet alleen op regressie;
elke bewering heeft een DOI of directe bronvermelding.



**Laatste check in deze reeks, met een bewust lichtere aanpak.** De
atleten-/werkersgroepen (`endurance_athletes`, `elite_athletes`,
`recreational_athletes`) vertegenwoordigen de gezonde/veerkrachtige kant van
het spectrum — minder beleidskritisch dan de kwetsbare groepen hiervoor.
Gecontroleerd, niet elk apart diepgaand onderzocht.

**Bevestigend:** de incidentie van inspanningsgebonden hitteberoerte bij
topsport is empirisch laag (PMC9826288, 2022) — consistent met deze zeer
hoge capaciteitswaarden (0,95-1,00).

**Twee reële, smalle nuances, geen getalswijziging:**
1. **Kortere, intensievere wedstrijden (bijv. 10km) dragen een hóger risico
   dan marathons** — lopers houden een hogere relatieve intensiteit langer
   vol bij kortere afstanden. Dit is geen correctie op deze groep zelf, maar
   een waarschuwing over welke intensiteit je eraan koppelt — sluit direct
   aan bij de eerdere `met_value`-fix in HESTIA.
2. **Bij topsporters kan extreme motivatie de normale beschermende
   gedragsrespons op oververhitting overstemmen** — ze negeren
   waarschuwingssignalen die een recreatieve sporter wél zou opvolgen
   (PMC9826288). Dit is gedragsmatig, geen capaciteitstekort — PYROX's
   knoppen kunnen dit niet vertegenwoordigen, net als bij eerdere
   gedragsmatige bevindingen. Terzijde: ~85% van de instortingen bij
   duursportevenementen gebeurt **na** de finish, meestal onschuldig
   (posturale hypotensie), een minderheid hitteberoerte — een onafhankelijke
   bevestiging van waarom HESTIA een aparte post-finish-module heeft.

**Bewust niet apart diepgaand behandeld in deze reeks:** `outdoor_workers`,
`indoor_workers`, `middle_aged_45_65` blijven staan zoals ze waren —
geëxtrapoleerd, niet apart tegen literatuur gecontroleerd. Verdienen ieder
een eigen sessie zoals de voorgaande tien, mocht je daar ooit behoefte aan
hebben.

**Status van de hele reeks (11 checks, 10 van de 23 groepen behandeld):**
`obesity`, `cardiovascular_disease`, `medication_impaired`,
`unacclimatized_travelers`, `pregnant_t1/t2/t3` (structureel herijkt),
`children_0_6/6_10`, `youth_10_18`, `severe_mental_illness` (bevestigd),
`dementia` (bevestigd), `chronic_comorbidities` (bevestigd),
`physical_disabilities` — elk met specifieke bronvermelding, geverifieerd
gedrag, en expliciete vlaggen waar het bewijs onzeker of het raamwerk
ontoereikend is. `verify.py` (23/23 groepen) en `suite_smoke_test.py`
slagen ongewijzigd door de hele reeks heen.



## ⚠️ BELANGRIJK — PYROX's `physical_disabilities`-groep herijkt (tiende diepgaande check) — zelfde heterogeniteitsprobleem als medication_impaired

**Dwarslaesie (SCI) blijkt een scherpe ernst-gradiënt naar laesiehoogte te
hebben die deze ene groep niet kan vertegenwoordigen.** Bij een hoge
(boven T6) complete dwarslaesie kan de hypothalamus geen signalen meer
ontvangen óf versturen onder het laesieniveau — geen zweten, geen
vaatverwijding, geen hartslagverhoging om bloed tegelijk naar huid én
spieren te sturen onder de laesie, verlies van ~50% van het
lichaamsoppervlak voor thermoregulatie (Mayo Clinic Proceedings klassieke
review; systematische review in PMC8049141: "hoe hoger het laesieniveau,
hoe meer het thermoregulatiesysteem is aangetast... personen met een hoog
laesieniveau, met name tetraplegie, bereikten een hogere kern- en
huidtemperatuur bij een lager zweettempo"). Dit is een van de meest
ernstige, mechanistisch direct aangetoonde stoornissen uit deze hele reeks
— vergelijkbaar met of erger dan dementie's hypothalame-schademechanisme,
voor hoge laesies specifiek. Maar "physical_disabilities" omvat óók
aandoeningen met volledig normale autonome/thermoregulatoire functie en
alleen verminderde mobiliteit/hitte-vermijdend gedrag — waar deze ernst
helemaal niet geldt.

**Gevlagd, net als bij medication_impaired:** deze ene groep zet een
genuine ernstige, goed gekarakteriseerde deelgroep (hoge dwarslaesie en
vergelijkbare autonome aandoeningen) op één lijn met veel mildere gevallen.
Splitsen in minstens twee groepen (autonoom/thermoregulatoir aangetast vs.
alleen mobiliteitsbeperking) zou de evidence beter recht doen — een
structurele wijziging die verder gaat dan een enkele-groep-herijking, jouw
beslissing.

**Kalibratie:** `recovery_threshold` verlaagd (0,75 → 0,65), verankerd aan
de ernstigere, beter-onderbouwde kant van het spectrum — een categorie
bedoeld om risico te signaleren moet haar kwetsbaarste leden niet
wegmiddelen. `capacity` ongewijzigd — de SCI-evidence beschrijft acuut
falen van specifieke effectormechanismen, geen capaciteitsplafond-concept,
en er is geen schoon kwantitatief ankerpunt gevonden voor die knop.

**Geverifieerd:** `verify.py` (23/23 groepen) en `suite_smoke_test.py`
slagen ongewijzigd.

## ⚠️ BELANGRIJK — PYROX's `chronic_comorbidities`-groep gecontroleerd (negende diepgaande check) — BEVESTIGD, met precieze dosis-responsdata

Derde check op rij die vooral bevestigt in plaats van corrigeert — en deze
keer met een verrassend nette, gekwantificeerde dosis-responsrelatie.

**Gevonden:** een bevolkingsregister uit Queensland, Australië
(spoedopnames 2004-2016) vond voor mensen met 0, 1, 2, of ≥3 van vijf
chronische aandoeningen (hart-vaatziekte, diabetes, psychische stoornis,
astma/COPD, chronische nierziekte) odds ratio's voor hittegerelateerde
spoedopname van **1,00 / 1,06 / 1,08 / 1,13** — een nette, monotone
dosis-responsrelatie waarbij vooral het **aantal** aandoeningen telt, niet
zozeer welke specifieke aandoening (doi:10.1016/j.envres.2024...). Dit
bescheiden, hitte-specifieke stapelingseffect moet niet verward worden met de
veel grotere dosis-responsrelaties uit de algemene (alle-oorzaken,
meerjarige) multimorbiditeitsliteratuur (Charlson Comorbidity Index-studies
met hazard ratio's van 3-12+) — die meten een ander eindpunt over een andere
tijdschaal en zijn niet direct overdraagbaar naar een enkel-hittegebeurtenis-
belastingsmodel.

**Check tegen de bestaande kalibratie:** deze groep's capaciteit (0,35) ligt
~12,5% onder cardiovascular_disease's herijkte capaciteit (0,40); de
hersteldrempel (0,65) ligt ~7% onder cardiovascular_disease's (0,70). Beide
liggen in dezelfde orde van grootte als het gevonden ~6-13%
hitte-specifieke stapelingseffect — de bestaande kalibratie komt dus al
redelijk overeen met wat direct bewijs ondersteunt voor het *extra* effect
van meerdere aandoeningen bovenop een enkele-aandoening-basislijn.

**Geen inhoudelijke getalswijziging** — gedocumenteerd in plaats van
gecorrigeerd, net als bij severe_mental_illness en dementia hiervoor.

**Geverifieerd:** `verify.py` (23/23 groepen) en `suite_smoke_test.py`
slagen ongewijzigd.



## ⚠️ BELANGRIJK — PYROX's `dementia`-groep gecontroleerd (achtste diepgaande check) — BEVESTIGD, met nóg directer bewijs dan severe_mental_illness

Zelfde uitkomst als de vorige check: bevestiging, geen correctie. Maar hier
is het mechanisme **directer fysiologisch**, niet alleen correlationeel/
multifactorieel.

**Directe structurele schade:** dementie, met name Alzheimer, kan de
**hypothalamus zelf beschadigen** — het lichaamseigen thermostaat — waardoor
zowel detectie als respons op temperatuurveranderingen echt fysiologisch
verstoord raakt, niet alleen een bewustzijns-/gedragstekort. Meerdere studies
melden een **verhoogde basale kerntemperatuur** bij Alzheimerpatiënten,
mogelijk door verhoogde cytokine-expressie en neuro-inflammatie in de
hersenen (PMC9898200). Een populatiestudie naar hittegolfsterfte bij
dementiepatiënten van 60+ in China (2013-2020) vond significant verhoogde
sterfte op hittegolfdagen t.o.v. niet-hittegolfdagen, binnen-persoon
vergeleken (PMC11490898). Een rattenmodel voor hitteberoerte toonde direct
hippocampale neuronale schade, degeneratie en amyloïde-plaquevorming aan na
hitteberoerte — histopathologisch bewijs dat de epidemiologische
dementiebevinding onderbouwt (doi:10.1186/s13195-024-01515-7).

**Medicatie, apart mechanisme:** cholinesteraseremmers (standaard
dementiemedicatie, zoals donepezil) verminderen het zweten — een ander,
goed gedocumenteerd mechanisme dan de antipsychotica-effecten die al in
`medication_impaired` zitten (enige overlap te verwachten, aangezien veel
dementiepatiënten met gedragssymptomen beide medicatieklassen krijgen
voorgeschreven).

**Bijkomend, minder goed vertegenwoordigbaar:** communicatie-/gedragstekorten
(herkennen geen dorst, vergeten te drinken, begrijpen niet dat ze kleding
moeten uittrekken of schaduw moeten zoeken; hittegerelateerde verwardheid kan
worden verward met basale dementiesymptomen, wat interventie vertraagt) — net
als bij `severe_mental_illness` iets dat PYROX's vier knoppen niet kunnen
vertegenwoordigen, maar hier bovenop een al goed onderbouwd direct
fysiologisch mechanisme, niet als voornaamste drijver.

**Geen getalswijziging** buiten documentatie: dit blijft de enige meest
ernstige groep in het hele bestand van 23 (zelfs onder de paper-gevalideerde
very_elderly_85plus-prototype op 0,25) — en het hier gevonden bewijs is zo
mogelijk nóg directer/robuuster dan bij severe_mental_illness, wat die
positionering eerder ondersteunt dan uitdaagt.

**Geverifieerd:** `verify.py` (23/23 groepen) en `suite_smoke_test.py`
slagen ongewijzigd.



## ⚠️ BELANGRIJK — PYROX's `severe_mental_illness`-groep gecontroleerd (zevende diepgaande check) — BEVESTIGD, niet gecorrigeerd

Anders dan de vorige zes checks: deze bevestigt grotendeels de bestaande,
zware positionering in plaats van 'm bij te stellen. Ook een waardevolle
uitkomst — niet elke check hoeft tot een wijziging te leiden.

**Sterk, goed gekwantificeerd bewijs:** psychiatrische patiënten hadden
**dubbel zoveel kans om te overlijden** tijdens een hittegolf t.o.v. de
algemene bevolking (Bark's analyse van het New York State psychiatrisch
ziekenhuis, 1950-1984, besproken in PMC6068666) — cruciaal: dit verhoogde
risico bestond **al vóór grootschalig antipsychoticagebruik** (voor de
jaren '60), dus er is een reëel, medicatie-onafhankelijk ziekte-component.
In het recente (2021) extreme hitte-evenement in Brits-Columbia (1.649
doden in 8 dagen) stond schizofrenie **bovenaan** de lijst van aandoeningen
geassocieerd met overlijden; antipsychoticagebruik was daarbovenop
**onafhankelijk** geassocieerd met 2,43x verhoogde sterftekans, ook na
correctie voor ziekte-ernst en comorbiditeit (Lee et al. 2025, Scientific
Reports, doi:10.1038/s41598-025-17591-0).

**Mechanisme, multifactorieel en deels onbegrepen:** centrale/hypothalame en
autonome disfunctie door de aandoening zelf; medicatie-effecten (al apart
gemodelleerd in `medication_impaired` — enige overlap is te verwachten,
aangezien de geciteerde sterftestudies échte populaties meten die doorgaans
zowel ziek als medicamenteus behandeld zijn, niet een geïsoleerd
"alleen-ziekte"-geval); en een **apart gedragsmatig/sociaal spoor** —
sociale isolatie (niemand die het welzijn in de gaten houdt tijdens een
hittegolf) en verminderd risicobesef. Dat laatste is **geen fysiologisch
capaciteitstekort** en kan door geen van PYROX's vier beschermingsknoppen
worden vertegenwoordigd — een structurele beperking van het raamwerk voor
juist deze groep, niet iets dat een parameterwijziging kan oplossen.

**Geen getalswijziging** buiten documentatie: de bestaande ernst (al een van
de laagste in het hele bestand) is goed onderbouwd door direct, gekwantificeerd
bewijs, in plaats van de ongevalideerde extrapolatie die het eerder leek.
**Gevlagd:** gezien het onvertegenwoordigde sociale-isolatie-spoor moet de
uitkomst van deze groep worden gelezen als een waarschijnlijke
**onderschatting** voor sociaal geïsoleerde individuen specifiek, niet als
een overschatting.

**Geverifieerd:** `verify.py` (23/23 groepen) en `suite_smoke_test.py`
slagen ongewijzigd.



## ⚠️ BELANGRIJK — PYROX's kinder-/jeugdgroepen herijkt (zesde diepgaande check)

**Opnieuw een mythe-doorprikkende bevinding, met één belangrijke uitzondering
die júist overeind blijft.**

Voor schoolkinderen en tieners is het traditionele beeld (hoge oppervlakte-
massa-verhouding, lager zweettempo → slechter bestand tegen hitte) stevig
herzien. Directe vergelijkende studies (Rowland et al., fietsen in 88°F-hitte,
geciteerd in Falk & Dotan 2008, doi:10.1139/H07-185) vonden **geen verschil**
tussen jongens en volwassen mannen. Verklarend mechanisme: het lagere
zweettempo van kinderen wordt gecompenseerd door minder lichaamsmassa om te
koelen en efficiëntere zweetverdamping. Bij inspanning geschaald naar
lichaamsgrootte is de warmteproductie per kg verwacht gelijk tussen kinderen
en volwassenen (Rowland 2008, J Appl Physiol, doi:10.1152/japplphysiol.01196.2007)
— consistent met HESTIA/PYROX's eigen MET-gebaseerde (per-kg) intensiteitsschaal.
Cruciaal: **"geen epidemiologische data tonen hogere hitteletsel-cijfers bij
kinderen, zelfs niet tijdens hittegolven"** (Falk & Dotan). De Amerikaanse
kinderartsenvereniging (AAP) heeft haar richtlijnen hierop al bijgesteld
(2011).

**Wat wél overeind blijft, en waarom `children_6_10` behoedzamer is bijgesteld
dan `youth_10_18`:** de hogere oppervlakte-massa-verhouding wordt juist een
nadeel in extreme hitte (omgeving warmer dan huid — sneller warmte-opname in
plaats van -afgifte), en jongere kinderen reguleren hun drinkgedrag slechter
(vrijwillige onderdrinking, sterker bij jongere leeftijd). Trager
acclimatiseren blijft ook gewoon gelden — de bestaande geheugenkernels
(MEMORY_FLAT/MILD_LINEAR) zijn daarom ongewijzigd gelaten.

**`children_0_6` is bewust veel behoedzamer bijgesteld dan de andere twee.**
Baby's en jonge kinderen zijn wél degelijk aantoonbaar kwetsbaarder voor
hittegerelateerde morbiditeit/mortaliteit (van de Kamp & Daanen 2025, VU
Amsterdam, doi:10.3390/ijerph22081265) — maar die review erkent expliciet dat
onduidelijk blijft of dat komt door **onrijpe fysiologie** of door
**afhankelijkheid van verzorgers** (kan zelf geen kleding uittrekken, water
halen, of een hete omgeving verlaten). Dat laatste is geen capaciteitstekort
dat PYROX's regeltechnische raamwerk kan vertegenwoordigen. Vandaar een kleine,
behoedzame bijstelling in plaats van de forsere correctie bij de andere twee
groepen — en een expliciete vlag dat deze groep zou moeten worden herzien
zodra event-specifieke leeftijdsdata beschikbaar zijn (PYROX modelleert
actieve evenementdeelnemers, die in deze leeftijdsband eerder aan de oudere,
zelfstandiger kant zitten dan echte zuigelingen).

**Kalibratie:**
```
                              was      wordt
youth_10_18       capacity    0,65  →  0,72
                  threshold   1,20  →  1,40
children_6_10     capacity    0,45  →  0,58
                  threshold   0,80  →  1,00
children_0_6      capacity    0,32  →  0,38   (kleine, behoedzame stap)
                  threshold   0,65  →  0,72
```
recovery_rate en suppression_strength **ongewijzigd** bij alle drie — geen
directe evidence gevonden voor die knoppen specifiek.

**Geverifieerd:** gerichte simulatie (14-daagse belasting, load=2,0) bevestigt
de bedoelde volgorde — jeugd (10-18) blijft volledig veilig zoals een gezonde
volwassene; kinderen 6-10 tonen kwetsbaarheid maar duidelijk later dan
voorheen (caution dag 5 i.p.v. gelijk met ouderen); kinderen 0-6 blijven het
snelst kwetsbaar van de drie, dicht bij het tempo van gezonde ouderen. `verify.py`
(23/23 groepen) en `suite_smoke_test.py` slagen ongewijzigd.

## ⚠️ BELANGRIJK — PYROX's zwangerschapstrimester-groepen structureel herijkt (vijfde diepgaande check, GEEN routinematige kalibratie)

Anders dan de vorige vier: geen kalibratie van getallen binnen dezelfde
structuur, maar een **herinterpretatie van wat de groep in PYROX's raamwerk
voorstelt**, op jouw expliciete instructie na het voorleggen van de bevinding.

**Wat er mis was met de oude aanname:** de drie trimesters stonden gekalibreerd
als een monotoon verslechterende cumulatieve-capaciteitsreeks (T1 0,42 → T2
0,35 → T3 0,28), dezelfde as als bijvoorbeeld fragiele ouderen. Recente,
goed-gecontroleerde klimaatkamerstudies (Sydney-onderzoek, Sports Medicine
2021, doi:10.1007/s40279-021-01504-y; "Cool Mama" 2024,
doi:10.1016/j.jesf.2024.08.001) vinden **geen verhoogde kerntemperatuur** bij
zwangere vrouwen (2e/3e trimester) t.o.v. niet-zwangere controles, zelfs niet
bij hoge-intensiteit hardlopen tot 35 weken — zwangerschapsfysiologie
(meer bloedvolume, eerder zweten) lijkt de warmteafgifte eerder te
ondersteunen dan te verzwakken. Het echte risico is **per trimester
mechanistisch verschillend**, niet één oplopende ernstschaal:
- **T1:** geen aangetoond capaciteitsverlies, maar een **acuut teratogeen
  drempeleffect** tijdens de organogenese — kerntemperatuur ≥39-39,5°C is
  geassocieerd met neuralebuisdefecten en hartafwijkingen (Ravanelli et al.
  2019, Br J Sports Med, systematische review, doi:10.1136/bjsports-2017-098914).
  Eén blootstelling tijdens een gevoelig ontwikkelingsvenster, geen
  meerdaagse opbouw.
- **T2/T3:** wél een reëel, maar ánder, cumulatief mechanisme — hittestress
  kan oxytocine/prostaglandine-F2α vrijmaken (trigger voor vroeggeboorte) en
  de uteroplacentaire doorbloeding verminderen (laag geboortegewicht).
  Grootschalig epidemiologisch onderzoek (2 miljoen+ geboortes, Californië)
  vond verhoogd laag-geboortegewicht-risico bij hitte in T2/T3, maar juist
  een omgekeerd verband tussen T1-hitte en vroeggeboorte (PMC6910775) — het
  mechanisme is dus echt trimester-specifiek, niet "hetzelfde probleem als T1
  maar erger".

**Structurele fix, niet alleen andere getallen:** PYROX heeft al een
mechanisme voor "snel een kritiek punt bereiken" —
`critical_strain = 1/strain_suppression_strength`. Voor T1 is
`strain_suppression_strength` fors verhoogd (0,50 → 0,90), wat de kritieke
drempel laat instorten van 2,0 naar ~1,11 — één significante acute
blootstelling raakt nu snel het "gevaar"-punt, in plaats van dat er dagen
cumulatieve opbouw nodig zijn. Tegelijk zijn T1's dagelijkse
capaciteit/hersteldrempel/hersteltempo teruggezet naar gezonde-volwassene-
niveau (geen aangetoond dagelijks capaciteitsverlies). T2/T3 kregen fors
hogere capaciteit/drempel (dichter bij gezond), met de kritieke drempel dicht
bij normaal gelaten — hun risico past wél bij een cumulatief-
blootstellingsraamwerk, in tegenstelling tot T1's acute drempel.

**Kalibratie:**
```
                              was              wordt
T1  capacity                  0,42      →       0,70
    recovery_threshold        0,80      →       1,20
    recovery_rate             0,25      →       0,28
    suppression_strength      0,50      →       0,90   (critical: 2,0 → 1,11)
T2  capacity                  0,35      →       0,65
    recovery_threshold        0,70      →       1,00
    recovery_rate             0,20      →       0,25
    suppression_strength      0,52      →       0,50   (critical: ~1,92 → 2,00)
T3  capacity                  0,28      →       0,55
    recovery_threshold        0,50      →       0,75
    recovery_rate             0,18      →       0,22
    suppression_strength      0,55      →       0,53   (critical: 1,82 → 1,89)
```

**Geverifieerd, expliciet op het nieuwe gedrag getest, niet alleen op
regressie:**
- Acute test (1 hete dag, load=3,0, daarna mild): T1 bereikt `danger_day=1`
  — bevestigt het acute-drempel-gedrag werkt.
- Aanhoudende 14-daagse belasting (load=2,0): T1 blijft volledig veilig
  (peak_strain=0,100, zoals een gezonde volwassene) — bevestigt dat T1 niet
  ten onrechte kwetsbaar wordt voor cumulatieve blootstelling. T2 toont
  milde, latere kwetsbaarheid (caution dag 6, danger dag 8); T3 sneller
  (caution dag 2, danger dag 3, vergelijkbaar tempo met gezonde ouderen) —
  precies de aflopende-maar-niet-extreme volgorde die het bewijs
  ondersteunt.
- `verify.py` (alle 23 groepen, alle invarianten) en `suite_smoke_test.py`
  slagen ongewijzigd.

## ⚠️ BELANGRIJK — PYROX's `unacclimatized_travelers`-groep herijkt (vierde diepgaande check)

**Ander type correctie dan de vorige drie:** obesitas, cardiovasculaire ziekte
en medicatiegebruik zijn permanente verlagingen van het beschermingsplafond.
Niet-geacclimatiseerd zijn is een **tijdelijke, volledig herstelbare** staat —
de consistente bevinding over CDC, arbeidshygiëne- en sportgeneeskunde-bronnen
is dat hitteacclimatisatie doorgaans binnen 7-14 dagen voltooid is
(cardiovasculaire aanpassingen al binnen de eerste week; zweetaanpassingen
hebben de volle 10-14 dagen nodig), en uitkomt op **hetzelfde normale
plafond** als ieder ander met vergelijkbare fitheid — niet een permanent
lager plafond (CDC NIOSH; Racinais et al. 2015 consensusverklaring over
trainen/wedstrijden in de hitte, doi:10.1007/s40279-015-0343-6, die
niet-geacclimatiseerde deelnemers aan massa-evenementen — precies dit
project se toepassing — expliciet noemt als groep waar organisatoren apart
op moeten letten).

`max_acclimatization_capacity` onderschatte deze groep daarom: de
kwetsbaarheid zit in de **trage start**, die deze groep se
blootstellingsgeheugen-kernel al correct modelleert (een bij-nul-beginnende
oplopende reeks — "geen eerdere blootstelling" — in plaats van de
lineaire/vlakke kernels elders). Het plafond óók verlagen, bovenop de trage
start, bestraft een conditie dubbel die volgens de literatuur binnen ~2 weken
weer normaal is. Ook gekwantificeerd: fitte mensen acclimatiseren ~50%
sneller dan onfitte (California DIR-richtlijn), en bij matige/zware arbeid
voorspellen VO2max-drempels van 30/36,5 mL/kg/min wie een hogere kerntemperatuur
oploopt terwijl niet-geacclimatiseerd (Notley et al., Frontiers in Physiology
2020, doi:10.3389/fphys.2020.541483) — consistent met dat dit over snelheid
en fitheidsinteractie gaat, niet over een verlaagd plafond.

**Kalibratie:** `max_acclimatization_capacity` verhoogd (0,50 → 0,65),
gepositioneerd net onder indoor_workers (0,70, al geacclimatiseerd) in plaats
van tussen de permanent-aangetaste groepen. `recovery_threshold` en
`base_recovery_rate` **ongewijzigd** (0,9 / 0,30) — deze weerspiegelen al
redelijk de verminderde-maar-niet-afwezige tolerantie in het vroege,
nog-niet-geacclimatiseerde venster, en er is geen scherper kwantitatief
ankerpunt gevonden om ze te verschuiven.

**Geverifieerd:** `verify.py` en `suite_smoke_test.py` slagen ongewijzigd.

## ⚠️ BELANGRIJK — PYROX's `cardiovascular_disease`-groep herijkt (tweede diepgaande check)

Vervolg op de obesitas-herijking, op verzoek om een soortgelijke diepgaande
check uit te voeren op de rest van de suite. Geprioriteerd op relevantie voor
je eigen werk (CVR/collapsrisico); de overige ~19 geëxtrapoleerde groepen zijn
nog niet gecontroleerd en verdienen elk een eigen sessie.

**Mechanisme, directer dan bij obesitas:** tijdens hittestress moet het hart-
minuutvolume fors stijgen om tegelijk de huid (tot 50-70% van rust-CO, ~8
L/min) én werkende spieren/vitale organen te bedienen — tot ~13 L/min bij
gezonde volwassenen (Kenney et al. 2004, Circulation,
doi:10.1161/CIRCULATIONAHA.105.540773, hartfalenpatiënten). Bij hartfalen
stijgt de output nog wel, maar "mogelijk minder dan nodig om de huid adequaat
te doorbloeden" — de cardiac-output-reserve schiet écht tekort bij die
gecombineerde vraag, en de cutane vasodilatatie-respons zelf is meetbaar
verzwakt (in tegenstelling tot obesitas, waar zweten/vaatverwijding grotendeels
intact bleken). **Dit is exact HESTIA's eigen CVR-conjunctieve-criterium**
(T_rect-overschrijding EN CO_reserve ≤ 0) — onafhankelijke bevestiging van die
constructie, niet alleen een PYROX-kalibratie. Klassiek werk (Rowell) laat
zien dat dit tekort zich specifiek openbaart onder **gecombineerde** inspanning-
plus-hitte, niet bij passieve hitteblootstelling — precies het scenario dat
PYROX en HESTIA allebei modelleren (evenementdeelnemers).

**Acclimatisatie — een geruststellende bevinding, geen invulling bij gebrek
aan beter:** anders dan bij obesitas ondersteunt de literatuur **niet** om de
acclimatisatiecapaciteit verder te verlagen. Hitteacclimatisatie gecombineerd
met training verminderde aantoonbaar ischemische schade na hartchirurgie bij
coronairlijden (Horowitz & Hasin 2023, Front Physiol, 30 jaar onderzoek naar
hitteacclimatisatie-gemedieerde kruistolerantie, doi:10.3389/fphys.2023.1074391),
en CAD-patiënten laten reële peak-VO2-verbetering zien bij training (al was dat
niet significant voor hartfalenpatiënten specifiek, PMC9203221). Omdat deze
PYROX-groep het hele cardiovasculaire spectrum omvat (niet alleen hartfalen),
blijft `max_acclimatization_capacity` **ongewijzigd**.

**Kalibratie:**
```
                              was      wordt
recovery_threshold             0,75  →  0,70
max_acclimatization_capacity   0,40  (ongewijzigd — bewijs pleit ertegen te verlagen)
base_recovery_rate              0,20  (ongewijzigd — geen directe bron)
strain_suppression_strength     0,55  (ongewijzigd — geen directe bron)
```

**Geverifieerd:** `verify.py` en `suite_smoke_test.py` slagen ongewijzigd.
Gerichte simulatie bevestigt een logische positionering (caution/danger-dagen
niet erger dan de meer ernstige categorieën zoals chronic_comorbidities,
niet beter dan obesitas).

## ⚠️ BELANGRIJK — PYROX's `obesity`-groep herijkt op directe thermoregulatie-literatuur (niet HESTIA)

Aanleiding: bij het uitzoeken van het geslachtsverschil in T_rect bleek dat een
"algemene bevolking met obesitastoename"-uitbreiding in HESTIA's Monte Carlo
PYROX en HESTIA door elkaar zou halen (terecht tegengehouden). HESTIA
simuleert deelnemers van een specifiek evenement (zelfgeselecteerd, fitter dan
de algemene bevolking — vandaar de marathonloper-referentie); PYROX beoordeelt
al populatiebreed welke groepen risico lopen, mét een bestaande `'obesity'`-
groep. Die groep is nu herijkt, niet HESTIA's populatie.

**Mechanisme, uit de literatuur:** de best-gecontroleerde vergelijkingen
(gematcht voor totale lichaamsmassa én fitheid, zodat alleen vetpercentage
verschilt) laten zien dat zweetrespons en vaatverwijding bij hoog
vetpercentage **grotendeels normaal** zijn — het sudomotor/vasomotor-systeem
is niet "kapot" door obesitas op zich (Cramer & Jay 2015/2016, J Appl Physiol,
gematcht 10,8% vs 32,0% vet, doi:10.1152/japplphysiol.00906.2015). Het
dominante mechanisme is **biofysisch/geometrisch**: een lagere
lichaamsoppervlakte-tot-massaverhouding betekent minder relatief oppervlak om
warmte kwijt te raken per eenheid geproduceerde warmte ("bij eenzelfde
warmtelast per kg lichaamsgewicht stijgt de weefseltemperatuur meer bij een
obees dan een slank persoon", Kenney 1985, geciteerd in Chiang et al. 2024,
doi:10.1016/j.puh.2023.11.008). Bij een **vaste absolute warmteproductie**
lieten massa-gematchte deelnemers met hoog vetpercentage ~32% grotere
kerntemperatuurstijging zien dan lage-vetpercentage-deelnemers (ΔTre 0,87 vs
0,66°C over 60 min; Cramer & Jay 2016, doi:10.1152/japplphysiol.00768.2016).
Een niet-gematchte systematische review/meta-analyse (10 studies, n=211,
36,7±11,8% vs 17,8±5,7%) vond dezelfde richting, al corrigeerden niet alle
studies voor massa/fitheid (Wickham et al. 2021, J Sci Med Sport,
doi:10.1016/j.jsams.2021.06.004). Een kleine pilotstudie naar 6 weken
hitteacclimatisatie-training specifiek bij mensen met overgewicht/obesitas
vond suggestief (niet doorslaggevend, n=8) bewijs dat het
**aanpassingsproces zelf** trager verloopt in de beginweken (Faulkner et al.
2015, doi:10.1186/2046-7648-4-S1-A115).

**Kalibratie:**
```
                              was      wordt
recovery_threshold            0,80  →  0,75
max_acclimatization_capacity   0,42  →  0,40
exposure_memory                MEMORY_FLAT → MEMORY_VERY_FLAT
base_recovery_rate             0,22  (ongewijzigd)
strain_suppression_strength    0,52  (ongewijzigd)
```
De laatste twee zijn **bewust ongewijzigd gelaten**: voor dag-tot-dag-herstel
en de kritieke-koppeling-sterkte specifiek bij obesitas is geen directe
thermoregulatie-literatuur gevonden — die knoppen aanpassen zou niet
evidence-based zijn geweest.

**Geverifieerd:** `verify.py` slaagt volledig (23/23 groepen, alle
invarianten). Gerichte simulatie (14-daagse hittegolf) bevestigt dat obesitas
nu qua ernst gelijk ligt met `cardiovascular_disease` (beide caution/danger
op dag 2) in plaats van er ver onder — een reële maar gematigde verzwaring,
niet erger dan een gediagnosticeerde hartaandoening. **Bewust niet** onder
cardiovascular_disease/physical_disabilities gepositioneerd: het bewijs
ondersteunt een reëel maar gematigd effect van vetpercentage alleen, niet een
effect dat een gediagnosticeerde hartaandoening overtreft. `suite_smoke_test.py`
slaagt ongewijzigd.



## ⚠️ BELANGRIJK — vetpercentage nu per individu gesampeld (was vast 25%/15% per geslacht)

Vervolg op de vorige twee bevindingen (collapsrisico-vlakheid, geslachtsscheiding
in de staarten). Op verzoek nagegaan of dit ook intern in JOS-3 zit, met een
gecontroleerd experiment: identieke lengte/gewicht/leeftijd/MET/omgeving,
alléén geslacht (en het daaraan gekoppelde vaste vetpercentage) verschillend:
```
male    fat=15%   eind-T_core = 37,0824°C
female  fat=25%   eind-T_core = 37,3060°C   (+0,22°C, puur uit JOS-3)
```
Dat is bijna de hele eerder waargenomen populatiekloof (~0,27°C) — vóórdat het
%VO2max-mechanisme er überhaupt aan te pas komt. Oorzaak: `hestia_model.py`
gebruikte op alle constructieplekken van het profiel
`fat_percentage = 25 if gender == "female" else 15` — een vaste, binaire
waarde zonder enige individuele spreiding. Reële populaties vertonen juist
aanzienlijke spreiding én overlap tussen de geslachten; een harde categoriale
knip garandeert daarom een kunstmatig scherpe (en dus overdreven volledige)
scheiding in precies de staarten die de risicoplots tonen.

**Fix:** `AdultParticipantProfile` heeft een nieuw veld `body_fat_pct`, nu per
individu gesampeld in `generate_base_population()`:
```python
man:    N(17,7%, 4,0%), geclipt [6%, 32%]
vrouw:  N(19,6%, 4,7%), geclipt [8%, 36%]
```
**Update na doorvragen:** de eerste versie hield de oude gemiddeldes aan
(15%/25%, een kloof van 10 procentpunt) — die kloof was zelf nooit
literatuur-gecheckt, alleen "overgenomen". Nagekeken tegen gepubliceerde data
voor recreatieve marathonlopers (Nikolaidis, Vancini, Andrade, de Lira &
Knechtle 2021, BioMed Research International 2021:3717562, BIA-gemeten,
n=32 vrouwen/134 mannen; bevestigd door een onafhankelijke steekproef in
Knechtle & Tanda 2013, 16,3±5,6% bij mannen): de werkelijke kloof is maar
~2 procentpunt (19,6% vrouwen, 17,7% mannen), niet 10. De spreiding (4%/5%)
bleek toevallig al goed te matchen met de gepubliceerde SD (4,0%/4,7%) — daar
is niets aan veranderd. **Nog steeds gevlagd:** deze referentiepopulatie is
marathonloper-specifiek; HESTIA's populatie is breder (VO2max tot ~24
mL/kg/min, ruim onder typische marathonvoltooiers) — een iets hoger algemeen
gemiddelde kan gerechtvaardigd zijn, maar de kloof tussen de geslachten zelf
hoort volgens dit bewijs veel kleiner te zijn dan de oorspronkelijke 10 punten.

`calculate_indices_jos3_adult()` gebruikt nu `body_fat_pct` uit
het profiel (met `getattr`-fallback naar het oude gedrag voor
achterwaartse compatibiliteit); `run_hestia.py`'s representatieve-profielbouwer
(individuele runs) gebruikt het gemiddelde zonder ruis, consistent met hoe de
andere representatieve velden daar al werden behandeld.

**Geverifieerd, drie stappen:**
1. Steekproef van 1000: mannen gemiddeld 14,8% (spreiding 4,0), vrouwen 25,3%
   (spreiding 5,0) — 461 van de 609 mannen vallen binnen het overlapgebied met
   de laagste vrouwenwaarde.
2. Zelfde scenario als de vorige twee bevindingen (wandelen, 04:30, n=150):
   top-20 op piek-T_rect ging van 19/20 vrouw → **13/20 vrouw**; bottom-20 op
   CO_reserve van 20/20 vrouw → **18/20 vrouw**. Nog steeds een reële trend
   (consistent met het overgebleven %VO2max-mechanisme), niet langer een
   kunstmatig volledige scheiding.
3. Regressie (`verify.py`, `suite_smoke_test.py`) slaagt ongewijzigd.

**Niet aangepast, bewust:** de kinderadapter (`run_pediatric_simulation`,
"unchanged from rev09") heeft dezelfde vaste-vetpercentage-constructie, maar
is niet aangesloten op de CLI/suite-integratie — buiten scope gelaten. De
losse MET-drempeldiagnostiek (`get_representative_participant`) idem, ook niet
bereikbaar vanuit de CLI.

## ⚠️ BELANGRIJK — collapsrisico exact gelijk voor alle 1000 deelnemers verklaard (geen bug)

Gevonden bij het beoordelen van een n=1000-run (wandelen, koel, 04:30-09:00):
`cvr_p_collapse_pct` was voor **alle 1000 deelnemers exact identiek**
(std = 6,9×10⁻¹⁸, numeriek nul) — ongeacht leeftijd, geslacht of individuele
fysiologie. Dat oogt als een bug, maar is het niet.

**Verklaring, geverifieerd tegen de brondata:** de collapsrisicoformule is
drempelgestuurd — elke van de vier bijdragende termen is een
`max(0, overschrijding)`:
```
z = W_T1·max(0,T_rect−39,5) + W_T2·max(0,T_rect−40,5)
  + W_C·max(0,2,0−CO_reserve) + W_D·max(0,dehydratie−3%)
p_collapse = sigmoid(intercept + z)
```
Gecontroleerd in de Excel-export van deze specifieke run:
```
n boven T_rect 39,5°C     : 0 / 1000
n onder CO_reserve 2,0    : 0 / 1000
n boven 3% dehydratie     : 0 / 1000
```
Bij nul overschrijdingen is `z` exact 0 voor iedereen, dus reduceert
`p_collapse` tot louter de gekalibreerde intercept — identiek voor de hele
populatie. Wiskundig correct, geen bug: voor een licht/koel scenario zoals dit
(wandelen, WBGT ~15-16°C, piek-T_rect max 38,7°C, CO_reserve nooit onder 2,8
L/min) verliest het collapsrisicomodel simpelweg zijn onderscheidend vermogen
en geeft het alleen nog de achtergrond-basisrisico terug.

**Fix:** `run_monte_carlo_adult()` waarschuwt nu expliciet wanneer 0% van de
populatie een van de vier drempels overschrijdt, zodat dit niet meer voor een
defect wordt aangezien:
```
Note: 0% of participants crossed any collapse-risk trigger condition
(T_rect>39.5/40.5°C, CO_reserve<2.0 L/min, dehydration>3%) in this
scenario. The collapse-risk value reported below is therefore the
calibrated baseline rate applied uniformly to everyone...
```
Getest: vuurt in de gereproduceerde wandelscenario (n=100, zelfde
weerbestand/tijdstip), vuurt niet in eerdere hardloopscenario's waar wel
overschrijdingen voorkomen. Regressie (`verify.py`, `suite_smoke_test.py`)
slaagt ongewijzigd.

## Observatie — sterke geslachtsverdeling in de extreme staarten (geen bug, wel opvallend)

In dezelfde n=1000-run bleek de top-20 (hoogste T_rect + laagste CO_reserve)
voor 95-100% uit vrouwen te bestaan (19/20 resp. 20/20), terwijl de populatie
60% man/40% vrouw is. Nagerekend in de brondata:
```
gemiddelde pct_vo2max   vrouw 0,384  vs  man 0,316
gemiddelde VO2max       vrouw 40,8   vs  man 49,0 mL/kg/min
gemiddelde piek-T_rect  vrouw 38,53  vs  man 38,26 °C
```
Dit is fysiologisch verklaarbaar en consistent met de fix: bij eenzelfde
absolute MET (wandelen) vragen vrouwen — door hun lagere gemiddelde VO2max —
een groter deel van hun eigen VO2max, dus relatief zwaardere inspanning, dus
iets hogere T_rect/lagere CO_reserve. De richting is correct en in lijn met
gepubliceerde inspanningsfysiologie. **De volledigheid van de scheiding (95-
100% in de staart) is wel opvallend genoeg om te vergelijken met echte
casussen-naar-geslacht als je die hebt** — dit is geen code-aanpassing die ik
nu doe, alleen een observatie om te laten meewegen bij interpretatie.

## ⚠️ BELANGRIJK — gekozen activiteit/MET stuurde de Monte Carlo-populatie niet

Gevonden na een gerichte plausibiliteitscheck: `generate_base_population()` had
géén `met_value`-parameter. De populatie kreeg haar inspanningsintensiteit
altijd via een vaste, intern hardgecodeerde marathon-tempo-aanname
(`EVENT_PACE_M`/`EVENT_PACE_F`, 5/6 min/km) — **volledig los van wat je in het
activiteitenmenu koos**. Concreet: een Monte Carlo-run met "Wandelen 4,0 km/u
(MET 3,5)" simuleerde in werkelijkheid nog steeds marathon-looptempo
(effectieve MET ~9,3), niet wandelen.

**Fix:** `generate_base_population()` heeft nu een `met_value`-parameter.
Wanneer gegeven, wordt de VO2-vraag per deelnemer rechtstreeks afgeleid van de
gekozen activiteit (`vo2_at_event_pace = met_value × VO2MAX_TO_MET_FACTOR`) in
plaats van de vaste marathon-pace-aanname; die laatste blijft als fallback
bestaan wanneer geen `met_value` wordt meegegeven (backward-compatible).
`run_monte_carlo_adult()` geeft `met_value` nu door aan
`generate_base_population()`.

**Bijkomende, expliciet gevlagde wijziging:** de `pct_vo2max`-clip
(voorheen [0,55, 0,95], gekalibreerd voor marathon-inspanning) is verruimd
naar [0,15, 0,95], anders zou lichte inspanning zoals wandelen alsnog
kunstmatig op minimaal 55% VO2max worden gevloerd — precies het probleem dat
deze fix moest oplossen. Deze ondergrens is een technische noodzaak van het
generaliseren van hetzelfde mechanisme naar lichtere activiteiten, geen
zelfstandig gevalideerd getal — graag beoordelen, vooral de ondergrens.

**Geverifieerd, niet alleen beargumenteerd:**
```
walking MET 3.5    n=300  mean_final_MET=3.51  (voorheen altijd ~9.3)
running MET 8.3    n=300  mean_final_MET=8.26
geen met_value      n=300  mean_final_MET=9.30  (ongewijzigde fallback)
```
En in een echte CLI-run (wandelen, MET 3,5, n=60): gemiddelde piek-T_rect nu
38,0°C (was ~39-40°C toen de wandelkeuze genegeerd werd) — een fysiologisch
plausibele waarde voor wandelinspanning. `verify.py` en `suite_smoke_test.py`
slagen ongewijzigd.



## ⚠️ BELANGRIJK — "Marathon, competition pace" (optie 10) is geen kalibratie-consistente keuze

Gevonden naar aanleiding van de vraag of de fix hierboven de marathon-situatie
niet juist slechter maakt. Getest tegen de kalibratie-referentie (de oude
vaste tempo-aanname, waar de collapsrisico-kalibratie/intercept tegen is
gevalideerd, met gemiddeld 73,9% VO2max):

```
Kalibratie-referentie (oude aanname)     mean_pct_vo2max = 0.739
Activiteit 10 "Marathon competition"     mean_pct_vo2max = 0.918, 71% geclipt op 0,95 (!)
Activiteit 2  "Running 9,6 km/h"         mean_pct_vo2max = 0.763  ← komt overeen met kalibratie
```

Optie 10 (MET 13,5, professioneel wedstrijdtempo) duwt 71% van een algemene
recreatieve-fitnessdoorsnede tegen hun fysiologische plafond — niet omdat de
fix dat fout doet, maar omdat een recreatieve steekproef dat tempo simpelweg
niet kan volhouden. Dat is zowel fysiologisch onrealistisch als statistisch
problematisch (kunstmatige opeenhoping op één waarde), en betekent dat de
Boston-Marathon-kalibratie niet zonder meer geldt voor een populatie
gesimuleerd op optie 10. Optie 2 ("Running, 9,6 km/h, recreational", MET 9,8)
of 11 ("Running, average", MET 10,0) liggen dicht bij wat de kalibratie
oorspronkelijk aannam.

**Fix:** `generate_base_population()` waarschuwt nu automatisch wanneer meer
dan 20% van de gegenereerde populatie tegen het VO2max-plafond aan zit,
ongeacht welke activiteit gekozen is — een generieke vangrail, niet specifiek
voor optie 10. Getest: vuurt bij MET 13,5 (73% geclipt), vuurt niet bij MET
9,8. Regressie (`verify.py`, `suite_smoke_test.py`) slaagt ongewijzigd.

## ⚠️ BELANGRIJK — post-finish TCF-dosis werd stilzwijgend op nul gehouden

Ontdekt tijdens het bouwen van de conjunctieve-criterium-tijdreeksplot, niet
tijdens een routinecontrole — dus meld dit vooraan en expliciet.

`simulate_post_finish()` in `hestia_model.py` berekent intern een
`control_failure_dose_postfinish` (de TCF-dosis — het tijdsintegraal van
max(0,T_rect−40,5) × max(0,−CO_reserve) — tijdens de 10 minuten na de finish).
Die waarde werd echter nooit doorgegeven aan het deelnemersrecord waar
`HESTIA_ControlFailure_Module.analyse_participant()` 'm uit leest; die functie
valt dan terug op een default van 0,0. Resultaat: **de post-finish-bijdrage
aan `tcf_dose_total_degC_L` (Excel-export) en aan `control_failure_dose_total`
was voor elke deelnemer, in elke eerdere run met dit model, stilzwijgend nul**
— ook wanneer T_rect en CO_reserve in die periode wel degelijk aan het
conjunctieve criterium voldeden.

Concreet voorbeeld uit een testrun (n=80, Nijmegen): de deelnemer met de
hoogste piek-T_rect had 10 minuten lang T_rect > 41°C en CO_reserve = −0,47
L/min — het criterium was continu actief — en toch stond er "postfinish dose:
0,0000". Na de fix: race-dosis 5,5865 + postfinish-dosis 5,1566 = totaal
10,7431 (bijna een verdubbeling t.o.v. wat er stond).

**Fix:** de drie ontbrekende sleutels (`control_failure_dose_postfinish`,
`control_failure_time_postfinish_min`, `t_control_failure_postfinish_min`) die
`simulate_post_finish()` al berekende, worden nu ook echt aan
`results[-1]` toegevoegd. Geen wijziging aan de berekening zelf — alleen aan
het doorgeven ervan. Geverifieerd: `analyse_participant()`, de Excel-kolom
`tcf_dose_total_degC_L`, en de nieuwe plot geven nu exact hetzelfde getal
(10,7431 in het voorbeeld hierboven). `verify.py` en `suite_smoke_test.py`
slagen nog steeds.

**Consequentie voor eerder gegenereerde rapporten/Excel-bestanden met deze
suite:** die `tcf_dose_total_degC_L`/`control_failure_class`-kolommen hebben
de post-finish-bijdrage gemist. Als je dat cijfer al ergens hebt gebruikt of
gerapporteerd, is het de moeite waard om te overwegen dat opnieuw te draaien
met deze gefixte versie.

## Update — plot 1 en 2 waren leeg

`plot_adult_results` en `plot_adult_boxplots` in `hestia_model.py` eindigden
met `plt.show(block=False)` zonder de figure terug te geven. `hestia_plots.py`
ving de figure daarom op via `plt.gcf()` ná die aanroep — op sommige backends
(o.a. bepaalde Spyder inline-plotconfiguraties) maakt `show()` het huidige
figuur ongeldig of leeg, waardoor `plt.gcf()` daarna een nieuw, leeg figuur
teruggeeft in plaats van het figuur met data. Vandaar de lege plot 1 en 2 —
plot 3-8 zijn eigen nieuwe functies die de figure direct `return`en en hadden
dit probleem niet.

**Fix:** alle drie de hergebruikte plotfuncties (`plot_adult_results`,
`plot_pediatric_results`, `plot_adult_boxplots`) geven nu `return fig` —
geen wijziging aan de plot-inhoud zelf, alleen aan wat de functie teruggeeft.
`hestia_plots.py` gebruikt nu die teruggegeven figure direct in plaats van
`plt.gcf()`. Getest door een backend te simuleren die het figuur na `show()`
opruimt (`plt.close(plt.gcf())` binnen een gemonkeypatchte `plt.show`): de
teruggegeven figure bleef geldig en gevuld met data, ook onder die
omstandigheden. `verify.py` en `suite_smoke_test.py` slagen nog steeds.

## Aanleiding

Je liep tegen een concrete klacht aan: "als ik nu de suite-versie van HESTIA
draai, mis ik de Monte Carlo simulaties." Dat bleek twee gescheiden problemen
te zijn, die alleen sámen zichtbaar werden:

1. `hestia_model.py` in de suite was de oude rev02-basisversie (okt 2025) —
   geen CVR-module, geen collapse-risicomodel, geen tailplot-kalibratie. Het
   CVR/tailplot-bestand (rev17) bestond wel, maar stond volledig los van de
   suite (niet in MANIFEST/CHECKSUMS, niet geïmporteerd door `run_hestia.py`).
2. Zelfs los daarvan: `run_hestia.py`'s `monte_carlo_adult()`-wrapper riep
   `hestia.run_monte_carlo_adult()` aan zonder het verplichte argument
   `age_configuration` mee te geven — elke aanroep crashte met een
   `TypeError`, ongeacht welke HESTIA-versie eronder zat. Dit was nooit
   opgemerkt omdat `suite_smoke_test.py` alleen het individu-pad test, nooit
   Monte Carlo.

## Wat is opgelost

### 1. CVR/tailplot-HESTIA is nu de suite-versie
`hestia_model.py` is vervangen door de rev17-versie (voorheen
`HESTIA_Data_Engine_CVR_v10_calibrated_tailplot.py`). De drie submodules die
dat bestand zelf nodig heeft, zijn toegevoegd als eigen suite-bestanden:
`HESTIA_CVR_Module_v2.py`, `HESTIA_CVR_Console.py`,
`HESTIA_ControlFailure_Module.py`. Geverifieerd via echte import:
`CVR_BESCHIKBAAR = True`, `TCF_BESCHIKBAAR = True` (voorheen `False` in elke
losse test van het CVR-bestand, omdat de submodules ontbraken).

**Eén marked edit** in `hestia_model.py`: de losse `print("Script started")`
op module-niveau (regel ~681) is verwijderd. Draaide bij elke import, ook als
library — geen inhoudelijke wijziging, alleen output-hygiëne.

### 2. Bug gevonden en gefixt in `HESTIA_ControlFailure_Module.py`
In `format_population_summary()` ontbrak een komma tussen twee regels,
waardoor Python's impliciete string-aaneenschakeling de P99.9/MAX-regel en de
Time-regel samensmolt tot één onleesbare regel. Getest vóór en na de fix met
een dummy summary-dict; nu twee correct gescheiden regels.

### 3. `run_hestia.py` volledig herschreven voor het rev10-contract
Twee brekende contractwijzigingen zaten in de weg:

- **Tuple → dataclass.** `calculate_indices_jos3_adult()` verwacht sinds
  rev10 een `AdultParticipantProfile`-dataclass-instantie, geen tuple. De
  oude adapter bouwde een tuple; dat crasht nu hard. Nieuw: een
  `_build_representative_profile()`-helper bouwt de dataclass, voor zowel de
  single-run als de Monte Carlo-weg (die laatste gebruikt HESTIA's eigen
  `generate_base_population()`).
- **De ontbrekende `age_configuration` uit je eigen melding.** De wrapper
  geeft nu `age_configuration="standard"` door (puur voor
  backwards-compatibele signatuur-match; rev10 negeert het argument zelf en
  print een deprecation-notice als het niet "standard" is, want leeftijd zit
  al in elk gesamplede profiel). `monte_carlo_adult()` geeft ook
  `base_population`, `random_seed` en `run_control_failure` door — dat laatste
  standaard `True`, want dat is het hele punt van deze integratie.

**Geverifieerd door het echt te draaien:**
```
n participants: 15
collapse_intercept_kal -7.903186
pct_control_failure_any 0.0
```
Monte Carlo faalde niet meer, en de CVR/collapse/control-failure-statistieken
komen door.

### 4. `summarize_individual()` uitgebreid
Geeft nu ook `min_co_reserve`, `decompensation_occurred`, `ehs_postfinish`,
`t_rect_peak_postfinish`, `auc_klinisch_totaal`, en (via
`HESTIA_ControlFailure_Module.analyse_participant`)
`control_failure_dose_total` / `control_failure_class` — voorheen alleen
`t_rect`/`water`/`rpe`.

### 5. `suite_smoke_test.py` uitgebreid met een Monte Carlo-stap
Dit is de regressie-beveiliging: de vorige smoke test testte alleen het
individu-pad en zag de kapotte Monte Carlo-wrapper daarom nooit. Er is nu een
`[3/3]`-stap die `monte_carlo_adult()` met een kleine populatie
(`n=10, use_parallel=False`) uitvoert en controleert dat er resultaten
terugkomen. Dit precieze gat — wel individu, geen Monte Carlo getest — was
exact de oorzaak dat de vorige bug onopgemerkt bleef.

## Wat NIET is aangepast (bewust)

- Geen enkele wetenschappelijke aanname, kalibratieconstante, of
  modelvergelijking in `hestia_model.py` zelf is veranderd. Alleen de import-
  en aanroepcontracten eromheen.
- De losse `load_weather_from_thermopoulos_excel()` in `hestia_model.py`
  (rev17's eigen, interactieve Excel-lezer) is laten staan, ongebruikt door de
  suite-integratie (die loopt via `thermopoulos_loader.py`). Verwijderen zou
  de standalone-bruikbaarheid van het bestand aantasten zonder functioneel
  voordeel voor de suite; vlag dit als opruimpunt, geen actie ondernomen.

## Nog open — vraagt jouw beoordeling

**MET-afleiding is niet langer direct.** Sinds rev10 is een deelnemers
gesimuleerde MET niet meer `met_value` zelf, maar
`vo2max * pct_vo2max / VO2MAX_TO_MET_FACTOR`. `met_value` stuurt alleen nog de
liveability-check. Voor `simulate_individual_adult()` (één representatieve
deelnemer, geen populatietrekking) los ik `pct_vo2max` terug op uit de
gevraagde `met_value` en een deterministisch gemiddelde VO2max voor
leeftijd/geslacht (dezelfde Tanaka-2001-vergelijking die
`generate_base_population()` al gebruikt, maar zonder de steekproefruis) — zo
blijft `simulate_individual_adult(met_value=8.0, ...)` zich gedragen zoals
voorheen. **Dit terugoplossen is een technische overbrugging die ik heb
gemaakt om het oude interface-gedrag te behouden, geen gevalideerde
wetenschappelijke keuze.** Zie de docstring bovenaan `run_hestia.py` voor de
volledige redenering. Beoordeel of dit de juiste aanpak is, vooral voor
individuele (niet-Monte-Carlo) runs op ongebruikelijke MET-waarden.

## Update — activiteiten-/kledingtabel uit `hestia_model.py` nu in de CLI

Je gaf terecht aan dat de oorspronkelijke HESTIA een keuzetabel activiteit → MET
heeft. Die stond er al (`MET_ACTIVITIES_ADULT`, `CLO_OPTIONS_ADULT`,
`select_met_activity()`, `select_clo_value()`, in `hestia_model.py`, ongewijzigd
sinds rev09), maar was niet aan `run_hestia.py`'s CLI gekoppeld — ik had daar
een losse "typ een MET-waarde"-vraag neergezet. Vervangen door de echte menu's:
19 activiteiten (12-18 zijn wandelen, incl. "Walking with backpack, 4.0 km/h"
MET 4.5) en 6 kledingopties. Getest end-to-end: activiteit 13 (Wandelen 4,0
km/u, MET 3,5) en kleding 1 correct opgepikt en doorgevoerd in een Monte
Carlo-run.

En passant nog een bug gevonden en gefixt in mijn eigen bestand-detectiecode
(niet in `hestia_model.py`): dezelfde Thermopoulos-Excel werd soms dubbel
getoond in de bestandenlijst (eenmaal als absoluut, eenmaal als relatief pad),
waardoor de keuzevolgorde verschoof. Nu genormaliseerd naar absolute paden
vóór het dedupliceren.

## Update — dedup bleek op Windows nog niet volledig

Bovenstaande fix deduplicete op kale tekstvergelijking van het absolute pad.
Op Windows is het bestandssysteem hoofdletterongevoelig, maar tekst vergelijken
is dat niet — dus `C:\...\Thermopoulos_...xlsx` en `c:\...\thermopoulos_...xlsx`
(dezelfde file, alleen wdir met een andere casing binnengekomen) werden nog
steeds als twee aparte bestanden getoond. Opgemerkt doordat je dit letterlijk
in de console zag verschijnen. Gefixt door te dedupliceren op
`os.path.normcase(os.path.abspath(pad))` (op Windows: lowercase + backslashes;
op Linux/Mac een no-op) in plaats van op het kale pad, met behoud van de
oorspronkelijke casing voor weergave/gebruik. Getest door Windows'
hoofdletterongevoelige gedrag te simuleren (`os.path.normcase` tijdelijk
vervangen door een lowercase-functie): twee paden die alleen in casing
verschilden, smolten correct samen tot één kandidaat.

- `verify.py` — ongewijzigd, alle checks slagen (PYROX is niet geraakt).
- `suite_smoke_test.py` — slaagt end-to-end: PYROX-populatie, HESTIA-individu,
  HESTIA-Monte-Carlo (nieuw), met echte Thermopoulos-Nijmegen-data.
- Losse tests van `simulate_individual_adult()` en `monte_carlo_adult()` met
  echte data, buiten de smoke test om, bevestigen CVR-velden
  (`co_reserve`, `decompensatie`, `ehs_postfinish`) en
  control-failure-statistieken komen door.

## Update — plots toegevoegd

Nieuw bestand `hestia_plots.py`. Hergebruikt twee bestaande, werkende
plotfuncties uit `hestia_model.py` zelf (`plot_adult_results` —
4-panelen-tijdreeks met T_rect/RPE/omgeving/%-at-risk, inclusief de
vulnerable-tail-overlay; `plot_adult_boxplots` — verdeling per
leeftijdsgroep/geslacht) en voegt vier nieuwe, CVR-specifieke plots toe die
nog ontbraken:

1. Tijdreeks + tail-overlay (hergebruikt)
2. Boxplots per leeftijdsgroep/geslacht (hergebruikt)
3. CO_reserve-verdeling, met de 2,0 L/min-risicogrens en de 0-lijn gemarkeerd
4. Collapsrisico-verdeling (gebruikt `stats['p_collapse_per_sim']`, dat het
   model al berekent maar verder alleen als geaggregeerde percentages naar de
   console stuurt)
5. Conjunctieve-risicozone-scatter: T_rect-piek vs. CO_reserve-minimum per
   deelnemer, gekleurd naar collapsrisico — visualiseert de daadwerkelijke
   T_rect>40,5 EN CO_reserve≤0-voorwaarde in plaats van de twee marginale
   verdelingen apart
6. Collapsrisico naar leeftijd, per geslacht

Voor individuele runs (niet-Monte-Carlo) is er een nieuwe
tijdreeksplot (T_rect, CO_reserve, geschatte hartslag, RPE/hydratie) — de
bestaande `hestia_model.py`-plotfuncties zijn allemaal Monte-Carlo-vormig en
dekten dat geval niet.

Aangesloten op `run_hestia.py`'s CLI: na elke run (individueel én populatie)
volgt een "Generate plot(s)? (y/n)"-vraag; bij ja worden de PNG's naast het
script weggeschreven (zelfde padlogica als de Excel-export) en de volledige
paden getoond. Getest end-to-end, inclusief visuele controle van de
gegenereerde PNG's.

Dezelfde reden als de activiteitentabel: `get_adaptation_profile()` bestond al
in `hestia_model.py` (4 niveaus — Beginner/Low-average/Average/Advanced — met
een aanbeveling gebaseerd op de gekozen activiteit), maar de CLI vroeg los om
een kale 0-1-waarde te typen. Nu aangesloten: na de activiteitkeuze toont de
CLI het aanbevolen niveau (bijv. "Beginner / Not acclimatized" voor rustig
wandelen), met de optie om te accepteren of uit de lijst te kiezen. Getest
beide paden (accepteren en expliciet niveau 3 kiezen).

## Update — plot 7: top-10 T_rect-max en bottom-10 CO_reserve-min, race + post-finish

Vroeg om het tijdsverloop van de 10 deelnemers met de hoogste piek-T_rect en de
10 met de laagste minimum-CO_reserve, van start simulatie tot einde plús de 10
minuten post-finish. Dat laatste stuk (`PF_DUUR_MIN = 10.0` minuten) berekent
`hestia_model.py`'s `simulate_post_finish()` al intern (metabole nagloed,
veneuze pooling), maar gaf voorheen alleen de piekwaarde en eindwaarde terug —
niet de tussenliggende reeks, dus die was niet te plotten.

**Eén gerichte, additieve wijziging in `hestia_model.py`** (geen
natuurkunde/parameters aangeraakt, alleen wat de bestaande lus al berekent nu
ook teruggeven): `simulate_post_finish()` bouwt nu ook
`t_rect_series_postfinish`, `co_reserve_series_postfinish` en
`time_min_series_postfinish` op tijdens dezelfde lus, en geeft die mee in de
return-dict; de aanroepplek hangt ze aan het laatste record van elke
deelnemer, naast de bestaande piek-/eindwaarden. Geverifieerd: `verify.py` en
`suite_smoke_test.py` slagen ongewijzigd (0 failures) — de bestaande
aggregaten (`t_rect_piek_postfinish`, `co_reserve_postfinish`, enz.) komen uit
dezelfde berekening als voorheen, er is alleen data toegevoegd, niets
gewijzigd.

Nieuwe plot 7 in `hestia_plots.py` (`plot_extreme_cohorts_timeseries`)
combineert per deelnemer de race-tijdreeks met deze post-finish-reeks tot één
doorlopende tijdas, selecteert de twee cohorten uit `results_df` (`nlargest`
op `max_t_rect`, `nsmallest` op `cvr_co_reserve_min`), en toont ze in twee
panelen met een verticale lijn op het race-einde. Aangesloten als 7e plot in
`generate_population_plots()`; getest end-to-end (PNG correct gegenereerd en
gecontroleerd op geldigheid).

## Update — conjunctief criterium als tijdsintegraal (plot 8 + individuele plot)

Gevraagd: T_rect × CO_reserve geplot in tijd, als tijdsintegraal. Rauwe
T_rect × CO_reserve is niet gebruikt: Celsius is een intervalschaal met een
willekeurig nulpunt, dus een direct product is niet fysiek betekenisvol (in
Fahrenheit zou hetzelfde product een ander getal geven). De suite heeft al
precies deze tijdsintegraal, alleen correct genormaliseerd: de TCF-dosis uit
`HESTIA_ControlFailure_Module.py`,
`∫ max(0, T_rect−40,5) × max(0, −CO_reserve) dt` — T_rect als overschrijding
boven een fysiologisch zinvolle drempel in plaats van de rauwe waarde.

Twee nieuwe plots, beide gebruiken `control_failure_increment()`/
`thermal_excess()`/`co_deficit()` rechtstreeks uit
`HESTIA_ControlFailure_Module.py` (geen herimplementatie van de formule):
- **Individueel:** `plot_conjunctive_criterion_individual()` — instantane
  "snelheid" en cumulatieve dosis over race + post-finish, voor één deelnemer.
- **Populatie (plot 8):** `plot_conjunctive_dose_extreme_cohorts()` — de
  cumulatieve dosis voor dezelfde twee cohorten als plot 7 (top-10 T_rect-max
  + bottom-10 CO_reserve-min), laat zien welke van die al-gemarkeerde
  deelnemers daadwerkelijk conjunctieve dosis opbouwen, en wanneer.

Bij het bouwen en cross-valideren van deze plots tegen de officiële
`tcf_dose_total_degC_L` kwam de hierboven beschreven bug aan het licht (zie
"⚠️ BELANGRIJK" bovenaan dit document) — de twee kwamen niet overeen totdat
die gefixt was. Na de fix komen ze exact overeen (geverifieerd tot op 4
decimalen). Aangesloten als 8e plot in `generate_population_plots()` en als
tweede plot in `generate_individual_plots()`.

## Update — Excel-output landde niet in de suite-map

Root cause: de Excel-bestandsnamen waren relatief (`"HESTIA_Individual_...xlsx"`),
dus ze landden in het *huidige working directory* van het Python-proces op het
moment van schrijven — dat hoeft niet gelijk te zijn aan de map waar de suite
staat, afhankelijk van hoe de IDE/console is gestart (herstarte kernel,
`runfile` met een andere `wdir`, etc.). Ook de zoekopdracht naar
`Thermopoulos_*.xlsx` had hetzelfde probleem.

Gefixt: beide schrijfpaden en de bestandszoekopdracht gebruiken nu
`os.path.dirname(os.path.abspath(__file__))` — hetzelfde patroon dat
`hestia_model.py`'s eigen interactieve `main()` al gebruikte, en om precies
dezelfde reden. Getest door het script vanuit een volledig andere directory
(`/tmp/elsewhere`) te draaien: het Thermopoulos-bestand werd gevonden in de
suite-map, en de output-Excel landde daar ook, met het volledige pad getoond
in de console.

## Update — `run_hestia.py` direct uitvoeren gaf alleen een demo

`run_hestia.py`'s `if __name__ == "__main__":`-blok riep alleen
`simulate_individual_adult()` aan met vaste parameters (n=30 bij een eerdere
tussenversie) — geen echte tool, een demo. Vervangen door een interactieve
CLI (`_run_cli()`): bestand-/sheet-keuze, individu vs. populatie, elke
parameter instelbaar (Enter = sensible default), volledige populatiegrootte
(standaard n=1000, niet beperkt tot een demo-omvang), rijke console-rapportage
via `print_cvr_population_summary` + `format_population_summary`, en
Excel-export van de resultaten. Getest end-to-end in beide modi met echte
Nijmegen-data (zie console-output hierboven ter referentie qua vorm).

## [2026-08-26] Reconciliation with a parallel branch (Klimatos.ClimateShift integration)

Two changes ported in from a separately-maintained branch that had diverged
from this baseline after 2026-07-27, reconciled onto this baseline (chosen as
the source of truth for everything else, including the CVR/Lloyd-2022
rebuild, the wind-direction fix, the TCF dose fix, the MET-derivation fix,
and the per-endpoint REF_CONDITIONS fix, none of which existed in the other
branch):

1. **Rehydration fix (`cvr_water_loss_kg`)**: the model's own ad-libitum
   drinking simulation ran AFTER the CVR snapshot was built for each
   timestep, so the CVR module's dehydration signal (`cvr_water_loss_kg`)
   was a separate, never-decremented accumulator that silently assumed zero
   fluid intake for the entire event -- even though `cumulative_water_loss`
   (used for the thirst/dehydration_pct calculation) correctly subtracted
   each drink. Fixed by moving the drinking block ahead of the CVR block and
   deriving `cvr_water_loss_kg` from the now-already-corrected
   `cumulative_water_loss` instead of a duplicate running total.

2. **Episode-count annotation on `plot_conjunctive_dose_extreme_cohorts`**
   (`hestia_plots.py`): each cohort member's legend entry now reports how
   many separate episodes their own conjunctive criterion (T_rect > t_rect_crit
   AND CO_reserve <= co_reserve_limit) was met, and the total time spent in
   that state -- a runner can cross out of and back into the violated state
   more than once, which the existing cumulative-dose curve alone does not
   make clear. Reuses the `rate` series `_conjunctive_series()` already
   computed (nonzero exactly when both conditions hold) rather than
   recomputing the condition separately, so it cannot drift from the
   officially reported dose it annotates.

Verified: `suite_smoke_test.py` and `verify.py` both pass unchanged after
both patches; a synthetic two-episode test case confirms the episode count
and duration match an independent recomputation using the same official
`thermal_excess`/`co_deficit` functions.

## [2026-08-26, vervolg] Klimatos.ClimateShift toegevoegd als onafhankelijke tweede ingang

Toegevoegd, additief, zonder de bestaande HESTIA/PYROX-bestanden verder aan
te raken: `Klimatos_ClimateShift.py` (het klimaattrend-instrument),
`klimatos_ehs_worker.py` (de parallelle worker), en `hestia_bridge.py` --
een nieuw bestand in DEZE baseline (die er nooit een had), niet een
gereconstrueerde Streamlit-brug. Het is een Streamlit-vrije afsplitsing van
een los onderhouden branch, met precies één verschil: de
`@st.cache_data`-decorator is verwijderd (irrelevant zonder
Streamlit-runtime; elke aanroep is toch al een apart weerscenario). Genoemd
`hestia_bridge.py` omdat `individual_engine.py` die exacte modulenaam
importeert.

`run_hestia.py` en `run_pyrox.py` zijn hierbij op geen enkele manier
gewijzigd -- de twee ingangen (HESTIA/PYROX console-suite, Klimatos'
klimaattrend-analyse) delen dezelfde kern maar zijn onafhankelijk van elkaar
te draaien.

Geverifieerd: `suite_smoke_test.py` en `verify.py` slagen ongewijzigd.
Klimatos' eigen testsuite (`test_end_to_end.py`, `test_new_modules.py`,
`test_rate_limit.py`) slaagt volledig tegen deze baseline. Een losse
end-to-end-test van de EHS-evolutiemodule (120 realisaties, echte fysiologie)
bevestigt: alle velden correct aanwezig (`falmouth_ehs_per_1000`,
`pct_true_ehe_criterion`, `pct_true_ehs_criterion`,
`expected_collapses_per_1000`, `t_rect_co_reserve_pairs`), eindpuntkeuze
(`ehs` vs `hospitalisation`) geeft correct verschillende waarden.

## [2026-08-26, vervolg 2] Sectie 9 toegevoegd aan generate_event_report.py: Falmouth-EHS / EHE / klinisch criterium

`generate_report()` las tot nu toe uitsluitend uit `monte_carlo_adult()`'s
eigen `stats`-dict -- de analyselaag die de nieuwe `hestia_bridge.py`
toevoegt (`falmouth_ehs_per_1000`, `pct_true_ehe_criterion`,
`pct_true_ehs_criterion`, `t_rect_co_reserve_pairs`) werd nergens gelezen,
simpelweg omdat `run_hestia.py`'s rapportagepad de brug nooit aanriep.

Toegevoegd: `generate_report()` kreeg een nieuwe, optionele parameter
`bridge_summary` (achterwaarts compatibel -- bestaande aanroepen zonder dit
argument werken ongewijzigd, met een expliciete "niet beschikbaar"-vermelding
in het rapport in plaats van stilzwijgend weggelaten cijfers). Nieuwe
sectie 9 toont de Falmouth-EHS-schatting, EHE- en klinisch-criteriumpercentages,
én een marge-tot-drempel-analyse (hoe dicht de dichtstbijzijnde werkelijk
gesimuleerde combinatie bij elke drempel kwam) -- essentieel bij een
uitkomst van 0%, die zonder deze marge een geruststellender beeld kan geven
dan gerechtvaardigd is.

`build_bridge_summary(all_results, interp_data)` toegevoegd aan
`hestia_bridge.py` als publieke ingang: `_summarize_results()` alleen bevat
GEEN `falmouth_ehs_per_1000` (die wordt elders apart berekend uit de
gemiddelde luchttemperatuur) -- bevestigd met een directe test vóór deze
functie werd toegevoegd, precies om te voorkomen dat elke aanroeper deze
tweetrapsstap zelf moet herontdekken.

`margin_to_threshold_stats()`/`format_margin_lines()` toegevoegd aan
`hestia_bridge.py` (gedeeld tussen het rapport en, als eigen kopie,
Klimatos.ClimateShift.py -- zie de docstring daar voor waarom bewust niet
via een import gedeeld: Klimatos moet blijven werken zonder HESTIA aanwezig).

`run_hestia.py`'s interactieve CLI vraagt nu ook "Generate event report
(Markdown)?", naast de bestaande plot-vraag, en roept daarvoor
`build_interpolated_weather()` een tweede keer aan (in plaats van
`monte_carlo_adult()`'s retourwaarde te wijzigen, wat `suite_smoke_test.py`
en andere bestaande aanroepers zou breken).

Geverifieerd: volledig rapport gegenereerd met en zonder `bridge_summary`
(beide paden correct, geen crash); sectie 9 toont correcte cijfers,
inclusief nette geneste Markdown-opmaak. `suite_smoke_test.py` en
`verify.py` slagen ongewijzigd; Klimatos' eigen testsuite slaagt volledig.

## [2026-08-26, vervolg 3] Geocoding-fix: hestia_model.py's eigen get_lat_lon()

`get_lat_lon()` (gebruikt door `hestia_model.py`'s eigen standalone `main()`,
los van `run_hestia.py` dat weerdata uit een voorbereid Excel-bestand leest)
had drie reële gebreken, gevonden bij review en vergeleken met het al
werkende patroon in `Klimatos_ClimateShift.py`/`Thermopoulos_Data_Engine.py`:

1. Kale f-string-URL-opbouw in plaats van `requests`' eigen `params=`.
   Direct getoetst (zonder live netwerktoegang, door het opgebouwde
   `PreparedRequest` te inspecteren): spaties en niet-ASCII-tekens werden al
   automatisch procent-gecodeerd door `requests` zelf, dus dit was in de
   praktijk grotendeels onschadelijk -- maar wel de verkeerde gewoonte om
   toevallig op te vertrouwen, en inconsistent met de rest van deze suite.
2. `count=1`, geen kandidatenkeuze: bij een naam als "Amsterdam" (bestaat
   ook in de VS, o.a. New York, Ohio, Missouri) werd stilzwijgend het eerste
   API-resultaat gepakt, zonder enige mogelijkheid dit op te merken of te
   corrigeren. Nu `count=7` met een keuzeprompt bij meerdere kandidaten,
   met dezelfde velden (naam/land/admin1/inwonertal) als elders in de suite.
3. Stille falen (`None, None`) met alleen een generieke foutmelding --
   onderscheidt nu expliciet "aanvraag mislukt" van "geen resultaten
   gevonden".

Getoetst tegen een nagebootste respons die exact het schema volgt van een
eerder in dit traject daadwerkelijk waargenomen, werkende Amsterdam-aanvraag
(naam/land/admin1/inwonertal/lat/lon) -- vier scenario's (meerdere
kandidaten, enkel resultaat, geen resultaten, netwerkfout) slagen allemaal.
De aanvraag zelf is NIET opnieuw live tegen Open-Meteo geverifieerd (geen
uitgaande netwerktoegang in deze omgeving); dit erft dezelfde blootstelling
die de rest van de suite al had als het schema ondertussen is gewijzigd.

`suite_smoke_test.py` en `verify.py` slagen ongewijzigd na deze fix.

## [2026-08-26, vervolg 4] Expliciete KNMI-modelkeuze voor voorspellingsaanvragen

Op verzoek gecontroleerd tegen Open-Meteo's eigen KNMI-documentatiepagina
(https://open-meteo.com/en/docs/knmi-api): KNMI's HARMONIE AROME is een
zuiver voorspellingsmodel (2 km resolutie voor Nederland/België, 2,5 dagen
eigen reikwijdte, "seamless" vult daarna aan met ECMWF tot 15 dagen) --
géén historisch archief. Dit raakt daarom uitsluitend de twee
voorspellingsaanvragen in deze suite, niet de historische ERA5-archief-
aanvraag die Klimatos voor de klimaattrendanalyse gebruikt (expliciet
gecontroleerd: geen `models=`-parameter in beide `archive-api.open-meteo.com`
aanroepen, ongewijzigd).

Beide voorspellingsfuncties vroegen voorheen geen expliciet model aan en
kregen dus Open-Meteo's eigen, niet-gedocumenteerde "Best Match"-keuze --
niet gegarandeerd het KNMI-model, ook niet voor een Nederlandse locatie.
Nu expliciet `models=knmi_seamless` toegevoegd aan:
- `hestia_model.py`'s `get_weather_forecast()`
- `Thermopoulos_Data_Engine.py`'s `fetch_hourly_forecast()`

`knmi_seamless` (niet de kale `knmi_harmonie_arome_netherlands`) gekozen
omdat die laatste na 2,5 dagen zonder voorspelling zou komen te zitten;
"seamless" vult automatisch aan met ECMWF voor de resterende dagen.

Getoetst (zonder live netwerktoegang, door de opgebouwde request te
inspecteren zonder te versturen): beide functies bevatten nu correct
`models=knmi_seamless` in de daadwerkelijk te versturen URL/parameters.
Niet opnieuw live tegen Open-Meteo geverifieerd. `suite_smoke_test.py`,
`verify.py` en Klimatos' eigen testsuite slagen ongewijzigd.

## [2026-08-26, vervolg 5] Regressie voorkomen: KNMI-model met automatische terugval buiten Nederland/België

Terechte vraag van de gebruiker legde een reële regressie in de vorige
wijziging bloot: KNMI's HARMONIE AROME dekt alleen Nederland/België (2 km)
en een breder "Centraal- en Noord-Europa tot IJsland"-gebied (5,5 km). Een
aanvraag voor een stad daarbuiten wordt door Open-Meteo niet stilzwijgend
opgevangen -- bevestigd via een echte, gedocumenteerde GitHub-issue
(open-meteo/open-meteo#1364): een model-aanvraag buiten het dekkingsgebied
geeft HTTP 400 terug met `{"error": true, "reason": "No data is available
for this location"}`. Zonder correctie zou elke niet-Europese stad na de
vorige wijziging op een crash zijn uitgelopen.

Opgelost zonder een geografische grens hard te coderen (fragiel, en zou uit
de pas kunnen gaan lopen als Open-Meteo KNMI's dekking ooit wijzigt): beide
functies proberen nu eerst `knmi_seamless`, en vallen bij precies deze
gedocumenteerde foutvorm automatisch terug op Open-Meteo's eigen
standaardmodel (door de `models`-parameter simpelweg weg te laten), met een
zichtbare melding in plaats van stilzwijgend.

Getest tegen nagebootste responsies die exact het bevestigde foutschema
volgen: een Nederlandse locatie (Amsterdam) krijgt KNMI in één aanroep,
zonder onnodige extra aanvraag; een niet-Europese locatie (New York) valt
correct terug op de tweede aanvraag en levert alsnog bruikbare data.
`suite_smoke_test.py`, `verify.py` en Klimatos' eigen testsuite slagen
ongewijzigd.

## [2026-08-27] Nieuwe rapportgenerator: generate_klimatos_report.py

Nieuwe module, in dezelfde stijl als generate_event_report.py (vaste
sectievolgorde, uitsluitend feitelijke waarden, geen aanbevelingen), maar
voor Klimatos' eigen klimaattrend-uitvoer (jaarlijkse extremen,
evenement-venster, EHS/EHE/klinisch-criterium-evolutie, collapse-risico,
ziekenhuisopnames, leefbaarheid) in plaats van één HESTIA-populatierun.
Neemt exact dezelfde DataFrames die save_results() al naar Excel schrijft
(annual, event_summary_df, ehs_summary_df, admissions_df, liveability_df,
accel_summary_df, meta) -- geen aparte herberekening nodig.

Sectie 7 (EHE/klinisch criterium, marge-tot-drempel) hergebruikt dezelfde
berekening als hestia_bridge.margin_to_threshold_stats() en Klimatos_
ClimateShift.py's eigen _ehe_margin_stats() -- een derde, kleine, losstaande
kopie (_local_margin_stats), bewust geen import: deze rapportgenerator moet
blijven werken zolang Klimatos zelf werkt, ook zonder HESTIA aanwezig.

Klimatos_ClimateShift.py's eigen main() vraagt nu ook "Generate event report
(Markdown)?", naast de bestaande Excel-export -- zelfde vraagpatroon als
run_hestia.py's eigen rapportprompt.

Geverifieerd: (1) volledig getest met synthetische data die de echte
kolomstructuren van elke DataFrame nabootst; (2) het daadwerkelijke
Utrecht Marathon-rapport gegenereerd uit de werkelijke consoleuitvoer van
een live run -- de marge-tot-drempel-cijfers in sectie 7 zijn expliciet
geverifieerd exact overeen te komen met de door de gebruiker gerapporteerde
waarden (T_rect-mediaan, CO-reserve-mediaan, dichtstbijzijnde punt), niet
benaderd; (3) end-to-end getest binnen de echte main()-flow (zowel de
"ja"- als de "nee"-route), met de daadwerkelijk gegenereerde rapporttekst
gecontroleerd. suite_smoke_test.py, verify.py en Klimatos' eigen
testsuite (test_end_to_end.py, aangepast met de nieuwe prompt in de
gescripte antwoordenreeks) slagen allemaal.

## [2026-08-28] Documentatiebestanden hersteld na eigen opruimfout

Bij twee eerdere opruimstappen deze sessie werd per ongeluk een te brede
`rm`-jokertekenreeks (`*.md`) gebruikt binnen de suite-map zelf -- bedoeld
om tijdens tests gegenereerde rapportbestanden (bijv.
`Klimatos_Rapport_TestCity_*.md`) op te ruimen, maar deze ving daarbij ook
`MANIFEST.md`, `README.md`, `PROJECT_INSTRUCTIONS.md` en dit
wijzigingslog-bestand zelf. Hersteld: de eerste drie uit de oorspronkelijke,
door de gebruiker geüploade baseline-zip (die door deze sessie nooit is
bewerkt); dit bestand door het origineel opnieuw te combineren met alle
sessie-eigen vermeldingen hierboven, teruggehaald uit de eigen
gespreksgeschiedenis. `MANIFEST.md` kreeg bovendien een addendum-sectie
("Added during Klimatos integration") die alle sinds de baseline
toegevoegde bestanden documenteert.

## [2026-08-28, vervolg] Sectie 7-verduidelijking: afstand-tot-drempel toegevoegd

Terechte vraag van de gebruiker: waarom stonden identieke cijfers onder
zowel "EHE-drempel" als "Klinische drempel" in gegenereerde rapporten?
Correct gedrag, geen bug -- beide subsecties toetsen dezelfde onderliggende
steekproef (T_rect, CO_reserve), dus mediaan- en dichtstbijzijnde-punt-
waarden zijn terecht gelijk. Wat ontbrak: de afstand van elke mediaan tot
de SPECIFIEKE drempel van die subsectie (bijv. "+0,40 t.o.v. de 39,5-graden-
drempel" versus "+1,40 t.o.v. de 40,5-graden-drempel" voor exact dezelfde
39,10-mediaan) -- aanwezig in het HESTIA-rapport-format, per ongeluk
weggelaten bij het bouwen van generate_klimatos_report.py.

Toegevoegd: dezelfde "t.o.v. de X-drempel"-annotatie als de HESTIA-kant,
plus een korte toelichtende zin bovenaan sectie 7 die uitlegt waarom de
ruwe getallen kunnen overlappen. Geverifieerd tegen het Utrecht Marathon-
rapport: de herberekende afstanden (+0,40 resp. +1,40 graden voor dezelfde
39,10-mediaan) komen exact overeen met wat in de oorspronkelijke
console-uitvoer van de gebruiker stond. suite_smoke_test.py, verify.py en
Klimatos' eigen testsuite slagen ongewijzigd.

## [2026-08-28, vervolg 2] Derde rapportgenerator (proefversie): generate_recommendation_report.py

Op verzoek: een adviesrapport, expliciet een ANDER documenttype dan de
twee bestaande feitenrapporten (generate_event_report.py, generate_
klimatos_report.py, beide bewust "geen aanbevelingen"). Deze nieuwe module
bevat wel een afweging en aanbeveling, uitsluitend gericht op
tijdstip-interventies (starttijd, seizoen/datum) -- expliciet niet over
andere maatregelen (drinkposten, medische bezetting).

Scope bewust beperkt op verzoek van de gebruiker (zonder extra modelrun):
- Starttijd-verschuiving: gekwantificeerd met Klimatos' eigen, al
  berekende vroege-start-scenario's (geen aparte run nodig).
- Seizoen/datum-verschuiving: uitdrukkelijk kwalitatief in deze versie --
  een kwantitatieve vergelijking vereist een nieuwe event-window-run
  geankerd op een andere datum, wat deze proefversie bewust niet doet. Het
  rapport benoemt dit gat expliciet in plaats van het te verbergen.

Gegenereerd als concreet voorbeeld: het Utrecht Marathon-adviesrapport,
met dezelfde geverifieerde cijfers als het eerdere feitenrapport (25%
EHS-reductie, 10-11% collapse-risico-reductie bij een verschuiving van
10:30 naar 09:00).

## [2026-08-28, vervolg 3] Baseline/referentieperiode expliciet benoemd in het adviesrapport

Terechte constatering van de gebruiker: sectie 2 van generate_recommendation_
report.py toonde een "Baseline"- en "Referentie"-kolom zonder ooit te
vermelden welke jaren die precies dekken. Toegevoegd: twee nieuwe optionele
parameters (baseline_period, reference_period), een definiërende zin
bovenaan sectie 2 ("Baseline = 1951-1980... Referentie = 1995-2025..."), de
jaartallen in de tabelkoppen zelf, en dezelfde vermelding bij de
referentiewaarden in sectie 3. Utrecht Marathon-rapport opnieuw
gegenereerd met deze correctie.

## [2026-08-28, vervolg 4] Uitgebreid hoofdstuk toegevoegd: kernvraag over verantwoorde datum

Op verzoek: een nieuw, substantieel hoofdstuk (## 4, met vijf subsecties)
in generate_recommendation_report.py, dat de vraag "is de huidige datum
nog verantwoord in [naaste doeljaar]" behandelt -- expliciet met de
kanttekening dat "verantwoord" geen modeluitkomst is maar een
risicotolerantie-vraag, die het model niet zelf beantwoordt.

Structuur: 4.1 de vraag scherp gesteld, 4.2 wat pleit voor zorg
(hergebruikt ehe_evidence + het punt dat het collapse-risico al vandaag
bestaat, niet pas in de toekomst), 4.3 wat pleit voor voorzichtigheid met
de conclusie (trend-significantie, PROVISIONAL-kalibratie inclusief
expliciete extrapolatie-kanttekening, klein EHE-ensemble), 4.4 het
kernpunt dat het verschil tussen nu en het naaste doeljaar bescheiden is
(het risico zit er dus al grotendeels vandaag in), 4.5 een expliciete
grens: wat het model wel en niet kan beantwoorden.

Drie nieuwe optionele parameters toegevoegd aan de functie-signatuur
(event_window_trend_significant, collapse_calibration_note) zodat het
sjabloon generiek blijft -- niet Utrecht-specifieke tekst hardgecodeerd.

Alle bestaande secties hernummerd (was 4-8, nu 5-9) met alle interne
kruisverwijzingen consistent bijgewerkt en stuk voor stuk gecontroleerd
(geen dubbele "sectie 5"-verwijzingen naar twee verschillende secties).
Utrecht Marathon-rapport opnieuw gegenereerd en het nieuwe hoofdstuk
volledig doorgelezen vóór oplevering. suite_smoke_test.py en verify.py
slagen ongewijzigd.

## [2026-08-29] Grote reconciliatie: de Streamlit-tak (PYROX_suite_5_apps_v6) samengevoegd

De gebruiker wees erop dat er ná de omschakeling naar deze gecombineerde,
niet-Streamlit-suite nog Nederlandse tekst en gemiste EHS/EHE-verbeteringen
aanwezig waren. Onderzoek in de eigen gespreksgeschiedenis bevestigde: er
was een doorlopende, samenhangende ontwikkellijn over minstens acht
sessies (2-20 augustus) op de Streamlit-tak, die nooit is samengevoegd met
deze suite. De gebruiker gaat de Streamlit-apps zelf niet meer gebruiken
(te traag), maar de wetenschappelijke fixes zaten in de GEDEELDE kernbestanden.

**Rechtstreeks overgenomen** (geen bekend conflict met deze suite se eigen
werk): `hestia_model.py`, `HESTIA_CVR_Module_v2.py`, `HESTIA_CVR_Console.py`,
`HESTIA_ControlFailure_Module.py`, `individual_engine.py`, `pyrox_groups.py`,
`local_storage.py` (bleek bij nader inzien GEEN Streamlit-specifieke code --
pure lokale JSON-opslag voor individual_engine.py, ten onrechte eerder als
UI-specifiek bestempeld).

**Bevestigde inhoud van deze overname** (rechtstreeks in de code geverifieerd,
niet aangenomen): de CO_reserve-NaN-na-stop-fix (`[fix, 2026-08-16]`), de
CO_reserve-tekenomkering-fix bij extreme hittestress (`[fix, 2026-08-17]`),
de niet-geseede-RNG-fix in `individual_engine.py`, de volledige EHS/EHE/EAC-
herdefinitie (EAC = Exercise-Associated Collapse, een derde, niet eerder
geïmplementeerd eindpunt), de clo_value-fix (0,5->0,2), de ehbo->first_aid-
hernoeming, en de correctie van drie PYROX-populatiegroepsdefecten
(dubbeltelling van weerstand, onbereikbare drempels, "letterlijke immuniteit"
bij duursporters -- bevestigd: 0 groepen met max_acclimatization_capacity=1.0
na de fix).

**Tweerichtingssamengevoegd** (beide kanten hadden unieke, echte inhoud):
`Thermopoulos_Data_Engine.py` -- de Streamlit-tak had een defensieve
try/except om TimezoneFinder (deploy-robuustheid) en de volledige
vertaalslag; deze suite had de KNMI-modelkeuze-met-terugval-fix. Beide
behouden.

**Ongewijzigd gelaten, na verificatie geen conflict**: `hestia_bridge.py`
(deze suite se eigen, Streamlit-vrije versie -- de analyselaag zelf bleek
identiek aan de Streamlit-tak se versie, en verwacht al correct `eac_hit()`
uit `individual_engine.py`), `pyrox_model.py` (checksum identiek).

**Bewust NIET meegenomen**: de vijf Streamlit-apps zelf (`app.py`,
`app_athletes.py`, `app_beleid.py`, `app_klimaatprojectie.py`,
`app_persoonlijk.py` -- 41 resp. 32 resterende Nederlandse tekstregels
zaten vrijwel uitsluitend in de laatste twee, die toch worden losgelaten),
en negen ondersteunende bestanden die geen enkel van de drie behouden
instapscripts (`run_hestia.py`, `run_pyrox.py`, `Klimatos_ClimateShift.py`)
importeert (`decision_support.py`, `evidence.py`, `experimental_risk.py`,
`gpx_route.py`, `terrain_lookup.py`, `individual_report.py`,
`report_generator.py`, `climate_projection_worker.py`, `pyrox_bridge.py`,
`plain_view.py`, `loop_view.py`) -- beschikbaar als latere aanvulling,
niet vereist voor de huidige validatiewerkzaamheid.

**Bekende, nog openstaande leemte**: `intercept_estimation.py` (het losse
herkalibratie-werkbankscript waar `hestia_model.py`'s eigen commentaar nog
naar verwijst) is NIET bijgewerkt -- geen recentere versie was in deze
upload aanwezig. De huidige, oudere versie in deze suite is vermoedelijk
niet meer volledig consistent met de REF_CONDITIONS_BY_KEY-architectuur.

**Resterende Nederlandse tekst, bewust**: de drie rapportgeneratoren
(`generate_event_report.py`, `generate_klimatos_report.py`,
`generate_recommendation_report.py`) produceren doelbewust Nederlandstalige
rapporten voor Nederlandse belanghebbenden (GHOR, Le Champion) -- dit is
geen vertaalgat maar de daadwerkelijke, bedoelde uitvoer. Idem één regel in
`hestia_bridge.py`'s `format_margin_lines()`. De onderliggende CODE zelf
(niet de rapporttekst) is na deze reconciliatie volledig Engelstalig,
geverifieerd met een uitgebreide, karakteristiek-Nederlandse woordenlijst
over alle bestanden.

Getest: `suite_smoke_test.py`, `verify.py` (inclusief de PYROX-groepsfix-
bevestiging "matches the corrected paper"), en drie meegenomen testbestanden
uit de Streamlit-tak (`test_cvr_freeze_fix.py` -- expliciete monotonie-
toets tot -7,73 bij extreme hittestress; `test_individual_engine.py`;
`test_uncertainty.py`) slagen allemaal. Klimatos' eigen testsuite
(`test_end_to_end.py`, `test_new_modules.py`, `test_rate_limit.py`) slaagt
ongewijzigd tegen deze bijgewerkte kern.

## [2026-08-29, vervolg] README.md bijgewerkt: Klimatos ontbrak volledig

Terechte constatering van de gebruiker: README.md noemde Klimatos nergens --
het was nog exact de tekst van de oorspronkelijke 2026-07-27 "zonder
streamlit"-baseline, van vóór de Klimatos-integratie. Bijgewerkt: Klimatos
als volwaardig derde onderdeel toegevoegd aan de inleiding, de bestandslijst
(inclusief `klimatos_ehs_worker.py`, `hestia_bridge.py`, beide
Klimatos-rapportgeneratoren, `HEATLim.py`, `individual_engine.py`,
`local_storage.py`, die er ook nog niet in stonden), een eigen quickstart-
regel (geen Thermopoulos_*.xlsx nodig, in tegenstelling tot PYROX/HESTIA),
het architectuurdiagram, en de statussectie.

Bijkomende ontdekking tijdens deze controle: `TECHNICAL_REFERENCE.md`, waar
README.md meermaals naar verwijst, **bestaat nergens** -- niet in deze suite,
niet in een van beide uploads die tot dit punt zijn ontvangen. Expliciet
vermeld in het README zelf in plaats van de kapotte verwijzingen stilzwijgend
te laten staan.

## [2026-08-30] TECHNICAL_REFERENCE.md written -- did not exist before this date

README.md referenced this file throughout (architecture overview, model
equations, glossary, deviations from the published paper §10) since at
least the 2026-07-27 baseline, but it was never actually included in any
upload received in this whole project. Written now, directly from the
codebase (every equation, threshold, and citation checked against source,
not reconstructed from memory) rather than left as a standing gap.

Covers: architecture overview (including why hestia_bridge.py exists
separately and the three report generators' differing philosophies),
PYROX's control-theoretic model (symbol reference, the three
population-group defects fixed 2026-08, the "illustrative not validated"
labelling that applies to most of its 23 groups), HESTIA's JOS-3 + CVR
module (the clo_value history, the CO_reserve NaN and sign-inversion
fixes, the apparent-wind correction), the EHS/EHE/EAC three-endpoint
framework with its temporal windows and the EHS-naming-collision caveat,
the COLLAPSE_ENDPOINTS calibration architecture and its N=200 provisional
status, the TCF metric, Klimatos' data sources/methodology (sliding
windows, Theil-Sen/Mann-Kendall, UHI, the event-window vs annual-maxima
divergence, the margin-to-threshold calculation), a key-equations
quick-reference, a full glossary, known open gaps, and an explicit "what
this suite is not" section.

## [2026-08-30, vervolg] Word-export (.docx) toegevoegd voor alle drie rapportgeneratoren

Nieuwe, gedeelde stijllaag (`report_to_docx.py` + `build_report_docx.js`,
docx-js/npm) die de bestaande Markdown-uitvoer van alle drie
rapportgeneratoren omzet naar een strak, presentatiegeschikt Word-document
-- geen drie keer losse implementatie, één parser + één renderer voor het
suite-eigen, consistente Markdown-dialect.

Twee visueel duidelijk onderscheiden stijlen, aansluitend bij het al
bestaande onderscheid in de Markdown-versie zelf:
- **"facts"** (`generate_event_report.py`, `generate_klimatos_report.py`):
  blauw-groen accent, "FEITENRAPPORT"-badge.
- **"advisory"** (`generate_recommendation_report.py`): warm amberkleurig
  accent, "ADVIESRAPPORT"-badge -- op het oog meteen te onderscheiden van
  een feitenrapport, niet alleen aan de tekst.

Titelpagina met accentbalk, kleurgemarkeerd disclaimer-kader, koppen met
accentkleur en onderstreping, tabellen met gekleurde koprij, paginanummers
in de voettekst. Vereist Node.js + de npm-package `docx` (nieuw
`package.json` in de suite-root; `npm install` voordat dit werkt).

Gekoppeld aan de bestaande "Generate event report (Markdown)?"-vragen in
zowel `run_hestia.py` als `Klimatos_ClimateShift.py`'s eigen `main()`, met
een aparte "Also export as Word (.docx)?"-vervolgvraag -- een mislukte
Word-export raakt de al geschreven Markdown-versie niet.

Getest: alle vijf pagina's van het adviesrapport en het Klimatos-feitenrapport
visueel gerenderd en gecontroleerd (titelpagina, genummerde secties met
subsecties, tabellen met meerregelige cellen, geneste opsommingen, een
bold-geleide alinea die niet volledig vetgedrukt is -- een reële parserfout
hierin gevonden en gefixt vóór oplevering). End-to-end getest binnen de
echte `main()`-flow van Klimatos (beide nieuwe prompts met "ja"
beantwoord, het daadwerkelijke .docx-bestand gecontroleerd). Klimatos'
eigen testsuite en `verify.py` slagen ongewijzigd.

**Les herhaald, ditmaal zonder gegevensverlies**: bij het opruimen van
testbestanden tijdens deze wijziging is opnieuw per ongeluk een brede
`*.md`-jokertekenreeks gebruikt in de suite-root, waardoor alle vijf
documentatiebestanden opnieuw werden verwijderd. Ditmaal hersteld uit de
laatst succesvol afgeleverde zip (die dateert van vlak vóór deze fout),
in plaats van handmatige reconstructie. Opruimopdrachten in dit traject
gebruiken voortaan uitsluitend specifieke bestandsnamen, nooit meer een
kale `*.md`-patroon.

## [2026-08-30, vervolg 2] Vierde rapportgenerator: generate_pyrox_report.py

PYROX had, in tegenstelling tot HESTIA en Klimatos, geen enkel bestandsmatig
rapport -- alleen een consoletabel die verdween zodra het venster sloot.
Nieuwe module, zelfde "alleen feiten"-filosofie als de andere twee, maar nu
mét alle zes beschikbare PYROX-plots (pyrox_plots.py) ingesloten, elk met
een toegankelijke, in gewone taal geschreven verklaring: divergentie tussen
groepen, het twee-lussen-detail voor de meest kwetsbare groep in deze
specifieke run, het risico-overzicht per dag, de voorspellingsonzekerheid
(indien van toepassing), de drie theoretische gedragsregimes, en de vaste
Parijs-2003-validatie.

Groepselectie voor de plots (niet alle 23 passen leesbaar op één as) is
DATAGEDREVEN, niet hardgecodeerd: de meest getroffen groepen (kleinste marge
tot de eigen kritieke grens, of een daadwerkelijk bereikt noodgeval) plus de
minst getroffen groep ter referentie -- past zich dus aan elke run aan.

report_to_docx.py en build_report_docx.js uitgebreid met afbeeldings-
ondersteuning (`![...](...)`-syntax, ImageRun in docx-js) om deze plots ook
in het Word-document te tonen -- de derde en vierde generator delen nu
dezelfde stijllaag als de eerste twee.

Twee echte fouten gevonden en gefixt tijdens het bouwen:
1. Een parser-onvolledigheid: afbeeldingsverwijzingen werden aanvankelijk
   niet herkend.
2. Een reëel Word-renderprobleem: een tabelrij met een naar twee regels
   omgebroken groepsnaam ("Cardiovascular Disease") werd door Word over een
   paginagrens gesplitst, met een spookrij ("Disease", lege cellen) tot
   gevolg -- opgelost door `cantSplit: true` op elke tabelrij te zetten, dus
   rijen verplaatsen nu in hun geheel naar de volgende pagina in plaats van
   te breken.

Gekoppeld aan `run_pyrox.py`'s `main()` (die voorheen geen enkele
interactieve vraag had) met dezelfde twee prompts als de andere drie
ingangen. Getest: alle zeven pagina's van een compleet voorbeeldrapport
(23 groepen, alle zes plots) visueel gerenderd en gecontroleerd; volledige
"ja, ja"-doorloop binnen de echte `main()`-flow bevestigd. Alle acht
bestaande testsuites (vijf HESTIA/PYROX, drie Klimatos) slagen ongewijzigd.

## [2026-08-31] Node-terugvalmechanisme na een reëel, herhaald WinError-2-probleem

Bij de gebruiker: Node.js correct geïnstalleerd en bevestigd werkend in een
vers geopend terminalvenster (`node --version` gaf een versienummer), maar
de Word-export vanuit Spyder bleef falen met exact dezelfde melding
(`[WinError 2] Het systeem kan het opgegeven bestand niet vinden`). Oorzaak:
Spyder draaide al vóór de Node.js-installatie, en had daardoor -- net als de
eerder aangetroffen terminalvensters -- een verouderde PATH die nooit is
ververst zonder herstart van de hele applicatie.

`report_to_docx.py`'s `_resolve_node_executable()` toegevoegd: probeert
eerst gewoon `node` via PATH (de normale weg), en valt bij het exacte
WinError-2-symptoom automatisch terug op de standaard Windows-
installatielocaties (`C:\Program Files\nodejs\`,
`C:\Program Files (x86)\nodejs\`, `%LOCALAPPDATA%\Programs\nodejs\`) voordat
het opgeeft met een duidelijke, actiegerichte foutmelding in plaats van de
kale WinError-2-tekst.

Getest: drie scenario's (normale PATH-resolutie, terugval naar
standaardlocatie, nergens vindbaar) elk expliciet getoetst; volledige
end-to-end Word-export opnieuw bevestigd. suite_smoke_test.py slaagt
ongewijzigd.

Herstart van de applicatie die de export aanroept (Spyder, in dit geval)
blijft de eerste, meest betrouwbare stap na een Node.js-installatie -- deze
toevoeging is een vangnet voor de tussentijd, geen vervanging daarvan.

## [2026-08-31, vervolg] node_modules gebundeld in de suite-zip zelf

Bij de gebruiker: een verse, opnieuw uitgepakte kopie van de suite (rev02,
naast de eerdere rev01) gaf een nieuwe fout -- "Cannot find module 'docx'".
Oorzaak: de vorige zip sloot node_modules bewust uit ("dat hoort lokaal
geinstalleerd te worden"), maar dat betekent dat ELKE nieuw uitgepakte kopie
opnieuw `npm install` nodig had -- een reeel, terugkerend struikelblok,
juist gezien de eerder genoemde zorg over administratieve belasting.

Twee wijzigingen:
1. `report_to_docx.py` controleert nu vooraf, in gewone taal, of
   `node_modules/docx` aanwezig is, in plaats van pas te falen met een kale
   Node.js-stacktrace ("Cannot find module 'docx'", een require()-callstack)
   die voor een niet-programmeur weinig zegt.
2. **`node_modules/` wordt voortaan gewoon meegepakt in de suite-zip zelf**
   (~11 MB, een kleine toevoeging naast de rest van de suite) -- een verse
   uitpak-actie werkt daardoor meteen, zonder enige `npm install`-stap.
   `npm install` is alleen nog nodig als iemand losse bestanden uit de
   suite kopieert zonder de hele map, of als node_modules om een andere
   reden ontbreekt/corrupt raakt.

Getest: beide scenario's (met en zonder node_modules aanwezig) expliciet
getoetst -- met: export slaagt zoals verwacht; zonder: de nieuwe, duidelijke
Python-melding verschijnt in plaats van de Node-stacktrace.
suite_smoke_test.py slaagt ongewijzigd.

## [2026-09-01] Alle elf HESTIA-plots ingesloten in het feitenrapport, elk met toegankelijke verklaring

Terechte constatering van de gebruiker (aan de hand van een echte, door
run_hestia.py gegenereerde HESTIA_Report_Utrecht_2026-05-31_n250.docx): de
afbeeldingsondersteuning die eerder specifiek voor generate_pyrox_report.py
werd gebouwd, was nooit teruggekoppeld naar generate_event_report.py --
terwijl run_hestia.py's "Generate plots?"-vraag al die tijd elf PNG's
genereerde die nergens in het rapport zelf terechtkwamen.

`generate_report()` kreeg een nieuwe, optionele parameter `plot_paths`.
Nieuwe sectie 10 ("Grafieken") matcht elk meegegeven pad op zijn vaste
HESTIA_plotN_-naamgeving en toont elke grafiek met een eigen, in gewone
taal geschreven verklaring (opgesteld na het navlooien van elke
plotfunctie se eigen docstring in hestia_plots.py/hestia_model.py, niet
generiek geraden) -- van de bevolkingsbrede tijdreeksen (plot 1-2), via de
verdelingen en de conjunctieve spreidingsplot (plot 3-6), tot de extreme-
cohort-tijdreeksen en de drie cumulatieve-dosismaten (plot 7-11, inclusief
de eerder toegevoegde episode-telling in plot 8).

`run_hestia.py` aangepast zodat `paths` altijd bestaat (lege lijst als de
plot-vraag met "nee" is beantwoord) en wordt doorgegeven aan
`generate_report()`. Ontbrekende plots (vraag niet bevestigend beantwoord)
geven een expliciete "niet gegenereerd voor deze run"-vermelding in plaats
van de sectie stilzwijgend leeg te laten.

Getest: een volledige, echte Monte Carlo-run (n=60) met alle elf plots
gegenereerd, ingesloten in zowel het Markdown- als het Word-rapport,
visueel gecontroleerd (titel, bijschrift, drempellijnen, legenda's) op
meerdere pagina's. suite_smoke_test.py slaagt ongewijzigd.

Openstaand, niet in deze wijziging meegenomen: generate_klimatos_report.py
heeft dezelfde soort gat -- Klimatos_ClimateShift.py genereert tientallen
eigen plots (jaarextremen, opwarmingsstrepen, de T_rect/CO_reserve-
spreidingsplot, EHS-evolutie, leefbaarheid, ...) waarvan er nog geen enkele
in dat rapport wordt getoond. Dat vraagt eerst een zorgvuldige selectie
(niet alle tientallen zijn even relevant voor een enkel rapport) voordat
dezelfde behandeling zinvol is toe te passen.

## [2026-09-01] Klimatos-rapport uitgebreid met plots, en twee reële kolomnaam-bugs gevonden en gefixt

Zelfde behandeling als het eerdere HESTIA-plots-werk, maar dan voor
Klimatos: van de 18 beschikbare plotfuncties (potentieel 40+ PNG's per
volledige run) is een doordachte selectie van 12 gemaakt -- één of enkele
per relevante sectie, geen dump. Sectie 2 (tijdreeks-trend per variabele,
4x), sectie 3 (versnellingscheck), sectie 4 (evenement-venster-trend per
variabele, 3x), sectie 5 (EHS-evolutie), sectie 7 (T_rect/CO_reserve-
spreidingsplot), sectie 8 (ziekenhuisopnames-verhouding), sectie 9
(leefbaarheidsbalk). Elk bijschrift geschreven na het navlooien van de
daadwerkelijke docstring van die plotfunctie.

`generate_klimatos_report()` kreeg een nieuwe, optionele `plot_paths`-
parameter en een gedeelde `_embed_plot()`-helperfunctie (zelfde patroon als
het HESTIA-rapport). Gekoppeld aan Klimatos_ClimateShift.py's eigen
main(), die de plot_paths-lijst al opbouwde voor de "Plots:"-consoleregel
maar nog nooit doorgaf aan de rapportgenerator.

**Twee reële, al langer bestaande bugs gevonden tijdens het testen met de
ECHTE build_event_summary()-functie (niet zelfgemaakte testdata zoals
eerdere tests toevallig gebruikten):** sectie 4 in zowel
generate_klimatos_report.py als generate_recommendation_report.py gebruikte
verkeerde kolomnamen (`reference_mean`/`trend_slope`/`proj_2030` in plaats
van de daadwerkelijke `trend_mean`/`slope_degC_per_yr`/`projected_2030`),
waardoor de Referentie/Trend/2030/2035/2040-kolommen altijd "n.b." toonden
zodra dit gevoed werd met build_event_summary()'s echte uitvoer -- alleen
Baseline (toevallig wel de juiste kolomnaam) werkte. Dit was nooit eerder
opgemerkt omdat alle voorgaande tests handmatig gebouwde testdata gebruikten
die (met dezelfde verkeerde aannames als de rapportcode zelf) toevallig wél
matchte. Beide bestanden gecorrigeerd.

Getest: alle 12 plots gegenereerd met de echte Klimatos-plotfuncties tegen
realistische synthetische data (vereiste een aantal aanvullingen op de
testdata: heat_degree_days, n_days_over_mmt, de hrsBelow_/hrsNonLiv_/
hrsNonSurv_-kolommen per leefbaarheidsprofiel, en een volledige ehs_res-
structuur met low/high-scenario's via de echte build_ehs_summary()). Alle
11 pagina's van het resulterende Word-document stuk voor stuk visueel
gecontroleerd -- precies deze controle legde de kolomnaam-bug bloot.
suite_smoke_test.py en Klimatos' eigen testsuite slagen ongewijzigd na de
fix.

## [2026-09-01, vervolg] Sectie 3-bug gevonden in echt Utrecht-rapport: 27 rijen i.p.v. 1

Bij het doorlezen van een daadwerkelijk door de gebruiker gegenereerd
Klimatos-rapport (Utrecht Halve Marathon, 2026-09-01): sectie 3
(Trendversnelling) toonde 27 bijna-identieke rijen voor T_air_max, elk met
"Breekpunt: n.b.". Oorzaak, tweeledig: (1) accel_df bevat bewust één rij
per GETEST kandidaat-breekpunt (de volledige scan, ook gebruikt voor de
plot) -- de rapporttabel filterde daar nooit op, en toonde dus de hele
scan in plaats van één samenvattende rij per variabele; (2) de kolomnaam
was verkeerd (`breakpoint_year` in de rapportcode, `breakpoint` in de
daadwerkelijke data) -- exact dezelfde soort fout als eerder vandaag bij
event_df gevonden.

Gefixt: gefilterd op `is_best==True` (de vlag die accel_summary_df's eigen
bouwcode al meegeeft) voordat de tabel wordt opgebouwd, en de juiste
kolomnaam gebruikt. Getest met een nagebootste volledige scan (27
kandidaten, 1 gemarkeerd als beste) -- de tabel toont nu correct één rij.

Ook gecontroleerd, GEEN bug: "Vroege start: n.b." in sectie 5/6 van
hetzelfde rapport -- kolomnamen kloppen, dit betekent legitiem dat deze
specifieke run geen vroege-start-scenario had berekend.

suite_smoke_test.py en Klimatos' eigen testsuite slagen ongewijzigd.

## [2026-09-05] Twee reële crashes uit het veld gevonden en gefixt

Beide gevonden via daadwerkelijke Windows-runs van de gebruiker, niet in
een test opgemerkt.

**Klimatos_ClimateShift.py**: een volledige run (75 jaar archiefdata,
3+ minuten, niet gecachet) crashte met `OSError [Errno 22] Invalid
argument` bij het wegschrijven van één specifieke plot
(`plot_event_warming_stripes_*.png`), na twee andere plots in dezelfde
map en dezelfde lus-iteratie die wel al geslaagd waren -- dat wijst op een
eenmalige, omgevingsgebonden hik (vermoedelijk antivirus-realtimescan of
cloud-sync die kortstondig het net aangemaakte bestand blokkeerde) in
plaats van een deterministische codefout, mede omdat exact dezelfde code
al eerder een keer zonder problemen had gedraaid.

Nieuwe `_safe_plot()`-helperfunctie toegevoegd; alle 17 plotoproepen in
`main()` gaan er nu doorheen. Eén mislukte plot geeft voortaan een
waarschuwing in de log en de run gaat door -- in plaats van 3+ minuten aan
niet-gecachete resultaten te verliezen over het falen van één enkel
plotbestand.

**HESTIA_CVR_Console.py**: een mild, kort scenario (Amsterdam, 1,5 uur,
MET 9,8) crashte met `ValueError: cannot convert float NaN to integer` in
`_bar()`, aangeroepen voor de dehydratie-mediaan. Oorzaak: bij dit milde
scenario kwam niemand in de subgroep waarover die specifieke
dehydratie-percentiel wordt berekend (dezelfde categorie als de al
bestaande "0% crossed any collapse-risk trigger"-situatie elders in
dezelfde module) -- de bovenliggende berekening gaf terecht NaN terug,
maar `_bar()` was daar niet tegen afgeschermd.

`_bar()` beschermd tegen NaN (beschermt in één keer alle 16 aanroepen in
dit bestand). De twee dehydratie-printregels tonen nu expliciet "n.v.t.
(geen deelnemers in deze subgroep)" in plaats van het verwarrende, niet-
crashende maar onduidelijke "nan%".

Getest: exacte crash-scenario's nagebouwd voor beide fixes (het precieze
foutbericht van elke crash gereproduceerd en bevestigd verholpen); een
normaal, niet-edge-case-scenario getest om te bevestigen dat de output
daar letterlijk ongewijzigd blijft. suite_smoke_test.py,
test_end_to_end.py en test_cvr_freeze_fix.py slagen alle drie ongewijzigd
na beide fixes.

## [2026-09-05, vervolg] Derde NaN-gerelateerde crash uit hetzelfde milde scenario

Zelfde Amsterdam-scenario (1,5 uur, MET 9,8) als de vorige twee fixes,
verder doorgelopen na de dehydratie-fix: crashte nu bij het genereren van
plot 4 (`plot_collapse_risk_distribution` in hestia_plots.py) met
`ValueError: autodetected range of [nan, nan] is not finite`. Zelfde
grondoorzaak als de dehydratie-crash: `stats['p_collapse_per_sim']` was in
dit milde scenario volledig NaN (0% overschreed enige collapse-risico-
drempel), en matplotlib's `hist()` kan geen bereik bepalen over een
volledig NaN-array.

De functie checkte al netjes of de sleutel `p_collapse_per_sim` uberhaupt
ontbrak (retourneert dan None, en de aanroepende
`generate_population_plots()` slaat een None-plot al correct over) --
alleen de "sleutel aanwezig maar volledig NaN"-situatie was niet gedekt.
Uitgebreid met dezelfde None-teruggave voor dat geval.

Getest: alle-NaN (nieuwe crash, nu correct overgeslagen), ontbrekende
sleutel (bestaand gedrag, ongewijzigd), volledig normale data (plot nog
gewoon gemaakt), en gedeeltelijk NaN -- sommige deelnemers wel geldige
waarden, anderen niet (plot terecht nog gemaakt, met alleen de geldige
deelnemers). Volledige pijplijn opnieuw getest met een realistisch mild
scenario: alle 11 HESTIA-plots gegenereerd zonder crash.
suite_smoke_test.py slaagt ongewijzigd.

## [2026-09-05, vervolg] Vierde bevinding: geen crash, maar een reële, stille datacorruptie in populatiestatistieken

Ontdekt door de gebruiker zelf, via een grondige blik op alle plots en het
rapport van dezelfde Amsterdam-run (1,5 uur, MET 9,8, n=1000): het rapport
toonde "n.b." voor alle populatiebrede T_rect-statistieken (gemiddelde,
90%-interval, P97,5, P99), en de bijbehorende plots (kern-temperatuur
tijdreeks, leefbaarheidspercentages, en de meeste extreme-cohort-grafieken)
waren volledig leeg of plat -- zonder dat er ergens een foutmelding of
crash was. Dit is een ander, in potentie ernstiger soort probleem dan de
eerdere drie fixes: geen crash, maar **stille dataverlies**.

Oorzaak, bevestigd door het ruwe Monte Carlo-resultatenbestand
(HESTIA_MonteCarlo_*.xlsx) direct te inspecteren: `mean_t_rect`,
`lower_t_rect`, `upper_t_rect`, `t_rect_p975`, `t_rect_p99` (en, met
dezelfde kwetsbaarheid: `mean_water`, `lower/upper_water`, `mean_rpe`,
`lower/upper_rpe`, `percent_stopped`, `percent_first_aid`,
`percent_unliveable`) werden berekend met de gewone `np.mean`/
`np.percentile` -- niet de NaN-veilige `np.nanmean`/`np.nanpercentile`.
Als ook maar ÉÉN van de 1.000 deelnemers een NaN heeft op een bepaald
tijdstip (bijvoorbeeld door een randgeval-fout in de simulatie voor dat
ene profiel), wordt de HELE populatiestatistiek op dat tijdstip NaN --
voor alle 1.000 deelnemers tegelijk, ook al hebben de overige 999 een
volkomen geldige waarde. Elders in dezelfde functie (de kwetsbare-
staartgroep-selectie, `np.nanmax`/`np.nanpercentile`) was dit al wél
correct NaN-veilig -- een inconsistentie binnen één en dezelfde functie.

Alle bovengenoemde regels omgezet naar hun NaN-veilige variant. Getest:
een directe, geïsoleerde reconstructie (1.000 deelnemers, 30 tijdstappen,
1 kunstmatig kapotte deelnemer) bevestigt dat vóór de fix alle 30
tijdstappen NaN werden, en na de fix alle 30 correct en ongewijzigd
bleven voor de overige 999 deelnemers. Een volledige, echte
simulatierun bevestigt bruikbare, realistische populatiestatistieken.
suite_smoke_test.py en test_cvr_freeze_fix.py slagen ongewijzigd.

**Nog open, apart van deze fix**: in dezelfde run was `max_water_loss_perc`
exact 0,0 voor alle 1.000 deelnemers -- geen NaN, een reëel getal, maar
fysiologisch onwaarschijnlijk voor 90 minuten inspanning op MET 9,8. Dit
lijkt een ander, nog niet gediagnosticeerd probleem (mogelijk in de
vochtverlies-/zweetberekening zelf voor deze specifieke combinatie van
milde omgevingscondities), niet gerelateerd aan de hierboven gefixte
NaN-propagatie. Vraagt eigen onderzoek in de zweet-/vochtverlies-
berekening voordat hier een fix aan wordt gedaan.

## [2026-09-05, vervolg 2] Werkelijke grondoorzaak van de "lege plots": ontbrekende brondata bij forecast_days=16, niet een simulatiebug

De vorige NaN-propagatiefix in hestia_model.py bleek correct maar
onvoldoende: dezelfde Amsterdam-run bleef daarna nog steeds lege plots
opleveren. Grondoorzaak, bevestigd door het ruwe
Thermopoulos_DataEngine_Amsterdam-weerbestand zelf te openen: de
gebruiker had `fetch_hourly_forecast(..., days=16)` in
Thermopoulos_Data_Engine.py hardgecodeerd van de functie-eigen standaard
(`days: int = 7`, vandaar de sheetnaam "Forecast_7d") naar 16 -- Open-
Meteo's eigen gedocumenteerde maximum -- om een evenement 15+ dagen
vooruit te kunnen bereiken. De opgehaalde data bevatte voor de HELE
laatste dag van dat venster (2026-09-20, vanaf 05:00) geen enkele
temperatuur/luchtvochtigheid/wind-waarde meer (wel tijdstempels, wel
enkele afgeleide velden zoals solar_elevation, maar de kernvelden zelf
ontbraken) -- terwijl elke eerdere dag in dezelfde 16-daagse ophaal
volledig was. Dit is kennelijk Open-Meteo's eigen gedrag aan de rand van
zijn geadverteerde bereik, geen fout in deze suite se eigen
ophaal-/verwerkingscode.

Gevolg: de Monte Carlo-simulatie draaide de volle 3-4 minuten door op
ongedefinieerde omgevingsinvoer, en pas ACHTERAF bleek dit uit een
volledig NaN populatie-tijdreeks (lege plots, "n.b." in het rapport) --
de vorige nanmean/nanpercentile-fix loste terecht de AGGREGATIE-kant op,
maar kon de onderliggende, echt-ontbrekende brondata natuurlijk niet
alsnog verzinnen.

Nieuwe, vroegtijdige controle toegevoegd in `build_interpolated_weather()`
(run_hestia.py): controleert vóór de simulatie of elk uur in het
gevraagde evenement-venster geldige temperatuur/luchtvochtigheid/wind-
waarden heeft, en geeft zo niet een duidelijke, direct bruikbare
foutmelding -- inclusief het exacte aantal ontbrekende uren, een
voorbeelduur, en het advies om dichter bij de evenementdatum opnieuw op
te halen. Bewust beperkt tot alleen deze drie kernvelden (geen fallback
elders) -- solar/globe/MRT/WBGT/UTCI zijn door get_hourly_weather()'s
eigen documentatie al als optioneel bedoeld (HESTIA valt dan intern terug
op eigen berekening), bevestigd doordat suite_smoke_test.py's eigen
minimale testdata deze velden nooit invult en toch correct hoort te
draaien.

Getest: het exacte kapotte venster (Amsterdam, 20-09, 13:00, 1,5u) geeft
nu meteen, vóór enige berekening, een duidelijke foutmelding. Een goed
venster (5-09, begin van dezelfde 16-daagse reeks) doorloopt ongewijzigd
correct. Eerste versie van deze check was te streng (blokkeerde ook op
optionele velden) en gebruikte `is None` in plaats van `pd.isna()` (mist
NaN-waarden, die is hoe ontbrekende Excel-cellen daadwerkelijk aankomen)
-- beide gecorrigeerd nadat suite_smoke_test.py dit meteen blootlegde.
Alle drie de bestaande testsuites (suite_smoke_test.py, test_end_to_end.py,
test_cvr_freeze_fix.py) slagen ongewijzigd.

## [2026-09-06] Uitlegtabel toegevoegd aan de conjunctieve-risico-spreidingsplot

Naar aanleiding van een terechte vraag: in `plot_conjunctive_risk_scatter`
(hestia_plots.py) kon een deelnemer die technisch binnen de rode
risicozone viel (T_rect>40,5°C ÉN CO_reserve≤0) toch een lage,
groen-gekleurde collapse-kans tonen -- geen fout, maar het gevolg van de
onderliggende gewogen risicoscore (T_rect boven de klinische 40,5°C-grens
weegt 4x zo zwaar als boven de 39,5°C-grens; een marginale overschrijding
draagt daardoor weinig bij). Zonder toelichting is dat voor een niet-
ingewijde lezer van de grafiek zelf niet te doorzien.

Een vaste uitlegtabel toegevoegd onderaan de figuur (in figuur-relatieve
coördinaten, dus altijd op dezelfde plek, ongeacht waar de data van een
specifieke run precies valt) die de vier gewichten en hun betekenis
toont, met een korte duiding waarom een lichte overschrijding een lage
kans kan geven. `fig.tight_layout()` verwijderd (zou de gereserveerde
ruimte voor de tabel weer hebben dichtgetrokken) en vervangen door een
expliciete `fig.subplots_adjust(bottom=0.30)`.

Getest: de daadwerkelijke Amsterdam-data (n=1000) die tot de vraag leidde,
opnieuw geplot -- tabel staat duidelijk leesbaar onder de grafiek, geen
overlap met de scatter-data. suite_smoke_test.py slaagt ongewijzigd.

## [2026-09-06, vervolg] EHE-drempel en -zone nu ook zichtbaar in de conjunctieve-risico-plot

Terechte vervolgvraag op de uitlegtabel van zonet: die noemt het EHE-
gewicht (39,5°C) als onderdeel van de risicoscore, maar de grafiek zelf
toonde tot nu toe alleen de klinische drempel/zone (40,5°C) -- er was
geen manier om te zien waar EHE-only-deelnemers (wel over 39,5°C, niet
over 40,5°C) zich precies bevinden.

Toegevoegd aan `plot_conjunctive_risk_scatter` (hestia_plots.py): een
tweede drempellijn (39,5°C, oranje gestreept) en een apart, lichter
gearceerd EHE-gebied (39,5-40,5°C) naast het bestaande klinische gebied
(boven 40,5°C) -- met een legenda die alle vier de elementen benoemt.
Titel aangepast om beide criteria expliciet te vermelden. Uitlegtabel
onderaan de figuur bijgewerkt om naar "de oranje of rode zone" te
verwijzen in plaats van alleen "de rode zone".

Getest: dezelfde Amsterdam-data (n=1000) opnieuw geplot -- beide zones
duidelijk te onderscheiden, legenda leesbaar, geen overlap met de
scatter-data of de tabel eronder. suite_smoke_test.py slaagt ongewijzigd.

## [2026-09-06, vervolg 2] Medische duiding van EHE/EHS toegevoegd aan de conjunctieve-risico-plot

Vervolg op de EHE-zone-toevoeging: naast wát de twee criteria zijn
(drempels, gewichten), ontbrak nog een uitleg van wat ze medisch
betekenen en waarom het ertoe doet. Een tweede, apart tekstvak toegevoegd
onder de grafiek (boven de bestaande gewichtstabel) met de klinische
betekenis van EHE (hitte-uitputting -- vermoeidheid/duizeligheid,
bewustzijn blijft helder, reageert doorgaans goed op rust/koeling/vocht)
en EHS/"klinisch criterium" (hitteberoerte -- kerntemperatuur >40,5°C MÉT
verstoord bewustzijn, medisch spoedgeval, snelheid van koelen bepalend
voor de uitkomst), inclusief een expliciete kanttekening dat dit rapport
"klinisch criterium" zegt in plaats van "EHS" om verwarring met de
losstaande Falmouth-EHS-schatting elders in de suite te voorkomen.

Twee lay-outproblemen onderweg gevonden en gecorrigeerd: (1) `wrap=True`
in matplotlib se `fig.text()` bleek onbetrouwbaar -- lange regels liepen
gewoon door voorbij de rand van het canvas in plaats van netjes af te
breken. Vervangen door volledig handmatige, kort genoeg regelafbrekingen.
(2) De twee tekstvakken (medisch + gewichtstabel) overlapten elkaar bij
de eerste verticale plaatsing -- de gereserveerde ruimte onderaan de
figuur was te krap voor beide volledige teksten. Vergroot en de
verticale ankerpunten opnieuw afgesteld totdat beide vakken, bij
visuele controle, volledig en zonder overlap zichtbaar waren.

Getest: dezelfde Amsterdam-data (n=1000) opnieuw geplot -- beide
tekstvakken volledig leesbaar, geen overlap met elkaar, de grafiek, of
de legenda. suite_smoke_test.py slaagt ongewijzigd.

## [2026-09-06, vervolg 3] Meteorologische omstandigheden toegevoegd aan het HESTIA-rapport

Terechte constatering: het rapport toonde de scenario-configuratie
(stad, starttijd, duur, activiteit) maar nergens de daadwerkelijke
weersomstandigheden waarop de simulatie draaide -- iemand die het
rapport las kon niet zien of het bijvoorbeeld 16 of 26 graden was
zonder apart in het ruwe Excel-weerbestand te duiken.

Nieuwe sectie 2 ("Meteorologische omstandigheden tijdens het evenement")
toegevoegd aan generate_event_report.py, met min/gemiddelde/max over de
volledige gesimuleerde periode voor luchttemperatuur, relatieve
luchtvochtigheid, windsnelheid, globetemperatuur, MRT, en WBGT/UTCI
(indien vooraf berekend aanwezig in de brondata -- anders "n.b.", met
een duidelijke voetnoot dat HESTIA in dat geval intern terugvalt op een
eigen berekening die niet apart gerapporteerd wordt). Alle overige
secties (voorheen 2-10) hernummerd naar 3-11, inclusief zes losse
interne verwijzingen ("zie sectie X") die anders naar het verkeerde
onderwerp waren gaan wijzen.

`generate_report()` kreeg een nieuwe, optionele `interp_data`-parameter;
`run_hestia.py` geeft de al bestaande `interp_for_bridge`-data (dezelfde
die de fysiologische simulatie zelf als invoer gebruikt) er nu aan door
-- geen nieuwe berekening nodig.

Getest: een volledige, echte run met de daadwerkelijke Amsterdam-
weerdata (2026-09-20, 13:00, 1,5 uur) -- sectie 2 toont zinvolle,
correcte waarden; alle elf secties gecontroleerd in het geconverteerde
Word-document, correct genummerd en zonder verwijzingsfouten.
suite_smoke_test.py slaagt ongewijzigd.

## [2026-09-06, vervolg 4] Meteo-sectie: expliciet gemaakt dat de luchttemperatuur de UHI-gecorrigeerde stedelijke waarde is

Vervolg op de nieuwe meteo-sectie: een gebruiker die opvallend hoge
luchttemperaturen zag (26-27 degC voor Amsterdam eind september) vroeg
terecht of dat de stedelijk-hitte-eiland-correctie (UHI) al meerekende.
Dat bleek zo te zijn (T_air_urban = T_air_rural + UHI_delta, bevestigd
in de ruwe brondata), maar de sectie zelf vermeldde dat nergens -- de
rij heette gewoon "Luchttemperatuur (T_air)".

Rij hernoemd naar "Luchttemperatuur (T_air, stedelijke waarde)" en de
voetnoot uitgebreid met een expliciete vermelding dat dit de stedelijke
(UHI-gecorrigeerde, indien toegepast bij het ophalen van de brondata)
waarde is -- inclusief de eerlijke kanttekening dat deze rapportagelaag
zelf niet kan zien of UHI voor een specifieke run aan of uit stond
(die keuze wordt gemaakt bij het genereren van de brondata in
Thermopoulos_Data_Engine.py, niet hier).

Zelfde gelegenheid gebruikt om de daadwerkelijke, reële hoge-temperatuur-
casus te onderzoeken: de brondata voor deze specifieke run laat 0%
bewolking en ~0,3 m/s wind zien om 13:00 op 20 september -- een
combinatie die een groot verschil tussen luchttemperatuur en
globetemperatuur/MRT fysisch verklaart (minimale convectieve koeling,
maximale directe zoninstraling), geen rekenfout.

Getest: dezelfde Amsterdam-data opnieuw gegenereerd -- label en
voetnoot tonen correct, cijfers ongewijzigd (26,0-27,2 degC).
suite_smoke_test.py slaagt ongewijzigd.

## [2026-09-06, vervolg 5] Rurale WBGT/UTCI berekend en naast de stedelijke waarden getoond

Vervolg op de vorige twee wijzigingen: in plaats van één stedelijke
luchttemperatuur met een uitleg-voetnoot over UHI, toont sectie 2 nu
rurale EN stedelijke waarden naast elkaar voor T_air, globetemperatuur,
MRT, WBGT en UTCI -- het UHI-effect is zo direct af te lezen uit het
verschil tussen de twee rijen, zonder dat er nog een aparte uitleg
nodig is.

Rurale WBGT/UTCI bestonden nog nergens in de suite -- Thermopoulos_
Data_Engine.py berekent globe/MRT/WBGT/UTCI uitsluitend vanuit
T_air_urban. Nieuwe rurale keten toegevoegd in hestia_model.py se
`interpolate_weather()`: T_air_rural wordt nu meegenomen vanaf
`get_hourly_weather()` (thermopoulos_loader.py), en de volledige fysische
keten (globe -> MRT -> natteboltemperatuur -> WBGT -> UTCI) wordt
opnieuw doorgerekend met T_air_rural als basis, met dezelfde functies en
in dezelfde volgorde als de bestaande stedelijke berekening in
Thermopoulos_Data_Engine.py -- inclusief het herberekenen van de
1,5m-wind via dezelfde logaritmische hoogtecorrectie (rurale ruwheid,
z0=0,1), aangezien die stedelijke 1,5m-wind zelf nooit werd doorgegeven
aan deze laag, alleen het einduitkomst-globe/MRT-resultaat.

Gracieus afgeschermd: als T_air_rural, GHI of zonshoogte in de brondata
ontbreken (oudere bestanden), blijven alle rurale velden "n.b." zonder
te crashen -- dezelfde aanpak als de bestaande stedelijke "n.b."-
afscherming.

Getest: de daadwerkelijke Amsterdam-data (waar dit uit voortkwam) geeft
consistent lagere rurale waarden dan stedelijke (bijv. WBGT 23,0-24,1
ruraal tegen 24,5-25,5 stedelijk) -- correct in de verwachte richting.
Randgeval (ontbrekende brondata) getest zonder crash. Volledig rapport
opnieuw gegenereerd en naar Word geconverteerd, sectie 2 visueel
gecontroleerd. Alle drie bestaande testsuites (suite_smoke_test.py,
test_end_to_end.py, test_cvr_freeze_fix.py) slagen ongewijzigd.

## [2026-09-06, vervolg 6] UHI paste geen bijbehorende RH-correctie toe -- luchtvochtigheid daalt niet mee met de temperatuurstijging

Terechte vervolgvraag: als UHI de temperatuur optelt (T_air_urban =
T_air_rural + UHI_delta), zou bij gelijkblijvend absoluut vochtgehalte
de relatieve luchtvochtigheid moeten DALEN -- warmere lucht kan meer
vocht bevatten, dus dezelfde hoeveelheid vocht komt overeen met een
lager RH-percentage. Bevestigd dat dit tot nu toe niet gebeurde: de
UHI-stap in Thermopoulos_Data_Engine.py verhoogde T_air_urban, maar
liet de RH ongewijzigd op de rurale waarde staan, en die ongewijzigde
RH werd vervolgens gebruikt voor de stedelijke natteboltemperatuur-,
WBGT- en UTCI-berekening.

Opvallend: exact deze dauwpunt-behoudende correctie (RH herberekenen bij
de nieuwe temperatuur, met behoud van absoluut vochtgehalte) bestond al
wél voor de kustcorrectie, vlak vóór de UHI-stap in dezelfde functie --
alleen de UHI-stap zelf miste 'm. Dezelfde bestaande
`dew_point_from_rh()`/`rh_from_dew_point()`-functies hergebruikt om een
nieuwe `RH_urban`-kolom te berekenen (dauwpunt behouden vanuit de rurale
T+RH, RH herberekend bij T_air_urban). De drie plekken die voorheen de
rurale RH gebruikten voor stedelijke berekeningen (twee
natteboltemperatuur-varianten, UTCI) aangepast naar `RH_urban`.

`thermopoulos_loader.py` uitgebreid met een `humidity_urban`-veld
(analoog aan het eerder toegevoegde `temp_rural`), met dezelfde
gracieuze `None`-afscherming voor oudere bestanden zonder deze kolom.

Getest: de dauwpunt-conversie geïsoleerd met Koos' eigen Amsterdam-
cijfers (T_rural=25,0 degC, RH=61%, UHI_delta=+1,0) geeft RH_urban=57,5%
-- correct gedaald, en de grootte (~3,5 procentpunt per graad opwarming)
komt overeen met de vuistregel uit de meteorologie. `suite_smoke_test.py`
en `test_end_to_end.py` slagen ongewijzigd, met bevestiging dat de
laatste daadwerkelijk het UHI-pad doorloopt (populatie=150.000).

**Belangrijk voor de gebruiker**: deze fix wijzigt hoe
Thermopoulos_Data_Engine.py nieuwe weerdata verwerkt -- reeds
gegenereerde Excel-bestanden bevatten nog de oude, ongecorrigeerde
WBGT/UTCI-waarden. Een nieuwe weerdata-ophaal is nodig om de
gecorrigeerde stedelijke WBGT/UTCI te krijgen.

## [2026-09-11] Windprofiel: "Stedelijk"-terreinoptie gaf stilzwijgend 0 m/s wind

Gevonden tijdens een vraag over welke terreinoptie het beste bij het
Dam tot Damloop-parcours past. `wind_speed_at_height()` (logaritmische
windwet, 10m naar 1,5m) deelt door `ln(z_target/z0)`; de
"Stedelijk/binnenstad"-optie in `ROUGHNESS_Z0_TERRAIN` had z0=1,5 m --
exact gelijk aan de 1,5m-doelhoogte die overal in de suite wordt
gebruikt, dus `ln(1,5/1,5)=ln(1)=0` en de functie gaf altijd 0 m/s
terug, ongeacht de werkelijke windsnelheid. De functie controleerde
alleen op `z0<=0`, niet op `z0>=z_target`.

Twee fixes in `Thermopoulos_Data_Engine.py`: (1) `wind_speed_at_height()`
weigert nu expliciet `z0>=z_target` (en `z0>=z_ref`), met een
waarschuwing en terugval op de referentiewind in plaats van een stille
nul; (2) de z0-waarde van "Stedelijk/binnenstad" zelf verlaagd van 1,5
naar 1,2 m, zodat hij niet meer op de doelhoogte-grens ligt en weer een
zinnige (niet-nul) uitkomst geeft.

Getest: numeriek nagerekend voor alle zes terreinopties -- "Stedelijk"
geeft nu 0,63 m/s bij een referentiewind van 6,0 m/s (was 0,0 m/s). De
guard afzonderlijk getest door z0=1,5 te forceren: geeft nu een
waarschuwing en de referentiewind terug, geen stille nul meer.

## [2026-09-11] Instelbare evenementafstand (HESTIA, PYROX-console, Klimatos)

Voorheen zat de evenementafstand op meerdere plekken hardcoded of
losgekoppeld van de rest van de berekening: `hestia_model.py`'s
`validate_population()`-finishtijdcheck testte altijd tegen de
marathonafstand (42,195 km), ongeacht welk evenement werd
gesimuleerd; `Klimatos_ClimateShift.py` had een vaste 16,1 km
(Dam tot Damloop) zonder console-ingang; `run_hestia.py` vroeg om een
losse "Duration (hours)" zonder enig verband met afstand of pace.

Nu overal instelbaar: `validate_population(event_dist_km=...)`
(default: marathon, ongewijzigd gedrag voor bestaande aanroepen; bij
een andere afstand worden de verwachtingsgrenzen proportioneel
geschaald en is de pass/fail-gate informatief, zodat een niet-marathon-
evenement nooit onterecht als "FAIL" wordt gerapporteerd).
`Klimatos_ClimateShift.py` heeft een nieuwe `EVENT_DIST_KM`-constante
mét console-prompt, gevraagd vóór de duur/pace-prompts zodat beide
daarvan afhankelijk zijn. `run_hestia.py` vraagt nu eerst de afstand,
en leidt de duur automatisch af uit afstand x pace (uit het bestaande
MET-activiteitenmenu, waarvan de meegeleverde snelheid voorheen werd
weggegooid) -- de duur-prompt blijft bestaan met de afgeleide waarde
als voorgesteld default.

Getest: `validate_population()` met `event_dist_km=16,1` (Dam tot
Damloop) op een testpopulatie -- P95 (1u39) haalt niet eens de
geschaalde verwachte ondergrens (1u43-2u06), een vroege aanwijzing dat
de populatie aan de snelle kant zit (zie ook de `sample_pace`-entry
verderop). `test_end_to_end.py` moest worden aangepast (één extra
console-vraag verschoof de vooraf-gescripte testantwoorden) en slaagt
weer.

## [2026-09-11] Klimatos: MET-conversie van pace was zelf-ijkend, niet fysiologisch afgeleid

De pace-naar-MET-omzetting in de console-prompt van
`Klimatos_ClimateShift.py` gebruikte een lineaire schaalfactor
(`0,733 * speed_kmh`) die met opzet zo gekozen was dat hij bij de
default-pace (5:30/km) uitkwam op de bestaande `EHS_MET_VALUE=8,0` --
dus rondgerekend om het eigen ankerpunt te bevestigen, niet afgeleid
uit een fysiologisch model. De eigen codecommentaar zei het al: de
ACSM-vergelijking geeft bij diezelfde pace een "noticeably higher MET".

Vervangen door een nieuwe, canonieke `_acsm_met_from_pace()`-functie
(nu in `hestia_model.py`, hergebruikt door Klimatos) die de ACSM
loop-/wandelvergelijkingen direct toepast. Bij de 5:30/km-ankerpace
geeft dit nu 11,4 MET (was 8,0) -- een verschil van ~30%. Meteen
gecombineerd met een tweede fix: `EVENT_DURATION_MIN` (default 100
min) en de pace-aanname (5:30/km, wat over 16,1 km eigenlijk 88,5 min
zou moeten zijn) bleken onderling niet consistent; beide worden nu uit
dezelfde pace afgeleid zodra die wordt ingevoerd, met de nieuwe default
89 min.

Getest: pace-naar-MET nagerekend over een reeks van 4:00 tot 7:45
min/km -- MET en impliciete duur zijn nu voor elk punt onderling
consistent (bijv. 5:30/km -> MET 11,4, duur 89 min, precies
5,5 x 16,1 km).

## [2026-09-11] "Twee lussen die om elkaar heen racen" was de verkeerde lezing van het eigen model

Bij het navragen van de forcing/feedbacklus-visualisatie bleek de
bestaande beschrijving (in zowel `pyrox_plots.py`'s `plot_feedback_race`
als `hestia_model.py`'s eigen moduledocstring "THE PRINCIPLE BEING
MODELLED") het model verkeerd te framen: als een wedloop tussen een
beschermende lus (acclimatisatie) en een ondermijnende lus (strain).
Nagerekend tegen de eigen paper-abstract (Research Square,
doi:10.21203/rs.3.rs-8626369/v1): die spreekt expliciet van "a closed
loop" (enkelvoud). Polariteit nagerekend: cumulatieve strain (+) ->
onderdrukking (-) -> acclimatisatie (-) -> strain; product van de drie
tekens is positief. Er is precies ÉÉN gesloten, zichzelf-versterkende
lus. Acclimatisatie zelf is geen lus -- het is een dempend pad,
aangedreven door de externe blootstelling, niet door de strain zelf.

Verder gecontroleerd tegen de daadwerkelijke vergelijkingen in de
paper-PDF (methodesectie): de evenwichtsvoorwaarde
(`R1(1-alpha_pot(1-kappa*Sigma*))-theta_rec = rho(1+0,1*Sigma*)`) en de
feedback-gain-drempel (`R1*alpha_pot*kappa > 0,1*rho`) komen
letterlijk overeen met `equilibrium_strain()` en `feedback_gain()` in
de code, inclusief de coëfficiënt 0,1 (`HOMEOSTATIC_DRIVE_COEFFICIENT`).

Gecorrigeerd op beide plekken: `pyrox_model.py`'s moduledocstring
herschreven naar de correcte één-lus-lezing, en `plot_feedback_race`
in `pyrox_plots.py` kreeg een nieuwe uitlegbox die het principiële
fundament van PYROX uitlegt (inclusief de polariteitsrekensom) plus een
duidelijke callout op de grafiek zelf die aangeeft welke lijn de
daadwerkelijke hittestress-uitkomst is (de andere drie lijnen zijn
verklarend, geen aparte uitkomsten).

Getest tegen vijf uiteenlopende scenario's (kort/snel stijgend,
lang/traag, nooit-kritiek, direct-kritiek, hoog startpunt) om de
callout-positionering en labelling te controleren; twee eigen fouten
gevonden en gecorrigeerd tijdens dat testen (callout-tekst botste met
de legenda bij korte reeksen; de callout-pijl zelf oogde bij een laag
startpunt als een tweede, valse strain-piek). Ook de kritieke-grens-
lijn (voorheen een kaal getal, "critical Sigma") kreeg de bestaande
caution/danger/emergency-zonelijnen (50/75/90% van kritiek) uit
`plot_strain_trajectories`, met een regel die uitlegt dat het getal
zelf een interne modeleenheid is, geen fysiologische maat.

## [2026-09-11] equilibrium_strain(): "veilig" en "runaway" gaven dezelfde None terug

Gevonden bij het onderzoeken van een nieuwe visualisatie-optie
(bifurcatiediagram) op basis van de tot dan toe ongebruikte
`equilibrium_strain()`/`feedback_gain()`-functies. De oude versie gaf
`None` terug wanneer `daily_change(strain)` overal hetzelfde teken
had op [0, critical_strain] -- maar dat gebeurt in twee tegengestelde
situaties die niet van elkaar te onderscheiden waren: overal negatief
(veilig, strain zakt naar 0) en overal positief (runaway, strain loopt
onvermijdelijk op naar kritiek). Numeriek bevestigd voor
very_elderly_85plus: bij load=0,5 was `daily_change` -0,12 en -0,14 op
beide uiteinden (veilig); bij load=3,0 was dat +1,63 en +2,36
(runaway). Beide gaven voorheen `None`.

Functie geeft nu `(state, value)` terug, met `state` een van "safe",
"equilibrium", "runaway". `plot_three_regimes` (voorheen een trage,
onnauwkeurige 80-dagen-simulatie-benadering met een 90%-van-kritiek-
heuristiek die een echt maar <90%-evenwicht ten onrechte als "dead-
zone veilig" classificeerde) gebruikt nu deze exacte, analytische
functie. Tweede bug gevonden tijdens het herbouwen: bij groepen die
binnen het geteste bereik nooit runaway bereiken (outdoor_workers,
elite_athletes -- 0 van 123 geteste belastingen tot R1=2,5) tekende de
plot toch een rode "RUNAWAY"-zone vanaf de rand van het testbereik,
alsof dat een echt omslagpunt was. Nu een expliciete "geen runaway
gevonden tot R1=2,5"-vermelding in plaats van een vals alarm.

Getest: `equilibrium_strain()` nagerekend voor drie groepen over een
reeks belastingen -- het onderscheid safe/equilibrium/runaway komt nu
overeen met de handmatig nagerekende tekens van `daily_change`.
`plot_three_regimes` opnieuw gerenderd voor drie groepen; geen valse
rode zones meer voor de twee groepen zonder gevonden runaway.

## [2026-09-11] Klimatos liveability-matrix: wit gat bleek een onbenoemde derde zone, geen renderfout

Gemeld als "wit stuk tussen het blauwe gebied en de rode curve".
Nagerekend in `HEATLim.py`'s `livability_Mmax()`: die heeft een eigen,
strengere "compensability"-check (`Ereq < Emax_constrain`), los van de
bredere `Survivability()`-grens die de rode lijn tekent. Waar
compensability faalt (strain kan zelfs in rust niet worden afgevoerd)
geeft de functie bewust NaN terug -- "no activity is possible without
storage heat internally", een derde, echte fysiologische zone tussen
"activiteit mogelijk" (gekleurd) en "niet overleefbaar" (rood). Numeriek
bevestigd (Amsterdam, RH=60%): Mmax wordt al NaN bij Ta=35,75 degC,
terwijl `Survivability()` pas bij Ta=38,75 degC omslaat.

`compute_mmax_met()` zelf is niet aangepast (dit is geen rekenfout, en
de docstring claimt validatie tot 1e-14 tegen de gepubliceerde
Vanos et al.-matrices). Wel `plot_liveability_matrix()` aangepast:
een grijze stippelarcering toegevoegd voor exact deze derde zone
(`surv AND isnan(mmax)`), met eigen legenda-item. Bijkomende fix: de
bestaande rode arcering voor de niet-overleefbare zone had `alpha=0`,
wat ook de arcering zelf onzichtbaar maakte (niet alleen de
achtergrondvulling zoals bedoeld) -- edgecolor nu expliciet gezet i.p.v.
via alpha. Matplotlib-compatibiliteitsfix nodig: `QuadContourSet` heeft
in matplotlib >=3.8 geen `.collections`-attribuut meer; nieuwe
`_set_hatch_edgecolor()`-helper werkt met beide API-varianten.

Getest: volledige functie end-to-end gedraaid met synthetische
jaardata -- het witte gat is verdwenen en als aparte, gelabelde zone
zichtbaar naast de rode niet-overleefbare arcering.

## [2026-09-11] run_pyrox.py: groepskeuze in de console

`main()` draaide voorheen altijd met alle 23 groepen
(`list(TARGET_GROUPS.keys())`), zonder mogelijkheid om een subset te
kiezen -- terwijl `assess_population()` zelf die mogelijkheid al had
(gebruikt door o.a. `generate_event_report.py`), alleen niets in het
interactieve scriptpad ontsloot dat. Nieuwe `_select_groups()`-functie:
toont een genummerde lijst van alle groepen (met `*` bij de drie
paper-gespecificeerde en het evidence_status-label erbij), en
accepteert kommagescheiden nummers, "all", of leeg (valt terug op de
drie paper-groepen).

Getest: parsing-logica los getest voor leeg/"all"/specifieke
nummers/ongeldige invoer/gemengd geldig-en-ongeldig -- alle gevallen
geven het verwachte resultaat zonder te crashen.

## [2026-09-11] sample_pace: individuele pace/MET/blootstellingsduur in plaats van gedeeld voor de hele populatie

Grootste wijziging van de sessie. Bevestigd via codespoor
(`hestia_bridge.py`'s `worker_args`-opbouw en, belangrijker,
`hestia_model.py`'s daadwerkelijk door `generate_event_report.py`
gebruikte `run_monte_carlo_adult()`) dat élke gesimuleerde deelnemer in
de populatie-Monte-Carlo tot nu toe dezelfde absolute MET én dezelfde
blootstellingsduur kreeg. De al bestaande VO2max/pct_vo2max-variatie
verandert alleen hoe zwaar die ene, gedeelde pace voor iemand aanvoelt
(relatieve inspanning/RPE), niet hoe snel iemand daadwerkelijk loopt of
hoe lang iemand aan het weer blootstaat. Vergelijking met de eerder
onderzochte echte Dam tot Damloop-tijdsverdeling (mediaan ~1u30-1u36,
lange staart richting de 2-uurslimiet) liet al zien dat dit de
blootstellingsduur van de tragere, vaak kwetsbaardere staart van het
veld structureel onderschat.

**Nieuw in `hestia_model.py`:**
- `_acsm_met_from_pace()` -- canonieke pace-naar-MET-conversie (zie ook
  de Klimatos-entry hierboven).
- `sample_recreational_pace_min_per_km(gender, event_dist_km)` --
  gender-geconditioneerde lognormale pace-sampler, geankerd op de
  onderzochte Dam tot Damloop-cijfers (mediaan mannen 5,35 min/km,
  vrouwen 6,15 min/km bij 16,1 km), geklemd op [3,3, 7,45] min/km
  (2-uurslimiet). Geschaald naar andere afstanden via Riegel's
  vermoeidheidsexponent (T2=T1*(D2/D1)^1,06; Riegel 1977/1981) --
  zonder deze schaling zou elke afstand stilzwijgend de 16,1km-pace
  hergebruiken. [Gevlagd voor review] Vickers & Vertosick (2016, n=2.303
  recreatieve lopers) vonden dat Riegel's marathonvoorspelling voor
  ongeveer de helft van de lopers minstens 10 minuten te snel uitvalt --
  er is geen aparte, hogere marathon-specifieke exponent geïmplementeerd,
  dus resultaten ruim voorbij de halve marathon (21,1 km) zijn eerder
  een ondergrens dan een precieze schatting.
- `AdultParticipantProfile` kreeg twee nieuwe velden,
  `pace_min_per_km`/`duration_hours`, met default 0,0 (niet verplicht --
  zie hieronder waarom).
- `generate_base_population(sample_pace=True, event_dist_km=...)`:
  wanneer aan, krijgt elke deelnemer een eigen pace/MET/duur in plaats
  van het gedeelde `met_value`.
- `run_monte_carlo_adult(sample_pace=True, event_dist_km=...)`: elke
  deelnemer krijgt nu een eigen segment van `interp_data` (geknipt op
  hun eigen duur, via de tijdstempels van de meegegeven weerdata) en
  hun eigen MET, in plaats van de volledige, gedeelde weerreeks en het
  gedeelde `met_value`.

**Drie bugs gevonden tijdens het testen, niet vooraf bedacht:**
1. Zes populatie-brede tijdreeks-arrays (`t_rect_sims`, `hr_sims`, e.a.)
   verwachtten een rechthoekige vorm (iedereen even lang) en crashten
   direct (`ValueError: inhomogeneous shape`) zodra trajecten
   verschillende lengtes kregen. Opgelost met NaN-opvulling tot de
   langste deelnemer -- met een aparte, ongevulde kopie van
   `all_results` voor alle plekken die de laatste/finale waarde van
   iemand uitlezen (`res[-1]...`), anders zou een korte deelnemer daar
   per ongeluk NaN in plaats van hun echte eindwaarde krijgen.
2. `_calculate_threshold_stats()` (percentage boven een T_rect-drempel
   per tijdstap) deelde door de vaste, volledige populatiegrootte, niet
   door het aantal nog actieve (niet-NaN) deelnemers op dat tijdstip --
   zou het percentage geleidelijk hebben laten dalen naarmate meer
   mensen (vaak de snellere, minder belaste) finishen, puur door
   verdunning van de noemer. Nu een dynamische, per-tijdstap noemer;
   het aantal actieve deelnemers wordt ook meegegeven (`n_active`) voor
   eventueel hergebruik door rapportage/plots.
3. `dehy_sims` had dezelfde rechthoekige-array-aanname, via
   kolomindexering (`dehy_sims[:, -1]`) in plaats van lijstindexering
   -- vereenvoudigd naar een directe per-persoon berekening vanuit
   ieders eigen laatste, echte meting, wat het probleem in één keer
   omzeilt.
4. Een RuntimeWarning ("Mean of empty slice") bij de kwetsbare-
   staartgroep-statistieken bleek inhoudelijk correct gedrag (die
   subgroep kan eerder klaar zijn dan de langst lopende deelnemer in de
   totale populatie) maar hoorde stil afgehandeld te worden; lokaal
   onderdrukt op de plek waar het optreedt.
5. Backward-compatibility-breuk: de twee nieuwe verplichte
   profielvelden braken drie andere plekken die `AdultParticipantProfile`
   los aanmaken zonder `generate_base_population()`
   (`run_hestia.py`, `individual_engine.py`, `test_cvr_freeze_fix.py`).
   Opgelost met defaultwaarden (0,0) in plaats van verplichte velden.

**Nog niet gedaan, expliciet:** dit nieuwe pad is nog niet ingeschakeld
voor een daadwerkelijke DtD-rapportgeneratie, en de impact op de
bestaande kalibratie-ankers (Falmouth, Boston, Paris 2003 -- allemaal
gekalibreerd met de aanname van gedeelde MET/duur) is nog niet
doorgerekend. `analyse_control_failure_population()` (de TCF-module)
is bij inspectie veilig bevonden (verwerkt per persoon, gebruikt al
nan-aware aggregatie) maar niet end-to-end getest met een ragged-
duur-populatie zoals de rest van de pijplijn wel is.

**Aangezet in de praktijk:** `run_hestia.py`'s interactieve
populatie-Monte-Carlo-keuze heeft nu een expliciete
"Sample individual pace/MET/duration..."-vraag (default "n" -- bewust
geen stille gedragswijziging), en `monte_carlo_adult()` verbreedt het
opgehaalde weervenster automatisch tot de traagst mogelijke deelnemer
zodra die vraag met "y" wordt beantwoord.

Getest: volledige bestaande testsuite (`suite_smoke_test.py`,
`test_individual_engine.py`, `test_new_modules.py`,
`test_uncertainty.py`, `test_cvr_freeze_fix.py`, `test_rate_limit.py`,
`test_end_to_end.py`) slaagt. Regressie bevestigd: de oude,
niet-`sample_pace`-route geeft aantoonbaar exact hetzelfde gedrag als
voorheen (alle trajecten dezelfde lengte, `n_active` blijft constant op
de volledige populatiegrootte). Nieuwe route getest zonder
RuntimeWarnings, met zichtbaar krimpende `n_active` naarmate deelnemers
finishen. Pace-schaling over vijf afstanden (5K tot marathon)
nagerekend tegen bekende recreatieve veldtijden.

## [2026-09-11, vervolg] Tweede blokdiagram: klassieke regeltechnische notatie naast de causal-loop-diagram

Op verzoek, na een handgetekende schets ter vergelijking: een tweede
versie van het PYROX-structuurdiagram, nu met som-/vermenigvuldigknopen
en een expliciete integrator voor Sigma(t), naast (niet in plaats van)
de eerdere causal-loop-diagram-versie.

De handgetekende schets gebruikte somknopen ("−") op de plek waar de
vergelijking vermenigvuldigingen vereist: `eff_acclim = damping x
(1-kappa*Sigma)`, niet een aftrekking. Ook ontbraken theta_rec en de
herstelterm rho(1+0,1*Sigma) nog in de schets. Bij het opnieuw opbouwen
van het diagram zelf nog een volgordefout gevonden en gecorrigeerd:
theta_rec moet vOOr de max(0,.)-verzadiging worden afgetrokken (het
bepaalt OF strain uberhaupt opbouwt), de herstelterm juist NA de
verzadiging (herstel wordt niet op dezelfde manier gepoort als de
instroom) -- in een eerste versie stonden deze in de verkeerde volgorde.

Beide diagrammen staan nu na elkaar in `TECHNICAL_REFERENCE.md` paragraaf
3.1, met een korte toelichting bij elk over wanneer welke notatie
duidelijker is.

## [2026-09-11, vervolg] Blokdiagram (regeltechnische versie): ontbrekende clip bij recovery

Terechte constatering: "er gaat iets niet goed met de recovery" in de
vorige versie van het blokdiagram. Nagerekend tegen `update_strain()`:
`updated = strain + net_strain_input - recovery`, vervolgens
`np.clip(updated, 0.0, critical_strain)` -- een dubbele begrenzing die in
het diagram nergens stond. Zonder die klem suggereerde het diagram dat de
recovery-term Sigma ongelimiteerd onder nul zou kunnen drukken, wat de
code niet toestaat.

Toegevoegd: een apart "Clip [0, Sigma_crit]"-blok na de integrator, en de
Sigma(t)-terugkoppeling naar suppression_factor/recovery nu expliciet
getekend als afkomstig van NA die clip, niet van de ongeklemde
integrator-uitgang.

## [2026-09-11, vervolg] Blokdiagram (regeltechnische versie): drie visuele aansluitfouten en een onduidelijke uitgang

Op verzoek de visualisatie zelf nauwkeurig nagelopen, in plaats van alleen
de inhoud. Drie echte aansluitfouten gevonden door in te zoomen op elk
knooppunt:

1. De uitgangspijl (na "Clip") had geen pijlpunt en eindigde los in de
   lucht, los van het "Sigma(t) Out"-label.
2. De terugkoppelpijl naar "suppression_factor" stopte met een zichtbare
   tussenruimte vlak vOOr de doos, niet erop aansluitend.
3. Op het hoekpunt waar de Sigma(t)-terugkoppellijn van verticaal naar
   horizontaal draait, stond een overtollige pijlpunt die nergens naar
   wees -- een artefact van twee los getekende pijlen die toevallig op
   hetzelfde punt eindigden/begonnen.

Oorzaak van (1) en verwant: de uitgangsmarkering (ster in cirkel) viel
buiten de as-grenzen (xlim) van de plot en werd stilzwijgend afgesneden --
canvas verbreed en coordinaten herzien zodat alles binnen de grenzen valt.

Vierde wijziging, geen fout maar een verduidelijking: de uitgang Sigma(t)
is nu expliciet gemarkeerd (rode ster in cirkel, "THE OUTPUT"-label) in
plaats van alleen een pijl die in een label eindigt -- voor een
niet-ingewijde was voorheen niet meteen duidelijk welk van de vele
blokken de daadwerkelijke uitkomst is.

## [2026-09-11, vervolg] Blok-voor-blok uitleg toegevoegd, los van de afbeeldingen zelf

Een verklarende tabel toegevoegd direct na de twee diagrammen in
`TECHNICAL_REFERENCE.md` paragraaf 3.1 -- een plain-language uitleg per
blok (Forcing, Damping, suppression_factor, theta_rec, Saturation,
Recovery, de integrator, de clip, en de Sigma(t)-uitgang). Bewust als
tekst in het document, niet in de PNG's zelf, om de diagrammen zelf niet
drukker/onoverzichtelijker te maken dan nodig.

## [2026-09-11, vervolg] Alle documentatie ook als Word (.docx)

Op verzoek: README.md, MANIFEST.md, PROJECT_INSTRUCTIONS.md,
TECHNICAL_REFERENCE.md en INTEGRATION_CHANGELOG.md geconverteerd naar
.docx via pandoc, in nieuwe map `docs_word/`. TECHNICAL_REFERENCE.md's
twee ingesloten diagrammen (`diagrams/*.png`) komen correct mee over
(geverifieerd door rendering naar PDF); MANIFEST.md/TECHNICAL_REFERENCE.md/
INTEGRATION_CHANGELOG.md kregen een inhoudsopgave (`--toc`), die pas
zichtbaar wordt na het openen in Word zelf (Word werkt TOC-velden bij bij
openen; een headless LibreOffice-render toont 'm leeg -- geen fout in het
bestand, wel iets om te weten bij het controleren via een PDF-render).

Deze .docx-bestanden zijn een export van de .md-bronbestanden, niet een
aparte bron -- bij toekomstige wijzigingen aan de .md's moeten de .docx's
opnieuw gegenereerd worden (`pandoc <bestand>.md -o docs_word/<bestand>.docx
--standalone [--toc --toc-depth=2/3] [--resource-path=. voor
TECHNICAL_REFERENCE.md]`), niet los bijgewerkt.

## [2026-09-11, vervolg] Echte crash uit een live run: plot_adult_results() met sample_pace=True

Koos draaide de suite zelf (Spyder/Anaconda, Windows) met de nieuwe
sample_pace-vraag op "y" en kreeg een echte crash, met volledige
traceback:

```
ValueError: x and y must have same first dimension, but have shapes (9,) and (12,)
  File hestia_model.py:4553 in plot_adult_results
    ax1.plot(times_dt, stats['mean_t_rect'], 'b-', label='Mean T_rect')
```

Oorzaak: `run_monte_carlo_adult()` geeft `all_results` ONGEVULD terug (met
opzet, om "laatste-waarde"-uitlezingen elders niet te laten verknoeien
door NaN-opvulling -- zie de eerdere sample_pace-entry). `stats['mean_
t_rect']` komt wel uit de opgevulde array (lengte = langste deelnemer).
`plot_adult_results()` bouwde zijn tijd-as echter uit `results[0]` --
toevallig een kortere deelnemer in Koos' run (7-12 stappen, verschillend
per deelnemer) -- vandaar de exacte mismatch (9 vs 12) uit de traceback.
Dit was niet gevonden bij het testen van `run_monte_carlo_adult()` zelf,
omdat ik alleen de teruggegeven `stats`/`all_results`-structuren
controleerde, niet de volledige plot-pijplijn (`generate_population_
plots -> plot_adult_results`) end-to-end met sample_pace=True.

Gefixed: `times_str`/`t_air_vals`/`utci_vals`/`wbgt_vals`/`mrt_vals`
worden nu opgebouwd uit de LANGSTE deelnemer (`max(results, key=len)`),
niet uit `results[0]`, zodat de lengte altijd overeenkomt met de
opgevulde stats-arrays, ongeacht welke deelnemer toevallig als eerste in
de lijst staat. (`plot_pediatric_results()` gebruikt bewust nog steeds
`results[0]` -- pediatrische populaties hebben geen sample_pace en dus
altijd gelijke lengtes, dus dat is daar geen bug.)

Tweede, kleinere fix uit dezelfde run: de misleidende waarschuwing
"... for the chosen MET (9.8)" bij sample_pace=True -- met sample_pace
aan wordt `met_value` nooit gebruikt (elke deelnemer heeft een eigen,
gesamplede pace/MET), dus de melding wees ten onrechte naar de gedeelde
MET. De onderliggende bevinding zelf (36% van de populatie op het
95%-VO2max-plafond) was en blijft correct -- alleen de tekst benoemde de
verkeerde oorzaak. Nu twee aparte berichten, afhankelijk van
`sample_pace`.

Beide gereproduceerd en bevestigd verholpen met Koos' eigen parameters
(MET 9,8, 16,1 km, 1,68u nominaal -> verbreed venster 2,00u, seed 42):
resultaatlengtes liepen van 7 tot 12 stappen, `plot_adult_results()`
draaide zonder fout.

**Les hieruit, expliciet**: dit is de tweede keer deze sessie dat een
reële bug pas zichtbaar werd door de VOLLEDIGE pijplijn (niet alleen de
kernfunctie) met sample_pace=True te draaien. Andere, nog niet
end-to-end geteste consumenten van `run_monte_carlo_adult()`'s
retourwaarden (rapportgenerators, overige plotfuncties) dienen als
verdacht te worden behandeld totdat ze ook zo zijn getest.

## [2026-09-11, vervolg] Tweede echte crash uit een live run: hestia_bridge.py's _summarize_results()

Zelfde dag, zelfde sample_pace-optie, tweede live crash -- dit keer pas
bij het genereren van het Markdown-rapport zelf (de 11 plots ervoor
liepen wel goed door, wat de vorige fix bevestigt):

```
ValueError: setting an array element with a sequence. The requested array
has an inhomogeneous shape after 1 dimensions.
  File hestia_bridge.py:576 in _summarize_results
    t_rect_sims = np.array([[r["t_rect"] for r in res] for res in all_results])
```

Exact dezelfde onderliggende oorzaak als de vorige twee keer (ragged
resultaatlengtes door sample_pace=True), nu in een DERDE, nog niet eerder
gecontroleerde consument: `hestia_bridge.py`'s `_summarize_results()`,
aangeroepen via `build_bridge_summary()` vanuit `run_hestia.py`'s
rapportage-stap.

Bij nader inzien was deze plek makkelijker te fixen dan de vorige twee:
`t_rect_sims` (de volledige matrix) werd nergens anders gebruikt dan om
er meteen de rij-maxima van te nemen (`peak_t_rect`). De rest van deze
functie is al ragged-veilig geschreven (per-deelnemer for-loops, of een
`defaultdict(list)` per minuut in `_population_median_trace()`, die van
nature met ongelijke lengtes overweg kan). Opgelost door de rechthoekige
matrix helemaal niet meer op te bouwen: `peak_t_rect` wordt nu direct
per deelnemer berekend (`np.nanmax([...]) for res in all_results`),
zonder tussenstap.

Gecontroleerd: geen andere plekken met hetzelfde patroon
(`for r in res] for res in all_results]`) elders in dit bestand.
Gereproduceerd met Koos' eigen parameters (Amsterdam 2024-09-22, MET 9,8,
seed 42) tot en met de exacte stap die crashte -- draait nu door zonder
fout. Volledige testsuite (7 bestanden) slaagt.

**Stand van zaken sample_pace, bijgewerkt**: twee van de drie tot nu toe
gevonden ragged-array-crashes zaten dus niet in de kernfunctie zelf
(die was al bij het bouwen getest), maar in twee losstaande consumenten
van de resultaten (`plot_adult_results()`, en nu
`hestia_bridge.py::_summarize_results()`) die ik niet vooraf had
gecontroleerd. Overige, nog niet zo geteste consumenten van
`run_monte_carlo_adult()`'s retourwaarden blijven verdacht.

## [2026-09-11, vervolg] Automatische circulariteitswaarschuwing in het rapport zelf

Aanleiding: Koos vertelde dat de daadwerkelijke DtDloop 2024 zo veel
ziekenhuisopnames had (50) dat de wedstrijd werd stilgelegd -- precies
het feit dat COLLAPSE_ENDPOINTS['hospitalisation'] gebruikt als
kalibratiedoel (50/35.000 = 14,29/10.000, bron: "GHOR Noord-Holland
Noord, Dam tot Damloop 2024"). Bij het vergelijken bleek: als je dat
eindpunt gebruikt om een simulatie van datzelfde evenement te
"valideren", is dat geen onafhankelijke toets -- de intercept is precies
zo vastgezet dat het model dat getal benadert.

`generate_event_report.py` waarschuwt nu automatisch voor dit geval: als
het jaartal in de kalibratiebron van het gebruikte eindpunt overeenkomt
met het jaartal van het gesimuleerde evenement, verschijnt er een expliciet
"Let op -- mogelijke circulariteit"-blok direct onder de scenario-tabel in
sectie 1. Gedetecteerd via een gedeeld 4-cijferig jaartal tussen
`active_endpoint_source` en `start_time` (niet hardgecodeerd op "Dam tot
Damloop 2024" specifiek), zodat dit ook correct afgaat voor een
toekomstig, vergelijkbaar zelfverwijzend eindpunt.

Bug gevonden en gefixed tijdens het bouwen: de eerste regex-versie
(`r"\b(19|20)\d{2}\b"`, met een capture-group om alleen de eeuw) ving
alleen "20" op in plaats van het volledige jaartal "2024" -- daardoor zou
elk jaar-paar in de 2000'en (bijv. 2024 vs 2026) ten onrechte als
overeenkomst zijn gezien. Gefixed door de capture-group niet-vastleggend
te maken (`r"\b(?:19|20)\d{2}\b"`).

Getest: eindpunt 'hospitalisation' + evenementjaar 2024 -> waarschuwing
verschijnt. Eindpunt 'hospitalisation' + evenementjaar 2026 (forecast) ->
geen waarschuwing. Eindpunt 'ehs' (Boston, geen gedeeld jaartal) +
evenementjaar 2024 -> geen waarschuwing. Volledige testsuite slaagt.

## [2026-09-11, vervolg] Diepgaand onderzoek: kloppen de cardiovasculaire uitkomsten van sample_pace met de werkelijkheid?

Aanleiding: het Amsterdam-2026-09-20-rapport (mild weer, WBGT 16,1-16,3 degC)
liet cardiovasculaire cijfers zien die nagenoeg gelijk waren aan de veel
heftigere 2024-hindcast (WBGT 20,7-21,1 degC, wedstrijd daadwerkelijk
stilgelegd) -- 3,868 vs 3,892 collapse-risico per 1.000, ondanks een groot
weerverschil. Diepgaand nagerekend of dat aan de cardiovasculaire
berekening zelf ligt, of aan de bevolkingsgeneratie.

**Bevinding: pace en conditie (VO2max) werden volledig onafhankelijk
gesampled.** Gemeten correlatie in een testpopulatie (N=1.000, seed=7):
r=-0,158. Fysiologisch zou dit sterk negatief moeten zijn -- in
werkelijkheid loopt iemand met een lage conditie een substantieel trager
tempo, juist omdat een snel tempo voor die persoon niet vol te houden is.
Concreet: iemand met vo2max=24 (de laagste waarde die het model voor
vrouwen toelaat) kreeg in de test pace-waarden tussen 5,1 en 7,4 min/km
toegewezen -- zelfs bij de traagst mogelijke pace in de hele verdeling
(7,45 min/km, de 2-uurslimiet) zat deze persoon nog op 95% van haar
VO2max, het door de code afgedwongen maximum. 37% van de populatie zat
tegen dit plafond aan, grotendeels ONGEACHT het weer -- wat verklaart
waarom de cardiovasculaire uitkomst zo weinig varieerde tussen het milde
2026-scenario en het hete 2024-scenario: een structureel, kunstmatig
aandeel van de populatie zat toch al tegen het plafond.

**Literatuuronderzoek naar de juiste doelcorrelatie**, vóór implementatie:
een klassieke ACSM-studie (Medicine & Science in Sports & Exercise, 1981,
N=50 recreatieve mannelijke marathonlopers) vond marathontijd omgekeerd
gecorreleerd met VO2max met r=-0,63. Ter ondersteuning: VO2max wordt vaak
genoemd als verklarende factor voor ~70% van de prestatievariatie tussen
lopers (R^2=0,70 -> r=0,84; TrainingPeaks, samenvattend op bredere
literatuur), en een recreatieve-marathonstudie (Gordon et al. 2017) vond
wedstrijdsnelheid gecorreleerd met lactaatdrempel-indicatoren (een nauwere
bepaler van houdbaar tempo dan VO2max alleen) met r=0,72-0,79. r=-0,63 is
gekozen als de meest directe, peer-reviewed match (VO2max specifiek), niet
naar boven afgerond richting de sterkere getallen.

**Geïmplementeerd**: `sample_recreational_pace_min_per_km()` accepteert nu
een optionele `vo2max_z`-parameter (de z-score van de deelnemer binnen
dezelfde leeftijd/geslacht-genormaliseerde verdeling waaruit vo2max zelf
is getrokken). Wanneer meegegeven, wordt pace via een Gaussian copula
gesampled: gecorreleerd met vo2max_z volgens `PACE_VO2MAX_CORRELATION`
(-0,63, met bovenstaande bronvermelding als commentaar bij de constante),
met behoud van de exacte marginale pace-verdeling (dezelfde lognormale
verdeling als voorheen -- alleen de KOPPELING met vo2max verandert, niet
de verzameling pace-waarden zelf). `generate_base_population()`'s
sample_pace-tak berekent nu deze z-score (uit de al-berekende vo2max_mu/
vo2max_sigma van diezelfde deelnemer) en geeft die door.

**Resultaat, gemeten (niet aangenomen) na implementatie:** correlatie nu
r=-0,628 (doel: -0,63 -- bevestigt dat de copula-implementatie correct
werkt). Plafond-aandeel: 37,0% -> **31,3%** -- een echte, maar bescheiden
verbetering, geen oplossing. Dezelfde tien laagste-VO2max-deelnemers uit de
oorspronkelijke test krijgen nu consequent trage paces (6,4-7,45 min/km,
merendeel exact op de 7,45-ceiling) toegewezen -- de koppeling werkt zoals
bedoeld -- maar blijven desondanks op het 95%-plafond zitten, omdat zelfs
de traagst mogelijke pace in de verdeling voor hen niet houdbaar is.

**Nog niet opgelost, expliciet, en een ander probleem dan de correlatie**:
dit wijst op een tweede, dieperliggende vraag -- is de VO2max-verdeling
zelf (met een ondergrens van 24 voor vrouwen) realistisch voor mensen die
daadwerkelijk een evenement van deze afstand/tempo-range uitlopen?
Deelname aan zo'n evenement is zelf al een selectie-effect: wie een 16,1km-
hardloopevenement daadwerkelijk uitloopt, heeft naar alle waarschijnlijkheid
al een hogere ondergrens aan conditie dan de algemene bevolking waarop de
huidige VO2max-referentiewaarden lijken te zijn gebaseerd. Dat is een apart
onderzoek (welke ondergrens is realistisch voor evenement-*finishers*,
niet voor de algemene bevolking), niet aangepakt in deze sessie.

Getest: correlatie en plafond-percentage direct gemeten voor en na (zie
boven). Volledige testsuite (7 bestanden) slaagt.

## [2026-09-11, vervolg] Uitgebreid onderzoek naar de VO2max-ondergrens, op basis van de organisatorische tijdslimiet

Vervolg op de correlatiefix. Vraag: is de tijdslimiet die organisaties
hanteren (voor Dam tot Damloop: 2 uur / 16,1 km) een goede indicatie voor
een realistische VO2max-ondergrens? Eerst onderzoek gedaan naar houdbaar
%VO2max over een inspanning van deze duur.

**Gevonden (training4endurance.co.uk, samenvattend op unter andere Costill
et al. 1973): bij getrainde atleten daalt houdbaar %VO2max van ~98% (5km)
naar ~92% (10km) naar ~78% (marathon)**, met de expliciete aantekening dat
dit bij minder getrainde/recreatieve populaties "significant lager" ligt.
Rechtstreekse recreatieve-populatiedata (eerder gevonden, PMC9566186):
recreatieve marathonlopers houden gemiddeld 74-81% VO2max vol over een
marathon (~4 uur). Voor de ~2-uurs DtD-duur (korter dan marathon, dus
hoger houdbaar percentage te verwachten, maar recreatief dus lager dan
getraind) is 0,72 gekozen als bewust conservatieve (lagere, dus minder
snel mensen ten onrechte uitsluitende) schatting, dicht bij het
recreatieve-marathoncijfer.

**Doorgerekend op de tijdslimiet zelf**: bij de traagste toegestane pace
(7,45 min/km, exact de 2-uurslimiet voor 16,1km) is 30,34 mL/kg/min VO2
vereist (via de bestaande ACSM-pace-naar-MET-conversie). Voor iemand met
de oude modelondergrens (vo2max=24) is dat 126% van het eigen maximum --
niet zwaar, maar fysiek onmogelijk. De 95%-plafondclip elders in de code
verborg dit stilzwijgend in plaats van het te signaleren.

**Geïmplementeerd**: nieuwe constante `SUSTAINABLE_VO2MAX_FRACTION_LONG_
EVENT = 0.72`, met de volledige onderbouwing als commentaar. In
`generate_base_population()` wordt, uitsluitend wanneer `sample_pace=True`
(dus specifiek voor evenement-deelnemers, niet voor HESTIA's overige
toepassingen zoals kwetsbare zittende/wandelende populaties, waar een lage
conditie wel degelijk realistisch is), een ondergrens afgeleid uit
`_acsm_met_from_pace(PACE_MIN_PER_KM_CEILING) * VO2MAX_TO_MET_FACTOR /
0.72`, en toegepast als `max(bestaande_ondergrens, afgeleide_ondergrens)`.

**Gemeten resultaat**: plafond-aandeel 37,0% -> 22,0% (in combinatie met
de eerdere correlatiefix) -- een substantiële verbetering.

**Maar: een nieuw, apart probleem gevonden bij het narekenen, niet
verzwegen.** De afgeleide ondergrens (42,1 mL/kg/min) geldt voor beide
geslachten gelijk (de fysieke vereiste hangt niet af van geslacht), maar
ligt zeer dicht bij het bestaande gemiddelde voor vrouwen (44,0, uit
Scharhag-Rosenberger et al. 2010) -- slechts 0,27 SD erboven. Gevolg:
**56,7% van de vrouwelijke populatie wordt nu tegen deze ene ondergrens
geklemd** (tegenover 23,0% van de mannen, gemiddelde 49,7, verder van de
ondergrens af) -- geen gladde verdeling meer, maar een kunstmatige piek op
één waarde bij meer dan de helft van de vrouwen.

**Niet opgelost in deze sessie, bewust**: als de afgeleide ondergrens
correct is, staat die op gespannen voet met het bestaande vrouwelijke
gemiddelde (44) voor evenement-deelnemers specifically. Dat gemiddelde zelf
aanpassen zou zijn eigen literatuuronderzoek vergen (net als bij de
ondergrens en de correlatie hiervoor) -- niet lichtvaardig gedaan binnen
deze sessie.

Getest: plafond-percentage en geslachtsverdeling direct gemeten voor en na
(zie boven). Volledige testsuite (7 bestanden) slaagt.

## [2026-09-11, vervolg] De juiste oplossing: afwijzen in plaats van vastklemmen

Vervolg op de vorige twee entries. Terechte weerstand tegen het "dit is
niet zomaar iets om te laten liggen" -- en een scherpe vraag ("misschien
moeten man en vrouw afzonderlijk behandeld worden?") die tot verder
onderzoek leidde.

**Eerst onderzocht of het sekseverschil zelf de kern was.** Een
hardloop-specifieke narratieve review (Sex Differences in Maximal Oxygen
Uptake Adjusted for Skeletal Muscle Mass in Amateur Endurance Athletes)
concludeert expliciet: "males and females do not differ in terms of
running economy or endurance (i.e. percentage VO2max sustained)". Dat
pleit TEGEN een sekseafhankelijke houdbare-%VO2max-fractie -- het
werkelijke probleem zat elders.

**Gevonden: het probleem zat niet in de ondergrens die ik had toegevoegd,
maar in het CLIP-MECHANISME zelf.** Mathematisch nagerekend: 39,3% van de
ruwe N(44,7)-verdeling voor vrouwen viel al onder de nieuwe ondergrens
(42,1) -- de leeftijdscorrectie duwde het werkelijke aandeel naar 56,7%.
Een `np.clip()` naar een vaste ondergrens duwt elke te-lage trekking naar
EXACT DEZELFDE waarde -- een kunstmatige piek, geen gladde
verdelingsstaart.

**Bovendien bleek er nog een tweede, onopgemerkt probleem in de bestaande
`pct_vo2max`-clip (0,95) te zitten**: die clip verandert niet alleen een
statistiek, maar **verandert daadwerkelijk welke MET wordt gesimuleerd**
voor die persoon -- iemand met een te-hoge vereiste inspanning wordt in
werkelijkheid gesimuleerd op 95% van hún vo2max, NIET op de MET die hun
eigen toegewezen pace impliceert. Hun `pace_min_per_km`-veld en hun
daadwerkelijk gesimuleerde inspanning kwamen dus niet meer overeen.

**Definitieve oplossing: de eerder toegevoegde vaste ondergrens is
teruggedraaid.** In plaats daarvan wordt de (leeftijd, geslacht, vo2max,
pace)-combinatie nu AFGEWEZEN (niet geklemd) wanneer `pct_vo2max_det`
(vóór ruis) boven 0,95 uitkomt -- exact hetzelfde afwijzingsmechanisme
dat deze lus al gebruikte voor bijvoorbeeld de BMI-check. Een afgewezen
combinatie wordt gewoon opnieuw getrokken (leeftijd, geslacht, vo2max EN
pace opnieuw), niet vastgeklemd op een grenswaarde.

**Resultaat, gemeten:**
- Plafond-aandeel: 37,0% (origineel) -> 31,3% (alleen correlatiefix) ->
  22,0% (correlatiefix + vaste ondergrens) -> **5,8%** (correlatiefix +
  afwijzing).
- Geen piek meer op één waarde: grootste aandeel identieke (afgeronde)
  vo2max-waarde nu 1,3% (mannen) / 2,0% (vrouwen) -- normale, gladde
  verdeling.
- Minimum geaccepteerde vo2max: 32,0 -- natuurlijk ontstaan uit de
  afwijzing, niet een arbitrair gekozen grenswaarde.
- Correlatie vo2max-pace: r=-0,764 -- sterker dan het literatuurdoel
  (-0,63). Verwacht en logisch: afwijzing verwijdert bij voorkeur precies
  de combinaties met lage vo2max + snelle pace, wat de waargenomen
  correlatie in de geaccepteerde populatie vanzelf versterkt bovenop de
  copula.
- Verworpen-pogingen: 1.430 voor 1.000 geaccepteerde deelnemers (43%
  afwijzingspercentage), ruim binnen het bestaande budget
  (`max_attempts = n_simulations * 30`).

Getest: correlatie, plafond-percentage, en afwezigheid van piekvorming
direct gemeten (zie boven). Beide andere paden (gedeelde MET, volledig
standaardpad) getest en werken ongewijzigd, met een licht hoger (verwacht)
afwijzingspercentage. Volledige testsuite (7 bestanden) slaagt.

## [2026-09-11, vervolg] Laatste onderzoek van de sessie: de "immune" PYROX-groepen herijkt

Vraag: onderzoek de vier groepen (endurance_athletes, elite_athletes,
recreational_athletes, outdoor_workers) die eerder deze sessie
"structureel onbereikbaar" bleken binnen het testbereik van
`plot_three_regimes()`.

**Eerst het omslagpunt (flip-point = recovery_threshold/(1-capacity))
teruggerekend naar de vereiste gevoelstemperatuur, via de bestaande
weer-naar-belasting-formule (thermopoulos_loader.py:
`load=(feels_like-22)*0.10`):**

| Groep | capacity (oud) | flip (oud) | vereiste gevoelstemp (oud) |
|---|---|---|---|
| outdoor_workers | 0,80 | 8,5 | 107 degC |
| recreational_athletes | 0,85 | 12,0 | 142 degC |
| elite_athletes | 0,95 | 40,0 | 422 degC |
| endurance_athletes | 1,00 | oneindig | GEEN ENKELE temperatuur op aarde |

Ter vergelijking: het hoogst ooit bevestigde hitte-index-record op aarde
is 81,1 degC (Dhahran, Saoedi-Arabië, 8 juli 2003; Guinness World
Records). Zelfs de MINST extreme van de vier (outdoor_workers, 107 degC)
lag daar ruim boven. Dit was dus niet "moeilijk bereikbaar" maar
"onbereikbaar op deze planeet", en voor endurance_athletes zelfs
wiskundig onmogelijk bij elke temperatuur.

**Bredere bevinding, buiten de scope van vandaag maar expliciet
gerapporteerd**: bij het sorteren van alle 23 groepen op flip-point bleek
zelfs `adults_18_45` (de gewone, gezonde volwassen referentiegroep)
een flip-point van 7,5 te hebben (vereist 97 degC) -- en `youth_10_18`
(5,0), `indoor_workers` (4,3), `pregnant_t1` (4,0) zitten in dezelfde
problematische zone. Het patroon is dus breder dan de vier vandaag
onderzochte groepen; deze vier waren de duidelijkste, meest extreme
gevallen, niet de enige. Aanbevolen als vervolgonderzoek.

**Literatuuronderzoek naar de daadwerkelijke epidemiologie, vóór
herijking**: een narratieve review (Périard, DeGroot & Jay 2022,
PMC9826288) laat zien dat inspanningsgebonden hitte-ziekte bij
duurhardlopen de HOOGSTE incidentie heeft van alle onderzochte sporten
(674 per 10.000 sporter-blootstellingen) -- niet de laagste. Elite-
marathons/racewalking laten incidenties tot 118-170 per 1.000 finishers
zien. Voor outdoor workers: reële, jaarlijks terugkerende
hitte-ziektegevallen (duizenden per jaar alleen al in de VS, OSHA/Nature
Sci Rep 2020), niet nul. Dit weerspreekt een eerdere aantekening in de
code zelf (bij endurance_athletes: "very-low-incidence positioning
remains well supported") -- die eerdere conclusie bleek gebaseerd op een
onvolledige lezing van de literatuur (populatie-brede basisrisico's,
niet de per-sporter/per-finisher-incidentie die deze groep zelf
beschrijft).

**Herijkt, met behoud van de relatieve volgorde**
(endurance > elite > recreational > outdoor_workers blijft de
weerstandsvolgorde, consistent met de epidemiologie: duurlopers
verdragen relatief meer inspanning langer, wat zowel hun hogere
weerstand als hun hogere absolute incidentie verklaart):

| Groep | capacity (nieuw) | empirisch geverifieerd omslagpunt |
|---|---|---|
| outdoor_workers | 0,55 | 68,5 degC |
| recreational_athletes | 0,60 | 77,0 degC |
| elite_athletes | 0,58 | 80,5 degC (net onder het wereldrecord) |
| endurance_athletes | 0,60 | 97,0 degC (bewust de meest extreme van de 23 groepen, boven het huidige record maar niet absurd) |

**Belangrijke methodologische les tijdens het verifiëren**: de eenvoudige
flip-point-formule (threshold/(1-capacity)) bleek slechts een
benadering -- het daadwerkelijke omslagpunt, geverifieerd via
`equilibrium_strain()`'s bisectie (niet aangenomen), lag voor alle vier
groepen 15-30% hoger dan de formule voorspelde (een smalle, echte
"stabiele-accumulatie"-zone tussen veilig en runaway, al eerder gezien
bij very_elderly_85plus). Eerste implementatiepoging (capacity 0,68/0,63
voor endurance/elite) gaf daardoor empirisch 100-116 degC in plaats van
de beoogde ~97-100 degC -- bijgesteld en herverifieerd tot de
uiteindelijke waarden in de tabel hierboven.

Getest: `equilibrium_strain()` direct bevraagd over een breed
belastingbereik (tot load=20) voor alle vier groepen -- runaway wordt nu
voor alle vier daadwerkelijk bereikt, niet alleen in theorie.
`plot_three_regimes()` opnieuw gerenderd: toont nu echte rode
runaway-zones met een reëel omslagpunt, in plaats van "geen runaway
gevonden". `verify.py` en de volledige smoke-test slagen.

**Nog niet gedaan, expliciet**: de bredere groep problematische groepen
(adults_18_45, youth_10_18, indoor_workers, pregnant_t1) is
geïdentificeerd maar niet herijkt in deze sessie.

## [2026-09-11, vervolg] Alle 23 groepen onderzocht, niet alleen de vier eerder gevonden

Vervolg op de vorige entry. Vraag: onderzoek alle 23 PYROX-groepen op
dezelfde manier (empirisch omslagpunt vertaald naar vereiste
gevoelstemperatuur), niet alleen de vier al gecorrigeerde.

**Methode**: voor elke groep `equilibrium_strain()` bevraagd over een
breed belastingbereik (tot load=25) om het daadwerkelijke, empirische
omslagpunt te vinden (niet de eenvoudige flip-formule, die -- zoals
eerder vastgesteld -- het werkelijke omslagpunt met 15-30% onderschat).

**Resultaat vóór verder ingrijpen: 20 van de 23 groepen bleken al
plausibel** (binnen het bevestigde wereldrecord van 81,1 degC), dankzij
de eerdere fix van de vier atleten-/werkersgroepen. Drie grensgevallen
resteerden:

| Groep | Vereiste gevoelstemp | Evidence-status |
|---|---|---|
| youth_10_18 | 84,5 degC | extrapolated |
| endurance_athletes | 97,5 degC | extrapolated |
| adults_18_45 | 112,0 degC | **paper** |

**youth_10_18 gecorrigeerd**: capacity 0,72 -> 0,68 (recovery_threshold
ongewijzigd). Empirisch geverifieerd na de fix: omslagpunt nu bij 77,0
degC, binnen het bevestigde bereik. Dit weerlegt niet de eerder
aangehaalde literatuur ("no differences... no epidemiological data show
higher heat-injury rates in children" -- Falk & Dotan 2008) -- de
kwalitatieve positionering (jongeren niet wezenlijk kwetsbaarder dan
volwassenen) blijft intact, alleen het eindige omslagpunt is teruggebracht
binnen het reële bereik.

**endurance_athletes NIET verder aangepast**: dit was vorige keer al
bewust als de meest extreme van de 23 groepen gepositioneerd (97,5 degC,
boven het huidige record maar niet absurd) -- een weloverwogen keuze,
geen nieuwe bevinding.

**adults_18_45 NIET aangepast, expliciet, en dat is een bewuste keuze,
geen omissie.** Dit is een van slechts drie groepen met
`evidence="paper"` -- de waarden (capacity=0,80, recovery_threshold=1,5)
zijn direct ontleend aan Sectie 2.3 van Koos' eigen gepubliceerde paper
(met een reeds eerder gedocumenteerde correctie van een verwisseling in
de gedrukte tabel). Deze aanpassen zonder ruggespraak zou een
inconsistentie met de gepubliceerde bron creëren -- een ander soort
probleem dan bij de "illustrative, not validated" groepen. Dit blijft
daarom expliciet openstaand, ter beslissing.

**Getest**: alle 23 groepen opnieuw empirisch doorgerekend na de
youth_10_18-fix -- eindresultaat 21/23 binnen het bevestigde
wereldrecordbereik, de resterende twee (endurance_athletes,
adults_18_45) bewust/bekend en met reden niet verder aangepast.
`suite_smoke_test.py` en `verify.py` (die specifiek "matches the
corrected paper" controleert, inclusief adults_18_45's ongewijzigde
waarden) slagen beide.


---

## 2026-10-01 — Review-opvolging (C1, C3, C4, C5, C6)

Naar aanleiding van de review "Thermopoulos-suite — technische review en
aanbevelingen" (1 oktober 2026), punten uit de categorie "nu":

- **C1 halfuur-klemming hersteld** (`thermopoulos_loader.py`,
  `get_hourly_weather`). Selectie loopt nu van `floor(start)` tot `ceil(einde)`.
  Een start om 09:30 begint nu op het geinterpoleerde weer tussen 09:00 en
  10:00 (testgeval Amsterdam 16-09-2026: 17,6 i.p.v. 17,0 graden C stedelijk).
  Starts op het hele uur zijn ongewijzigd. Gevolg: eerder gemaakte runs voor
  golven die op het halve uur starten (o.a. DtD 2026 09:30, 10:30, 11:30,
  12:30, 13:30) gebruikten in hun eerste 30 minuten het weer van het volgende
  hele uur.
- **C3 nieuwe tests**: `test_recent_features.py` (23 controles, alle geslaagd).
  Gecontroleerd dat de halfuur-test op de oude code faalt.
- **C4 documentatie**: TECHNICAL_REFERENCE.md sectie 8a, MANIFEST.md,
  CHECKSUMS.txt opnieuw berekend.
- **C5**: minimale Python-versie 3.10 vastgelegd in requirements.txt en
  README.md (pythermalcomfort >= 4 vereist zelf 3.10).
- **C6**: `test_pyrox_report.py` gebruikt een tijdelijke map in plaats van een
  vast /tmp-pad.
- Eerder vandaag: `run_pyrox.py` f-string die alleen op Python 3.12+ werkte,
  gecorrigeerd (uw Historical_Custom-wijziging).

Niet in deze ronde: C2 (UHI-dagcurve), en alle validatie- en
uitbreidingspunten (V, U), die eigen data of keuzes vragen.


---

## 2026-10-04 — CVR-module onder nul (op verzoek van Koos)

`HESTIA_CVR_Module_v2.py`, alleen voor inspanningsdeel f > 1 (voorbij het
door hitte verlaagde VO2max). Boven nul niets gewijzigd.

- Afkapping van f op 1,15 verwijderd. Die maakte de reserve onder nul
  niet-monotoon: het tekort werd kleiner bij meer hitte.
- Hartslag afgekapt op HR_max (was 1,05 x HR_max), conform metingen bij
  inspanning tot uitputting in hitte (Gonzalez-Alonso & Calbet 2003).
- Onder nul: CO_reserve = -g0 x (VO2 - VO2max_heat), met g0 = Lloyds
  basisverhouding CO/VO2. Volgt de echte hittecurve van het plafond in
  plaats van een rechte lijn; naadloos bij nul; monotoon dalend.
  MODELKEUZE, NIET GEVALIDEERD.
- Slagvolume uit geleverd volume (hooguit het plafond).
- Nieuwe test in test_recent_features.py (4 controles); faalt op de oude
  module, slaagt op de nieuwe. Alle tien testscripts slagen.
- Gepaarde run (800 lopers, 26->30 C): zelfde lopers onder nul (204),
  klinisch 42 en conjunctie 41 ongewijzigd; mediane laagste reserve
  -0,34 -> -0,53 L/min; TCF relevant 4 -> 8, max dosis 30,4 -> 50,7.
  Gevolg: eerdere TCF-aantallen (o.a. DtD 2026) horen bij de oude module en
  moeten opnieuw worden berekend.


---

## 2026-10-05 — Documentatiecontrole

- MANIFEST.md: participant_dose_analysis.py, test_individual_engine.py,
  test_uncertainty.py en test_pyrox_report.py toegevoegd (ontbraken).
- CHECKSUMS.txt: participant_dose_analysis.py toegevoegd; alle 37 kloppen.
- Verouderde opmerkingen in de code bijgewerkt: bron van K_P_PACING
  (Ely BR e.a. 2010 i.p.v. de niet-bestaande "Ely 2007") in hestia_model.py;
  verwijzing naar de afkapping op 1,15 als historisch gemarkeerd in
  HESTIA_CVR_Module_v2.py en test_cvr_freeze_fix.py.
- docs_word/: alle vijf Word-kopieen opnieuw gegenereerd uit de .md-bestanden
  (stonden op 1 oktober en misten de wijzigingen sindsdien).
