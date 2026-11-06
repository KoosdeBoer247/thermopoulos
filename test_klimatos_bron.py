"""[2026-11-06] Klimatos requests one fixed reanalysis source for every year.

Without models= the Open-Meteo archive serves "Best Match", which switches to
a different source from 2017 (step of up to 1.5 degC in July maxima; see
TECHNICAL_REFERENCE section 5.1). This test intercepts the HTTP request of
fetch_hourly_year (no network) and checks that models=era5_seamless and
cell_selection=land are sent, for a year before and a year after 2017.
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import Klimatos_ClimateShift as K

fails = []


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


class _Resp:
    status_code = 200

    def __init__(self, year):
        import pandas as pd
        t = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
        n = len(t)
        h = {"time": [x.strftime("%Y-%m-%dT%H:%M") for x in t]}
        for f in K.REQUIRED_HOURLY_FIELDS:
            h[f] = list(np.full(n, 50.0 if "humidity" in f or "cloud" in f else 10.0))
        self._j = {"hourly": h, "latitude": 52.1, "longitude": 5.2}

    def raise_for_status(self):
        pass

    def json(self):
        return self._j


sent = []


def fake_get(url, params=None, timeout=None):
    sent.append(dict(params))
    return _Resp(int(params["start_date"][:4]))


K.requests.get = fake_get
for year in (2010, 2020):
    try:
        K.fetch_hourly_year(52.10, 5.18, "Europe/Amsterdam", year)
    except Exception as e:   # only the request matters here
        print(f"  (processing of the fake reply raised {type(e).__name__}: {e})")
check("two requests made", len(sent) >= 2, f"{len(sent)}")
for p in sent:
    y = p["start_date"][:4]
    check(f"{y}: models=era5_seamless", p.get("models") == "era5_seamless", str(p.get("models")))
    check(f"{y}: cell_selection=land", p.get("cell_selection") == "land", str(p.get("cell_selection")))
check("constant documented", K.ARCHIVE_MODEL == "era5_seamless")

print()
print("ALLE CONTROLES GESLAAGD" if not fails else f"{len(fails)} CONTROLE(S) MISLUKT")
sys.exit(1 if fails else 0)
