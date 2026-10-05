![Thermopoulos](branding/thermopoulos.png){width=1.8in}

# HESTIA–PYROX Suite — complete file manifest

Generated as a single consistent, tested snapshot. Every script compiles, all
modules import, `verify.py` passes, and `suite_smoke_test.py` runs both models
end to end from one data source (no exec, no live API) — **individual AND
Monte Carlo**, both for HESTIA.

**This snapshot integrates the CVR/tailplot-calibrated HESTIA (rev17)**,
previously a separate file (`HESTIA_Data_Engine_CVR_v10_calibrated_tailplot.py`)
with three undocumented dependencies, not part of any prior suite snapshot.
See `INTEGRATION_CHANGELOG.md` for exactly what changed, what was broken
before, and what is flagged for your review.

**⚠️ This snapshot also fixes a bug affecting reported TCF dose values**: the
post-finish contribution to `control_failure_dose_total` /
`tcf_dose_total_degC_L` was silently zero in every prior run of this model
(the value was computed internally but never propagated to where it's read).
See the top of `INTEGRATION_CHANGELOG.md` for the full explanation and a
concrete before/after example.

**⚠️ This snapshot also fixes the Monte Carlo population's exertion level**:
`generate_base_population()` previously ignored the chosen activity/MET
entirely and always assumed a fixed marathon-race pace. It now derives each
participant's intensity from the actually-selected `met_value`. See
`INTEGRATION_CHANGELOG.md` for the verified before/after numbers.

**⚠️ This snapshot also recalibrates PYROX's `cardiovascular_disease`
population group** (Kenney et al. 2004; Horowitz & Hasin 2023), `medication_
impaired` (Ebi et al. 2024), and `unacclimatized_travelers` (CDC NIOSH;
Racinais et al. 2015) — literature-grounded checks across PYROX's 21
extrapolated groups, prioritized by relevance. See `INTEGRATION_CHANGELOG.md`.

**⚠️ This snapshot also structurally recalibrates PYROX's pregnancy-trimester
groups** (`pregnant_t1/t2/t3`) — not a routine number update but a
reinterpretation of what each group represents, since the evidence shows
trimester-specific risk mechanisms (an acute teratogenic threshold in T1 vs.
cumulative placental-flow risk in T2/T3) rather than a single monotonically
worsening capacity axis. See `INTEGRATION_CHANGELOG.md`.

**⚠️ This snapshot also recalibrates PYROX's children/youth groups**
(`children_0_6`, `children_6_10`, `youth_10_18`) — a myth-busting finding for
school-age children/teens (comparative studies find no thermoregulatory
inferiority vs. adults, no epidemiological excess heat-injury rate), but a
deliberately more cautious, smaller adjustment for `children_0_6` given the
established-but-mechanistically-ambiguous (physiology vs. caregiver-
dependency) infant heat vulnerability literature. See
`INTEGRATION_CHANGELOG.md`.

**⚠️ This snapshot also recalibrates PYROX's `obesity` population group**
(pyrox_groups.py) against direct thermoregulation literature (Cramer & Jay
2016; Wickham et al. 2021; Faulkner et al. 2015), rather than extending
HESTIA's event-participant population to a general-population/obesity-
epidemic model, which would have duplicated PYROX's existing role. See
`INTEGRATION_CHANGELOG.md`.

**⚠️ This snapshot also adds a warning explaining an easy-to-misread result**:
for light activity / cool conditions, the collapse-risk model can correctly
produce an *identical* value for every participant (the risk formula is
threshold-gated; with zero threshold-crossings the whole population reduces
to the calibrated baseline rate). This is not a bug, but a warning is now
printed so it isn't mistaken for one. See `INTEGRATION_CHANGELOG.md`.

**⚠️ [2026-07] This snapshot also fixes terrain-roughness handling in
`Thermopoulos_Data_Engine.py`**: the 10m->1.5m wind-speed correction
previously chose a fixed roughness length purely from `population > 0`
(0.8 "urban" vs. 0.1 "rural"), which applied a suburban roughness to
open-coast race courses regardless of the actual terrain -- traced to an
implausibly low simulated wind speed (and correspondingly inflated UTCI)
for a real Falmouth Road Race hindcast. Replaced with an explicit,
per-run terrain choice (`select_terrain_roughness()`,
`ROUGHNESS_Z0_TERRAIN`: six standard Davenport/Wieringa categories from
open water to dense urban). Also fixed in the same file: the coastal-
correction flag was a shared module-level global, silently inherited by
whichever dataset (forecast/hindcast/custom-historical) was processed
after the last fetch call set it -- including the forecast, which uses a
different, higher-resolution model that never needs the correction. Now
returned explicitly per dataset and passed into `process_weather_data()`
as an argument. See `INTEGRATION_CHANGELOG.md` for the full trace.

**⚠️ [2026-07] This snapshot also removes an undocumented hard clip on
`co_reserve`/`cvs_index`** in `HESTIA_CVR_Module_v2.py`
(`co_reserve = max(-4.0, ...)`, `cvs_index = clip(..., 0, 1)`), which
collapsed every participant beyond the clip onto the same value --
destroying resolution in exactly the extreme-cohort tail the metric
exists to differentiate. Because the collapse-risk z-function's
`W_C * clip(2.0 - co_reserve, 0, None)` term depended on that clipped
range, `COLLAPSE_ENDPOINTS[*]['intercept_kal']` in `hestia_model.py` was
re-derived via `intercept_estimation.py` (now included in this snapshot --
previously referenced but missing). Current values are a reduced-sample
(N=200, single-core feasibility run) recalibration, marked PROVISIONAL --
rerun at production scale (N=10,000-50,000, multi-core) before treating
them as final.

**⚠️ [2026-07] Full English translation pass**: all Python source files
(identifiers, comments, docstrings, and printed console/demo output) and
the shorter documentation files have been translated from Dutch to
English. `INTEGRATION_CHANGELOG.md`'s pre-2026-07 history is still
largely in Dutch -- see the note at the top of that file.
`PROJECT_INSTRUCTIES.md` was translated and renamed to
`PROJECT_INSTRUCTIONS.md`.

**⚠️ [2026-07] This snapshot also rebuilds `HESTIA_CVR_Module_v2.py`'s core
cardiac-output calculation.** The previous version derived `co_demand` from
JOS-3's own `cardiac_output` output (a thermal-model sum of tissue blood
flows). Verified by direct test that this overstates the heat-driven
cardiac-output increase during exercise by roughly 5-25x relative to the
measured literature (Lloyd et al. 2022, the same paper this module already
cites: -3% to +15% during exercise in heat, vs. JOS-3's own +80% at fixed
MET between tdb=20 and 38degC). Rebuilt to implement that paper's workload-
response and heat-strain equations (Eq. 12-13, 22-32) directly instead --
validated by the paper's authors against real heart-rate data from 101
individuals (R2=0.82-0.97). Two other same-day attempts (an intensity-
dependent a-vO2diff; a MET-only VO2 calculation that silently discarded the
heat-driven signal) were tried, diagnosed as wrong, and reverted -- see
`INTEGRATION_CHANGELOG.md` for the full trace of both dead ends and the
final fix. Falmouth 2015 test result: expected collapses/1000 dropped from
92.7 to 9.75, now within/just above the documented real-world range of
3.93-9.45 (previously ~10-20x too high).

**⚠️ [2026-07] This snapshot also fixes a dead zone in the post-finish
venous-pooling formula** (`simulate_post_finish()` in `hestia_model.py`).
The old formula (`PF_DELTA_CO_POOLING`, a fraction of the shrinking
`co_res` itself) could mathematically never push a positive CO_reserve
below zero -- harmless before the CVR rebuild above (finish-line values
were often already negative), but it meant the well-documented "collapses
minutes after crossing the line" phenomenon (Roberts 1998) could no longer
be captured for the healthier post-rebuild population. Rescaled to a
fraction of CO_max (`PF_POOLING_FRAC_OF_COMAX = 0.06`, provisional) instead
-- verified that 30.7% of Falmouth-2015 test participants who finished with
a positive reserve are now correctly pushed into deficit within the
10-minute post-finish window, versus 0% before.

**⚠️ [2026-07] This snapshot also adds the runner's own forward speed to
the wind fed into JOS-3.** Previously `jos3_model.v` used ambient wind
alone -- the runner's own speed was computed (`select_met_activity()`)
but discarded. This created a large, direction-dependent asymmetry
between calm and windy race days (Falmouth 2003 vs. 2015: 35x too severe
for the calm year, versus a documented ~1.7x difference in the opposite
direction). Fixed via `compute_relative_wind()` (law-of-cosines apparent
wind, standard sailing/running-aerodynamics practice per Pugh 1971 /
Davies 1980). Wind direction and course heading are not tracked anywhere
in this pipeline, so each participant's relative wind angle is sampled
`Uniform[0, 2*pi)` in `generate_base_population()` (new `wind_angle_rad`
field on `AdultParticipantProfile`) rather than assumed -- the population
mean recovers the standard Pythagorean estimate while individual spread
reflects the real, unresolved direction uncertainty. Narrowed the
Falmouth 2003-vs-2015 model ratio from 35x to 1.5x (documented: 0.6x,
i.e. 2003 more severe) -- most, but not all, of the original discrepancy.
Not extended to the child simulation path (out of scope for this
adult-road-race investigation).

**⚠️ [2026-07] This snapshot is the project's baseline version.** A final,
unbiased re-read of the day's cumulative changes found and fixed two
behaviourally-harmless code-hygiene issues left over from same-day
revert cycles: an orphaned `pct_vo2max` field on `RunnerProfile` with a
docstring pointing at a since-removed method, and Dutch variable naming
(`SV_rust`/`HR_rust`/`CO_rust`) reintroduced after the earlier translation
pass. Verified output is byte-for-byte identical to immediately before
this cleanup. See `INTEGRATION_CHANGELOG.md` for the full detail. Use
this snapshot as the reference point to diff future changes against.

**⚠️ [2026-07] This snapshot also fixes a structural bug where post-finish
CO_reserve could mathematically never recover**, even as T_rect declined.
`simulate_post_finish()` now recomputes CO_max/CO_demand at each step via
the same `CVRModel.compute_step()` used during the race (declining T_rect,
resting MET), instead of a one-way pooling-only formula. The acute
venous-pooling dip is kept as an additive perturbation on top, not
replaced. Verified: individual trajectories now show the expected
dip-then-recover shape; overall post-finish-episode incidence dropped from
20.7% to 0.3% on the same (Falmouth 2015) scenario, since most finishers
who dip now correctly recover within the window. Checked consistent on
Falmouth 2003 and Amsterdam DtD 2024 too. See `INTEGRATION_CHANGELOG.md`
for the full trace, including a documented dead end (an apparent
"clustering" in duration that turned out to be a right-censoring artifact
of the fixed window, not a real physiological signature) that led to
finding this bug in the first place.

**⚠️ [2026-07] This snapshot also restructures `intercept_estimation.py`
to a generalizable, per-endpoint reference-conditions architecture.**
Previously all three endpoints (`ehs`, `hospitalisation`, `ehbo`) were
calibrated against one shared, module-level reference scenario (Boston's
own conditions) -- even though `hospitalisation`/`ehbo` are DtD-observed
numbers from DtD's own, different real conditions. Verified this produced
a misleading near-constant "intercept minus logit(target)" pattern across
all three that looked like a duration-scaling finding but was actually
just an artifact of sharing one z-distribution. Fixed generally (not a
DtD-specific patch): `REF_CONDITIONS_BY_KEY` now holds one reference block
per real originating event, and each `ENDPOINTS[*]` entry names its own
`ref_conditions_key` -- adding a future calibration point just means
adding one more block and one entry naming it. New intercepts:
`hospitalisation` -8.340 -> -7.282, `ehbo` -7.235 -> -6.179 (`ehs`
unchanged). See `INTEGRATION_CHANGELOG.md` for the full verification.

**⚠️ [2026-07] This snapshot adds `generate_event_report.py`** -- a
standardized, factual report template (`generate_report()`) that turns
any `monte_carlo_adult()` output into a fixed-structure Markdown report,
in Dutch, for sharing with organizations and emergency services. Contains
facts only (computed values, their definitions, and model provenance/
calibration status) -- no recommendations, so the reader draws their own
conclusions. Same section order every time, so reports from different
events can be laid side by side. See `INTEGRATION_CHANGELOG.md` for the
full section list and a bug found/fixed during testing (several `stats`
fields are time series, not scalars).

**Note on this snapshot's scope:** this package does not include the
`docs/` or `plots_examples/` directories referenced later in this
manifest and in `CHECKSUMS.txt` -- confirm with the suite owner whether
those should be added back before treating this as the complete suite.



1. Put all files in one project folder, preserving the structure below.
2. `pip install -r requirements.txt`
3. `python Thermopoulos_Data_Engine.py` — enter a city; it writes `Thermopoulos_*.xlsx` into the folder.
4. `python verify.py`            — confirms PYROX matches the paper
5. `python run_pyrox.py`         — population assessment
6. `python run_hestia.py`        — individual simulation
7. `python pyrox_plots.py`       — menu: pick a city, then the plots

## Files

### Data source (root)
| File | Purpose |
|------|---------|
| `Thermopoulos_Data_Engine.py` | Fetches weather (Open-Meteo), applies UHI, computes MRT/WBGT/UTCI, writes `Thermopoulos_*.xlsx`. **Run this first.** Interactive: enter a city, it produces the Excel the suite reads. |

### Core model (root)
| File | Purpose |
|------|---------|
| `pyrox_model.py` | PYROX dynamics — 5 daily steps, stability helpers, 3-regime structure |
| `pyrox_groups.py` | 23 population groups, corrected & evidence-labelled |
| `thermopoulos_loader.py` | Shared data source + weather→load bridge (0.10, Fouillet-calibrated); city menu; 14d+7d combined window; optional nocturnal-recovery (`night_sleep_quality`) |
| `paris2003.py` | Paris-2003 reference data (reconstructed weather + observed Fouillet mortality) |

### Run scripts (root)
| File | Purpose |
|------|---------|
| `run_pyrox.py` | Loader → PYROX population assessment; `use_nocturnal_recovery` flag |
| `run_hestia.py` | Loader → HESTIA adapter (offline; air-quality overridden). Rewritten for the rev17 CVR contract: builds `AdultParticipantProfile` (not a tuple), fixes the previously-broken `monte_carlo_adult()` wrapper, exposes CVR/control-failure fields in `summarize_individual()`. See its module docstring for flagged assumptions. |
| `hestia_model.py` | The CVR/tailplot-calibrated HESTIA (rev17: JOS-3 + cardiovascular-response module + collapse-risk model + tailplot calibration). Unchanged except one marked `[integration edit]` (stray `print("Script started")` on import, removed). Formerly the separate, undocumented `HESTIA_Data_Engine_CVR_v10_calibrated_tailplot.py`. |
| `HESTIA_CVR_Module_v2.py` | Cardiovascular Response module (Lloyd et al. 2022): `RunnerProfile`, `JOS3Outputs`, `link_cvr_to_jos3`. Required by `hestia_model.py`; previously missing from every prior snapshot (CVR silently disabled). [2026-07] Undocumented hard clip on `co_reserve`/`cvs_index` removed; see the note above. |
| `HESTIA_CVR_Console.py` | Console/report formatting for CVR population summaries, time series, comparisons, and the collapse-risk score. Required by `hestia_model.py`. |
| `HESTIA_ControlFailure_Module.py` | Thermoregulatory Control Failure (TCF) metric: integral of (T_rect excess) × (CO_reserve deficit) × dt. Required by `hestia_model.py`. Fixed one bug here: a missing comma in `format_population_summary()` was merging two report lines via implicit string concatenation. |
| `hestia_plots.py` | HESTIA plotting: reuses `hestia_model.py`'s own `plot_adult_results` (time-series + vulnerable-tail overlay) and `plot_adult_boxplots`, adds new CVR-specific plots (CO_reserve distribution, collapse-risk distribution, conjunctive-risk scatter, age-vs-collapse-risk, top-10-T_rect/bottom-10-CO_reserve extreme-cohort time course through race+10min post-finish, and the conjunctive-criterion time integral for both individual runs and the extreme cohorts). Wired into `run_hestia.py`'s CLI ("Generate plots?" prompt). |
| `intercept_estimation.py` | **[2026-07, new to this snapshot]** Newton-calibrates `COLLAPSE_ENDPOINTS['*']['intercept_kal']` against reference incidence data (Boston Marathon / DtD). Run this after any change that shifts the T_rect, CO_reserve, or dehydration distributions (e.g. the clip removal above) -- see its module docstring for the full recipe, and paste its printed `COLLAPSE_ENDPOINTS` block into `hestia_model.py` when done. |

### Tools & tests (root)
| File | Purpose |
|------|---------|
| `pyrox_plots.py` | 6 plot types: strain trajectories, feedback race, Paris validation, risk heatmap, three-regimes. City menu + group menu for regimes |
| `verify.py` | Scientific verification of PYROX vs the corrected paper |
| `suite_smoke_test.py` | End-to-end plumbing test. **Now covers three paths, not one**: PYROX population assessment, HESTIA individual simulation, AND HESTIA Monte Carlo (`monte_carlo_adult`). The Monte Carlo step is new — its absence in prior snapshots is exactly why the broken `monte_carlo_adult()` wrapper went undetected. |
| `requirements.txt` | Dependencies (PYROX core needs only numpy/pandas; HESTIA needs the full stack) |
| `README.md` | Quick orientation |
| `PROJECT_INSTRUCTIONS.md` | Project context, working relationship, and locked-in facts for whoever (human or AI) picks up this project next. Translated from `PROJECT_INSTRUCTIES.md` [2026-07]. |
| `INTEGRATION_CHANGELOG.md` | What changed in this snapshot vs. the previous one: bugs found and fixed, files added, and assumptions flagged for review. **[2026-07]** New entries (roughness/coastal fix, clip removal + recalibration, translation pass) are in English; the pre-2026-07 history is still largely in Dutch pending a dedicated translation pass. |

### Documentation (docs/)
| File | Purpose |
|------|---------|
| `TECHNICAL_REFERENCE.md` | Architecture, equations, location-independence (§5.1), control-theory regimes (§10b), glossary, references |
| `REFERENCES.md` | Verified DOIs with scope notes (what each source does and does NOT support) |
| `COUPLING_DESIGN.md` | Conceptual PYROX→HESTIA coupling design (paper-only, not implemented) |
| `FUTURE_DIRECTIONS.md` | Prioritised roadmap: NL calibration, local climatological baseline, absolute physiological ceiling (two-boundary structure), WBGT/LCZ |
| `CONTRIBUTION_AND_POSITIONING.md` | Field positioning, comparison table, control-theory basis, warning-instrument framing, honest boundaries |

### Example outputs (plots_examples/)
| File | Purpose |
|------|---------|
| `pyrox_block_diagram.svg/.png` | PYROX as a feedback control system, with transfer functions |
| `pyrox_three_regimes.png` | Dead-zone / stable / runaway, verified against simulation |
| `pyrox_forecast_uncertainty.png` | Strain with a ±2°C forecast-uncertainty band (narrow = robust warning) |

### Added during Klimatos integration (2026-08-26/27)

Everything above this line describes the 2026-07-27 baseline as uploaded.
The files below were added afterwards, additively -- none of the files
above were removed, and only `hestia_model.py` and `Thermopoulos_Data_Engine.py`
were themselves edited (see INTEGRATION_CHANGELOG.md's 2026-08-26/27 entries
for exactly what and why: a rehydration fix, an episode-count annotation on
an existing plot, a geocoding robustness fix, and explicit KNMI model
selection with fallback).

| File | Purpose |
|------|---------|
| `Klimatos_ClimateShift.py` | Standalone climate-trend tool: annual maxima of T_air/WBT/WBGT/UTCI in sliding 30-year windows, event-window trend + projections for a fixed annual event, EHS/EHE/collapse-risk evolution across target years. Independently runnable without any HESTIA/PYROX file present (`HESTIA_AVAILABLE` degrades gracefully). |
| `klimatos_ehs_worker.py` | Parallel worker for Klimatos' EHS-evolution module: runs one weather-scenario-year through `hestia_bridge.run_quick_estimate()` per call. Streamlit-free, picklable (required for `ProcessPoolExecutor`). |
| `hestia_bridge.py` | **New in this baseline** (it never had one): a de-Streamlit-ified analysis layer -- `falmouth_ehs_per_1000()`, true-EHE/clinical-criterion detection, `t_rect_co_reserve_pairs` extraction, `margin_to_threshold_stats()`/`format_margin_lines()`, `build_bridge_summary()`. Named `hestia_bridge.py` because `individual_engine.py` imports that exact module name. Not the Streamlit-caching wrapper from the separate PYROX-Streamlit-apps branch -- this suite has no Streamlit dependency anywhere in its critical path. |
| `generate_klimatos_report.py` | Fixed-template Markdown report generator for a Klimatos run (climate trend + EHS evolution), same style/philosophy as `generate_event_report.py` but for Klimatos' own DataFrames rather than one HESTIA Monte Carlo run. Wired into `Klimatos_ClimateShift.py`'s own CLI ("Generate event report?"). |
| `generate_event_report.py` | HESTIA-side fixed-template Markdown report generator for one `monte_carlo_adult()` run. Extended (2026-08-26) with a 9th section surfacing the `hestia_bridge.py` analysis layer via a new optional `bridge_summary` parameter. Wired into `run_hestia.py`'s own CLI. |
| `HEATLim.py` | Physiological liveability model (HEAT-Lim; Vanos et al. 2023) used by Klimatos' liveability-matrix/timeseries plots. |
| `uncertainty.py` | Carried over from the Klimatos branch; confirmed to import cleanly against this baseline's `hestia_model.py`/`hestia_bridge.py` (every name it needs verified present). `individual_engine.py`'s original Klimatos-branch copy was superseded on 2026-08-29 -- see the section below. |
| `test_recent_features.py` | [2026-10-01] Tests for the September/October 2026 additions: `sheet_period()`, the half-hour clamp fix, TCF arithmetic and bands, pacing/clinical constants, the conjunction and one-sided-extreme export columns, a scan for f-strings that only parse on Python 3.12+, and [2026-10-04] the CVR below-zero behaviour (monotonic, seamless, HR ≤ HR_max). 27 checks. |
| `participant_dose_analysis.py` | [2026-09] Per-participant time-series export of the dose build-up (T_rect, CO_reserve, cumulative AUC_thermisch / AUC_klinisch, Roberts flag) to Excel, at 10-min native or 5-min interpolated resolution. Offered at the end of `run_hestia.py`. |
| `test_individual_engine.py` | Regression tests for `individual_engine.py` and `local_storage.py` (signature drift, storage round-trip) without network access. |
| `test_uncertainty.py` | Acceptance tests for `uncertainty.py` (Falmouth reconstruction, uncertainty bands). |
| `test_pyrox_report.py` | Builds a PYROX report end to end (Markdown, plots, Word) from a synthetic Thermopoulos file. Uses a temporary directory since 2026-10-01. |
| `test_end_to_end.py`, `test_new_modules.py`, `test_rate_limit.py` | Klimatos' own test suite, all passing against this baseline. Complements (does not replace) `suite_smoke_test.py`/`verify.py` above, which cover the HESTIA/PYROX side. |

### Merged from the Streamlit-apps branch (2026-08-29)

The person's separate Streamlit-based branch (`app.py` + 4 other apps, sharing
the same underlying scientific core) had continued evolving independently
from 2026-07-27 through 2026-08-20 across roughly eight development sessions,
never merged into this baseline until now. The Streamlit apps themselves are
being retired (execution speed) but the shared core files carried real,
verified scientific fixes -- see INTEGRATION_CHANGELOG.md's 2026-08-29 entry
for the full account. Summary of what changed file-by-file:

| File | What changed |
|------|---------|
| `hestia_model.py` | Replaced with the 2026-08-16 version: fixes CO_reserve silently going NaN (not frozen like T_rect) for any participant who stops (RPE>=19.5) partway through a race -- previously invisible to every conjunctive criterion for the remainder of their trace. |
| `HESTIA_CVR_Module_v2.py` | Replaced with the 2026-08-17 version: fixes a sign-inversion bug where CO_reserve became non-monotonic at extreme heat strain (CHSI), spuriously turning positive again exactly where every EHE/EHS criterion needs it negative. Verified: CO_reserve now strictly decreases through CHSI 1-10, reaching -7.73 at the extreme (`test_cvr_freeze_fix.py`). |
| `individual_engine.py` | Replaced with the 2026-08-20 version: seeds the global numpy RNG (previously unseeded -- 49/60 participants changed dose between identical runs); implements the full EHS/EHE/EAC clinical redefinition (EAC = Exercise-Associated Collapse, a third endpoint, post-finish only, not previously modelled anywhere in this suite). |
| `HESTIA_CVR_Console.py`, `HESTIA_ControlFailure_Module.py` | Replaced with their translated, currently-dated versions. |
| `pyrox_groups.py` | Replaced: fixes three population-group defects (resilience double-counted via post-acclimatization threshold evaluation; several groups with unreachable recovery thresholds; endurance athletes had `max_acclimatization_capacity=1.00`, literal immunity to heat). Verified at the time: 0 groups with that value after the fix; `verify.py` confirmed "matches the corrected paper". **[2026-09-11 correction]: no longer accurate** — a later review reinstated `endurance_athletes`'s capacity to 1.00 (documented in that group's own code comments, on empirical low-incidence grounds); see `TECHNICAL_REFERENCE.md` §3.3 for what that value mathematically forces (zero reachable strain at any load, not merely low) and which other groups share the same structural issue at a finite-but-unreachable threshold. |
| `local_storage.py` | Added (was absent from this baseline entirely). Local-only JSON persistence for `individual_engine.py`'s saved profiles/history -- no network code, despite the "Streamlit branch" origin this is not Streamlit-specific. |
| `Thermopoulos_Data_Engine.py` | Two-way merged: kept this baseline's KNMI-model-selection-with-fallback fix (2026-08-26) *and* took the Streamlit branch's defensive TimezoneFinder import and translation completeness. |
| `pyrox_model.py`, `hestia_bridge.py` | Compared directly -- both identical in substance to this baseline's own copies (this baseline's `hestia_bridge.py` already expected `individual_engine.py`'s `eac_hit()`, confirming the two branches had already converged on the EAC concept independently). No change made. |

Deliberately **not** merged: the five Streamlit apps themselves, and nine
support files (`decision_support.py`, `evidence.py`, `experimental_risk.py`,
`gpx_route.py`, `terrain_lookup.py`, `individual_report.py`,
`report_generator.py`, `climate_projection_worker.py`, `pyrox_bridge.py`,
`plain_view.py`, `loop_view.py`) that none of `run_hestia.py`/`run_pyrox.py`/
`Klimatos_ClimateShift.py` import -- available to add later if needed, not
required for current console-based validation work.

**Known open gap**: `intercept_estimation.py` (the standalone recalibration
workbench script `hestia_model.py`'s own comments still reference) was not
updated -- no newer version was available in the Streamlit-branch upload.
The copy in this suite likely no longer fully matches the newer
`REF_CONDITIONS_BY_KEY` per-endpoint architecture; treat any number it
produces with extra caution until reconciled.

**Dutch text, remaining and intentional**: `generate_event_report.py`,
`generate_klimatos_report.py`, and `generate_recommendation_report.py`
deliberately produce Dutch-language report *output* for Dutch stakeholders
(GHOR, Le Champion) -- this is not a translation gap. The underlying code
itself (not report text) was verified, file-by-file, to be fully English
after this merge.

## Key facts locked into this snapshot

- Weather→load bridge: `HEAT_LOAD_PER_DEGREE = 0.10`, calibrated against Fouillet
  2003 (deviation ~day 4-6, critical/peak day 9-12, age gradient, no excess <35y).
- Nocturnal recovery (optional, OFF by default): warm nights blunt recovery via
  `q = night_sleep_quality(t_min)`. Refines the recovery term, NOT the bridge, so
  the calibration/validation is unchanged. Brings the critical warning ~1 day
  earlier on the Maastricht heatwave; catches warm-night/moderate-day edge cases.
- Stability: three regimes (dead-zone / stable accumulation / runaway), derived
  analytically and verified 24/24 against the running simulation.
- Suppression term (1−κΣ): framed as net erosion of protective benefit, not a
  mechanism (Daanen 2018).
- Integration: real imports only, one shared data source. PYROX→HESTIA model
  coupling is designed but NOT implemented (see COUPLING_DESIGN.md).
- Intended role: early-warning instrument (groups, timing, ordering), not an
  absolute mortality predictor.
- **HESTIA CVR/tailplot integration (new in this snapshot):** `hestia_model.py`
  is now the rev17 CVR-calibrated version. Population Monte Carlo
  (`run_hestia.monte_carlo_adult`) produces, in addition to the previous
  thermal/RPE/water statistics: CO_reserve percentiles, decompensation
  incidence, collapse-risk probability (Boston-Marathon-calibrated, per
  `COLLAPSE_ENDPOINTS`/`intercept_kal`), and the Thermoregulatory Control
  Failure dose. Individual runs (`simulate_individual_adult`) surface the same
  fields per participant via `summarize_individual`.
- **[flagged] MET-derivation change (rev10):** an individual's simulated MET is
  no longer `met_value` directly — it is derived from
  `vo2max * pct_vo2max / VO2MAX_TO_MET_FACTOR`. `met_value` now only feeds the
  liveability check. `run_hestia.py` back-solves `pct_vo2max` from the
  requested `met_value` for single-run calls so behaviour matches the old
  interface by default; this back-solve is an engineering bridge, not a
  validated scientific choice — see `run_hestia.py`'s module docstring.
- **[2026-07] Recalibrated collapse-risk intercepts (PROVISIONAL, reduced-N):**
  after removing the `co_reserve`/`cvs_index` clip described above,
  `COLLAPSE_ENDPOINTS['ehs']['intercept_kal']` moved from -7.903186 to
  -8.396342 (similar-sized shifts for the other two endpoints). Derived at
  N=200 (single-core feasibility run) rather than the usual 10,000-50,000 —
  rerun `intercept_estimation.py` at production scale before relying on
  these for GHOR reporting.

### Word (.docx) export added (2026-08-30)

| File | Purpose |
|------|---------|
| `report_to_docx.py` | Parses this suite's own report-generator Markdown dialect into structured blocks and calls `build_report_docx.js` to render a styled .docx. Shared by all three report generators -- see its own module docstring. |
| `build_report_docx.js` | Node/docx-js renderer. Two visual themes ("facts": blue-teal, "advisory": amber) matching the facts-vs-recommendation distinction the Markdown reports already make. |
| `package.json` | Node dependency manifest (`docx` npm package). Run `npm install` once before using Word export. |

Wired into the existing "Generate event report (Markdown)?" prompts in
`run_hestia.py` and `Klimatos_ClimateShift.py`, with a follow-up "Also
export as Word (.docx)?" question. `generate_recommendation_report.py`'s
own output works with `export_report_docx()` too (confirmed) but has no
existing CLI prompt to wire into yet -- call it directly, as shown in that
module's own docstring.

### Fourth report generator + image support (2026-08-30)

| File | Purpose |
|------|---------|
| `generate_pyrox_report.py` | Facts-only report for a PYROX `assess_population()` run, embedding all six `pyrox_plots.py` plots with plain-language captions. Group selection for the plots is computed from the actual run's results each time (most-affected + least-affected groups), not a fixed name list. Wired into `run_pyrox.py`'s `main()` (which previously had no interactive prompts at all). |

`report_to_docx.py`/`build_report_docx.js` extended to support embedded
images (`![alt](path.png)` Markdown syntax -> `ImageRun` in the .docx),
displayed at full content width with height derived from the image's own
aspect ratio (deliberately DPI-independent -- does not assume a fixed
matplotlib `dpi=` setting). Table rows now set `cantSplit: true`: a
two-word group name ("Cardiovascular Disease") wrapping onto two lines
inside its cell was, without this, sometimes split by Word across a page
boundary into a spurious extra row with empty cells -- found during
visual verification of this exact PYROX report before it shipped.

### 2026-09-11 session: universal event distance, per-person pace, and several real bugs found while building both

Full narrative detail is in `INTEGRATION_CHANGELOG.md`'s nine
2026-09-11 entries; this is the file-level summary.

| File | What changed |
|------|---------|
| `Thermopoulos_Data_Engine.py` | `wind_speed_at_height()` silently returned 0 m/s for the "Stedelijk/binnenstad" terrain option (z0=1.5 == the 1.5m target height, `ln(1)=0`). Now guards `z0>=z_target`/`z0>=z_ref` explicitly; that terrain's z0 also lowered to 1.2 so it no longer sits on the boundary. |
| `hestia_model.py` | (1) `validate_population(event_dist_km=...)` -- finish-time check no longer hardcoded to the marathon distance. (2) New `_acsm_met_from_pace()`, canonical pace->MET conversion, also used by Klimatos. (3) New `sample_recreational_pace_min_per_km()`, `AdultParticipantProfile.pace_min_per_km`/`duration_hours`, `generate_base_population(sample_pace=True)`, `run_monte_carlo_adult(sample_pace=True)` -- per-participant pace/MET/exposure duration instead of one shared value for the whole population; see TECHNICAL_REFERENCE.md §4.6. (4) `equilibrium_strain()` now returns `(state, value)` with state in {"safe","equilibrium","runaway"} instead of a bare value-or-None that conflated the first and third. (5) `_calculate_threshold_stats()` divides by the per-timestep active-participant count, not the fixed population size (a real, silent bug exposed by ragged sample_pace durations, not merely a precaution). (6) Module docstring's "two competing loops" corrected to the verified one-loop structure. |
| `run_hestia.py` | Console flow: asks for event distance before duration and derives the duration default from distance x the chosen activity's pace; new "Sample individual pace/MET/duration per participant?" prompt (default no) wired to the `sample_pace` path above. |
| `pyrox_plots.py` | `plot_feedback_race()`: corrected loop labelling (see hestia_model.py item 6), added the missing `acclimatization_potential` signal and the gap-shading that makes the reinforcing loop's effect visible, an explicit callout marking which line is the actual heat-stress outcome, caution/danger/emergency zone lines replacing a bare "critical Sigma" number, and a "principled foundation" explanatory text box. `plot_three_regimes()`: now uses `equilibrium_strain()` directly (exact + fast) instead of an 80-day brute-force approximation with a 90%-of-critical heuristic; no longer draws a false "runaway" zone for groups where none was found in the tested range. Figure sizing for the longer text box is now computed from the text itself instead of hand-tuned constants. |
| `run_pyrox.py` | New `_select_groups()` console menu (numbered list of all 23 groups, comma-separated selection / "all" / blank-for-paper-groups) -- `main()` previously always ran all 23 with no way to pick a subset. |
| `Klimatos_ClimateShift.py` | `EHS_MET_VALUE`'s pace-to-MET conversion was a linear scale self-calibrated to reproduce its own anchor value, not physiologically derived (own prior comment already flagged the ACSM equation gives a different answer) -- replaced with `_acsm_met_from_pace()`. New `EVENT_DIST_KM` console prompt; `EVENT_DURATION_MIN` is now derived from pace x distance instead of drifting independently of it (previously inconsistent with its own default pace by ~11 minutes). |
| `HEATLim.py`-adjacent (`Klimatos_ClimateShift.py`'s `plot_liveability_matrix()`) | A visual gap between the coloured Mmax region and the red survivability boundary, reported as a possible rendering bug, is a real third zone (`livability_Mmax()`'s own, stricter compensability check) that the plot left unlabelled -- now shown as a distinct grey-hatched zone with its own legend entry. Unrelated fix in the same function: the red non-survivable hatch had `alpha=0`, silently zeroing the hatch strokes themselves, not just the intended-transparent fill. |
| `TECHNICAL_REFERENCE.md` | New §2.3 (wind profile/terrain/event distance), §3.4 (equilibrium_strain fix), §4.6 (sample_pace), §5.7-5.8 (Klimatos MET fix, liveability matrix); §3.1 rewritten (one loop, not two, now with a block diagram) and §3.3 corrected (the "zero groups have capacity=1.0" claim no longer holds). |
| `diagrams/pyrox_control_structure.png` | New. Block diagram of PYROX's control structure (forcing, damping path, the one reinforcing loop with signed polarity), referenced from `TECHNICAL_REFERENCE.md` §3.1. |
| `diagrams/pyrox_control_block_diagram.png` | New [2026-09, second pass]. Same structure in classical control-block-diagram form (summing/multiplying junctions, explicit integrator for Σ(t)) at the person's request, after their own hand-drawn sketch used summing junctions where the actual equations are multiplicative (`eff_acclim = damping × (1−κΣ)`, not a subtraction) and had θ_rec/recovery not yet represented. Both diagrams are kept side by side in `TECHNICAL_REFERENCE.md` §3.1, not one replacing the other. |

**Three bugs found while testing `sample_pace`, not designed in from the
start** (full account in `INTEGRATION_CHANGELOG.md`): six population-level
per-timestep arrays assumed every participant's result list was the same
length and crashed on ragged durations (fixed via NaN-padding, with an
unpadded copy kept specifically for reads of each participant's own final
value); `_calculate_threshold_stats()`'s fixed-denominator bug (above);
and a backward-compatibility break where making the two new
`AdultParticipantProfile` fields mandatory broke three other construction
sites elsewhere in the suite (fixed with default values instead).

**Also this session, after the above was first written:** the report
generator (`generate_event_report.py`) now states explicitly whether a
given run used `sample_pace` (previously unstated -- a reader had to infer
it indirectly from unusually high cardiovascular figures). Investigating
why a mild-weather Amsterdam 2026-09-20 forecast produced cardiovascular
results nearly identical to the much more severe, real 2024-09-22 hindcast
(which halted for 50 hospitalisations) found that `sample_pace` drew pace
and `vo2max` fully independently (measured r=-0.158, should be strongly
negative) -- fixed with a literature-grounded Gaussian copula
(`PACE_VO2MAX_CORRELATION = -0.63`, from a classic ACSM marathon-performance
study). A follow-up fix (deriving a `vo2max` floor from the event's own
time limit) initially reduced the 95%-ceiling-pinned share (37.0% -> 22.0%)
but caused a new artifact -- 56.7% of women clipped to one identical value.
Replaced with rejection sampling (discard and redraw implausible
combinations instead of clipping) -- final result: **r=-0.764, ceiling-
pinned share 5.8%, no pile-up in either sex**. See `TECHNICAL_REFERENCE.md`
§4.6.1-4.6.2 for the full account, including the superseded intermediate
approach and why it was replaced.

**Known open items, unchanged by this session:**
`intercept_estimation.py` still predates the `REF_CONDITIONS_BY_KEY`
architecture (see the pre-existing "Known open gap" note above -- not
touched this session). `sample_pace=True` has not been used to regenerate
any existing event report, and its effect on the three calibrated
`COLLAPSE_ENDPOINTS` intercepts (all fit under the shared-duration
assumption) has not been assessed. `pyrox_groups.py`'s four
structurally-unreachable-threshold groups (`endurance_athletes`,
`elite_athletes`, `recreational_athletes`, `outdoor_workers` -- see
`TECHNICAL_REFERENCE.md` §3.3) are documented but not recalibrated.
