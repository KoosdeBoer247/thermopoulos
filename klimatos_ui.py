# -*- coding: utf-8 -*-
"""
klimatos_ui.py
==============
Visuele invoer en weergave (Tkinter) voor Klimatos.ClimateShift, in de stijl van
hestia_loper_ui.py, hestia_populatie_ui.py en pyrox_ui.py.

De suite blijft bevroren: dit script verandert geen suitebestand en roept alleen
bestaande functies aan.

  ophalen per jaar ........ Klimatos_ClimateShift.fetch_hourly_year (met zijn eigen
                            rate-limit-afhandeling), plus een cache op schijf in
                            deze UI (de suite zelf heeft geen cache)
  verwerken per jaar ...... Klimatos_ClimateShift.build_annual_maxima, jaar voor jaar
                            aangeroepen (voortschrijdend, parallel); het resultaat is
                            bit-identiek aan een aanroep over de hele periode
  analyse ................. Klimatos_ClimateShift.main() zelf, met de console-invoer
                            ingevuld door de UI en het ophalen vervangen door de
                            jaren die al binnen zijn; alle vensters, toetsen, figuren,
                            Excel (save_results) en het rapportpakket komen dus
                            ongewijzigd uit Klimatos
  EHS-evolutie ............ dezelfde main() met ENABLE_EHS_EVOLUTION aan (lang; aparte knop)
  Word-rapport ............ rapportpakket.maak (generate_klimatos_report + report_to_docx)

BEOORDELINGSMODUS KUSTCORRECTIE (geen suitegedrag)
  Klimatos past de ERA5 land-zeecorrectie van de Data Engine bewust NIET toe
  (Known issue 14). Om het effect te kunnen beoordelen kan deze UI een tweede,
  volledig gecorrigeerde run maken: per jaar era5_kustcorrectie.corrigeer_dataframe,
  toegepast zoals Thermopoulos_Data_Engine.process_weather_data stap 0 dat doet
  (dauwpunt vast, RH opnieuw berekend, voor de UHI). Die run kost veel
  Open-Meteo-eenheden en loopt daardoor over meerdere dagen; de cache maakt hem
  hervatbaar. De gecorrigeerde resultaten worden altijd apart getoond en nooit
  met de suiteresultaten vermengd.

SNELLE VERKENNING
  Haalt alleen de laatste 30 jaar op (bij een evenement vanaf het begin van
  EVENT_TREND_PERIOD, zodat de evenementtrend volledig is). De referentieperiode
  1951-1980 valt dan buiten de data; Klimatos klemt die op de beschikbare jaren,
  wat een lege referentie geeft. Daarom wordt in deze modus (en alleen daar) de
  referentieperiode op de eerste 10 opgehaalde jaren gezet; dat staat in de
  weergave en in de meta-gegevens. De suite-instellingen blijven verder ongewijzigd.

Starten:  python klimatos_ui.py
"""
from __future__ import annotations

import io
import os
import queue
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

HIER = Path(__file__).resolve().parent
if str(HIER) not in sys.path:
    sys.path.insert(0, str(HIER))


# =============================================================================
# 1. CACHE
# =============================================================================
def cache_map() -> Path:
    if os.environ.get("KLIMATOS_UI_CACHE"):
        p = Path(os.environ["KLIMATOS_UI_CACHE"])
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        p = Path(os.environ["LOCALAPPDATA"]) / "Thermopoulos" / "klimatos_ui"
    else:
        p = Path.home() / ".cache" / "thermopoulos" / "klimatos_ui"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _pad(lat, lon, jaar, soort) -> Path:
    import Klimatos_ClimateShift as ks
    return cache_map() / f"{lat:.4f}_{lon:.4f}_{ks.ARCHIVE_MODEL}_{ks.ARCHIVE_CELL_SELECTION}_{jaar}_{soort}.pkl"


def in_cache(lat, lon, jaar, soort="ruw") -> bool:
    return _pad(lat, lon, jaar, soort).exists()


def ruw_jaar(lat, lon, tz, jaar) -> tuple[pd.DataFrame, bool]:
    """Ruwe ERA5 van een jaar (uitvoer van fetch_hourly_year). (frame, uit_cache)."""
    import Klimatos_ClimateShift as ks
    p = _pad(lat, lon, jaar, "ruw")
    if p.exists():
        df = pd.read_pickle(p)
        return df.tz_convert(tz) if df.index.tz is not None else df, True
    df = ks.fetch_hourly_year(lat, lon, tz, jaar)
    tmp = p.with_suffix(".tmp")
    df.to_pickle(tmp)
    tmp.replace(p)
    return df, False


class KustFout(RuntimeError):
    pass


def kust_jaar(lat, lon, jaar, ruw: pd.DataFrame) -> tuple[pd.Series, dict, bool]:
    """Correctie per uur voor een jaar (era5_kustcorrectie.corrigeer_dataframe).
    Alleen een geslaagde berekening wordt bewaard; bij een fout (daglimiet, netwerk)
    volgt KustFout, zodat de gecorrigeerde run later hervat kan worden."""
    import era5_kustcorrectie as ek
    p = _pad(lat, lon, jaar, "kust")
    if p.exists():
        d = pd.read_pickle(p)
        corr = d["corr"]
        corr.index = ruw.index
        return corr, d["info"], True
    corr, info = ek.corrigeer_dataframe(ruw, lat, lon)
    melding = str(info.get("melding", ""))
    if melding.startswith("ERA5 land-sea correction not applied"):
        raise KustFout(melding)
    bewaar = {k: v for k, v in info.items() if k != "reden"}
    if isinstance(info.get("reden"), pd.Series):
        bewaar["reden_telling"] = info["reden"].value_counts().to_dict()
    pd.to_pickle({"corr": pd.Series(corr.to_numpy(), index=ruw.index), "info": bewaar}, p)
    return corr, bewaar, False


def pas_correctie_toe(ruw: pd.DataFrame, corr: pd.Series) -> pd.DataFrame:
    """Zoals Thermopoulos_Data_Engine.process_weather_data stap 0: dauwpunt vast,
    temperatuur gecorrigeerd, RH opnieuw uit het dauwpunt."""
    from Thermopoulos_Data_Engine import dew_point_from_rh, rh_from_dew_point
    df = ruw.copy()
    c = corr.reindex(df.index).fillna(0.0).to_numpy()
    if not np.any(c != 0.0):
        return df
    dauw = dew_point_from_rh(df["T_air_rural"].values, df["RH"].values)
    df["T_air_rural"] = df["T_air_rural"] + c
    df["RH"] = rh_from_dew_point(df["T_air_rural"].values, dauw)
    return df


# =============================================================================
# 2. INVOER EN SUITE-INSTELLINGEN
# =============================================================================
@dataclass
class KlimInvoer:
    city: dict
    uhi: bool = False
    evenement: bool = True
    naam: str = "Dam tot Damloop"
    dag: int = 22
    maand: int = 9
    uur: int = 13
    minuut: int = 30
    afstand_km: float = 16.1
    tempo: str = "5:30"            # min/km (mm:ss of decimaal)
    snel: bool = False
    kust: bool = False             # beoordelingsmodus kustcorrectie
    ehs: bool = False

    @property
    def tempo_min(self) -> float:
        t = self.tempo.strip().replace(",", ".")
        if ":" in t:
            m, s = t.split(":", 1)
            return float(m) + float(s) / 60.0
        return float(t)

    @property
    def duur_min(self) -> int:
        return int(round(self.tempo_min * self.afstand_km))


def laatste_jaar() -> int:
    import Klimatos_ClimateShift as ks
    return ks.END_YEAR if ks.END_YEAR is not None else datetime.now().year - 1


def jaren(inv: KlimInvoer) -> list[int]:
    """Zoals main(): earliest = min(START_YEAR, REFERENCE_PERIOD[0], EVENT_TREND_PERIOD[0])."""
    import Klimatos_ClimateShift as ks
    eind = laatste_jaar()
    if inv.snel:
        begin = eind - 29
        if inv.evenement:
            begin = min(begin, ks.EVENT_TREND_PERIOD[0])
    else:
        begin = min(ks.START_YEAR, ks.REFERENCE_PERIOD[0])
        if inv.evenement:
            begin = min(begin, ks.EVENT_TREND_PERIOD[0])
    return list(range(begin, eind + 1))


def zet_suite(ks, inv: KlimInvoer, eerste_jaar: Optional[int] = None):
    """Zet de module-instellingen zoals main() ze uit de console-invoer zet."""
    ks.ENABLE_EVENT_WINDOW = bool(inv.evenement)
    ks.EVENT_NAME = inv.naam
    ks.EVENT_DAY, ks.EVENT_MONTH = int(inv.dag), int(inv.maand)
    ks.EVENT_START_HOUR, ks.EVENT_START_MINUTE = int(inv.uur), int(inv.minuut)
    ks.EVENT_DIST_KM = float(inv.afstand_km)
    ks.EVENT_DURATION_MIN = inv.duur_min
    ks.EHS_MET_VALUE = ks._acsm_met_from_pace(inv.tempo_min)
    ks.ENABLE_EHS_EVOLUTION = bool(inv.ehs)
    if inv.snel and eerste_jaar is not None:
        ks.REFERENCE_PERIOD = (eerste_jaar, eerste_jaar + 9)


# =============================================================================
# 3. VERWERKEN PER JAAR (procespool)
# =============================================================================
def _verwerk_jaar(inv_d: dict, jaar: int, ruw: pd.DataFrame, corr: Optional[pd.Series]):
    """build_annual_maxima voor een jaar, met dit jaar als 'opgehaalde' data."""
    import contextlib
    import logging
    logging.disable(logging.WARNING)
    import Klimatos_ClimateShift as ks
    inv = KlimInvoer(**inv_d)
    zet_suite(ks, inv)
    data = pas_correctie_toe(ruw, corr) if corr is not None else ruw
    oud = (ks.fetch_hourly_year, ks.REQUEST_PAUSE_S, ks.era5_correctie_waarschuwing)
    ks.fetch_hourly_year = lambda lat, lon, tz, year: data.copy()
    ks.REQUEST_PAUSE_S = 0.0
    ks.era5_correctie_waarschuwing = lambda lat, lon: ""
    es, lr = {}, {}
    c = inv.city
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            df = ks.build_annual_maxima(c["latitude"], c["longitude"], c["timezone"], c, jaar, jaar,
                                        apply_uhi=inv.uhi, event_slices=es, liveability_raw=lr)
    finally:
        ks.fetch_hourly_year, ks.REQUEST_PAUSE_S, ks.era5_correctie_waarschuwing = oud
    return jaar, df, es.get(jaar), lr.get(jaar)


# =============================================================================
# 4. ANALYSE: Klimatos main() zelf (apart proces)
# =============================================================================
class _Regels(io.TextIOBase):
    def __init__(self, q):
        self.q, self.buf = q, ""

    def write(self, s):
        self.buf += s.replace("\r", "\n")
        while "\n" in self.buf:
            regel, self.buf = self.buf.split("\n", 1)
            if regel.strip():
                try:
                    self.q.put(("log", regel))
                except Exception:
                    pass
        return len(s)

    def flush(self):
        pass


def analyse(inv_d: dict, annual: pd.DataFrame, slices: dict, lraw: dict, uitmap: str, q=None) -> dict:
    """Draait Klimatos_ClimateShift.main() met de UI-invoer en de opgehaalde jaren.
    Geeft alles terug wat main() aan save_results en rapportpakket.bewaar doorgeeft."""
    import contextlib
    import logging
    logging.disable(logging.WARNING)
    os.makedirs(uitmap, exist_ok=True)
    os.chdir(uitmap)
    import Klimatos_ClimateShift as ks
    import rapportpakket
    inv = KlimInvoer(**inv_d)
    zet_suite(ks, inv, eerste_jaar=int(annual.index.min()))
    c = inv.city
    antwoorden = [
        ("city name", c["name"]),
        ("urban heat island", "y" if inv.uhi else "n"),
        ("fixed annual event", "y" if inv.evenement else "n"),
        ("Event name", inv.naam),
        ("Date as DD-MM", f"{inv.dag:02d}-{inv.maand:02d}"),
        ("Start time", f"{inv.uur:02d}:{inv.minuut:02d}"),
        ("distance", f"{inv.afstand_km:g}"),
        ("Duration", str(inv.duur_min)),
        ("pace", inv.tempo),
        ("Generate report", "n"),
    ]

    def invoer(prompt=""):
        for sleutel, antw in antwoorden:
            if sleutel.lower() in prompt.lower():
                return antw
        return ""

    ks.input = invoer
    ks.geocode_city_candidates = lambda naam: [c]

    def bouw(lat, lon, tz, city, start_year, end_year, apply_uhi=False, event_slices=None,
             liveability_raw=None):
        if event_slices is not None:
            event_slices.update({j: s for j, s in slices.items() if start_year <= j <= end_year})
        if liveability_raw is not None:
            liveability_raw.update({j: s for j, s in lraw.items() if start_year <= j <= end_year})
        return annual.loc[start_year:end_year].copy()

    ks.build_annual_maxima = bouw
    vang = {}
    orig_save = ks.save_results

    def save(annual_, stats_by_var, plot_paths, meta, *a, **k):
        vang["stats_by_var"] = stats_by_var
        pad = orig_save(annual_, stats_by_var, plot_paths, meta, *a, **k)
        vang["excel"] = os.path.abspath(pad)
        return pad

    ks.save_results = save
    orig_bewaar = rapportpakket.bewaar

    def bewaar(soort, gegevens, stam):
        vang["pakket"] = gegevens
        vang["rapport_stam"] = os.path.abspath(str(stam))
        return orig_bewaar(soort, gegevens, stam)

    rapportpakket.bewaar = bewaar
    uit = _Regels(q) if q is not None else io.StringIO()
    t0 = time.time()
    with contextlib.redirect_stdout(uit):
        ks.main()
    if "pakket" not in vang:
        raise RuntimeError("Klimatos main() eindigde zonder resultaat (zie het logboek).")
    g = dict(vang["pakket"])
    g["plot_paths"] = [os.path.abspath(p) for p in g.get("plot_paths", [])]
    return dict(gegevens=g, stats_by_var=vang.get("stats_by_var"), excel=vang.get("excel"),
                rapport_stam=vang.get("rapport_stam"), uitmap=uitmap, duur_s=time.time() - t0,
                referentie=ks.REFERENCE_PERIOD, snel=inv.snel, kust=inv.kust, ehs=inv.ehs)


def maak_rapport(pakket: dict, stam: str, uitmap: str) -> list:
    """rapportpakket.maak in de uitvoermap van de run (daar staan de figuren, die
    generate_klimatos_report op bestandsnaam invoegt); daarna worden .md en .docx
    naar de gekozen plek gekopieerd. De .docx bevat de figuren zelf."""
    import contextlib
    import shutil
    os.chdir(uitmap)
    import rapportpakket
    binnen = os.path.join(uitmap, Path(stam).name)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rapportpakket.maak({"soort": "klimatos", "rapport_stam": binnen, "gegevens": pakket}, vraag_word=False)
    uit = []
    for ext in (".md", ".docx"):
        if os.path.exists(binnen + ext):
            if os.path.abspath(binnen + ext) != os.path.abspath(stam + ext):
                shutil.copyfile(binnen + ext, stam + ext)
            uit.append(stam + ext)
    if not os.path.exists(binnen + ".docx"):
        regel = next((r for r in buf.getvalue().splitlines() if "Word-export" in r), "")
        uit.append("Word-rapport niet gemaakt: " + (regel.strip() if regel else
                   "voor Word zijn Node.js en eenmalig 'npm install' in de suitemap nodig; "
                   "het Markdown-rapport staat er wel."))
    uit.append(f"(De figuren bij het Markdown-rapport staan in {uitmap}.)")
    return uit


def waarschuwing(lat, lon) -> str:
    import contextlib
    import Klimatos_ClimateShift as ks
    with contextlib.redirect_stdout(io.StringIO()):
        return ks.era5_correctie_waarschuwing(lat, lon)


# =============================================================================
# 5. GEBRUIKERSINTERFACE
# =============================================================================
VARIANT_NAAM = {"suite": "suite (ERA5 zonder kustcorrectie)", "kust": "beoordeling: ERA5 + kustcorrectie"}


def _hms(s: Optional[float]) -> str:
    if s is None or not np.isfinite(s):
        return "--:--:--"
    s = int(max(0, s))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _start_ui(na_start=None):
    import multiprocessing as mp
    import shutil
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import tkinter.font as tkfont
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    from matplotlib.colors import TwoSlopeNorm
    import logging
    logging.disable(logging.WARNING)
    import Klimatos_ClimateShift as ks
    import era5_kustcorrectie as ek
    from thermal_env import geocode_city_candidates

    LETTER = 12
    import ui_gemeen as ug
    matplotlib.rcParams.update({"font.size": 11, "axes.titlesize": 12, "axes.titleweight": "bold",
                                "axes.grid": True, "grid.alpha": 0.3, "legend.fontsize": 9})
    VAR_NL = {"T_air_max": "Tlucht max (°C)", "WBT_max": "natteboltemperatuur max (°C)",
              "WBGT_max": "WBGT max (°C)", "UTCI_max": "UTCI max (°C)"}
    KLEUR = {"suite": "#2471a3", "kust": "#c0392b"}

    def nl(x, d=1):
        return "–" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}".replace(".", ",")

    class App:
        def __init__(self, root):
            self.root = root
            root.title("Klimatos.ClimateShift · klimaatverschuiving per plaats  (research software)")
            for naam in ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont"):
                try:
                    tkfont.nametofont(naam).configure(size=LETTER)
                except tk.TclError:
                    pass
            st = ttk.Style()
            st.configure("TLabelframe.Label", font=("TkDefaultFont", LETTER, "bold"))
            st.configure("K.Treeview", font=("TkDefaultFont", LETTER - 2), rowheight=int(LETTER * 1.9))
            st.configure("K.Treeview.Heading", font=("TkDefaultFont", LETTER - 2, "bold"))
            bw, bh = root.winfo_screenwidth(), root.winfo_screenheight()
            root.geometry(f"{min(1800, bw - 40)}x{min(1040, bh - 80)}+10+10")
            ug.maximaliseer(root)
            self.q = queue.Queue()
            self.kandidaten = []
            self.d = {v: self._leeg() for v in ("suite", "kust")}
            self.run = None            # dict met status van de lopende run
            self.stop = threading.Event()
            # 'spawn': een geforkt kindproces zou de X-verbinding van Tk erven en bij het
            # afsluiten meenemen (de UI verliest dan zijn venster)
            self.ctx = mp.get_context("spawn")
            self.ypool = ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) // 2), mp_context=self.ctx)
            self.apool = ProcessPoolExecutor(max_workers=1, mp_context=self.ctx)
            self.rpool = ProcessPoolExecutor(max_workers=1, mp_context=self.ctx)
            self.man = None
            self.analyse_duur = 180.0
            self._bouw()
            self._poll()
            self._klok()
            root.protocol("WM_DELETE_WINDOW", self._sluit)

        @staticmethod
        def _leeg():
            return {"rows": {}, "slices": {}, "lraw": {}, "res": None, "fout": [], "info": {}, "inv": None}

        # ------------------------------------------------------------ opbouw
        def _bouw(self):
            links = ttk.Frame(self.root, padding=6)
            links.pack(side="left", fill="y")
            cv = tk.Canvas(links, width=ug.px(self.root, 455), highlightthickness=0)
            sb = ttk.Scrollbar(links, orient="vertical", command=cv.yview)
            self.form = ttk.Frame(cv)
            self.form.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
            cv.create_window((0, 0), window=self.form, anchor="nw")
            cv.configure(yscrollcommand=sb.set)
            cv.pack(side="left", fill="y")
            sb.pack(side="left", fill="y")
            cv.bind_all("<Button-4>", lambda e: cv.yview_scroll(-2, "units"))
            cv.bind_all("<Button-5>", lambda e: cv.yview_scroll(2, "units"))
            cv.bind_all("<MouseWheel>", lambda e: cv.yview_scroll(int(-e.delta / 120), "units"))
            self.v, self.w = {}, {}

            ug.invoer_legenda(self.form, LETTER)
            r = self._sectie("Locatie en gegevensbron", "verplicht",
                             "Gegevens: ERA5-heranalyse (Open-Meteo-archief), één gridcel bij de gekozen plaats.")
            rij = self._rij(r, "Plaats")
            self.v["plaats"] = tk.StringVar(value="Amsterdam")
            pe = ttk.Entry(rij, textvariable=self.v["plaats"], width=14)
            pe.pack(side="left")
            pe.bind("<Return>", lambda e: self._zoek())
            ttk.Button(rij, text="Zoek", width=6, command=self._zoek).pack(side="left", padx=3)
            self.cb_kand = ttk.Combobox(r, state="readonly", width=42)
            self.cb_kand.pack(fill="x", pady=2)
            self.cb_kand.bind("<<ComboboxSelected>>", lambda e: self._plaats_gekozen())
            self.v["uhi"] = tk.BooleanVar(value=bool(ks.APPLY_UHI))
            self.w["uhi"] = ttk.Checkbutton(r, text="Stedelijk hitte-eiland (UHI) toepassen", variable=self.v["uhi"],
                                            command=self._gewijzigd)
            self.w["uhi"].pack(anchor="w")
            self.lbl_kust = ttk.Label(r, text="", wraplength=430, foreground="#7a5b00",
                                      font=("TkDefaultFont", LETTER - 2))
            self.lbl_kust.pack(anchor="w", pady=(2, 0))

            r = self._sectie("Analyseperiode", "verplicht")
            self.v["snel"] = tk.StringVar(value="vol")
            eind = laatste_jaar()
            ttk.Radiobutton(r, text=f"Volledig ({min(ks.START_YEAR, ks.REFERENCE_PERIOD[0])}–{eind})",
                            variable=self.v["snel"], value="vol", command=self._gewijzigd).pack(anchor="w")
            ttk.Label(r, text="Alle jaren met de referentieperiode van de suite. Duurt lang.", foreground="#555",
                      font=("TkDefaultFont", LETTER - 2)).pack(anchor="w", padx=(22, 0))
            ttk.Radiobutton(r, text=f"Snelle verkenning (laatste 30 jaar)", variable=self.v["snel"],
                            value="snel", command=self._gewijzigd).pack(anchor="w")
            ttk.Label(r, text="Referentie = de eerste 10 opgehaalde jaren; niet vergelijkbaar met een volledige "
                              "run.", foreground="#555", font=("TkDefaultFont", LETTER - 2), wraplength=400,
                      justify="left").pack(anchor="w", padx=(22, 0))

            r = self._sectie("Evenement (vaste jaarlijkse datum)", "optioneel")
            self.v["ev"] = tk.BooleanVar(value=True)
            ttk.Checkbutton(r, text="Evenement analyseren", variable=self.v["ev"],
                            command=self._gewijzigd).pack(anchor="w")
            self._tekst(r, "naam", "Naam", ks.EVENT_NAME, breed=20)
            self._tekst(r, "datum", "Datum (DD-MM)", f"{ks.EVENT_DAY:02d}-{ks.EVENT_MONTH:02d}")
            self._tekst(r, "start", "Starttijd (HH:MM)", f"{ks.EVENT_START_HOUR:02d}:{ks.EVENT_START_MINUTE:02d}")
            self._tekst(r, "afstand", "Afstand (km)", f"{ks.EVENT_DIST_KM:g}".replace(".", ","))
            self._tekst(r, "tempo", "Tempo mediaan (min/km)", "5:30")
            self.lbl_afgeleid = ttk.Label(r, text="", foreground="#555", font=("TkDefaultFont", LETTER - 2))
            self.lbl_afgeleid.pack(anchor="w")

            r = self._sectie("Uit te voeren analyses", "actie")

            def toelichting(tekst):
                ttk.Label(r, text=tekst, foreground="#555", font=("TkDefaultFont", LETTER - 2), wraplength=420,
                          justify="left").pack(anchor="w", padx=(4, 0))
            ttk.Label(r, text="1. Suite-run", font=("TkDefaultFont", LETTER, "bold")).pack(anchor="w")
            rij = ttk.Frame(r)
            rij.pack(fill="x", pady=(2, 0))
            self.knop_start = ttk.Button(rij, text="▶ Start run", command=lambda: self._start("suite"))
            self.knop_start.pack(side="left")
            self.knop_stop = ttk.Button(rij, text="■ Stop", command=self._stop, state="disabled")
            self.knop_stop.pack(side="left", padx=4)
            toelichting("Klimatos zoals in de suite: ERA5 zonder kustcorrectie. Dit is de officiële uitkomst.")
            ttk.Label(r, text="2. Aanvullend (na een suite-run)", font=("TkDefaultFont", LETTER, "bold")).pack(
                anchor="w", pady=(6, 0))
            self.knop_ehs = ttk.Button(r, text="EHS-evolutie berekenen (lang)", command=self._ehs)
            self.knop_ehs.pack(anchor="w", pady=(2, 0))
            toelichting("HESTIA-ensemble voor de evenementdag in de doeljaren. Voegt toe aan de suite-run.")
            self.knop_kust = ttk.Button(r, text="Kustcorrectie-run starten / hervatten (beoordeling)",
                                        command=lambda: self._start("kust"))
            self.knop_kust.pack(anchor="w", pady=(4, 0))
            toelichting("Aparte run met ERA5-kustcorrectie, alleen om de correctie te beoordelen. Wordt nooit met "
                        "de suite-uitkomst gemengd; kies hem rechts bij 'Toon'.")
            ttk.Label(r, text="3. Opslaan", font=("TkDefaultFont", LETTER, "bold")).pack(anchor="w", pady=(6, 0))
            rij = ttk.Frame(r)
            rij.pack(fill="x", pady=(2, 0))
            ttk.Button(rij, text="Excel opslaan…", command=self._excel).pack(side="left")
            ttk.Button(rij, text="Rapport (Word)", command=self._rapport).pack(side="left", padx=4)
            self.pb = ttk.Progressbar(r, length=420, mode="determinate")
            self.pb.pack(fill="x", pady=(8, 2))
            self.lbl_fase = ttk.Label(r, text="", wraplength=430, font=("TkDefaultFont", LETTER - 1))
            self.lbl_fase.pack(anchor="w")

            r = self._sectie("Vaste suite-instellingen", "info")
            vast = [f"referentieperiode {ks.REFERENCE_PERIOD[0]}–{ks.REFERENCE_PERIOD[1]}",
                    f"vensters {ks.WINDOW_LENGTH} jaar, stap {ks.WINDOW_STEP}, vanaf {ks.START_YEAR}",
                    f"evenementtrend {ks.EVENT_TREND_PERIOD[0]}–{ks.EVENT_TREND_PERIOD[1]}, ±{ks.EVENT_DAY_WINDOW} dagen",
                    f"doeljaren {', '.join(map(str, ks.EHS_TARGET_YEARS))}",
                    f"EHS: aanpassing start {ks.EHS_ADAPT_START_HOUR:02d}:{ks.EHS_ADAPT_START_MINUTE:02d}, "
                    f"n = {ks.EHS_ENSEMBLE_N}, eindpunt {ks.COLLAPSE_ENDPOINT}",
                    f"HEAT-Lim: {ks.LIVEABILITY_EXP_TIME} h, {ks.LIVEABILITY_SUN}, "
                    f"{'beschikbaar' if ks.HEATLIM_AVAILABLE else 'NIET beschikbaar'}",
                    f"HESTIA {'beschikbaar' if ks.HESTIA_AVAILABLE else 'NIET beschikbaar'}",
                    f"ERA5: {ks.ARCHIVE_MODEL}, cel {ks.ARCHIVE_CELL_SELECTION}",
                    f"cache: {cache_map()}"]
            ttk.Label(r, text="\n".join(vast), foreground="#555", font=("TkDefaultFont", LETTER - 2),
                      justify="left", wraplength=430).pack(anchor="w")

            # ---- rechts
            rechts = ttk.Frame(self.root, padding=(4, 6))
            rechts.pack(side="left", fill="both", expand=True)
            boven = ttk.Frame(rechts)
            boven.pack(fill="x")
            self.lbl_kop = tk.Label(boven, text="  Klimatos — kies een plaats en start een run  ",
                                    font=("TkDefaultFont", LETTER + 1, "bold"), bg="#dddddd", padx=10, pady=4,
                                    anchor="w", justify="left", wraplength=820)
            self.lbl_kop.pack(side="left")
            klok = tk.Frame(boven)
            klok.pack(side="right", padx=6)
            tk.Label(klok, text="verstreken", font=("TkDefaultFont", LETTER - 2)).grid(row=0, column=0)
            tk.Label(klok, text="nog", font=("TkDefaultFont", LETTER - 2)).grid(row=0, column=1)
            self.lbl_verstreken = tk.Label(klok, text="--:--:--", font=("TkFixedFont", LETTER + 8, "bold"),
                                           fg="#333", padx=8)
            self.lbl_verstreken.grid(row=1, column=0)
            self.lbl_nog = tk.Label(klok, text="--:--:--", font=("TkFixedFont", LETTER + 8, "bold"), fg="#1a5e20",
                                    padx=8)
            self.lbl_nog.grid(row=1, column=1)
            rij = ttk.Frame(rechts)
            rij.pack(fill="x", pady=(4, 0))
            ttk.Label(rij, text="Toon:").pack(side="left")
            self.v["toon"] = tk.StringVar(value="suite")
            for k in ("suite", "kust"):
                ttk.Radiobutton(rij, text=VARIANT_NAAM[k], variable=self.v["toon"], value=k,
                                command=self._teken_alles).pack(side="left", padx=6)
            self.tegels = ug.Tegels(rechts, LETTER)
            self.tegels.pack(fill="x", pady=(4, 0))
            self.herkomst = ug.Herkomst(rechts, LETTER)
            self.herkomst.pack(side="bottom", fill="x", pady=(3, 0))
            ttk.Style().configure("K.TNotebook.Tab", padding=(3, 1), font=("TkDefaultFont", LETTER - 1))
            nb = ttk.Notebook(rechts, style="K.TNotebook")
            nb.pack(fill="both", expand=True, pady=(4, 0))
            self.nb = nb
            self.tab = {}
            UITLEG = {
                "jm": "Startpunt. Het warmste uur van elk jaar (Tlucht, WBGT, UTCI) met de trend. Laat zien of de "
                      "hitte-extremen op deze plek toenemen.",
                "ve": "Gemiddelden over schuivende vensters van meerdere jaren, vergeleken met de referentieperiode. "
                      "Minder gevoelig voor één uitschieter dan de jaarmaxima.",
                "st": "Warming stripes: elk jaar één streep, blauw = koeler en rood = warmer dan de referentie. Geschikt "
                      "voor presentaties.",
                "tv": "Voor onderzoek. Gaat de opwarming sneller? Trend over opeenvolgende perioden vergeleken.",
                "ev": "Het weer tijdens het evenement (vaste datum en starttijd) door de jaren heen, met de trend en, na "
                      "de EHS-berekening, het verwachte aantal EHS-gevallen per 1000 deelnemers in de doeljaren.",
                "op": "Hittegerelateerde ziekenhuisopnames in de bevolking als index per jaar (mei–september), "
                      "en de verhouding tot de referentieperiode. Een index die de trend laat zien, geen aantal opnames.",
                "lb": "Leefbaarheid (HEAT-Lim): uren per jaar waarin normale activiteit of zelfs rust buiten niet meer "
                      "veilig vol te houden is, voor 18–40 en 65+.",
                "ku": "Beoordeling van de ERA5-kustcorrectie: suite-run en gecorrigeerde run naast elkaar, met uurdetail "
                      "per jaar. Niet de officiële uitkomst.",
                "fi": "De figuren die de suite zelf maakt, zoals ze ook in het rapport komen.",
                "lg": "Logboek van de run: voor controle en foutzoeken.",
            }
            for k, titel in (("jm", "Jaarmaxima"), ("ve", "Vensters"), ("st", "Warming stripes"),
                             ("tv", "Trendversnelling"), ("ev", "Evenement"), ("op", "Opnames"),
                             ("lb", "Leefbaarheid"), ("ku", "Kustcorrectie"), ("fi", "Suite-figuren"),
                             ("lg", "Logboek")):
                f = ttk.Frame(nb)
                nb.add(f, text=titel)
                ug.tab_uitleg(f, UITLEG[k], LETTER)
                t = {"f": f}
                if k == "lg":
                    tx = tk.Text(f, font=("TkFixedFont", LETTER - 2), wrap="none")
                    ys = ttk.Scrollbar(f, orient="vertical", command=tx.yview)
                    tx.configure(yscrollcommand=ys.set)
                    ys.pack(side="right", fill="y")
                    tx.pack(fill="both", expand=True)
                    t["tx"] = tx
                    self.tab[k] = t
                    continue
                ink = ug.Inklap(f, "Toelichting bij deze grafiek (bron en rekenwijze)", LETTER)
                ink.pack(side="bottom", fill="x", pady=(0, 2))
                lbl = ttk.Label(ink.binnen, text="", font=("TkDefaultFont", LETTER - 1), wraplength=1250,
                                justify="left")
                lbl.pack(fill="x", padx=8, pady=2)
                t["lbl"] = lbl
                if k in ("ev", "lb", "ku"):
                    tv = ttk.Treeview(f, show="headings", height=3, style="K.Treeview")
                    tv.pack(side="bottom", fill="x", padx=6)
                    t["tv"] = tv
                if k == "fi":
                    lb = tk.Listbox(f, width=30, font=("TkDefaultFont", LETTER - 2))
                    lb.pack(side="left", fill="y", padx=(6, 0), pady=4)
                    lb.bind("<<ListboxSelect>>", lambda e: self._toon_figuur())
                    t["lb"] = lb
                if k == "ku":
                    balk = ttk.Frame(f)
                    balk.pack(side="bottom", fill="x", padx=8)
                    ttk.Label(balk, text="Jaar voor het uurdetail:").pack(side="left")
                    self.v["ku_jaar"] = tk.StringVar(value="")
                    self.cb_kujaar = ttk.Combobox(balk, textvariable=self.v["ku_jaar"], state="readonly", width=8)
                    self.cb_kujaar.pack(side="left", padx=4)
                    self.cb_kujaar.bind("<<ComboboxSelected>>", lambda e: self._teken_ku())
                fig = Figure(figsize=(12, 7), dpi=96, constrained_layout=True)
                canv = FigureCanvasTkAgg(fig, master=f)
                canv.get_tk_widget().pack(side="top", fill="both", expand=True)
                t.update(fig=fig, cv=canv)
                self.tab[k] = t
            self._afgeleid()
            self.root.after(300, self._zoek)
            self.root.after(400, self._kop)

        def _sectie(self, titel, soort="verplicht", uitleg=""):
            return ug.sectie(self.form, titel, soort, LETTER, uitleg)

        def _rij(self, ouder, label):
            rij = ttk.Frame(ouder)
            rij.pack(fill="x", pady=1)
            ttk.Label(rij, text=label, width=22).pack(side="left")
            return rij

        def _tekst(self, ouder, k, label, std, breed=11):
            rij = self._rij(ouder, label)
            self.v[k] = tk.StringVar(value=std)
            e = ttk.Entry(rij, textvariable=self.v[k], width=breed)
            e.pack(side="left")
            self.w[k] = e
            self.v[k].trace_add("write", lambda *a: (self._afgeleid(), self._gewijzigd()))

        # ------------------------------------------------------- invoer
        def _kandidaat(self):
            i = self.cb_kand.current()
            return self.kandidaten[i] if 0 <= i < len(self.kandidaten) else None

        def _invoer(self, variant) -> KlimInvoer:
            c = self._kandidaat()
            if c is None:
                raise ValueError("kies eerst een plaats (Zoek)")
            dd, mm = (int(x) for x in self.v["datum"].get().replace("/", "-").split("-")[:2])
            pd.Timestamp(year=2000, month=mm, day=dd)
            hh, mi = (int(x) for x in self.v["start"].get().replace(".", ":").split(":")[:2])
            if not (0 <= hh <= 23 and 0 <= mi <= 59):
                raise ValueError("starttijd")
            km_ = float(self.v["afstand"].get().replace(",", "."))
            if km_ <= 0:
                raise ValueError("afstand")
            inv = KlimInvoer(city=dict(c), uhi=bool(self.v["uhi"].get() and (c.get("population") or 0) > 0),
                             evenement=bool(self.v["ev"].get()), naam=self.v["naam"].get().strip() or "Evenement",
                             dag=dd, maand=mm, uur=hh, minuut=mi, afstand_km=km_, tempo=self.v["tempo"].get().strip(),
                             snel=self.v["snel"].get() == "snel", kust=(variant == "kust"))
            if inv.tempo_min <= 0:
                raise ValueError("tempo")
            return inv

        def _afgeleid(self):
            try:
                inv = KlimInvoer(city={}, afstand_km=float(self.v["afstand"].get().replace(",", ".")),
                                 tempo=self.v["tempo"].get())
                self.lbl_afgeleid.config(text=f"→ duur {inv.duur_min} min, MET "
                                              f"{nl(ks._acsm_met_from_pace(inv.tempo_min))} (ACSM, zoals Klimatos)")
            except Exception:
                self.lbl_afgeleid.config(text="→ (tempo of afstand onleesbaar)")

        def _gewijzigd(self):
            if self.run is not None:
                return
            for v in ("suite", "kust"):
                if self.d[v]["inv"] is not None and self.d[v]["rows"]:
                    try:
                        if asdict(self._invoer(v)) != asdict(self.d[v]["inv"]):
                            self.lbl_fase.config(text="Instellingen gewijzigd: start de run opnieuw "
                                                      "(opgehaalde jaren komen uit de cache).")
                    except Exception:
                        pass

        def _zoek(self):
            naam = self.v["plaats"].get().strip()
            if not naam:
                return
            self.lbl_fase.config(text=f"Plaats zoeken: {naam} …")

            def werk():
                try:
                    self.q.put(("kandidaten", geocode_city_candidates(naam)))
                except Exception as ex:
                    self.q.put(("fout", f"Plaats zoeken mislukt: {ex}"))
            threading.Thread(target=werk, daemon=True).start()

        def _plaats_gekozen(self):
            c = self._kandidaat()
            if c is None:
                return
            pop = c.get("population") or 0
            self.w["uhi"].state(["!disabled"] if pop > 0 else ["disabled"])
            try:
                ld = ek.landdeel(c["latitude"], c["longitude"], 0.10)
            except Exception:
                ld = None
            if ld is None:
                t = "Landdeel van de ERA5-cel onbekend (global-land-mask ontbreekt)."
            else:
                t = (f"ERA5-cel {ld:.0%} land: " + ("KUST — absolute waarden kunnen te gunstig zijn (Known issue 14)."
                                                    if ld < 0.9 else "binnenland."))
            self.lbl_kust.config(text=t)
            self.lbl_fase.config(text="")

        # ------------------------------------------------------------ run
        def _start(self, variant):
            if self.run is not None:
                return
            try:
                inv = self._invoer(variant)
            except Exception as ex:
                return self._fout(f"Invoer: {ex}")
            if variant == "kust" and ek._globe() is None:
                return self._fout("Kustcorrectie niet mogelijk: global-land-mask ontbreekt (pip install global-land-mask).")
            if variant == "kust":
                ld = ek.landdeel(inv.city["latitude"], inv.city["longitude"], 0.10)
                n_open = sum(not in_cache(inv.city["latitude"], inv.city["longitude"], j, "kust") for j in jaren(inv))
                if not messagebox.askyesno(
                        "Kustcorrectie-run (beoordeling)",
                        f"{n_open} van {len(jaren(inv))} jaren hebben nog geen correctie.\n\n"
                        "Kosten (schatting uit de Klimatos-documentatie): eenmalig ±2.000 Open-Meteo-eenheden "
                        "per plaats, daarna ±130–400 per jaar. De gratis daglimiet is 10.000: de run loopt "
                        "daardoor mogelijk over meerdere dagen. Bij de daglimiet stopt hij netjes; start hem "
                        "later opnieuw, hij gaat verder waar hij was.\n\n"
                        f"ERA5-cel: {'onbekend' if ld is None else f'{ld:.0%} land'}. "
                        "De correctie is alleen op Nederlandse stations gefit.\n\nStarten?"):
                    return
            d = self.d[variant]
            if d["inv"] is None or asdict(d["inv"]) != asdict(inv):
                self.d[variant] = d = self._leeg()
            d["inv"] = inv
            alle = jaren(inv)
            todo = [j for j in alle if j not in d["rows"]]
            self.stop.clear()
            self.run = dict(variant=variant, t0=time.time(), jaren=alle, todo=todo, klaar=len(alle) - len(todo),
                            fase="ophalen", t_net=[], t_cache=[], n_wacht=0, eta_analyse=self.analyse_duur,
                            ehs_eta=None, inv=inv)
            self.pb.configure(maximum=len(alle), value=self.run["klaar"])
            self._knoppen(True)
            self._log(f"=== Run {VARIANT_NAAM[variant]}: {inv.city['name']}, {alle[0]}–{alle[-1]} "
                      f"({len(todo)} jaren te doen) ===")
            if not inv.kust:
                self._log(waarschuwing(inv.city["latitude"], inv.city["longitude"]))
            threading.Thread(target=self._haal, args=(variant, inv, todo), daemon=True).start()

        def _haal(self, variant, inv, todo):
            c = inv.city
            lat, lon, tz = c["latitude"], c["longitude"], c["timezone"]
            inv_d = asdict(inv)
            futs = []
            for j in todo:
                if self.stop.is_set():
                    break
                t = time.time()
                try:
                    ruw, uit_cache = ruw_jaar(lat, lon, tz, j)
                    corr = None
                    if inv.kust:
                        corr, info, kc = kust_jaar(lat, lon, j, ruw)
                        uit_cache = uit_cache and kc
                        self.q.put(("kustinfo", variant, j, info))
                    if not uit_cache:
                        time.sleep(ks.REQUEST_PAUSE_S)
                except KustFout as ex:
                    self.q.put(("log", f"[kustcorrectie] {j}: {ex}"))
                    self.q.put(("fout", f"Kustcorrectie gestopt bij {j}: {ex}  — start later opnieuw om te hervatten."))
                    break
                except Exception as ex:
                    self.q.put(("jaarfout", variant, j, str(ex)))
                    continue
                self.q.put(("tijd", "cache" if uit_cache else "net", time.time() - t))
                f = self.ypool.submit(_verwerk_jaar, inv_d, j, ruw, corr)
                f.add_done_callback(lambda fu, v=variant, jj=j: self.q.put(
                    ("jaar", v, fu.result()) if fu.exception() is None else ("jaarfout", v, jj, str(fu.exception()))))
                futs.append(f)
            for f in futs:
                try:
                    f.result()
                except Exception:
                    pass
            self.q.put(("opgehaald", variant, self.stop.is_set()))

        def _start_analyse(self, variant, ehs=False):
            d = self.d[variant]
            if not d["rows"]:
                return self._klaar()
            inv = KlimInvoer(**{**asdict(d["inv"]), "ehs": ehs})
            annual = pd.concat([d["rows"][j] for j in sorted(d["rows"])])
            if self.man is None:
                self.man = self.ctx.Manager()
            lq = self.man.Queue()
            uitmap = str(HIER / "klimatos_ui_uitvoer" / f"{inv.city['name']}_{variant}"
                                                     f"{'_snel' if inv.snel else ''}{'_ehs' if ehs else ''}"
                                                     f"_{datetime.now():%Y%m%d_%H%M%S}")
            self.run.update(fase="EHS-evolutie" if ehs else "analyse", t_analyse=time.time(), lq=lq)
            self.lbl_fase.config(text=("EHS-evolutie en analyse via Klimatos main() …" if ehs
                                       else "Analyse via Klimatos main() (vensters, toetsen, figuren, Excel) …"))
            f = self.apool.submit(analyse, asdict(inv), annual, dict(d["slices"]), dict(d["lraw"]), uitmap, lq)
            f.add_done_callback(lambda fu: self.q.put(("analyse", variant, fu.result())
                                                      if fu.exception() is None else
                                                      ("fout", f"Analyse mislukt: {fu.exception()}")))

        def _ehs(self):
            if self.run is not None:
                return
            v = self.v["toon"].get()
            d = self.d[v]
            if not d["rows"] or d["inv"] is None:
                return messagebox.showinfo("EHS-evolutie", "Draai eerst een run (deze variant).")
            if not d["inv"].evenement:
                return messagebox.showinfo("EHS-evolutie", "Zet eerst het evenement aan en draai de run opnieuw.")
            if len(d["rows"]) < len(jaren(d["inv"])):
                if not messagebox.askyesno("EHS-evolutie", "Niet alle jaren zijn binnen. Toch berekenen?"):
                    return
            self.stop.clear()
            self.run = dict(variant=v, t0=time.time(), jaren=jaren(d["inv"]), todo=[], klaar=len(d["rows"]),
                            fase="EHS-evolutie", t_net=[], t_cache=[], eta_analyse=None, ehs_eta=None, inv=d["inv"])
            self._knoppen(True)
            self._log(f"=== EHS-evolutie {VARIANT_NAAM[v]} ===")
            self._start_analyse(v, ehs=True)

        def _stop(self):
            if self.run is None:
                return
            self.stop.set()
            if self.run.get("fase") in ("analyse", "EHS-evolutie"):
                self.lbl_fase.config(text="Een lopende analyse kan niet tussentijds stoppen; hij maakt zijn werk af.")
            else:
                self.lbl_fase.config(text="Stoppen na het lopende jaar …")

        def _klaar(self):
            if self.run is not None:
                self.lbl_verstreken.config(text=_hms(time.time() - self.run["t0"]))
            self.lbl_nog.config(text="00:00:00")
            self.run = None
            self._knoppen(False)

        def _knoppen(self, bezig):
            for k in (self.knop_start, self.knop_ehs, self.knop_kust):
                k.state(["disabled"] if bezig else ["!disabled"])
            self.knop_stop.state(["!disabled"] if bezig else ["disabled"])

        # ------------------------------------------------------------ klokken
        def _eta(self):
            r = self.run
            if r is None:
                return None
            if r["fase"] == "ophalen":
                c = r["inv"].city
                rest = [j for j in r["todo"] if j not in self.d[r["variant"]]["rows"]]
                gem_net = np.mean(r["t_net"][-10:]) if r["t_net"] else 6.0
                gem_c = np.mean(r["t_cache"][-20:]) if r["t_cache"] else 0.3
                soort = "kust" if r["inv"].kust else "ruw"
                s = sum(gem_c if in_cache(c["latitude"], c["longitude"], j, soort) else gem_net for j in rest)
                workers = max(1, (os.cpu_count() or 2) // 2)
                s = max(s, len(rest) * 0.4 / workers)
                return s + (r["eta_analyse"] or 0)
            if r["fase"] == "analyse":
                return max(0.0, r["eta_analyse"] - (time.time() - r["t_analyse"]))
            if r["fase"] == "EHS-evolutie":
                if r.get("ehs_eta") is not None:
                    eta, t_meting = r["ehs_eta"]
                    return max(0.0, eta - (time.time() - t_meting)) + 0.5 * self.analyse_duur
                return None
            return None

        def _klok(self):
            if self.run is not None:
                self.lbl_verstreken.config(text=_hms(time.time() - self.run["t0"]))
                self.lbl_nog.config(text=_hms(self._eta()))
            self.root.after(1000, self._klok)

        # ------------------------------------------------------------ berichten
        def _poll(self):
            try:
                for _ in range(200):
                    m = self.q.get_nowait()
                    self._bericht(m)
            except queue.Empty:
                pass
            except Exception as ex:
                self._fout(f"Interne fout: {ex}\n{traceback.format_exc()}")
            if self.run is not None and self.run.get("lq") is not None:
                try:
                    for _ in range(200):
                        m = self.run["lq"].get_nowait()
                        self._logregel(m[1])
                except Exception:
                    pass
            self.root.after(200, self._poll)

        def _logregel(self, regel):
            self._log(regel)
            r = self.run
            if r is None:
                return
            m = re.search(r"\[EHS\] rough estimate: ~(\d+) min", regel)
            if m:
                r["ehs_eta"] = (float(m.group(1)) * 60, time.time())
            m = re.search(r"\[EHS\] (\d+)/(\d+) year-tasks .*eta ([\d.]+) min", regel)
            if m:
                r["ehs_eta"] = (float(m.group(3)) * 60, time.time())
                self.lbl_fase.config(text=f"EHS-evolutie: {m.group(1)}/{m.group(2)} jaartaken")
            if regel.startswith("Liveability hours: temperature-shift projection"):
                self.lbl_fase.config(text="Analyse: HEAT-Lim-projectie …")

        def _bericht(self, m):
            soort = m[0]
            if soort == "kandidaten":
                self.kandidaten = m[1]
                self.cb_kand["values"] = [
                    f"{k.get('name')}, {k.get('admin1', '')} ({k.get('country_code', k.get('country', ''))})"
                    f" – {k.get('population', 0) or 0:,} inw.".replace(",", ".") for k in self.kandidaten]
                if self.kandidaten:
                    self.cb_kand.current(0)
                    self._plaats_gekozen()
            elif soort == "tijd":
                if self.run:
                    self.run["t_net" if m[1] == "net" else "t_cache"].append(m[2])
            elif soort == "kustinfo":
                self.d[m[1]]["info"][m[2]] = m[3]
            elif soort == "jaar":
                v, (j, df, s, l) = m[1], m[2]
                d = self.d[v]
                d["rows"][j] = df
                if s is not None:
                    d["slices"][j] = s
                if l is not None:
                    d["lraw"][j] = l
                if self.run:
                    self.pb.configure(value=len(d["rows"]))
                    self.lbl_fase.config(text=f"{VARIANT_NAAM[v]}: {len(d['rows'])}/{len(self.run['jaren'])} jaren "
                                              f"binnen (laatste: {j})")
                n = len(d["rows"])
                if v == self.v["toon"].get() and (n % 3 == 0 or n == len(self.run["jaren"] if self.run else [])):
                    self._teken_jm()
                if v == "kust" or self.d["kust"]["rows"]:
                    if n % 5 == 0:
                        self._teken_ku()
            elif soort == "jaarfout":
                self.d[m[1]]["fout"].append(m[2])
                self._log(f"[{m[1]}] jaar {m[2]} mislukt: {m[3]}")
            elif soort == "opgehaald":
                v, gestopt = m[1], m[2]
                d = self.d[v]
                self._teken_jm()
                self._teken_ku()
                if gestopt or not d["rows"]:
                    self.lbl_fase.config(text=f"Gestopt: {len(d['rows'])}/{len(self.run['jaren'])} jaren binnen. "
                                              "Start opnieuw om verder te gaan.")
                    return self._klaar()
                ontbreekt = [j for j in self.run["jaren"] if j not in d["rows"]]
                if ontbreekt and v == "kust":
                    self.lbl_fase.config(text=f"Kustcorrectie: {len(d['rows'])}/{len(self.run['jaren'])} jaren. "
                                              "Analyse volgt als alle jaren binnen zijn.")
                    return self._klaar()
                if ontbreekt:
                    self._log(f"Ontbrekende jaren: {ontbreekt} — Klimatos rekent met de jaren die er zijn.")
                self._start_analyse(v)
            elif soort == "analyse":
                v, res = m[1], m[2]
                self.d[v]["res"] = res
                if not res.get("ehs"):
                    self.analyse_duur = res.get("duur_s", self.analyse_duur)
                self._log(f"Klaar: {len(res['gegevens']['plot_paths'])} figuren, Excel {res.get('excel')}")
                self.lbl_fase.config(text=f"Klaar ({VARIANT_NAAM[v]}). Uitvoer: {res['uitmap']}")
                self.v["toon"].set(v)
                self._klaar()
                self._teken_alles()
            elif soort == "rapport":
                self.lbl_fase.config(text="Rapport klaar")
                messagebox.showinfo("Klimatos-rapport", "\n".join(m[1]))
            elif soort == "log":
                self._log(m[1])
            elif soort == "fout":
                self._fout(m[1])
                if self.run is not None and self.run.get("fase") in ("analyse", "EHS-evolutie"):
                    self._klaar()

        def _log(self, tekst):
            tx = self.tab["lg"]["tx"]
            tx.insert("end", tekst + "\n")
            if int(tx.index("end-1c").split(".")[0]) > 6000:
                tx.delete("1.0", "1000.0")
            tx.see("end")

        def _fout(self, tekst):
            self.lbl_fase.config(text=tekst.splitlines()[0][:220])
            self._log("FOUT: " + tekst)

        # ------------------------------------------------------------ tekenen
        def _huidig(self):
            v = self.v["toon"].get()
            return v, self.d[v]

        def _annual(self, d):
            if d["res"] is not None:
                return d["res"]["gegevens"]["annual"]
            if not d["rows"]:
                return None
            return pd.concat([d["rows"][j] for j in sorted(d["rows"])])

        def _ref(self, d):
            if d["res"] is not None:
                return tuple(d["res"]["gegevens"]["ref_window"])
            if d["inv"] is not None and d["inv"].snel:
                j0 = jaren(d["inv"])[0]
                return (j0, j0 + 9)
            return tuple(ks.REFERENCE_PERIOD)

        def _leeg_fig(self, k, tekst):
            t = self.tab[k]
            t["fig"].clear()
            ax = t["fig"].add_subplot(111)
            ax.set_axis_off()
            ax.text(0.5, 0.5, tekst, ha="center", va="center", fontsize=13, transform=ax.transAxes, wrap=True)
            t["cv"].draw_idle()

        def _teken_alles(self):
            for f in (self._kop, self._teken_jm, self._teken_ve, self._teken_st, self._teken_tv, self._teken_ev,
                      self._teken_op, self._teken_lb, self._teken_ku, self._vul_figuren):
                try:
                    f()
                except Exception as ex:
                    self._log(f"tekenfout {f.__name__}: {ex}\n{traceback.format_exc()}")

        def _kop(self):
            v, d = self._huidig()
            res = d["res"]
            self._toon_herkomst(v, d)
            if res is None:
                self.lbl_kop.config(text=f"  {VARIANT_NAAM[v]}: nog geen analyse  ", bg="#dddddd", fg="black")
                self.tegels.leeg("Nog geen analyse voor deze variant. Start een run; de uitkomsten verschijnen hier "
                                 "zodra de analyse klaar is.")
                return
            g = res["gegevens"]
            sdf = res["stats_by_var"]["T_air_max"]
            laatste = sdf[~sdf["is_reference"]].iloc[-1]
            mk = ks.mann_kendall(g["annual"]["T_air_max"].dropna().values)
            ref = g["ref_window"]
            tekst = (f"  {g['meta']['city']} — Tlucht-max venster {int(laatste['start'])}–{int(laatste['end'])}: "
                     f"{'+' if laatste['mean_vs_ref'] >= 0 else ''}{nl(laatste['mean_vs_ref'])} °C t.o.v. "
                     f"{ref[0]}–{ref[1]}; trend {nl(10 * mk['slope'], 2)} °C/decennium"
                     + ("   [SNELLE VERKENNING]" if res.get("snel") else "")
                     + ("   [BEOORDELING KUSTCORRECTIE]" if v == "kust" else "") + "  ")
            kleur = "#c0392b" if laatste["mean_vs_ref"] >= 1.0 else ("#e67e22" if laatste["mean_vs_ref"] > 0.3 else "#2471a3")
            self.lbl_kop.config(text=tekst, bg=kleur, fg="white")
            self._toon_tegels(v, res, laatste, mk, ref, kleur)

        def _toon_tegels(self, v, res, laatste, mk, ref, kleur):
            g = res["gegevens"]
            a = g["annual"]["T_air_max"].dropna()
            p = mk.get("p", np.nan)
            items = [
                dict(titel="Laatste venster t.o.v. referentie",
                     waarde=f"{'+' if laatste['mean_vs_ref'] >= 0 else ''}{nl(laatste['mean_vs_ref'])} °C",
                     sub=f"Tlucht-max {int(laatste['start'])}–{int(laatste['end'])} vs {ref[0]}–{ref[1]}", kleur=kleur),
                dict(titel="Trend jaarmaximum Tlucht", waarde=f"{nl(10 * mk['slope'], 2)} °C/10 j",
                     sub=(f"Mann-Kendall p = {nl(p, 3)}" if np.isfinite(p) else "Mann-Kendall") +
                         f"; {len(a)} jaren", kleur="#5d6d7e"),
            ]
            ev = g.get("event_df")
            if ev is not None and len(ev) and "slope_degC_per_yr" in ev:
                rij = ev[ev["variable"] == "WBGT_event"]
                rij = rij.iloc[0] if len(rij) else ev.iloc[0]
                naam = str(rij["variable"]).replace("_event", "")
                sub = f"{g['event_name']}, {ks.EVENT_TREND_PERIOD[0]}–{ks.EVENT_TREND_PERIOD[1]}"
                if "slope_lo" in rij and np.isfinite(rij["slope_lo"]):
                    sub += f"; 95%: {nl(10 * rij['slope_lo'], 2)} tot {nl(10 * rij['slope_hi'], 2)}"
                items.append(dict(titel=f"Trend {naam} evenement", waarde=f"{nl(10 * rij['slope_degC_per_yr'], 2)} °C/10 j",
                                  sub=sub, kleur="#e67e22"))
                pj = sorted(int(re.search(r"\d{4}", c).group(0)) for c in rij.index
                            if re.fullmatch(r"projected_\d{4}_vs_baseline", str(c)) and np.isfinite(rij[c]))
                if pj:
                    laatst = pj[-1]
                    d_ = float(rij[f"projected_{laatst}_vs_baseline"])
                    items.append(dict(
                        titel=f"Vooruitzicht {naam} evenement {laatst}",
                        waarde=f"{'+' if d_ >= 0 else ''}{nl(d_)} °C",
                        sub="t.o.v. basis; " + ", ".join(
                            f"{j}: {'+' if rij[f'projected_{j}_vs_baseline'] >= 0 else ''}"
                            f"{nl(float(rij[f'projected_{j}_vs_baseline']))}" for j in pj[:-1])
                            + ("; " if len(pj) > 1 else "") + "lineaire doortrekking, geen klimaatscenario",
                        kleur="#c0392b"))
            items.append(dict(titel="Referentieperiode", waarde=f"{ref[0]}–{ref[1]}",
                              sub=("snelle verkenning: eerste 10 opgehaalde jaren" if res.get("snel")
                                   else "referentie van de suite"),
                              kleur="#b9770e" if res.get("snel") else "#117a65"))
            items.append(dict(titel="Kustcorrectie", waarde="toegepast" if v == "kust" else "niet toegepast",
                              sub="beoordelingsrun, niet officieel" if v == "kust" else "zoals de suite (Known issue 14)",
                              kleur="#7d3c98" if v == "kust" else "#5d6d7e"))
            uitleg = ("Historische analyse van ERA5-heranalysedata voor één gridcel, geen stationsmeting. Bij kustplaatsen "
                      "kan ERA5 afwijken van lokale waarnemingen."
                      + (" Snelle verkenning: andere referentieperiode, dus niet vergelijkbaar met een volledige run."
                         if res.get("snel") else ""))
            self.tegels.zet(items, uitleg)

        def _toon_herkomst(self, v, d):
            stad = ""
            if d.get("res") is not None:
                stad = d["res"]["gegevens"]["meta"].get("city", "")
            elif d.get("inv") is not None:
                stad = d["inv"].city.get("name", "")
            elif self.cb_kand.get():
                stad = self.cb_kand.get().split(",")[0]
            uhi = "UHI aan" if self.v["uhi"].get() else "UHI uit"
            self.herkomst.zet(
                f"ERA5-archief (Open-Meteo, {ks.ARCHIVE_MODEL}) via Klimatos_ClimateShift; {stad}", 
                "beoordeling" if v == "kust" else "historisch",
                status_tekst="beoordeling · ERA5 + kustcorrectie" if v == "kust" else "historische analyse",
                extra=uhi,
                niet="een stationsmeting of een klimaatprojectie"
                     + ("; kustcorrectie in beoordeling." if v == "kust" else "."))

        def _teken_jm(self):
            t = self.tab["jm"]
            v, d = self._huidig()
            a = self._annual(d)
            if a is None or a.empty:
                return self._leeg_fig("jm", "Nog geen jaren binnen.")
            fig = t["fig"]
            fig.clear()
            ref = self._ref(d)
            for i, var in enumerate(ks.VARIABLES):
                ax = fig.add_subplot(2, 2, i + 1)
                s = a[var].dropna()
                ok = a.loc[s.index, "valid"].astype(bool) if "valid" in a else pd.Series(True, index=s.index)
                ax.plot(s.index, s.values, "-", color=KLEUR[v], lw=1, alpha=0.5)
                ax.plot(s.index[ok], s.values[ok], "o", color=KLEUR[v], ms=4,
                        label="gecorrigeerd (beoordeling)" if v == "kust" else None)
                if (~ok).any():
                    ax.plot(s.index[~ok], s.values[~ok], "x", color="#999", ms=6, label="onvolledig jaar")
                if v == "kust" and self.d["suite"]["rows"]:
                    b = self._annual(self.d["suite"])
                    if b is not None and var in b:
                        ax.plot(b.index, b[var], "-", color=KLEUR["suite"], lw=1, alpha=0.6, label="suite")
                ax.axvspan(ref[0] - 0.5, ref[1] + 0.5, color="#888", alpha=0.10)
                for th in ks.THRESHOLDS.get(var, []):
                    if s.min() - 3 < th < s.max() + 3:
                        ax.axhline(th, color="#c0392b", lw=0.8, ls=":")
                        ax.text(s.index.min(), th, f" {nl(th, 0)}", va="bottom", fontsize=8, color="#c0392b")
                if len(s) >= ks.PROJECTION_MIN_YEARS:
                    mk = ks.mann_kendall(s.values)
                    if np.isfinite(mk["slope"]):
                        x = np.arange(len(s))
                        ax.plot(s.index, mk["intercept"] + mk["slope"] * x, "--", color="#222", lw=1.4,
                                label=f"Theil-Sen {nl(10 * mk['slope'], 2)} °C/10 j, p={nl(mk['p'], 3)}")
                ax.set_title(VAR_NL.get(var, var))
                if ax.get_legend_handles_labels()[0]:
                    ax.legend(loc="upper left", fontsize=8)
            n = len(a)
            t["lbl"].config(text=(
                f"{VARIANT_NAAM[v]} — {n} jaren. Jaarmaxima uit Klimatos (build_annual_maxima); grijs vlak = "
                f"referentieperiode {ref[0]}–{ref[1]}; stippellijnen = drempels uit Klimatos (THRESHOLDS); trendlijn = "
                "Klimatos mann_kendall (Theil-Sen over de opeenvolgende jaren). × = jaar met te weinig uren. "
                "De grafiek groeit mee terwijl de jaren binnenkomen."))
            t["cv"].draw_idle()

        def _res_of_leeg(self, k):
            v, d = self._huidig()
            if d["res"] is None:
                self._leeg_fig(k, f"{VARIANT_NAAM[v]}: nog geen analyse.\nStart een run; dit verschijnt na de analyse.")
                self.tab[k]["lbl"].config(text="")
                return None
            return d["res"]

        def _teken_ve(self):
            res = self._res_of_leeg("ve")
            if res is None:
                return
            t = self.tab["ve"]
            fig = t["fig"]
            fig.clear()
            for i, var in enumerate(ks.VARIABLES):
                ax = fig.add_subplot(2, 2, i + 1)
                sdf = res["stats_by_var"][var]
                lab = [f"{int(a)}–{int(b)}" for a, b in zip(sdf["start"], sdf["end"])]
                kl = ["#888" if r else ("#c0392b" if m > 0 else "#2471a3")
                      for r, m in zip(sdf["is_reference"], sdf["mean_vs_ref"])]
                ax.bar(range(len(sdf)), sdf["mean_vs_ref"], color=kl)
                th = ks.THRESHOLDS[var][1]
                col = f"RP_gev_{th:g}"
                for x, (m, rp) in enumerate(zip(sdf["mean_vs_ref"], sdf.get(col, [np.nan] * len(sdf)))):
                    if np.isfinite(rp):
                        txt = f"1 op {rp:.0f} j" if rp < 1e4 else "zeer zeldzaam"
                        ax.text(x, m, txt, ha="center", va="bottom" if m >= 0 else "top", fontsize=7)
                ax.set_xticks(range(len(sdf)))
                ax.set_xticklabels(lab, rotation=35, fontsize=8)
                ax.axhline(0, color="#333", lw=0.8)
                ax.set_ylabel("°C t.o.v. referentie")
                ax.set_title(f"{VAR_NL[var]}: venster − referentie (label: {nl(th, 0)} °C)", fontsize=11)
            t["lbl"].config(text=(
                "Bron: Klimatos analyze_variable_windows (stats_by_var). Balk = gemiddeld jaarmaximum per 30-jaarsvenster "
                "min dat van de referentieperiode (grijs). Label = terugkeerperiode van de middelste drempel volgens de "
                "GEV-fit van dat venster. Alle figuren van Klimatos zelf (normaal vs GEV, Q-Q, terugkeerniveaus) staan "
                "onder 'Suite-figuren'."))
            t["cv"].draw_idle()

        def _teken_st(self):
            res = self._res_of_leeg("st")
            if res is None:
                return
            t = self.tab["st"]
            g = res["gegevens"]
            a = g["annual"]
            ref = g["ref_window"]
            vars_ = [ks.STRIPES_VARIABLE] + (["T_air_event"] if "T_air_event" in a else [])
            fig = t["fig"]
            fig.clear()
            for i, var in enumerate(vars_):
                ax = fig.add_subplot(len(vars_), 1, i + 1)
                s = a[var].dropna()
                basis = s.loc[ref[0]:ref[1]].mean()
                an = s - basis
                lim = max(0.5, float(np.nanmax(np.abs(an))))
                norm = TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim)
                cmap = matplotlib.colormaps["RdBu_r"]
                for y, val in an.items():
                    ax.axvspan(y - 0.5, y + 0.5, color=cmap(norm(val)), lw=0)
                ax.set_xlim(s.index.min() - 0.5, s.index.max() + 0.5)
                ax.set_yticks([])
                ax.grid(False)
                ax.set_title(("Jaarmaximum Tlucht" if var == "T_air_max" else "Evenementuren Tlucht (gemiddelde)")
                             + f" — afwijking t.o.v. {ref[0]}–{ref[1]} (±{nl(lim)} °C)", loc="left")
            t["lbl"].config(text=(
                "Warming stripes zoals Klimatos plot_warming_stripes: één balk per jaar, kleur = afwijking van het "
                "gemiddelde van de referentieperiode. De versie van Klimatos zelf, met gearceerde projectiejaren, staat "
                "onder 'Suite-figuren'."))
            t["cv"].draw_idle()

        def _teken_tv(self):
            res = self._res_of_leeg("tv")
            if res is None:
                return
            t = self.tab["tv"]
            acc = res["gegevens"].get("accel_df")
            if acc is None or len(acc) == 0:
                self._leeg_fig("tv", "Geen trendversnellingstoets (te weinig jaren?).")
                return
            fig = t["fig"]
            fig.clear()
            vars_ = list(dict.fromkeys(acc["variable"]))
            for i, var in enumerate(vars_):
                s = acc[acc["variable"] == var].sort_values("breakpoint")
                ax = fig.add_subplot(len(vars_), 2, 2 * i + 1)
                ax.fill_between(s["breakpoint"], 10 * s["diff_ci_lo"], 10 * s["diff_ci_hi"], color="#2471a3", alpha=0.2,
                                label="95 %-interval (bootstrap)")
                ax.plot(s["breakpoint"], 10 * s["slope_diff"], "o-", color="#2471a3", label="verschil na − voor")
                sig = s[s["significant"].astype(bool)]
                ax.plot(sig["breakpoint"], 10 * sig["slope_diff"], "o", color="#c0392b", ms=8, label="significant")
                ax.axhline(0, color="#333", lw=0.8)
                best = s[s["is_best"].astype(bool)]
                if len(best):
                    ax.axvline(best["breakpoint"].iloc[0], color="#7a5b00", ls="--")
                ax.set_xlabel("knikjaar")
                ax.set_ylabel("°C per decennium")
                ax.set_title(f"{var}: verandering van de trend")
                ax.legend(fontsize=8)
                ax2 = fig.add_subplot(len(vars_), 2, 2 * i + 2)
                ax2.plot(s["breakpoint"], 10 * s["slope_before"], "s-", color="#2471a3", label="trend vóór knik")
                ax2.plot(s["breakpoint"], 10 * s["slope_after"], "o-", color="#c0392b", label="trend na knik")
                ax2.set_xlabel("knikjaar")
                ax2.set_ylabel("°C per decennium")
                ax2.set_title("Theil-Sen-trend aan beide kanten")
                ax2.legend(fontsize=8)
            mode = acc["mode"].iloc[0]
            t["lbl"].config(text=(
                f"Bron: Klimatos check_trend_acceleration (modus: {mode}). Per kandidaat-knikjaar een Theil-Sen-trend "
                "ervoor en erna, met een bootstrap-interval voor het verschil. In scanmodus is de 'beste' knik "
                "verkennend (meervoudig toetsen): de significantie is dan optimistisch. Het aerosolmechanisme achter een "
                "knik rond 1980 geldt voor Europa/Noord-Amerika."))
            t["cv"].draw_idle()

        def _tabel(self, tv, df, kolommen, koppen, breedte=None):
            tv.delete(*tv.get_children())
            tv["columns"] = kolommen
            for k, kop in zip(kolommen, koppen):
                tv.heading(k, text=kop)
                tv.column(k, width=(breedte or {}).get(k, 130), anchor="center")
            if df is None:
                return
            for _, r in df.iterrows():
                vals = []
                for k in kolommen:
                    x = r.get(k, "")
                    if isinstance(x, (float, np.floating)):
                        x = nl(float(x), 3 if abs(x) < 0.1 else 2)
                    vals.append(x)
                tv.insert("", "end", values=vals)
            tv.configure(height=min(max(len(df), 1), 5))

        def _teken_ev(self):
            res = self._res_of_leeg("ev")
            t = self.tab["ev"]
            if res is None:
                self._tabel(t["tv"], None, [], [])
                return
            g = res["gegevens"]
            a = g["annual"]
            ev = g.get("event_df")
            if ev is None or "T_air_event" not in a:
                self._leeg_fig("ev", "Geen evenementanalyse (evenement uit, of geen data in de trendperiode).")
                self._tabel(t["tv"], None, [], [])
                return
            ehs = g.get("ehs_df")
            fig = t["fig"]
            fig.clear()
            n = 2 if ehs is not None else 1
            ax = fig.add_subplot(1, n, 1)
            kl = {"T_air_event": "#c0392b", "WBGT_event": "#e67e22", "UTCI_event": "#7d3c98"}
            tp = ks.EVENT_TREND_PERIOD
            for var in ("T_air_event", "WBGT_event", "UTCI_event"):
                if var not in a:
                    continue
                s = a[var].dropna()
                ax.plot(s.index, s.values, "o-", ms=3, lw=1, color=kl[var], label=var.replace("_event", ""))
                r = ev[ev["variable"] == var]
                if len(r):
                    r = r.iloc[0]
                    yy = np.array([tp[0], tp[1]])
                    mid = 0.5 * (tp[0] + tp[1])
                    ax.plot(yy, r["trend_mean"] + r["slope_degC_per_yr"] * (yy - mid), "--", color=kl[var], lw=2)
                    pj = sorted((int(re.search(r"\d{4}", c).group(0)), float(r[c])) for c in r.index
                                if re.fullmatch(r"projected_\d{4}", str(c)) and np.isfinite(r[c]))
                    if pj:
                        ax.plot([tp[1]] + [j for j, _ in pj],
                                [r["trend_mean"] + r["slope_degC_per_yr"] * (tp[1] - mid)] + [v for _, v in pj],
                                ":", color=kl[var], lw=1.5)
                        ax.plot([j for j, _ in pj], [v for _, v in pj], "D", color=kl[var], ms=6,
                                markeredgecolor="white", label=None)
                        if var == "T_air_event":
                            for j, v in pj:
                                ax.annotate(f"{j}\n{nl(v)} °C", (j, v), textcoords="offset points", xytext=(0, 8),
                                            ha="center", fontsize=8, color=kl[var])
            ax.axvspan(tp[0], tp[1], color="#888", alpha=0.08)
            ax.set_title(f"{g['event_name']}: gemiddelde over de evenementuren (±{ks.EVENT_DAY_WINDOW} d)")
            ax.set_ylabel("°C")
            ax.legend(fontsize=8)
            if ehs is not None:
                ax2 = fig.add_subplot(1, n, 2)
                self._ehs_plot(ax2, ehs)
            kol = [c for c in ev.columns if c in ("label", "baseline_mean", "trend_mean", "slope_degC_per_yr", "slope_lo",
                                                    "slope_hi", "mk_p")]
            # Weergave: per doeljaar één kolom 'waarde (verschil met basis)'; de getallen zelf
            # komen ongewijzigd uit build_event_summary.
            ev_t = ev.copy()
            jaren_p = sorted({re.search(r"\d{4}", c).group(0) for c in ev.columns
                              if re.fullmatch(r"projected_\d{4}", str(c))})
            kop = {"label": "grootheid", "baseline_mean": "basis (°C)", "trend_mean": "trendgem. (°C)",
                   "slope_degC_per_yr": "trend (°C/jaar)", "slope_lo": "trend laag", "slope_hi": "trend hoog",
                   "mk_p": "Mann-Kendall p"}
            for jr in jaren_p:
                v, dv = ev_t[f"projected_{jr}"], ev_t.get(f"projected_{jr}_vs_baseline")
                ev_t["p" + jr] = [f"{nl(float(a))} ({'+' if b >= 0 else ''}{nl(float(b))})" if dv is not None
                                  else nl(float(a)) for a, b in zip(v, dv if dv is not None else v)]
                kop["p" + jr] = f"{jr} °C (Δ)"
            kolt = kol + ["p" + jr for jr in jaren_p]
            self._tabel(t["tv"], ev_t, kolt, [kop[c] for c in kolt],
                        {**{"label": 250}, **{c: 112 for c in kolt if c != "label"}})
            t["lbl"].config(text=(
                "Bron: Klimatos analyze_event_window en build_event_summary (normale fits op gemiddelden over de "
                f"evenementuren, trend verankerd op {tp[0]}–{tp[1]}). Streepjeslijn = Theil-Sen-trend in de trendperiode; "
                f"stippellijn met ruitjes = vooruitzicht voor de doeljaren ({', '.join(map(str, ks.EVENT_TARGET_YEARS))}): "
                "Klimatos' lineaire doortrekking van die trend (projected_JJJJ), geen klimaatscenario. "
                + ("Rechts: EHS-evolutie uit Klimatos run_ehs_evolution/build_ehs_summary: EHS per 1000 (Falmouth), "
                   "×-label = verhouding tot de referentie (de robuuste maat), groen = aanpassingsscenario met een "
                   "vroegere start. Foutstreep = trendband (Sen's slope laag/hoog)."
                   if ehs is not None else "EHS-evolutie: knop 'EHS-evolutie berekenen' (lang).")))
            t["cv"].draw_idle()

        def _ehs_plot(self, ax, ehs):
            e = ehs.sort_values("target_year")
            jr = e["target_year"].astype(int).tolist()
            x = np.arange(len(jr) + 1)
            ref = float(e["reference_ehs_per_1000"].iloc[0])
            ax.bar(0, ref, 0.6, color="#888", label="referentie (trendperiode)")
            y = e["ehs_per_1000"].to_numpy(float)
            lo = e["ehs_per_1000_lo"].to_numpy(float)
            hi = e["ehs_per_1000_hi"].to_numpy(float)
            fout = np.where(np.isfinite(lo) & np.isfinite(hi), np.vstack([y - lo, hi - y]), 0.0)
            ax.bar(x[1:] - 0.17, y, 0.34, color="#c0392b", yerr=fout, capsize=3,
                   label=f"start {ks.EVENT_START_HOUR:02d}:{ks.EVENT_START_MINUTE:02d}")
            vroeg = e["ehs_per_1000_early_start"].to_numpy(float)
            ax.bar(x[1:] + 0.17, vroeg, 0.34, color="#1a8a4a",
                   label=f"vroegere start {ks.EHS_ADAPT_START_HOUR:02d}:{ks.EHS_ADAPT_START_MINUTE:02d}")
            for xi, yi, r in zip(x[1:], y, e["ratio_vs_reference"]):
                ax.text(xi - 0.17, yi, f"×{nl(float(r), 2)}", ha="center", va="bottom", fontsize=9)
            ax.set_xticks(x)
            ax.set_xticklabels(["ref."] + [str(j) for j in jr])
            ax.set_ylabel("EHS per 1000 deelnemers")
            ax.set_title("EHS-evolutie (Falmouth-gekalibreerd)")
            ax.legend(fontsize=8)

        def _teken_op(self):
            res = self._res_of_leeg("op")
            if res is None:
                return
            t = self.tab["op"]
            g = res["gegevens"]
            a, adf = g["annual"], g.get("admissions_df")
            if adf is None or "heat_admit_index" not in a:
                return self._leeg_fig("op", "Geen opname-analyse (ENABLE_ADMISSIONS_ERF uit).")
            fig = t["fig"]
            fig.clear()
            ax = fig.add_subplot(1, 2, 1)
            ax.bar(a.index, a["heat_admit_index"], color="#c0392b", width=0.8)
            ax.set_title("Hittegerelateerde opname-index per jaar (ERF, mei–sep)")
            ax.set_ylabel("Σ (exp(β·overschrijding) − 1)")
            ax2 = fig.add_subplot(1, 2, 2)
            lab = [f"{int(s)}–{int(e)}" for s, e in zip(adf["start"], adf["end"])]
            x = np.arange(len(adf))
            ax2.bar(x - 0.2, adf["ratio_ERF_vs_ref"], 0.4, color="#c0392b", label="ERF-index")
            ax2.bar(x + 0.2, adf["ratio_HDD_vs_ref"], 0.4, color="#e67e22", label="hittegraaddagen")
            ax2.axhline(1, color="#333", lw=0.8)
            ax2.set_xticks(x)
            ax2.set_xticklabels(lab, rotation=30, fontsize=8)
            ax2.set_title("Verhouding tot de referentieperiode")
            ax2.legend(fontsize=8)
            t["lbl"].config(text=(
                "Bron: Klimatos heat_admission_indices en analyze_admissions_windows. Blootstelling-responsfunctie van van "
                f"Loenhout et al. 2018 (MMT {nl(ks.ERF_MMT_C, 0)} °C, log-lineaire benadering), op de landelijke "
                "dagmaximumtemperatuur. Een index, geen aantal opnames."))
            t["cv"].draw_idle()

        def _teken_lb(self):
            res = self._res_of_leeg("lb")
            t = self.tab["lb"]
            if res is None:
                self._tabel(t["tv"], None, [], [])
                return
            g = res["gegevens"]
            a = g["annual"]
            if "minMmax_young" not in a:
                self._tabel(t["tv"], None, [], [])
                return self._leeg_fig("lb", "Geen HEAT-Lim-analyse (HEATLim.py niet beschikbaar).")
            fig = t["fig"]
            fig.clear()
            ax = fig.add_subplot(1, 2, 1)
            for p, kl in (("young", "#2471a3"), ("old", "#c0392b")):
                ax.plot(a.index, a[f"hrsBelow_{p}"], "o-", ms=3, color=kl,
                        label=ks.LIVEABILITY_PROFILE_LABEL.get(p, p))
            ax.set_title(f"Uren per jaar onder {nl(ks.LIVEABILITY_ACTIVITY_MET, 1)} MET (beperkt leefbaar)")
            ax.set_ylabel("uren")
            ax.legend(fontsize=8)
            ax2 = fig.add_subplot(1, 2, 2)
            for p, kl in (("young", "#2471a3"), ("old", "#c0392b")):
                ax2.plot(a.index, a[f"minMmax_{p}"], "o-", ms=3, color=kl,
                         label=ks.LIVEABILITY_PROFILE_LABEL.get(p, p))
            ax2.axhline(ks.LIVEABILITY_ACTIVITY_MET, color="#7a5b00", ls="--", lw=1)
            ax2.set_title("Laagste toelaatbare inspanning (min Mmax)")
            ax2.set_ylabel("MET")
            ax2.legend(fontsize=8)
            pr = g.get("liveability_proj_df")
            if pr is not None and len(pr):
                jr = [c for c in pr.columns if re.fullmatch(r"\d{4}", str(c))]
                kol = ["label", "metric", "reference_mean"] + jr
                self._tabel(t["tv"], pr, kol, ["profiel", "maat", "referentie"] + jr,
                            {"label": 220, "metric": 160})
            else:
                self._tabel(t["tv"], None, [], [])
            t["lbl"].config(text=(
                "Bron: Klimatos liveability_year_metrics (HEAT-Lim, Vanos et al. 2023; "
                f"{ks.LIVEABILITY_EXP_TIME} h blootstelling, {ks.LIVEABILITY_SUN}) en run_liveability_projection "
                "(tabel: projectie in uren per jaar). Let op Known issue 14: aan de kust kunnen deze absolute uren te "
                "gunstig zijn; zie het tabblad Kustcorrectie."))
            t["cv"].draw_idle()

        # ---------------------------------------------------- kustcorrectie
        def _teken_ku(self):
            t = self.tab["ku"]
            dsu, dku = self.d["suite"], self.d["kust"]
            c = (dku["inv"] or dsu["inv"]).city if (dku["inv"] or dsu["inv"]) else self._kandidaat()
            fig = t["fig"]
            fig.clear()
            info_txt = ""
            if c:
                try:
                    ld = ek.landdeel(c["latitude"], c["longitude"], 0.10)
                except Exception:
                    ld = None
                buiten = not (ek.FIT_AREA["lat"][0] <= c["latitude"] <= ek.FIT_AREA["lat"][1]
                              and ek.FIT_AREA["lon"][0] <= c["longitude"] <= ek.FIT_AREA["lon"][1])
                eerste = next(iter(dku["info"].values()), {})
                info_txt = (f"{c['name']}: ERA5-cel {'?' if ld is None else f'{ld:.0%}'} land "
                            f"({'kust' if ld is not None and ld < 0.9 else 'binnenland'}); "
                            f"{eerste.get('n_landcellen', '?')} landcellen binnen 30 km"
                            + ("; smal eiland" if eerste.get("eiland") else "")
                            + ("; BUITEN het fitgebied (extrapolatie)" if buiten else "") + ". ")
            gemeen = sorted(set(dsu["rows"]) & set(dku["rows"]))
            jaren_ = sorted(self.cb_kujaar["values"] or [])
            if dku["rows"]:
                self.cb_kujaar["values"] = [str(j) for j in sorted(dku["rows"])]
                if not self.v["ku_jaar"].get() and dku["rows"]:
                    a = pd.concat([dku["rows"][j] for j in sorted(dku["rows"])])
                    self.v["ku_jaar"].set(str(int(a["T_air_max"].idxmax())))
            if not gemeen:
                ax = fig.add_subplot(111)
                ax.set_axis_off()
                ax.text(0.5, 0.5, "Voor de vergelijking zijn beide runs nodig (suite en kustcorrectie).\n"
                                  f"Nu binnen: suite {len(dsu['rows'])} jaren, kustcorrectie {len(dku['rows'])} jaren.",
                        ha="center", va="center", fontsize=13, transform=ax.transAxes)
                t["lbl"].config(text=info_txt)
                self._tabel(t["tv"], None, [], [])
                t["cv"].draw_idle()
                return
            A = pd.concat([dsu["rows"][j] for j in gemeen])
            B = pd.concat([dku["rows"][j] for j in gemeen])
            ax = fig.add_subplot(2, 2, 1)
            for var, kl in (("T_air_max", "#c0392b"), ("WBGT_max", "#e67e22"), ("UTCI_max", "#7d3c98"),
                            ("WBT_max", "#2471a3")):
                ax.plot(gemeen, B[var].values - A[var].values, "o-", ms=3, lw=1, color=kl, label=var)
            ax.axhline(0, color="#333", lw=0.8)
            ax.set_title("Jaarmaxima: gecorrigeerd − suite")
            ax.set_ylabel("°C")
            ax.legend(fontsize=8)
            ax2 = fig.add_subplot(2, 2, 2)
            if "T_air_event" in A:
                for var, kl in (("T_air_event", "#c0392b"), ("WBGT_event", "#e67e22"), ("UTCI_event", "#7d3c98")):
                    if var in A:
                        ax2.plot(gemeen, B[var].values - A[var].values, "o-", ms=3, lw=1, color=kl, label=var)
                ax2.axhline(0, color="#333", lw=0.8)
                ax2.legend(fontsize=8)
            ax2.set_title("Evenementuren: gecorrigeerd − suite")
            ax2.set_ylabel("°C")
            ax3 = fig.add_subplot(2, 2, 3)
            if "hrsBelow_old" in A:
                for p, kl in (("young", "#2471a3"), ("old", "#c0392b")):
                    ax3.plot(gemeen, B[f"hrsBelow_{p}"].values - A[f"hrsBelow_{p}"].values, "o-", ms=3, lw=1, color=kl,
                             label=ks.LIVEABILITY_PROFILE_LABEL.get(p, p))
                ax3.axhline(0, color="#333", lw=0.8)
                ax3.legend(fontsize=8)
            ax3.set_title(f"HEAT-Lim-uren onder {nl(ks.LIVEABILITY_ACTIVITY_MET, 1)} MET: gecorrigeerd − suite")
            ax3.set_ylabel("uren per jaar")
            ax4 = fig.add_subplot(2, 2, 4)
            self._uurdetail(ax4, c)
            # tabel: trends en gemiddelden
            rijen = []
            for var in ("T_air_max", "WBGT_max", "UTCI_max", "T_air_event", "hrsBelow_old"):
                if var not in A:
                    continue
                ma, mb = ks.mann_kendall(A[var].values), ks.mann_kendall(B[var].values)
                rijen.append({"grootheid": var, "gem_suite": A[var].mean(), "gem_kust": B[var].mean(),
                              "verschil": (B[var] - A[var]).mean(), "max_verschil": (B[var] - A[var]).max(),
                              "trend_suite": 10 * ma["slope"], "trend_kust": 10 * mb["slope"]})
            self._tabel(t["tv"], pd.DataFrame(rijen), ["grootheid", "gem_suite", "gem_kust", "verschil", "max_verschil",
                                                         "trend_suite", "trend_kust"],
                        ["grootheid", "gem. suite", "gem. gecorrigeerd", "gem. verschil", "max. verschil",
                         "trend suite /10 j", "trend gecorr. /10 j"], {"grootheid": 160})
            n_k = len(dku["rows"])
            n_tot = len(jaren(dku["inv"])) if dku["inv"] else 0
            t["lbl"].config(text=(
                info_txt + f"Kustcorrectie: {n_k}/{n_tot} jaren. BEOORDELINGSMODUS, geen suitegedrag: per jaar "
                "era5_kustcorrectie.corrigeer_dataframe, toegepast zoals de Data Engine (dauwpunt vast, RH opnieuw, vóór de "
                "UHI; alleen hete dagen). Gefit op 26 KNMI-stations; strikte toets: TXx aan het water −3,5 → −1,9 °C, "
                "nachten aan de kust verschuiven tussen stations (Known issue 14). Trends in de tabel: Klimatos mann_kendall "
                "over de jaren die in beide runs zitten."))
            t["cv"].draw_idle()

        def _uurdetail(self, ax, c):
            try:
                j = int(self.v["ku_jaar"].get())
            except Exception:
                ax.set_axis_off()
                return
            if c is None or not in_cache(c["latitude"], c["longitude"], j, "kust"):
                ax.set_axis_off()
                return
            ruw, _ = ruw_jaar(c["latitude"], c["longitude"], c["timezone"], j)
            corr, info, _ = kust_jaar(c["latitude"], c["longitude"], j, ruw)
            gec = pas_correctie_toe(ruw, corr)
            dag = ruw["T_air_rural"].resample("D").max().idxmax()
            sl = slice(dag - pd.Timedelta(days=1), dag + pd.Timedelta(days=2))
            ax.plot(ruw.loc[sl].index, ruw.loc[sl, "T_air_rural"], color=KLEUR["suite"], lw=2, label="ERA5 (suite)")
            ax.plot(gec.loc[sl].index, gec.loc[sl, "T_air_rural"], color=KLEUR["kust"], lw=2, label="gecorrigeerd")
            ax.set_title(f"Uurverloop rond de heetste dag van {j} ({dag:%d-%m})")
            ax.set_ylabel("°C (landelijk, vóór UHI)")
            ax.legend(fontsize=8)
            import matplotlib.dates as mdates
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m %Hh"))

        # ---------------------------------------------------- suite-figuren
        def _vul_figuren(self):
            t = self.tab["fi"]
            v, d = self._huidig()
            lb = t["lb"]
            lb.delete(0, "end")
            self._paden = []
            if d["res"] is None:
                return self._leeg_fig("fi", f"{VARIANT_NAAM[v]}: nog geen figuren.")
            self._paden = [p for p in d["res"]["gegevens"]["plot_paths"] if os.path.exists(p)]
            for p in self._paden:
                lb.insert("end", Path(p).stem.replace("plot_", ""))
            if self._paden:
                lb.selection_set(0)
                self._toon_figuur()
            t["lbl"].config(text=f"Figuren precies zoals Klimatos ze maakt (map: {d['res']['uitmap']}).")

        def _toon_figuur(self):
            t = self.tab["fi"]
            sel = t["lb"].curselection()
            if not sel or not getattr(self, "_paden", None):
                return
            import matplotlib.image as mpimg
            fig = t["fig"]
            fig.clear()
            ax = fig.add_subplot(111)
            ax.imshow(mpimg.imread(self._paden[sel[0]]))
            ax.set_axis_off()
            t["cv"].draw_idle()

        # ---------------------------------------------------- export
        def _excel(self):
            v, d = self._huidig()
            if d["res"] is None or not d["res"].get("excel"):
                return messagebox.showinfo("Excel", "Er is nog geen analyse voor deze variant.")
            p = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")],
                                             initialfile=Path(d["res"]["excel"]).stem
                                             + ("_kustcorrectie_beoordeling" if v == "kust" else "") + ".xlsx")
            if p:
                shutil.copyfile(d["res"]["excel"], p)
                self.lbl_fase.config(text=f"Excel opgeslagen: {p}")

        def _rapport(self):
            v, d = self._huidig()
            if d["res"] is None:
                return messagebox.showinfo("Rapport", "Er is nog geen analyse voor deze variant.")
            p = filedialog.asksaveasfilename(title="Rapport opslaan als", defaultextension=".docx",
                                             filetypes=[("Word", "*.docx")],
                                             initialfile=Path(d["res"]["rapport_stam"]).name
                                             + ("_kustcorrectie_beoordeling" if v == "kust" else ""))
            if not p:
                return
            g = dict(d["res"]["gegevens"])
            if v == "kust":
                g["meta"] = {**g["meta"], "model": g["meta"].get("model", "") +
                             " — BEOORDELING: ERA5 met land-zeecorrectie (era5_kustcorrectie), geen suitegedrag"}
                g["event_name"] = f"{g['event_name']} (beoordeling kustcorrectie)"
            if d["res"].get("snel"):
                g["meta"] = {**g["meta"], "reference_period": g["meta"].get("reference_period", "")
                             + " (snelle verkenning: eerste 10 opgehaalde jaren)"}
            self.lbl_fase.config(text="Rapport maken …")
            f = self.rpool.submit(maak_rapport, g, str(Path(p).with_suffix("")), d["res"]["uitmap"])
            f.add_done_callback(lambda fu: self.q.put(("rapport", fu.result()) if fu.exception() is None
                                                      else ("fout", f"Rapport mislukt: {fu.exception()}")))

        def _sluit(self):
            self.stop.set()
            for p in (self.ypool, self.apool, self.rpool):
                p.shutdown(wait=False, cancel_futures=True)
            self.root.destroy()
            os._exit(0)

    root = tk.Tk()
    app = App(root)
    if na_start is not None:
        na_start(app, root)
    root.mainloop()


if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()
    os.chdir(HIER)
    _start_ui()
