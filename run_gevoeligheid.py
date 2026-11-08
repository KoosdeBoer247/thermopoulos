# -*- coding: utf-8 -*-
"""
run_gevoeligheid.py -- ERA5 sensitivity for HESTIA and PYROX
============================================================

[2026-11-08] Start menu choice 6. Takes ONE existing Data Engine file, makes
a scenario file per hypothetical weather disturbance (gevoeligheid.py), runs
HESTIA (event, Monte Carlo) or PYROX (heatwave) on every scenario file with
identical settings, and writes one comparison.

The settings are asked once. HESTIA uses the same virtual participants in
every scenario (fixed seed: 'random' is not offered here), so a difference
between scenarios comes from the weather only. The neutral scenario (the
base file recomputed by the current Data Engine) is always run and is the
reference for every difference.

Output in the working folder:
    Gevoeligheid_<model>_<place>_<timestamp>.xlsx
        Scenarios   all parameters of every scenario
        Weather     per scenario the weather over the event window / the sheet
        Results     per scenario and outcome: value, neutral, difference, %
    Gevoeligheid_<model>_<place>_<timestamp>.png   one dot per scenario
and the scenario weather files in scenarios/<base file>/ (kept, so a scenario
can be opened in HESTIA or PYROX on its own).

Facts only, no verdict: which result is robust is for the reader.

Author: Koos de Boer (sole developer); written with the help of Claude
(Anthropic) as an assistant.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import gevoeligheid as gv                                   # noqa: E402
from thermopoulos_loader import ThermopoulosData            # noqa: E402

SCENARIO_FILE = "gevoeligheid_scenarios.json"   # optional own list (shared with Klimatos)
SECONDS_PER_PARTICIPANT = 0.35                   # rough, one core, for the estimate

# HESTIA outcomes compared (key in monte_carlo_adult()'s stats, label, unit)
HESTIA_OUTCOMES = [
    ("expected_collapses_per_1000", "expected collapses per 1000 (active endpoint)", "per 1000"),
    ("p_collapse_mean", "mean collapse probability", "fraction"),
    ("pct_decompensation", "share with cardiovascular decompensation", "%"),
    ("pct_roberts_kritiek", "share in Roberts critical zone", "%"),
    ("pct_ehs_postfinish", "share EHS after the finish", "%"),
    ("eac_per_1000", "exercise-associated collapse per 1000", "per 1000"),
    ("co_reserve_min_p50", "lowest CO_reserve, median", "L/min"),
    ("co_reserve_min_p05", "lowest CO_reserve, 5th percentile", "L/min"),
    ("hr_peak_p50", "peak heart rate, median", "bpm"),
    ("dehy_pct_p50", "dehydration, median", "% body mass"),
    ("t_rect_pf_p95", "peak core temperature, 95th percentile", "degC"),
    ("wbgt_race_max_p50", "highest WBGT during the race, median", "degC"),
]
HESTIA_KEYS = [("HESTIA", "expected collapses per 1000 (active endpoint)"),
               ("HESTIA", "share with cardiovascular decompensation"),
               ("HESTIA", "peak core temperature, 95th percentile"),
               ("HESTIA", "lowest CO_reserve, median"),
               ("Weather", "T_air_urban max"), ("Weather", "WBGT max")]


# ---------------------------------------------------------------------------
# weather summary
# ---------------------------------------------------------------------------
def weather_rows(path, sheet: str, scenario: str, start=None, hours=None) -> List[Dict]:
    """Max air temperature, WBGT, UTCI and wet bulb, min air temperature and
    mean RH over the event window (HESTIA) or the whole sheet (PYROX)."""
    df = pd.read_excel(path, sheet_name=sheet, index_col=0)
    df.index = pd.to_datetime(df.index)
    if start is not None and hours is not None:
        t0 = pd.Timestamp(start)
        df = df[(df.index >= t0.floor("h")) & (df.index <= t0 + pd.Timedelta(hours=hours))]
    rows = []
    for col, stat, unit in (("T_air_urban", "max", "degC"), ("T_air_urban", "min", "degC"),
                            ("RH_urban", "mean", "%"), ("T_wetbulb", "max", "degC"),
                            ("WBGT", "max", "degC"), ("UTCI", "max", "degC"),
                            ("MRT", "max", "degC")):
        if col in df.columns and len(df):
            v = float(getattr(df[col], stat)())
            rows.append({"scenario": scenario, "group": "Weather", "outcome": f"{col} {stat}",
                         "unit": unit, "value": v})
    return rows


# ---------------------------------------------------------------------------
# HESTIA
# ---------------------------------------------------------------------------
def run_hestia_scenarios(base_path, scenarios: List[gv.Scenario], settings: Dict,
                         out_dir=None, progress=print) -> pd.DataFrame:
    """Run monte_carlo_adult() on every scenario file with the same settings.

    settings: sheet, start_time, duration_hours, met_value, clo_value,
    n_simulations, training_factor, acclimatization_factor, use_parallel,
    random_seed (int), sample_pace, event_dist_km, population, endpoint.
    Returns the long comparison table (compare_to_neutral)."""
    import hestia_model as hestia
    import run_hestia
    if settings.get("random_seed") is None:
        raise ValueError("a fixed random seed is required: every scenario must use the same participants")
    old_ep = hestia.ACTIVE_ENDPOINT
    if settings.get("endpoint"):
        hestia.ACTIVE_ENDPOINT = settings["endpoint"]
    rows: List[Dict] = []
    try:
        for i, sc in enumerate(scenarios, 1):
            progress(f"\n[{i}/{len(scenarios)}] {sc.name}: {sc.description}")
            path = gv.make_scenario_file(base_path, sc, out_dir)
            data = ThermopoulosData(path)
            _, stats, _ = run_hestia.monte_carlo_adult(
                data, settings["start_time"], settings["duration_hours"],
                met_value=settings["met_value"], clo_value=settings["clo_value"],
                n_simulations=settings["n_simulations"],
                training_factor=settings.get("training_factor", 0.0),
                acclimatization_factor=settings.get("acclimatization_factor", 0.0),
                sheet=settings["sheet"], use_parallel=settings.get("use_parallel", False),
                random_seed=settings["random_seed"], run_control_failure=False,
                sample_pace=settings.get("sample_pace", False),
                event_dist_km=settings.get("event_dist_km", 16.1),
                population=settings.get("population", "lopers"))
            if stats is None:
                progress(f"  {sc.name}: no valid participants, skipped")
                continue
            for key, label, unit in HESTIA_OUTCOMES:
                v = stats.get(key)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    rows.append({"scenario": sc.name, "group": "HESTIA", "outcome": label,
                                 "unit": unit, "value": float(v)})
            rows += weather_rows(path, settings["sheet"], sc.name,
                                 settings["start_time"], settings["duration_hours"])
    finally:
        hestia.ACTIVE_ENDPOINT = old_ep
    return gv.compare_to_neutral(rows, neutral_name=_neutral_name(scenarios))


# ---------------------------------------------------------------------------
# PYROX
# ---------------------------------------------------------------------------
def run_pyrox_scenarios(base_path, scenarios: List[gv.Scenario], sheet: str,
                        group_names: Optional[List[str]] = None,
                        initial: str = "follow", out_dir=None, progress=print) -> pd.DataFrame:
    """Run assess_population() on every scenario file.

    initial = 'follow' (default): PYROX starts each scenario in equilibrium with
              that scenario's own first day, as it always does -- if ERA5 is
              too cool here, the population was also used to the warmer weather.
    initial = 'neutral': every scenario starts from the NEUTRAL first-day load,
              so the result shows the effect of the warmer heatwave itself.
    """
    from run_pyrox import assess_population
    from pyrox_groups import TARGET_GROUPS
    if initial not in ("follow", "neutral"):
        raise ValueError("initial must be 'follow' or 'neutral'")
    neutral = _neutral_name(scenarios)
    files = {}
    for sc in scenarios:
        files[sc.name] = gv.make_scenario_file(base_path, sc, out_dir)
    pre = None
    if initial == "neutral":
        pre = float(ThermopoulosData(files[neutral]).get_daily_heat_loads(sheet)["baseline_heat_load"].iloc[0])
    rows: List[Dict] = []
    for i, sc in enumerate(scenarios, 1):
        progress(f"[{i}/{len(scenarios)}] {sc.name}: {sc.description}")
        rep = assess_population(ThermopoulosData(files[sc.name]), sheet=sheet,
                                group_names=group_names, pre_heatwave_heat_load=pre)
        hl = np.asarray(rep["heat_loads"], dtype=float)
        rows.append({"scenario": sc.name, "group": "PYROX", "outcome": "heat load, mean over the days",
                     "unit": "load", "value": float(hl.mean())})
        rows.append({"scenario": sc.name, "group": "PYROX", "outcome": "heat load, highest day",
                     "unit": "load", "value": float(hl.max())})
        rows.append({"scenario": sc.name, "group": "PYROX", "outcome": "sleep quality, mean",
                     "unit": "0-1", "value": float(np.mean(rep["sleep_quality"]))})
        for name, res in rep["groups"].items():
            label = TARGET_GROUPS[name].display_name
            rows.append({"scenario": sc.name, "group": label, "outcome": "peak strain",
                         "unit": "strain", "value": float(res["peak_strain"])})
            # critical_strain is the group's fixed ceiling (1/strength), not a count
            rows.append({"scenario": sc.name, "group": label, "outcome": "peak strain, share of critical strain",
                         "unit": "fraction", "value": float(res["peak_strain"]) / float(res["critical_strain"])})
            rows.append({"scenario": sc.name, "group": label, "outcome": "highest final risk",
                         "unit": "risk", "value": float(np.nanmax(np.asarray(res["final_risk"], dtype=float)))})
            # day index of the strain trajectory: 0 = initial state, k = after day k
            for k, lab in (("caution_day", "first caution day (index, 0 = start)"),
                           ("danger_day", "first danger day (index, 0 = start)"),
                           ("emergency_day", "first emergency day (index, 0 = start)")):
                v = res.get(k)
                rows.append({"scenario": sc.name, "group": label, "outcome": lab, "unit": "day index",
                             "value": float(v) if v is not None else np.nan})
        rows += weather_rows(files[sc.name], sheet, sc.name)
    return gv.compare_to_neutral(rows, neutral_name=neutral)


def _neutral_name(scenarios: List[gv.Scenario]) -> str:
    for sc in scenarios:
        if sc.is_neutral():
            return sc.name
    raise ValueError("the scenario list needs the neutral scenario")


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------
def save(table: pd.DataFrame, scenarios: List[gv.Scenario], model: str, place: str,
         settings: Dict, base_path, keys: List, out_dir=".") -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    stem = Path(out_dir) / f"Gevoeligheid_{model}_{gv._safe(str(place))}_{stamp}"
    xlsx = stem.with_suffix(".xlsx")
    info = {"model": model, "place": place, "base_file": Path(base_path).name,
            "scenario_type": gv.SCENARIO_FILE_TYPE,
            "generated": datetime.now().isoformat(timespec="seconds"),
            **{f"setting_{k}": (str(v) if not isinstance(v, (int, float, bool)) else v)
               for k, v in settings.items()}}
    with pd.ExcelWriter(xlsx, engine="xlsxwriter") as w:
        gv.scenario_table(scenarios).to_excel(w, sheet_name="Scenarios", index=False)
        table[table["group"] == "Weather"].to_excel(w, sheet_name="Weather", index=False)
        table[table["group"] != "Weather"].to_excel(w, sheet_name="Results", index=False)
        pd.DataFrame([info]).to_excel(w, sheet_name="Metadata", index=False)
    gv.plot_dots(table, keys, f"{place}: {model} under ERA5 scenarios (dashed = neutral)",
                 stem.with_suffix(".png"))
    return xlsx


def print_table(table: pd.DataFrame, keys: List) -> None:
    names = list(dict.fromkeys(table["scenario"]))
    for g, o in keys:
        d = table[(table["group"] == g) & (table["outcome"] == o)].set_index("scenario")
        if d.empty:
            continue
        unit = d["unit"].iloc[0]
        k, u = (100.0, "%") if unit == "fraction" else (1.0, unit)
        print(f"\n  {g}: {o} [{u}]")
        for n in names:
            if n in d.index and np.isfinite(d.loc[n, "value"]):
                print(f"    {n:<18s} {d.loc[n, 'value'] * k:10.3f}   ({d.loc[n, 'difference'] * k:+.3f})")


# ---------------------------------------------------------------------------
# console
# ---------------------------------------------------------------------------
def _ask(msg: str, default: str) -> str:
    try:
        a = input(f"{msg} [{default}]: ").strip()
    except EOFError:
        a = ""
    return a or default


def ask_scenarios(base_path) -> List[gv.Scenario]:
    if os.path.exists(SCENARIO_FILE) and not _ask(
            f"Own scenario file '{SCENARIO_FILE}' found. Use it? (y/n)", "y").lower().startswith("n"):
        try:
            return gv.load_scenarios(SCENARIO_FILE)
        except Exception as exc:
            print(f"  Could not read it ({exc}); using the standard set.")
    coastal = _ask("Coastal site? Adds the coastal-correction scenarios "
                   "(Data Engine shape, peak 3.0 C, and 2, 4, 6 C) (y/n)", "n").lower().startswith("y")
    if coastal:
        try:
            with pd.ExcelFile(base_path) as xls:
                already = any(
                    bool(pd.read_excel(xls, sheet_name=s, usecols=["coastal_correction_applied"])
                         ["coastal_correction_applied"].astype(bool).any())
                    for s in xls.sheet_names if s != "Metadata")
            if already:
                print("  Note: this file already carries the Data Engine's coastal correction; "
                      "the coastal scenarios come on top of it.")
        except Exception:
            pass
    return gv.scenario_set(coastal=coastal)


def _pick_file() -> Optional[Path]:
    from thermopoulos_loader import choose_thermopoulos_file
    return choose_thermopoulos_file(".")


def interactive_hestia(base_path: Path) -> None:
    import hestia_model as hestia
    from hestia_model import MET_ACTIVITIES_ADULT, CLO_OPTIONS_ADULT
    from hestia_console import select_met_activity, select_clo_value, get_adaptation_profile
    data = ThermopoulosData(base_path)
    print(f"\nBase file: {base_path.name}  (place: {data.city})")
    print(f"Sheets: {data.available_sheets}")
    default_sheet = "Forecast_7d" if "Forecast_7d" in data.available_sheets else data.available_sheets[0]
    sheet = _ask("Sheet", default_sheet)
    if sheet not in data.available_sheets:
        sheet = default_sheet
    daily = data.get_daily_heat_loads(sheet)
    print(f"Dates on this sheet: {daily['date'].iloc[0]} .. {daily['date'].iloc[-1]}")
    keys = list(hestia.COLLAPSE_ENDPOINTS)
    for i, k in enumerate(keys, 1):
        print(f"  {i}. {hestia.COLLAPSE_ENDPOINTS[k]['label']}")
    ep = _ask("Endpoint (number)", "1")
    endpoint = keys[int(ep) - 1] if ep.isdigit() and 1 <= int(ep) <= len(keys) else keys[0]
    start_time = f"{_ask('Start date (YYYY-MM-DD)', str(daily['date'].iloc[0]))} {_ask('Start time (HH:MM)', '09:00')}"
    dist = float(_ask("Event distance (km)", "16.1"))
    try:
        act, met, speed = select_met_activity(MET_ACTIVITIES_ADULT)
        implied = round(dist / (speed * 3.6), 2) if speed > 0 else 4.0
    except EOFError:
        act, met, implied = 13, 8.0, 4.0
    duration = float(_ask(f"Duration in hours (distance / pace = {implied:.2f})", str(implied)))
    try:
        clo = select_clo_value(CLO_OPTIONS_ADULT)
    except EOFError:
        clo = 0.3
    try:
        ad = get_adaptation_profile(act)
        tf, af = ad["training"], ad["acclimatization"]
    except EOFError:
        tf, af = 0.0, 0.0
    n = int(_ask("Participants per scenario", "1000"))
    par = _ask("Use multiprocessing? (y/n)", "y").lower().startswith("y")
    pace = _ask("Individual pace per participant? (y/n)", "n").lower().startswith("y")
    pop = "wandelaars" if _ask("Population: runners (r) or walkers (w)", "r").lower().startswith("w") else "lopers"
    if pop == "wandelaars":
        pace = False
    seed_raw = _ask("Random seed (fixed, the same for every scenario)", "42")
    seed = int(seed_raw) if seed_raw.lstrip("-").isdigit() else 42
    scen = ask_scenarios(base_path)
    est = len(scen) * n * SECONDS_PER_PARTICIPANT / (max(1, (os.cpu_count() or 1) - 1) if par else 1) / 60
    print(f"\n{len(scen)} scenarios: " + ", ".join(s.name for s in scen))
    print(f"Estimated time: about {est:.0f} min ({n} participants x {len(scen)} scenarios).")
    if not _ask("Start? (y/n)", "y").lower().startswith("y"):
        return
    settings = dict(sheet=sheet, start_time=start_time, duration_hours=duration, met_value=met,
                    clo_value=clo, n_simulations=n, training_factor=tf, acclimatization_factor=af,
                    use_parallel=par, random_seed=seed, sample_pace=pace, event_dist_km=dist,
                    population=pop, endpoint=endpoint)
    t = time.time()
    table = run_hestia_scenarios(base_path, scen, settings)
    print(f"\nDone in {(time.time() - t) / 60:.1f} min.")
    print_table(table, HESTIA_KEYS)
    path = save(table, scen, "HESTIA", data.city, settings, base_path, HESTIA_KEYS)
    print(f"\nWritten: {path.name} and {path.with_suffix('.png').name}; "
          f"scenario weather files in {gv.scenario_folder(base_path)}")


def interactive_pyrox(base_path: Path) -> None:
    from run_pyrox import _select_data_sheet, _select_groups
    from pyrox_groups import TARGET_GROUPS
    data = ThermopoulosData(base_path)
    print(f"\nBase file: {base_path.name}  (place: {data.city})")
    sheet = _select_data_sheet(data)
    groups = _select_groups()
    ini = _ask("Initial condition: follow each scenario's first day (f) or fixed at the neutral "
               "first day (n)", "f").lower()
    initial = "neutral" if ini.startswith("n") else "follow"
    scen = ask_scenarios(base_path)
    table = run_pyrox_scenarios(base_path, scen, sheet, groups, initial)
    keys = [("PYROX", "heat load, highest day"), ("PYROX", "sleep quality, mean")]
    keys += [(TARGET_GROUPS[g].display_name, "peak strain") for g in groups[:3]]
    keys += [("Weather", "T_air_urban max"), ("Weather", "T_air_urban min")]
    print_table(table, keys)
    settings = dict(sheet=sheet, groups=",".join(groups), initial_condition=initial)
    path = save(table, scen, "PYROX", data.city, settings, base_path, keys)
    print(f"\nWritten: {path.name} and {path.with_suffix('.png').name}; "
          f"scenario weather files in {gv.scenario_folder(base_path)}")


def interactive_files_only(base_path: Path) -> None:
    scen = ask_scenarios(base_path)
    paths = gv.make_scenario_files(base_path, scen)
    print(f"\n{len(paths)} scenario weather files written to {gv.scenario_folder(base_path)}:")
    for n, p in paths.items():
        print(f"  {n:<18s} {p.name}")
    print("Open one in HESTIA or PYROX by copying it into the working folder.")


def main() -> None:
    print("=" * 70)
    print("  SENSITIVITY  -  how much does the result depend on the ERA5 input?")
    print("  Hypothetical scenarios, not corrections; the neutral run is the result.")
    print("=" * 70)
    base = _pick_file()
    if base is None:
        print("No Data Engine file chosen (start menu choice 5 makes one).")
        return
    k = _ask("\n1 HESTIA event, 2 PYROX heatwave, 3 scenario weather files only", "1")
    if k == "2":
        interactive_pyrox(Path(base))
    elif k == "3":
        interactive_files_only(Path(base))
    else:
        interactive_hestia(Path(base))


if __name__ == "__main__":
    main()
