# -*- coding: utf-8 -*-
"""
test_zweet_fix.py -- regressietest voor de zweetsnelheid (2026-10-09)

FOUT: calculate_indices_jos3_adult() nam de zweetsnelheid als
np.mean(dict_results()['weight_loss_by_evap_and_res']), het gemiddelde over
de HELE voorgeschiedenis in plaats van over de minuten van de huidige stap.
Bij oplopend zweten bleef het opgetelde vochtverlies daardoor 19-28 % te laag.

TOETS: zonder drinken en met zweetfactor 1 moet het opgetelde vochtverlies
van de engine gelijk zijn aan de som van JOS-3's eigen verlies per minuut.
[2026-11-04] plus het druppelende zweet (HUTAS, jos3_leeftijd), dat de engine
per stap ophaalt; hier per aanroep van drip_take_rate geteld.

    PYTHONPATH=. python3 test_zweet_fix.py
"""
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import hestia_model as h
import jos3_leeftijd as jl


def main() -> int:
    gevangen = []
    origineel = h.maak_jos3

    def vang(**kw):
        m = origineel(**kw)
        gevangen.append(m)
        return m

    h.maak_jos3 = vang
    druppel = []                       # [2026-11-04] g dripped sweat per take
    orig_take = jl.drip_take_rate

    def tel(n_steps=1):
        druppel.append(jl._DRIP["w"] * 60.0 / jl.JOS3_LATENT_HEAT_J_G)   # W summed per 60-s step -> g
        return orig_take(n_steps)

    jl.drip_take_rate = tel
    try:
        times = pd.date_range("2026-07-15 12:00", periods=13, freq="10min")
        interp = [{"time": t, "temp": 25.0, "wind": 2.0, "rh": 50.0, "clouds": 20.0,
                   "pressure": 1013.0, "ghi": 600.0, "solar_elevation": 55.0,
                   "globe_temp": 35.0, "mrt": 38.0} for t in times]
        prof = h.AdultParticipantProfile(
            height=1.78, weight=72.0, age=35, gender="male", body_fat_pct=18.0, vo2max=50.0,
            pct_vo2max=0.65, temp_variation=0.0, rh_variation=0.0, mf_score=0.5,
            sweat_factor=1.0, thirst_threshold=99.0, kp_pacing=0.0,
            nsaid_gebruik=False, wind_angle_rad=0.0)
        met = 50.0 * 0.65 / h.VO2MAX_TO_MET_FACTOR
        res = h.calculate_indices_jos3_adult(interp, 52.0, 5.0, met, 0.2, prof, 0.5, 0.0)
    finally:
        h.maak_jos3 = origineel
        jl.drip_take_rate = orig_take

    model = gevangen[0]
    wl = np.asarray(model.dict_results()["weight_loss_by_evap_and_res"], dtype=float).ravel()
    # [2026-10-20] Since PF_JOS3 the same JOS-3 model runs on for 30 min in the
    # finish zone. res[-1]["water"] is the race total, so count the race records
    # only: 120 race minutes + 1 record, the same 121 records as before PF_JOS3.
    wl = wl[:(len(times) - 1) * 10 + 1]
    drip_g = float(sum(druppel[:len(times)]))         # race steps only, not the finish zone
    verdampt = float(wl.sum() * 60.0)
    verwacht = verdampt + drip_g                     # g, per minuut opgeteld + druppelzweet
    oud = 0.0                                        # de oude rekenwijze, ter vergelijking
    for k in range(1, len(times)):
        oud += float(np.mean(wl[:k * 10])) * 60.0 * 10
    oud += drip_g
    engine = float(res[-1]["water"])
    stopte = any(r.get("stopped") for r in res)
    ok1 = abs(engine - verwacht) / verwacht < 0.005
    ok2 = oud < 0.9 * verwacht
    print(f"[{'PASS' if not stopte else 'FAIL'}] scenario zonder stop")
    print(f"[{'PASS' if ok1 else 'FAIL'}] engine {engine:.0f} g = som per minuut {verwacht:.0f} g "
          f"(verdampt {verdampt:.0f} + gedruppeld {drip_g:.0f})")
    print(f"[{'PASS' if ok2 else 'FAIL'}] oude rekenwijze zou {oud:.0f} g geven "
          f"({(1 - oud / verwacht) * 100:.0f} % te laag)")
    alles = ok1 and ok2 and not stopte
    print("ALLES OK" if alles else "FOUT")
    return 0 if alles else 1


if __name__ == "__main__":
    raise SystemExit(main())
