"""[2026-11-12] ERA5 runs about 5 days behind real time. fetch_historical_data
fills that recent gap from the forecast API's recent analyses (past_days).

No network: requests.get is replaced by a fake that serves
  * the archive (era5_seamless): 14 days, the last 5 days null;
  * the forecast API (knmi_seamless, past_days): the recent days filled.
Checked:
  1. after fetch_historical_data no hour is missing any more;
  2. the filled hours are marked from_forecast_api, the ERA5 hours are not;
  3. the forecast request asks for past_days covering the gap and uses knmi_seamless;
  4. the ERA5 coastal correction is not applied to the filled hours;
  5. an old gap (more than RECENT_GAP_DAYS ago) is left alone, without a request;
  6. a failing forecast API leaves the gap as it was, without an exception.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import Thermopoulos_Data_Engine as DE

fails = []


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


TZ = "Europe/Amsterdam"
VANDAAG = pd.Timestamp.now(tz=TZ).normalize()
START = VANDAAG - pd.Timedelta(days=14)
EIND = VANDAAG - pd.Timedelta(days=1)
GAT_VANAF = VANDAAG - pd.Timedelta(days=5)


def _uren(a, b):
    return pd.date_range(a.tz_localize(None), b.tz_localize(None) + pd.Timedelta(hours=23), freq="h")


class _Resp:
    def __init__(self, j, status=200):
        self._j, self.status_code = j, status

    def json(self):
        return self._j

    def raise_for_status(self):
        if self.status_code >= 400:
            raise DE.requests.HTTPError(f"{self.status_code}")


AANVRAGEN = []


def nep_get(url, params=None, timeout=None, **kw):
    AANVRAGEN.append((url, dict(params or {})))
    if "archive" in url:
        t = _uren(pd.Timestamp(params["start_date"], tz=TZ), pd.Timestamp(params["end_date"], tz=TZ))
        leeg = t >= GAT_VANAF.tz_localize(None)
        h = {"time": [x.strftime("%Y-%m-%dT%H:%M") for x in t]}
        for v, w in (("temperature_2m", 20.0), ("relative_humidity_2m", 60.0), ("surface_pressure", 1013.0),
                     ("wind_speed_10m", 3.0), ("shortwave_radiation", 300.0), ("cloud_cover", 40.0)):
            h[v] = [None if l else w for l in leeg]
        return _Resp({"hourly": h, "latitude": 52.1, "longitude": 5.2})
    if FORECAST_FAALT:
        return _Resp({"error": True, "reason": "server"}, status=500)
    past = int(params["past_days"])
    t = pd.date_range((VANDAAG - pd.Timedelta(days=past)).tz_localize(None),
                      (VANDAAG + pd.Timedelta(days=1)).tz_localize(None) - pd.Timedelta(hours=1), freq="h")
    h = {"time": [x.strftime("%Y-%m-%dT%H:%M") for x in t]}
    for v, w in (("temperature_2m", 25.0), ("relative_humidity_2m", 55.0), ("surface_pressure", 1010.0),
                 ("wind_speed_10m", 4.0), ("shortwave_radiation", 400.0), ("cloud_cover", 20.0)):
        h[v] = [w] * len(t)
    return _Resp({"hourly": h})


FORECAST_FAALT = False
DE.requests.get = nep_get

print("1-3. Recent gap filled from the forecast API")
df, kust = DE.fetch_historical_data(52.1, 5.18, TZ, f"{START:%Y-%m-%d}", f"{EIND:%Y-%m-%d}")
check("no missing hours left", int(df["T_air_rural"].isna().sum()) == 0, f"{int(df['T_air_rural'].isna().sum())} missing")
recent = df.index >= GAT_VANAF
check("filled hours marked from_forecast_api", bool(df.loc[recent, "from_forecast_api"].all()))
check("ERA5 hours not marked", not bool(df.loc[~recent, "from_forecast_api"].any()))
check("filled hours carry the forecast values", bool(np.allclose(df.loc[recent, "T_air_rural"], 25.0)))
check("ERA5 hours unchanged", bool(np.allclose(df.loc[~recent, "T_air_rural"], 20.0)))
fc = [p for u, p in AANVRAGEN if "forecast" in u]
check("one forecast request", len(fc) == 1, str(len(fc)))
check("forecast request uses knmi_seamless", fc and fc[0].get("models") == "knmi_seamless")
check("past_days covers the gap", fc and int(fc[0]["past_days"]) >= 5, str(fc[0].get("past_days") if fc else None))

print("4. Coastal correction not applied to the filled hours")
proc = DE.process_weather_data(df.copy(), {"population": 0}, 52.1, 5.18, TZ, True, 0.03)
corr = proc["coastal_correction_degrees"]
check("no correction on forecast hours", float(corr[recent].abs().max()) == 0.0)
check("correction still on ERA5 daytime hours", float(corr[~recent].max()) > 0.5, f"max {float(corr[~recent].max()):.2f}")

print("5. Old gap left alone")
AANVRAGEN.clear()
oud = df.copy()
oud.index = oud.index - pd.Timedelta(days=40)
oud.loc[oud.index[-10:], "T_air_rural"] = np.nan
uit = DE.fill_recent_gap(oud.drop(columns=["from_forecast_api"]), 52.1, 5.18, TZ)
check("no forecast request for an old gap", not [u for u, _ in AANVRAGEN if "forecast" in u])
check("old gap still missing", int(uit["T_air_rural"].isna().sum()) == 10)

print("6. Failing forecast API")
FORECAST_FAALT = True
AANVRAGEN.clear()
df2, _ = DE.fetch_historical_data(52.1, 5.18, TZ, f"{START:%Y-%m-%d}", f"{EIND:%Y-%m-%d}")
check("no exception, gap stays missing", int(df2["T_air_rural"].isna().sum()) == 5 * 24,
      f"{int(df2['T_air_rural'].isna().sum())} missing")

print()
if fails:
    print(f"FAILED: {len(fails)} check(s): {fails}")
    sys.exit(1)
print("All checks passed.")
