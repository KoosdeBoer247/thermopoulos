"""
hestia_console.py -- interactive console of the HESTIA engine (menu, prompts).

Split off from hestia_model.py on 2026-10-25 so that the physics module
contains no interactive input(). Behaviour is unchanged: run
    python hestia_console.py          (or: python hestia_model.py)
Programmatic use goes through hestia_model / run_hestia without prompts.
"""
import hestia_model as _hm
from hestia_model import *  # noqa: F401,F403  (the console uses the engine's public names)
from hestia_model import _format_pct_with_band  # noqa: F401
from hestia_model_plots import (plot_adult_results, plot_pediatric_results,  # noqa: F401
                                plot_adult_boxplots, plot_met_thresholds)


def select_met_activity(activity_dict):
    print("\nChoose an activity:")
    for key, activity in activity_dict.items():
        print(f"{key}. {activity['description']} (MET: {activity['met']})")
    while True:
        try:
            choice = int(input("Enter the activity number: "))
            if choice in activity_dict:
                selected = activity_dict[choice]
                return choice, selected["met"], selected["speed_kmh"] * 1000 / 3600
            print("Invalid choice.")
        except ValueError:
            print("Please enter a valid number.")


def select_clo_value(clo_dict):
    print("\nChoose a clothing option:")
    for key, option in clo_dict.items():
        print(f"{key}. {option['description']} (clo: {option['clo']})")
    while True:
        try:
            choice = int(input("Enter the clothing option number: "))
            if choice in clo_dict:
                return clo_dict[choice]["clo"]
            print("Invalid choice.")
        except ValueError:
            print("Please enter a valid number.")


def select_age_configuration():
    """
    [rev10] NOTE: age_configuration is now only used as a label.
    Age is embedded in each profile from generate_base_population().
    This function is retained for backward compatibility.
    """
    print("\n[rev10] Age distribution is now set in generate_base_population().")
    print("        N(40, 10) clipped [18, 65] -- representative of NL marathon events.")
    return "standard"


def get_adaptation_profile(activity_choice):
    profiles = {
        1: {"name": "Beginner / Not acclimatized",         "training": 0.0,  "acclimatization": 0.0},
        2: {"name": "Low-average / Partially acclimatized","training": 0.25, "acclimatization": 0.3},
        3: {"name": "Average / Well-acclimatized",         "training": 0.5,  "acclimatization": 0.6},
        4: {"name": "Advanced / Fully acclimatized",       "training": 1.0,  "acclimatization": 1.0},
    }
    if activity_choice in [6, 7, 8, 9, 10]:        recommended = 4
    elif activity_choice in [1, 2, 3, 4, 5, 11]:   recommended = 3
    elif activity_choice in [15, 16, 17]:           recommended = 2
    else:                                            recommended = 1

    print(f"\n{Fore.CYAN}Recommended: {profiles[recommended]['name']}{Style.RESET_ALL}")
    while True:
        use = input("Use this profile? (y/n): ").lower().strip()
        if use in ['y', 'yes', '']:
            return profiles[recommended]
        if use in ['n', 'no']:
            for k, v in profiles.items():
                print(f"{k}. {v['name']}")
            while True:
                try:
                    c = int(input("Enter number: "))
                    if c in profiles:
                        return profiles[c]
                    print("Invalid.")
                except ValueError:
                    print("Please enter a valid number.")
        print("Please enter 'y' or 'n'.")


def main():
    """
    Main simulation pipeline.

    [rev10] Population workflow:
    1. User is prompted for population parameters (N, seed).
    2. generate_base_population() creates the fixed population.
    3. validate_population() is called and results printed.
    4. User can optionally save/load the population (.pkl).
    5. run_monte_carlo_adult() uses the fixed population.

    [rev11] Population files now carry a version tag. A mismatch warning is
    printed if a file saved by a different revision is loaded.
    """
    plt.close('all')
    clear_all_caches()
    init(autoreset=True)
    print(f"{Style.BRIGHT}HESTIA: Integrated Thermal Simulation Tool (rev17){Style.RESET_ALL}")
    print(f"{Fore.CYAN}rev17 changes: optional Thermoregulatory Control Failure "
          f"module with Thermal-CVR deficit dose (degC*L).{Style.RESET_ALL}")
    print(f"{Fore.CYAN}rev16 changes: T_rect P97.5/P99 plot lines and a fixed top-2.5% "
          f"vulnerable tail group based on peak T_rect.{Style.RESET_ALL}")
    print(f"{Fore.CYAN}rev15 changes: calibration-uncertainty band for all GHOR percentages "
          f"(pct_decompensation, pct_roberts_kritiek, pct_ehs_postfinish, collapse){Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[rev14] INTERCEPT RECALIBRATION REQUIRED: the K_p distribution and "
          f"post-finish module shift the T_rect distribution. Run intercept_estimation.py "
          f"with a tdb 22->26 degC reference for GHOR reports.{Style.RESET_ALL}")

    try:
        # --- Mode Selection ---
        while True:
            print("\nSelect the simulation mode:")
            print("1. Adults (Thermal Simulation)")
            print("2. Children (Thermal Simulation)")
            print("3. WBGT Calculation (5-day forecast)")
            print("4. Use existing Thermopoulos Excel data")
            sim_mode = input("Enter your choice (1, 2, 3, or 4): ").strip()
            if sim_mode in ['1', '2', '3', '4']:
                sim_mode = ({'1': 'adult', '2': 'child', '3': 'wbgt', '4': 'excel'})[sim_mode]
                break
            print(f"{Fore.RED}Invalid choice.{Style.RESET_ALL}")

        print(f"\n--- Mode selected: {sim_mode.upper()} ---")

        # --- [rev12] Collapse endpoint selection ---
        # The active endpoint determines which intercept_kal is used for the
        # collapse risk model. Default is 'ehs' (most conservative, best documented).
        if sim_mode in ('adult', '1') or True:   # show for all adult sims
            print(f"\n[rev12] Collapse risk endpoint selection:")
            ep_keys = list(COLLAPSE_ENDPOINTS.keys())
            for i, k in enumerate(ep_keys, 1):
                ep = COLLAPSE_ENDPOINTS[k]
                status_color = Fore.GREEN if ep['status'] == 'VALIDATED' else Fore.YELLOW
                print(f"  {i}. {ep['label']}")
                print(f"     P_obs: {ep['p_obs']*10000:.1f}/10.000  |  "
                      f"intercept: {ep['intercept_kal']:.3f}  |  "
                      f"{status_color}{ep['status']}{Style.RESET_ALL}")
            print(f"  (default: 1 = EHS, most conservative)")
            ep_choice = input("Select endpoint (1/2/3, or Enter for default): ").strip()
            if ep_choice in ('2', '3'):
                import builtins
                # Override module-level ACTIVE_ENDPOINT for this session
                import sys
                _chosen_key = ep_keys[int(ep_choice) - 1]
                # Patch module globals for this run
                _hm.ACTIVE_ENDPOINT = _chosen_key
                _hm.P_OBS_COLLAPSE = COLLAPSE_ENDPOINTS[_chosen_key]['p_obs']
                print(f"{Fore.CYAN}[rev12] Active endpoint set to: "
                      f"'{COLLAPSE_ENDPOINTS[_chosen_key]['label']}'{Style.RESET_ALL}")
                if COLLAPSE_ENDPOINTS[_chosen_key]['status'] in ('PROVISIONAL', 'REQUIRES_RECALIBRATION'):
                    print(f"{Fore.YELLOW}[rev12] WARNING: This endpoint is PROVISIONAL. "
                          f"See module docstring for calibration status.{Style.RESET_ALL}")
            else:
                print(f"{Fore.CYAN}[rev12] Using default endpoint: "
                      f"'{COLLAPSE_ENDPOINTS['ehs']['label']}'{Style.RESET_ALL}")

        city_name = input("Enter the city name (e.g., Amsterdam): ")
        lat, lon  = get_lat_lon(city_name)
        if lat is None:
            print(f"{Fore.RED}Could not retrieve coordinates.{Style.RESET_ALL}")
            return

        if sim_mode == 'wbgt':
            apply_uhi  = input("Apply Urban Heat Island (UHI) effect? (y/n): ").lower() == 'y'
            population = int(input("City population: ")) if apply_uhi else None
            calculate_and_export_wbgt(city_name, lat, lon, apply_uhi, population)
            return

        sim_submode = None

        if sim_mode == 'excel':
            excel_file = input("Enter the Thermopoulos Excel filename: ").strip()
            if not os.path.isfile(excel_file):
                print(f"{Fore.RED}File not found.{Style.RESET_ALL}")
                return
            try:
                from openpyxl import load_workbook
                wb     = load_workbook(excel_file, read_only=True)
                sheets = wb.sheetnames
                print("\nAvailable sheets:")
                for i, s in enumerate(sheets, 1):
                    print(f"{i}. {s}")
                sheet_name = sheets[int(input("Select sheet number: ")) - 1]
            except Exception as e:
                print(f"{Fore.YELLOW}Could not list sheets: {e}{Style.RESET_ALL}")
                sheet_name = input("Enter sheet name: ").strip()

            weather_data, tz_str = load_weather_from_thermopoulos_excel(excel_file, sheet_name)
            if weather_data is None:
                _tz = input("Enter timezone (e.g., Europe/Amsterdam), or Enter to stop: ").strip()
                if _tz:
                    weather_data, tz_str = load_weather_from_thermopoulos_excel(excel_file, sheet_name, timezone=_tz)
            if weather_data is None:
                return
            local_timezone = pytz.timezone(tz_str)

            while True:
                sub = input("\nSimulate for (1) Adults or (2) Children? ").strip()
                if sub in ['1', '2']:
                    sim_submode = 'adult' if sub == '1' else 'child'
                    break
                print(f"{Fore.RED}Invalid choice.{Style.RESET_ALL}")

            apply_uhi  = False
            population = None

        else:
            weather_data = get_weather_forecast(lat, lon)
            if not weather_data:
                return

            print("\n--- Raw Weather Forecast Summary ---")
            print("{:<20} {:<10} {:<10} {:<10}".format("Time (UTC)", "Temp (°C)", "RH (%)", "Wind (m/s)"))
            print("-" * 55)
            for entry in weather_data[:5]:
                dt_utc = datetime.fromtimestamp(entry["dt"], tz=UTC)
                print("{:<20} {:<10.1f} {:<10.0f} {:<10.1f}".format(
                    dt_utc.strftime('%Y-%m-%d %H:%M'),
                    entry["main"]["temp"], entry["main"]["humidity"], entry["wind"]["speed"]))
            print("...")

            available_dates = sorted(set([
                pd.Timestamp(datetime.fromtimestamp(e["dt"], tz=UTC)).date()
                for e in weather_data
            ]))
            print("\nAvailable forecast dates:")
            for i, d in enumerate(available_dates):
                print(f"{i+1}. {d.strftime('%Y-%m-%d')}")
            date_choice   = int(input("Choose date number: ")) - 1
            date_str      = available_dates[date_choice].strftime('%Y-%m-%d')
            local_timezone= get_timezone(lat, lon)
            apply_uhi     = input("Apply UHI effect? (y/n): ").lower() == 'y'
            population_uhi= int(input("City population: ")) if apply_uhi else None
            sim_submode   = sim_mode

        # --- Date / time selection ---
        if sim_mode == 'excel':
            available_dates = sorted(set([
                datetime.fromtimestamp(e["dt"], tz=local_timezone).date()
                for e in weather_data
            ]))
            print("\nAvailable dates:")
            for i, d in enumerate(available_dates):
                print(f"{i+1}. {d.strftime('%Y-%m-%d')}")
            date_choice = int(input("Choose date number: ")) - 1
            date_str    = available_dates[date_choice].strftime('%Y-%m-%d')

        print(f"\nDate selected: {date_str}.")
        start_time_str = input("Enter start time (HH:MM): ")
        duration       = float(input("Event duration in hours (e.g., 1.5): "))
        n_simulations  = int(input("Number of simulated participants (e.g., 5000): "))
        use_control_failure = False

        # --- Mode-specific inputs ---
        if sim_submode == 'adult':
            activity_choice, met_value, _ = select_met_activity(MET_ACTIVITIES_ADULT)
            adaptation_profile  = get_adaptation_profile(activity_choice)
            training_factor     = adaptation_profile['training']
            acclimatization_factor = adaptation_profile['acclimatization']
            clo_value           = select_clo_value(CLO_OPTIONS_ADULT)
            age_config          = select_age_configuration()  # [rev10] label only
            if TCF_AVAILABLE:
                tcf_choice = input(
                    "\nRun Thermoregulatory Control Failure module "
                    "(experimental T_rect x CO-deficit dose)? (y/N): "
                ).lower().strip()
                use_control_failure = tcf_choice in ('y', 'yes', 'j', 'ja')
            else:
                print(f"{Fore.YELLOW}Control Failure module not available; "
                      f"extra TCF analysis is skipped.{Style.RESET_ALL}")
        else:
            age_group_choice    = input("Select age group (1: 0-10, 2: 11-20): ")
            age_config          = "0-10" if age_group_choice == '1' else "11-20"
            _, met_value, _     = select_met_activity(MET_ACTIVITIES_CHILD)
            fitness_choice      = input("Fitness level (1: Low, 2: Medium, 3: High): ")
            fitness_factor      = {'1': 0.2, '2': 0.5, '3': 0.8}.get(fitness_choice, 0.5)
            clo_value           = select_clo_value(CLO_OPTIONS_CHILD)

        # --- [rev10] Population generation and validation ---
        base_population = None
        if sim_submode == 'adult':
            # Ask for random seed for reproducibility
            # [2026-10-25] Reproducible by default (seed 42); type 'random' for a fresh draw.
            seed_input = input("\n[rev10] Random seed for the population "
                               "(Enter = 42, reproducible; 'random' = different each run): ").strip()
            random_seed = None if seed_input.lower() == "random" else (int(seed_input) if seed_input else DEFAULT_RANDOM_SEED)

            # Check for existing population file
            pop_file = f"HESTIA_population_N{n_simulations}_seed{random_seed}.pkl"
            if os.path.isfile(pop_file):
                load_existing = input(f"Found existing population file '{pop_file}'. Load it? (y/n): ").lower()
                if load_existing == 'y':
                    base_population = load_population(pop_file)
                    print(f"{Fore.CYAN}Loaded {len(base_population)} profiles from disk.{Style.RESET_ALL}")

            if base_population is None:
                # Generate fresh population
                base_population = generate_base_population(
                    n_simulations         = n_simulations,
                    training_factor       = training_factor,
                    acclimatization_factor= acclimatization_factor,
                    random_seed           = random_seed,
                )
                # Validate
                print("\nRunning population validation...")
                val_result = validate_population(base_population, show_plots=True)
                if not val_result['all_pass']:
                    print(f"{Fore.YELLOW}[rev10] Population validation found issues. "
                          f"Check warnings above before proceeding.{Style.RESET_ALL}")

                # Offer to save
                save_pop = input(f"\nSave population to '{pop_file}' for future use? (y/n): ").lower()
                if save_pop == 'y':
                    save_population(base_population, pop_file)

            n_simulations = len(base_population)

        # --- Weather preparation ---
        start_dt    = pd.Timestamp(f"{date_str} {start_time_str}", tz=local_timezone.zone)
        end_dt      = start_dt + timedelta(hours=duration)
        interp_data = interpolate_weather(weather_data, start_dt, end_dt)

        if apply_uhi and sim_mode != 'excel':
            print(f"\nApplying UHI effect for {city_name}...")
            for entry in interp_data:
                is_daytime   = 6 <= entry["time"].hour < 18
                entry["temp"]+= calculate_uhi_effect(population_uhi, entry["wind"], is_daytime)

        print(f"\nStarting simulation for {n_simulations} participants in {city_name}...")

        if sim_submode == 'adult':
            all_results, stats, results_df = run_monte_carlo_adult(
                interp_data, lat, lon, met_value, clo_value, n_simulations,
                age_config, training_factor, acclimatization_factor,
                use_parallel=True,
                base_population=base_population,   # [rev10]
                random_seed=random_seed,           # [rev10]
                run_control_failure=use_control_failure,  # [rev17]
            )
        else:
            all_results, stats = run_monte_carlo_pediatric(
                interp_data, lat, lon, met_value, clo_value, n_simulations,
                age_config, fitness_factor, use_parallel=True
            )

        if not all_results:
            print("No results were calculated.")
            return

        # --- Excel export ---
        if sim_submode == 'adult' and results_df is not None:
            # Always write to this script's own directory, so
            # HESTIA_TCF_Plots.py always finds the files alongside it.
            _script_dir    = os.path.dirname(os.path.abspath(__file__))
            excel_filename = os.path.join(_script_dir, "HESTIA_Simulation_Results.xlsx")
            ts_filename    = os.path.join(_script_dir, "HESTIA_TCF_Timeseries.xlsx")
            sheet_name     = f"{city_name.replace(' ', '_')}_{start_dt.strftime('%Y-%m-%d')}"
            print(f"\n[INFO] Exporting to '{excel_filename}', sheet '{sheet_name}'...")
            try:
                if os.path.exists(excel_filename):
                    with pd.ExcelWriter(excel_filename, engine='openpyxl', mode='a',
                                        if_sheet_exists='replace') as writer:
                        results_df.to_excel(writer, sheet_name=sheet_name, index=False)
                else:
                    with pd.ExcelWriter(excel_filename, engine='openpyxl', mode='w') as writer:
                        results_df.to_excel(writer, sheet_name=sheet_name, index=False)
                print(f"{Fore.GREEN}[SUCCESS] Exported {len(results_df)} participants.{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}[ERROR] Excel export failed: {e}{Style.RESET_ALL}")

            try:
                import importlib.util as _ilu
                _ts_mod_path = os.path.join(_script_dir, "HESTIA_TCF_Timeseries_Export.py")
                _spec = _ilu.spec_from_file_location("HESTIA_TCF_Timeseries_Export", _ts_mod_path)
                _ts_mod = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_ts_mod)
                _ts_mod.export_tcf_timeseries(
                    all_results, results_df, sheet_name,
                    output_path=ts_filename,
                )
            except Exception as e_ts:
                print(f"{Fore.YELLOW}[WAARSCHUWING] Timeseries export mislukt: {e_ts}{Style.RESET_ALL}")

        # --- Environmental data summary ---
        print("\n--- Interpolated Environmental Data Used in Simulation ---")
        print("{:<20} {:<10} {:<10} {:<15} {:<10} {:<10}".format(
            "Time", "Temp (°C)", "RH (%)", "TWB (°C)", "Wind (m/s)", "MRT (°C)"))
        print("-" * 80)
        first_sim = all_results[0]
        for i, entry in enumerate(interp_data):
            print("{:<20} {:<10.1f} {:<10.0f} {:<15.1f} {:<10.1f} {:<10.1f}".format(
                entry["time"].strftime('%Y-%m-%d %H:%M'),
                entry["temp"], entry["rh"], entry["twb"],
                entry["wind"], first_sim[i]['mrt'],
            ))

        # --- Results display ---
        if sim_submode == 'adult':
            print(f"\n=== Adult Risk Classification Summary (95th Percentile + T_rect Tail) ===")
            print("{:<20} {:<10} {:<10} {:<15} {:<15} {:<10} {:<40}".format(
                "Time", "UTCI", "WBGT", "T_rect(95%)", "T_rect(97.5%)", "RPE(95%)", "Overall Risk"))
            print("-" * 122)
            for i, r_point in enumerate(all_results[0]):
                risk = calculate_adult_risk_classification(
                    r_point['utci'], r_point['wbgt'],
                    stats['upper_t_rect'][i], stats['upper_rpe'][i])
                t975 = stats.get('t_rect_p975', stats['upper_t_rect'])[i]
                print(f"{r_point['time']:<20} {r_point['utci']:<10.2f} {r_point['wbgt']:<10.2f} "
                      f"{stats['upper_t_rect'][i]:<15.2f} {t975:<15.2f} "
                      f"{stats['upper_rpe'][i]:<10.2f} "
                      f"{risk['risk_color']}{risk['detailed_risk']}")

            print(f"\n=== Core Temperature Risk Threshold Analysis (T_rect) ===")
            thresholds = sorted([float(k) for k in stats['temp_threshold_stats'].keys()])
            header = "{:<20}".format("Time") + "".join(
                [" {:<25}".format(f"% > {t}°C (95% CI)") for t in thresholds])
            print(header)
            print("-" * len(header))
            for i, r_point in enumerate(all_results[0]):
                row = "{:<20}".format(r_point['time'])
                for t in thresholds:
                    t_str = f"{t:.1f}"
                    m  = stats['temp_threshold_stats'][t_str]['mean'][i]
                    lo = stats['temp_threshold_stats'][t_str]['ci_lower'][i]
                    hi = stats['temp_threshold_stats'][t_str]['ci_upper'][i]
                    row += " {:<25}".format(f"{m:8.4f} ({lo:8.4f}-{hi:8.4f})")
                print(row)

            if 'vulnerable_tail_n' in stats:
                print(f"\n=== Vulnerable Tail Cohort (top 2.5% by peak T_rect) ===")
                print(f"Participants: {stats['vulnerable_tail_n']} "
                      f"({stats['vulnerable_tail_pct_actual']:.2f}% of simulation)")
                print(f"Peak T_rect cutoff: {stats['vulnerable_tail_peak_cutoff']:.2f} °C")
                print(f"Mean age: {stats['vulnerable_tail_age_mean']:.1f} y | "
                      f"Mean VO2max: {stats['vulnerable_tail_vo2max_mean']:.1f} mL/kg/min | "
                      f"Mean K_p: {stats['vulnerable_tail_kp_mean']:.3f} MET/°C | "
                      f"NSAID flag (no model effect): {stats['vulnerable_tail_nsaid_pct']:.1f}%")
                if 'vulnerable_tail_co_reserve_min_p50' in stats:
                    print(f"Tail CO reserve min P50/P05: "
                          f"{stats['vulnerable_tail_co_reserve_min_p50']:.2f} / "
                          f"{stats['vulnerable_tail_co_reserve_min_p05']:.2f} L/min | "
                          f"Tail dehydration P50/P95: "
                          f"{stats['vulnerable_tail_dehy_pct_p50']:.2f}% / "
                          f"{stats['vulnerable_tail_dehy_pct_p95']:.2f}%")

            plot_adult_results(all_results, stats, city_name, start_dt, duration)
            if results_df is not None:
                plot_adult_boxplots(results_df)

            if CVR_AVAILABLE and 'hr_peak_p50' in stats:
                # [rev12] Print active endpoint before CVR summary for traceability
                if 'active_endpoint_label' in stats:
                    ep_status = stats['active_endpoint_status']
                    ep_color  = Fore.GREEN if ep_status == 'VALIDATED' else Fore.YELLOW
                    print(f"\n{'='*72}")
                    print(f"[rev12] COLLAPSE RISK MODEL -- ACTIVE ENDPOINT")
                    print(f"  Endpoint : {stats['active_endpoint_label']}")
                    print(f"  Status   : {ep_color}{ep_status}{Style.RESET_ALL}")
                    print(f"  P_obs    : {stats['active_endpoint_p_obs']*10000:.1f} / 10.000")
                    print(f"  Intercept: {stats['collapse_intercept_kal']:.3f}")
                    print(f"  Source   : {stats['active_endpoint_source']}")
                    if ep_status in ('PROVISIONAL', 'REQUIRES_RECALIBRATION'):
                        print(f"  {Fore.YELLOW}NOTE: Recalibration required after the rev14 "
                              f"K_p distribution (A) and post-finish module (C) changes. "
                              f"Run intercept_estimation.py with tdb 22->26degC.{Style.RESET_ALL}")
                    print(f"{'='*72}")

                # [rev14] GHOR OPERATIONAL SUMMARY
                print(f"\n{'='*72}")
                print(f"[rev14] GHOR OPERATIONAL SUMMARY")
                print(f"{'='*72}")

                # A -- K_p population
                if 'kp_mean' in stats:
                    print(f"\n  [A] POPULATION PACING RESPONSIVENESS")
                    print(f"      K_p mean             : {stats['kp_mean']:.3f} MET/°C")
                    print(f"      K_p P5               : {stats['kp_p05']:.3f} MET/°C")
                    pct_km = stats['pct_kp_onder_002']
                    km_col = Fore.RED if pct_km > 5 else Fore.YELLOW if pct_km > 2 else Fore.GREEN
                    # [rev15] No intercept sensitivity for K_p (it is sampled independently);
                    # report as point estimate with MC note.
                    print(f"      % K_p < 0.02 (overmotivated): "
                          f"{km_col}{pct_km:.1f}%{Style.RESET_ALL}  "
                          f"[MC sample; N={n_simulations}]")
                    print(f"      % NSAID use          : {stats.get('pct_nsaid', 0):.1f}%")
                    if pct_km > 3:
                        print(f"      {Fore.YELLOW}ATTENTION: {pct_km:.1f}% of the population does not "
                              f"pace down under thermal overload. Increased "
                              f"finish-zone surveillance recommended.{Style.RESET_ALL}")

                # B — AUC clinical (Roberts)
                if 'auc_klinisch_p95' in stats:
                    print(f"\n  [B] THERMAL DOSE (Roberts 2007, threshold 60 degree-min)")
                    print(f"      AUC_klinisch P50     : {stats['auc_klinisch_p50']:.2f} degC*min")
                    print(f"      AUC_klinisch P95     : {stats['auc_klinisch_p95']:.2f} degC*min")
                    print(f"      AUC total P95        : {stats['auc_klinisch_totaal_p95']:.2f} degC*min")
                    pct_rob = stats['pct_roberts_kritiek']
                    rob_col = Fore.RED if pct_rob > 1 else Fore.YELLOW if pct_rob > 0.1 else Fore.GREEN
                    # [rev15] Calibration uncertainty band
                    rob_lo  = stats.get('pct_roberts_kritiek_lo', pct_rob)
                    rob_hi  = stats.get('pct_roberts_kritiek_hi', pct_rob)
                    rob_str = _format_pct_with_band(pct_rob, rob_lo, rob_hi)
                    print(f"      % above Roberts threshold: "
                          f"{rob_col}{rob_str}{Style.RESET_ALL}")
                    print(f"      [rev15] Band = calibration uncertainty, intercept +/-0.5; "
                          f"not a classical 95% CI")
                    if pct_rob > 0.5:
                        print(f"      {Fore.RED}CRITICAL: >0.5% of population exceeds 60 degree-min. "
                              f"Cooling within 5-10 min after collapse is essential.{Style.RESET_ALL}")

                # C — Post-finish
                if 'pct_ehs_postfinish' in stats:
                    print(f"\n  [C] POST-FINISH RISK ZONE (30 min after finish)")
                    pct_pf = stats['pct_ehs_postfinish']
                    pf_col = Fore.RED if pct_pf > 0.5 else Fore.YELLOW if pct_pf > 0.1 else Fore.GREEN
                    # [rev15] Calibration uncertainty band
                    pf_lo  = stats.get('pct_ehs_postfinish_lo', pct_pf)
                    pf_hi  = stats.get('pct_ehs_postfinish_hi', pct_pf)
                    pf_str = _format_pct_with_band(pct_pf, pf_lo, pf_hi)
                    print(f"      % EHS post-finish    : "
                          f"{pf_col}{pf_str}{Style.RESET_ALL}")
                    print(f"      T_rect peak PF P95   : {stats['t_rect_pf_p95']:.2f}degC")
                    # [2026-10-20 late] EAC-staan (collapse on standing after the finish)
                    if stats.get('eac_buiten_bereik'):
                        print(f"      EAC per 1000         : {Fore.RED}zeer hoog (WBGT "
                              f"{stats['wbgt_race_max_p50']:.1f} > {EAC_WBGT_VALID_MAX:.0f} degC, "
                              f"no field data, no number){Style.RESET_ALL}")
                    elif 'eac_per_1000' in stats:
                        print(f"      EAC per 1000         : {stats['eac_per_1000']:.2f}  "
                              f"(provisional: calibrated at one reference point, not validated)")
                    print(f"      [rev15] Band = calibration uncertainty, intercept +/-0.5")
                    if pct_pf > 0.1:
                        print(f"      {Fore.YELLOW}ATTENTION: increased medical staffing "
                              f"in the finish zone recommended (first 10 min after finish).{Style.RESET_ALL}")

                # D -- Thermoregulatory Control Failure (experimental)
                if 'control_failure_dose_p95' in stats:
                    print(f"\n  [D] THERMOREGULATORY CONTROL FAILURE "
                          f"(experimental mechanistic metric)")
                    for line in format_control_failure_summary(stats):
                        print(f"      {line}")
                    pct_tcf_severe = stats.get('pct_control_failure_severe', 0.0)
                    if pct_tcf_severe > 1.0:
                        print(f"      {Fore.RED}CRITICAL: >1% severe control-failure dose. "
                              f"Prioritise finish-zone cooling and rapid triage.{Style.RESET_ALL}")
                    elif stats.get('pct_control_failure_relevant', 0.0) > 1.0:
                        print(f"      {Fore.YELLOW}ATTENTION: relevant TCF dose in a vulnerable "
                              f"subgroup; monitor P95/P99 and the finish zone.{Style.RESET_ALL}")
                print(f"{'='*72}")
                print_cvr_population_summary(
                    stats,
                    start_group_label=city_name,
                    n_participants=n_simulations,
                    edition=str(start_dt.date()),
                )

                # [rev15] CALIBRATION UNCERTAINTY SUMMARY
                # Printed after CVR console output so GHOR readers see the
                # uncertainty context for every percentage above.
                if 'pct_decompensation_lo' in stats:
                    print(f"\n{'='*72}")
                    print(f"[rev15] CALIBRATION UNCERTAINTY BAND (intercept +/-0.5 log-odds)")
                    print(f"{'='*72}")
                    print(f"  Note: the '~lo-hi%' band reflects the uncertainty in the")
                    print(f"  calibration source (Boston->DtD transfer), NOT a classical")
                    print(f"  95% CI. Monte Carlo sampling uncertainty (Wald, N={n_simulations})")
                    print(f"  is NOT the dominant factor here.")
                    print(f"")
                    dec_str = _format_pct_with_band(
                        stats['pct_decompensation'],
                        stats['pct_decompensation_lo'],
                        stats['pct_decompensation_hi'])
                    col_str = _format_pct_with_band(
                        stats['p_collapse_mean'],
                        stats['p_collapse_mean_lo'],
                        stats['p_collapse_mean_hi'])
                    hoog_str = _format_pct_with_band(
                        stats['pct_high_collapse_risk'],
                        stats['pct_high_collapse_risk_lo'],
                        stats['pct_high_collapse_risk_hi'])
                    print(f"  CVR decompensating        : {dec_str}")
                    print(f"  Mean collapse probability: {col_str}")
                    print(f"  % high collapse risk     : {hoog_str}")
                    if 'pct_roberts_kritiek_lo' in stats:
                        rob_str = _format_pct_with_band(
                            stats['pct_roberts_kritiek'],
                            stats['pct_roberts_kritiek_lo'],
                            stats['pct_roberts_kritiek_hi'])
                        print(f"  % above Roberts threshold: {rob_str}")
                    if 'pct_ehs_postfinish_lo' in stats:
                        pf_str = _format_pct_with_band(
                            stats['pct_ehs_postfinish'],
                            stats['pct_ehs_postfinish_lo'],
                            stats['pct_ehs_postfinish_hi'])
                        print(f"  EHS post-finish          : {pf_str}")
                    print(f"")
                    print(f"  Band narrows after clinical calibration (")
                    print(f"  Radboudumc) of the Z-function coefficients W_T1/W_T2/W_C/W_D.")
                    print(f"{'='*72}")

            df_met_analysis = analyze_met_thresholds(interp_data, lat, lon, clo_value)
            plot_met_thresholds(df_met_analysis, met_value)

        else:
            print(f"\n=== Pediatric Risk Classification Summary (95th Percentile) ===")
            print("{:<20} {:<10} {:<10} {:<15} {:<10} {:<15} {:<40}".format(
                "Time", "UTCI", "WBGT", "T_core(95%)", "RPE(95%)", "% First Aid", "Risk"))
            print("-" * 130)
            for i, r_point in enumerate(all_results[0]):
                risk = calculate_pediatric_risk_classification(
                    r_point['utci'], r_point['wbgt'],
                    stats['upper_t_core'][i], stats['upper_rpe'][i])
                print(f"{r_point['time']:<20} {r_point['utci']:<10.2f} {r_point['wbgt']:<10.2f} "
                      f"{stats['upper_t_core'][i]:<15.2f} {stats['upper_rpe'][i]:<10.2f} "
                      f"{stats['percent_first_aid'][i]:<15.1f} "
                      f"{risk['risk_color']}{risk['detailed_risk']}")

            plot_pediatric_results(all_results, stats, city_name, start_dt, duration)

        input("\nPress Enter to close the plot windows and exit.")

    except ValueError as e:
        import traceback
        traceback.print_exc()
        print(f"{Fore.RED}Invalid input error: {e}{Style.RESET_ALL}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"{Fore.RED}An unexpected error occurred: {e}{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
