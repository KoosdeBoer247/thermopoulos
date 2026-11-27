"""[2026-11-19] ERA5 land-sea correction (era5_kustcorrectie.py).

No network: requests.get is replaced by a fake archive.
Checked:
  1. the frozen parameters are the ones of the run of 19-11-2026;
  2. the model gives the same correction as buurcel_toets.py ('volledig: land
     eerst gecorrigeerd') on a reference set of 5 stations x 3 hot days
     (testdata/era5_kustcorrectie_referentie.csv; inputs from the estimate
     cache, so this checks the formula, not the quality of the correction);
  3. no correction on days with a T_land maximum of 20 C or less, a gradual
     transition from 20 to 24 C without a jump at 24 C (2026-11-27), and no
     correction without a land cell (except on a narrow island);
  4. night rule: at the coast f_land is 0 at night, inland it is not;
  5. corrigeer_dataframe with a fake archive: land cells cached, hot-day hours
     corrected, forecast-API hours left alone, times in UTC;
  6. a failing archive gives no correction and no exception;
  7. Data Engine: process_weather_data applies it, keeps T_air_era5, keeps
     the dew point; the forecast (coastal_active False) is untouched.
"""
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ["ERA5_KUST_CACHE"] = tempfile.mkdtemp(prefix="era5kust_")
import era5_kustcorrectie as K

fails = []


def check(naam, ok, info=""):
    print(("  ok    " if ok else "  FOUT  ") + naam + (f"  ({info})" if info else ""))
    if not ok:
        fails.append(naam)


# 1. parameters ---------------------------------------------------------------
P = K.PARAMS
check("wmax 0.8954", abs(P["w"]["wmax"] - 0.8954052) < 1e-6, P["w"]["wmax"])
check("L 4.213 km", abs(P["w"]["L_km"] - 4.2133385) < 1e-6, P["w"]["L_km"])
check("c 0.6785", abs(P["c_island_per_100Wm2"] - 0.6785156) < 1e-6)
check("f_land: 24 hours x 10", len(P["_mos"]) == 24 and all(len(c) == 10 for c in P["_mos"].values()))
check("f_land hour 0 intercept", abs(P["_mos"][0][0] - (-2.749404)) < 1e-5, P["_mos"][0][0])

# 2. reference set ------------------------------------------------------------
R = pd.read_csv(HERE / "testdata" / "era5_kustcorrectie_referentie.csv", parse_dates=["tijd_utc"],
                index_col="tijd_utc")
globe_ok = K._globe() is not None
check("global-land-mask installed", globe_ok)
maxd = 0.0
if globe_ok:
    for st, d in R.groupby("STN"):
        lat, lon = float(d.LAT.iloc[0]), float(d.LON.iloc[0])
        ei = K.eiland_info(lat, lon)
        res = K.correctie(d.era, d.land if bool(d.heeft_land.iloc[0]) else None, d.ghi,
                          d.bew.fillna(d.bew_vul.iloc[0]), d.wind.fillna(d.wind_vul.iloc[0]), d.dd,
                          K.land_tabel(lat, lon), bool(d.kust.iloc[0]), ei)
        ref = d.ref_correctie.to_numpy()
        ok = np.isfinite(ref)
        maxd = max(maxd, float(np.max(np.abs(res.correctie.to_numpy()[ok] - ref[ok]))))
        check(f"station {st}: same hot hours as the script",
              int((res.reden == "applied").sum()) == int(ok.sum()))
check("same correction as buurcel_toets.py", maxd < 1e-6, f"max difference {maxd:.1e} C")

# 3./4. synthetic day ---------------------------------------------------------
idx = pd.date_range("2022-07-19", periods=48, freq="h")
uur = idx.hour.to_numpy()
zon = np.clip(800 * np.sin((uur - 4) / 16 * np.pi), 0, None)
T_land = pd.Series(np.r_[18 + 8 * np.sin((uur[:24] - 8) / 24 * 2 * np.pi),
                         14 + 6 * np.sin((uur[24:] - 8) / 24 * 2 * np.pi)], index=idx)
T_cel = T_land - 2.0
een = pd.Series(1.0, index=idx)
tab = np.full(360, 40.0)                 # land air from every direction
geen_eiland = dict(eiland=False, landdeel_cel=1.0)
r_land = K.correctie(T_cel, T_land, pd.Series(zon, index=idx), 20 * een, 3 * een, 90 * een,
                     tab, False, geen_eiland)
r_kust = K.correctie(T_cel, T_land, pd.Series(zon, index=idx), 20 * een, 3 * een, 90 * een,
                     tab, True, geen_eiland)
dag1, dag2 = idx.day == 19, idx.day == 20
check("day 1 hot (max T_land 26 C) is corrected", (r_land.reden[dag1] == "applied").all())
check("day 2 max 20 C: no correction",
      (r_land.correctie[dag2] == 0).all() and (r_land.reden[dag2] == "not a hot day").all())
nacht = dag1 & (zon <= 10)
check("night rule: coast f_land = 0 at night", (r_kust.f_land[nacht] == 0).all())
check("night rule: inland f_land not 0 at night", (r_land.f_land[nacht] != 0).all())
check("by day coast and inland equal",
      np.allclose(r_kust.correctie[dag1 & (zon > 10)], r_land.correctie[dag1 & (zon > 10)]))
check("w(40 km) = wmax(1-exp(-40/L))",
      abs(r_land.w.iloc[12] - P["w"]["wmax"] * (1 - np.exp(-40 / P["w"]["L_km"]))) < 1e-12)
# [2026-11-27] gradual transition 20-24 C instead of a hard switch at 24 C
check("day weight 0 / 0.5 / 1 at 20 / 22 / 24 C",
      np.allclose(K.ramp_gewicht(pd.Series([19.0, 20.0, 22.0, 24.0, 30.0])).to_numpy(), [0, 0, 0.5, 1, 1]))
def _dag(tmax):
    i = pd.date_range("2022-07-19", periods=24, freq="h")
    u = i.hour.to_numpy()
    tl = pd.Series(tmax - 6 + 6 * np.sin((u - 8) / 24 * 2 * np.pi), index=i)
    tl = tl - tl.max() + tmax
    z = pd.Series(np.clip(800 * np.sin((u - 4) / 16 * np.pi), 0, None), index=i)
    e = pd.Series(1.0, index=i)
    return K.correctie(tl - 2.0, tl, z, 20 * e, 3 * e, 90 * e, tab, False, geen_eiland)
c_net_onder = _dag(23.999).correctie.to_numpy()
c_op = _dag(24.0).correctie.to_numpy()
check("no jump at 24 C (23.999 vs 24.0)", np.max(np.abs(c_net_onder - c_op)) < 0.01,
      f"max {np.max(np.abs(c_net_onder - c_op)):.4f} C")
c22 = _dag(22.0)
check("22 C: day weight 0.5 and correction applied",
      np.allclose(c22.dag_gewicht, 0.5) and (c22.reden == "applied").all())
check("20 C: no correction", (_dag(20.0).correctie == 0).all())
r_geen = K.correctie(T_cel, None, pd.Series(zon, index=idx), 20 * een, 3 * een, 90 * een,
                     tab, True, geen_eiland)
check("no land cell, no island: no correction", (r_geen.correctie == 0).all())
r_eil = K.correctie(T_land, None, pd.Series(zon, index=idx), 20 * een, 3 * een, 90 * een,
                    np.zeros(360), True, dict(eiland=True, landdeel_cel=0.3))
mid = dag1 & (uur == 12)
check("island without land cell: island term (+ day f_land)",
      np.allclose(r_eil.G[mid], zon[mid] / 100 * 0.7) and (r_eil.correctie[mid] != 0).all())

# 5./6. corrigeer_dataframe with a fake archive -------------------------------
import requests

AANVRAGEN = []


class _Resp:
    def __init__(self, j, status=200):
        self._j, self.status_code, self.text = j, status, ""

    def json(self):
        return self._j


ARCHIEF_FAALT = False


def nep_get(url, params=None, timeout=None, **kw):
    AANVRAGEN.append(dict(params))
    if ARCHIEF_FAALT:
        return _Resp({"error": True}, status=500)
    t = pd.date_range(params["start_date"], pd.Timestamp(params["end_date"]) + pd.Timedelta(hours=23), freq="h")
    lats = [float(x) for x in str(params["latitude"]).split(",")]
    lons = [float(x) for x in str(params["longitude"]).split(",")]
    u = t.hour.to_numpy()
    uit = []
    for la, lo in zip(lats, lons):
        if params["hourly"] == "wind_direction_10m":
            v = [90.0] * len(t)
        else:
            # land (east of 5 E) has a large diurnal cycle, the rest a small one
            amp = 8.0 if lo >= 5.0 else 2.0
            v = list(20 + amp * np.sin((u - 8) / 24 * 2 * np.pi) + (4 if t.month[0] == 7 else 0))
        uit.append({"latitude": la, "longitude": lo, "elevation": 0.0,
                    "hourly": {"time": [x.strftime("%Y-%m-%dT%H:%M") for x in t],
                               params["hourly"]: v}})
    return _Resp(uit if len(uit) > 1 else uit[0])


echte_get, K.PAUSE_S = requests.get, 0.0
requests.get = nep_get
try:
    tz = "Europe/Amsterdam"
    lok = pd.date_range("2022-07-19 00:00", periods=48, freq="h", tz=tz)
    df = pd.DataFrame({"T_air_rural": 24.0, "RH": 50.0, "solar_radiation": 500.0,
                       "cloud_cover": 10.0, "wind_10m": 3.0, "pressure": 1013.0}, index=lok)
    df["from_forecast_api"] = False
    df.iloc[-3:, df.columns.get_loc("from_forecast_api")] = True
    lat, lon = 52.10, 5.18                     # De Bilt
    corr, info = K.corrigeer_dataframe(df, lat, lon, overslaan=df.from_forecast_api)
    check("applied on the hot day", info["toegepast"], info["melding"])
    check("land cells found", info.get("n_landcellen", 0) > 0, info.get("n_landcellen"))
    check("cache file written", any(Path(os.environ["ERA5_KUST_CACHE"]).glob("landcellen_*.json")))
    n_ref = sum(1 for a in AANVRAGEN if a["start_date"].endswith("-05-01"))
    check("reference summers fetched once (5 years)", n_ref == 5, n_ref)
    check("all requests in GMT", all(a["timezone"] == "GMT" for a in AANVRAGEN))
    check("forecast-API hours not corrected", (corr[df.from_forecast_api] == 0).all()
          and (info["reden"][df.from_forecast_api] == "forecast-API hour").all())
    AANVRAGEN.clear()
    corr2, info2 = K.corrigeer_dataframe(df, lat, lon)
    check("second run: reference from cache", not any(a["start_date"].endswith("-05-01") for a in AANVRAGEN))
    check("second run: same result", np.allclose(corr2[~df.from_forecast_api], corr[~df.from_forecast_api]))

    ARCHIEF_FAALT = True
    corr3, info3 = K.corrigeer_dataframe(df, 51.44, 3.60)   # Vlissingen, not in the cache
    check("failing archive: no correction, no exception",
          (corr3 == 0).all() and not info3["toegepast"] and "not applied" in info3["melding"],
          info3["melding"][:80])
    ARCHIEF_FAALT = False

    # 7. Data Engine
    import Thermopoulos_Data_Engine as DE
    proc = DE.process_weather_data(df.copy(), {"population": 0}, lat, lon, tz, True, 0.03)
    check("Data Engine: T_air_era5 kept", np.allclose(proc.T_air_era5, df.T_air_rural))
    check("Data Engine: correction added",
          np.allclose(proc.T_air_rural - proc.T_air_era5, proc.coastal_correction_degrees))
    check("Data Engine: some hours applied", bool(proc.coastal_correction_applied.any()))
    dp0 = DE.dew_point_from_rh(df.T_air_rural.values, df.RH.values)
    dp1 = DE.dew_point_from_rh(proc.T_air_rural.values, proc.RH.values)
    check("Data Engine: dew point unchanged", np.allclose(dp0, dp1, atol=1e-6))
    procf = DE.process_weather_data(df.copy(), {"population": 0}, lat, lon, tz, False, 0.03)
    check("Data Engine: forecast untouched", (procf.coastal_correction_degrees == 0).all()
          and (procf.coastal_correction_reason == "not ERA5").all())
finally:
    requests.get = echte_get

print()
if fails:
    print(f"FOUT: {len(fails)} controle(s) mislukt: {fails}")
    sys.exit(1)
print("Alle controles geslaagd.")
