"""HESTIA-werk (2026-11-24): werkschema, groep werkers, grenzen en een korte
werkdag van begin tot eind. hestia_model.py is voor deze modus niet gewijzigd;
de golden test bewaakt dat lopers en wandelaars bit-gelijk blijven."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import pytest

import hestia_werk as hw


def test_fasen_cyclus_en_pauze():
    s = hw.WerkSchema(begin="07:00", einde="09:00", werk_min=45, rust_min=15, pauzes=[("08:00", 10)])
    tijden = pd.date_range("2026-07-01 07:00", "2026-07-01 09:00", freq="5min")
    f = hw.fasen(s, tijden)
    assert len(f) == len(tijden)
    assert f[0] == "werk"
    # 07:00-07:45 werk (stappen 1..9), 07:45-08:00 rust (10..12)
    assert f[1:10] == ["werk"] * 9
    assert f[10:13] == ["rust"] * 3
    # 08:00-08:10 pauze gaat voor de cyclus
    assert f[13:15] == ["pauze"] * 2
    assert f[15] == "werk"


def test_fasen_doorwerken_zonder_pauze():
    s = hw.WerkSchema(begin="07:00", einde="08:00", werk_min=60, rust_min=0, pauzes=[])
    f = hw.fasen(s, pd.date_range("2026-07-01 07:00", "2026-07-01 08:00", freq="5min"))
    assert set(f) == {"werk"}


def test_schema_fouten():
    assert hw.WerkSchema().fouten() == []
    assert hw.WerkSchema(begin="10:00", einde="09:00").fouten()
    assert hw.WerkSchema(werk_min=43).fouten()
    assert hw.WerkSchema(pauzes=[("10:00", 7)]).fouten()


def test_groep_werkers_herhaalbaar_en_binnen_grenzen():
    a = hw.genereer_werkers(300, 7, 4.0, 0.8, 0.5, 0.6)
    b = hw.genereer_werkers(300, 7, 4.0, 0.8, 0.5, 0.6)
    assert [p.vo2max for p in a] == [p.vo2max for p in b]
    assert len(a) == 300
    leeftijd = np.array([p.age for p in a])
    assert leeftijd.min() >= hw.LEEFTIJD_MIN and leeftijd.max() <= hw.LEEFTIJD_MAX
    man = np.mean([p.gender == "male" for p in a])
    assert 0.72 < man < 0.88
    assert all(0.15 <= p.pct_vo2max <= 0.95 for p in a)
    bmi = np.array([p.weight / p.height ** 2 for p in a])
    assert bmi.min() >= 18.0 and bmi.max() <= 40.0


def test_globale_rng_niet_geraakt():
    np.random.seed(123)
    voor = np.random.random()
    np.random.seed(123)
    hw.genereer_werkers(20, 1, 4.0, 0.8, 0.0, 0.0)
    assert np.random.random() == voor


def test_iso7243_tabel_gezondheidsraad():
    assert hw.iso7243_grens(60, True) == 33.0
    assert hw.iso7243_grens(100, False) == 29.0
    assert hw.iso7243_grens(165, True) == 28.0
    assert hw.iso7243_grens(230, False) == 22.0
    assert hw.iso7243_grens(230, False, luchtbeweging=True) == 23.0
    assert hw.iso7243_grens(300, True) == 23.0


def test_iso8996_omrekening():
    assert hw.met_uit_w_m2(165.0) == pytest.approx(165.0 / 58.2)
    assert hw.w_m2_uit_met(hw.met_uit_w_m2(230.0)) == pytest.approx(230.0)


def test_korte_werkdag_van_begin_tot_eind():
    import hestia_bridge as hb
    import hestia_loper_ui as hlu
    hb._patch_air_quality(1)
    w = hlu.WeerBron().excel(str(ROOT / "DtD2024_Amsterdam_hindcast.xlsx"), pd.Timestamp("2024-09-22 11:00"),
                             pd.Timestamp("2024-09-22 13:00"), "stad")
    inv = hw.WerkInvoer("Amsterdam", "2024-09-22", hw.WerkSchema(begin="11:00", einde="12:30", pauzes=[]),
                        4.0, "test", 0.9, 1, 1)
    r = hw.bereken(inv, w.df, w.lat, w.lon, w.tz, n=3, seed=5, tf=0.25, af=0.3, aqi=1)
    s = r["samen"]
    assert s["n"] == 3
    assert np.all(np.isfinite(s["gem"]))
    assert 36.5 < s["gem_max"] < 40.0
    assert s["geacclimatiseerd"] is False and s["grens_hoofd"] == 38.0
    assert len(s["uren"]) == 2
    ph = r["phs"]
    assert np.all(np.isfinite(ph["t_re"])) and ph["water_g"][-1] > 0
    # Zelfde werker, zelfde uitkomst (zaad uit het eigen profiel).
    args = hw.taak_args(r["interp"], w.lat, w.lon, r["profielen"][:1], r["fase"], inv, 0.25, 0.3)[0]
    a, b = hw.simuleer_werker(args), hw.simuleer_werker(args)
    assert [x["t_rect"] for x in a] == [x["t_rect"] for x in b]
    assert [x["t_rect"] for x in a] == [x["t_rect"] for x in r["sporen"][0]]
    # Rust volgt het schema: rust-MET in rust en pauze.
    for x in a[1:]:
        if x["fase"] != "werk":
            assert x["met_plan"] == pytest.approx(inv.schema.rust_met)
