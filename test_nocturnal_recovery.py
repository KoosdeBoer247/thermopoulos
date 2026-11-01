"""
test_nocturnal_recovery.py -- nocturnal recovery in PYROX (2026-10-17).

Run:  python test_nocturnal_recovery.py      (~10 s)
"""
import os, tempfile, warnings
warnings.filterwarnings("ignore")
import numpy as np
import builtins

FAILS = []


def check(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILS.append(name)


from thermopoulos_loader import ThermopoulosData, night_sleep_quality
import run_pyrox

print("\n1. Night minimum = the night AFTER each day")
d = ThermopoulosData("Thermopoulos_SmokeTest.xlsx")
daily = d.get_daily_heat_loads("Forecast_7d")
h = d._load_sheet("Forecast_7d")
day0 = daily["date"].iloc[0]
import pandas as pd
w = h["T_air_urban"][(h.index >= pd.Timestamp(day0) + pd.Timedelta(hours=18)) &
                     (h.index <= pd.Timestamp(day0) + pd.Timedelta(hours=32))]
check("t_night_min column present", "t_night_min" in daily.columns)
check("day 1: minimum over 18:00 -> 08:00 next day", abs(daily["t_night_min"].iloc[0] - w.min()) < 1e-9,
      f"{daily['t_night_min'].iloc[0]:.2f}")
check("last day has no complete next night (NaN)", np.isnan(daily["t_night_min"].iloc[-1]))
q = d.sleep_quality_series(daily)
check("last day falls back to its own minimum",
      abs(q[-1] - night_sleep_quality(daily["t_air_min"].iloc[-1])) < 1e-12)

print("\n2. Nocturnal recovery is ON by default (author's decision 2026-10-17)")
on = run_pyrox.assess_population(d, sheet="Forecast_7d", group_names=["elderly_65_85"])
off = run_pyrox.assess_population(d, sheet="Forecast_7d", group_names=["elderly_65_85"],
                                  use_nocturnal_recovery=False)
check("default is on", on["nocturnal_recovery"] is True and off["nocturnal_recovery"] is False)
check("default uses the night-after series", on["sleep_quality"] == d.sleep_quality_series(daily))
check("warm nights raise peak strain", on["groups"]["elderly_65_85"]["peak_strain"]
      > off["groups"]["elderly_65_85"]["peak_strain"] + 0.1,
      f"{off['groups']['elderly_65_85']['peak_strain']:.2f} -> {on['groups']['elderly_65_85']['peak_strain']:.2f}")

print("\n3. Paris 2003 with measured night minima")
from paris2003 import paris_2003_heat_loads, paris_2003_sleep_quality, PARIS_2003_TMIN_MEASURED
from pyrox_model import PyroxModel
from pyrox_groups import TARGET_GROUPS
check("Montsouris record night 25.5 C on 11 and 12 Aug",
      PARIS_2003_TMIN_MEASURED[10] == 25.5 and PARIS_2003_TMIN_MEASURED[11] == 25.5)
loads = paris_2003_heat_loads(per_degree=0.10)
g = TARGET_GROUPS["elderly_65_85"]
r_off = PyroxModel(g).simulate(loads, pre_heatwave_heat_load=loads[0])
r_on = PyroxModel(g).simulate(loads, pre_heatwave_heat_load=loads[0],
                              sleep_quality_series=paris_2003_sleep_quality("night_after"))
check("baseline (off) unchanged: 65-85 emergency day 9", r_off["emergency_day"] == 9, str(r_off["emergency_day"]))
check("with recovery: one day earlier (8)", r_on["emergency_day"] == 8, str(r_on["emergency_day"]))

print("\n4. Report: nights section and correct emergency threshold")
import generate_pyrox_report as R
with tempfile.TemporaryDirectory() as tmp:
    txt = R.generate_pyrox_report("Test", on, os.path.join(tmp, "r.md"))
check("section 2b (nights) present", "## 2b. Nachten" in txt)
check("report states that the night counts", "Nachtelijk herstel | telt mee" in txt)
check("emergency threshold text says 90% (code: 0.90)", "75% en 90%" in txt and "75% en 95%" not in txt)

print()
if FAILS:
    print(f"FAILED: {FAILS}")
    raise SystemExit(1)
print("ALL CHECKS PASSED")
