# -*- coding: utf-8 -*-
"""
hestia_werk_ui.py
=================
Visuele invoer en weergave (Tkinter) voor HESTIA-werk: een virtuele groep
buitenwerkers over een werkdag (bronnenstudie 24-11-2026, keuze 5b: een apart
scherm met dezelfde onderdelen als de andere HESTIA-schermen).

Alle berekeningen komen uit hestia_werk.py, dat de bouwstenen van de suite
aanroept (zie de kop van dat bestand). Weer laden en plaats zoeken gaan via
hestia_loper_ui.WeerBron, net als in de andere HESTIA-schermen.

Status: research software (zie README). Niet voor operationele beslissingen.

Starten:  python hestia_werk_ui.py
"""
from __future__ import annotations

from taal import vt, getal, engels

import os
import queue
import threading
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from hestia_loper_ui import HIER, WeerBron, _opwarmen, _suite, _werker_init
import hestia_werk as hw


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
    import hestia_populatie_ui as hpu
    import ui_gemeen as ug

    LETTER = 12
    matplotlib.rcParams.update({"font.size": 11, "axes.titlesize": 12, "axes.titleweight": "bold",
                                "axes.grid": True, "grid.alpha": 0.3, "legend.fontsize": 9})
    KL = {"lijn": "#1f5fa8", "rood": "#c0392b", "oranje": "#e67e22", "geel": "#d4ac0d",
          "grijs": "#7f8c8d", "groen": "#27ae60", "paars": "#7d3c98"}
    PROFIELEN = hpu.adaptatieprofielen()
    PROFIEL_NL = [vt("Beginner / niet geacclimatiseerd", "Beginner / not acclimatised"), vt("Laag-gemiddeld / deels geacclimatiseerd", "Low-average / partly acclimatised"),
                  vt("Gemiddeld / goed geacclimatiseerd", "Average / well acclimatised"), vt("Gevorderd / volledig geacclimatiseerd", "Advanced / fully acclimatised")]

    nl = getal   # komma (NL) of punt (EN), taal.py

    def pct(fi):
        return f"{fi['point']:.0%} (95%: {fi['lo']:.0%}–{fi['hi']:.0%})"

    KLASSE_TXT = [vt(f"ISO 8996 {k}: {nl(v['w_m2'], 0)} W/m² = {nl(hw.met_uit_w_m2(v['w_m2']), 1)} MET", f"ISO 8996 {hw.klasse_naam(k)}: {nl(v['w_m2'], 0)} W/m² = {nl(hw.met_uit_w_m2(v['w_m2']), 1)} MET")
                  for k, v in hw.ISO_8996_KLASSEN.items()]
    BEROEP_TXT = [f"{n} – {nl(m)} MET (Compendium {c})" for n, c, m, _ in hw.BEROEPEN]
    KLEDING_TXT = [f"{n} – {nl(c)} clo" + (f", WBGT +{nl(cav)} °C" if cav else "")
                   for n, c, cav in hw.KLEDING]

    class App:
        def __init__(self, root):
            self.root = root
            root.title(vt("HESTIA-werk · buitenwerkers over een werkdag  (research software)", "HESTIA work · outdoor workers over a working day  (research software)"))
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
            self.taak: Optional[hw.WerkTaak] = None
            self.resultaat = None
            self.weer = None
            self.futures = []
            self.q = queue.Queue()
            self._plan = None
            self._weer_sleutel = None
            self._laatst = 0.0
            self.extra = None
            self.volledig = False
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
            r = self._sectie(vt("Werk", "Work"), "verplicht",
                             vt("Kies een beroep (2024 Adult Compendium) of een ISO 8996-klasse. "
                             "Beide geven de MET-waarde tijdens het werk.",
                                "Choose an occupation (2024 Adult Compendium) or an ISO 8996 class. "
                             "Both give the MET value during work."))
            self._keuze(r, "soort", vt("Werkzwaarte uit", "Workload from"), [vt("beroep", "occupation"), vt("ISO 8996-klasse", "ISO 8996 class")], vt("beroep", "occupation"))
            self._keuze(r, "beroep", vt("Beroep", "Occupation"), BEROEP_TXT, BEROEP_TXT[0], breed=44)
            self.w["beroep"].bind("<<ComboboxSelected>>", lambda e: self._beroep_gekozen())
            self._keuze(r, "klasse", vt("ISO 8996-klasse", "ISO 8996 class"), KLASSE_TXT, KLASSE_TXT[2], breed=44)
            self._keuze(r, "kleding", vt("Kleding", "Clothing"), KLEDING_TXT, KLEDING_TXT[1], breed=44)
            ttk.Label(r, text=vt("Dampdichte beschermende kleding is niet gemodelleerd.", "Vapour-barrier protective clothing is not modelled."),
                      foreground="#9c4400", wraplength=440).pack(anchor="w", padx=4)

            r = self._sectie(vt("Werkdag", "Working day"), "verplicht",
                             vt("Werk-rustcyclus per uur volgens de indeling van ACGIH/NIOSH. "
                             "Pauzes: UU:MM duur, gescheiden door komma's.",
                                "Work–rest cycle per hour following the ACGIH/NIOSH classes. "
                             "Breaks: HH:MM duration, separated by commas."))
            self._tekst(r, "datum", vt("Datum (JJJJ-MM-DD)", "Date (YYYY-MM-DD)"), pd.Timestamp.now().strftime("%Y-%m-%d"), weer=True)
            self._tekst(r, "begin", vt("Begin (UU:MM)", "Start (HH:MM)"), "07:00")
            self._tekst(r, "einde", vt("Einde (UU:MM)", "End (HH:MM)"), "16:00")
            self._tekst(r, "werk_min", vt("Werk per cyclus (min)", "Work per cycle (min)"), "45")
            self._tekst(r, "rust_min", vt("Rust per cyclus (min)", "Rest per cycle (min)"), "15")
            self._tekst(r, "pauzes", vt("Pauzes", "Breaks"), "10:00 15, 12:30 30, 15:00 15", breed=24)
            self._tekst(r, "rust_met", vt("Rust-MET", "Rest MET"), nl(1.5), hint=vt("staan/zitten", "standing/sitting"))
            self.v["schaduw"] = tk.BooleanVar(value=False)
            ttk.Checkbutton(r, text=vt("Rust en pauze in de schaduw", "Rest and breaks in the shade"), variable=self.v["schaduw"],
                            command=self._gewijzigd).pack(anchor="w", padx=4, pady=2)
            self.lbl_schema = ttk.Label(r, text="", foreground="#555", wraplength=440, justify="left")
            self.lbl_schema.pack(anchor="w", padx=4)

            r = self._sectie(vt("Werkers", "Workers"), "verplicht",
                             vt("Leeftijd 18–67 uit CBS; lichaamsbouw en fitheid als de wandelaars.", "Age 18–67 from CBS (Statistics Netherlands); body build and fitness as the walkers."))
            self._tekst(r, "man", vt("Aandeel mannen", "Share of men"), nl(0.95, 2), hint=vt("0–1; volgt het beroep", "0–1; follows the occupation"))
            self._keuze(r, "profiel", vt("Training/acclimatisatie", "Training/acclimatisation"), PROFIEL_NL, PROFIEL_NL[2], breed=40)

            r = self._sectie(vt("Plaats en weer", "Location and weather"), "verplicht")
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
            self._keuze(r, "route", vt("Route", "Route"), [vt("stad", "urban"), vt("platteland", "rural")], vt("stad", "urban"), weer=True)

            r = self._sectie(vt("Berekening", "Calculation"), "model",
                             vt("Live: snelle schatting bij elke wijziging. Meer werkers = kleinere "
                             "steekproefmarge, maar langzamer.",
                                "Live: quick estimate at every change. More workers = smaller "
                             "sampling margin, but slower."))
            self._tekst(r, "n_snel", vt("Live (snel): werkers", "Live (quick): workers"), "40")
            self._tekst(r, "n_vol", vt("Volledige run: werkers", "Full run: workers"), "300", herreken=False)
            self._tekst(r, "seed", "Seed", "42")
            rij = ttk.Frame(r)
            rij.pack(fill="x", pady=4)
            ttk.Button(rij, text=vt("Volledige run starten", "Start full run"), command=self._volledig).pack(side="left", padx=2)
            ttk.Button(rij, text=vt("Word-rapport", "Word report"), command=self._rapport).pack(side="left", padx=2)

            rechts = ttk.Frame(self.root, padding=(4, 6))
            rechts.pack(side="left", fill="both", expand=True)
            boven = ttk.Frame(rechts)
            boven.pack(fill="x")
            self.pb = ttk.Progressbar(boven, length=ug.px(self.root, 120), maximum=1.0)
            self.pb.pack(side="right")
            ttk.Button(boven, text=vt("Extra grafieken", "More charts"), command=self._open_extra).pack(side="right", padx=8)
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
            ug.tab_uitleg(tab_u, vt("De uitkomst getoetst aan de beroepsgrenzen: de gemiddelde kerntemperatuur van de "
                                 "groep (zoals de Gezondheidsraad 2011 de grens bedoelt), het aandeel werkers boven de "
                                 "grenzen en de WBGT tegen ISO 7243. 'Extra grafieken' toont de 10 werkers met de "
                                 "hoogste kerntemperatuur en de WBGT per uur.",
                                    "The result judged against occupational limits: the mean core temperature of the "
                                 "group (as the Health Council of the Netherlands 2011 intends the limit), the share of "
                                 "workers above the limits and WBGT against ISO 7243. 'More charts' shows the 10 workers "
                                 "with the highest core temperature and WBGT per hour."), LETTER)
            self.tegels = ug.Tegels(tab_u, LETTER)
            self.tegels.pack(fill="x", pady=(2, 4))
            self.herkomst = ug.Herkomst(tab_u, LETTER)
            self.herkomst.pack(side="bottom", fill="x", pady=(4, 0))
            onder = ttk.Frame(tab_u)
            onder.pack(fill="both", expand=True)
            self.txt = tk.Text(onder, height=6, wrap="word", font=("TkDefaultFont", LETTER),
                               relief="flat", background="#f6f6f6", padx=8, pady=6, spacing1=2)
            tsb = ttk.Scrollbar(onder, orient="vertical", command=self.txt.yview)
            self.txt.configure(yscrollcommand=tsb.set)
            self.txt.pack(side="left", fill="both", expand=True)
            tsb.pack(side="left", fill="y")
            self.txt.tag_configure("vet", font=("TkDefaultFont", LETTER, "bold"))
            self.txt.tag_configure("waarsch", foreground="#9c4400")

            self.fig = Figure(figsize=(12, 7.6), dpi=96, constrained_layout=True)
            gs = self.fig.add_gridspec(3, 2)
            self.ax = {"t": self.fig.add_subplot(gs[0, 0]), "wbgt": self.fig.add_subplot(gs[0, 1]),
                       "kern": self.fig.add_subplot(gs[1, 0]), "hr": self.fig.add_subplot(gs[1, 1]),
                       "vocht": self.fig.add_subplot(gs[2, 0]), "phs": self.fig.add_subplot(gs[2, 1])}
            self.canvas = FigureCanvasTkAgg(self.fig, master=tab_g)
            self.canvas.get_tk_widget().pack(fill="both", expand=True)
            self._modus()
            self.root.after(300, self._zoek_plaats)

        def _sectie(self, titel, soort="verplicht", uitleg=""):
            return ug.sectie(self.form, titel, soort, LETTER, uitleg)

        def _rij(self, ouder, label):
            rij = ttk.Frame(ouder)
            rij.pack(fill="x", pady=1)
            ttk.Label(rij, text=label, width=20).pack(side="left")
            return rij

        def _tekst(self, ouder, k, label, std, hint="", weer=False, herreken=True, breed=12):
            rij = self._rij(ouder, label)
            self.v[k] = tk.StringVar(value=std)
            e = ttk.Entry(rij, textvariable=self.v[k], width=breed)
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
        def _f(self, k):
            s = self.v[k].get().strip().replace(",", ".")
            if s == "":
                raise ValueError(vt(f"'{k}' is leeg", f"'{k}' is empty"))
            return float(s)

        def _pauzes(self):
            uit = []
            for deel in self.v["pauzes"].get().split(","):
                deel = deel.strip()
                if not deel:
                    continue
                t, d = deel.split()
                uit.append((t, int(d)))
            return uit

        def _invoer(self) -> hw.WerkInvoer:
            if self.v["soort"].get() == vt("beroep", "occupation"):
                i = BEROEP_TXT.index(self.v["beroep"].get())
                met, label = hw.BEROEPEN[i][2], hw.BEROEPEN[i][0]
            else:
                i = KLASSE_TXT.index(self.v["klasse"].get())
                k = list(hw.ISO_8996_KLASSEN)[i]
                met, label = hw.met_uit_w_m2(hw.ISO_8996_KLASSEN[k]["w_m2"]), vt(f"ISO 8996 {k}", f"ISO 8996 {hw.klasse_naam(k)}")
            schema = hw.WerkSchema(begin=self.v["begin"].get().strip(), einde=self.v["einde"].get().strip(),
                                   werk_min=int(self._f("werk_min")), rust_min=int(self._f("rust_min")),
                                   pauzes=self._pauzes(), rust_met=self._f("rust_met"),
                                   schaduw=bool(self.v["schaduw"].get()))
            return hw.WerkInvoer(plaats=self.v["plaats"].get().strip(),
                                 datum=pd.Timestamp(self.v["datum"].get().strip()).strftime("%Y-%m-%d"),
                                 schema=schema, werk_met=float(met), werk_label=label,
                                 man_aandeel=self._f("man"),
                                 kleding=KLEDING_TXT.index(self.v["kleding"].get()),
                                 profiel=PROFIEL_NL.index(self.v["profiel"].get()))

        def _beroep_gekozen(self):
            """Aandeel mannen volgt het gekozen beroep (modelkeuze, bronnenstudie)."""
            i = BEROEP_TXT.index(self.v["beroep"].get())
            self.v["man"].set(nl(hw.BEROEPEN[i][3], 2))

        def _kandidaat(self):
            i = self.cb_kand.current()
            return self.kandidaten[i] if 0 <= i < len(self.kandidaten) else None

        def _modus(self):
            beroep = self.v["soort"].get() == vt("beroep", "occupation")
            self.w["beroep"].state(["!disabled"] if beroep else ["disabled"])
            self.w["klasse"].state(["disabled"] if beroep else ["!disabled"])
            try:
                inv = self._invoer()
                s = inv.schema
                self.lbl_schema.config(
                    text=vt(f"Werkdag {nl(s.duur_h(), 1)} u; werkaandeel per cyclus {s.werkaandeel():.0%}; "
                         f"werk-MET {nl(inv.werk_met, 1)} ({nl(hw.w_m2_uit_met(inv.werk_met), 0)} W/m²).",
                            f"Working day {nl(s.duur_h(), 1)} h; work share per cycle {s.werkaandeel():.0%}; "
                         f"work MET {nl(inv.werk_met, 1)} ({nl(hw.w_m2_uit_met(inv.werk_met), 0)} W/m²).")
                         + ("" if not s.fouten() else vt("  Let op: ", "  Note: ") + "; ".join(s.fouten())))
            except Exception:
                self.lbl_schema.config(text="")

        # --------------------------------------------------- gebeurtenissen
        def _gewijzigd(self, vertraging=900):
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
                fouten = inv.fouten()
                if fouten:
                    raise ValueError("; ".join(fouten))
                n = int(self._f("n_vol" if volledig else "n_snel"))
                seed = int(self._f("seed"))
                if not 1 <= n <= 5000:
                    raise ValueError(vt("aantal werkers: 1 t/m 5000", "number of workers: 1 to 5000"))
            except Exception as ex:
                self._fout(vt(f"Invoer: {ex}", f"Input: {ex}"))
                return
            excel = self.v["bron"].get().startswith("Data")
            route = ("stad", "platteland")[max(0, self.w["route"].current())]   # sleutel voor de suite
            s, e = inv.venster()
            if excel:
                pad = self.v["excel"].get().strip()
                if not pad:
                    self._fout(vt("Kies een Data Engine-bestand.", "Choose a Data Engine file."))
                    return
                sleutel = ("excel", pad, route, inv.datum, inv.schema.begin, inv.schema.einde)
            else:
                kand = self._kandidaat()
                if kand is None:
                    self._fout(vt("Kies eerst een plaats (Zoek).", "First choose a location (Search)."))
                    return
                sleutel = ("online", kand.get("id", (kand["latitude"], kand["longitude"])), inv.datum, route)
            self._annuleer()
            self.gen += 1
            gen = self.gen
            self.volledig = volledig

            def start(w):
                self._start(gen, inv, w, n, seed)

            if sleutel == self._weer_sleutel and self.weer is not None:
                start(self.weer)
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

        def _start(self, gen, inv, weer, n, seed):
            if gen != self.gen:
                return
            self.lbl_status.config(text=vt("Groep werkers trekken …", "Drawing the group of workers …"))
            self.root.update_idletasks()
            try:
                _, tf, af = PROFIELEN[inv.profiel]
                t = hw.voorbereiden(inv, weer.df, weer.lat, weer.lon, weer.tz, n, seed, tf, af, gen)
            except Exception as ex:
                self._fout(str(ex))
                return
            self.taak, self.resultaat = t, None
            self.futures = [self.pool.submit(hw.werker_lid, (gen, i, a, weer.aqi))
                            for i, a in enumerate(t.args)]
            for f in self.futures:
                f.add_done_callback(self._klaar)
            self._teken(None)
            self._kop(None)
            self._toon_tekst()
            self.pb["value"] = 0
            self.lbl_status.config(text=f"{'Volledige run' if self.volledig else 'Snelle schatting'}: 0/{t.n}")

        def _klaar(self, f):
            if f.cancelled():
                return
            try:
                self.q.put(("lid",) + f.result())
            except Exception as ex:
                self.q.put(("fout", vt(f"Werker mislukt: {ex}\n{traceback.format_exc()}", f"Worker failed: {ex}\n{traceback.format_exc()}"), None))

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
                            self._weer_sleutel, self.weer = sleutel, w
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
                            self._teken(r)
                            self._kop(r)
                            self._toon_tekst()
                            self._teken_extra()
                            self.lbl_status.config(
                                text=vt(f"Klaar: {'volledige run' if self.volledig else 'snelle schatting'}, "
                                     f"n = {r['n']} (seed {r['seed']})",
                                        f"Done: {'full run' if self.volledig else 'quick estimate'}, "
                                     f"n = {r['n']} (seed {r['seed']})"))
                    elif s == "fout":
                        if m[2] is None or m[2] == self.gen:
                            self._fout(m[1])
            except queue.Empty:
                pass
            if nieuw and self.taak is not None:
                t = self.taak
                k = len(t.res)
                self.pb["value"] = k / t.n
                self.lbl_status.config(text=f"{'Volledige run' if self.volledig else 'Snelle schatting'}: {k}/{t.n}")
                self.tegels.leeg(vt(f"Berekenen … {k}/{t.n} werkers.", f"Calculating … {k}/{t.n} workers."))
                nu = time.monotonic()
                if k == t.n or nu - self._laatst >= 1.5:
                    self._laatst = nu
                    self._teken(None)
                if k == t.n:
                    self.lbl_status.config(text=vt("Uitkomst samenvatten (beroepsgrenzen, WBGT, PHS) …", "Summarising the result (occupational limits, WBGT, PHS) …"))
                    gen = t.gen

                    def werk():
                        try:
                            self.q.put(("eind", gen, hw.afronden(t)))
                        except Exception as ex:
                            self.q.put(("fout", vt(f"Samenvatten mislukt: {ex}\n{traceback.format_exc()}", f"Summary failed: {ex}\n{traceback.format_exc()}"), gen))
                    threading.Thread(target=werk, daemon=True).start()

        # ------------------------------------------------------- tekenen
        def _x(self, ax):
            ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=8))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

        def _rust_banden(self, ax, tijden, fase):
            """Grijze banden voor rust en pauze."""
            i = 1
            while i < len(fase):
                if fase[i] != "werk":
                    j = i
                    while j + 1 < len(fase) and fase[j + 1] != "werk":
                        j += 1
                    ax.axvspan(tijden[i - 1], tijden[j], color="#bbbbbb" if fase[i] == "pauze" else "#dddddd",
                               alpha=0.45, lw=0, zorder=0)
                    i = j + 1
                else:
                    i += 1

        def _teken(self, r):
            for a in self.ax.values():
                a.clear()
            t = self.taak
            if t is None:
                self.canvas.draw_idle()
                return
            tijden = [pd.Timestamp(x["time"]).tz_localize(None) for x in t.interp]
            sporen = [t.res[i] for i in sorted(t.res)]
            n_txt = f"n = {t.n}" if r is not None else vt(f"voorlopig, {len(sporen)}/{t.n}", f"provisional, {len(sporen)}/{t.n}")
            # weer
            a = self.ax["t"]
            temp = [x["temp"] for x in t.interp]
            a.plot(tijden, temp, color=KL["rood"], lw=2, label=vt("luchttemperatuur", "air temperature"))
            a.plot(tijden, [x["mrt"] for x in t.interp], color=KL["oranje"], lw=1.2, ls="--",
                   label=vt("stralingstemperatuur (MRT)", "mean radiant temperature (MRT)"))
            a.set_title(vt("Luchttemperatuur en straling", "Air temperature and radiation"))
            a.set_ylabel("°C")
            a.legend(loc="upper left")
            a = self.ax["wbgt"]
            if r is not None:
                om = r["omgeving"]
                a.plot(tijden, om["wbgt"], color=KL["oranje"], lw=2, label=vt("WBGT in de zon", "WBGT in the sun"))
                if t.inv.schema.schaduw:
                    a.plot(tijden, om["wbgt_schaduw"], color=KL["grijs"], lw=1.2, ls="--",
                           label=vt("WBGT in de schaduw", "WBGT in the shade"))
                for u in r["samen"]["uren"]:
                    x0 = u["uur"].tz_localize(None)
                    a.hlines(u["grens"], x0, x0 + pd.Timedelta(hours=1), color=KL["rood"], lw=2)
                a.plot([], [], color=KL["rood"], lw=2, label=vt("ISO 7243-grens (per uur, bij gemiddelde M)", "ISO 7243 limit (per hour, at mean M)"))
                a.legend(loc="upper left")
            a.set_title(vt("WBGT en de ISO 7243-grens", "WBGT and the ISO 7243 limit"))
            a.set_ylabel("°C")
            # kern
            if sporen:
                tm = hw._matrix(sporen, "t_rect")
                k = self.ax["kern"]
                with np.errstate(all="ignore"):
                    import warnings
                    warnings.simplefilter("ignore", RuntimeWarning)
                    gem, lo, hi = np.nanmean(tm, 0), np.nanpercentile(tm, 5, 0), np.nanpercentile(tm, 95, 0)
                    k.fill_between(tijden, lo, hi, color=KL["lijn"], alpha=0.18, lw=0, label="p5–p95")
                    k.plot(tijden, gem, color=KL["lijn"], lw=2, label=vt("groepsgemiddelde", "group mean"))
                    k.axhline(hw.T_KERN_GRENS_NIET_ACCL, color=KL["oranje"], lw=1.2, ls=":",
                              label=vt("38,0 °C (niet geacclimatiseerd)", "38.0 °C (not acclimatised)"))
                    k.axhline(hw.T_KERN_GRENS_ACCL, color=KL["rood"], lw=1.2, ls=":",
                              label=vt("38,5 °C (geacclimatiseerd, geselecteerd)", "38.5 °C (acclimatised, selected)"))
                    g42 = hm.T_THERMAL_ONLY_CRITICAL
                    if np.nanmax(hi) >= g42 - 0.3:
                        k.axhline(g42, color="#6e0b0b", lw=1.4, ls="--")
                        k.text(0.01, g42, vt(f" {nl(g42, 0)} °C: model buiten getoetst gebied", f" {nl(g42, 0)} °C: model outside its tested range"),
                               transform=k.get_yaxis_transform(), va="bottom", fontsize=8, color="#6e0b0b")
                    k.set_title(vt(f"Kerntemperatuur T_rect   ({n_txt})", f"Core temperature T_rect   ({n_txt})"))
                    k.set_ylabel("°C")
                    k.legend(loc="lower right")
                    hrm = hw._matrix(sporen, "hr")
                    h = self.ax["hr"]
                    h.fill_between(tijden, np.nanpercentile(hrm, 5, 0), np.nanpercentile(hrm, 95, 0),
                                   color=KL["paars"], alpha=0.18, lw=0, label="p5–p95")
                    h.plot(tijden, np.nanmean(hrm, 0), color=KL["paars"], lw=2, label=vt("gemiddelde", "mean"))
                    h.axhline(hw.HR_WERKDAG_GEMIDDELD, color=KL["oranje"], lw=1, ls=":",
                              label=vt("110/min: grens daggemiddelde (NIOSH)", "110/min: limit for the day mean (NIOSH)"))
                    h.set_title(vt(f"Hartslag (CVR-model)   ({n_txt})", f"Heart rate (CVR model)   ({n_txt})"))
                    h.set_ylabel(vt("slagen/min", "beats/min"))
                    h.legend(loc="lower right")
                    dm = hw._matrix(sporen, "dehyd_pct")
                    v = self.ax["vocht"]
                    v.fill_between(tijden, np.nanpercentile(dm, 5, 0), np.nanpercentile(dm, 95, 0),
                                   color="#2471a3", alpha=0.18, lw=0, label="p5–p95")
                    v.plot(tijden, np.nanmean(dm, 0), color="#2471a3", lw=2, label=vt("gemiddelde", "mean"))
                    v.axhline(hw.GEWICHTSVERLIES_GRENS_PCT, color=KL["oranje"], lw=1, ls=":",
                              label=vt("1,5 % (ACGIH)", "1.5 % (ACGIH)"))
                    v.set_title(vt("Netto vochtverlies (na drinken)", "Net fluid loss (after drinking)"))
                    v.set_ylabel(vt("% lichaamsgewicht", "% body mass"))
                    v.legend(loc="upper left")
            p = self.ax["phs"]
            if r is not None:
                s = r["samen"]
                p.plot(tijden, s["gem"], color=KL["lijn"], lw=2, label=vt("HESTIA (JOS-3), groepsgemiddelde", "HESTIA (JOS-3), group mean"))
                p.plot(tijden, r["phs"]["t_re"], color=KL["groen"], lw=2, ls="--",
                       label=vt("ISO 7933 PHS, gemiddelde werker", "ISO 7933 PHS, average worker"))
                p.legend(loc="lower right")
                if r["phs"]["stappen_buiten"]:
                    p.text(0.01, 0.98, vt(f"PHS buiten geldigheidsgebied in {r['phs']['stappen_buiten']} van "
                                       f"{r['phs']['stappen']} stappen",
                                          f"PHS outside its validity range in {r['phs']['stappen_buiten']} of "
                                       f"{r['phs']['stappen']} steps"), transform=p.transAxes, va="top",
                           fontsize=8, color="#9c4400")
            p.set_title(vt("Controle: HESTIA tegen ISO 7933 (PHS)", "Check: HESTIA against ISO 7933 (PHS)"))
            p.set_ylabel("°C")
            for a in self.ax.values():
                self._rust_banden(a, tijden, t.fase)
                a.set_xlim(tijden[0], tijden[-1])
                self._x(a)
            self.canvas.draw_idle()

        def _kop(self, r):
            if r is None:
                self.lbl_kop.config(text="  —  ", bg="#dddddd", fg="black")
                return
            s = r["samen"]
            g = s["grens_hoofd"]
            boven = s["gem_max"] >= g
            self.lbl_kop.config(
                text=vt(f"  Groepsgemiddelde kerntemperatuur max. {nl(s['gem_max'], 2)} °C  ·  grens {nl(g)} °C: "
                     f"{'OVERSCHREDEN' if boven else 'niet overschreden'}  ",
                        f"  Group-mean core temperature max. {nl(s['gem_max'], 2)} °C  ·  limit {nl(g)} °C: "
                     f"{'EXCEEDED' if boven else 'not exceeded'}  "),
                bg="#c0392b" if boven else "#27ae60", fg="white")

        def _toon_tegels(self):
            r = self.resultaat
            if r is None:
                return
            s = r["samen"]
            uren_boven = sum(u["boven"] for u in s["uren"])

            def tijd(x):
                return x.strftime("%H:%M") if x is not None else vt("niet bereikt", "not reached")
            items = [
                dict(titel=vt("Groepsgemiddelde kerntemp.", "Group-mean core temp."), waarde=f"{nl(s['gem_max'], 2)} °C",
                     sub=vt(f"38,0 °C om {tijd(s['gem_tijd_380'])}; 38,5 °C om {tijd(s['gem_tijd_385'])}", f"38.0 °C at {tijd(s['gem_tijd_380'])}; 38.5 °C at {tijd(s['gem_tijd_385'])}"),
                     kleur=KL["rood"] if s["gem_max"] >= s["grens_hoofd"] else KL["groen"]),
                dict(titel=vt("Werkers ooit ≥ 38,0 °C", "Workers ever ≥ 38.0 °C"), waarde=f"{s['fi_380']['point']:.0%}",
                     sub=f"95%: {s['fi_380']['lo']:.0%}–{s['fi_380']['hi']:.0%}; ≥ {nl(38.5)} °C: "
                         f"{s['fi_385']['point']:.0%}", kleur=KL["oranje"]),
                dict(titel=vt("Vochtverlies ≥ 1,5 %", "Fluid loss ≥ 1.5 %"), waarde=f"{s['fi_dehyd']['point']:.0%}",
                     sub=vt("netto, na drinken naar dorst", "net, drinking to thirst"), kleur="#2471a3"),
                dict(titel=vt("Hartslag", "Heart rate"), waarde=f"{nl(s['hr_dag_gem'], 0)}/min",
                     sub=vt(f"daggemiddelde (grens 110); > 180 − leeftijd: {s['fi_hr']['point']:.0%}", f"day mean (limit 110); > 180 − age: {s['fi_hr']['point']:.0%}"),
                     kleur=KL["paars"]),
                dict(titel=vt("WBGT boven ISO 7243", "WBGT above ISO 7243"), waarde=vt(f"{uren_boven} van {len(s['uren'])} uur", f"{uren_boven} of {len(s['uren'])} hours"),
                     sub=vt("geacclimatiseerd", "acclimatised") if s["geacclimatiseerd"] else vt("niet geacclimatiseerd", "not acclimatised"),
                     kleur=KL["rood"] if uren_boven else KL["groen"]),
            ]
            self.tegels.zet(items, vt("Grenzen: ACGIH TLV (38,0/38,5 °C; 1,5 %; 180 − leeftijd), NIOSH 2016 "
                                   "(110/min), ISO 7243 via Gezondheidsraad 2011.",
                                      "Limits: ACGIH TLV (38.0/38.5 °C; 1.5 %; 180 − age), NIOSH 2016 "
                                   "(110/min), ISO 7243 via the Health Council of the Netherlands 2011."))
            w = self.weer
            hist = pd.Timestamp(r["invoer"].datum) < pd.Timestamp.now().normalize()
            self.herkomst.zet(
                f"{w.label}; {w.city.get('name', '')}, route {self.v['route'].get()}",
                "historisch" if hist else "prognose",
                status_tekst=vt("simulatie · ", "simulation · ") + (vt("historisch weer", "historical weather") if hist else vt("verwachtingsweer", "forecast weather")),
                extra=vt(f"model: HESTIA-werk (hestia_werk.py), n = {r['n']}, seed {r['seed']}", f"model: HESTIA work (hestia_werk.py), n = {r['n']}, seed {r['seed']}"),
                niet=vt("een EHS-kans; de collaps-kalibratie van HESTIA geldt voor lopers", "an EHS probability; the HESTIA collapse calibration applies to runners"))

        def _toon_tekst(self):
            self._toon_tegels()
            t, r = self.taak, self.resultaat
            self.txt.config(state="normal")
            self.txt.delete("1.0", "end")
            if t is None:
                self.txt.config(state="disabled")
                return
            ins = self.txt.insert
            inv = t.inv
            naam, tf, af = PROFIELEN[inv.profiel]
            ins("end", vt("Opzet: ", "Set-up: "), "vet")
            ins("end", vt(f"{inv.werk_label}, werk-MET {nl(inv.werk_met)}; werkdag {inv.schema.begin}–"
                       f"{inv.schema.einde}, cyclus {inv.schema.werk_min}/{inv.schema.rust_min} min, pauzes "
                       f"{', '.join(f'{a} ({d} min)' for a, d in inv.schema.pauzes) or 'geen'}; rust-MET "
                       f"{nl(inv.schema.rust_met)}{', rust in de schaduw' if inv.schema.schaduw else ''}; "
                       f"kleding {hw.KLEDING[inv.kleding][0]}; {PROFIEL_NL[inv.profiel]} (training {nl(tf, 2)}, "
                       f"acclimatisatie {nl(af, 2)}); aandeel mannen {nl(inv.man_aandeel, 2)}.\n",
                          f"{inv.werk_label}, work MET {nl(inv.werk_met)}; working day {inv.schema.begin}–"
                       f"{inv.schema.einde}, cycle {inv.schema.werk_min}/{inv.schema.rust_min} min, breaks "
                       f"{', '.join(f'{a} ({d} min)' for a, d in inv.schema.pauzes) or 'none'}; rest MET "
                       f"{nl(inv.schema.rust_met)}{', rest in the shade' if inv.schema.schaduw else ''}; "
                       f"clothing {hw.KLEDING[inv.kleding][0]}; {PROFIEL_NL[inv.profiel]} (training {nl(tf, 2)}, "
                       f"acclimatisation {nl(af, 2)}); share of men {nl(inv.man_aandeel, 2)}.\n"))
            if r is None:
                self.txt.config(state="disabled")
                return
            s = r["samen"]
            ins("end", vt("\nKerntemperatuur. ", "\nCore temperature. "), "vet")
            g = s["grens_hoofd"]
            ins("end", vt(f"Het groepsgemiddelde komt maximaal op {nl(s['gem_max'], 2)} °C. De grens voor deze groep is "
                       f"{nl(g)} °C ({'geacclimatiseerd' if s['geacclimatiseerd'] else 'niet geacclimatiseerd'}); "
                       f"die wordt {'overschreden' if s['gem_max'] >= g else 'niet overschreden'}. "
                       f"Van de werkers komt {pct(s['fi_380'])} ooit op of boven 38,0 °C en {pct(s['fi_385'])} op "
                       f"of boven 38,5 °C. De Gezondheidsraad (2011) bedoelt de grens van 38 °C voor het "
                       f"groepsgemiddelde, niet voor één persoon: fitte mensen gaan er zonder klachten overheen.\n",
                          f"The group mean reaches at most {nl(s['gem_max'], 2)} °C. The limit for this group is "
                       f"{nl(g)} °C ({'acclimatised' if s['geacclimatiseerd'] else 'not acclimatised'}); "
                       f"it is {'exceeded' if s['gem_max'] >= g else 'not exceeded'}. "
                       f"Of the workers, {pct(s['fi_380'])} ever reach 38.0 °C or more and {pct(s['fi_385'])} "
                       f"38.5 °C or more. The Health Council of the Netherlands (2011) intends the 38 °C limit for "
                       f"the group mean, not for one person: fit people exceed it without complaints.\n"))
            ins("end", vt("Vocht en hart. ", "Fluid and heart. "), "vet")
            ins("end", vt(f"Netto vochtverlies ≥ 1,5 % bij {pct(s['fi_dehyd'])} (werkers drinken naar dorst, zoals in "
                       f"de loopsimulatie). Gemiddelde hartslag over de dag {nl(s['hr_dag_gem'], 0)}/min "
                       f"(NIOSH: ongeveer 110 voor een volle dienst); {pct(s['fi_hr'])} komt minstens 5 min "
                       f"boven 180 − leeftijd.\n",
                          f"Net fluid loss ≥ 1.5 % in {pct(s['fi_dehyd'])} (workers drink to thirst, as in "
                       f"the running simulation). Mean heart rate over the day {nl(s['hr_dag_gem'], 0)}/min "
                       f"(NIOSH: about 110 for a full shift); {pct(s['fi_hr'])} spend at least 5 min "
                       f"above 180 − age.\n"))
            if s["fi_42"]["k"] > 0:
                ins("end", vt(f"Let op: {pct(s['fi_42'])} van de werkers komt boven {nl(s['t_kritiek'], 0)} °C. Daar is "
                           f"het model niet getoetst, en in werkelijkheid stopt een werker eerder of wordt hij "
                           f"onwel. Het model laat niemand stoppen; waarden boven {nl(s['t_kritiek'], 0)} °C zijn "
                           f"geen voorspelling.\n",
                              f"Note: {pct(s['fi_42'])} of the workers exceed {nl(s['t_kritiek'], 0)} °C. The model has not "
                           f"been tested there, and in reality a worker stops earlier or becomes unwell. The "
                           f"model lets nobody stop; values above {nl(s['t_kritiek'], 0)} °C are "
                           f"not predictions.\n"), "waarsch")
            ins("end", vt("Werkzwaarte. ", "Workload. "), "vet")
            ins("end", vt(f"{pct(s['fi_pct50'])} van de werkers werkt boven 50 % van de eigen VO2max; dat houdt men "
                       f"in de praktijk geen hele dag vol zonder langzamer te gaan. Het model laat het tempo "
                       f"bewust staan (geen tempo-regeling).",
                          f"{pct(s['fi_pct50'])} of the workers work above 50 % of their own VO2max; in practice "
                       f"nobody keeps that up for a whole day without slowing down. The model deliberately keeps "
                       f"the pace (no pacing)."))
            if s["fi_pct50"]["point"] > 0.5:
                ins("end", vt(" De gekozen werk-MET is voor de meeste werkers niet een hele dag vol te houden. Een "
                           "Compendium-waarde geldt tijdens de handeling zelf, niet als gemiddelde over de dienst; "
                           "kies dan een lagere ISO 8996-klasse of een langere rust per cyclus.",
                              " For most workers the chosen work MET cannot be sustained for a whole day. A "
                           "Compendium value applies during the task itself, not as a mean over the shift; "
                           "choose a lower ISO 8996 class or a longer rest per cycle."), "waarsch")
            if s["met_plafond_aandeel"] > 0:
                ins("end", vt(f" Bij {s['met_plafond_aandeel']:.0%} van de werkers begrensde het hart de werklast "
                           f"(fysiek plafond).",
                              f" For {s['met_plafond_aandeel']:.0%} of the workers the heart limited the workload "
                           f"(physical ceiling)."), "waarsch")
            ins("end", "\n")
            ins("end", vt("WBGT (ISO 7243). ", "WBGT (ISO 7243). "), "vet")
            boven = [u["uur"].strftime("%H") + vt(" uur", ":00") for u in s["uren"] if u["boven"]]
            ins("end", (vt("Boven de grens in: ", "Above the limit at: ") + ", ".join(boven) + ". ") if boven else vt("Geen uur boven de grens. ", "No hour above the limit. "))
            ins("end", vt("Tijdgewogen WBGT en stofwisseling per klokuur; kledingcorrectie meegeteld.\n", "Time-weighted WBGT and metabolic rate per clock hour; clothing correction included.\n"))
            ph = r["phs"]
            ins("end", vt("Controle ISO 7933 (PHS). ", "Check ISO 7933 (PHS). "), "vet")
            ins("end", vt(f"Gemiddelde werker: rectale temperatuur maximaal {nl(max(ph['t_re']), 2)} °C, zweetverlies "
                       f"{nl(ph['water_g'][-1] / 1000.0, 1)} L (PHS rekent bruto, zonder drinken). HESTIA: "
                       f"{nl(s['gem_max'], 2)} °C.",
                          f"Average worker: rectal temperature at most {nl(max(ph['t_re']), 2)} °C, sweat loss "
                       f"{nl(ph['water_g'][-1] / 1000.0, 1)} L (PHS counts gross, without drinking). HESTIA: "
                       f"{nl(s['gem_max'], 2)} °C."))
            if ph["stappen_buiten"]:
                ins("end", vt(f" PHS valt in {ph['stappen_buiten']} van {ph['stappen']} stappen buiten het "
                           f"geldigheidsgebied van de norm.",
                              f" PHS falls outside the validity range of the standard in {ph['stappen_buiten']} of "
                           f"{ph['stappen']} steps."), "waarsch")
            ins("end", vt("\n\nNiet gemodelleerd: ", "\n\nNot modelled: "), "vet")
            ins("end", vt("dampdichte beschermende kleding; vrijwillig langzamer werken; nagloei bij het stoppen; "
                       "een EHS-kans (de kalibratie geldt voor lopers). Leeftijd uit CBS, lichaamsbouw en fitheid "
                       "als bij de wandelaars (bronnenstudie 24-11-2026).",
                          "vapour-barrier protective clothing; voluntary slowing down; after-glow on stopping; "
                       "an EHS probability (the calibration applies to runners). Age from CBS, body build and "
                       "fitness as for the walkers (source study 24-11-2026)."), "waarsch")
            self.txt.config(state="disabled")

        def _fout(self, tekst):
            self.tegels.leeg(vt("Geen uitkomst: zie de melding hieronder.", "No result: see the message below."))
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
            w.title(vt("HESTIA-werk: extra grafieken", "HESTIA work: more charts"))
            bw, bh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            w.geometry(f"{min(1500, bw - 60)}x{min(900, bh - 100)}+40+30")
            ug.maximaliseer(w)
            nb = ttk.Notebook(w)
            nb.pack(fill="both", expand=True)
            self.nb_extra = nb
            self.ex = {}
            for naam, titel in (("top", vt("  Top 10 werkers  ", "  Top 10 workers  ")), ("uur", vt("  WBGT per uur  ", "  WBGT per hour  "))):
                f = ttk.Frame(nb, padding=4)
                nb.add(f, text=titel)
                if naam == "top":
                    kol = ("nr", "geslacht", "leeftijd", "vo2", "met", "piek", "vocht", "hr")
                    kop = ("#", vt("geslacht", "sex"), vt("leeftijd", "age"), "VO2max", vt("werk-MET", "work MET"), vt("piek T_rect", "peak T_rect"), vt("max vocht %", "max fluid %"),
                           "max HR")
                    st = ttk.Style()
                    st.configure("Top.Treeview", rowheight=ug.px(self.root, 24))
                    tv = ttk.Treeview(f, columns=kol, show="headings", height=10, style="Top.Treeview")
                    for c, h in zip(kol, kop):
                        tv.heading(c, text=h)
                        tv.column(c, width=ug.px(self.root, 100), anchor="center")
                    tv.pack(fill="x")
                    self.ex["tv"] = tv
                fig = Figure(figsize=(12, 6), dpi=96, constrained_layout=True)
                ax = fig.add_subplot(111)
                c = FigureCanvasTkAgg(fig, master=f)
                c.get_tk_widget().pack(fill="both", expand=True)
                self.ex[naam] = (fig, ax, c)

            def sluit():
                self.extra = None
                w.destroy()
            w.protocol("WM_DELETE_WINDOW", sluit)
            self.extra = w
            self._teken_extra()

        def _teken_extra(self):
            if self.extra is None or self.resultaat is None:
                return
            r = self.resultaat
            sporen = r["sporen"]
            tijden = [pd.Timestamp(x["time"]).tz_localize(None) for x in r["interp"]]
            top = hw.top_tien(sporen)
            tv = self.ex["tv"]
            tv.delete(*tv.get_children())
            fig, ax, c = self.ex["top"]
            ax.clear()
            for rang, j in enumerate(top, 1):
                p = r["profielen"][j]
                sp = sporen[j]
                tv.insert("", "end", values=(
                    rang, vt("man", "man") if p.gender == "male" else vt("vrouw", "woman"), p.age, nl(p.vo2max), nl(sp[-1]["met_werk"], 2),
                    nl(max(x["t_rect"] for x in sp), 2), nl(max(x["dehyd_pct"] for x in sp), 2),
                    nl(np.nanmax([x["hr"] for x in sp]), 0)))
                ax.plot(tijden, [x["t_rect"] for x in sp], lw=1.4,
                        label=f"#{rang}: {'m' if p.gender == 'male' else 'v'}, {p.age} j")
            ax.axhline(38.0, color=KL["oranje"], ls=":", lw=1.2)
            ax.axhline(38.5, color=KL["rood"], ls=":", lw=1.2)
            self._rust_banden(ax, tijden, r["fase"])
            ax.set_title(vt("De 10 werkers met de hoogste kerntemperatuur", "The 10 workers with the highest core temperature"))
            ax.set_ylabel("T_rect (°C)")
            ax.legend(loc="lower right", ncol=2)
            self._x(ax)
            c.draw_idle()
            fig, ax, c = self.ex["uur"]
            ax.clear()
            u = r["samen"]["uren"]
            x = np.arange(len(u))
            ax.bar(x - 0.2, [v["wbgt_twa"] for v in u], width=0.4, color=KL["oranje"],
                   label=vt("WBGT tijdgewogen (+ kledingcorrectie)", "WBGT time-weighted (+ clothing correction)"))
            ax.bar(x + 0.2, [v["grens"] for v in u], width=0.4, color=KL["grijs"], label=vt("ISO 7243-grens", "ISO 7243 limit"))
            ax.set_xticks(x, [v["uur"].strftime("%H:00") for v in u])
            for i, v in enumerate(u):
                ax.text(i, max(v["wbgt_twa"], v["grens"]) + 0.3, f"M {nl(v['m_twa'], 0)} W/m²",
                        ha="center", fontsize=8)
            ax.set_ylabel("°C")
            ax.set_title(vt("WBGT per klokuur tegen ISO 7243 (tijdgewogen over werk en rust)", "WBGT per clock hour against ISO 7243 (time-weighted over work and rest)"))
            ax.legend(loc="upper left")
            c.draw_idle()

        # ------------------------------------------------------- rapport
        def _rapport(self):
            if self.resultaat is None:
                messagebox.showinfo(vt("Word-rapport", "Word report"), vt("Nog geen uitkomst.", "No result yet."))
                return
            p = filedialog.asksaveasfilename(title=vt("Word-rapport opslaan", "Save Word report"), defaultextension=".docx",
                                             initialfile=vt("HESTIA_werk_rapport.docx", "HESTIA_work_report.docx"),
                                             filetypes=[("Word", "*.docx")])
            if not p:
                return
            try:
                import hestia_werk_rapport as hwr
                hwr.maak_rapport(self.resultaat, self.weer.label, p, PROFIEL_NL[self.resultaat["invoer"].profiel])
                messagebox.showinfo(vt("Word-rapport", "Word report"), vt(f"Opgeslagen:\n{p}", f"Saved:\n{p}"))
            except Exception as ex:
                messagebox.showerror(vt("Word-rapport", "Word report"), vt(f"Mislukt: {ex}", f"Failed: {ex}"))

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
