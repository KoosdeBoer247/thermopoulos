# -*- coding: utf-8 -*-
"""
clinic_invoer.py -- deelnemersgegevens van een Thermo Clinic inlezen
=====================================================================

Leest het bestand ``deelnemers.xlsx`` dat Joost per clinic invult en zet elke
regel om naar een gecontroleerd ``Deelnemer``-record. Er staan GEEN namen in:
alleen codes (L01, L02, ...). De sleutellijst code -> persoon blijft bij Joost.

Het bestand heeft twee tabbladen:

  Clinic       een rij met gegevens voor de hele clinic
               (datum, starttijd hoofddeel, plaats, geplande afstand,
               pad naar het weerbestand van de Data Engine, terrein)
  Deelnemers   een rij per loper (zie KOLOMMEN hieronder)

Een leeg sjabloon maken:   python clinic_invoer.py sjabloon deelnemers.xlsx

Dit bestand verandert niets aan de loper-module; ``naar_loperinvoer`` zet een
deelnemer om naar dezelfde ``LoperInvoer`` als de vragenlijst van run_loper.py,
zodat modus A precies de bestaande loperberekening is.
"""
from __future__ import annotations

import datetime as _dt
import math
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

import pandas as pd

#: Kolommen van het tabblad Deelnemers: (naam, verplicht, uitleg)
KOLOMMEN = [
    ("code",            True,  "L01, L02, ... (geen naam)"),
    ("geslacht",        True,  "m of v"),
    ("leeftijd",        True,  "jaren"),
    ("lengte_cm",       True,  "cm"),
    ("gewicht_voor_kg", True,  "kg, zonder schoenen, na plassen"),
    ("gewicht_na_kg",   False, "kg, zelfde weegschaal, zonder schoenen"),
    ("verwacht_tempo",  True,  "min/km, bijv. 5:45"),
    ("kleding",         True,  "licht / normaal / lang"),
    ("hitte_gewend",    True,  "j of n"),
    ("drank_ml",        False, "ml gedronken tussen de twee wegingen"),
    ("geplast",         False, "j als de loper tussen de wegingen heeft geplast"),
    ("afstand_km",      False, "alleen invullen als anders dan de clinic-afstand"),
    ("starttijd",       False, "UU:MM, alleen als anders dan de clinic-starttijd"),
    ("vo2max",          False, "mL/kg/min uit een test (niet de horlogewaarde)"),
    ("hr_max",          False, "gemeten maximale hartslag"),
    ("hr_rust",         False, "rusthartslag 's ochtends"),
    ("opmerking",       False, "bijzonderheden, ziekte in de week ervoor, uitval"),
]

CLINIC_VELDEN = [
    ("datum",        "JJJJ-MM-DD"),
    ("starttijd",    "UU:MM, start van het hoofddeel (lokale tijd)"),
    ("plaats",       "plaats van de clinic"),
    ("afstand_km",   "geplande afstand van het hoofddeel"),
    ("weerbestand",  "pad naar Thermopoulos_DataEngine_*.xlsx met deze datum"),
    ("terrein",      "open / bos / stad (beschrijvend)"),
]

KLEDING = ("licht", "normaal", "lang")


# -----------------------------------------------------------------------------
# Hulpfuncties voor wat Excel ervan maakt
# -----------------------------------------------------------------------------
def _leeg(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x)) or (isinstance(x, str) and not x.strip())


def _getal(x) -> Optional[float]:
    if _leeg(x):
        return None
    if isinstance(x, str):
        x = x.strip().replace(",", ".")
    return float(x)


def _jn(x) -> bool:
    if _leeg(x):
        return False
    return str(x).strip().lower() in ("j", "ja", "y", "yes", "1", "true", "waar")


def _tempo(x) -> str:
    """'5:45', 5.75, of een Excel-tijd 05:45:00 -> '5:45'."""
    if isinstance(x, (_dt.time, _dt.datetime)):
        # Excel leest 5:45 vaak als 05:45 uur; dat zijn hier minuten:seconden
        return f"{x.hour}:{x.minute:02d}"
    if isinstance(x, _dt.timedelta):
        s = x.total_seconds()
        if s >= 3600:                       # 5:45 als 5 uur 45 gelezen
            s /= 60.0
        return f"{int(s // 60)}:{int(round(s % 60)):02d}"
    if isinstance(x, (int, float)):
        m = float(x)
        return f"{int(m)}:{int(round((m - int(m)) * 60)):02d}"
    s = str(x).strip()
    deel = s.split(":")
    if len(deel) == 3:                      # '05:45:00'
        return f"{int(deel[0])}:{int(deel[1]):02d}"
    return s


def _klok(x) -> Optional[str]:
    if _leeg(x):
        return None
    if isinstance(x, (_dt.time, _dt.datetime)):
        return f"{x.hour:02d}:{x.minute:02d}"
    if isinstance(x, _dt.timedelta):
        m = int(x.total_seconds() // 60)
        return f"{m // 60:02d}:{m % 60:02d}"
    s = str(x).strip()
    d = s.split(":")
    return f"{int(d[0]):02d}:{int(d[1]):02d}"


def _datum(x) -> str:
    if isinstance(x, (_dt.date, _dt.datetime, pd.Timestamp)):
        return pd.Timestamp(x).strftime("%Y-%m-%d")
    return pd.Timestamp(str(x).strip()).strftime("%Y-%m-%d")


# -----------------------------------------------------------------------------
# Records
# -----------------------------------------------------------------------------
@dataclass
class Clinic:
    datum: str
    starttijd: str
    plaats: str
    afstand_km: float
    weerbestand: str
    terrein: str = ""

    @property
    def start(self) -> pd.Timestamp:
        return pd.Timestamp(f"{self.datum} {self.starttijd}")


@dataclass
class Deelnemer:
    code: str
    geslacht: str                 # 'man' | 'vrouw'
    leeftijd: int
    lengte_cm: float
    gewicht_voor_kg: float
    verwacht_tempo: str           # 'm:ss'
    kleding: str
    hitte_gewend: bool
    gewicht_na_kg: Optional[float] = None
    drank_ml: Optional[float] = None
    geplast: bool = False
    afstand_km: Optional[float] = None
    starttijd: Optional[str] = None
    vo2max: Optional[float] = None
    hr_max: Optional[float] = None
    hr_rust: Optional[float] = None
    opmerking: str = ""
    waarschuwingen: list = field(default_factory=list)

    # ------------------------------------------------------------------
    def vochtverlies_gemeten_pct(self) -> Optional[float]:
        """(gewicht voor - gewicht na + drank in kg) / gewicht voor x 100.
        None als een van de gegevens ontbreekt of als de loper plaste."""
        if self.gewicht_na_kg is None or self.drank_ml is None or self.geplast:
            return None
        return ((self.gewicht_voor_kg - self.gewicht_na_kg + self.drank_ml / 1000.0)
                / self.gewicht_voor_kg * 100.0)

    def reden_geen_vochtverlies(self) -> str:
        if self.geplast:
            return "geplast tussen de wegingen"
        if self.gewicht_na_kg is None:
            return "gewicht na ontbreekt"
        if self.drank_ml is None:
            return "drankhoeveelheid ontbreekt"
        return ""


def _deelnemer_uit_rij(rij: dict) -> Deelnemer:
    fouten, waarsch = [], []
    code = str(rij.get("code", "")).strip()
    if not code:
        raise ValueError("lege code")
    g = str(rij.get("geslacht", "")).strip().lower()
    geslacht = {"m": "man", "man": "man", "v": "vrouw", "vrouw": "vrouw",
                "f": "vrouw"}.get(g)
    if geslacht is None:
        fouten.append("geslacht moet m of v zijn")
    leeftijd = _getal(rij.get("leeftijd"))
    lengte = _getal(rij.get("lengte_cm"))
    if lengte is not None and lengte < 3:          # in meters ingevuld
        lengte *= 100.0
    m_voor = _getal(rij.get("gewicht_voor_kg"))
    m_na = _getal(rij.get("gewicht_na_kg"))
    kleding = str(rij.get("kleding", "")).strip().lower()
    for naam, v, lo, hi in [("leeftijd", leeftijd, 16, 90), ("lengte_cm", lengte, 130, 220),
                            ("gewicht_voor_kg", m_voor, 30, 200)]:
        if v is None:
            fouten.append(f"{naam} ontbreekt")
        elif not lo <= v <= hi:
            fouten.append(f"{naam} {v:g} buiten {lo}-{hi}")
    if kleding not in KLEDING:
        fouten.append(f"kleding moet een van {KLEDING} zijn")
    tempo = _tempo(rij.get("verwacht_tempo")) if not _leeg(rij.get("verwacht_tempo")) else ""
    try:
        mm, ss = tempo.split(":")
        t = int(mm) + int(ss) / 60.0
        if not 2.5 <= t <= 15:
            fouten.append(f"tempo {tempo} buiten 2:30-15:00")
    except Exception:
        fouten.append("verwacht_tempo onleesbaar; gebruik bijv. 5:45")
    if m_voor is not None and m_na is not None:
        verschil = m_voor - m_na
        if not -1.0 <= verschil <= 4.0:
            fouten.append(f"gewicht voor - na = {verschil:.1f} kg; controleer de wegingen")
    drank = _getal(rij.get("drank_ml"))
    if drank is not None and not 0 <= drank <= 3000:
        fouten.append("drank_ml buiten 0-3000")
    if fouten:
        raise ValueError(f"{code}: " + "; ".join(fouten))
    if m_na is None:
        waarsch.append("gewicht na ontbreekt: geen gemeten vochtverlies")
    if drank is None:
        waarsch.append("drank_ml ontbreekt: geen gemeten vochtverlies")
    return Deelnemer(
        code=code, geslacht=geslacht, leeftijd=int(round(leeftijd)), lengte_cm=float(lengte),
        gewicht_voor_kg=float(m_voor), verwacht_tempo=tempo, kleding=kleding,
        hitte_gewend=_jn(rij.get("hitte_gewend")), gewicht_na_kg=m_na, drank_ml=drank,
        geplast=_jn(rij.get("geplast")), afstand_km=_getal(rij.get("afstand_km")),
        starttijd=_klok(rij.get("starttijd")), vo2max=_getal(rij.get("vo2max")),
        hr_max=_getal(rij.get("hr_max")), hr_rust=_getal(rij.get("hr_rust")),
        opmerking="" if _leeg(rij.get("opmerking")) else str(rij.get("opmerking")).strip(),
        waarschuwingen=waarsch)


def lees_deelnemers(pad: str | Path) -> tuple[Clinic, list[Deelnemer], list[str]]:
    """Lees deelnemers.xlsx. Geeft (clinic, deelnemers, meldingen).
    Een regel met fouten wordt NIET stil overgeslagen: alle fouten samen
    geven een ValueError, zodat het bestand eerst gecorrigeerd wordt."""
    pad = Path(pad)
    with pd.ExcelFile(pad) as xl:
        if "Clinic" not in xl.sheet_names or "Deelnemers" not in xl.sheet_names:
            raise ValueError(f"{pad.name} mist het tabblad 'Clinic' of 'Deelnemers'.")
        cl = pd.read_excel(xl, "Clinic", header=None)
        dn = pd.read_excel(xl, "Deelnemers", dtype=object)
    # Clinic: twee kolommen (veld, waarde)
    kv = {str(r[0]).strip(): r[1] for r in cl.itertuples(index=False) if not _leeg(r[0])}
    ontbreekt = [v for v, _ in CLINIC_VELDEN if v != "terrein" and _leeg(kv.get(v))]
    if ontbreekt:
        raise ValueError("Tabblad Clinic mist: " + ", ".join(ontbreekt))
    weer = Path(str(kv["weerbestand"]).strip())
    if not weer.is_absolute():
        weer = (pad.parent / weer)
    clinic = Clinic(datum=_datum(kv["datum"]), starttijd=_klok(kv["starttijd"]),
                    plaats=str(kv["plaats"]).strip(), afstand_km=float(_getal(kv["afstand_km"])),
                    weerbestand=str(weer), terrein="" if _leeg(kv.get("terrein")) else str(kv["terrein"]))
    dn.columns = [str(c).strip() for c in dn.columns]
    mist = [k for k, verplicht, _ in KOLOMMEN if verplicht and k not in dn.columns]
    if mist:
        raise ValueError("Tabblad Deelnemers mist kolommen: " + ", ".join(mist))
    deelnemers, fouten, meldingen = [], [], []
    for rij in dn.to_dict("records"):
        if all(_leeg(v) for v in rij.values()):
            continue
        try:
            d = _deelnemer_uit_rij(rij)
            deelnemers.append(d)
            meldingen += [f"{d.code}: {w}" for w in d.waarschuwingen]
        except ValueError as e:
            fouten.append(str(e))
    codes = [d.code for d in deelnemers]
    dubbel = sorted({c for c in codes if codes.count(c) > 1})
    if dubbel:
        fouten.append("dubbele codes: " + ", ".join(dubbel))
    if fouten:
        raise ValueError("deelnemers.xlsx klopt niet:\n  - " + "\n  - ".join(fouten))
    return clinic, deelnemers, meldingen


def naar_loperinvoer(d: Deelnemer, clinic: Clinic):
    """Zelfde invoer als de vragenlijst van run_loper.py (modus A)."""
    from hestia_loper import LoperInvoer
    return LoperInvoer(
        lengte_cm=d.lengte_cm, gewicht_kg=d.gewicht_voor_kg, leeftijd=d.leeftijd,
        geslacht=d.geslacht, evenement=f"Thermo Clinic {clinic.datum}",
        datum=clinic.datum, starttijd=d.starttijd or clinic.starttijd, plaats=clinic.plaats,
        afstand_km=d.afstand_km or clinic.afstand_km, tempo_min_per_km=d.verwacht_tempo,
        drinkt_bij_elke_post=bool(d.drank_ml and d.drank_ml >= 100),
        hitte_geacclimatiseerd=d.hitte_gewend, kleding=d.kleding,
        vo2max_bekend=d.vo2max, hr_max_bekend=d.hr_max, hr_rust_bekend=d.hr_rust,
        weerbron="excel", weer_excel=clinic.weerbestand, naam=d.code)


# -----------------------------------------------------------------------------
# Sjabloon
# -----------------------------------------------------------------------------
def maak_sjabloon(pad: str | Path, voorbeeld: bool = True) -> Path:
    """Leeg (of met een voorbeeldregel) deelnemers.xlsx voor Joost."""
    pad = Path(pad)
    clinic = pd.DataFrame([(v, "", u) for v, u in CLINIC_VELDEN],
                          columns=["veld", "waarde", "uitleg"])
    rijen = []
    if voorbeeld:
        rijen.append({"code": "L01", "geslacht": "m", "leeftijd": 40, "lengte_cm": 182,
                      "gewicht_voor_kg": 75.0, "gewicht_na_kg": 74.2, "verwacht_tempo": "5:45",
                      "kleding": "normaal", "hitte_gewend": "n", "drank_ml": 250,
                      "geplast": "n", "opmerking": "VOORBEELD - verwijderen"})
    dn = pd.DataFrame(rijen, columns=[k for k, _, _ in KOLOMMEN])
    uitleg = pd.DataFrame([(k, "ja" if v else "nee", u) for k, v, u in KOLOMMEN],
                          columns=["kolom", "verplicht", "uitleg"])
    with pd.ExcelWriter(pad, engine="openpyxl") as xw:
        clinic.to_excel(xw, sheet_name="Clinic", index=False, header=False)
        dn.to_excel(xw, sheet_name="Deelnemers", index=False)
        uitleg.to_excel(xw, sheet_name="Uitleg", index=False)
        for blad, breed in (("Clinic", (16, 40, 55)), ("Uitleg", (18, 10, 60))):
            ws = xw.sheets[blad]
            for i, b in enumerate(breed):
                ws.column_dimensions["ABC"[i]].width = b
        ws = xw.sheets["Deelnemers"]
        for i in range(len(KOLOMMEN)):
            ws.column_dimensions[ws.cell(1, i + 1).column_letter].width = 16
        # tempo en tijden als tekst laten staan
        for rij in ws.iter_rows(min_row=2):
            for c in rij:
                c.number_format = "@"
    return pad


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "sjabloon":
        print("Sjabloon gemaakt:", maak_sjabloon(sys.argv[2]))
    elif len(sys.argv) >= 2:
        c, dl, m = lees_deelnemers(sys.argv[1])
        print(c)
        for d in dl:
            print(d.code, d.geslacht, d.leeftijd, d.lengte_cm, d.gewicht_voor_kg,
                  d.verwacht_tempo, "vochtverlies %:", d.vochtverlies_gemeten_pct())
        for x in m:
            print("let op:", x)
    else:
        print(__doc__)
