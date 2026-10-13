# -*- coding: utf-8 -*-
"""
start_thermopoulos.py -- één startmenu voor de hele suite
=========================================================

Start dit bestand (in Spyder: F5, of `python start_thermopoulos.py`). Je kiest
dan uit een menu in plaats van zelf het juiste script te zoeken. Het menu:

  * laat zien welke weerbestanden (Thermopoulos_*.xlsx) er in de werkmap staan
    en voor welke periode, omdat PYROX, HESTIA en de loperanalyse er een nodig
    hebben;
  * zet de stappen in de goede volgorde en waarschuwt als een stap nog niet
    kan (bijvoorbeeld een analyse zonder weerbestand);
  * toont voor een Thermo Clinic per stap wat al gedaan is en wat de volgende
    stap is, en laat 'vergelijken' alleen toe na een vastgelegde voorspelling.

De werkmap is de map waar weerbestanden en uitvoer staan. De scripts zelf
blijven in de suitemap. Werkmap en clinicmap worden onthouden in
~/.thermopoulos_start.json (alleen paden, geen gegevens).
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
        print("  Weerbestanden: GEEN. Begin met stap 1 (Data Engine) of kies een andere werkmap.")
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
         "volgende": "kies eerst een clinicmap (optie 6)"}
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
    finally:
        input("\nEnter = terug naar het menu ")


def _clinic_stap(stap: str, cmap: Path | None, werkmap: Path | None = None) -> None:
    if not cmap:
        print("  Kies eerst een clinicmap (optie 6).")
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
# Menu
# -----------------------------------------------------------------------------
def menu() -> None:
    inst = _lees_instellingen()
    werkmap = Path(inst.get("werkmap", Path.cwd()))
    werkmap = werkmap if werkmap.exists() else Path.cwd()
    cmap = Path(inst["clinicmap"]) if inst.get("clinicmap") and Path(inst["clinicmap"]).exists() else None
    while True:
        print(f"\n{LIJN}\n  THERMOPOULOS  -  startmenu\n{LIJN}")
        print(f"  Werkmap: {werkmap}")
        w = toon_weer(werkmap)
        s = clinic_status(cmap)
        geen_weer = "  (eerst een weerbestand nodig: stap 1)" if not w else ""
        print(f"""
  STAP 1  WEER
    1  Weerdata ophalen (Data Engine) -> Thermopoulos_<plaats>.xlsx in de werkmap

  STAP 2  ANALYSES MET EEN WEERBESTAND{geen_weer}
    2  PYROX: hittebelasting van de bevolking
    3  HESTIA: evenement, deelnemers met Monte Carlo
    4  Persoonlijke loperanalyse (vragenlijst of opgeslagen invoer)

  LOS
    5  Klimatos: klimaattrend (haalt zelf het weer op)

  THERMO CLINIC (validatie, volgorde a -> b -> c -> d)""")
        toon_clinic(s)
        print("""    6  Clinicmap kiezen
    a  Leeg deelnemers.xlsx maken
    b  Voorspellen (modus A)        vóór je de FIT-bestanden bekijkt
    c  FIT-bestanden omzetten       uit <clinicmap>/fit_invoer, met codes, geen namen
    d  Vergelijken (modus B)        maakt Excel, figuren en Word-rapport

  HULPMIDDELEN
    7  Losse FIT-bestanden lezen (controle van sensor en horloge)
    8  Tests van de suite draaien
    W  Werkmap wijzigen
    0  Stoppen""")
        k = input("\nKeuze: ").strip().lower()
        if k == "":
            continue
        if k in ("0", "q"):
            _bewaar_instellingen({"werkmap": str(werkmap), "clinicmap": str(cmap) if cmap else ""})
            print("Tot ziens.")
            return
        if k == "w":
            werkmap = _vraag_map("Werkmap (map met weerbestanden en uitvoer)", werkmap)
        elif k == "1":
            draai_script("Thermopoulos_Data_Engine.py", werkmap)
        elif k in ("2", "3", "4"):
            if not w and input("  Er is nog geen weerbestand in de werkmap. Toch starten? (j/N): ") \
                    .strip().lower() not in ("j", "ja"):
                continue
            draai_script({"2": "run_pyrox.py", "3": "run_hestia.py", "4": "run_loper.py"}[k], werkmap)
        elif k == "5":
            draai_script("Klimatos_ClimateShift.py", werkmap)
        elif k == "6":
            cmap = _vraag_map("Clinicmap (met deelnemers.xlsx)", cmap or werkmap)
            print("  Zet het weerbestand van de clinicdag in deze map of vul het pad in op het "
                  "tabblad Clinic van deelnemers.xlsx.")
        elif k in ("a", "b", "c", "d"):
            clinic_stap(k, cmap, werkmap)
        elif k == "7":
            draai_script("fit_lezer.py", werkmap)
        elif k == "8":
            draai_tests()
        else:
            print("  Onbekende keuze.")
        _bewaar_instellingen({"werkmap": str(werkmap), "clinicmap": str(cmap) if cmap else ""})


if __name__ == "__main__":
    menu()
