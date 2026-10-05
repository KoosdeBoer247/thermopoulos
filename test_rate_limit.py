# -*- coding: utf-8 -*-
"""Tests the HTTP 429 backoff path with a stubbed requests.get (no network)."""
import warnings, time
warnings.filterwarnings("ignore")
import requests
import Klimatos_ClimateShift as K

# keep the test fast; the logic under test is the same at any scale
K.RATE_LIMIT_BASE_WAIT_S = 1.0
K.RATE_LIMIT_MAX_WAIT_S = 4.0
K.RATE_LIMIT_MAX_RETRIES = 3

class FakeResp:
    def __init__(self, status, headers=None):
        self.status_code = status; self.headers = headers or {}
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")
    def json(self):
        return {"hourly": {"time": ["2020-01-01T00:00"]}}

print("=== TEST 1: 429 twice, then success -> must recover ===")
calls = {"n": 0}
def fake_get(url, params=None, timeout=None):
    calls["n"] += 1
    return FakeResp(429) if calls["n"] <= 2 else FakeResp(200)
K.requests.get = fake_get
t0 = time.time()
r = K._get_with_rate_limit_retry("http://x", {}, 1990)
el = time.time() - t0
print(f"  recovered after {calls['n']} calls, waited {el:.1f}s (expect ~3s: 1s + 2s backoff)")
assert r.status_code == 200 and calls["n"] == 3
assert 2.5 < el < 6.0, f"backoff timing wrong: {el:.1f}s"
print("  OK: exponential backoff applied, then succeeded\n")

print("=== TEST 2: Retry-After header must override the backoff ===")
calls["n"] = 0
def fake_get2(url, params=None, timeout=None):
    calls["n"] += 1
    return FakeResp(429, {"Retry-After": "2"}) if calls["n"] == 1 else FakeResp(200)
K.requests.get = fake_get2
t0 = time.time(); K._get_with_rate_limit_retry("http://x", {}, 1991); el = time.time() - t0
print(f"  waited {el:.1f}s (expect ~2s from Retry-After, not the 1s base backoff)")
assert 1.5 < el < 3.5, f"Retry-After not honoured: {el:.1f}s"
print("  OK: server-specified wait honoured\n")

print("=== TEST 3: persistent 429 -> must eventually raise, not loop forever ===")
K.requests.get = lambda url, params=None, timeout=None: FakeResp(429)
t0 = time.time()
try:
    K._get_with_rate_limit_retry("http://x", {}, 1992)
    raise AssertionError("should have raised HTTPError")
except requests.HTTPError:
    print(f"  raised HTTPError after {time.time()-t0:.1f}s, as intended")
print("  OK: gives up cleanly so the caller's skip path still works\n")

print("=== TEST 4: non-429 error must NOT be retried (fail fast) ===")
calls["n"] = 0
def fake_get4(url, params=None, timeout=None):
    calls["n"] += 1; return FakeResp(500)
K.requests.get = fake_get4
try:
    K._get_with_rate_limit_retry("http://x", {}, 1993)
    raise AssertionError("should have raised")
except requests.HTTPError:
    pass
assert calls["n"] == 1, f"500 should not be retried by this helper, got {calls['n']} calls"
print("  OK: only 429 triggers backoff; other errors surface immediately\n")

print("ALL RATE-LIMIT TESTS PASSED")
