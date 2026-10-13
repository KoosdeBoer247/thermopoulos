# -*- coding: utf-8 -*-
"""
hestia_loper.py
===============
Persoonlijke hitte-risicoanalyse voor EEN hardloper bij EEN evenement.

Wat deze module doet
--------------------
1. INVOER   -- LoperInvoer: alles wat de loper zelf invult (persoon, fitheid,
               gedrag, evenement) plus een lijst risicofactoren die het model
               NIET meeneemt maar wel in het rapport worden genoemd. Opslaan/
               laden als JSON; een interactieve vragenlijst staat in
               run_loper.py.
2. ANALYSE  -- analyseer_loper(): bouwt PersonalInputs/EventScenario voor
               individual_engine.run_individual_assessment() (JOS-3 + CVR,
               persoonlijk ensemble) en berekent per ensemble-run de maten die
               de populatie-runs ook gebruiken: T_rect-piek, Roberts-dosis
               (AUC boven 40,5 C), TCF (HESTIA_ControlFailure_Module),
               punt-van-geen-terugkeer, EHE/EAC, collapsekans (dezelfde
               twee-fasen logistiek als run_monte_carlo_adult), uitdroging,
               pacing en afgelegde afstand.
3. SIGNAAL  -- risicosignaal(): een vierkleurig modelsignaal (groen/geel/
               oranje/rood) met de redenen erbij.
4. WAT-ALS  -- tempo_gevoeligheid(): dezelfde loper bij een langzamer tempo.

Plots: hestia_loper_plots.py. Rapport: hestia_loper_rapport.py.
Startpunt: run_loper.py.

Geen fysiologie wordt hier opnieuw geimplementeerd. Alle simulatie loopt via
individual_engine.py -> hestia_model.calculate_indices_jos3_adult().

Privacy: persoonlijke gegevens verlaten de computer niet. Alleen bij
weerbron 'online' gaan plaatsnaam en lat/lon/datum naar Open-Meteo (zie
individual_engine.py); bij weerbron 'excel' is er geen netwerkverkeer.

Status van de uitkomsten (zie ook TECHNICAL_REFERENCE.md):
  - T_rect / huidtemperatuur (JOS-3): gevalideerd voor sport (bias ~+0,2 C).
  - Hartslag en CO_reserve boven nul (CVR, Lloyd 2022): gevalideerd op HR.
  - CO_reserve onder nul: extrapolatie [NIET GEVALIDEERD].
  - TCF-klassen 5/20/60 C.L: [NIET GEVALIDEERD].
  - Collapse-intercept: VOORLOPIG, gekalibreerd met de CVR-module van voor
    2026-10-04; moet opnieuw gekalibreerd worden.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

import individual_engine as ie
from hestia_model import (
    COLLAPSE_ENDPOINTS, ACTIVE_ENDPOINT, AUC_ROBERTS_GRENS,
    VO2MAX_TO_MET_FACTOR, _daniels_gilbert_vo2_at_pace,
)
from HESTIA_ControlFailure_Module import analyse_participant, DEFAULT_CONFIG as TCF_CFG
from uncertainty import fraction_interval


# =============================================================================
# 1. INVOER
# =============================================================================
KLEDING_CLO = {
    "licht":   0.2,   # singlet + korte broek (standaard hardloopkleding)
    "normaal": 0.3,   # T-shirt + korte broek
    "lang":    0.5,   # lange mouwen en/of lange broek
}

#: Trainingsomvang -> training_factor van de engine (0..1). MODELKEUZE:
#: de engine gebruikt training_factor voor loopeconomie (5% MET) en RPE;
#: een directe meting bestaat niet, dus een grove indeling in vier klassen.
TRAINING_FACTOR = [(10, 0.2), (25, 0.4), (45, 0.6), (1e9, 0.8)]

#: Risicofactoren die het model NIET meeneemt, met de reden waarom ze er
#: toch toe doen (ACSM Expert Consensus Statement on Exertional Heat Illness
#: 2023; Casa et al. 2015 NATA position statement).
NIET_GEMODELLEERD = {
    "koorts_of_ziekte_recent": (
        "Koorts of een (darm)infectie in de afgelopen week",
        "Een recente infectie verhoogt de kans op hitteziekte, ook als je je "
        "alweer goed voelt. Het model gaat uit van een gezond lichaam."),
    "slecht_geslapen": (
        "Slecht of kort geslapen voor de loop",
        "Slaaptekort vermindert de warmtetolerantie. Het model kent geen slaap."),
    "alcohol_dag_ervoor": (
        "Alcohol de dag ervoor",
        "Alcohol werkt vochtafdrijvend; je begint dan mogelijk met een "
        "vochttekort. Het model start iedereen goed gehydrateerd."),
    "eerder_hitteziekte": (
        "Eerder een hitteberoerte of hitte-uitputting gehad",
        "Een eerdere hitteziekte is een bekende risicofactor voor herhaling. "
        "Het model weet dat niet."),
    "medicatie_hart_bloeddruk_zweten": (
        "Medicijnen die hartslag, bloeddruk of zweten beinvloeden "
        "(bijv. betablokkers, plaspillen, antihistaminica, sommige antidepressiva)",
        "Zulke middelen veranderen precies de mechanismen die het model "
        "doorrekent (hartslag, bloedvolume, zweten). Bespreek dit met je arts."),
    "hart_vaat_aandoening": (
        "Een hart- of vaataandoening",
        "Het CVR-model gaat uit van een gezond hart. Bij een hart- of "
        "vaataandoening zegt de berekende reserve weinig; overleg met je arts."),
}


def tempo_naar_min(tempo) -> float:
    """'5:30' of '5.5' of 5.5 -> 5.5 min/km."""
    if isinstance(tempo, (int, float)):
        return float(tempo)
    s = str(tempo).strip().replace(",", ".")
    if ":" in s:
        m, sec = s.split(":", 1)
        return int(m) + float(sec) / 60.0
    return float(s)


def min_naar_tempo(x: float) -> str:
    m = int(x)
    s = int(round((x - m) * 60))
    if s == 60:
        m, s = m + 1, 0
    return f"{m}:{s:02d}"


@dataclass
class LoperInvoer:
    """Alles wat de loper invult. Verplicht: de eerste blokken. Optioneel
    (None = onbekend): alles met een standaardwaarde None."""
    # --- Persoon
    lengte_cm: float
    gewicht_kg: float
    leeftijd: int
    geslacht: str                       # 'man' | 'vrouw'
    # --- Evenement
    evenement: str
    datum: str                          # 'JJJJ-MM-DD'
    starttijd: str                      # 'UU:MM' lokale tijd
    plaats: str
    afstand_km: float
    tempo_min_per_km: str               # '5:30' (verwacht gemiddeld tempo)
    # --- Gedrag en omstandigheden
    drinkt_bij_elke_post: bool = True
    nsaid_voor_of_tijdens: bool = False
    hitte_geacclimatiseerd: bool = False
    kleding: str = "licht"              # zie KLEDING_CLO
    trainingskm_per_week: float = 25.0
    # --- Fitheid (optioneel, verbetert de berekening sterk)
    vo2max_bekend: Optional[float] = None          # mL/kg/min (horloge/test)
    wedstrijd_afstand_km: Optional[float] = None   # recente wedstrijd...
    wedstrijd_tijd: Optional[str] = None           # ...'u:mm:ss' of 'mm:ss'
    hr_max_bekend: Optional[float] = None          # slagen/min (gemeten)
    hr_rust_bekend: Optional[float] = None         # slagen/min ('s ochtends)
    vetpercentage_bekend: Optional[float] = None
    # --- Weerbron
    weerbron: str = "excel"             # 'excel' | 'online'
    weer_excel: Optional[str] = None    # pad naar Thermopoulos_*.xlsx
    # --- Niet gemodelleerde risicofactoren (alleen in het rapport)
    koorts_of_ziekte_recent: bool = False
    slecht_geslapen: bool = False
    alcohol_dag_ervoor: bool = False
    eerder_hitteziekte: bool = False
    medicatie_hart_bloeddruk_zweten: bool = False
    hart_vaat_aandoening: bool = False
    # --- Vrij
    naam: str = ""                      # alleen voor het rapport

    # ---------------------------------------------------------------- helpers
    @property
    def tempo(self) -> float:
        return tempo_naar_min(self.tempo_min_per_km)

    @property
    def duur_min(self) -> float:
        return self.afstand_km * self.tempo

    @property
    def gender_en(self) -> str:
        return {"man": "male", "vrouw": "female"}[self.geslacht]

    @property
    def start(self) -> pd.Timestamp:
        return pd.Timestamp(f"{self.datum} {self.starttijd}")

    def valideer(self) -> list[str]:
        """Harde fouten -> ValueError. Geeft een lijst waarschuwingen terug."""
        fouten = []
        if self.geslacht not in ("man", "vrouw"):
            fouten.append("geslacht moet 'man' of 'vrouw' zijn")
        if not 130 <= self.lengte_cm <= 220:
            fouten.append("lengte buiten 130-220 cm")
        if not 30 <= self.gewicht_kg <= 200:
            fouten.append("gewicht buiten 30-200 kg")
        if not 16 <= self.leeftijd <= 90:
            fouten.append("leeftijd buiten 16-90 jaar (kinderen: aparte module)")
        if not 1 <= self.afstand_km <= 50:
            fouten.append("afstand buiten 1-50 km")
        try:
            t = self.tempo
            if not 2.5 <= t <= 15:
                fouten.append("tempo buiten 2:30-15:00 min/km")
        except ValueError:
            fouten.append("tempo onleesbaar; gebruik bijv. 5:30")
        try:
            self.start
        except Exception:
            fouten.append("datum/starttijd onleesbaar; gebruik JJJJ-MM-DD en UU:MM")
        if self.kleding not in KLEDING_CLO:
            fouten.append(f"kleding moet een van {list(KLEDING_CLO)} zijn")
        if self.weerbron not in ("excel", "online"):
            fouten.append("weerbron moet 'excel' of 'online' zijn")
        if self.weerbron == "excel" and not self.weer_excel:
            fouten.append("weerbron 'excel' vraagt een pad in weer_excel")
        if (self.wedstrijd_afstand_km is None) != (self.wedstrijd_tijd is None):
            fouten.append("vul wedstrijdafstand EN wedstrijdtijd in, of geen van beide")
        if self.hr_max_bekend is not None and not 120 <= self.hr_max_bekend <= 230:
            fouten.append("HRmax buiten 120-230")
        if self.hr_rust_bekend is not None and not 30 <= self.hr_rust_bekend <= 110:
            fouten.append("rusthartslag buiten 30-110")
        if fouten:
            raise ValueError("Invoer klopt niet:\n  - " + "\n  - ".join(fouten))
        waarsch = []
        if self.duur_min > 300:
            waarsch.append("Looptijd > 5 uur: het model is getest tot marathonduur.")
        return waarsch

    # ------------------------------------------------------------------ JSON
    def opslaan(self, pad: str | Path) -> None:
        Path(pad).write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False),
                             encoding="utf-8")

    @classmethod
    def laden(cls, pad: str | Path) -> "LoperInvoer":
        d = json.loads(Path(pad).read_text(encoding="utf-8"))
        d = {k: v for k, v in d.items() if not k.startswith("_")}
        return cls(**d)


# =============================================================================
# Afgeleide fitheid
# =============================================================================
def _tijd_naar_min(s: str) -> float:
    delen = [float(x) for x in str(s).strip().split(":")]
    if len(delen) == 3:
        return delen[0] * 60 + delen[1] + delen[2] / 60
    if len(delen) == 2:
        return delen[0] + delen[1] / 60
    return delen[0]


def daniels_pct_vo2max(duur_min: float) -> float:
    """Fractie van VO2max die een getrainde loper volhoudt over duur_min
    (Daniels & Gilbert 1979)."""
    t = duur_min
    return (0.8 + 0.1894393 * math.exp(-0.012778 * t)
            + 0.2989558 * math.exp(-0.1932605 * t))


def vo2max_uit_wedstrijd(afstand_km: float, tijd: str) -> float:
    """VDOT (Daniels & Gilbert 1979) uit een recente wedstrijdprestatie."""
    t = _tijd_naar_min(tijd)
    vo2 = _daniels_gilbert_vo2_at_pace(t / afstand_km)
    return vo2 / daniels_pct_vo2max(t)


def _dg_snelheid_uit_vo2(vo2: float) -> float:
    """Inverse van Daniels-Gilbert: VO2 (mL/kg/min) -> snelheid (m/min)."""
    a, b, c = 0.000104, 0.182258, -4.60 - vo2
    return max(0.0, (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a))


def vo2_anker(vo2_tempo: float, vo2max: float) -> float:
    """VO2 waarmee de simulatie werkelijk START. Normaal het geplande tempo;
    bij een tempo boven 95% van VO2max begrenst de engine (pct_vo2max <= 0,95),
    en loopt de gesimuleerde loper dus langzamer dan gepland. Afstand, tempo
    en finishtijd moeten op dat werkelijke startniveau gebaseerd zijn.
    [fix 2026-10-06: eerst altijd het geplande tempo -> te snelle finishtijd
    bij een begrensde run]"""
    return min(vo2_tempo, 0.95 * vo2max)


def haalbaar_tempo(vo2max: float, afstand_km: float) -> float:
    """Tempo (min/km) dat een getrainde loper volgens Daniels & Gilbert over
    deze afstand volhoudt: VO2(tempo) = %VO2max(duur) x VO2max."""
    tempo = 6.0
    for _ in range(50):
        duur = tempo * afstand_km
        doel = daniels_pct_vo2max(duur) * vo2max
        v = _dg_snelheid_uit_vo2(doel)
        nieuw = 1000.0 / v
        if abs(nieuw - tempo) < 1e-4:
            break
        tempo = nieuw
    return tempo


@dataclass
class Afgeleid:
    vo2max: float
    vo2max_bron: str
    vo2_bij_tempo: float
    pct_vo2max: float
    pct_geklemd: bool
    met_tempo: float
    hr_max: float
    hr_max_bron: str
    hr_rust: Optional[float]
    training_factor: float
    clo: float
    waarschuwingen: list = field(default_factory=list)


def afleiden(inv: LoperInvoer) -> Afgeleid:
    w = []
    if inv.vo2max_bekend:
        vo2max, bron = float(inv.vo2max_bekend), "zelf opgegeven (horloge/test)"
    elif inv.wedstrijd_afstand_km:
        vo2max = vo2max_uit_wedstrijd(inv.wedstrijd_afstand_km, inv.wedstrijd_tijd)
        bron = (f"berekend uit wedstrijd {inv.wedstrijd_afstand_km:g} km in "
                f"{inv.wedstrijd_tijd} (Daniels & Gilbert)")
    else:
        vo2max = ie._default_vo2max(inv.leeftijd, inv.gender_en)
        bron = "populatiegemiddelde voor leeftijd en geslacht (onzeker, ca. +/-15%)"
        w.append("VO2max is niet opgegeven. Het model gebruikt een gemiddelde voor "
                 "jouw leeftijd en geslacht. Vul een recente wedstrijdtijd of de "
                 "VO2max van je horloge in voor een betrouwbaarder resultaat.")
    vo2_t = _daniels_gilbert_vo2_at_pace(inv.tempo)
    pct = vo2_t / vo2max
    geklemd = pct > 0.95
    ht = haalbaar_tempo(vo2max, inv.afstand_km)
    if geklemd:
        w.append(f"Het opgegeven tempo vraagt {pct:.0%} van je (geschatte) VO2max. "
                 f"Dat is niet vol te houden; de engine begrenst op 95%, waardoor "
                 f"de simulatie langzamer loopt dan je tempo (ongeveer "
                 f"{min_naar_tempo(1000.0 / _dg_snelheid_uit_vo2(0.95 * vo2max))} min/km) "
                 f"en de uitkomsten horen bij een loper die op de grens van zijn "
                 f"vermogen loopt. Met deze VO2max is over {inv.afstand_km:g} km "
                 f"ongeveer {min_naar_tempo(ht)} min/km een realistisch wedstrijdtempo. "
                 f"Pas het tempo of de VO2max/wedstrijdtijd aan.")
    elif pct > daniels_pct_vo2max(inv.duur_min) + 0.03:
        w.append(f"Je tempo ({pct:.0%} van VO2max) ligt boven wat een getrainde "
                 f"loper volgens Daniels over {inv.duur_min:.0f} minuten volhoudt "
                 f"(~{daniels_pct_vo2max(inv.duur_min):.0%}). Ofwel je VO2max is hoger "
                 f"dan geschat, ofwel het tempo is te ambitieus.")
    if inv.hr_max_bekend:
        hrmax, hbron = float(inv.hr_max_bekend), "zelf opgegeven"
    else:
        hrmax, hbron = 208 - 0.7 * inv.leeftijd, "Tanaka (208 - 0,7 x leeftijd)"
    tf = next(f for grens, f in TRAINING_FACTOR if inv.trainingskm_per_week <= grens)
    return Afgeleid(vo2max=vo2max, vo2max_bron=bron, vo2_bij_tempo=vo2_t,
                    pct_vo2max=min(pct, 0.95), pct_geklemd=geklemd,
                    met_tempo=vo2_t / VO2MAX_TO_MET_FACTOR,
                    hr_max=hrmax, hr_max_bron=hbron, hr_rust=inv.hr_rust_bekend,
                    training_factor=tf, clo=KLEDING_CLO[inv.kleding],
                    waarschuwingen=w)


# =============================================================================
# Weer
# =============================================================================
WEER_KOLOMMEN = ["T_air_urban", "RH", "pressure", "wind_10m", "cloud_cover",
                 "solar_radiation", "MRT"]


def _zoek_blad(xl, start, eind):
    meta = xl.parse("Metadata").iloc[0]
    tz = str(meta["timezone"]).strip()
    city = {"name": str(meta.get("city", "")), "country": str(meta.get("country", ""))}
    lat, lon = float(meta["latitude"]), float(meta["longitude"])
    lo, hi = start - pd.Timedelta(hours=1), eind + pd.Timedelta(hours=1)
    gezien = []
    for sheet in xl.sheet_names:
        if sheet == "Metadata":
            continue
        df = xl.parse(sheet, index_col=0)
        if not isinstance(df.index, pd.DatetimeIndex) or not set(WEER_KOLOMMEN) <= set(df.columns):
            continue
        if df.index.tz is not None:
            df.index = df.index.tz_convert(tz).tz_localize(None)
        venster = df.loc[lo.floor("h"):hi.ceil("h"), WEER_KOLOMMEN]
        gezien.append(f"{sheet}: {df.index.min():%Y-%m-%d %H:%M} t/m {df.index.max():%Y-%m-%d %H:%M}"
                      f" ({int(df[WEER_KOLOMMEN[0]].notna().sum())} uur met data)")
        if len(venster) == 0 or venster.index.min() > lo or venster.index.max() < hi:
            continue
        if venster.isna().any().any():
            continue
        df = df.copy()
        df.index = df.index.tz_localize(tz, nonexistent="shift_forward", ambiguous="infer")
        return (df, city, lat, lon, tz, sheet), gezien
    return None, gezien


def weer_uit_excel(pad: str | Path, start: pd.Timestamp, eind: pd.Timestamp):
    """Zoek in een Thermopoulos Data Engine-bestand het tabblad dat het hele
    venster [start-1u, eind+1u] VOLLEDIG dekt. Geeft dezelfde tuple terug als
    individual_engine.fetch_scenario_weather().

    Ontbrekende waarden worden NIET stil geinterpoleerd: de engine rekent
    met NaN door zonder foutmelding (gezien op 2026-10-06: een Hindcast-blad
    zonder archiefdata voor de laatste dagen gaf een T_rect-reeks van NaN).
    """
    pad = Path(pad)
    # [fix 2026-10-08] ExcelFile altijd sluiten (with-blok); anders volgt
    # een ResourceWarning 'unclosed file' midden in de simulatie.
    with pd.ExcelFile(pad) as xl:
        gevonden = _zoek_blad(xl, start, eind)
    if gevonden[0] is not None:
        return gevonden[0]
    gezien = gevonden[1]
    raise ValueError(
        f"Geen tabblad in {pad.name} heeft volledige weerdata voor "
        f"{start:%Y-%m-%d %H:%M} - {eind:%H:%M}.\nBeschikbaar:\n  "
        + "\n  ".join(gezien)
        + "\nMaak met de Data Engine een bestand met deze datum (forecast of "
          "Historical_Custom) en probeer opnieuw.")


# =============================================================================
# 2. ANALYSE
# =============================================================================
def _eindig(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return x if np.isfinite(x) else float("nan")


def collapse_p(t_rect_max: float, co_min: float, dehyd_pct: float) -> float:
    """Zelfde twee-fasen logistiek als hestia_model.run_monte_carlo_adult()."""
    ic = COLLAPSE_ENDPOINTS[ACTIVE_ENDPOINT]["intercept_kal"]
    z = (ic
         + 1.0 * max(0.0, t_rect_max - 39.5)
         + 4.0 * max(0.0, t_rect_max - 40.5)
         + 0.8 * max(0.0, 2.0 - co_min)
         + 0.5 * max(0.0, dehyd_pct - 3.0))
    return 1.0 / (1.0 + math.exp(-z))


def run_maten(res: list, gewicht: float, vo2_tempo: float, afstand_km: float) -> dict:
    """Alle kernmaten van een ensemble-run (een 'res'-lijst van de engine)."""
    race = [r for r in res]
    t = np.array([_eindig(r.get("t_rect")) for r in race])
    c = np.array([_eindig(r.get("co_reserve")) for r in race])
    hr = np.array([_eindig(r.get("hr_geschat")) for r in race])
    met = np.array([_eindig(r.get("current_met")) for r in race])
    water = np.array([_eindig(r.get("water")) for r in race])
    last = res[-1]
    pf_t = [_eindig(x) for x in (last.get("t_rect_series_postfinish") or [])]
    pf_c = [_eindig(x) for x in (last.get("co_reserve_series_postfinish") or [])]

    t_max_race = float(np.nanmax(t)) if np.isfinite(t).any() else float("nan")
    t_max = float(np.nanmax([t_max_race] + pf_t)) if pf_t else t_max_race
    c_min_race = float(np.nanmin(c)) if np.isfinite(c).any() else float("nan")
    dehyd = water / 1000.0 / gewicht * 100.0
    dehyd_eind = float(dehyd[np.isfinite(dehyd)][-1]) if np.isfinite(dehyd).any() else 0.0

    # Afstand: snelheid volgt de MET-verhouding (pacing) via de inverse van
    # Daniels-Gilbert, verankerd op het opgegeven tempo. Na 'stopped' = 0.
    met0 = met[0] if np.isfinite(met[0]) and met[0] > 0 else np.nan
    afst = 0.0
    gestopt = False
    stop_min = None
    for i in range(1, len(race)):
        if race[i].get("stopped"):
            if not gestopt:
                stop_min = i * 10
            gestopt = True
            continue
        f = met[i - 1] / met0 if np.isfinite(met0) else 1.0
        v = _dg_snelheid_uit_vo2(vo2_tempo * f)
        afst += v * 10.0 / 1000.0
    # Geschatte finishtijd: moment waarop de afstand bereikt is; als dat
    # binnen de gesimuleerde tijd niet lukt (pacing), extrapolatie met de
    # laatste snelheid. De extra blootstelling na de geplande tijd wordt NIET
    # gesimuleerd (beperking van de engine: tijd- en niet afstandgestuurd).
    cum, finish_min = 0.0, None
    for i in range(1, len(race)):
        f = met[i - 1] / met0 if np.isfinite(met0) else 1.0
        v = _dg_snelheid_uit_vo2(vo2_tempo * f) if not race[i].get("stopped") else 0.0
        stap = v * 10.0 / 1000.0
        if finish_min is None and cum + stap >= afstand_km and stap > 0:
            finish_min = (i - 1) * 10.0 + (afstand_km - cum) / stap * 10.0
        cum += stap
    if finish_min is None and not gestopt:
        f = met[np.isfinite(met)][-1] / met0 if np.isfinite(met0) else 1.0
        v_eind = _dg_snelheid_uit_vo2(vo2_tempo * f)
        finish_min = (len(race) - 1) * 10.0 + (afstand_km - cum) * 1000.0 / max(v_eind, 1.0)
    tcf = analyse_participant(res, TCF_CFG)
    roberts = _eindig(last.get("auc_klinisch_totaal", last.get("auc_klinisch", 0.0)))
    return {
        "t_rect_max": t_max,
        "t_rect_max_race": t_max_race,
        "co_reserve_min": c_min_race,
        "co_reserve_min_postfinish": float(np.nanmin(pf_c)) if pf_c and np.isfinite(pf_c).any() else float("nan"),
        "hr_piek": float(np.nanmax(hr)) if np.isfinite(hr).any() else float("nan"),
        "met_start": float(met[0]),
        "met_eind": float(met[np.isfinite(met)][-1]),
        "tempo_daling_pct": float((1 - met[np.isfinite(met)][-1] / met[0]) * 100) if met[0] else 0.0,
        "dehydratie_eind_pct": dehyd_eind,
        "afstand_in_tijd_km": afst,
        "afstand_gehaald": bool(afst >= afstand_km * 0.995),
        "finish_min_geschat": float(finish_min) if finish_min is not None else float("nan"),
        "gestopt": gestopt,
        "stop_min": stop_min,
        "roberts_auc": 0.0 if not np.isfinite(roberts) else roberts,
        "roberts_kritiek": bool(roberts > AUC_ROBERTS_GRENS),
        "tcf_dosis": float(tcf["control_failure_dose_total"]),
        "tcf_klasse": tcf["control_failure_class"],
        "tcf_tijd_min": float(tcf["control_failure_time_total_min"]),
        "conjunctie": bool(last.get("conjunctie_ooit_bereikt", False)),
        "conjunctie_eerste_min": last.get("conjunctie_eerste_min"),
        "conjunctie_hersteld": bool(last.get("conjunctie_ooit_hersteld", False)),
        "ehe": bool(ie.conjunctive_hit(res, ie.EHE_T_THRESHOLD, ie.EHE_CO_THRESHOLD,
                                       strict=True, window="race")),
        "ehe_dosis": ie.ehe_dose(res),
        "eac": bool(ie.eac_hit(res)),
        "eac_dosis": ie.eac_dose(res),
        # Race-maximum, net als run_monte_carlo_adult() (t_rect_sims bevat
        # alleen de race-stappen). De na-finish piek telt daar niet mee.
        "p_collapse": collapse_p(t_max_race, c_min_race if np.isfinite(c_min_race) else 2.0, dehyd_eind),
    }


def _band(rows: list, sleutel: Callable, lo=2.5, hi=97.5) -> dict:
    import warnings
    warnings.filterwarnings("ignore", message="All-NaN slice")
    n = min(len(r) for r in rows)
    m = np.array([[sleutel(r[i]) for i in range(n)] for r in rows], dtype=float)
    return {"med": np.nanmedian(m, axis=0), "lo": np.nanpercentile(m, lo, axis=0),
            "hi": np.nanpercentile(m, hi, axis=0), "minuten": np.arange(n) * 10.0}


@dataclass
class LoperResultaat:
    invoer: LoperInvoer
    afgeleid: Afgeleid
    assessment: ie.IndividualAssessment
    per_run: pd.DataFrame
    banden: dict
    weer_sheet: str
    lat: float
    lon: float
    seed: int
    signaal: dict = field(default_factory=dict)
    gevoeligheid: Optional[pd.DataFrame] = None

    def samenvatting(self) -> dict:
        d = self.per_run
        n = len(d)

        def pc(col, q):
            return float(np.nanpercentile(d[col], q))

        def frac(col):
            k = int(d[col].sum())
            fi = fraction_interval(k, n)
            return {"k": k, "n": n, "frac": k / n, "lo": fi.get("lo", float("nan")),
                    "hi": fi.get("hi", float("nan"))}

        return {
            "n": n,
            "t_rect_max": {"med": pc("t_rect_max_race", 50), "lo": pc("t_rect_max_race", 2.5), "hi": pc("t_rect_max_race", 97.5)},
            "t_rect_max_pf": {"med": pc("t_rect_max", 50), "lo": pc("t_rect_max", 2.5), "hi": pc("t_rect_max", 97.5)},
            "co_min": {"med": pc("co_reserve_min", 50), "lo": pc("co_reserve_min", 2.5), "hi": pc("co_reserve_min", 97.5)},
            "hr_piek": {"med": pc("hr_piek", 50), "lo": pc("hr_piek", 2.5), "hi": pc("hr_piek", 97.5)},
            "dehyd": {"med": pc("dehydratie_eind_pct", 50), "lo": pc("dehydratie_eind_pct", 2.5), "hi": pc("dehydratie_eind_pct", 97.5)},
            "tempo_daling": {"med": pc("tempo_daling_pct", 50), "hi": pc("tempo_daling_pct", 97.5)},
            "afstand": {"med": pc("afstand_in_tijd_km", 50), "lo": pc("afstand_in_tijd_km", 2.5)},
            "finish": {"med": pc("finish_min_geschat", 50), "hi": pc("finish_min_geschat", 97.5)},
            "roberts": {"med": pc("roberts_auc", 50), "hi": pc("roberts_auc", 97.5)},
            "tcf": {"med": pc("tcf_dosis", 50), "hi": pc("tcf_dosis", 97.5), "max": float(d["tcf_dosis"].max())},
            "p_collapse": {"med": pc("p_collapse", 50), "lo": pc("p_collapse", 2.5),
                           "hi": pc("p_collapse", 97.5), "mean": float(d["p_collapse"].mean())},
            "f_conjunctie": frac("conjunctie"),
            "f_roberts": frac("roberts_kritiek"),
            "f_tcf_relevant": {**frac("tcf_relevant")},
            "f_ehe": frac("ehe"),
            "f_eac": frac("eac"),
            "f_gestopt": frac("gestopt"),
            "f_hersteld": int(d.loc[d["conjunctie"], "conjunctie_hersteld"].sum()),
        }


def _maak_inputs(inv: LoperInvoer, af: Afgeleid, tempo: float | None = None):
    pi = ie.PersonalInputs(
        height_m=inv.lengte_cm / 100.0, weight_kg=inv.gewicht_kg, age=int(inv.leeftijd),
        gender=inv.gender_en,
        expected_pace_min_per_km=tempo if tempo is not None else inv.tempo,
        nsaid_use=inv.nsaid_voor_of_tijdens, drinks_readily=inv.drinkt_bij_elke_post,
        heat_acclimatized=inv.hitte_geacclimatiseerd,
        known_vo2max=af.vo2max, known_body_fat_pct=inv.vetpercentage_bekend)
    duur = inv.afstand_km * (tempo if tempo is not None else inv.tempo)
    # De engine rekent in stappen van 10 min en laat een restant na de
    # laatste hele stap weg (pd.date_range tot en met de finish). Afronden
    # naar boven zorgt dat de hele geplande looptijd gesimuleerd wordt.
    duur = math.ceil(duur / 10.0) * 10.0
    sc = ie.EventScenario(location_query=inv.plaats, start_local=inv.start,
                          duration_minutes=duur, use_historical=inv.start < pd.Timestamp.now(),
                          clo_value=af.clo)
    return pi, sc


def _hook(inv: LoperInvoer):
    def h(profile):
        if inv.hr_max_bekend:
            profile.hr_max_known = float(inv.hr_max_bekend)
        if inv.hr_rust_bekend:
            profile.hr_rest_known = float(inv.hr_rust_bekend)
        return profile
    return h


def _weer(inv: LoperInvoer, eind: pd.Timestamp):
    if inv.weerbron == "excel":
        df, city, lat, lon, tz, sheet = weer_uit_excel(inv.weer_excel, inv.start, eind)
        return (df, city, lat, lon, tz), sheet
    pi, sc = _maak_inputs(inv, afleiden(inv))
    sc.duration_minutes = (eind - inv.start).total_seconds() / 60
    w = ie.fetch_scenario_weather(sc)
    df = w[0]
    venster = df.loc[(inv.start - pd.Timedelta(hours=1)).tz_localize(w[4], ambiguous=True):
                     (eind + pd.Timedelta(hours=1)).tz_localize(w[4], ambiguous=True),
                     [c for c in WEER_KOLOMMEN if c in df.columns]]
    if venster.isna().any().any() or len(venster) == 0:
        raise ValueError("Open-Meteo gaf onvolledige weerdata voor dit tijdvenster.")
    return w, "online (Open-Meteo)"


def _ensemble(inv, af, weer, n, seed, tempo=None, progress=None):
    pi, sc = _maak_inputs(inv, af, tempo)
    return ie.run_individual_assessment(
        pi, sc, n_ensemble=n, training_factor=af.training_factor, random_seed=seed,
        weather_override=weer, profile_hook=_hook(inv), progress_callback=progress)


def analyseer_loper(inv: LoperInvoer, n_ensemble: int = 200, seed: int = 42,
                    gevoeligheid: bool = True,
                    progress: Optional[Callable[[float, str], None]] = None) -> LoperResultaat:
    w_inv = inv.valideer()
    af = afleiden(inv)
    af.waarschuwingen = w_inv + af.waarschuwingen
    # Weer ophalen voor het langste scenario (tempo + 1:00/km) zodat de
    # gevoeligheidsruns hetzelfde weerbestand gebruiken.
    eind_max = inv.start + pd.Timedelta(minutes=inv.afstand_km * (inv.tempo + (1.0 if gevoeligheid else 0.0)) + 60)
    weer, sheet = _weer(inv, eind_max)
    a = _ensemble(inv, af, weer, n_ensemble, seed, progress=progress)

    anker = vo2_anker(af.vo2_bij_tempo, af.vo2max)
    rijen = [run_maten(res, inv.gewicht_kg, anker, inv.afstand_km) for res in a.all_traces]
    df = pd.DataFrame(rijen)
    df["tcf_relevant"] = df["tcf_dosis"] >= TCF_CFG.relevant_dose
    gewicht = inv.gewicht_kg
    banden = {
        "hr": _band(a.all_traces, lambda r: _eindig(r.get("hr_geschat"))),
        "met": _band(a.all_traces, lambda r: _eindig(r.get("current_met"))),
        "dehyd": _band(a.all_traces, lambda r: _eindig(r.get("water")) / 1000 / gewicht * 100),
        "t_rect": _band(a.all_traces, lambda r: _eindig(r.get("t_rect"))),
        "co": _band(a.all_traces, lambda r: _eindig(r.get("co_reserve"))),
    }
    # Tempo per run, elk genormaliseerd op de EIGEN start-MET: iedereen
    # start op het geplande tempo; de ensemble-spreiding in de start-MET is
    # spreiding in loopeconomie (zelfde tempo, andere inspanning), geen
    # spreiding in starttempo.
    def _tempo_reeks(res):
        met = np.array([_eindig(x.get("current_met")) for x in res])
        m0 = met[0]
        uit = []
        for mi, x in zip(met, res):
            v = _dg_snelheid_uit_vo2(anker * mi / m0) if not x.get("stopped") else 0.0
            uit.append(1000.0 / v if v > 0 else np.nan)
        return uit
    reeksen = [_tempo_reeks(res) for res in a.all_traces]
    nmin = min(len(x) for x in reeksen)
    tm = np.array([x[:nmin] for x in reeksen], dtype=float)
    banden["tempo"] = {"med": np.nanmedian(tm, axis=0), "lo": np.nanpercentile(tm, 2.5, axis=0),
                       "hi": np.nanpercentile(tm, 97.5, axis=0), "minuten": np.arange(nmin) * 10.0}
    r = LoperResultaat(invoer=inv, afgeleid=af, assessment=a, per_run=df, banden=banden,
                       weer_sheet=sheet, lat=weer[2], lon=weer[3], seed=seed)
    r.signaal = risicosignaal(r)
    if gevoeligheid:
        r.gevoeligheid = tempo_gevoeligheid(inv, af, weer, max(40, n_ensemble // 2), seed)
    return r


# =============================================================================
# 3. SIGNAAL
# =============================================================================
#: Drempels van het modelsignaal. MODELKEUZE: ze volgen de criteria die de
#: suite al gebruikt (Roberts 40,5 C / 60 C.min; EHE 39,5 C + COr<0; COr-
#: decompensatiegrens 2,0 L/min; 3% uitdroging uit de collapselogistiek).
#: Het signaal is een samenvatting van de modeluitkomst, GEEN medisch oordeel.
SIGNAAL_AANDEEL = 0.05   # >= 5% van de eigen ensemble-runs telt mee


def nl(x: float, d: int = 1) -> str:
    """Getal met komma als decimaalteken."""
    return f"{x:.{d}f}".replace(".", ",")


def risicosignaal(r: LoperResultaat) -> dict:
    d = r.per_run
    s = r.samenvatting()
    redenen = {"rood": [], "oranje": [], "geel": []}
    if s["f_conjunctie"]["frac"] >= SIGNAAL_AANDEEL:
        redenen["rood"].append(
            f"In {s['f_conjunctie']['frac']:.0%} van de runs komen een rectale temperatuur "
            f"van 40,5 C of meer en een uitgeputte hartreserve tegelijk voor.")
    if s["f_roberts"]["frac"] >= SIGNAAL_AANDEEL:
        redenen["rood"].append(
            f"In {s['f_roberts']['frac']:.0%} van de runs is de hittedosis boven 40,5 C "
            f"groter dan {AUC_ROBERTS_GRENS:.0f} C.min (Roberts-grens).")
    if s["t_rect_max"]["hi"] >= 40.5 and not redenen["rood"]:
        redenen["oranje"].append(
            f"In de ongunstigste runs loopt de kerntemperatuur op tot {nl(s['t_rect_max']['hi'])} C.")
    if s["f_ehe"]["frac"] >= SIGNAAL_AANDEEL:
        redenen["oranje"].append(
            f"In {s['f_ehe']['frac']:.0%} van de runs is de hartreserve op (onder nul) "
            f"bij een kerntemperatuur boven 39,5 C: de regeling heeft dan geen marge meer.")
    if s["f_gestopt"]["frac"] >= SIGNAAL_AANDEEL:
        redenen["oranje"].append(
            f"In {s['f_gestopt']['frac']:.0%} van de runs raak je in het model zo uitgeput "
            f"(ervaren inspanning 19,5 of hoger op de Borg-schaal) dat je stopt.")
    if s["dehyd"]["med"] > 3.0:
        redenen["oranje"].append(
            f"Verwacht vochtverlies {nl(s['dehyd']['med'])}% van je lichaamsgewicht (boven 3%).")
    if s["t_rect_max"]["hi"] >= 39.5 and not redenen["rood"] and not redenen["oranje"]:
        redenen["geel"].append(
            f"In de ongunstigste runs komt de kerntemperatuur boven 39,5 C ({nl(s['t_rect_max']['hi'])} C).")
    if s["co_min"]["lo"] < 2.0 and not redenen["rood"] and not redenen["oranje"]:
        redenen["geel"].append(
            f"De hartreserve zakt in de ongunstigste runs onder 2 L/min ({nl(s['co_min']['lo'])}); "
            f"weinig marge voor een extra inspanning zoals een eindsprint.")
    if s["dehyd"]["hi"] > 2.0 and not redenen["rood"] and not redenen["oranje"]:
        redenen["geel"].append(
            f"Vochtverlies tot {nl(s['dehyd']['hi'])}% in de ongunstigste runs.")
    for kleur in ("rood", "oranje", "geel"):
        if redenen[kleur]:
            return {"kleur": kleur, "redenen": redenen[kleur]}
    return {"kleur": "groen",
            "redenen": [f"Kerntemperatuur blijft onder 39,5 C ({nl(s['t_rect_max']['hi'])} C in de "
                        f"ongunstigste runs) en de hartreserve houdt marge "
                        f"(laagste {nl(s['co_min']['lo'])} L/min)."]}


SIGNAAL_TEKST = {
    "groen":  "Laag modelsignaal",
    "geel":   "Let op",
    "oranje": "Verhoogd modelsignaal",
    "rood":   "Hoog modelsignaal",
}


# =============================================================================
# 4. WAT-ALS: langzamer lopen
# =============================================================================
def tempo_gevoeligheid(inv: LoperInvoer, af: Afgeleid, weer, n: int, seed: int,
                       stappen=(0.0, 0.5, 1.0)) -> pd.DataFrame:
    """Dezelfde loper bij tempo +0:00, +0:30 en +1:00 min/km. Langzamer
    betekent lagere warmteproductie maar ook langer in de zon; het model
    rekent beide mee. Kleiner ensemble (n) dan de hoofdrun."""
    rij = []
    for st in stappen:
        tempo = inv.tempo + st
        a = _ensemble(inv, af, weer, n, seed, tempo=tempo)
        vo2 = vo2_anker(_daniels_gilbert_vo2_at_pace(tempo), af.vo2max)
        d = pd.DataFrame([run_maten(res, inv.gewicht_kg, vo2, inv.afstand_km) for res in a.all_traces])
        rij.append({
            "tempo": min_naar_tempo(tempo), "extra_s_per_km": int(st * 60),
            "begrensd": bool(_daniels_gilbert_vo2_at_pace(tempo) > 0.95 * af.vo2max),
            "duur_min": inv.afstand_km * tempo, "n": n,
            "t_rect_max_med": d["t_rect_max_race"].median(),
            "t_rect_max_p975": d["t_rect_max_race"].quantile(0.975),
            "t_rect_max_p90": d["t_rect_max_race"].quantile(0.90),
            "co_min_med": d["co_reserve_min"].median(),
            "co_min_p10": d["co_reserve_min"].quantile(0.10),
            "co_min_p025": d["co_reserve_min"].quantile(0.025),
            "dehyd_med": d["dehydratie_eind_pct"].median(),
            "f_conjunctie": d["conjunctie"].mean(),
            "f_ehe": d["ehe"].mean(),
            "tcf_p975": d["tcf_dosis"].quantile(0.975),
            "p_collapse_mean": d["p_collapse"].mean(),
        })
    return pd.DataFrame(rij)


# =============================================================================
# Export
# =============================================================================
def exporteer_excel(r: LoperResultaat, pad: str | Path) -> Path:
    pad = Path(pad)
    s = r.samenvatting()
    plat = []
    for k, v in s.items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                plat.append({"maat": f"{k}.{kk}", "waarde": vv})
        else:
            plat.append({"maat": k, "waarde": v})
    with pd.ExcelWriter(pad, engine="openpyxl") as xw:
        pd.DataFrame([asdict(r.invoer)]).T.rename(columns={0: "waarde"}).to_excel(xw, sheet_name="Invoer")
        a = asdict(r.afgeleid)
        a["waarschuwingen"] = " | ".join(a["waarschuwingen"])
        pd.DataFrame([a]).T.rename(columns={0: "waarde"}).to_excel(xw, sheet_name="Afgeleid")
        pd.DataFrame(plat).to_excel(xw, sheet_name="Samenvatting", index=False)
        r.per_run.to_excel(xw, sheet_name="Per_run", index_label="run")
        ts = pd.DataFrame({"minuut": r.banden["t_rect"]["minuten"]})
        for k, b in r.banden.items():
            for q in ("med", "lo", "hi"):
                ts[f"{k}_{q}"] = b[q]
        ts.to_excel(xw, sheet_name="Tijdreeks", index=False)
        if r.gevoeligheid is not None:
            r.gevoeligheid.to_excel(xw, sheet_name="Tempo_watals", index=False)
    return pad


if __name__ == "__main__":
    # Dit is een bibliotheekmodule; het startpunt is run_loper.py. Wie dit
    # bestand toch direct start (bijv. F5 in Spyder), krijgt hetzelfde menu.
    print("hestia_loper.py is de rekenmodule; het programma start via run_loper.py.\n")
    from run_loper import main as _main
    _main([])
