"""PYROX option B (2026-11-23): population layer PyroxPopulation."""
import numpy as np

import paris2003 as P
from pyrox_groups import TARGET_GROUPS, PAPER_PROTOTYPES
from pyrox_model import PyroxModel, PyroxPopulation, resilience_multipliers, member_group


def _paris():
    loads = P.paris_2003_heat_loads(per_degree=0.10)
    return loads, P.paris_2003_sleep_quality("night_after")


def test_zonder_spreiding_gelijk_aan_enkel_model():
    loads, sq = _paris()
    for k in TARGET_GROUPS:
        a = PyroxModel(TARGET_GROUPS[k]).simulate(loads, pre_heatwave_heat_load=loads[0], sleep_quality_series=sq)
        b = PyroxPopulation(TARGET_GROUPS[k], cv=0.0).simulate(loads, pre_heatwave_heat_load=loads[0],
                                                              sleep_quality_series=sq)
        assert np.array_equal(a["cumulative_strain"], b["cumulative_strain"])
        assert a["emergency_day"] == b["emergency_day"]


def test_mediaan_lid_is_de_groep():
    f = resilience_multipliers()
    assert len(f) == 41 and abs(f[20] - 1.0) < 1e-12
    assert np.all(np.diff(f) > 0)
    g = TARGET_GROUPS["elderly_65_85"]
    assert member_group(g, 1.0) is g


def test_deterministisch():
    loads, sq = _paris()
    g = TARGET_GROUPS["very_elderly_85plus"]
    a = PyroxPopulation(g).simulate(loads, pre_heatwave_heat_load=loads[0], sleep_quality_series=sq)
    b = PyroxPopulation(g).simulate(loads, pre_heatwave_heat_load=loads[0], sleep_quality_series=sq)
    assert np.array_equal(a["cumulative_strain"], b["cumulative_strain"])


def test_parijs_geleidelijk_en_geordend():
    """Criteria 1 en 2 van het toetsplan (volgorde, jong niet nul)."""
    loads, sq = _paris()
    F = []
    for k in ["adults_18_45", "middle_aged_45_65", "elderly_65_85", "very_elderly_85plus"]:
        r = PyroxPopulation(TARGET_GROUPS[k]).simulate(loads, pre_heatwave_heat_load=loads[0],
                                                       sleep_quality_series=sq)
        F.append(float(np.mean(r["member_peak_strain"] >= 0.9 * r["critical_strain"])))
    assert F[0] > 0
    assert all(F[i] < F[i + 1] for i in range(3))


def test_sporters_en_buitenwerkers_verwijderd():
    for k in ("endurance_athletes", "elite_athletes", "recreational_athletes", "outdoor_workers"):
        assert k not in TARGET_GROUPS
    assert len(TARGET_GROUPS) == 19
    assert all(k in TARGET_GROUPS for k in PAPER_PROTOTYPES)
