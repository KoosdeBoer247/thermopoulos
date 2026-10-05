![Thermopoulos](branding/thermopoulos.png){width=1.8in}

# HESTIA–PYROX–Klimatos Suite

A unified heat-risk modelling suite. One weather source feeds three scales:

- **PYROX** — population strain dynamics across 23 groups (control-theoretic
  dual-process model from the PYROX whitepaper).
- **HESTIA** — individual JOS-3 thermophysiology (core temp, sweat, RPE,
  survivability).
- **Klimatos.ClimateShift** — climate-trend analysis: annual maxima of
  T_air/WBT/WBGT/UTCI in sliding 30-year windows, event-window trend +
  projections for a fixed annual event (e.g. a recurring marathon), and
  (via HESTIA) EHS/EHE/collapse-risk evolution across future target years.
  Fetches and processes its own historical/forecast weather directly —
  does not need a pre-built `Thermopoulos_*.xlsx` the way PYROX/HESTIA do.

Built with **real Python imports** — no `exec`, no subprocess, no live API calls
during simulation (Klimatos is the one exception: it does make live weather
API calls, since fetching historical/forecast data is its whole purpose).
This is the cleaned successor to the old `*_Integrated_Fixed.py` attempt.

## Files

```
thermopoulos_loader.py         shared data source + weather→load bridge
pyrox_model.py                 PYROX dynamics (paper Section 2.2 / 3)
pyrox_groups.py                23 population groups (corrected & evidence-labelled)
run_pyrox.py                   loader → PYROX population assessment
hestia_model.py                HESTIA model, CVR/tailplot-calibrated (rev17); one marked edit
HESTIA_CVR_Module_v2.py        cardiovascular response module (Lloyd et al. 2022)
HESTIA_CVR_Console.py          CVR report/console formatting
HESTIA_ControlFailure_Module.py Thermoregulatory Control Failure metric
run_hestia.py                  loader → HESTIA adapter (offline; rev17 contract)
individual_engine.py           personal/individual-assessment engine (EHS/EHE/EAC criteria)
local_storage.py               local-only JSON persistence for individual_engine.py profiles/history
verify.py                      PYROX scientific verification vs the paper
suite_smoke_test.py            end-to-end plumbing test (PYROX + HESTIA individual + Monte Carlo)
generate_event_report.py       standardized, factual event report generator (Dutch, fixed template,
                                no recommendations) for one HESTIA run -- see its own module docstring
intercept_estimation.py        Newton-calibrates COLLAPSE_ENDPOINTS intercepts; run after any
                                change that shifts the T_rect/CO_reserve/dehydration distributions
                                [KNOWN GAP, 2026-08-29: not updated to the current
                                REF_CONDITIONS_BY_KEY per-endpoint architecture --
                                see INTEGRATION_CHANGELOG.md]
Klimatos_ClimateShift.py       standalone climate-trend tool -- own entry point, own weather fetch
klimatos_ehs_worker.py         parallel worker for Klimatos' EHS-evolution module
hestia_bridge.py               de-Streamlit-ified analysis layer (Falmouth EHS, true-EHE/clinical
                                criterion, margin-to-threshold) that Klimatos and generate_event_report.py
                                both use; individual_engine.py also imports from this module by name
generate_klimatos_report.py    factual Markdown report generator for a Klimatos run (climate trend +
                                EHS evolution) -- same style as generate_event_report.py, different content
generate_recommendation_report.py  ADVISORY report generator (timing interventions only: start time,
                                season/date) -- unlike the other two report generators, this one
                                contains a genuine recommendation, clearly labelled as such
generate_pyrox_report.py       factual Markdown report for one PYROX population run, embedding all six
                                pyrox_plots.py plots with plain-language captions
report_to_docx.py               shared Word (.docx) export layer used by all four report generators above
build_report_docx.js           Node/docx-js renderer report_to_docx.py calls -- node_modules/ ships
                                bundled in this suite's own .zip, no separate install step needed
HEATLim.py                     physiological liveability model (Vanos et al. 2023) used by Klimatos
diagrams/                      [2026-09] static images referenced from TECHNICAL_REFERENCE.md
                                (e.g. pyrox_control_structure.png, pyrox_control_block_diagram.png)
docs_word/                     [2026-09] Word (.docx) versions of all five .md docs below, generated
                                with pandoc -- regenerate after editing the .md source, not by hand
INTEGRATION_CHANGELOG.md       what changed in this snapshot and why
requirements.txt               dependencies
```

See `TECHNICAL_REFERENCE.md` for the full architecture overview, the model
equations (including a block diagram of PYROX's control structure), the
integration design, and the abbreviations list.

## Quick start

Requires **Python 3.10 or newer** (tested on 3.12; pythermalcomfort >= 4 itself
needs >= 3.10).

```bash
pip install -r requirements.txt
# node_modules/ (for Word/.docx export) ships bundled in this suite's own
# .zip -- no 'npm install' needed for a fresh copy of it. Only run
# 'npm install' here if you assembled this folder by hand and node_modules
# didn't come along, or if Word export reports it's missing.
python verify.py            # PYROX matches the paper
python suite_smoke_test.py  # both HESTIA/PYROX models, end to end (synthetic data if needed)
```

Then, with a real `Thermopoulos_*.xlsx` in the directory (see
`Thermopoulos_Data_Engine.py` for how to generate one):

```bash
python run_pyrox.py         # population heat-risk report
python run_hestia.py        # individual simulation
```

Klimatos needs no pre-built Excel file -- it fetches its own weather data
directly and runs standalone:

```bash
python Klimatos_ClimateShift.py   # climate-trend + EHS-evolution analysis
```

## The big picture

```
Thermopoulos_Data_Engine.py ─► Thermopoulos_*.xlsx ─► thermopoulos_loader ─┬─► run_pyrox  ─► PYROX  (population)
                                           └─► run_hestia ─► HESTIA (individual)

Klimatos_ClimateShift.py ─► (own weather fetch) ─► klimatos_ehs_worker ─► hestia_bridge ─► HESTIA
                             (independent of the above three -- shares only the underlying
                              hestia_model.py/HESTIA_CVR_Module_v2.py scientific core)
```

See **TECHNICAL_REFERENCE.md** for the architecture overview, the model
equations, the integration design, and the full abbreviations list.

## Status

- PYROX core: verified against the paper (`verify.py`, all checks pass).
- HESTIA: CVR/tailplot-calibrated version (rev17), now further updated
  2026-08-16/17/20 (see below) with fixes carried in from a separately
  maintained Streamlit-based branch; runs offline via the adapter, both
  individual and Monte Carlo.
- Klimatos: standalone climate-trend tool, independently runnable without
  any HESTIA/PYROX file present; three report generators (facts-only for
  HESTIA runs, facts-only for Klimatos runs, and one genuinely advisory
  report for timing interventions).
- Integration: real imports, single data source, no `exec`. Smoke test passes,
  now covering PYROX, HESTIA individual, and HESTIA Monte Carlo (previously
  only the first two were tested — see `INTEGRATION_CHANGELOG.md`).

Deviations from the published paper (parameter-table correction, demonstration
load) are documented in `TECHNICAL_REFERENCE.md` §3.3 and flagged in code.

**Flagged for your review:** the MET-derivation semantics changed upstream in
rev10 (see `INTEGRATION_CHANGELOG.md` and the docstring at the top of
`run_hestia.py`) — this is a modelling detail, not a plumbing bug, and is
called out rather than silently resolved.

**Also flagged (2026-08-29):** `hestia_model.py`, `HESTIA_CVR_Module_v2.py`,
`individual_engine.py`, and `pyrox_groups.py` were just replaced with newer,
independently-developed versions carrying real bug fixes (CO_reserve
freeze-on-stop, CO_reserve sign-inversion at extreme heat strain, unseeded
RNG, three PYROX population-group defects) and a clinical redefinition of
the heat-illness endpoints (EHS/EHE/EAC, replacing the older single
"collapse" concept). See `INTEGRATION_CHANGELOG.md`'s 2026-08-29 entry for
the full account, including what was deliberately NOT merged (the Streamlit
apps themselves, being retired) and one known open gap
(`intercept_estimation.py` not yet updated to match).

**[2026-09-11] Substantial session, summarized here — full detail in
`INTEGRATION_CHANGELOG.md`'s 2026-09-11 entries:**

- **Event distance is now universal**, not DtD-specific: `event_dist_km` is
  a console-adjustable parameter in HESTIA (`validate_population()`,
  `run_hestia.py`), PYROX-adjacent tooling, and Klimatos alike, with
  Riegel-scaled pace distributions (see next point) so results for a 5K, a
  half marathon, or a marathon are each computed for that actual distance,
  not the 16.1 km default reused unchanged.
- **HESTIA's population Monte Carlo can now give each participant their
  own pace, MET, and exposure duration** (`generate_base_population(
  sample_pace=True)`), instead of every participant sharing one MET and
  one duration regardless of who they are — off by default (explicit
  opt-in in `run_hestia.py`'s console flow), since it changes results
  relative to every run so far. See `TECHNICAL_REFERENCE.md` §4.6 for the
  architecture and the three ragged-duration bugs found and fixed while
  building it.
- **PYROX's "two competing feedback loops" framing was corrected to the
  actual, verified structure**: one damping path plus one closed,
  self-reinforcing loop — checked against the model's own paper abstract
  and equations (`TECHNICAL_REFERENCE.md` §3.1, now with a block diagram).
- **`equilibrium_strain()` could not distinguish "safe" from "runaway"**
  (both returned `None`) — now returns a three-way safe/equilibrium/runaway
  result, and exposed a real finding: three PYROX groups (`outdoor_
  workers`, `elite_athletes`, `endurance_athletes`) cannot reach runaway
  at any load this suite's weather pipeline can actually produce, not
  because it's rare for them but because their thresholds put it out of
  reach by construction. See `TECHNICAL_REFERENCE.md` §3.3-3.4.
- Also fixed: a silent-zero bug in the wind-profile correction for
  dense-urban terrain (§2.3), Klimatos' self-calibrating (rather than
  physiologically derived) pace-to-MET conversion (§5.7), and a mislabelled
  third physiological zone in the HEAT-Lim liveability matrix that looked
  like a rendering gap (§5.8).


