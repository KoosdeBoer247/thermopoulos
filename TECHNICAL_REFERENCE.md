![Thermopoulos](branding/thermopoulos.png){width=1.8in}

# Technical Reference — HESTIA–PYROX–Klimatos Suite

*First written 2026-08-30. This file did not exist before that date, despite
being referenced throughout README.md and in code comments across the suite
(`hestia_model.py`, `run_hestia.py`) since at least the 2026-07-27 baseline.
Written from the codebase itself — every equation, threshold, and citation
below was checked directly against the source rather than reconstructed from
memory. Where a value could not be directly verified in this snapshot, that
is stated rather than guessed.*

---

## 1. Purpose and scope

This suite answers three related but distinct questions about heat risk for
outdoor endurance events and heat exposure more broadly:

1. **PYROX** — *"How does accumulated heat strain evolve over a multi-day
   heatwave, for a given population group?"* A control-theoretic dynamical
   model (not a physiological simulation) operating on a scalar heat-load
   signal, built around a single reinforcing feedback loop
   [2026-09: corrected from an earlier "two competing loops" description --
   see section 3.1].
2. **HESTIA** — *"What happens physiologically to an individual runner (or a
   Monte Carlo population of them) during and after a specific race, given
   the weather?"* A minute-by-minute thermophysiological simulation (JOS-3 +
   a cardiovascular response module) producing core temperature, cardiac
   output reserve, and dose-based risk endpoints per participant.
3. **Klimatos.ClimateShift** — *"Is a recurring event's fixed calendar slot
   becoming systematically riskier as the climate changes, by how much, and
   what does a specific intervention (earlier start time) buy back?"* A
   climate-trend tool built on real historical reanalysis data, feeding
   HESTIA's own machinery to project EHS/EHE/collapse-risk forward.

None of the three replaces day-of-event decision-making (WBGT flag systems,
on-site medical judgement). All three are explicitly analysis/planning tools,
not real-time safety systems — see §9 for what each is not validated to do.

---

## 2. Architecture overview

```
                          ┌─────────────────────────────┐
                          │  Thermopoulos_Data_Engine.py │  (fetch + physics chain:
                          │  (Open-Meteo: forecast/      │   solar position, globe
                          │   archive/geocoding)         │   temp, MRT, WBT, WBGT,
                          └───────────────┬──────────────┘   UTCI)
                                          │
                                          ▼
                          Thermopoulos_*.xlsx (on disk)
                                          │
                                          ▼
                          ┌─────────────────────────────┐
                          │     thermopoulos_loader.py    │  (shared loader)
                          └──────┬───────────────┬────────┘
                                 │               │
                    ┌────────────▼───┐   ┌───────▼────────────┐
                    │  run_pyrox.py   │   │   run_hestia.py     │
                    │  → PYROX        │   │   → HESTIA adapter  │
                    │  (population,   │   │   (individual +     │
                    │   23 groups)    │   │    Monte Carlo)      │
                    └─────────────────┘   └──────────┬──────────┘
                                                      │
                                        hestia_model.py (shared core)
                                        HESTIA_CVR_Module_v2.py
                                        HESTIA_ControlFailure_Module.py
                                        individual_engine.py (EHS/EHE/EAC)


          ┌───────────────────────────────────────────────────────┐
          │              Klimatos_ClimateShift.py                  │
          │  (own weather fetch — ERA5 archive + KNMI/ECMWF        │
          │   forecast — independent of Thermopoulos_Data_Engine)  │
          └───────────────────────┬─────────────────────────────────┘
                                  │
                    klimatos_ehs_worker.py (parallel, per scenario-year)
                                  │
                          hestia_bridge.py
                                  │
                    hestia_model.run_monte_carlo_adult()
                    (SAME shared core as run_hestia.py above)
```

Klimatos shares the underlying physiological engine with HESTIA
(`hestia_model.py`, `HESTIA_CVR_Module_v2.py`) but has its own, independent
weather-fetch path and its own entry point. It is designed to keep working
with zero HESTIA/PYROX files present (`HESTIA_AVAILABLE` flag degrades
gracefully) — see `Klimatos_ClimateShift.py`'s own import-guard near the top
of the file.

### 2.1 Why `hestia_bridge.py` exists as a separate file

`hestia_bridge.py` is a **de-Streamlit-ified** analysis layer. A parallel,
Streamlit-UI-based branch of this suite (five `app_*.py` files, since
retired for being too slow to run) had its own version of this file using
`@st.cache_data` for UI responsiveness. This suite's copy has that decorator
removed (a worker process evaluating one weather-scenario-year has nothing
to cache against) but is otherwise the same analysis layer: the Falmouth
epidemiological regression, true-EHE/clinical-criterion detection from raw
simulation output, and the margin-to-threshold calculation. It is named
`hestia_bridge.py` — not something else — because `individual_engine.py`
imports several names from it by that exact module name.

### 2.2 Three report generators, two philosophies

| Generator | Produces | Contains recommendations? |
|---|---|---|
| `generate_event_report.py` | Fixed-template report for one HESTIA Monte Carlo run | **No** — facts only |
| `generate_klimatos_report.py` | Fixed-template report for one Klimatos climate-trend run | **No** — facts only |
| `generate_recommendation_report.py` | Advisory report on timing interventions (start time, season/date) for a specific event | **Yes**, explicitly labelled as such |

All three deliberately produce **Dutch-language** report text (the intended
audience is Dutch stakeholders — GHOR, event organisers) even though the
underlying code is English. This is not a translation gap.

### 2.3 Wind profile, terrain, and event distance (shared plumbing)

[2026-09] `Thermopoulos_Data_Engine.py`'s `wind_speed_at_height()`
(logarithmic 10m→1.5m wind-profile correction) divides by
`ln(z_target/z0)`. `ROUGHNESS_Z0_TERRAIN`'s "Stedelijk/binnenstad"
(dense-urban) option had `z0=1.5` — identical to the 1.5m target height
used everywhere in this suite — so `ln(1.5/1.5)=ln(1)=0` and that terrain
choice silently returned exactly 0 m/s regardless of the true wind speed;
the function only guarded `z0<=0`, not `z0>=z_target`. Fixed two ways:
the function now explicitly rejects `z0>=z_target` (and `z0>=z_ref`),
falling back to the reference wind with a warning instead of a silent
zero; and the "Stedelijk/binnenstad" value itself was lowered to `z0=1.2`
so it no longer sits on that boundary at all.

Event distance was previously hardcoded or inconsistent in three separate
places — `hestia_model.py`'s `validate_population()` always checked
against the marathon distance regardless of what was actually simulated;
`Klimatos_ClimateShift.py` had a fixed 16.1 km (Dam tot Damloop) with no
console entry point; `run_hestia.py` asked for a duration with no link to
distance or pace at all. All three now expose an explicit,
console-adjustable `event_dist_km` (default 16.1 km, matching the
suite's most common use case, but not hardcoded to it): `validate_
population(event_dist_km=...)` scales its expected finish-time bounds
proportionally and treats the pass/fail gate as informational for
non-marathon distances (so a legitimately different event is never
reported as a validation "FAIL" against marathon-shaped expectations);
`run_hestia.py` derives its duration prompt's default from distance ×
the chosen activity's own pace instead of an unrelated fixed number; see
§4.6 for how `event_dist_km` also now drives HESTIA's per-person
`sample_pace` distribution via Riegel scaling, and §5.7 for the same
distance parameter in Klimatos.

---

## 3. PYROX — population strain dynamics

![PYROX](branding/pyrox.png){width=1.3in}

### 3.1 Theoretical basis

PYROX is a **control-theoretic**, not physiological, model: a scalar
`cumulative_strain` (Σ) state variable per population group. [2026-09:
corrected below -- this was previously described as "two competing
feedback loops"; verified against the model's own paper abstract
(doi:10.21203/rs.3.rs-8626369/v1), which describes "a closed loop"
(singular), and against the equations in the paper's methods section,
which match `equilibrium_strain()`/`feedback_gain()` in `pyrox_model.py`
exactly, including the 0.1 coefficient (`HOMEOSTATIC_DRIVE_COEFFICIENT`).
See `pyrox_model.py`'s own module docstring for the full plain-language
account, reproduced in summary here.]

![PYROX control structure -- forcing, damping path, and the one reinforcing loop](diagrams/pyrox_control_structure.png)

*Block diagram, [2026-09]. Solid arrows are causal influences with an
explicit polarity (+ increases, − decreases the target variable). Forcing
(external heat exposure) has two effects: directly on cumulative strain,
and — with an ~10-14 day delay — on the damping path (acclimatization).
The damping path itself closes no loop; it is a straight-through
inhibitory effect driven by forcing, not by strain. The single closed
loop runs strain → suppression_factor (+) → damping path's effective
output (−) → strain (−); the product of those three signs is positive,
i.e. reinforcing (marked "R"), not balancing. This is the same structure
implemented in `pyrox_plots.py`'s `plot_feedback_race()` and derived
analytically in `equilibrium_strain()`/`feedback_gain()` below.*

A second, equivalent view, in classical control-block-diagram form
(summing/multiplying junctions and an explicit integrator), for readers
who find that notation more direct:

![PYROX control structure -- control-block-diagram form](diagrams/pyrox_control_block_diagram.png)

*Block diagram, [2026-09], second form. The two junctions on the damping
path are multiplications, not sums — `eff_acclim = damping × (1 − κΣ)`,
then `1 − eff_acclim` — a parameter-varying gain on the forcing path, not
a linear subtraction. `θ_rec` is subtracted BEFORE the `max(0, ·)`
saturation (it gates whether strain accumulates at all); `ρ(1+0.1Σ)`
recovery is subtracted AFTER saturation, outside the max() (recovery is
not gated the same way input is). The integrator's output is explicitly
clipped to `[0, Σ_crit]` — without this, the diagram would imply recovery
could drive Σ arbitrarily far below zero, which the code does not permit
(`np.clip(updated, 0.0, critical_strain)`); the Σ(t) feedback into
`suppression_factor` and `Recovery` is taken from after this clip, not
from the raw integrator output. The output itself — Σ(t), what the whole
model is ultimately for — is marked with a filled star, not just a bare
arrow-end, since a non-specialist reader could otherwise reasonably ask
"so which of these boxes is the actual answer?" This closes the one
reinforcing loop shown as the "R" marker in the first diagram above.*

**Block-by-block glossary** (applies to both diagrams above — the causal
labels on the left match the first diagram's box names; the code/paper
symbols on the right match the second):

| Block | Plain-language meaning |
|---|---|
| **Forcing** / `R(t)` | Today's external heat exposure (`baseline_heat_load`) — the only input the model doesn't compute itself; it comes from the weather pipeline. |
| **Damping path** / `acclimatization_potential` | How much protective adaptation the group has built up from *past* exposure. Driven by an ~10-14 day memory of prior days' forcing (a FIR kernel), not by today's forcing directly — this is the delay that lets a heatwave "outrun" the body's adjustment early on. |
| **1 − κΣ** / `suppression_factor` | The gate that closes the one reinforcing loop. Starts at 1 (full protective benefit available) and shrinks toward 0 as cumulative strain Σ rises — at Σ = critical_strain it reaches exactly 0, cancelling the damping path's benefit entirely regardless of how much adaptation has built up. |
| **× (damping path)** | Combines the two above: `eff_acclim = damping × suppression_factor`. Multiplicative, not additive — a large damping potential is worth nothing if the gate has already closed. |
| **1 − (·)** | `1 − eff_acclim` — turns "how much protection is left" into "what fraction of the load still gets through." |
| **× (main path)** | `R(t) × (1 − eff_acclim)` — today's forcing, reduced by whatever fraction of it the (possibly suppressed) damping path absorbs. This is the "experienced load" — what the group actually has to deal with today, as opposed to the raw weather. |
| **θ_rec** / `recovery_threshold` | A floor, not a signal that varies over time: below this experienced load, nothing accumulates at all — the group can fully handle that much load on an ordinary day. |
| **Saturation** / `max(0, ·)` | Only load *above* θ_rec ever counts toward strain; this block discards the (necessarily non-negative, since it's already past a subtraction) rest, giving `net_strain_input`. |
| **Recovery** / `ρ(1 + 0.1Σ)` | Strain the group clears today regardless of today's weather — driven by rest/sleep, not exposure. Rises slightly with existing strain (`0.1Σ` term): a body under more strain works a little harder to recover, but not enough to outpace a reinforcing loop already in motion. |
| **∫ dt** | The accumulator: today's cumulative strain is yesterday's plus today's net change (`net_strain_input − Recovery`). This is the model's memory of everything that has happened so far in the heatwave. |
| **Clip** / `[0, Σ_crit]` | Strain can't go below 0 (there's no such thing as "negative heat strain") and is capped at `critical_strain` (beyond that point the group is defined as being in runaway decompensation — see §3.4). |
| **Σ(t) — the output** | Cumulative strain: the one number this entire model exists to produce. Everything else on the page explains how it gets there, and it alone feeds back into `suppression_factor` and `Recovery` above — the mechanism that makes this a dynamical system rather than a one-shot calculation. |


- **Damping path (acclimatization)**, not a loop on its own: repeated heat
  exposure builds short-term adaptation, which lowers the *experienced*
  load. This path has a start-up delay — adaptation is driven by an
  ~10-14 day exposure memory (Périard, Racinais & Sawka 2015), so it
  cannot act on day one of a heatwave. It is driven by the external
  forcing, not by strain, so on its own it does not close a loop.
- **The one reinforcing loop**: once load exceeds a group-specific
  `recovery_threshold`, strain accumulates. Rising strain then *erodes the
  net protective benefit* of acclimatization via a coupling term
  `(1 - kappa * Sigma)` — an effective description of the net outcome, not a
  claim about a specific physiological blocking mechanism. Tracing the
  polarity around this cycle (strain -> suppression: +; suppression ->
  effective acclimatization: -; acclimatization -> strain: -) gives a
  positive product: a single, self-reinforcing loop, not two loops in a
  race.

Because the damping path starts late and the one reinforcing loop acts
from day one, the outcome depends on which gets ahead first: under mild
load, damping gets ahead before the loop can bite, and strain stabilises
(an `equilibrium_strain` exists below critical); under severe load, the
reinforcing loop overtakes the damping path before it can engage, net
protection collapses to zero, and the system "runs away" to
`critical_strain` regardless of starting point (no equilibrium exists —
see `equilibrium_strain()`'s three-way "safe"/"equilibrium"/"runaway"
result). The critical strain level is not a tuned threshold — it falls
out of the algebra of the suppression term.

**Reference**: de Boer, K. (2026). "A Control-Theoretic Framework for
Dynamic Heat Risk Assessment: Modeling Acclimatization, Cumulative Strain,
and Stability Thresholds During Multi-Day Heat Exposure." Research Square.
https://doi.org/10.21203/rs.3.rs-8626369/v1

### 3.2 Symbol reference (paper notation → code name)

| Paper | Code | Meaning |
|---|---|---|
| R1 | `baseline_heat_load` | Tier-1 input |
| R2 | `final_risk` | Tier-3 output |
| α | `acclimatization` | current adaptation level |
| α_max | `max_acclimatization_capacity` | group-specific ceiling |
| Σ | `cumulative_strain` | the state variable |
| Σ_crit | `critical_strain` | runaway threshold (derived, not tuned) |
| κ | `strain_suppression_strength` | net-protection erosion rate |
| θ_rec | `recovery_threshold` | load above which strain accumulates |
| ρ | `base_recovery_rate` | |
| γ | `strain_amplification` | |
| u(t) | `exposure_signal` | |
| s(t) | `acclimatization_stimulus` | |
| h[k] | `exposure_memory_weights` | FIR kernel over ~10-14 days |
| Δ | `net_strain_input` | |

### 3.3 The 23 population groups, and what changed 2026-08

`pyrox_groups.py` defines 23 demographic/occupational groups (age bands,
outdoor workers by exertion level, endurance athletes, and others), each
with its own `recovery_threshold`, `max_acclimatization_capacity`,
`base_recovery_rate`. Three real defects were found and fixed (2026-08,
prior to this suite's own 2026-08-29 merge — see
INTEGRATION_CHANGELOG.md for the full provenance):

1. **Resilience double-counted**: `recovery_threshold` was evaluated *after*
   acclimatization's load reduction was applied, making the *effective* flip
   load `recovery_threshold / (1 - max_acclimatization_capacity)` rather
   than the threshold alone. Outdoor workers, for example, had an effective
   tolerance far above any achievable weather load.
2. **Unreachable thresholds**: several groups had raw `recovery_threshold`
   values exceeding any load the model could ever produce, meaning strain
   could structurally never accumulate for them regardless of real-world
   plausibility.
3. **Endurance athletes had `max_acclimatization_capacity = 1.00`** —
   literal, complete immunity to heat, not a physiologically defensible
   claim.

**[2026-09] Correction to the paragraph below**: this snapshot's own
"verified: zero of 23 groups" claim, made after the August 2026 fix, is no
longer accurate — `endurance_athletes` currently has
`max_acclimatization_capacity = 1.00` again. A later review (documented in
`pyrox_groups.py`'s own extensive comment block at that group's
definition) re-confirmed this value deliberately, on the grounds that
empirical elite-sport EHS incidence is very low, consistent with a
capacity in the 0.95–1.00 range. That empirical grounding is reasonable,
but the specific value 1.00 was not re-checked against what the value
*mathematically forces*: `net_strain_input`'s flip point is
`recovery_threshold / (1 - capacity)`, undefined (division by zero) at
capacity=1.00 — meaning this group cannot accumulate ANY strain at ANY
load, by construction, not merely "rarely." Checked against the weather
pipeline's own achievable load ceiling
(`daily_weather_to_heat_load()`, `thermopoulos_loader.py`: load =
(feels-like − 22°C) × 0.10, giving a realistic Dutch/European maximum
around 2.3–2.8): `outdoor_workers`, `recreational_athletes`, and
`elite_athletes` have the same structural problem at a finite but still
unreachable flip point (8.5, 12.0, and 40.0 respectively, all far above
the ~3.0 pipeline ceiling) — confirmed via `plot_three_regimes()`
(§3.4 below): these three groups show **zero runaway occurrences across
123 tested load values up to R1=2.5**, not because runaway is rare for
them, but because it is unreachable given how this pipeline generates
`baseline_heat_load`. Not yet fixed in `pyrox_groups.py` itself — flagged
here since the "verified: zero of 23 groups" claim otherwise overstates
what was actually re-confirmed as still true.

Verified in this snapshot (historically, at the time of the August fix):
zero of the 23 groups had
`max_acclimatization_capacity = 1.0` (`verify.py`'s own "matches the
corrected paper" check exercises this against the then-current values;
it has not been re-run against the current `endurance_athletes` value).

**[2026-09, resolved]** All four groups named above were recalibrated
this session. Grounded in a literature finding that reframes the whole
premise: endurance athletes have the *highest* exertional heat illness
incidence of any sport studied (674 per 10,000 athlete-exposures —
Périard, DeGroot & Jay 2022, PMC9826288), not the lowest — the "very-low-
incidence... well supported" reasoning in the August review above was
based on an incomplete reading of the literature (population-wide base
rates, not the per-athlete-exposure or per-finisher rates that actually
describe this group). Checked against real-world extremes, not just the
pipeline's own typical range: the highest heat index ever confirmed on
Earth is 81.1°C (Dhahran, Saudi Arabia, 2003) — `outdoor_workers` alone
required 107°C, `endurance_athletes` required an infinite temperature at
any load. Recalibrated (capacity lowered, `endurance_athletes` no longer
at the literal 1.00 ceiling), preserving the relative resistance ordering
(endurance > elite > recreational > outdoor_workers) while bringing every
threshold to a finite, empirically-verified (via `equilibrium_strain()`
bisection, not the flip-point formula alone — see the note on why they
differ, next to the code itself) value: 68.5°C (outdoor_workers), 77.0°C
(recreational_athletes), 80.5°C (elite_athletes, just under the confirmed
record), 97.0°C (endurance_athletes, deliberately left as the single most
resistant group in the 23-group taxonomy, above the confirmed record but
not absurdly so). Full account, including the broader pattern this
exposed (`adults_18_45` and three other groups share the same structural
issue, not yet addressed), in `INTEGRATION_CHANGELOG.md`'s final
2026-09-11 entry.

**[2026-09, follow-up] All 23 groups checked, not only the four above.**
The same empirical method applied to every group: **20 of 23 were already
plausible** (within the confirmed 81.1°C world record) as a direct
consequence of the four-group fix above. Three borderline cases remained:
`youth_10_18` (84.5°C), `endurance_athletes` (97.5°C, already deliberately
positioned as the most extreme of the 23, not touched again), and
`adults_18_45` (112.0°C). `youth_10_18` was corrected (capacity
0.72→0.68, threshold unchanged) — empirically verified at 77.0°C after
the fix, without reversing the literature this group's parameters are
otherwise grounded in (adolescent thermoregulation is not meaningfully
inferior to adults' — Falk & Dotan 2008). **`adults_18_45` was
deliberately left unchanged**: it is one of only three groups with
`evidence="paper"` status, its values taken directly from the paper's
own Section 2.3 (already once corrected for a printed-table transposition
error). Changing it without the author's sign-off would create an
inconsistency with the published source itself — a different and more
serious problem than the "illustrative, not validated" groups this
session otherwise recalibrated. Final state: 21/23 groups within the
confirmed real-world range; the remaining two are a deliberate design
choice (`endurance_athletes`) and a paper-constrained value awaiting an
explicit decision (`adults_18_45`), not oversights.

**Important labelling note, stated directly in the source**: the majority of
these 23 groups (per the code's own comments) are *"illustrative, not
validated, do not cite as empirical values"* — parameter values are
physiological-plausibility estimates, not measured constants. Only the
overall dual-loop *structure* (validated against the 2003 French heatwave's
age-graded, cumulative excess-mortality pattern — Fouillet et al. 2006) has
a direct empirical anchor.

**[2026-09] Console group selection**: `run_pyrox.py`'s `main()` previously
always assessed all 23 groups with no way to pick a subset from the
console, even though `assess_population()` itself already accepted a
`group_names` argument (used programmatically by `generate_event_
report.py`). A new `_select_groups()` prompt lists all 23 (marking the
three paper-specified ones and each group's `evidence_status`) and
accepts comma-separated numbers, `all`, or blank (falls back to the three
paper groups — the previous programmatic default).

### 3.4 The three-regime plot and `equilibrium_strain()`'s safe/equilibrium/runaway result

[2026-09] `equilibrium_strain()` (bisection for the steady-state strain at
a constant load) previously returned a bare `Optional[float]`: `None`
whenever `daily_change(strain)` had the same sign at both ends of
`[0, critical_strain]` — but that happens in two opposite situations that
were indistinguishable to any caller: `daily_change` negative throughout
(strain always decays to 0 — **safe**) and `daily_change` positive
throughout (strain always grows to `critical_strain` — **runaway**, the
case the function's old docstring's "None = runaway" was describing,
incorrectly, for both). Now returns `(state, value)` with `state` one of
`"safe"` / `"equilibrium"` / `"runaway"`.

`plot_three_regimes()` (previously a brute-force 80-day-simulation
approximation of the steady state, edge-detected via a `> 0.9 ×
critical_strain` heuristic that mislabelled any group with a genuine
but sub-90%-of-critical equilibrium as still "dead-zone safe") now calls
`equilibrium_strain()` directly — exact rather than approximated, and
much faster (bisection vs. simulating 80 days per tested load). When no
runaway state occurs anywhere in the tested load range (the
`outdoor_workers`/`elite_athletes` case described in §3.3 above), the
plot now says so explicitly instead of drawing a red "runaway" zone
starting at the edge of the tested range, which would otherwise imply
that edge is a real transition point rather than simply where testing
stopped.

---

## 4. HESTIA — individual thermophysiology

![HESTIA](branding/hestia.png){width=1.3in}

### 4.1 JOS-3

HESTIA's thermal engine is JOS-3 (Takahashi et al. 2021), a 17-segment
multi-node human thermoregulation model computing core/skin temperatures,
sweat rate, and blood flow redistribution from ambient conditions, activity
level (MET), and clothing insulation (`clo_value`).

**Known calibration history (relevant to trusting any specific number)**:
`clo_value` was for a period hardcoded at 0.5 (light indoor clothing)
instead of 0.2 (typical warm-weather running kit) — correcting this dropped
median simulated peak race-phase core temperature from 41.4°C to 40.0°C and
the fraction exceeding the clinical EHS threshold from 93% to 8%, validated
against Veltmeijer et al. (2014) Zevenheuvelenloop field data (mean T_rect
39.2°C, 15% ≥40°C at WBGT 11°C). This fix is present in this snapshot.

### 4.2 The cardiovascular response (CVR) module

`HESTIA_CVR_Module_v2.py` implements Lloyd et al. (2022)'s cardiovascular
response equations — cardiac output (CO), heart rate, stroke volume, and
CO_reserve (available cardiac capacity above resting demand) as a function
of JOS-3's own thermal state, the runner's workload (current MET), and the
Cardiac Heat Strain Index (CHSI).

**Key fixed defects, present in this snapshot** (both discovered and fixed
2026-08, in the parallel Streamlit-based branch, merged into this suite
2026-08-29 — full account in INTEGRATION_CHANGELOG.md):

- **CO_reserve froze incorrectly to NaN, not to its last value**, for any
  participant who stopped mid-race (RPE ≥ 19.5) — the rest of that
  participant's trace was silently invisible to every conjunctive
  criterion (EHE, EHS, EAC — see §4.3), regardless of their true
  physiological state at the point they stopped.
- **CO_reserve was non-monotonic at extreme heat strain** (a sign-inversion
  bug: two negative factors in the CO_reserve formula multiplied to give a
  spuriously positive value at the highest CHSI values) — meaning every
  conjunctive criterion requiring `CO_reserve < 0` silently stopped firing
  in exactly the most severe simulated scenarios. Verified in this snapshot
  (`test_cvr_freeze_fix.py`): CO_reserve now strictly decreases through
  CHSI 1–10, reaching −7.73 at the extreme.
- Earlier (2026-07): JOS-3's own `cardiac_output` field was found to
  **overstate the heat-driven CO increase during exercise by roughly
  5–25×** relative to Lloyd et al.'s own measured figures (their Fig. 2D:
  −3% to +15% during exercise in heat, versus JOS-3's own field showing
  +80% at fixed MET across a tdb 20→38°C range). Fixed by computing CO
  directly via Lloyd's Eq. 12–31 (workload response + CHSI) rather than
  reading JOS-3's own output.
- A **law-of-cosines apparent-wind correction** was added: JOS-3 was being
  fed ambient wind alone, discarding the runner's own forward speed
  entirely. Wind direction (untracked anywhere in this pipeline) is
  represented as a per-participant Monte Carlo variable, Uniform[0, 2π).
  This resolved most of a large asymmetry between two historical Falmouth
  Road Race years (2003 vs. 2015) that had been ~35× in the model versus a
  documented ~1.7× in the opposite direction in the literature; with the
  runner's own speed included, the model's gap narrowed to ~1.5× (still in
  the reverse direction of the documented figures — plausibly attributable
  to definitional differences between the two years' source studies, not
  fully resolved).

### 4.3 EHS / EHE / EAC — three distinct, non-interchangeable endpoints

A prior single "collapse" concept was split into three properly-grounded,
clinically distinct endpoints (`individual_engine.py`), **each with its own
temporal window** — this is enforced in code, not just documentation:

| Endpoint | Full name | Criterion | Window | Calibration status |
|---|---|---|---|---|
| **EHS** | Exertional Heat Stroke | T_rect ≥ 40.5°C **AND** CO_reserve ≤ 0 | during exertion | Calibrated against Falmouth/Boston pooled data |
| **EHE** | Exertional Heat Exhaustion | T_rect > 39.5°C **AND** CO_reserve < 0 | during exertion only | Uncalibrated (mechanistic only) |
| **EAC** | Exercise-Associated Collapse | sustained CO_reserve deficit, **no temperature condition** | post-finish only | Uncalibrated (mechanistic only) |

**A naming collision worth knowing about**: `hestia_bridge.py`'s own field
`pct_true_ehs_criterion` uses the *same numeric threshold* as EHS above
(T_rect ≥ 40.5, CO_reserve ≤ 0) and is the mechanistically correct one — an
*earlier* naming convention in this suite's own reporting layer had, for a
period, called the *Falmouth epidemiological regression* "EHS" instead
(`falmouth_ehs_per_1000` — a population-level statistical estimate with no
mechanistic criterion at all) and referred to the mechanistic 40.5°C
criterion as "the clinical criterion" to avoid confusion. Both quantities
still exist in the code under those two different names
(`falmouth_ehs_per_1000` and `pct_true_ehs_criterion`) — they are **not the
same thing** despite the overlapping "EHS" language, and any report
surfacing both should say explicitly which is which (see
`generate_klimatos_report.py`/`generate_event_report.py`'s own margin
sections for the pattern to follow).

EAC citations: Asplund & O'Connor (2011); Roberts (2007); StatPearls. The
Gothenburg Half Marathon reports 1.53 EAC cases per 1000 runners, and EAC
accounts for 59–85% of finish-line medical-tent visits — making it, by
incidence, the *most common* of the three endpoints in real events, despite
being the most recently added to this suite and the least represented in
its own historical reporting.

### 4.4 The collapse-risk endpoints (calibrated, logistic)

`hestia_model.py`'s `COLLAPSE_ENDPOINTS` table holds three **separately
calibrated, logistic-model** endpoints — a different mechanism from EHS/
EHE/EAC above (those are hard conjunctive thresholds; these have a
calibrated intercept and never floor at exactly zero):

| Key | Label | p_obs | Source | Status |
|---|---|---|---|---|
| `ehs` | EHS (clinical, Boston Marathon pooled) | 9/10,000 | Breslow RG et al. (2021) Am J Sports Med 49(10):2696-2703 | PROVISIONAL |
| `hospitalisation` | Hospital admission (DtD 2024) | 50/35,000 | GHOR Noord-Holland Noord, Dam tot Damloop 2024 | PROVISIONAL |
| `first_aid` | (renamed from `ehbo`) | — | DtD 2024, same origin as `hospitalisation` | PROVISIONAL |

**Calibration architecture history worth knowing**: all three endpoints
were, for a period, calibrated against a *single shared reference scenario*
(Boston Marathon conditions: 4h, 18–22°C, MET 11.0) — even though
`hospitalisation` and `first_aid` are DtD-observed numbers under DtD's own,
quite different conditions (~1.63h, Amsterdam, September). This was found to
be a real, non-harmless problem: `intercept − logit(p_obs)` was nearly
constant across all three endpoints purely because they shared one
reference z-distribution, not because of any genuine relationship between
event duration and incidence. Fixed via a generalizable per-endpoint
architecture (`REF_CONDITIONS_BY_KEY`, in `intercept_estimation.py`) so each
endpoint is now calibrated against its own matching reference conditions.

**All three intercepts in this snapshot were fit at N=200** (a single-core
feasibility run) rather than the production-scale 10,000–50,000 the model
is designed for. `intercept_estimation.py` is the standalone recalibration
workbench for re-deriving these at full N — **see the known gap noted in
§8**: this suite's current copy of that script predates the
`REF_CONDITIONS_BY_KEY` architecture and should not be trusted to reproduce
the current intercepts without reconciliation.

### 4.5 The Thermoregulatory Control Failure (TCF) metric

`HESTIA_ControlFailure_Module.py` implements an experimental, mechanistic
dose measure: `control_failure_increment()` computes
`thermal_excess(T_rect) × co_deficit(CO_reserve)` per timestep, integrated
over the race and post-finish window (`ControlFailureConfig`'s
`t_rect_crit=40.5`, `co_reserve_limit=0.0` by default — matching EHS's own
threshold, not EHE's). This is *not* a raw temperature-times-reserve
product (which has no physically meaningful zero-point — see
`hestia_plots.py`'s `plot_conjunctive_dose_extreme_cohorts()` docstring for
why) but a purpose-built dose function with defensible units.

### 4.6 Per-person pace, MET, and exposure duration (`sample_pace`)

[2026-09, new] Until this addition, `run_monte_carlo_adult()` gave every
simulated participant the **same** `met_value` and the **same**
`interp_data` weather window (hence the same exposure duration),
regardless of who they were. The existing VO2max/`pct_vo2max` Monte Carlo
variation only changes how hard that one shared pace *feels* to a given
participant (relative intensity, RPE), not how fast they actually move
or how long they are exposed to the weather — confirmed by tracing
`generate_base_population()`'s met_value branch (`vo2_at_event_pace =
met_value * VO2MAX_TO_MET_FACTOR`, the *same* `met_value` for every
participant) through to `run_monte_carlo_adult()`'s `worker_args`
construction (the same `interp_data`/`met_value` tuple entries for every
`params` in the population loop).

`generate_base_population(sample_pace=True, event_dist_km=...)` now
gives each participant their own pace, sampled from
`sample_recreational_pace_min_per_km(gender, event_dist_km)` — a
gender-conditioned lognormal distribution anchored on real Dam tot
Damloop finish-time data (median 5.35 min/km men / 6.15 min/km women at
the 16.1 km anchor distance), Riegel-scaled (`(D2/D1)^1.06`, Riegel
1977/1981) to whatever `event_dist_km` is given so the distribution
itself — not just the resulting duration — shifts correctly for other
event distances. **Known limitation, not yet addressed**: Vickers &
Vertosick (2016, n=2,303 recreational runners) found Riegel's marathon
predictions came in at least 10 minutes too fast for about half of
runners; no separate, larger marathon-specific exponent is implemented,
so `sample_pace` results for `event_dist_km` well beyond half-marathon
(21.1 km) should be read as an optimistic bound, not a precise estimate.

Each participant's pace converts to their own MET (`_acsm_met_from_pace()`,
the ACSM running/walking equations — see §5's Klimatos MET-conversion
note, which uses the same function) and their own `duration_hours =
pace × event_dist_km`. `run_monte_carlo_adult(sample_pace=True)` widens
the fetched weather window to the slowest participant the pace sampler
can produce (`PACE_MIN_PER_KM_CEILING × event_dist_km`), then gives each
participant a *slice* of that shared `interp_data` sized to their own
duration (via each entry's own timestamp, not a hardcoded interval
assumption) and their own derived MET, instead of the shared tuple every
participant received before.

**Architectural consequence, fixed in the same change**: population-level
per-timestep arrays (`t_rect_sims`, `water_sims`, `hr_sims`, `cvs_sims`,
and three others) assumed every participant's result list was the same
length — true by construction before `sample_pace`, false the moment
durations vary. Ragged results are padded to the longest participant's
length with NaN for the purpose of building these arrays only; a
separate, unpadded copy of the raw results is kept for every place that
reads a participant's own *final* value (`res[-1]...]`), so a
short-duration participant's real last reading is never confused with
padding. `_calculate_threshold_stats()` (percentage of the population
above a T_rect threshold, per timestep) divides by the number of
participants still active at that timestep, not the fixed population
size — otherwise participants who already finished would silently count
as "below threshold" and dilute the percentage as more of the field
finishes. This entire ragged-duration path is off by default
(`sample_pace=False`); the pre-existing shared-duration behaviour is
unchanged when it is not explicitly requested.

**Not yet done**: `sample_pace=True` has not been used to (re)generate any
of this suite's existing event reports, and its effect on the three
calibrated `COLLAPSE_ENDPOINTS` intercepts (§4.4) — all fit under the
shared-duration assumption — has not been assessed.

### 4.6.1 Pace–VO2max correlation (fixed) and a second, unresolved issue it exposed

[2026-09] `sample_pace`'s cardiovascular output looked weather-insensitive
in practice: an Amsterdam 2026-09-20 forecast (mild, WBGT 16.1–16.3°C)
produced a collapse-risk figure (3.868/1,000) nearly identical to the much
more severe 2024-09-22 hindcast (WBGT 20.7–21.1°C, the real event was
halted for 50 hospitalisations) at 3.892/1,000. Investigated directly:
pace and `vo2max` were sampled **fully independently** of each other —
measured correlation r=−0.158 in a 1,000-person test population, when
physiologically it should be strongly negative (fitter people genuinely
run faster; a real race's observed pace distribution already reflects
this self-selection). Concretely, a participant at `vo2max=24` (this
model's own floor for women) still landed at `pct_vo2max=0.95` (the
enforced ceiling) even at fast-for-her sampled paces, because pace was
drawn from the population-wide distribution with no reference to her own
fitness.

**Literature-grounded target correlation, researched before implementing**:
a classic ACSM study (Costill et al., *Medicine & Science in Sports and
Exercise* 1981, N=50 recreational male marathoners) found marathon time
inversely correlated with VO2max at r=−0.63. Supporting figures: VO2max is
commonly cited as explaining ~70% of inter-individual race-performance
variance (R²≈0.70 → r≈0.84; TrainingPeaks, summarising the wider
literature), and Gordon et al. (2017, recreational marathoners) found race
speed correlated with lactate-threshold markers (a closer determinant of
sustainable pace than VO2max alone) at r=0.72–0.79. −0.63 was used as the
most direct, peer-reviewed VO2max-specific match, not rounded toward the
stronger supporting figures.

**Fix**: `sample_recreational_pace_min_per_km()` now accepts an optional
`vo2max_z` (the participant's own z-score within the same age/gender
normal distribution `vo2max` was drawn from). When given,
`generate_base_population()`'s `sample_pace` branch draws pace via a
Gaussian copula correlated with it at `PACE_VO2MAX_CORRELATION = -0.63` —
a direct bivariate-normal construction (`z_pace = ρ·vo2max_z +
√(1-ρ²)·noise`, then `pace = exp(log(median) + σ·z_pace)`), which leaves
pace's own marginal (lognormal) distribution exactly as calibrated;
only its pairing with `vo2max` changes.

**Measured after the fix, not assumed**: correlation r=−0.628 (matches the
−0.63 target, confirming the copula works as intended). The
95%-VO2max-ceiling-pinned share dropped from 37.0% to **31.3%** — a real
but modest improvement, not a resolution. The same ten lowest-`vo2max`
participants from the original test now consistently receive slow paces
(6.4–7.45 min/km, most at the 7.45 ceiling) — the coupling works — yet
remain pinned at the 95% ceiling regardless, because even the *slowest*
pace this distribution can produce is not sustainable for someone at
`vo2max=24` over ~100 minutes.

**A second, distinct, unresolved issue this exposed**: whether the
`vo2max` distribution's own lower tail (floor 24 for women, 28 for men —
§4.6's `generate_base_population`) is realistic for people who actually
*finish* an event at this distance/pace range at all. Event participation
is itself a selection effect — real finishers of a 16.1 km mass
participation run are very unlikely to be drawn from as low a fitness
floor as a general-population reference distribution would suggest. Fixing
the pace↔fitness correlation does not address this; it is a separate
question about the `vo2max` marginal distribution itself, requiring its
own literature basis, not undertaken this session.

#### 4.6.2 From a floor-clip to rejection sampling — the correct fix

[2026-09] Investigated on the hypothesis that an event's organisational
time limit is a natural, literature-groundable way to derive a realistic
`vo2max` floor for finishers. Researched the duration↔%VO2max relationship
first: trained-athlete figures (training4endurance.co.uk, summarising
Costill et al. 1973 and others) show sustainable %VO2max falling from
~98% (5 km) to ~92% (10 km) to ~78% (marathon), explicitly noting
recreational populations sustain "significantly lower" fractions at a
given duration; direct recreational-population marathon data (§4.6.1's
PMC9566186 citation) found 74–81% sustained over ~4 hours. Computed
directly: at `PACE_MIN_PER_KM_CEILING` (7.45 min/km, the 2-hour course
limit), the required VO2 is `_acsm_met_from_pace(7.45) ×
VO2MAX_TO_MET_FACTOR` ≈ 30.34 mL/kg/min — for the *original* floor
(`vo2max=24`), that is **126% of the person's own maximum**, not merely
strenuous but physiologically impossible; the pre-existing
`pct_vo2max=0.95` ceiling clip silently absorbed this rather than
surfacing it.

**First attempt (superseded): a derived floor clip.** Raising
`vo2max_clip`'s floor to ≈42.1 (from `required_vo2_at_ceiling /
SUSTAINABLE_VO2MAX_FRACTION_LONG_EVENT`, 0.72 chosen as a literature-
grounded conservative estimate) did reduce the 95%-ceiling-pinned share
(37.0% → 22.0% combined with the §4.6.1 correlation fix) — but introduced
a *third* problem: the derived floor sits only 0.27 SD below the
*existing* female mean (44.0, Scharhag-Rosenberger et al. 2010), and
since `np.clip()` maps every below-floor draw to the exact same value,
**56.7% of the female population ended up clipped to one identical
vo2max** — not a smooth distribution tail, but an artificial spike.

**Investigated whether sex-specific treatment was the right fix instead**
(a natural next question given the female-specific severity of the
spike). A running-specific narrative review (*Sex Differences in Maximal
Oxygen Uptake Adjusted for Skeletal Muscle Mass in Amateur Endurance
Athletes*) states explicitly that "males and females do not differ in
terms of running economy or endurance (i.e. percentage VO2max
sustained)" — evidence against making `SUSTAINABLE_VO2MAX_FRACTION_
LONG_EVENT` itself sex-specific. The real defect was the *mechanism*
(clip → point mass), not the target value or its uniformity across sexes.

**Fix**: the floor-clip approach was reverted. Instead,
`generate_base_population()` now **rejects** (via the same `continue`-
based rejection this loop already uses for e.g. its BMI-plausibility
check) any `(age, gender, vo2max, pace)` draw whose deterministic
`pct_vo2max_det = vo2_at_event_pace / vo2max` exceeds 0.95, *before*
adding economy-variability noise or clipping — applied universally (not
only under `sample_pace`), since a >95% deterministic requirement is
implausible regardless of which code path produced it. A rejected draw
is simply redrawn (fresh age, gender, `vo2max`, *and* pace), rather than
having any of its values forced to a boundary.

**Measured after this fix (replacing the §4.6.1-only correlation
figures)**: 95%-ceiling-pinned share **5.8%** (down from 37.0% originally,
22.0% with the superseded floor-clip approach). No pile-up: the largest
share of participants sharing one (rounded) `vo2max` value is 1.3% (male)
/ 2.0% (female) — an ordinary, smooth distribution. Minimum accepted
`vo2max` in a 1,000-person test population: 32.0, an emergent value from
rejection, not an arbitrary chosen cutoff. Measured correlation between
`vo2max` and pace: **r=−0.764** — stronger than the §4.6.1 literature
target of −0.63, an expected consequence of rejection preferentially
removing exactly the low-`vo2max`/fast-pace combinations, compounding
with the copula already in place. Rejection rate: 1,430 attempts for
1,000 accepted profiles (43%), comfortably inside the existing
`max_attempts = n_simulations × 30` budget.

**Also fixed as part of this investigation**: the pre-existing
`pct_vo2max=0.95` clip did not only round a displayed statistic — it
changed *which MET was actually simulated* for a capped participant (to
whatever 95% of their own `vo2max` implies), leaving their recorded
`pace_min_per_km` inconsistent with their simulated effort. Rejecting the
draw upstream, instead of clipping its consequence downstream, removes
this inconsistency too: every accepted participant's simulated effort now
matches their own recorded pace.

---

## 5. Klimatos.ClimateShift — climate-trend analysis

![Klimatos](branding/klimatos.png){width=1.3in}

### 5.1 Data sources

- **Historical**: Open-Meteo's Archive API (ERA5 reanalysis), no `models=`
  parameter (KNMI's regional forecast model has no multi-decade historical
  archive equivalent — irrelevant to this code path).
- **Forecast** (used only by the event-window's near-term context, not the
  historical trend): Open-Meteo's Forecast API, explicitly requesting
  `models=knmi_seamless` for higher resolution over the Netherlands/Belgium
  (2 km native, 2.5-day window, blended with ECMWF beyond that), with an
  automatic fallback to Open-Meteo's own default model for any location
  outside KNMI's coverage (confirmed via a documented Open-Meteo GitHub
  issue: an out-of-domain model request returns HTTP 400 with a specific,
  checkable error body).

### 5.2 Annual maxima and sliding windows

For each of four variables (T_air, WBT, WBGT, UTCI), annual maxima are
computed and analysed in **sliding 30-year windows, 5-year steps**
(`WINDOW_LENGTH=30`, `WINDOW_STEP=5`), against a fixed
**1951–1980 reference period** (`REFERENCE_PERIOD`, the NASA GISS
pre-warming baseline convention). Both a **Normal** and a **GEV**
(Generalized Extreme Value, `scipy.stats.genextreme`) distribution are
fit to each window, reported side by side rather than the GEV being
presented as unconditionally superior.

### 5.3 Trend detection

**Theil-Sen slope estimation** with **Mann-Kendall** significance testing —
chosen over ordinary least-squares specifically for robustness to the
non-normal, heavy-tailed behaviour of annual extremes. An optional trend-
acceleration check (`check_trend_acceleration()`) scans for a breakpoint
year using bootstrapped before/after slope comparison; see that function's
own docstring for why a found breakpoint should not be causally attributed
to a specific mechanism (e.g. aerosol dimming/brightening) outside
Europe/North America, where that mechanism was originally characterised.

### 5.4 Urban Heat Island correction

`calculate_uhi_oke()` implements Oke's (1973) population-based UHI model
with a modern correction and diurnal weighting — applied optionally
(`apply_uhi` flag), producing `T_air_urban = T_air_rural + UHI_delta`
alongside the unmodified rural signal, so a report can show both the clean
regional climate signal and the urban lived-environment value.

### 5.5 The event-window module

For a fixed annual event (a specific calendar date, start time, duration),
Klimatos computes the mean of each heat-stress variable over that
event-specific window across the same 30-year record — deliberately
**not** the annual maxima. A recurring, empirically confirmed finding
across the runs conducted with this suite: the event-window mean warms
noticeably *more slowly* than the annual maxima (roughly a factor of 3-4 in
several real city analyses), because the annual maxima are driven by
whichever week of the year happens to produce the summer's peak heatwave —
which does not necessarily coincide with any specific fixed calendar date.
This is why event-specific analysis, not a generic climate-trend headline,
is the relevant input for a recurring-event risk question.

### 5.6 EHS-evolution and the margin-to-threshold analysis

Klimatos' own worker (`klimatos_ehs_worker.py`) runs each weather-scenario-
year through `hestia_bridge.run_quick_estimate()` (small ensemble,
deliberately n≈5, since weather dominates realisation-to-realisation
variance at this scale — see the module's own CONFIG note) and
deliberately **pools and subsamples** (T_rect, CO_reserve) pairs across many
realisations (`SCATTER_PAIRS_PER_DAY_CAP`) rather than preserving full,
ordered, per-participant traces — a deliberate trade-off keeping IPC/memory
costs manageable across thousands of realisations, at the cost of not being
able to directly feed the same pooled data into `hestia_plots.py`'s
individual-trace plotting functions without a further architectural change.

The **margin-to-threshold** calculation
(`hestia_bridge.margin_to_threshold_stats()`, and an independent copy in
`Klimatos_ClimateShift.py`'s own `_ehe_margin_stats()` for the same reason
`hestia_bridge.py` cannot be hard-imported there — see §2.1) answers a
question a bare percentage cannot: when EHE/EHS reads 0%, *how close* did
the sampled population actually come? Because EHE/EHS are **conjunctive**
(both T_rect and CO_reserve must cross simultaneously), the relevant
distance is the *harder-to-close* of the two margins, not either axis in
isolation — `max(t_threshold − T_rect, CO_reserve − c_threshold)`,
minimised across all sampled points. This has repeatedly changed the
practical reading of a "0%" result from reassuring to concerning across
real analyses conducted with this suite (observed margins as small as a
few hundredths of a degree/L·min⁻¹ in some real runs, versus multiple
degrees/L·min⁻¹ in others).

### 5.7 Pace, MET, and duration consistency (`EHS_MET_VALUE`/`EVENT_DURATION_MIN`)

[2026-09] `klimatos_ehs_worker.py`'s pace-driven MET (`EHS_MET_VALUE`) and
event duration (`EVENT_DURATION_MIN`) were previously two independent
hardcoded constants that did not actually agree with each other: the
5:30 min/km pace implied by `EHS_MET_VALUE`'s own comment corresponds to
88.5 minutes over the 16.1 km Dam tot Damloop distance, not the
`EVENT_DURATION_MIN=100` default both were shipped with. Separately, the
pace-to-MET conversion itself was a linear scale (`0.733 × speed_kmh`)
fitted so it happened to reproduce the existing `EHS_MET_VALUE=8.0`
constant at that one anchor pace — self-calibrating, not derived from a
physiological model; the code's own prior comment already noted the
ACSM running equation gives a "noticeably higher MET" at the same pace.

Both fixed together: pace now converts to MET via `_acsm_met_from_pace()`
(the ACSM running/walking equations directly — same canonical function
§4.6 describes for HESTIA's `sample_pace`), and a new `EVENT_DIST_KM`
constant lets duration be derived from pace × distance whenever a pace is
entered, instead of drifting independently. At the 5:30 min/km anchor,
this moved the defaults from MET=8.0/duration=100min to MET=11.4/
duration=89min — a real, ~30% change in the MET default, not a rounding
adjustment; treat any climate-shift run predating this fix as using the
old, internally-inconsistent pair.

### 5.8 HEAT-Lim liveability matrix — the non-compensable-but-survivable zone

`compute_mmax_met()`/`plot_liveability_matrix()` wrap `HEATLim.py`
(Vanos et al. 2023's published model, validated to <1e-14 against the
authors' own matrices — not modified). [2026-09] A visual gap between the
coloured `Mmax` region and the red `Survivability()` boundary — reported
as looking like missing data — is in fact a third, real physiological
zone the plot previously left unlabelled: `livability_Mmax()` has its own,
*stricter* compensability check (`Ereq < Emax_constrain`) than the
broader survivability boundary, and returns NaN wherever it fails — "can
survive, but zero activity is sustainable without storing heat," by the
function's own docstring. Confirmed numerically for Amsterdam at RH=60%:
`Mmax` already goes NaN at Ta=35.75°C, while `Survivability()` does not
flip to non-survivable until Ta=38.75°C. `plot_liveability_matrix()` now
shades this zone explicitly (grey dotted hatch, its own legend entry)
instead of leaving it blank. Unrelated rendering fix in the same
function: the non-survivable zone's own red hatching had `alpha=0`,
which silently zeroed the hatch strokes along with the intentionally
transparent fill — edge colour is now set explicitly on the returned
contour set instead (also fixes a matplotlib ≥3.8 API change: `QuadContourSet`
no longer exposes `.collections`).

---

## 6. Key equations quick-reference

- **Falmouth epidemiological EHS regression** (`hestia_bridge.
  falmouth_ehs_per_1000`), DeMartini et al. (2014), fit on n=12 individual
  race-years at the Falmouth Road Race:
  `EHS per 1000 finishers = 0.004 × exp(0.250 × T_amb,°C)`, R²=0.653, P=.001.
- **Heat-attributable admissions ERF** (Klimatos), van Loenhout et al.
  (2018): log-linear exposure-response function, MMT (minimum-mortality
  temperature) ≈ 21°C, β ≈ 0.0158/°C — plus a β-free heat-degree-day
  robustness check reported alongside it in every Klimatos run, so the
  admissions ratio is never presented as dependent on the β estimate alone.
- **HR_max** (age-predicted): Tanaka et al. (2001), `HR_max = 208 − 0.7 × age`.
- **CO = SV × HR** (Lloyd et al. 2022, Eq. 2), with CO/HR/SV computed via
  the full Eq. 12–31 workload-and-CHSI-dependent system, not JOS-3's own CO.

---

## 7. Glossary / abbreviations

| Term | Meaning |
|---|---|
| CHSI | Cardiac Heat Strain Index |
| clo | Clothing insulation value (dimensionless, ISO 9920 units) |
| CO | Cardiac output |
| CO_reserve | Cardiac output reserve — CO_max minus current CO demand |
| CVR | Cardiovascular Response (module) |
| EAC | Exercise-Associated Collapse |
| EHE | Exertional Heat Exhaustion |
| EHS | Exertional Heat Stroke — **see §4.3 for the naming-collision caveat** |
| ERF | Exposure-Response Function |
| GEV | Generalized Extreme Value (distribution) |
| HR | Heart rate |
| JOS-3 | 17-segment multi-node human thermoregulation model (Takahashi et al. 2021) |
| MET | Metabolic equivalent of task |
| MMT | Minimum-mortality temperature |
| MRT | Mean radiant temperature |
| PYROX | Populational strain model (this suite's population-tier component; also historically expanded as "Populational Yield for Relative Outdoor eXposure") |
| RPE | Rating of Perceived Exertion |
| SV | Stroke volume |
| TCF | Thermoregulatory Control Failure (metric) |
| T_rect | Rectal (core) temperature |
| UHI | Urban Heat Island |
| UTCI | Universal Thermal Climate Index |
| VO2max | Maximal oxygen uptake |
| WBGT | Wet Bulb Globe Temperature |
| WBT | Wet-bulb temperature |

---

## 8. Known open gaps in this snapshot (2026-09-11)

- **`intercept_estimation.py`** was not updated during the 2026-08-29
  Streamlit-branch merge — no newer version was available in that upload.
  The copy in this suite likely predates the `REF_CONDITIONS_BY_KEY`
  per-endpoint architecture described in §4.4. Treat any figure it produces
  with extra caution until reconciled.
- **All three `COLLAPSE_ENDPOINTS` intercepts** are fit at N=200, not
  production scale — re-run `intercept_estimation.py` at full N (once
  reconciled) before treating absolute collapse-risk numbers as final;
  ratios (current-vs-reference, current-vs-projected) are comparatively
  more robust to this than the absolute figures, since a systematic
  calibration bias partially cancels in a ratio.
- **[2026-09] `sample_pace=True` (§4.6) has not been used to regenerate any
  existing event report**, and its effect on the three `COLLAPSE_ENDPOINTS`
  intercepts above (all fit under the old shared-duration assumption) has
  not been assessed — the intercepts and the new per-person exposure model
  have not yet been reconciled with each other.
- **[2026-09] Four PYROX groups had a structurally unreachable runaway
  threshold — resolved.** `endurance_athletes`, `elite_athletes`,
  `recreational_athletes`, `outdoor_workers` (§3.3) required feels-like
  temperatures of 107–∞°C to ever reach runaway — above the highest heat
  index ever confirmed on Earth (81.1°C, Dhahran 2003). Recalibrated
  (§3.3), grounded in a literature finding that endurance athletes have
  the *highest*, not lowest, exertional heat illness incidence of any
  sport studied (674/10,000 athlete-exposures — Périard, DeGroot & Jay
  2022). Empirically verified (not merely estimated) new thresholds:
  68.5–97.0°C, three of the four now within the confirmed world-record
  range.
- **[2026-09] All 23 groups checked (follow-up) — resolved to 21/23, two
  remaining by deliberate choice, not oversight.** The suspicion that the
  pattern extended beyond the original four groups was confirmed and then
  addressed: empirically checking all 23 groups (not just sorting by the
  approximate flip-point formula) found 20/23 already plausible as a
  consequence of the four-group fix above; `youth_10_18` was the one
  remaining case worth correcting and was fixed (84.5°C → 77.0°C).
  `endurance_athletes` (97.5°C) is deliberately the most extreme of the
  23 by design, not an oversight. `adults_18_45` (112.0°C) is one of only
  three `evidence="paper"` groups — its values come directly from the
  published paper and were deliberately left unchanged pending the
  author's explicit decision, since altering them would create an
  inconsistency with the published source rather than merely updating an
  "illustrative, not validated" placeholder.
- **[2026-09] The Riegel fatigue exponent (1.06) used for `sample_pace`'s
  distance scaling (§4.6) is not marathon-specific** — Vickers & Vertosick
  (2016) found it underestimates recreational marathon slowdown for about
  half of runners. No separate, larger exponent is implemented for
  `event_dist_km` beyond half-marathon.
- **[2026-09] `vo2max`'s lower tail for event finishers (§4.6.1–4.6.2) —
  resolved.** An initial fix (a derived floor clip) reduced the
  95%-ceiling-pinned population share (37.0% → 22.0%) but caused a new
  artifact (56.7% of women clipped to one identical value). Replaced with
  rejection sampling (discard and redraw implausible `(age, gender,
  vo2max, pace)` combinations instead of clipping any of their values) —
  95%-ceiling-pinned share now 5.8%, with no pile-up (largest shared
  value ≤2.0% of either sex) and no sex-differential distortion.
- **This document itself** should be checked against the codebase again
  after any future merge — it was written from a single snapshot and, like
  every other piece of documentation in this suite, will drift if not
  actively maintained alongside code changes. See INTEGRATION_CHANGELOG.md
  for the pattern of keeping a dated, append-only record of what changed
  and why, which is the mechanism that made writing this document possible
  in the first place.

---

## 8a. Additions September–October 2026 (documented 2026-10-01)

Added after the 2026-09-11 snapshot above; covered by `test_recent_features.py`.

### HESTIA

- **Gradual cardiovascular pacing term** (`hestia_model.py`). The pacing law is now

  ```
  met_reduction = kp_ind    * max(0, T_rect - T_RECT_PACING_THRESHOLD)        # 38.5 °C
                + kp_ind_cv * max(0, CO_RESERVE_PACING_THRESHOLD - CO_reserve) # 2.0 L/min
  current_met   = max(1.5, met_initial - met_reduction)
  ```

  Previously the cardiovascular term only acted below CO_reserve = 0 (a hard
  knee). The 2.0 L/min onset reuses the existing decompensation reference;
  `K_P_PACING_CV = 0.10` remains **[NOT VALIDATED]**. Paired A/B test (same
  population, seed 42, N=800): EHE −30 %, mean collapse probability −14 %.
  The choice takes a side in an unresolved debate (Périard et al. 2011,
  Exp Physiol 96(2):134–144, versus the published rebuttal in 96(4):476–478).
- **Thermal pacing citation corrected**: Ely BR et al. (2010), Med Sci Sports
  Exerc 42(1):135–141 (the previously cited "Ely 2007, 39:1949–1955" does not
  exist).
- **Point-of-no-return flags** (Monte Carlo export): `conjunctie_ooit_bereikt`,
  `conjunctie_eerste_min`, `conjunctie_ooit_hersteld` — first time step at
  which T_rect > 40.5 °C AND CO_reserve ≤ 0 hold simultaneously, and whether
  that conjunction ever lapses again during the race. Computed after the
  post-loop CVR linking, so it uses the same `co_reserve` values as every
  other reported metric. Race phase only; the post-finish phase is not
  covered. Observed so far: 0 of 10 cases recovered (simulation only).
- **One-sided-extreme diagnostics** (Monte Carlo export): `thermisch_percentiel`,
  `cardiovasculair_percentiel`, `eenzijdig_extreem` (≥ 97.5th percentile on at
  least one axis), `gemist_door_bestaande_criteria`. Percentiles are relative
  *within one run* — the flagged count is fixed by construction and says
  nothing about absolute risk; only the "missed" share is informative.
- **`participant_dose_analysis.py`**: per-participant time series export
  (T_rect, CO_reserve, cumulative AUCs, Roberts flag) at 10-min native or
  5-min interpolated resolution.
- **TCF thresholds** (`HESTIA_ControlFailure_Module.py`): checked against all
  five cited sources — none supports the specific values 5 / 20 / 60 °C·L.
  The construction (product-integral of thermal excess and cardiovascular
  deficit) is physiologically motivated; the thresholds are an internally
  consistent, illustrative scale (**[NOT VALIDATED]**), plausibly built as
  1.0 °C × 0.5 L/min × {10, 40, 120} min. Open research question for a
  clinical partner.

- **CVR below zero (2026-10-04, model choice, not validated)**
  (`HESTIA_CVR_Module_v2.py`). Above zero nothing changed (Lloyd 2022,
  Eq. 29–31). Three changes beyond the heat-reduced VO2max (f > 1):
  1. The workload fraction is no longer clipped at 1.15. That clip made the
     reserve non-monotonic: the deficit *shrank* with more heat (e.g. −0.54 at
     41.6 °C back to −0.01 at 42.8 °C, MET 10), because the reserve became
     −0.15 × (CO_max_heat − CO_rest_heat), a difference that narrows with heat.
  2. Heart rate is capped at HR_max (was 1.05 × HR_max). In exercise to
     exhaustion in the heat, HR reaches maximal values and stroke volume and
     delivered cardiac output fall (González-Alonso & Calbet 2003, Circulation
     107:824–830).
  3. Beyond f = 1 the unmet oxygen demand is converted to blood with Lloyd's
     baseline CO–VO2 relation: g0 = (CO_max − CO_rest)/(VO2max − VO2rest),
     CO_demand = CO_max_heat + g0 × (VO2 − VO2max_heat), so
     CO_reserve = −g0 × (VO2 − VO2max_heat). This follows the real heat curve
     of the ceiling, joins Eq. 30 seamlessly at f = 1, and decreases
     monotonically with heat. It is demand that is *not* delivered; reported
     SV now uses delivered CO (at most the ceiling).
  Effect (paired run, 800 runners, 26→30 °C): the same runners cross zero
  (204), klinisch/EHE/conjunction unchanged, but deficits are deeper (median
  of minimum reserve −0.34 → −0.53 L/min) and TCF doses larger (relevant
  4 → 8, maximum dose 30.4 → 50.7 °C·L). **TCF thresholds and any earlier
  TCF counts (incl. the DtD 2026 comparison) belong to the previous module
  and must be recomputed.**

### Data Engine, loader and PYROX

- **`Historical_Custom` sheet**: the Data Engine can fetch any past period
  (ERA5 archive, 1940 onwards). `ThermopoulosData.sheet_period(sheet)`
  returns its interval; `run_pyrox.py`'s `_select_data_sheet()` offers it
  first when present, otherwise lists Forecast_7d / Hindcast_14d with their
  periods.
- **Half-hour clamp fixed** (`get_hourly_weather`, 2026-10-01): the hourly
  selection now starts at `floor(start)` and ends at `ceil(end)`. Before, a
  09:30 start received the 10:00 values for its first 30 minutes (including
  the hour-10 UHI factor instead of hour 9). Whole-hour starts are unchanged.
  Reports for half-hour waves produced before this date are affected.

### Maintenance

- Minimum Python version recorded: **3.10** (pythermalcomfort ≥ 4 requires
  it; tested on 3.12). `test_recent_features.py` scans all modules for
  f-strings that only parse on Python ≥ 3.12.
- `test_pyrox_report.py` now uses a temporary directory (works on Windows).

### Still open (from the 2026-10-01 review)

- **UHI diurnal step function** (`Thermopoulos_Data_Engine.py`): factor 0.6
  up to 09:59, 0.2 from 10:00 — a ~2 °C urban drop between 09:00 and 10:00
  while rural air warms. Not yet smoothed.
- **JOS-3 bias** (+0.18 °C, sport-specific validation) is not corrected in
  headline figures.
- **PYROX weather-to-load bridge** calibrated on Paris 2003 only; nocturnal
  recovery (`use_nocturnal_recovery`) is off by default. Amsterdam,
  18–29 June 2026, is the natural second test.
- **`PACE_MIN_PER_KM_CEILING = 7.45`** is the Dam tot Damloop course limit and
  is not rescaled for other event distances.

---

## 9. What this suite is not

- Not a real-time, day-of-event safety system — no component here replaces
  on-site medical judgement or an official WBGT flag protocol.
- Not validated for outcome prediction in most population groups PYROX
  covers — the majority of its 23 groups are explicitly labelled in source
  as illustrative parameter estimates, not measured constants.
- Klimatos' projections are a **naive linear extrapolation** of an observed
  historical trend, not a physical climate model, and not a forecast for
  any specific year.
- No component in this suite has had independent, external peer review as
  of this snapshot. Internal test suites (`verify.py`, `suite_smoke_test.py`,
  and the others listed in MANIFEST.md) confirm internal consistency and
  regression-safety, not scientific correctness.
