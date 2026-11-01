# -*- coding: utf-8 -*-
"""
fit_lezer.py -- FIT-bestanden (Garmin + CORE-sensor) lezen, anonimiseren
en exporteren naar Excel/CSV voor vergelijking met HESTIA.

Wat het doet
------------
1. Leest een .fit-bestand met de bibliotheek `fitdecode`.
2. Neemt ALLEEN velden over die op de toegestane lijst staan (TOEGESTAAN).
   Alles wat niet op die lijst staat -- GPS-route, serienummers, het
   Garmin-gebruikersprofiel, hartslagvariabiliteit, onbekende velden, en
   velden die een toekomstige app-versie toevoegt -- valt automatisch weg.
3. Vervangt de absolute klok door seconden vanaf de start. Alleen de datum
   en het startuur (afgerond op 10 min, lokale tijd) blijven bewaard, voor
   het weer uit de Data Engine.
4. Zoekt de stukken waarin echt gelopen is (inspanningsdelen).
5. Schrijft per bestand:
     <code>_<datum>.xlsx   bladen Meta, Per_minuut, Per_seconde,
                           Inspanning, Controleverslag
     <code>_<datum>.csv    de per-seconde-data
     <code>_<datum>.png    controlefiguur (hartslag, temperaturen, tempo)
   De uitvoernamen gebruiken de code die de gebruiker opgeeft, NOOIT de
   oorspronkelijke bestandsnaam (die bevat bij Garmin-exports vaak een
   e-mailadres).

Het Controleverslag noemt per berichttype welke velden zijn overgenomen en
welke zijn weggelaten (alleen namen, geen waarden), zodat de clinic-organisatie/Radboudumc
voor het doorsturen kunnen controleren wat erin zit.

Gebruik
-------
    python fit_lezer.py                 # menu: kies .fit-bestanden in de map
    python fit_lezer.py a.fit b.fit     # zelfde, voor deze bestanden

    from fit_lezer import lees_fit, exporteer
    rit = lees_fit("x.fit", code="L01")
    exporteer(rit, "fit_uitvoer")

Getest op Garmin-bestanden met de CORE Connect IQ-app (2026-09-18).

CORE-velden: core_temperature en skin_temperature (deg C),
core_data_quality en heat_strain_index (CORE's eigen index, niet die van
HESTIA).

core_data_quality [uitgezocht 2026-10-09]:
  - laagste bits = kwaliteitsniveau volgens de CORE BLE Service
    Specification (v2.2, tabel 4): 0 ongeldig, 1 slecht, 2 redelijk,
    3 goed, 4 uitstekend, 7 niet beschikbaar.
  - +16 = de CORE gebruikt een hartslagsignaal (sportalgoritme), volgens
    CORE's Developer Information voor FIT-bestanden. Zonder hartslag valt de
    CORE terug op het algoritme voor dagelijks leven; volgens de
    specificatie is de schatting tijdens zware inspanning dan veel minder
    goed.
  - Kanttekening: in de BLE-specificatie zelf betekent bit 4 'hartslag
    ondersteund, geen signaal' en bit 5 'signaal ontvangen'; de FIT-
    conventie van de Connect IQ-app (+16 = hartslag in gebruik) wijkt
    daarvan af. Wij volgen de FIT-documentatie; ter controle navragen.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import fitdecode
except ImportError:            # pragma: no cover
    fitdecode = None

# -----------------------------------------------------------------------------
# Toegestane velden: bericht 'record' -> naam in de uitvoer
# -----------------------------------------------------------------------------
TOEGESTAAN = {
    "heart_rate":        "hartslag",          # slagen/min
    "enhanced_speed":    "snelheid_ms",       # m/s (voorkeur)
    "speed":             "_snelheid_oud",     # m/s (als enhanced ontbreekt)
    "distance":          "afstand_m",         # m vanaf de start
    "enhanced_altitude": "hoogte_m",          # m (voorkeur)
    "altitude":          "_hoogte_oud",
    "cadence":           "cadans",            # stappen/min per been (Garmin)
    "core_temperature":  "kern_temp",         # deg C (CORE-sensor, schatting)
    "skin_temperature":  "huid_temp",         # deg C (CORE-sensor)
    "core_data_quality": "core_kwaliteit",    # CORE-kwaliteitsindicator
    "heat_strain_index": "core_hsi",          # CORE's eigen hittebelastingsindex
}
#: Uit 'session' alleen deze samenvattende, niet-herleidbare velden
SESSIE_TOEGESTAAN = {"sport", "sub_sport", "total_timer_time", "total_distance"}

#: Drempel voor 'lopen' (m/s, voortschrijdend gemiddelde over 60 s).
#: 1,8 m/s = 9:16 min/km: wandelen blijft eronder, rustig joggen erboven.
KWALITEIT_LABEL = {0: "ongeldig", 1: "slecht", 2: "redelijk", 3: "goed", 4: "uitstekend",
                   7: "niet beschikbaar"}

LOOP_DREMPEL_MS = 1.8
MIN_DEEL_S = 120          # kortere stukken tellen niet als inspanningsdeel


@dataclass
class FitRit:
    code: str
    data: pd.DataFrame                    # per seconde, alleen toegestane kolommen
    meta: dict
    verslag: pd.DataFrame                 # overgenomen/weggelaten per bericht
    delen: pd.DataFrame                   # inspanningsdelen
    per_minuut: pd.DataFrame = field(default_factory=pd.DataFrame)


def _lokale_offset(activity: dict) -> pd.Timedelta:
    """Verschil lokale tijd - UTC uit het activity-bericht (Garmin slaat
    beide op). Geeft 0 als het ontbreekt."""
    try:
        lt, ts = activity.get("local_timestamp"), activity.get("timestamp")
        if lt is None or ts is None:
            return pd.Timedelta(0)
        lt = pd.Timestamp(lt).tz_localize(None) if getattr(lt, "tzinfo", None) else pd.Timestamp(lt)
        ts = pd.Timestamp(ts).tz_convert(None) if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts)
        return (lt - ts).round("15min")
    except Exception:
        return pd.Timedelta(0)


def _inspanningsdelen(df: pd.DataFrame) -> pd.DataFrame:
    if "snelheid_ms" not in df or df["snelheid_ms"].isna().all():
        return pd.DataFrame(columns=["deel", "start_s", "eind_s", "duur_min", "afstand_km",
                                     "tempo_min_km", "hartslag_gem", "kern_start", "kern_max"])
    s = df.set_index("t_s")["snelheid_ms"]
    # op een regelmatig 1-s raster voor het voortschrijdend gemiddelde
    raster = s.reindex(np.arange(0, int(s.index.max()) + 1)).interpolate(limit=10)
    loopt = raster.rolling(60, center=True, min_periods=30).mean() > LOOP_DREMPEL_MS
    rijen, start = [], None
    for t, l in zip(loopt.index, loopt.values):
        if l and start is None:
            start = t
        elif not l and start is not None:
            if t - start >= MIN_DEEL_S:
                rijen.append((start, t))
            start = None
    if start is not None and loopt.index[-1] - start >= MIN_DEEL_S:
        rijen.append((start, loopt.index[-1]))
    uit = []
    for i, (a, b) in enumerate(rijen, 1):
        sel = df[(df.t_s >= a) & (df.t_s <= b)]
        afst = (sel.afstand_m.max() - sel.afstand_m.min()) / 1000 if "afstand_m" in sel else np.nan
        duur = (b - a) / 60
        uit.append({
            "deel": i, "start_s": int(a), "eind_s": int(b), "duur_min": round(duur, 1),
            "afstand_km": round(afst, 2),
            "tempo_min_km": round(duur / afst, 2) if afst and afst > 0 else np.nan,
            "hartslag_gem": round(sel.hartslag.mean(), 0) if "hartslag" in sel else np.nan,
            "kern_start": round(sel.kern_temp.dropna().iloc[0], 2) if "kern_temp" in sel and sel.kern_temp.notna().any() else np.nan,
            "kern_max": round(sel.kern_temp.max(), 2) if "kern_temp" in sel else np.nan,
            "core_hartslag_gebruikt_pct": (round(100 * sel.core_hartslag_gebruikt.mean(), 0)
                                           if "core_hartslag_gebruikt" in sel else np.nan),
            "core_goed_of_beter_pct": (round(100 * (sel.core_niveau >= 3).mean(), 0)
                                       if "core_niveau" in sel else np.nan),
        })
    return pd.DataFrame(uit)


def lees_fit(pad: str | Path, code: str) -> FitRit:
    if fitdecode is None:
        raise ImportError("Installeer eerst fitdecode:  pip install fitdecode")
    pad = Path(pad)
    rijen = []
    gezien = defaultdict(set)            # bericht -> veldnamen
    activity, sessie = {}, {}
    dev_apps = 0
    vo2_garmin = None
    with fitdecode.FitReader(str(pad)) as fr:
        for f in fr:
            if not isinstance(f, fitdecode.FitDataMessage):
                continue
            for fd in f.fields:
                gezien[f.name].add(fd.name)
            if f.name == "record":
                d = {}
                for fd in f.fields:
                    if fd.name == "timestamp":
                        d["timestamp"] = fd.value
                    elif fd.name in TOEGESTAAN and fd.value is not None:
                        d[TOEGESTAAN[fd.name]] = fd.value
                rijen.append(d)
            elif f.name == "activity":
                activity = {fd.name: fd.value for fd in f.fields}
            elif f.name == "session":
                sessie = {fd.name: fd.value for fd in f.fields if fd.name in SESSIE_TOEGESTAAN}
            elif f.name == "developer_data_id":
                dev_apps += 1
            elif f.name == "unknown_140":
                # [2026-10-09] Garmin's VO2max-schatting na de activiteit:
                # bericht 140, veld 7 = METmax x 65536 (niet officieel
                # gedocumenteerd; GoldenCheetah, Intervals.icu). VO2max =
                # waarde x 3,5 / 65536. Hoort bij het PROFIEL op het horloge.
                for fd in f.fields:
                    if fd.name == "unknown_7" and isinstance(fd.value, (int, float)) and fd.value > 0:
                        vo2_garmin = round(fd.value * 3.5 / 65536, 1)

    if not rijen:
        raise ValueError(f"Geen meetwaarden (record-berichten) in {pad.name}")
    df = pd.DataFrame(rijen)
    ts = pd.to_datetime(df.pop("timestamp"), utc=True)
    t0 = ts.min()
    df.insert(0, "t_s", (ts - t0).dt.total_seconds().astype(float))
    # voorkeursvelden samenvoegen
    if "snelheid_ms" not in df and "_snelheid_oud" in df:
        df["snelheid_ms"] = df["_snelheid_oud"]
    if "hoogte_m" not in df and "_hoogte_oud" in df:
        df["hoogte_m"] = df["_hoogte_oud"]
    if "hoogte_m" in df and "_hoogte_oud" in df:
        df["hoogte_m"] = df["hoogte_m"].fillna(df["_hoogte_oud"])
    df = df.drop(columns=[c for c in df.columns if c.startswith("_")])
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # CORE-kwaliteit ontleden: niveau (0-4) en vlag 'hartslag gebruikt' (+16)
    if "core_kwaliteit" in df:
        q = df["core_kwaliteit"]
        df["core_niveau"] = (q % 16).where(q.notna())
        df["core_hartslag_gebruikt"] = (q >= 16).where(q.notna())
    # hoogte relatief maken (absolute hoogte + parcours kan een locatie verraden)
    if "hoogte_m" in df and df["hoogte_m"].notna().any():
        df["hoogte_m"] = df["hoogte_m"] - df["hoogte_m"].dropna().iloc[0]
        df = df.rename(columns={"hoogte_m": "hoogteverschil_m"})
    df["t_min"] = df["t_s"] / 60.0
    df = df.sort_values("t_s").reset_index(drop=True)

    offset = _lokale_offset(activity)
    start_lokaal = (t0.tz_convert(None) + offset).floor("10min")
    stappen = df.t_s.diff().dropna()

    # Controleverslag
    rijen_v = []
    for bericht in sorted(gezien):
        velden = sorted(gezien[bericht])
        if bericht == "record":
            over = sorted(v for v in velden if v in TOEGESTAAN or v == "timestamp")
        elif bericht == "session":
            over = sorted(v for v in velden if v in SESSIE_TOEGESTAAN)
        elif bericht == "unknown_140":
            over = ["unknown_7 (VO2max-schatting)"] if "unknown_7" in velden else []
        else:
            over = []
        weg = sorted(set(velden) - {o.split(" ")[0] for o in over})
        rijen_v.append({"bericht": bericht,
                        "overgenomen": ", ".join(over) if over else "-",
                        "weggelaten": ", ".join(weg) if weg else "-",
                        "aantal_weggelaten": len(weg)})
    verslag = pd.DataFrame(rijen_v)

    delen = _inspanningsdelen(df)

    def _stat(col):
        return (round(float(df[col].min()), 2), round(float(df[col].median()), 2),
                round(float(df[col].max()), 2)) if col in df and df[col].notna().any() else None

    meta = {
        "code": code,
        "datum": start_lokaal.strftime("%Y-%m-%d"),
        "starttijd_lokaal_afgerond": start_lokaal.strftime("%H:%M"),
        "utc_offset_uur": round(offset.total_seconds() / 3600, 2),
        "duur_min": round(df.t_s.max() / 60, 1),
        "afstand_km": round(float(df.afstand_m.max()) / 1000, 2) if "afstand_m" in df else None,
        "sport": str(sessie.get("sport", "")),
        "aantal_metingen": int(len(df)),
        "meetinterval_mediaan_s": float(stappen.median()) if len(stappen) else None,
        "gaten_langer_dan_5s": int((stappen > 5).sum()),
        "langste_gat_s": float(stappen.max()) if len(stappen) else None,
        "core_sensor_aanwezig": bool("kern_temp" in df and df.kern_temp.notna().any()),
        "kern_temp_min_med_max": _stat("kern_temp"),
        "huid_temp_min_med_max": _stat("huid_temp"),
        "hartslag_min_med_max": _stat("hartslag"),
        "aantal_inspanningsdelen": int(len(delen)),
        "connect_iq_apps": dev_apps,
        "vo2max_garmin_schatting": vo2_garmin,
        "vo2max_garmin_let_op": ("schatting van het horloge na deze activiteit; hoort bij het profiel "
                                 "op het horloge, niet per se bij deze loper") if vo2_garmin else None,
    }
    if "core_niveau" in df and df.core_niveau.notna().any():
        meta["core_hartslag_gebruikt_pct"] = round(100 * float(df.core_hartslag_gebruikt.mean()), 1)
        verd = df.core_niveau.map(KWALITEIT_LABEL).value_counts(normalize=True) * 100
        meta["core_kwaliteit_verdeling_pct"] = {k: round(v, 1) for k, v in verd.items()}
        waarsch = []
        if meta["core_hartslag_gebruikt_pct"] < 50:
            waarsch.append("CORE gebruikte meestal GEEN hartslag (niet gekoppeld?): "
                           "kerntemperatuur tijdens inspanning minder betrouwbaar")
        if (df.core_niveau <= 1).mean() > 0.10:
            waarsch.append("meer dan 10% van de tijd kwaliteit 'slecht' of 'ongeldig'")
        meta["core_waarschuwing"] = "; ".join(waarsch) if waarsch else "geen"

    # per minuut
    pm = df.assign(minuut=(df.t_s // 60).astype(int)).groupby("minuut").agg(
        {c: "mean" for c in df.columns if c not in ("t_s", "t_min")})
    if "snelheid_ms" in pm:
        pm["tempo_min_km"] = np.where(pm.snelheid_ms > 0.5, 1000 / 60 / pm.snelheid_ms, np.nan)
    pm = pm.reset_index().round(3)

    return FitRit(code=code, data=df, meta=meta, verslag=verslag, delen=delen, per_minuut=pm)


def plot_rit(rit: FitRit, pad: str | Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 14, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": "#e4e3df"})
    pm = rit.per_minuut
    panelen = [("hartslag", "Hartslag (/min)", "#2a78d6"),
               ("kern_temp", "Kerntemperatuur CORE (C)", "#d03b3b"),
               ("huid_temp", "Huidtemperatuur CORE (C)", "#eb6834"),
               ("tempo_min_km", "Tempo (min/km)", "#1baf7a"),
               ("core_niveau", "CORE-kwaliteit (0-4)", "#4a3aa7")]
    panelen = [p for p in panelen if p[0] in pm and pm[p[0]].notna().any()]
    fig, axs = plt.subplots(len(panelen), 1, figsize=(11, 2.6 * len(panelen)), sharex=True)
    axs = np.atleast_1d(axs)
    for ax, (kol, lab, kl) in zip(axs, panelen):
        ax.plot(pm.minuut, pm[kol], color=kl, lw=1.8)
        ax.set_ylabel(lab, fontsize=12)
        for _, d in rit.delen.iterrows():
            ax.axvspan(d.start_s / 60, d.eind_s / 60, color="#888780", alpha=0.10, lw=0)
        if kol == "core_niveau":
            ax.set_ylim(-0.3, 4.3)
            ax.set_yticks([0, 1, 2, 3, 4])
            ax.set_yticklabels(["ongeldig", "slecht", "redelijk", "goed", "uitst."], fontsize=10)
            if "core_hartslag_gebruikt" in pm:
                zonder = pm.core_hartslag_gebruikt < 0.5
                ax.fill_between(pm.minuut, -0.3, 4.3, where=zonder, color="#d03b3b", alpha=0.10,
                                lw=0, step="mid", label="CORE zonder hartslag")
                if zonder.any():
                    ax.legend(loc="lower left", fontsize=10, frameon=False)
        if kol == "tempo_min_km":
            ax.set_ylim(min(12, np.nanmax(pm[kol]) if pm[kol].notna().any() else 12), 3)
    axs[-1].set_xlabel("Minuten vanaf de start (grijs = inspanningsdeel)")
    fig.suptitle(f"{rit.code} - {rit.meta['datum']} start ~{rit.meta['starttijd_lokaal_afgerond']}", fontsize=16)
    fig.tight_layout()
    fig.savefig(pad, dpi=130)
    plt.close(fig)
    return Path(pad)


def exporteer(rit: FitRit, map_: str | Path = "fit_uitvoer") -> dict:
    map_ = Path(map_)
    map_.mkdir(parents=True, exist_ok=True)
    stam = f"{rit.code}_{rit.meta['datum']}"
    xlsx = map_ / f"{stam}.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        pd.DataFrame(list(rit.meta.items()), columns=["gegeven", "waarde"]).astype(str) \
            .to_excel(xw, sheet_name="Meta", index=False)
        rit.per_minuut.to_excel(xw, sheet_name="Per_minuut", index=False)
        rit.data.round(3).to_excel(xw, sheet_name="Per_seconde", index=False)
        rit.delen.to_excel(xw, sheet_name="Inspanning", index=False)
        rit.verslag.to_excel(xw, sheet_name="Controleverslag", index=False)
    csv = map_ / f"{stam}.csv"
    rit.data.round(3).to_csv(csv, index=False, sep=";", decimal=",")
    png = plot_rit(rit, map_ / f"{stam}.png")
    return {"xlsx": xlsx, "csv": csv, "png": png}


# -----------------------------------------------------------------------------
# Menu
# -----------------------------------------------------------------------------
def _kies_bestanden() -> list[Path]:
    kand = sorted({p.resolve() for m in (Path.cwd(), Path.cwd() / "fit_invoer")
                   if m.is_dir() for p in m.glob("*.fit")})
    if not kand:
        print("Geen .fit-bestanden gevonden in deze map of in de submap fit_invoer.")
        return []
    print("\nGevonden FIT-bestanden:")
    for i, p in enumerate(kand, 1):
        print(f"  {i:>2}. {p.name}")
    k = input("Welke verwerken? (bijv. 1,3 of A voor alle, Q = stoppen): ").strip().lower()
    if k in ("q", ""):
        return []
    if k == "a":
        return kand
    keuze = []
    for deel in k.split(","):
        if deel.strip().isdigit() and 1 <= int(deel) <= len(kand):
            keuze.append(kand[int(deel) - 1])
    return keuze


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    bestanden = [Path(a) for a in argv] if argv else _kies_bestanden()
    if not bestanden:
        return 0
    print("\nGeef elke loper een code (geen naam). Leeg = voorgestelde code.")
    for i, p in enumerate(bestanden, 1):
        voorstel = f"L{i:02d}"
        code = input(f"Code voor bestand {i} van {len(bestanden)} [{voorstel}]: ").strip() or voorstel
        code = "".join(c for c in code if c.isalnum() or c in "-_") or voorstel
        try:
            rit = lees_fit(p, code)
        except Exception as e:
            print(f"  ! {code}: kan niet lezen ({e})")
            continue
        uit = exporteer(rit)
        m = rit.meta
        print(f"  {code}: {m['datum']} ~{m['starttijd_lokaal_afgerond']}, {m['duur_min']} min, "
              f"{m['afstand_km']} km, {m['aantal_inspanningsdelen']} inspanningsdeel/delen, "
              f"CORE: {'ja' if m['core_sensor_aanwezig'] else 'nee'}")
        if m.get("core_waarschuwing", "geen") != "geen":
            print(f"     ! CORE: {m['core_waarschuwing']}")
        print(f"     -> {uit['xlsx'].resolve()}")
    print("\nControleer het blad 'Controleverslag' voordat je iets doorstuurt.")
    return 0


if __name__ == "__main__":
    _rc = main()
    if _rc and not (hasattr(sys, "ps1") or "IPython" in sys.modules):
        sys.exit(_rc)
