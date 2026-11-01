# -*- coding: utf-8 -*-
"""
hestia_loper_plots.py -- alle figuren voor het persoonlijke rapport.

Elke functie krijgt een LoperResultaat (hestia_loper.py) en schrijft een PNG.
Groot lettertype (basis 15 pt) voor leesbaarheid. Banden zijn 95%-banden van
het eigen ensemble: elke run is dezelfde loper met andere aannames over
onbekende dag-factoren (pacingrespons, windrichting, zweetvariatie).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from hestia_loper import LoperResultaat, _dg_snelheid_uit_vo2, min_naar_tempo
import individual_engine as ie

# Kleuren (dataviz-referentiepalet; status alleen voor drempels)
BLAUW, ORANJE, AQUA, PAARS = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"
INKT, INKT2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
GEEL_S, ORANJE_S, ROOD_S, GROEN_S = "#fab219", "#ec835a", "#d03b3b", "#0ca30c"

plt.rcParams.update({
    "font.size": 15, "axes.titlesize": 17, "axes.labelsize": 15,
    "xtick.labelsize": 13, "ytick.labelsize": 13, "legend.fontsize": 13,
    "axes.edgecolor": INKT2, "axes.labelcolor": INKT, "text.color": INKT,
    "xtick.color": INKT2, "ytick.color": INKT2, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False,
    "axes.spines.right": False, "lines.linewidth": 2.0,
    "axes.formatter.use_locale": False,
})


def _komma(ax):
    from matplotlib.ticker import FuncFormatter
    def f(x, _):
        s = f"{x:g}"
        return s.replace(".", ",")
    ax.yaxis.set_major_formatter(FuncFormatter(f))


def _drempel(ax, y, tekst, kleur, x_tekst=None, va="bottom"):
    ax.axhline(y, color=kleur, lw=1.6, ls="--", zorder=1)
    xl = ax.get_xlim()
    ax.text(x_tekst if x_tekst is not None else xl[0] + 0.01 * (xl[1] - xl[0]), y, " " + tekst,
            color=INKT2, fontsize=12, va=va, ha="left")


def _finishlijn(ax, x):
    ax.axvline(x, color=INKT2, lw=1.2, ls=":")
    ax.text(x, ax.get_ylim()[1], " finish", color=INKT2, fontsize=12, va="top")


def _opslaan(fig, pad):
    fig.tight_layout()
    fig.savefig(pad, dpi=150)
    plt.close(fig)
    return Path(pad)


# -----------------------------------------------------------------------------
# [2026-10-31] Uitgebreide weer- en loopgrafieken (verzoek van de auteur)
# -----------------------------------------------------------------------------
def _tijdas(ax):
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))


def _weer_panelen(fig, axs, tijd, d, venster=None):
    """Drie panelen: temperaturen, vocht en wind, zon en bewolking."""
    tijd = [t.tz_localize(None) if getattr(t, "tzinfo", None) else t for t in tijd]
    def g(*keys):
        for k in keys:
            if k in d and d[k] is not None and np.isfinite(np.asarray(d[k], float)).any():
                return np.asarray(d[k], float)
        return None
    ax = axs[0]
    for keys, lab, kl, ls in ((("t_air", "T_air_urban"), "Luchttemperatuur", BLAUW, "-"),
                              (("t_wet", "T_wetbulb"), "Natteboltemperatuur", AQUA, "-"),
                              (("wbgt", "WBGT"), "WBGT", ORANJE, "-"),
                              (("utci", "UTCI"), "UTCI (gevoelstemperatuur)", ROOD_S, "--"),
                              (("mrt", "MRT"), "Stralingstemperatuur (MRT)", PAARS, ":"),
                              (("t_globe", "T_globe"), "Bolthermometer", INKT2, "-.")):
        y = g(*keys)
        if y is not None:
            ax.plot(tijd, y, color=kl, ls=ls, lw=2, label=lab)
    ax.set_ylabel("°C")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=11)
    ax = axs[1]
    y = g("rh", "RH_urban", "RH")
    if y is not None:
        ax.plot(tijd, y, color=BLAUW, lw=2, label="Relatieve vochtigheid (%)")
    ax.set_ylabel("RV (%)")
    ax2 = ax.twinx()
    for keys, lab, kl, ls in ((("wind", "wind_1.5m"), "Wind op 1,5 m (m/s)", ORANJE, "-"),
                              (("wind10", "wind_10m"), "Wind op 10 m (m/s)", ORANJE, "--")):
        y = g(*keys)
        if y is not None:
            ax2.plot(tijd, y, color=kl, ls=ls, lw=2, label=lab)
    ax2.set_ylabel("Wind (m/s)")
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", bbox_to_anchor=(1.08, 1.0), frameon=False, fontsize=11)
    ax = axs[2]
    y = g("ghi", "solar_radiation")
    if y is not None:
        ax.fill_between(tijd, 0, y, color=GEEL_S, alpha=0.5, lw=0, label="Zonnestraling (W/m²)")
        ax.plot(tijd, y, color=ORANJE, lw=1.5)
    ax.set_ylabel("Zon (W/m²)")
    ax3 = ax.twinx()
    y = g("cloud", "cloud_cover")
    if y is not None:
        ax3.plot(tijd, y, color=INKT2, lw=2, ls="--", label="Bewolking (%)")
    ax3.set_ylabel("Bewolking (%)")
    ax3.set_ylim(0, 105)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax3.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", bbox_to_anchor=(1.08, 1.0), frameon=False, fontsize=11)
    for a_ in axs:
        _tijdas(a_)
        if venster:
            a_.axvspan(venster[0], venster[1], color=BLAUW, alpha=0.08, lw=0)
        _komma(a_)
    axs[-1].set_xlabel("Tijd (lokaal)")


def plot_weer(r: LoperResultaat, pad):
    m = r.assessment.meteo
    fig, axs = plt.subplots(3, 1, figsize=(12, 10.5), sharex=True)
    _weer_panelen(fig, axs, m["time"], m)
    t0 = m["time"][0]
    axs[0].set_title(f"Weer tijdens de loop - {r.assessment.city_name}, {t0:%d-%m-%Y} "
                     f"(stadsklimaat meegerekend)")
    fig.tight_layout()
    return _opslaan(fig, pad)


def plot_weer_dag(r: LoperResultaat, pad):
    m = r.assessment.meteo
    d = m.get("dag")
    if not d or len(d.get("time", [])) < 3:
        return None
    t0, t1 = m["time"][0], m["time"][-1]
    t0 = t0.tz_localize(None) if getattr(t0, "tzinfo", None) else t0
    t1 = t1.tz_localize(None) if getattr(t1, "tzinfo", None) else t1
    fig, axs = plt.subplots(3, 1, figsize=(12, 10.5), sharex=True)
    _weer_panelen(fig, axs, d["time"], d, venster=(t0, t1))
    axs[0].set_title(f"Het weer over de hele dag - {r.assessment.city_name}, {t0:%d-%m-%Y} "
                     f"(blauwe band = de loop)")
    fig.tight_layout()
    return _opslaan(fig, pad)


def _trace_band(r: LoperResultaat, key: str):
    """Mediaan en 95%-band over alle runs voor een veld uit de 10-minutenregels."""
    traces = r.assessment.all_traces
    n = max(len(t) for t in traces)
    m = np.full((len(traces), n), np.nan)
    for i, t in enumerate(traces):
        for j, rec in enumerate(t):
            v = rec.get(key)
            try:
                m[i, j] = float(v)
            except (TypeError, ValueError):
                pass
    if not np.isfinite(m).any():
        return None
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return {"min": np.arange(n) * 10.0, "med": np.nanmedian(m, 0),
                    "lo": np.nanpercentile(m, 2.5, 0), "hi": np.nanpercentile(m, 97.5, 0), "alle": m}


def plot_dashboard(r: LoperResultaat, pad):
    """Alles op een pagina: kern, hartslag, hartreserve, inspanning, tempo, vocht,
    inspanningsbeleving en netto vochtverlies, met de WBGT als achtergrond."""
    a, b = r.assessment, r.banden
    panelen = [
        ("Kerntemperatuur (°C)", "t_rect", None, ((39.5, ORANJE_S), (40.5, ROOD_S))),
        ("Hartslag (/min)", "hr", None, ((r.afgeleid.hr_max, ROOD_S),)),
        ("Hartreserve (L/min)", "co", None, ((2.0, ORANJE_S), (0.0, ROOD_S))),
        ("Inspanning (MET)", "met", None, ()),
        ("Tempo (min/km)", "tempo", None, ()),
        ("Vochtverlies (% lichaamsgewicht)", "dehyd", None, ((2.0, ORANJE_S), (3.0, ROOD_S))),
        ("Inspanningsbeleving (Borg 6-20)", None, "rpe_total", ((17, ORANJE_S), (19.5, ROOD_S))),
        ("Netto vochtverlies (L, zweten min drinken)", None, "water", ()),
    ]
    fig, axs = plt.subplots(4, 2, figsize=(14, 15), sharex=True)
    wbgt = np.asarray(a.meteo["wbgt"], float)
    x_w = np.arange(len(wbgt)) * 10.0
    for ax, (titel, bk, tk, drempels) in zip(axs.flat, panelen):
        if bk:
            band = b.get(bk)
            x, med, lo, hi = band["minuten"], band["med"], band["lo"], band["hi"]
        else:
            band = _trace_band(r, tk)
            if band is None:
                ax.set_visible(False)
                continue
            x, med, lo, hi = band["min"], band["med"], band["lo"], band["hi"]
            if tk == "water":
                med, lo, hi = med / 1000, lo / 1000, hi / 1000
        ax.fill_between(x, lo, hi, color=BLAUW, alpha=0.18, lw=0)
        ax.plot(x, med, color=BLAUW, lw=2)
        for y, k in drempels:
            ax.axhline(y, color=k, ls="--", lw=1.2)
        if bk == "tempo":
            from matplotlib.ticker import FuncFormatter
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: min_naar_tempo(v)))
            ax.invert_yaxis()
        axw = ax.twinx()
        axw.plot(x_w, wbgt, color=ORANJE, lw=1, alpha=0.6)
        if np.isfinite(wbgt).any():
            axw.set_ylim(np.floor(np.nanmin(wbgt)) - 4, np.ceil(np.nanmax(wbgt)) + 4)
        from matplotlib.ticker import MaxNLocator
        axw.yaxis.set_major_locator(MaxNLocator(4))
        axw.set_ylabel("WBGT (°C)", color=ORANJE, fontsize=10)
        axw.tick_params(axis="y", labelsize=9, colors=ORANJE)
        axw.grid(False)
        ax.set_title(titel, fontsize=13)
        _komma(ax)
    for ax in axs[-1]:
        ax.set_xlabel("Minuten na de start")
    fig.suptitle(f"Alle modelwaarden van deze loop (blauw: mediaan en 95% van {a.n_ensemble} runs; "
                 f"oranje: WBGT)", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    return _opslaan(fig, pad)


def plot_alle_runs(r: LoperResultaat, pad):
    """Elke afzonderlijke run: kerntemperatuur, hartreserve en afgelegde afstand."""
    sets = [("Kerntemperatuur (°C)", "t_rect"), ("Hartreserve (L/min)", "co_reserve"),
            ("Inspanning (MET)", "current_met"), ("Inspanningsbeleving (Borg)", "rpe_total")]
    fig, axs = plt.subplots(2, 2, figsize=(14, 9.5), sharex=True)
    for ax, (titel, key) in zip(axs.flat, sets):
        band = _trace_band(r, key)
        if band is None:
            ax.set_visible(False)
            continue
        for row in band["alle"]:
            ax.plot(band["min"], row, color=BLAUW, alpha=max(0.04, min(0.35, 8 / len(band["alle"]))), lw=0.8)
        ax.plot(band["min"], band["med"], color=INKT, lw=2.2, label="mediaan")
        ax.set_title(titel, fontsize=13)
        _komma(ax)
    for ax in axs[-1]:
        ax.set_xlabel("Minuten na de start")
    fig.suptitle(f"Alle {r.assessment.n_ensemble} afzonderlijke runs (dunne lijnen) en de mediaan", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return _opslaan(fig, pad)


def plot_uitkomsten(r: LoperResultaat, pad):
    """Verdeling van de uitkomsten over alle runs."""
    d = r.per_run
    sets = [("t_rect_max_race", "Hoogste kern tijdens de loop (°C)", ((39.5, ORANJE_S), (40.5, ROOD_S))),
            ("t_rect_max", "Hoogste kern incl. na de finish (°C)", ((39.5, ORANJE_S), (40.5, ROOD_S))),
            ("co_reserve_min", "Laagste hartreserve (L/min)", ((2.0, ORANJE_S), (0.0, ROOD_S))),
            ("hr_piek", "Hoogste hartslag (/min)", ((r.afgeleid.hr_max, ROOD_S),)),
            ("dehydratie_eind_pct", "Vochtverlies aan het eind (%)", ((2.0, ORANJE_S), (3.0, ROOD_S))),
            ("tempo_daling_pct", "Vertraging aan het eind (%)", ()),
            ("finish_min_geschat", "Finishtijd (min)", ()),
            ("p_collapse", "Kans op collaps (per 10.000)", ())]
    fig, axs = plt.subplots(2, 4, figsize=(16, 8))
    for ax, (col, titel, drempels) in zip(axs.flat, sets):
        if col not in d or not np.isfinite(d[col].astype(float)).any():
            ax.set_visible(False)
            continue
        v = d[col].astype(float) * (1e4 if col == "p_collapse" else 1)
        ax.hist(v.dropna(), bins=20, color=BLAUW, edgecolor="white", linewidth=1)
        for y, k in drempels:
            ax.axvline(y, color=k, ls="--", lw=1.3)
        ax.axvline(np.nanmedian(v), color=INKT, lw=2)
        ax.set_title(titel, fontsize=12)
        ax.grid(axis="x", visible=False)
        _komma(ax)
    fig.suptitle(f"Verdeling over {len(d)} runs (zwarte lijn = mediaan)", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return _opslaan(fig, pad)


def plot_samenhang(r: LoperResultaat, pad):
    """Hoogste kern tegen laagste hartreserve per run, gekleurd naar vertraging."""
    d = r.per_run
    fig, ax = plt.subplots(figsize=(10, 7))
    sc = ax.scatter(d["t_rect_max_race"], d["co_reserve_min"], c=d["tempo_daling_pct"], cmap="viridis",
                    s=45, edgecolor="white", linewidth=0.5)
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("Vertraging aan het eind (%)")
    ax.axvline(39.5, color=ORANJE_S, ls="--"); ax.axvline(40.5, color=ROOD_S, ls="--")
    ax.axhline(2.0, color=ORANJE_S, ls="--"); ax.axhline(0.0, color=ROOD_S, ls="--")
    ax.set_xlabel("Hoogste kerntemperatuur tijdens de loop (°C)")
    ax.set_ylabel("Laagste hartreserve (L/min)")
    ax.set_title("Elke run: hitte en hart samen (rechtsonder = beide in de gevarenzone)")
    _komma(ax)
    return _opslaan(fig, pad)


def plot_kerntemperatuur(r: LoperResultaat, pad):
    a = r.assessment
    x = np.array(a.minutes)
    fig, ax = plt.subplots(figsize=(10, 5.6))
    ax.fill_between(x, a.t_rect_lo, a.t_rect_hi, color=BLAUW, alpha=0.18, lw=0,
                    label="95% van de runs")
    ax.plot(x, a.t_rect_median, color=BLAUW, label="Mediaan")
    ax.set_xlim(0, x.max())
    ax.set_ylim(min(37.0, np.nanmin(a.t_rect_lo) - 0.2), max(41.0, np.nanmax(a.t_rect_hi) + 0.2))
    _drempel(ax, 39.5, "39,5 C: grens hitte-uitputting (EHE-criterium)", ORANJE_S)
    _drempel(ax, 40.5, "40,5 C: grens hitteberoerte (Roberts)", ROOD_S)
    _finishlijn(ax, a.median_stop_minute)
    ax.set_xlabel("Minuten na de start (na de finish: herstel)")
    ax.set_ylabel("Rectale temperatuur (C)")
    ax.set_title("Kerntemperatuur (model JOS-3)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, frameon=False)
    _komma(ax)
    return _opslaan(fig, pad)


def plot_hartreserve(r: LoperResultaat, pad):
    a = r.assessment
    x = np.array(a.minutes)
    lo, hi, med = np.array(a.co_reserve_lo), np.array(a.co_reserve_hi), np.array(a.co_reserve_median)
    fig, ax = plt.subplots(figsize=(10, 5.6))
    ymin = min(-1.0, np.nanmin(lo) - 0.5)
    ax.axhspan(ymin, 0, color=ROOD_S, alpha=0.06, lw=0)
    ax.fill_between(x, lo, hi, color=BLAUW, alpha=0.18, lw=0, label="95% van de runs")
    ax.plot(x, med, color=BLAUW, label="Mediaan")
    ax.set_xlim(0, x.max())
    ax.set_ylim(ymin, np.nanmax(hi) + 1)
    _drempel(ax, 2.0, "2 L/min: marge bijna op", ORANJE_S)
    _drempel(ax, 0.0, "0: vraag = maximale pompcapaciteit", ROOD_S)
    ax.text(x.max(), ymin, "onder nul: extrapolatie, niet gevalideerd ", ha="right", va="bottom",
            fontsize=12, color=INKT2)
    _finishlijn(ax, a.median_stop_minute)
    ax.set_xlabel("Minuten na de start (na de finish: herstel)")
    ax.set_ylabel("Hartminuutvolume-reserve (L/min)")
    ax.set_title("Hartreserve: wat het hart nog extra kan pompen (CVR, Lloyd 2022)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, frameon=False)
    _komma(ax)
    return _opslaan(fig, pad)


def plot_hartslag(r: LoperResultaat, pad):
    b = r.banden["hr"]
    x = b["minuten"][1:]
    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.fill_between(x, b["lo"][1:], b["hi"][1:], color=BLAUW, alpha=0.18, lw=0, label="95% van de runs")
    ax.plot(x, b["med"][1:], color=BLAUW, label="Mediaan (voorspeld)")
    ax.set_xlim(0, b["minuten"].max())
    ax.set_ylim(min(100, np.nanmin(b["lo"][1:]) - 5), r.afgeleid.hr_max + 12)
    _drempel(ax, r.afgeleid.hr_max, f"HRmax {r.afgeleid.hr_max:.0f} ({r.afgeleid.hr_max_bron})", ROOD_S)
    ax.set_xlabel("Minuten na de start")
    ax.set_ylabel("Hartslag (slagen/min)")
    ax.set_title("Voorspelde hartslag - vergelijk achteraf met je horloge")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, frameon=False)
    return _opslaan(fig, pad)


def plot_tempo(r: LoperResultaat, pad):
    b = r.banden["tempo"]
    med, snel, traag = b["med"], b["lo"], b["hi"]
    x = b["minuten"]
    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.fill_between(x, snel, traag, color=BLAUW, alpha=0.18, lw=0, label="95% van de runs")
    ax.plot(x, med, color=BLAUW, label="Mediaan")
    ax.axhline(r.invoer.tempo, color=INKT2, ls="--", lw=1.4)
    ax.text(0, r.invoer.tempo, f" gepland {min_naar_tempo(r.invoer.tempo)} min/km", va="bottom",
            fontsize=12, color=INKT2)
    ax.invert_yaxis()
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: min_naar_tempo(v)))
    lo_y = min(np.nanmin(snel), r.invoer.tempo) - 0.05
    hi_y = max(np.nanmax(traag), r.invoer.tempo) + 0.05
    ax.set_ylim(hi_y, lo_y)
    ax.set_xlabel("Minuten na de start")
    ax.set_ylabel("Tempo (min/km), omhoog = sneller")
    ax.set_title("Tempo volgens de pacingwet (vertraging bij hitte en weinig hartreserve)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, frameon=False)
    return _opslaan(fig, pad)


def plot_vocht(r: LoperResultaat, pad):
    b = r.banden["dehyd"]
    x = b["minuten"]
    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.fill_between(x, b["lo"], b["hi"], color=BLAUW, alpha=0.18, lw=0, label="95% van de runs")
    ax.plot(x, b["med"], color=BLAUW, label="Mediaan")
    ax.set_xlim(0, x.max())
    ax.set_ylim(0, max(3.6, np.nanmax(b["hi"]) + 0.4))
    _drempel(ax, 2.0, "2%: prestatie gaat merkbaar achteruit", ORANJE_S)
    _drempel(ax, 3.0, "3%: telt mee in de collapsekans", ROOD_S)
    ax.set_xlabel("Minuten na de start")
    ax.set_ylabel("Vochtverlies (% lichaamsgewicht)")
    ax.set_title("Vochtbalans (zweten min drinken)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2, frameon=False)
    _komma(ax)
    return _opslaan(fig, pad)


def plot_fasediagram(r: LoperResultaat, pad):
    trs = ie.representative_trajectories(r.assessment.all_traces)
    fig, ax = plt.subplots(figsize=(10, 6.4))
    kleuren = [BLAUW, ORANJE, AQUA, PAARS]
    tmin = min(min(t for t in tr["t"] if np.isfinite(t)) for tr in trs)
    tmax = max(max(t for t in tr["t"] if np.isfinite(t)) for tr in trs)
    cmin = min(min(c for c in tr["c"] if np.isfinite(c)) for tr in trs)
    cmax = max(max(c for c in tr["c"] if np.isfinite(c)) for tr in trs)
    x0, x1 = min(37.0, tmin - 0.2), max(41.2, tmax + 0.2)
    y0, y1 = min(-1.5, cmin - 0.5), cmax + 0.5
    ax.fill_between([40.5, x1], y0, 0, color=ROOD_S, alpha=0.12, lw=0)
    ax.fill_between([39.5, x1], 0, 2, color=GEEL_S, alpha=0.12, lw=0)
    ax.text(x1 - 0.05, y0 + 0.1, "gevarenzone\n>= 40,5 C en reserve op", ha="right", va="bottom",
            fontsize=12, color=INKT2)
    for i, tr in enumerate(trs[:4]):
        t, c = np.array(tr["t"], float), np.array(tr["c"], float)
        ok = np.isfinite(t) & np.isfinite(c)
        lab = {"Population median": "mediaan van alle runs", "Lowest risk (dose=0)": "run zonder dosis",
               "Median non-zero dose": "mediane run met dosis", "Highest dose": "run met hoogste dosis",
               "Coolest participant": "koelste run", "Median participant": "mediane run",
               "Hottest participant": "heetste run"}.get(tr["label"], tr["label"])
        mins = np.array(tr["min"], float)
        race = ok & (mins <= tr["stopped_at"] + 1e-6)
        pf = ok & (mins >= tr["stopped_at"] - 1e-6)
        ax.plot(t[race], c[race], color=kleuren[i % 4], lw=2.0, label=lab, marker="o", ms=4)
        ax.plot(t[pf], c[pf], color=kleuren[i % 4], lw=1.2, ls="--")
        ax.plot(t[ok][0], c[ok][0], marker="s", ms=9, color=kleuren[i % 4])
    ax.axhline(0, color=ROOD_S, lw=1.2, ls="--")
    ax.axvline(40.5, color=ROOD_S, lw=1.2, ls="--")
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_xlabel("Rectale temperatuur (C)")
    ax.set_ylabel("Hartreserve (L/min)")
    ax.set_title("Route door het risicovlak (vierkant = start, stippel = na de finish)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2, frameon=False)
    _komma(ax)
    return _opslaan(fig, pad)


def plot_verdeling(r: LoperResultaat, pad):
    d = r.per_run
    fig, axs = plt.subplots(1, 2, figsize=(12, 5.0))
    axs[0].hist(d["t_rect_max"], bins=20, color=BLAUW, edgecolor="white", linewidth=1.5)
    for y, k in ((39.5, ORANJE_S), (40.5, ROOD_S)):
        axs[0].axvline(y, color=k, ls="--", lw=1.5)
    axs[0].set_xlabel("Hoogste rectale temperatuur (C)")
    axs[0].set_ylabel("Aantal runs")
    axs[0].set_title("Piektemperatuur per run")
    axs[1].hist(d["co_reserve_min"], bins=20, color=BLAUW, edgecolor="white", linewidth=1.5)
    for y, k in ((2.0, ORANJE_S), (0.0, ROOD_S)):
        axs[1].axvline(y, color=k, ls="--", lw=1.5)
    axs[1].set_xlabel("Laagste hartreserve tijdens de loop (L/min)")
    axs[1].set_title("Laagste hartreserve per run")
    for ax in axs:
        ax.grid(axis="x", visible=False)
    return _opslaan(fig, pad)


def plot_tempo_watals(r: LoperResultaat, pad):
    """Mediaan (staaf) met de 10%-ongunstigste grens (streepje). Bewust niet
    de 2,5%-staart: met ~100 runs per tempo berust die op 2-3 runs en
    springt hij van tempo tot tempo."""
    g = r.gevoeligheid
    if g is None:
        return None
    fig, axs = plt.subplots(1, 3, figsize=(13, 5.0))
    x = np.arange(len(g))
    lab = [f"{t}\n(+{s} s/km)" if s else f"{t}\n(gepland)" for t, s in zip(g["tempo"], g["extra_s_per_km"])]
    for ax, med, staart, titel, drempels in (
            (axs[0], "t_rect_max_med", "t_rect_max_p90", "Piektemperatuur (C)", ((39.5, ORANJE_S), (40.5, ROOD_S))),
            (axs[1], "co_min_med", "co_min_p10", "Laagste hartreserve (L/min)", ((2.0, ORANJE_S), (0.0, ROOD_S))),
            (axs[2], "dehyd_med", None, "Vochtverlies (%)", ((2.0, ORANJE_S),))):
        temp = med == "t_rect_max_med"
        if temp:   # geen staaf: de as begint niet bij nul
            ax.plot(x, g[med], "o", ms=13, color=BLAUW, zorder=4, label="mediaan")
        else:
            ax.bar(x, g[med], color=BLAUW, width=0.55, label="mediaan")
        if staart:
            ax.hlines(g[staart], x - 0.2, x + 0.2, color=INKT, lw=2.5, zorder=3,
                      label="grens 10% ongunstigste runs")
            for xi, lo_, hi_ in zip(x, g[med], g[staart]):
                ax.plot([xi, xi], [lo_, hi_], color=INKT, lw=1.2, zorder=3)
        for y, k in drempels:
            ax.axhline(y, color=k, ls="--", lw=1.4)
        for xi, v in zip(x, g[med]):
            if temp:
                ax.text(xi + 0.12, v, f"{v:.1f}".replace(".", ","), ha="left", va="center", fontsize=13)
                continue
            ax.text(xi, 0.02, f"{v:.1f}".replace(".", ","), ha="center", va="bottom", fontsize=13,
                    color="white", fontweight="bold", transform=ax.get_xaxis_transform())
        ax.set_xticks(x)
        ax.set_xticklabels(lab, fontsize=12)
        ax.set_xlim(-0.6, len(x) - 0.4)
        ax.set_title(titel, fontsize=15)
        ax.grid(axis="x", visible=False)
        if med == "t_rect_max_med":
            ax.set_ylim(min(38.0, g[med].min() - 0.3), max(41, g[staart].max() + 0.3))
        _komma(ax)
    h, l = axs[0].get_legend_handles_labels()
    fig.suptitle("Wat als je langzamer loopt?", fontsize=17)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.legend(h, l, loc="lower center", ncol=2, frameon=False)
    fig.savefig(pad, dpi=150)
    plt.close(fig)
    return Path(pad)


ALLE_PLOTS = [
    ("weer", plot_weer),
    ("weer_dag", plot_weer_dag),
    ("dashboard", plot_dashboard),
    ("alle_runs", plot_alle_runs),
    ("uitkomsten", plot_uitkomsten),
    ("samenhang", plot_samenhang),
    ("kerntemperatuur", plot_kerntemperatuur),
    ("hartreserve", plot_hartreserve),
    ("hartslag", plot_hartslag),
    ("tempo", plot_tempo),
    ("vocht", plot_vocht),
    ("fasediagram", plot_fasediagram),
    ("verdeling", plot_verdeling),
    ("tempo_watals", plot_tempo_watals),
]


def maak_alle_plots(r: LoperResultaat, map_: str | Path, prefix: str = "loper") -> dict:
    map_ = Path(map_)
    map_.mkdir(parents=True, exist_ok=True)
    uit = {}
    for naam, fn in ALLE_PLOTS:
        p = fn(r, map_ / f"{prefix}_{naam}.png")
        if p is not None:
            uit[naam] = p
    return uit


if __name__ == "__main__":
    print(f"{__file__} is een hulpmodule; start het programma met run_loper.py.")
