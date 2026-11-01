"""Runs every stand-alone test script of the suite (the same list as
run_all_tests.py) as a pytest test, each in its own Python process.

    pytest              # fast scripts + golden-output check (default; slow ones deselected)
    pytest -m slow      # only the JOS-3 Monte Carlo scripts (~10 min)
    pytest -m ""        # everything
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_all_tests import TESTS  # noqa: E402

PARAMS = [pytest.param(s, id=s, marks=[pytest.mark.slow] if slow else []) for s, slow in TESTS]


@pytest.mark.parametrize("script", PARAMS)
def test_script(script):
    env = dict(os.environ, HESTIA_NONINTERACTIVE="1", HESTIA_CAL_NONINTERACTIVE="1", MPLBACKEND="Agg")
    r = subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, f"{script} failed:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}"
