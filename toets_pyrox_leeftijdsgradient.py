# -*- coding: utf-8 -*-
"""
Toets PYROX optie B tegen de leeftijdsgradiënt van Parijs 2003.

Voert het plan uit dat vooraf is vastgelegd in
toetsplan_pyrox_leeftijdsgradient_2026-11-23.md, zonder wijzigingen in de
criteria. Schrijft het resultaat naar toets_pyrox_leeftijdsgradient_resultaat.json.

    python toets_pyrox_leeftijdsgradient.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import paris2003 as P
from pyrox_groups import TARGET_GROUPS
from pyrox_model import PyroxModel, PyroxPopulation

HIER = Path(__file__).resolve().parent
GROEPEN = ["adults_18_45", "middle_aged_45_65", "elderly_65_85", "very_elderly_85plus"]
BANDEN = ["15–44 j", "45–64 j", "65–84 j", "85+ j"]
# Fouillet et al. 2006, tabel 1, O/E 1–20 aug 2003 -> overmaat E = O/E - 1
E_GEMETEN = [0.13, 0.30, 0.50, 0.85]
REF = 2  # 65-84 j


def invoer():
    loads = P.paris_2003_heat_loads(per_degree=0.10)
    sq = P.paris_2003_sleep_quality("night_after")
    return loads, sq


def ensemble(cv):
    loads, sq = invoer()
    uit = []
    for k in GROEPEN:
        r = PyroxPopulation(TARGET_GROUPS[k], cv=cv).simulate(
            loads, pre_heatwave_heat_load=loads[0], sleep_quality_series=sq)
        c = r["critical_strain"]
        uit.append(dict(
            groep=k,
            F=float(np.mean(r["member_peak_strain"] >= 0.90 * c)),
            piek_gem_pct=float(100 * r["peak_strain"] / c),
            reeks=r["cumulative_strain"],
        ))
    return uit


def vorm_r(reeksen):
    """Pearson r tussen de dagelijkse belasting (eind van dag d, d = 1..16) van
    65-84 j en 85+ j en de dagelijkse oversterfte (Fouillet)."""
    doden = np.asarray(P.paris_2003_excess_deaths(), float)
    rs = []
    for tr in reeksen:
        x = np.asarray(tr, float)[1:len(doden) + 1]
        rs.append(float(np.corrcoef(x, doden)[0, 1]))
    return rs


def huidig_vorm_r():
    loads, sq = invoer()
    reeksen = []
    for k in GROEPEN[2:]:
        r = PyroxModel(TARGET_GROUPS[k]).simulate(loads, pre_heatwave_heat_load=loads[0],
                                                   sleep_quality_series=sq)
        reeksen.append(r["cumulative_strain"])
    return vorm_r(reeksen)


def toets(cv):
    res = ensemble(cv)
    F = [r["F"] for r in res]
    verh_model = [f / F[REF] if F[REF] > 0 else float("nan") for f in F]
    verh_gem = [e / E_GEMETEN[REF] for e in E_GEMETEN]
    factor = [m / g if g > 0 and np.isfinite(m) and m > 0 else float("inf")
              for m, g in zip(verh_model, verh_gem)]
    r_nieuw = vorm_r([res[2]["reeks"], res[3]["reeks"]])
    r_oud = huidig_vorm_r()
    c1 = all(F[i] < F[i + 1] for i in range(3))
    c2 = F[0] > 0
    c3 = all(0.5 <= f <= 2.0 for f in factor)
    c4 = all(rn >= ro - 0.05 for rn, ro in zip(r_nieuw, r_oud))
    return dict(
        cv=cv,
        groepen=[dict(band=b, groep=r["groep"], E_gemeten=e, F=round(r["F"], 4),
                      piek_gem_pct=round(r["piek_gem_pct"], 1),
                      verhouding_model=round(vm, 3), verhouding_gemeten=round(vg, 3),
                      factor=round(fa, 2) if np.isfinite(fa) else None)
                 for b, r, e, vm, vg, fa in zip(BANDEN, res, E_GEMETEN, verh_model, verh_gem, factor)],
        vorm_r_nieuw={"65-84": round(r_nieuw[0], 3), "85+": round(r_nieuw[1], 3)},
        vorm_r_huidig={"65-84": round(r_oud[0], 3), "85+": round(r_oud[1], 3)},
        criteria={"1_volgorde": c1, "2_jong_niet_nul": c2, "3_verhoudingen_factor_2": c3,
                  "4_vorm_niet_slechter": c4},
        geslaagd=bool(c1 and c2 and c3 and c4),
    )


def main():
    uitkomst = {"plan": "toetsplan_pyrox_leeftijdsgradient_2026-11-23.md",
                "hoofdtoets": toets(0.30),
                "gevoeligheid": [toets(0.20), toets(0.40)]}
    pad = HIER / "toets_pyrox_leeftijdsgradient_resultaat.json"
    pad.write_text(json.dumps(uitkomst, indent=2, ensure_ascii=False), encoding="utf-8")
    h = uitkomst["hoofdtoets"]
    print(f"Hoofdtoets CV 0,30: {'GESLAAGD' if h['geslaagd'] else 'NIET GESLAAGD'}")
    for g in h["groepen"]:
        print(f"  {g['band']:8s} F={g['F']:.3f}  model {g['verhouding_model']:.2f}  "
              f"gemeten {g['verhouding_gemeten']:.2f}  factor {g['factor']}")
    print("  criteria:", h["criteria"])
    print("  vorm r nieuw", h["vorm_r_nieuw"], "huidig", h["vorm_r_huidig"])
    for t in uitkomst["gevoeligheid"]:
        print(f"Gevoeligheid CV {t['cv']}: {'geslaagd' if t['geslaagd'] else 'niet geslaagd'} {t['criteria']}")
    print("Geschreven:", pad.name)


if __name__ == "__main__":
    main()
