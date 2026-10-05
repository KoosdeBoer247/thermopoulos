# -*- coding: utf-8 -*-
"""
Run PYROX on Thermopoulos data
================================================================================
The PYROX half of the suite, wired with REAL IMPORTS (no exec, no subprocess).

Pipeline:
    Thermopoulos Excel
        -> thermopoulos_loader.ThermopoulosData.get_heat_load_series()
        -> pyrox_model.PyroxModel.simulate()
        -> per-group strain trajectories and intervention-zone days

Usage (programmatic):
    from thermopoulos_loader import ThermopoulosData, find_latest_thermopoulos_file
    from run_pyrox import assess_population

    data = ThermopoulosData(find_latest_thermopoulos_file())
    report = assess_population(data, sheet="Forecast_7d",
                               group_names=["adults_18_45", "very_elderly_85plus"])

Usage (script):
    python run_pyrox.py            # uses newest Thermopoulos_*.xlsx in cwd
"""

from __future__ import annotations

from typing import List, Dict, Optional

import pandas as pd

from thermopoulos_loader import ThermopoulosData, find_latest_thermopoulos_file
from pyrox_model import PyroxModel
from pyrox_groups import TARGET_GROUPS, PAPER_PROTOTYPES


def _select_data_sheet(data: ThermopoulosData) -> str:
    """Choose the PYROX input sheet, with explicit support for Historical_Custom.

    If the Thermopoulos Data Engine supplied a custom historical period, show its
    exact available interval and offer it as the first choice. The selected sheet
    is then passed unchanged to assess_population().
    """
    if "Historical_Custom" in data.available_sheets:
        try:
            info = data.sheet_period("Historical_Custom")
            hist = data._load_sheet("Historical_Custom")
            if len(hist):
                start = info["start"]
                end = info["end"]
                print("\nHistorical_Custom gevonden in Thermopoulos Data Engine.")
                print(f"  Beschikbaar: {start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M} "
                      f"({len(hist)} uur)")
                print("  Dit is het door jou opgegeven historische tijdvak; er wordt niets opnieuw opgehaald.")
                try:
                    answer = input("Gebruik dit historische tijdvak voor PYROX? [Y/n]: ").strip().lower()
                except EOFError:
                    answer = "y"
                if answer not in ("n", "no"):
                    return "Historical_Custom"
        except Exception as exc:
            print(f"  Waarschuwing: Historical_Custom kon niet worden gelezen ({exc}).")

    choices = [s for s in ("Forecast_7d", "Hindcast_14d") if s in data.available_sheets]
    if not choices:
        choices = list(data.available_sheets)
    print("\nBeschikbare PYROX-datasets:")
    for i, name in enumerate(choices, 1):
        try:
            info = data.sheet_period(name)
            interval = f"{info['start']:%Y-%m-%d %H:%M} -> {info['end']:%Y-%m-%d %H:%M}"
        except Exception:
            interval = "periode onbekend"
        print(f"  {i}. {name:<18} {interval}")
    if not choices:
        raise ValueError("Geen bruikbare Thermopoulos-dataset gevonden.")
    try:
        answer = input(f"Kies dataset (1-{len(choices)}, ENTER = 1): ").strip()
    except EOFError:
        answer = ""
    idx = int(answer) - 1 if answer.isdigit() and 1 <= int(answer) <= len(choices) else 0
    return choices[idx]


def assess_population(data: ThermopoulosData,
                      sheet: str = "Forecast_7d",
                      group_names: Optional[List[str]] = None,
                      pre_heatwave_heat_load: Optional[float] = None,
                      sleep_quality_series: Optional[List[float]] = None,
                      use_nocturnal_recovery: bool = False) -> Dict:
    """Run PYROX for a set of population groups on one Thermopoulos sheet.

    Parameters
    ----------
    data : ThermopoulosData
        An initialised loader.
    sheet : str
        Which data sheet to use (e.g. 'Forecast_7d', 'Hindcast_14d').
    group_names : list of str, optional
        Which groups to assess. Defaults to the three paper prototypes.
    pre_heatwave_heat_load : float, optional
        Baseline load the population is acclimatized to at the start (thermal-
        equilibrium initial condition). Defaults to the first day's load.
    sleep_quality_series : list of float, optional
        Per-day sleep quality in (0, 1]. Defaults to ideal (1.0) every day.
    use_nocturnal_recovery : bool, optional
        If True and no explicit sleep_quality_series is given, derive one from
        the night's minimum temperature (warm nights blunt recovery). OFF by
        default, so the baseline calibration/validation is unchanged.

    Returns
    -------
    dict
        {
          'city', 'sheet', 'dates', 'heat_loads',
          'groups': { group_name: simulate()-result-dict, ... }
        }
    """
    if group_names is None:
        group_names = list(PAPER_PROTOTYPES)

    daily = data.get_daily_heat_loads(sheet)
    heat_loads = daily["baseline_heat_load"].tolist()
    dates = [str(d) for d in daily["date"].tolist()]

    # optional nocturnal-recovery refinement (off by default)
    if sleep_quality_series is None and use_nocturnal_recovery:
        sleep_quality_series = data.sleep_quality_series(daily)

    results = {}
    for name in group_names:
        if name not in TARGET_GROUPS:
            raise KeyError(f"Unknown group '{name}'. "
                           f"Known: {sorted(TARGET_GROUPS)}")
        model = PyroxModel(TARGET_GROUPS[name])
        results[name] = model.simulate(
            heat_loads,
            sleep_quality_series=sleep_quality_series,
            pre_heatwave_heat_load=pre_heatwave_heat_load,
        )

    return {
        "city": data.city,
        "sheet": sheet,
        "dates": dates,
        "heat_loads": heat_loads,
        "groups": results,
    }


def print_report(report: Dict) -> None:
    """Human-readable summary of an assess_population result."""
    print(f"\nPYROX population heat-risk — {report['city']} ({report['sheet']})")
    print(f"Days: {len(report['heat_loads'])}, "
          f"baseline heat loads: "
          f"{', '.join(f'{x:.2f}' for x in report['heat_loads'])}")
    print(f"\n{'group':<30}{'peak strain':>12}{'critical':>9}"
          f"{'caution':>9}{'danger':>8}{'emerg':>7}")
    print("-" * 75)
    for name, res in report["groups"].items():
        print(f"{res['group'].display_name:<30}"
              f"{res['peak_strain']:>12.3f}{res['critical_strain']:>9.1f}"
              f"{str(res['caution_day']):>9}{str(res['danger_day']):>8}"
              f"{str(res['emergency_day']):>7}")


def _select_groups() -> List[str]:
    """Console menu for picking which PYROX groups to assess.

    [2026-09] Previously main() always ran every group in TARGET_GROUPS with
    no way to pick a subset from the console -- assess_population() itself
    already supported a group_names argument (used programmatically, e.g. by
    generate_event_report.py), just nothing in the interactive script path
    exposed it.
    """
    names = sorted(TARGET_GROUPS)
    print("\nAvailable PYROX groups:")
    for i, name in enumerate(names, 1):
        grp = TARGET_GROUPS[name]
        star = "*" if name in PAPER_PROTOTYPES else " "
        print(f"  {i:2d}. {star} {grp.display_name:<38} "
              f"[{grp.evidence_status}]")
    print("     (* = paper-specified group; others are extrapolated -- "
          "see pyrox_groups.py's own header for what that means)")
    print("\nKies groepen: nummers gescheiden door komma's, 'all' voor alle "
          f"{len(names)}, of leeg voor de {len(PAPER_PROTOTYPES)} "
          "paper-groepen.")
    try:
        answer = input("Groepen: ").strip().lower()
    except EOFError:
        answer = ""

    if answer == "":
        return list(PAPER_PROTOTYPES)
    if answer == "all":
        return names

    selected = []
    for part in answer.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            idx = int(part)
            if 1 <= idx <= len(names):
                selected.append(names[idx - 1])
            else:
                print(f"  (genegeerd: {part} valt buiten 1-{len(names)})")
        except ValueError:
            print(f"  (genegeerd: '{part}' is geen geldig nummer)")
    if not selected:
        print(f"  (geen geldige keuzes -- terugvallen op de "
              f"{len(PAPER_PROTOTYPES)} paper-groepen)")
        return list(PAPER_PROTOTYPES)
    return selected


def main():
    latest = find_latest_thermopoulos_file()
    if latest is None:
        print("No Thermopoulos_*.xlsx found. Run the Thermopoulos Data Engine first.")
        return 1
    data = ThermopoulosData(latest)
    sheet = _select_data_sheet(data)
    selected_groups = _select_groups()
    report = assess_population(data, sheet=sheet, group_names=selected_groups)
    print_report(report)

    # [2026-08-30] Optional Markdown + Word report, same prompt pattern
    # already used by run_hestia.py and Klimatos_ClimateShift.py's main() --
    # see generate_pyrox_report.py's own docstring for what it covers
    # (all six of pyrox_plots.py's own plots, each with a plain-language
    # caption) and report_to_docx.py's docstring for the shared styling
    # layer all four of this suite's report generators now use.
    try:
        report_answer = input("\nGenerate event report (Markdown)? [y/n, default y]: ").strip().lower()
    except EOFError:
        report_answer = "y"
    if report_answer != "n":
        from datetime import datetime
        from generate_pyrox_report import generate_pyrox_report
        safe_city = "".join(ch for ch in data.city if ch.isalnum() or ch in (" ", "_", "-")).strip()
        report_path = f"PYROX_Rapport_{safe_city}_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
        report_text = generate_pyrox_report(
            event_name=f"{data.city} ({sheet})", pyrox_report=report,
            output_path=report_path,
        )
        print(f"Report written to: {report_path}")

        try:
            docx_answer = input("Also export as Word (.docx)? [y/n, default y]: ").strip().lower()
        except EOFError:
            docx_answer = "y"
        if docx_answer != "n":
            try:
                from report_to_docx import export_report_docx
                docx_path = report_path[:-3] + ".docx"
                export_report_docx(report_text, docx_path, report_kind="facts",
                                   event_name=f"{data.city} ({sheet})")
                print(f"Word report written to: {docx_path}")
            except Exception as e:
                print(f"Word export failed ({e}) -- the Markdown report above is unaffected.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
