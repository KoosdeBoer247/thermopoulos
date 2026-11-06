# Manifest — release 2026.10.27

Every file in the release and what it does. History of individual files:
`CHANGELOG.md`. Architecture: `TECHNICAL_REFERENCE.md` §2.

## Documentation and metadata

| File | Contents |
|---|---|
| `README.md` | overview, validation status, known issues, installation, quick start |
| `TECHNICAL_REFERENCE.md` | architecture, equations, calibration, validation chapter (§8a), glossary |
| `CHANGELOG.md` | changes, reasons and findings, newest first |
| `MANIFEST.md` | this file |
| `CORE_SENSOR.md` | the CORE sensor as field reference: literature on its error, Emmen analysis, recommendations for the clinics |
| `DATA_SOURCES.md` | weather data, bundled data files, calibration targets, third-party code, licences |
| `THIRD_PARTY_LICENSES.md` | licence and attribution of included third-party code (HEAT-Lim, CC BY 4.0) |
| `CITATION.cff` | citation metadata |
| `LICENSE` | MIT licence of the suite's own code (third-party parts: `THIRD_PARTY_LICENSES.md`) |
| `CHECKSUMS.txt` | SHA-256 of every released file (`sha256sum -c CHECKSUMS.txt`) |
| `requirements.txt` | exact, tested dependency versions (lock file) |
| `pyproject.toml` | project metadata, compatible dependency ranges, pytest settings |
| `package.json`, `package-lock.json` | Node.js dependency (`docx`) for the Word export; install with `npm install` |
| `.gitignore` | keeps outputs, caches and field data out of version control |
| `.github/workflows/tests.yml` | GitHub Actions: fast tests + golden check, then the slow tests |
| `branding/` | logos of the suite and its components (author's own) |
| `diagrams/` | PYROX block diagrams (causal loop and control-engineering notation) |

## Weather

| File | Purpose |
|---|---|
| `Thermopoulos_Data_Engine.py` | fetches forecast/archive weather (Open-Meteo), computes UHI, solar position, globe temperature, MRT, wet-bulb, WBGT, UTCI; writes `Thermopoulos_DataEngine_*.xlsx` |
| `thermal_env.py` | shared physics and location helpers for the Data Engine and Klimatos (wind profile, Oke UHI, ISO 7726 globe/MRT, solar position, geocoding, location choice) |
| `thermopoulos_loader.py` | reads the Data Engine Excel format for PYROX and HESTIA |

## HESTIA (individual thermophysiology and event risk)

| File | Purpose |
|---|---|
| `hestia_model.py` | engine core: JOS-3 set-up (`maak_jos3`), population generation, Monte Carlo, pacing, post-finish phase, collapse endpoints and their calibrated intercepts, radiation handling (`radiation_series`) |
| `hestia_console.py` | the engine's own interactive console (menus, prompts) |
| `hestia_model_plots.py` | figures of that console |
| `jos3_leeftijd.py` | gradual, fitness- and heat-scaled JOS-3 age effect; replaces three JOS-3 functions in memory; requires pythermalcomfort 4.6.2 |
| `HESTIA_CVR_Module_v2.py` | cardiovascular response (Lloyd et al. 2022): heart rate, CO_reserve |
| `HESTIA_CVR_Console.py` | stand-alone demo of the CVR module |
| `HESTIA_ControlFailure_Module.py` | thermoregulatory control-failure (TCF) dose |
| `run_hestia.py` | event Monte Carlo on a Data Engine file, with report |
| `hestia_plots.py` | population figures for the reports |
| `participant_dose_analysis.py` | per-participant dose build-up over time (optional after a run) |
| `uncertainty.py` | uncertainty band of the headline EHS estimate |
| `individual_engine.py` | one-person wrapper of the same physiology (scenarios, EHS/EHE/EAC criteria) |
| `local_storage.py` | local-only persistence for the personal app |
| `hestia_bridge.py` | adapter for Klimatos and the app (weather to engine input, summaries) |
| `intercept_estimation.py` | calibration of the collapse-risk intercepts per endpoint (Boston, Dam tot Damloop 2024 with real weather) |
| `intercept_controle_2026-11-04.json` | raw results of the current calibration |
| `intercept_controle_2026-11-01.json` | raw results of the previous calibration (before the HUTAS wettedness change) |
| `intercept_controle_2026-10-31.json` | raw results of the calibration of 31 October |
| `intercept_controle_2026-10-24.json` | raw results of the previous calibration |
| `DtD2024_Amsterdam_hindcast.xlsx` | real hourly weather of 22–23 Sept 2024 (Amsterdam), reference of the Dam tot Damloop calibration |

## Personal runner analysis

| File | Purpose |
|---|---|
| `hestia_loper.py` | analysis for one runner (input, fitness, weather, ensemble, risk measures, signal) |
| `hestia_loper_plots.py` | figures of the personal report |
| `hestia_loper_rapport.py` | personal Word report (Dutch) |
| `run_loper.py` | command line / menu for the runner analysis |
| `loper_invoer_voorbeeld.json` | example input (fictitious runner) |

## Field validation (Thermo Clinic)

| File | Purpose |
|---|---|
| `fit_lezer.py` | reads Garmin/CORE FIT files, keeps an allow-list of fields, anonymises file names |
| `clinic_invoer.py` | reads the clinic participant file |
| `inspanning_uit_fit.py` | turns a FIT export into model input and measurement |
| `hestia_reconstructie.py` | mode B: reconstruction with the measured effort (variants B1/B2/B3) |
| `dynamiek.py` | system identification (gain, dead time, time constants) for model and sensor |
| `aanmelding.py` | sign-up list + FIT files with e-mail addresses in their names -> codelist `deelnemers.xlsx`, `fit_uitvoer/` and a private `PRIVE_koppeltabel.xlsx`; codes per Garmin set (G001) |
| `groep_lopers.py` | a list of known runners (Deelnemers sheet) through a chosen run: own body, pace and fitness (from a test, an earlier FIT run, or estimated); overview Excel/Word, optional per-runner reports |
| `fit_loop.py` | one run from a FIT file recomputed with HESTIA (measured pace, Data Engine weather; variants B3 and B4), with Excel, figure and Word report |
| `clinic_validatie.py` | the validation chain: frozen prediction (mode A), comparison (mode B) |
| `clinic_rapport.py` | Excel, figures and Word report of the validation |
| `criteria.json` | pre-registered measures and acceptance limits |

## PYROX (population groups)

| File | Purpose |
|---|---|
| `pyrox_model.py` | the dynamic heat-strain model (reference implementation) |
| `pyrox_groups.py` | parameters of the 23 population groups |
| `run_pyrox.py` | PYROX on a Data Engine file |
| `pyrox_plots.py` | diagnostic and publication figures |
| `paris2003.py` | Paris August 2003 reference series (shape validation) |
| `verify.py` | reproduces the paper's results |

## Klimatos (climate trends)

| File | Purpose |
|---|---|
| `Klimatos_ClimateShift.py` | climate-shift engine: ERA5 series, windows, trends, event windows, EHS evolution, liveability |
| `klimatos_ehs_worker.py` | picklable worker for the EHS-evolution module |
| `HEATLim.py` | ASU/USYD HEAT-Lim survivability/liveability functions (third-party, CC BY 4.0, see `THIRD_PARTY_LICENSES.md`) |

## Reports

| File | Purpose |
|---|---|
| `generate_event_report.py` | factual HESTIA event report (Dutch) |
| `generate_klimatos_report.py` | Klimatos event report |
| `generate_recommendation_report.py` | timing-advice report (proof of concept) |
| `generate_pyrox_report.py` | PYROX population report |
| `report_to_docx.py`, `build_report_docx.js` | Word export of the reports (Node.js, `npm install`) |

## Menu and tests

| File | Purpose |
|---|---|
| `start_thermopoulos.py` | main menu for the whole suite (Dutch): HESTIA, PYROX, Klimatos, FIT files, weather, reports |
| `rapportpakket.py` | keeps the report data of every calculation (`*_rapportpakket.pkl`) and makes the report later (menu choice R) |
| `test_aanmelding.py` | sign-up list conversion with invented names/addresses: column recognition, linking, codes, no personal data in outputs, tempo override |
| `test_klimatos_bron.py` | Klimatos requests one fixed reanalysis source (models=era5_seamless, cell_selection=land) for every year; no network |
| `klimatos_bronnen_test.py` | diagnostic (needs internet): compares the archive default with ERA5, ERA5-Land and ERA5-Seamless per year for seven locations, 2007–2025 |
| `test_hutas_zweet.py` | maximum skin wettedness and dripping sweat as in HUTAS: w_max per acclimatisation, whole-body cap, sweating efficiency, effect in cool, dry and humid heat |
| `test_wandelaars.py` | walkers' population (Four Days Marches type): runners unchanged, sex, age, BMI and VO2max as in the sources |
| `test_hittegewenning.py` | heat acclimation: JOS-3 sweat gain (dry and humid heat), plasma volume in the CVR module, sweat factor independent of acclimation |
| `test_globe_liljegren.py` | globe temperature against the Liljegren et al. (2008) C reference, recomputing older weather files, urban humidity |
| `test_herladen.py` | the suite keeps working when modules are reloaded between runs (Spyder) |
| `test_groep_lopers.py` | group what-if run on synthetic weather, overview and per-runner reports |
| `test_fit_loop.py` | FIT-loop analysis, report packages and a scripted walk through the main menu |
| `run_all_tests.py` | runs every test script with a summary |
| `tests/test_scripts.py` | the same scripts under pytest (slow ones marked `slow`) |
| `tests/test_golden.py`, `tests/golden_dump.py`, `tests/golden_reference.json` | golden-output regression test against the 2026-11-04 calibration version |
| `suite_smoke_test.py` | end-to-end smoke test |
| `test_koude_huid.py` | cold-skin limit of JOS-3 (off by default, effect in cold, none in heat, clinic variant B4) |
| `test_leefbaarheid_uren.py` | Klimatos liveability: rest floor of the worst-hour Mmax, hours-per-year trend and projection, report section |
| `test_*.py` | regression and feature tests per module (see each file's docstring) |
| `Thermopoulos_SmokeTest.xlsx`, `testdata/` | synthetic weather for the tests |
