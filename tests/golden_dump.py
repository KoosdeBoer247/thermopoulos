"""Golden-output dump: run fixed, seeded computations against a suite folder
and write every numeric result to JSON, so a refactored copy can be compared
for exact equality.  Usage: python golden.py SUITE_DIR OUT.json"""
import sys, os, json, io, contextlib, warnings, hashlib
warnings.filterwarnings('ignore')
S, OUT = sys.argv[1], sys.argv[2]
sys.path.insert(0, S); os.chdir(S)
import numpy as np, pandas as pd
R = {}
def num(x):
    if isinstance(x, (np.floating, float)): return None if not np.isfinite(x) else float(f'{float(x):.12g}')
    if isinstance(x, (np.integer, int, bool, np.bool_)): return int(x) if not isinstance(x, (bool, np.bool_)) else bool(x)
    if isinstance(x, (list, tuple, np.ndarray, pd.Series)): return [num(v) for v in list(x)]
    if isinstance(x, dict): return {str(k): num(v) for k, v in x.items()}
    if isinstance(x, pd.DataFrame): return {c: num(x[c].to_numpy()) for c in x.columns if pd.api.types.is_numeric_dtype(x[c])}
    return None
def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return f(*a, **k)
# 1. weather pipelines on a synthetic raw frame
idx = pd.date_range('2024-07-20 00:00', periods=72, freq='h', tz='Europe/Amsterdam')
h = np.arange(72) % 24
raw = pd.DataFrame({'T_air_rural': 18 + 9 * np.sin(np.pi * (h - 6) / 14).clip(-0.4, None), 'RH': 70 - 25 * np.sin(np.pi * (h - 6) / 14).clip(0, None),
                    'pressure': 1013.0, 'wind_10m': 2 + (h % 5) * 0.7, 'solar_radiation': (750 * np.sin(np.pi * (h - 6) / 14)).clip(0, None), 'cloud_cover': (h * 7) % 100}, index=idx)
city = {'name': 'Amsterdam', 'population': 900000, 'country': 'NL'}
import Thermopoulos_Data_Engine as DE, Klimatos_ClimateShift as K
R['de_process'] = num(quiet(DE.process_weather_data, raw.copy(), city, 52.37, 4.89, 'Europe/Amsterdam', False, 1.2))
R['de_process_coastal'] = num(quiet(DE.process_weather_data, raw.copy(), city, 52.37, 4.89, 'Europe/Amsterdam', True, 0.5))
R['kl_process_uhi'] = num(quiet(K.process_weather_data, raw.copy(), city, 52.37, 4.89, 'Europe/Amsterdam', True))
R['kl_process_nouhi'] = num(quiet(K.process_weather_data, raw.copy(), city, 52.37, 4.89, 'Europe/Amsterdam', False))
rng = np.random.default_rng(3); g = []
for _ in range(300):
    T = rng.uniform(-5, 42); gh = rng.uniform(0, 1000); w = rng.uniform(0, 10); e = rng.uniform(-5, 65); c = rng.uniform(0, 100)
    tg = DE._calculate_globe_scalar(T, gh, w, e, 1010, c, 2); g += [tg, DE._calculate_mrt_scalar(tg, T, w, gh, e), K._calculate_globe_scalar(T, gh, w, e, 1010, c, 2)]
R['radiant'] = num(g)
R['heatlim'] = num([K.compute_mmax_met([30, 35, 40, 44], [40, 60, 20, 50], [1.0] * 4, [35, 40, 45, 50], K.LIVEABILITY_PROFILES[p]) for p in K.LIVEABILITY_PROFILES])
# 2. HESTIA engine (event path)
import hestia_model as H, run_hestia
from thermopoulos_loader import ThermopoulosData
d = ThermopoulosData('DtD2024_Amsterdam_hindcast.xlsx')
pop = quiet(H.generate_base_population, n_simulations=16, random_seed=42, met_value=9.8, sample_pace=True, event_dist_km=16.1, training_factor=0.5, acclimatization_factor=0.6)
allr, st, df = quiet(run_hestia.monte_carlo_adult, d, '2024-09-22 11:30', 1.63, 9.8, 0.2, n_simulations=16, training_factor=0.5, acclimatization_factor=0.6,
                     sheet='Historical_Custom', random_seed=42, sample_pace=True, event_dist_km=16.1, use_parallel=False, base_population=pop)
R['engine_stats'] = num({k: v for k, v in st.items() if isinstance(v, (int, float, np.floating, np.integer))})
R['engine_df'] = num(df)
R['engine_trace0'] = num([{k: v for k, v in r.items() if isinstance(v, (int, float, np.floating))} for r in allr[0]])
# 3. runner module
import hestia_loper as hl
inv = hl.LoperInvoer(lengte_cm=180, gewicht_kg=75, leeftijd=60, geslacht='man', evenement='t', datum='2024-09-22', starttijd='12:00', plaats='Amsterdam', afstand_km=16.1,
                     tempo_min_per_km='5:45', drinkt_bij_elke_post=True, hitte_geacclimatiseerd=False, kleding='licht', vo2max_bekend=42.0, hr_rust_bekend=55,
                     weerbron='excel', weer_excel='DtD2024_Amsterdam_hindcast.xlsx')
lr = quiet(hl.analyseer_loper, inv, n_ensemble=8, seed=42, gevoeligheid=False)
R['loper_per_run'] = num(lr.per_run)
R['loper_band_t'] = num(lr.banden['t_rect']); R['loper_band_co'] = num(lr.banden['co'])
# 4. clinic reconstruction (synthetic one-hour run, Data Engine-like weather)
import hestia_reconstructie as hr_
w = pd.DataFrame({'T_air_urban': 14.0, 'RH': 75.0, 'MRT': 25.0, 'wind_10m': 3.0, 'T_air_rural': 13.5}, index=pd.date_range('2026-10-17 09:00', periods=6, freq='h'))
p = hr_.Persoon(geslacht='m', leeftijd=60, lengte_cm=178, gewicht_kg=76, clo=hr_.KLEDING_CLO['normaal'], hitte_gewend=True, drank_ml=0.0, hr_max=170, hr_rust=50)
mn = pd.DataFrame({'snelheid_ms': [0.0] * 20 + [2.9] * 45 + [0.0] * 30, 'met': [1.3] * 20 + [10.0] * 45 + [1.3] * 30})
rc = quiet(hr_.reconstrueer_varianten, p, mn, w, pd.Timestamp('2026-10-17 10:00'), ['B1', 'B3'], {'populatie': 40.0, 'hestia': 45.0}, n_ensemble=4, seed=42)
R['clinic'] = {v: {'centraal': num(rc[v].centraal), 'band': num(rc[v].band), 'hr': {k: num(x) for k, x in rc[v].hr.items()}} for v in rc}
# 5. calibration reference weather
import intercept_estimation as IE
for key in ('dtd', 'boston'):
    cfg = dict(IE.REF_CONDITIONS_BY_KEY[key]); cfg['duration_h'] = max(cfg['duration_h'], H.race_window_hours(cfg.get('event_dist_km', 16.1)))
    R['ref_' + key] = num([{k: v for k, v in e.items() if k != 'time'} for e in quiet(IE.build_reference_interp, cfg)])
# 6. PYROX
import run_pyrox
td = ThermopoulosData('Thermopoulos_SmokeTest.xlsx')
rep = quiet(run_pyrox.assess_population, td, sheet='Forecast_7d')
R['pyrox'] = num({g: {k: v for k, v in r.items() if isinstance(v, (list, np.ndarray, float, int))} for g, r in rep['groups'].items()})
json.dump(R, open(OUT, 'w'), sort_keys=True)
print('golden written', OUT, hashlib.md5(json.dumps(R, sort_keys=True).encode()).hexdigest())
