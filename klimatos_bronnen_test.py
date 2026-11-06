"""Klimatos: welke ERA5-bron levert het Open-Meteo-archief, en geeft die een
sprong rond 2017? Test voor meerdere locaties tegelijk.

Per locatie en per jaar (2007-2025) haalt het script uurwaarden van de 2 m-
temperatuur, de relatieve vochtigheid en de wind op 10 m op, voor vier bronnen:
  standaard      geen models= (precies wat Klimatos nu doet)
  era5           ERA5, ca. 25 km
  era5_land      ERA5-Land, ca. 11 km (geen wind)
  era5_seamless  ERA5-Land T/RV + ERA5 wind/straling (wat de Data Engine doet)
Allemaal met de standaard celkeuze 'land', net als Klimatos.

Per jaar: jaarmaximum T, gemiddelde maximale dagtemperatuur in juli,
gemiddelde wind, gemiddelde relatieve vochtigheid. Daarna:
  * is 'standaard' gelijk aan era5 (dan krijgt Klimatos gewoon ERA5)?
  * verschil standaard - era5_land voor 2017 en vanaf 2017 (sprong?)
  * welke rastercel (lat, lon, hoogte) elke bron kiest.

Gebruik:   python klimatos_bronnen_test.py
Uitvoer:   op het scherm, en klimatos_bronnen_resultaat.json in dezelfde map.
           Upload dat json-bestand in de chat voor het testrapport.
Rekentijd: 7 locaties x 4 bronnen x 19 jaar = 532 aanvragen, ca. 15-30 min.
Alleen standaardbibliotheek van Python nodig.
"""
import json
import statistics as st
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

LOCATIES = [   # (naam, lat, lon, soort)
    ("De Bilt", 52.10, 5.18, "binnenland"),
    ("Den Helder", 52.96, 4.76, "zee"),
    ("Scheveningen", 52.11, 4.28, "zee, stad"),
    ("Enkhuizen", 52.70, 5.29, "groot meer (IJsselmeer)"),
    ("Falmouth MA", 41.55, -70.61, "zee (KFMH-vergelijking)"),
    ("Chennai", 13.08, 80.27, "tropisch, zee, stad"),
    ("Hyderabad", 17.39, 78.49, "tropisch, binnenland, stad"),
]
JAREN = list(range(2007, 2026))
BRONNEN = ["standaard", "era5", "era5_land", "era5_seamless"]
URL = "https://archive-api.open-meteo.com/v1/archive"
UIT = Path(__file__).with_name("klimatos_bronnen_resultaat.json")


def haal(lat, lon, jaar, bron):
    q = dict(latitude=lat, longitude=lon, start_date=f"{jaar}-01-01", end_date=f"{jaar}-12-31",
             hourly="temperature_2m,wind_speed_10m,relative_humidity_2m", timezone="GMT", wind_speed_unit="ms")
    if bron != "standaard":
        q["models"] = bron
    for poging in range(6):
        try:
            with urllib.request.urlopen(URL + "?" + urllib.parse.urlencode(q), timeout=90) as r:
                return json.load(r)
        except Exception as e:   # 429 (te veel aanvragen) of netwerk: wachten en opnieuw
            wacht = 15 * (poging + 1)
            print(f"    {jaar} {bron}: {e}; opnieuw over {wacht} s", flush=True)
            time.sleep(wacht)
    raise RuntimeError(f"{jaar} {bron} mislukt")


def samenvat(d):
    h = d["hourly"]
    t = [x for x in h["temperature_2m"] if x is not None]
    w = [x for x in h["wind_speed_10m"] if x is not None]
    rv = [x for x in h["relative_humidity_2m"] if x is not None]
    juli = {}
    for ts, x in zip(h["time"], h["temperature_2m"]):
        if x is not None and ts[5:7] == "07":
            juli[ts[:10]] = max(juli.get(ts[:10], -99.0), x)
    return {"tmax_jaar": max(t) if t else None,
            "tmax_juli_gem": st.mean(juli.values()) if juli else None,
            "wind_gem": st.mean(w) if w else None,
            "rv_gem": st.mean(rv) if rv else None,
            "cel": [d.get("latitude"), d.get("longitude"), d.get("elevation")]}


def verschil(res, a, b, k):
    voor = [res[a][j][k] - res[b][j][k] for j in JAREN
            if j < 2017 and res[a][j][k] is not None and res[b][j][k] is not None]
    na = [res[a][j][k] - res[b][j][k] for j in JAREN
          if j >= 2017 and res[a][j][k] is not None and res[b][j][k] is not None]
    if not voor or not na:
        return None
    return {"voor_2017": round(st.mean(voor), 3), "vanaf_2017": round(st.mean(na), 3),
            "sprong": round(st.mean(na) - st.mean(voor), 3)}


alles = {"jaren": JAREN, "bronnen": BRONNEN, "locaties": {}}
for naam, lat, lon, soort in LOCATIES:
    print(f"\n=== {naam} ({soort})", flush=True)
    res = {b: {} for b in BRONNEN}
    for jaar in JAREN:
        for b in BRONNEN:
            res[b][jaar] = samenvat(haal(lat, lon, jaar, b))
            time.sleep(1.0)
        print(f"  {jaar} klaar", flush=True)
    gelijk = all(res["standaard"][j]["tmax_jaar"] is not None and res["era5"][j]["tmax_jaar"] is not None
                 and abs(res["standaard"][j]["tmax_jaar"] - res["era5"][j]["tmax_jaar"]) < 0.05
                 for j in JAREN)
    loc = {"lat": lat, "lon": lon, "soort": soort,
           "cel_per_bron": {b: res[b][JAREN[-1]]["cel"] for b in BRONNEN},
           "standaard_is_era5": gelijk,
           "per_jaar": {b: {j: {k: res[b][j][k] for k in ("tmax_jaar", "tmax_juli_gem", "wind_gem", "rv_gem")}
                            for j in JAREN} for b in BRONNEN},
           "sprong": {
               "tmax_jaar standaard-era5_land": verschil(res, "standaard", "era5_land", "tmax_jaar"),
               "tmax_juli standaard-era5_land": verschil(res, "standaard", "era5_land", "tmax_juli_gem"),
               "tmax_juli standaard-era5": verschil(res, "standaard", "era5", "tmax_juli_gem"),
               "tmax_juli era5_seamless-era5": verschil(res, "era5_seamless", "era5", "tmax_juli_gem"),
               "wind standaard-era5": verschil(res, "standaard", "era5", "wind_gem"),
               "rv standaard-era5_land": verschil(res, "standaard", "era5_land", "rv_gem"),
           }}
    alles["locaties"][naam] = loc
    print(f"  rastercel per bron: {loc['cel_per_bron']}")
    print(f"  standaard == era5: {'JA' if gelijk else 'NEE'}")
    for k, v in loc["sprong"].items():
        print(f"  {k}: {v}")
    UIT.write_text(json.dumps(alles, indent=1))   # tussentijds opslaan

print(f"\nKlaar. Resultaat: {UIT}")
