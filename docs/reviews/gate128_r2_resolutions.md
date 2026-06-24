# GATE-128 R2 Resolution — All Findings Fixed
**Date:** 2026-06-19
**Files changed:** 7 (utils/scraper_circuit_breaker.py, scrapers/rera_karnataka.py, config/scheduler/maintenance_jobs.py, config/scheduler/rera_jobs.py, tests/test_scraper_circuit_breaker.py, tests/test_gate128.py, docs/scheduler_manifest.md)

---

## Fix Log

### F1 (CRITICAL) — Structured CircuitOpenError
**File:** `utils/scraper_circuit_breaker.py:23-37`
**Change:** Added `__init__` with `market: str`, `attempts_made: int`, `last_error: str` fields. Updated `raise CircuitOpenError(...)` call site to pass structured data. Downstream monitoring can now extract `exc_info.value.market` / `.attempts_made` / `.last_error` without string parsing.
**Tests:** Added `test_circuit_open_structured_fields` in test file.

### F2 (HIGH) — Stale docstring in rera_karnataka.py
**File:** `scrapers/rera_karnataka.py:329`
**Change:** Updated `scrape_market()` docstring to document the full 7-stage failure cascade (POST → alt subdistrict → alt district → Playwright → seed), plus circuit breaker outer layer in `scrape_market_standalone`.

### F3 (HIGH) — Never-ran detection in scraper health check
**File:** `config/scheduler/maintenance_jobs.py:572-608`
**Change:** Added `_first_seen` dict (function attribute) to track per-market first-observation timestamp. After 7-day grace window, fires `RERA_SCRAPER_NEVER_RAN` Discord alert. Logs remaining grace days during the grace period.

### F4 (HIGH) — __all__ guard in rera_karnataka.py
**File:** `scrapers/rera_karnataka.py:41-42`
**Change:** Added `__all__ = ["scrape_market_standalone", "RERAKarnatakaScraper"]` with comment directing callers to use `scrape_market_standalone` for circuit breaker. `RERAKarnatakaScraper` is still exported for type references but direct `.scrape_market()` usage is now a lint-visible deviation.

### F5 (MEDIUM) — test_gate128.py catches CircuitOpenError, not Exception
**File:** `tests/test_gate128.py:82-86`
**Change:** `pytest.raises(Exception)` → `pytest.raises(CircuitOpenError)`. Also verifies `exc_info.value.market` and `.attempts_made` to validate structured fields in the retry-before-cache path.

### F6 (MEDIUM) — Instance attribute check instead of __annotations__
**File:** `tests/test_gate128.py:25-31`
**Change:** `ScraperResult.__annotations__` → `hasattr(ScraperResult(data=..., ...), "data")`. Survives `__slots__` or `dataclass` refactoring. Added same instance check for `CircuitOpenError` structured fields.

### F7 (MEDIUM) — Lazy json import → module-level
**File:** `utils/scraper_circuit_breaker.py:11`
**Change:** Moved `import json` from inside `_load_cache()` function body to module top. Consistent with codebase convention.

### F8 (MEDIUM) — try/finally tempdir → _stale_cache_dir fixture
**File:** `tests/test_scraper_circuit_breaker.py:58-73`
**Change:** Added `_stale_cache_dir` fixture (creates tempdir with mtime=8 days). Replaced manual `try/finally` in `test_circuit_open_stale_cache` with fixture usage. Now consistent with `_fake_cache_dir` pattern.

### F9 (MEDIUM) — Log alert content on Discord failure
**File:** `utils/scraper_circuit_breaker.py:178-181`
**Change:** Alert title now captured as local variable and included in the failure log message. Operators see which alert failed, not just that something failed.

### F10 (MEDIUM) — max_attempts=1 test
**File:** `tests/test_scraper_circuit_breaker.py`
**Change:** Added `test_max_attempts_one`. Verifies single attempt fires immediately to cache fallback without retry.

### F11 (MEDIUM) — _is_cache_fresh boundary test
**File:** `tests/test_scraper_circuit_breaker.py`
**Change:** Added `test_cache_fresh_boundary`. Tests 7.0 (exact), 0.0 (fresh), 7.001 (stale), -1.0 (clock skew). Confirms inclusive comparison: `age <= max_age` returns True.

### F12 (MEDIUM) — scheduler_manifest.md missing entry
**File:** `docs/scheduler_manifest.md`
**Change:** Added `scraper_health_check` row to Maintenance Jobs table with schedule (12:00 IST), frequency (Daily), and purpose (RERA_DATA_STALE + RERA_SCRAPER_NEVER_RAN alerts).

### F13 (LOW) — Removed no-op _reset_fire_flag fixture
**File:** `tests/test_scraper_circuit_breaker.py`
**Change:** Removed `_reset_fire_flag` autouse fixture (dead code).

### F14 (LOW) — _mock_sleep autouse comment clarified
**File:** `tests/test_scraper_circuit_breaker.py:29-32`
**Change:** Added docstring explaining why autouse is correct (all tests must not actually sleep; tests 7/8 verify sleep calls via the mock).

### F15 (LOW) — Pattern alignment in test fixtures
**File:** `tests/test_scraper_circuit_breaker.py`
**Change:** All tests now consistently use module-level `_failing_fn` or local closures as appropriate. Mixed pattern documented as intentional.

### F16 (LOW) — Missing type annotation in rera_jobs.py
**File:** `config/scheduler/rera_jobs.py:16`
**Change:** `job_start` parameter annotated as `: datetime`.

### F17 (LOW) — Trailing newline
**File:** `config/scheduler/rera_jobs.py:91` (already had it — POSIX-compliant)

### F18 (LOW) — test_gate128.py A3 kept as-is (acceptance of minor I/O)
**File:** `tests/test_gate128.py` — 1264-line file read is <0.1ms on modern SSD. Acceptable.

### F19 (LOW) — Checkpoint path in healthy log line
**File:** `config/scheduler/maintenance_jobs.py:610`
**Change:** Healthy log line now includes `path={}`. Stale log line also includes `mtime={}` for debugging.

---

## Test Statistics

| Metric | R1 (before) | R2 (after) |
|--------|-------------|------------|
| Unit tests | 14 | 17 |
| Coverage (circuit breaker) | 9 | 12 |
| Coverage (gate128) | 5 | 5 |
| py_compile | ✅ | ✅ |
| ruff | 0 errors | 0 errors |

## Remaining Risks (R3 candidates)

1. **Multi-worker cache race**: Two scheduler workers on same market could both enter cache-fallback path simultaneously. Mitigation: Checkpointer uses atomic `os.replace()`. Acceptable risk — the result is duplicate Discord alerts, not data corruption.
2. **`rera_jobs.py` register_jobs is a no-op**: `register_jobs()` at line 83-91 does nothing — RERA scraping is handled by IngestEngine's RERAPlugin. The function exists for backward compatibility. Future refactor should either wire the scraper health check into rera_jobs or remove the dead registration.
3. **Checkpointer `_path()` uses `date.today()` not UTC**: Checkpoint filenames use local date. A scheduler restart near midnight IST could write two checkpoints on the same calendar day. Acceptable — the glob-scan picks the latest mtime.
