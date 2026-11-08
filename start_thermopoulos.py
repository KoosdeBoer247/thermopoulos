# -*- coding: utf-8 -*-
"""
start_thermopoulos.py -- één startmenu voor de hele suite
=========================================================

Start dit bestand (in Spyder: F5, of `python start_thermopoulos.py`). Het
hoofdmenu [2026-10-27] biedt vijf onderdelen: HESTIA (evenement of één loper),
PYROX, Klimatos, FIT-bestanden (één loop narekenen of een Thermo Clinic) en
het weer ophalen, plus R: een rapport maken van een eerdere berekening
(rapportpakket.py). Na elke berekening vraagt de suite of er meteen een
rapport moet komen. Het menu verder:

  * laat zien welke weerbestanden (Thermopoulos_*.xlsx) er in de werkmap staan
    en voor welke periode, omdat PYROX, HESTIA en de loperanalyse er een nodig
    hebben;
  * zet de stappen in de goede volgorde en waarschuwt als een stap nog niet
    kan (bijvoorbeeld een analyse zonder weerbestand);
  * toont voor een Thermo Clinic per stap wat al gedaan is en wat de volgende
    stap is, en laat 'vergelijken' alleen toe na een vastgelegde voorspelling.

De werkmap is de map waar weerbestanden en uitvoer staan: de map van waaruit
het menu is opgestart (in Spyder: de map van dit script). Met W kies je voor
deze sessie een andere werkmap; die wordt niet onthouden. Alleen de clinicmap
wordt onthouden in ~/.thermopoulos_start.json (alleen een pad, geen gegevens).
[2026-10-28] Eerder werd ook de werkmap onthouden, waardoor uitvoer in een
oude map belandde.
"""
from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import traceback
from pathlib import Path

SUITE = Path(__file__).resolve().parent
INSTELLINGEN = Path.home() / ".thermopoulos_start.json"
if str(SUITE) not in sys.path:
    sys.path.insert(0, str(SUITE))

LIJN = "=" * 70


# -----------------------------------------------------------------------------
# Instellingen
# -----------------------------------------------------------------------------
def _lees_instellingen() -> dict:
    try:
        return json.loads(INSTELLINGEN.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _bewaar_instellingen(d: dict) -> None:
    try:
        INSTELLINGEN.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except Exception:
        pass


def _vraag_map(tekst: str, standaard: Path) -> Path:
    s = input(f"{tekst} [{standaard}]: ").strip().strip('"')
    p = Path(s).expanduser() if s else standaard
    if not p.exists():
        if input(f"  {p} bestaat niet. Aanmaken? (j/N): ").strip().lower() in ("j", "ja"):
            p.mkdir(parents=True, exist_ok=True)
        else:
            return standaard
    return p.resolve()


# -----------------------------------------------------------------------------
# Status
# -----------------------------------------------------------------------------
def weerbestanden(map_: Path) -> list[dict]:
    """Thermopoulos_*.xlsx in de map, nieuwste eerst, met plaats en perioden."""
    uit = []
    for p in sorted(map_.glob("Thermopoulos_*.xlsx"), key=lambda x: x.stat().st_mtime, reverse=True):
        info = {"pad": p, "plaats": "?", "verwachting": "", "hindcast": "", "eigen": ""}
        try:
            import pandas as pd
            m = pd.read_excel(p, sheet_name="Metadata").iloc[0]
            info["plaats"] = str(m.get("city", "?"))
            kort = lambda s: str(s)[:10] + " t/m " + str(s).split(" to ")[-1][:10] if " to " in str(s) else ""
            info["verwachting"] = kort(m.get("forecast_period", ""))
            info["hindcast"] = kort(m.get("hindcast_period", ""))
            eigen = m.get("custom_historical_period", "")
            info["eigen"] = kort(eigen) if isinstance(eigen, str) and eigen != "None" else ""
        except Exception:
            pass
        uit.append(info)
    return uit


def toon_weer(map_: Path) -> list[dict]:
    w = weerbestanden(map_)
    if not w:
        print("  Weerbestanden: GEEN. Haal eerst het weer op (keuze 5) of kies een andere werkmap.")
        return w
    print(f"  Weerbestanden: {len(w)} (nieuwste eerst)")
    for i in w[:3]:
        extra = f", eigen periode {i['eigen']}" if i["eigen"] else ""
        print(f"    - {i['pad'].name}: {i['plaats']}; verwachting {i['verwachting']}; "
              f"hindcast {i['hindcast']}{extra}")
    if len(w) > 3:
        print(f"    ... en {len(w) - 3} oudere")
    return w


def clinic_status(cmap: Path | None) -> dict:
    s = {"map": cmap, "deelnemers": False, "voorspeld": False, "fit": 0, "vergeleken": False,
         "volgende": "kies eerst een clinicmap (K)"}
    if not cmap or not cmap.exists():
        return s
    s["deelnemers"] = (cmap / "deelnemers.xlsx").exists()
    s["voorspeld"] = (cmap / "modus_A" / "vastlegging.json").exists()
    s["fit"] = len(list((cmap / "fit_uitvoer").glob("*.xlsx"))) if (cmap / "fit_uitvoer").exists() else 0
    s["vergeleken"] = (cmap / "validatie_uitvoer" / "validatie.xlsx").exists()
    if not s["deelnemers"]:
        s["volgende"] = "a: leeg deelnemers.xlsx maken en laten invullen"
    elif not s["voorspeld"]:
        s["volgende"] = "b: voorspellen (modus A), VOORDAT je de FIT-bestanden bekijkt"
    elif s["fit"] == 0:
        s["volgende"] = "c: FIT-bestanden omzetten"
    elif not s["vergeleken"]:
        s["volgende"] = "d: vergelijken (modus B + rapport)"
    else:
        s["volgende"] = "klaar; rapport staat in validatie_uitvoer"
    return s


def toon_clinic(s: dict) -> None:
    if not s["map"]:
        print("  Clinicmap: nog niet gekozen")
        return
    v = lambda b: "ja " if b else "nee"
    print(f"  Clinicmap: {s['map']}")
    print(f"    a deelnemers.xlsx: {v(s['deelnemers'])}   b voorspelling vastgelegd: {v(s['voorspeld'])}   "
          f"c FIT-exports: {s['fit']}   d vergeleken: {v(s['vergeleken'])}")
    print(f"    Volgende stap: {s['volgende']}")


# -----------------------------------------------------------------------------
# Uitvoeren
# -----------------------------------------------------------------------------
def draai_script(naam: str, werkmap: Path, argv: list[str] | None = None) -> None:
    """Een script van de suite draaien alsof je het zelf start, met de werkmap
    als huidige map (daar zoeken de scripts hun weerbestand en schrijven ze)."""
    pad = SUITE / naam
    oud_cwd, oud_argv = Path.cwd(), sys.argv[:]
    print(f"\n{LIJN}\n  {naam}  (werkmap: {werkmap})\n{LIJN}")
    try:
        os.chdir(werkmap)
        sys.argv = [str(pad)] + (argv or [])
        runpy.run_path(str(pad), run_name="__main__")
    except SystemExit:
        pass
    except KeyboardInterrupt:
        print("\n  Afgebroken.")
    except Exception:
        print("\n  ! Er ging iets mis:")
        traceback.print_exc()
    finally:
        os.chdir(oud_cwd)
        sys.argv = oud_argv
    input("\nEnter = terug naar het menu ")


def clinic_stap(stap: str, cmap: Path | None, werkmap: Path | None = None) -> None:
    try:
        _clinic_stap(stap, cmap, werkmap)
    except ImportError as e:
        print(f"\n  ! Een benodigd pakket ontbreekt of heeft de verkeerde versie:\n    {e}")
        print("    Installeer de geteste versies met:  pip install -r requirements.txt")
        print("    (in Spyder: %pip install -r requirements.txt, daarna de kernel herstarten)")
    except Exception:
        print("\n  ! Er ging iets mis:")
        traceback.print_exc()
    finally:
        input("\nEnter = terug naar het menu ")


def _clinic_stap(stap: str, cmap: Path | None, werkmap: Path | None = None) -> None:
    if not cmap:
        print("  Kies eerst een clinicmap (K).")
        return
    import clinic_validatie as cv
    s = clinic_status(cmap)
    try:
        if stap == "a":
            print("  Gemaakt:", cv.sjabloon(cmap))
        elif stap == "b":
            if not s["deelnemers"]:
                print("  Eerst stap a: deelnemers.xlsx ontbreekt.")
                return
            if s["fit"]:
                print("  LET OP: er staan al FIT-exports in deze clinicmap. De voorspelling is dan "
                      "niet meer blind; het rapport meldt dat.")
                if input("  Toch doorgaan? (j/N): ").strip().lower() not in ("j", "ja"):
                    return
            cv.voorspel(cmap)
        elif stap == "c":
            if not s["voorspeld"]:
                print("  De voorspelling (stap b) is nog niet vastgelegd.")
                if input("  FIT-bestanden toch nu omzetten? Dan is stap b daarna niet meer blind. (j/N): ") \
                        .strip().lower() not in ("j", "ja"):
                    return
            print("  Zet de .fit-bestanden in de clinicmap of in de submap fit_invoer.")
            oud = Path.cwd()
            try:
                os.chdir(cmap)
                cv.fit_omzetten(cmap)
            finally:
                os.chdir(oud)
        elif stap == "d":
            if not s["voorspeld"]:
                print("  Eerst stap b: er is geen vastgelegde voorspelling.")
                return
            if s["fit"] == 0:
                print("  Eerst stap c: er zijn nog geen FIT-exports.")
                return
            cv.vergelijk(cmap, weerbestand=kies_weer_b(cmap, werkmap))
    except (ValueError, FileNotFoundError, FileExistsError) as e:
        print("\n  ! " + str(e))
    except Exception:
        traceback.print_exc()


def kies_weer_b(cmap: Path, werkmap: Path | None):
    """Los weerbestand voor de reconstructie (bijv. archiefweer achteraf).
    deelnemers.xlsx blijft ongewijzigd; Enter = het bestand daaruit."""
    kandidaten, gezien = [], set()
    for m in (cmap, werkmap):
        if m and Path(m).exists():
            for w in weerbestanden(Path(m)):
                if w["pad"].resolve() not in gezien:
                    gezien.add(w["pad"].resolve())
                    kandidaten.append(w)
    if not kandidaten:
        return None
    print("\n  Welk weer voor de reconstructie (modus B)?")
    print("    Enter = het weerbestand uit deelnemers.xlsx (hetzelfde als de voorspelling)")
    for i, w in enumerate(kandidaten, 1):
        extra = f", eigen periode {w['eigen']}" if w["eigen"] else ""
        print(f"    {i} = {w['pad'].name}: {w['plaats']}{extra}")
    k = input("  Keuze: ").strip()
    if k.isdigit() and 1 <= int(k) <= len(kandidaten):
        p = kandidaten[int(k) - 1]["pad"]
        print(f"  Modus B rekent met {p.name}; uitvoer in validatie_uitvoer_{p.stem}")
        return p
    return None


def draai_tests() -> None:
    tests = [("Loper-module", "test_loper.py"), ("Clinicketen", "test_clinic.py"),
             ("Zweetverlies", "test_zweet_fix.py"), ("FIT-lezer", "test_fit_lezer.py"),
             ("PYROX tegen de publicatie", "verify.py")]
    print("\n  Tests draaien (dit duurt enkele minuten)...")
    env = dict(os.environ, PYTHONPATH=str(SUITE))
    for label, naam in tests:
        if not (SUITE / naam).exists():
            continue
        r = subprocess.run([sys.executable, str(SUITE / naam)], cwd=str(SUITE), env=env,
                           capture_output=True, text=True)
        laatste = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()][-1:] or [""]
        print(f"  {'OK  ' if r.returncode == 0 else 'FOUT'}  {label:28s} {laatste[0][:70]}")
    input("\nEnter = terug naar het menu ")


# -----------------------------------------------------------------------------
# Rapport later maken
# -----------------------------------------------------------------------------
def rapport_later(werkmap: Path, cmap: Path | None) -> None:
    """Keuze R: een rapport maken van een eerdere berekening (rapportpakket)."""
    import rapportpakket as rp
    mappen = [werkmap, SUITE] + [p for p in werkmap.glob("*") if p.is_dir()]
    pakketten = rp.vind(*mappen)
    print(f"\n{LIJN}\n  RAPPORT MAKEN VAN EEN EERDERE BEREKENING\n{LIJN}")
    if not pakketten:
        print("  Geen bewaarde berekeningen gevonden in de werkmap of de suitemap.\n"
              "  Elke berekening (HESTIA, PYROX, Klimatos, FIT-loop) bewaart vanaf nu zijn\n"
              "  rapportgegevens als *_rapportpakket.pkl; daarna verschijnt hij hier.")
    else:
        for i, p in enumerate(pakketten[:20], 1):
            print(f"    {i:>2}  {rp.omschrijving(p)}")
    if cmap and (cmap / "validatie_uitvoer").exists():
        print("\n  Thermo Clinic: het validatierapport maak je opnieuw met keuze 4 -> d.")
    k = input("\n  Nummer (Enter = terug): ").strip()
    if k.isdigit() and 1 <= int(k) <= min(20, len(pakketten)):
        oud = Path.cwd()
        try:
            os.chdir(pakketten[int(k) - 1].parent)
            rp.maak(pakketten[int(k) - 1])
        except Exception:
            print("\n  ! Het rapport lukte niet:")
            traceback.print_exc()
        finally:
            os.chdir(oud)
        input("\nEnter = terug naar het menu ")


# -----------------------------------------------------------------------------
# Menu's
# -----------------------------------------------------------------------------
def _weer_nodig(w: list) -> bool:
    if w:
        return True
    return input("  Er staat nog geen weerbestand in de werkmap (eerst keuze 5). Toch starten? (j/N): ") \
        .strip().lower() in ("j", "ja")


def menu_hestia(werkmap: Path, w: list) -> None:
    while True:
        print(f"""
{LIJN}
  HESTIA  -  hitterisico voor lopers en evenementen
{LIJN}
    1  Evenement: alle deelnemers doorrekenen (Monte Carlo)
         kans op hitte-incidenten, kerntemperatuur en hartreserve van de groep
    2  Persoonlijke loperanalyse: één loper, eigen gegevens en tempo
         risicosignaal, kerntemperatuur, hartslag en vochtverlies voor die loper
    3  Groep bekende lopers door een gekozen loop sturen (wat-als)
         lijst met lopers (zoals deelnemers.xlsx van een clinic) + plaats, datum,
         starttijd en afstand; verleden (archiefweer) of komende ~16 dagen

    Na elke berekening vraagt de suite of er meteen een rapport moet komen.
    0  Terug naar het hoofdmenu""")
        k = input("\nKeuze: ").strip().lower()
        if k in ("0", "", "q"):
            return
        if k in ("1", "2") and _weer_nodig(w):
            draai_script({"1": "run_hestia.py", "2": "run_loper.py"}[k], werkmap)
        elif k == "3" and _weer_nodig(w):
            oud = Path.cwd()
            try:
                os.chdir(werkmap)
                import groep_lopers
                groep_lopers.interactief(werkmap)
            except Exception:
                traceback.print_exc()
            finally:
                os.chdir(oud)
            input("\nEnter = terug naar het menu ")
        elif k not in ("1", "2", "3"):
            print("  Onbekende keuze.")


def _run_in(werkmap: Path, fn) -> None:
    """Een functie draaien met de werkmap als huidige map (zoals draai_script)."""
    oud = Path.cwd()
    try:
        os.chdir(werkmap)
        fn()
    except KeyboardInterrupt:
        print("\n  Afgebroken.")
    except Exception:
        print("\n  ! Er ging iets mis:")
        traceback.print_exc()
    finally:
        os.chdir(oud)
    input("\nEnter = terug naar het menu ")


def menu_gevoeligheid(werkmap: Path, w: list) -> None:
    """[2026-11-08] ERA5-gevoeligheid: wat als het echte weer anders was dan
    ERA5 aangeeft? Hypothetische scenario's, geen correcties (gevoeligheid.py)."""
    while True:
        print(f"""
{LIJN}
  GEVOELIGHEID  -  hoe sterk hangt de uitkomst af van de weerinvoer (ERA5)?
{LIJN}
    1  HESTIA-evenement onder alle scenario's
    2  PYROX-hittegolf onder alle scenario's
    3  Alleen scenario-weerbestanden maken (zelf verder rekenen)
    4  Klimatos met gevoeligheid (welke conclusies blijven overeind?)

    Scenario's: ERA5 zoals geleverd (neutraal), -1 tot +3 graden, overdag
    warmer en 's nachts koeler, vochtiger, minder wind, meer zon; bij een
    kustlocatie ook de kustcorrectie (piek 2, 3, 4 en 6 graden). Een eigen
    lijst kan in gevoeligheid_scenarios.json in de werkmap.
    0  Terug naar het hoofdmenu""")
        k = input("\nKeuze: ").strip().lower()
        if k in ("0", "", "q"):
            return
        if k in ("1", "2", "3") and _weer_nodig(w):
            import run_gevoeligheid as rg

            def stap():
                from thermopoulos_loader import choose_thermopoulos_file
                base = choose_thermopoulos_file(".")
                if base is None:
                    return
                {"1": rg.interactive_hestia, "2": rg.interactive_pyrox,
                 "3": rg.interactive_files_only}[k](Path(base))
            _run_in(werkmap, stap)
        elif k == "4":
            print("  Klimatos vraagt na de UHI-vraag of de gevoeligheidsanalyse mee moet: antwoord y.")
            draai_script("Klimatos_ClimateShift.py", werkmap)
        elif k not in ("1", "2", "3"):
            print("  Onbekende keuze.")


def menu_fit(werkmap: Path, cmap: Path | None) -> Path | None:
    while True:
        s = clinic_status(cmap)
        print(f"""
{LIJN}
  FIT-BESTANDEN  -  metingen van horloge en CORE-sensor met HESTIA verwerken
{LIJN}
    1  Eén loop narekenen
         één FIT-bestand + het weer van die dag; HESTIA rekent de loop na met het
         gemeten tempo en vergelijkt met de gemeten hartslag en kerntemperatuur

    THERMO CLINIC  (groep lopers, voorspelling vooraf; volgorde a -> b -> c -> d)""")
        toon_clinic(s)
        print("""    K  Clinicmap kiezen
    a  Leeg deelnemers.xlsx maken
    b  Voorspellen (modus A)        vóór je de FIT-bestanden bekijkt
    c  FIT-bestanden omzetten       uit <clinicmap>/fit_invoer, met codes, geen namen
    d  Vergelijken (modus B)        maakt Excel, figuren en het validatierapport

    G  Aanmeldlijst + FIT-bestanden automatisch naar codes (Garmin001 -> G001)
         herkent de e-mailadressen in de FIT-bestandsnamen; namen en e-mail komen
         alleen in PRIVE_koppeltabel.xlsx, nooit in een rapport
    F  Een FIT-bestand controleren (sensor en horloge, zonder model)
    0  Terug naar het hoofdmenu""")
        k = input("\nKeuze: ").strip().lower()
        if k in ("0", "", "q"):
            return cmap
        if k == "1":
            oud = Path.cwd()
            try:
                os.chdir(werkmap)
                import fit_loop
                fit_loop.interactief(werkmap)
            except Exception:
                traceback.print_exc()
            finally:
                os.chdir(oud)
            input("\nEnter = terug naar het menu ")
        elif k == "g":
            doel = cmap or werkmap
            print(f"  Map: {doel}  (kies eerst K voor een andere map)")
            try:
                import aanmelding
                uit = aanmelding.interactief(doel)
                if uit:
                    cmap = Path(uit).parent
            except ImportError as e:
                print(f"\n  ! Een benodigd pakket ontbreekt: {e}")
            except Exception:
                traceback.print_exc()
            input("\nEnter = terug naar het menu ")
        elif k == "k":
            cmap = _vraag_map("Clinicmap (met deelnemers.xlsx)", cmap or werkmap)
            print("  Zet het weerbestand van de clinicdag in deze map of vul het pad in op het "
                  "tabblad Clinic van deelnemers.xlsx.")
        elif k in ("a", "b", "c", "d"):
            clinic_stap(k, cmap, werkmap)
        elif k == "f":
            draai_script("fit_lezer.py", werkmap)
        else:
            print("  Onbekende keuze.")


def _pakket_waarschuwing() -> str | None:
    """Waarschuwing als pythermalcomfort niet de geteste versie heeft."""
    try:
        from importlib.metadata import version
        v = version("pythermalcomfort")
    except Exception:
        return "pythermalcomfort is niet geïnstalleerd"
    if v != "4.6.2" and not os.environ.get("HESTIA_ALLOW_OTHER_PYTHERMALCOMFORT"):
        return f"pythermalcomfort {v} gevonden, HESTIA heeft 4.6.2 nodig"
    return None


def menu() -> None:
    inst = _lees_instellingen()
    werkmap = Path.cwd().resolve()          # [2026-10-28] altijd de opstartmap
    cmap = Path(inst["clinicmap"]) if inst.get("clinicmap") and Path(inst["clinicmap"]).exists() else None
    pw = _pakket_waarschuwing()
    while True:
        print(f"\n{LIJN}\n  THERMOPOULOS  -  hoofdmenu\n{LIJN}")
        print(f"  Werkmap: {werkmap}")
        if pw:
            print(f"  LET OP: {pw}.\n          HESTIA, FIT en clinic werken dan niet. Installeer met:"
                  f" pip install -r requirements.txt\n          (in Spyder: %pip install -r requirements.txt,"
                  f" daarna de kernel herstarten)")
        w = toon_weer(werkmap)
        print("""
    1  HESTIA         hitterisico voor lopers en evenementen
                      (evenement met alle deelnemers, één loper, of een groep
                      bekende lopers in een gekozen loop)
    2  PYROX          hittebelasting van bevolkingsgroepen tijdens een hittegolf
    3  KLIMATOS       klimaattrend en toekomst rond een vaste datum of evenement
                      (haalt zelf het historische weer op)
    4  FIT-BESTANDEN  metingen van horloge en CORE-sensor inlezen en met HESTIA
                      narekenen: één loop, of een Thermo Clinic

    5  WEER           weerdata ophalen met de Data Engine (verwachting of archief);
                      nodig voor 1, 2, 4 en 6
    6  GEVOELIGHEID   wat als het echte weer anders was dan ERA5 aangeeft?
                      HESTIA, PYROX of Klimatos opnieuw met verschoven weer
    R  RAPPORT        een rapport maken van een eerdere berekening

    T  Tests van de suite     W  Werkmap wijzigen     0  Stoppen""")
        k = input("\nKeuze: ").strip().lower()
        if k == "":
            continue
        if k in ("0", "q"):
            _bewaar_instellingen({"clinicmap": str(cmap) if cmap else ""})
            print("Tot ziens.")
            return
        if k == "1":
            menu_hestia(werkmap, w)
        elif k == "2":
            if _weer_nodig(w):
                draai_script("run_pyrox.py", werkmap)
        elif k == "3":
            draai_script("Klimatos_ClimateShift.py", werkmap)
        elif k == "4":
            cmap = menu_fit(werkmap, cmap)
        elif k == "5":
            draai_script("Thermopoulos_Data_Engine.py", werkmap)
        elif k == "6":
            menu_gevoeligheid(werkmap, w)
        elif k == "r":
            rapport_later(werkmap, cmap)
        elif k == "t":
            draai_tests()
        elif k == "w":
            werkmap = _vraag_map("Werkmap voor deze sessie (map met weerbestanden en uitvoer)", werkmap)
        else:
            print("  Onbekende keuze.")
        _bewaar_instellingen({"clinicmap": str(cmap) if cmap else ""})


if __name__ == "__main__":
    menu()
