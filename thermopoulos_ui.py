# -*- coding: utf-8 -*-
"""
thermopoulos_ui.py -- startscherm voor de vier visuele UI's
============================================================

Eén venster met vier keuzes; elke keuze opent de bijbehorende UI in een eigen
venster (eigen proces), en dit startscherm blijft open:

  HESTIA · één loper ........ hestia_loper_ui.py
  HESTIA · evenement ........ hestia_populatie_ui.py
  PYROX · hittegolf ......... pyrox_ui.py
  KLIMATOS · klimaat ........ klimatos_ui.py

De suite zelf blijft ongewijzigd; dit script start alleen de UI-scripts die
naast de suite staan. Huisstijl en logo's uit branding/.

Starten:  python thermopoulos_ui.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent

PAGINA = "#1F2730"
KAART = "#2B3541"          # = achtergrond van de logo's in branding/
WIT = "#FFFFFF"
GRIJS = "#AEBBC8"
DONKERGRIJS = "#6E7D8C"
VERLOOP = ["#1E7FD8", "#2FA66B", "#F7B733", "#F2611D", "#D62828"]

KEUZES = [
    dict(sleutel="loper", script="hestia_loper_ui.py", logo="hestia", kleur="#2FA66B",
         label="HESTIA  ·  ÉÉN LOPER",
         vraag="Hoe heet wordt het voor mij tijdens deze loop?",
         tekst="Kerntemperatuur, CO-reserve, WBGT en wind minuut voor minuut, voor jouw lichaam, "
               "tempo en route. Schuif met de starttijd en zie het effect meteen. Ook in rust.",
         tijd="direct"),
    dict(sleutel="populatie", script="hestia_populatie_ui.py", logo="hestia", kleur="#1E7FD8",
         label="HESTIA  ·  EVENEMENT",
         vraag="Hoeveel deelnemers lopen hitterisico?",
         tekst="Een virtueel deelnemersveld door het weer van de dag: EHS per 1000, risicobalk, "
               "wanneer en waar het misgaat, de tien heetste lopers en het effect van een andere starttijd.",
         tijd="ca. 1 minuut"),
    dict(sleutel="pyrox", script="pyrox_ui.py", logo="pyrox", kleur="#F2611D",
         label="PYROX  ·  HITTEGOLF",
         vraag="Wie loopt gevaar tijdens een hittegolf?",
         tekst="Opgebouwde hittebelasting per groep, dag na dag, met warme nachten erbij. Marge, "
               "nawerking en kantelpunt, plus een A4-briefing voor veiligheidsfunctionarissen.",
         tijd="direct"),
    dict(sleutel="klimatos", script="klimatos_ui.py", logo="klimatos", kleur="#1FA39B",
         label="KLIMATOS  ·  KLIMAAT",
         vraag="Hoe verschuift de hitte op deze plek en deze datum?",
         tekst="75 jaar ERA5: trends in jaarmaxima, warming stripes, leefbaarheid (HEAT-Lim) en "
               "EHS-evolutie van een vast evenement. Met beoordelingsmodus voor de kustcorrectie.",
         tijd="minuten (uren met EHS)"),
]


def _logo(naam: str, maat: int):
    """Rond logo uit branding/<naam>.png (ring + teken), geschaald."""
    from PIL import Image, ImageTk
    pad = HIER / "branding" / f"{naam}.png"
    if not pad.exists():
        return None
    import numpy as np
    im = Image.open(pad).convert("RGB").crop((148, 62, 364, 278)).resize((maat, maat), Image.LANCZOS)
    a = np.asarray(im).astype(float)
    # achtergrond van het logo doorzichtig maken (zachte rand), zodat het op elke kleur past
    afstand = np.sqrt(((a - np.array([43, 53, 65])) ** 2).sum(axis=2))
    alfa = np.clip(afstand / 45.0, 0, 1)
    rgba = np.dstack([a, 255 * alfa]).astype("uint8")
    return ImageTk.PhotoImage(Image.fromarray(rgba, "RGBA"))


def _mix(a: str, b: str, t: float) -> str:
    ra, ga, ba = (int(a[i:i + 2], 16) for i in (1, 3, 5))
    rb, gb, bb = (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t))


def _verloop(t: float) -> str:
    t = min(max(t, 0.0), 1.0) * (len(VERLOOP) - 1)
    i = min(int(t), len(VERLOOP) - 2)
    return _mix(VERLOOP[i], VERLOOP[i + 1], t - i)


def _start_ui(na_start=None):
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import messagebox

    root = tk.Tk()
    root.title("Thermopoulos — HESTIA · PYROX · Klimatos")
    root.configure(bg=PAGINA)
    bw, bh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{min(1360, bw - 60)}x{min(880, bh - 80)}+20+20")
    root.minsize(1080, 760)

    familie = "Segoe UI" if sys.platform.startswith("win") else ("Helvetica Neue" if sys.platform == "darwin"
                                                                 else "DejaVu Sans")
    if familie not in tkfont.families():
        familie = "Helvetica"
    F = lambda grootte, gewicht="normal": tkfont.Font(family=familie, size=grootte, weight=gewicht)
    f_titel, f_sub, f_label = F(30, "bold"), F(14), F(11, "bold")
    f_vraag, f_tekst, f_klein, f_knop = F(18, "bold"), F(12), F(11), F(13, "bold")

    cv = tk.Canvas(root, bg=PAGINA, highlightthickness=0)
    cv.pack(fill="both", expand=True)
    beeld = {"kop": _logo("thermopoulos", 92)}
    for k in KEUZES:
        beeld[k["sleutel"]] = _logo(k["logo"], 118)
    processen: dict[str, subprocess.Popen] = {}
    toestand = {"hover": None}

    def rond(x0, y0, x1, y1, r, **kw):
        p = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
             x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return cv.create_polygon(p, smooth=True, splinesteps=24, **kw)

    def open_(k):
        script = HIER / k["script"]
        if not script.exists():
            messagebox.showerror("Niet gevonden", f"{k['script']} staat niet in\n{HIER}")
            return
        p = processen.get(k["sleutel"])
        if p is not None and p.poll() is None:
            if not messagebox.askyesno(k["label"].replace("  ", " "),
                                       "Deze UI is al geopend. Nog een venster openen?"):
                return
        flags = {}
        if sys.platform.startswith("win"):
            flags["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        processen[k["sleutel"]] = subprocess.Popen([sys.executable, str(script)], cwd=str(HIER), **flags)
        teken()

    def teken(_=None):
        cv.delete("all")
        W, H = max(cv.winfo_width(), 1080), max(cv.winfo_height(), 760)
        m = 56
        # ---- kop
        if beeld["kop"] is not None:
            cv.create_image(m, 40, image=beeld["kop"], anchor="nw")
        x_t = m + 112
        cv.create_text(x_t, 52, text="T H E R M O P O U L O S", font=f_titel, fill=WIT, anchor="nw")
        cv.create_text(x_t + 3, 100, text="Hitte, mens en klimaat  —  kies wat je wilt weten", font=f_sub,
                       fill=GRIJS, anchor="nw")
        cv.create_text(W - m, 58, text="HESTIA  ·  PYROX  ·  KLIMATOS", font=f_label, fill=DONKERGRIJS,
                       anchor="ne")
        y_lijn = 150
        n = W - 2 * m
        stap = 3
        for i in range(0, n, stap):
            cv.create_line(m + i, y_lijn, m + i + stap, y_lijn, fill=_verloop(i / n), width=3)
        # ---- kaarten
        gat = 28
        top = y_lijn + 32
        onder = H - 78
        kb = (W - 2 * m - gat) / 2
        kh = (onder - top - gat) / 2
        for idx, k in enumerate(KEUZES):
            rij, kol = divmod(idx, 2)
            x0 = m + kol * (kb + gat)
            y0 = top + rij * (kh + gat)
            x1, y1 = x0 + kb, y0 + kh
            tag = f"kaart_{k['sleutel']}"
            actief = toestand["hover"] == k["sleutel"]
            bestaat = (HIER / k["script"]).exists()
            rond(x0, y0, x1, y1, 22, fill=KAART, outline=k["kleur"] if actief else "#37434F",
                 width=3 if actief else 1, tags=tag)
            cv.create_line(x0 + 22, y0 + 1.5, x1 - 22, y0 + 1.5, fill=k["kleur"], width=3, tags=tag)
            if beeld[k["sleutel"]] is not None:
                cv.create_image(x0 + 26, y0 + 30, image=beeld[k["sleutel"]], anchor="nw", tags=tag)
            tx = x0 + 168
            tb = x1 - tx - 30
            cv.create_text(tx, y0 + 34, text=k["label"], font=f_label, fill=k["kleur"], anchor="nw", tags=tag)
            vraag_id = cv.create_text(tx, y0 + 60, text=k["vraag"], font=f_vraag, fill=WIT, anchor="nw",
                                      width=tb, tags=tag)
            vb = cv.bbox(vraag_id)
            cv.create_text(tx, vb[3] + 12, text=k["tekst"], font=f_tekst, fill=GRIJS, anchor="nw", width=tb,
                           tags=tag)
            # onderrand: tijd, status, knop
            yb = y1 - 30
            cv.create_text(x0 + 30, yb, text=f"◷  {k['tijd']}", font=f_klein, fill=DONKERGRIJS, anchor="w",
                           tags=tag)
            p = processen.get(k["sleutel"])
            if p is not None and p.poll() is None:
                cv.create_text(x0 + 30, yb - 24, text="●  geopend", font=f_klein, fill=k["kleur"], anchor="w",
                               tags=tag)
            if not bestaat:
                cv.create_text(x0 + 30, yb - 24, text="script niet gevonden", font=f_klein, fill="#D62828",
                               anchor="w", tags=tag)
            kb_x1, kb_x0 = x1 - 28, x1 - 28 - 150
            rond(kb_x0, yb - 21, kb_x1, yb + 21, 21,
                 fill=k["kleur"] if actief else _mix(k["kleur"], KAART, 0.35), outline="", tags=tag)
            cv.create_text((kb_x0 + kb_x1) / 2, yb, text="Openen   →", font=f_knop, fill=WIT, tags=tag)
            cv.tag_bind(tag, "<Enter>", lambda e, s=k["sleutel"]: hover(s))
            cv.tag_bind(tag, "<Leave>", lambda e: hover(None))
            cv.tag_bind(tag, "<Button-1>", lambda e, kk=k: open_(kk))
        # ---- voet
        cv.create_text(m, H - 38, anchor="w", font=f_klein, fill=DONKERGRIJS,
                       text="Research software  ·  Koos de Boer  ·  elke UI opent in een eigen venster; "
                            "dit startscherm blijft open")
        cv.create_text(W - m, H - 38, anchor="e", font=f_klein, fill=DONKERGRIJS,
                       text="Niet bedoeld als medisch of operationeel advies")

    def hover(s):
        if toestand["hover"] != s:
            toestand["hover"] = s
            cv.configure(cursor="hand2" if s else "")
            teken()

    def peil():
        teken() if any(p.poll() is not None for p in processen.values()) and not toestand.get("stil") else None
        for s in [s for s, p in processen.items() if p.poll() is not None]:
            processen.pop(s)
        root.after(1500, peil)

    cv.bind("<Configure>", teken)
    root.bind("<Key-1>", lambda e: open_(KEUZES[0]))
    root.bind("<Key-2>", lambda e: open_(KEUZES[1]))
    root.bind("<Key-3>", lambda e: open_(KEUZES[2]))
    root.bind("<Key-4>", lambda e: open_(KEUZES[3]))
    root.after(1500, peil)
    if na_start is not None:
        na_start(root, cv, hover, open_)
    root.mainloop()


if __name__ == "__main__":
    os.chdir(HIER)
    _start_ui()
