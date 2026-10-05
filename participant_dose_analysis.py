"""
participant_dose_analysis.py
=============================
Per-deelnemer tijdreeks-analyse van de dosisopbouw (graad-minuten boven de
EHE- en klinische drempel), voor handmatige inspectie van individuele
gevallen -- bijvoorbeeld de deelnemer(s) die het dichtst bij, of over, de
Roberts-dosisdrempel (AUC_klinisch > 60 degC.min) uitkwamen.

Leest rechtstreeks uit `all_results` (de ruwe, per-tijdstap resultatenlijst
die monte_carlo_adult() al produceert) -- er wordt niets herberekend, dit
is een export van wat de simulatie al bijhield. `auc_thermisch` en
`auc_klinisch` zijn in hestia_model.py per tijdstap al de CUMULATIEVE som
tot en met dat moment (regel ~3499: "auc_klinisch += max(0, T_rect-40.5) *
dt_min"), dus deze module hoeft alleen te lezen en (optioneel) te
resamplen, niet te integreren.

Het standaard-tijdinterval van een HESTIA-run is 10 minuten (het
suite-brede weer-interpolatie-interval, overal `interval_minutes=10`).
Bij interval_minutes=10 (of de detectie van diezelfde native afstand)
worden de gesimuleerde tijdstappen ongewijzigd geëxporteerd. Bij een
fijner verzoek (bv. 5 min) wordt lineair geïnterpoleerd tussen de
native punten -- legitiem voor de twee AUC-kolommen (gladde cumulatieve
integralen) en voor T_rect/CO_reserve, maar dit is GEEN hogere-resolutie
simulatie-uitkomst en wordt als zodanig gemarkeerd in de output
(kolom 'geinterpoleerd'). Booleans (stopped/decompensating) worden bij
interpolatie met forward-fill behandeld, nooit geïnterpoleerd.
"""

import os
from datetime import datetime
import numpy as np
import pandas as pd


AUC_THERMISCH_DREMPEL = 39.0   # degC -- vroeg-signaal / EHE-achtig
AUC_KLINISCH_DREMPEL = 40.5    # degC -- Roberts (2007) klinische drempel
ROBERTS_KRITIEK_GRENS = 60.0   # degC.min -- Roberts' eigen afkappunt


def _sim_to_dataframe(sim):
    """Eén deelnemers-resultatenlijst (all_results[idx]) -> DataFrame."""
    rows = []
    for r in sim:
        rows.append({
            "time":            pd.to_datetime(r["time"]),
            "t_rect_degC":     r.get("t_rect", np.nan),
            "co_reserve_Lmin": r.get("co_reserve", np.nan),
            "auc_thermisch_cumulatief_degCmin": r.get("auc_thermisch", np.nan),
            "auc_klinisch_cumulatief_degCmin":  r.get("auc_klinisch", np.nan),
            "wbgt_degC":       r.get("wbgt", np.nan),
            "current_met":     r.get("current_met", np.nan),
            "rpe_total":       r.get("rpe_total", np.nan),
            "gestopt":         bool(r.get("stopped", False)),
            "decompenserend":  bool(r.get("decompensating", False)),
        })
    df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
    return df


def _resample_to_interval(df, interval_minutes):
    """
    Retourneert (df_out, was_geinterpoleerd, native_interval_min).
    Bij interval_minutes >= native: eenvoudige selectie/aggregatie op de
    dichtstbijzijnde beschikbare tijdstappen (geen interpolatie nodig).
    Bij interval_minutes < native: lineaire interpolatie van de continue
    kolommen; booleans krijgen forward-fill.
    """
    if len(df) < 2:
        return df.copy(), False, None

    native_min = (df["time"].iloc[1] - df["time"].iloc[0]).total_seconds() / 60.0

    if interval_minutes is None or abs(interval_minutes - native_min) < 1e-6:
        out = df.copy()
        return out, False, native_min

    start, end = df["time"].iloc[0], df["time"].iloc[-1]
    new_index = pd.date_range(start=start, end=end, freq=f"{interval_minutes}min")
    if new_index[-1] < end:
        new_index = new_index.append(pd.DatetimeIndex([end]))

    if interval_minutes > native_min:
        # Grover dan native: dichtstbijzijnde bestaande tijdstap pakken
        # (geen interpolatie -- alle waarden, ook de cumulatieve AUC's,
        # zijn dan exact wat er op dat moment al gesimuleerd was).
        out = df.set_index("time").reindex(new_index, method="nearest").reset_index()
        out = out.rename(columns={"index": "time"})
        return out, False, native_min

    # Fijner dan native: lineair interpoleren (continue kolommen) +
    # forward-fill (booleans).
    df_idx = df.set_index("time")
    bool_cols = ["gestopt", "decompenserend"]
    cont_cols = [c for c in df_idx.columns if c not in bool_cols]

    combined_index = df_idx.index.union(new_index)
    out_cont = df_idx[cont_cols].reindex(combined_index).interpolate(method="time").reindex(new_index)
    out_bool = df_idx[bool_cols].reindex(combined_index).ffill().reindex(new_index)
    out = pd.concat([out_cont, out_bool], axis=1).reset_index().rename(columns={"index": "time"})
    return out, True, native_min


def export_participant_dose_buildup(all_results, participant_ids, interval_minutes=10,
                                     out_path=None, results_df=None,
                                     city="Amsterdam", start_date=""):
    """
    Exporteer de tijdreeks-opbouw van AUC_thermisch en AUC_klinisch (en
    T_rect/CO_reserve als context) voor de gekozen deelnemer-ID's naar een
    los Excel-bestand, één werkblad per deelnemer.

    Parameters
    ----------
    all_results : list
        De ruwe, per-deelnemer resultatenlijst zoals geretourneerd door
        monte_carlo_adult() -- all_results[i] is deelnemer i+1 (1-indexed
        participant_id, dezelfde conventie als de Monte-Carlo-Excel-export).
    participant_ids : int of list[int]
        Eén of meer 1-indexed deelnemer-ID's om te exporteren.
    interval_minutes : int, default 10
        Gewenst tijdinterval in de output. 10 (of het native interval van
        de run) geeft de werkelijk gesimuleerde tijdstappen ongewijzigd.
        Een kleinere waarde interpoleert (zie moduledocstring); een
        grotere waarde selecteert de dichtstbijzijnde native tijdstap.
    out_path : str, optioneel
        Volledig pad voor het Excel-bestand. Als None, wordt een naam
        gegenereerd: HESTIA_DeelnemerDosisOpbouw_{city}_{start_date}_
        {timestamp}.xlsx in de huidige map.
    results_df : pd.DataFrame, optioneel
        De reguliere per-deelnemer samenvattings-Excel-data (met
        participant_id, age, gender, vo2max_ml_kg_min, etc.) -- indien
        meegegeven wordt per deelnemer een profielblok bovenaan het
        werkblad gezet.

    Returns
    -------
    str
        Pad naar het geschreven Excel-bestand.
    """
    if isinstance(participant_ids, int):
        participant_ids = [participant_ids]
    participant_ids = list(dict.fromkeys(int(p) for p in participant_ids))  # uniek, volgorde behouden

    n_sim = len(all_results)
    invalid = [p for p in participant_ids if p < 1 or p > n_sim]
    if invalid:
        raise ValueError(
            f"Deelnemer-ID('s) {invalid} buiten bereik -- deze run heeft "
            f"deelnemers 1 t/m {n_sim}."
        )

    if out_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        out_path = f"HESTIA_DeelnemerDosisOpbouw_{city}_{start_date}_{timestamp}.xlsx"

    readme_rows = [
        ["Doel", "Tijdreeks-opbouw van de dosismaten per gekozen deelnemer, "
                 "rechtstreeks uit de simulatie -- niets herberekend."],
        ["auc_thermisch_cumulatief_degCmin",
         f"Cumulatieve graad-minuten T_rect boven {AUC_THERMISCH_DREMPEL} degC "
         f"(vroeg-signaal, EHE-achtig), vanaf de start tot dat moment."],
        ["auc_klinisch_cumulatief_degCmin",
         f"Cumulatieve graad-minuten T_rect boven {AUC_KLINISCH_DREMPEL} degC "
         f"(Roberts 2007, klinische dosis). Roberts-kritiek bij > "
         f"{ROBERTS_KRITIEK_GRENS} degC.min."],
        ["delta_*_dit_interval", "Toename sinds de vorige rij in dit werkblad "
                                  "(dus AFHANKELIJK van interval_minutes)."],
        ["geinterpoleerd", "True = deze rij is lineair geinterpoleerd tussen "
                            "werkelijk gesimuleerde tijdstappen (fijner "
                            "verzocht dan het native interval). False = "
                            "exact een gesimuleerde tijdstap."],
    ]

    with pd.ExcelWriter(out_path, engine="xlsxwriter") as writer:
        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#1F4E79",
                                           "font_color": "white", "border": 1})
        note_fmt = workbook.add_format({"italic": True, "font_color": "#595959"})

        # --- Leeswijzer-blad ---
        readme_df = pd.DataFrame(readme_rows, columns=["Veld", "Betekenis"])
        readme_df.to_excel(writer, sheet_name="Leeswijzer", index=False)
        ws = writer.sheets["Leeswijzer"]
        for col, width in [("A", 34), ("B", 90)]:
            ws.set_column(f"{col}:{col}", width)
        for c, name in enumerate(readme_df.columns):
            ws.write(0, c, name, header_fmt)

        native_min_seen = None
        for pid in participant_ids:
            sim = all_results[pid - 1]
            df = _sim_to_dataframe(sim)
            df_out, was_interp, native_min = _resample_to_interval(df, interval_minutes)
            native_min_seen = native_min_seen or native_min

            df_out.insert(1, "geinterpoleerd", was_interp if was_interp else False)
            df_out["delta_auc_thermisch_dit_interval"] = df_out["auc_thermisch_cumulatief_degCmin"].diff().fillna(0.0)
            df_out["delta_auc_klinisch_dit_interval"] = df_out["auc_klinisch_cumulatief_degCmin"].diff().fillna(0.0)
            df_out["roberts_kritiek_bereikt"] = df_out["auc_klinisch_cumulatief_degCmin"] > ROBERTS_KRITIEK_GRENS

            sheet_name = f"Deelnemer_{pid}"[:31]  # Excel-limiet: 31 tekens
            start_row = 0

            # --- profielblok, indien results_df meegegeven ---
            if results_df is not None and "participant_id" in results_df.columns:
                prof = results_df[results_df["participant_id"] == pid]
                if not prof.empty:
                    prof_cols = [c for c in ["participant_id", "age", "gender", "height_m",
                                              "weight_kg", "vo2max_ml_kg_min", "pct_vo2max",
                                              "nsaid_gebruik"] if c in prof.columns]
                    prof_out = prof[prof_cols].T.reset_index()
                    prof_out.columns = ["Profielveld", "Waarde"]
                    prof_out.to_excel(writer, sheet_name=sheet_name, index=False, startrow=0)
                    ws2 = writer.sheets[sheet_name]
                    for c, name in enumerate(prof_out.columns):
                        ws2.write(0, c, name, header_fmt)
                    start_row = len(prof_out) + 2

            df_out.to_excel(writer, sheet_name=sheet_name, index=False, startrow=start_row)
            ws2 = writer.sheets[sheet_name]
            for c, name in enumerate(df_out.columns):
                ws2.write(start_row, c, name, header_fmt)
            ws2.set_column("A:A", 18)
            ws2.set_column("B:L", 15)
            if was_interp:
                ws2.write(start_row - 1, 0,
                          f"Let op: interval_minutes={interval_minutes} is fijner dan het "
                          f"native simulatie-interval ({native_min:.0f} min) -- deze reeks is "
                          f"lineair geinterpoleerd, geen extra simulatie-precisie.", note_fmt)

    return out_path


# ---------------------------------------------------------------------------
# Optionele interactieve CLI-hook -- aan te roepen aan het einde van een
# HESTIA-run (zie run_hestia.py: na de Word/Markdown-rapportage-prompts).
# ---------------------------------------------------------------------------
def maybe_run_participant_analysis(all_results, results_df=None, city="Amsterdam",
                                    start_date="", script_dir=None, prompt_fn=None):
    """
    Vraagt interactief of de gebruiker de deelnemer-dosisopbouw-tool wil
    draaien, en zo ja, welke deelnemer-ID's en welk tijdinterval.
    `prompt_fn`: optioneel een functie(msg, default) -> str, zodat dit
    dezelfde _prompt()-stijl als de rest van run_hestia.py kan hergebruiken
    zonder een circulaire import.
    """
    def _default_prompt(msg, default):
        raw = input(f"{msg} [{default}]: ").strip()
        return raw if raw else default

    ask = prompt_fn or _default_prompt

    if not ask("Deelnemer-dosisopbouw exporteren naar Excel? (y/n)", "n").lower().startswith("y"):
        return None

    raw_ids = ask("Deelnemer-ID('s), komma-gescheiden (1-indexed)", "1")
    try:
        participant_ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
    except ValueError:
        print("  Ongeldige invoer -- geen geldige deelnemer-ID's, tool overgeslagen.")
        return None

    raw_interval = ask("Tijdinterval in minuten (5 of 10; 10 = native, geen interpolatie)", "10")
    try:
        interval_minutes = int(raw_interval)
    except ValueError:
        interval_minutes = 10

    out_dir = script_dir or os.getcwd()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_path = os.path.join(
        out_dir, f"HESTIA_DeelnemerDosisOpbouw_{city}_{start_date}_{timestamp}.xlsx")

    try:
        written = export_participant_dose_buildup(
            all_results, participant_ids, interval_minutes=interval_minutes,
            out_path=out_path, results_df=results_df, city=city, start_date=start_date,
        )
        print(f"  Deelnemer-dosisopbouw geschreven naar: {written}")
        return written
    except ValueError as e:
        print(f"  {e}")
        return None
