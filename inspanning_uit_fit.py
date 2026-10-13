# -*- coding: utf-8 -*-
"""
inspanning_uit_fit.py -- van een fit_lezer-export naar modelinvoer en meting
============================================================================

Werkt op de Excel-export van fit_lezer.py (``<code>_<datum>.xlsx``), nooit op
het ruwe FIT-bestand: wat hier binnenkomt is al geanonimiseerd.

Levert:
  * ``Meting``             per-seconde- en per-minuutdata van een loper
  * ``met_uit_snelheid``   inspanning (MET) uit de gemeten snelheid
  * ``hoofddeel``          het langste aaneengesloten stuk lopen (>= 10 min)
  * ``kwaliteit``          de inclusie-eisen uit hoofdstuk 3 van het
                           validatieschema
  * ``vo2max_uit_loop``    VO2max uit hartslag en snelheid (hoofdstuk 5)

Inspanning uit snelheid (MODELKEUZE, vastgelegd voor de clinic):
  hardlopen  (>= 1,8 m/s)  Daniels & Gilbert:
                           VO2 = -4,60 + 0,182258 v + 0,000104 v^2  (v in m/min)
  wandelen   (0,3-1,8 m/s) ACSM-loopformule: VO2 = 0,1 v + 3,5
  stilstaan  (< 0,3 m/s)   1,5 MET (staan, praten, rustig bewegen)
  MET = VO2 / 3,5
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

LOOP_MS = 1.8
WANDEL_MS = 0.3
MET_STIL = 1.5
MIN_HOOFDDEEL_MIN = 10.0

# Eisen uit hoofdstuk 3 van het validatieschema
EIS_CORE_HR = 0.80          # CORE ontvangt hartslag >= 80% van de tijd
EIS_CORE_GOED = 0.80        # kwaliteit goed/uitstekend >= 80%
EIS_HR_AANWEZIG = 0.90      # hartslag aanwezig >= 90%
EIS_HR_SPRONG = 30.0        # geen sprongen > 30 slagen ...
EIS_HR_SPRONG_S = 5         # ... binnen 5 s
EIS_NAWARMTE_MIN = 8.0      # horloge loopt >= 8 min door na het stoppen
NAWARMTE_VENSTER_MIN = 10.0


def vo2_uit_snelheid(v_ms: float) -> float:
    """mL/kg/min bij snelheid v (m/s), zie de modelkeuze bovenaan."""
    if not np.isfinite(v_ms) or v_ms < WANDEL_MS:
        return MET_STIL * 3.5
    vm = v_ms * 60.0
    if v_ms >= LOOP_MS:
        vo2 = -4.60 + 0.182258 * vm + 0.000104 * vm ** 2
    else:
        vo2 = 0.1 * vm + 3.5
    return max(MET_STIL * 3.5, vo2)


def met_uit_snelheid(v_ms: float) -> float:
    return vo2_uit_snelheid(v_ms) / 3.5


# -----------------------------------------------------------------------------
@dataclass
class Meting:
    code: str
    datum: str
    start_lokaal: pd.Timestamp          # afgerond op 10 min door fit_lezer
    meta: dict
    per_seconde: pd.DataFrame
    delen: pd.DataFrame
    per_minuut: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def vo2max_garmin(self) -> Optional[float]:
        v = self.meta.get("vo2max_garmin_schatting")
        try:
            v = float(v)
            return v if np.isfinite(v) and v > 0 else None
        except (TypeError, ValueError):
            return None


def _per_minuut(ps: pd.DataFrame) -> pd.DataFrame:
    d = ps.copy()
    d["minuut"] = (d["t_s"] // 60).astype(int)
    g = d.groupby("minuut")
    pm = pd.DataFrame({
        "snelheid_ms": g["snelheid_ms"].mean() if "snelheid_ms" in d else np.nan,
        "hartslag": g["hartslag"].mean() if "hartslag" in d else np.nan,
        "kern_temp": g["kern_temp"].mean() if "kern_temp" in d else np.nan,
        "huid_temp": g["huid_temp"].mean() if "huid_temp" in d else np.nan,
    })
    n = g.size()
    pm["n_s"] = n
    pm["hr_aanwezig"] = (g["hartslag"].count() / n) if "hartslag" in d else 0.0
    if "core_niveau" in d:
        pm["core_goed"] = g["core_niveau"].apply(lambda s: float((s >= 3).mean()) if s.notna().any() else 0.0)
    else:
        pm["core_goed"] = 0.0
    if "core_hartslag_gebruikt" in d:
        pm["core_hr"] = g["core_hartslag_gebruikt"].apply(
            lambda s: float(s.fillna(0).astype(float).mean()))
    else:
        pm["core_hr"] = 0.0
    # hartslagsprongen: > 30 slagen binnen 5 s (op de regelmatige 1-s-reeks)
    if "hartslag" in d:
        hr = d.set_index("t_s")["hartslag"]
        hr = hr[~hr.index.duplicated()].reindex(
            np.arange(int(d["t_s"].min()), int(d["t_s"].max()) + 1))
        sprong = (hr.rolling(EIS_HR_SPRONG_S + 1, min_periods=2).max()
                  - hr.rolling(EIS_HR_SPRONG_S + 1, min_periods=2).min()) > EIS_HR_SPRONG
        pm["hr_sprong"] = sprong.groupby((sprong.index // 60).astype(int)).any().reindex(pm.index).fillna(False)
    else:
        pm["hr_sprong"] = False
    pm["met"] = [met_uit_snelheid(v) for v in pm["snelheid_ms"].fillna(0.0)]
    pm = pm.reindex(np.arange(pm.index.min(), pm.index.max() + 1))
    pm.index.name = "minuut"
    return pm


def lees_export(pad: str | Path) -> Meting:
    """Lees ``<code>_<datum>.xlsx`` van fit_lezer.py."""
    pad = Path(pad)
    with pd.ExcelFile(pad) as xl:
        meta_df = pd.read_excel(xl, "Meta")
        ps = pd.read_excel(xl, "Per_seconde")
        delen = pd.read_excel(xl, "Inspanning") if "Inspanning" in xl.sheet_names else pd.DataFrame()
    meta = dict(zip(meta_df.iloc[:, 0].astype(str), meta_df.iloc[:, 1]))
    datum = str(meta.get("datum"))[:10]
    klok = str(meta.get("starttijd_lokaal_afgerond", "00:00"))[:5]
    m = Meting(code=str(meta.get("code")), datum=datum,
               start_lokaal=pd.Timestamp(f"{datum} {klok}"), meta=meta,
               per_seconde=ps, delen=delen)
    m.per_minuut = _per_minuut(ps)
    return m


# -----------------------------------------------------------------------------
@dataclass
class Hoofddeel:
    start_min: int        # eerste hele minuut binnen het deel
    eind_min: int         # laatste hele minuut binnen het deel
    duur_min: float
    afstand_km: float
    tempo_min_km: float

    @property
    def minuten(self) -> np.ndarray:
        return np.arange(self.start_min, self.eind_min + 1)


def hoofddeel(m: Meting) -> Optional[Hoofddeel]:
    """Langste inspanningsdeel uit fit_lezer, minstens 10 minuten."""
    if m.delen is None or len(m.delen) == 0:
        return None
    d = m.delen.sort_values("duur_min", ascending=False).iloc[0]
    if float(d["duur_min"]) < MIN_HOOFDDEEL_MIN:
        return None
    s, e = float(d["start_s"]), float(d["eind_s"])
    return Hoofddeel(start_min=int(np.ceil(s / 60.0)), eind_min=int(np.floor(e / 60.0)) - 1,
                     duur_min=(e - s) / 60.0, afstand_km=float(d.get("afstand_km", np.nan)),
                     tempo_min_km=float(d.get("tempo_min_km", np.nan)))


def kwaliteit(m: Meting, hd: Optional[Hoofddeel]) -> dict:
    """Inclusie per vergelijking (hoofdstuk 3). Elke vergelijking: (ok, reden)."""
    uit = {}
    if hd is None:
        reden = f"geen aaneengesloten stuk lopen van >= {MIN_HOOFDDEEL_MIN:.0f} min"
        return {k: (False, reden) for k in ("kern", "hartslag", "nawarmte")}
    pm = m.per_minuut.loc[hd.minuten]
    core_hr, core_goed = float(pm["core_hr"].mean()), float(pm["core_goed"].mean())
    if pm["kern_temp"].notna().mean() < 0.5:
        uit["kern"] = (False, "geen CORE-kerntemperatuur in het hoofddeel")
    elif core_hr < EIS_CORE_HR:
        uit["kern"] = (False, f"CORE ontving hartslag {core_hr:.0%} van de tijd (eis >= {EIS_CORE_HR:.0%})")
    elif core_goed < EIS_CORE_GOED:
        uit["kern"] = (False, f"CORE-kwaliteit goed/uitstekend {core_goed:.0%} (eis >= {EIS_CORE_GOED:.0%})")
    else:
        uit["kern"] = (True, f"CORE-hartslag {core_hr:.0%}, goed/uitstekend {core_goed:.0%}")
    hr_aan = float((pm["hr_aanwezig"] * pm["n_s"]).sum() / max(1.0, (hd.eind_min - hd.start_min + 1) * 60.0))
    if hr_aan < EIS_HR_AANWEZIG:
        uit["hartslag"] = (False, f"hartslag aanwezig {hr_aan:.0%} (eis >= {EIS_HR_AANWEZIG:.0%})")
    elif bool(pm["hr_sprong"].any()):
        n = int(pm["hr_sprong"].sum())
        uit["hartslag"] = (False, f"hartslagsprongen > {EIS_HR_SPRONG:.0f}/min binnen {EIS_HR_SPRONG_S} s in {n} minuut/minuten")
    else:
        uit["hartslag"] = (True, f"hartslag aanwezig {hr_aan:.0%}, geen sprongen")
    na = m.per_minuut.loc[hd.eind_min + 1:]
    na_duur = float(len(na))
    if na_duur < EIS_NAWARMTE_MIN:
        uit["nawarmte"] = (False, f"horloge liep {na_duur:.0f} min door na het stoppen (eis >= {EIS_NAWARMTE_MIN:.0f})")
    else:
        v = na.iloc[:int(NAWARMTE_VENSTER_MIN)]
        if v["core_hr"].mean() < EIS_CORE_HR or v["core_goed"].mean() < EIS_CORE_GOED:
            uit["nawarmte"] = (False, "CORE-kwaliteit na het stoppen onder de eis")
        elif not uit["kern"][0]:
            uit["nawarmte"] = (False, "kerntemperatuur in het hoofddeel voldoet niet")
        else:
            uit["nawarmte"] = (True, f"{na_duur:.0f} min na het stoppen geregistreerd")
    return uit


def nawarmte_gemeten(m: Meting, hd: Hoofddeel) -> float:
    """Hoogste kerntemperatuur in de 10 min na het stoppen - waarde bij stoppen."""
    k = m.per_minuut["kern_temp"]
    bij_stop = float(k.loc[hd.eind_min])
    na = k.loc[hd.eind_min + 1: hd.eind_min + int(NAWARMTE_VENSTER_MIN)]
    return float(na.max() - bij_stop) if na.notna().any() else float("nan")


# -----------------------------------------------------------------------------
@dataclass
class VO2maxSchatting:
    vo2max: float
    venster: tuple            # (eerste, laatste minuut)
    snelheid_ms: float
    vo2_bij_snelheid: float
    hartslag: float
    hr_rust: float
    hr_rust_bron: str
    hr_max: float
    hr_max_bron: str
    pct_hrr: float
    snelheid_cv: float
    opmerking: str = ""


def vo2max_uit_loop(m: Meting, hd: Hoofddeel, leeftijd: float,
                    hr_max: Optional[float] = None, hr_rust: Optional[float] = None,
                    venster=(5, 15)) -> Optional[VO2maxSchatting]:
    """VO2max uit hartslag en snelheid in minuut 5-15 van het hoofddeel
    (eerste stabiele stuk, voordat de hartslag gaat oplopen; de eerste 5
    minuten loopt de hartslag nog in). %HRR ~ %VO2-reserve (Swain 1994):
        VO2max = 3,5 + (VO2 - 3,5) / %HRR
    HRmax: gemeten of Tanaka (208 - 0,7 x leeftijd). Rusthartslag: gemeten of
    de laagste 2-minuutwaarde voor het hoofddeel (staan, dus hoger dan echte
    rust: dat maakt de schatting eerder te hoog)."""
    lo = hd.start_min + venster[0]
    hi = min(hd.start_min + venster[1] - 1, hd.eind_min)
    opm = ""
    if hi - lo + 1 < 5:
        lo, hi = hd.start_min + 2, hd.eind_min
        opm = "hoofddeel kort; venster vanaf minuut 2"
        if hi - lo + 1 < 5:
            return None
    pm = m.per_minuut.loc[lo:hi]
    v = float(pm["snelheid_ms"].mean())
    hr = float(pm["hartslag"].mean())
    cv = float(pm["snelheid_ms"].std() / v) if v > 0 else float("nan")
    if hr_max:
        hmax, hbron = float(hr_max), "gemeten"
    else:
        hmax, hbron = 208.0 - 0.7 * leeftijd, "Tanaka (208 - 0,7 x leeftijd)"
    if hr_rust:
        hrust, rbron = float(hr_rust), "gemeten"
    else:
        voor = m.per_minuut.loc[:hd.start_min - 1, "hartslag"].dropna()
        if len(voor) >= 2:
            hrust = float(voor.rolling(2).mean().min())
            rbron = "laagste 2-minuutwaarde voor het hoofddeel"
        else:
            hrust, rbron = 60.0, "aangenomen 60/min (geen data voor de start)"
    vo2 = vo2_uit_snelheid(v)
    pct = (hr - hrust) / (hmax - hrust) if hmax > hrust else float("nan")
    if not (np.isfinite(pct) and 0.2 < pct < 1.0):
        return VO2maxSchatting(float("nan"), (lo, hi), v, vo2, hr, hrust, rbron, hmax, hbron,
                               pct, cv, "hartslagreserve buiten 20-100%: geen schatting")
    if cv > 0.10:
        opm = (opm + "; " if opm else "") + f"snelheid wisselend (CV {cv:.0%})"
    return VO2maxSchatting(3.5 + (vo2 - 3.5) / pct, (lo, hi), v, vo2, hr, hrust, rbron,
                           hmax, hbron, pct, cv, opm)
