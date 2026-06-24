# GATE-128 R1 Full Audit — Scraper Circuit Breaker + Health Check
**Date:** 2026-06-19
**Auditor:** Kilo Code
**Scope:** T-1327→T-1331 (utils/scraper_circuit_breaker.py, scrapers/rera_karnataka.py §922-970, config/scheduler/maintenance_jobs.py §572-608, tests/test_scraper_circuit_breaker.py, tests/test_gate128.py, docs/scheduler_manifest.md)
**Status:** 20 findings (1 CRITICAL, 4 HIGH, 8 MEDIUM, 7 LOW)

---

## CRITICAL

### F1 — `CircuitOpenError` has no structured fields (observability gap)
**File:** `utils/scraper_circuit_breaker.py:23`
**Severity:** CRITICAL
**Description:** `CircuitOpenError` inherits from `Exception` with only a human-readable message string. Monitoring systems (Grafana, Prometheus, log aggregators) cannot extract market name, attempt count, or last error without fragile regex parsing on `str(exc)`. Failed circuit breakers are invisible to automated SLI tracking.
**Fix:** Add `market: str`, `attempts_made: int`, and `last_error: str | None` fields to `CircuitOpenError`.

---

## HIGH

### F2 — `rera_karnataka.py:329` docstring stale (misleading maintenance surface)
**File:** `scrapers/rera_karnataka.py:329`
**Severity:** HIGH
**Description:** Docstring says *"Falls back to hardcoded sample data if portal unreachable"* — this omits the entire circuit breaker cascade (retry ×3 → cache → seed). Any engineer reading the docstring to understand failure modes will miss the primary resilience layer. The module is 983 lines; docstrings are the main navigation aid.
**Fix:** Update docstring to document the full failure cascade.

### F3 — `run_scraper_health_check` no checkpoint-ever-run detection
**File:** `config/scheduler/maintenance_jobs.py:589`
**Severity:** HIGH
**Description:** Line 589: `if not cp.exists(market, "rera_scraped"): logger.info("[ScraperHealth] {}: no checkpoint yet", market); continue` — silently skips markets that have NEVER had a checkpoint. A fresh deployment with a dead scraper would never alert. The job would log "no checkpoint yet" every day until Jinu notices.
**Fix:** Track per-market "first seen" watermark; after 7 days with no checkpoint ever written, fire `RERA_SCRAPER_NEVER_RAN` alert.

### F4 — `rera_jobs.py` uses `subprocess.Popen` (circuit breaker bypass surface)
**File:** `config/scheduler/rera_jobs.py:58-61`
**Severity:** HIGH
**Description:** `run_single_market_rera` spawns `scrapers/rera_karnataka.py --market X` via `subprocess.Popen`. The circuit breaker lives inside `scrape_market_standalone()` — it runs correctly. But any future code path calling `RERAKarnatakaScraper.scrape_market()` directly bypasses the breaker entirely. There is no guard, no import-time check, no linter rule preventing direct instantiation. `scrape_market_standalone` is a free function any caller can skip.
**Fix:** Move breaker into `scrape_market()` as a wrapper, or add a module-level `__all__` that only exports `scrape_market_standalone`.

---

## MEDIUM

### F5 — `test_gate128.py:82` catches `Exception` not `CircuitOpenError`
**File:** `tests/test_gate128.py:82`
**Severity:** MEDIUM
**Description:** `pytest.raises(Exception)` will pass on ANY exception, including `KeyboardInterrupt` or `SystemExit`. Weakens the assertion's semantic guarantee. The test is meant to verify `CircuitOpenError` specifically.
**Fix:** Change to `pytest.raises(CircuitOpenError)`.

### F6 — `test_gate128.py:27` uses `__annotations__` (fragile introspection)
**File:** `tests/test_gate128.py:27`
**Severity:** MEDIUM
**Description:** `ScraperResult.__annotations__` returns an empty dict if the class uses `__slots__` or is a `dataclass` with `@dataclass(slots=True)`. Attribute annotations are a CPython implementation detail, not a guaranteed API. A future refactor to slots would silently break this test.
**Fix:** Test instance attributes via `hasattr(ScraperResult(...), "data")`.

### F7 — `_load_cache` imports `json` inside function body (lazy import)
**File:** `utils/scraper_circuit_breaker.py:150`
**Severity:** MEDIUM
**Description:** `import json` is inside the `with open(...)` block of `_load_cache`. This is an unnecessary lazy import for a stdlib module that should be loaded at module top. Every call to `_load_cache` pays the (tiny) dict-lookup cost, but more importantly, it's inconsistent with the rest of the codebase — every other file imports json at module level.
**Fix:** Move `import json` to module top.

### F8 — `test_circuit_open_stale_cache` uses `try/finally` not fixture
**File:** `tests/test_scraper_circuit_breaker.py:141-156`
**Severity:** MEDIUM
**Description:** Test 5 manually creates a temp dir and sets mtime via `os.utime`, then cleans up with `try/finally`. Tests 3 and 6 use `_fake_cache_dir` fixture for the same purpose. Two patterns for the same setup = maintenance surface area.
**Fix:** Extend `_fake_cache_dir` to support mtime override, or create a `_stale_cache_dir` fixture.

### F9 — `_fire_cache_alert` doesn't log alert content on failure
**File:** `utils/scraper_circuit_breaker.py:174`
**Severity:** MEDIUM
**Description:** `logger.warning("[CircuitBreaker:{}] Discord alert send failed: {}", self.market, exc)` — doesn't include the alert title or message that failed to send. If Discord is down, operators see "Discord alert send failed" but not *which* alert.
**Fix:** Log the alert content that failed.

### F10 — No `max_attempts=1` test coverage
**File:** `tests/test_scraper_circuit_breaker.py`
**Severity:** MEDIUM
**Description:** All 9 tests use `max_attempts=3` (default). The edge case `max_attempts=1` (single attempt, no retry, immediate cache fallback) is untested. This is the minimum viable configuration and should be verified.
**Fix:** Add test `test_max_attempts_one`.

### F11 — No boundary test for `_is_cache_fresh`
**File:** `tests/test_scraper_circuit_breaker.py`
**Severity:** MEDIUM
**Description:** Test 5 tests stale (8 days). No test for exactly 7.0 days (boundary), 0.0 days (fresh), or negative days (clock skew). The boundary `age_days == max_age` should return `True` (inclusive comparison is correct) but is untested.
**Fix:** Add boundary test `test_cache_fresh_boundary`.

### F12 — No `scraper_health_check` entry in `docs/scheduler_manifest.md`
**File:** `docs/scheduler_manifest.md`
**Severity:** MEDIUM
**Description:** The `scraper_health_check` job exists in `maintenance_jobs.py:1257-1264` and is registered in the scheduler, but the manifest at `docs/scheduler_manifest.md` has no entry for it. Operators reading the manifest won't know this job exists.
**Fix:** Add entry to `docs/scheduler_manifest.md` maintenance jobs table.

---

## LOW

### F13 — `_reset_fire_flag` autouse fixture is a no-op
**File:** `tests/test_scraper_circuit_breaker.py:33-34`
**Severity:** LOW
**Description:** Fixture `_reset_fire_flag` has `autouse=True` but yields with no logic. It has no side effects. Leftover from an earlier pattern or intended for future use. Dead code.
**Fix:** Remove the fixture.

### F14 — `_mock_sleep` autouse on tests that don't need it
**File:** `tests/test_scraper_circuit_breaker.py:27-29`
**Severity:** LOW
**Description:** `_mock_sleep` is `autouse=True` even for tests that verify sleep calls explicitly (7, 8) — those tests correctly re-patch sleep, but the autouse is redundant for them. Tests 4, 5, 6 that use `_failing_fn` (3 failures) would wait 30+60=90s without the mock. The autouse is functionally correct but unclear in intent.
**Fix:** Change to explicit fixture usage instead of autouse.

### F15 — Module-level `_failing_fn` vs per-test closures (pattern inconsistency)
**File:** `tests/test_scraper_circuit_breaker.py:61`
**Severity:** LOW
**Description:** Tests 3, 4, 5, 6 use module-level `_failing_fn`. Tests 2, 7, 8 define closures inside the test. Both work but mix patterns. Not harmful but inconsistent.
**Fix:** Align on a single pattern (module-level factory).

### F16 — `rera_jobs.py:16` type annotation `job_start` missing type
**File:** `config/scheduler/rera_jobs.py:16`
**Severity:** LOW
**Description:** `def _send_rera_alert(market: str, job_start)` — `job_start` parameter has no type annotation. Minor but inconsistent with type-annotated codebase.
**Fix:** Add `: datetime` annotation.

### F17 — `rera_jobs.py:80` newline at end of file missing
**File:** `config/scheduler/rera_jobs.py:91`
**Severity:** LOW
**Description:** File ends without a trailing newline — minor POSIX convention violation.
**Fix:** Add trailing newline.

### F18 — `test_gate128.py` A3 reads full file for simple string check
**File:** `tests/test_gate128.py:51`
**Severity:** LOW
**Description:** Reads entire maintenance_jobs.py (1264 lines) into memory just to check for substring presence. Negligible performance impact but unnecessary I/O.
**Fix:** Use `pathlib.Path.read_text` with a limit or grep. Acceptable as-is — optimization for correctness.

### F19 — `run_scraper_health_check` stale checkpoint detection lacks detailed logging
**File:** `config/scheduler/maintenance_jobs.py:606`
**Severity:** LOW
**Description:** Healthy checkpoints log `{market} healthy ({age:.1f}d old)` but don't include the checkpoint file path. During debugging, knowing *which* file was evaluated helps correlate with filesystem issues.
**Fix:** Include checkpoint path in healthy log line.

---

## Summary

| Severity | Count | Key Pattern |
|----------|-------|-------------|
| CRITICAL | 1 | Structured error data for observability |
| HIGH | 3 | Doc drift, silent-skip detection, bypass surface |
| MEDIUM | 8 | Test quality, import style, manifest gap, alert logging |
| LOW | 7 | Fixture hygiene, annotations, minor nits |
