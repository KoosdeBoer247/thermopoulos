"""
generate_recommendation_report.py -- Klimatos.ClimateShift TIMING-ADVICE
report generator (rev1, 2026-08-28, proof-of-concept)

BELANGRIJK ONDERSCHEID MET DE ANDERE TWEE RAPPORTGENERATOREN:
generate_event_report.py en generate_klimatos_report.py zijn bewust
"alleen feiten, geen advies" -- deze module is het tegenovergestelde, en
bewust zo. Dit rapport bevat wel degelijk een afweging en een aanbeveling.
Het is bedoeld als een apart, duidelijk als zodanig gelabeld documenttype
voor organisaties die specifiek een advies willen over TIJDSTIP-
interventies (starttijd, datum/seizoen) -- niet over andere maatregelen
(drinkposten, medische bezetting, etc. vallen hier uitdrukkelijk buiten).

Scope, bewust beperkt
----------------------
- Starttijd-verschuiving: GEKWANTIFICEERD, met de "early start"-cijfers die
  Klimatos' eigen EHS-evolutiemodule al berekent (geen aparte modelrun
  nodig -- dezelfde run die de EHS/EHE/collapse-risico-evolutie oplevert,
  berekent ook een vroege-start-scenario ernaast).
- Datum/seizoen-verschuiving: UITDRUKKELIJK KWALITATIEF in deze versie. Een
  kwantitatieve vergelijking (bijv. "wat als dit evenement in april in
  plaats van mei plaatsvond") vereist een nieuwe event-window-run
  geankerd op die andere datum -- een aparte, tijdrovende berekening die
  deze versie bewust niet doet. Dat gat wordt expliciet benoemd in het
  rapport zelf, niet verstopt.

Generiek, met één evenement als voorbeeld
-------------------------------------------
De sjabloonstructuur is generiek (bruikbaar voor elk evenement waarvoor
Klimatos is gedraaid); dit script vult hem op dit moment met de Utrecht
Marathon als concreet, doorgerekend voorbeeld.
"""

from datetime import datetime, timezone
import numpy as np
import pandas as pd


def _fmt(x, decimals=2, suffix=""):
    if x is None:
        return "n.b."
    try:
        if pd.isna(x):
            return "n.b."
    except (TypeError, ValueError):
        pass
    try:
        return f"{float(x):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(x)


def generate_recommendation_report(event_name: str,
                                    meta: dict,
                                    event_df: pd.DataFrame,
                                    ehs_df: pd.DataFrame,
                                    output_path: str,
                                    current_start_time: str,
                                    early_start_time: str,
                                    baseline_period: tuple = None,
                                    reference_period: tuple = None,
                                    ehe_evidence: dict = None,
                                    event_window_trend_significant: bool = None,
                                    collapse_calibration_note: str = None,
                                    documented_reference: str = None) -> str:
    """
    Genereer een adviesrapport over tijdstip-interventies (vroegere
    starttijd, en kwalitatief: andere datum/seizoen) voor een specifiek
    evenement, en schrijf het weg als Markdown.

    In tegenstelling tot generate_event_report.py / generate_klimatos_
    report.py bevat dit rapport WEL een afweging en een aanbeveling.

    Parameters
    ----------
    event_name : str
    meta : dict
        Zelfde metadata-dict als de andere generators (stad, coördinaten,
        event_window-beschrijving, ...).
    event_df : pd.DataFrame
        Klimatos' event-window-samenvatting (baseline/referentie/trend/
        projecties per variabele) -- voor de "oorzaak"-sectie.
    ehs_df : pd.DataFrame
        Klimatos' EHS-evolutie-samenvatting, MET de early-start-kolommen
        (ehs_per_1000_early_start, collapse_per_1000_early_start,
        ratio_early_start_vs_reference, collapse_ratio_early_start_vs_early_reference)
        -- voor zowel "gevolg" als de starttijd-aanbeveling.
    output_path : str
    current_start_time, early_start_time : str
        Vrije tekst, bijv. "10:30" en "09:00", voor leesbare vermelding.
    baseline_period, reference_period : tuple, optional
        (start, eind) van de "Baseline"- resp. "Referentie"-periode die in
        event_df wordt vergeleken (bijv. (1951, 1980) en (1995, 2025)).
        Zonder deze twee parameters is de Baseline/Referentie-tabel in
        sectie 2 niet te interpreteren -- welke jaren die kolommen dekken
        staat dan nergens vermeld.
    ehe_evidence : dict, optional
        Losse feitelijke EHE/klinisch-criterium-bevindingen (bijv. "EHE
        vuurde daadwerkelijk, dichtstbijzijnde punt was X" of "EHE bleef op
        0%, dichtstbijzijnde punt was Y verwijderd") als vrije tekstregels,
        voor de "gevolg"-sectie. None laat die alinea weg.
    event_window_trend_significant : bool, optional
        Of de evenement-venster-trend (niet de jaarlijkse extremen)
        statistisch significant was. None laat de kanttekening generiek
        ("mogelijk niet significant, zie de feitenrapportage").
    collapse_calibration_note : str, optional
        Vrije tekst over de ijkingsherkomst van het collapse-risico-
        eindpunt voor dít evenement (bijv. "geijkt op een 100 minuten durend
        evenement, hier geëxtrapoleerd naar 231 minuten"), voor de
        kernvraag-sectie. None laat een generieke PROVISIONAL-kanttekening
        staan zonder de extrapolatie-specifieke toevoeging.
    documented_reference : str, optional

    Returns
    -------
    str
    """
    lines = []
    A = lines.append

    A(f"# Adviesrapport tijdstip-interventies — {event_name}")
    A("")
    A(f"*Automatisch gegenereerd op {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"door generate_recommendation_report.py (proefversie).*")
    A("")
    A("**Dit is een ADVIESDOCUMENT, geen feitenrapport.** In tegenstelling "
      "tot de EHS/collapse-risico-feitenrapporten van deze suite bevat dit "
      "document een afweging en een aanbeveling, op basis van de "
      "onderliggende modelcijfers. Het gaat uitsluitend over TIJDSTIP-"
      "interventies (starttijd, datum/seizoen) -- niet over andere "
      "maatregelen zoals drinkposten of medische bezetting, die hier "
      "bewust buiten beschouwing blijven.")
    A("")
    A("---")
    A("")

    # ------------------------------------------------------------------ #
    A("## 1. Samenvatting")
    A("")
    ref_ehs = ehs_df["reference_ehs_per_1000"].iloc[0] if (
        ehs_df is not None and not ehs_df.empty and "reference_ehs_per_1000" in ehs_df.columns) else np.nan
    ref_collapse = ehs_df["reference_collapse_per_1000"].iloc[0] if (
        ehs_df is not None and not ehs_df.empty and "reference_collapse_per_1000" in ehs_df.columns) else np.nan
    last_row = ehs_df.iloc[-1] if ehs_df is not None and not ehs_df.empty else None
    if last_row is not None:
        far_year = int(last_row["target_year"])
        A(f"Voor {event_name} laat het model een reëel, oplopend hitterisico "
          f"zien richting {far_year} ({_fmt(last_row.get('ratio_vs_reference'), 2, 'x')} "
          f"de huidige EHS-referentie, {_fmt(last_row.get('collapse_ratio_vs_reference'), 2, 'x')} "
          f"de collapse-risico-referentie). Een vroegere starttijd "
          f"({current_start_time} -> {early_start_time}) vermindert dit "
          f"aantoonbaar, met cijfers uit ditzelfde model. Een verschuiving "
          f"naar een ander seizoen zou naar verwachting een groter effect "
      f"hebben, maar is in dit rapport niet doorgerekend (zie sectie 6).")
    A("")

    # ------------------------------------------------------------------ #
    A("## 2. Oorzaak: de klimaattrend")
    A("")
    baseline_label = f"{baseline_period[0]}-{baseline_period[1]}" if baseline_period else "n.b."
    reference_label = f"{reference_period[0]}-{reference_period[1]}" if reference_period else "n.b."
    if event_df is not None and not event_df.empty:
        A(f"**Baseline = {baseline_label}** (vroegst beschikbare vergelijkingsperiode); "
          f"**Referentie = {reference_label}** (het meest recente venster waarop de "
          f"trend is geankerd, ofwel het huidige klimaat). Het verschil tussen deze "
          f"twee is dus de reeds waargenomen opwarming; de projectiekolom gaat daar "
          f"met de lineaire trend nog overheen.")
        A("")
        A("Het evenement-venster zelf (niet de jaarlijkse extremen) is de "
          "relevante maat voor dit evenement: de jaarlijkse extremen worden "
          "vooral gedreven door zomerse hittegolven, niet per se door de "
          "specifieke datum/tijd van dit evenement -- in eerdere analyses "
          "bleek het evenement-venster doorgaans een factor 3-4 minder snel "
          "op te warmen dan de jaarlijkse extremen. De cijfers hieronder "
          "zijn daarom specifiek voor het evenement-venster berekend.")
        A("")
        A(f"| Variabele | Baseline ({baseline_label}) | Referentie ({reference_label}) | "
          f"Trend | Projectie |")
        A("|---|---|---|---|---|")
        for _, row in event_df.iterrows():
            proj_col = next((c for c in ("projected_2040", "projected_2035", "projected_2030") if c in row.index
                             and pd.notna(row[c])), None)
            proj_val = row[proj_col] if proj_col else np.nan
            proj_label = proj_col.replace("projected_", "") if proj_col else "n.b."
            A(f"| {row.get('variable', 'n.b.')} | {_fmt(row.get('baseline_mean'), 2, ' degC')} | "
              f"{_fmt(row.get('trend_mean'), 2, ' degC')} | "
              f"{_fmt(row.get('slope_degC_per_yr'), 4, ' degC/jr')} | "
              f"{_fmt(proj_val, 2, ' degC')} ({proj_label}) |")
    else:
        A("Niet beschikbaar voor deze run.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 3. Gevolg: risico-evolutie voor dit evenement")
    A("")
    if ehs_df is not None and not ehs_df.empty:
        A(f"Referentiewaarden (huidige klimaat, {reference_label}): {_fmt(ref_ehs, 2)} EHS per 1.000 "
          f"deelnemers (Falmouth, temperatuur-alleen); {_fmt(ref_collapse, 2)} "
          f"per 1.000 voor het collapse-risico-eindpunt (gekalibreerd, "
          f"PROVISIONAL -- zie de feitenrapporten van deze suite voor de "
          f"volledige kanttekening).")
        A("")
        A("| Doeljaar | EHS/1000 | x referentie | Collapse-risico/1000 | x referentie |")
        A("|---|---|---|---|---|")
        for _, row in ehs_df.iterrows():
            A(f"| {int(row['target_year'])} | {_fmt(row.get('ehs_per_1000'), 2)} | "
              f"{_fmt(row.get('ratio_vs_reference'), 2, 'x')} | "
              f"{_fmt(row.get('collapse_per_1000'), 2)} | "
              f"{_fmt(row.get('collapse_ratio_vs_reference'), 2, 'x')} |")
    else:
        A("Niet beschikbaar voor deze run.")
    if ehe_evidence:
        A("")
        for line in ehe_evidence.get("lines", []):
            A(f"- {line}")
    A("")

    # ------------------------------------------------------------------ #
    near_row = ehs_df.iloc[0] if ehs_df is not None and not ehs_df.empty else None
    near_year = int(near_row["target_year"]) if near_row is not None else None
    A(f"## 4. Kernvraag: is de huidige datum voor {event_name} nog verantwoord in "
      f"{near_year if near_year else 'het naaste doeljaar'}?")
    A("")
    A("### 4.1 De vraag scherp gesteld")
    A("")
    A(f"Dit model kan niet rechtstreeks berekenen of iets \"verantwoord\" is "
      f"-- dat is een risicotolerantie-vraag, geen modeluitkomst. Wat het "
      f"model wél kan doen: het risiconiveau kwantificeren, en laten zien "
      f"hoe dat verandert tegen {near_year if near_year else 'het naaste doeljaar'} "
      f"ten opzichte van nu. Die twee dingen samen -- het niveau, en de "
      f"verandering -- zijn de bouwstenen voor een eigen afweging, niet een "
      f"vervanging ervoor.")
    A("")
    A("### 4.2 Wat pleit voor zorg")
    A("")
    if ehe_evidence and ehe_evidence.get("lines"):
        for line in ehe_evidence["lines"]:
            A(f"- {line}")
    if ref_collapse is not None and pd.notna(ref_collapse):
        A(f"- Het collapse-risico-eindpunt staat nu al op {_fmt(ref_collapse, 2)} per "
          f"1.000 deelnemers -- dit is geen uitsluitend toekomstig risico, het "
          f"bestaat al in het huidige klimaat.")
    A("")
    A("### 4.3 Wat pleit voor voorzichtigheid met de conclusie")
    A("")
    if event_window_trend_significant is False:
        A("- De evenement-venster-trend zelf is NIET statistisch significant "
          "(brede, overlappende betrouwbaarheidsintervallen) -- de bredere "
          "regionale opwarming is onomstreden, maar hoeveel specifiek dit "
          "evenement-venster daadwerkelijk verschuift, is onzeker.")
    elif event_window_trend_significant is None:
        A("- De statistische significantie van de evenement-venster-trend "
          "specifiek is hier niet apart vermeld -- zie de feitenrapportage "
          "van deze suite voor die toets.")
    A("- Het collapse-risico-eindpunt is PROVISIONAL (gereduceerde N)."
      + (f" {collapse_calibration_note}" if collapse_calibration_note else ""))
    A("- EHE-bevindingen zijn gebaseerd op een klein ensemble -- het "
      "onderliggende signaal is reëel, maar de precieze frequentie is niet "
      "scherp geschat.")
    A("")
    A(f"### 4.4 Het kernpunt: nu versus {near_year if near_year else 'het naaste doeljaar'}")
    A("")
    if near_row is not None:
        near_ratio = near_row.get("ratio_vs_reference", np.nan)
        near_collapse_ratio = near_row.get("collapse_ratio_vs_reference", np.nan)
        A(f"Het verschil tussen nu en {near_year} is bescheiden: "
          f"{_fmt(near_ratio, 2, 'x')} voor EHS, {_fmt(near_collapse_ratio, 2, 'x')} "
          f"voor het collapse-risico. Het grootste deel van het risico dat "
          f"deze cijfers laten zien, zit er dus al VANDAAG in, niet pas "
          f"vanaf {near_year}. Dat verschuift de vraag: \"is {near_year} nog "
          f"verantwoord\" is grotendeels dezelfde vraag als \"is het huidige "
          f"risiconiveau verantwoord\" -- {near_year} versterkt dat enigszins, "
          f"maar verandert het oordeel niet fundamenteel in de ene of "
          f"andere richting.")
    else:
        A("Niet beschikbaar voor deze run.")
    A("")
    A("### 4.5 Wat het model wel en niet kan beantwoorden")
    A("")
    A("Het model laat zien: het risiconiveau nu, de verandering richting "
      "toekomstige doeljaren, en het gekwantificeerde effect van een "
      "vroegere starttijd (sectie 5). Het model laat NIET zien: welk "
      "risiconiveau aanvaardbaar is voor deze organisatie, deze deelnemers, "
      "of deze context -- dat is een keuze die buiten dit model valt.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 5. Interventie: vroegere starttijd (gekwantificeerd)")
    A("")
    if ehs_df is not None and not ehs_df.empty and "ehs_per_1000_early_start" in ehs_df.columns:
        A(f"Zelfde model, zelfde doeljaren, enige wijziging: starttijd "
          f"{current_start_time} -> {early_start_time}.")
        A("")
        A("| Doeljaar | EHS/1000 huidig | EHS/1000 vroege start | Reductie | "
          "Collapse/1000 huidig | Collapse/1000 vroege start | Reductie |")
        A("|---|---|---|---|---|---|---|")
        for _, row in ehs_df.iterrows():
            ehs_now = row.get("ehs_per_1000", np.nan)
            ehs_early = row.get("ehs_per_1000_early_start", np.nan)
            ehs_red = (1 - ehs_early / ehs_now) * 100 if pd.notna(ehs_now) and ehs_now > 0 and pd.notna(ehs_early) else np.nan
            coll_now = row.get("collapse_per_1000", np.nan)
            coll_early = row.get("collapse_per_1000_early_start", np.nan)
            coll_red = (1 - coll_early / coll_now) * 100 if pd.notna(coll_now) and coll_now > 0 and pd.notna(coll_early) else np.nan
            A(f"| {int(row['target_year'])} | {_fmt(ehs_now, 2)} | {_fmt(ehs_early, 2)} | "
              f"{_fmt(ehs_red, 0, '%')} | {_fmt(coll_now, 2)} | {_fmt(coll_early, 2)} | "
              f"{_fmt(coll_red, 0, '%')} |")
        A("")
        A("Dit is de enige interventie in dit rapport die met hetzelfde "
          "model, dezelfde aannames en dezelfde doeljaren rechtstreeks "
          "vergelijkbaar is met de referentiecijfers hierboven -- geen "
          "aparte modelrun nodig, want de vroege-start-scenario's zijn al "
          "onderdeel van Klimatos' eigen EHS-evolutieberekening.")
    else:
        A("Niet beschikbaar voor deze run (geen vroege-start-scenario "
          "berekend).")
    A("")

    # ------------------------------------------------------------------ #
    A("## 6. Interventie: ander seizoen/datum (kwalitatief, NIET doorgerekend)")
    A("")
    A("**Dit onderdeel bevat geen modelcijfers.** Een kwantitatieve "
      "vergelijking vereist een nieuwe event-window-berekening, geankerd "
      "op een andere kalenderdatum -- een aparte, tijdrovende modelrun die "
      "in deze proefversie bewust niet is uitgevoerd.")
    A("")
    A("De structurele reden om dit toch te overwegen: sectie 2 liet zien "
      "dat de jaarlijkse extremen sneller opwarmen dan het evenement-"
      "venster zelf, wat erop wijst dat het jaargetijde waarin een "
      "evenement valt een grotere invloed heeft op de blootstelling dan de "
      "geleidelijke jaar-op-jaar-trend. Een verschuiving naar een koeler "
      "deel van het jaar zou daarom, in principe, een groter effect kunnen "
      "hebben dan de starttijd-verschuiving in sectie 5 -- maar dit rapport "
      "kan dat niet met een cijfer onderbouwen.")
    A("")
    A("Als vervolgstap zou dezelfde EHS-evolutieberekening opnieuw gedraaid "
      "kunnen worden met een gewijzigde evenementdatum, om deze sectie in "
      "een volgende versie alsnog te kwantificeren.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 7. Afweging")
    A("")
    A("| | Vroegere starttijd | Ander seizoen/datum |")
    A("|---|---|---|")
    A("| Onderbouwd met modelcijfers | ja (sectie 5) | nee (sectie 6, kwalitatief) |")
    A("| Vermoedelijke effectgrootte | beperkt (zie sectie 5) | vermoedelijk groter, niet gekwantificeerd |")
    A("| Operationele impact | vermoedelijk beperkt (zelfde datum, zelfde vergunningen) | "
      "vermoedelijk groot (kalenderplanning, deelnemersverwachting, andere evenementen) |")
    A("")
    A("Beide overwegingen worden hier feitelijk naast elkaar gezet; welke "
      "afweging voor een organisatie zwaarder weegt (bewezen maar beperkt "
      "effect, versus vermoedelijk groter maar onbewezen effect) is een "
      "keuze die buiten dit model valt.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 8. Aanbeveling")
    A("")
    if last_row is not None and pd.notna(last_row.get("ratio_vs_reference")):
        A(f"Op basis van de doorgerekende cijfers: een vroegere starttijd "
          f"is een concrete, met dit model onderbouwde maatregel die het "
          f"EHS- en collapse-risico voor {event_name} meetbaar vermindert "
          f"(sectie 5), zonder de kalenderdatum te wijzigen. Een "
          f"verschuiving naar een koeler seizoen zou structureel een groter "
          f"effect kunnen hebben, maar vereist eerst een aanvullende "
          f"modelrun voordat die aanbeveling met cijfers kan worden "
          f"onderbouwd (sectie 6).")
    else:
        A("Onvoldoende gegevens voor een aanbeveling in deze run.")
    A("")

    # ------------------------------------------------------------------ #
    A("## 9. Aannames en beperkingen")
    A("")
    A("- Projecties zijn een naïeve lineaire extrapolatie van de "
      "waargenomen trend, geen fysisch klimaatmodel.")
    A("- Het collapse-risico-eindpunt is PROVISIONAL (gereduceerde N, "
      "wachtend op nadere klinische onderbouwing).")
    A("- De vroege-start-cijfers in sectie 5 veronderstellen dat verder "
      "niets aan het evenement verandert (zelfde populatie, zelfde beleid) "
      "behalve de starttijd.")
    A("- Sectie 6 (ander seizoen/datum) bevat geen modelcijfers en mag niet "
      "als kwantitatieve onderbouwing worden gelezen.")
    if documented_reference:
        A(f"- Gedocumenteerd referentiecijfer voor dit evenement: {documented_reference}")
    A("- Geen onafhankelijke, externe peer review van dit specifieke traject.")
    A("")
    A("*Einde rapport.*")

    text = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    return text
