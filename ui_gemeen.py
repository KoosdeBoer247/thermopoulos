# -*- coding: utf-8 -*-
"""
ui_gemeen.py
============
Gedeelde presentatie-onderdelen voor de Thermopoulos-interfaces
(hestia_loper_ui, hestia_populatie_ui, pyrox_ui, klimatos_ui).

Alleen weergave. Deze module rekent niets uit: elke waarde die erin wordt
getoond komt van de aanroepende UI, die haar uit de suite haalt.

Onderdelen
----------
- sectie(...)        invoerblok met een label 'verplicht', 'optioneel' of
                     'modelinstelling', zodat zichtbaar is wat nodig is voor
                     de berekening en wat de suite zelf invult.
- invoer_legenda()   korte uitleg van die drie labels bovenaan de invoer.
- Tegels             de belangrijkste uitkomsten groot, met daaronder een
                     regel interpretatie.
- Herkomst           een vaste regel onderaan: gegevensbron, suiteversie,
                     status (simulatie / prognose / historische analyse /
                     beoordeling) en wat de uitkomst NIET is.
- tab_uitleg(...)    een korte regel bovenaan een tabblad: wat staat hier en
                     waarvoor gebruik je het.
"""
from __future__ import annotations

from taal import vt, getal

import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

HIER = Path(__file__).resolve().parent

SOORT = {
    "verplicht": (vt("VERPLICHT", "REQUIRED"), "#1f5fa8"),
    "optioneel": (vt("OPTIONEEL", "OPTIONAL"), "#6c7a89"),
    "model":     (vt("MODELINSTELLING", "MODEL SETTING"), "#7d3c98"),
    "actie":     (vt("ACTIES", "ACTIONS"), "#1a7f5a"),
    "melding":   (vt("ALLEEN MELDING", "NOTICE ONLY"), "#9c4400"),
    "info":      (vt("VAST", "FIXED"), "#6c7a89"),
}

STATUS_KLEUR = {
    "simulatie": "#1f5fa8",
    "prognose": "#b9770e",
    "historisch": "#117a65",
    "beoordeling": "#7d3c98",
    "gemengd": "#b9770e",
}


def suite_versie() -> str:
    """Versie uit pyproject.toml (dezelfde als in CITATION.cff)."""
    try:
        tekst = (HIER / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', tekst, re.M)
        if m:
            return m.group(1)
    except OSError:
        pass
    return vt("onbekend", "unknown")


def sectie(ouder, titel: str, soort: str, letter: int = 12, uitleg: str = ""):
    """LabelFrame met een gekleurd soortlabel in de kop. Geeft het frame terug."""
    kop = tk.Frame(ouder)
    tk.Label(kop, text=titel, font=("TkDefaultFont", letter, "bold")).pack(side="left")
    tekst, kleur = SOORT[soort]
    tk.Label(kop, text=f" {tekst} ", font=("TkDefaultFont", max(8, letter - 3), "bold"),
             fg="white", bg=kleur, padx=2).pack(side="left", padx=(6, 0))
    f = ttk.LabelFrame(ouder, labelwidget=kop, padding=6)
    f.pack(fill="x", padx=2, pady=4)
    if uitleg:
        ttk.Label(f, text=uitleg, foreground="#555", font=("TkDefaultFont", letter - 2),
                  wraplength=430, justify="left").pack(anchor="w", pady=(0, 3))
    return f


def invoer_legenda(ouder, letter: int = 12, extra: str = ""):
    f = tk.Frame(ouder, bg="#f2f4f6", padx=6, pady=4)
    f.pack(fill="x", padx=2, pady=(2, 4))
    regels = [("verplicht", vt("nodig voor de berekening", "needed for the calculation")),
              ("optioneel", vt("mag leeg blijven; grijs = waarde die de suite dan gebruikt", "may stay empty; grey = value the suite then uses")),
              ("model", vt("standaard van de suite; alleen aanpassen voor onderzoek", "suite default; change only for research"))]
    for soort, uitleg in regels:
        rij = tk.Frame(f, bg="#f2f4f6")
        rij.pack(anchor="w")
        tekst, kleur = SOORT[soort]
        tk.Label(rij, text=f" {tekst} ", font=("TkDefaultFont", max(8, letter - 3), "bold"), fg="white",
                 bg=kleur, width=17).pack(side="left")
        tk.Label(rij, text=" " + uitleg, bg="#f2f4f6", font=("TkDefaultFont", letter - 2)).pack(side="left")
    if extra:
        tk.Label(f, text=extra, bg="#f2f4f6", fg="#555", font=("TkDefaultFont", letter - 2),
                 wraplength=440, justify="left").pack(anchor="w", pady=(2, 0))
    return f


class Tegels(tk.Frame):
    """Rij van uitkomsttegels plus een interpretatieregel.

    zet(items, uitleg) met items = lijst van dicts:
        titel  korte naam van de grootheid
        waarde de waarde, groot weergegeven
        sub    spreiding of toelichting (klein)
        kleur  kleur van de balk links (optioneel)
    """

    def __init__(self, ouder, letter: int = 12):
        super().__init__(ouder, bg="white", highlightthickness=1, highlightbackground="#d5d8dc")
        self.letter = letter
        self.breedte = 200
        self._items, self._uitleg = [], ""
        self.rij = tk.Frame(self, bg="white")
        self.rij.pack(fill="x", padx=4, pady=(3, 0))
        self.lbl_uitleg = tk.Label(self, text="", bg="white", anchor="w", justify="left",
                                   font=("TkDefaultFont", letter - 1), wraplength=1200)
        self.lbl_uitleg.pack(fill="x", padx=8, pady=(1, 3))
        self.bind("<Configure>", self._maat)
        self.leeg(vt("Nog geen uitkomst.", "No result yet."))

    def _maat(self, e):
        self.lbl_uitleg.config(wraplength=max(400, e.width - 24))
        n = max(1, len(self._items))
        b = max(150, int((e.width - 16) / n) - 24)
        if abs(b - self.breedte) > 8:
            self.breedte = b
            self.zet(self._items, self._uitleg)

    def leeg(self, tekst: str):
        self.zet([], tekst)

    def zet(self, items, uitleg: str = ""):
        self._items, self._uitleg = list(items), uitleg
        for c in self.rij.winfo_children():
            c.destroy()
        L = self.letter
        for i in range(self.rij.grid_size()[0]):
            self.rij.grid_columnconfigure(i, weight=0, uniform="")
        for i, it in enumerate(items):
            vak = tk.Frame(self.rij, bg="white")
            vak.grid(row=0, column=i, sticky="nsew", padx=3)
            self.rij.grid_columnconfigure(i, weight=1, uniform="tegel")
            tk.Frame(vak, bg=it.get("kleur") or "#1f5fa8", width=5).pack(side="left", fill="y")
            binnen = tk.Frame(vak, bg="white")
            binnen.pack(side="left", fill="both", expand=True, padx=(6, 2))
            tk.Label(binnen, text=it["titel"], bg="white", fg="#555", anchor="w", justify="left",
                     font=("TkDefaultFont", L - 1), wraplength=self.breedte).pack(anchor="w")
            groot = L + 5 if len(it["waarde"]) <= 13 else L + 2
            tk.Label(binnen, text=it["waarde"], bg="white", fg="#1b1b1b", anchor="w", justify="left",
                     font=("TkDefaultFont", groot, "bold"), wraplength=self.breedte).pack(anchor="w")
            if it.get("sub"):
                tk.Label(binnen, text=it["sub"], bg="white", fg="#555", anchor="w", justify="left",
                         font=("TkDefaultFont", L - 2), wraplength=self.breedte).pack(anchor="w")
        self.lbl_uitleg.config(text=uitleg)


class Herkomst(tk.Frame):
    """Vaste regel: gegevensbron | suiteversie | status | wat het niet is."""

    def __init__(self, ouder, letter: int = 12):
        super().__init__(ouder, bg="#eef1f4")
        self.letter = letter
        self.lbl_status = tk.Label(self, text=" — ", fg="white", bg="#7f8c8d",
                                   font=("TkDefaultFont", letter - 2, "bold"), padx=4)
        self.lbl_status.pack(side="left", padx=(4, 6), pady=3, anchor="n")
        self.lbl = tk.Label(self, text="", bg="#eef1f4", anchor="w", justify="left",
                            font=("TkDefaultFont", letter - 2), wraplength=1200)
        self.lbl.pack(side="left", fill="x", expand=True, pady=3)
        self.bind("<Configure>", lambda e: self.after_idle(self._maat))
        self.versie = suite_versie()
        self.zet("—", "simulatie", "")

    def _maat(self):
        b = max(300, self.winfo_width() - self.lbl_status.winfo_reqwidth() - 30)
        if int(self.lbl.cget("wraplength")) != b:
            self.lbl.config(wraplength=b)

    def zet(self, bron: str, status: str, niet: str = "", status_tekst: str = "", extra: str = ""):
        _st_en = {"simulatie": "simulation", "prognose": "forecast", "historisch": "historical",
                  "beoordeling": "assessment", "gemengd": "mixed"}
        self.lbl_status.config(text=" " + (status_tekst or vt(status, _st_en.get(status, status))).upper() + " ",
                               bg=STATUS_KLEUR.get(status, "#7f8c8d"))
        self.after_idle(self._maat)
        delen = [vt(f"Gegevensbron: {bron}", f"Data source: {bron}"), f"Suite {self.versie}"]
        if extra:
            delen.append(extra)
        tekst = "  │  ".join(delen)
        if niet:
            tekst += vt(f"  │  Dit is niet: {niet}", f"  │  This is not: {niet}")
        self.lbl.config(text=tekst)


def tab_uitleg(ouder, tekst: str, letter: int = 12):
    """Uitlegregel bovenaan een tabblad. Moet als eerste met side='top' gepakt worden."""
    f = tk.Frame(ouder, bg="#f7f3e8")
    tk.Label(f, text="ⓘ", bg="#f7f3e8", fg="#7a5b00", font=("TkDefaultFont", letter, "bold")).pack(
        side="left", padx=(6, 4), anchor="n")
    lbl = tk.Label(f, text=tekst, bg="#f7f3e8", fg="#3d3d3d", anchor="w", justify="left",
                   font=("TkDefaultFont", letter - 2), wraplength=1200)
    lbl.pack(side="left", fill="x", expand=True, pady=2)
    f.bind("<Configure>", lambda e: lbl.config(wraplength=max(400, e.width - 40)))
    f.pack(side="top", fill="x", padx=4, pady=(3, 1))
    return f


class Inklap(tk.Frame):
    """Inklapbaar blok: een knop '▸ titel' die de inhoud (self.binnen) toont of verbergt."""

    def __init__(self, ouder, titel: str, letter: int = 12, open_: bool = False):
        super().__init__(ouder)
        self.titel = titel
        self.knop = tk.Label(self, text="", fg="#1f5fa8", cursor="hand2", anchor="w",
                             font=("TkDefaultFont", letter - 1, "underline"))
        self.knop.pack(fill="x", padx=6)
        self.knop.bind("<Button-1>", lambda e: self.wissel())
        self.binnen = tk.Frame(self)
        self.open = not open_
        self.wissel()

    def wissel(self):
        self.open = not self.open
        self.knop.config(text=("▾ " if self.open else "▸ ") + self.titel)
        if self.open:
            self.binnen.pack(fill="x")
        else:
            self.binnen.pack_forget()


def px(root, n: int) -> int:
    """Pixelmaat n (ontworpen voor 96 dpi) aangepast aan de schermschaling van Windows."""
    try:
        f = float(root.tk.call("tk", "scaling")) / (96 / 72)
    except (tk.TclError, ValueError):
        f = 1.0
    return int(round(n * max(1.0, f)))


def maximaliseer(root):
    """Venster zo groot mogelijk openen (Windows: gemaximaliseerd)."""
    try:
        root.state("zoomed")
        return
    except tk.TclError:
        pass
    try:
        root.attributes("-zoomed", True)
    except tk.TclError:
        pass
