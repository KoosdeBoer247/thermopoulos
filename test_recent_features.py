# -*- coding: utf-8 -*-
"""
test_recent_features.py -- tests voor de functies van september/oktober 2026
==========================================================================

Aanleiding: review 2026-10-01 (aanbeveling C3) -- geen enkele bestaande test
raakte de functies die in september/oktober 2026 zijn toegevoegd. Dit bestand
dekt ze met kleine tests met een bekende uitkomst:

  1. ThermopoulosData.sheet_period()           (Historical_Custom-ondersteuning)
  2. get_hourly_weather(): halfuur-klemming     (fix C1, 2026-10-01)
  3. TCF-rekenregels en klasse-grenzen          (HESTIA_ControlFailure_Module)
  4. Pacing- en klinische constanten            (hestia_model)
  5. Monte Carlo-export: conjunctie-, eenzijdig-extreem- en TCF-kolommen,
     met hun onderlinge logica (klein: n=10)
  6. Geen f-strings die alleen op Python 3.12+ werken (fix 2026-10-01)
  7. CVR onder nul: monotoon, naadloos, hartslag <= maximum (2026-10-04)

Draaien:  python test_recent_features.py
Gebruikt een tijdelijke map (tempfile), dus werkt ook op Windows.
"""
import os
import sys
import tempfile
import tokenize
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd

results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def make_excel(tmpdir):
    from suite_smoke_test import build_synthetic_excel
    return build_synthetic_excel(os.path.join(tmpdir, "Thermopoulos_Test.xlsx"))


# ---------------------------------------------------------------------------
def test_sheet_period(path):
    print("\n=== 1. sheet_period() ===")
    from thermopoulos_loader import ThermopoulosData
    data = ThermopoulosData(path)
    sheet = data.available_sheets[0]
    info = data.sheet_period(sheet)
    df = data._load_sheet(sheet)
    check("geeft sheetnaam terug", info["sheet"] == sheet)
    check("start = eerste tijdstip", info["start"] == df.index.min())
    check("einde = laatste tijdstip", info["end"] == df.index.max())
    check("aantal uren klopt", info["hours"] == len(df), f"{info['hours']} uur")


# ---------------------------------------------------------------------------
def test_half_hour_clamp(path):
    print("\n=== 2. get_hourly_weather(): halfuur-klemming (C1) ===")
    from thermopoulos_loader import ThermopoulosData
    data = ThermopoulosData(path)
    sheet = data.available_sheets[0]
    df = data._load_sheet(sheet)
    t0 = df.index[5]                       # een heel uur midden in de reeks
    half = t0 + pd.Timedelta(minutes=30)

    rows_half = data.get_hourly_weather(sheet, start_time=str(half), duration_hours=2)
    rows_full = data.get_hourly_weather(sheet, start_time=str(t0), duration_hours=2)
    t_ref = float(df.loc[t0, "T_air_urban"])
    check("start :30 bevat de uurrij ervoor",
          abs(rows_half[0]["main"]["temp"] - t_ref) < 1e-9,
          f"eerste rij {rows_half[0]['main']['temp']:.2f} C = uur {t0:%H:%M}")
    check("start op heel uur ongewijzigd",
          abs(rows_full[0]["main"]["temp"] - t_ref) < 1e-9 and len(rows_full) == 3)
    # 09:30 + 2 u = 11:30 -> uurrijen 09:00, 10:00, 11:00, 12:00
    check("einde wordt naar boven afgerond op heel uur", len(rows_half) == 4,
          f"{len(rows_half)} uurrijen")


# ---------------------------------------------------------------------------
def test_tcf_rules():
    print("\n=== 3. TCF-rekenregels en klassen ===")
    import HESTIA_ControlFailure_Module as tcf
    check("increment = excess x tekort x dt",
          abs(tcf.control_failure_increment(41.5, -0.5, 10.0) - 5.0) < 1e-9)
    check("geen dosis onder 40,5 C", tcf.control_failure_increment(40.4, -2.0, 10.0) == 0.0)
    check("geen dosis bij positieve CO-reserve", tcf.control_failure_increment(42.0, 0.1, 10.0) == 0.0)
    check("NaN CO-reserve telt als geen tekort", tcf.co_deficit(float("nan")) == 0.0)
    grenzen = [(0, "none"), (4.99, "brief"), (5.0, "relevant"), (19.99, "relevant"),
               (20.0, "severe"), (59.99, "severe"), (60.0, "extreme")]
    ok = all(tcf.classify_dose(d) == k for d, k in grenzen)
    check("klassegrenzen 5 / 20 / 60", ok)


# ---------------------------------------------------------------------------
def test_constants():
    print("\n=== 4. Pacing- en klinische constanten ===")
    import hestia_model as hm
    check("CO_RESERVE_PACING_THRESHOLD = 2,0 L/min", hm.CO_RESERVE_PACING_THRESHOLD == 2.0)
    check("T_RECT_PACING_THRESHOLD = 38,5 C", hm.T_RECT_PACING_THRESHOLD == 38.5)
    check("T_AUC_KLINISCH = 40,5 C", hm.T_AUC_KLINISCH == 40.5)
    check("AUC_ROBERTS_GRENS = 60", hm.AUC_ROBERTS_GRENS == 60.0)
    check("K_P_PACING_CV bestaat en is positief", getattr(hm, "K_P_PACING_CV", 0) > 0)


# ---------------------------------------------------------------------------
def test_mc_export(path):
    print("\n=== 5. Monte Carlo-export (n=10) ===")
    from thermopoulos_loader import ThermopoulosData
    from run_hestia import monte_carlo_adult
    data = ThermopoulosData(path)
    sheet = data.available_sheets[0]
    daily = data.get_daily_heat_loads(sheet)
    start = f"{daily['date'].iloc[3]} 09:30"   # bewust een halfuur-start
    _, _, df = monte_carlo_adult(data, start_time=start, duration_hours=2.0,
                                 met_value=9.0, clo_value=0.2, n_simulations=10,
                                 use_parallel=False, random_seed=42, sheet=sheet)
    nodig = ["conjunctie_ooit_bereikt", "conjunctie_eerste_min", "conjunctie_ooit_hersteld",
             "eenzijdig_extreem", "gemist_door_bestaande_criteria",
             "thermisch_percentiel", "cardiovasculair_percentiel"]
    ontbrekend = [c for c in nodig if c not in df.columns]
    check("alle nieuwe kolommen aanwezig", not ontbrekend, f"ontbrekend: {ontbrekend}" if ontbrekend else "")
    if ontbrekend:
        return
    check("hersteld impliceert bereikt",
          bool(((df["conjunctie_ooit_hersteld"] == 1) <= (df["conjunctie_ooit_bereikt"] == 1)).all()))
    check("eerste moment alleen ingevuld als bereikt",
          bool((df.loc[df["conjunctie_ooit_bereikt"] == 0, "conjunctie_eerste_min"].isna()).all()))
    check("gemist impliceert eenzijdig extreem",
          bool(((df["gemist_door_bestaande_criteria"] == 1) <= (df["eenzijdig_extreem"] == 1)).all()))
    pct_ok = df["thermisch_percentiel"].between(0, 100).all() and df["cardiovasculair_percentiel"].between(0, 100).all()
    check("percentielen tussen 0 en 100", bool(pct_ok))


# ---------------------------------------------------------------------------
def _py312_only_fstrings(path):
    """Zoek f-strings die binnen de accolades dezelfde aanhalingstekens gebruiken
    als de f-string zelf. Dat mag pas vanaf Python 3.12 (PEP 701)."""
    hits = []
    if not hasattr(tokenize, "FSTRING_START"):
        return hits        # oudere Python: zo'n bestand zou al niet importeren
    with open(path, "rb") as f:
        try:
            toks = list(tokenize.tokenize(f.readline))
        except (tokenize.TokenError, SyntaxError):
            return hits
    stack = []
    for t in toks:
        if t.type == tokenize.FSTRING_START:
            q = t.string.lstrip("rRfFbBuU")[:1]
            if stack and q == stack[-1]:
                hits.append(t.start[0])
            stack.append(q)
        elif t.type == tokenize.FSTRING_END and stack:
            stack.pop()
        elif t.type == tokenize.STRING and stack:
            q = t.string.lstrip("rRfFbBuU")[:1]
            if q == stack[-1]:
                hits.append(t.start[0])
    return hits


def test_python_compat():
    print("\n=== 6. Geen f-strings die alleen op Python 3.12+ werken ===")
    if not hasattr(tokenize, "FSTRING_START"):
        check("controle overgeslagen (Python < 3.12 heeft dit al bij import afgevangen)", True)
        return
    bad = {}
    for fn in sorted(os.listdir(HERE)):
        if fn.endswith(".py"):
            h = _py312_only_fstrings(os.path.join(HERE, fn))
            if h:
                bad[fn] = h
    check("alle modules werken ook op Python 3.10/3.11", not bad, f"gevonden: {bad}" if bad else "")


# ---------------------------------------------------------------------------
def test_cvr_below_zero():
    print("\n=== 7. CVR onder nul: monotoon, naadloos, hartslag <= max (2026-10-04) ===")
    from HESTIA_CVR_Module_v2 import CVRModel, RunnerProfile, JOS3Outputs
    profielen = [(45, 45, 10.0), (30, 55, 12.0), (60, 35, 8.0), (25, 60, 13.0)]
    alles_mono, alles_hr, alles_naad = True, True, True
    ref = None
    for age, vo2, met in profielen:
        m = CVRModel(RunnerProfile(mass=75, height=178, age=age, sex="male", vo2max=vo2))
        res, hr_over = [], 0.0
        for tc in np.round(np.arange(37.5, 43.01, 0.05), 2):
            st = m.compute_step(JOS3Outputs(0, 0, float(tc), float(tc), 0.03 * 75 * max(0, (tc - 37.5) / 4),
                                            0, 0, 0, float(tc - 3.5), met))
            res.append(float(st.CO_reserve)); hr_over = max(hr_over, float(st.HR) - float(st.HR_max))
        r = np.array(res)
        alles_mono &= bool(np.all(np.diff(r) <= 1e-9))
        alles_hr &= hr_over <= 1e-9
        stappen = np.abs(np.diff(r))
        alles_naad &= bool(stappen.max() < 0.2)          # geen sprong in de curve
        if (age, vo2, met) == (45, 45, 10.0):
            ref = r[0]
    check("CO_reserve daalt steeds bij meer hitte (ook onder nul)", alles_mono)
    check("hartslag nooit boven het maximum", alles_hr)
    check("geen sprong in de curve (stap < 0,2 L/min per 0,05 C)", alles_naad)
    check("boven nul ongewijzigd (referentie 3,834 L/min bij 37,5 C)", abs(ref - 3.834) < 0.001, f"{ref:.3f}")


# ---------------------------------------------------------------------------
def main():
    print("=" * 70)
    print("TESTS RECENTE FUNCTIES (sept/okt 2026)")
    print("=" * 70)
    with tempfile.TemporaryDirectory() as tmp:
        path = make_excel(tmp)
        for fn in (lambda: test_sheet_period(path), lambda: test_half_hour_clamp(path),
                   test_tcf_rules, test_constants, lambda: test_mc_export(path),
                   test_python_compat, test_cvr_below_zero):
            try:
                fn()
            except Exception as exc:          # een crash telt als FAIL, niet als stilte
                check(f"onverwachte fout: {type(exc).__name__}", False, str(exc)[:200])
    n_ok, n = sum(results), len(results)
    print("\n" + "=" * 70)
    print(f"{n_ok}/{n} controles geslaagd")
    print("=" * 70)
    return 0 if n_ok == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
