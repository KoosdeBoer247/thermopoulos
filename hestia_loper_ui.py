# -*- coding: utf-8 -*-
"""
hestia_loper_ui.py
==================
Visuele invoer en weergave (Tkinter) voor de persoonlijke HESTIA-loperanalyse.

De gebruiker vult persoon, fitheid, gedrag, kleding en de loop in; elke
wijziging start meteen een nieuwe berekening. Getoond worden tijdens de run:
luchttemperatuur, WBGT, RH, windsnelheid, kerntemperatuur (T_rect) en
CO_reserve.

Geen eigen fysiologie of weerfysica
-----------------------------------
Alles loopt via de bestaande suite:
  - invoer, validatie, afgeleide fitheid ...... hestia_loper (LoperInvoer,
                                                  valideer, afleiden, _maak_inputs, _hook)
  - weer ophalen en verwerken ................. Thermopoulos_Data_Engine
                                                  (geocode, forecast/ERA5 + kustcorrectie,
                                                  process_weather_data: UHI, globe/MRT,
                                                  natte bol, WBGT, UTCI)
  - Data Engine-bestand lezen ................. hestia_loper._zoek_blad (zelfde
                                                  bladkeuze en dekkingseisen)
  - weer naar 10-min stappen .................. hestia_bridge.build_interp_data
  - ensemble-profielen ........................ individual_engine._build_profile
  - een ensemble-lid .......................... hestia_model.calculate_indices_jos3_adult
  - banden T_rect/CO_reserve .................. individual_engine._extended_bands
  - eindresultaat, risicosignaal, export ...... hestia_loper.analyseer_loper (via
                                                  terugspelen, zie hieronder),
                                                  risicosignaal, exporteer_excel

Wat deze UI anders doet dan run_loper.py (alleen de UITVOERING)
---------------------------------------------------------------
1. Voortschrijdend en parallel. individual_engine.run_individual_assessment()
   draait de ensemble-leden een voor een (~0,4 s per lid). Hier worden de
   leden over alle processorkernen verdeeld en de banden bijgewerkt zodra er
   leden klaar zijn ('voorlopig, n = 37/200'). Bij elke wijziging wordt de
   lopende berekening afgebroken.
2. De PROFIELEN zijn exact dezelfde als in run_individual_assessment(): ze
   worden vooraf, in dezelfde volgorde, met np.random.default_rng(seed)
   getrokken (_build_profile + dezelfde profile_hook).
3. De enige andere toevalsbron binnen een lid is de drinkportie
   (np.random.uniform(120, 180) in calculate_indices_jos3_adult, globale
   numpy-RNG). Serieel hangt die af van alle vorige leden; parallel kan dat
   niet. Elk lid krijgt daarom een eigen seed np.random.seed([seed, i]).
   Gevolg: per lid een andere, even waarschijnlijke reeks drinkporties dan in
   run_loper.py; de ensemblestatistiek is gelijkwaardig maar niet bit-voor-bit
   gelijk aan run_loper.py met dezelfde seed. Met dezelfde invoer en dezelfde
   seed geeft de UI wel steeds exact hetzelfde resultaat.
4. Als alle leden klaar zijn, loopt het eindresultaat door de echte
   hestia_loper.analyseer_loper(): de al berekende leden worden teruggespeeld
   in plaats van opnieuw gerekend. Daarbij wordt per lid gecontroleerd dat het
   profiel identiek is aan het profiel waarmee het lid berekend is.
5. Luchtkwaliteit: calculate_indices_jos3_adult() vraagt per lid de AQI op
   (gecachet per proces). Hier wordt de AQI een keer opgehaald en in elk
   werkproces vastgezet met hestia_bridge._patch_air_quality(), dezelfde
   patch die de populatie-apps gebruiken.
6. Weerbron online: verleden datum -> ERA5-archief (met kustcorrectie en
   aanvulling van de laatste dagen, fetch_historical_data); vandaag of later ->
   forecast (max. 16 dagen). hestia_loper beslist op het starttijdstip
   (start < nu); hier op de datum, zodat het weer niet opnieuw wordt opgehaald
   als de starttijd op de dag van vandaag verschuift. Voor vandaag levert het
   ERA5-archief nog niets en vult fill_recent_gap() juist uit de forecast aan.

Route (keuze 2026-11-20, variant a): stad of platteland voor de hele loop.
  stad       -> T_air_urban / RH_urban (UHI naar inwonertal, Oke 1973)
  platteland -> de rurale tak van process_weather_data (inwonertal 0):
                T_air_urban = T_air_rural; globe/MRT/WBGT/UTCI daarmee berekend.
Bos (schaduw) en 'gedeeltelijk stad' kent de suite niet (README Known issue 11).

Wind in de grafiek: de 10 m-wind van het weerbestand en de wind op 1,5 m die
de fysiologie werkelijk krijgt (calculate_indices_jos3_adult rekent met
wind_speed_at_height(w, 10, 1.5), vaste z0 = 0,1 m, los van het gekozen
terrein). Daarbovenop telt het model per lid de eigen loopsnelheid mee
(compute_relative_wind); die relatieve luchtstroom staat niet in de grafiek.

Status: research software (zie README). Niet voor operationele beslissingen.

Starten:  python hestia_loper_ui.py
"""
from __future__ import annotations

import json
import math
import os
import queue
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

HIER = Path(__file__).resolve().parent

# =============================================================================
# 1. WERKPROCES  (een ensemble-lid)
# =============================================================================
_WERKER_KLAAR = False


def _werker_init():
    """Importeert de suite eenmalig per werkproces (o.a. de JOS-3-patch van
    jos3_leeftijd, die hestia_model bij import toepast)."""
    global _WERKER_KLAAR
    import sys
    if str(HIER) not in sys.path:
        sys.path.insert(0, str(HIER))
    import hestia_model  # noqa: F401
    import hestia_bridge  # noqa: F401
    _WERKER_KLAAR = True


def _opwarmen(_=None):
    return os.getpid()


def _bereken_lid(args):
    """Een ensemble-lid: exact de aanroep uit
    individual_engine.run_individual_assessment()."""
    (gen, i, interp, lat, lon, met_ref, clo, profiel, tf, accl, seed, aqi, plafond) = args
    import hestia_model as hm
    import hestia_bridge as hb
    hb._patch_air_quality(aqi)
    # plafond=True is de suite-standaard. False alleen voor de scatterplot
    # (zie SCATTER hieronder): de bestaande suite-schakelaar CV_CEILING_FORCED.
    # Werkprocessen worden hergebruikt, dus elke taak zet hem expliciet.
    hm.CV_CEILING_FORCED = bool(plafond)
    np.random.seed([int(seed), int(i)])   # zie modulekop, punt 3
    res = hm.calculate_indices_jos3_adult(interp, lat, lon, met_ref, clo, profiel, tf, accl)
    return gen, i, res, bool(plafond)


# =============================================================================
# 2. REKENKERN (hoofdproces)
# =============================================================================
def _suite():
    """Late import: werkprocessen op Windows (spawn) importeren dit bestand
    opnieuw; de zware suite-import gebeurt alleen waar nodig."""
    import hestia_loper as hl
    import individual_engine as ie
    import hestia_model as hm
    import hestia_bridge as hb
    import Thermopoulos_Data_Engine as de
    return hl, ie, hm, hb, de


@dataclass
class Weer:
    df: pd.DataFrame
    city: dict
    lat: float
    lon: float
    tz: str
    label: str            # voor weergave/rapport (zoals LoperResultaat.weer_sheet)
    aqi: int

    @property
    def tuple(self):
        return (self.df, self.city, self.lat, self.lon, self.tz)


class _CacheXL:
    """Gedraagt zich voor hestia_loper._zoek_blad() als een pd.ExcelFile, maar
    leest elk blad maar een keer van schijf."""

    def __init__(self, pad: Path):
        with pd.ExcelFile(pad) as xl:
            self.sheet_names = list(xl.sheet_names)
            self._meta = xl.parse("Metadata")
            self._bladen = {}
            for s in self.sheet_names:
                if s == "Metadata":
                    continue
                self._bladen[s] = xl.parse(s, index_col=0)

    def parse(self, naam, index_col=None):
        if naam == "Metadata":
            return self._meta.copy()
        return self._bladen[naam].copy()

    def bereik(self) -> list[str]:
        uit = []
        for s, d in self._bladen.items():
            if isinstance(d.index, pd.DatetimeIndex) and len(d):
                uit.append(f"{s}: {d.index.min():%Y-%m-%d} t/m {d.index.max():%Y-%m-%d}")
        return uit


RURAAL_NODIG = ["T_air_rural", "RH", "pressure", "wind_10m", "solar_radiation", "cloud_cover"]
KUST_KOLOMMEN = ["T_air_era5", "coastal_correction_applied", "coastal_correction_degrees",
                 "coastal_correction_reason"]


def _ruraal(df: pd.DataFrame, lat, lon, tz, z0: float) -> pd.DataFrame:
    """Rurale tak van process_weather_data (inwonertal 0) op een al verwerkt
    blad: T_air_rural is daar al gecorrigeerd (kustcorrectie), dus
    coastal_active=False; de kustkolommen van het origineel blijven bewaard."""
    _, _, _, _, de = _suite()
    ontbreekt = [c for c in RURAAL_NODIG if c not in df.columns]
    if ontbreekt:
        raise ValueError("Dit weerbestand mist kolommen voor 'platteland': " + ", ".join(ontbreekt))
    bewaar = {c: df[c].copy() for c in KUST_KOLOMMEN if c in df.columns}
    uit = de.process_weather_data(df[RURAAL_NODIG].copy(), {"population": 0}, lat, lon, tz,
                                  coastal_active=False, roughness_z0=z0)
    for c, v in bewaar.items():
        uit[c] = v
    return uit


class WeerBron:
    """Haalt en verwerkt weer met de Data Engine-functies en bewaart het, zodat
    een andere starttijd geen nieuwe download vraagt."""

    def __init__(self):
        self._ruw = {}        # (lat, lon, modus, datum) -> (df, coastal)
        self._verwerkt = {}   # + route
        self._xl = {}         # pad -> _CacheXL
        self._aqi = {}

    # ---------------------------------------------------------------- AQI
    def aqi(self, lat, lon) -> int:
        k = (round(lat, 4), round(lon, 4))
        if k not in self._aqi:
            _, _, hm, _, _ = _suite()
            try:
                self._aqi[k] = int(hm.get_air_quality(lat, lon))
            except Exception:
                self._aqi[k] = 1      # dezelfde terugval als hestia_model
        return self._aqi[k]

    # ------------------------------------------------------------- online
    def online(self, kandidaat: dict, datum: str, route: str) -> Weer:
        _, ie, _, _, de = _suite()
        lat, lon, tz = kandidaat["latitude"], kandidaat["longitude"], kandidaat["timezone"]
        d = pd.Timestamp(datum).normalize()
        vandaag = pd.Timestamp.now(tz=tz).tz_localize(None).normalize()
        modus = "historisch" if d < vandaag else "forecast"
        sleutel = (round(lat, 4), round(lon, 4), modus, str(d.date()))
        if sleutel not in self._ruw:
            if modus == "historisch":
                eind = min(d + pd.Timedelta(days=1), vandaag - pd.Timedelta(days=1))
                eind = max(eind, d)
                ruw = de.fetch_historical_data(lat, lon, tz, d.strftime("%Y-%m-%d"),
                                               eind.strftime("%Y-%m-%d"))
                ruw = (de.validate_weather_data(ruw[0], "historical"), ruw[1])
            else:
                dagen = (d - vandaag).days + 2          # dag zelf + volgende dag
                if (d - vandaag).days + 1 > 16:
                    raise ValueError("Datum ligt verder dan 16 dagen vooruit: buiten de "
                                     "verwachtingshorizon van Open-Meteo.")
                ruw = de.fetch_hourly_forecast(lat, lon, tz, min(16, dagen))
                ruw = (de.validate_weather_data(ruw[0], "forecast"), ruw[1])
            self._ruw[sleutel] = ruw
        vsl = sleutel + (route,)
        if vsl not in self._verwerkt:
            df, coastal = self._ruw[sleutel]
            city = dict(kandidaat)
            if route == "platteland":
                city["population"] = 0
            z0 = de.ROUGHNESS_Z0_TERRAIN[ie.EventScenario.__dataclass_fields__["terrain_key"].default][1]
            self._verwerkt[vsl] = de.process_weather_data(
                df.copy(), city, lat, lon, tz, coastal_active=coastal, roughness_z0=z0)
        dfv = self._verwerkt[vsl]
        if modus == "historisch":
            dag = dfv.loc[str(d.date())]
            n_toe = int(dag["coastal_correction_applied"].sum()) if "coastal_correction_applied" in dag else 0
            if n_toe:
                bron = (f"ERA5-archief; land-zeecorrectie op {n_toe} uur van deze dag, max "
                        f"{dag['coastal_correction_degrees'].max():+.1f} °C").replace(".", ",")
            else:
                reden = ""
                if "coastal_correction_reason" in dag and len(dag):
                    reden = str(dag["coastal_correction_reason"].mode().iloc[0])
                bron = f"ERA5-archief; land-zeecorrectie niet toegepast ({reden})"
        else:
            bron = "forecast"
        return Weer(dfv, dict(kandidaat), lat, lon, tz,
                    f"online (Open-Meteo, {bron})", self.aqi(lat, lon))

    # -------------------------------------------------------------- excel
    def excel(self, pad: str, start: pd.Timestamp, eind: pd.Timestamp, route: str) -> Weer:
        hl, *_ = _suite()
        pad = Path(pad)
        if str(pad) not in self._xl:
            self._xl[str(pad)] = _CacheXL(pad)
        xl = self._xl[str(pad)]
        gevonden, gezien = hl._zoek_blad(xl, start, eind)
        if gevonden is None:
            raise ValueError(
                f"Geen tabblad in {pad.name} heeft volledige weerdata voor "
                f"{start:%Y-%m-%d %H:%M} - {eind:%H:%M}.\nBeschikbaar:\n  " + "\n  ".join(gezien))
        df, city, lat, lon, tz, sheet = gevonden
        if route == "platteland":
            vsl = (str(pad), sheet, "platteland")
            if vsl not in self._verwerkt:
                meta = xl.parse("Metadata").iloc[0]
                try:
                    z0 = float(meta.get("roughness_z0", 0.1))
                except (TypeError, ValueError):
                    z0 = 0.1
                self._verwerkt[vsl] = _ruraal(df, lat, lon, tz, z0 if np.isfinite(z0) else 0.1)
            df = self._verwerkt[vsl]
        meta = xl.parse("Metadata").iloc[0]
        city = dict(city)
        try:
            city["population"] = int(meta.get("population", 0) or 0)
        except (TypeError, ValueError):
            city["population"] = 0
        return Weer(df, city, lat, lon, tz, f"{pad.name} / {sheet}", self.aqi(lat, lon))

    def excel_bereik(self, pad: str) -> list[str]:
        if str(pad) not in self._xl:
            self._xl[str(pad)] = _CacheXL(Path(pad))
        return self._xl[str(pad)].bereik()


def weer_venster(inv) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Hetzelfde venster als hestia_loper.analyseer_loper(gevoeligheid=False):
    start .. start + looptijd + 60 min (de nafinishfase)."""
    return inv.start, inv.start + pd.Timedelta(minutes=inv.afstand_km * inv.tempo + 60)


def controleer_dekking(weer: Weer, inv) -> None:
    """Zelfde eis als hestia_loper._weer (online) en _zoek_blad (excel): het
    hele venster [start-1u, eind+1u] aanwezig en zonder ontbrekende waarden."""
    hl, *_ = _suite()
    start, eind = weer_venster(inv)
    lo = (start - pd.Timedelta(hours=1)).floor("h").tz_localize(weer.tz, ambiguous=True,
                                                                 nonexistent="shift_forward")
    hi = (eind + pd.Timedelta(hours=1)).ceil("h").tz_localize(weer.tz, ambiguous=True,
                                                               nonexistent="shift_forward")
    kol = [c for c in hl.WEER_KOLOMMEN if c in weer.df.columns]
    v = weer.df.loc[lo:hi, kol]
    if len(v) == 0 or v.index.min() > lo or v.index.max() < hi:
        raise ValueError(f"Het weer dekt {start:%d-%m %H:%M} - {eind:%H:%M} niet volledig "
                         f"(beschikbaar {weer.df.index.min():%d-%m %H:%M} t/m "
                         f"{weer.df.index.max():%d-%m %H:%M}).")
    if v.isna().any().any():
        raise ValueError("Het weer heeft ontbrekende waarden in het loopvenster.")


@dataclass
class Taak:
    gen: int
    inv: object
    af: object
    weer: Weer
    n: int
    seed: int
    interp: list
    profielen: list
    met_ref: float
    clo: float
    tf: float
    accl: float
    start_aware: pd.Timestamp
    finish_aware: pd.Timestamp
    meteo: dict
    wind_fysiologie: np.ndarray
    traces: dict = field(default_factory=dict)
    traces_vrij: dict = field(default_factory=dict)   # zonder hartplafond (scatter)
    vrij_ingediend: bool = False


def bereid_voor(gen: int, inv, weer: Weer, n: int, seed: int) -> Taak:
    """Alle stappen van run_individual_assessment() VOOR de ensemble-lus."""
    hl, ie, hm, hb, _ = _suite()
    waarsch = inv.valideer()
    af = hl.afleiden(inv)
    af.waarschuwingen = waarsch + af.waarschuwingen
    controleer_dekking(weer, inv)
    pi, sc = hl._maak_inputs(inv, af)
    pi.validate()
    finish_local = sc.start_local + pd.Timedelta(minutes=sc.duration_minutes)
    start_aware = ie._localize_naive(sc.start_local, weer.tz)
    finish_aware = ie._localize_naive(finish_local, weer.tz)
    interp = hb.build_interp_data(weer.df, start_aware, finish_aware)
    meteo = ie.meteo_timeseries(weer.df, start_aware, finish_aware)
    met_ref = hm._daniels_gilbert_vo2_at_pace(pi.expected_pace_min_per_km) / hm.VO2MAX_TO_MET_FACTOR
    accl = 1.0 if pi.heat_acclimatized else 0.0
    rng = np.random.default_rng(seed)
    hook = hl._hook(inv)
    profielen = [hook(ie._build_profile(pi, rng)) for _ in range(n)]
    wind15 = np.array([hm.wind_speed_at_height(r["wind"], 10, 1.5) for r in interp], dtype=float)
    return Taak(gen=gen, inv=inv, af=af, weer=weer, n=n, seed=seed, interp=interp,
                profielen=profielen, met_ref=met_ref, clo=sc.clo_value, tf=af.training_factor,
                accl=accl, start_aware=start_aware, finish_aware=finish_aware, meteo=meteo,
                wind_fysiologie=wind15)


def taak_argumenten(t: Taak, plafond: bool = True):
    for i, p in enumerate(t.profielen):
        yield (t.gen, i, t.interp, t.weer.lat, t.weer.lon, t.met_ref, t.clo, p, t.tf,
               t.accl, t.seed, t.weer.aqi, plafond)


# SCATTER T_rect - CO_reserve (verzoek 2026-11-20)
# ------------------------------------------------
# Met het geforceerde hartplafond (hestia_model.CV_CEILING_FORCED = True, de
# suite-standaard) vertraagt de loper zodra het hart aan zijn plafond zit,
# en blijft CO_reserve tijdens de loop rond 0. Alleen voor de scatterplot
# draait een tweede ensemble met CV_CEILING_FORCED = False: zelfde profielen,
# zelfde seeds, maar de loper houdt het tempo vast. CO_reserve loopt dan door
# in negatieve waarden: de ONVERVULDE zuurstofvraag in liters bloed per minuut
# (HESTIA_CVR_Module_v2, 'MODELKEUZE, NIET GEVALIDEERD'), geen stromend bloed.
# De punten zijn alle tijdstappen van alle leden (loop + nafinish), zoals de
# scatter_pairs van Klimatos; zones, kleuring en dichtstbijzijnde-punt-
# markeringen volgen Klimatos_ClimateShift.plot_trect_co_reserve_scatter.
def scatter_paren(sporen) -> list:
    paren = []
    for res in sporen:
        for r in res:
            t, c = r.get("t_rect"), r.get("co_reserve")
            if t is not None and c is not None and np.isfinite(t) and np.isfinite(c):
                paren.append((float(t), float(c)))
        if res:
            for t, c in zip(res[-1].get("t_rect_series_postfinish") or [],
                            res[-1].get("co_reserve_series_postfinish") or []):
                if t is not None and c is not None and np.isfinite(t) and np.isfinite(c):
                    paren.append((float(t), float(c)))
    return paren


def voorlopige_banden(t: Taak) -> Optional[dict]:
    _, ie, *_ = _suite()
    if not t.traces:
        return None
    sporen = [t.traces[i] for i in sorted(t.traces)]
    return ie._extended_bands(sporen)


_TERUGSPEEL_SLOT = threading.Lock()


@contextmanager
def _vervang(module, naam, nieuw):
    oud = getattr(module, naam)
    setattr(module, naam, nieuw)
    try:
        yield
    finally:
        setattr(module, naam, oud)


def eindresultaat(t: Taak):
    """Loopt door de echte hestia_loper.analyseer_loper(gevoeligheid=False);
    calculate_indices_jos3_adult wordt vervangen door het teruggeven van de al
    berekende leden, _weer door het al geladen weer."""
    hl, ie, *_ = _suite()
    sporen = [t.traces[i] for i in range(t.n)]
    teller = iter(range(t.n))

    def terugspelen(interp_data, lat, lon, met_value, clo_value, profile, tf, accl):
        i = next(teller)
        if asdict(profile) != asdict(t.profielen[i]):
            raise RuntimeError(f"Profiel van lid {i} wijkt af van het berekende profiel.")
        if (len(interp_data) != len(t.interp) or abs(clo_value - t.clo) > 1e-12
                or abs(tf - t.tf) > 1e-12 or abs(accl - t.accl) > 1e-12):
            raise RuntimeError("Invoer van het terugspelen wijkt af van de berekening.")
        return sporen[i]

    with _TERUGSPEEL_SLOT, \
            _vervang(ie, "calculate_indices_jos3_adult", terugspelen), \
            _vervang(hl, "_weer", lambda inv, eind: (t.weer.tuple, t.weer.label)):
        r = hl.analyseer_loper(t.inv, n_ensemble=t.n, seed=t.seed, gevoeligheid=False)
    if next(teller, None) is not None:
        raise RuntimeError("Niet alle berekende leden zijn teruggespeeld.")
    return r


# =============================================================================
# 2b. RUSTTOESTAND (HEAT-Lim, exact zoals Klimatos_ClimateShift)
# =============================================================================
# Keuze 2026-11-20 (optie 1): de rusttoestand wordt NIET met een eigen
# rustsimulatie berekend, maar met HEAT-Lim (Vanos et al. 2023) zoals de suite
# het in Klimatos gebruikt: Klimatos_ClimateShift.compute_mmax_met() met de
# twee gepubliceerde profielen LIVEABILITY_PROFILES ('young' 18-40, 'old' 65+)
# en dezelfde instellingen (LIVEABILITY_EXP_TIME, _SUN, _TA_MIN, _MIN_WIND,
# _ACTIVITY_MET) en dezelfde invoerkolommen als liveability_year_metrics():
# T_air_urban, RH_urban, wind_1.5m (ondergrens), MRT. Per uur, zoals Klimatos.
# Persoonsgegevens worden niet gebruikt: HEAT-Lim rekent met vaste profielen.
# Herkomst: 3 en 4 zijn HEAT-Lim-uitkomsten (livability_Mmax: non_livable;
# Survivability: False); de grenzen 3 MET en 25 °C zijn Klimatos-instellingen
# (LIVEABILITY_ACTIVITY_MET, LIVEABILITY_TA_MIN), geen HEAT-Lim-grenzen.
RUST_CAT = {0: "niet beoordeeld: < 25 °C (Klimatos-grens)",
            1: "leefbaar, ≥ 3 MET (Klimatos-grens)",
            2: "leefbaar, < 3 MET (Klimatos-grens)",
            3: "rust niet leefbaar (HEAT-Lim)",
            4: "niet overleefbaar bij 3 u aanhoudend (HEAT-Lim)"}
RUST_CAT_KORT = {0: "niet beoordeeld (< 25 °C)", 1: "leefbaar (≥ 3 MET)", 2: "leefbaar, < 3 MET",
                 3: "rust niet leefbaar", 4: "niet overleefbaar bij 3 u aanhoudend"}


@dataclass
class RustResultaat:
    weer: Weer
    start_aware: pd.Timestamp
    eind_aware: pd.Timestamp
    uren: list
    ta: np.ndarray
    rh: np.ndarray
    av: np.ndarray
    mrt: np.ndarray
    mmax: dict          # profiel -> Mmax [MET] per uur (NaN = niet compenseerbaar/beoordeeld)
    surv: dict          # profiel -> overleefbaar per uur
    cat: dict           # profiel -> categorie per uur (RUST_CAT)
    beoordeeld: np.ndarray
    meteo: dict
    instellingen: dict


def bereken_rust(weer: Weer, start: pd.Timestamp, eind: pd.Timestamp,
                 zon: Optional[bool] = None) -> RustResultaat:
    """zon=None volgt Klimatos (LIVEABILITY_SUN); True = 'outdoor' (MRT uit de
    Data Engine), False = 'shade' (MRT = luchttemperatuur), dezelfde twee
    standen als Klimatos kent."""
    _, ie, *_ = _suite()
    import Klimatos_ClimateShift as K
    s = start.tz_localize(weer.tz, ambiguous=True, nonexistent="shift_forward")
    e = eind.tz_localize(weer.tz, ambiguous=True, nonexistent="shift_forward")
    d = weer.df.loc[s.floor("h"):e.ceil("h")]
    nodig = ["T_air_urban", "wind_1.5m", "MRT", "RH_urban" if "RH_urban" in weer.df.columns else "RH"]
    ontbreekt = [c for c in nodig if c not in weer.df.columns]
    if ontbreekt:
        raise ValueError("Het weer mist kolommen voor HEAT-Lim: " + ", ".join(ontbreekt))
    if len(d) == 0 or d.index.min() > s.floor("h") or d.index.max() < e.ceil("h"):
        raise ValueError(f"Het weer dekt {start:%d-%m %H:%M} - {eind:%d-%m %H:%M} niet volledig "
                         f"(beschikbaar {weer.df.index.min():%d-%m %H:%M} t/m "
                         f"{weer.df.index.max():%d-%m %H:%M}).")
    if d[nodig].isna().any().any():
        raise ValueError("Het weer heeft ontbrekende waarden in dit venster.")
    # --- zoals Klimatos_ClimateShift.liveability_year_metrics() -------------
    Ta = d["T_air_urban"].values
    RH = d["RH_urban"].values if "RH_urban" in d.columns else d["RH"].values
    Av = np.clip(d["wind_1.5m"].values, K.LIVEABILITY_MIN_WIND, None)
    if zon is None:
        zon = K.LIVEABILITY_SUN == "outdoor"
    mrt = d["MRT"].values if zon else Ta.copy()
    warm = Ta >= K.LIVEABILITY_TA_MIN
    mmax, surv, cat = {}, {}, {}
    for pkey, prof in K.LIVEABILITY_PROFILES.items():
        mm = np.full(len(Ta), np.nan)
        sv = np.ones(len(Ta), dtype=bool)
        if warm.any():
            m_w, s_w = K.compute_mmax_met(Ta[warm], RH[warm], Av[warm], mrt[warm], prof)
            mm[warm], sv[warm] = m_w, s_w
        c = np.zeros(len(Ta), dtype=int)
        c[warm] = 1
        c[warm & ~(mm >= K.LIVEABILITY_ACTIVITY_MET)] = 2     # NaN telt als 'onder', zoals hrsBelow
        c[warm & np.isnan(mm) & sv] = 3                       # hrsNonLiv
        c[warm & ~sv] = 4                                     # hrsNonSurv
        mmax[pkey], surv[pkey], cat[pkey] = mm, sv, c
    meteo = ie.meteo_timeseries(weer.df, s, e)
    inst = {"blootstelling_u": K.LIVEABILITY_EXP_TIME, "zon": "outdoor" if zon else "shade",
            "ta_min": K.LIVEABILITY_TA_MIN, "wind_min": K.LIVEABILITY_MIN_WIND,
            "activiteit_met": K.LIVEABILITY_ACTIVITY_MET,
            "rustniveau_met": {k: K.rest_floor_met(p) for k, p in K.LIVEABILITY_PROFILES.items()},
            "profielen": K.LIVEABILITY_PROFILES}
    return RustResultaat(weer, s, e, list(d.index), Ta, RH, Av, mrt, mmax, surv, cat, warm,
                         meteo, inst)


def rust_profielen_voor_leeftijd(leeftijd: int) -> list[str]:
    """HEAT-Lim heeft alleen 'young' (18-40) en 'old' (65+); daartussen geen profiel."""
    if leeftijd <= 40:
        return ["young"]
    if leeftijd >= 65:
        return ["old"]
    return ["young", "old"]


def rust_tabel(r: RustResultaat) -> pd.DataFrame:
    t = pd.DataFrame({"tijd": [x.tz_localize(None) for x in r.uren], "T_air (°C)": r.ta,
                      "RH (%)": r.rh, "wind 1,5 m HEAT-Lim (m/s)": r.av,
                      "MRT HEAT-Lim (°C)" + (" = T_air (schaduw)" if r.instellingen["zon"] == "shade" else ""): r.mrt})
    for k, naam in (("young", "18-40"), ("old", "65+")):
        t[f"Mmax {naam} (MET)"] = r.mmax[k]
        t[f"overleefbaar {naam}"] = r.surv[k]
        t[f"categorie {naam}"] = [RUST_CAT[c] for c in r.cat[k]]
    return t


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
    import ui_gemeen as ug

    LETTER = 12
    matplotlib.rcParams.update({"font.size": 11, "axes.titlesize": 12,
                                "axes.titleweight": "bold", "axes.grid": True,
                                "grid.alpha": 0.3, "legend.fontsize": 9})
    KLEUR = {"lijn": "#1f5fa8", "band": "#1f5fa8", "rood": "#c0392b", "oranje": "#e67e22",
             "geel": "#d4ac0d", "groen": "#27ae60", "grijs": "#7f8c8d"}
    KORT_LABEL = {
        "koorts_of_ziekte_recent": "Koorts of (darm)infectie, afgelopen week",
        "slecht_geslapen": "Slecht of kort geslapen",
        "alcohol_dag_ervoor": "Alcohol de dag ervoor",
        "eerder_hitteziekte": "Eerder hitteziekte gehad",
        "medicatie_hart_bloeddruk_zweten": "Medicatie hart/bloeddruk/zweten",
        "hart_vaat_aandoening": "Hart- of vaataandoening",
    }
    assert set(KORT_LABEL) == set(hl.NIET_GEMODELLEERD)
    SIGNAAL_KLEUR = {"groen": "#27ae60", "geel": "#d4ac0d", "oranje": "#e67e22", "rood": "#c0392b"}

    class App:
        def __init__(self, root):
            self.root = root
            root.title("HESTIA · persoonlijke hitte-analyse voor hardlopers  (research software)")
            for naam in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont"):
                try:
                    tkfont.nametofont(naam).configure(size=LETTER)
                except tk.TclError:
                    pass
            st = ttk.Style()
            st.configure("Kop.TLabel", font=("TkDefaultFont", LETTER + 1, "bold"))
            st.configure("TLabelframe.Label", font=("TkDefaultFont", LETTER, "bold"))
            bw, bh = root.winfo_screenwidth(), root.winfo_screenheight()
            root.geometry(f"{min(1800, bw - 40)}x{min(1040, bh - 80)}+10+10")
            ug.maximaliseer(root)

            self.weerbron = WeerBron()
            self.kandidaten: list[dict] = []
            self.gen = 0
            self.taak: Optional[Taak] = None
            self.futures = []
            self.q: queue.Queue = queue.Queue()
            self._plan = None
            self._weer_sleutel = None
            self._weer: Optional[Weer] = None
            self.resultaat = None
            self._laatst_getekend = 0.0
            self.pool = ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1),
                                            initializer=_werker_init)
            for _ in range(self.pool._max_workers):
                self.pool.submit(_opwarmen)

            self._bouw()
            self._poll()
            root.protocol("WM_DELETE_WINDOW", self._sluit)

        # ----------------------------------------------------------- opbouw
        def _bouw(self):
            links = ttk.Frame(self.root, padding=6)
            links.pack(side="left", fill="y")
            canvas = tk.Canvas(links, width=ug.px(self.root, 540), highlightthickness=0)
            sb = ttk.Scrollbar(links, orient="vertical", command=canvas.yview)
            self.form = ttk.Frame(canvas)
            self.form.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=self.form, anchor="nw")
            canvas.configure(yscrollcommand=sb.set)
            canvas.pack(side="left", fill="y", expand=False)
            sb.pack(side="left", fill="y")
            canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
            canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-2, "units"))
            canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(2, "units"))

            self.v = {}
            self.hint = {}
            self.widget = {}
            self.suiteveld = {}
            self.rust = None
            self._focus = None
            ug.invoer_legenda(self.form, LETTER)
            r = self._sectie("Persoon", "verplicht")
            self._keuze(r, "geslacht", "Geslacht", ["man", "vrouw"], "man")
            self._getal(r, "leeftijd", "Leeftijd (jaar)", "45")
            self._getal(r, "gewicht", "Gewicht (kg)", "75")
            self._getal(r, "lengte", "Lengte (cm)", "180")

            r = self._sectie("Fitheid", "verplicht")
            self._getal(r, "trainingskm", "Training (km/week)", "30")
            self._vink(r, "acclim", "Hitte-geacclimatiseerd", False)

            r = self._sectie("Fitheid, nauwkeuriger", "optioneel",
                             "Leeg laten mag. Grijs = waarde die de suite dan zelf gebruikt; een eigen "
                             "meting maakt de berekening persoonlijker.")
            self._getal(r, "hr_rust", "Rusthartslag (/min)", "", hint="Lloyd 2022, vgl. 9", suite=True)
            self._getal(r, "hr_max", "Max. hartslag (/min)", "", hint="Tanaka 2001", suite=True)
            self._getal(r, "vo2max", "VO2max (mL/kg/min)", "", hint="", suite=True)
            self._getal(r, "wedstr_km", "Recente wedstrijd: km", "", hint="alleen voor VO2max",
                        suite=True)
            self._getal(r, "wedstr_tijd", "Recente wedstrijd: tijd", "", hint="u:mm:ss / mm:ss",
                        suite=True)
            self._getal(r, "vet", "Vetpercentage (%)", "", hint="Nikolaidis 2021", suite=True)
            self.lbl_vo2_bron = self.hint["vo2max"]

            r = self._sectie("Activiteit", "verplicht")
            self._keuze(r, "activiteit", "Activiteit", ["hardlopen", "rust (HEAT-Lim)"], "hardlopen")
            self.v["activiteit"].trace_add("write", lambda *a: self._wissel_modus())
            self._getal(r, "duur", "Duur in rust (uur)", "6")
            self._keuze(r, "zon", "Rust in", ["zon", "schaduw"], "zon")
            self._getal(r, "afstand", "Afstand (km)", "10")
            rij = self._rij(r, "Verwachte snelheid")
            self.v["snelheid"] = tk.StringVar(value="11")
            e = ttk.Entry(rij, textvariable=self.v["snelheid"], width=7)
            e.pack(side="left")
            self.widget["snelheid"] = e
            self.v["eenheid"] = tk.StringVar(value="km/u")
            cb = ttk.Combobox(rij, textvariable=self.v["eenheid"], values=["km/u", "min/km"],
                              width=7, state="readonly")
            cb.pack(side="left", padx=4)
            self.widget["eenheid"] = cb
            self.v["snelheid"].trace_add("write", lambda *a: self._gewijzigd())
            self.v["eenheid"].trace_add("write", lambda *a: self._eenheid_om())
            self._eenheid_vorig = "km/u"
            self.lbl_tempo = ttk.Label(r, text="", foreground="#555")
            self.lbl_tempo.pack(anchor="w", padx=4)
            self._keuze(r, "kleding", "Kleding",
                        ["licht (singlet + korte broek)", "normaal (T-shirt + korte broek)",
                         "lang (lange mouwen/broek)"], "licht (singlet + korte broek)")
            self._vink(r, "drinkt", "Drinkt bij elke post", True)
            self._vink(r, "nsaid", "NSAID (bijv. ibuprofen) voor/tijdens", False)

            r = self._sectie("Datum, tijd en plaats", "verplicht")
            self._getal(r, "datum", "Datum (JJJJ-MM-DD)", pd.Timestamp.now().strftime("%Y-%m-%d"),
                        weer=True)
            rij = self._rij(r, "Starttijd")
            self.v["start_min"] = tk.DoubleVar(value=10 * 60)
            self.v["starttijd"] = tk.StringVar(value="10:00")
            ent = ttk.Entry(rij, textvariable=self.v["starttijd"], width=6)
            ent.pack(side="left")
            ent.bind("<Return>", lambda e: self._tijd_uit_tekst())
            ent.bind("<FocusOut>", lambda e: self._tijd_uit_tekst())
            sc = ttk.Scale(r, from_=0, to=23 * 60 + 55, variable=self.v["start_min"],
                           command=lambda x: self._schuif())
            sc.pack(fill="x", padx=4, pady=(0, 4))

            self._keuze(r, "bron", "Weerbron", ["online (Open-Meteo)", "Data Engine-bestand"],
                        "online (Open-Meteo)", weer=True)
            rij = self._rij(r, "Plaats")
            self.v["plaats"] = tk.StringVar(value="Schagen")
            pe = ttk.Entry(rij, textvariable=self.v["plaats"], width=16)
            pe.pack(side="left")
            pe.bind("<Return>", lambda e: self._zoek_plaats())
            ttk.Button(rij, text="Zoek", command=self._zoek_plaats, width=6).pack(side="left", padx=3)
            self.v["kandidaat"] = tk.StringVar(value="")
            self.cb_kand = ttk.Combobox(r, textvariable=self.v["kandidaat"], state="readonly", width=44)
            self.cb_kand.pack(fill="x", padx=4, pady=2)
            self.cb_kand.bind("<<ComboboxSelected>>", lambda e: self._weer_gewijzigd())
            rij = self._rij(r, "Bestand")
            self.v["excel"] = tk.StringVar(value="")
            ttk.Entry(rij, textvariable=self.v["excel"], width=16).pack(side="left")
            ttk.Button(rij, text="Kies…", command=self._kies_excel, width=6).pack(side="left", padx=3)
            self._keuze(r, "route", "Route", ["stad", "platteland"], "stad", weer=True)

            r = self._sectie("Niet in het model", "melding",
                             "Deze factoren rekent het model niet mee; aanvinken geeft alleen een "
                             "waarschuwing bij de uitkomst.")
            for k, kort in KORT_LABEL.items():
                self._vink(r, k, kort, False, herreken=False)

            r = self._sectie("Berekening en bestanden", "model",
                             "Aantal ensemble-leden en seed: standaard van de suite. Meer leden = "
                             "nauwkeuriger banden, maar langzamer.")
            self._getal(r, "n", "Ensemble-leden", "200")
            self._getal(r, "seed", "Seed", "42")
            rij = ttk.Frame(r)
            rij.pack(fill="x", pady=4)
            ttk.Button(rij, text="Invoer opslaan", command=self._opslaan).pack(side="left", padx=2)
            ttk.Button(rij, text="Invoer laden", command=self._laden).pack(side="left", padx=2)
            ttk.Button(rij, text="Excel-export", command=self._export).pack(side="left", padx=2)

            # ------------------------------------------------ rechts: grafieken
            rechts = ttk.Frame(self.root, padding=(4, 6))
            rechts.pack(side="left", fill="both", expand=True)
            boven = ttk.Frame(rechts)
            boven.pack(fill="x")
            # Knoppen eerst plaatsen: dan blijven ze altijd zichtbaar, ook bij een lange kop- of statustekst.
            self.pb = ttk.Progressbar(boven, length=ug.px(self.root, 160), maximum=1.0)
            self.pb.pack(side="right")
            ttk.Button(boven, text="Scatter T_rect–CO_reserve", command=self._open_scatter).pack(
                side="right", padx=8)
            self.lbl_signaal = tk.Label(boven, text="  —  ", font=("TkDefaultFont", LETTER + 2, "bold"),
                                        bg="#dddddd", padx=10, pady=4)
            self.lbl_signaal.pack(side="left")
            self.lbl_status = ttk.Label(rechts, text="", font=("TkDefaultFont", LETTER - 1), foreground="#444")
            self.lbl_status.pack(fill="x", padx=4, pady=(2, 0))
            self.sc_win = None
            self._sc_getekend = 0.0

            self.nb = ttk.Notebook(rechts)
            self.nb.pack(fill="both", expand=True, pady=(4, 0))
            tab_u = ttk.Frame(self.nb, padding=(2, 4))
            tab_g = ttk.Frame(self.nb, padding=(2, 2))
            self.nb.add(tab_u, text="  Uitkomst  ")
            self.nb.add(tab_g, text="  Grafieken  ")
            ug.tab_uitleg(tab_u, "De uitkomst in het kort: kerncijfers en de volledige toelichting. Het tabblad "
                                 "Grafieken toont het weer, de kerntemperatuur en de CO-reserve tijdens de loop.", LETTER)
            self.tegels = ug.Tegels(tab_u, LETTER)
            self.tegels.pack(fill="x", pady=(2, 4))
            self.herkomst = ug.Herkomst(tab_u, LETTER)
            self.herkomst.pack(side="bottom", fill="x", pady=(4, 0))

            self.fig = Figure(figsize=(12, 8.0), dpi=96, constrained_layout=True)
            gs = self.fig.add_gridspec(3, 2)
            self.ax = {
                "t": self.fig.add_subplot(gs[0, 0]), "wbgt": self.fig.add_subplot(gs[0, 1]),
                "rh": self.fig.add_subplot(gs[1, 0]), "wind": self.fig.add_subplot(gs[1, 1]),
                "kern": self.fig.add_subplot(gs[2, 0]), "co": self.fig.add_subplot(gs[2, 1]),
            }
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

            self._toon_tempo()
            self._suitewaarden()
            self._wissel_modus(herbereken=False)
            self.root.after(300, self._zoek_plaats)

        def _sectie(self, titel, soort="verplicht", uitleg=""):
            return ug.sectie(self.form, titel, soort, LETTER, uitleg)

        def _rij(self, ouder, label):
            rij = ttk.Frame(ouder)
            rij.pack(fill="x", pady=1)
            ttk.Label(rij, text=label, width=22).pack(side="left")
            return rij

        def _getal(self, ouder, sleutel, label, standaard, hint="", weer=False, suite=False):
            rij = self._rij(ouder, label)
            self.v[sleutel] = tk.StringVar(value=standaard)
            e = ttk.Entry(rij, textvariable=self.v[sleutel], width=10)
            e.pack(side="left")
            self.widget[sleutel] = e
            self.hint[sleutel] = ttk.Label(rij, text=hint, foreground="#777")
            self.hint[sleutel].pack(side="left", padx=4)
            cb = self._weer_gewijzigd if weer else self._gewijzigd
            self.v[sleutel].trace_add("write", lambda *a: cb())
            if suite:
                # Grijze waarde IN het veld zolang het leeg is en geen focus heeft.
                # Het is een label boven op het invoerveld: de StringVar blijft leeg,
                # dus de suite krijgt 'onbekend' en rekent zelf met deze waarde.
                bg = ttk.Style().lookup("TEntry", "fieldbackground") or "white"
                lbl = tk.Label(e, text="", fg="#8c8c8c", bg=bg, bd=0, padx=0, pady=0,
                               font=("TkDefaultFont", LETTER, "italic"), anchor="w")
                lbl.bind("<Button-1>", lambda ev: e.focus_set())

                def focus(aan):
                    self._focus = sleutel if aan else None
                    self._toon_suitewaarde(sleutel)
                e.bind("<FocusIn>", lambda ev: focus(True), add="+")
                e.bind("<FocusOut>", lambda ev: focus(False), add="+")
                self.v[sleutel].trace_add("write", lambda *a: self._toon_suitewaarde(sleutel))
                self.suiteveld[sleutel] = (e, lbl)

        LOOP_VELDEN = ["geslacht", "gewicht", "lengte", "trainingskm", "hr_rust", "hr_max", "vo2max",
                       "wedstr_km", "wedstr_tijd", "vet", "acclim", "afstand", "snelheid", "eenheid",
                       "kleding", "drinkt", "nsaid", "n", "seed"]
        RUST_VELDEN = ["duur", "zon"]

        def _is_rust(self):
            return self.v["activiteit"].get().startswith("rust")

        def _wissel_modus(self, herbereken=True):
            rust = self._is_rust()
            for k in self.LOOP_VELDEN:
                self.widget[k].state(["disabled"] if rust else ["!disabled"])
            for k in self.RUST_VELDEN:
                self.widget[k].state(["!disabled"] if rust else ["disabled"])
            self._toon_tempo()
            if herbereken:
                self._gewijzigd()

        def _toon_suitewaarde(self, k):
            e, lbl = self.suiteveld[k]
            if self.v[k].get() == "" and self._focus != k and lbl.cget("text"):
                lbl.place(x=4, rely=0.5, anchor="w")
            else:
                lbl.place_forget()

        def _suitewaarden(self):
            """Berekent met de suitefuncties welke waarden het model gebruikt voor
            de lege optionele velden (dezelfde aanroepen als in de berekening)."""
            from HESTIA_CVR_Module_v2 import CVRModel, RunnerProfile
            w = {k: "" for k in self.suiteveld}
            bron_vo2 = ""
            try:
                geslacht = self.v["geslacht"].get()
                leeftijd = int(self._f("leeftijd"))
                try:
                    tempo = hl.min_naar_tempo(self._tempo())
                except Exception:
                    tempo = "6:00"
                basis = dict(lengte_cm=self._f("lengte"), gewicht_kg=self._f("gewicht"),
                             leeftijd=leeftijd, geslacht=geslacht, evenement="-",
                             datum="2026-01-01", starttijd="12:00", plaats="-", afstand_km=10,
                             tempo_min_per_km=tempo, weerbron="online",
                             hitte_geacclimatiseerd=self.v["acclim"].get(),
                             vo2max_bekend=self._f("vo2max", True),
                             trainingskm_per_week=self._f("trainingskm", True) or 0)
                try:
                    af = hl.afleiden(hl.LoperInvoer(
                        **basis, wedstrijd_afstand_km=self._f("wedstr_km", True),
                        wedstrijd_tijd=self.v["wedstr_tijd"].get().strip() or None))
                except Exception:          # onvolledige/onleesbare wedstrijd: zonder
                    af = hl.afleiden(hl.LoperInvoer(**basis))
                inv0 = hl.LoperInvoer(**basis)
                w["vo2max"] = hl.nl(af.vo2max)
                bron_vo2 = ("uit wedstrijd" if "wedstrijd" in af.vo2max_bron
                            else "populatiegemiddelde" if "populatie" in af.vo2max_bron else "")
                cvr = CVRModel(RunnerProfile(
                    mass=inv0.gewicht_kg, height=inv0.lengte_cm, age=leeftijd,
                    sex=inv0.gender_en, vo2max=af.vo2max,
                    hr_max=self._f("hr_max", True), hr_rest=None,
                    acclimatisation=1.0 if self.v["acclim"].get() else 0.0))
                w["hr_rust"] = f"{cvr.HR_rest:.0f}"
                w["hr_max"] = f"{cvr.HR_max:.0f}"
                w["vet"] = hl.nl(ie._default_body_fat_pct(inv0.gender_en))
                w["wedstr_km"] = w["wedstr_tijd"] = "—"
            except Exception:
                pass
            for k, (e, lbl) in self.suiteveld.items():
                lbl.config(text=w[k])
                self._toon_suitewaarde(k)
            self.lbl_vo2_bron.config(text=bron_vo2 if self.v["vo2max"].get() == "" else "")

        def _keuze(self, ouder, sleutel, label, waarden, standaard, weer=False):
            rij = self._rij(ouder, label)
            self.v[sleutel] = tk.StringVar(value=standaard)
            w = ttk.Combobox(rij, textvariable=self.v[sleutel], values=waarden, state="readonly",
                             width=max(10, max(len(w) for w in waarden) - 4))
            w.pack(side="left")
            self.widget[sleutel] = w
            cb = self._weer_gewijzigd if weer else self._gewijzigd
            self.v[sleutel].trace_add("write", lambda *a: cb())

        def _vink(self, ouder, sleutel, label, standaard, herreken=True):
            self.v[sleutel] = tk.BooleanVar(value=standaard)
            w = ttk.Checkbutton(ouder, text=label, variable=self.v[sleutel])
            w.pack(anchor="w")
            self.widget[sleutel] = w
            if herreken:
                self.v[sleutel].trace_add("write", lambda *a: self._gewijzigd())
            else:
                self.v[sleutel].trace_add("write", lambda *a: self._toon_tekst())

        # ---------------------------------------------------- invoer lezen
        def _f(self, k, opt=False):
            s = self.v[k].get().strip().replace(",", ".")
            if s == "":
                if opt:
                    return None
                raise ValueError(f"'{k}' is leeg")
            return float(s)

        def _tempo(self) -> float:
            x = self.v["snelheid"].get().strip().replace(",", ".")
            if self.v["eenheid"].get() == "km/u":
                kmu = float(x)
                if kmu <= 0:
                    raise ValueError("snelheid moet groter dan 0 zijn")
                return 60.0 / kmu
            return hl.tempo_naar_min(x)

        def _eenheid_om(self):
            nieuw = self.v["eenheid"].get()
            if nieuw == self._eenheid_vorig:
                return
            try:
                oud = self._eenheid_vorig
                self._eenheid_vorig = nieuw
                x = self.v["snelheid"].get().strip().replace(",", ".")
                if oud == "km/u":
                    self.v["snelheid"].set(hl.min_naar_tempo(60.0 / float(x)))
                else:
                    self.v["snelheid"].set(f"{60.0 / hl.tempo_naar_min(x):.2f}".replace(".", ","))
            except Exception:
                pass

        def _toon_tempo(self):
            if self._is_rust():
                self.lbl_tempo.config(text="")
                return
            try:
                t = self._tempo()
                km = self._f("afstand")
                self.lbl_tempo.config(text=f"= {hl.min_naar_tempo(t)} min/km, {60 / t:.1f} km/u; "
                                           f"looptijd ≈ {hl.min_naar_tempo(km * t)} (mm:ss)".replace(".", ",", 1))
            except Exception:
                self.lbl_tempo.config(text="")

        def _kleding(self):
            return self.v["kleding"].get().split()[0]

        def _invoer(self):
            d = pd.Timestamp(self.v["datum"].get().strip()).strftime("%Y-%m-%d")
            wk, wt = self._f("wedstr_km", True), self.v["wedstr_tijd"].get().strip() or None
            excel = self.v["bron"].get().startswith("Data")
            kw = dict(
                lengte_cm=self._f("lengte"), gewicht_kg=self._f("gewicht"),
                leeftijd=int(self._f("leeftijd")), geslacht=self.v["geslacht"].get(),
                evenement="Hardloop-UI", datum=d, starttijd=self.v["starttijd"].get().strip(),
                plaats=self._plaatsnaam(), afstand_km=self._f("afstand"),
                tempo_min_per_km=hl.min_naar_tempo(self._tempo()),
                drinkt_bij_elke_post=self.v["drinkt"].get(),
                nsaid_voor_of_tijdens=self.v["nsaid"].get(),
                hitte_geacclimatiseerd=self.v["acclim"].get(),
                kleding=self._kleding(), trainingskm_per_week=self._f("trainingskm"),
                vo2max_bekend=self._f("vo2max", True),
                wedstrijd_afstand_km=wk, wedstrijd_tijd=wt,
                hr_max_bekend=self._f("hr_max", True), hr_rust_bekend=self._f("hr_rust", True),
                vetpercentage_bekend=self._f("vet", True),
                weerbron="excel" if excel else "online",
                weer_excel=self.v["excel"].get().strip() or None,
                naam="")
            for k in hl.NIET_GEMODELLEERD:
                kw[k] = bool(self.v[k].get())
            return hl.LoperInvoer(**kw)

        def _plaatsnaam(self):
            k = self._kandidaat()
            return k["name"] if k else self.v["plaats"].get().strip()

        def _kandidaat(self) -> Optional[dict]:
            i = self.cb_kand.current()
            return self.kandidaten[i] if 0 <= i < len(self.kandidaten) else None

        # ------------------------------------------------------ gebeurtenissen
        def _schuif(self):
            m = int(round(self.v["start_min"].get() / 5.0)) * 5
            tekst = f"{m // 60:02d}:{m % 60:02d}"
            if self.v["starttijd"].get() != tekst:
                self.v["starttijd"].set(tekst)
                self._gewijzigd(vertraging=250)

        def _tijd_uit_tekst(self):
            try:
                u, m = self.v["starttijd"].get().strip().split(":")
                self.v["start_min"].set(int(u) * 60 + int(m))
                self._gewijzigd()
            except Exception:
                self._fout("Starttijd onleesbaar; gebruik UU:MM.")

        def _gewijzigd(self, vertraging=600):
            self._toon_tempo()
            self._suitewaarden()
            if self._plan is not None:
                self.root.after_cancel(self._plan)
            self._plan = self.root.after(vertraging, self._herbereken)

        def _weer_gewijzigd(self):
            self._weer_sleutel = None
            self._gewijzigd()

        def _zoek_plaats(self):
            naam = self.v["plaats"].get().strip()
            if not naam or self.v["bron"].get().startswith("Data"):
                return
            self.lbl_status.config(text=f"Plaats zoeken: {naam} …")

            def werk():
                try:
                    self.q.put(("kandidaten", de.geocode_city_candidates(naam)))
                except Exception as e:
                    self.q.put(("fout", f"Plaats zoeken mislukt: {e}"))
            threading.Thread(target=werk, daemon=True).start()

        def _kies_excel(self):
            p = filedialog.askopenfilename(title="Data Engine-bestand",
                                           filetypes=[("Excel", "*.xlsx"), ("Alle", "*.*")],
                                           initialdir=str(HIER))
            if p:
                self.v["excel"].set(p)
                self.v["bron"].set("Data Engine-bestand")
                try:
                    self._xl_bereik = self.weerbron.excel_bereik(p)
                except Exception as e:
                    self._fout(f"Bestand niet leesbaar: {e}")

        # -------------------------------------------------------- berekenen
        def _herbereken(self):
            self._plan = None
            if self._is_rust():
                return self._herbereken_rust()
            try:
                inv = self._invoer()
                n, seed = int(self._f("n")), int(self._f("seed"))
                if not 1 <= n <= 2000:
                    raise ValueError("ensemble-leden: 1 t/m 2000")
                inv.valideer()
            except Exception as e:
                self._fout(str(e))
                return
            excel = inv.weerbron == "excel"
            if excel:
                sleutel = ("excel", inv.weer_excel, self.v["route"].get())
            else:
                k = self._kandidaat()
                if k is None:
                    self._fout("Kies eerst een plaats (Zoek).")
                    return
                sleutel = ("online", k.get("id", (k["latitude"], k["longitude"])), inv.datum,
                           self.v["route"].get())
            self._annuleer()
            self.gen += 1
            gen = self.gen
            route = self.v["route"].get()
            if excel or sleutel != self._weer_sleutel or self._weer is None:
                self.lbl_status.config(text="Weer laden …")
                kand = None if excel else self._kandidaat()

                def werk():
                    try:
                        if excel:
                            s, e = weer_venster(inv)
                            w = self.weerbron.excel(inv.weer_excel, s, e, route)
                        else:
                            w = self.weerbron.online(kand, inv.datum, route)
                        self.q.put(("weer", gen, sleutel, w,
                                    lambda w_: self._start(gen, inv, w_, n, seed)))
                    except Exception as ex:
                        self.q.put(("fout", f"Weer: {ex}", gen))
                threading.Thread(target=werk, daemon=True).start()
            else:
                self._start(gen, inv, self._weer, n, seed)

        def _herbereken_rust(self):
            try:
                d = pd.Timestamp(self.v["datum"].get().strip()).strftime("%Y-%m-%d")
                u, mi = self.v["starttijd"].get().strip().split(":")
                start = pd.Timestamp(f"{d} {int(u):02d}:{int(mi):02d}")
                duur = self._f("duur")
                if not 1 <= duur <= 24:
                    raise ValueError("duur in rust: 1 t/m 24 uur")
                int(self._f("leeftijd"))
            except Exception as e:
                self._fout(f"Invoer: {e}")
                return
            eind = start + pd.Timedelta(hours=duur)
            zon = self.v["zon"].get() == "zon"
            excel = self.v["bron"].get().startswith("Data")
            route = self.v["route"].get()
            if excel:
                pad = self.v["excel"].get().strip()
                if not pad:
                    self._fout("Kies een Data Engine-bestand.")
                    return
                sleutel = ("excel", pad, route)
            else:
                kand = self._kandidaat()
                if kand is None:
                    self._fout("Kies eerst een plaats (Zoek).")
                    return
                sleutel = ("online", kand.get("id", (kand["latitude"], kand["longitude"])), d, route)
                if eind.normalize() > pd.Timestamp(d) + pd.Timedelta(days=1):
                    self._fout("Het rustvenster mag niet verder lopen dan de dag na de gekozen datum.")
                    return
            self._annuleer()
            self.gen += 1
            gen = self.gen
            self.taak, self.resultaat = None, None
            self.lbl_status.config(text="HEAT-Lim berekenen …")
            self.pb["value"] = 0

            def rekenen(w):
                def werk():
                    try:
                        self.q.put(("rust", gen, bereken_rust(w, start, eind, zon=zon)))
                    except Exception as ex:
                        self.q.put(("fout", f"{ex}", gen))
                threading.Thread(target=werk, daemon=True).start()

            if not excel and sleutel == self._weer_sleutel and self._weer is not None:
                rekenen(self._weer)
                return

            def laad():
                try:
                    if excel:
                        w = self.weerbron.excel(pad, start, eind, route)
                    else:
                        w = self.weerbron.online(kand, d, route)
                    self.q.put(("weer", gen, sleutel, w, rekenen))
                except Exception as ex:
                    self.q.put(("fout", f"Weer: {ex}", gen))
            self.lbl_status.config(text="Weer laden …")
            threading.Thread(target=laad, daemon=True).start()

        def _start(self, gen, inv, weer, n, seed):
            if gen != self.gen:
                return
            try:
                t = bereid_voor(gen, inv, weer, n, seed)
            except Exception as e:
                self._fout(str(e))
                return
            self.taak, self.resultaat = t, None
            self.futures = [self.pool.submit(_bereken_lid, a) for a in taak_argumenten(t)]
            for f in self.futures:
                f.add_done_callback(self._lid_klaar)
            if self.sc_win is not None:
                self._dien_vrij_in()
            self._teken_scatter()
            self._teken_weer(t)
            self._teken_fysiologie(t, None)
            self._signaal(None)
            self._toon_tekst()
            self.pb["value"] = 0
            self.lbl_status.config(text=f"Berekenen … 0/{n}")

        def _lid_klaar(self, f):
            if f.cancelled():
                return
            try:
                self.q.put(("lid",) + f.result())
            except Exception as e:
                self.q.put(("fout", f"Ensemble-lid mislukt: {e}\n{traceback.format_exc()}"))

        def _annuleer(self):
            for f in self.futures:
                f.cancel()
            self.futures = []

        def _poll(self):
            nieuw = False
            nieuw_vrij = False
            try:
                while True:
                    m = self.q.get_nowait()
                    soort = m[0]
                    if soort == "lid":
                        _, gen, i, res, plafond = m
                        if self.taak is not None and gen == self.taak.gen == self.gen:
                            if plafond:
                                self.taak.traces[i] = res
                                nieuw = True
                            else:
                                self.taak.traces_vrij[i] = res
                                nieuw_vrij = True
                    elif soort == "weer":
                        _, gen, sleutel, w, verder = m
                        if gen == self.gen:
                            if sleutel[0] == "online":
                                self._weer_sleutel, self._weer = sleutel, w
                            verder(w)
                    elif soort == "rust":
                        _, gen, rr = m
                        if gen == self.gen:
                            self.rust = rr
                            self._teken_scatter()
                            self._teken_rust(rr)
                            self._toon_tekst()
                            self.pb["value"] = 1.0
                            self.lbl_status.config(text="Klaar (HEAT-Lim, per uur)")
                    elif soort == "kandidaten":
                        self.kandidaten = m[1]
                        self.cb_kand["values"] = [
                            f"{k.get('name')}, {k.get('admin1', '')} ({k.get('country_code', '')})"
                            f" – {k.get('population', 0) or 0:,} inw.".replace(",", ".")
                            for k in self.kandidaten]
                        if self.kandidaten:
                            self.cb_kand.current(0)
                        self._weer_gewijzigd()
                    elif soort == "eind":
                        _, gen, r = m
                        if gen == self.gen:
                            self.resultaat = r
                            self._teken_fysiologie(self.taak, r)
                            self._signaal(r.signaal)
                            self._toon_tekst()
                            self.lbl_status.config(text=f"Klaar: n = {self.taak.n} (seed {self.taak.seed})")
                    elif soort == "fout":
                        if len(m) < 3 or m[2] == self.gen:
                            self._fout(m[1])
            except queue.Empty:
                pass
            if (nieuw or nieuw_vrij) and self.sc_win is not None and self.taak is not None:
                nu = time.monotonic()
                klaar = (len(self.taak.traces_vrij) == self.taak.n and len(self.taak.traces) == self.taak.n)
                if klaar or nu - self._sc_getekend >= 1.0:
                    self._sc_getekend = nu
                    self._teken_scatter()
            if nieuw and self.taak is not None:
                t = self.taak
                k = len(t.traces)
                self.pb["value"] = k / t.n
                self.lbl_status.config(text=f"Voorlopig: n = {k}/{t.n}")
                self.tegels.leeg(f"Berekenen … n = {k}/{t.n}. De grafieken tonen de voorlopige banden.")
                nu = time.monotonic()
                if k == t.n or nu - self._laatst_getekend >= 0.7:
                    self._laatst_getekend = nu
                    self._teken_fysiologie(t, None)
                if k == t.n:
                    self.lbl_status.config(text="Samenvatten (hestia_loper) …")
                    gen = t.gen

                    def werk():
                        try:
                            self.q.put(("eind", gen, eindresultaat(t)))
                        except Exception as e:
                            self.q.put(("fout", f"Samenvatten mislukt: {e}\n{traceback.format_exc()}", gen))
                    threading.Thread(target=werk, daemon=True).start()
            self.root.after(250, self._poll)

        # -------------------------------------------------------- tekenen
        @staticmethod
        def _lokaal(tijden):
            return [pd.Timestamp(x).tz_localize(None) for x in tijden]

        def _x_as(self, ax):
            ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

        def _teken_weer(self, t, wind2=None):
            m = t.meteo
            tijd = self._lokaal(m["time"])
            route = self.v["route"].get()
            for k in ("t", "wbgt", "rh", "wind"):
                self.ax[k].clear()
            a = self.ax["t"]
            a.plot(tijd, m["t_air"], color=KLEUR["rood"], lw=2,
                   label="luchttemp. " + ("stad (met UHI)" if route == "stad" else "platteland"))
            if route == "stad" and np.isfinite(m.get("t_air_rural", [np.nan])).any():
                a.plot(tijd, m["t_air_rural"], color=KLEUR["grijs"], lw=1, ls="--",
                       label="platteland (zonder UHI)")
            a.set_title("Luchttemperatuur")
            a.set_ylabel("°C")
            a.legend(loc="best")
            a = self.ax["wbgt"]
            a.plot(tijd, m["wbgt"], color=KLEUR["oranje"], lw=2)
            for y, kl in ((18, KLEUR["geel"]), (23, KLEUR["oranje"]), (28, KLEUR["rood"])):
                a.axhline(y, color=kl, lw=0.8, ls=":")
            a.set_title("WBGT")
            a.set_ylabel("°C")
            a = self.ax["rh"]
            a.plot(tijd, m["rh"], color="#2471a3", lw=2)
            a.set_title("Relatieve luchtvochtigheid")
            a.set_ylabel("%")
            a = self.ax["wind"]
            a.plot(tijd, m["wind10"], color=KLEUR["grijs"], lw=1.5, label="10 m (weerdata)")
            if wind2 is None:
                a.plot(tijd[:len(t.wind_fysiologie)], t.wind_fysiologie, color="#117a65", lw=2,
                       label="1,5 m (zoals het model rekent)")
            else:
                a.plot(*wind2, color="#117a65", lw=2, marker="o", ms=4,
                       label="1,5 m zoals HEAT-Lim rekent (min. 0,5)")
            a.set_title("Windsnelheid")
            a.set_ylabel("m/s")
            a.set_ylim(bottom=0)
            a.legend(loc="best")
            for k in ("t", "wbgt", "rh", "wind"):
                self._x_as(self.ax[k])

        def _teken_fysiologie(self, t: Taak, r):
            for k in ("kern", "co"):
                self.ax[k].clear()
            if r is not None:
                a = r.assessment
                b = {"minutes": a.minutes, "median_stop_minute": a.median_stop_minute,
                     "t_rect_median": a.t_rect_median, "t_rect_lo": a.t_rect_lo,
                     "t_rect_hi": a.t_rect_hi, "co_reserve_median": a.co_reserve_median,
                     "co_reserve_lo": a.co_reserve_lo, "co_reserve_hi": a.co_reserve_hi}
                n_txt = f"n = {t.n}"
            else:
                b = voorlopige_banden(t)
                n_txt = f"voorlopig, n = {len(t.traces)}/{t.n}"
            start = t.start_aware.tz_localize(None)
            if b is not None:
                x = [start + pd.Timedelta(minutes=float(mm)) for mm in b["minutes"]]
                fin = start + pd.Timedelta(minutes=float(b["median_stop_minute"]))
                for k, sleutel, titel, eenheid in (("kern", "t_rect", "Kerntemperatuur (T_rect)", "°C"),
                                                   ("co", "co_reserve", "Cardiac-output-reserve", "L/min")):
                    ax = self.ax[k]
                    ax.fill_between(x, b[f"{sleutel}_lo"], b[f"{sleutel}_hi"], color=KLEUR["band"],
                                    alpha=0.18, lw=0, label="95%-band ensemble")
                    ax.plot(x, b[f"{sleutel}_median"], color=KLEUR["lijn"], lw=2, label="mediaan")
                    ax.axvline(fin, color="k", lw=1, ls="--")
                    ax.text(fin, 1.0, " finish (mediaan)", transform=ax.get_xaxis_transform(),
                            va="top", fontsize=9)
                    ax.set_title(f"{titel}   ({n_txt})")
                    ax.set_ylabel(eenheid)
                kern = self.ax["kern"]
                kern.axhline(39.5, color=KLEUR["oranje"], lw=1, ls=":")
                kern.axhline(40.5, color=KLEUR["rood"], lw=1, ls=":")
                kern.text(x[0], 39.5, " 39,5", color=KLEUR["oranje"], va="bottom", fontsize=9)
                kern.text(x[0], 40.5, " 40,5", color=KLEUR["rood"], va="bottom", fontsize=9)
                g42 = hm.T_THERMAL_ONLY_CRITICAL
                lo42, hi42 = kern.get_ylim()
                if hi42 >= g42 - 0.3:
                    kern.axhline(g42, color="#6e0b0b", lw=1.4, ls="--")
                    kern.text(0.01, g42, f" {g42:.0f} °C: model buiten getoetst gebied",
                              transform=kern.get_yaxis_transform(), va="bottom", fontsize=8, color="#6e0b0b")
                    kern.set_ylim(lo42, max(hi42, g42 + 0.3))
                co = self.ax["co"]
                co.axhline(2.0, color=KLEUR["oranje"], lw=1, ls=":")
                co.axhline(0.0, color=KLEUR["rood"], lw=1.2)
                co.text(x[0], 2.0, " 2,0", color=KLEUR["oranje"], va="bottom", fontsize=9)
                co.text(x[0], 0.0, " 0: onder nul = extrapolatie", color=KLEUR["rood"],
                        va="bottom", fontsize=9)
                kern.legend(loc="lower right")
                xmin, xmax = start, x[-1]
            else:
                for k, titel in (("kern", "Kerntemperatuur (T_rect)"), ("co", "Cardiac-output-reserve")):
                    self.ax[k].set_title(f"{titel}   (berekenen …)")
                xmin = start
                xmax = t.finish_aware.tz_localize(None) + pd.Timedelta(minutes=30)
            for k in self.ax:
                self.ax[k].set_xlim(xmin, xmax)
                self._x_as(self.ax[k])
            fin_plan = t.finish_aware.tz_localize(None)
            for k in ("t", "wbgt", "rh", "wind"):
                for ln in list(self.ax[k].patches):
                    ln.remove()
                self.ax[k].axvspan(start, fin_plan, color="#f4d03f", alpha=0.08, lw=0)
            self.canvas.draw_idle()

        def _teken_rust(self, rr: RustResultaat):
            from matplotlib.patches import Patch
            uren = [x.tz_localize(None) for x in rr.uren]
            self._teken_weer(rr, wind2=(uren, rr.av))
            leeftijd = int(self._f("leeftijd"))
            eigen = rust_profielen_voor_leeftijd(leeftijd)
            naam = {"young": "18–40 jaar", "old": "65+"}
            kl = {"young": "#2e86c1", "old": "#884ea0"}
            a = self.ax["kern"]
            a.clear()
            for k in ("young", "old"):
                dik = k in eigen
                a.plot(uren, rr.mmax[k], color=kl[k], lw=2.6 if dik else 1.2, marker="o",
                       ms=5 if dik else 3, alpha=1.0 if dik else 0.6,
                       label=f"HEAT-Lim {naam[k]}" + ("  (jouw leeftijd)" if dik and len(eigen) == 1 else ""))
            act = rr.instellingen["activiteit_met"]
            vloer = rr.instellingen["rustniveau_met"]["young"]
            a.axhline(act, color=KLEUR["oranje"], lw=1, ls="--")
            a.text(uren[0], act, f" {hl.nl(act)} MET: normale activiteit", color=KLEUR["oranje"],
                   va="bottom", fontsize=9)
            a.axhline(vloer, color=KLEUR["rood"], lw=1.2)
            a.text(uren[0], vloer, f" rustniveau {hl.nl(vloer)} MET", color=KLEUR["rood"],
                   va="bottom", fontsize=9)
            a.set_ylim(bottom=0)
            a.set_title("Max. volhoudbare activiteit (Mmax), per uur")
            a.set_ylabel("MET")
            a.legend(loc="best")
            b = self.ax["co"]
            b.clear()
            kleur_cat = {0: "#d5d8dc", 1: "#27ae60", 2: "#d4ac0d", 3: "#e67e22", 4: "#c0392b"}
            half = pd.Timedelta(minutes=30)
            for y, k in ((1, "young"), (0, "old")):
                for t_, c in zip(uren, rr.cat[k]):
                    b.broken_barh([(mdates.date2num(t_ - half), 1 / 24)], (y - 0.35, 0.7),
                                  facecolors=kleur_cat[int(c)], edgecolor="white")
            b.set_yticks([1, 0])
            b.set_yticklabels([naam["young"], naam["old"]])
            b.set_ylim(-0.6, 1.6)
            b.grid(False)
            b.set_title(f"HEAT-Lim per uur, rust in de "
                        f"{'zon' if rr.instellingen['zon'] == 'outdoor' else 'schaduw'}")
            b.legend(handles=[Patch(color=kleur_cat[i], label=RUST_CAT[i]) for i in (1, 2, 3, 4, 0)],
                     loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, fontsize=8, frameon=False)
            x0, x1 = uren[0] - half, uren[-1] + half
            for k in self.ax:
                self.ax[k].set_xlim(x0, x1)
                self._x_as(self.ax[k])
            for k in ("t", "wbgt", "rh", "wind"):
                self.ax[k].axvspan(rr.start_aware.tz_localize(None), rr.eind_aware.tz_localize(None),
                                   color="#f4d03f", alpha=0.08, lw=0)
            zwaarst = max(int(rr.cat[k].max()) for k in eigen)
            uur = next(i for i in range(len(uren)) if any(int(rr.cat[k][i]) == zwaarst for k in eigen))
            self._signaal_rust(zwaarst, uren[uur], rr.av[uur], rr.instellingen["zon"] == "outdoor")
            self.canvas.draw_idle()

        def _signaal_rust(self, c, uur, wind, zon):
            kleur = {0: "#aab7b8", 1: "#27ae60", 2: "#d4ac0d", 3: "#e67e22", 4: "#c0392b"}[c]
            tekst = f"HEAT-Lim: {RUST_CAT_KORT[c]}"
            if c >= 2:
                tekst += (f" zoals om {uur:%H:%M} ({'zon' if zon else 'schaduw'}, "
                          f"wind {hl.nl(float(wind))} m/s)")
            self.lbl_signaal.config(text=f"  {tekst}  ", bg=kleur,
                                    fg="black" if c in (0, 2) else "white")

        def _toon_tekst_rust(self):
            rr = self.rust
            self._toon_tegels_rust()
            self._toon_herkomst()
            self.txt.config(state="normal")
            self.txt.delete("1.0", "end")
            if rr is None:
                self.txt.config(state="disabled")
                return
            import HEATLim as H
            w, ins = rr.weer, rr.instellingen

            def dec(x, n):
                return f"{float(x):.{n}f}".replace(".", ",")
            self.txt.insert("end", "Weer: ", "vet")
            uhi = ""
            if "UHI_delta" in w.df.columns:
                dd = w.df.loc[rr.uren[0]:rr.uren[-1], "UHI_delta"]
                if len(dd):
                    uhi = f"; UHI gemiddeld {hl.nl(float(dd.mean()))} °C"
            self.txt.insert("end", f"{w.label}; {w.city.get('name', '')} "
                                   f"({(w.city.get('population') or 0):,} inw.){uhi}; "
                                   f"route {self.v['route'].get()}.\n".replace(",", "."))
            self.txt.insert("end", "Methode: ", "vet")
            self.txt.insert("end", f"HEAT-Lim (Vanos et al. 2023) zoals Klimatos: per uur, "
                                   f"{ins['blootstelling_u']} u blootstelling, "
                                   f"{'in de zon (MRT uit de Data Engine)' if ins['zon'] == 'outdoor' else 'in de schaduw (MRT = luchttemperatuur)'}, "
                                   f"wind op 1,5 m minimaal {hl.nl(ins['wind_min'])} m/s, "
                                   f"alleen uren vanaf {ins['ta_min']:g} °C.\n")
            leeftijd = int(self._f("leeftijd"))
            eigen = rust_profielen_voor_leeftijd(leeftijd)
            naam = {"young": "18–40 jaar", "old": "65+"}
            if len(eigen) == 2:
                self.txt.insert("end", f"⚠ Voor {leeftijd} jaar heeft HEAT-Lim geen profiel (alleen 18–40 "
                                       f"en 65+); beide worden getoond, de kleur bovenaan volgt de "
                                       f"zwaarste van de twee.\n", "waarsch")
            ev = rr.beoordeeld
            for k in ("young", "old"):
                p = ins["profielen"][k]
                mm = rr.mmax[k]
                laagste = hl.nl(float(np.nanmin(mm))) if np.isfinite(mm).any() else "—"
                c = rr.cat[k]
                self.txt.insert("end", f"{naam[k]}" + (" (jouw leeftijd)" if k in eigen and len(eigen) == 1 else "")
                                + ": ", "vet")
                self.txt.insert("end",
                    f"laagste Mmax {laagste} MET; uren onder {hl.nl(ins['activiteit_met'])} MET: "
                    f"{int(np.sum(c >= 2))}; rust niet leefbaar: {int(np.sum(c == 3))}; niet overleefbaar: "
                    f"{int(np.sum(c == 4))}; niet beoordeeld (< {ins['ta_min']:g} °C): {int(np.sum(~ev))} "
                    f"van {len(c)} uur.  Profiel: {dec(p['Mass'], 1)} kg, kleding Icl {dec(p['Icl'], 2)}, "
                    f"max. huidbevochtiging {dec(H.wmax(p['wmax_condition']), 2)}, max. zweet "
                    f"{dec(p['smax_rate'], 2)} L/u.\n")
            self.txt.insert("end", "In rust gebruikt HEAT-Lim de gepubliceerde profielen: geslacht, gewicht, "
                                   "lengte, fitheid en kleding uit het formulier tellen niet mee.\n", "waarsch")
            for k, (tekst, uitleg) in hl.NIET_GEMODELLEERD.items():
                if self.v[k].get():
                    self.txt.insert("end", f"⚠ {tekst}: {uitleg}\n", "waarsch")
            self.txt.insert("end", "Lezen: HEAT-Lim rekent per uur een evenwichtstoestand. 'Niet overleefbaar' "
                                   f"betekent: als de omstandigheden van dat uur {ins['blootstelling_u']} uur "
                                   "onveranderd aanhouden, met iemand die stilzit, overschrijdt de warmteopslag "
                                   "de kritieke grens. Het is geen voorspelling voor de hele dag.\n")
            self.txt.insert("end", "Research software: niet gevalideerd voor operationele beslissingen. "
                                   "HEAT-Lim rekent buiten; binnenshuis zit er niet in.")
            self.txt.config(state="disabled")

        def _dien_vrij_in(self):
            t = self.taak
            if t is None or t.vrij_ingediend:
                return
            t.vrij_ingediend = True
            nieuw = [self.pool.submit(_bereken_lid, a) for a in taak_argumenten(t, plafond=False)]
            for f in nieuw:
                f.add_done_callback(self._lid_klaar)
            self.futures += nieuw

        def _open_scatter(self):
            if self.sc_win is not None:
                self.sc_win.lift()
                return
            w = tk.Toplevel(self.root)
            w.title("T_rect tegen CO_reserve  (research software)")
            bw, bh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            w.geometry(f"{min(1150, bw - 60)}x{min(860, bh - 100)}+60+40")
            self.sc_fig = Figure(figsize=(11, 8), dpi=96, constrained_layout=True)
            self.sc_ax = self.sc_fig.add_subplot(111)
            self.sc_lbl = ttk.Label(w, text="", font=("TkDefaultFont", LETTER - 1), wraplength=1100,
                                    justify="left")
            self.sc_lbl.pack(side="bottom", fill="x", padx=8, pady=6)
            self.sc_canvas = FigureCanvasTkAgg(self.sc_fig, master=w)
            self.sc_canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
            self.sc_win = w

            def dicht():
                self.sc_win = None
                w.destroy()
            w.protocol("WM_DELETE_WINDOW", dicht)
            if not self._is_rust():
                self._dien_vrij_in()
            self._teken_scatter()

        def _teken_scatter(self):
            if self.sc_win is None:
                return
            import Klimatos_ClimateShift as K
            ax = self.sc_ax
            ax.clear()
            t = self.taak
            if self._is_rust() or t is None:
                ax.text(0.5, 0.5, "Alleen bij hardlopen: in rust rekent de suite met HEAT-Lim\n"
                                  "(geen kerntemperatuur of CO_reserve).", ha="center", va="center",
                        transform=ax.transAxes, fontsize=13)
                ax.set_axis_off()
                self.sc_lbl.config(text="")
                self.sc_canvas.draw_idle()
                return
            vrij = scatter_paren([t.traces_vrij[i] for i in sorted(t.traces_vrij)])
            std = scatter_paren([t.traces[i] for i in sorted(t.traces)])
            alle = vrij + std
            if not alle:
                ax.text(0.5, 0.5, "Berekenen …", ha="center", va="center", transform=ax.transAxes,
                        fontsize=14)
                ax.set_axis_off()
                self.sc_canvas.draw_idle()
                return
            co = [c for _, c in alle]
            tt = [x for x, _ in alle]
            x_lo, x_hi = min(co) - 0.3, max(co) + 0.3
            y_lo, y_hi = min(min(tt), 38.5), max(max(tt), 41.0)
            ax.axhspan(39.5, 40.5, color="#f0a30a", alpha=0.18, zorder=0,
                       label="T_rect > 39,5 °C (EHE-drempel)")
            ax.axhspan(40.5, y_hi, color="#d62728", alpha=0.22, zorder=0,
                       label="T_rect > 40,5 °C (klinische EHS-drempel)")
            ax.axvline(0, color="black", lw=1, ls=":", zorder=1)
            if std:
                ax.scatter([c for _, c in std], [x for x, _ in std], s=8, color="#9a9a9a", alpha=0.35,
                           zorder=2, label=f"met hartplafond (standaard, zoals hoofdgrafieken)")
            if vrij:
                ta = np.array([x for x, _ in vrij])
                ca = np.array([c for _, c in vrij])
                tol = hm.CO_RESERVE_CEILING_TOL   # 0,05 L/min; Klimatos gebruikt dezelfde waarde
                in_ehe = (ta > 39.5) & (ca < tol)
                in_kl = (ta >= 40.5) & (ca <= tol)
                ax.scatter(ca[~in_ehe], ta[~in_ehe], s=12, color="steelblue", alpha=0.55, zorder=3,
                           label="zonder hartplafond: tijdstap")
                ax.scatter(ca[in_ehe & ~in_kl], ta[in_ehe & ~in_kl], s=18, color="black", alpha=0.8,
                           zorder=4, label="voldoet aan EHE (T > 39,5 EN COr < 0)")
                if in_kl.any():
                    ax.scatter(ca[in_kl], ta[in_kl], s=26, marker="X", color="#8B0000", zorder=4,
                               label="voldoet aan klinisch criterium (T ≥ 40,5 EN COr ≤ 0)")
                for mstats, kleur, naam, ms, dy in (
                        (K._ehe_margin_stats(vrij, 39.5, 0.0), "#c07800", "EHE", 140, 8),
                        (K._ehe_margin_stats(vrij, 40.5, 0.0), "#8B0000", "klinisch", 80, -16)):
                    if mstats is None:
                        continue
                    ax.scatter([mstats["closest_c"]], [mstats["closest_t"]], s=ms, facecolors="none",
                               edgecolors=kleur, linewidths=2, zorder=5,
                               label=f"dichtst bij {naam}-drempel")
                    bn = mstats["closest_bottleneck"]
                    noot = (f"{hl.nl(bn)} van {naam}" if bn > 0 else f"{naam} overschreden")
                    ax.annotate(noot, xy=(mstats["closest_c"], mstats["closest_t"]), xytext=(10, dy),
                                textcoords="offset points", fontsize=10, color=kleur, fontweight="bold",
                                zorder=6, bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=kleur, alpha=0.9))
            ax.set_xlim(x_lo, x_hi)
            ax.set_ylim(y_lo, y_hi)
            ax.set_xlabel("CO_reserve (L/min)  —  links van 0: onvervulde vraag (alleen zonder plafond)")
            ax.set_ylabel("T_rect (°C)")
            ax.set_title(f"T_rect tegen CO_reserve, alle tijdstappen (loop + nafinish)\n"
                         f"zonder plafond: {len(t.traces_vrij)}/{t.n} leden, {len(vrij)} punten;  "
                         f"met plafond: {len(t.traces)}/{t.n} leden")
            ax.grid(alpha=0.25)
            ax.legend(fontsize=9, loc="lower left")
            self.sc_lbl.config(text=(
                "Gekleurd: tweede ensemble met CV_CEILING_FORCED = False (zelfde profielen en seeds): de loper "
                "houdt zijn tempo vast als het hart aan het plafond zit, dus CO_reserve loopt door onder 0. "
                "Onder 0 is dat de onvervulde zuurstofvraag in liters bloed per minuut (modelkeuze in de "
                "CVR-module, niet gevalideerd), geen werkelijk stromend bloed. Grijs: de standaardberekening "
                "met plafond, die de loper laat vertragen; daarop zijn alle andere grafieken gebaseerd. "
                "Zones, kleuring en markeringen zoals Klimatos (plot_trect_co_reserve_scatter)."))
            self.sc_canvas.draw_idle()

        def _signaal(self, s):
            if not s:
                self.lbl_signaal.config(text="  —  ", bg="#dddddd", fg="black")
                return
            self.lbl_signaal.config(text="  " + hl.SIGNAAL_TEKST[s["kleur"]] + "  ",
                                    bg=SIGNAAL_KLEUR[s["kleur"]],
                                    fg="black" if s["kleur"] in ("geel",) else "white")

        def _toon_tekst(self):
            if self._is_rust():
                return self._toon_tekst_rust()
            self._toon_tegels()
            self._toon_herkomst()
            t = self.taak
            self.txt.config(state="normal")
            self.txt.delete("1.0", "end")
            if t is None:
                self.txt.config(state="disabled")
                return
            w, af = t.weer, t.af
            uhi = ""
            if "UHI_delta" in w.df.columns:
                s, e = t.start_aware, t.finish_aware
                d = w.df.loc[s.floor("h"):e.ceil("h"), "UHI_delta"]
                if len(d):
                    uhi = f"; UHI gemiddeld {hl.nl(float(d.mean()))} °C"
            self.txt.insert("end", "Weer: ", "vet")
            self.txt.insert("end", f"{w.label}; {w.city.get('name', '')} "
                                   f"({(w.city.get('population') or 0):,} inw.){uhi}; "
                                   f"route {self.v['route'].get()}.\n".replace(",", "."))
            self.txt.insert("end", "Fitheid: ", "vet")
            self.txt.insert("end", f"VO2max {hl.nl(af.vo2max)} ({af.vo2max_bron}); tempo vraagt "
                                   f"{af.pct_vo2max:.0%} van VO2max; HRmax {af.hr_max:.0f} "
                                   f"({af.hr_max_bron}); training_factor {hl.nl(af.training_factor)}; "
                                   f"clo {hl.nl(af.clo)}.\n")
            r = self.resultaat
            if r is not None:
                s = r.samenvatting()
                self.txt.insert("end", "Uitkomst (mediaan [95%]): ", "vet")
                self.txt.insert("end",
                    f"piek T_rect {hl.nl(s['t_rect_max']['med'])} [{hl.nl(s['t_rect_max']['lo'])}–"
                    f"{hl.nl(s['t_rect_max']['hi'])}] °C; laagste CO_reserve {hl.nl(s['co_min']['med'])} "
                    f"[{hl.nl(s['co_min']['lo'])}–{hl.nl(s['co_min']['hi'])}] L/min; piekhartslag "
                    f"{s['hr_piek']['med']:.0f}/min; vochtverlies {hl.nl(s['dehyd']['med'])}% "
                    f"(tot {hl.nl(s['dehyd']['hi'])}%); finish ≈ "
                    f"{hl.min_naar_tempo(s['finish']['med'])} (mm:ss).\n")
                self.txt.insert("end", "Modelsignaal: ", "vet")
                self.txt.insert("end", " ".join(r.signaal["redenen"]) + "\n")
                if s["t_rect_max"]["hi"] > hm.T_THERMAL_ONLY_CRITICAL:
                    self.txt.insert("end", f"⚠ Piek-T_rect komt boven {hm.T_THERMAL_ONLY_CRITICAL:.0f} °C "
                                           "(T_THERMAL_ONLY_CRITICAL: kritieke thermische maximumtemperatuur). "
                                           "Daarboven rekent het model buiten zijn getoetste gebied en heeft het "
                                           "geen mechanisme dat de loop beëindigt: in werkelijkheid is de loper "
                                           "dan al eerder uitgevallen.\n", "waarsch")
            for x in af.waarschuwingen:
                self.txt.insert("end", "⚠ " + x + "\n", "waarsch")
            try:
                if np.nanmax(t.meteo["wbgt"]) < 18:
                    self.txt.insert("end", "⚠ WBGT onder ca. 18: het model berekent de kerntemperatuur bij "
                                           "koel weer enkele tienden te hoog (README, Known issue 9).\n",
                                    "waarsch")
            except ValueError:
                pass
            for k, (tekst, uitleg) in hl.NIET_GEMODELLEERD.items():
                if self.v[k].get():
                    self.txt.insert("end", f"⚠ {tekst}: {uitleg}\n", "waarsch")
            self.txt.insert("end", "Research software: niet gevalideerd voor operationele "
                                   "beslissingen; de officiële WBGT-protocollen en medische staf beslissen.")
            self.txt.config(state="disabled")

        # ------------------------------------------- uitkomsttegels en herkomst
        def _weer_status(self, start_aware):
            nu = pd.Timestamp.now(tz=start_aware.tz)
            return ("historisch", "simulatie · historisch weer") if start_aware < nu else \
                   ("prognose", "simulatie · verwachtingsweer")

        def _toon_herkomst(self):
            if self._is_rust():
                rr = self.rust
                if rr is None:
                    return
                st, st_t = self._weer_status(rr.start_aware)
                self.herkomst.zet(
                    f"{rr.weer.label}; {rr.weer.city.get('name', '')}", st, status_tekst=st_t,
                    extra="model: HEAT-Lim (Vanos et al. 2023) zoals in Klimatos, gepubliceerde profielen",
                    niet="een meting of een medisch advies; HEAT-Lim rekent per uur een evenwichtstoestand "
                         "voor iemand die stilzit, buiten.")
                return
            t = self.taak
            if t is None:
                return
            st, st_t = self._weer_status(t.start_aware)
            self.herkomst.zet(
                f"{t.weer.label}; {t.weer.city.get('name', '')}, route {self.v['route'].get()}", st,
                status_tekst=st_t,
                extra=f"model: HESTIA (JOS-3 + CVR) via hestia_loper, ensemble n = {t.n}, seed {t.seed}",
                niet="een gemeten kerntemperatuur of een medisch advies (voorspelde modeltoestand).")

        def _toon_tegels(self):
            t, r = self.taak, self.resultaat
            if t is None:
                self.tegels.leeg("Nog geen uitkomst.")
                return
            if r is None:
                self.tegels.leeg(f"Berekenen … n = {len(t.traces)}/{t.n}. De grafieken tonen de "
                                 "voorlopige banden.")
                return
            s, a = r.samenvatting(), r.assessment
            tr, co = s["t_rect_max"], s["co_min"]
            kl_t = KLEUR["rood"] if tr["med"] >= 40.5 else KLEUR["oranje"] if tr["med"] >= 39.5 else KLEUR["groen"]
            kl_c = KLEUR["rood"] if co["med"] <= 0 else KLEUR["oranje"] if co["med"] <= 2.0 else KLEUR["groen"]
            start = t.start_aware.tz_localize(None)

            def eerst(reeks, grens, boven):
                for mm, v in zip(a.minutes, reeks):
                    if (v >= grens) if boven else (v <= grens):
                        return (start + pd.Timedelta(minutes=float(mm))).strftime("%H:%M")
                return None

            m_t = eerst(a.t_rect_median, 39.5, True)
            h_t = eerst(a.t_rect_hi, 39.5, True)
            m_c = eerst(a.co_reserve_median, 2.0, False)
            if m_t or m_c:
                delen = []
                if m_t:
                    delen.append(f"T_rect 39,5 °C om {m_t}")
                if m_c:
                    delen.append(f"CO-reserve 2,0 om {m_c}")
                kritiek = " · ".join(delen)
                kl_k = KLEUR["oranje"]
            else:
                kritiek = "niet bereikt"
                kl_k = KLEUR["groen"]
            sub_k = "mediaan van het ensemble"
            if h_t and h_t != m_t:
                sub_k += f"; bovenkant 95%-band 39,5 °C om {h_t}"
            sig = r.signaal or {}
            items = [
                dict(titel="Piek kerntemperatuur", waarde=f"{hl.nl(tr['med'])} °C",
                     sub=f"95%-band {hl.nl(tr['lo'])}–{hl.nl(tr['hi'])} °C", kleur=kl_t),
                dict(titel="Laagste CO-reserve", waarde=f"{hl.nl(co['med'])} L/min",
                     sub=f"95%-band {hl.nl(co['lo'])}–{hl.nl(co['hi'])} L/min", kleur=kl_c),
                dict(titel="Grenswaarde bereikt", waarde=kritiek if len(kritiek) < 22 else kritiek.split(" · ")[0],
                     sub=(kritiek.split(" · ")[1] + "; " if " · " in kritiek else "") + sub_k, kleur=kl_k),
                dict(titel="Looptijd (mediaan, mm:ss)", waarde=hl.min_naar_tempo(s["finish"]["med"]),
                     sub=f"traagste 2,5%: {hl.min_naar_tempo(s['finish']['hi'])}; vochtverlies "
                         f"{hl.nl(s['dehyd']['med'])}%", kleur="#5d6d7e"),
                dict(titel="Modelsignaal", waarde=hl.SIGNAAL_TEKST.get(sig.get("kleur"), "—"),
                     sub=f"n = {t.n} ensemble-leden", kleur=SIGNAAL_KLEUR.get(sig.get("kleur"), "#7f8c8d")),
            ]
            uitleg = ("Betekenis: " + " ".join(sig.get("redenen", []))).strip()
            if tr["hi"] > hm.T_THERMAL_ONLY_CRITICAL:
                uitleg += (f"  ⚠ Bovenkant boven {hm.T_THERMAL_ONLY_CRITICAL:.0f} °C: daar rekent het model "
                           "buiten zijn getoetste gebied (zie onder).")
            self.tegels.zet(items, uitleg)

        def _toon_tegels_rust(self):
            rr = self.rust
            if rr is None:
                self.tegels.leeg("Berekenen (HEAT-Lim) …")
                return
            ins = rr.instellingen
            eigen = rust_profielen_voor_leeftijd(int(self._f("leeftijd")))
            naam = {"young": "18–40 jaar", "old": "65+"}
            kleur_cat = {0: "#aab7b8", 1: "#27ae60", 2: "#d4ac0d", 3: "#e67e22", 4: "#c0392b"}
            items = []
            for k in eigen:
                mm, c = rr.mmax[k], rr.cat[k]
                laagste = hl.nl(float(np.nanmin(mm))) + " MET" if np.isfinite(mm).any() else "—"
                items.append(dict(titel=f"Laagste Mmax, {naam[k]}", waarde=laagste,
                                  sub=f"normale activiteit = {hl.nl(ins['activiteit_met'])} MET",
                                  kleur=kleur_cat[int(c.max())]))
                items.append(dict(titel=f"Uren, {naam[k]}", waarde=f"{int(np.sum(c >= 2))} van {len(c)}",
                                  sub=f"onder normale activiteit; niet leefbaar {int(np.sum(c == 3))}, "
                                      f"niet overleefbaar {int(np.sum(c == 4))}",
                                  kleur=kleur_cat[int(c.max())]))
            zwaarst = max(int(rr.cat[k].max()) for k in eigen)
            items.append(dict(titel="Zwaarste uur", waarde=RUST_CAT_KORT[zwaarst],
                              sub=f"rust in de {'zon' if ins['zon'] == 'outdoor' else 'schaduw'}, "
                                  f"{ins['blootstelling_u']} u blootstelling", kleur=kleur_cat[zwaarst]))
            self.tegels.zet(items, "Betekenis: per uur, als de omstandigheden van dat uur "
                                   f"{ins['blootstelling_u']} uur aanhouden. Geen voorspelling voor de hele dag.")

        def _fout(self, tekst):
            self.tegels.leeg("Geen uitkomst: zie de melding onder de grafieken.")
            self.lbl_status.config(text="Fout – zie onder")
            self.txt.config(state="normal")
            self.txt.delete("1.0", "end")
            self.txt.insert("end", tekst, "waarsch")
            self.txt.config(state="disabled")
            self.pb["value"] = 0

        # ------------------------------------------------------ opslaan/laden
        def _opslaan(self):
            try:
                inv = self._invoer()
            except Exception as e:
                self._fout(str(e))
                return
            p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")],
                                             initialdir=str(HIER))
            if p:
                inv.opslaan(p)

        def _laden(self):
            p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")], initialdir=str(HIER))
            if not p:
                return
            try:
                inv = hl.LoperInvoer.laden(p)
            except Exception as e:
                self._fout(f"Laden mislukt: {e}")
                return
            zet = {"geslacht": inv.geslacht, "leeftijd": inv.leeftijd, "gewicht": inv.gewicht_kg,
                   "lengte": inv.lengte_cm, "trainingskm": inv.trainingskm_per_week,
                   "afstand": inv.afstand_km, "datum": inv.datum, "plaats": inv.plaats}
            opt = {"hr_rust": inv.hr_rust_bekend, "hr_max": inv.hr_max_bekend,
                   "vo2max": inv.vo2max_bekend, "wedstr_km": inv.wedstrijd_afstand_km,
                   "wedstr_tijd": inv.wedstrijd_tijd, "vet": inv.vetpercentage_bekend}
            for k, x in {**zet, **opt}.items():
                self.v[k].set("" if x is None else str(x).replace(".", ",") if isinstance(x, float) else str(x))
            self.v["eenheid"].set("min/km")
            self._eenheid_vorig = "min/km"
            self.v["snelheid"].set(inv.tempo_min_per_km)
            for k, attr in (("drinkt", "drinkt_bij_elke_post"), ("nsaid", "nsaid_voor_of_tijdens"),
                            ("acclim", "hitte_geacclimatiseerd")):
                self.v[k].set(bool(getattr(inv, attr)))
            self.v["kleding"].set(next(w for w in ["licht (singlet + korte broek)",
                                                   "normaal (T-shirt + korte broek)",
                                                   "lang (lange mouwen/broek)"]
                                       if w.startswith(inv.kleding)))
            for k in hl.NIET_GEMODELLEERD:
                self.v[k].set(bool(getattr(inv, k)))
            self.v["starttijd"].set(inv.starttijd)
            self._tijd_uit_tekst()
            if inv.weerbron == "excel" and inv.weer_excel:
                pad = Path(inv.weer_excel)
                if not pad.is_absolute():
                    pad = Path(p).parent / pad
                self.v["excel"].set(str(pad))
                self.v["bron"].set("Data Engine-bestand")
            else:
                self.v["bron"].set("online (Open-Meteo)")
                self._zoek_plaats()

        def _export(self):
            if self._is_rust():
                if self.rust is None:
                    messagebox.showinfo("Excel-export", "Er is nog geen resultaat.")
                    return
                p = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                                 filetypes=[("Excel", "*.xlsx")], initialdir=str(HIER))
                if p:
                    try:
                        rust_tabel(self.rust).to_excel(p, sheet_name="HEAT-Lim per uur", index=False)
                    except Exception as e:
                        self._fout(f"Export mislukt: {e}")
                return
            if self.resultaat is None:
                messagebox.showinfo("Excel-export", "Er is nog geen volledig resultaat.")
                return
            p = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                             initialdir=str(HIER))
            if p:
                try:
                    hl.exporteer_excel(self.resultaat, p)
                except Exception as e:
                    self._fout(f"Export mislukt: {e}")

        def _sluit(self):
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
