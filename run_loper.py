# -*- coding: utf-8 -*-
"""
run_loper.py -- persoonlijke hitte-analyse voor een hardloper.

Gebruik
-------
  python run_loper.py --nieuw mijn_loop.json
        Vragenlijst invullen; slaat de antwoorden op als JSON.
  python run_loper.py mijn_loop.json
        Analyse + figuren + Word-rapport + Excel in de map loper_uitvoer/.
  python run_loper.py mijn_loop.json --n 200 --uit map --geen-watals
  python run_loper.py            (zonder argumenten, bijv. in Spyder: keuzemenu)
  python run_loper.py --voorbeeld voorbeeld.json
        Schrijft een ingevuld voorbeeldbestand om aan te passen.

Weer: bij "weerbron": "excel" wordt een Thermopoulos Data Engine-bestand
gebruikt (offline, zelfde data als de populatieruns). Kies een bestand
waarin de datum van de loop zit (Forecast_7d, Hindcast_14d of
Historical_Custom). Bij "online" haalt de suite het weer bij Open-Meteo.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import fields
from pathlib import Path

from hestia_loper import LoperInvoer, NIET_GEMODELLEERD, KLEDING_CLO, analyseer_loper, exporteer_excel

VOORBEELD = LoperInvoer(
    naam="", lengte_cm=180, gewicht_kg=75, leeftijd=45, geslacht="man",
    evenement="Dam tot Damloop", datum="2026-09-20", starttijd="14:00",
    plaats="Amsterdam", afstand_km=16.1, tempo_min_per_km="5:30",
    drinkt_bij_elke_post=True, nsaid_voor_of_tijdens=False,
    hitte_geacclimatiseerd=False, kleding="licht", trainingskm_per_week=30,
    vo2max_bekend=None, wedstrijd_afstand_km=10, wedstrijd_tijd="50:00",
    hr_max_bekend=None, hr_rust_bekend=None, vetpercentage_bekend=None,
    weerbron="excel", weer_excel="Thermopoulos_DataEngine_Amsterdam.xlsx",
)


def _vraag(tekst, standaard=None, soort=str, optioneel=False, keuzes=None):
    extra = f" [{standaard}]" if standaard not in (None, "") else (" [leeg = onbekend]" if optioneel else "")
    if keuzes:
        extra = f" ({'/'.join(keuzes)})" + extra
    while True:
        a = input(f"{tekst}{extra}: ").strip()
        if a == "":
            if standaard not in (None, ""):
                a = str(standaard)
            elif optioneel:
                return None
            else:
                print("  Dit veld is verplicht.")
                continue
        if keuzes and a not in keuzes:
            print(f"  Kies uit: {', '.join(keuzes)}")
            continue
        try:
            if soort is bool:
                if a.lower() in ("j", "ja", "y", "yes", "true", "1"):
                    return True
                if a.lower() in ("n", "nee", "no", "false", "0"):
                    return False
                raise ValueError
            return soort(a.replace(",", ".")) if soort in (int, float) else a
        except ValueError:
            print("  Onleesbaar, probeer opnieuw.")


def vragenlijst() -> LoperInvoer:
    print("\nPersoonlijke hitte-analyse - vragenlijst")
    print("Je gegevens blijven op deze computer.\n")
    print("-- Over jou")
    d = dict(
        naam=_vraag("Naam (alleen voor het rapport)", standaard="-") ,
        lengte_cm=_vraag("Lengte in cm", soort=float),
        gewicht_kg=_vraag("Gewicht in kg", soort=float),
        leeftijd=_vraag("Leeftijd in jaren", soort=int),
        geslacht=_vraag("Geslacht", keuzes=["man", "vrouw"]),
    )
    print("\n-- De loop")
    d.update(
        evenement=_vraag("Naam van het evenement"),
        datum=_vraag("Datum (JJJJ-MM-DD)"),
        starttijd=_vraag("Starttijd (UU:MM)"),
        plaats=_vraag("Plaats"),
        afstand_km=_vraag("Afstand in km", soort=float),
        tempo_min_per_km=_vraag("Verwacht gemiddeld tempo in min/km (bijv. 5:30)"),
    )
    print("\n-- Fitheid (hoe meer je weet, hoe beter de berekening)")
    d.update(
        trainingskm_per_week=_vraag("Gemiddeld aantal km per week de laatste 2 maanden", soort=float),
        vo2max_bekend=_vraag("VO2max (van horloge of test), mL/kg/min", soort=float, optioneel=True),
    )
    if d["vo2max_bekend"] is None:
        d["wedstrijd_afstand_km"] = _vraag("Afstand van een recente wedstrijd (laatste 6 maanden) in km",
                                           soort=float, optioneel=True)
        d["wedstrijd_tijd"] = (_vraag("Eindtijd van die wedstrijd (u:mm:ss of mm:ss)")
                               if d["wedstrijd_afstand_km"] else None)
    d.update(
        hr_max_bekend=_vraag("Maximale hartslag (gemeten)", soort=float, optioneel=True),
        hr_rust_bekend=_vraag("Rusthartslag ('s ochtends gemeten)", soort=float, optioneel=True),
        vetpercentage_bekend=_vraag("Vetpercentage (gemeten)", soort=float, optioneel=True),
    )
    print("\n-- Gedrag en omstandigheden")
    d.update(
        drinkt_bij_elke_post=_vraag("Drink je bij (bijna) elke drankpost? (j/n)", "j", bool),
        nsaid_voor_of_tijdens=_vraag("Neem je pijnstillers zoals ibuprofen of naproxen voor/tijdens? (j/n)", "n", bool),
        hitte_geacclimatiseerd=_vraag("Heb je de laatste 2 weken regelmatig in de warmte getraind? (j/n)", "n", bool),
        kleding=_vraag("Kleding", "licht", keuzes=list(KLEDING_CLO)),
    )
    print("\n-- Gezondheid (niet in de berekening, wel in het rapport)")
    for k, (titel, _) in NIET_GEMODELLEERD.items():
        d[k] = _vraag(f"{titel}? (j/n)", "n", bool)
    print("\n-- Weer")
    d["weerbron"] = _vraag("Weerbron", "excel", keuzes=["excel", "online"])
    if d["weerbron"] == "excel":
        d["weer_excel"] = _kies_weerbestand()
    if d["naam"] == "-":
        d["naam"] = ""
    return LoperInvoer(**d)


def _kies_weerbestand() -> str:
    """Kies een Thermopoulos-bestand uit de werkmap (zelfde menu als
    run_hestia/run_pyrox); anders het pad laten intypen."""
    from thermopoulos_loader import choose_thermopoulos_file
    for map_ in (Path.cwd(), Path(__file__).resolve().parent):
        f = choose_thermopoulos_file(map_)
        if f is not None:
            return str(f)
    return _vraag("Pad naar het Thermopoulos Data Engine-bestand (.xlsx)")


def _zoek_weerbestand(inv: LoperInvoer, json_pad: Path) -> None:
    """Een relatief of verplaatst pad naar het weerbestand terugvinden; zo
    niet, de gebruiker laten kiezen."""
    if inv.weerbron != "excel":
        return
    p = Path(inv.weer_excel or "")
    for kandidaat in (p, json_pad.parent / p.name, Path.cwd() / p.name,
                      Path(__file__).resolve().parent / p.name):
        if p.name and kandidaat.is_file():
            inv.weer_excel = str(kandidaat)
            return
    print(f"\nWeerbestand '{inv.weer_excel}' niet gevonden.")
    inv.weer_excel = _kies_weerbestand()


def _kies_json() -> str | None:
    kandidaten = []
    for map_ in (Path.cwd(), Path(__file__).resolve().parent):
        for f in sorted(map_.glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True):
            if f.name.startswith("package"):     # node-bestanden van de Word-export
                continue
            if f.resolve() not in [k.resolve() for k in kandidaten]:
                kandidaten.append(f)
    if not kandidaten:
        print("Geen invoerbestanden (.json) gevonden in de werkmap.")
        return None
    print("\nInvoerbestanden:")
    for i, f in enumerate(kandidaten, 1):
        print(f"  {i:>2}. {f.name}")
    while True:
        k = input(f"Kies (1-{len(kandidaten)}, Q = terug): ").strip()
        if k.lower() in ("q", ""):
            return None
        if k.isdigit() and 1 <= int(k) <= len(kandidaten):
            return str(kandidaten[int(k) - 1])
        print("  Ongeldige keuze.")


def menu(args) -> int | None:
    """Keuzemenu als het script zonder argumenten start (bijv. in Spyder)."""
    print("\nPersoonlijke hitte-analyse (HESTIA)")
    print("-" * 44)
    print("  1. Nieuwe loper invullen (vragenlijst)")
    print("  2. Bestaand invoerbestand (.json) gebruiken")
    print("  3. Voorbeeldbestand maken om aan te passen")
    print("  Q. Stoppen")
    while True:
        k = input("Keuze: ").strip().lower()
        if k in ("q", ""):
            return 0
        if k == "1":
            naam = _vraag("Bestandsnaam voor je antwoorden", "mijn_loop.json")
            args.nieuw = naam if naam.endswith(".json") else naam + ".json"
            return None
        if k == "2":
            args.invoer = _kies_json()
            if args.invoer is None:
                return 0
            args.n = _vraag("Aantal runs (meer = nauwkeuriger, ca. 0,8 s per run)", args.n, int)
            return None
        if k == "3":
            args.voorbeeld = "loper_invoer_voorbeeld.json"
            return None
        print("  Kies 1, 2, 3 of Q.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Persoonlijke hitte-analyse (HESTIA)")
    ap.add_argument("invoer", nargs="?", help="JSON-bestand met de invoer")
    ap.add_argument("--nieuw", metavar="JSON", help="vragenlijst invullen en opslaan")
    ap.add_argument("--voorbeeld", metavar="JSON", help="voorbeeldinvoer schrijven")
    ap.add_argument("--n", type=int, default=200, help="aantal ensemble-runs (standaard 200)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--uit", default="loper_uitvoer", help="uitvoermap")
    ap.add_argument("--geen-watals", action="store_true", help="tempo-gevoeligheid overslaan")
    args = ap.parse_args(argv)
    if not (args.invoer or args.nieuw or args.voorbeeld):
        rc = menu(args)
        if rc is not None:
            return rc

    if args.voorbeeld:
        VOORBEELD.opslaan(args.voorbeeld)
        print(f"Voorbeeld geschreven: {Path(args.voorbeeld).resolve()}")
        print("Pas het aan (bijv. in Kladblok of Spyder) en kies daarna in het menu optie 2.")
        return 0
    if args.nieuw:
        while True:
            inv = vragenlijst()
            try:
                inv.valideer()
                break
            except ValueError as e:
                print(f"\n{e}\nVul de vragenlijst opnieuw in.")
        inv.opslaan(args.nieuw)
        print(f"\nOpgeslagen: {args.nieuw}")
        if _vraag("Nu de analyse draaien? (j/n)", "j", bool):
            args.invoer = args.nieuw
        else:
            return 0
    if not args.invoer:
        ap.print_help()
        return 1

    from hestia_loper_plots import maak_alle_plots
    from hestia_loper_rapport import maak_rapport

    inv = LoperInvoer.laden(args.invoer)
    _zoek_weerbestand(inv, Path(args.invoer))
    uit = Path(args.uit)
    uit.mkdir(parents=True, exist_ok=True)
    stam = f"HESTIA_Loper_{inv.evenement.replace(' ', '_')}_{inv.datum}_{inv.starttijd.replace(':', '')}"

    t0 = time.time()
    def prog(f, tekst):
        print(f"\r  {f * 100:5.1f}%  {tekst:<40}", end="", flush=True)
    print("Analyse loopt...")
    try:
        r = analyseer_loper(inv, n_ensemble=args.n, seed=args.seed,
                            gevoeligheid=not args.geen_watals, progress=prog)
    except ValueError as e:
        print(f"\n\nKan de analyse niet uitvoeren:\n{e}")
        return 1
    print(f"\n  klaar in {time.time() - t0:.0f} s. Signaal: {r.signaal['kleur']}")
    for w in r.afgeleid.waarschuwingen:
        print(f"  ! {w}")
    plots = maak_alle_plots(r, uit / f"{stam}_figuren")
    docx = maak_rapport(r, plots, uit / f"{stam}.docx")
    xlsx = exporteer_excel(r, uit / f"{stam}.xlsx")
    print(f"Rapport:  {docx.resolve()}\nGegevens: {xlsx.resolve()}\nFiguren:  {(uit / (stam + '_figuren')).resolve()}")
    return 0


if __name__ == "__main__":
    # Alleen bij een fout een exitcode: in Spyder geeft sys.exit(0) anders
    # een verwarrende 'SystemExit'-melding.
    _rc = main()
    _interactief = hasattr(sys, "ps1") or "IPython" in sys.modules or "spyder_kernels" in sys.modules
    if _rc and not _interactief:
        sys.exit(_rc)
