"""Test van aanmelding.py en de groepskoppeling (2026-10-29).

Met een verzonnen aanmeldlijst (verzonnen namen en e-mailadressen, example.com)
en verzonnen FIT-bestandsnamen in de Garmin-opmaak:
  1. kolommen herkend, afwezige loper overgeslagen;
  2. FIT-bestanden via het e-mailadres gekoppeld, code per Garmin-set (G001),
     dubbel e-mailadres opgelost via de vraag, loper zonder FIT -> N01;
  3. deelnemers.xlsx en fit_uitvoer bevatten GEEN naam of e-mailadres;
     de koppeltabel wel (privé);
  4. ontbrekend gewicht gemeld; standaardwaarden kleding/hitte_gewend;
  5. de codelijst is leesbaar voor groep_lopers.lees_lopers;
  6. tempo-aanpassing voor een andere loop (+15 % en vast tempo).
Leest geen echte FIT-bestanden (de lezer wordt vervangen); schrijft alleen in
een tijdelijke map.
"""
import atexit
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import aanmelding as am
import fit_lezer as fl
import groep_lopers as gl

TMP = Path(tempfile.mkdtemp(prefix="test_aanmelding_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
fails = []


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


# verzonnen aanmeldlijst in de opmaak van een loopgroep
lijst = pd.DataFrame([
    {"Email": "piet.proef@example.com", "aanwezig (Ja/Nee)": "Ja", "Datum": "Sun 11-Oct-2026",
     "Tijd": "14-17 uur", "Locatie": "Testduinen", "Leeftijd": 33, "Gender (M/V)": "m",
     "Gewicht voor de start": "93.4", "Gewicht na de finish": None, "Lengte ( cm )": 185,
     "Verwacht tempo": 5.4},
    {"Email": "Kees.Test@example.org", "aanwezig (Ja/Nee)": "Ja", "Datum": "Sun 11-Oct-2026",
     "Tijd": "14-17 uur", "Locatie": "Testduinen", "Leeftijd": 40, "Gender (M/V)": "M",
     "Gewicht voor de start": 82, "Lengte ( cm )": 180, "Verwacht tempo": "5:40"},
    {"Email": "afwezig@example.com", "aanwezig (Ja/Nee)": "Nee", "Datum": "Sun 11-Oct-2026",
     "Leeftijd": "afwezig"},
    {"Email": "gezin@example.net", "aanwezig (Ja/Nee)": "Ja", "Leeftijd": 33, "Gender (M/V)": "m",
     "Gewicht voor de start": 83, "Lengte ( cm )": 186, "Verwacht tempo": 5.4},
    {"Email": "gezin@example.net", "aanwezig (Ja/Nee)": "Ja", "Leeftijd": 65, "Gender (M/V)": "V",
     "Gewicht voor de start": None, "Lengte ( cm )": 170, "Verwacht tempo": "6:10"},
    {"Email": "zonderfit@example.com", "aanwezig (Ja/Nee)": "Ja (Arts)", "Leeftijd": 63,
     "Gender (M/V)": "v", "Gewicht voor de start": 60, "Lengte ( cm )": 168, "Verwacht tempo": "6:30"},
])
bron = TMP / "deelnemers.xlsx"          # zoals de organisatie hem noemt
lijst.to_excel(bron, index=False)
for naam in ["20261012_Garmin001_piet.proef-at-example.com.fit",
             "20261012_Garmin002_Kees.Test-at-example.org.fit",
             "20261012_Garmin008_gezin-at-example.net.fit",
             "20261012_Garmin014_gezin-at-example.net.fit",
             "20261012_Garmin020_onbekend-at-example.com.fit"]:
    (TMP / naam).write_bytes(b"")

check("aanmeldlijst herkend", am.is_aanmeldlijst(bron))
kaart = am.herken_kolommen(lijst.columns)
check("kolommen herkend", {"email", "leeftijd", "geslacht", "gewicht_voor_kg", "gewicht_na_kg",
                           "lengte_cm", "verwacht_tempo", "datum", "tijd", "locatie"} <= set(kaart.values()),
      str(sorted(kaart.values())))
check("gewicht na niet als gewicht voor", kaart["Gewicht na de finish"] == "gewicht_na_kg")
ll = am.lees_aanmeldlijst(bron)
check("afwezige overgeslagen", len(ll) == 5 and "afwezig@example.com" not in set(ll.email))

# lezer vervangen: geen echte FIT-bestanden nodig
class _Rit:
    def __init__(self, code):
        self.code, self.meta = code, {"datum": "2026-10-11", "duur_min": 45.0, "afstand_km": 8.1}

geexporteerd = []
_orig = fl.exporteer
fl.exporteer = lambda rit, map_: (Path(map_).mkdir(parents=True, exist_ok=True),
                                  (Path(map_) / f"{rit.code}_2026-10-11.xlsx").write_text("x"),
                                  geexporteerd.append(rit.code),
                                  {"xlsx": Path(map_) / f"{rit.code}_2026-10-11.xlsx"})[-1]
antwoorden = iter(["", "5", "", "64"])   # hernoemen: Enter=ja; dubbel: regel 5 (de tweede volgt vanzelf); onbekend bestand: Enter; gewicht 64
vraag = lambda t: next(antwoorden, "")
nieuw = am.bewaar_aanmeldlijst(bron, vraag=vraag)
check("aanmeldlijst hernoemd", nieuw.name == am.AANMELD_PRIVE and nieuw.exists() and not bron.exists())
res = am.omzetten(nieuw, vraag=vraag, fit_lezen=lambda p, code: _Rit(code), progress=lambda *_: None)
fl.exporteer = _orig
codes = {k.code: k for k in res.koppelingen}
check("codes per Garmin-set", {"G001", "G002", "G008", "G014"} <= set(codes), str(sorted(codes)))
check("loper zonder FIT krijgt N01", "N01" in codes and codes["N01"].fit is None)
check("dubbel e-mailadres via de vraag", codes["G008"].regel == 5 and codes["G014"].regel == 6)
check("onbekend bestand niet gekoppeld", len(res.niet_gekoppeld) == 1
      and "Garmin020" in res.niet_gekoppeld[0].name)
check("FIT-uitvoer met codes", sorted(geexporteerd) == ["G001", "G002", "G008", "G014"])

dn = pd.read_excel(res.deelnemers_xlsx, "Deelnemers", dtype=object)
tekst = dn.to_string() + pd.read_excel(res.deelnemers_xlsx, "Clinic", header=None).to_string()
check("codelijst zonder e-mail of naam", "@" not in tekst and "example" not in tekst.lower()
      and "piet" not in tekst.lower())
check("uitvoernamen zonder e-mail", all("example" not in p.name for p in (TMP / "fit_uitvoer").iterdir()))
kt = pd.read_excel(res.koppeltabel, "Koppeling")
check("koppeltabel bevat de koppeling (privé)", "piet.proef@example.com" in set(kt.email))
check("gewicht nagevraagd", float(dn.loc[dn.code == "G014", "gewicht_voor_kg"].iloc[0]) == 64.0)
check("standaard kleding en hitte_gewend", set(dn.kleding) == {"licht"} and set(dn.hitte_gewend) == {"n"})
check("clinicvelden uit de lijst", "2026-10-11" in tekst and "14:00" in tekst and "Testduinen" in tekst)
lopers = gl.lees_lopers(res.deelnemers_xlsx)
check("codelijst leesbaar voor groep_lopers", len(lopers) == 5, str(len(lopers)))
t1 = gl._tempo_aanpassen(lopers, "+15%")
g001 = next(d for d in t1 if d.code == "G001")
check("tempo +15 %", g001.verwacht_tempo == "6:13", g001.verwacht_tempo)   # 5:24 x 1,15
t2 = gl._tempo_aanpassen(lopers, "6:30")
check("vast tempo", {d.verwacht_tempo for d in t2} == {"6:30"})
t3 = gl._tempo_aanpassen(lopers, "m+10%", None)
check("gemeten tempo zonder meting valt terug op de lijst (+10 %)",
      next(d for d in t3 if d.code == "G001").verwacht_tempo == "5:56"
      and "tempo uit de lijst" in next(d for d in t3 if d.code == "G001").opmerking)
check("samenvatting meldt niet-gekoppeld", "Niet gekoppeld" in am.samenvatting(res))

print()
print("ALLE CONTROLES GESLAAGD" if not fails else f"{len(fails)} CONTROLE(S) MISLUKT")
sys.exit(1 if fails else 0)
