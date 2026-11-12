"""
run_all_tests.py -- runs every test script of the suite, one by one, and
prints a summary. [2026-10-17]

Why a runner and not plain pytest: most test scripts are stand-alone scripts
that do their work at import and print their own checks (some take minutes,
because they run JOS-3 Monte Carlo). This runner starts each one in its own
Python process, records the exit code and the time, and ends with one table.

Run:    python run_all_tests.py            (all, ~15-25 min)
        python run_all_tests.py --quick    (skips the slow ones)

First check the dependencies:  pip install -r requirements.txt
"""
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

TESTS = [  # (script, slow?)
    ("verify.py", False),
    ("test_recent_features.py", False),
    ("test_pyrox_report.py", False),
    ("test_fit_lezer.py", False),
    ("test_rate_limit.py", False),
    ("test_uncertainty.py", False),
    ("test_new_modules.py", False),
    ("test_clinic.py", False),
    ("test_nocturnal_recovery.py", False),
    ("test_cv_ceiling.py", False),
    ("test_straling.py", False),
    ("test_leefbaarheid_uren.py", False),
    ("test_koude_huid.py", False),
    ("test_fit_loop.py", False),
    ("test_groep_lopers.py", False),
    ("test_aanmelding.py", False),
    ("test_herladen.py", False),
    ("test_globe_liljegren.py", False),
    ("test_hittegewenning.py", False),
    ("test_wandelaars.py", False),
    ("test_hutas_zweet.py", False),
    ("test_klimatos_bron.py", False),
    ("test_hindcast_gat.py", False),
    ("test_plausibility_2026_10_14.py", True),
    ("test_individual_engine.py", True),
    ("test_loper.py", True),
    ("test_jos3_leeftijd.py", True),
    ("test_zweet_fix.py", True),
    ("test_cvr_freeze_fix.py", True),
    ("test_end_to_end.py", True),
    ("suite_smoke_test.py", True),
]

REQUIRED = ["numpy", "pandas", "scipy", "matplotlib", "seaborn", "pythermalcomfort",
            "pvlib", "timezonefinder", "pytz", "openpyxl", "xlsxwriter", "docx",
            "fitdecode", "tqdm", "colorama", "requests"]   # import names of requirements.txt


def missing_packages():
    return [m for m in REQUIRED if importlib.util.find_spec(m) is None]


def main():
    quick = "--quick" in sys.argv
    miss = missing_packages()
    if miss:
        print("Missing packages: " + ", ".join(miss))
        print("Install first:  pip install -r requirements.txt")
        sys.exit(2)
    rows = []
    for script, slow in TESTS:
        if quick and slow:
            rows.append((script, "skipped", 0.0))
            continue
        if not (HERE / script).is_file():
            rows.append((script, "not found", 0.0))
            continue
        print(f"\n=== {script} ===", flush=True)
        t0 = time.time()
        r = subprocess.run([sys.executable, script], cwd=HERE)
        rows.append((script, "OK" if r.returncode == 0 else f"FAIL ({r.returncode})",
                     time.time() - t0))
    print("\n" + "=" * 60)
    for script, status, dt in rows:
        print(f"{script:36s} {status:12s} {dt:7.0f} s")
    fails = [r for r in rows if r[1].startswith("FAIL") or r[1] == "not found"]
    print("=" * 60)
    print("ALL TESTS PASSED" if not fails else f"{len(fails)} test script(s) failed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
