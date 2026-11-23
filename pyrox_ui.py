# -*- coding: utf-8 -*-
"""
pyrox_ui.py
===========
Visuele invoer en weergave (Tkinter) voor PYROX: meerdaagse hittebelasting van
bevolkingsgroepen.

De suite blijft bevroren: dit script verandert niets aan de suitebestanden en
roept alleen bestaande functies aan.

  weer per uur ............ Data Engine-bestand (ThermopoulosData) of online via
                            Thermopoulos_Data_Engine (fetch_hourly_forecast,
                            fetch_historical_data, process_weather_data), zoals
                            de Data Engine zelf: verwachting 16 dagen, de
                            afgelopen dagen uit het ERA5-archief ervoor
  dagtabel ................ thermopoulos_loader.ThermopoulosData.get_daily_heat_loads
                            (Tmax, Tmin, nacht-minimum, RH, wind, warmtebelasting)
  verleden + verwachting .. ThermopoulosData.get_combined_window / forecast_start_index
  slaapkwaliteit .......... ThermopoulosData.sleep_quality_series
  PYROX per groep ......... run_pyrox.assess_population -> PyroxModel.simulate
  zones ................... pyrox_plots._strain_zone (50 / 75 / 90 % van de
                            kritieke grens van de groep)
  terugkoppeling .......... de diagnostics van simulate() (zoals plot_feedback_race)
  onzekerheid verwachting . central / -D / +D op de verwachtingsdagen, D = graden x
                            HEAT_LOAD_PER_DEGREE (zoals plot_forecast_uncertainty)
  regimes ................. pyrox_model.equilibrium_strain (zoals plot_three_regimes)
  Word-rapport ............ generate_pyrox_report + report_to_docx.export_report_docx
                            (zoals rapportpakket), in een apart proces

Om het weer aan de suitefuncties te geven worden twee kleine tussenobjecten
gebruikt (_UurBron, _DagBron) die zich gedragen als ThermopoulosData; de
rekenregels zelf komen ongewijzigd uit de suite.

Weergave: Sigma staat als percentage van de kritieke grens van de eigen groep,
zodat groepen met een andere kritieke grens (bijv. zwangeren T1: 1,11) op een
gemeenschappelijke schaal staan; de zonegrenzen 50/75/90 % zijn dan voor alle
groepen dezelfde lijnen. Dat is alleen weergave: de waarden zijn die van de suite.

Route platteland: de rurale tak van process_weather_data (inwonertal 0). Bij een
Data Engine-bestand wordt dat per blad opnieuw verwerkt; de terreinruwheid z0
doet voor PYROX niet ter zake (de dagtabel gebruikt wind_10m).

Status: research software. De warmtebelasting is een modelkeuze (gekalibreerd op
Parijs 2003); 16 van de 19 groepen zijn geextrapoleerd (pyrox_groups.py).

Starten:  python pyrox_ui.py
"""
from __future__ import annotations

import os
import queue
import threading
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

HIER = Path(__file__).resolve().parent
COMBI = "Verleden + verwachting (gecombineerd)"


# =============================================================================
# 1. REKENKERN
# =============================================================================
class _UurBron:
    """Gedraagt zich voor ThermopoulosData.get_daily_heat_loads() als een
    ThermopoulosData met een uurblad (naive lokale tijd)."""

    def __init__(self, uur: pd.DataFrame, naam: str):
        self._uur = uur
        self.excel_path = Path(naam)

    def _load_sheet(self, sheet):
        return self._uur


def dagtabel(uur: pd.DataFrame, naam: str = "online") -> pd.DataFrame:
    from thermopoulos_loader import ThermopoulosData
    if uur.index.tz is not None:
        uur = uur.copy()
        uur.index = uur.index.tz_localize(None)
    return ThermopoulosData.get_daily_heat_loads(_UurBron(uur, naam), "UI")


class _DagBron:
    """Gedraagt zich voor run_pyrox.assess_population() (en voor
    ThermopoulosData.get_combined_window) als een ThermopoulosData."""

    def __init__(self, city: str, dagen: dict):
        self.city = city
        self._dagen = dagen          # bladnaam -> dagtabel

    def get_daily_heat_loads(self, sheet):
        return self._dagen[sheet].copy()

    @staticmethod
    def sleep_quality_series(daily):
        from thermopoulos_loader import ThermopoulosData
        return ThermopoulosData.sleep_quality_series(daily)


def combineer(dag_verleden: pd.DataFrame, dag_verwachting: pd.DataFrame, n_verleden: int,
              n_verwachting: int) -> tuple[pd.DataFrame, int]:
    from thermopoulos_loader import ThermopoulosData
    b = _DagBron("", {"H": dag_verleden, "F": dag_verwachting})
    comb = ThermopoulosData.get_combined_window(b, hindcast_days=n_verleden, forecast_days=n_verwachting,
                                                hindcast_sheet="H", forecast_sheet="F")
    return comb, ThermopoulosData.forecast_start_index(b, comb)


class Weer:
    """Dagtabel klaar voor PYROX."""

    def __init__(self, daily: pd.DataFrame, city: str, label: str, forecast_start: Optional[int],
                 bladnaam_rapport: str):
        self.daily = daily.reset_index(drop=True)
        self.city = city
        self.label = label
        self.forecast_start = forecast_start
        self.bladnaam_rapport = bladnaam_rapport


class WeerLader:
    def __init__(self):
        self._cache = {}

    def _verwerk(self, ruw, coastal, kand, route):
        import Thermopoulos_Data_Engine as de
        city = dict(kand)
        if route == "platteland":
            city["population"] = 0
        z0 = de.ROUGHNESS_Z0_TERRAIN["3"][1]
        return de.process_weather_data(ruw.copy(), city, kand["latitude"], kand["longitude"],
                                       kand["timezone"], coastal_active=coastal, roughness_z0=z0)

    # ---------------------------------------------------------------- online
    def online_verwachting(self, kand, route, n_verleden, n_verwachting) -> Weer:
        import Thermopoulos_Data_Engine as de
        lat, lon, tz = kand["latitude"], kand["longitude"], kand["timezone"]
        vandaag = str(pd.Timestamp.now(tz=tz).date())
        k = ("verw", round(lat, 4), round(lon, 4), vandaag, n_verleden, route)
        if k not in self._cache:
            fr, fc = de.fetch_hourly_forecast(lat, lon, tz, days=16)          # zoals de Data Engine
            fr = de.validate_weather_data(fr, "forecast")
            start = fr.index[0].date()
            h_eind = start - pd.Timedelta(days=1)
            h_start = h_eind - pd.Timedelta(days=n_verleden - 1)
            hr, hc = de.fetch_historical_data(lat, lon, tz, start_date=h_start.strftime("%Y-%m-%d"),
                                              end_date=h_eind.strftime("%Y-%m-%d"))
            hr = de.validate_weather_data(hr, "hindcast")
            self._cache[k] = (dagtabel(self._verwerk(hr, hc, kand, route)),
                              dagtabel(self._verwerk(fr, fc, kand, route)))
        dh, df_ = self._cache[k]
        comb, fs = combineer(dh, df_, n_verleden, n_verwachting)
        return Weer(comb, kand["name"], f"online: {n_verleden} d ERA5-archief + {n_verwachting} d verwachting",
                    fs, f"Hindcast_{n_verleden}d + verwachting_{n_verwachting}d")

    def online_historisch(self, kand, route, van, tot) -> Weer:
        import Thermopoulos_Data_Engine as de
        lat, lon, tz = kand["latitude"], kand["longitude"], kand["timezone"]
        k = ("hist", round(lat, 4), round(lon, 4), van, tot, route)
        if k not in self._cache:
            if pd.Timestamp(tot) >= pd.Timestamp.now().normalize():
                raise ValueError("Historische periode: 'tot' moet in het verleden liggen.")
            r, c = de.fetch_historical_data(lat, lon, tz, start_date=van, end_date=tot)
            r = de.validate_weather_data(r, "historical")
            self._cache[k] = dagtabel(self._verwerk(r, c, kand, route))
        return Weer(self._cache[k], kand["name"], f"online: ERA5-archief {van} t/m {tot}", None,
                    "Historical_Custom")

    # ----------------------------------------------------------------- excel
    def excel(self, pad, blad, route, n_verleden, n_verwachting) -> Weer:
        from thermopoulos_loader import ThermopoulosData
        k = ("xl", str(pad), route)
        if k not in self._cache:
            data = ThermopoulosData(str(pad))
            dagen = {}
            for s in data.available_sheets:
                if route == "stad":
                    dagen[s] = data.get_daily_heat_loads(s)
                else:
                    from hestia_loper_ui import _ruraal
                    uur = data._load_sheet(s).copy()
                    uur.index = uur.index.tz_localize(data.timezone, ambiguous=True, nonexistent="shift_forward")
                    dagen[s] = dagtabel(_ruraal(uur, data.latitude, data.longitude, data.timezone, 0.1),
                                        Path(pad).name)
            self._cache[k] = (data, dagen)
        data, dagen = self._cache[k]
        if blad == COMBI:
            if "Hindcast_14d" not in dagen or "Forecast_7d" not in dagen:
                raise ValueError("Voor 'verleden + verwachting' zijn de bladen Hindcast_14d en Forecast_7d nodig.")
            comb, fs = combineer(dagen["Hindcast_14d"], dagen["Forecast_7d"], n_verleden, n_verwachting)
            return Weer(comb, data.city, f"{Path(pad).name}: Hindcast_14d (laatste {n_verleden} d) + "
                                         f"Forecast_7d (eerste {n_verwachting} d)", fs,
                        f"Hindcast_{n_verleden}d + verwachting_{n_verwachting}d")
        fs = 0 if "forecast" in blad.lower() else None   # zoals generate_pyrox_report
        return Weer(dagen[blad], data.city, f"{Path(pad).name}: {blad}", fs, blad)

    @staticmethod
    def bladen(pad) -> list[str]:
        from thermopoulos_loader import ThermopoulosData
        s = list(ThermopoulosData(str(pad)).available_sheets)
        if "Hindcast_14d" in s and "Forecast_7d" in s:
            s = [COMBI] + s
        return s


def bereken(weer: Weer, groepen: list[str], nacht: bool, pre: Optional[float]) -> dict:
    """run_pyrox.assess_population, precies zoals de suite."""
    from run_pyrox import assess_population
    bron = _DagBron(weer.city, {weer.bladnaam_rapport: weer.daily})
    return assess_population(bron, sheet=weer.bladnaam_rapport, group_names=groepen,
                             pre_heatwave_heat_load=pre, use_nocturnal_recovery=nacht)


def onzekerheid(weer: Weer, rapport: dict, groep: str, graden: float, pre: Optional[float]):
    """Zoals pyrox_plots.plot_forecast_uncertainty: central, -D, +D, alleen op de
    verwachtingsdagen (vanaf forecast_start)."""
    from thermopoulos_loader import HEAT_LOAD_PER_DEGREE
    from pyrox_model import PyroxPopulation
    from pyrox_groups import TARGET_GROUPS
    loads = np.array(rapport["heat_loads"], dtype=float)
    d = graden * HEAT_LOAD_PER_DEGREE
    fc = weer.forecast_start if weer.forecast_start is not None else 0
    p = pre if pre is not None else loads[0]
    sq = rapport["sleep_quality"] if rapport.get("nocturnal_recovery") else None

    def sim(sign):
        x = loads.copy()
        x[fc:] = np.clip(x[fc:] + sign * d, 0, None)
        return PyroxPopulation(TARGET_GROUPS[groep]).simulate(x.tolist(), pre_heatwave_heat_load=p,
                                                              sleep_quality_series=sq)["cumulative_strain"]
    return sim(0), sim(-1), sim(+1)


# -----------------------------------------------------------------------------
# Regimes: evenwicht, stabiliteit en kantelpunt
# -----------------------------------------------------------------------------
# pyrox_model.equilibrium_strain geeft het nulpunt van de dagelijkse verandering,
# maar zegt niet of dat nulpunt stabiel is. Is de verandering negatief bij Sigma = 0
# en positief bij de kritieke grens, dan is het nulpunt een KANTELPUNT: daaronder
# dooft Sigma uit, daarboven loopt Sigma door naar de kritieke grens en blijft daar
# (bistabiel, hysterese). Daarom wordt hier met PyroxModel.simulate zelf bepaald
# (1) waar Sigma bij een aanhoudende belasting uitkomt, (2) vanaf welke begin-Sigma
# de groep kantelt, en (3) of het analytische nulpunt stabiel of instabiel is.
REG_DAGEN = 120          # lang genoeg om ook een langzame klim tot het eind te volgen
REG_LOADS = np.round(np.arange(0.1, 2.5 + 1e-9, 0.02), 2)
_REG_CACHE: dict = {}


def _eind(grp, R, s0, n=REG_DAGEN):
    from pyrox_model import PyroxModel
    return float(PyroxModel(grp).simulate([float(R)] * n, pre_heatwave_heat_load=float(R),
                                          initial_strain=float(s0))["cumulative_strain"][-1])


def kantelpunt(grp, R):
    """Kleinste begin-Sigma waarbij een aanhoudende belasting R de groep naar de
    kritieke grens brengt (PyroxModel.simulate). None = kantelt nooit (ook niet
    vlak onder de kritieke grens); 0 = kantelt vanuit elke begintoestand."""
    c = grp.critical_strain
    kantelt = lambda s0: _eind(grp, R, s0) >= 0.99 * c
    if kantelt(0.0):
        return 0.0
    if not kantelt(0.995 * c):
        return None
    lo, hi = 0.0, 0.995 * c
    for _ in range(16):
        m = 0.5 * (lo + hi)
        lo, hi = (lo, m) if kantelt(m) else (m, hi)
    return hi


def regimes(sleutel: str) -> dict:
    from pyrox_groups import TARGET_GROUPS
    from pyrox_model import equilibrium_strain
    if sleutel in _REG_CACHE:
        return _REG_CACHE[sleutel]
    grp = TARGET_GROUPS[sleutel]
    c = grp.critical_strain
    ana_st, ana_v, ana_stab, eind, drempel = [], [], [], [], []
    for R in REG_LOADS:
        st, v = equilibrium_strain(grp, R, grp.max_acclimatization_capacity)
        ana_st.append(st)
        ana_v.append(v)
        stab = None
        if st == "equilibrium" and v is not None:
            d = 0.03 * c
            onder, boven = _eind(grp, R, max(v - d, 0.0)), _eind(grp, R, min(v + d, 0.995 * c))
            if onder < v and boven >= 0.99 * c:
                stab = "instabiel"
            elif abs(onder - v) < 2 * d and abs(boven - v) < 2 * d:
                stab = "stabiel"
            else:
                stab = "onduidelijk"
        ana_stab.append(stab)
        eind.append(_eind(grp, R, 0.1))
        drempel.append(kantelpunt(grp, R))
    zone = ["veilig" if k is None else ("kritiek" if k == 0.0 else "kantel") for k in drempel]
    uit = dict(loads=REG_LOADS, ana_state=ana_st, ana_value=ana_v, ana_stab=ana_stab, eind=np.array(eind),
               drempel=drempel, zone=zone)
    _REG_CACHE[sleutel] = uit
    return uit


def piekvoorbeeld(grp, R, voor=5, na=40, duur=3):
    """Zoek een korte hete piek (duur dagen) die de groep bij aanhoudende belasting R
    over het kantelpunt duwt. Geeft (piekbelasting, reeks) of None."""
    c = grp.critical_strain
    from pyrox_model import PyroxModel
    for dR in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0):
        reeks = [R] * voor + [R + dR] * duur + [R] * na
        tr = PyroxModel(grp).simulate(reeks, pre_heatwave_heat_load=R)["cumulative_strain"]
        if tr[-1] >= 0.99 * c:
            return R + dR, reeks
    return None


# -----------------------------------------------------------------------------
# Briefing: marge, nawerking, zekerheid, kantellandschap (alles via simulate)
# -----------------------------------------------------------------------------
DAGNAAM = ["ma", "di", "wo", "do", "vr", "za", "zo"]
ZONE_VOLGORDE = ["safe", "caution", "danger", "emergency"]
ZONE_WOORD = {"safe": "veilig", "caution": "let op", "danger": "gevaar", "emergency": "noodsituatie"}
MAX_DAGEN = 30


def dagtekst(d) -> str:
    d = pd.Timestamp(d)
    return f"{DAGNAAM[d.dayofweek]} {d:%d-%m}"


def _zone_i(v, crit) -> int:
    from pyrox_plots import _strain_zone
    return ZONE_VOLGORDE.index(_strain_zone(v, crit))


def _sim(groep: str, loads, sq, pre):
    from pyrox_model import PyroxPopulation
    from pyrox_groups import TARGET_GROUPS
    return PyroxPopulation(TARGET_GROUPS[groep]).simulate([float(x) for x in loads], pre_heatwave_heat_load=pre,
                                                     sleep_quality_series=sq)["cumulative_strain"]


def _invoer(rapport):
    loads = [float(x) for x in rapport["heat_loads"]]
    sq = [float(x) for x in rapport["sleep_quality"]] if rapport.get("nocturnal_recovery") else None
    return loads, sq


def marge(rapport: dict, groep: str, peildag: int, pre, max_dagen: int = MAX_DAGEN) -> dict:
    """'Als het zo heet blijft als op de peildag': de reeks t/m de peildag, daarna
    dezelfde dagbelasting (en dezelfde nacht) aanhoudend. Telt de dagen tot de
    zones gevaar (75 %) en noodsituatie (90 %). 0 = nu al, None = niet binnen max_dagen."""
    from pyrox_groups import TARGET_GROUPS
    crit = TARGET_GROUPS[groep].critical_strain
    loads, sq = _invoer(rapport)
    L = loads[:peildag + 1] + [loads[peildag]] * max_dagen
    S = None if sq is None else sq[:peildag + 1] + [sq[peildag]] * max_dagen
    tr = _sim(groep, L, S, pre)
    uit = {"nu": ZONE_VOLGORDE[_zone_i(tr[peildag + 1], crit)]}
    for naam, zi in (("gevaar", 2), ("nood", 3)):
        uit[naam] = None
        for k in range(0, max_dagen + 1):
            if _zone_i(tr[peildag + 1 + k], crit) >= zi:
                uit[naam] = k
                break
    return uit


def nawerking(rapport: dict, groep: str, pre, max_dagen: int = MAX_DAGEN) -> dict:
    """'Als het na de laatste dag koel wordt': belasting 0 en volledige nachtrust
    (slaapkwaliteit 1) na het venster. Telt de dagen tot Sigma weer in de veilige
    zone ligt. None = herstelt in het model niet vanzelf binnen max_dagen."""
    from pyrox_groups import TARGET_GROUPS
    crit = TARGET_GROUPS[groep].critical_strain
    loads, sq = _invoer(rapport)
    n = len(loads)
    L = loads + [0.0] * max_dagen
    S = None if sq is None else sq + [1.0] * max_dagen
    tr = np.asarray(_sim(groep, L, S, pre))
    dagen = None
    if _zone_i(tr[n], crit) == 0:
        dagen = 0
    else:
        for k in range(1, max_dagen + 1):
            if _zone_i(tr[n + k], crit) == 0:
                dagen = k
                break
    return {"dagen": dagen, "eind_zone": ZONE_VOLGORDE[_zone_i(tr[n], crit)],
            "verlenging": tr[n:], "blijft_kritiek": bool(tr[-1] >= 0.99 * crit)}


def zekerheid(weer, rapport: dict, groep: str, graden: float, pre) -> list:
    """Per dag: zone centraal, -Delta en +Delta (zoals plot_forecast_uncertainty)."""
    from pyrox_groups import TARGET_GROUPS
    crit = TARGET_GROUPS[groep].critical_strain
    if weer.forecast_start is None:
        c = rapport["groups"][groep]["cumulative_strain"]
        lo = hi = c
    else:
        c, lo, hi = onzekerheid(weer, rapport, groep, graden, pre)
    return [(_zone_i(c[i + 1], crit), _zone_i(lo[i + 1], crit), _zone_i(hi[i + 1], crit))
            for i in range(len(rapport["dates"]))]


def kalenderzin(weer, rapport: dict, groep: str, graden: float, pre) -> str:
    from pyrox_groups import TARGET_GROUPS
    zk = zekerheid(weer, rapport, groep, graden, pre)
    datums = rapport["dates"]
    fs = weer.forecast_start
    delen = []
    for zi in (1, 2, 3):
        c = next((i for i, z in enumerate(zk) if z[0] >= zi), None)
        lo = next((i for i, z in enumerate(zk) if z[1] >= zi), None)
        hi = next((i for i, z in enumerate(zk) if z[2] >= zi), None)
        w = ZONE_WOORD[ZONE_VOLGORDE[zi]]
        if c is not None:
            if fs is None or c < fs:
                woord = ""
            else:
                woord = " (zeker)" if (lo is not None and lo <= c) else " (waarschijnlijk)"
            delen.append(f"{w} vanaf {dagtekst(datums[c])}{woord}")
        elif hi is not None and fs is not None:
            delen.append(f"{w} mogelijk vanaf {dagtekst(datums[hi])}")
    naam = TARGET_GROUPS[groep].display_name
    if not delen:
        return f"{naam}: blijft veilig."
    boven = [i for i, z in enumerate(zk) if z[0] >= 1]
    t_m = (" — boven 'let op' t/m het einde van de periode" if boven and boven[-1] == len(zk) - 1
           else (f" — weer veilig vanaf {dagtekst(datums[boven[-1] + 1])}" if boven else ""))
    return f"{naam}: " + "; ".join(delen) + t_m + "."


def landschap(groep: str, R: float, n: int = 101):
    """Kantellandschap bij een aanhoudende belasting R. f(S) = verandering van
    Sigma in een dag vanaf begin-Sigma S (PyroxModel.simulate met initial_strain);
    hoogte V(S) = -som f dS: de bal rolt omlaag, de top is het kantelpunt."""
    from pyrox_model import PyroxModel
    from pyrox_groups import TARGET_GROUPS
    grp = TARGET_GROUPS[groep]
    S = np.linspace(0.0, 0.995 * grp.critical_strain, n)
    f = np.array([PyroxModel(grp).simulate([float(R)], pre_heatwave_heat_load=float(R),
                                           initial_strain=float(s))["cumulative_strain"][-1] - s for s in S])
    dS = S[1] - S[0]
    V = -np.concatenate([[0.0], np.cumsum(0.5 * (f[1:] + f[:-1]) * dS)])
    return S, f, V


ADVIES = {
    "safe": ["Geen extra maatregelen nodig; volg de verwachting."],
    "rest": ["Breng kwetsbare groepen in beeld (o.a. ouderen, alleenwonenden, zorginstellingen) en houd dagelijks contact.",
             "Zorg voor koele ruimtes overdag en zo koel mogelijke nachten; let op voldoende drinken.",
             "Schaal niet af zodra het koeler wordt: opgebouwde belasting werkt na (zie 'Nawerking')."],
}


def schrijf_briefing(pad: str, app) -> str:
    """Briefingkaart van een A4 (python-docx, staat in requirements.txt)."""
    import tempfile
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from pyrox_plots import ZONE_COLOURS
    r, weer = app.rapport, app.weer
    tekst, zone = app.kernboodschap
    zinnen, rijen, peil = app._briefing_teksten()
    with tempfile.TemporaryDirectory() as tmp:
        beelden = app._maak_beelden(tmp)
        doc = Document()
        sec = doc.sections[0]
        sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
        for k in ("left_margin", "right_margin"):
            setattr(sec, k, Cm(1.6))
        sec.top_margin, sec.bottom_margin = Cm(1.3), Cm(1.2)
        st = doc.styles["Normal"]
        st.font.name, st.font.size = "Calibri", Pt(10.5)
        st.paragraph_format.space_after = Pt(2)

        def alinea(t, grootte=10.5, vet=False, kleur=None, na=2):
            par = doc.add_paragraph()
            run = par.add_run(t)
            run.font.size, run.bold = Pt(grootte), vet
            if kleur:
                run.font.color.rgb = RGBColor.from_string(kleur)
            par.paragraph_format.space_after = Pt(na)
            return par

        alinea(f"Hittebriefing — {weer.city}", 20, True, na=0)
        d0, d1 = pd.Timestamp(r["dates"][0]), pd.Timestamp(r["dates"][-1])
        verw = (f" · verwachting vanaf {dagtekst(r['dates'][weer.forecast_start])}"
                if weer.forecast_start is not None and 0 <= weer.forecast_start < len(r["dates"]) else "")
        alinea(f"{dagtekst(d0)} {d0.year} t/m {dagtekst(d1)} {d1.year}{verw} · woonomgeving {app.v['route'].get()} · "
               f"gemaakt {pd.Timestamp.now():%d-%m-%Y %H:%M} · PYROX (research software)", 8.5, kleur="666666", na=6)
        par = alinea(tekst, 13, True, kleur="000000" if zone == "danger" else "FFFFFF", na=6)
        sh = OxmlElement("w:shd")
        sh.set(qn("w:val"), "clear")
        sh.set(qn("w:fill"), ZONE_COLOURS[zone].lstrip("#"))
        par._p.get_or_add_pPr().append(sh)
        doc.add_picture(beelden["kalender"], width=Cm(17.6))
        for z in zinnen:
            p_ = doc.add_paragraph(style="List Bullet")
            p_.add_run(z).font.size = Pt(9.5)
            p_.paragraph_format.space_after = Pt(0)
        alinea(f"Marge vanaf {dagtekst(r['dates'][peil])} (als het zo heet blijft) en herstel (als het daarna koel wordt)",
               10.5, True, na=2).paragraph_format.space_before = Pt(6)
        tab = doc.add_table(rows=1, cols=5)
        tab.style = "Light Grid Accent 1"
        for c, t in zip(tab.rows[0].cells, ("Groep", "Nu", "Tot gevaar", "Tot noodsituatie", "Herstel na koel weer")):
            c.text = t
        for rij in rijen:
            cells = tab.add_row().cells
            for c, t in zip(cells, rij):
                c.text = t
        for row in tab.rows:
            for c in row.cells:
                for p_ in c.paragraphs:
                    for run in p_.runs:
                        run.font.size = Pt(9)
        doc.add_picture(beelden["emmers"], width=Cm(15.5))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        alinea("Wat te doen", 10.5, True, na=1)
        for a in ADVIES["safe" if zone == "safe" else "rest"]:
            p_ = doc.add_paragraph(style="List Bullet")
            p_.add_run(a).font.size = Pt(9.5)
            p_.paragraph_format.space_after = Pt(0)
        alinea("Standaardadviezen; volg het lokale hitteplan. Marge = de warmtebelasting van de peildag houdt aan; herstel = "
               "na de laatste dag geen warmtebelasting en volledige nachtrust. '?' = uitkomst hangt af van de verwachting "
               f"(±{nl_(app.onz)} °C). PYROX is research software: de warmtebelasting is gekalibreerd op Parijs 2003 en 16 van "
               "de 19 groepen zijn geëxtrapoleerd.", 7.5, kleur="666666", na=0).paragraph_format.space_before = Pt(4)
        doc.save(pad)
    return pad


def nl_(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def _rapport_proces(event_name, rapport, stam, word, aanhangsel=""):
    """Apart proces: generate_pyrox_report schakelt matplotlib naar Agg."""
    import sys
    if str(HIER) not in sys.path:
        sys.path.insert(0, str(HIER))
    os.chdir(HIER)
    from generate_pyrox_report import generate_pyrox_report
    md = stam + ".md"
    tekst = generate_pyrox_report(event_name, rapport, md)
    if aanhangsel:
        eind = "*Einde rapport.*"
        tekst = (tekst.replace(eind, aanhangsel.rstrip() + "\n\n" + eind, 1) if eind in tekst
                 else tekst.rstrip() + "\n\n" + aanhangsel)
        Path(md).write_text(tekst, encoding="utf-8")
    uit = [md]
    if word:
        try:
            from report_to_docx import export_report_docx
            export_report_docx(tekst, stam + ".docx", report_kind="facts", event_name=event_name)
            uit.append(stam + ".docx")
        except Exception as e:
            uit.append(f"Word-export lukte niet ({e}); het Markdown-rapport staat er wel.")
    return uit


# =============================================================================
# 2. GEBRUIKERSINTERFACE
# =============================================================================
def _start_ui(na_start=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import tkinter.font as tkfont
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.dates as mdates
    import matplotlib.patches
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch
    import Thermopoulos_Data_Engine as de
    from pyrox_groups import TARGET_GROUPS, PAPER_PROTOTYPES
    import ui_gemeen as ug
    from pyrox_plots import ZONE_COLOURS, _strain_zone
    from pyrox_model import PyroxModel, equilibrium_strain
    from thermopoulos_loader import NIGHT_COMFORT_TEMP, NIGHT_SEVERE_TEMP

    LETTER = 12
    matplotlib.rcParams.update({"font.size": 11, "axes.titlesize": 12, "axes.titleweight": "bold",
                                "axes.grid": True, "grid.alpha": 0.3, "legend.fontsize": 9})
    ZONE_NL = {"safe": "veilig", "caution": "let op", "danger": "gevaar", "emergency": "noodsituatie"}
    ZONES = ["safe", "caution", "danger", "emergency"]
    VOLGORDE = list(TARGET_GROUPS)           # resilient -> kwetsbaar (zoals pyrox_groups)

    def nl(x, d=2):
        return f"{x:.{d}f}".replace(".", ",")

    class App:
        def __init__(self, root):
            self.root = root
            root.title("PYROX · meerdaagse hittebelasting van bevolkingsgroepen  (research software)")
            for naam in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont"):
                try:
                    tkfont.nametofont(naam).configure(size=LETTER)
                except tk.TclError:
                    pass
            st = ttk.Style()
            st.configure("TLabelframe.Label", font=("TkDefaultFont", LETTER, "bold"))
            st.configure("P.Treeview", font=("TkDefaultFont", LETTER - 1), rowheight=ug.px(self.root, int(LETTER * 2.0)))
            st.configure("P.Treeview.Heading", font=("TkDefaultFont", LETTER - 1, "bold"))
            bw, bh = root.winfo_screenwidth(), root.winfo_screenheight()
            root.geometry(f"{min(1800, bw - 40)}x{min(1040, bh - 80)}+10+10")
            ug.maximaliseer(root)
            self.lader = WeerLader()
            self.q = queue.Queue()
            self.kandidaten = []
            self.weer: Optional[Weer] = None
            self.rapport = None
            self._plan = None
            self._laad_gen = 0
            self.rpool = ProcessPoolExecutor(max_workers=1)
            self._bouw()
            self._poll()
            root.protocol("WM_DELETE_WINDOW", self._sluit)

        # ------------------------------------------------------------ opbouw
        def _bouw(self):
            links = ttk.Frame(self.root, padding=6)
            links.pack(side="left", fill="y")
            cv = tk.Canvas(links, width=ug.px(self.root, 470), highlightthickness=0)
            sb = ttk.Scrollbar(links, orient="vertical", command=cv.yview)
            self.form = ttk.Frame(cv)
            self.form.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
            cv.create_window((0, 0), window=self.form, anchor="nw")
            cv.configure(yscrollcommand=sb.set)
            cv.pack(side="left", fill="y")
            sb.pack(side="left", fill="y")
            cv.bind_all("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))
            cv.bind_all("<Button-4>", lambda e: cv.yview_scroll(-2, "units"))
            cv.bind_all("<Button-5>", lambda e: cv.yview_scroll(2, "units"))
            self.v, self.w = {}, {}

            ug.invoer_legenda(self.form, LETTER)
            r = self._sectie("Weer", "verplicht")
            self._keuze(r, "bron", "Weerbron", ["online (Open-Meteo)", "Data Engine-bestand"],
                        "online (Open-Meteo)", weer=True)
            rij = self._rij(r, "Bestand")
            self.v["excel"] = tk.StringVar(value="")
            ttk.Entry(rij, textvariable=self.v["excel"], width=14).pack(side="left")
            ttk.Button(rij, text="Kies…", command=self._kies_excel, width=6).pack(side="left", padx=3)
            self._keuze(r, "blad", "Blad", [COMBI], COMBI, weer=True, breed=36)
            rij = self._rij(r, "Plaats")
            self.v["plaats"] = tk.StringVar(value="Schagen")
            pe = ttk.Entry(rij, textvariable=self.v["plaats"], width=14)
            pe.pack(side="left")
            pe.bind("<Return>", lambda e: self._zoek_plaats())
            ttk.Button(rij, text="Zoek", command=self._zoek_plaats, width=6).pack(side="left", padx=3)
            self.v["kandidaat"] = tk.StringVar(value="")
            self.cb_kand = ttk.Combobox(r, textvariable=self.v["kandidaat"], state="readonly", width=40)
            self.cb_kand.pack(fill="x", padx=4, pady=2)
            self.cb_kand.bind("<<ComboboxSelected>>", lambda e: self._weer_gewijzigd())
            self._keuze(r, "periode", "Periode (online)", ["verwachting met verleden", "historische periode"],
                        "verwachting met verleden", weer=True)
            self._tekst(r, "n_verl", "Verleden (dagen)", "14", weer=True)
            self._tekst(r, "n_verw", "Verwachting (dagen)", "7", weer=True)
            vandaag = pd.Timestamp.now().normalize()
            self._tekst(r, "van", "Van (historisch)", (vandaag - pd.Timedelta(days=30)).strftime("%Y-%m-%d"),
                        weer=True)
            self._tekst(r, "tot", "Tot (historisch)", (vandaag - pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
                        weer=True)
            self._keuze(r, "route", "Woonomgeving", ["stad", "platteland"], "stad", weer=True)

            r = self._sectie("Groepen", "verplicht", "Kies minstens één groep. Volgorde: van "
                             "veerkrachtig naar kwetsbaar, zoals in pyrox_groups.")
            knop = ttk.Frame(r)
            knop.pack(fill="x", pady=(0, 4))
            ttk.Label(knop, text="Snel kiezen:").pack(side="left", padx=(0, 4))
            ttk.Button(knop, text="Paper-groepen", command=lambda: self._zet_groepen(PAPER_PROTOTYPES)).pack(side="left")
            ttk.Button(knop, text="Alle", command=lambda: self._zet_groepen(VOLGORDE)).pack(side="left", padx=3)
            ttk.Button(knop, text="Geen", command=lambda: self._zet_groepen([])).pack(side="left")
            for status, kop, uitleg in (
                    ("paper", "Uit het paper", "gekalibreerd; de best onderbouwde groepen"),
                    ("extrapolated", "Geëxtrapoleerd", "afgeleid van de paper-groepen; minder zeker")):
                ttk.Label(r, text=kop, font=("TkDefaultFont", LETTER, "bold")).pack(anchor="w", pady=(4, 0))
                ttk.Label(r, text=uitleg, foreground="#777", font=("TkDefaultFont", LETTER - 2)).pack(anchor="w")
                for g in VOLGORDE:
                    grp = TARGET_GROUPS[g]
                    if (grp.evidence_status == "paper") != (status == "paper"):
                        continue
                    self.v["g_" + g] = tk.BooleanVar(value=g in PAPER_PROTOTYPES)
                    ttk.Checkbutton(r, text=grp.display_name, variable=self.v["g_" + g]).pack(anchor="w", padx=(10, 0))
                    self.v["g_" + g].trace_add("write", lambda *a: self._gewijzigd())

            r = self._sectie("Model", "model", "Standaard van de suite. 'Groep voor detail' kiest alleen "
                             "welke groep de tabbladen Terugkoppeling, Regimes en Uitleg tonen.")
            self.v["nacht"] = tk.BooleanVar(value=True)
            ttk.Checkbutton(r, text="Nachtelijk herstel (warme nachten remmen herstel)",
                            variable=self.v["nacht"]).pack(anchor="w")
            self.v["nacht"].trace_add("write", lambda *a: self._gewijzigd())
            self._tekst(r, "pre", "Belasting vóór hittegolf", "", hint="leeg: eerste dag")
            self._tekst(r, "onz", "Onzekerheid verwachting ±°C", "2")
            self._keuze(r, "fb", "Groep voor detail", [TARGET_GROUPS[g].display_name for g in VOLGORDE],
                        TARGET_GROUPS["very_elderly_85plus"].display_name, breed=36)
            r = self._sectie("Uitvoer", "actie")
            rij = ttk.Frame(r)
            rij.pack(fill="x", pady=4)
            ttk.Button(rij, text="Excel-export", command=self._export).pack(side="left", padx=2)
            ttk.Button(rij, text="Rapport (Word)", command=self._rapport).pack(side="left", padx=2)
            ttk.Button(rij, text="Briefing (Word)", command=self._briefing).pack(side="left", padx=2)
            ttk.Label(r, text="Rapport: volledig technisch verslag. Briefing: één A4 voor "
                              "veiligheidsfunctionarissen.", foreground="#555", wraplength=430,
                      font=("TkDefaultFont", LETTER - 2)).pack(anchor="w")

            # ---- rechts
            rechts = ttk.Frame(self.root, padding=(4, 6))
            rechts.pack(side="left", fill="both", expand=True)
            boven = ttk.Frame(rechts)
            boven.pack(fill="x")
            self.lbl_kop = tk.Label(boven, text="  —  ", font=("TkDefaultFont", LETTER + 2, "bold"),
                                    bg="#dddddd", padx=10, pady=4)
            self.lbl_kop.pack(side="left")
            ttk.Button(boven, text="Briefing voor niet-specialisten →",
                       command=lambda: self.nb.select(self.tab["br"]["f"])).pack(side="right", padx=4)
            self.lbl_status = ttk.Label(boven, text="", font=("TkDefaultFont", LETTER - 2), wraplength=420,
                                        justify="left")
            self.lbl_status.pack(side="left", padx=10)
            self.tegels = ug.Tegels(rechts, LETTER)
            self.tegels.pack(fill="x", pady=(4, 0))
            self.herkomst = ug.Herkomst(rechts, LETTER)
            self.herkomst.pack(side="bottom", fill="x", pady=(3, 0))
            nb = ttk.Notebook(rechts)
            nb.pack(fill="both", expand=True, pady=(4, 0))
            self.nb = nb
            self.tab = {}
            UITLEG = {
                "ov": "Startpunt. Temperatuur, dagelijkse warmtebelasting met nachtelijk herstel, en de opgebouwde "
                      "belasting per groep als percentage van de eigen kritieke grens. Elke groep is een ensemble van "
                      "41 leden die verschillen in hittebestendigheid; de lijn is het gemiddelde. De tabel geeft per "
                      "groep de eerste dag in elke zone en het grootste aandeel leden in de noodsituatie.",
                "hm": "Alle gekozen groepen in één beeld: per dag de zone. Handig om te zien welke groepen het "
                      "eerst en het langst in gevaar komen.",
                "fb": "Voor onderzoek. Laat voor het typische (mediane) lid van één groep zien hoe belasting en "
                      "herstel elkaar dag na dag versterken (de terugkoppeling in het model).",
                "onz": "Hoe gevoelig is de uitkomst voor fouten in de weersverwachting? De verwachte temperaturen "
                       "worden met ± de ingestelde marge verschoven en opnieuw doorgerekend.",
                "reg": "Voor onderzoek. Bij welke dagelijkse belasting blijft het typische (mediane) lid van een "
                       "groep in evenwicht, en vanaf welke belasting loopt de opbouw door (kantelpunt)? Andere leden "
                       "van de groep kantelen eerder of later.",
                "br": "Voor veiligheidsfunctionarissen en organisatoren: kalender, marge tot de volgende zone en "
                      "nawerking na de hittegolf, in gewone taal. Zelfde inhoud als de Briefing (Word).",
                "em": "Uitleg en presentatie. Elke groep als emmer die volloopt met hittebelasting en 's nachts "
                      "deels leegloopt. Met ▶ afspelen loopt de hittegolf dag voor dag.",
                "kp": "Uitleg en presentatie. Het kantelpunt als landschap voor het typische (mediane) lid: een bal "
                      "die terugrolt (herstel) of over de rand gaat (doorlopende opbouw).",
            }
            for k, titel in (("ov", "Overzicht"), ("hm", "Heatmap"), ("fb", "Terugkoppeling"),
                             ("onz", "Onzekerheid verwachting"), ("reg", "Regimes"), ("br", "Briefing"),
                             ("em", "Emmers"), ("kp", "Uitleg: kantelpunt")):
                f = ttk.Frame(nb)
                nb.add(f, text=titel)
                ug.tab_uitleg(f, UITLEG[k], LETTER)
                ink = ug.Inklap(f, "Toelichting bij deze grafiek (bron en rekenwijze)", LETTER)
                ink.pack(side="bottom", fill="x", pady=(0, 2))
                lbl = ttk.Label(ink.binnen, text="", font=("TkDefaultFont", LETTER - 1), wraplength=1250,
                                justify="left")
                lbl.pack(fill="x", padx=8, pady=2)
                tv = None
                if k == "ov":
                    kol = ("groep", "status", "kritiek", "piek", "piek_pct", "aandeel", "letop", "gevaar", "nood")
                    kopt = ("groep", "evidentie", "kritieke grens", "piek Σ", "piek (% kritiek)",
                            "max. deel in nood", "let op (50 %)", "gevaar (75 %)", "noodsituatie (90 %)")
                    tv = ttk.Treeview(f, columns=kol, show="headings", height=3, style="P.Treeview")
                    for c, t in zip(kol, kopt):
                        tv.heading(c, text=t)
                        tv.column(c, width=ug.px(self.root, 260) if c == "groep" else ug.px(self.root, 105),
                                  anchor="w" if c == "groep" else "center")
                    tv.pack(side="bottom", fill="x", padx=6)
                sc = None
                if k in ("br", "em", "kp"):
                    balk = ttk.Frame(f)
                    balk.pack(side="bottom", fill="x", padx=8)
                    ttk.Label(balk, text={"br": "Peildag (marge):", "em": "Dag:", "kp": "Dag:"}[k]).pack(side="left")
                    self.v["dag_" + k] = tk.IntVar(value=0)
                    sc = tk.Scale(balk, from_=0, to=1, orient="horizontal", showvalue=False, length=700,
                                  variable=self.v["dag_" + k], command=lambda _v, kk=k: self._dag_gewijzigd(kk))
                    sc.pack(side="left", padx=6)
                    lbd = ttk.Label(balk, text="", width=14)
                    lbd.pack(side="left")
                    self.v["lbl_dag_" + k] = lbd
                    if k == "em":
                        self.knop_af = ttk.Button(balk, text="▶ afspelen", command=self._afspelen)
                        self.knop_af.pack(side="left", padx=8)
                    if k == "kp":
                        self.v["kp_eigen"] = tk.BooleanVar(value=False)
                        ttk.Checkbutton(balk, text="eigen belasting:", variable=self.v["kp_eigen"],
                                        command=lambda: self._dag_gewijzigd("kp")).pack(side="left", padx=(16, 2))
                        self.v["kp_last"] = tk.DoubleVar(value=1.0)
                        tk.Scale(balk, from_=0.1, to=2.5, resolution=0.02, orient="horizontal", length=260,
                                 variable=self.v["kp_last"], command=lambda _v: self.v["kp_eigen"].get()
                                 and self._dag_gewijzigd("kp")).pack(side="left")
                fig = Figure(figsize=(12, 6.5 if k in ("ov", "br") else 7.5), dpi=96, constrained_layout=True)
                canv = FigureCanvasTkAgg(fig, master=f)
                canv.get_tk_widget().pack(side="top", fill="both", expand=True)
                self.tab[k] = {"fig": fig, "cv": canv, "lbl": lbl, "tv": tv, "sc": sc, "f": f}
            self._spelen = None
            self.root.after(300, self._zoek_plaats)

        def _sectie(self, titel, soort="verplicht", uitleg=""):
            return ug.sectie(self.form, titel, soort, LETTER, uitleg)

        def _rij(self, ouder, label):
            rij = ttk.Frame(ouder)
            rij.pack(fill="x", pady=1)
            ttk.Label(rij, text=label, width=24).pack(side="left")
            return rij

        def _tekst(self, ouder, k, label, std, hint="", weer=False):
            rij = self._rij(ouder, label)
            self.v[k] = tk.StringVar(value=std)
            e = ttk.Entry(rij, textvariable=self.v[k], width=11)
            e.pack(side="left")
            self.w[k] = e
            if hint:
                ttk.Label(rij, text=hint, foreground="#777").pack(side="left", padx=4)
            self.v[k].trace_add("write", lambda *a: (self._weer_gewijzigd() if weer else self._gewijzigd()))

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
            self.v[k].trace_add("write", lambda *a: (self._weer_gewijzigd() if weer else self._gewijzigd()))

        # ------------------------------------------------------- invoer
        def _f(self, k, opt=False):
            s = self.v[k].get().strip().replace(",", ".")
            if s == "":
                if opt:
                    return None
                raise ValueError(f"'{k}' is leeg")
            return float(s)

        def _groepen(self):
            return [g for g in VOLGORDE if self.v["g_" + g].get()]

        def _fb_groep(self):
            for g in VOLGORDE:
                if TARGET_GROUPS[g].display_name == self.v["fb"].get():
                    return g
            return "very_elderly_85plus"

        def _kandidaat(self):
            i = self.cb_kand.current()
            return self.kandidaten[i] if 0 <= i < len(self.kandidaten) else None

        def _zet_groepen(self, lijst):
            for g in VOLGORDE:
                self.v["g_" + g].set(g in lijst)

        # ---------------------------------------------------- gebeurtenissen
        def _gewijzigd(self, vertraging=300):
            if self._plan is not None:
                self.root.after_cancel(self._plan)
            self._plan = self.root.after(vertraging, self._herbereken)

        def _weer_gewijzigd(self):
            excel = self.v["bron"].get().startswith("Data")
            online_hist = self.v["periode"].get().startswith("hist")
            for k in ("n_verl", "n_verw"):
                aan = (excel and self.v["blad"].get() == COMBI) or (not excel and not online_hist)
                self.w[k].state(["!disabled"] if aan else ["disabled"])
            for k in ("van", "tot"):
                self.w[k].state(["!disabled"] if (not excel and online_hist) else ["disabled"])
            self.w["periode"].state(["disabled"] if excel else ["!disabled"])
            self.w["blad"].state(["!disabled"] if excel else ["disabled"])
            if self._plan is not None:
                self.root.after_cancel(self._plan)
            self._plan = self.root.after(500, self._laad_weer)

        def _zoek_plaats(self):
            naam = self.v["plaats"].get().strip()
            if not naam or self.v["bron"].get().startswith("Data"):
                self._weer_gewijzigd()
                return
            self.lbl_status.config(text=f"Plaats zoeken: {naam} …")

            def werk():
                try:
                    self.q.put(("kandidaten", de.geocode_city_candidates(naam)))
                except Exception as ex:
                    self.q.put(("fout", f"Plaats zoeken mislukt: {ex}"))
            threading.Thread(target=werk, daemon=True).start()

        def _kies_excel(self):
            p = filedialog.askopenfilename(title="Data Engine-bestand", initialdir=str(HIER),
                                           filetypes=[("Excel", "*.xlsx"), ("Alle", "*.*")])
            if not p:
                return
            try:
                bl = WeerLader.bladen(p)
            except Exception as ex:
                return self._fout(f"Bestand niet leesbaar: {ex}")
            self.w["blad"]["values"] = bl
            self.v["blad"].set(bl[0])
            self.v["excel"].set(p)
            self.v["bron"].set("Data Engine-bestand")

        # ---------------------------------------------------------- laden
        def _laad_weer(self):
            self._plan = None
            excel = self.v["bron"].get().startswith("Data")
            route = self.v["route"].get()
            try:
                nv, nw = int(self._f("n_verl")), int(self._f("n_verw"))
                if not (1 <= nv <= 60 and 1 <= nw <= 16):
                    raise ValueError("verleden 1–60 dagen, verwachting 1–16 dagen")
            except Exception as ex:
                return self._fout(f"Invoer: {ex}")
            self._laad_gen += 1
            gen = self._laad_gen
            if excel:
                pad, blad = self.v["excel"].get().strip(), self.v["blad"].get()
                if not pad:
                    return self._fout("Kies een Data Engine-bestand.")

                def werk():
                    return self.lader.excel(pad, blad, route, nv, nw)
            else:
                kand = self._kandidaat()
                if kand is None:
                    return self._fout("Kies eerst een plaats (Zoek).")
                if self.v["periode"].get().startswith("hist"):
                    try:
                        van = pd.Timestamp(self.v["van"].get().strip()).strftime("%Y-%m-%d")
                        tot = pd.Timestamp(self.v["tot"].get().strip()).strftime("%Y-%m-%d")
                        if pd.Timestamp(tot) <= pd.Timestamp(van):
                            raise ValueError("'tot' moet na 'van' liggen")
                    except Exception as ex:
                        return self._fout(f"Periode: {ex}")

                    def werk():
                        return self.lader.online_historisch(kand, route, van, tot)
                else:
                    def werk():
                        return self.lader.online_verwachting(kand, route, nv, nw)
            self.lbl_status.config(text="Weer laden …")

            def draad():
                try:
                    self.q.put(("weer", gen, werk()))
                except Exception as ex:
                    self.q.put(("fout", f"Weer: {ex}"))
            threading.Thread(target=draad, daemon=True).start()

        def _herbereken(self):
            self._plan = None
            if self.weer is None:
                return
            groepen = self._groepen()
            if not groepen:
                return self._fout("Kies minstens één groep.")
            try:
                pre = self._f("pre", True)
                onz = self._f("onz")
                if pre is not None and not 0 <= pre <= 5:
                    raise ValueError("belasting vóór hittegolf: 0 t/m 5")
            except Exception as ex:
                return self._fout(f"Invoer: {ex}")
            try:
                self.rapport = bereken(self.weer, groepen, self.v["nacht"].get(), pre)
                self.pre, self.onz = pre, onz
            except Exception as ex:
                return self._fout(f"PYROX: {ex}\n{traceback.format_exc()}")
            self._teken_alles()
            self.lbl_status.config(text=f"{self.weer.label} — {len(self.weer.daily)} dagen, {len(groepen)} groepen")

        def _poll(self):
            try:
                while True:
                    m = self.q.get_nowait()
                    if m[0] == "kandidaten":
                        self.kandidaten = m[1]
                        self.cb_kand["values"] = [
                            f"{k.get('name')}, {k.get('admin1', '')} ({k.get('country_code', '')})"
                            f" – {k.get('population', 0) or 0:,} inw.".replace(",", ".")
                            for k in self.kandidaten]
                        if self.kandidaten:
                            self.cb_kand.current(0)
                        self._weer_gewijzigd()
                    elif m[0] == "weer":
                        if m[1] == self._laad_gen:
                            self.weer = m[2]
                            self._herbereken()
                    elif m[0] == "rapport":
                        self.lbl_status.config(text="Rapport klaar")
                        messagebox.showinfo("PYROX-rapport", "\n".join(m[1]))
                    elif m[0] == "fout":
                        self._fout(m[1])
            except queue.Empty:
                pass
            except Exception as ex:
                self._fout(f"Interne fout: {ex}\n{traceback.format_exc()}")
            self.root.after(250, self._poll)

        # --------------------------------------------------------- tekenen
        def _datums(self):
            return [pd.Timestamp(d) for d in self.rapport["dates"]]

        def _x(self, ax):
            n = len(self.rapport["dates"])
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, int(np.ceil(n / 12)))))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m"))

        def _scheiding(self, ax, x, tekst=True):
            fs = self.weer.forecast_start
            if fs is not None and 0 < fs < len(x):
                grens = x[fs] - pd.Timedelta(hours=12)
                ax.axvline(grens, color="#333", lw=1.4, alpha=0.7)
                if tekst:
                    ax.text(grens, 0.03, " verwachting →", transform=ax.get_xaxis_transform(), va="bottom",
                            ha="left", fontsize=9, color="#333",
                            bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))
                    ax.text(grens, 0.03, "← verleden ", transform=ax.get_xaxis_transform(), va="bottom",
                            ha="right", fontsize=9, color="#333",
                            bbox=dict(fc="white", ec="none", alpha=0.7, pad=1))

        def _zonelijnen(self, ax, rechts=True):
            for frac, z in ((50, "caution"), (75, "danger"), (90, "emergency")):
                ax.axhline(frac, color=ZONE_COLOURS[z], lw=1, ls="--", alpha=0.8)
                if rechts:
                    ax.text(1.0, frac, f" {ZONE_NL[z]}", transform=ax.get_yaxis_transform(), va="center",
                            ha="left", fontsize=9, color=ZONE_COLOURS[z])

        def _dag(self, idx):
            """Index in de Sigma-reeks (0 = beginwaarde) -> datum."""
            if idx is None:
                return "–"
            if idx == 0:
                return "al bij de start"
            return pd.Timestamp(self.rapport["dates"][idx - 1]).strftime("%d-%m-%Y")

        def _teken_alles(self):
            self._teken_overzicht()
            self._teken_heatmap()
            self._teken_fb()
            self._teken_onz()
            self._teken_reg()
            self._zet_dagschalen()
            self._teken_briefing()
            self._teken_emmers()
            self._teken_kp()
            self._kop()

        def _kop(self):
            r = self.rapport
            slechtst, wie, wanneer = "safe", None, None
            for g, res in r["groups"].items():
                traj = res["cumulative_strain"][1:]
                for i, v in enumerate(traj):
                    z = _strain_zone(v, res["critical_strain"])
                    if ZONES.index(z) > ZONES.index(slechtst) or (
                            z == slechtst and z != "safe" and wanneer is not None and i < wanneer):
                        slechtst, wie, wanneer = z, g, i
            if wie is None:
                tekst = "  Alle gekozen groepen blijven veilig  "
            else:
                tekst = (f"  Zwaarste zone: {ZONE_NL[slechtst].upper()} — {TARGET_GROUPS[wie].display_name}, "
                         f"vanaf {pd.Timestamp(r['dates'][wanneer]).strftime('%d-%m-%Y')}  ")
            self.kernboodschap = (tekst.strip(), slechtst)
            self.lbl_kop.config(text=tekst, bg=ZONE_COLOURS[slechtst],
                                fg="black" if slechtst == "danger" else "white")
            self._toon_waarschuwing(slechtst, wie, wanneer)
            self._toon_herkomst()

        def _soort_dag(self, i):
            """i = index in rapport['dates'] -> ('verleden'|'verwachting', uitleg)."""
            fs = self.weer.forecast_start
            if fs is not None and i >= fs:
                return "verwachting", "modelprojectie op de weersverwachting"
            return "verleden", "berekend uit het weer van die dag (ERA5 of bestand)"

        def _toon_waarschuwing(self, slechtst, wie, wanneer):
            r = self.rapport
            if wie is None:
                piek = max(r["groups"].items(),
                           key=lambda kv: kv[1]["peak_strain"] / kv[1]["critical_strain"])
                g, res = piek
                self.tegels.zet([
                    dict(titel="Zwaarste zone", waarde="veilig", sub="alle gekozen groepen onder 50 % van hun "
                                                                   "kritieke grens", kleur=ZONE_COLOURS["safe"]),
                    dict(titel="Hoogste groep", waarde=f"{100 * res['peak_strain'] / res['critical_strain']:.0f} %",
                         sub=TARGET_GROUPS[g].display_name, kleur="#5d6d7e"),
                ], "Geen enkele gekozen groep bereikt de zone 'let op' (50 % van de eigen kritieke grens).")
                return
            res = r["groups"][wie]
            grp = TARGET_GROUPS[wie]
            crit = res["critical_strain"]
            grens = {"caution": 50, "danger": 75, "emergency": 90}[slechtst]
            soort, soort_uitleg = self._soort_dag(wanneer)
            datum = pd.Timestamp(r["dates"][wanneer]).strftime("%d-%m-%Y")
            pct = 100 * res["peak_strain"] / crit
            traj = list(res["cumulative_strain"][1:])
            ipiek = int(np.argmax(traj))
            nood = res["emergency_day"]
            if nood is None:
                fr = float(np.max(res["fraction_emergency"])) if "fraction_emergency" in res else 0.0
                nood_w = "niet bereikt"
                nood_s = ("door het groepsgemiddelde; wel " f"{100 * fr:.0f} % van de leden"
                          if fr > 0 else "binnen deze periode")
            else:
                nood_w = self._dag(nood)
                nood_s = self._soort_dag(nood - 1)[0] if nood > 0 else "bij de start"
            items = [
                dict(titel="Bepalende groep", waarde=grp.display_name,
                     sub=("uit het paper (gekalibreerd)" if grp.evidence_status == "paper"
                          else "geëxtrapoleerd (minder zeker)"),
                     kleur=ZONE_COLOURS[slechtst]),
                dict(titel=f"Overschreden grens: {ZONE_NL[slechtst]}", waarde=f"≥ {grens} %",
                     sub=f"van de eigen kritieke grens (Σ_crit = {nl(crit)})", kleur=ZONE_COLOURS[slechtst]),
                dict(titel="Vanaf", waarde=datum, sub=f"{soort}: {soort_uitleg}",
                     kleur="#b9770e" if soort == "verwachting" else "#117a65"),
                dict(titel="Piek (gemiddelde van de groep)", waarde=f"{pct:.0f} %",
                     sub=f"op {pd.Timestamp(r['dates'][ipiek]).strftime('%d-%m-%Y')} "
                         f"({self._soort_dag(ipiek)[0]})"
                         + (f"; max. {100 * float(np.max(res['fraction_emergency'])):.0f} % van de leden in nood"
                            if "fraction_emergency" in res else ""), kleur="#5d6d7e"),
            ]
            if slechtst == "emergency":
                items.append(dict(titel="Opbouw daarvoor", waarde=f"let op {self._dag(res['caution_day'])}",
                                  sub=f"gevaar {self._dag(res['danger_day'])}", kleur=ZONE_COLOURS["danger"]))
            else:
                items.append(dict(titel="Noodsituatie (90 %)", waarde=nood_w, sub=nood_s,
                                  kleur=ZONE_COLOURS["emergency"] if nood is not None else "#5d6d7e"))
            uitleg = ("De kleur bovenaan volgt de groep die de zwaarste zone het eerst bereikt. Zones = 50 / 75 / 90 % "
                      "van de eigen kritieke grens van die groep.")
            self.tegels.zet(items, uitleg)

        def _toon_herkomst(self):
            w = self.weer
            fs = w.forecast_start
            n = len(self.rapport["dates"])
            if fs is not None and 0 < fs < n:
                st, st_t = "gemengd", "berekening · verleden + verwachting"
            elif fs == 0:
                st, st_t = "prognose", "berekening · verwachting"
            else:
                st, st_t = "historisch", "berekening · historische periode"
            self.herkomst.zet(
                f"{w.label}; {w.city}, woonomgeving {self.v['route'].get()}", st, status_tekst=st_t,
                extra="model: PYROX (run_pyrox.assess_population), nachtelijk herstel "
                      + ("aan" if self.v["nacht"].get() else "uit"),
                niet="een waargenomen gezondheidseffect of een officiële hittewaarschuwing.")

        def _teken_overzicht(self):
            t = self.tab["ov"]
            r, d = self.rapport, self.weer.daily
            x = self._datums()
            fig = t["fig"]
            fig.clear()
            a1, a2, a3 = fig.add_subplot(3, 1, 1), fig.add_subplot(3, 1, 2), fig.add_subplot(3, 1, 3)
            a1.plot(x, d["t_air_max"], "o-", color="#c0392b", lw=2, ms=4, label="Tmax (overdag)")
            a1.plot(x, d["t_air_min"], "o-", color="#2471a3", lw=1.5, ms=3, label="Tmin (kalenderdag)")
            if r.get("t_night_min") is not None:
                a1.plot(x, r["t_night_min"], "s--", color="#7d3c98", lw=1.5, ms=3, label="minimum nacht erna")
            a1.axhline(NIGHT_COMFORT_TEMP, color="#7d3c98", lw=0.8, ls=":")
            a1.axhline(NIGHT_SEVERE_TEMP, color="#7d3c98", lw=0.8, ls=":")
            a1.set_ylabel("°C")
            a1.set_title("Temperatuur (stad met UHI)" if self.v["route"].get() == "stad" else "Temperatuur (platteland)")
            a1.legend(loc="upper left", ncol=3)
            a2.bar(x, r["heat_loads"], width=0.8, color="#bbbbbb", label="warmtebelasting")
            a2.set_ylabel("warmtebelasting")
            a2b = a2.twinx()
            a2b.plot(x, r["sleep_quality"], "o-", color="#7d3c98", lw=1.5, ms=3, label="slaapkwaliteit")
            a2b.set_ylim(0, 1.05)
            a2b.set_ylabel("slaapkwaliteit", color="#7d3c98")
            a2b.grid(False)
            a2.set_title("Dagelijkse warmtebelasting en nachtelijk herstel"
                         + ("" if r.get("nocturnal_recovery") else "  (nachtelijk herstel UIT: volledig herstel)"))
            kleuren = matplotlib.colormaps["tab10"].colors
            for i, (g, res) in enumerate(r["groups"].items()):
                pct = 100 * np.asarray(res["cumulative_strain"][1:]) / res["critical_strain"]
                a3.plot(x, pct, "o-", lw=2, ms=3, color=kleuren[i % 10], label=TARGET_GROUPS[g].display_name)
            self._zonelijnen(a3)
            a3.set_ylim(0, 105)
            a3.set_ylabel("Σ (% van kritieke grens)")
            a3.set_title("Opgebouwde hittebelasting per groep")
            a3.legend(loc="upper left", fontsize=8, ncol=2)
            for a in (a1, a2, a3):
                self._x(a)
                self._scheiding(a, x, tekst=(a is a1))
            t["cv"].draw_idle()
            tv = t["tv"]
            tv.delete(*tv.get_children())
            tv.configure(height=min(max(len(r["groups"]), 1), 6))
            for g, res in r["groups"].items():
                grp = res["group"]
                tv.insert("", "end", values=(
                    grp.display_name, grp.evidence_status, nl(res["critical_strain"]), nl(res["peak_strain"], 3),
                    f"{100 * res['peak_strain'] / res['critical_strain']:.0f} %",
                    (f"{100 * float(np.max(res['fraction_emergency'])):.0f} %" if "fraction_emergency" in res else "–"),
                    self._dag(res["caution_day"]), self._dag(res["danger_day"]), self._dag(res["emergency_day"])))
            t["lbl"].config(text=(
                "Bron: run_pyrox.assess_population (PyroxPopulation: per groep 41 leden met verschillende hittebestendigheid, "
                "CV 0,30; lijn = gemiddelde; 'max. deel in nood' = grootste aandeel leden ≥ 90 % van de kritieke grens). "
                "Warmtebelasting per dag = (gevoelstemperatuur bij "
                "Tmax − 22 °C) × 0,10 (thermopoulos_loader; modelkeuze, gekalibreerd op Parijs 2003). Slaapkwaliteit uit het "
                "minimum van de nacht na elke dag: 1,0 tot 18 °C, 0,4 vanaf 26 °C (stippellijnen). Σ is hier weergegeven als "
                "percentage van de eigen kritieke grens van de groep; zones 50/75/90 % zoals pyrox_plots. Datum in de tabel = "
                "eerste dag waarop de zone na het nachtelijk herstel van die dag bereikt is. Bij een gecombineerd venster kent de "
                "laatste verleden-dag geen nachtminimum (die nacht valt in het verwachtingsblad); de suite neemt dan de "
                "slaapkwaliteit van de nacht ervoor over."))

        def _teken_heatmap(self):
            t = self.tab["hm"]
            r = self.rapport
            fig = t["fig"]
            fig.clear()
            ax = fig.add_subplot(111)
            namen = list(r["groups"])
            n = len(r["dates"])
            grid = np.zeros((len(namen), n))
            for i, g in enumerate(namen):
                res = r["groups"][g]
                for j, v in enumerate(res["cumulative_strain"][1:]):
                    grid[i, j] = ZONES.index(_strain_zone(v, res["critical_strain"]))
            cmap = ListedColormap([ZONE_COLOURS[z] for z in ZONES])
            ax.imshow(grid, aspect="auto", cmap=cmap, norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], 4),
                      extent=[-0.5, n - 0.5, len(namen) - 0.5, -0.5])
            ax.set_yticks(range(len(namen)))
            ax.set_yticklabels([TARGET_GROUPS[g].display_name for g in namen], fontsize=10)
            stap = max(1, n // 14)
            ax.set_xticks(range(0, n, stap))
            ax.set_xticklabels([pd.Timestamp(r["dates"][i]).strftime("%d-%m") for i in range(0, n, stap)])
            ax.grid(False)
            for xx in np.arange(0.5, n - 0.5, 1):
                ax.axvline(xx, color="white", lw=0.6, alpha=0.6)
            for yy in np.arange(0.5, len(namen) - 0.5, 1):
                ax.axhline(yy, color="white", lw=0.6, alpha=0.6)
            fs = self.weer.forecast_start
            if fs is not None and 0 < fs < n:
                ax.axvline(fs - 0.5, color="white", lw=3)
                ax.axvline(fs - 0.5, color="#222", lw=1.3, ls="--")
            ax.set_title("Wie loopt wanneer risico (zone per groep per dag)")
            ax.legend(handles=[Patch(color=ZONE_COLOURS[z], label=ZONE_NL[z]) for z in ZONES],
                      loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=4, frameon=False)
            t["lbl"].config(text="Zoals pyrox_plots.plot_risk_heatmap: zone uit pyrox_plots._strain_zone per dag (Σ na "
                                 "die dag), groepen geordend van weerbaar naar kwetsbaar. Stippellijn = overgang van "
                                 "verleden naar verwachting.")
            t["cv"].draw_idle()

        def _teken_fb(self):
            t = self.tab["fb"]
            g = self._fb_groep()
            grp = TARGET_GROUPS[g]
            loads = self.rapport["heat_loads"]
            sq = self.rapport["sleep_quality"] if self.rapport.get("nocturnal_recovery") else None
            # zoals plot_feedback_race: simulate met dezelfde invoer
            res = PyroxModel(grp).simulate(loads, pre_heatwave_heat_load=self.pre,
                                           sleep_quality_series=sq)
            dg = res["diagnostics"]
            x = self._datums()
            fig = t["fig"]
            fig.clear()
            ax = fig.add_subplot(111)
            crit = grp.critical_strain
            ax.plot(x, [d["cumulative_strain"] for d in dg], lw=3, color=ZONE_COLOURS["emergency"],
                    label="opgebouwde belasting Σ (de uitkomst)")
            pot = [d["acclimatization_potential"] for d in dg]
            eff = [d["effective_acclimatization"] for d in dg]
            ax.plot(x, pot, lw=1.5, ls="--", color=ZONE_COLOURS["safe"], label="acclimatisatie-potentieel (zonder onderdrukking)")
            ax.plot(x, eff, lw=2.5, color=ZONE_COLOURS["safe"], label="effectieve acclimatisatie (met onderdrukking)")
            ax.fill_between(x, eff, pot, color=ZONE_COLOURS["safe"], alpha=0.15, label="voetafdruk van de terugkoppelingslus")
            ax.plot(x, [d["suppression_factor"] for d in dg], lw=1.5, ls=":", color="#4063d8",
                    label="onderdrukkingsfactor (1 − κΣ)")
            ax.axhline(crit, ls=":", color="grey", lw=1.2)
            ax.text(0.0, crit, " kritieke grens (bescherming volledig overmeesterd)", transform=ax.get_yaxis_transform(),
                    va="bottom", fontsize=9, color="grey")
            for frac, z in ((0.5, "caution"), (0.75, "danger"), (0.9, "emergency")):
                ax.axhline(frac * crit, color=ZONE_COLOURS[z], lw=1, ls="--", alpha=0.6)
                ax.text(1.0, frac * crit, f" {ZONE_NL[z]}", transform=ax.get_yaxis_transform(), va="center",
                        fontsize=9, color=ZONE_COLOURS[z])
            ax.set_ylim(0, crit * 1.22)
            ax.set_title(f"De ene terugkoppelingslus in actie — {grp.display_name} ({grp.evidence_status})")
            ax.set_ylabel("waarde (modeleenheden)")
            ax.legend(loc="center left", fontsize=9)
            self._x(ax)
            self._scheiding(ax, x)
            t["lbl"].config(text=(
                "Zoals pyrox_plots.plot_feedback_race (diagnostics van PyroxModel.simulate). Hitte werkt rechtstreeks op Σ en "
                "vertraagd via acclimatisatie (10 dagen geheugen). Er is één gesloten lus: Σ → onderdrukking → (remt) "
                "acclimatisatie → (zou remmen op) Σ; polariteit (+)(−)(−) = +, zichzelf versterkend. De gearceerde kloof tussen "
                "potentieel en effectieve acclimatisatie is de voetafdruk van die lus. Kies de groep links onder 'Groep voor detail'."))
            t["cv"].draw_idle()

        def _teken_onz(self):
            t = self.tab["onz"]
            fig = t["fig"]
            fig.clear()
            ax = fig.add_subplot(111)
            fs = self.weer.forecast_start
            if fs is None:
                ax.text(0.5, 0.5, "Deze periode bevat geen verwachting (alleen waargenomen dagen).",
                        ha="center", va="center", transform=ax.transAxes, fontsize=13)
                ax.set_axis_off()
                t["lbl"].config(text="")
                t["cv"].draw_idle()
                return
            x = self._datums()
            kleuren = matplotlib.colormaps["tab10"].colors
            for i, g in enumerate(self.rapport["groups"]):
                c, lo, hi = onzekerheid(self.weer, self.rapport, g, self.onz, self.pre)
                crit = TARGET_GROUPS[g].critical_strain
                k = kleuren[i % 10]
                ax.fill_between(x, 100 * np.asarray(lo[1:]) / crit, 100 * np.asarray(hi[1:]) / crit, color=k, alpha=0.18)
                ax.plot(x, 100 * np.asarray(c[1:]) / crit, lw=2.2, color=k, label=TARGET_GROUPS[g].display_name)
            self._zonelijnen(ax)
            ax.set_ylim(0, 105)
            ax.set_ylabel("Σ (% van kritieke grens)")
            ax.set_title(f"Gevoeligheid voor de verwachting: band = ±{nl(self.onz, 1)} °C op de verwachtingsdagen")
            ax.legend(loc="upper left", fontsize=9)
            self._x(ax)
            self._scheiding(ax, x)
            t["lbl"].config(text=(
                "Zoals pyrox_plots.plot_forecast_uncertainty: drie runs per groep (centraal, −Δ, +Δ) met Δ = graden × "
                "HEAT_LOAD_PER_DEGREE, alleen vanaf de eerste verwachtingsdag. Smalle band = robuuste waarschuwing; brede band "
                "= uitkomst hangt af van hoe de verwachting uitpakt. Bij een los Forecast-blad geldt (zoals in het rapport) de "
                "hele periode als verwachting."))
            t["cv"].draw_idle()

        def _teken_reg(self):
            t = self.tab["reg"]
            g = self._fb_groep()
            grp = TARGET_GROUPS[g]
            crit = grp.critical_strain
            fig = t["fig"]
            fig.clear()
            a1, a2 = fig.add_subplot(1, 2, 1), fig.add_subplot(1, 2, 2)
            rg = regimes(g)
            L = rg["loads"]
            stap = L[1] - L[0]
            kleur = {"veilig": ZONE_COLOURS["safe"], "kantel": ZONE_COLOURS["danger"], "kritiek": ZONE_COLOURS["emergency"]}
            for R, z in zip(L, rg["zone"]):
                a1.axvspan(R - stap / 2, R + stap / 2, color=kleur[z], alpha=0.16, lw=0)
            # kantelpunt (simulatie)
            kp = np.array([np.nan if (k is None or k == 0.0) else k for k in rg["drempel"]])
            a1.plot(L, kp, color="#b03a2e", lw=2.4, ls="--", label="kantelpunt: begin-Σ waarboven de groep kantelt")
            # eindtoestand bij normale start
            a1.plot(L, rg["eind"], color="#222", lw=2.6,
                    label=f"eindtoestand na {REG_DAGEN} dagen (normale start)")
            # analytisch (suite, volle acclimatisatie), per stabiliteit
            av = np.array([np.nan if v is None else v for v in rg["ana_value"]])
            inst = np.array([s_ == "instabiel" for s_ in rg["ana_stab"]])
            a1.plot(L, np.where(inst, av, np.nan), color="#555", lw=1.2, ls=":",
                    label="Σ* equilibrium_strain, instabiel (volle acclim.)")
            a1.plot(L, np.where(~inst, av, np.nan), color="#555", lw=1.2, ls="-.",
                    label="Σ* equilibrium_strain, overig (volle acclim.)")
            a1.axhline(crit, ls=":", color="grey")
            hl_ = np.asarray(self.rapport["heat_loads"])
            a1.axvline(hl_.max(), color="#c0392b", lw=1.5)
            a1.text(hl_.max(), 0.98, f" hoogste dag in deze periode ({nl(hl_.max())})",
                    transform=a1.get_xaxis_transform(), va="top", fontsize=9, color="#c0392b", rotation=90, ha="right")
            zonelijst = rg["zone"]
            def grens(z):
                i = [k for k, x in enumerate(zonelijst) if x == z]
                return (L[i[0]], L[i[-1]]) if i else None
            gk, gr = grens("kantel"), grens("kritiek")
            regels = []
            regels.append(f"kantelzone: {nl(gk[0])} – {nl(gk[1])}" if gk else "geen kantelzone tot 2,5")
            regels.append(f"kantelt altijd vanaf {nl(gr[0])}" if gr else "kantelt niet vanuit elke start tot 2,5")
            a1.text(0.02, 0.62, "\n".join(regels), transform=a1.transAxes, fontsize=10, color="#7a5b00",
                    fontweight="bold", va="top", bbox=dict(fc="white", ec="#7a5b00", alpha=0.85))
            a1.set_xlim(L[0], L[-1])
            a1.set_ylim(-0.05, crit * 1.08)
            a1.set_xlabel("aanhoudende warmtebelasting")
            a1.set_ylabel("Σ")
            a1.set_title(f"{grp.display_name} — regimes")
            a1.legend(loc="upper left", fontsize=8)
            # rechts: voorbeeldverlopen
            def kies(z, positie=0.5):
                i = [k for k, x in enumerate(zonelijst) if x == z]
                return float(L[i[int(positie * (len(i) - 1))]]) if i else None
            voorbeelden = []
            rv = kies("veilig", 0.7)
            if rv is not None:
                voorbeelden.append(([rv] * 48, ZONE_COLOURS["safe"], "-", f"constant {nl(rv)} → dooft uit"))
            rk = kies("kantel", 0.5)
            if rk is not None:
                voorbeelden.append(([rk] * 48, "#b8860b", "-", f"constant {nl(rk)} → blijft laag"))
                pv = piekvoorbeeld(grp, rk)
                if pv is not None:
                    voorbeelden.append((pv[1], "#b03a2e", "--",
                                        f"{nl(rk)} met 3 dagen {nl(pv[0])} → blijft kritiek"))
            rr = kies("kritiek", 0.2)
            if rr is not None:
                voorbeelden.append(([rr] * 48, ZONE_COLOURS["emergency"], "-", f"constant {nl(rr)} → op hol"))
            for reeks, kl, ls, lab in voorbeelden:
                traj = PyroxModel(grp).simulate(reeks, pre_heatwave_heat_load=reeks[0])["cumulative_strain"]
                a2.plot(range(len(traj)), traj, color=kl, lw=2.4, ls=ls, marker="o", ms=2.5, label=lab)
            if rk is not None and any(v[2] == "--" for v in voorbeelden):
                a2.axvspan(5, 8, color="#b03a2e", alpha=0.10)
                a2.text(6.5, crit * 1.03, "piek", ha="center", fontsize=9, color="#b03a2e")
            a2.axhline(crit, ls=":", color="grey")
            a2.set_ylim(-0.05, crit * 1.08)
            a2.set_xlabel("dag")
            a2.set_ylabel("Σ(t)")
            a2.set_title("Voorbeeldverlopen: zonder en met korte piek")
            a2.legend(loc="center right", fontsize=9)
            t["lbl"].config(text=(
                "Alles met PyroxModel.simulate en pyrox_model.equilibrium_strain van de suite. Groen: Σ dooft uit, ook vanaf "
                "vlak onder de kritieke grens. Geel (kantelzone): bistabiel; onder het kantelpunt (rode stippellijn) dooft Σ "
                "uit, erboven loopt Σ door naar de kritieke grens en blijft daar, ook als de belasting weer daalt (hysterese). "
                "Rood: kantelt vanuit elke begintoestand (binnen " + str(REG_DAGEN) + " dagen). Het analytische Σ* van equilibrium_strain (grijs; in plot_three_regimes "
                "als 'evenwicht' getekend) is in de kantelzone instabiel en dus een grens, geen rustpunt; het rekent bovendien met "
                "volle acclimatisatie. Een omslag geldt voor AANHOUDENDE belasting."))
            t["cv"].draw_idle()

        # ------------------------------------------------- briefing-weergaven
        def _zet_dagschalen(self):
            n = len(self.rapport["dates"])
            fs = self.weer.forecast_start
            std = {"br": fs if (fs is not None and 0 < fs < n) else n - 1,
                   "em": fs if (fs is not None and 0 < fs < n) else int(np.argmax(self.rapport["heat_loads"])),
                   "kp": self._kp_standaarddag()}
            sleutel = (self.weer.label, n, fs)
            nieuw = getattr(self, "_dagsleutel", None) != sleutel
            self._dagsleutel = sleutel
            kp_nieuw = getattr(self, "_kp_groep", None) != self._fb_groep()
            self._kp_groep = self._fb_groep()
            for k in ("br", "em", "kp"):
                self.tab[k]["sc"].configure(to=n - 1)
                if nieuw or self.v["dag_" + k].get() > n - 1 or (k == "kp" and kp_nieuw):
                    self.v["dag_" + k].set(std[k])
                self.v["lbl_dag_" + k].config(text=dagtekst(self.rapport["dates"][self.v["dag_" + k].get()]))

        def _kp_standaarddag(self):
            """Dag waarvan de belasting een rand (kantelpunt) geeft voor de detailgroep; anders de heetste dag."""
            loads = np.asarray(self.rapport["heat_loads"], dtype=float)
            g = self._fb_groep()
            for i in np.argsort(-loads):
                S, f, V = landschap(g, float(loads[i]), n=41)
                if any(V[j] >= V[j - 1] and V[j] >= V[j + 1] and V[j] > V[0] for j in range(2, len(V) - 2)):
                    return int(i)
            return int(np.argmax(loads))

        def _dag_gewijzigd(self, k):
            if self.rapport is None:
                return
            self.v["lbl_dag_" + k].config(text=dagtekst(self.rapport["dates"][self.v["dag_" + k].get()]))
            {"br": self._teken_briefing, "em": self._teken_emmers, "kp": self._teken_kp}[k]()

        def _afspelen(self):
            if self._spelen is not None:
                self.root.after_cancel(self._spelen)
                self._spelen = None
                self.knop_af.config(text="▶ afspelen")
                return
            self.knop_af.config(text="■ stop")
            n = len(self.rapport["dates"])
            if self.v["dag_em"].get() >= n - 1:
                self.v["dag_em"].set(0)

            def stap():
                i = self.v["dag_em"].get()
                self._dag_gewijzigd("em")
                if i >= n - 1:
                    self._spelen = None
                    self.knop_af.config(text="▶ afspelen")
                    return
                self.v["dag_em"].set(i + 1)
                self._spelen = self.root.after(700, stap)
            stap()

        def _fig_kalender(self, fig, ax=None, klein=False):
            r = self.rapport
            ax = ax or fig.add_subplot(111)
            namen = list(r["groups"])
            n = len(r["dates"])
            fs = self.weer.forecast_start
            for i, g in enumerate(namen):
                zk = zekerheid(self.weer, r, g, self.onz, self.pre)
                for j, (c, lo, hi) in enumerate(zk):
                    ax.add_patch(matplotlib.patches.Rectangle((j + 0.05, i + 0.08), 0.9, 0.84,
                                                              color=ZONE_COLOURS[ZONE_VOLGORDE[c]], lw=0))
                    if fs is not None and j >= fs and lo != hi:
                        ax.text(j + 0.5, i + 0.5, "?", ha="center", va="center", fontsize=11, fontweight="bold",
                                color="black" if c == 2 else "white")
            ax.set_xlim(0, n)
            ax.set_ylim(len(namen), 0)
            ax.set_yticks([i + 0.5 for i in range(len(namen))])
            ax.set_yticklabels([TARGET_GROUPS[g].display_name for g in namen], fontsize=10)
            stap = max(1, int(np.ceil(n / (11 if klein else 12))))
            ax.set_xticks([j + 0.5 for j in range(0, n, stap)])
            ax.set_xticklabels([dagtekst(r["dates"][j]).replace(" ", "\n") for j in range(0, n, stap)], fontsize=9)
            ax.tick_params(length=0)
            ax.grid(False)
            for sp in ax.spines.values():
                sp.set_visible(False)
            if fs is not None and 0 < fs < n:
                ax.axvline(fs, color="#222", lw=1.5, ls="--")
                ax.text(fs, 1.01, " verwachting →", transform=ax.get_xaxis_transform(), fontsize=9, va="bottom")
            hand = [Patch(color=ZONE_COLOURS[z], label=ZONE_WOORD[z]) for z in ZONE_VOLGORDE]
            if fs is not None:
                hand.append(Patch(color="white", label=f"? = hangt af van de verwachting (±{nl(self.onz, 1)} °C)"))
            ax.legend(handles=hand, loc="upper center", bbox_to_anchor=(0.5, -0.28), ncol=3 if klein else 5,
                      frameon=False, fontsize=7 if klein else 9)
            ax.set_title("Wie loopt wanneer risico", loc="left")

        def _fig_marge(self, ax, peil):
            r = self.rapport
            namen = list(r["groups"])
            y = np.arange(len(namen))
            for i, g in enumerate(namen):
                m = marge(r, g, peil, self.pre)
                if m["gevaar"] is None and m["nood"] is None:
                    ax.text(0.3, i, f"bereikt 'gevaar' niet binnen {MAX_DAGEN} dagen", va="center", fontsize=9,
                            color="#555")
                    continue
                for k, (naam, kleur, dy) in enumerate((("gevaar", ZONE_COLOURS["danger"], -0.18),
                                                       ("nood", ZONE_COLOURS["emergency"], 0.18))):
                    v = m[naam]
                    if v is None:
                        ax.text(0.3, i + dy, f"niet binnen {MAX_DAGEN} dagen", va="center", fontsize=9, color="#555")
                        continue
                    ax.barh(i + dy, max(v, 0.15), height=0.34, color=kleur)
                    ax.text(max(v, 0.15) + 0.3, i + dy, "nu al" if v == 0 else f"{v} d", va="center", fontsize=9)
            ax.set_yticks(y)
            ax.set_yticklabels([TARGET_GROUPS[g].display_name for g in namen], fontsize=9)
            ax.set_ylim(len(namen) - 0.45, -0.55)
            ax.set_xlim(0, MAX_DAGEN + 5)
            ax.set_xlabel("dagen tot de zone bereikt is")
            ax.set_title(f"Marge vanaf {dagtekst(r['dates'][peil])} (bij gelijke hitte)", loc="left", fontsize=11)
            ax.legend(handles=[Patch(color=ZONE_COLOURS["danger"], label="tot gevaar"),
                               Patch(color=ZONE_COLOURS["emergency"], label="tot noodsituatie")],
                      loc="lower right", fontsize=8)

        def _fig_nawerking(self, ax):
            r = self.rapport
            x = self._datums()
            kleuren = matplotlib.colormaps["tab10"].colors
            for i, (g, res) in enumerate(r["groups"].items()):
                crit = res["critical_strain"]
                nw = nawerking(r, g, self.pre)
                k = kleuren[i % 10]
                ax.plot(x, 100 * np.asarray(res["cumulative_strain"][1:]) / crit, lw=2, color=k,
                        label=TARGET_GROUPS[g].display_name)
                xv = [x[-1] + pd.Timedelta(days=d) for d in range(len(nw["verlenging"]))]
                ax.plot(xv, 100 * nw["verlenging"] / crit, lw=1.8, ls="--", color=k)
                if nw["dagen"]:
                    ax.plot(xv[nw["dagen"]], 100 * nw["verlenging"][nw["dagen"]] / crit, "o", ms=7, color=k,
                            mec="black")
            ax.axvspan(x[-1], x[-1] + pd.Timedelta(days=MAX_DAGEN), color="#2471a3", alpha=0.06)
            ax.set_xlim(x[0], x[-1] + pd.Timedelta(days=min(MAX_DAGEN, 21)))
            ax.text(x[-1], 102, "  daarna koel (aanname)", fontsize=8, color="#2471a3", va="bottom")
            self._zonelijnen(ax)
            ax.set_ylim(0, 112)
            ax.set_ylabel("% van kritieke grens")
            ax.set_title("Nawerking: herstel", loc="left", fontsize=11)
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=7))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m"))
            ax.legend(loc="upper left", fontsize=7)

        def _briefing_teksten(self):
            r = self.rapport
            zinnen = [kalenderzin(self.weer, r, g, self.onz, self.pre) for g in r["groups"]]
            peil = self.v["dag_br"].get()
            rijen = []
            for g in r["groups"]:
                m = marge(r, g, peil, self.pre)
                nw = nawerking(r, g, self.pre)
                f = lambda v: "nu al" if v == 0 else (f"> {MAX_DAGEN} dagen" if v is None else
                                                      ("1 dag" if v == 1 else f"{v} dagen"))
                if nw["dagen"] == 0:
                    her = "al veilig"
                elif nw["dagen"] is None:
                    her = "herstelt in het model niet vanzelf binnen 30 dagen"
                else:
                    her = (f"{nw['dagen']} {'dag' if nw['dagen'] == 1 else 'dagen'} (veilig vanaf "
                           f"{dagtekst(pd.Timestamp(r['dates'][-1]) + pd.Timedelta(days=nw['dagen']))})")
                rijen.append((TARGET_GROUPS[g].display_name, ZONE_WOORD[m["nu"]], f(m["gevaar"]), f(m["nood"]), her))
            return zinnen, rijen, peil

        def _teken_briefing(self):
            t = self.tab["br"]
            fig = t["fig"]
            fig.clear()
            gs = fig.add_gridspec(2, 2, height_ratios=[1.0, 1.15])
            self._fig_kalender(fig, fig.add_subplot(gs[0, :]))
            peil = self.v["dag_br"].get()
            self._fig_marge(fig.add_subplot(gs[1, 0]), peil)
            self._fig_nawerking(fig.add_subplot(gs[1, 1]))
            zinnen, rijen, _ = self._briefing_teksten()
            t["lbl"].config(text="\n".join(zinnen) + "\n" + (
                "Marge: de belasting van de peildag houdt aan (PyroxModel.simulate). Nawerking: na de laatste dag belasting 0 "
                "en volledige nachtrust (aanname). (zeker) = ook bij −Δ °C; (waarschijnlijk) = bij de centrale verwachting; "
                "mogelijk = alleen bij +Δ °C."))
            t["cv"].draw_idle()

        def _fig_emmers(self, fig, dag):
            r = self.rapport
            d = self.weer.daily.iloc[dag]
            ax = fig.add_subplot(111)
            ax.set_axis_off()
            namen = list(r["groups"])
            n = len(namen)
            breed, gat = 1.0, 0.55
            last = float(r["heat_loads"][dag])
            sq = float(r["sleep_quality"][dag]) if r.get("nocturnal_recovery") else 1.0
            for i, g in enumerate(namen):
                res = r["groups"][g]
                frac = res["cumulative_strain"][dag + 1] / res["critical_strain"]
                z = ZONE_VOLGORDE[_zone_i(res["cumulative_strain"][dag + 1], res["critical_strain"])]
                x0 = i * (breed + gat)
                ax.add_patch(matplotlib.patches.Rectangle((x0, 0), breed, min(frac, 1.0), color=ZONE_COLOURS[z], lw=0))
                ax.add_patch(matplotlib.patches.Rectangle((x0, 0), breed, 1.0, fill=False, lw=1.6, ec="#333"))
                for fr, zz in ((0.5, "caution"), (0.75, "danger"), (0.9, "emergency")):
                    ax.plot([x0, x0 + breed], [fr, fr], ls="--", lw=1, color=ZONE_COLOURS[zz])
                if last > 0:
                    ax.annotate("", xy=(x0 + breed / 2, 1.04), xytext=(x0 + breed / 2, 1.24),
                                arrowprops=dict(arrowstyle="-|>", lw=1 + 5 * min(last / 2.0, 1.0), color="#D85A30"))
                ax.annotate("", xy=(x0 + breed / 2, -0.28), xytext=(x0 + breed / 2, -0.03),
                            arrowprops=dict(arrowstyle="-|>", lw=1 + 5 * sq, color="#378ADD"))
                naam = TARGET_GROUPS[g].display_name
                if len(naam) > 18 and " " in naam[10:]:
                    k = naam.find(" ", 12)
                    naam = naam[:k] + "\n" + naam[k + 1:] if k > 0 else naam
                ax.text(x0 + breed / 2, -0.36, naam, ha="center", va="top", fontsize=9 if n > 4 else 10)
                ax.text(x0 + breed / 2, min(frac, 1.0) + 0.02 if frac < 0.9 else 0.5, ZONE_WOORD[z],
                        ha="center", va="bottom", fontsize=10, fontweight="bold",
                        color="#222" if frac < 0.9 or z == "danger" else "white")
            for fr, zz in ((0.5, "caution"), (0.75, "danger"), (0.9, "emergency")):
                ax.text(-0.08, fr, ZONE_WOORD[zz], ha="right", va="center", fontsize=9, color=ZONE_COLOURS[zz])
            ax.set_xlim(-0.9, n * (breed + gat))
            ax.set_ylim(-1.02, 1.30)
            nacht = d.get("t_night_min", np.nan)
            ax.set_title(f"{dagtekst(r['dates'][dag])} {pd.Timestamp(r['dates'][dag]).year} — Tmax "
                         f"{nl(d['t_air_max'], 1)} °C, minimum nacht erna "
                         f"{'–' if pd.isna(nacht) else nl(nacht, 1) + ' °C'}"
                         + ("   (verwachting)" if self.weer.forecast_start is not None and dag >= self.weer.forecast_start
                            else ""), loc="left")
            ax.text(-0.85, -0.86, "rode pijl (boven): hitte van deze dag", ha="left", va="center",
                    fontsize=8, color="#D85A30")
            ax.text(-0.85, -0.96, "blauwe pijl (onder): herstel in de nacht, dunner = warmere nacht",
                    ha="left", va="center", fontsize=8, color="#378ADD")

        def _teken_emmers(self):
            t = self.tab["em"]
            fig = t["fig"]
            fig.clear()
            self._fig_emmers(fig, self.v["dag_em"].get())
            t["lbl"].config(text=(
                "Elke groep is een emmer: een hete dag vult hem (dikte rode pijl = warmtebelasting van die dag), de nacht laat "
                "hem leeglopen (dikte blauwe pijl = slaapkwaliteit; een warme nacht knijpt de afvoer dicht). Het peil is de "
                "opgebouwde belasting Σ als deel van de kritieke grens van de groep (PyroxModel.simulate). Zo wordt zichtbaar "
                "waarom de vierde hete dag gevaarlijker is dan de eerste, ook als het niet heter wordt. Gebruik 'afspelen' voor "
                "een presentatie."))
            t["cv"].draw_idle()

        def _fig_landschap(self, fig, dag, g):
            r = self.rapport
            grp = TARGET_GROUPS[g]
            crit = grp.critical_strain
            R = float(self.v["kp_last"].get()) if self.v["kp_eigen"].get() else float(r["heat_loads"][dag])
            S, f, V = landschap(g, R)
            pct = 100 * S / crit
            ax = fig.add_subplot(111)
            for a, b, z in ((0, 50, "safe"), (50, 75, "caution"), (75, 90, "danger"), (90, 100, "emergency")):
                ax.axvspan(a, b, color=ZONE_COLOURS[z], alpha=0.12, lw=0)
            ax.plot(pct, V, color="#5F5E5A", lw=3.5)
            vmin, vmax = float(V.min()), float(V.max())
            span = max(vmax - vmin, 1e-6)
            sigma = r["groups"][g]["cumulative_strain"][dag + 1] if g in r["groups"] else \
                _sim(g, *_invoer(r), self.pre)[dag + 1]
            xb = 100 * sigma / crit
            yb = float(np.interp(xb, pct, V))
            ax.plot([xb], [yb + 0.035 * span], "o", ms=22, color="#D85A30", mec="#4A1B0C", zorder=5)
            fb = float(np.interp(sigma, S, f))
            if abs(fb) > 1e-4:
                ax.annotate("", xy=(xb + (8 if fb > 0 else -8), yb + 0.035 * span - (0.08 if True else 0) * span),
                            xytext=(xb, yb + 0.035 * span),
                            arrowprops=dict(arrowstyle="-|>", lw=2, color="#4A1B0C"))
            binnen = np.arange(2, len(V) - 2)
            top = [i for i in binnen if V[i] >= V[i - 1] and V[i] >= V[i + 1] and V[i] > V[0] + 0.02 * span]
            if top:
                i = top[int(np.argmax(V[top]))]
                ax.annotate("rand = kantelpunt", xy=(pct[i], V[i]), xytext=(pct[i], V[i] + 0.25 * span),
                            ha="center", fontsize=10, arrowprops=dict(arrowstyle="-", lw=1, color="#333"))
            ax.text(2, vmin - 0.12 * span, "herstel", fontsize=10, color=ZONE_COLOURS["safe"], fontweight="bold")
            ax.text(98, vmin - 0.12 * span, "vastgelopen", fontsize=10, color=ZONE_COLOURS["emergency"],
                    fontweight="bold", ha="right")
            ax.set_ylim(vmin - 0.2 * span, vmax + 0.4 * span)
            ax.set_xlim(-3, 100)
            ax.set_yticks([])
            ax.set_xlabel("opgebouwde belasting (% van kritieke grens)")
            ax.set_ylabel("hoogte (zonder eenheid)")
            ax.set_title(f"{grp.display_name} — aanhoudende warmtebelasting {nl(R)}"
                         + ("" if self.v["kp_eigen"].get() else f" (die van {dagtekst(r['dates'][dag])})")
                         + f"\nbal = toestand van de groep op {dagtekst(r['dates'][dag])}", loc="left")

        def _teken_kp(self):
            t = self.tab["kp"]
            fig = t["fig"]
            fig.clear()
            self._fig_landschap(fig, self.v["dag_kp"].get(), self._fb_groep())
            t["lbl"].config(text=(
                "De bal is de toestand van de groep op die dag; hij rolt altijd omlaag. Links ligt de kuil van herstel. Is het "
                "warm genoeg, dan ontstaat er een rand: zolang de bal ervoor blijft, rolt hij terug; is hij erover, dan rolt hij "
                "naar rechts tegen de kritieke grens en komt hij door een koelere dag niet vanzelf terug (hysterese). Heel hete "
                "dagen maken de helling naar rechts zo steil dat er geen rand meer is. Het landschap volgt uit de dagelijkse "
                "verandering van Σ in PyroxModel.simulate bij een aanhoudende belasting van die dag; de groep kies je links onder "
                "'Groep voor detail'. Bedoeld voor uitleg, niet voor beslissingen."))
            t["cv"].draw_idle()

        # ------------------------------------------------- briefing als Word
        def _maak_beelden(self, map_):
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            paden = {}
            peil = self.v["dag_br"].get()
            for naam, maat, teken in (
                    ("kalender", (7.2, 2.0 + 0.32 * len(self.rapport["groups"])), lambda f: self._fig_kalender(f, klein=True)),
                    ("marge_nawerking", (7.2, 5.4), lambda f: (lambda gs: (self._fig_marge(f.add_subplot(gs[0]), peil),
                                                                          self._fig_nawerking(f.add_subplot(gs[1]))))(
                        f.add_gridspec(2, 1))),
                    ("emmers", (7.2, 2.9), lambda f: self._fig_emmers(f, peil)),
                    ("kantelpunt", (7.2, 3.2), lambda f: self._fig_landschap(f, self.v["dag_kp"].get(),
                                                                             self._fb_groep()))):
                f = Figure(figsize=maat, dpi=200, constrained_layout=True)
                FigureCanvasAgg(f)
                with matplotlib.rc_context({"font.size": 8, "axes.titlesize": 9, "legend.fontsize": 7}):
                    teken(f)
                    pad = str(Path(map_) / f"pyrox_briefing_{naam}.png")
                    f.savefig(pad)
                paden[naam] = pad
            return paden

        def _briefing(self):
            if self.rapport is None:
                return messagebox.showinfo("Briefing", "Er is nog geen resultaat.")
            p = filedialog.asksaveasfilename(title="Briefing opslaan als", defaultextension=".docx",
                                             filetypes=[("Word", "*.docx")], initialdir=str(HIER),
                                             initialfile=f"PYROX_Briefing_{self.weer.city}_{pd.Timestamp.now():%Y%m%d_%H%M}")
            if not p:
                return
            try:
                schrijf_briefing(p, self)
                self.lbl_status.config(text=f"Briefing opgeslagen: {p}")
                messagebox.showinfo("Briefing", f"Opgeslagen:\n{p}")
            except Exception as ex:
                self._fout(f"Briefing mislukt: {ex}\n{traceback.format_exc()}")

        def _briefing_markdown(self, map_):
            paden = self._maak_beelden(map_)
            zinnen, rijen, peil = self._briefing_teksten()
            r = self.rapport
            md = ["## Briefing voor veiligheidsfunctionarissen", "",
                  f"Kernboodschap: {self.kernboodschap[0]}", "",
                  f"![Wie loopt wanneer risico]({Path(paden['kalender']).name})", ""]
            md += [f"- {z}" for z in zinnen]
            md += ["", f"Marge vanaf {dagtekst(r['dates'][peil])} (als het zo heet blijft) en nawerking (als het daarna "
                       "koel wordt):", "",
                   "| Groep | Nu | Tot gevaar | Tot noodsituatie | Herstel na koel weer |", "|---|---|---|---|---|"]
            md += [f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in rijen]
            md += ["", f"![Marge en nawerking]({Path(paden['marge_nawerking']).name})", "",
                   f"![Emmers op de peildag]({Path(paden['emmers']).name})", "",
                   "### Uitleg: het kantelpunt", "",
                   f"![Kantellandschap]({Path(paden['kantelpunt']).name})", "",
                   "Voorbij de rand rolt de bal naar de kritieke grens en komt door een koelere dag niet vanzelf terug. "
                   "Dit is een modeluitkomst (PYROX, research software), geen vastgestelde drempel.", ""]
            return "\n".join(md)

        def _fout(self, tekst):
            self.tegels.leeg("Geen uitkomst: " + tekst.splitlines()[0][:200])
            self.lbl_status.config(text=tekst.splitlines()[0][:160])
            self.lbl_kop.config(text="  Fout  ", bg="#999999", fg="white")

        # ---------------------------------------------------- export, rapport
        def _export(self):
            if self.rapport is None:
                return messagebox.showinfo("Excel-export", "Er is nog geen resultaat.")
            p = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                             initialdir=str(HIER))
            if not p:
                return
            r = self.rapport
            try:
                dag = self.weer.daily.copy()
                dag["slaapkwaliteit"] = r["sleep_quality"]
                per = []
                for g, res in r["groups"].items():
                    per.append({"groep": res["group"].display_name, "sleutel": g,
                                "evidentie": res["group"].evidence_status, "kritieke_grens": res["critical_strain"],
                                "piek_sigma": res["peak_strain"], "let_op": self._dag(res["caution_day"]),
                                "gevaar": self._dag(res["danger_day"]), "noodsituatie": self._dag(res["emergency_day"])})
                    dag[f"sigma_{g}"] = res["cumulative_strain"][1:]
                    dag[f"zone_{g}"] = [ZONE_NL[_strain_zone(v, res["critical_strain"])]
                                        for v in res["cumulative_strain"][1:]]
                meta = pd.DataFrame([("weer", self.weer.label), ("plaats", self.weer.city),
                                     ("woonomgeving", self.v["route"].get()),
                                     ("nachtelijk_herstel", r["nocturnal_recovery"]),
                                     ("belasting_voor_hittegolf", self.pre if self.pre is not None else "eerste dag")],
                                    columns=["grootheid", "waarde"])
                with pd.ExcelWriter(p) as xw:
                    meta.to_excel(xw, sheet_name="Instellingen", index=False)
                    pd.DataFrame(per).to_excel(xw, sheet_name="Per groep", index=False)
                    dag.to_excel(xw, sheet_name="Per dag", index=False)
            except Exception as ex:
                self._fout(f"Export mislukt: {ex}")

        def _rapport(self):
            if self.rapport is None:
                return messagebox.showinfo("Rapport", "Er is nog geen resultaat.")
            p = filedialog.asksaveasfilename(title="Rapport opslaan als", defaultextension=".docx",
                                             filetypes=[("Word", "*.docx")], initialdir=str(HIER),
                                             initialfile=f"PYROX_Rapport_{self.weer.city}_{pd.Timestamp.now():%Y%m%d_%H%M}")
            if not p:
                return
            stam = str(Path(p).with_suffix(""))
            naam = f"{self.weer.city} ({self.weer.bladnaam_rapport})"
            self.lbl_status.config(text="Rapport maken (generate_pyrox_report + Word) …")
            try:
                aanhangsel = self._briefing_markdown(str(Path(stam).parent))
            except Exception as ex:
                aanhangsel = ""
                self._fout(f"Briefing-aanhangsel mislukt: {ex}")
            f = self.rpool.submit(_rapport_proces, naam, self.rapport, stam, True, aanhangsel)

            def klaar(fut):
                try:
                    self.q.put(("rapport", fut.result()))
                except Exception as ex:
                    self.q.put(("fout", f"Rapport mislukt: {ex}"))
            f.add_done_callback(klaar)

        def _sluit(self):
            self.rpool.shutdown(wait=False, cancel_futures=True)
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
