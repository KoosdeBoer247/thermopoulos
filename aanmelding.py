# -*- coding: utf-8 -*-
"""
aanmelding.py -- aanmeldlijst + FIT-bestanden automatisch omzetten naar codes
=============================================================================

[2026-10-29, verzoek van de auteur] De FIT-bestanden van een clinic komen
binnen met namen of e-mailadressen in de bestandsnaam, bijvoorbeeld

    20261012_Garmin001_jan.jansen-at-example.com.fit

en de organisatie houdt een aanmeldlijst bij met e-mailadres, leeftijd,
gender, gewicht, lengte en tempo, in haar eigen opmaak. Dit hulpmiddel:

1. herkent de kolommen van de aanmeldlijst aan hun kopjes (Email, Leeftijd,
   Gender (M/V), Gewicht voor de start, Lengte (cm), Verwacht tempo, ...);
   namen en e-mailadressen worden nooit overgenomen;
2. koppelt elk FIT-bestand aan een regel van de lijst via het e-mailadres in
   de bestandsnaam ("-at-" = "@"); bij twijfel (twee lopers met hetzelfde
   adres) vraagt het wie het is;
3. geeft elke loper automatisch een code die bij de Garmin-set hoort:
   Garmin001 -> G001. Lopers zonder FIT-bestand krijgen N01, N02, ...;
4. schrijft in de doelmap
     deelnemers.xlsx           de lijst in de opmaak van de suite, alleen codes
     fit_uitvoer/<code>_*.xlsx de FIT-gegevens, alleen codes (fit_lezer)
     PRIVE_koppeltabel.xlsx    code -> Garmin-set, regel en e-mailadres.
                               Alleen voor de organisatie; nooit delen.
   De rapporten van de suite lezen alleen deelnemers.xlsx en fit_uitvoer, en
   zien dus nooit een naam of e-mailadres.

Ontbrekende verplichte waarden (bijv. gewicht) vraagt het interactief na;
zonder antwoord blijft het veld leeg en meldt het samenvatting wat nog moet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

import clinic_invoer as ci

KOPPELTABEL = "PRIVE_koppeltabel.xlsx"
AANMELD_PRIVE = "aanmeldlijst_PRIVE.xlsx"

# Herkenning van kolomkopjes (kleine letters, alleen letters en cijfers).
# Volgorde telt: specifieke sleutels eerst ('gewicht na' voor 'gewicht').
HERKENNING = [
    ("email",           ("email", "emailadres", "mail", "mailadres")),
    ("aanwezig",        ("aanwezig", "present", "deelname")),
    ("gewicht_na_kg",   ("gewichtnadefinish", "gewichtna", "gewichtfinish", "weightafter")),
    ("gewicht_voor_kg", ("gewichtvoordestart", "gewichtvoor", "gewicht", "weight")),
    ("geslacht",        ("gendermv", "gender", "geslacht", "sekse", "mv")),
    ("leeftijd",        ("leeftijd", "age")),
    ("lengte_cm",       ("lengtecm", "lengte", "length", "height")),
    ("verwacht_tempo",  ("verwachttempo", "tempo", "pace")),
    ("kleding",         ("kleding", "clothing")),
    ("hitte_gewend",    ("hittegewend", "hitte", "acclimatisatie", "geacclimatiseerd")),
    ("hr_max",          ("hrmax", "maxhartslag", "maximalehartslag", "hartslagmax")),
    ("hr_rust",         ("hrrust", "rusthartslag", "hartslagrust")),
    ("vo2max",          ("vo2max", "vo2")),
    ("drank_ml",        ("drankml", "drank", "gedronken")),
    ("starttijd",       ("starttijd",)),
    ("datum",           ("datum", "date")),
    ("tijd",            ("tijd", "time")),
    ("locatie",         ("locatie", "plaats", "location")),
    ("opmerking",       ("opmerking", "opmerkingen", "bijzonderheden")),
]
# Kopjes die persoonsgegevens bevatten en altijd worden weggelaten
WEGLATEN = ("naam", "voornaam", "achternaam", "name", "telefoon", "tel", "adres", "woonplaats")

VERPLICHT = [k for k, v, _ in ci.KOLOMMEN if v and k != "code"]
STANDAARD = {"kleding": "licht", "hitte_gewend": "n"}


def _schoon(s) -> str:
    return re.sub(r"[^0-9a-z]", "", str(s).lower())


def _sleutel_email(s) -> str:
    """E-mailadres of bestandsnaamdeel -> vergelijkbare sleutel."""
    s = str(s).strip().lower()
    s = re.sub(r"^mailto:", "", s)                 # [2026-10-30] hyperlink-cellen
    s = s.replace("@", "at")
    return re.sub(r"[^0-9a-z]", "", s)


def herken_kolommen(kolommen) -> dict:
    """{oorspronkelijk kopje: suiteveld} voor de herkende kolommen."""
    uit, gebruikt = {}, set()
    schoon = {k: _schoon(k) for k in kolommen}
    for veld, sleutels in HERKENNING:
        for k, s in schoon.items():
            if k in uit or veld in gebruikt:
                continue
            if any(s == x or s.startswith(x) for x in sleutels):
                if veld == "tijd" and "start" in s:
                    continue
                uit[k] = veld
                gebruikt.add(veld)
    return uit


def is_aanmeldlijst(pad: str | Path) -> bool:
    """True als het eerste/enige blad een e-mailkolom heeft en geen kolom 'code'."""
    try:
        with pd.ExcelFile(pad) as xl:
            blad = "Deelnemers" if "Deelnemers" in xl.sheet_names else xl.sheet_names[0]
            kop = pd.read_excel(xl, blad, nrows=0).columns
    except Exception:
        return False
    velden = set(herken_kolommen(kop).values())
    return "email" in velden and "code" not in [str(k).strip().lower() for k in kop]


def lees_aanmeldlijst(pad: str | Path) -> pd.DataFrame:
    """Aanmeldlijst -> tabel met suitevelden + 'email' + 'regel' (Excel-regelnummer).
    Afwezigen ('Nee', of 'afwezig' in een cel) vallen weg."""
    with pd.ExcelFile(pad) as xl:
        blad = "Deelnemers" if "Deelnemers" in xl.sheet_names else xl.sheet_names[0]
        df = pd.read_excel(xl, blad, dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    kaart = herken_kolommen(df.columns)
    rijen = []
    for i, r in enumerate(df.to_dict("records")):
        if all(ci._leeg(v) for v in r.values()):
            continue
        d = {"regel": i + 2}
        for k, veld in kaart.items():
            d[veld] = r.get(k)
        tekst = " ".join(str(v).lower() for v in r.values() if not ci._leeg(v))
        aanw = str(d.get("aanwezig", "ja")).strip().lower()
        if aanw.startswith("nee") or aanw == "n" or "afwezig" in tekst:
            continue
        rijen.append(d)
    return pd.DataFrame(rijen)


_FIT_PATROON = re.compile(r"garmin\s*0*(\d+)", re.I)


def garmin_nummer(bestandsnaam: str) -> Optional[int]:
    m = _FIT_PATROON.search(bestandsnaam)
    return int(m.group(1)) if m else None


def email_deel(bestandsnaam: str) -> str:
    """Het deel van de bestandsnaam na '..._GarminNNN_' (zonder .fit)."""
    stam = Path(bestandsnaam).stem
    m = re.search(r"garmin\s*\d+[_\- ]+(.+)$", stam, re.I)
    return m.group(1) if m else stam


@dataclass
class Koppeling:
    fit: Optional[Path]
    regel: Optional[int]
    code: str
    garmin: Optional[int] = None
    email: str = ""
    opmerking: str = ""


@dataclass
class Resultaat:
    deelnemers_xlsx: Optional[Path]
    koppeltabel: Optional[Path]
    fit_exports: list = field(default_factory=list)
    koppelingen: list = field(default_factory=list)
    niet_gekoppeld: list = field(default_factory=list)     # FIT-bestanden zonder loper
    nog_invullen: list = field(default_factory=list)       # (code, veld)
    standaard_gebruikt: list = field(default_factory=list)  # (code, veld, waarde)


def koppel(lijst: pd.DataFrame, fits: list, vraag: Optional[Callable[[str], str]] = None) -> tuple[list, list]:
    """Koppel FIT-bestanden aan regels. Geeft (koppelingen, niet_gekoppeld)."""
    sleutels = {int(r.regel): _sleutel_email(r.email) for r in lijst.itertuples()
                if "email" in lijst and not ci._leeg(r.email)}
    bezet, kop, los = set(), [], []
    for p in sorted(fits, key=lambda x: (garmin_nummer(x.name) or 9999, x.name)):
        sk = _sleutel_email(email_deel(p.name))
        kand = [rg for rg, s in sleutels.items() if s and (s == sk or (len(sk) >= 8 and len(s) >= 8 and (
            s.startswith(sk) or sk.startswith(s) or sk in s or s in sk)))]
        kand = [rg for rg in kand if rg not in bezet] or kand
        regel = None
        if len(kand) == 1 and kand[0] not in bezet:
            regel = kand[0]
        elif len(kand) > 1 and vraag:
            opties = lijst[lijst.regel.isin(kand)]
            print(f"\n  {p.name[:28]}...: dit e-mailadres staat bij meer lopers:")
            for r in opties.itertuples():
                print(f"    regel {r.regel}: {r.geslacht}, {r.leeftijd} jaar"
                      + ("  (al gekoppeld)" if r.regel in bezet else ""))
            a = vraag("  Welke regel hoort bij dit bestand? (nummer, Enter = overslaan): ").strip()
            regel = int(a) if a.isdigit() and int(a) in kand else None
        if regel is None and not kand and vraag:
            # [2026-10-30] geen passend e-mailadres: laat de gebruiker kiezen uit de
            # regels die nog geen FIT-bestand hebben
            vrij = lijst[~lijst.regel.isin(bezet)]
            if len(vrij):
                print(f"\n  {p.name}: geen passend e-mailadres in de lijst gevonden.")
                for r in vrij.itertuples():
                    print(f"    regel {r.regel}: {getattr(r, 'email', '')}  ({getattr(r, 'geslacht', '')}, "
                          f"{getattr(r, 'leeftijd', '')} jaar)")
                a = vraag("  Welke regel hoort bij dit bestand? (nummer, Enter = niet koppelen): ").strip()
                regel = int(a) if a.isdigit() and int(a) in set(vrij.regel) else None
        if regel is None:
            los.append(p)
            continue
        bezet.add(regel)
        nr = garmin_nummer(p.name)
        email = str(lijst.loc[lijst.regel == regel, "email"].iloc[0])
        kop.append(Koppeling(fit=p, regel=regel, code=f"G{nr:03d}" if nr is not None else "",
                             garmin=nr, email=email))
    # codes zonder Garmin-nummer, en lopers zonder FIT-bestand
    n = 1
    for k in kop:
        if not k.code:
            k.code = f"F{n:02d}"
            n += 1
    m = 1
    for r in lijst.itertuples():
        if int(r.regel) not in bezet:
            kop.append(Koppeling(fit=None, regel=int(r.regel), code=f"N{m:02d}",
                                 email="" if ci._leeg(getattr(r, "email", None)) else str(r.email),
                                 opmerking="geen FIT-bestand"))
            m += 1
    return sorted(kop, key=lambda k: k.code), los


def _clinic_velden(lijst: pd.DataFrame) -> dict:
    """Datum, starttijd en plaats uit de aanmeldlijst, als ze er staan."""
    uit = {}
    if "datum" in lijst and lijst.datum.notna().any():
        v = lijst.datum.dropna().iloc[0]
        d = None
        if hasattr(v, "strftime"):
            d = pd.Timestamp(v)
        else:
            m = re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}[-/ ][A-Za-z]{3,9}[-/ ]\d{4}|\d{1,2}[-/]\d{1,2}[-/]\d{4}", str(v))
            if m:
                d = pd.to_datetime(m.group(0), dayfirst=True, errors="coerce")
        if d is not None and pd.notna(d):
            uit["datum"] = d.strftime("%Y-%m-%d")
    if "tijd" in lijst and lijst.tijd.notna().any():
        m = re.search(r"(\d{1,2})(?::(\d{2}))?", str(lijst.tijd.dropna().iloc[0]))
        if m:
            uit["starttijd"] = f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    if "locatie" in lijst and lijst.locatie.notna().any():
        uit["plaats"] = str(lijst.locatie.dropna().iloc[0]).strip()
    return uit


def _waarde(v, veld):
    if ci._leeg(v):
        return None
    if veld == "geslacht":
        g = str(v).strip().lower()[:1]
        return {"m": "m", "v": "v", "f": "v", "w": "v"}.get(g)
    if veld in ("leeftijd", "lengte_cm", "gewicht_voor_kg", "gewicht_na_kg",
                "hr_max", "hr_rust", "vo2max", "drank_ml"):
        try:
            return ci._getal(v)
        except (TypeError, ValueError):
            return None
    if veld == "verwacht_tempo":
        return ci._tempo(v)
    if veld == "hitte_gewend":
        return "j" if ci._jn(v) else "n"
    return str(v).strip()


def omzetten(aanmeldlijst: str | Path, fit_map: str | Path | None = None,
             doelmap: str | Path | None = None, vraag: Optional[Callable[[str], str]] = None,
             fit_lezen: Optional[Callable] = None, progress=print) -> Resultaat:
    """Aanmeldlijst + FIT-bestanden -> deelnemers.xlsx, fit_uitvoer/ en PRIVE_koppeltabel.xlsx.

    fit_map: map met de .fit-bestanden (standaard: de map van de lijst, en de
    submap fit_invoer). doelmap: standaard de map van de lijst. vraag: functie
    voor interactieve vragen (input), of None = niet vragen."""
    import fit_lezer as fl
    aanmeldlijst = Path(aanmeldlijst)
    doelmap = Path(doelmap) if doelmap else aanmeldlijst.parent
    doelmap.mkdir(parents=True, exist_ok=True)
    mappen = [Path(fit_map)] if fit_map else [aanmeldlijst.parent, aanmeldlijst.parent / "fit_invoer"]
    fits = sorted({p.resolve() for m in mappen if m.is_dir() for p in m.glob("*.fit")})
    lijst = lees_aanmeldlijst(aanmeldlijst)
    if lijst.empty:
        raise ValueError(f"{aanmeldlijst.name}: geen aanwezige lopers gevonden.")
    progress(f"  Aanmeldlijst: {len(lijst)} aanwezige lopers; FIT-bestanden: {len(fits)}")
    kop, los = koppel(lijst, fits, vraag=vraag)
    res = Resultaat(deelnemers_xlsx=None, koppeltabel=None, koppelingen=kop, niet_gekoppeld=los)

    # deelnemers.xlsx in de opmaak van de suite (alleen codes)
    rijen = []
    for k in kop:
        r = lijst[lijst.regel == k.regel].iloc[0].to_dict()
        rij = {"code": k.code}
        for kolom, _, _ in ci.KOLOMMEN[1:]:
            rij[kolom] = _waarde(r.get(kolom), kolom)
        for veld, std in STANDAARD.items():
            if rij.get(veld) in (None, ""):
                rij[veld] = std
                res.standaard_gebruikt.append((k.code, veld, std))
        for veld in VERPLICHT:
            if rij.get(veld) in (None, ""):
                antw = ""
                if vraag:
                    antw = vraag(f"  {k.code} (regel {k.regel}): {veld} ontbreekt. Waarde (Enter = later invullen): ").strip()
                if antw:
                    rij[veld] = _waarde(antw, veld)
                if rij.get(veld) in (None, ""):
                    res.nog_invullen.append((k.code, veld))
        if k.opmerking:
            rij["opmerking"] = (str(rij.get("opmerking") or "") + "; " + k.opmerking).strip("; ")
        rijen.append(rij)
    dn = pd.DataFrame(rijen, columns=[k for k, _, _ in ci.KOLOMMEN])
    doel = doelmap / "deelnemers.xlsx"
    if doel.exists() and doel.resolve() != aanmeldlijst.resolve():
        if not vraag or not vraag(f"  {doel.name} bestaat al. Overschrijven? (j/N): ").strip().lower().startswith("j"):
            doel = doelmap / "deelnemers_codes.xlsx"
    if doel.resolve() == aanmeldlijst.resolve():
        raise ValueError("de aanmeldlijst heet deelnemers.xlsx; hernoem hem eerst (zie bewaar_aanmeldlijst)")
    ci.maak_sjabloon(doel, voorbeeld=False)
    clinic = _clinic_velden(lijst)
    with pd.ExcelWriter(doel, engine="openpyxl", mode="a", if_sheet_exists="replace") as xw:
        cl = pd.DataFrame([(v, clinic.get(v, ""), u) for v, u in ci.CLINIC_VELDEN])
        cl.to_excel(xw, sheet_name="Clinic", index=False, header=False)
        dn.astype(object).where(dn.notna(), None).to_excel(xw, sheet_name="Deelnemers", index=False)
    res.deelnemers_xlsx = doel

    # FIT-bestanden omzetten, met de code als naam
    lezen = fit_lezen or fl.lees_fit
    for k in kop:
        if k.fit is None:
            continue
        try:
            rit = lezen(k.fit, k.code)
            u = fl.exporteer(rit, doelmap / "fit_uitvoer")
            res.fit_exports.append(u["xlsx"])
            progress(f"  {k.code}: {rit.meta.get('duur_min')} min, {rit.meta.get('afstand_km')} km "
                     f"-> {u['xlsx'].name}")
        except Exception as e:
            progress(f"  {k.code}: FIT-bestand niet leesbaar ({e})")

    # privé koppeltabel
    kt = pd.DataFrame([{"code": k.code, "garmin_set": k.garmin, "regel_aanmeldlijst": k.regel,
                        "email": k.email, "fit_bestand": k.fit.name if k.fit else "",
                        "opmerking": k.opmerking} for k in kop])
    res.koppeltabel = doelmap / KOPPELTABEL
    with pd.ExcelWriter(res.koppeltabel, engine="openpyxl") as xw:
        pd.DataFrame({"LET OP": ["PRIVÉ: koppelt codes aan personen. Niet delen, niet in rapporten, "
                                 "niet in de suitemap op GitHub."]}).to_excel(xw, sheet_name="Let op", index=False)
        kt.to_excel(xw, sheet_name="Koppeling", index=False)
    return res


def bewaar_aanmeldlijst(pad: Path, vraag: Optional[Callable[[str], str]] = None) -> Path:
    """Als de aanmeldlijst 'deelnemers.xlsx' heet: hernoemen naar aanmeldlijst_PRIVE.xlsx
    (na bevestiging), zodat deelnemers.xlsx voor de codelijst vrij komt."""
    pad = Path(pad)
    if pad.name.lower() != "deelnemers.xlsx":
        return pad
    nieuw = pad.with_name(AANMELD_PRIVE)
    if nieuw.exists():
        nieuw = pad.with_name(f"aanmeldlijst_PRIVE_{pd.Timestamp.now():%Y%m%d_%H%M}.xlsx")
    if vraag and vraag(f"  Uw aanmeldlijst heet deelnemers.xlsx. Hernoemen naar {nieuw.name}? "
                       f"(J/n): ").strip().lower().startswith("n"):
        raise ValueError("niet hernoemd; geef de aanmeldlijst eerst een andere naam")
    pad.rename(nieuw)
    return nieuw


def samenvatting(res: Resultaat) -> str:
    r = [f"  Codelijst:   {res.deelnemers_xlsx}",
         f"  FIT-uitvoer: {len(res.fit_exports)} bestanden in fit_uitvoer",
         f"  Koppeltabel: {res.koppeltabel}  (PRIVÉ, niet delen)"]
    if res.niet_gekoppeld:
        r.append("  Niet gekoppeld (geen passend e-mailadres in de lijst):")
        r += [f"    - {p.name[:40]}..." for p in res.niet_gekoppeld]
    geen = [k.code for k in res.koppelingen if k.fit is None]
    if geen:
        r.append("  Zonder FIT-bestand (fitheid wordt geschat): " + ", ".join(geen))
    if res.standaard_gebruikt:
        velden = sorted({v for _, v, _ in res.standaard_gebruikt})
        r.append("  Standaard ingevuld (controleer): " + ", ".join(
            f"{v} = {STANDAARD[v]}" for v in velden))
    if res.nog_invullen:
        r.append("  NOG INVULLEN in de codelijst:")
        r += [f"    - {c}: {v}" for c, v in res.nog_invullen]
    return "\n".join(r)


def interactief(map_: str | Path) -> Optional[Path]:
    """Menu: aanmeldlijst kiezen in map_ en omzetten. Geeft het pad van de codelijst."""
    map_ = Path(map_)
    kand = [p for p in sorted(map_.glob("*.xlsx")) if not p.name.startswith(("~$", "Thermopoulos", "PRIVE_"))
            and is_aanmeldlijst(p)]
    if not kand:
        print("  Geen aanmeldlijst (met een kolom Email) gevonden in", map_)
        return None
    for i, p in enumerate(kand, 1):
        print(f"    {i}  {p.name}")
    a = input("  Aanmeldlijst (nummer): ").strip()
    if not a.isdigit() or not 1 <= int(a) <= len(kand):
        return None
    lijst = bewaar_aanmeldlijst(kand[int(a) - 1], vraag=input)
    res = omzetten(lijst, vraag=input)
    print("\n" + samenvatting(res))
    return res.deelnemers_xlsx
