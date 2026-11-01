# Data sources and licences

## Weather data (runtime)

The Thermopoulos Data Engine (`Thermopoulos_Data_Engine.py`), Klimatos
(`Klimatos_ClimateShift.py`) and the HESTIA forecast path fetch weather from
the Open-Meteo APIs (forecast, historical/archive, geocoding, air quality).

- **Weather data by [Open-Meteo.com](https://open-meteo.com)**, offered under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Anyone who shows
  or redistributes data or reports produced with this suite must give the same
  credit with a link to open-meteo.com and the licence, and indicate that the
  data were processed (this suite derives urban temperature, globe temperature,
  MRT, wet-bulb temperature, WBGT and UTCI from them).
- The archive data are the Copernicus **ERA5 / ERA5-Land reanalysis**:
  *contains modified Copernicus Climate Change Service information*. Forecast
  data come from national weather services (for example KNMI, DWD) via
  Open-Meteo; see Open-Meteo's licence page for the source list and terms.
- **Free API: non-commercial use only.** Open-Meteo's terms state: "You may
  only use the free API services for non-commercial purposes" (limits: fewer
  than 10,000 calls per day, 5,000 per hour, 600 per minute). Commercial users,
  for example organisers running a paid service, need a paid Open-Meteo plan.
  See <https://open-meteo.com/en/terms> and <https://open-meteo.com/en/licence>.

## Bundled data files

| File | Content | Origin / licence |
|---|---|---|
| `DtD2024_Amsterdam_hindcast.xlsx` | Hourly weather Amsterdam, 22–23 Sept 2024 (Data Engine hindcast), reference weather of the Dam tot Damloop calibration | Open-Meteo (ERA5), CC BY 4.0, processed by the Data Engine |
| `Thermopoulos_SmokeTest.xlsx`, `testdata/Thermopoulos_TestAMS.xlsx` | Synthetic weather for tests | generated, no external data |
| `paris2003.py` (embedded series) | Paris August 2003: reconstructed daily maximum temperature, Météo-France station values for night minima, national excess mortality | Fouillet et al. (2006) and the sources cited in the file; used only for the PYROX shape check |
| `intercept_controle_2026-10-24.json` | Raw results of the current endpoint calibration | produced by `intercept_estimation.py` |
| `criteria.json` | Pre-registered acceptance limits of the Thermo Clinic validation | author |
| `loper_invoer_voorbeeld.json` | Example input of the personal runner analysis (fictitious runner) | author |

## Calibration targets (published or provided)

| Endpoint | Target | Source |
|---|---|---|
| EHS (`ehs`) | 4.5 per 10,000 starters | Breslow RG et al. (2021) Med Sci Sports Exerc 53(9):1818–1825 (3.7 per 10,000 pooled 2015–2019; 4.5 is the author's choice for a warm edition) |
| Hospital admission (`hospitalisation`) | 50 per 35,000 | Dam tot Damloop 2024: data provided by GHOR Noord-Holland Noord and Le Champion |
| First-aid contact (`first_aid`) | 150 per 35,000 | Dam tot Damloop 2024: data provided by GHOR Noord-Holland Noord and Le Champion (estimate) |
| Collapse on standing after the finish (EAC) | 1.5 per 1000 | Naidoo D et al. (2022) J Sports Med Phys Fitness 62(11):1519–1525 |

## Third-party code

| File | Origin | Licence |
|---|---|---|
| `HEATLim.py` | ASU/USYD HEAT-Lim by Gisel Guzman-Echavarria, Jennifer Vanos et al., Zenodo doi:10.5281/zenodo.15642387 (v2); scientific basis Vanos et al. (2023) Nature Communications 14, doi:10.1038/s41467-023-43121-5 | **CC BY 4.0** (not MIT); attribution and changes in `THIRD_PARTY_LICENSES.md` |

Runtime dependencies (pythermalcomfort MIT, pvlib BSD-3, numpy/pandas/scipy
BSD, matplotlib PSF-based, docx for Node MIT) are installed separately and not
redistributed.

## Field data

Thermo Clinic recordings (Garmin watch, CORE sensor, weighing) are **not**
included. They stay with the clinic and the author. The documentation reports
group-level results only.
