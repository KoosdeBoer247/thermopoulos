"""
hestia_model_plots.py -- matplotlib figures of the HESTIA engine's own console
(adult / paediatric Monte Carlo summaries, box plots, MET thresholds).

Split off from hestia_model.py on 2026-10-25; code unchanged. The
population/report figures used by the reports live in hestia_plots.py.
"""
from hestia_model import *  # noqa: F401,F403


def plot_adult_results(results, stats, city_name, start_time, duration_hours):
    """
    4-panel plot for adult simulation results.

    The T_rect panel includes P97.5/P99 reference curves and, when available,
    the mean trajectory of the vulnerable tail cohort: the runners whose own
    peak T_rect falls in the highest 2.5% of the Monte Carlo population.
    """
    # [2026-09] Was `results[0]` -- silently assumed every participant's
    # result list is the same length, true before sample_pace existed
    # (everyone shared one duration) but false the moment it doesn't:
    # `results` here is run_monte_carlo_adult()'s UNPADDED return value,
    # so results[0] can be a short-duration participant while stats['mean_
    # t_rect'] etc. were built from the padded (longest-participant-length)
    # arrays inside that function. Reproduced directly: a real run with
    # sample_pace=True crashed here with "x and y must have same first
    # dimension, but have shapes (9,) and (12,)" -- the (9,) came from
    # results[0] happening to be a faster (shorter-duration) participant,
    # not from the actual weather window, which does cover 12 steps. Using
    # the longest result list instead guarantees the same length as the
    # padded stats arrays regardless of which participant results[0]
    # happens to be.
    longest = max(results, key=len)
    times_str = [r["time"] for r in longest]
    times_dt  = [pd.to_datetime(t) for t in times_str]

    fig, axs = plt.subplots(2, 2, figsize=(20, 14), gridspec_kw={'hspace': 0.4, 'wspace': 0.3})
    fig.suptitle(f"Adult Thermal Simulation for {city_name} on {pd.to_datetime(start_time).date()}",
                 fontsize=18, weight='bold')

    ax1 = axs[0, 0]
    ax1.plot(times_dt, stats['mean_t_rect'], 'b-', label='Mean T_rect')
    ax1.fill_between(times_dt, stats['lower_t_rect'], stats['upper_t_rect'],
                     color='blue', alpha=0.2, label='5th-95th Percentile')
    if 't_rect_p975' in stats:
        ax1.plot(times_dt, stats['t_rect_p975'], color='darkorange',
                 linestyle='-.', linewidth=2.0, label='P97.5 T_rect')
    if 't_rect_p99' in stats:
        ax1.plot(times_dt, stats['t_rect_p99'], color='red',
                 linestyle=':', linewidth=2.4, label='P99 T_rect')
    if 'vulnerable_tail_mean_t_rect' in stats:
        tail_label = (
            f"Vulnerable tail mean "
            f"(top {stats.get('vulnerable_tail_pct_actual', 2.5):.1f}% by peak T_rect)"
        )
        ax1.plot(times_dt, stats['vulnerable_tail_mean_t_rect'], color='black',
                 linestyle='-', linewidth=2.6, label=tail_label)
    ax1.axhline(y=39.0, color='gold',       linestyle='--', label='Heat Stress (39°C)')
    ax1.axhline(y=40.0, color='darkorange', linestyle='--', label='Serious Risk (40°C)')
    ax1.axhline(y=42.0, color='red',        linestyle='--', label='Life-threatening (42°C)')
    ax1.axhline(y=43.0, color='black',      linestyle='-',  linewidth=2,
                label='Lethal Limit (43°C, Vanos 2023)')
    ax1.set_title("Core Body Temperature (T_rect)", fontsize=14)
    ax1.set_ylabel("T_rect (°C)", fontsize=12)

    # [2026-09, requested by the author] The mean/percentile/vulnerable-tail lines
    # above are nanmean/nanpercentile over whoever is still running at each
    # clock-time step (see run_monte_carlo_adult() -- sample_pace=True gives
    # each participant their own duration; a finished participant simply has
    # a shorter per-person result list, i.e. their remaining steps are
    # absent, not physically NaN-filled until the padding happens later for
    # the fixed-width arrays used inside that function). That is not a
    # confidence interval over a fixed cohort: the population behind each
    # point shrinks over time, and it shrinks in a biased way (faster,
    # higher-MET, hence hotter participants finish and drop out first),
    # which on its own can make a line fall even though no individual's own
    # T_rect ever did. Plotting how many people are still behind each line
    # turns that hidden confound into a visible axis instead of a silent
    # one. Computed directly from `results` (the ragged, unpadded per-
    # participant list this function already receives) rather than from
    # any array internal to run_monte_carlo_adult, which is out of scope
    # here. The vulnerable-tail count re-derives the same top-2.5%-by-peak-
    # T_rect membership run_monte_carlo_adult uses for stats[
    # 'vulnerable_tail_mean_t_rect'], since that membership mask itself
    # isn't returned in `stats` -- it is the subgroup most visibly affected,
    # since it disproportionately contains early, high-MET finishers.
    n_steps = len(times_dt)
    n_total = len(results)
    active_n_total = np.array([
        sum(1 for res in results if len(res) > i) for i in range(n_steps)
    ])
    ax1b = ax1.twinx()
    ax1b.fill_between(times_dt, 0, active_n_total / n_total * 100,
                       color='gray', alpha=0.10, step=None, zorder=0,
                       label='% deelnemers nog actief (totale populatie)')
    peak_t_rect_per_result = np.array([
        max((r['t_rect'] for r in res if not np.isnan(r['t_rect'])), default=np.nan)
        for res in results
    ])
    if np.any(~np.isnan(peak_t_rect_per_result)):
        tail_cutoff = np.nanpercentile(peak_t_rect_per_result, 97.5)
        tail_mask = peak_t_rect_per_result >= tail_cutoff
        tail_results = [res for res, m in zip(results, tail_mask) if m]
        n_tail = len(tail_results)
        if n_tail > 0:
            active_n_tail = np.array([
                sum(1 for res in tail_results if len(res) > i) for i in range(n_steps)
            ])
            ax1b.plot(times_dt, active_n_tail / n_tail * 100,
                      color='black', linestyle=(0, (1, 1)), linewidth=1.3, alpha=0.55,
                      label='% van de kwetsbare-staartgroep nog actief')
    ax1b.set_ylabel("% deelnemers nog actief", fontsize=10, color='gray')
    ax1b.set_ylim(0, 105)
    ax1b.tick_params(axis='y', labelcolor='gray', labelsize=8)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines1b, labels1b = ax1b.get_legend_handles_labels()
    ax1.legend(lines1 + lines1b, labels1 + labels1b, fontsize=8, loc='upper right')

    ax2 = axs[0, 1]
    ax2.plot(times_dt, stats['mean_rpe'], 'r-', label='Mean RPE')
    ax2.fill_between(times_dt, stats['lower_rpe'], stats['upper_rpe'],
                     color='red', alpha=0.2, label='5th-95th Percentile')
    ax2.axhline(y=17,   color='purple', linestyle=':',  label='Exhaustion (RPE 17)')
    ax2.axhline(y=19.5, color='black',  linestyle='--', label='Stop Threshold (RPE 19.5)')
    ax2.set_title("Rate of Perceived Exertion (Borg 6-20)", fontsize=14)
    ax2.set_ylabel("RPE (6-20)", fontsize=12)
    ax2.set_ylim(6, 20.5)
    ax2.legend()

    ax3  = axs[1, 0]
    # [changed on request] The old panel used two separate y-axes (twinx)
    # for UTCI and WBGT -- this was the source of the matplotlib warning
    # "Axes that are not compatible with tight_layout", and the place
    # where the UTCI display bug occurred (never traced with certainty to
    # a specific cause, despite extensive investigation). Replaced by a
    # single shared axis (everything is in degC, so one scale is correct
    # on the merits, not just simpler): T_air, WBGT, UTCI, MRT.
    t_air_vals = [r["t_air"] for r in longest]
    utci_vals  = [r["utci"]  for r in longest]
    wbgt_vals  = [r["wbgt"]  for r in longest]
    mrt_vals   = [r["mrt"]   for r in longest]
    ax3.plot(times_dt, t_air_vals, color='#0057D9', linewidth=2.2, label='T_air (°C)')
    ax3.plot(times_dt, wbgt_vals,  color='#00A650', linewidth=2.2, label='WBGT (°C)')
    ax3.plot(times_dt, utci_vals,  color='#B300B3', linewidth=2.2, label='UTCI (°C)')
    ax3.plot(times_dt, mrt_vals,   color='#E8580C', linewidth=2.2, label='MRT (°C)')
    ax3.set_ylabel("Temperature (°C)", fontsize=12)
    ax3.set_title("Environmental Thermal Indices", fontsize=14)
    ax3.legend(loc='upper left')

    ax5 = axs[1, 1]
    ax5.plot(times_dt, stats['percent_stopped'],    color='black',     linestyle='--', label='% Stopped')
    ax5.plot(times_dt, stats['percent_first_aid'],       color='magenta',   linestyle='--', label='% screening-vlag (geen EHBO-voorspelling)')
    ax5.plot(times_dt, stats['percent_unliveable'], color='darkviolet',linewidth=2.5,  label='% Unliveable')
    ax5.fill_between(times_dt, 0, stats['percent_unliveable'], color='darkviolet', alpha=0.2)
    ax5.set_title("Percentage of Participants at Risk", fontsize=14)
    ax5.set_ylabel("Participants (%)", fontsize=12)
    ax5.set_ylim(0, 101)
    ax5.legend()

    for ax in axs.flat:
        ax.set_xlabel("Time", fontsize=12)
        ax.grid(True, linestyle='--', alpha=0.6)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.tick_params(axis='x', rotation=45)
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.show(block=False)
    return fig


def plot_pediatric_results(results, stats, city_name, start_time, duration_hours):
    """4-panel plot for pediatric simulation results. Unchanged."""
    times_str = [r["time"] for r in results[0]]
    times_dt  = [pd.to_datetime(t) for t in times_str]
    fig, axs  = plt.subplots(2, 2, figsize=(20, 14), gridspec_kw={'hspace': 0.4, 'wspace': 0.3})
    fig.suptitle(f"Pediatric Thermal Simulation for {city_name} on {pd.to_datetime(start_time).date()}",
                 fontsize=18, weight='bold')

    ax1 = axs[0, 0]
    ax1.plot(times_dt, stats['mean_t_core'], 'b-', label='Mean T_core')
    ax1.fill_between(times_dt, stats['lower_t_core'], stats['upper_t_core'],
                     color='blue', alpha=0.2, label='5th-95th Percentile')
    ax1.axhline(y=38.5, color='gold',       linestyle='--', label='Moderate Stress (38.5°C)')
    ax1.axhline(y=39.2, color='darkorange', linestyle='--', label='High Risk (39.2°C)')
    ax1.set_title("Core Body Temperature (T_core)", fontsize=14)
    ax1.set_ylabel("T_core (°C)", fontsize=12)
    ax1.legend()

    ax2 = axs[0, 1]
    ax2.plot(times_dt, stats['mean_rpe'], 'r-', label='Mean RPE (OMNI 0-10)')
    ax2.fill_between(times_dt, stats['lower_rpe'], stats['upper_rpe'],
                     color='red', alpha=0.2, label='5th-95th Percentile')
    ax2.axhline(y=8.5, color='purple', linestyle=':', label='First Aid (RPE 8.5)')
    ax2.axhline(y=9.5, color='black',  linestyle='--', label='Stop Threshold (RPE 9.5)')
    ax2.set_title("Rate of Perceived Exertion (OMNI 0-10)", fontsize=14)
    ax2.set_ylabel("RPE (0-10)", fontsize=12)
    ax2.set_ylim(0, 10.5)
    ax2.legend()

    ax3 = axs[1, 0]
    t_air_vals = [r["t_air"] for r in results[0]]
    utci_vals  = [r["utci"]  for r in results[0]]
    wbgt_vals  = [r["wbgt"]  for r in results[0]]
    mrt_vals   = [r["mrt"]   for r in results[0]]
    ax3.plot(times_dt, t_air_vals, color='#0057D9', linewidth=2.2, label='T_air (°C)')
    ax3.plot(times_dt, wbgt_vals,  color='#00A650', linewidth=2.2, label='WBGT (°C)')
    ax3.plot(times_dt, utci_vals,  color='#B300B3', linewidth=2.2, label='UTCI (°C)')
    ax3.plot(times_dt, mrt_vals,   color='#E8580C', linewidth=2.2, label='MRT (°C)')
    ax3.set_ylabel("Temperature (°C)", fontsize=12)
    ax3.set_title("Environmental Thermal Indices", fontsize=14)
    ax3.legend(loc='upper left')

    ax5 = axs[1, 1]
    ax5.plot(times_dt, stats['percent_stopped'],   color='black',   label='% Stopped')
    ax5.plot(times_dt, stats['percent_first_aid'], color='magenta', linestyle='--', label='% First Aid')
    ax5.set_title("Percentage of Participants at Risk", fontsize=14)
    ax5.set_ylabel("Participants (%)", fontsize=12)
    ax5.set_ylim(0, 101)
    ax5.legend()

    for ax in axs.flat:
        ax.set_xlabel("Time", fontsize=12)
        ax.grid(True, linestyle='--', alpha=0.6)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.tick_params(axis='x', rotation=45)
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.show(block=False)
    return fig


def plot_adult_boxplots(results_df):
    """Boxplots by age group and gender. Unchanged."""
    if results_df is None or results_df.empty:
        return
    sns.set(style="whitegrid")
    variables = [
        ('max_t_rect',         'Maximum Core Temperature (°C)', [37, 42]),
        ('max_rpe',            'Maximum Perceived Exertion (RPE)', [6, 20]),
        ('max_water_loss_perc','Maximum Water Loss (% body weight)', [0, 5]),
    ]
    fig, axes = plt.subplots(3, 1, figsize=(14, 18))
    fig.suptitle("Distribution of Max Values by Age Group and Gender", fontsize=16)
    for i, (var, title, ylim) in enumerate(variables):
        ax    = axes[i]
        order = sorted(results_df['age_group'].unique())
        sns.boxplot(data=results_df, x='age_group', y=var, hue='gender', ax=ax,
                    palette={"male": "skyblue", "female": "lightpink"},
                    showmeans=True,
                    meanprops={"marker": "o", "markerfacecolor": "white", "markeredgecolor": "black"},
                    order=order)
        ax.set_title(title, fontsize=14)
        ax.set_xlabel("Age Group", fontsize=12)
        ax.set_ylabel(title.split('(')[0].strip(), fontsize=12)
        ax.set_ylim(ylim)
        ax.legend(title="Gender", loc='upper right')
        ax.grid(True, linestyle='--', alpha=0.6)
        sns.stripplot(data=results_df, x='age_group', y=var, hue='gender', ax=ax,
                      dodge=True, jitter=True, alpha=0.4,
                      palette={"male": "blue", "female": "red"}, legend=False, order=order)
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    plt.show(block=False)
    return fig


def plot_met_thresholds(df_met, user_selected_met):
    """Plot permissible MET values by age group. Unchanged."""
    sns.set(style="whitegrid")
    age_groups   = sorted(df_met['age_group'].unique())
    n_groups     = len(age_groups)
    fig, axes    = plt.subplots(n_groups, 1, figsize=(12, 5 * n_groups), sharex=True, sharey=True)
    if n_groups == 1:
        axes = [axes]
    temp_colors  = {39.0: 'blue', 39.5: 'green', 40.0: 'orange', 41.0: 'red'}
    gender_styles= {'male': '-', 'female': '--'}
    for i, age_group in enumerate(age_groups):
        ax       = axes[i]
        df_group = df_met[df_met['age_group'] == age_group]
        for gender in ['male', 'female']:
            df_g = df_group[df_group['gender'] == gender]
            for temp, color in temp_colors.items():
                df_t = df_g[df_g['temp_threshold'] == temp]
                if not df_t.empty:
                    ax.plot(df_t['time'], df_t['permissible_met'],
                            label=f'{gender.capitalize()} < {temp}°C',
                            color=color, linestyle=gender_styles[gender],
                            marker='o', markersize=3)
        ax.axhline(y=user_selected_met, color='black', linestyle=':', linewidth=2.5,
                   label=f'Chosen Activity (MET: {user_selected_met})')
        ax.set_title(f'Permissible Activity Intensity: {age_group}', fontsize=14)
        ax.set_ylabel('MET Value', fontsize=12)
        ax.legend(title="Legend", bbox_to_anchor=(1.02, 1), loc='upper left')
        ax.grid(True, which='both', linestyle='--', linewidth=0.5)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    axes[-1].set_xlabel("Time", fontsize=12)
    plt.ylim(bottom=1)
    fig.suptitle('Analysis of Maximum Permissible MET Values', fontsize=18, weight='bold')
    plt.tight_layout(rect=[0, 0, 0.85, 0.96])
    plt.show()


