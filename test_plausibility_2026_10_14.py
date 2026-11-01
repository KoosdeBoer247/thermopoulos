"""
test_plausibility_2026_10_14.py -- regression tests for the 2026-10-14 fixes
(review of the Amsterdam 2026-10-18 marathon run, n=5000, seed 42).

Run:  python test_plausibility_2026_10_14.py
Fast (no JOS-3 Monte Carlo); takes ~30 s for population sampling.

Covers:
  1. sustainable_vo2max_fraction(): Daniels & Gilbert (1979) values.
  2. generate_base_population(sample_pace=True): no participant above the
     duration-dependent ceiling; demographics kept at their targets.
  3. simulate_post_finish(): total metabolic after-glow equals
     PF_DELTA_T_NAGLOED (was 2x too large -- units error).
  4. Excel export / report: new columns and report sections present.
"""
import os
import tempfile
import atexit
import shutil
_TMP = tempfile.mkdtemp(prefix="hestia_plaus_")
atexit.register(shutil.rmtree, _TMP, True)
_REPORT_PATH = os.path.join(_TMP, "_test_report.md")
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import hestia_model as H

FAILS = []


def check(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILS.append(name)


print("\n1. Daniels-Gilbert sustainable fraction")
f90, f180, f240, f300 = (H.sustainable_vo2max_fraction(t) for t in (90, 180, 240, 300))
check("~0.86 at 90 min", abs(f90 - 0.859) < 0.01, f"{f90:.3f}")
check("~0.82 at 3 h", abs(f180 - 0.819) < 0.01, f"{f180:.3f}")
check("~0.81 at 4 h", abs(f240 - 0.809) < 0.01, f"{f240:.3f}")
check("monotone decreasing", f90 > f180 > f240 > f300)
check("capped at 0.95 for short efforts", H.sustainable_vo2max_fraction(5) == 0.95)

print("\n2. Population sampling, marathon, sample_pace=True (n=3000, seed 42)")
pop = H.generate_base_population(3000, random_seed=42, sample_pace=True, event_dist_km=42.195)
pct = np.array([p.pct_vo2max for p in pop])
dur = np.array([p.duration_hours for p in pop])
ceil = np.array([H.sustainable_vo2max_fraction(d * 60) for d in dur])
male = np.mean([p.gender == "male" for p in pop])
age_med = np.median([p.age for p in pop])
check("nobody above own duration ceiling", np.all(pct <= ceil + 1e-9),
      f"max excess {np.max(pct - ceil):+.4f}")
check("median %VO2max in recreational range 0.68-0.78", 0.68 <= np.median(pct) <= 0.78,
      f"{np.median(pct):.3f}")
check("no pile-up at the ceiling (<5% within 0.005)", np.mean(ceil - pct < 0.005) < 0.05,
      f"{np.mean(ceil - pct < 0.005)*100:.1f}%")
check("male share kept near 58% target", abs(male - 0.58) < 0.03, f"{male*100:.1f}%")
check("median age kept near 40 target (>=38)", age_med >= 38, f"{age_med:.0f}")

print("\n   Pace follows absolute fitness (2026-10-16)")
ages = np.array([p.age for p in pop]); fin = np.array([p.duration_hours for p in pop])
check("older runners slower: corr(age, finish time) > 0.15", np.corrcoef(ages, fin)[0, 1] > 0.15,
      f"{np.corrcoef(ages, fin)[0, 1]:+.2f}")
check("60-65 y median finish later than 18-40 y", np.median(fin[ages >= 60]) > np.median(fin[ages < 40]) + 0.3,
      f"{np.median(fin[ages >= 60]):.2f} vs {np.median(fin[ages < 40]):.2f} h")

print("\n   Same with the ceiling switched off (previous behaviour)")
H.USE_DURATION_INTENSITY_CEILING = False
pop_old = H.generate_base_population(3000, random_seed=42, sample_pace=True, event_dist_km=42.195)
H.USE_DURATION_INTENSITY_CEILING = True
pct_old = np.array([p.pct_vo2max for p in pop_old])
check("old behaviour reproducible (>=25% at >=85% VO2max)", np.mean(pct_old >= 0.85) > 0.25,
      f"{np.mean(pct_old >= 0.85)*100:.1f}%")

print("\n   Fixed-marathon-pace path (Boston ehs calibration population)")
popb = H.generate_base_population(2000, training_factor=0.30, acclimatization_factor=0.35, random_seed=42)
pctb = np.array([p.pct_vo2max for p in popb])
check("calibration population below 4-h ceiling (max <= 0.82)", pctb.max() <= 0.82, f"max {pctb.max():.3f}")

print("\n   Integral pacing term on by default")
check("K_I_PACING_CV == 0.02", H.K_I_PACING_CV == 0.02)

print("\n   NSAID flag has no thermal effect (2026-10-16)")
check("K_P_NSAID_FACTOR == 1.0", H.K_P_NSAID_FACTOR == 1.0)
_ns = np.array([p.nsaid_gebruik for p in pop])
check("NSAID prevalence ~25% kept as export flag", abs(_ns.mean() - 0.25) < 0.03, f"{_ns.mean()*100:.1f}%")

print("\n   Worker reproducible regardless of global RNG state (2026-10-15)")
import run_hestia
from thermopoulos_loader import ThermopoulosData
_d = ThermopoulosData("Thermopoulos_SmokeTest.xlsx")
_it = run_hestia.build_interpolated_weather(_d, "2026-08-01 10:00", 1.5)
_p = pop_old[0]
_args = (_it, _d.latitude, _d.longitude, 9.8, 0.2, _p, 0.0, 0.0)
np.random.seed(1); _r1 = H.worker_monte_carlo_adult(_args)
np.random.seed(999); _r2 = H.worker_monte_carlo_adult(_args)
check("identical water loss for two different RNG states",
      _r1[-1]["water"] == _r2[-1]["water"], f"{_r1[-1]['water']:.1f} / {_r2[-1]['water']:.1f} g")

print("\n   Intercepts after recalibration (2026-11-01)")
check("ehs intercept -9.130380", abs(H.COLLAPSE_ENDPOINTS["ehs"]["intercept_kal"] - (-9.130380)) < 1e-6)
check("ehs target 4.5/10,000 (2026-10-17)", H.COLLAPSE_ENDPOINTS["ehs"]["p_obs"] == 4.5 / 10_000)
check("ehs source is Breslow 2021 MSSE, not the non-existent AJSM reference",
      "1818-1825" in H.COLLAPSE_ENDPOINTS["ehs"]["source"] and "2696" not in H.COLLAPSE_ENDPOINTS["ehs"]["source"])
check("hospitalisation intercept -8.490417", abs(H.COLLAPSE_ENDPOINTS["hospitalisation"]["intercept_kal"] - (-8.490417)) < 1e-6)

print("\n3. Post-finish after-glow")
# WBGT 35 -> passive cooling term is exactly 0, so the rise is the after-glow alone.
pf = H.simulate_post_finish(t_rect_finish=39.0, co_reserve_finish=5.0,
                            auc_klinisch_race=0.0, wbgt_finish=35.0)
rise = pf["t_rect_piek_postfinish"] - 39.0
expected = H.PF_DELTA_T_NAGLOED * (1 - np.exp(-H.PF_DUUR_MIN / H.PF_TAU_NAGLOED))
check("total after-glow == PF_DELTA_T_NAGLOED (was ~0.9)", abs(rise - expected) < 0.01,
      f"rise {rise:.3f} vs {expected:.3f} degC")
pf_cool = H.simulate_post_finish(t_rect_finish=39.0, co_reserve_finish=5.0,
                                 auc_klinisch_race=0.0, wbgt_finish=10.0)
check("cool finish area: peak rise < 0.3 degC", pf_cool["t_rect_piek_postfinish"] - 39.0 < 0.3,
      f"{pf_cool['t_rect_piek_postfinish'] - 39.0:.3f}")

print("\n4. Report generator (synthetic inputs)")
import pandas as pd
import generate_event_report as R
rng = np.random.default_rng(1)
n = 200
df = pd.DataFrame({
    "participant_id": np.arange(1, n + 1), "gender": rng.choice(["male", "female"], n),
    "pct_vo2max": rng.uniform(.6, .8, n), "implied_met_initial": rng.uniform(8, 12, n),
    "finish_time_h": rng.uniform(3, 5.2, n), "max_t_rect": rng.normal(39.2, .4, n),
    "max_t_rect_incl_postfinish": rng.normal(39.3, .4, n), "max_rpe": rng.uniform(13, 19, n),
    "pacing_reductie_pct": rng.uniform(0, 5, n),
    "vulnerable_tail_top_2_5pct": (np.arange(n) < 5).astype(int),
})


class _D:
    def metadata(self):
        return {"city": "Test", "latitude": 52.0, "longitude": 4.9}


stats = {"percent_first_aid": np.r_[np.linspace(0, 60, 20), [np.nan] * 3],
         "percent_stopped": np.zeros(23), "vulnerable_tail_mean_t_rect": np.r_[np.ones(20) * 40, [np.nan] * 3],
         "vulnerable_tail_n": 5}
txt = R.generate_report("Test", _D(), stats, df, "2026-10-18 09:00", 4.4, "test", n,
                        _REPORT_PATH, sample_pace=True, event_dist_km=42.195)
check("distance shown", "| Afstand | 42.195 km |" in txt)
check("effective window shown (5.24 h x sweep 1.25 = 6.55 h)", "6.55 uur" in txt and "bezemwagen" in txt)
check("finish time row", "Gesimuleerde finishtijd" in txt)
check("section 3 uses peak values", "Piek T_rect tijdens de race" in txt)
tail_line = [l for l in txt.splitlines() if l.startswith("| Gemiddelde piek T_rect in deze groep")][0]
check("section 8 tail peak no longer n.b.", "n.b." not in tail_line, tail_line)
check("screening flag named correctly, no 'EHBO-contact' row",
      "Screeningsvlag" in txt and "met EHBO-contact" not in txt)
check("no NSAID share row for the tail group", "NSAID-gebruik in deze groep" not in txt)
check("no stale 'sectie 10' references to the criteria", "uit sectie 10" not in txt
      and "criterium in sectie 10" not in txt)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} check(s): {FAILS}")
    raise SystemExit(1)
print("ALL CHECKS PASSED")
