# -*- coding: utf-8 -*-
"""
test_zweet_fix.py -- regressietest voor de zweetsnelheid (2026-10-09)

FOUT: calculate_indices_jos3_adult() nam de zweetsnelheid als
np.mean(dict_results()['weight_loss_by_evap_and_res']), het gemiddelde over
de HELE voorgeschiedenis in plaats van over de minuten van de huidige stap.
Bij oplopend zweten bleef het opgetelde vochtverlies daardoor 19-28 % te laag.

TOETS: zonder drinken en met zweetfactor 1 moet het opgetelde vochtverlies
van de engine gelijk zijn aan de som van JOS-3's eigen verlies per minuut.

    PYTHONPATH=. python3 test_zweet_fix.py
"""
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import hestia_model as h


def main() -> int:
    gevangen = []
    origineel = h.maak_jos3

    def vang(**kw):
        m = origineel(**kw)
        gevangen.append(m)
        return m

    h.maak_jos3 = vang
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

    model = gevangen[0]
    wl = np.asarray(model.dict_results()["weight_loss_by_evap_and_res"], dtype=float).ravel()
    verwacht = float(wl.sum() * 60.0)                # g, per minuut opgeteld
    oud = 0.0                                        # de oude rekenwijze, ter vergelijking
    for k in range(1, len(times)):
        oud += float(np.mean(wl[:k * 10])) * 60.0 * 10
    engine = float(res[-1]["water"])
    stopte = any(r.get("stopped") for r in res)
    ok1 = abs(engine - verwacht) / verwacht < 0.005
    ok2 = oud < 0.9 * verwacht
    print(f"[{'PASS' if not stopte else 'FAIL'}] scenario zonder stop")
    print(f"[{'PASS' if ok1 else 'FAIL'}] engine {engine:.0f} g = som per minuut {verwacht:.0f} g")
    print(f"[{'PASS' if ok2 else 'FAIL'}] oude rekenwijze zou {oud:.0f} g geven "
          f"({(1 - oud / verwacht) * 100:.0f} % te laag)")
    alles = ok1 and ok2 and not stopte
    print("ALLES OK" if alles else "FOUT")
    return 0 if alles else 1


if __name__ == "__main__":
    raise SystemExit(main())
