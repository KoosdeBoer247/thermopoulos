# -*- coding: utf-8 -*-
"""
hestia_reconstructie.py -- modus B: reconstructie met de gemeten inspanning
===========================================================================

Het model krijgt per minuut de GEMETEN snelheid in plaats van een gepland
tempo met pacingwet. Verschillen tussen model en meting komen dan uit JOS-3
en de CVR-module, niet uit een verkeerde tempo-inschatting.

Wat anders is dan de populatie- en loperberekening (hestia_model):
  * stappen van 1 minuut, vanaf het begin van de FIT-registratie;
  * inspanning (MET) uit de gemeten snelheid (inspanning_uit_fit);
  * eigen rugwind uit de gemeten snelheid, niet terugberekend uit MET;
  * geen pacingwet, geen stop bij RPE >= 19,5 (de loper liep echt door);
  * drinken: de opgegeven hoeveelheid, gelijk verdeeld over de registratie,
    in plaats van het gesimuleerde dorstgedrag;
  * zweetverlies per minuut uit de laatste JOS-3-stap.
De populatie- en loperberekening zelf worden NIET aangeraakt: deze module
gebruikt alleen maak_jos3, wind_speed_at_height en de CVR-module.

Drie varianten, vooraf vastgelegd (zie het validatieschema):
  B1  zoals de suite nu rekent: JOS-3 par = MET; T_rect = gemiddelde van de
      17 kernsegmenten + 0,5 C
  B2  JOS-3 par = MET x 58,2 / BMR (JOS-3 verwacht een veelvoud van de
      eigen rustverbranding, niet van 1 MET); T_rect als B1
  B3  par als B2; T_rect = JOS-3-bekkenkern (segment 4), zonder correctie
  B4  [2026-10-27, verkennend] als B3, met het koude-huidsignaal van JOS-3
      begrensd op 2 K (jos3_leeftijd.COLD_SKIN_LIMIT_K); achteraf toegevoegd
De CVR-module krijgt in alle varianten de echte MET (Lloyd 2022 rekent in MET).

Onzekerheid (ensemble, per variant dezelfde trekkingen):
  luchttemperatuur  + N(0; 1,0) C       (stationsweer vs. de plek zelf)
  luchtvochtigheid  + N(0; 5) %-punt
  straling          tr = tdb + f x (MRT - tdb), f ~ U(0, 1)  (schaduw..zon)
  windrichting      hoek ~ U(0, 2 pi) t.o.v. de looprichting
  kleding in rust   + U(0; 0,3) clo in minuten met MET < 2 (jas aan voor de start)
  zweetfactor       N(0,8; 0,15), geknipt op [0,4; 1,5]  [2026-11-01: hitte-
                    gewenning zit nu in JOS-3 zelf, +20 % zweetsignaal]
                    (zelfde verdeling als hestia_model, alleen voor het vochtverlies)
De centrale run: geen afwijkingen, f = 1 (MRT van de Data Engine, zoals de
suite), hoek 90 graden, zweetfactor = het midden.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from hestia_model import maak_jos3, wind_speed_at_height
from HESTIA_CVR_Module_v2 import CVRModel, JOS3Outputs, RunnerProfile

MET_W_M2 = 58.2
SEG_BORST = 2
SEG_BEKKEN = 4

VARIANTEN = {
    "B1": {"par": "met", "t_rect": "gem17", "label": "B1 zoals nu (par = MET, gem. 17 seg. + 0,5)"},
    "B2": {"par": "omgerekend", "t_rect": "gem17", "label": "B2 omgerekend, gem. 17 seg. + 0,5"},
    "B3": {"par": "omgerekend", "t_rect": "bekken", "label": "B3 omgerekend, bekkenkern"},
    # [2026-10-27] B4 = B3 met begrensd koude-huidsignaal (jos3_leeftijd.
    # COLD_SKIN_LIMIT_K); verkennend, achteraf toegevoegd, niet vooraf vastgelegd.
    "B4": {"par": "omgerekend", "t_rect": "bekken", "koude_huid_k": 2.0,
           "label": "B4 als B3, koude-huidsignaal begrensd (2 K)"},
}

KLEDING_CLO = {"licht": 0.2, "normaal": 0.3, "lang": 0.5}


@dataclass
class Persoon:
    geslacht: str                 # 'man' | 'vrouw'
    leeftijd: float
    lengte_cm: float
    gewicht_kg: float
    clo: float
    hitte_gewend: bool = False
    drank_ml: float = 0.0
    hr_max: Optional[float] = None
    hr_rust: Optional[float] = None

    @property
    def sex(self) -> str:
        return "male" if self.geslacht == "man" else "female"


@dataclass
class Trekking:
    dT: float = 0.0
    dRH: float = 0.0
    f_mrt: float = 1.0
    hoek: float = math.pi / 2
    clo_rust_extra: float = 0.0
    zweetfactor: float = 0.8


def weer_per_minuut(weer: pd.DataFrame, start: pd.Timestamp, n_min: int) -> pd.DataFrame:
    """Uurweer (Data Engine) lineair naar minuten vanaf ``start`` (lokale tijd)."""
    weer = weer.copy()
    if getattr(weer.index, "tz", None) is not None:
        weer.index = weer.index.tz_localize(None)
    weer = weer.sort_index().loc[start - pd.Timedelta(hours=1):
                                 start + pd.Timedelta(minutes=n_min) + pd.Timedelta(hours=1)]
    idx = weer.index
    x = (idx - start).total_seconds().to_numpy() / 60.0
    t = np.arange(n_min, dtype=float)
    if t[-1] > x.max() or t[0] < x.min():
        raise ValueError("Het weerbestand dekt de registratie niet volledig.")

    def ip(col, fallback=None):
        if col not in weer.columns:
            return None if fallback is None else ip(fallback)
        s = weer[col].astype(float).to_numpy()
        if np.isnan(s).any():
            raise ValueError(f"Weerkolom {col} bevat lege waarden in dit venster.")
        return np.interp(t, x, s)

    T = ip("T_air_urban", "T_air_rural")
    mrt = ip("MRT")
    w10 = ip("wind_10m")
    return pd.DataFrame({
        "T": T, "RH": ip("RH"),
        "MRT": mrt if mrt is not None else T,
        "wind_1_5m": np.array([wind_speed_at_height(w, 10, 1.5) for w in w10]),
    })


def _relatieve_wind(v_omg: float, v_loop: float, hoek: float) -> float:
    # cosinusregel, zelfde vorm als hestia_model.compute_relative_wind
    return math.sqrt(max(0.0, v_omg ** 2 + v_loop ** 2 + 2 * v_omg * v_loop * math.cos(hoek)))


def _veld(h, naam: str, standaard: float = float("nan")) -> float:
    """Waarde van de laatste JOS-3-stap, voor pythermalcomfort 3.x (dict) en
    4.x (dataclass met JOS3BodyParts). Lichaamsdelen worden opgeteld."""
    v = h.get(naam, None) if isinstance(h, dict) else getattr(h, naam, None)
    if v is None:
        return standaard
    if hasattr(v, "get_attribute_names"):
        return float(sum(float(getattr(v, a)) for a in v.get_attribute_names()))
    return float(np.sum(np.asarray(v, dtype=float)))


def _jos3_run(p: Persoon, met: np.ndarray, v_loop: np.ndarray, w: pd.DataFrame,
              variant: str, tr: Trekking) -> tuple[pd.DataFrame, list]:
    cfg = VARIANTEN[variant]
    m = maak_jos3(height=p.lengte_cm / 100.0, weight=p.gewicht_kg, age=int(round(p.leeftijd)),
                  sex=p.sex)
    bmr = float(m.bmr)                         # W/m2
    n = len(met)
    drank_per_min_g = (p.drank_ml or 0.0) / n
    rijen, snaps = [], []
    zweet_cum = 0.0                            # g, na zweetfactor
    netto_cum = 0.0                            # g, zweet - drinken (voor de CVR)
    for i in range(n):
        par = max(1.0, float(met[i] if cfg["par"] == "met" else met[i] * MET_W_M2 / bmr))
        T = float(w["T"].iat[i] + tr.dT)
        t_r = float(T + tr.f_mrt * (w["MRT"].iat[i] - w["T"].iat[i]))
        rh = float(np.clip(w["RH"].iat[i] + tr.dRH, 10, 95))
        v_lucht = max(0.1, _relatieve_wind(float(w["wind_1_5m"].iat[i]), float(v_loop[i]), tr.hoek))
        clo = p.clo + (tr.clo_rust_extra if met[i] < 2.0 else 0.0)
        m.par, m.tdb, m.tr, m.rh, m.v, m.clo = par, T, t_r, rh, v_lucht, clo
        m.simulate(times=1, dtime=60)
        h = m._history[-1]
        tc = np.asarray(m.t_core, dtype=float)
        ts = np.asarray(m.t_skin, dtype=float)
        g_per_s = _veld(h, "weight_loss_by_evap_and_res")
        zweet = g_per_s * 60.0 * tr.zweetfactor
        zweet_cum += zweet
        netto_cum = max(0.0, netto_cum + zweet - drank_per_min_g)
        gem17 = float(tc.mean()) + 0.5
        bekken = float(tc[SEG_BEKKEN])
        rijen.append({
            "minuut": i, "met": float(met[i]), "par": par, "v_lucht": v_lucht,
            "tdb": T, "tr": t_r, "clo": clo,
            "t_rect": bekken if cfg["t_rect"] == "bekken" else gem17,
            "t_bekken": bekken, "t_gem17_05": gem17,
            "huid_borst": float(ts[SEG_BORST]), "huid_gem": float(m.t_skin_mean),
            "zweet_g_cum": zweet_cum,
        })
        snaps.append(JOS3Outputs(
            t_min=i, cardiac_output=_veld(h, "cardiac_output"), t_core_mean=float(tc.mean()),
            t_cb=_veld(h, "t_cb", float(tc.mean())), weight_loss_g_s=netto_cum / 1000.0,
            bf_skin_total=_veld(h, "bf_skin"), bf_ava_hand=_veld(h, "bf_ava_hand", 0.5),
            bf_ava_foot=_veld(h, "bf_ava_foot", 0.5),
            current_met=float(met[i]), t_skin_mean=float(m.t_skin_mean)))
    df = pd.DataFrame(rijen).set_index("minuut")
    df["vocht_pct_cum"] = df["zweet_g_cum"] / 1000.0 / p.gewicht_kg * 100.0
    df.attrs["bmr_w_m2"] = bmr
    return df, snaps


def hartslag(p: Persoon, snaps: list, vo2max: float) -> pd.DataFrame:
    """CVR-module over een vastgelegde JOS-3-reeks, voor een gegeven VO2max."""
    prof = RunnerProfile(mass=p.gewicht_kg, height=p.lengte_cm, age=p.leeftijd, sex=p.sex,
                         vo2max=float(vo2max), hr_max=p.hr_max, hr_rest=p.hr_rust,
                         acclimatisation=1.0 if p.hitte_gewend else 0.0)   # [2026-11-01]
    cvr = CVRModel(prof)
    uit = []
    for s in snaps:
        st = cvr.compute_step(s)
        uit.append({"minuut": s.t_min, "hr": float(st.HR), "co_reserve": float(st.CO_reserve)})
    return pd.DataFrame(uit).set_index("minuut")


@dataclass
class Reconstructie:
    variant: str
    centraal: pd.DataFrame                    # per minuut, centrale run
    band: pd.DataFrame                        # per minuut: t_rect p2.5/p50/p97.5, vocht ...
    hr: dict                                  # bron -> DataFrame(hr, co_reserve)
    vocht_pct_runs: np.ndarray                # eind-vochtverlies per ensemble-run
    trekkingen: list = field(default_factory=list)


def trekkingen(n: int, seed: int, hitte_gewend: bool) -> list[Trekking]:
    rng = np.random.default_rng(seed)
    loc = 0.8   # [2026-11-01] hittegewenning nu in JOS-3 (jos3_leeftijd.ACCLIM_SWEAT_GAIN)
    return [Trekking(dT=float(rng.normal(0, 1.0)), dRH=float(rng.normal(0, 5.0)),
                     f_mrt=float(rng.uniform(0, 1)), hoek=float(rng.uniform(0, 2 * math.pi)),
                     clo_rust_extra=float(rng.uniform(0, 0.3)),
                     zweetfactor=float(np.clip(rng.normal(loc, 0.15), 0.4, 1.5)))
            for _ in range(n)]


def _maak_band(T: np.ndarray, H: np.ndarray, index) -> pd.DataFrame:
    return pd.DataFrame({
        "t_rect_lo": np.percentile(T, 2.5, axis=0), "t_rect_med": np.percentile(T, 50, axis=0),
        "t_rect_hi": np.percentile(T, 97.5, axis=0),
        "huid_borst_lo": np.percentile(H, 2.5, axis=0), "huid_borst_hi": np.percentile(H, 97.5, axis=0),
    }, index=index)


def reconstrueer_varianten(p: Persoon, minuten: pd.DataFrame, weer: pd.DataFrame,
                           start: pd.Timestamp, varianten, vo2max: dict, n_ensemble: int = 50,
                           seed: int = 42, progress=None) -> dict:
    """Alle gevraagde varianten. Varianten met dezelfde par-keuze (B2, B3)
    delen dezelfde JOS-3-runs; alleen de definitie van T_rect verschilt.

    minuten : DataFrame per minuut (index 0..n-1) met 'snelheid_ms' en 'met'
    weer    : uurweer van de Data Engine (index = lokale tijd)
    vo2max  : {'populatie': x, 'garmin': y | None, 'hestia': z | None}
    """
    met = minuten["met"].to_numpy(dtype=float)
    v = minuten["snelheid_ms"].fillna(0.0).to_numpy(dtype=float)
    w = weer_per_minuut(weer, start, len(met))
    trk = trekkingen(n_ensemble, seed, p.hitte_gewend)
    centr = Trekking(zweetfactor=0.8)
    # [2026-10-23] age decrement scaled by fitness and heat acclimatisation
    # (jos3_leeftijd.set_person). Fitness: the HESTIA estimate from heart rate
    # and speed, else Garmin, else the population mean (= factor 0 by definition).
    import jos3_leeftijd as _jl
    _vo2 = vo2max.get("hestia") or vo2max.get("garmin") or vo2max.get("populatie")
    _jl.set_person(_vo2, p.leeftijd, p.sex, 1.0 if p.hitte_gewend else 0.0)
    uit = {}
    groepen = {}
    for var in varianten:
        sleutel = (VARIANTEN[var]["par"], VARIANTEN[var].get("koude_huid_k"))
        groepen.setdefault(sleutel, []).append(var)
    vorige_grens = _jl.cold_skin_limit()
    for (par_modus, koude), vs in groepen.items():
        basis = vs[0]
        # B4: koude-huidgrens alleen tijdens deze runs; daarna de oude instelling terug
        _jl.set_cold_skin_limit(koude if koude is not None else vorige_grens)
        try:
            df, snaps = _jos3_run(p, met, v, w, basis, centr)
            hr = {bron: hartslag(p, snaps, x) for bron, x in vo2max.items() if x}
            runs = []
            for k, tr in enumerate(trk):
                d, _ = _jos3_run(p, met, v, w, basis, tr)
                runs.append(d)
                if progress:
                    progress((k + 1) / n_ensemble, f"{par_modus}: run {k + 1}/{n_ensemble}")
        finally:
            _jl.set_cold_skin_limit(vorige_grens)
        H = np.array([d["huid_borst"].to_numpy() for d in runs])
        vocht = np.array([float(d["vocht_pct_cum"].iat[-1]) for d in runs])
        for var in vs:
            kol = "t_bekken" if VARIANTEN[var]["t_rect"] == "bekken" else "t_gem17_05"
            c = df.copy()
            c["t_rect"] = c[kol]
            c.attrs.update(df.attrs)
            T = np.array([d[kol].to_numpy() for d in runs])
            uit[var] = Reconstructie(variant=var, centraal=c, band=_maak_band(T, H, df.index),
                                     hr=hr, vocht_pct_runs=vocht, trekkingen=trk)
    return uit


def reconstrueer(p: Persoon, minuten: pd.DataFrame, weer: pd.DataFrame, start: pd.Timestamp,
                 variant: str, vo2max: dict, n_ensemble: int = 50, seed: int = 42,
                 progress=None) -> Reconstructie:
    """Een variant (zie reconstrueer_varianten)."""
    return reconstrueer_varianten(p, minuten, weer, start, [variant], vo2max, n_ensemble,
                                  seed, progress)[variant]
