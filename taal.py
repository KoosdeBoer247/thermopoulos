# -*- coding: utf-8 -*-
"""
taal.py — taalkeuze voor de vensters en de rapporten (Nederlands / Engels)
=========================================================================

Het startscherm (thermopoulos_ui.py) opent standaard in het Nederlands; met de
Britse vlag schakelt het naar het Engels en start elk venster met de
omgevingsvariabele THERMOPOULOS_TAAL=en. Een venster kan ook los in het Engels
starten:  python hestia_werk_ui.py --lang en

Elke tekst staat in de code als vt("Nederlands", "English"): beide talen naast
elkaar, zodat een wijziging in de ene taal meteen zichtbaar maakt dat de
andere mee moet. De berekeningen zijn in beide talen gelijk (golden test).
Vaste termen: woordenlijst "Engelse versie: woordenlijst NL–EN" (24-11-2026,
goedgekeurd): Brits Engels, decimale punt in het Engels, datum invoeren als
JJJJ-MM-DD in beide talen.

Language choice for the windows and reports (Dutch / English). Every text is
written as vt("Dutch", "English"); calculations are identical in both
languages.
"""
from __future__ import annotations

import os
import sys

_GELDIG = ("nl", "en")


def _begin() -> str:
    for i, a in enumerate(sys.argv):
        if a == "--lang" and i + 1 < len(sys.argv) and sys.argv[i + 1] in _GELDIG:
            return sys.argv[i + 1]
        if a.startswith("--lang=") and a.split("=", 1)[1] in _GELDIG:
            return a.split("=", 1)[1]
    t = os.environ.get("THERMOPOULOS_TAAL", "nl").strip().lower()
    return t if t in _GELDIG else "nl"


TAAL = _begin()
# Werkprocessen (spawn) erven de omgeving; zo rekenen en schrijven ze in dezelfde taal.
os.environ["THERMOPOULOS_TAAL"] = TAAL


def zet_taal(t: str) -> None:
    """Alleen voor het startscherm en tests: taal van dit proces wijzigen."""
    global TAAL
    if t not in _GELDIG:
        raise ValueError(t)
    TAAL = t
    os.environ["THERMOPOULOS_TAAL"] = t


def engels() -> bool:
    return TAAL == "en"


def vt(nl: str, en: str) -> str:
    """De tekst in de gekozen taal."""
    return en if TAAL == "en" else nl


def getal(x, d: int = 1) -> str:
    """Getal met d decimalen: komma in het Nederlands, punt in het Engels."""
    s = f"{x:.{d}f}"
    return s if TAAL == "en" else s.replace(".", ",")


def duizend(n) -> str:
    """Geheel getal met duizendtalscheiding: 12.345 (NL) of 12,345 (EN)."""
    s = f"{int(round(n)):,}"
    return s if TAAL == "en" else s.replace(",", ".")


def pct(x: float, d: int = 0) -> str:
    """Fractie als percentage (0,25 -> 25%)."""
    return getal(100.0 * x, d) + "%"


_MAAND_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MAAND_NL = ("jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec")


def datum(ts, met_jaar: bool = True) -> str:
    """22 Sep 2024 (EN) of 22-09-2024 (NL)."""
    import pandas as pd
    t = pd.Timestamp(ts)
    if TAAL == "en":
        return f"{t.day} {_MAAND_EN[t.month - 1]}" + (f" {t.year}" if met_jaar else "")
    return t.strftime("%d-%m-%Y" if met_jaar else "%d-%m")


def maand(m: int) -> str:
    return (_MAAND_EN if TAAL == "en" else _MAAND_NL)[int(m) - 1]
