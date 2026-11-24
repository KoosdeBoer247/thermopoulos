# -*- coding: utf-8 -*-
"""
hestia_werk.py
==============
HESTIA-werk: een virtuele groep buitenwerkers over een werkdag
(auteursbesluit 24-11-2026; bronnenstudie "HESTIA werkers: bronnenstudie").

Waarom een eigen module en geen wijziging van hestia_model.py
--------------------------------------------------------------
De loopsimulatie (hestia_model.calculate_indices_jos3_adult) is gebouwd rond
een wedstrijd: afstand, finish, vrijwillige tempo-regeling, stoppen op RPE en
de nazorg na de finish. Geen van die onderdelen hoort bij een werkdag. In
plaats van die functie vol uitzonderingen te zetten, staat de werkdag hier als
een eigen tijdstaplus die DEZELFDE bouwstenen van de suite aanroept:

  weer per stap ......... hestia_bridge.build_interp_data(interval_minutes=5)
  straling, MRT ......... hestia_model.radiation_series()
  WBGT / UTCI ........... pythermalcomfort wbgt()/utci() zoals in hestia_model
  lichaam ............... hestia_model.maak_jos3(), jos3_par(), jos3_t_rect(),
                          jos3_core_for_chsi(); jos3_leeftijd.set_person(),
                          drip_take_rate()
  wind op 1,5 m ......... hestia_model.wind_speed_at_height(),
                          compute_relative_wind() (geen loopwind: v_running 0)
  drinken ............... dezelfde regel als in de loopsimulatie
                          (DRINK_EVERY_STEP_WHEN_THIRSTY, 120-180 g)
  hart en bloedsomloop .. HESTIA_CVR_Module_v2: CVRModel (live) en
                          link_cvr_to_jos3 (achteraf), cv_met_lag()
  fysiek plafond ........ CVRModel.met_at_ceiling() met CV_CEILING_FORCED

Gevolg: hestia_model.py is niet gewijzigd; lopers en wandelaars blijven
bit-gelijk (golden test).

Verschillen met de loopsimulatie (bronnenstudie, keuze 3a en "wat vervalt")
---------------------------------------------------------------------------
* MET komt uit het werk-rustschema: werk-MET in werktijd, rust-MET in rust en
  pauze. Geen vrijwillige tempo-regeling (K_p-termen uit).
* Het fysieke hartplafond (CV_CEILING_FORCED) blijft: dat is geen keuze van
  de werker maar een grens van het lichaam. Wordt het geraakt, dan staat dat
  in de uitkomst (met_plafond_min).
* Geen afstand, finish, RPE-stop, nazorg na de finish, EAC-staan.
* Geen nagloei bij MET-daling (SLOWDOWN_AFTERGLOW): die is afgeleid voor het
  vertragen van een loper; bij elke rustpauze zou hij anders opnieuw warmte
  toevoegen. MODELKEUZE, ter beoordeling van de auteur.
* Geen eigen loopwind (v_running = 0).
* Rust in de schaduw (optie): in rust- en pauzestappen MRT = luchttemperatuur.

Status: research software. Niet voor operationele beslissingen.
"""
from __future__ import annotations

from taal import vt, getal

import math
import zlib
from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np
import pandas as pd

# =============================================================================
# 1. BRONGEGEVENS (bronnenstudie 24-11-2026)
# =============================================================================

#: ISO 8996 niveau 1, gemiddelde stofwisseling per klasse (W/m2), via Parsons.
ISO_8996_KLASSEN = {
    "rust":       {"w_m2": 65.0,  "voorbeeld": vt("rustig zitten", "resting, sitting")},
    "licht":      {"w_m2": 100.0, "voorbeeld": vt("zitten of staan, handwerk", "sitting or standing, hand work")},
    "matig":      {"w_m2": 165.0, "voorbeeld": vt("aanhoudend hand- en armwerk", "sustained hand and arm work")},
    "zwaar":      {"w_m2": 230.0, "voorbeeld": vt("intensief werk", "intense work")},
    "zeer zwaar": {"w_m2": 290.0, "voorbeeld": vt("zeer intensief tot maximaal", "very intense to maximal")},
}

#: Engelse namen van de ISO 8996-klassen (de sleutels blijven Nederlands).
ISO_8996_EN = {"rust": "resting", "licht": "low", "matig": "moderate", "zwaar": "high", "zeer zwaar": "very high"}


def klasse_naam(k: str) -> str:
    return vt(k, ISO_8996_EN[k])


#: Beroepen als voorinstelling: 2024 Adult Compendium (pacompendium.com/occupation),
#: aandeel mannen = modelkeuze (bronnenstudie, akkoord 24-11-2026).
BEROEPEN = [
    # naam, Compendium-code, MET, aandeel mannen
    (vt("Stratenmaker / metselaar, matig", "Paver / bricklayer, moderate"),   "11480", 4.3, 0.95),
    (vt("Bouw buiten, dak en nieuwbouw", "Construction outside, roofing and new build"),     "11120", 4.0, 0.95),
    (vt("Timmerman, matig", "Carpenter, moderate"),                  "11040", 4.3, 0.95),
    (vt("Hovenier, tuinwerk algemeen", "Gardener, general yard work"),       "11415", 4.0, 0.80),
    (vt("Oogstwerk, tuinbouw", "Harvesting, horticulture"),               "11146", 4.8, 0.65),
    (vt("Graafwerk met schop", "Digging with a shovel"),               "11540", 7.3, 0.95),
    (vt("Zware lasten dragen", "Carrying heavy loads"),               "11050", 8.0, 0.95),
    (vt("Vuilnisophaler, straatreiniging", "Refuse collector, street cleaning"),   "11375", 3.8, 0.80),
    (vt("Postbezorger, lopend", "Postal carrier, walking"),              "11486", 2.3, 0.80),
    (vt("Verkeersregelaar, staand", "Traffic controller, standing"),          "11035", 2.0, 0.80),
]
MAN_AANDEEL_STANDAARD = 0.80   # CBS-dashboard beroepen: ~8 op 10 in technische/agrarische beroepen

#: Werkkleding: clo opgebouwd uit losse kledingstukken (voorlopig, ISO 9920
#: niet ingezien) en WBGT-correctie volgens ACGIH tabel 1.
KLEDING = [
    # naam, clo, WBGT-correctie (degC)
    (vt("Korte broek, T-shirt", "Shorts, T-shirt"),                 0.3, 0.0),
    (vt("Werkbroek, T-shirt", "Work trousers, T-shirt"),                   0.5, 0.0),
    (vt("Werkbroek, lange mouwen", "Work trousers, long sleeves"),              0.6, 0.0),
    (vt("Katoenen overall over ondergoed", "Cotton coverall over underwear"),      0.7, 0.0),
    (vt("SMS-polypropyleen overall", "SMS polypropylene coverall"),            0.7, 0.5),
    (vt("Polyolefin overall", "Polyolefin coverall"),                   0.7, 1.0),
]
# Dampdichte PBM bewust weggelaten: JOS-3 kent alleen clo en een vaste
# damp-doorlaatbaarheid (pythermalcomfort i_clo = 0,45).

#: CBS werkzame beroepsbevolking, 3e kwartaal 2026 (x 1000), 85264NED en 85267NED.
#: (onder, boven, mannen, vrouwen); 45-55 afgeleid als 45-75 min 55-65 min 65-75.
CBS_LEEFTIJD = (
    (15, 25, 833, 812),
    (25, 45, 2121, 1920),
    (45, 55, 951, 888),
    (55, 65, 1007, 875),
    (65, 75, 262, 163),
)
LEEFTIJD_MIN, LEEFTIJD_MAX = 18, 67   # AOW-leeftijd (modelkeuze)

#: Beroepsgrenzen (ACGIH TLV tabel 4; NIOSH 2016).
T_KERN_GRENS_NIET_ACCL = 38.0
T_KERN_GRENS_ACCL = 38.5
GEWICHTSVERLIES_GRENS_PCT = 1.5
HR_WERKDAG_GEMIDDELD = 110.0          # NIOSH 2016, 8-uurs dienst
HR_AANHOUDEND = lambda leeftijd: 180.0 - float(leeftijd)   # noqa: E731

#: ISO 7243 per stofwisselingsklasse (W/m2), via Gezondheidsraad 2011 (degC WBGT).
#: (bovengrens M, geacclimatiseerd, niet geacclimatiseerd,
#:  geacclimatiseerd met luchtbeweging, niet geaccl. met luchtbeweging)
ISO_7243 = (
    (65.0,  33.0, 32.0, 33.0, 32.0),
    (130.0, 30.0, 29.0, 30.0, 29.0),
    (200.0, 28.0, 26.0, 28.0, 26.0),
    (260.0, 25.0, 22.0, 26.0, 23.0),
    (1e9,   23.0, 18.0, 25.0, 20.0),
)
ACCL_DREMPEL = 0.5   # acclimatisatiefactor vanaf hier telt de groep als geacclimatiseerd

STAP_MIN = 5         # tijdstap van het weer en het werkschema (min)


def met_uit_w_m2(w_m2: float) -> float:
    import hestia_model as hm
    return float(w_m2) / hm.MET_W_M2


def w_m2_uit_met(met: float) -> float:
    import hestia_model as hm
    return float(met) * hm.MET_W_M2


def iso7243_grens(m_w_m2: float, geacclimatiseerd: bool, luchtbeweging: bool = False) -> float:
    for rij in ISO_7243:
        if m_w_m2 <= rij[0]:
            if luchtbeweging:
                return rij[3] if geacclimatiseerd else rij[4]
            return rij[1] if geacclimatiseerd else rij[2]
    raise ValueError("onbereikbaar")


# =============================================================================
# 2. WERKSCHEMA
# =============================================================================
@dataclass
class WerkSchema:
    begin: str = "07:00"
    einde: str = "16:00"
    werk_min: int = 45            # per cyclus
    rust_min: int = 15            # per cyclus (0 = doorwerken)
    pauzes: list = field(default_factory=lambda: [("10:00", 15), ("12:30", 30), ("15:00", 15)])
    rust_met: float = 1.5         # = hestia_model.PF_MET_RUST (staan/zitten)
    schaduw: bool = False         # rust en pauze in de schaduw

    def fouten(self) -> list[str]:
        f = []
        try:
            b = pd.Timestamp(f"2000-01-01 {self.begin}")
            e = pd.Timestamp(f"2000-01-01 {self.einde}")
            if e <= b:
                f.append(vt("einde moet na begin liggen", "end must be after start"))
            elif (e - b) > pd.Timedelta(hours=14):
                f.append(vt("werkdag langer dan 14 uur", "working day longer than 14 hours"))
        except Exception:
            f.append(vt("begin/einde: tijd als UU:MM", "start/end: time as HH:MM"))
        if self.werk_min <= 0 or self.rust_min < 0:
            f.append(vt("werk-rustcyclus: werkminuten > 0, rustminuten >= 0", "work–rest cycle: work minutes > 0, rest minutes >= 0"))
        if self.werk_min % STAP_MIN or self.rust_min % STAP_MIN:
            f.append(vt(f"werk- en rustminuten in stappen van {STAP_MIN}", f"work and rest minutes in steps of {STAP_MIN}"))
        for t, d in self.pauzes:
            try:
                pd.Timestamp(f"2000-01-01 {t}")
            except Exception:
                f.append(vt(f"pauze {t}: tijd als UU:MM", f"break {t}: time as HH:MM"))
            if d <= 0 or d % STAP_MIN:
                f.append(vt(f"pauze {t}: duur > 0 in stappen van {STAP_MIN} min", f"break {t}: duration > 0 in steps of {STAP_MIN} min"))
        if not 1.0 <= self.rust_met <= 3.0:
            f.append(vt("rust-MET: 1,0 t/m 3,0", "rest MET: 1.0 to 3.0"))
        return f

    def duur_h(self) -> float:
        b = pd.Timestamp(f"2000-01-01 {self.begin}")
        e = pd.Timestamp(f"2000-01-01 {self.einde}")
        return (e - b).total_seconds() / 3600.0

    def werkaandeel(self) -> float:
        return self.werk_min / float(self.werk_min + self.rust_min)


def fasen(schema: WerkSchema, tijden) -> list[str]:
    """Fase per tijdstap: 'werk', 'rust' of 'pauze'. Stap i beslaat
    (t[i-1], t[i]]; de fase volgt het midden van die stap. Stap 0 is de
    begintoestand (geen verstreken tijd) en krijgt de fase van de eerste stap."""
    tijden = [pd.Timestamp(t) for t in tijden]
    if not tijden:
        return []
    begin = tijden[0]
    cyc = schema.werk_min + schema.rust_min
    pz = []
    for t, d in schema.pauzes:
        s = pd.Timestamp(f"{begin.date()} {t}")
        if begin.tzinfo is not None and s.tzinfo is None:
            s = s.tz_localize(begin.tzinfo)
        pz.append((s, s + pd.Timedelta(minutes=int(d))))
    uit = []
    for i, t in enumerate(tijden):
        if i == 0:
            mid = t + pd.Timedelta(minutes=STAP_MIN / 2.0)
        else:
            mid = tijden[i - 1] + (t - tijden[i - 1]) / 2
        if any(a <= mid < b for a, b in pz):
            uit.append("pauze")
            continue
        m = (mid - begin).total_seconds() / 60.0
        uit.append("werk" if (m % cyc) < schema.werk_min else "rust")
    return uit


# =============================================================================
# 3. GROEP WERKERS
# =============================================================================
@dataclass
class WerkerProfiel:
    height: float
    weight: float
    age: int
    gender: str
    body_fat_pct: float
    vo2max: float
    pct_vo2max: float          # deel van VO2max bij het werk (vóór trainingscorrectie)
    temp_variation: float
    rh_variation: float
    mf_score: float
    sweat_factor: float
    thirst_threshold: float
    wind_angle_rad: float
    nummer: int = 0


def _leeftijd(rng, gender: str) -> int:
    kol = 2 if gender == "male" else 3
    banden = []
    for lo, hi, m, v in CBS_LEEFTIJD:
        a, b = max(lo, LEEFTIJD_MIN), min(hi, LEEFTIJD_MAX + 1)   # [a, b) in hele jaren
        if b <= a:
            continue
        gewicht = (m if kol == 2 else v) * (b - a) / float(hi - lo)
        banden.append((a, b, gewicht))
    w = np.array([g for _, _, g in banden], dtype=float)
    k = int(rng.choice(len(banden), p=w / w.sum()))
    return int(rng.integers(banden[k][0], banden[k][1]))


def genereer_werkers(n: int, seed: int, werk_met: float, man_aandeel: float,
                     training_factor: float, acclimatisatie: float) -> list[WerkerProfiel]:
    """Groep werkers. Lichaamsbouw en fitheid zoals de wandelaars in
    hestia_model (LowLands/de Wild VO2max, CV 0,19; BMI Terink 2018;
    Deurenberg-vet), leeftijd uit CBS. %VO2max bij het werk: werk-MET x 3,5 /
    VO2max met dezelfde ruis (sigma 0,04) als generate_base_population,
    begrensd op 0,15-0,95 (geen afwijzing: zwaar werk voor een minder fitte
    werker blijft in de groep; het aandeel boven 50 % VO2max staat in de
    uitkomst). Eigen RNG: raakt de globale numpy-RNG niet."""
    import hestia_model as hm
    rng = np.random.default_rng(int(seed))
    uit = []
    pogingen = 0
    while len(uit) < n and pogingen < n * 30:
        pogingen += 1
        gender = "male" if rng.random() < float(man_aandeel) else "female"
        age = _leeftijd(rng, gender)
        mu = hm.walker_vo2max_mean(age, gender)
        vo2max = float(np.clip(rng.normal(mu, hm.WALKER_VO2MAX_CV * mu), 15.0, 70.0))
        if gender == "male":
            height = float(np.clip(rng.normal(1.78, 0.07), 1.60, 2.00))
        else:
            height = float(np.clip(rng.normal(1.65, 0.06), 1.48, 1.85))
        mb, sb = hm.WALKER_BMI[gender]
        bmi_t = float(np.clip(rng.normal(mb, sb), 18.0, 40.0))
        weight = float(np.clip(bmi_t * height ** 2, 40.0, 150.0))
        bmi = weight / height ** 2
        if not 18.0 <= bmi <= 40.0:
            continue
        fat = float(np.clip(hm.walker_body_fat(bmi, age, gender) + rng.normal(0.0, 4.0), 8.0, 50.0))
        pct_det = werk_met * hm.VO2MAX_TO_MET_FACTOR / vo2max
        pct = float(np.clip(rng.normal(pct_det, 0.04), 0.15, 0.95))
        sweat = float(np.clip(rng.normal(0.8, 0.15), 0.4, 1.5))
        thirst = float(rng.uniform(1.0, max(1.1, 2.5 - float(acclimatisatie) * 1.0)))
        uit.append(WerkerProfiel(
            height=height, weight=weight, age=age, gender=gender, body_fat_pct=fat,
            vo2max=vo2max, pct_vo2max=pct,
            temp_variation=float(rng.normal(0.0, 1.5)), rh_variation=float(rng.normal(0.0, 3.0)),
            mf_score=float(rng.uniform(0.0, 1.0)), sweat_factor=sweat, thirst_threshold=thirst,
            wind_angle_rad=float(rng.uniform(0.0, 2 * np.pi)), nummer=len(uit)))
    return uit


def werk_met_individueel(p: WerkerProfiel, training_factor: float) -> float:
    """Zoals calculate_indices_jos3_adult: vo2max x pct / 3,5 min de
    trainingscorrectie (0,05 x tf), minimaal 1,5 MET."""
    import hestia_model as hm
    basis = p.vo2max * p.pct_vo2max / hm.VO2MAX_TO_MET_FACTOR
    return max(1.5, basis - training_factor * basis * 0.05)


# =============================================================================
# 4. OMGEVING PER STAP
# =============================================================================
def omgeving(interp, lat, lon, aqi_patch: Optional[int] = None,
             temp_var: float = 0.0, rh_var: float = 0.0) -> dict:
    """Luchttemperatuur, RV, wind op 1,5 m, MRT, WBGT en UTCI per stap, met
    dezelfde regels als calculate_indices_jos3_adult (voorberekende waarden
    van de Data Engine waar aanwezig)."""
    import hestia_model as hm
    from pythermalcomfort.models import utci, wbgt
    times = [e["time"] for e in interp]
    temps = [e["temp"] + temp_var for e in interp]
    wind_10m = [e["wind"] for e in interp]
    wind_15 = [hm.wind_speed_at_height(w, 10, 1.5) for w in wind_10m]
    rhs = [float(np.clip(e["rh"] + rh_var, 10, 95)) for e in interp]
    clouds = [e["clouds"] for e in interp]
    pressures = [e["pressure"] for e in interp]
    aqi = hm.get_air_quality(lat, lon)
    ghi, elev, globe, mrts, bron = hm.radiation_series(
        interp, times, temps, wind_15, pressures, clouds, lat, lon, aqi, rhs=rhs)
    if interp[0].get("twb_precomputed") is not None:
        twbs = [e["twb_precomputed"] for e in interp]
    else:
        twbs = [hm.wet_bulb_tmp(tdb=t, rh=r) for t, r in zip(temps, rhs)]
    w_pre = [e.get("wbgt_precomputed") for e in interp]
    u_pre = [e.get("utci_precomputed") for e in interp]
    wbgts, wbgt_schaduw, utcis = [], [], []
    for i in range(len(interp)):
        if w_pre[i] is not None:
            wv = w_pre[i]
        else:
            zon = bool(ghi[i] > 0 and elev[i] > 0)
            a = {"twb": twbs[i], "tg": globe[i], "with_solar_load": zon, "round_output": True}
            if zon:
                a["tdb"] = temps[i]
            wv = float(wbgt(**a).wbgt)
        wbgts.append(float(wv))
        # Schaduw: bolthermometer = luchttemperatuur, zonder zonlast (WBGT binnen).
        wbgt_schaduw.append(float(wbgt(twb=twbs[i], tg=temps[i], with_solar_load=False,
                                       round_output=True).wbgt))
        utcis.append(float(u_pre[i]) if u_pre[i] is not None else
                     float(utci(tdb=temps[i], tr=mrts[i], v=wind_10m[i], rh=rhs[i]).utci))
    return {"times": times, "temps": temps, "rhs": rhs, "wind_10m": wind_10m, "wind_15": wind_15,
            "mrts": [float(x) for x in mrts], "wbgt": wbgts, "wbgt_schaduw": wbgt_schaduw,
            "utci": utcis, "stralingsbron": bron}


# =============================================================================
# 5. EEN WERKER (tijdstaplus)
# =============================================================================
def _zaad(p: WerkerProfiel) -> int:
    """Zoals worker_monte_carlo_adult: zaad uit het eigen profiel, zodat de
    drinkslokken niet afhangen van volgorde of parallel/serieel rekenen."""
    k = (round(float(p.height), 6), round(float(p.weight), 6), int(p.age),
         round(float(p.vo2max), 6), round(float(p.pct_vo2max), 6),
         round(float(p.wind_angle_rad), 9))
    return zlib.crc32(repr(k).encode()) & 0xFFFFFFFF


def simuleer_werker(args) -> list[dict]:
    """Een werker over de werkdag. args = (interp, lat, lon, profiel, fasen,
    rust_met, clo, schaduw, training_factor, acclimatisatie). Top-level
    (ProcessPool, spawn)."""
    (interp, lat, lon, p, fase, rust_met, clo, schaduw, tf, af) = args
    import hestia_model as hm
    import jos3_leeftijd
    from HESTIA_CVR_Module_v2 import RunnerProfile, JOS3Outputs, CVRModel, link_cvr_to_jos3

    np.random.seed(_zaad(p))
    om = omgeving(interp, lat, lon, temp_var=p.temp_variation, rh_var=p.rh_variation)
    times, temps, rhs, mrts, wind_15 = om["times"], om["temps"], om["rhs"], om["mrts"], om["wind_15"]
    met_werk = werk_met_individueel(p, tf)

    jos3_leeftijd.set_person(p.vo2max, p.age, p.gender, af)
    model = hm.maak_jos3(height=p.height, weight=p.weight, age=p.age, fat=p.body_fat_pct, sex=p.gender)
    runner = RunnerProfile(mass=p.weight, height=p.height * 100, age=p.age, sex=p.gender,
                           vo2max=p.vo2max, hr_max=None, hr_rest=None,
                           acclimatisation=float(af or 0.0))
    cvr_live = CVRModel(runner)

    dts = [0.0] + [(times[i + 1] - times[i]).total_seconds() / 60.0 for i in range(len(times) - 1)]
    res, reeks = [], []
    water_g = 0.0
    kan_drinken = True
    met_cv = hm.PF_MET_RUST
    snap_prev = None
    cap_last = None
    plafond_min = 0.0
    for i in range(len(times)):
        f = fase[i]
        met_plan = met_werk if f == "werk" else float(rust_met)
        met = met_plan
        if hm.CV_CEILING_FORCED and i > 0 and snap_prev is not None:
            cap_now = cvr_live.met_at_ceiling(snap_prev)
            cap = cap_now - (max(0.0, cap_last - cap_now)
                             if hm.CV_CEILING_ANTICIPATE and cap_last is not None else 0.0)
            cap_last = cap_now
            if met > cap:
                met = max(1.5, cap)
                plafond_min += dts[i]
        dt = float(dts[i])
        rust_schaduw = schaduw and f != "werk"
        model.par = hm.jos3_par(model, met)
        model.tdb = temps[i]
        model.tr = temps[i] if rust_schaduw else mrts[i]
        model.rh = rhs[i]
        model.v = hm.compute_relative_wind(v_ambient=wind_15[i], v_running=0.0,
                                           angle_rad=p.wind_angle_rad)
        model.clo = clo
        if i > 0:
            model.simulate(times=int(round(dt)), dtime=60)
        drip = jos3_leeftijd.drip_take_rate(int(round(dt)) if i > 0 else 1)
        t_rect = hm.jos3_t_rect(model)
        rj = model.dict_results()
        wl = np.asarray(rj["weight_loss_by_evap_and_res"], dtype=float).ravel()
        n_stap = max(1, int(round(dt))) if i > 0 else 1
        rate = (float(np.mean(wl[-n_stap:])) if wl.size else 0.0) + drip
        zweet = rate * 60.0 * p.sweat_factor
        water_g += zweet * dt if i > 0 else 0.0
        pct = (water_g / 1000.0) / p.weight * 100.0
        dorst = pct >= p.thirst_threshold
        if dorst and (kan_drinken or hm.DRINK_EVERY_STEP_WHEN_THIRSTY):
            water_g = max(0.0, water_g - np.random.uniform(120, 180))
            kan_drinken = False
        if not dorst:
            kan_drinken = True
        hr = co_res = float("nan")
        if i > 0:
            met_cv = hm.cv_met_lag(met_cv, met, dt)
            co_lh = float(np.array(rj["cardiac_output"]).flat[-1]) if "cardiac_output" in rj else 900.0
            if "bf_skin" in rj:
                a = np.array(rj["bf_skin"])
                bfsk = float(a[-1].sum() if a.ndim == 2 else a.sum())
            else:
                bfsk = co_lh * 0.25
            snap = JOS3Outputs(
                t_min=i, cardiac_output=co_lh, t_core_mean=hm.jos3_core_for_chsi(model),
                t_cb=float(np.array(rj["t_cb"]).flat[-1]) if "t_cb" in rj else hm.jos3_core_for_chsi(model),
                weight_loss_g_s=water_g / 1000.0, bf_skin_total=bfsk,
                bf_ava_hand=float(np.array(rj["bf_ava_hand"]).flat[-1]) if "bf_ava_hand" in rj else 0.5,
                bf_ava_foot=float(np.array(rj["bf_ava_foot"]).flat[-1]) if "bf_ava_foot" in rj else 0.5,
                current_met=met_cv, t_skin_mean=model.t_skin.mean())
            reeks.append(snap)
            st = cvr_live.compute_step(snap)
            snap_prev = snap
            hr, co_res = float(st.HR), float(st.CO_reserve)
        res.append({
            "time": pd.Timestamp(times[i]).strftime("%Y-%m-%d %H:%M"),
            "fase": f, "met": met, "met_plan": met_plan, "t_rect": float(t_rect),
            "t_skin": float(model.t_skin.mean()), "water_g": water_g,
            "dehyd_pct": (water_g / 1000.0) / p.weight * 100.0,
            "hr": hr, "co_reserve": co_res, "t_air": temps[i], "rh": rhs[i],
            "mrt": model.tr, "wbgt": om["wbgt"][i], "utci": om["utci"][i], "dt_min": dt,
        })
    # Achteraf, zoals de loopsimulatie: dezelfde reeks door link_cvr_to_jos3.
    if reeks:
        ts = link_cvr_to_jos3(runner, reeks)
        for j, s in enumerate(ts.states):
            if j + 1 < len(res):
                res[j + 1]["hr"] = float(s.HR)
                res[j + 1]["co_reserve"] = float(s.CO_reserve)
    res[-1]["met_werk"] = met_werk
    res[-1]["met_plafond_min"] = plafond_min
    res[-1]["hr_max"] = float(cvr_live.HR_max)
    return res


# =============================================================================
# 6. ISO 7933 (PHS) ALS CONTROLE
# =============================================================================
def phs_controle(interp, lat, lon, fase, met_werk: float, rust_met: float, clo: float,
                 schaduw: bool, gewicht: float, lengte: float, geacclimatiseerd: bool) -> dict:
    """Een gemiddelde werker met het PHS-model van ISO 7933:2023
    (pythermalcomfort.models.phs), per stap doorgeschakeld met de toestand van
    de vorige stap. limit_inputs=False; stappen buiten het geldigheidsgebied
    worden gemeld (0,96-4,3 MET; 15-50 degC; tr - tdb 0-60; clo 0,1-1)."""
    from pythermalcomfort.models import phs
    om = omgeving(interp, lat, lon)
    t_re, water, buiten = [], [], 0
    staat = {}
    water_tot = 0.0
    for i, t in enumerate(om["times"]):
        f = fase[i]
        met = met_werk if f == "werk" else rust_met
        tr = om["temps"][i] if (schaduw and f != "werk") else om["mrts"][i]
        tdb = om["temps"][i]
        if not (0.96 < met < 4.3 and 15 < tdb < 50 and 0 <= tr - tdb < 60 and 0.1 < clo < 1):
            buiten += 1
        if i == 0:
            t_re.append(36.8)
            water.append(0.0)
            continue
        dt = int(round((om["times"][i] - om["times"][i - 1]).total_seconds() / 60.0))
        r = phs(tdb=tdb, tr=tr, v=max(0.1, om["wind_15"][i]), rh=om["rhs"][i], met=met, clo=clo,
                posture="standing", round_output=False, duration=dt, limit_inputs=False,
                weight=gewicht, height=lengte, acclimatized=100 if geacclimatiseerd else 0,
                drink=1, **staat)
        staat = {"t_sk": r.t_sk, "t_cr": r.t_cr, "t_re": r.t_re, "t_cr_eq": r.t_cr_eq,
                 "t_sk_t_cr_wg": r.t_sk_t_cr_wg, "sweat_rate_watt": r.sweat_rate_watt,
                 "evap_load_wm2_min": r.evap_load_wm2_min}
        water_tot = float(r.sweat_loss_g)   # bij doorschakelen al cumulatief (gecontroleerd)
        t_re.append(float(r.t_re))
        water.append(water_tot)
    return {"times": om["times"], "t_re": t_re, "water_g": water, "stappen_buiten": buiten,
            "stappen": len(om["times"])}


# =============================================================================
# 7. UITKOMST
# =============================================================================
def _matrix(sporen, sleutel):
    n = max((len(s) for s in sporen), default=0)
    m = np.full((len(sporen), n), np.nan)
    for j, s in enumerate(sporen):
        for k, r in enumerate(s):
            v = r.get(sleutel)
            if v is not None:
                try:
                    m[j, k] = float(v)
                except (TypeError, ValueError):
                    pass
    return m


def samenvatting(sporen: list, profielen: list, fase: list, om: dict, met_werk_plan: float,
                 rust_met: float, kleding_cav: float, acclimatisatie: float,
                 schaduw: bool) -> dict:
    """Beroepsgrenzen per groep (bronnenstudie, hoofdstuk Uitkomst)."""
    from uncertainty import fraction_interval
    n = len(sporen)
    import warnings
    warnings.filterwarnings("ignore", "Mean of empty slice", RuntimeWarning)
    tm = _matrix(sporen, "t_rect")
    dm = _matrix(sporen, "dehyd_pct")
    hm_ = _matrix(sporen, "hr")
    tijden = [pd.Timestamp(r["time"]) for r in sporen[0]]
    gem = np.nanmean(tm, axis=0)
    p5, p95 = np.nanpercentile(tm, 5, axis=0), np.nanpercentile(tm, 95, axis=0)
    accl = float(acclimatisatie) >= ACCL_DREMPEL

    def eerste(drempel):
        k = np.where(gem >= drempel)[0]
        return tijden[int(k[0])] if k.size else None

    piek = np.nanmax(tm, axis=1)
    dehyd_max = np.nanmax(dm, axis=1)
    leeftijden = np.array([p.age for p in profielen], dtype=float)
    # Aanhoudende hartslag: minstens een hele stap (5 min) boven 180 - leeftijd.
    hr_boven = np.array([np.any(hm_[j, 1:] > HR_AANHOUDEND(leeftijden[j])) for j in range(n)])
    werk = np.array([f == "werk" for f in fase])
    hr_dag = np.nanmean(hm_[:, 1:], axis=1)
    met_ind = np.array([s[-1]["met_werk"] for s in sporen])
    vo2 = np.array([p.vo2max for p in profielen])
    pct_werk = met_ind * 3.5 / vo2
    k38 = int(np.sum(piek >= T_KERN_GRENS_NIET_ACCL))
    k385 = int(np.sum(piek >= T_KERN_GRENS_ACCL))
    kdeh = int(np.sum(dehyd_max >= GEWICHTSVERLIES_GRENS_PCT))
    khr = int(np.sum(hr_boven))
    k50 = int(np.sum(pct_werk > 0.50))
    import hestia_model as hm
    k42 = int(np.sum(piek > hm.T_THERMAL_ONLY_CRITICAL))   # buiten het getoetste gebied van het model

    # WBGT per klokuur tegen ISO 7243: tijdgewogen WBGT en M over werk en rust.
    df = pd.DataFrame({"t": om["times"], "fase": fase, "wbgt": om["wbgt"],
                       "wbgt_s": om["wbgt_schaduw"]})
    df["t"] = pd.to_datetime(df["t"])
    df["wbgt_eff"] = np.where((df["fase"] != "werk") & schaduw, df["wbgt_s"], df["wbgt"]) + kleding_cav
    df["m"] = np.where(df["fase"] == "werk", w_m2_uit_met(met_werk_plan), w_m2_uit_met(rust_met))
    df = df.iloc[1:]   # stap 0 = begintoestand
    uren = []
    for uur, g in df.groupby(df["t"].dt.floor("h")):
        m = float(g["m"].mean())
        w = float(g["wbgt_eff"].mean())
        uren.append({"uur": uur, "wbgt_twa": w, "m_twa": m,
                     "grens": iso7243_grens(m, accl), "boven": w > iso7243_grens(m, accl)})
    return {
        "n": n, "tijden": tijden, "gem": gem, "p5": p5, "p95": p95,
        "gem_max": float(np.nanmax(gem)),
        "gem_tijd_380": eerste(T_KERN_GRENS_NIET_ACCL),
        "gem_tijd_385": eerste(T_KERN_GRENS_ACCL),
        "geacclimatiseerd": accl,
        "grens_hoofd": T_KERN_GRENS_ACCL if accl else T_KERN_GRENS_NIET_ACCL,
        "fi_380": fraction_interval(k38, n), "fi_385": fraction_interval(k385, n),
        "fi_dehyd": fraction_interval(kdeh, n), "fi_hr": fraction_interval(khr, n),
        "fi_pct50": fraction_interval(k50, n),
        "fi_42": fraction_interval(k42, n), "t_kritiek": float(hm.T_THERMAL_ONLY_CRITICAL),
        "hr_dag_gem": float(np.nanmean(hr_dag)),
        "piek": piek, "dehyd_max": dehyd_max,
        "dehyd_gem": np.nanmean(dm, axis=0),
        "hr_gem": np.nanmean(hm_, axis=0),
        "met_plafond_aandeel": float(np.mean([s[-1]["met_plafond_min"] > 0 for s in sporen])),
        "uren": uren, "fase": fase,
        "werkminuten": float(df.loc[df["fase"] == "werk", "t"].count() * STAP_MIN),
    }


def top_tien(sporen, n=10) -> list[int]:
    piek = [np.nanmax([r["t_rect"] for r in s]) for s in sporen]
    return [int(i) for i in np.argsort(piek)[::-1][:n]]


# =============================================================================
# 8. VOLLEDIGE RUN (serieel of met een pool van buitenaf)
# =============================================================================
@dataclass
class WerkInvoer:
    plaats: str
    datum: str
    schema: WerkSchema
    werk_met: float
    werk_label: str
    man_aandeel: float
    kleding: int            # index in KLEDING
    profiel: int            # index in adaptatieprofielen (hestia_console)

    def fouten(self) -> list[str]:
        f = list(self.schema.fouten())
        if not 1.0 <= self.werk_met <= 10.0:
            f.append(vt("werk-MET: 1,0 t/m 10,0", "work MET: 1.0 to 10.0"))
        if not 0.0 <= self.man_aandeel <= 1.0:
            f.append(vt("aandeel mannen: 0 t/m 1", "share of men: 0 to 1"))
        if not 0 <= self.kleding < len(KLEDING):
            f.append(vt("onbekende kleding", "unknown clothing"))
        return f

    def venster(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return (pd.Timestamp(f"{self.datum} {self.schema.begin}"),
                pd.Timestamp(f"{self.datum} {self.schema.einde}"))


def werker_lid(a):
    """Voor een ProcessPool: (gen, i, args, aqi) -> (gen, i, sporen). Zet de
    luchtkwaliteit vast zoals hestia_bridge._patch_air_quality (geen
    netwerkaanroep per werker)."""
    gen, i, args, aqi = a
    import hestia_bridge as hb
    import hestia_model as hm
    hb._patch_air_quality(aqi)
    hm.CV_CEILING_FORCED = True   # suite-standaard
    return gen, i, simuleer_werker(args)


def taak_args(interp, lat, lon, profielen, fase, inv: WerkInvoer, tf, af):
    clo = KLEDING[inv.kleding][1]
    return [(interp, lat, lon, p, fase, inv.schema.rust_met, clo, inv.schema.schaduw, tf, af)
            for p in profielen]


@dataclass
class WerkTaak:
    inv: WerkInvoer
    lat: float
    lon: float
    tz: str
    n: int
    seed: int
    tf: float
    af: float
    interp: list
    fase: list
    profielen: list
    args: list
    gen: int = 0
    res: dict = field(default_factory=dict)


def voorbereiden(inv: WerkInvoer, weer_df: pd.DataFrame, lat: float, lon: float, tz: str,
                 n: int = 200, seed: int = 42, tf: float = None, af: float = None,
                 gen: int = 0) -> WerkTaak:
    """Weer op 5-min stappen, fasen, groep werkers en de argumenten per werker."""
    import hestia_bridge as hb
    import individual_engine as ie
    if inv.fouten():
        raise ValueError("; ".join(inv.fouten()))
    if tf is None or af is None:
        import hestia_populatie_ui as hpu
        _, tf, af = hpu.adaptatieprofielen()[inv.profiel]
    s, e = inv.venster()
    sa, ea = ie._localize_naive(s, tz), ie._localize_naive(e, tz)
    lo, hi = weer_df.index.min(), weer_df.index.max()
    if sa < lo or ea > hi:
        raise ValueError(vt(f"Het weer dekt de werkdag {s:%d-%m %H:%M} - {e:%H:%M} niet "
                         f"(beschikbaar {lo:%d-%m %H:%M} t/m {hi:%d-%m %H:%M}).",
                            f"The weather does not cover the working day {s:%d-%m %H:%M} - {e:%H:%M} "
                         f"(available {lo:%d-%m %H:%M} to {hi:%d-%m %H:%M})."))
    interp = hb.build_interp_data(weer_df, sa, ea, interval_minutes=STAP_MIN)
    fase = fasen(inv.schema, [r["time"] for r in interp])
    prof = genereer_werkers(n, seed, inv.werk_met, inv.man_aandeel, tf, af)
    if not prof:
        raise ValueError(vt("Geen werkers getrokken.", "No workers drawn."))
    return WerkTaak(inv, lat, lon, tz, len(prof), seed, tf, af, interp, fase, prof,
                    taak_args(interp, lat, lon, prof, fase, inv, tf, af), gen)


def afronden(t: WerkTaak) -> dict:
    """Uitkomst als alle werkers klaar zijn: beroepsgrenzen, WBGT per uur en PHS."""
    inv = t.inv
    sporen = [t.res[i] for i in range(t.n)]
    om = omgeving(t.interp, t.lat, t.lon)
    sam = samenvatting(sporen, t.profielen, t.fase, om, inv.werk_met, inv.schema.rust_met,
                       KLEDING[inv.kleding][2], t.af, inv.schema.schaduw)
    gl = float(np.mean([p.height for p in t.profielen]))
    gw = float(np.mean([p.weight for p in t.profielen]))
    phs_r = phs_controle(t.interp, t.lat, t.lon, t.fase,
                         float(np.mean([s[-1]["met_werk"] for s in sporen])),
                         inv.schema.rust_met, KLEDING[inv.kleding][1], inv.schema.schaduw,
                         gw, gl, sam["geacclimatiseerd"])
    return {"invoer": inv, "interp": t.interp, "fase": t.fase, "profielen": t.profielen,
            "sporen": sporen, "omgeving": om, "samen": sam, "phs": phs_r, "tf": t.tf, "af": t.af,
            "n": t.n, "seed": t.seed}


def bereken(inv: WerkInvoer, weer_df: pd.DataFrame, lat: float, lon: float, tz: str,
            n: int = 200, seed: int = 42, kaart=map, tf: float = None, af: float = None,
            aqi: Optional[int] = None) -> dict:
    """Volledige berekening in een keer. `kaart` = map (serieel) of pool.map."""
    import hestia_bridge as hb
    if aqi is not None:
        hb._patch_air_quality(int(aqi))
    t = voorbereiden(inv, weer_df, lat, lon, tz, n, seed, tf, af)
    for i, sp in enumerate(kaart(simuleer_werker, t.args)):
        t.res[i] = sp
    return afronden(t)
