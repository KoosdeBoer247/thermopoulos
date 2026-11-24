# -*- coding: utf-8 -*-
"""
thermopoulos_ui.py -- startscherm voor de vijf visuele UI's
============================================================

Eén venster met vijf keuzes; elke keuze opent de bijbehorende UI in een eigen
venster (eigen proces), en dit startscherm blijft open:

  HESTIA · één loper ........ hestia_loper_ui.py
  HESTIA · evenement ........ hestia_populatie_ui.py
  HESTIA · werk ............. hestia_werk_ui.py
  PYROX · hittegolf ......... pyrox_ui.py
  KLIMATOS · klimaat ........ klimatos_ui.py

De suite zelf blijft ongewijzigd; dit script start alleen de UI-scripts die
naast de suite staan. Huisstijl en logo's uit branding/.

Taal: het startscherm opent in het Nederlands. De Britse vlag (rechtsboven)
schakelt het startscherm naar het Engels; elk venster dat daarna geopend wordt
start in het Engels (THERMOPOULOS_TAAL=en, zie taal.py). De Nederlandse vlag
schakelt terug.

Starten:  python thermopoulos_ui.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
if str(HIER) not in sys.path:
    sys.path.insert(0, str(HIER))
import taal  # noqa: E402
from taal import vt  # noqa: E402

PAGINA = "#1F2730"
KAART = "#2B3541"          # = achtergrond van de logo's in branding/
WIT = "#FFFFFF"
GRIJS = "#AEBBC8"
DONKERGRIJS = "#6E7D8C"
VERLOOP = ["#1E7FD8", "#2FA66B", "#F7B733", "#F2611D", "#D62828"]

def keuzes() -> list:
    """De vijf kaarten in de gekozen taal (opnieuw opgevraagd bij elke taalwissel)."""
    return [
    dict(sleutel="loper", script="hestia_loper_ui.py", logo="hestia", kleur="#2FA66B",
         label=vt("HESTIA  ·  ÉÉN LOPER", "HESTIA  ·  ONE RUNNER"),
         vraag=vt("Hoe heet wordt het voor mij tijdens deze loop?", "How hot will this run be for me?"),
         tekst=vt("Kerntemperatuur, CO-reserve, WBGT en wind minuut voor minuut, voor jouw lichaam, "
                  "tempo en route. Schuif met de starttijd en zie het effect meteen. Ook in rust.",
                  "Core temperature, cardiac reserve, WBGT and wind minute by minute, for your body, pace "
                  "and route. Move the start time and see the effect at once. Also at rest."),
         tijd=vt("direct", "instant")),
    dict(sleutel="populatie", script="hestia_populatie_ui.py", logo="hestia", kleur="#1E7FD8",
         label=vt("HESTIA  ·  EVENEMENT", "HESTIA  ·  EVENT"),
         vraag=vt("Hoeveel deelnemers lopen hitterisico?", "How many participants are at heat risk?"),
         tekst=vt("Een virtueel deelnemersveld door het weer van de dag: EHS per 1000, risicobalk, "
                  "wanneer en waar het misgaat, de tien heetste lopers en het effect van een andere starttijd.",
                  "A virtual field of participants through the weather of the day: EHS per 1000, risk bar, "
                  "when and where it goes wrong, the ten hottest runners and the effect of another start time."),
         tijd=vt("ca. 1 minuut", "about 1 minute")),
    dict(sleutel="werk", script="hestia_werk_ui.py", logo="hestia", kleur="#7D3C98",
         label=vt("HESTIA  ·  WERK", "HESTIA  ·  WORK"),
         vraag=vt("Hoe zwaar is de hitte voor buitenwerkers vandaag?", "How hard is the heat on outdoor workers today?"),
         tekst=vt("Een groep werkers over de werkdag met werk-rustschema en pauzes: kerntemperatuur, vocht "
                  "en hartslag tegen de beroepsgrenzen, WBGT tegen ISO 7243.",
                  "A group of workers over the working day with a work–rest schedule and breaks: core "
                  "temperature, fluid loss and heart rate against occupational limits, WBGT against ISO 7243."),
         tijd=vt("ca. 1 minuut", "about 1 minute")),
    dict(sleutel="pyrox", script="pyrox_ui.py", logo="pyrox", kleur="#F2611D",
         label=vt("PYROX  ·  HITTEGOLF", "PYROX  ·  HEATWAVE"),
         vraag=vt("Wie loopt gevaar tijdens een hittegolf?", "Who is in danger during a heatwave?"),
         tekst=vt("Opgebouwde hittebelasting per groep, dag na dag, met warme nachten erbij. Marge, "
                  "nawerking en kantelpunt, plus een A4-briefing voor veiligheidsfunctionarissen.",
                  "Accumulated heat strain per group, day after day, including warm nights. Margin, "
                  "after-effect and tipping point, plus an A4 briefing for safety officers."),
         tijd=vt("direct", "instant")),
    dict(sleutel="klimatos", script="klimatos_ui.py", logo="klimatos", kleur="#1FA39B",
         label=vt("KLIMATOS  ·  KLIMAAT", "KLIMATOS  ·  CLIMATE"),
         vraag=vt("Hoe verschuift de hitte op deze plek en deze datum?",
                  "How is the heat shifting at this place and date?"),
         tekst=vt("75 jaar ERA5: trends in jaarmaxima, warming stripes, leefbaarheid (HEAT-Lim) en "
                  "EHS-evolutie van een vast evenement. Met beoordelingsmodus voor de kustcorrectie.",
                  "75 years of ERA5: trends in annual maxima, warming stripes, liveability (HEAT-Lim) and "
                  "EHS evolution of a fixed event. With an assessment mode for the coastal correction."),
         tijd=vt("minuten (uren met EHS)", "minutes (hours with EHS)")),
    ]


KEUZES = keuzes()   # voor bestaande tests en scripts


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
    staat_k = {"k": keuzes()}
    root.configure(bg=PAGINA)
    bw, bh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{min(1360, bw - 60)}x{min(1000, bh - 80)}+20+20")
    root.minsize(1080, 820)

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
    RIJEN = (len(KEUZES) + 1) // 2
    LOGO = 118 if RIJEN <= 2 else 92
    for k in staat_k["k"]:
        beeld[k["sleutel"]] = _logo(k["logo"], LOGO)
    processen: dict[str, subprocess.Popen] = {}
    toestand = {"hover": None}

    def rond(x0, y0, x1, y1, r, **kw):
        p = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
             x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return cv.create_polygon(p, smooth=True, splinesteps=24, **kw)

    def open_(k):
        script = HIER / k["script"]
        if not script.exists():
            messagebox.showerror(vt("Niet gevonden", "Not found"),
                                 vt(f"{k['script']} staat niet in\n{HIER}", f"{k['script']} is not in\n{HIER}"))
            return
        p = processen.get(k["sleutel"])
        if p is not None and p.poll() is None:
            if not messagebox.askyesno(k["label"].replace("  ", " "),
                                       vt("Deze UI is al geopend. Nog een venster openen?",
                                          "This interface is already open. Open another window?")):
                return
        flags = {}
        if sys.platform.startswith("win"):
            flags["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        env = dict(os.environ, THERMOPOULOS_TAAL=taal.TAAL)
        processen[k["sleutel"]] = subprocess.Popen([sys.executable, str(script)], cwd=str(HIER), env=env,
                                                   **flags)
        teken()

    def vlag_nl(x, y, w, h, tag):
        for i, kleur in enumerate(("#AE1C28", "#FFFFFF", "#21468B")):
            cv.create_rectangle(x, y + i * h / 3, x + w, y + (i + 1) * h / 3, fill=kleur, outline="", tags=tag)

    def vlag_uk(x, y, w, h, tag):
        """Union Jack, vereenvoudigd (St Patrick's kruis niet verschoven)."""
        cv.create_rectangle(x, y, x + w, y + h, fill="#012169", outline="", tags=tag)
        for (a, b, c, d) in ((x, y, x + w, y + h), (x, y + h, x + w, y)):
            cv.create_line(a, b, c, d, fill="#FFFFFF", width=h * 0.2, tags=tag)
            cv.create_line(a, b, c, d, fill="#C8102E", width=h * 0.07, tags=tag)
        cv.create_rectangle(x + w / 2 - h * 0.17, y, x + w / 2 + h * 0.17, y + h, fill="#FFFFFF", outline="",
                            tags=tag)
        cv.create_rectangle(x, y + h / 2 - h * 0.17, x + w, y + h / 2 + h * 0.17, fill="#FFFFFF", outline="",
                            tags=tag)
        cv.create_rectangle(x + w / 2 - h * 0.1, y, x + w / 2 + h * 0.1, y + h, fill="#C8102E", outline="",
                            tags=tag)
        cv.create_rectangle(x, y + h / 2 - h * 0.1, x + w, y + h / 2 + h * 0.1, fill="#C8102E", outline="",
                            tags=tag)

    def vlaggen(x_rechts, y):
        """Taalkeuze rechtsboven: Nederlandse en Britse vlag; de gekozen taal krijgt een rand."""
        h = 24
        for t, w, teken_vlag, x0 in (("en", 48, vlag_uk, x_rechts - 48),
                                      ("nl", 36, vlag_nl, x_rechts - 48 - 14 - 36)):
            tag = f"taal_{t}"
            teken_vlag(x0, y, w, h, tag)
            actief = taal.TAAL == t
            cv.create_rectangle(x0 - 3, y - 3, x0 + w + 3, y + h + 3, outline=WIT if actief else "#37434F",
                                width=2 if actief else 1, tags=tag)
            cv.tag_bind(tag, "<Button-1>", lambda e, tt=t: wissel_taal(tt))
            cv.tag_bind(tag, "<Enter>", lambda e: cv.configure(cursor="hand2"))
            cv.tag_bind(tag, "<Leave>", lambda e: cv.configure(cursor=""))
        cv.create_text(x_rechts - 48 - 14 - 36 - 10, y + h / 2, anchor="e", font=f_klein, fill=DONKERGRIJS,
                       text=vt("Taal", "Language"))

    def wissel_taal(t):
        if t == taal.TAAL:
            return
        taal.zet_taal(t)
        staat_k["k"] = keuzes()
        teken()

    def teken(_=None):
        cv.delete("all")
        W, H = max(cv.winfo_width(), 1080), max(cv.winfo_height(), 820)
        m = 56
        # ---- kop
        if beeld["kop"] is not None:
            cv.create_image(m, 40, image=beeld["kop"], anchor="nw")
        x_t = m + 112
        cv.create_text(x_t, 52, text="T H E R M O P O U L O S", font=f_titel, fill=WIT, anchor="nw")
        cv.create_text(x_t + 3, 100, text=vt("Hitte, mens en klimaat  —  kies wat je wilt weten",
                                             "Heat, people and climate  —  choose what you want to know"),
                       font=f_sub, fill=GRIJS, anchor="nw")
        cv.create_text(W - m, 58, text="HESTIA  ·  PYROX  ·  KLIMATOS", font=f_label, fill=DONKERGRIJS,
                       anchor="ne")
        vlaggen(W - m, 92)
        y_lijn = 150
        n = W - 2 * m
        stap = 3
        for i in range(0, n, stap):
            cv.create_line(m + i, y_lijn, m + i + stap, y_lijn, fill=_verloop(i / n), width=3)
        # ---- kaarten
        gat = 28 if RIJEN <= 2 else 20
        top = y_lijn + (32 if RIJEN <= 2 else 22)
        onder = H - 78
        kb = (W - 2 * m - gat) / 2
        kh = (onder - top - gat * (RIJEN - 1)) / RIJEN
        for idx, k in enumerate(staat_k["k"]):
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
                cv.create_image(x0 + 26, y0 + (30 if RIJEN <= 2 else 22), image=beeld[k["sleutel"]],
                                anchor="nw", tags=tag)
            tx = x0 + LOGO + 50
            tb = x1 - tx - 30
            ty = y0 + (34 if RIJEN <= 2 else 22)
            cv.create_text(tx, ty, text=k["label"], font=f_label, fill=k["kleur"], anchor="nw", tags=tag)
            yb = y1 - (30 if RIJEN <= 2 else 24)
            # Vraag naast het logo, toelichting eronder over de volle breedte; lettergrootte
            # zakt stapsgewijs tot alles boven de knoprij past (vijf kaarten in drie rijen).
            # Laatste stap: alleen de vraag (bij een klein venster of schermschaling).
            maten = ((f_vraag, f_tekst), (F(16, "bold"), F(11)), (F(15, "bold"), F(10)), (F(15, "bold"), None))
            for poging, (fv, ft) in enumerate(maten):
                ids = []
                vraag_id = cv.create_text(tx, ty + 24, text=k["vraag"], font=fv, fill=WIT, anchor="nw",
                                          width=tb, tags=tag)
                ids.append(vraag_id)
                vb = cv.bbox(vraag_id)
                logo_onder = y0 + (30 if RIJEN <= 2 else 22) + LOGO
                t_y = max(vb[3] + 10, logo_onder + 8) if RIJEN > 2 else vb[3] + 12
                t_x = x0 + 30 if RIJEN > 2 else tx
                if ft is None:
                    break
                t_id = cv.create_text(t_x, t_y, text=k["tekst"], font=ft, fill=GRIJS, anchor="nw",
                                      width=(x1 - 30 - t_x), tags=tag)
                ids.append(t_id)
                if cv.bbox(t_id)[3] <= yb - 23:
                    break
                for i_ in ids:
                    cv.delete(i_)
            # onderrand: tijd, status, knop
            cv.create_text(x0 + 30, yb, text=f"◷  {k['tijd']}", font=f_klein, fill=DONKERGRIJS, anchor="w",
                           tags=tag)
            p = processen.get(k["sleutel"])
            if p is not None and p.poll() is None:
                cv.create_text(x0 + 220, yb, text=vt("●  geopend", "●  open"), font=f_klein, fill=k["kleur"], anchor="w",
                               tags=tag)
            if not bestaat:
                cv.create_text(x0 + 220, yb, text=vt("script niet gevonden", "script not found"), font=f_klein, fill="#D62828",
                               anchor="w", tags=tag)
            kb_x1, kb_x0 = x1 - 28, x1 - 28 - 150
            rond(kb_x0, yb - 21, kb_x1, yb + 21, 21,
                 fill=k["kleur"] if actief else _mix(k["kleur"], KAART, 0.35), outline="", tags=tag)
            cv.create_text((kb_x0 + kb_x1) / 2, yb, text=vt("Openen   →", "Open   →"), font=f_knop, fill=WIT,
                           tags=tag)
            cv.tag_bind(tag, "<Enter>", lambda e, s=k["sleutel"]: hover(s))
            cv.tag_bind(tag, "<Leave>", lambda e: hover(None))
            cv.tag_bind(tag, "<Button-1>", lambda e, kk=k: open_(kk))
        # ---- voet
        links_id = cv.create_text(m, H - 38, anchor="w", font=f_klein, fill=DONKERGRIJS,
                                  text=vt("Research software  ·  Koos de Boer  ·  elke UI opent in een eigen "
                                          "venster; dit startscherm blijft open",
                                          "Research software  ·  Koos de Boer  ·  each interface opens in its own "
                                          "window; this start screen stays open"))
        rechts_id = cv.create_text(W - m, H - 38, anchor="e", font=f_klein, fill=DONKERGRIJS,
                                   text=vt("Niet bedoeld als medisch of operationeel advies",
                                           "Not intended as medical or operational advice"))
        if cv.bbox(links_id)[2] + 20 > cv.bbox(rechts_id)[0]:   # smal venster: onder elkaar
            cv.move(links_id, 0, -12)
            cv.coords(rechts_id, m, H - 26)
            cv.itemconfigure(rechts_id, anchor="w")

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
    for _i in range(5):
        root.bind(f"<Key-{_i + 1}>", lambda e, i=_i: open_(staat_k["k"][i]))
    root.after(1500, peil)
    if na_start is not None:
        na_start(root, cv, hover, open_) if na_start.__code__.co_argcount == 4 else \
            na_start(root, cv, hover, open_, wissel_taal)
    root.mainloop()


if __name__ == "__main__":
    os.chdir(HIER)
    _start_ui()
