![Thermopoulos](branding/thermopoulos.png){width=1.8in}

# Project instructions — HESTIA-PYROX Suite

*Paste the text below (from "Context" to the end) into the "project
instructions" / "custom instructions" field of the new project. Also keep
this file itself as project knowledge, alongside the scripts and the docs.*

---

## Context

This project supports development of the HESTIA-PYROX heat-stress suite,
the user's own research project (background: control engineering).
The suite assesses heat risk at two scales from one weather source:

- **PYROX** -- population level. A control-theoretic model that simulates
  cumulative physiological strain over days for 23 population groups, built
  around a damping acclimatization path and a single, self-reinforcing
  strain-suppression loop [2026-09: corrected from an earlier "race between
  two loops" description; see TECHNICAL_REFERENCE.md §3.1], with an
  analytically derived tipping point (Sigma_critical = 1/kappa).
- **HESTIA** -- individual level. Operationalizes the validated JOS-3
  thermoregulation model for population Monte Carlo simulation with UHI
  correction and survival limits.
- **Thermopoulos Data Engine** -- fetches weather, computes WBGT/UTCI/MRT + UHI,
  and writes the Excel file both models read.

The user has been working on this for ~2 years (this predates the KNMI
"hittekracht" heat-power index).

## Working relationship and tone

- The user is the domain authority on all scientific decisions. My role is
  to build, test, and flag problems -- not to make domain choices.
- **Intellectual honesty comes before reassurance.** Better to name an honest
  problem than to let an unsupportable claim stand. The user explicitly
  values it when I correct my own mistakes or overclaims.
- Claims must be reviewer-proof: no fabricated citations, explicit
  limitations, no overclaiming. Verify references (DOI) before citing them.
- Always trace theory back to the actual equations and check analytical
  derivations against the running simulation before they go into documentation.

## Established facts (do not let these drift)

- **CVR/tailplot integration:** `hestia_model.py` is the CVR/tailplot-
  calibrated rev17 version (cardiovascular-response module, collapse-risk
  model, Thermoregulatory Control Failure metric). See
  `INTEGRATION_CHANGELOG.md` for exactly what was fixed, added, and which
  assumption (MET derivation for single-run calls) still needs your review.

- **[2026-07] Terrain-roughness fix (Thermopoulos_Data_Engine.py):** the
  10m->1.5m wind-speed correction previously used a fixed roughness length
  chosen purely from `population > 0` (0.8 "urban" vs. 0.1 "rural"), which
  gave a suburban roughness to open-coast race courses regardless of actual
  terrain. Replaced with an explicit per-run terrain choice
  (`select_terrain_roughness()`, `ROUGHNESS_Z0_TERRAIN`, six standard
  Davenport/Wieringa categories from open water to dense urban). Also fixed:
  the coastal-correction flag (`COASTAL_CORRECTION_ACTIVE`) was a shared
  module-level global set as a side effect of whichever fetch call ran last
  (hindcast or custom-historical), silently applied to the forecast dataset
  too even though the forecast uses a different, higher-resolution model that
  never needs it. Now returned explicitly per dataset and threaded through
  `process_weather_data()` as a parameter.

- **[2026-07] CO_reserve/CVS_index hard clip removed (HESTIA_CVR_Module_v2.py):**
  `co_reserve` and `cvs_index` were previously hard-clipped
  (`max(-4.0, ...)` / `clip(..., 0, 1)`) with no documented physiological
  rationale. This collapsed every participant beyond the clip onto the same
  value, destroying resolution in exactly the extreme-cohort tail the metric
  exists to differentiate. Removed; `co_reserve` is now an unbounded
  "distance from safe" quantity. Because the collapse-risk z-function's
  `W_C * clip(2.0 - co_reserve, 0, None)` term depended on the clipped range,
  `COLLAPSE_ENDPOINTS['*']['intercept_kal']` in `hestia_model.py` was
  re-derived via `intercept_estimation.py` (now included in this snapshot;
  previously missing). Current values are a reduced-sample (N=200,
  single-core feasibility run) recalibration, marked PROVISIONAL -- rerun
  at production scale (N=10,000-50,000) before treating them as final.

- **[2026-07] Full English translation pass:** all Python source files,
  the demo/CLI output, and the shorter documentation files have been
  translated from Dutch to English (identifiers, comments, docstrings, and
  printed console text). `INTEGRATION_CHANGELOG.md`'s pre-2026-07 history is
  still largely in Dutch -- see the note at the top of that file.

- **Weather-to-load bridge:** `HEAT_LOAD_PER_DEGREE = 0.10`, calibrated
  against Fouillet 2003 (Paris). Reproduces the age-graded mortality timing.
  This calibrates the bridge, not the dynamics; not yet independently
  validated.
- **Three regimes** (checked 24/24 against simulation): dead-zone (safe,
  effective load < theta_rec) -> stable accumulation (narrow) -> runaway.
  The instability is a derived pole condition / gate collapse at
  Sigma=1/kappa, not a fitted threshold. The stable-accumulation regime is
  intrinsically narrow -> the model is close to binary, which explains the
  sharp group separation seen in real data.
- **Suppression term (1-kappa*Sigma):** a net-effect description (erosion
  of protective benefit), NOT a mechanistic claim that strain inhibits
  adaptation. Mild strain can in fact enhance adaptation (permissive
  dehydration). Domain of validity: sustained, non-compensable heat in
  vulnerable groups (Daanen 2018).
- **Location independence:** the dynamics (load->strain) are location-blind;
  location lives in the bridge upstream of it. Global comparability only
  holds if the same bridge is applied everywhere.
- **Integration:** real imports only, one shared data source. The
  PYROX->HESTIA model coupling is designed (COUPLING_DESIGN.md) but NOT
  implemented.
- **Nocturnal recovery (optional, OFF by default):** warm nights blunt
  recovery via q = night_sleep_quality(t_min). Affects the recovery term,
  not the bridge; calibration/validation remains intact. Enable via
  use_nocturnal_recovery=True.

## What can and cannot be claimed

- **Can:** PYROX is an early-warning instrument that gets groups, timing,
  and ordering right; it reproduces the cumulative, age-graded pattern of a
  historical heatwave; the control-theoretic structure is the contribution.
- **Cannot:** no absolute mortality prediction, no percentages-per-group
  (the strain->incidence calibration is deliberately deferred until
  multiple validation datasets exist). HESTIA's physiology (JOS-3) is not
  new -- the operationalization is.
- **Known limitations to disclose:** lacks mortality displacement/harvesting
  and recovery-after-decompensation; possibly too sensitive on the
  low-intensity side (Paris calibration); validation rests on a single event.

## File structure

Data chain: `Thermopoulos_Data_Engine.py` -> `Thermopoulos_*.xlsx` ->
`thermopoulos_loader.py` -> `run_pyrox.py`/`run_hestia.py` -> models -> plots.
Core: `pyrox_model.py`, `pyrox_groups.py`. Tests: `verify.py`,
`suite_smoke_test.py`. Plots: `pyrox_plots.py` (city menu + group menu).
Calibration tool: `intercept_estimation.py` (Newton-calibrates
`COLLAPSE_ENDPOINTS` against reference incidence data; run after any change
that shifts the T_rect/CO_reserve/dehydration distributions).
Documentation in `docs/`: TECHNICAL_REFERENCE, REFERENCES, COUPLING_DESIGN,
CONTRIBUTION_AND_POSITIONING. See MANIFEST.md for the full overview.

## Verified core references

Takahashi 2021 (JOS-3, doi:10.1016/j.enbuild.2020.110575); Tartarini & Schiavon
2020 (pythermalcomfort, doi:10.1016/j.softx.2020.100578); Vanos 2023
(survival limits, doi:10.1038/s41467-023-43121-5); Periard 2015
(acclimatization timescale, doi:10.1111/sms.12408); Daanen 2018
(acclimatization decay, doi:10.1007/s40279-017-0808-x); Fouillet 2006
(Paris 2003, doi:10.1007/s00420-006-0089-4); Moran 1998
(PSI, doi:10.1152/ajpregu.1998.275.1.R129); Lloyd et al. 2022 (cardiovascular
response model, doi:10.1152/japplphysiol.00619.2021); Breslow RG et al. 2021
(Boston Marathon EHS incidence, Am J Sports Med 49(10):2696-2703).
