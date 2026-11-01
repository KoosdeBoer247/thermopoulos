"""Golden-output regression test.

tests/golden_reference.json was produced by the calibration version of
2026-11-01 (heat acclimation in JOS-3 and the CVR module). This test
re-runs the same seeded computations (weather pipelines, HESTIA event engine,
runner module, clinic reconstruction, calibration reference weather, PYROX)
and requires every number to match within a relative tolerance of 1e-9, so a
refactoring cannot silently change model results.
"""
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent


def _close(a, b, path="root"):
    if isinstance(a, dict):
        assert isinstance(b, dict) and set(a) == set(b), f"{path}: keys differ"
        for k in a:
            _close(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        assert isinstance(b, list) and len(a) == len(b), f"{path}: length differs"
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f"{path}[{i}]")
    elif isinstance(a, float) and isinstance(b, (int, float)):
        assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12), f"{path}: {a} != {b}"
    else:
        assert a == b, f"{path}: {a!r} != {b!r}"


def test_golden_outputs(tmp_path):
    out = tmp_path / "golden_now.json"
    subprocess.run([sys.executable, str(HERE / "golden_dump.py"), str(ROOT), str(out)],
                   check=True, capture_output=True, text=True, timeout=900)
    _close(json.load(open(HERE / "golden_reference.json")), json.load(open(out)))
