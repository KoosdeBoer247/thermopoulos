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


def plot_weer(r: LoperResultaat, pad):
    m = r.assessment.meteo
    t0 = m["time"][0]
    x = [(t - t0).total_seconds() / 60 for t in m["time"]]
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for key, lab, kl in (("t_air", "Luchttemperatuur", BLAUW), ("wbgt", "WBGT", ORANJE),
                         ("utci", "UTCI (gevoelstemperatuur)", AQUA), ("mrt", "Stralingstemperatuur (MRT)", PAARS)):
        ax.plot(x, m[key], color=kl, label=lab)
    ax.set_xlabel(f"Minuten na de start ({t0:%H:%M})")
    ax.set_ylabel("C")
    ax.set_title(f"Weer tijdens jouw loop - {r.assessment.city_name}, {t0:%d-%m-%Y}")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False)
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
    ax.set_title("Kerntemperatuur (JOS-3, gevalideerd voor sport)")
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
