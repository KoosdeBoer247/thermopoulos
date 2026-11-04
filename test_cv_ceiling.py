"""
test_cv_ceiling.py -- forced pace reduction at the cardiovascular ceiling
(CV_CEILING_FORCED, 2026-10-19).

Run:  python test_cv_ceiling.py      (~1 min)
"""
import os
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import hestia_model as H
from HESTIA_CVR_Module_v2 import CVRModel, JOS3Outputs

FAILS = []


def check(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILS.append(name)


print("\n1. met_at_ceiling() is the MET where CO_reserve = 0")
pop = H.generate_base_population(1, random_seed=7)
p = pop[0]
import inspect
src = inspect.getsource(H.calculate_indices_jos3_adult)
check("engine uses the forced ceiling switch", "CV_CEILING_FORCED" in src and "met_at_ceiling" in src)
check("switch on by default", H.CV_CEILING_FORCED is True)
from HESTIA_CVR_Module_v2 import RunnerProfile
# same construction as the engine (hestia_model.calculate_indices_jos3_adult)
runner = RunnerProfile(mass=p.weight, height=p.height * 100, age=p.age, sex=p.gender, vo2max=p.vo2max)
model = CVRModel(runner)
for t_core, t_skin, dehy in ((37.8, 33.0, 0.5), (39.0, 34.5, 2.0), (40.0, 35.5, 3.5)):
    snap = JOS3Outputs(t_min=0, cardiac_output=0.0, t_core_mean=t_core, t_cb=t_core,
                       weight_loss_g_s=dehy / 100 * runner.mass, bf_skin_total=0.0,
                       bf_ava_hand=0.5, bf_ava_foot=0.5,
                       current_met=1.0, t_skin_mean=t_skin)
    cap = model.met_at_ceiling(snap)
    snap.current_met = cap
    r0 = model.compute_step(snap).CO_reserve
    snap.current_met = cap * 0.97
    r_below = model.compute_step(snap).CO_reserve
    check(f"T_core {t_core}: reserve 0 at the cap ({cap:.2f} MET)", abs(r0) < 1e-3, f"{r0:+.4f} L/min")
    check(f"T_core {t_core}: positive reserve 3% below the cap", r_below > 0, f"{r_below:+.3f}")
caps = []
for t_core in (37.5, 38.5, 39.5, 40.5):
    snap = JOS3Outputs(t_min=0, cardiac_output=0.0, t_core_mean=t_core, t_cb=t_core,
                       weight_loss_g_s=0.0, bf_skin_total=0.0, bf_ava_hand=0.5, bf_ava_foot=0.5,
                       current_met=1.0, t_skin_mean=t_core - 4.0)
    caps.append(model.met_at_ceiling(snap))
snap = JOS3Outputs(t_min=0, cardiac_output=0.0, t_core_mean=39.0, t_cb=39.0,
                   weight_loss_g_s=0.12 * runner.mass, bf_skin_total=0.0, bf_ava_hand=0.5,
                   bf_ava_foot=0.5, current_met=2.0, t_skin_mean=35.0)
check("crossed regime (12 % dehydration, test runner CO_max 29 L/min): ceiling 0, reserve negative even at 2 MET",
      model.met_at_ceiling(snap) == 0.0 and model.compute_step(snap).CO_reserve < 0,
      f"reserve {model.compute_step(snap).CO_reserve:+.2f}")
check("ceiling falls with heat (monotonic)", all(a > b for a, b in zip(caps, caps[1:])),
      " > ".join(f"{c:.2f}" for c in caps))

print("\n2. Engine: Amsterdam runners pushed past the ceiling are forced down")
# Same population and weather as the Amsterdam comparison (N=1000, seed 42,
# sample_pace=True, 42.195 km, start 2026-10-18 09:00). Participants 731,
# 813 and 279 were the three with the largest forced reduction there.
import contextlib, io
import run_hestia
from thermopoulos_loader import ThermopoulosData
d = ThermopoulosData(os.path.join(os.path.dirname(os.path.abspath(__file__)), "testdata", "Thermopoulos_TestAMS.xlsx"))
with contextlib.redirect_stdout(io.StringIO()):
    pop = H.generate_base_population(n_simulations=1000, random_seed=42, met_value=9.8,
                                     sample_pace=True, event_dist_km=42.195)
# [2026-10-19, night] After the drinking fix these runners no longer reach
# the ceiling in mild Amsterdam weather. To test the MECHANISM they are made
# into runners who do: no drinking (thirst threshold 99 %), no voluntary
# pacing and full motivation (never quit on RPE).
sel = [pop[k].__class__(**{**pop[k].__dict__, "thirst_threshold": 99.0, "kp_pacing": 0.0,
                           "mf_score": 1.0}) for k in (731, 813, 279)]


def run(flag):
    H.CV_CEILING_FORCED = flag
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        out = run_hestia.monte_carlo_adult(d, "2026-10-18 09:00", 4.4, 9.8, 0.2, n_simulations=3,
                                           random_seed=42, sample_pace=True, event_dist_km=42.195,
                                           use_parallel=False, base_population=sel)
    return out[2]


df_on = run(True)
df_off = run(False)
H.CV_CEILING_FORCED = True
check("forced reduction happens in all three", (df_on["cv_plafond_stappen"] > 0).all(),
      ", ".join(f"{n} steps / max {m:.2f} MET" for n, m in zip(df_on["cv_plafond_stappen"], df_on["cv_plafond_max_met"])))
check("no forced reduction with the switch off", (df_off["cv_plafond_stappen"] == 0).all())
check("ceiling keeps the reserve higher than without it (crossed regime may still go below 0)",
      (df_on["cvr_co_reserve_min"] > df_off["cvr_co_reserve_min"] + 0.1).all(),
      ", ".join(f"{a:+.3f} vs {b:+.3f}" for a, b in zip(df_on["cvr_co_reserve_min"], df_off["cvr_co_reserve_min"])))
check("without the ceiling the reserve went clearly negative",
      (df_off["cvr_co_reserve_min"] < -H.CO_RESERVE_CEILING_TOL).any(),
      ", ".join(f"{v:+.3f}" for v in df_off["cvr_co_reserve_min"]))

print("\n3. 'At the ceiling' is applied consistently")
import individual_engine as IE
check("tolerance 0.05 L/min", H.CO_RESERVE_CEILING_TOL == 0.05)
check("EHE uses the same line", IE.EHE_CO_THRESHOLD == H.CO_RESERVE_CEILING_TOL)
check("legacy EAC threshold (post-finish CO_reserve) unchanged at 0", IE.EAC_CO_THRESHOLD == 0.0)
check("at_cv_ceiling(0.03) and not at_cv_ceiling(0.08)", H.at_cv_ceiling(0.03) and not H.at_cv_ceiling(0.08))
check("ceiling_depth: 0 above the line, tol - c below it",
      H.ceiling_depth(0.5) == 0.0 and abs(H.ceiling_depth(-0.1) - 0.15) < 1e-12)


print("\n4. Race follows the distance, RPE stop ends the race, after-glow on slowing")
df_new = run(True)        # all switches on (defaults)
check("forced runners need longer than planned",
      (df_new["race_actual_h"] > df_new["finish_time_h"]).all(),
      ", ".join(f"{a:.2f} h vs {b:.2f} h" for a, b in zip(df_new["race_actual_h"], df_new["finish_time_h"])))
# [2026-11-04] With dripping sweat and no drinking (thirst threshold 99) one
# runner is so slow that the weather window (6.5 h) ends just before the line.
_end = df_new["race_actual_h"] >= df_new["race_actual_h"].max() - 1e-9
check("they cover the full 42.195 km, or run until the weather window ends",
      ((abs(df_new["race_distance_km"] - 42.195) < 0.02) | (_end & (df_new["race_distance_km"] > 40.0))).all()
      and (abs(df_new["race_distance_km"] - 42.195) < 0.02).sum() >= 2,
      ", ".join(f"{x:.2f} km in {h:.2f} h" for x, h in zip(df_new["race_distance_km"], df_new["race_actual_h"])))
check("after-glow added when slowing", (df_new["nagloei_vertraging_totaal_c"] > 0).all(),
      ", ".join(f"{x:.3f} C" for x in df_new["nagloei_vertraging_totaal_c"]))
H.RACE_DISTANCE_MODE = False
H.SLOWDOWN_AFTERGLOW = False
df_old = run(True)
H.RACE_DISTANCE_MODE = True
H.SLOWDOWN_AFTERGLOW = True
check("switches off: race length = planned (within one 10-min step)",
      (abs(df_old["race_actual_h"] - df_old["finish_time_h"]) <= 10 / 60 + 1e-6).all())
check("switches off: no after-glow on slowing", (df_old["nagloei_vertraging_totaal_c"] == 0).all())

# RPE stop: smoke-test weather is hot enough to stop a runner at 95 % VO2max
# without pacing almost at once.
d_hot = ThermopoulosData(os.path.join(os.path.dirname(os.path.abspath(__file__)), "Thermopoulos_SmokeTest.xlsx"))
interp_hot = run_hestia.build_interpolated_weather(d_hot, "2026-08-04 11:00", 4.0)
base = H.generate_base_population(1, random_seed=11)[0]
hard = base.__class__(**{**base.__dict__, "pct_vo2max": 0.95, "kp_pacing": 0.0, "mf_score": 0.0})
with contextlib.redirect_stdout(io.StringIO()):
    res_stop = H.worker_monte_carlo_adult((interp_hot, d_hot.latitude, d_hot.longitude, 9.8, 0.2, hard, 0.0, 0.0))
    H.RPE_STOP_ENDS_RACE = False
    res_frozen = H.worker_monte_carlo_adult((interp_hot, d_hot.latitude, d_hot.longitude, 9.8, 0.2, hard, 0.0, 0.0))
    H.RPE_STOP_ENDS_RACE = True
check("RPE stop happens", any(r["stopped"] for r in res_stop))
check("race ends at the stop (no frozen rows)", len(res_stop) < len(res_frozen),
      f"{len(res_stop)} vs {len(res_frozen)} steps")
check("post-finish module follows the stopped runner",
      len(res_stop[-1].get("t_rect_series_postfinish") or []) > 0 and res_stop[-1].get("stop_min") is not None,
      f"stop at {res_stop[-1].get('stop_min')} min")


print("\n5. Foundation repair, drinking and RPE (2026-10-19, night)")
m0 = H.maak_jos3(height=1.75, weight=70, age=35, fat=15, sex="male")
check("par = MET x 58.2 / BMR", abs(H.jos3_par(m0, 10.0) - 10.0 * 58.2 / float(m0.bmr)) < 1e-9,
      f"10 MET -> par {H.jos3_par(m0, 10.0):.2f} (BMR {float(m0.bmr):.1f} W/m2)")
check("T_rect = pelvis core (segment 4)", H.jos3_t_rect(m0) == float(m0.t_core[4]))
check("start T_rect 36.9-37.6 degC (was ~36.5 with the 17-segment mean)",
      36.9 <= H.jos3_t_rect(m0) <= 37.6, f"{H.jos3_t_rect(m0):.2f}")
check("CHSI uses the same pelvis core", H.jos3_core_for_chsi(m0) == H.jos3_t_rect(m0))
H.JOS3_PAR_FROM_BMR = False
check("switch off: par = MET", H.jos3_par(m0, 10.0) == 10.0)
H.JOS3_PAR_FROM_BMR = True
normal = pop[0]
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    df_n = run_hestia.monte_carlo_adult(d, "2026-10-18 09:00", 4.4, 9.8, 0.2, n_simulations=1,
                                        random_seed=42, sample_pace=True, event_dist_km=42.195,
                                        use_parallel=False, base_population=[normal])[2]
_loss = float(df_n["max_water_loss_perc"].iloc[0])
check("drinking: net loss of an ordinary marathon runner 0.5-3.5 % (Zouhal 2011: mean 2.3 %)",
      0.5 <= _loss <= 3.5, f"{_loss:.2f} %")
r_rest = H.calculate_adult_rpe_from_hr(55, 55, 185, 0.0, 0.5)[0]
r_max = H.calculate_adult_rpe_from_hr(185, 55, 185, 0.0, 0.5)[0]
check("RPE from HR: 6 at rest, 20 at HR_max", abs(r_rest - 6) < 1e-9 and abs(r_max - 20) < 1e-9)
lo = H.calculate_adult_rpe_from_hr(170, 55, 185, 0.0, 0.1)[1]
hi = H.calculate_adult_rpe_from_hr(170, 55, 185, 0.0, 0.9)[1]
check("motivation lowers rpe_total (bug fixed)", hi < lo, f"mf 0.9: {hi:.2f} < mf 0.1: {lo:.2f}")
lo_l = H.calculate_adult_rpe_improved(10, 39.5, 0.0, 0.0, 0.1, 0.78, 35)[1]
hi_l = H.calculate_adult_rpe_improved(10, 39.5, 0.0, 0.0, 0.9, 0.78, 35)[1]
check("legacy RPE: motivation lowers rpe_total too", hi_l < lo_l)
check("stop limit 19.5 up to mf 0.5, 20.5 at mf 1",
      H.rpe_stop_threshold(0.2) == 19.5 and abs(H.rpe_stop_threshold(1.0) - 20.5) < 1e-9)


print("\n6. Heart lags the load (CV_LAG_ENABLED, 2026-10-20)")
check("tau 3 min by default (clinic 11 Oct)", H.CV_TAU_RISE_MIN == 3.0 and H.CV_TAU_FALL_MIN == 3.0)
_m = H.cv_met_lag(10.0, 1.5, 3.0)
check("after one tau, 63 % of a drop is done", abs((10.0 - _m) / 8.5 - (1 - np.exp(-1))) < 1e-9, f"{_m:.2f} MET")
check("10-min race step: start lag almost gone", H.cv_met_lag(1.5, 10.0, 10.0) > 9.6)
pf_kw = dict(t_rect_finish=39.5, co_reserve_finish=1.0, auc_klinisch_race=0.0, wbgt_finish=15.0,
             co_max_finish=20.0, cvr_model=model, t_skin_finish=35.0, dehydration_kg_finish=1.0)
pf_lag = H.simulate_post_finish(met_cv_finish=10.0, **pf_kw)
H.CV_LAG_ENABLED = False
pf_inst = H.simulate_post_finish(met_cv_finish=10.0, **pf_kw)
H.CV_LAG_ENABLED = True
c_lag, c_inst = pf_lag["co_reserve_series_postfinish"][2], pf_inst["co_reserve_series_postfinish"][2]
check("post-finish: reserve recovers more slowly with the lag (1 min after the finish)",
      c_lag < c_inst - 1.0, f"{c_lag:+.2f} vs {c_inst:+.2f} L/min")


print("\n7. Collapse risk counts the finish zone (COLLAPSE_INCLUDES_POSTFINISH, 2026-10-20)")
_res = [{"t_rect": 39.0, "co_reserve": float("nan")}, {"t_rect": 40.0, "co_reserve": 1.0},
        {"t_rect": 40.2, "co_reserve": 0.8, "t_rect_series_postfinish": [40.2, 40.6, 40.4],
         "co_reserve_series_postfinish": [0.8, -0.3, 2.0]}]
check("extremes over race + finish zone", H.collapse_extremes(_res) == (40.6, -0.3), str(H.collapse_extremes(_res)))
H.COLLAPSE_INCLUDES_POSTFINISH = False
check("switch off: race only", H.collapse_extremes(_res) == (40.2, 0.8), str(H.collapse_extremes(_res)))
H.COLLAPSE_INCLUDES_POSTFINISH = True
import intercept_estimation as _IE, inspect as _insp
check("calibration uses the same extremes", "collapse_extremes" in _insp.getsource(_IE.run_calibration_simulation))


print("\n8. EAC-staan (collapse on standing, 2026-10-20)")
check("tolerance normal = 1", abs(H.eac_tolerance(34.3, 36.8, 0.0) - 1.0) < 1e-12)
_ts = H.eac_tolerance(37.6, 37.1, 0.0); _tc = H.eac_tolerance(35.0, 38.3, 0.0); _tb = H.eac_tolerance(38.8, 38.1, 0.0)
check("Pearson 2017 conditions: skin ~0.56, core ~0.56, both ~0.25",
      0.4 < _ts < 0.65 and 0.45 < _tc < 0.65 and 0.2 < _tb < 0.32, f"{_ts:.2f} / {_tc:.2f} / {_tb:.2f}")
_td = H.eac_tolerance(34.3, 36.8, 1.9)
check("Schlader 2015: 1.9 % dehydration ~0.69", abs(_td - 0.69) < 0.03, f"{_td:.2f}")
check("probability rises with standing load",
      H.eac_probability(5) < H.eac_probability(20) < H.eac_probability(100))
check("no standing, no EAC", H.eac_probability(0.0) == 0.0)
# [2026-10-20 late] core counts up to 38.3 degC only; heat-independent base share
check("core term capped at 38.3 degC (Pearson's tested range)",
      abs(H.eac_tolerance(35.0, 40.5, 0.0) - H.eac_tolerance(35.0, 38.3, 0.0)) < 1e-12
      and H.eac_tolerance(35.0, 38.0, 0.0) > H.eac_tolerance(35.0, 38.3, 0.0))
check("base share: a standing runner never falls below EAC_BASE_P",
      abs(H.eac_probability(1e-3) - H.EAC_BASE_P) < 1e-6 and H.EAC_BASE_P == 0.0010)
check("WBGT limit for an EAC number is 28 degC (ACSM black flag)", H.EAC_WBGT_VALID_MAX == 28.0)
check("3 % standing deficit on CO_reserve removed", not hasattr(H, "PF_STAND_POOLING_FRAC"))
check("finish zone: 5 min walking, 5 min standing", H.PF_WALK_MIN == 5.0 and H.PF_STAND_MIN == 5.0)
_r0 = df_new if "eac_staanbelasting" in df_new else None
check("engine exports the standing load and probability", _r0 is not None and (df_new["eac_staanbelasting"] > 0).all(),
      ", ".join(f"R {r:.1f} min, P {p:.4f}" for r, p in zip(df_new["eac_staanbelasting"], df_new["eac_kans"])) if _r0 is not None else "")

print()
if FAILS:
    print(f"FAILED: {FAILS}")
    raise SystemExit(1)
print("ALL CHECKS PASSED")
