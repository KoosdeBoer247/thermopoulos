# -*- coding: utf-8 -*-
"""
clinic_validatie.py -- HESTIA tegen echte lopers (Thermo Clinic)
================================================================

Volgorde (afgedwongen, zodat de voorspelling echt vooraf is):

  1. python clinic_validatie.py sjabloon  <map>   leeg deelnemers.xlsx voor de clinic-organisatie
  2. python clinic_validatie.py voorspel  <map>   modus A: alleen deelnemers.xlsx
                                                  + weer; legt de voorspelling
                                                  vast met tijdstempel en
                                                  vingerafdruk van de suite
  3. python clinic_validatie.py fit       <map>   FIT-bestanden -> fit_uitvoer/
                                                  (via fit_lezer, met codes)
  4. python clinic_validatie.py vergelijk <map>   modus B + vergelijking +
                                                  Excel + figuren + Word-rapport
                                                  (weigert zonder stap 2)

Zonder argumenten (Spyder, F5) verschijnt een menu.

Mapindeling:
  <map>/deelnemers.xlsx
  <map>/fit_uitvoer/<code>_<datum>.xlsx     (uitvoer van fit_lezer)
  <map>/modus_A/                            (voorspelling + vastlegging.json)
  <map>/validatie_uitvoer/                  (vergelijking)

De meting gaat alleen de vergelijking in, nooit terug het model in.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import clinic_invoer as ci
import dynamiek as dyn
import inspanning_uit_fit as iuf
import hestia_reconstructie as hr_

SUITE_MAP = Path(__file__).resolve().parent
CRITERIA_PAD = SUITE_MAP / "criteria.json"
VINGERAFDRUK_BESTANDEN = [
    "hestia_model.py", "individual_engine.py", "hestia_bridge.py", "HESTIA_CVR_Module_v2.py",
    "hestia_loper.py", "clinic_invoer.py", "inspanning_uit_fit.py", "hestia_reconstructie.py",
    "clinic_validatie.py", "dynamiek.py", "criteria.json",
]
N_ENSEMBLE_A = 200
N_ENSEMBLE_B = 50
SEED = 42
PF_STAP_MIN = 0.5            # hestia_model.PF_DT_MIN
NAWARMTE_MIN = 10.0


# =============================================================================
# Hulpfuncties
# =============================================================================
def _sha(pad: Path) -> str:
    h = hashlib.sha256()
    with open(pad, "rb") as f:
        for blok in iter(lambda: f.read(1 << 16), b""):
            h.update(blok)
    return h.hexdigest()


def vingerafdruk() -> dict:
    return {n: _sha(SUITE_MAP / n)[:16] for n in VINGERAFDRUK_BESTANDEN if (SUITE_MAP / n).exists()}


def laad_criteria(pad: Path = CRITERIA_PAD) -> dict:
    return json.loads(Path(pad).read_text(encoding="utf-8"))


def oordeel(waarde: float, c: dict) -> str:
    if waarde is None or not np.isfinite(waarde):
        return "geen data"
    if c.get("goed") is None:
        return "geen grens"
    t = c["toets"]
    if t in ("abs_max", "abs_max_per_loper"):
        x = abs(waarde)
        return "goed" if x <= c["goed"] else "acceptabel" if x <= c["acceptabel"] else "onvoldoende"
    if t == "max":
        return "goed" if waarde <= c["goed"] else "acceptabel" if waarde <= c["acceptabel"] else "onvoldoende"
    if t == "min":
        return "goed" if waarde >= c["goed"] else "acceptabel" if waarde >= c["acceptabel"] else "onvoldoende"
    raise ValueError(t)


def _helling_per_10min(y: np.ndarray) -> float:
    y = np.asarray(y, dtype=float)
    x = np.arange(len(y), dtype=float)
    ok = np.isfinite(y)
    if ok.sum() < 5:
        return float("nan")
    return float(np.polyfit(x[ok], y[ok], 1)[0] * 10.0)


def _print(msg: str):
    print(msg, flush=True)


# =============================================================================
# Stap 1 - sjabloon
# =============================================================================
def sjabloon(map_: Path) -> Path:
    map_.mkdir(parents=True, exist_ok=True)
    pad = map_ / "deelnemers.xlsx"
    if pad.exists():
        raise FileExistsError(f"{pad} bestaat al; niet overschreven.")
    return ci.maak_sjabloon(pad)


# =============================================================================
# Stap 2 - voorspellen (modus A)
# =============================================================================
def _modus_a_maten(r) -> dict:
    """Per loper: banden over de tijd + maten voor de vergelijking."""
    from hestia_loper import _eindig
    a = r.assessment
    gewicht = r.invoer.gewicht_kg
    runs = []
    for res in a.all_traces:
        t = np.array([_eindig(x.get("t_rect")) for x in res])
        pf = [_eindig(x) for x in (res[-1].get("t_rect_series_postfinish") or [])]
        n10 = int(round(NAWARMTE_MIN / PF_STAP_MIN))
        naw = (float(np.nanmax(pf[:n10])) - t[-1]) if pf else float("nan")
        runs.append({"t_start": t[0], "t_eind": t[-1], "opwarming": t[-1] - t[0], "nawarmte": naw})
    d = pd.DataFrame(runs)
    s = r.samenvatting()
    return {
        "n": int(len(d)),
        "t_eind_med": float(d.t_eind.median()), "t_eind_lo": float(d.t_eind.quantile(.025)),
        "t_eind_hi": float(d.t_eind.quantile(.975)),
        "opwarming_med": float(d.opwarming.median()),
        "nawarmte_med": float(d.nawarmte.median()),
        "nawarmte_lo": float(d.nawarmte.quantile(.025)), "nawarmte_hi": float(d.nawarmte.quantile(.975)),
        "hr_piek_med": s["hr_piek"]["med"],
        "uitdroging_netto_med": s["dehyd"]["med"],
        "finish_med_min": s["finish"]["med"],
        "vo2max": r.afgeleid.vo2max, "vo2max_bron": r.afgeleid.vo2max_bron,
        "pct_vo2max": r.afgeleid.pct_vo2max, "pct_geklemd": r.afgeleid.pct_geklemd,
        "weer_blad": r.weer_sheet,
    }


def voorspel(map_: Path, n: int = N_ENSEMBLE_A, seed: int = SEED, codes=None) -> Path:
    from hestia_loper import analyseer_loper, exporteer_excel
    map_ = Path(map_)
    dpad = map_ / "deelnemers.xlsx"
    clinic, deelnemers, meldingen = ci.lees_deelnemers(dpad)
    uit = map_ / "modus_A"
    vast = uit / "vastlegging.json"
    if vast.exists():
        raise FileExistsError(
            f"{vast} bestaat al. Een vastgelegde voorspelling wordt niet overschreven; "
            f"verwijder de map modus_A zelf als je bewust opnieuw wilt voorspellen.")
    fit_map = map_ / "fit_uitvoer"
    if fit_map.exists() and any(fit_map.glob("*.xlsx")):
        _print("LET OP: fit_uitvoer bevat al bestanden. De voorspelling wordt vastgelegd, "
               "maar het rapport meldt dat de FIT-data er eerder waren.")
    uit.mkdir(parents=True, exist_ok=True)
    for m in meldingen:
        _print("  let op: " + m)
    resultaten, fouten = {}, {}
    for d in deelnemers:
        if codes and d.code not in codes:
            continue
        _print(f"Modus A: {d.code} ...")
        t0 = time.time()
        try:
            inv = ci.naar_loperinvoer(d, clinic)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = analyseer_loper(inv, n_ensemble=n, seed=seed, gevoeligheid=False)
            exporteer_excel(r, uit / f"{d.code}_modusA.xlsx")
            resultaten[d.code] = _modus_a_maten(r)
            resultaten[d.code]["waarschuwingen"] = r.afgeleid.waarschuwingen
            bt = r.banden["t_rect"]
            bh = r.banden["hr"]
            pd.DataFrame({"minuut": bt["minuten"], "t_rect_med": bt["med"], "t_rect_lo": bt["lo"],
                          "t_rect_hi": bt["hi"], "hr_med": bh["med"][:len(bt["minuten"])],
                          "hr_lo": bh["lo"][:len(bt["minuten"])], "hr_hi": bh["hi"][:len(bt["minuten"])]}
                         ).to_csv(uit / f"{d.code}_modusA_band.csv", index=False)
            _print(f"   klaar in {time.time() - t0:.0f} s")
        except Exception as e:                       # loper overslaan, wel vastleggen
            fouten[d.code] = f"{type(e).__name__}: {e}"
            _print(f"   ! {d.code}: {fouten[d.code]}")
    vastlegging = {
        "aangemaakt": datetime.now().isoformat(timespec="seconds"),
        "deelnemers_sha256": _sha(dpad),
        "suite_vingerafdruk": vingerafdruk(),
        "n_ensemble": n, "seed": seed,
        "clinic": asdict(clinic),
        "voorspellingen": resultaten, "fouten": fouten,
    }
    vast.write_text(json.dumps(vastlegging, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    _print(f"\nVoorspelling vastgelegd: {vast}")
    return vast


# =============================================================================
# Stap 3 - FIT omzetten
# =============================================================================
def fit_omzetten(map_: Path, bestanden: Optional[list] = None) -> list[Path]:
    import fit_lezer as fl
    fit_map = Path(map_) / "fit_uitvoer"
    bestanden = [Path(b) for b in bestanden] if bestanden else fl._kies_bestanden()
    gemaakt = []
    _print("Geef elke loper de code uit deelnemers.xlsx (geen naam).")
    for i, p in enumerate(bestanden, 1):
        code = input(f"Code voor bestand {i} van {len(bestanden)}: ").strip()
        code = "".join(c for c in code if c.isalnum() or c in "-_")
        if not code:
            _print("  overgeslagen (geen code)")
            continue
        rit = fl.lees_fit(p, code)
        u = fl.exporteer(rit, fit_map)
        gemaakt.append(u["xlsx"])
        _print(f"  {code}: {rit.meta['duur_min']} min, {rit.meta['afstand_km']} km -> {u['xlsx'].name}")
    return gemaakt


# =============================================================================
# Stap 4 - vergelijken (modus B)
# =============================================================================
@dataclass
class LoperVergelijking:
    code: str
    deelnemer: ci.Deelnemer
    inclusie: dict                       # 'kern'/'hartslag'/'nawarmte'/'vocht' -> (ok, reden)
    meting: Optional[iuf.Meting] = None
    hoofddeel: Optional[iuf.Hoofddeel] = None
    vo2max: dict = field(default_factory=dict)
    vo2_schatting: Optional[iuf.VO2maxSchatting] = None
    recon: dict = field(default_factory=dict)        # variant -> Reconstructie
    maten: dict = field(default_factory=dict)        # variant -> dict
    modus_a: dict = field(default_factory=dict)
    algemeen: dict = field(default_factory=dict)     # variant-onafhankelijke maten
    opmerking: str = ""


def _zoek_export(fit_map: Path, code: str) -> Optional[Path]:
    kand = sorted(fit_map.glob(f"{code}_*.xlsx"))
    return kand[-1] if kand else None


def _kern_maten(rc: hr_.Reconstructie, meting: iuf.Meting, hd: iuf.Hoofddeel) -> dict:
    mins = hd.minuten
    k = meting.per_minuut["kern_temp"].reindex(mins).to_numpy(dtype=float)
    mod = rc.centraal["t_rect"].reindex(mins).to_numpy(dtype=float)
    lo = rc.band["t_rect_lo"].reindex(mins).to_numpy(dtype=float)
    hi = rc.band["t_rect_hi"].reindex(mins).to_numpy(dtype=float)
    ok = np.isfinite(k) & np.isfinite(mod)
    d = mod[ok] - k[ok]
    k_ok = np.where(np.isfinite(k))[0]
    opw_m = float(k[k_ok[-1]] - k[k_ok[0]]) if len(k_ok) >= 2 else float("nan")
    opw_mod = float(mod[k_ok[-1]] - mod[k_ok[0]]) if len(k_ok) >= 2 else float("nan")
    # Verkennend: vertraging van de meting t.o.v. het model (0-20 min)
    kv = meting.per_minuut["kern_temp"]
    beste = (0, float("nan"))
    for lag in range(0, 21):
        km = kv.reindex(mins + lag).to_numpy(dtype=float)
        o = np.isfinite(km) & np.isfinite(mod)
        if o.sum() >= 0.8 * len(mins):
            r = float(np.sqrt(np.mean((mod[o] - km[o]) ** 2)))
            if not np.isfinite(beste[1]) or r < beste[1]:
                beste = (lag, r)
    huid_m = meting.per_minuut["huid_temp"].reindex(mins).to_numpy(dtype=float)
    huid_mod = rc.centraal["huid_borst"].reindex(mins).to_numpy(dtype=float)
    oh = np.isfinite(huid_m) & np.isfinite(huid_mod)
    return {
        "kern_bias": float(d.mean()) if len(d) else float("nan"),
        "kern_rmse": float(np.sqrt(np.mean(d ** 2))) if len(d) else float("nan"),
        "kern_opwarming_model": opw_mod, "kern_opwarming_meting": opw_m,
        "kern_opwarming_verschil": opw_mod - opw_m,
        "kern_dekking": float(np.mean((k[ok] >= lo[ok]) & (k[ok] <= hi[ok])) * 100) if ok.any() else float("nan"),
        "kern_start_model": float(mod[0]), "kern_start_meting": float(k[k_ok[0]]) if len(k_ok) else float("nan"),
        "kern_gem_model": float(np.nanmean(mod[ok])) if ok.any() else float("nan"),
        "kern_gem_meting": float(np.nanmean(k[ok])) if ok.any() else float("nan"),
        "verkennend_vertraging_min": beste[0], "verkennend_rmse_na_vertraging": beste[1],
        "huid_borst_bias": float(np.mean(huid_mod[oh] - huid_m[oh])) if oh.any() else float("nan"),
        "nawarmte_model_B": _nawarmte_reeks(rc.centraal["t_rect"], hd),
    }


def _nawarmte_reeks(s: pd.Series, hd: iuf.Hoofddeel) -> float:
    bij = s.get(hd.eind_min, np.nan)
    na = s.loc[hd.eind_min + 1: hd.eind_min + int(NAWARMTE_MIN)]
    return float(na.max() - bij) if len(na) else float("nan")


def _hr_maten(hrdf: pd.DataFrame, meting: iuf.Meting, hd: iuf.Hoofddeel) -> dict:
    mins = hd.minuten
    h = meting.per_minuut["hartslag"].reindex(mins).to_numpy(dtype=float)
    m = hrdf["hr"].reindex(mins).to_numpy(dtype=float)
    ok = np.isfinite(h) & np.isfinite(m)
    d = m[ok] - h[ok]
    dm, dh = _helling_per_10min(m), _helling_per_10min(h)
    return {"hr_bias": float(d.mean()) if len(d) else float("nan"),
            "hr_rmse": float(np.sqrt(np.mean(d ** 2))) if len(d) else float("nan"),
            "hr_drift_model": dm, "hr_drift_meting": dh, "hr_drift_verschil": dm - dh}


def vergelijk_loper(d: ci.Deelnemer, clinic: ci.Clinic, fit_map: Path, weer_df: Optional[pd.DataFrame],
                    modus_a: dict, n: int, seed: int, varianten=("B1", "B2", "B3", "B4"),
                    weerbestand: Optional[str] = None) -> LoperVergelijking:
    from individual_engine import _default_vo2max
    from hestia_loper import weer_uit_excel
    lv = LoperVergelijking(code=d.code, deelnemer=d, inclusie={}, modus_a=modus_a or {})
    exp = _zoek_export(fit_map, d.code)
    if exp is None:
        lv.inclusie = {k: (False, "geen FIT-export voor deze code") for k in ("kern", "hartslag", "nawarmte", "vocht")}
        return lv
    m = iuf.lees_export(exp)
    lv.meting = m
    hd = iuf.hoofddeel(m)
    lv.hoofddeel = hd
    lv.inclusie = iuf.kwaliteit(m, hd)
    vp = d.vochtverlies_gemeten_pct()
    lv.inclusie["vocht"] = (vp is not None, "gewogen en drank bekend" if vp is not None else d.reden_geen_vochtverlies())
    if d.opmerking:
        lv.opmerking = d.opmerking
    if hd is None:
        return lv
    # --- VO2max-bronnen
    pop = d.vo2max or _default_vo2max(d.leeftijd, "male" if d.geslacht == "man" else "female")
    lv.vo2max = {"populatie" if not d.vo2max else "gemeten": float(pop), "garmin": m.vo2max_garmin}
    lv.vo2_schatting = iuf.vo2max_uit_loop(m, hd, d.leeftijd, d.hr_max, d.hr_rust)
    if lv.vo2_schatting is not None and np.isfinite(lv.vo2_schatting.vo2max):
        lv.vo2max["hestia"] = float(lv.vo2_schatting.vo2max)
    # --- weer: voor de hele registratie, starttijd uit de FIT-export
    start = m.start_lokaal
    n_min = int(m.per_minuut.index.max()) + 1
    if weer_df is None:
        weer_df = weer_uit_excel(weerbestand or clinic.weerbestand, start,
                                 start + pd.Timedelta(minutes=n_min))[0]
    p = hr_.Persoon(geslacht=d.geslacht, leeftijd=d.leeftijd, lengte_cm=d.lengte_cm,
                    gewicht_kg=d.gewicht_voor_kg, clo=hr_.KLEDING_CLO[d.kleding],
                    hitte_gewend=d.hitte_gewend, drank_ml=d.drank_ml or 0.0,
                    hr_max=d.hr_max, hr_rust=d.hr_rust)
    minuten = m.per_minuut.reindex(np.arange(n_min))[["snelheid_ms", "met"]].copy()
    minuten["met"] = minuten["met"].fillna(iuf.MET_STIL)
    minuten = minuten.reset_index(drop=True)
    alle = hr_.reconstrueer_varianten(p, minuten, weer_df, start, varianten, lv.vo2max,
                                      n_ensemble=n, seed=seed)
    # --- verkennend: dynamica (K, dode tijd, tau) en maximum, zie dynamiek.py
    u = minuten["met"].to_numpy(dtype=float)
    kern_reeks = m.per_minuut["kern_temp"].reindex(np.arange(n_min)).to_numpy(dtype=float)
    dyn_core = dyn.analyse(u, kern_reeks, hd.start_min, hd.eind_min)
    for v in varianten:
        rc = alle[v]
        lv.recon[v] = rc
        mt = _kern_maten(rc, m, hd)
        for bron, h in rc.hr.items():
            for k, x in _hr_maten(h, m, hd).items():
                mt[f"{k}_{bron}"] = x
        hrs = [rc.hr[b]["hr"] for b in ("populatie", "gemeten", "garmin") if b in rc.hr]
        if len(hrs) >= 1:
            lo = np.minimum.reduce([s.reindex(hd.minuten).to_numpy() for s in hrs])
            hi = np.maximum.reduce([s.reindex(hd.minuten).to_numpy() for s in hrs])
            hm = m.per_minuut["hartslag"].reindex(hd.minuten).to_numpy(dtype=float)
            o = np.isfinite(hm)
            mt["hr_binnen_band_pct"] = float(np.mean((hm[o] >= lo[o] - 0.5) & (hm[o] <= hi[o] + 0.5)) * 100) if o.any() else float("nan")
        # vochtverlies over de hele registratie (de wegingen omsluiten de sessie)
        mt["vocht_model_pct"] = float(rc.centraal["vocht_pct_cum"].iat[-1])
        mt["vocht_model_lo"] = float(np.percentile(rc.vocht_pct_runs, 2.5))
        mt["vocht_model_hi"] = float(np.percentile(rc.vocht_pct_runs, 97.5))
        mt["vocht_meting_pct"] = vp if vp is not None else float("nan")
        mt["vocht_verschil"] = mt["vocht_model_pct"] - mt["vocht_meting_pct"]
        mt["bmr_w_m2"] = rc.centraal.attrs.get("bmr_w_m2", float("nan"))
        dm = dyn.analyse(u, rc.centraal["t_rect"].to_numpy(dtype=float), hd.start_min, hd.eind_min)
        for k_, x_ in dm.items():
            mt[f"dyn_{k_}_model"] = x_
        mt["dyn_K_verhouding"] = dyn_core["K"] / dm["K"] if dm["K"] else float("nan")
        mt["dyn_dode_tijd_verschil"] = dyn_core["dode_tijd"] - dm["dode_tijd"]
        mt["dyn_tau_verschil"] = dyn_core["tau"] - dm["tau"]
        mt["kern_max_verschil"] = dm["piek"] - dyn_core["piek"]
        mt["kern_max_tijdverschil_min"] = dyn_core["piek_minuut"] - dm["piek_minuut"]
        hr_bron = "populatie" if "populatie" in rc.hr else ("gemeten" if "gemeten" in rc.hr else None)
        if hr_bron:
            hd_ = dyn.hartslag_dynamiek(
                u, m.per_minuut["hartslag"].reindex(np.arange(n_min)).to_numpy(dtype=float),
                hd.start_min, hd.eind_min,
                rc.hr[hr_bron]["hr"].reindex(np.arange(n_min)).to_numpy(dtype=float))
            for k_, x_ in hd_.items():
                mt[f"dyn_{k_}"] = x_
            mt["dyn_hr_tau_verschil"] = hd_.get("hr_tau", np.nan) - hd_.get("hr_tau_model", np.nan)
        lv.maten[v] = mt
    # --- variant-onafhankelijk
    alg = {"hoofddeel_start_min": hd.start_min, "hoofddeel_duur_min": hd.duur_min,
           "hoofddeel_afstand_km": hd.afstand_km, "hoofddeel_tempo": hd.tempo_min_km,
           "nawarmte_meting": iuf.nawarmte_gemeten(m, hd),
           **{f"dyn_{k_}_CORE": x_ for k_, x_ in dyn_core.items()},
           "hartslag_ontkoppeld_pct": dyn.hartslag_ontkoppeld(
               m.per_minuut["met"].reindex(np.arange(n_min)).to_numpy(dtype=float),
               m.per_minuut["hartslag"].reindex(np.arange(n_min)).to_numpy(dtype=float),
               hd.start_min, hd.eind_min)}
    if lv.vo2_schatting is not None and m.vo2max_garmin and np.isfinite(lv.vo2_schatting.vo2max):
        alg["vo2max_verschil_pct"] = (lv.vo2_schatting.vo2max - m.vo2max_garmin) / m.vo2max_garmin * 100
    else:
        alg["vo2max_verschil_pct"] = float("nan")
    if modus_a:
        # modus A begint bij de start van het hoofddeel; eindtemperatuur op de
        # gemeten duur van het hoofddeel (lineair tussen de 10-minuutstappen)
        band = modus_a.get("_band")
        if band is not None:
            alg["A_t_op_meetduur_med"] = float(np.interp(hd.duur_min, band["minuut"], band["t_rect_med"]))
            alg["A_t_op_meetduur_lo"] = float(np.interp(hd.duur_min, band["minuut"], band["t_rect_lo"]))
            alg["A_t_op_meetduur_hi"] = float(np.interp(hd.duur_min, band["minuut"], band["t_rect_hi"]))
            kk = m.per_minuut["kern_temp"]
            alg["meting_t_eind_hoofddeel"] = float(kk.get(hd.eind_min, np.nan))
        alg["A_nawarmte_med"] = modus_a.get("nawarmte_med", float("nan"))
        alg["A_finish_med_min"] = modus_a.get("finish_med_min", float("nan"))
    lv.algemeen = alg
    return lv


def groep(lopers: list[LoperVergelijking], criteria: dict, varianten=("B1", "B2", "B3", "B4")) -> pd.DataFrame:
    """Groepsgemiddelde per maat en variant, met 95%-BI (t) en oordeel."""
    from scipy import stats
    nmin = criteria["min_lopers_groepsoordeel"]
    rijen = []
    eis = {"kern_bias": "kern", "kern_rmse": "kern", "kern_opwarming_verschil": "kern",
           "kern_dekking": "kern", "vocht_verschil": "vocht", "hr_bias": "hartslag",
           "hr_drift_verschil": "hartslag", "kern_max_verschil": "kern", "dyn_K_verhouding": "kern",
           "dyn_dode_tijd_verschil": "kern", "dyn_tau_verschil": "kern",
           "dyn_hr_tau_verschil": "hartslag", "dyn_hr_na_model_verschil": "hartslag",
           "huid_borst_bias": "kern"}
    for maat, c in criteria["maten"].items():
        for v in (varianten if maat != "vo2max_verschil_pct" else ("-",)):
            for bron in (("populatie", "gemeten", "garmin") if maat.startswith("hr_") else ("",)):
                xs = []
                for lv in lopers:
                    if maat == "vo2max_verschil_pct":
                        x = lv.algemeen.get(maat, np.nan)
                    else:
                        if not lv.inclusie.get(eis[maat], (False,))[0] or v not in lv.maten:
                            continue
                        x = lv.maten[v].get(f"{maat}_{bron}" if bron else maat, np.nan)
                    if x is not None and np.isfinite(x):
                        xs.append(float(x))
                xs = np.array(xs)
                n = len(xs)
                if bron == "gemeten" and n == 0:
                    continue
                gem = float(np.mean(np.abs(xs))) if c["toets"] == "abs_max_per_loper" and n else (float(np.mean(xs)) if n else float("nan"))
                if n >= 2:
                    sd = float(np.std(xs, ddof=1))
                    hw = float(stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n))
                else:
                    sd = hw = float("nan")
                if n == 0:
                    oo = "geen data"
                elif c.get("verkennend"):
                    oo = f"verkennend ({oordeel(gem, c)})"
                elif n < nmin:
                    oo = f"beschrijvend, n < {nmin} ({oordeel(gem, c)})"
                else:
                    oo = oordeel(gem, c)
                rijen.append({"maat": maat, "label": c["label"], "eenheid": c["eenheid"], "variant": v,
                              "vo2max_bron": bron, "n_lopers": n, "groepswaarde": gem, "sd": sd,
                              "bi95_lo": gem - hw if np.isfinite(hw) else np.nan,
                              "bi95_hi": gem + hw if np.isfinite(hw) else np.nan,
                              "goed": c["goed"], "acceptabel": c["acceptabel"], "oordeel": oo})
    return pd.DataFrame(rijen)


def vergelijk(map_: Path, n: int = N_ENSEMBLE_B, seed: int = SEED, codes=None,
              fit_map: Optional[Path] = None, zonder_voorspelling: bool = False,
              rapport: bool = True, weerbestand=None) -> dict:
    """Modus B + vergelijking voor alle deelnemers. Geeft de uitvoerpaden terug.

    weerbestand: [2026-10-12] los weerbestand voor modus B (bijv. archiefweer
    achteraf), zonder deelnemers.xlsx te wijzigen. Modus A blijft de vastgelegde
    voorspelling. Uitvoer dan in validatie_uitvoer_<naam weerbestand>, zodat een
    run met het verwachte weer en een met het archiefweer naast elkaar blijven."""
    import clinic_rapport as cr
    map_ = Path(map_)
    clinic, deelnemers, meldingen = ci.lees_deelnemers(map_ / "deelnemers.xlsx")
    vast_pad = map_ / "modus_A" / "vastlegging.json"
    if vast_pad.exists():
        vast = json.loads(vast_pad.read_text(encoding="utf-8"))
    elif zonder_voorspelling:
        vast = None
    else:
        raise FileNotFoundError(
            "Er is geen vastgelegde voorspelling (modus_A/vastlegging.json). Draai eerst "
            "'voorspel', VOORDAT je de FIT-bestanden bekijkt. (Alleen voor ontwikkeling: "
            "--zonder-voorspelling.)")
    fit_map = Path(fit_map) if fit_map else map_ / "fit_uitvoer"
    controles = []
    if vast:
        t_vast = datetime.fromisoformat(vast["aangemaakt"]).timestamp()
        ouder = [p.name.split("_")[0] for p in fit_map.glob("*.xlsx") if p.stat().st_mtime < t_vast]
        if ouder:
            controles.append(f"FIT-export(s) ouder dan de voorspelling: {', '.join(sorted(set(ouder)))}")
        if _sha(map_ / "deelnemers.xlsx") != vast["deelnemers_sha256"]:
            controles.append("deelnemers.xlsx is gewijzigd na de voorspelling")
        nu = vingerafdruk()
        anders = [k for k, v in vast["suite_vingerafdruk"].items() if nu.get(k) != v]
        if anders:
            controles.append("suitebestanden gewijzigd na de voorspelling: " + ", ".join(anders))
    criteria = laad_criteria()
    if weerbestand:
        weerbestand = Path(weerbestand)
        if not weerbestand.is_absolute():
            weerbestand = map_ / weerbestand
        if not weerbestand.exists():
            raise FileNotFoundError(f"Weerbestand niet gevonden: {weerbestand}")
        uit = map_ / f"validatie_uitvoer_{weerbestand.stem}"
        weer_info = (f"{weerbestand.name} (los gekozen voor de reconstructie); modus A gebruikte "
                     f"{Path(clinic.weerbestand).name}")
    else:
        uit = map_ / "validatie_uitvoer"
        weer_info = f"{Path(clinic.weerbestand).name} (uit deelnemers.xlsx, hetzelfde als modus A)"
    uit.mkdir(parents=True, exist_ok=True)
    weer_cache = {}
    lopers = []
    for d in deelnemers:
        if codes and d.code not in codes:
            continue
        _print(f"Modus B: {d.code} ...")
        t0 = time.time()
        ma = {}
        if vast and d.code in vast.get("voorspellingen", {}):
            ma = dict(vast["voorspellingen"][d.code])
            bp = map_ / "modus_A" / f"{d.code}_modusA_band.csv"
            if bp.exists():
                ma["_band"] = pd.read_csv(bp)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                lv = vergelijk_loper(d, clinic, fit_map, None, ma, n, seed,
                                     weerbestand=str(weerbestand) if weerbestand else None)
        except Exception as e:
            lv = LoperVergelijking(code=d.code, deelnemer=d,
                                   inclusie={k: (False, f"fout: {type(e).__name__}: {e}")
                                             for k in ("kern", "hartslag", "nawarmte", "vocht")})
        lopers.append(lv)
        _print(f"   klaar in {time.time() - t0:.0f} s; kern: {lv.inclusie.get('kern', ('', ''))[1]}")
    g = groep(lopers, criteria)
    paden = cr.schrijf_excel(lopers, g, criteria, vast, controles, uit / "validatie.xlsx",
                             weer_info=weer_info)
    figs = cr.figuren(lopers, g, criteria, uit)
    out = {"excel": paden, "figuren": figs}
    if rapport:
        out["rapport"] = cr.maak_rapport(lopers, g, criteria, clinic, vast, controles, figs,
                                         uit / "Validatierapport_HESTIA_ThermoClinic.docx",
                                         weer_info=weer_info)
    _print(f"\nKlaar. Uitvoer in {uit}")
    return out


# =============================================================================
# Menu en opdrachtregel
# =============================================================================
def _vraag_map() -> Path:
    s = input("Map van de clinic (met deelnemers.xlsx) [huidige map]: ").strip().strip('"')
    return Path(s) if s else Path.cwd()


def menu():
    print(__doc__)
    map_ = _vraag_map()
    keuzes = {"1": "leeg deelnemers.xlsx maken", "2": "voorspellen (modus A)",
              "3": "FIT-bestanden omzetten", "4": "vergelijken (modus B + rapport)", "0": "stoppen"}
    while True:
        print()
        for k, t in keuzes.items():
            print(f"  {k}  {t}")
        k = input("Keuze: ").strip()
        try:
            if k == "1":
                print("Gemaakt:", sjabloon(map_))
            elif k == "2":
                voorspel(map_)
            elif k == "3":
                fit_omzetten(map_)
            elif k == "4":
                vergelijk(map_)
            elif k in ("0", ""):
                return 0
        except (ValueError, FileNotFoundError, FileExistsError) as e:
            print("\n! " + str(e))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return menu() or 0
    ap = argparse.ArgumentParser(description="HESTIA-validatie Thermo Clinic")
    ap.add_argument("stap", choices=["sjabloon", "voorspel", "fit", "vergelijk"])
    ap.add_argument("map", type=Path)
    ap.add_argument("--n", type=int, default=None, help="ensemblegrootte")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--codes", nargs="*", default=None)
    ap.add_argument("--fit-map", type=Path, default=None)
    ap.add_argument("--zonder-voorspelling", action="store_true",
                    help="alleen voor ontwikkeling (bijv. L01 van 18 september)")
    ap.add_argument("--weer", type=Path, default=None,
                    help="los weerbestand voor modus B (bijv. archiefweer), stap vergelijk")
    ap.add_argument("bestanden", nargs="*", default=None, help="FIT-bestanden (stap fit)")
    a = ap.parse_args(argv)
    try:
        if a.stap == "sjabloon":
            print("Gemaakt:", sjabloon(a.map))
        elif a.stap == "voorspel":
            voorspel(a.map, a.n or N_ENSEMBLE_A, a.seed, a.codes)
        elif a.stap == "fit":
            fit_omzetten(a.map, a.bestanden)
        else:
            vergelijk(a.map, a.n or N_ENSEMBLE_B, a.seed, a.codes, a.fit_map, a.zonder_voorspelling,
                      weerbestand=a.weer)
    except (ValueError, FileNotFoundError, FileExistsError) as e:
        print("\n! " + str(e))
        return 1
    return 0


if __name__ == "__main__":
    _rc = main()
    if _rc and not (hasattr(sys, "ps1") or "IPython" in sys.modules):
        sys.exit(_rc)
