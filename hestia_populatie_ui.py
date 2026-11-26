# -*- coding: utf-8 -*-
"""
hestia_populatie_ui.py
======================
Visuele invoer en weergave (Tkinter) voor het HESTIA-populatiemodel: een
evenement met een virtueel deelnemersveld.

De suite blijft bevroren: dit script verandert niets aan de suitebestanden en
roept alleen bestaande functies aan, in dezelfde volgorde als run_hestia.py
(populatiemodus) en hestia_bridge.py:

  deelnemersveld ......... hestia_model.generate_base_population()
  weer -> 10-min stappen . hestia_bridge.build_interp_data()   (zoals Klimatos
                            en de loper-UI; run_hestia gebruikt de loader-route
                            met dezelfde kolommen)
  een deelnemer .......... hestia_model.worker_monte_carlo_adult()  (zaait zelf
                            per deelnemer uit het profiel -> volgorde-onafhankelijk)
  populatiestatistiek .... hestia_model.run_monte_carlo_adult()  (via terugspelen)
  criteria, dosis, paren . hestia_bridge._summarize_results()
  dosis-respons-EHS ...... hestia_bridge._dose_response_pct_patched() +
                            uncertainty.ehs_interval()   (zoals run_quick_estimate)
  steekproefonzekerheid .. uncertainty.fraction_interval()
  trainingsprofielen ..... hestia_console.get_adaptation_profile()  (uitgelezen)
  activiteiten, kleding .. hestia_model.MET_ACTIVITIES_ADULT, CLO_OPTIONS_ADULT
  eindpunten ............. hestia_model.COLLAPSE_ENDPOINTS / ACTIVE_ENDPOINT

Uitvoering
----------
* Live (bij elke wijziging): een snelle schatting met n = 100 (hestia_bridge.QUICK_N).
  Knop 'Volledige run': hetzelfde met het grotere aantal (standaard 1000).
* De deelnemers worden parallel over alle kernen verdeeld; de banden worden
  bijgewerkt zodra er deelnemers klaar zijn. Omdat worker_monte_carlo_adult()
  elke deelnemer zelf zaait uit zijn eigen profiel, is het resultaat
  bit-voor-bit gelijk aan een seriele run_monte_carlo_adult() met dezelfde
  populatie (gecontroleerd bij het bouwen).
* Als alle deelnemers klaar zijn, loopt het eindresultaat door de echte
  run_monte_carlo_adult(use_parallel=False, base_population=...): de al
  berekende deelnemers worden teruggespeeld, met per deelnemer een controle
  dat profiel, MET, kleding en weervenster gelijk zijn.
* Luchtkwaliteit: eenmaal opgehaald en per werkproces vastgezet met
  hestia_bridge._patch_air_quality() (zoals hestia_bridge). run_hestia.py zet
  hem offline op 1.

Banden in de grafieken: gemiddelde met p5-p95 per tijdstap over de deelnemers
die nog lopen (zoals mean_t_rect / lower_t_rect / upper_t_rect in
run_monte_carlo_adult). Voor CO_reserve maakt de suite zelf geen band per
tijdstap; dezelfde rekenregel is daarvoor gebruikt.

Status: research software (zie README). Niet voor operationele beslissingen.

Starten:  python hestia_populatie_ui.py
"""
from __future__ import annotations

from taal import vt, getal, engels

import inspect
import os
import queue
import re
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from hestia_loper_ui import HIER, Weer, WeerBron, _opwarmen, _suite, _vervang, _werker_init

# =============================================================================
# 1. WERKPROCES
# =============================================================================


def _pop_lid(a):
    """Een deelnemer: precies hestia_model.worker_monte_carlo_adult(args)."""
    gen, i, args, aqi = a
    import hestia_model as hm
    import hestia_bridge as hb
    hb._patch_air_quality(aqi)
    hm.CV_CEILING_FORCED = True   # suite-standaard (werkprocessen kunnen gedeeld zijn)
    return gen, i, hm.worker_monte_carlo_adult(args)


# =============================================================================
# 2. REKENKERN
# =============================================================================
def adaptatieprofielen() -> list[tuple[str, float, float]]:
    """De vier profielen uit hestia_console.get_adaptation_profile(),
    rechtstreeks uit de broncode gelezen (de waarden staan daar lokaal in de
    functie en zijn niet los op te vragen)."""
    import hestia_console
    src = inspect.getsource(hestia_console.get_adaptation_profile)
    gevonden = re.findall(r'\{"name":\s*"([^"]+)",\s*"training":\s*([0-9.]+),\s*'
                          r'"acclimatization":\s*([0-9.]+)\}', src)
    if len(gevonden) != 4:
        raise RuntimeError(vt("Trainingsprofielen niet te lezen uit hestia_console.get_adaptation_profile", "Training profiles cannot be read from hestia_console.get_adaptation_profile"))
    return [(n, float(t), float(a)) for n, t, a in gevonden]


@dataclass
class PopInvoer:
    evenement: str
    populatie: str            # 'lopers' | 'wandelaars'
    afstand_km: float
    eigen_tempo: bool         # sample_pace
    activiteit: int           # sleutel in MET_ACTIVITIES_ADULT
    duur_h: Optional[float]   # None = afgeleid (afstand / snelheid)
    clo: float
    profiel: int              # index in adaptatieprofielen()
    eindpunt: str             # sleutel in COLLAPSE_ENDPOINTS
    datum: str
    starttijd: str

    @property
    def start(self) -> pd.Timestamp:
        return pd.Timestamp(f"{self.datum} {self.starttijd}")


def afgeleide_duur(inv: PopInvoer) -> float:
    """Zoals run_hestia._run_cli(): duur = afstand / snelheid van de activiteit
    (4,0 u als de activiteit geen snelheid heeft). Met eigen tempo per deelnemer
    wordt het venster verbreed tot hestia_model.race_window_hours() (de
    langzaamste deelnemer plus bezemwagenruimte), zoals monte_carlo_adult()."""
    _, _, hm, _, _ = _suite()
    act = hm.MET_ACTIVITIES_ADULT[inv.activiteit]
    if inv.duur_h is not None:
        d = float(inv.duur_h)
    else:
        d = round(inv.afstand_km / act["speed_kmh"], 2) if act["speed_kmh"] > 0 else 4.0
    if inv.eigen_tempo:
        d = max(d, hm.race_window_hours(inv.afstand_km))
    return d


def valideer(inv: PopInvoer) -> list[str]:
    _, _, hm, _, _ = _suite()
    fouten = []
    if not 0.5 <= inv.afstand_km <= 100:
        fouten.append(vt("afstand: 0,5 t/m 100 km", "distance: 0.5 to 100 km"))
    if inv.eigen_tempo and inv.populatie == "wandelaars":
        fouten.append(vt("eigen tempo per deelnemer kan alleen bij lopers (generate_base_population)", "individual pace per participant is only possible for runners (generate_base_population)"))
    if inv.activiteit not in hm.MET_ACTIVITIES_ADULT:
        fouten.append(vt("onbekende activiteit", "unknown activity"))
    if inv.eindpunt not in hm.COLLAPSE_ENDPOINTS:
        fouten.append(vt("onbekend eindpunt", "unknown endpoint"))
    d = afgeleide_duur(inv)
    if not 0.1 <= d <= 24:
        fouten.append(vt("duur: 0,1 t/m 24 uur", "duration: 0.1 to 24 hours"))
    return fouten


def venster(inv: PopInvoer) -> tuple[pd.Timestamp, pd.Timestamp]:
    return inv.start, inv.start + pd.Timedelta(hours=afgeleide_duur(inv))


def controleer_dekking(weer: Weer, start: pd.Timestamp, eind: pd.Timestamp) -> None:
    """Uurrijen van floor(start) t/m ceil(eind) + 1 u aanwezig en compleet
    (run_hestia vraagt duration_hours + 1 uur weer op)."""
    hl, *_ = _suite()
    lo = start.floor("h").tz_localize(weer.tz, ambiguous=True, nonexistent="shift_forward")
    hi = (eind.ceil("h") + pd.Timedelta(hours=1)).tz_localize(weer.tz, ambiguous=True,
                                                                nonexistent="shift_forward")
    kol = [c for c in hl.WEER_KOLOMMEN if c in weer.df.columns]
    v = weer.df.loc[lo:hi, kol]
    if len(v) == 0 or v.index.min() > lo or v.index.max() < hi:
        raise ValueError(vt(f"Het weer dekt {start:%d-%m %H:%M} - {eind:%d-%m %H:%M} (+1 u) niet "
                         f"volledig (beschikbaar {weer.df.index.min():%d-%m %H:%M} t/m "
                         f"{weer.df.index.max():%d-%m %H:%M}).",
                            f"The weather does not fully cover {start:%d-%m %H:%M} - {eind:%d-%m %H:%M} (+1 h) "
                         f"(available {weer.df.index.min():%d-%m %H:%M} to "
                         f"{weer.df.index.max():%d-%m %H:%M})."))
    if v.isna().any().any():
        raise ValueError(vt("Het weer heeft ontbrekende waarden in het venster.", "The weather has missing values in the window."))


@dataclass
class PopTaak:
    gen: int
    inv: PopInvoer
    weer: Weer
    n: int
    seed: int
    volledig: bool
    met: float
    tf: float
    af: float
    interp: list
    populatie: list
    args: list
    start_aware: pd.Timestamp
    eind_aware: pd.Timestamp
    meteo: dict
    wind15: np.ndarray
    res: dict = field(default_factory=dict)


def bereid_voor(gen, inv: PopInvoer, weer: Weer, n: int, seed: int, volledig: bool) -> PopTaak:
    _, ie, hm, hb, _ = _suite()
    fouten = valideer(inv)
    if fouten:
        raise ValueError("; ".join(fouten))
    s, e = venster(inv)
    controleer_dekking(weer, s, e)
    sa = ie._localize_naive(s, weer.tz)
    ea = ie._localize_naive(e, weer.tz)
    interp = hb.build_interp_data(weer.df, sa, ea)
    met = float(hm.MET_ACTIVITIES_ADULT[inv.activiteit]["met"])
    _, tf, af = adaptatieprofielen()[inv.profiel]
    with _POP_SLOT:   # generate_base_population zaait de GLOBALE numpy-RNG
        pop = hm.generate_base_population(
            n_simulations=n, training_factor=tf, acclimatization_factor=af, random_seed=seed,
            met_value=met, sample_pace=inv.eigen_tempo, event_dist_km=inv.afstand_km,
            population=inv.populatie)
    if not pop:
        raise ValueError(vt("generate_base_population leverde geen deelnemers op.", "generate_base_population returned no participants."))
    # --- worker_args precies zoals in hestia_model.run_monte_carlo_adult() ----
    step = ((interp[1]["time"] - interp[0]["time"]).total_seconds() / 60.0
            if inv.eigen_tempo and len(interp) >= 2 else None)
    args = []
    for p in pop:
        if inv.eigen_tempo and step and p.duration_hours > 0:
            n_steps = max(2, int(round(p.duration_hours * 60.0 / step)) + 1)
            person_interp = interp if hm.RACE_DISTANCE_MODE else interp[:n_steps]
            args.append((person_interp, weer.lat, weer.lon, hm._acsm_met_from_pace(p.pace_min_per_km),
                         inv.clo, p, tf, af))
        else:
            args.append((interp, weer.lat, weer.lon, met, inv.clo, p, tf, af))
    meteo = ie.meteo_timeseries(weer.df, sa, ea)
    wind15 = np.array([hm.wind_speed_at_height(r["wind"], 10, 1.5) for r in interp], dtype=float)
    return PopTaak(gen, inv, weer, len(pop), seed, volledig, met, tf, af, interp, pop, args,
                   sa, ea, meteo, wind15)


def taak_argumenten(t: PopTaak):
    for i, a in enumerate(t.args):
        yield (t.gen, i, a, t.weer.aqi)


def _matrix(sporen, sleutel):
    lengte = max((len(r) for r in sporen), default=0)
    m = np.full((len(sporen), lengte), np.nan)
    for j, res in enumerate(sporen):
        for k, r in enumerate(res):
            v = r.get(sleutel)
            if v is not None:
                try:
                    m[j, k] = float(v)
                except (TypeError, ValueError):
                    pass
    return m


def banden(t: PopTaak) -> Optional[dict]:
    """Gemiddelde en p5-p95 per tijdstap over de deelnemers die nog lopen,
    dezelfde rekenregel als mean/lower/upper_t_rect in run_monte_carlo_adult()."""
    _, _, hm, _, _ = _suite()
    if not t.res:
        return None
    sporen = [t.res[i] for i in sorted(t.res)]
    uit = {"n": len(sporen)}
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for k, sl in (("t", "t_rect"), ("co", "co_reserve")):
                m = _matrix(sporen, sl)
                uit[k] = (np.nanmean(m, axis=0), np.nanpercentile(m, 5, axis=0),
                          np.nanpercentile(m, 95, axis=0))
            tm = _matrix(sporen, "t_rect")
            uit["drempels"] = hm._calculate_threshold_stats(tm, len(sporen))
            uit["actief"] = np.sum(~np.isnan(tm), axis=0)
    return uit


_TERUGSPEEL_SLOT = threading.Lock()
_POP_SLOT = threading.Lock()


def eindresultaat(t: PopTaak) -> dict:
    """Loopt door run_monte_carlo_adult(use_parallel=False, base_population=...)
    met teruggespeelde deelnemers, daarna door hestia_bridge._summarize_results()
    en de dosis-respons-stappen van run_quick_estimate()."""
    _, _, hm, hb, _ = _suite()
    from uncertainty import ehs_interval, fraction_interval
    index = {id(p): i for i, p in enumerate(t.populatie)}
    gezien = set()

    def terugspelen(args):
        i = index.get(id(args[5]))
        if i is None:
            raise RuntimeError(vt("Onbekende deelnemer bij terugspelen.", "Unknown participant on replay."))
        eigen = t.args[i]
        if (len(args[0]) != len(eigen[0]) or abs(args[3] - eigen[3]) > 1e-12
                or abs(args[4] - eigen[4]) > 1e-12 or args[6] != eigen[6] or args[7] != eigen[7]):
            raise RuntimeError(vt(f"Invoer van deelnemer {i} wijkt af van de berekening.", f"Input of participant {i} differs from the calculation."))
        gezien.add(i)
        return t.res[i]

    with _TERUGSPEEL_SLOT, _vervang(hm, "worker_monte_carlo_adult", terugspelen), \
            _vervang(hm, "ACTIVE_ENDPOINT", t.inv.eindpunt):
        all_results, stats, results_df = hm.run_monte_carlo_adult(
            t.interp, t.weer.lat, t.weer.lon, t.met, t.inv.clo, n_simulations=t.n,
            age_configuration="standard", training_factor=t.tf, acclimatization_factor=t.af,
            use_parallel=False, base_population=t.populatie, random_seed=t.seed,
            run_control_failure=True, sample_pace=t.inv.eigen_tempo,
            event_dist_km=t.inv.afstand_km, population=t.inv.populatie)
    if len(gezien) != t.n:
        raise RuntimeError(vt("Niet alle berekende deelnemers zijn teruggespeeld.", "Not all calculated participants were replayed."))
    samen = hb._summarize_results(all_results)
    mean_t_air = float(np.mean([r["temp"] for r in t.interp]))
    samen["mean_t_air_race_window"] = mean_t_air
    samen["pct_dose_response_ehs"] = hb._dose_response_pct_patched(samen["cumulative_doses_all"],
                                                                    mean_t_air)
    samen["ehs_interval"] = ehs_interval(samen["cumulative_doses_all"], mean_t_air)
    samen["falmouth_ehs_per_1000"] = hb.falmouth_ehs_per_1000(mean_t_air)   # [2026-11-26] as in the event report
    n = samen["n_simulations_used"]
    samen["fi"] = {k: fraction_interval(samen[f"n_true_{k}_hits"], n) for k in ("ehs", "ehe", "eac")}
    # Thermisch kritiek: dezelfde regel als pct_thermal_only_critical in
    # run_monte_carlo_adult (piek-T_rect tijdens de loop > T_THERMAL_ONLY_CRITICAL),
    # hier als aantal zodat er een interval bij kan.
    piek_loop = np.array([np.nanmax([np.nan if r.get("t_rect") is None else float(r["t_rect"]) for r in res])
                          for res in all_results])
    k_th = int(np.sum(piek_loop > hm.T_THERMAL_ONLY_CRITICAL))
    if abs(100.0 * k_th / n - float(stats["pct_thermal_only_critical"])) > 1e-9:
        raise RuntimeError(vt("Telling thermisch kritiek wijkt af van pct_thermal_only_critical.", "Count of thermally critical differs from pct_thermal_only_critical."))
    samen["n_thermisch_kritiek"] = k_th
    samen["piek_loop"] = piek_loop
    samen["fi"]["thermisch"] = fraction_interval(k_th, n)
    gestopt = 100.0 * float(np.mean([any(bool(x.get("stopped")) for x in res) for res in all_results]))
    return {"stats": stats, "samen": samen, "results_df": results_df, "all_results": all_results,
            "pct_gestopt": gestopt}


class _WeerMeta:
    """Wat generate_event_report van ThermopoulosData gebruikt (metadata()),
    uit het weer van dit venster."""

    def __init__(self, weer: Weer):
        c = weer.city or {}
        self.city = c.get("name", "?")
        self._meta = {"city": self.city, "latitude": float(weer.lat), "longitude": float(weer.lon),
                      "timezone": weer.tz, "population": int(c.get("population") or 0)}

    def metadata(self) -> dict:
        return dict(self._meta)


def interp_voor_rapport(weer_df, interp: list) -> list:
    """[2026-11-26] Kopie van het interp-venster met de velden die het
    evenementrapport (tabel 2) zoekt maar die hestia_bridge.build_interp_data
    niet doorgeeft: landelijke luchttemperatuur, WBGT en UTCI uit het weerbestand
    (Thermopoulos_Data_Engine). Alleen voor het rapport; de simulatie gebruikt
    het oorspronkelijke interp-venster en verandert niet. Zelfde interpolatie
    als de bridge (lineair op de tijdas)."""
    import numpy as np
    if not interp:
        return interp
    idx = weer_df.index.astype("int64").to_numpy()
    q = pd.DatetimeIndex([e["time"] for e in interp]).astype("int64").to_numpy()
    extra = {}
    for kol, sleutel in (("T_air_rural", "temp_rural"), ("WBGT", "wbgt_precomputed"),
                         ("UTCI", "utci_precomputed")):
        if kol in weer_df.columns:
            v = pd.to_numeric(weer_df[kol], errors="coerce").to_numpy(dtype=float)
            ok = np.isfinite(v)
            if ok.sum() >= 2:
                extra[sleutel] = np.interp(q, idx[ok], v[ok])
    if not extra:
        return interp
    return [{**e, **{k: float(a[i]) for k, a in extra.items()}} for i, e in enumerate(interp)]


def maak_evenementrapport(t: PopTaak, r: dict, docx_pad) -> str:
    """[2026-11-25] Evenementrapport (Markdown + Word) met dezelfde gegevens die
    run_hestia.py aan generate_event_report.generate_report() geeft; plots via
    hestia_plots.generate_population_plots(), bridge via build_bridge_summary()
    op het interp-venster van deze berekening. Rekent niets opnieuw."""
    _, _, hm, _, _ = _suite()
    from pathlib import Path
    from generate_event_report import generate_report, _g
    from hestia_bridge import build_bridge_summary
    from hestia_plots import generate_population_plots
    from report_to_docx import export_report_docx
    docx_pad = Path(docx_pad)
    md_pad = docx_pad.with_suffix(".md")
    inv = t.inv
    start_time = f"{inv.datum} {inv.starttijd}"
    duur = afgeleide_duur(inv)
    figuren = docx_pad.with_name(docx_pad.stem + vt("_figuren", "_figures"))
    plots = generate_population_plots(r["all_results"], r["results_df"], r["stats"],
                                      _WeerMeta(t.weer).city, start_time, duur, str(figuren))
    activiteit = (vt(f"Per deelnemer eigen pace/MET, clo {_g(inv.clo)}; opgegeven nominale MET {_g(t.met)} "
                     f"wordt in deze modus niet gebruikt",
                     f"Own pace/MET per participant, clo {_g(inv.clo)}; the nominal MET {_g(t.met)} entered "
                     f"is not used in this mode") if inv.eigen_tempo else f"MET {_g(t.met)}, clo {_g(inv.clo)}")
    naam = f"{inv.evenement} {inv.datum}"
    with _vervang(hm, "ACTIVE_ENDPOINT", inv.eindpunt):
        tekst = generate_report(
            event_name=naam, data=_WeerMeta(t.weer), stats=r["stats"], results_df=r["results_df"],
            start_time=start_time, duration_hours=duur, activity_description=activiteit,
            n_simulations=len(r["all_results"]), output_path=str(md_pad),
            bridge_summary=build_bridge_summary(r["all_results"], t.interp),
            plot_paths=plots, interp_data=interp_voor_rapport(t.weer.df, t.interp),
            sample_pace=inv.eigen_tempo,
            event_dist_km=inv.afstand_km, training_factor=t.tf, acclimatization_factor=t.af,
            population=inv.populatie)
    export_report_docx(tekst, str(docx_pad), report_kind="facts", event_name=naam,
                       image_base_dir=str(figuren))
    return str(docx_pad)


def ehs_momenten(all_results) -> list:
    """Per deelnemer: of en wanneer het EHS-criterium voor het eerst geldt,
    met PRECIES de regel van hestia_bridge._summarize_results(): tijdens de loop
    T_rect >= 40,5 EN CO_reserve <= CO_RESERVE_CEILING_TOL op dezelfde tijdstap,
    of anders ehs_postfinish. (De suitevariabele conjunctie_eerste_min gebruikt
    '>' en telt de nafinish niet mee; daarom niet gebruikt, zodat de aantallen
    optellen tot het EHS-getal.) km alleen als het model afstand bijhoudt
    (RACE_DISTANCE_MODE, dus eigen tempo)."""
    _, _, hm, _, _ = _suite()
    tol = hm.CO_RESERVE_CEILING_TOL
    uit = []
    for res in all_results:
        hit = None
        for r in res:
            t, c = r.get("t_rect"), r.get("co_reserve")
            if (t is not None and c is not None and not np.isnan(t) and not np.isnan(c)
                    and t >= 40.5 and c <= tol):
                km = r.get("distance_km")
                hit = {"fase": "loop", "tijd": pd.Timestamp(r["time"]),
                       "km": float(km) if km is not None and np.isfinite(km) else None}
                break
        if hit is None and res and bool(res[-1].get("ehs_postfinish", False)):
            km = res[-1].get("race_distance_km")
            hit = {"fase": "nafinish", "tijd": pd.Timestamp(res[-1]["time"]),
                   "km": float(km) if km is not None and np.isfinite(km) else None}
        uit.append(hit)
    return uit


def per_groep(populatie, momenten) -> dict:
    """EHS-aantal per leeftijdsgroep (hestia_model.get_age_group) en geslacht,
    met Clopper-Pearson-interval (uncertainty.fraction_interval)."""
    _, _, hm, _, _ = _suite()
    from uncertainty import fraction_interval
    groepen = {}
    for p, m in zip(populatie, momenten):
        k = (hm.get_age_group(p.age), p.gender)
        g = groepen.setdefault(k, [0, 0])
        g[0] += m is not None
        g[1] += 1
    return {k: fraction_interval(h, n) for k, (h, n) in sorted(groepen.items())}


def risicoklassen() -> list[tuple[float, str, str]]:
    """Kleurgrenzen voor 'verwachte collapsen per 1000', afgelezen uit de suite
    zelf (HESTIA_CVR_Console._per1000_color, gebruikt in
    print_cvr_population_summary) door de functie af te tasten. Geeft
    [(ondergrens, suite-kleur, label), ...]."""
    import HESTIA_CVR_Console as C
    from colorama import Fore
    naam = {Fore.GREEN: "GREEN", Fore.YELLOW: "YELLOW", Fore.MAGENTA: "MAGENTA", Fore.RED: "RED"}
    v = np.round(np.arange(0.0, 20.0, 0.01), 2)
    c = [naam[C._per1000_color(float(x))] for x in v]
    grenzen = [(0.0, c[0])] + [(float(v[i]), c[i]) for i in range(1, len(v)) if c[i] != c[i - 1]]
    labels = {"GREEN": vt("laag", "low"), "YELLOW": vt("matig", "moderate"), "MAGENTA": vt("hoog", "high"), "RED": vt("extreem", "extreme")}
    return [(g, k, labels[k]) for g, k in grenzen]


def top_tien(all_results, populatie, n=10) -> list[int]:
    """Indices van de n deelnemers met de hoogste piek-T_rect over loop +
    nafinish (hestia_model.collapse_extremes, dezelfde maat als de collaps-
    logistiek)."""
    _, _, hm, _, _ = _suite()
    piek = [hm.collapse_extremes(res)[0] for res in all_results]
    return [int(i) for i in np.argsort(np.nan_to_num(piek, nan=-1.0))[::-1][:n]]


def starttijden(van: str, tot: str, stap_min: int) -> list[str]:
    a = pd.Timestamp(f"2000-01-01 {van}")
    b = pd.Timestamp(f"2000-01-01 {tot}")
    if b < a or stap_min < 5:
        raise ValueError(vt("starttijden: 'tot' na 'van', stap minimaal 5 min", "start times: 'to' after 'from', step at least 5 min"))
    return [x.strftime("%H:%M") for x in pd.date_range(a, b, freq=f"{int(stap_min)}min")]


# =============================================================================
# 3. GEBRUIKERSINTERFACE
# =============================================================================
def _start_ui(na_start=None):
    """na_start: optioneel callable(app, root), alleen voor tests."""
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import tkinter.font as tkfont
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.dates as mdates
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    hl, ie, hm, hb, de = _suite()
    import Klimatos_ClimateShift as K
    import ui_gemeen as ug

    LETTER = 12
    matplotlib.rcParams.update({"font.size": 11, "axes.titlesize": 12, "axes.titleweight": "bold",
                                "axes.grid": True, "grid.alpha": 0.3, "legend.fontsize": 9})
    KL = {"lijn": "#1f5fa8", "rood": "#c0392b", "oranje": "#e67e22", "geel": "#d4ac0d",
          "grijs": "#7f8c8d"}
    PROFIELEN = adaptatieprofielen()
    PROFIEL_NL = [vt("Beginner / niet geacclimatiseerd", "Beginner / not acclimatised"), vt("Laag-gemiddeld / deels geacclimatiseerd", "Low-average / partly acclimatised"),
                  vt("Gemiddeld / goed geacclimatiseerd", "Average / well acclimatised"), vt("Gevorderd / volledig geacclimatiseerd", "Advanced / fully acclimatised")]
    ACT = hm.MET_ACTIVITIES_ADULT
    ACT_TXT = {k: f"{k}. {v['description']} – {hl.nl(v['met'])} MET" for k, v in ACT.items()}
    CLO = hm.CLO_OPTIONS_ADULT
    CLO_TXT = {k: f"{v['description']} – {hl.nl(v['clo'])} clo" for k, v in CLO.items()}
    EP = hm.COLLAPSE_ENDPOINTS
    EP_TXT = {k: f"{v['label']} ({v['status']})" for k, v in EP.items()}

    nl = getal   # komma (NL) of punt (EN), taal.py

    KLASSEN = risicoklassen()
    KLASSE_KLEUR = {"GREEN": "#27ae60", "YELLOW": "#f1c40f", "MAGENTA": "#c2185b", "RED": "#c0392b"}

    def klasse(v):
        k = KLASSEN[0]
        for g in KLASSEN:
            if v >= g[0]:
                k = g
        return k

    class App:
        def __init__(self, root):
            self.root = root
            root.title(vt("HESTIA · populatie-analyse voor evenementen  (research software)", "HESTIA · population analysis for events  (research software)"))
            for naam in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont"):
                try:
                    tkfont.nametofont(naam).configure(size=LETTER)
                except tk.TclError:
                    pass
            ttk.Style().configure("TLabelframe.Label", font=("TkDefaultFont", LETTER, "bold"))
            bw, bh = root.winfo_screenwidth(), root.winfo_screenheight()
            root.geometry(f"{min(1800, bw - 40)}x{min(1040, bh - 80)}+10+10")
            ug.maximaliseer(root)
            self.weerbron = WeerBron()
            self.kandidaten = []
            self.gen = 0
            self.taak: Optional[PopTaak] = None
            self.resultaat = None
            self.futures = []
            self.q = queue.Queue()
            self._plan = None
            self._weer_sleutel = None
            self._weer = None
            self._laatst = 0.0
            self.extra = None
            self.pool = ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1),
                                            initializer=_werker_init)
            for _ in range(self.pool._max_workers):
                self.pool.submit(_opwarmen)
            self._bouw()
            self._poll()
            root.protocol("WM_DELETE_WINDOW", self._sluit)

        # ------------------------------------------------------------ opbouw
        def _bouw(self):
            links = ttk.Frame(self.root, padding=6)
            links.pack(side="left", fill="y")
            canvas = tk.Canvas(links, width=ug.px(self.root, 520), highlightthickness=0)
            sb = ttk.Scrollbar(links, orient="vertical", command=canvas.yview)
            self.form = ttk.Frame(canvas)
            self.form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=self.form, anchor="nw")
            canvas.configure(yscrollcommand=sb.set)
            canvas.pack(side="left", fill="y")
            sb.pack(side="left", fill="y")
            canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
            canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-2, "units"))
            canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(2, "units"))
            self.v, self.w = {}, {}

            ug.invoer_legenda(self.form, LETTER)
            r = self._sectie(vt("Evenement", "Event"), "verplicht")
            self._tekst(r, "evenement", vt("Naam", "Name"), vt("Evenement", "Event"))
            self._tekst(r, "afstand", vt("Afstand (km)", "Distance (km)"), getal(16.1))
            self._keuze(r, "tempo", vt("Tempo", "Pace"),
                        [vt("eigen tempo per deelnemer", "individual pace per participant"), vt("één gedeelde activiteit", "one shared activity")],
                        vt("eigen tempo per deelnemer", "individual pace per participant"))
            self._keuze(r, "activiteit", vt("Activiteit", "Activity"), list(ACT_TXT.values()), ACT_TXT[11], breed=38)
            self._tekst(r, "duur", vt("Duur (uur)", "Duration (hours)"), "", hint=vt("leeg: afgeleid", "empty: derived"))
            self.lbl_duur = ttk.Label(r, text="", foreground="#555", wraplength=440, justify="left")
            self.lbl_duur.pack(anchor="w", padx=4)

            r = self._sectie(vt("Deelnemers", "Participants"), "verplicht")
            self._keuze(r, "populatie", vt("Populatie", "Population"), [vt("lopers", "runners"), vt("wandelaars (Vierdaagse-type)", "walkers (Four Days type)")], vt("lopers", "runners"))
            self._keuze(r, "kleding", vt("Kleding", "Clothing"), list(CLO_TXT.values()), CLO_TXT[1], breed=38)
            self._keuze(r, "profiel", vt("Training/acclimatisatie", "Training/acclimatisation"), PROFIEL_NL, PROFIEL_NL[2], breed=40)

            r = self._sectie(vt("Datum, tijd, plaats en weer", "Date, time, location and weather"), "verplicht")
            self._tekst(r, "datum", vt("Datum (JJJJ-MM-DD)", "Date (YYYY-MM-DD)"), pd.Timestamp.now().strftime("%Y-%m-%d"),
                        weer=True)
            rij = self._rij(r, vt("Starttijd", "Start time"))
            self.v["start_min"] = tk.DoubleVar(value=9 * 60)
            self.v["starttijd"] = tk.StringVar(value="09:00")
            ent = ttk.Entry(rij, textvariable=self.v["starttijd"], width=6)
            ent.pack(side="left")
            ent.bind("<Return>", lambda e: self._tijd_uit_tekst())
            ent.bind("<FocusOut>", lambda e: self._tijd_uit_tekst())
            ttk.Scale(r, from_=0, to=23 * 60 + 55, variable=self.v["start_min"],
                      command=lambda x: self._schuif()).pack(fill="x", padx=4, pady=(0, 4))
            self._keuze(r, "bron", vt("Weerbron", "Weather source"), ["online (Open-Meteo)", vt("Data Engine-bestand", "Data Engine file")],
                        "online (Open-Meteo)", weer=True)
            rij = self._rij(r, vt("Plaats", "Location"))
            self.v["plaats"] = tk.StringVar(value="Amsterdam")
            pe = ttk.Entry(rij, textvariable=self.v["plaats"], width=13)
            pe.pack(side="left")
            pe.bind("<Return>", lambda e: self._zoek_plaats())
            ttk.Button(rij, text=vt("Zoek", "Search"), command=self._zoek_plaats, width=6).pack(side="left", padx=3)
            self.v["kandidaat"] = tk.StringVar(value="")
            self.cb_kand = ttk.Combobox(r, textvariable=self.v["kandidaat"], state="readonly", width=40)
            self.cb_kand.pack(fill="x", padx=4, pady=2)
            self.cb_kand.bind("<<ComboboxSelected>>", lambda e: self._weer_gewijzigd())
            rij = self._rij(r, vt("Bestand", "File"))
            self.v["excel"] = tk.StringVar(value="")
            ttk.Entry(rij, textvariable=self.v["excel"], width=13).pack(side="left")
            ttk.Button(rij, text=vt("Kies…", "Choose…"), command=self._kies_excel, width=6).pack(side="left", padx=3)
            self._keuze(r, "route", "Route", [vt("stad", "urban"), vt("platteland", "rural")], vt("stad", "urban"), weer=True)

            r = self._sectie(vt("Risicocriterium en berekening", "Risk criterion and calculation"), "model",
                             vt("Standaard van de suite. Het eindpunt bepaalt waarop de risicobalk rekent; "
                             "meer deelnemers = kleinere steekproefmarge, maar langzamer.",
                                "Suite default. The endpoint decides what the risk bar is based on; "
                             "more participants = smaller sampling margin, but slower."))
            self._keuze(r, "eindpunt", vt("Eindpunt collapsrisico", "Collapse-risk endpoint"), list(EP_TXT.values()), EP_TXT["ehs"],
                        breed=38)
            self._tekst(r, "n_snel", vt("Live (snel): deelnemers", "Live (quick): participants"), str(hb.QUICK_N))
            self._tekst(r, "n_vol", vt("Volledige run: deelnemers", "Full run: participants"), "1000", herreken=False)
            self._tekst(r, "seed", "Seed", "42")
            rij = ttk.Frame(r)
            rij.pack(fill="x", pady=4)
            ttk.Button(rij, text=vt("Volledige run starten", "Start full run"), command=self._volledig).pack(side="left", padx=2)
            ttk.Button(rij, text=vt("Excel-export", "Excel export"), command=self._export).pack(side="left", padx=2)
            ttk.Button(rij, text=vt("Evenementrapport (Word)", "Event report (Word)"), command=self._rapport).pack(side="left", padx=2)

            rechts = ttk.Frame(self.root, padding=(4, 6))
            rechts.pack(side="left", fill="both", expand=True)
            boven = ttk.Frame(rechts)
            boven.pack(fill="x")
            # Knoppen eerst plaatsen: dan blijven ze altijd zichtbaar, ook bij een lange kop- of statustekst.
            self.pb = ttk.Progressbar(boven, length=ug.px(self.root, 120), maximum=1.0)
            self.pb.pack(side="right")
            ttk.Button(boven, text=vt("Extra grafieken", "More charts"), command=self._open_extra).pack(
                side="right", padx=8)
            self.lbl_kop = tk.Label(boven, text="  —  ", font=("TkDefaultFont", LETTER + 1, "bold"),
                                    bg="#dddddd", padx=10, pady=4)
            self.lbl_kop.pack(side="left")
            self.lbl_status = ttk.Label(rechts, text="", font=("TkDefaultFont", LETTER - 1), foreground="#444")
            self.lbl_status.pack(fill="x", padx=4, pady=(2, 0))

            self.nb = ttk.Notebook(rechts)
            self.nb.pack(fill="both", expand=True, pady=(4, 0))
            tab_u = ttk.Frame(self.nb, padding=(2, 4))
            tab_g = ttk.Frame(self.nb, padding=(2, 2))
            self.nb.add(tab_u, text=vt("  Uitkomst  ", "  Result  "))
            self.nb.add(tab_g, text=vt("  Grafieken  ", "  Charts  "))
            ug.tab_uitleg(tab_u, vt("De uitkomst in het kort: risicobalk, kerncijfers en de volledige toelichting. "
                                 "Het tabblad Grafieken toont het weer en de verdeling over de deelnemers. De knop "
                                 "'Extra grafieken' (rechtsboven) opent o.a. de 10 deelnemers met de hoogste "
                                 "kerntemperatuur, scatter en drempels, wanneer en waar, en starttijden vergelijken.",
                                    "The result in brief: risk bar, key figures and the full explanation. "
                                 "The Charts tab shows the weather and the distribution over the participants. The "
                                 "'More charts' button (top right) opens, among others, the 10 participants with the "
                                 "highest core temperature, scatter and thresholds, when and where, and compare start times."),
                         LETTER)
            self.rb_fig = Figure(figsize=(12, 1.1), dpi=96)
            self.rb_ax = self.rb_fig.add_axes([0.02, 0.36, 0.96, 0.32])
            self.rb_canvas = FigureCanvasTkAgg(self.rb_fig, master=tab_u)
            self.rb_canvas.get_tk_widget().pack(fill="x")
            self._teken_risicobalk(None)
            self.tegels = ug.Tegels(tab_u, LETTER)
            self.tegels.pack(fill="x", pady=(2, 4))
            self.herkomst = ug.Herkomst(tab_u, LETTER)
            self.herkomst.pack(side="bottom", fill="x", pady=(4, 0))

            self.fig = Figure(figsize=(12, 7.6), dpi=96, constrained_layout=True)
            gs = self.fig.add_gridspec(3, 2)
            self.ax = {"t": self.fig.add_subplot(gs[0, 0]), "wbgt": self.fig.add_subplot(gs[0, 1]),
                       "rh": self.fig.add_subplot(gs[1, 0]), "wind": self.fig.add_subplot(gs[1, 1]),
                       "kern": self.fig.add_subplot(gs[2, 0]), "co": self.fig.add_subplot(gs[2, 1])}
            onder = ttk.Frame(tab_u)
            onder.pack(fill="both", expand=True)
            self.canvas = FigureCanvasTkAgg(self.fig, master=tab_g)
            self.canvas.get_tk_widget().pack(fill="both", expand=True)
            self.txt = tk.Text(onder, height=6, wrap="word", font=("TkDefaultFont", LETTER),
                               relief="flat", background="#f6f6f6", padx=8, pady=6, spacing1=2)
            tsb = ttk.Scrollbar(onder, orient="vertical", command=self.txt.yview)
            self.txt.configure(yscrollcommand=tsb.set)
            self.txt.pack(side="left", fill="both", expand=True)
            tsb.pack(side="left", fill="y")
            self.txt.tag_configure("vet", font=("TkDefaultFont", LETTER, "bold"))
            self.txt.tag_configure("waarsch", foreground="#9c4400")

            self._modus()
            self.root.after(300, self._zoek_plaats)

        def _sectie(self, titel, soort="verplicht", uitleg=""):
            return ug.sectie(self.form, titel, soort, LETTER, uitleg)

        def _rij(self, ouder, label):
            rij = ttk.Frame(ouder)
            rij.pack(fill="x", pady=1)
            ttk.Label(rij, text=label, width=20).pack(side="left")
            return rij

        def _tekst(self, ouder, k, label, std, hint="", weer=False, herreken=True):
            rij = self._rij(ouder, label)
            self.v[k] = tk.StringVar(value=std)
            e = ttk.Entry(rij, textvariable=self.v[k], width=12)
            e.pack(side="left")
            self.w[k] = e
            if hint:
                ttk.Label(rij, text=hint, foreground="#777").pack(side="left", padx=4)
            if herreken:
                cb = self._weer_gewijzigd if weer else self._gewijzigd
                self.v[k].trace_add("write", lambda *a: cb())

        def _keuze(self, ouder, k, label, waarden, std, weer=False, breed=None):
            if breed:
                ttk.Label(ouder, text=label).pack(anchor="w")
                rij = ttk.Frame(ouder)
                rij.pack(fill="x", pady=(0, 3))
            else:
                rij = self._rij(ouder, label)
            self.v[k] = tk.StringVar(value=std)
            cb = ttk.Combobox(rij, textvariable=self.v[k], values=waarden, state="readonly",
                              width=breed or max(10, max(len(x) for x in waarden) - 2))
            cb.pack(side="left", padx=(16 if breed else 0, 0))
            self.w[k] = cb
            f = self._weer_gewijzigd if weer else self._gewijzigd
            self.v[k].trace_add("write", lambda *a: f())

        # ---------------------------------------------------------- invoer
        def _f(self, k, opt=False):
            s = self.v[k].get().strip().replace(",", ".")
            if s == "":
                if opt:
                    return None
                raise ValueError(vt(f"'{k}' is leeg", f"'{k}' is empty"))
            return float(s)

        def _sleutel(self, tekst_map, waarde):
            for k, t in tekst_map.items():
                if t == waarde:
                    return k
            raise ValueError(vt("onbekende keuze", "unknown choice"))

        def _invoer(self) -> PopInvoer:
            return PopInvoer(
                evenement=self.v["evenement"].get().strip() or vt("Evenement", "Event"),
                populatie="wandelaars" if self.v["populatie"].get().startswith(vt("wandel", "walk")) else "lopers",
                afstand_km=self._f("afstand"),
                eigen_tempo=self.v["tempo"].get().startswith(vt("eigen", "individual")),
                activiteit=self._sleutel(ACT_TXT, self.v["activiteit"].get()),
                duur_h=self._f("duur", True),
                clo=float(CLO[self._sleutel(CLO_TXT, self.v["kleding"].get())]["clo"]),
                profiel=PROFIEL_NL.index(self.v["profiel"].get()),
                eindpunt=self._sleutel(EP_TXT, self.v["eindpunt"].get()),
                datum=pd.Timestamp(self.v["datum"].get().strip()).strftime("%Y-%m-%d"),
                starttijd=self.v["starttijd"].get().strip())

        def _route(self) -> str:
            """Sleutel voor de suite ('stad'/'platteland'), los van de getoonde taal."""
            return ("stad", "platteland")[max(0, self.w["route"].current())]

        def _kandidaat(self):
            i = self.cb_kand.current()
            return self.kandidaten[i] if 0 <= i < len(self.kandidaten) else None

        def _modus(self):
            """Wandelaars: geen eigen tempo (generate_base_population staat het
            niet toe). Eigen tempo: activiteit en duur niet gebruikt."""
            wandel = self.v["populatie"].get().startswith(vt("wandel", "walk"))
            if wandel and self.v["tempo"].get().startswith(vt("eigen", "individual")):
                self.v["tempo"].set(vt("één gedeelde activiteit", "one shared activity"))
                self.v["activiteit"].set(ACT_TXT[14])
            self.w["tempo"].state(["disabled"] if wandel else ["!disabled"])
            eigen = self.v["tempo"].get().startswith(vt("eigen", "individual"))
            for k in ("activiteit", "duur"):
                self.w[k].state(["disabled"] if eigen else ["!disabled"])
            try:
                inv = self._invoer()
                d = afgeleide_duur(inv)
                if eigen:
                    tekst = (vt(f"eigen tempo per deelnemer; weervenster {nl(d, 2)} u "
                             f"(langzaamste deelnemer + bezemwagen)",
                                f"individual pace per participant; weather window {nl(d, 2)} h "
                             f"(slowest participant + sweeper bus)"))
                else:
                    tekst = vt(f"duur {nl(d, 2)} u bij {nl(ACT[inv.activiteit]['speed_kmh'])} km/u", f"duration {nl(d, 2)} h at {nl(ACT[inv.activiteit]['speed_kmh'])} km/h")
                self.lbl_duur.config(text=tekst)
            except Exception:
                self.lbl_duur.config(text="")

        # --------------------------------------------------- gebeurtenissen
        def _schuif(self):
            m = int(round(self.v["start_min"].get() / 5.0)) * 5
            t = f"{m // 60:02d}:{m % 60:02d}"
            if self.v["starttijd"].get() != t:
                self.v["starttijd"].set(t)
                self._gewijzigd(vertraging=300)

        def _tijd_uit_tekst(self):
            try:
                u, m = self.v["starttijd"].get().strip().split(":")
                self.v["start_min"].set(int(u) * 60 + int(m))
                self._gewijzigd()
            except Exception:
                self._fout(vt("Starttijd onleesbaar; gebruik UU:MM.", "Start time unreadable; use HH:MM."))

        def _gewijzigd(self, vertraging=700):
            self._modus()
            if self._plan is not None:
                self.root.after_cancel(self._plan)
            self._plan = self.root.after(vertraging, lambda: self._herbereken(False))

        def _weer_gewijzigd(self):
            self._weer_sleutel = None
            self._gewijzigd()

        def _zoek_plaats(self):
            naam = self.v["plaats"].get().strip()
            if not naam or self.v["bron"].get().startswith("Data"):
                return
            self.lbl_status.config(text=vt(f"Plaats zoeken: {naam} …", f"Searching location: {naam} …"))

            def werk():
                try:
                    self.q.put(("kandidaten", de.geocode_city_candidates(naam)))
                except Exception as ex:
                    self.q.put(("fout", vt(f"Plaats zoeken mislukt: {ex}", f"Location search failed: {ex}"), None))
            threading.Thread(target=werk, daemon=True).start()

        def _kies_excel(self):
            p = filedialog.askopenfilename(title=vt("Data Engine-bestand", "Data Engine file"),
                                           filetypes=[("Excel", "*.xlsx"), (vt("Alle", "All"), "*.*")],
                                           initialdir=str(HIER))
            if p:
                self.v["excel"].set(p)
                self.v["bron"].set(vt("Data Engine-bestand", "Data Engine file"))

        def _volledig(self):
            self._herbereken(True)

        # ------------------------------------------------------- berekenen
        def _herbereken(self, volledig):
            self._plan = None
            try:
                inv = self._invoer()
                fouten = valideer(inv)
                if fouten:
                    raise ValueError("; ".join(fouten))
                n = int(self._f("n_vol" if volledig else "n_snel"))
                seed = int(self._f("seed"))
                if not 1 <= n <= 20000:
                    raise ValueError(vt("aantal deelnemers: 1 t/m 20000", "number of participants: 1 to 20000"))
            except Exception as ex:
                self._fout(vt(f"Invoer: {ex}", f"Input: {ex}"))
                return
            excel = self.v["bron"].get().startswith("Data")
            route = self._route()
            s, e = venster(inv)
            if excel:
                pad = self.v["excel"].get().strip()
                if not pad:
                    self._fout(vt("Kies een Data Engine-bestand.", "Choose a Data Engine file."))
                    return
                sleutel = ("excel", pad, route)
            else:
                kand = self._kandidaat()
                if kand is None:
                    self._fout(vt("Kies eerst een plaats (Zoek).", "First choose a location (Search)."))
                    return
                sleutel = ("online", kand.get("id", (kand["latitude"], kand["longitude"])), inv.datum, route)
            self._annuleer()
            self.gen += 1
            gen = self.gen

            def start(w):
                self._start(gen, inv, w, n, seed, volledig)

            if not excel and sleutel == self._weer_sleutel and self._weer is not None:
                start(self._weer)
                return

            def laad():
                try:
                    if excel:
                        w = self.weerbron.excel(pad, s, e + pd.Timedelta(hours=1), route)
                    else:
                        w = self.weerbron.online(kand, inv.datum, route)
                    self.q.put(("weer", gen, sleutel, w, start))
                except Exception as ex:
                    self.q.put(("fout", vt(f"Weer: {ex}", f"Weather: {ex}"), gen))
            self.lbl_status.config(text=vt("Weer laden …", "Loading weather …"))
            threading.Thread(target=laad, daemon=True).start()

        def _start(self, gen, inv, weer, n, seed, volledig):
            if gen != self.gen:
                return
            self.lbl_status.config(text=vt("Deelnemersveld trekken …", "Drawing the field of participants …"))
            self.root.update_idletasks()
            try:
                t = bereid_voor(gen, inv, weer, n, seed, volledig)
            except Exception as ex:
                self._fout(str(ex))
                return
            self.taak, self.resultaat = t, None
            self.futures = [self.pool.submit(_pop_lid, a) for a in taak_argumenten(t)]
            for f in self.futures:
                f.add_done_callback(self._klaar)
            self._teken_weer(t)
            self._teken_pop(t)
            self._kop(None)
            self._toon_tekst()
            self.pb["value"] = 0
            self.lbl_status.config(text=f"{'Volledige run' if volledig else 'Snelle schatting'}: 0/{t.n}")

        def _klaar(self, f):
            if f.cancelled():
                return
            try:
                self.q.put(("lid",) + f.result())
            except Exception as ex:
                self.q.put(("fout", vt(f"Deelnemer mislukt: {ex}\n{traceback.format_exc()}", f"Participant failed: {ex}\n{traceback.format_exc()}"), None))

        def _annuleer(self):
            for f in self.futures:
                f.cancel()
            self.futures = []

        def _poll(self):
            try:
                self._poll_stap()
            except Exception as ex:
                self._fout(vt(f"Interne fout: {ex}\n{traceback.format_exc()}", f"Internal error: {ex}\n{traceback.format_exc()}"))
            finally:
                self.root.after(250, self._poll)

        def _poll_stap(self):
            nieuw = False
            try:
                while True:
                    m = self.q.get_nowait()
                    s = m[0]
                    if s == "lid":
                        _, gen, i, res = m
                        if self.taak is not None and gen == self.taak.gen == self.gen:
                            self.taak.res[i] = res
                            nieuw = True
                    elif s == "weer":
                        _, gen, sleutel, w, verder = m
                        if gen == self.gen:
                            if sleutel[0] == "online":
                                self._weer_sleutel, self._weer = sleutel, w
                            verder(w)
                    elif s == "kandidaten":
                        self.kandidaten = m[1]
                        self.cb_kand["values"] = [
                            vt(f"{k.get('name')}, {k.get('admin1', '')} ({k.get('country_code', '')})"
                            f" – {k.get('population', 0) or 0:,} inw.",
                               f"{k.get('name')}, {k.get('admin1', '')} ({k.get('country_code', '')})"
                            f" – {k.get('population', 0) or 0:,} inhabitants").replace(",", "." if not engels() else ",")
                            for k in self.kandidaten]
                        if self.kandidaten:
                            self.cb_kand.current(0)
                        self._weer_gewijzigd()
                    elif s == "eind":
                        _, gen, r = m
                        if gen == self.gen:
                            self.resultaat = r
                            self._teken_pop(self.taak)
                            self._kop(r)
                            self._toon_tekst()
                            self._teken_extra()
                            t = self.taak
                            self.lbl_status.config(
                                text=vt(f"Klaar: {'volledige run' if t.volledig else 'snelle schatting'}, "
                                     f"n = {t.n} (seed {t.seed})",
                                        f"Done: {'full run' if t.volledig else 'quick estimate'}, "
                                     f"n = {t.n} (seed {t.seed})"))
                    elif s == "sweep":
                        _, sg, st, d = m
                        sw = getattr(self, "sweep", None)
                        if sw and sw["gen"] == sg:
                            sw["rijen"][st] = d
                            self._teken_sweep()
                    elif s == "sweep_status":
                        _, sg, tekst = m
                        sw = getattr(self, "sweep", None)
                        if sw and sw["gen"] == sg and self.extra is not None:
                            self.lbl_sweep.config(text=tekst)
                    elif s == "fout":
                        if m[2] is None or m[2] == self.gen:
                            self._fout(m[1])
            except queue.Empty:
                pass
            if nieuw and self.taak is not None:
                t = self.taak
                k = len(t.res)
                self.pb["value"] = k / t.n
                self.lbl_status.config(
                    text=f"{'Volledige run' if t.volledig else 'Snelle schatting'}: {k}/{t.n}")
                self.tegels.leeg(vt(f"Berekenen … {k}/{t.n} deelnemers. De grafieken tonen de voorlopige verdeling.", f"Calculating … {k}/{t.n} participants. The charts show the provisional distribution."))
                nu = time.monotonic()
                if k == t.n or nu - self._laatst >= 1.0:
                    self._laatst = nu
                    self._teken_pop(t)
                    self._teken_extra()
                if k == t.n:
                    self.lbl_status.config(text=vt("Populatiestatistiek (run_monte_carlo_adult) …", "Population statistics (run_monte_carlo_adult) …"))
                    gen = t.gen

                    def werk():
                        try:
                            self.q.put(("eind", gen, eindresultaat(t)))
                        except Exception as ex:
                            self.q.put(("fout", vt(f"Samenvatten mislukt: {ex}\n{traceback.format_exc()}", f"Summary failed: {ex}\n{traceback.format_exc()}"), gen))
                    threading.Thread(target=werk, daemon=True).start()

        # ------------------------------------------------------- tekenen
        def _x(self, ax):
            ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

        def _tijden(self, t: PopTaak):
            return [pd.Timestamp(r["time"]).tz_localize(None) for r in t.interp]

        def _teken_weer(self, t: PopTaak):
            m = t.meteo
            tijd = [pd.Timestamp(x).tz_localize(None) for x in m["time"]]
            for k in ("t", "wbgt", "rh", "wind"):
                self.ax[k].clear()
            a = self.ax["t"]
            route = self._route()
            a.plot(tijd, m["t_air"], color=KL["rood"], lw=2,
                   label=vt("luchttemp. ", "air temp. ") + (vt("stad (met UHI)", "urban (with UHI)") if route == "stad" else vt("platteland", "rural")))
            if route == "stad" and np.isfinite(m.get("t_air_rural", [np.nan])).any():
                a.plot(tijd, m["t_air_rural"], color=KL["grijs"], lw=1, ls="--", label=vt("platteland (zonder UHI)", "rural (without UHI)"))
            a.set_title(vt("Luchttemperatuur", "Air temperature"))
            a.set_ylabel("°C")
            a.legend(loc="best")
            a = self.ax["wbgt"]
            a.plot(tijd, m["wbgt"], color=KL["oranje"], lw=2)
            for y, c in ((18, KL["geel"]), (23, KL["oranje"]), (28, KL["rood"])):
                a.axhline(y, color=c, lw=0.8, ls=":")
            a.set_title("WBGT")
            a.set_ylabel("°C")
            a = self.ax["rh"]
            a.plot(tijd, m["rh"], color="#2471a3", lw=2)
            a.set_title(vt("Relatieve luchtvochtigheid", "Relative humidity"))
            a.set_ylabel("%")
            a = self.ax["wind"]
            a.plot(tijd, m["wind10"], color=KL["grijs"], lw=1.5, label=vt("10 m (weerdata)", "10 m (weather data)"))
            ti = self._tijden(t)
            a.plot(ti, t.wind15, color="#117a65", lw=2, label=vt("1,5 m (zoals het model rekent)", "1.5 m (as the model calculates)"))
            a.set_title(vt("Windsnelheid", "Wind speed"))
            a.set_ylabel("m/s")
            a.set_ylim(bottom=0)
            a.legend(loc="best")
            for k in ("t", "wbgt", "rh", "wind"):
                self._x(self.ax[k])

        def _teken_pop(self, t: PopTaak):
            for k in ("kern", "co"):
                self.ax[k].clear()
            b = banden(t)
            ti = self._tijden(t)
            voorlopig = self.resultaat is None
            n_txt = (vt(f"voorlopig, n = {len(t.res)}/{t.n}", f"provisional, n = {len(t.res)}/{t.n}") if voorlopig else f"n = {t.n}")
            if b is not None:
                lengte = len(b["t"][0])
                x = ti[:lengte]
                for k, (gem, lo, hi), titel, eenheid in (
                        ("kern", b["t"], vt("Kerntemperatuur T_rect, populatie", "Core temperature T_rect, population"), "°C"),
                        ("co", b["co"], vt("CO_reserve, populatie", "CO_reserve, population"), "L/min")):
                    ax = self.ax[k]
                    ax.fill_between(x, lo[:len(x)], hi[:len(x)], color=KL["lijn"], alpha=0.18, lw=0,
                                    label="p5–p95")
                    ax.plot(x, gem[:len(x)], color=KL["lijn"], lw=2, label=vt("gemiddelde", "mean"))
                    ax.set_title(f"{titel}   ({n_txt})")
                    ax.set_ylabel(eenheid)
                k = self.ax["kern"]
                k.axhline(39.5, color=KL["oranje"], lw=1, ls=":")
                k.axhline(40.5, color=KL["rood"], lw=1, ls=":")
                self._lijn42(k)
                k.legend(loc="lower right")
                c = self.ax["co"]
                c.axhline(2.0, color=KL["oranje"], lw=1, ls=":")
                c.axhline(0.0, color=KL["rood"], lw=1.2)
                if t.inv.eigen_tempo:
                    k.text(0.01, 0.98, vt("band over deelnemers die nog lopen", "band over participants still running"), transform=k.transAxes,
                           va="top", fontsize=9, color="#555")
            else:
                for k, titel in (("kern", vt("Kerntemperatuur T_rect, populatie", "Core temperature T_rect, population")), ("co", vt("CO_reserve, populatie", "CO_reserve, population"))):
                    self.ax[k].set_title(vt(f"{titel}   (berekenen …)", f"{titel}   (calculating …)"))
            for k in self.ax:
                self.ax[k].set_xlim(ti[0], ti[-1])
                self._x(self.ax[k])
            self.canvas.draw_idle()

        def _lijn42(self, ax, x0=None):
            """Lijn bij T_THERMAL_ONLY_CRITICAL; alleen tonen als de as er komt."""
            g = hm.T_THERMAL_ONLY_CRITICAL
            lo, hi = ax.get_ylim()
            if hi >= g - 0.3:
                ax.axhline(g, color="#6e0b0b", lw=1.4, ls="--")
                ax.text(0.01, g, vt(f" {nl(g, 0)} °C: model buiten getoetst gebied", f" {nl(g, 0)} °C: model outside its tested range"), transform=ax.get_yaxis_transform(),
                        va="bottom", fontsize=8, color="#6e0b0b")
                ax.set_ylim(lo, max(hi, g + 0.3))

        def _teken_risicobalk(self, r):
            """Verwachte collapsen per 1000 (gekozen eindpunt) op een log-schaal met de
            kleurklassen van HESTIA_CVR_Console._per1000_color."""
            a = self.rb_ax
            a.clear()
            lo_x, hi_x = 0.05, 1000.0
            grenzen = [g[0] for g in KLASSEN] + [hi_x]
            for (g, k, lab), g2 in zip(KLASSEN, grenzen[1:]):
                x0 = max(g, lo_x)
                a.axvspan(x0, g2, color=KLASSE_KLEUR[k], alpha=0.85, lw=0)
                xm = np.sqrt(x0 * g2)
                a.text(xm, 0.5, lab, ha="center", va="center", fontsize=11, fontweight="bold",
                       color="black" if k == "YELLOW" else "white")
            for g in grenzen[1:-1]:
                a.text(g, -0.12, nl(g), ha="center", va="top", fontsize=9, transform=a.get_xaxis_transform())
            ref = EP["hospitalisation"]["p_obs"] * 1000
            a.axvline(ref, color="black", lw=1, ls="--")
            a.text(ref, 1.06, f"DtD 2024: {nl(ref, 2)}", ha="center", va="bottom", fontsize=8,
                   transform=a.get_xaxis_transform())
            a.set_xscale("log")
            a.set_xlim(lo_x, hi_x)
            a.set_ylim(0, 1)
            a.set_yticks([])
            a.set_xticks([])
            a.minorticks_off()
            if r is None:
                titel = vt("Ter vergelijking: gekalibreerd collapsrisico per 1000 — berekenen …", "For comparison: calibrated collapse risk per 1000 — calculating …")
            else:
                st = r["stats"]
                v = float(st.get("expected_collapses_per_1000", np.nan))
                vlo = float(st.get("p_collapse_mean_lo", np.nan)) * 10
                vhi = float(st.get("p_collapse_mean_hi", np.nan)) * 10
                if np.isfinite(vlo) and np.isfinite(vhi):
                    a.plot([np.clip(vlo, lo_x, hi_x), np.clip(vhi, lo_x, hi_x)], [0.5, 0.5], color="black", lw=3,
                           solid_capstyle="butt", zorder=4)
                if np.isfinite(v):
                    a.plot([np.clip(v, lo_x, hi_x)], [0.5], marker="D", ms=13, color="white",
                           markeredgecolor="black", markeredgewidth=2, zorder=5)
                kort = {"ehs": vt("EHS (Boston, Breslow 2021)", "EHS (Boston, Breslow 2021)"), "hospitalisation": vt("ziekenhuisopname (DtD 2024)", "hospital admission (DtD 2024)"),
                        "first_aid": vt("EHBO-contact (DtD 2024)", "first-aid contact (DtD 2024)")}.get(self.taak.inv.eindpunt, self.taak.inv.eindpunt)
                titel = (vt(f"Ter vergelijking: gekalibreerd collapsrisico {nl(v, 1)} per 1000  ·  {klasse(v)[2]}  ·  {kort}", f"For comparison: calibrated collapse risk {nl(v, 1)} per 1000  ·  {klasse(v)[2]}  ·  {kort}")
                         + f"  ·  n = {self.taak.n}"
                         + (vt("  ·  voorlopig", "  ·  provisional") if not self.taak.volledig else ""))
            self.rb_fig.suptitle(titel, fontsize=11, y=0.99)
            self.rb_canvas.draw_idle()

        def _kop(self, r):
            self._teken_risicobalk(r)
            if r is None:
                self.lbl_kop.config(text="  —  ", bg="#dddddd", fg="black")
                return
            s = r["samen"]
            n = s["n_simulations_used"]

            def kort_pct(res):
                d = 2 if res["hi"] < 0.01 else 1
                return f"{nl(100 * res['point'], d)}% ({nl(100 * res['lo'], d)}–{nl(100 * res['hi'], d)}%)"
            self.lbl_kop.config(
                text=(f"  EHS {s['n_true_ehs_hits']}/{n}: {kort_pct(s['fi']['ehs'])}  ·  "
                      f"EHE {s['n_true_ehe_hits']}/{n}: {kort_pct(s['fi']['ehe'])}  "),
                bg="#34495e", fg="white")

        def _toon_tegels(self):
            t, r = self.taak, self.resultaat
            if t is None or r is None:
                return
            s, st = r["samen"], r["stats"]
            v = float(st.get("expected_collapses_per_1000", np.nan))
            vlo = float(st.get("p_collapse_mean_lo", np.nan)) * 10
            vhi = float(st.get("p_collapse_mean_hi", np.nan)) * 10
            ep = EP[t.inv.eindpunt]
            kl = klasse(v) if np.isfinite(v) else None
            fi = s["fi"]["ehs"]
            n = s["n_simulations_used"]
            pk = s["peak_t_rect_p95"]
            from generate_event_report import criteria_betekenis, pct_interval
            cb = criteria_betekenis()
            items = [
                dict(titel=cb["ehs_naam"], waarde=vt(f"{s['n_true_ehs_hits']} van {n}", f"{s['n_true_ehs_hits']} of {n}"),
                     sub=pct_interval(fi), kleur=KL["rood"] if s["n_true_ehs_hits"] else "#34495e"),
                dict(titel=cb["ehe_naam"], waarde=vt(f"{s['n_true_ehe_hits']} van {n}", f"{s['n_true_ehe_hits']} of {n}"),
                     sub=pct_interval(s["fi"]["ehe"]), kleur=KL["oranje"] if s["n_true_ehe_hits"] else "#34495e"),
                dict(titel=vt(f"Kerntemperatuur > {nl(hm.T_THERMAL_ONLY_CRITICAL, 0)} °C", f"Core temperature > {nl(hm.T_THERMAL_ONLY_CRITICAL, 0)} °C"),
                     waarde=vt(f"{s['n_thermisch_kritiek']} van {n}", f"{s['n_thermisch_kritiek']} of {n}"),
                     sub=vt("deelnemers waar het model buiten zijn getoetste gebied rekent", "participants for whom the model calculates outside its tested range"),
                     kleur=KL["rood"] if s["n_thermisch_kritiek"] else "#27ae60"),
                dict(titel=vt("Piek-T_rect", "Peak T_rect"), waarde=f"{nl(s['peak_t_rect_mean'], 1)} °C",
                     sub=vt(f"gemiddeld; warmste 5%: {nl(pk, 1)} °C", f"mean; hottest 5%: {nl(pk, 1)} °C"),
                     kleur=KL["rood"] if pk >= 40.5 else KL["oranje"] if pk >= 39.5 else "#27ae60"),
                dict(titel=vt("Laagste CO-reserve (p5)", "Lowest CO reserve (p5)"),
                     waarde=f"{nl(float(st.get('co_reserve_min_p05', np.nan)), 1)} L/min",
                     sub=vt("de 5% deelnemers met de minste hartreserve", "the 5% of participants with the lowest cardiac reserve"), kleur="#5d6d7e"),
            ]
            uitleg = (vt(f"Gebaseerd op {n} gesimuleerde deelnemers (seed {t.seed}, "
                         f"{'volledige run' if t.volledig else 'snelle schatting'}). ",
                         f"Based on {n} simulated participants (seed {t.seed}, "
                         f"{'full run' if t.volledig else 'quick estimate'}). ")
                      + "EHS: " + cb["ehs_def"] + ". EHE: " + cb["ehe_def"] + ". " + cb["interval"]
                      + vt(" De risicobalk bovenaan is een andere schatting, ter vergelijking; "
                           "de zwarte streep daarin is de gevoeligheid voor het kalibratie-intercept.",
                           " The risk bar at the top is another estimate, for comparison; "
                           "its black line is the sensitivity to the calibration intercept."))
            self.tegels.zet(items, uitleg)
            nu = pd.Timestamp.now(tz=t.start_aware.tz)
            hist = t.start_aware < nu
            self.herkomst.zet(
                f"{t.weer.label}; {t.weer.city.get('name', '')}, route {self.v['route'].get()}",
                "historisch" if hist else "prognose",
                status_tekst=vt("simulatie · ", "simulation · ") + (vt("historisch weer", "historical weather") if hist else vt("verwachtingsweer", "forecast weather")),
                extra=f"model: HESTIA via hestia_bridge / run_monte_carlo_adult, n = {n}, seed {t.seed}",
                niet=vt("een telling van werkelijke patiënten of een medisch advies (virtuele deelnemers; "
                     "eindpunten PROVISIONAL).",
                        "a count of real patients or medical advice (virtual participants; "
                     "endpoints PROVISIONAL)."))

        def _toon_tekst(self):
            self._toon_tegels()
            t = self.taak
            self.txt.config(state="normal")
            self.txt.delete("1.0", "end")
            if t is None:
                self.txt.config(state="disabled")
                return
            ins = self.txt.insert
            w = t.weer
            ins("end", vt("Weer: ", "Weather: "), "vet")
            ins("end", vt(f"{w.label}; {w.city.get('name', '')} ({(w.city.get('population') or 0):,} inw.); "
                       f"route {self.v['route'].get()}.\n",
                          f"{w.label}; {w.city.get('name', '')} ({(w.city.get('population') or 0):,} inhabitants); "
                       f"route {self.v['route'].get()}.\n").replace(",", "." if not engels() else ","))
            naam, tf, af = PROFIELEN[t.inv.profiel]
            ins("end", vt("Opzet: ", "Set-up: "), "vet")
            tempo = (vt("eigen tempo per deelnemer (sample_pace; RACE_DISTANCE_MODE: wie vertraagt, loopt langer)", "individual pace per participant (sample_pace; RACE_DISTANCE_MODE: whoever slows down runs longer)")
                     if t.inv.eigen_tempo else
                     vt(f"gedeelde activiteit {ACT[t.inv.activiteit]['description']} ({hl.nl(t.met)} MET), "
                     f"vaste duur {nl(afgeleide_duur(t.inv), 2)} u",
                        f"shared activity {ACT[t.inv.activiteit]['description']} ({hl.nl(t.met)} MET), "
                     f"fixed duration {nl(afgeleide_duur(t.inv), 2)} h"))
            ins("end", vt(f"{t.inv.populatie}, {nl(t.inv.afstand_km)} km, {tempo}; clo {hl.nl(t.inv.clo)}; "
                       f"{PROFIEL_NL[t.inv.profiel]} (training {tf:g}, acclimatisatie {af:g}).\n",
                          f"{vt('lopers', 'runners') if t.inv.populatie == 'lopers' else vt('wandelaars', 'walkers')}, {nl(t.inv.afstand_km)} km, {tempo}; clo {hl.nl(t.inv.clo)}; "
                       f"{PROFIEL_NL[t.inv.profiel]} (training {tf:g}, acclimatisation {af:g}).\n").replace(".", ",", 0))
            r = self.resultaat
            if r is not None:
                s, st = r["samen"], r["stats"]
                from uncertainty import format_fraction_interval as _ffi
                from taal import engels as _eng

                def format_fraction_interval(res):
                    # Suite text is Dutch; English rendering of the same numbers.
                    if not _eng() or "error" in res:
                        return _ffi(res)
                    pct = int(round((1 - res["alpha"]) * 100))
                    return (f"{res['point']:.0%} ({res['k']} of {res['n']}; "
                            f"{pct}% interval {res['lo']:.0%}\u2013{res['hi']:.0%})")
                from generate_event_report import criteria_betekenis
                cb = criteria_betekenis()
                ins("end", vt("Criteria (aantal deelnemers): ", "Criteria (number of participants): "), "vet")
                from generate_event_report import pct_interval
                ins("end", f"{cb['ehs_naam']} {s['n_true_ehs_hits']} " + vt("van", "of") + f" {s['n_simulations_used']}, "
                           f"{pct_interval(s['fi']['ehs'])}; {cb['ehe_naam']} {s['n_true_ehe_hits']} " + vt("van", "of")
                           + f" {s['n_simulations_used']}, {pct_interval(s['fi']['ehe'])}; "
                           + vt("EAC-criterium (telling, hartreserve onder nul in de nafase) ", "EAC criterion (count, cardiac reserve below zero after the finish) ") + f"{format_fraction_interval(s['fi']['eac'])}.\n")
                ins("end", vt("Betekenis: ", "Meaning: "), "vet")
                ins("end", cb["ehs_betekenis"] + " " + cb["ehe_betekenis"] + " " + cb["interval"] + "\n")
                ins("end", vt(f"Thermisch kritiek (piek-T_rect tijdens de loop > {nl(hm.T_THERMAL_ONLY_CRITICAL)} °C, "
                           "pct_thermal_only_critical): ",
                              f"Thermally critical (peak T_rect during the run > {nl(hm.T_THERMAL_ONLY_CRITICAL)} °C, "
                           "pct_thermal_only_critical): "), "vet")
                ins("end", format_fraction_interval(s["fi"]["thermisch"]) + ".\n")
                if s["n_thermisch_kritiek"] > 0:
                    ins("end", vt(f"⚠ Boven {nl(hm.T_THERMAL_ONLY_CRITICAL)} °C (kritieke thermische maximumtemperatuur, "
                               "Hubbard; begin onomkeerbare zenuwschade, Gähwiler) rekent het model buiten zijn getoetste "
                               "gebied: de suite meldt dat deze grens in geen enkel kalibratiescenario is bereikt. Het model "
                               "heeft bovendien geen mechanisme dat de loop bij extreme kerntemperatuur beëindigt (de RPE-stop "
                               "is bij training ≥ 0,17 onbereikbaar). Lees zulke deelnemers als 'in werkelijkheid al eerder "
                               "uitgevallen', niet als een realistisch verloop. Ze tellen niet altijd mee in het EHS-criterium, "
                               "omdat dat ook CO_reserve ≤ 0,05 eist.\n",
                                  f"⚠ Above {nl(hm.T_THERMAL_ONLY_CRITICAL)} °C (critical thermal maximum, "
                               "Hubbard; onset of irreversible neural damage, Gähwiler) the model calculates outside its tested "
                               "range: the suite reports that this limit was not reached in any calibration scenario. The model "
                               "also has no mechanism that ends the run at extreme core temperature (the RPE stop "
                               "is unreachable at training ≥ 0.17). Read such participants as 'in reality already dropped out "
                               "earlier', not as a realistic course. They do not always count in the EHS criterion, "
                               "because that also requires CO_reserve ≤ 0.05.\n"), "waarsch")
                ei = s["ehs_interval"]
                ins("end", vt("Ter vergelijking (andere schattingen) — dosis-respons-EHS: ", "For comparison (other estimates) — dose–response EHS: "), "vet")
                if "error" not in ei:
                    ins("end", vt(f"{nl(ei['point_per_1000'], 2)} per 1000 "
                               f"(bereik {nl(ei['lo_per_1000'], 2)}–{nl(ei['hi_per_1000'], 2)}; een ondergrens van de "
                               f"onzekerheid, geen 95%-betrouwbaarheidsinterval).  ",
                                  f"{nl(ei['point_per_1000'], 2)} per 1000 "
                               f"(range {nl(ei['lo_per_1000'], 2)}–{nl(ei['hi_per_1000'], 2)}; a lower bound on the "
                               f"uncertainty, not a 95% confidence interval).  "))
                ep = EP[t.inv.eindpunt]
                ins("end", vt("Collapsrisico (", "Collapse risk (") + ep["label"] + ", " + ep["status"] + "): ", "vet")
                ins("end", vt(f"{nl(st.get('expected_collapses_per_1000', float('nan')), 2)} per 1000 verwacht. ", f"{nl(st.get('expected_collapses_per_1000', float('nan')), 2)} per 1000 expected. "))
                ins("end", vt("Falmouth-EHS: ", "Falmouth EHS: "), "vet")
                ins("end", f"{nl(s.get('falmouth_ehs_per_1000', float('nan')), 1)} per 1000. ")
                ins("end", vt("EAC-kans (model): ", "EAC probability (model): "), "vet")
                eac_txt = (vt("zeer hoog (WBGT boven 28 °C)", "very high (WBGT above 28 °C)") if st.get("eac_buiten_bereik")
                           else nl(float(st.get("eac_per_1000", float("nan"))), 1))
                ins("end", eac_txt + " per 1000.\n")
                _fa = np.asarray(st.get("percent_first_aid", [np.nan]), dtype=float)
                fa_max = float(np.nanmax(_fa)) if _fa.size and not np.all(np.isnan(_fa)) else float("nan")
                ins("end", vt("Verder: ", "Further: "), "vet")
                ins("end", vt(f"piek-T_rect gemiddeld {nl(s['peak_t_rect_mean'], 2)} °C, p95 "
                           f"{nl(s['peak_t_rect_p95'], 2)} °C; laagste CO_reserve p5 "
                           f"{nl(st.get('co_reserve_min_p05', float('nan')), 2)} L/min; uitdroging p95 "
                           f"{nl(st.get('dehy_pct_p95', float('nan')))}%; screeningsvlag aan het eind van de loop "
                           f"{nl(s['pct_first_aid'])}%, hoogste aandeel onderweg {nl(fa_max)}% (brede screening, geen "
                           f"voorspelling van EHBO-contacten); gestopt op RPE "
                           f"{nl(r['pct_gestopt'])}%; Roberts-kritiek "
                           f"{nl(st.get('pct_roberts_kritiek', float('nan')))}%.\n",
                              f"peak T_rect mean {nl(s['peak_t_rect_mean'], 2)} °C, p95 "
                           f"{nl(s['peak_t_rect_p95'], 2)} °C; lowest CO_reserve p5 "
                           f"{nl(st.get('co_reserve_min_p05', float('nan')), 2)} L/min; dehydration p95 "
                           f"{nl(st.get('dehy_pct_p95', float('nan')))}%; screening flag at the end of the run "
                           f"{nl(s['pct_first_aid'])}%, highest share during the run {nl(fa_max)}% (broad screening, not a "
                           f"prediction of first-aid contacts); stopped on RPE "
                           f"{nl(r['pct_gestopt'])}%; Roberts critical "
                           f"{nl(st.get('pct_roberts_kritiek', float('nan')))}%.\n"))
            grens = 20.0 * (1.0 - 0.15 * tf)
            if grens < hm.RPE_STOP_THRESHOLD:
                ins("end", vt(f"⚠ Model: bij training {tf:g} is de hoogst haalbare RPE {nl(grens)} "
                           f"(calculate_adult_rpe_from_hr); de RPE-stop ({nl(hm.RPE_STOP_THRESHOLD)}) kan "
                           f"daardoor niet afgaan.\n",
                              f"⚠ Model: at training {tf:g} the highest reachable RPE is {nl(grens)} "
                           f"(calculate_adult_rpe_from_hr); the RPE stop ({nl(hm.RPE_STOP_THRESHOLD)}) can "
                           f"therefore not trigger.\n"), "waarsch")
            if not t.inv.eigen_tempo:
                ins("end", vt("⚠ Gedeelde activiteit: vaste duur, vertragen verlengt de blootstelling niet.\n", "⚠ Shared activity: fixed duration, slowing down does not lengthen the exposure.\n"),
                    "waarsch")
            try:
                if np.nanmax(t.meteo["wbgt"]) < 18:
                    ins("end", vt("⚠ WBGT onder ca. 18: het model berekent de kerntemperatuur bij koel weer "
                               "enkele tienden te hoog (README, Known issue 9).\n",
                                  "⚠ WBGT below about 18: the model calculates the core temperature in cool weather "
                               "a few tenths too high (README, Known issue 9).\n"), "waarsch")
            except ValueError:
                pass
            ins("end", vt("Risicobalk: verwachte collapsen per 1000 voor het gekozen eindpunt (p_collapse_mean × 10); "
                       "kleurgrenzen uit de suite (HESTIA_CVR_Console._per1000_color: 0,5 / 1,5 / 3,0), daar "
                       "gekalibreerd rond het waargenomen DtD 2024-niveau (1,43 per 1000 ziekenhuisopnames) en "
                       "toegepast op elk eindpunt. De zwarte streep is de gevoeligheid voor het kalibratie-intercept "
                       "(±0,5), niet de steekproefonzekerheid.\n",
                          "Risk bar: expected collapses per 1000 for the chosen endpoint (p_collapse_mean × 10); "
                       "colour limits from the suite (HESTIA_CVR_Console._per1000_color: 0.5 / 1.5 / 3.0), there "
                       "calibrated around the observed DtD 2024 level (1.43 per 1000 hospital admissions) and "
                       "applied to every endpoint. The black line is the sensitivity to the calibration intercept "
                       "(±0.5), not the sampling uncertainty.\n"))
            ins("end", vt("Research software: niet gevalideerd voor operationele beslissingen. Alle eindpunten "
                       "van het collapsrisico zijn PROVISIONAL.",
                          "Research software: not validated for operational decisions. All endpoints "
                       "of the collapse risk are PROVISIONAL."))
            self.txt.config(state="disabled")

        def _fout(self, tekst):
            self.tegels.leeg(vt("Geen uitkomst: zie de melding onder de grafieken.", "No result: see the message below the charts."))
            self.lbl_status.config(text=vt("Fout – zie onder", "Error – see below"))
            self.txt.config(state="normal")
            self.txt.delete("1.0", "end")
            self.txt.insert("end", tekst, "waarsch")
            self.txt.config(state="disabled")
            self.pb["value"] = 0

        # ------------------------------------------------- extra venster
        def _open_extra(self):
            if self.extra is not None:
                self.extra.lift()
                return
            w = tk.Toplevel(self.root)
            w.title(vt("HESTIA populatie: extra grafieken", "HESTIA population: more charts"))
            bw, bh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            w.geometry(f"{min(1500, bw - 60)}x{min(900, bh - 100)}+40+30")
            ug.maximaliseer(w)
            nb = ttk.Notebook(w)
            nb.pack(fill="both", expand=True)
            self.nb_extra = nb
            self.ex = {}

            def tab(naam, titel, figsize, met_balk=False):
                f = ttk.Frame(nb)
                nb.add(f, text=titel)
                balk = None
                if met_balk:
                    balk = ttk.Frame(f)
                    balk.pack(side="top", fill="x", padx=6, pady=4)
                lbl = ttk.Label(f, text="", font=("TkDefaultFont", LETTER - 1), wraplength=1440,
                                justify="left")
                lbl.pack(side="bottom", fill="x", padx=8, pady=6)
                fig = Figure(figsize=figsize, dpi=96, constrained_layout=True)
                cv = FigureCanvasTkAgg(fig, master=f)
                cv.get_tk_widget().pack(side="top", fill="both", expand=True)
                self.ex[naam] = {"fig": fig, "cv": cv, "lbl": lbl, "balk": balk}
                return balk

            tab("sc", vt("Scatter en drempels", "Scatter and thresholds"), (15, 7.5))
            tab("ww", vt("Wanneer en waar", "When and where"), (15, 7.5))
            tab("wie", vt("Wie (na volledige run)", "Who (after full run)"), (15, 7.5))
            tab("top", vt("Top 10 T_rect", "Top 10 T_rect"), (15, 5.2))
            st_ = ttk.Style()
            st_.configure("Top.Treeview", font=("TkDefaultFont", LETTER - 1), rowheight=ug.px(self.root, int(LETTER * 2.1)))
            st_.configure("Top.Treeview.Heading", font=("TkDefaultFont", LETTER - 1, "bold"))
            kolommen = ("rang", "deelnemer", "geslacht", "leeftijd", "gewicht", "VO2max", "%VO2max", "tempo",
                        "kp_pacing", "motivatie", "NSAID", "piek T_rect", "min CO_res", "EHS", "> 42 °C")
            tv = ttk.Treeview(self.ex["top"]["cv"].get_tk_widget().master, columns=kolommen, show="headings",
                              height=10, style="Top.Treeview")
            kop_en = {"rang": "rank", "deelnemer": "participant", "geslacht": "sex", "leeftijd": "age",
                      "gewicht": "weight", "tempo": "pace", "motivatie": "motivation", "piek T_rect": "peak T_rect"}
            for k in kolommen:
                tv.heading(k, text=vt(k, kop_en.get(k, k)))
                tv.column(k, width=90 if k not in ("rang", "EHS", "NSAID", "> 42 °C") else 62, anchor="center")
            # Tabel vóór de grafiek inpakken: alle 10 rijen blijven zichtbaar, de grafiek krijgt de rest.
            cvw = self.ex["top"]["cv"].get_tk_widget()
            cvw.pack_forget()
            tv.pack(side="bottom", fill="x", padx=6, pady=(0, 4))
            cvw.pack(side="top", fill="both", expand=True)
            self.ex["top"]["tv"] = tv
            balk = tab("st", vt("Starttijd vergelijken", "Compare start time"), (15, 7.0), met_balk=True)
            self.v.setdefault("st_van", tk.StringVar(value="06:00"))
            self.v.setdefault("st_tot", tk.StringVar(value="20:00"))
            self.v.setdefault("st_stap", tk.StringVar(value="60"))
            for lab, k, wd in ((vt("Van", "From"), "st_van", 6), (vt("tot", "to"), "st_tot", 6), (vt("stap (min)", "step (min)"), "st_stap", 5)):
                ttk.Label(balk, text=lab).pack(side="left", padx=(8, 3))
                ttk.Entry(balk, textvariable=self.v[k], width=wd).pack(side="left")
            ttk.Button(balk, text=vt("Vergelijking starten", "Start comparison"), command=self._sweep_start).pack(side="left", padx=10)
            ttk.Button(balk, text=vt("Stoppen", "Stop"), command=self._sweep_stop).pack(side="left")
            self.lbl_sweep = ttk.Label(balk, text="")
            self.lbl_sweep.pack(side="left", padx=10)
            self.extra = w

            def dicht():
                self._sweep_stop()
                self.extra = None
                w.destroy()
            w.protocol("WM_DELETE_WINDOW", dicht)
            self._teken_extra()
            self._teken_sweep()

        def _teken_extra(self):
            if self.extra is None:
                return
            self._teken_scatter()
            self._teken_wanneer()
            self._teken_wie()
            self._teken_top()

        def _teken_top(self):
            e = self.ex["top"]
            tv = e["tv"]
            tv.delete(*tv.get_children())
            t, r = self.taak, self.resultaat
            if t is None or r is None:
                return self._leeg("top", vt("Wordt getoond zodra de berekening klaar is.", "Shown as soon as the calculation is ready."))
            ar = r["all_results"]
            idx = top_tien(ar, t.populatie)
            mom = ehs_momenten(ar)
            e["fig"].clear()
            a1, a2 = e["fig"].add_subplot(1, 2, 1), e["fig"].add_subplot(1, 2, 2)
            kleuren = matplotlib.colormaps["tab10"].colors
            for rang, i in enumerate(idx, 1):
                res = ar[i]
                kl = kleuren[(rang - 1) % 10]
                tijd = [pd.Timestamp(x["time"]) for x in res]
                tr = [x.get("t_rect", np.nan) for x in res]
                co = [x.get("co_reserve", np.nan) if x.get("co_reserve") is not None else np.nan for x in res]
                pf_t = res[-1].get("time_min_series_postfinish") or []
                fin = tijd[-1]
                pf_x = [fin + pd.Timedelta(minutes=float(m)) for m in pf_t]
                lab = vt(f"#{rang} (deelnemer {i + 1})", f"#{rang} (participant {i + 1})")
                a1.plot(tijd, tr, color=kl, lw=1.8, label=lab)
                a2.plot(tijd, co, color=kl, lw=1.8)
                if pf_x:
                    a1.plot(pf_x, (res[-1].get("t_rect_series_postfinish") or [])[:len(pf_x)], color=kl, lw=1.2, ls=":")
                    a2.plot(pf_x, (res[-1].get("co_reserve_series_postfinish") or [])[:len(pf_x)], color=kl, lw=1.2, ls=":")
                p = t.populatie[i]
                tmax, cmin = hm.collapse_extremes(res)
                tempo = hl.min_naar_tempo(p.pace_min_per_km) if t.inv.eigen_tempo and p.pace_min_per_km else "–"
                tv.insert("", "end", values=(
                    rang, i + 1, vt("man", "man") if p.gender == "male" else vt("vrouw", "woman"), p.age, nl(p.weight),
                    nl(p.vo2max), f"{p.pct_vo2max:.0%}", tempo, nl(p.kp_pacing, 3), nl(p.mf_score, 2),
                    vt("ja", "yes") if p.nsaid_gebruik else vt("nee", "no"), nl(tmax, 2), nl(cmin, 2),
                    vt("ja", "yes") if mom[i] is not None else vt("nee", "no"),
                    vt("ja", "yes") if r["samen"]["piek_loop"][i] > hm.T_THERMAL_ONLY_CRITICAL else vt("nee", "no")))
            for a in (a1, a2):
                self._x(a)
            a1.axhline(39.5, color=KL["oranje"], lw=1, ls=":")
            a1.axhline(40.5, color=KL["rood"], lw=1, ls=":")
            self._lijn42(a1)
            a1.set_title(vt("T_rect van de 10 deelnemers met de hoogste piek (stippel = nafinish)", "T_rect of the 10 participants with the highest peak (dotted = post-finish)"))
            a1.set_ylabel("°C")
            a1.legend(fontsize=8, loc="lower right", ncol=2)
            a2.axhline(0, color=KL["rood"], lw=1.2)
            a2.axhline(2.0, color=KL["oranje"], lw=1, ls=":")
            a2.set_title(vt("CO_reserve van dezelfde 10", "CO_reserve of the same 10"))
            a2.set_ylabel("L/min")
            e["lbl"].config(text=(
                vt("Rangorde op piek-T_rect over loop + nafinish (hestia_model.collapse_extremes, dezelfde maat als de "
                "collaps-logistiek). Tabel: profiel zoals getrokken door generate_base_population (kp_pacing = "
                "gevoeligheid voor de thermische tempo-rem, motivatie = mf_score). Deelnemernummer = volgorde in de "
                "populatie, gelijk aan participant_id in de Excel-export. Kolom '> 42 °C' = piek tijdens de loop boven "
                "T_THERMAL_ONLY_CRITICAL (zelfde regel als pct_thermal_only_critical); de rangorde telt ook de "
                "nafinish mee, dus een piek boven 42 °C alleen ná de finish staat hier als 'nee'.",
                   "Ranking on peak T_rect over run + post-finish (hestia_model.collapse_extremes, the same measure as the "
                "collapse logistic). Table: profile as drawn by generate_base_population (kp_pacing = "
                "sensitivity to the thermal pace brake, motivation = mf_score). Participant number = order in the "
                "population, equal to participant_id in the Excel export. Column '> 42 °C' = peak during the run above "
                "T_THERMAL_ONLY_CRITICAL (same rule as pct_thermal_only_critical); the ranking also counts the "
                "post-finish, so a peak above 42 °C only after the finish shows here as 'no'.")))
            e["cv"].draw_idle()

        def _leeg(self, naam, tekst):
            e = self.ex[naam]
            e["fig"].clear()
            ax = e["fig"].add_subplot(111)
            ax.text(0.5, 0.5, tekst, ha="center", va="center", transform=ax.transAxes, fontsize=14)
            ax.set_axis_off()
            e["cv"].draw_idle()

        def _teken_scatter(self):
            e = self.ex["sc"]
            t = self.taak
            if t is None or not t.res:
                return self._leeg("sc", vt("Berekenen …", "Calculating …"))
            from hestia_loper_ui import scatter_paren
            e["fig"].clear()
            gs = e["fig"].add_gridspec(2, 2, width_ratios=[1.4, 1])
            a, h, d = e["fig"].add_subplot(gs[:, 0]), e["fig"].add_subplot(gs[0, 1]), e["fig"].add_subplot(gs[1, 1])
            sporen = [t.res[i] for i in sorted(t.res)]
            paren = (self.resultaat["samen"]["t_rect_co_reserve_pairs"] if self.resultaat is not None
                     else scatter_paren(sporen))
            ta = np.array([p[0] for p in paren])
            ca = np.array([p[1] for p in paren])
            tol = hm.CO_RESERVE_CEILING_TOL
            y_hi = max(41.0, float(ta.max()) + 0.2)
            a.axhspan(39.5, 40.5, color="#f0a30a", alpha=0.18, zorder=0, label=vt("T_rect > 39,5 °C (EHE-drempel)", "T_rect > 39.5 °C (EHE threshold)"))
            a.axhspan(40.5, y_hi, color="#d62728", alpha=0.22, zorder=0,
                      label=vt("T_rect > 40,5 °C (klinische EHS-drempel)", "T_rect > 40.5 °C (clinical EHS threshold)"))
            a.axvline(0, color="black", lw=1, ls=":")
            ehe = (ta > 39.5) & (ca < tol)
            kl = (ta >= 40.5) & (ca <= tol)
            a.scatter(ca[~ehe], ta[~ehe], s=6, color="steelblue", alpha=0.35, label=vt("tijdstap (loop + nafinish)", "time step (run + post-finish)"))
            a.scatter(ca[ehe & ~kl], ta[ehe & ~kl], s=10, color="black", alpha=0.7,
                      label=vt("voldoet aan EHE (T > 39,5 EN COr < 0)", "meets EHE (T > 39.5 AND COr < 0)"))
            if kl.any():
                a.scatter(ca[kl], ta[kl], s=18, marker="X", color="#8B0000",
                          label=vt("voldoet aan klinisch criterium (T ≥ 40,5 EN COr ≤ 0)", "meets clinical criterion (T ≥ 40.5 AND COr ≤ 0)"))
            for drempel, kleur, naam, ms, dy in ((39.5, "#c07800", "EHE", 140, 8),
                                                 (40.5, "#8B0000", vt("klinisch", "clinical"), 80, -16)):
                mst = K._ehe_margin_stats(paren, drempel, 0.0)
                if mst is None:
                    continue
                a.scatter([mst["closest_c"]], [mst["closest_t"]], s=ms, facecolors="none", edgecolors=kleur,
                          linewidths=2, zorder=5, label=vt(f"dichtst bij {naam}-drempel", f"closest to {naam} threshold"))
                bn = mst["closest_bottleneck"]
                a.annotate(vt(f"{hl.nl(bn)} van {naam}", f"{hl.nl(bn)} of {naam}") if bn > 0 else vt(f"{naam} overschreden", f"{naam} exceeded"),
                           xy=(mst["closest_c"], mst["closest_t"]), xytext=(10, dy), textcoords="offset points",
                           fontsize=10, color=kleur, fontweight="bold", zorder=6,
                           bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=kleur, alpha=0.9))
            a.set_ylim(min(38.0, float(ta.min()) - 0.2), y_hi)
            self._lijn42(a)
            a.set_xlabel("CO_reserve (L/min)")
            a.set_ylabel("T_rect (°C)")
            a.set_title(vt(f"T_rect tegen CO_reserve, alle deelnemers ({len(sporen)}/{t.n})", f"T_rect against CO_reserve, all participants ({len(sporen)}/{t.n})"))
            a.legend(fontsize=8, loc="lower left")
            piek = np.array([np.nanmax(_matrix([r], "t_rect")) for r in sporen])
            h.hist(piek, bins=30, color=KL["lijn"], alpha=0.8)
            h.axvline(39.5, color=KL["oranje"], ls=":", lw=1)
            h.axvline(40.5, color=KL["rood"], ls=":", lw=1)
            h.set_title(vt("Verdeling piek-T_rect (loop)", "Distribution of peak T_rect (run)"))
            h.set_xlabel("°C")
            h.set_ylabel(vt("deelnemers", "participants"))
            b = banden(t)
            ti = self._tijden(t)
            for dk, kleur in (("39.5", KL["oranje"]), ("40.5", KL["rood"])):
                st = b["drempels"][dk]
                x = ti[:len(st["mean"])]
                d.fill_between(x, st["ci_lower"][:len(x)], st["ci_upper"][:len(x)], color=kleur, alpha=0.15, lw=0)
                d.plot(x, st["mean"][:len(x)], color=kleur, lw=2, label=vt(f"T_rect > {dk.replace('.', ',')} °C", f"T_rect > {dk.replace('.', ',') if vt('nl', 'en') == 'nl' else dk} °C"))
            d.set_title(vt("Aandeel deelnemers boven drempel (van wie nog loopt)", "Share of participants above threshold (of those still running)"))
            d.set_ylabel("%")
            d.set_ylim(bottom=0)
            d.legend(loc="upper left")
            self._x(d)
            e["lbl"].config(text=(
                vt("Scatter: alle tijdstappen van alle deelnemers, loop en nafinish (hestia_bridge._summarize_results, "
                "t_rect_co_reserve_pairs); zones, kleuring en markeringen zoals Klimatos plot_trect_co_reserve_scatter. "
                "Met het hartplafond (suite-standaard) blijft CO_reserve tijdens de loop rond 0. Drempels: "
                "hestia_model._calculate_threshold_stats, noemer = deelnemers die nog lopen, band = 95%-Wald-interval.",
                   "Scatter: all time steps of all participants, run and post-finish (hestia_bridge._summarize_results, "
                "t_rect_co_reserve_pairs); zones, colouring and markers as Klimatos plot_trect_co_reserve_scatter. "
                "With the cardiovascular ceiling (suite default) CO_reserve stays around 0 during the run. Thresholds: "
                "hestia_model._calculate_threshold_stats, denominator = participants still running, band = 95% Wald interval.")))
            e["cv"].draw_idle()

        def _teken_wanneer(self):
            e = self.ex["ww"]
            t, r = self.taak, self.resultaat
            if t is None or r is None:
                return self._leeg("ww", vt("Wordt getoond zodra de berekening klaar is.", "Shown as soon as the calculation is ready."))
            mom = ehs_momenten(r["all_results"])
            hits = [m for m in mom if m is not None]
            assert len(hits) == r["samen"]["n_true_ehs_hits"], vt("telling wijkt af van _summarize_results", "count differs from _summarize_results")
            e["fig"].clear()
            a1, a2 = e["fig"].add_subplot(1, 2, 1), e["fig"].add_subplot(1, 2, 2)
            ti = self._tijden(t)
            if hits:
                bins = pd.date_range(ti[0].floor("10min"), max(ti[-1], max(m["tijd"].tz_localize(None) if m["tijd"].tzinfo else m["tijd"] for m in hits)).ceil("10min") + pd.Timedelta(minutes=10), freq="10min")
                loop = [m["tijd"].tz_localize(None) if m["tijd"].tzinfo else m["tijd"] for m in hits if m["fase"] == "loop"]
                naf = [m["tijd"].tz_localize(None) if m["tijd"].tzinfo else m["tijd"] for m in hits if m["fase"] == "nafinish"]
                a1.hist([mdates.date2num(loop), mdates.date2num(naf)], bins=mdates.date2num(bins), stacked=True,
                        color=[KL["rood"], "#7d3c98"], label=[vt("tijdens de loop", "during the run"), vt("alleen in de finishzone (nafinish)", "only in the finish zone (post-finish)")])
                a1.legend(loc="upper left")
            else:
                a1.text(0.5, 0.5, vt("Geen deelnemer haalt het EHS-criterium", "No participant meets the EHS criterion"), ha="center", va="center",
                        transform=a1.transAxes, fontsize=12)
            a1.set_title(vt(f"Eerste moment EHS-criterium, kloktijd ({len(hits)} van {t.n})", f"First moment of EHS criterion, clock time ({len(hits)} of {t.n})"))
            a1.set_ylabel(vt("deelnemers per 10 min", "participants per 10 min"))
            self._x(a1)
            if t.inv.eigen_tempo:
                km_loop = [m["km"] for m in hits if m["fase"] == "loop" and m["km"] is not None]
                km_naf = [m["km"] for m in hits if m["fase"] == "nafinish" and m["km"] is not None]
                if km_loop or km_naf:
                    a2.hist([km_loop, km_naf], bins=np.arange(0, t.inv.afstand_km + 1.0, 1.0), stacked=True,
                            color=[KL["rood"], "#7d3c98"], label=[vt("tijdens de loop", "during the run"), vt("alleen in de finishzone", "only in the finish zone")])
                    a2.legend(loc="upper left")
                a2.axvline(t.inv.afstand_km, color="k", ls="--", lw=1)
                a2.set_xlim(0, t.inv.afstand_km + 1)
                a2.set_title(vt("Eerste moment EHS-criterium, afgelegde afstand", "First moment of EHS criterion, distance covered"))
                a2.set_xlabel(vt("km (stippellijn = finish)", "km (dotted line = finish)"))
                a2.set_ylabel(vt("deelnemers per km", "participants per km"))
            else:
                a2.text(0.5, 0.5, vt("Afstand alleen bij 'eigen tempo per deelnemer':\n"
                                  "alleen dan houdt het model de afgelegde afstand bij\n(RACE_DISTANCE_MODE).",
                                     "Distance only with 'individual pace per participant':\n"
                                  "only then does the model track the distance covered\n(RACE_DISTANCE_MODE)."),
                        ha="center", va="center", transform=a2.transAxes, fontsize=12)
                a2.set_axis_off()
            e["lbl"].config(text=(
                vt("Eerste tijdstap waarop T_rect ≥ 40,5 °C en CO_reserve ≤ 0,05 L/min gelijktijdig gelden, of anders "
                "ehs_postfinish (in de finishzone): dezelfde regel als hestia_bridge._summarize_results, zodat de "
                "aantallen optellen tot het EHS-getal bovenin. Tijdstappen zijn 10 minuten; de kloktijd is het einde "
                "van die stap. Bruikbaar voor de plaatsing van medische posten, niet als voorspelling per persoon.",
                   "First time step at which T_rect ≥ 40.5 °C and CO_reserve ≤ 0.05 L/min hold at the same time, or else "
                "ehs_postfinish (in the finish zone): the same rule as hestia_bridge._summarize_results, so the "
                "counts add up to the EHS number at the top. Time steps are 10 minutes; the clock time is the end "
                "of that step. Useful for placing medical posts, not as a prediction per person.")))
            e["cv"].draw_idle()

        def _teken_wie(self):
            e = self.ex["wie"]
            t, r = self.taak, self.resultaat
            if t is None or r is None:
                return self._leeg("wie", vt("Wordt getoond zodra de berekening klaar is.", "Shown as soon as the calculation is ready."))
            if not t.volledig:
                return self._leeg("wie", vt("Alleen na een volledige run: bij de snelle schatting\n"
                                         "zijn de subgroepen te klein voor een uitspraak.",
                                            "Only after a full run: with the quick estimate\n"
                                         "the subgroups are too small for a conclusion."))
            g = per_groep(t.populatie, ehs_momenten(r["all_results"]))
            e["fig"].clear()
            ax = e["fig"].add_subplot(111)
            leeft = sorted({k[0] for k in g})
            breedte = 0.38
            for j, (gesl, kleur, naam) in enumerate((("male", "#2e86c1", vt("man", "men")), ("female", "#c0392b", vt("vrouw", "women")))):
                x, y, lo, hi, n_txt = [], [], [], [], []
                for i, lg in enumerate(leeft):
                    fi = g.get((lg, gesl))
                    if fi is None or "error" in fi:
                        continue
                    x.append(i + (j - 0.5) * breedte)
                    y.append(100 * fi["point"])
                    lo.append(100 * (fi["point"] - fi["lo"]))
                    hi.append(100 * (fi["hi"] - fi["point"]))
                    n_txt.append(f"{fi['k']}/{fi['n']}")
                ax.bar(x, y, width=breedte, color=kleur, alpha=0.8, label=naam,
                       yerr=[lo, hi], capsize=4, error_kw={"lw": 1})
                for xi, yi, tx in zip(x, y, n_txt):
                    ax.text(xi, yi, tx, ha="center", va="bottom", fontsize=9)
            ax.set_xticks(range(len(leeft)))
            ax.set_xticklabels([x.replace("60-65", "60–65") for x in leeft])
            ax.set_xlabel(vt("leeftijdsgroep (hestia_model.get_age_group)", "age group (hestia_model.get_age_group)"))
            ax.set_ylabel(vt("% met EHS-criterium", "% with EHS criterion"))
            ax.set_ylim(bottom=0)
            ax.set_title(vt(f"EHS-criterium per leeftijdsgroep en geslacht (n = {t.n})", f"EHS criterion per age group and sex (n = {t.n})"))
            ax.legend(loc="upper left")
            e["lbl"].config(text=(
                vt("Balk = aandeel deelnemers met het EHS-criterium; streep = 95%-interval (Clopper-Pearson, "
                "uncertainty.fraction_interval); getal = aantal met criterium / aantal in de groep. Het interval dekt "
                "alleen de steekproefgrootte, niet de onzekerheid in de fysiologie. De verdeling naar leeftijd en "
                "geslacht volgt generate_base_population (58 % man; leeftijd N(40, 10), 18–65).",
                   "Bar = share of participants with the EHS criterion; line = 95% interval (Clopper-Pearson, "
                "uncertainty.fraction_interval); number = count with criterion / count in the group. The interval covers "
                "only the sample size, not the uncertainty in the physiology. The distribution by age and "
                "sex follows generate_base_population (58 % men; age N(40, 10), 18–65).")))
            e["cv"].draw_idle()

        # ------------------------------------------- starttijd vergelijken
        def _sweep_sig(self):
            inv = self._invoer()
            return (tuple(v for k, v in inv.__dict__.items() if k != "starttijd"),
                    self.v["n_snel"].get(), self.v["seed"].get(), self._route(),
                    self.v["bron"].get(), self.v["excel"].get(), self.v["kandidaat"].get())

        def _sweep_start(self):
            self._sweep_stop()
            try:
                inv = self._invoer()
                tijden = starttijden(self.v["st_van"].get().strip(), self.v["st_tot"].get().strip(),
                                     int(self._f("st_stap")))
                n, seed = int(self._f("n_snel")), int(self._f("seed"))
                fouten = valideer(inv)
                if fouten:
                    raise ValueError("; ".join(fouten))
            except Exception as ex:
                self.lbl_sweep.config(text=vt(f"Invoer: {ex}", f"Input: {ex}"))
                return
            excel = self.v["bron"].get().startswith("Data")
            route = self._route()
            pad = self.v["excel"].get().strip()
            kand = self._kandidaat()
            if (excel and not pad) or (not excel and kand is None):
                self.lbl_sweep.config(text=vt("Kies eerst weerbron en plaats.", "First choose weather source and location."))
                return
            self.sweep_gen = getattr(self, "sweep_gen", 0) + 1
            sg = self.sweep_gen
            self.sweep = {"gen": sg, "stop": False, "rijen": {}, "tijden": tijden, "n": n,
                          "sig": self._sweep_sig(), "huidig": inv.starttijd, "futures": []}
            sw = self.sweep
            self._teken_sweep()

            def werk():
                from concurrent.futures import wait
                for st in tijden:
                    if sw["stop"]:
                        break
                    self.q.put(("sweep_status", sg, vt(f"bezig: {st} ({tijden.index(st) + 1}/{len(tijden)})", f"busy: {st} ({tijden.index(st) + 1}/{len(tijden)})")))
                    try:
                        inv2 = PopInvoer(**{**inv.__dict__, "starttijd": st})
                        s2, e2 = venster(inv2)
                        w = (self.weerbron.excel(pad, s2, e2 + pd.Timedelta(hours=1), route) if excel
                             else self.weerbron.online(kand, inv2.datum, route))
                        t = bereid_voor(-sg, inv2, w, n, seed, False)
                        fs = [self.pool.submit(_pop_lid, a) for a in taak_argumenten(t)]
                        sw["futures"] = fs
                        wait(fs)
                        if sw["stop"]:
                            break
                        for f in fs:
                            _, i, res = f.result()
                            t.res[i] = res
                        r = eindresultaat(t)
                        s_ = r["samen"]
                        wb = np.asarray(t.meteo["wbgt"], dtype=float)
                        self.q.put(("sweep", sg, st, {
                            "fi": s_["fi"]["ehs"], "col": r["stats"].get("expected_collapses_per_1000", np.nan),
                            "wbgt_gem": float(np.nanmean(wb)), "wbgt_max": float(np.nanmax(wb)),
                            "piek_p95": s_["peak_t_rect_p95"]}))
                    except Exception as ex:
                        self.q.put(("sweep", sg, st, {"fout": str(ex).splitlines()[0][:120]}))
                self.q.put(("sweep_status", sg, "gestopt" if sw["stop"] else "klaar"))
            threading.Thread(target=werk, daemon=True).start()

        def _sweep_stop(self):
            sw = getattr(self, "sweep", None)
            if sw:
                sw["stop"] = True
                for f in sw.get("futures", []):
                    f.cancel()

        def _teken_sweep(self):
            if self.extra is None:
                return
            e = self.ex["st"]
            sw = getattr(self, "sweep", None)
            if not sw:
                return self._leeg("st", vt("Kies het bereik en klik op 'Vergelijking starten'.\n"
                                        "Elke starttijd is een eigen snelle schatting (n = 'Live (snel)').",
                                           "Choose the range and click 'Start comparison'.\n"
                                        "Each start time is its own quick estimate (n = 'Live (quick)')."))
            e["fig"].clear()
            a1, a2, a3 = (e["fig"].add_subplot(3, 1, k) for k in (1, 2, 3))
            klaar = [(st, sw["rijen"][st]) for st in sw["tijden"] if st in sw["rijen"] and "fout" not in sw["rijen"][st]]
            fout = [st for st in sw["tijden"] if st in sw["rijen"] and "fout" in sw["rijen"][st]]
            x_all = [pd.Timestamp(f"2000-01-01 {st}") for st in sw["tijden"]]
            if klaar:
                x = [pd.Timestamp(f"2000-01-01 {st}") for st, _ in klaar]
                p = np.array([100 * d["fi"]["point"] for _, d in klaar])
                lo = np.array([100 * d["fi"]["lo"] for _, d in klaar])
                hi = np.array([100 * d["fi"]["hi"] for _, d in klaar])
                a1.fill_between(x, lo, hi, color=KL["rood"], alpha=0.15, lw=0, label=vt("95%-interval", "95% interval"))
                a1.plot(x, p, "o-", color=KL["rood"], lw=2, label=vt("EHS-criterium", "EHS criterion"))
                a1.legend(loc="upper left")
                a2.plot(x, [d["col"] for _, d in klaar], "o-", color="#34495e", lw=2)
                a3.plot(x, [d["wbgt_gem"] for _, d in klaar], "o-", color=KL["oranje"], lw=2, label=vt("gemiddeld", "mean"))
                a3.plot(x, [d["wbgt_max"] for _, d in klaar], "o--", color=KL["oranje"], lw=1, label="max")
                a3.legend(loc="upper left")
            for xf in fout:
                for a in (a1, a2, a3):
                    a.axvline(pd.Timestamp(f"2000-01-01 {xf}"), color="#bbbbbb", lw=6, alpha=0.5)
            h = pd.Timestamp(f"2000-01-01 {sw['huidig']}")
            for a in (a1, a2, a3):
                a.axvline(h, color="k", ls=":", lw=1)
                a.set_xlim(x_all[0] - pd.Timedelta(minutes=20), x_all[-1] + pd.Timedelta(minutes=20))
                self._x(a)
            a1.set_ylabel(vt("% deelnemers", "% participants"))
            a1.set_ylim(bottom=0)
            ep = EP[self.taak.inv.eindpunt] if self.taak else EP["ehs"]
            a2.set_ylabel("per 1000")
            a2.set_ylim(bottom=0)
            ymax = a2.get_ylim()[1]
            for (g, k, lab), g2 in zip(KLASSEN, [x[0] for x in KLASSEN[1:]] + [max(ymax, KLASSEN[-1][0]) * 10]):
                a2.axhspan(g, g2, color=KLASSE_KLEUR[k], alpha=0.18, lw=0, zorder=0)
            a2.set_ylim(0, ymax)
            a3.set_ylabel("WBGT (°C)")
            a3.set_xlabel("starttijd")
            verouderd = False
            try:
                verouderd = self._sweep_sig() != sw["sig"]
            except Exception:
                pass
            a1.set_title(vt(f"EHS-criterium per starttijd (n = {sw['n']} per starttijd)", f"EHS criterion per start time (n = {sw['n']} per start time)")
                         + (vt("   — VEROUDERD: invoer gewijzigd", "   — OUTDATED: input changed") if verouderd else ""))
            a2.set_title(vt(f"Verwachte collapsen per 1000 ({ep['label']}, {ep['status']})", f"Expected collapses per 1000 ({ep['label']}, {ep['status']})"))
            a3.set_title(vt("WBGT in het loopvenster", "WBGT in the running window"))
            e["lbl"].config(text=(
                vt("Elke starttijd is een volledige HESTIA-berekening met dezelfde invoer, populatie-seed en n (de snelle "
                "schatting); alleen de starttijd verschilt. Stippellijn = huidige starttijd in het hoofdvenster. Grijze "
                "balk = geen volledige weerdata voor die starttijd. Bij n = 100 zijn verschillen tussen naburige "
                "starttijden vaak kleiner dan het interval: let op de trend, niet op één punt.",
                   "Each start time is a full HESTIA calculation with the same input, population seed and n (the quick "
                "estimate); only the start time differs. Dotted line = current start time in the main window. Grey "
                "bar = no complete weather data for that start time. At n = 100 differences between neighbouring "
                "start times are often smaller than the interval: look at the trend, not at one point.")
                + (vt(f" Mislukt: {', '.join(fout)}.", f" Failed: {', '.join(fout)}.") if fout else "")))
            e["cv"].draw_idle()

        # ------------------------------------------------------- export
        def _rapport(self):
            """[2026-11-25] Het evenementrapport van de suite (generate_event_report +
            report_to_docx), met de populatie uit dit venster als bron; dezelfde
            gegevens als run_hestia.py aan het rapport geeft; taal volgt het venster."""
            if self.resultaat is None or self.taak is None:
                messagebox.showinfo(vt("Evenementrapport", "Event report"), vt("Er is nog geen volledig resultaat.", "There is no full result yet."))
                return
            p = filedialog.asksaveasfilename(title=vt("Evenementrapport opslaan", "Save event report"), defaultextension=".docx",
                                             initialfile=vt("HESTIA_evenementrapport.docx", "HESTIA_event_report.docx"),
                                             filetypes=[("Word", "*.docx")], initialdir=str(HIER))
            if not p:
                return
            try:
                self.root.config(cursor="watch")
                self.root.update_idletasks()
                pad = maak_evenementrapport(self.taak, self.resultaat, p)
                messagebox.showinfo(vt("Evenementrapport", "Event report"),
                                    vt(f"Opgeslagen:\n{pad}", f"Saved:\n{pad}"))
            except Exception as ex:
                # [2026-11-26] Zeg ook waar het Markdown-rapport staat, als dat er al is.
                from pathlib import Path as _P
                _md = _P(p).with_suffix(".md")
                _extra = (vt(f"\n\nHet Markdown-rapport is wel opgeslagen:\n{_md}",
                             f"\n\nThe Markdown report was saved:\n{_md}") if _md.is_file() else "")
                messagebox.showerror(vt("Evenementrapport", "Event report"),
                                     vt(f"Mislukt: {ex}", f"Failed: {ex}") + _extra)
            finally:
                self.root.config(cursor="")

        def _export(self):
            if self.resultaat is None:
                messagebox.showinfo(vt("Excel-export", "Excel export"), vt("Er is nog geen volledig resultaat.", "There is no full result yet."))
                return
            p = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                             initialdir=str(HIER))
            if not p:
                return
            try:
                r, t = self.resultaat, self.taak
                s = r["samen"]
                rijen = [("evenement", t.inv.evenement), ("datum", t.inv.datum), ("start", t.inv.starttijd),
                         ("weer", t.weer.label), ("route", self._route()), ("populatie", t.inv.populatie),
                         ("afstand_km", t.inv.afstand_km), ("eigen_tempo", t.inv.eigen_tempo),
                         ("met_gedeeld", t.met), ("clo", t.inv.clo), ("training_factor", t.tf),
                         ("acclimatization_factor", t.af), ("eindpunt", t.inv.eindpunt), ("n", t.n),
                         ("seed", t.seed)]
                for k in ("pct_true_ehs_criterion", "pct_true_ehe_criterion", "pct_true_eac_criterion",
                          "n_true_ehs_hits", "n_true_ehe_hits", "n_true_eac_hits", "pct_dose_response_ehs",
                          "peak_t_rect_mean", "peak_t_rect_p95", "pct_first_aid"):
                    rijen.append((k, s[k]))
                rijen.append(("pct_gestopt_rpe", r["pct_gestopt"]))
                rijen.append(("n_thermisch_kritiek_42C", s["n_thermisch_kritiek"]))
                rijen.append(("pct_thermal_only_critical", r["stats"].get("pct_thermal_only_critical")))
                for k in ("expected_collapses_per_1000", "pct_roberts_kritiek",
                          "dehy_pct_p95", "co_reserve_min_p05"):
                    rijen.append((k, r["stats"].get(k)))
                with pd.ExcelWriter(p) as xw:
                    pd.DataFrame(rijen, columns=[vt("grootheid", "quantity"), vt("waarde", "value")]).to_excel(
                        xw, sheet_name=vt("Samenvatting", "Summary"), index=False)
                    r["results_df"].to_excel(xw, sheet_name=vt("Per deelnemer", "Per participant"), index=False)
            except Exception as ex:
                self._fout(vt(f"Export mislukt: {ex}", f"Export failed: {ex}"))

        def _sluit(self):
            self._sweep_stop()
            self._annuleer()
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.root.destroy()

    root = tk.Tk()
    app = App(root)
    if na_start is not None:
        na_start(app, root)
    root.mainloop()


if __name__ == "__main__":
    import multiprocessing as mp
    import sys
    mp.freeze_support()
    os.chdir(HIER)
    if str(HIER) not in sys.path:
        sys.path.insert(0, str(HIER))
    _start_ui()
