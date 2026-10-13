# -*- coding: utf-8 -*-
"""
dynamiek.py -- systeemidentificatie van de kerntemperatuur (verkennend)
=======================================================================

Invoer u(t): inspanning in MET per minuut, uit de gemeten snelheid (gelijk
voor model en meting). Uitvoer y(t): kerntemperatuur (model of CORE).

Per signaal wordt een eerste-orde systeem met dode tijd gefit:

    y(t) = y0 + K * x(t),   tau * dx/dt = (u(t - L) - 1,5) - x(t)

  K     statische versterking (C per MET boven 1,5 MET): de eindwaarde
  L     dode tijd (hele minuten, 0-10)
  tau   dominante tijdconstante (min)

Waarom: bias en RMSE per minuut mengen niveau en timing. K zegt of het model
de juiste eindtemperatuur bereikt; L en tau zeggen hoe snel. Een CORE die
trager reageert dan het model (L01: tau 28 tegen 19 min) geeft bij een gelijke
K toch een grote RMSE. Model en CORE worden zo apart vergeleken op niveau en
op dynamica.

Daarnaast:
  * tau apart voor stijgen en dalen (K en L vast uit de totale fit); bij een
    lineair systeem zijn die gelijk, verschil wijst op niet-lineair gedrag;
  * het maximum in het hoofddeel + 20 min (ongevoelig voor timing);
  * 'hartslag ontkoppeld': minuten waarin de inspanning >= 20% onder het
    gemiddelde van het hoofddeel zakt, terwijl de hartslag >= 95% blijft.
    De CORE gebruikt de hartslag in zijn rekenregel; in die minuten is de
    CORE minder onafhankelijk van de hartslag.

Alles hier is VERKENNEND: wel berekend en gerapporteerd, geen oordeel.
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

MET_BASIS = 1.5
MAX_DODE_TIJD = 10
VOOR_MIN = 15          # identificatievenster begint 15 min voor het hoofddeel
NA_MIN = 40            # en loopt tot 40 min erna (of het einde van de registratie)
PIEK_NA_MIN = 20       # maximum gezocht in hoofddeel + 20 min


def simuleer(u: np.ndarray, y0: float, K: float, L: int, tau: float) -> np.ndarray:
    v = np.asarray(u, dtype=float) - MET_BASIS
    if L > 0:
        v = np.concatenate([np.full(L, v[0]), v[:len(v) - L]])
    a = 1.0 - np.exp(-1.0 / max(tau, 0.05))
    x = np.zeros_like(v)
    for i in range(1, len(v)):
        x[i] = x[i - 1] + a * (v[i] - x[i - 1])
    return y0 + K * x


GRENZEN_TEMP = ([25.0, 0.0, 0.5], [42.0, 2.0, 200.0])      # y0, K, tau
GRENZEN_HR = ([30.0, 0.0, 0.2], [220.0, 40.0, 60.0])


def _fit(u, y, masker, L, p0, grenzen=GRENZEN_TEMP):
    def f(p):
        return simuleer(u, p[0], p[1], L, p[2])[masker] - y[masker]
    r = least_squares(f, p0, bounds=grenzen)
    return r.x, float(np.sqrt(np.mean(r.fun ** 2)))


def identificeer(u: np.ndarray, y: np.ndarray, masker: np.ndarray, grenzen=GRENZEN_TEMP) -> dict:
    """Eerste-orde + dode tijd. masker = minuten die meetellen."""
    y = np.asarray(y, dtype=float)
    m = masker & np.isfinite(y)
    if m.sum() < 20:
        return {"K": np.nan, "dode_tijd": np.nan, "tau": np.nan, "y0": np.nan, "rmse": np.nan}
    beste = None
    for L in range(0, MAX_DODE_TIJD + 1):
        p0 = [float(y[m][0]), 0.25, 15.0] if grenzen is GRENZEN_TEMP else [float(y[m][0]), 8.0, 3.0]
        p, rm = _fit(u, y, m, L, p0, grenzen)
        if beste is None or rm < beste[0]:
            beste = (rm, L, p)
    rm, L, p = beste
    return {"K": float(p[1]), "dode_tijd": int(L), "tau": float(p[2]), "y0": float(p[0]), "rmse": rm}


def tau_segment(u, y, masker_seg, ident: dict) -> float:
    """tau (en K) opnieuw fitten op een deel; y0 en L vast."""
    y = np.asarray(y, dtype=float)
    m = masker_seg & np.isfinite(y)
    if m.sum() < 8 or not np.isfinite(ident["tau"]):
        return float("nan")

    def f(q):
        return simuleer(u, ident["y0"], q[1], ident["dode_tijd"], q[0])[m] - y[m]
    r = least_squares(f, [ident["tau"], ident["K"]], bounds=([0.5, 0.0], [200.0, 2.0]))
    return float(r.x[0])


def analyse(u: np.ndarray, y: np.ndarray, start: int, eind: int) -> dict:
    """Volledige verkennende analyse van een signaal rond het hoofddeel
    (minuten start..eind, indices in u en y)."""
    n = len(u)
    t = np.arange(n)
    venster = (t >= max(0, start - VOOR_MIN)) & (t <= min(n - 1, eind + NA_MIN))
    idf = identificeer(u, y, venster)
    stijg = (t >= max(0, start - 3)) & (t <= eind)
    daal = (t > eind) & (t <= min(n - 1, eind + NA_MIN))
    y = np.asarray(y, dtype=float)
    pv = (t >= start) & (t <= min(n - 1, eind + PIEK_NA_MIN)) & np.isfinite(y)
    piek = float(np.max(y[pv])) if pv.any() else float("nan")
    piek_t = int(t[pv][np.argmax(y[pv])]) if pv.any() else -1
    return {**idf, "tau_stijgen": tau_segment(u, y, stijg, idf),
            "tau_dalen": tau_segment(u, y, daal, idf), "piek": piek, "piek_minuut": piek_t}


def hartslag_ontkoppeld(met: np.ndarray, hr: np.ndarray, start: int, eind: int) -> float:
    """% van de minuten in hoofddeel + 20 min waarin de inspanning >= 20%
    onder het gemiddelde van het hoofddeel ligt terwijl de hartslag >= 95%
    van het gemiddelde van het hoofddeel blijft."""
    met = np.asarray(met, dtype=float)
    hr = np.asarray(hr, dtype=float)
    hd = slice(start, eind + 1)
    m_ref, h_ref = np.nanmean(met[hd]), np.nanmean(hr[hd])
    w = slice(start, min(len(met), eind + 1 + PIEK_NA_MIN))
    mm, hh = met[w], hr[w]
    ok = np.isfinite(mm) & np.isfinite(hh)
    if not ok.any():
        return float("nan")
    los = (mm[ok] <= 0.8 * m_ref) & (hh[ok] >= 0.95 * h_ref)
    return float(np.mean(los) * 100.0)


def hartslag_dynamiek(u: np.ndarray, hr: np.ndarray, start: int, eind: int,
                      hr_model: np.ndarray | None = None) -> dict:
    """Hartslag als uitvoer, inspanning als invoer (zelfde eerste-orde-vorm).

    De hartslag komt van de borstband, zonder rekenregel: de tijdconstante is
    fysiologisch. Daarnaast 'hr_na_extra': de gemiddelde gemeten hartslag
    boven de eigen fit in de 20 minuten na het hoofddeel (blijvende belasting
    bovenop de traagheid). Met hr_model: 'hr_na_model_verschil' = gemeten min
    model na het hoofddeel, gecorrigeerd voor het verschil in de 30 minuten
    voor de start (verschuiving in de rusthartslag)."""
    n = len(u)
    t = np.arange(n)
    hr = np.asarray(hr, dtype=float)
    venster = (t >= max(0, start - VOOR_MIN)) & (t <= min(n - 1, eind + NA_MIN))
    idf = identificeer(u, hr, venster, GRENZEN_HR)
    uit = {f"hr_{k}": v for k, v in idf.items()}
    na = (t > eind) & (t <= min(n - 1, eind + PIEK_NA_MIN)) & np.isfinite(hr)
    if np.isfinite(idf["tau"]) and na.any():
        fit = simuleer(u, idf["y0"], idf["K"], idf["dode_tijd"], idf["tau"])
        uit["hr_na_extra"] = float(np.mean(hr[na] - fit[na]))
    else:
        uit["hr_na_extra"] = float("nan")
    if hr_model is not None:
        hm = np.asarray(hr_model, dtype=float)
        voor = (t >= max(0, start - 35)) & (t < start - 5) & np.isfinite(hr) & np.isfinite(hm)
        nm = na & np.isfinite(hm)
        if voor.any() and nm.any():
            verschuiving = float(np.mean(hr[voor] - hm[voor]))
            uit["hr_rust_verschuiving"] = verschuiving
            uit["hr_na_model_verschil"] = float(np.mean(hr[nm] - hm[nm])) - verschuiving
        mm = venster & np.isfinite(hm)
        idm = identificeer(u, np.where(mm, hm, np.nan), venster, GRENZEN_HR)
        uit["hr_tau_model"] = idm["tau"]
        uit["hr_K_model"] = idm["K"]
    return uit

