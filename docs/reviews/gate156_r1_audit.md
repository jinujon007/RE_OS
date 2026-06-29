# GATE-156 — R1 Audit Report
**Date:** 2026-06-29 | **Auditor:** Kilo Code

## Summary

5 files audited across 4 modules. 18 findings: 2 CRITICAL, 4 HIGH, 7 MEDIUM, 5 LOW.

---

## CRITICAL

### C-1: Transit signal logic duplicated across endpoint and board room
**File:** `dashboard/routers/data.py` + `crews/board_room.py`
**Issue:** `transit_demand_signal` computation appears inline in the endpoint (`data.py:2588-2596`) and as a standalone helper `_derive_transit_signal` in `crews/board_room.py:112-117`. Any change to signal rules (e.g., adding a "VERY_STRONG" tier) requires touching two files. Violates DRY.
**Fix:** Move `_derive_transit_signal` into `STRROverlay` as a classmethod. Both consumers call the single source.

### C-2: Board Room A4 test does not test actual integration point
**File:** `tests/test_gate156.py:97-127`
**Issue:** A4 constructs a context string manually rather than exercising the actual code path in `_run_dept_heads`. It patches `overlay.stations_near` on a fresh instance instead of patching `utils.strr_overlay.STRROverlay` where `crews.board_room` imports it. The test passes even if the board_room.py import site is broken.
**Fix:** Patch `crews.board_room.STRROverlay.stations_near` and call the actual `_run_dept_heads` (or at minimum `_build_bd_agent` with full context assembly).

---

## HIGH

### H-1: No Prometheus metrics on STRR overlay endpoint
**File:** `dashboard/routers/data.py:2580-2610`
**Issue:** Every comparable intel endpoint (VEL competitive report, VEL pricing sensitivity, download guide, backtest accuracy) has `_counter` + `_histogram` metrics. The STRR endpoint has neither.
**Fix:** Add `_strr_overlay_requests_total` counter and `_strr_overlay_duration_seconds` histogram, instrument success/failure/cache_hit.

### H-2: No cache with thread safety on STRR overlay endpoint
**File:** `dashboard/routers/data.py:2573-2576`
**Issue:** The `_strr_overlay_cache` dict is defined inline with no locking. Concurrent requests under load risk race conditions. Pattern in codebase (`_vel_competitive_report_cache` + `_LOCK`) uses threading.Lock.
**Fix:** Add `_STRR_OVERLAY_CACHE_LOCK = threading.Lock()` + helper functions `_cached_strr` / `_set_cached_strr`.

### H-3: No Cache-Control headers on responses
**File:** `dashboard/routers/data.py`
**Issue:** VEL competitive report returns `Cache-Control: private, max-age=120`. STRR endpoint returns bare JSON with no caching headers. STRR station data is static — aggressive caching (5min+) is safe.
**Fix:** Add `Cache-Control: private, max-age=300, stale-while-revalidate=60` to success responses.

### H-4: Missing `__all__` in strr_overlay.py
**File:** `utils/strr_overlay.py`
**Issue:** Every utils module in RE_OS exports `__all__`. Missing here means `from utils.strr_overlay import *` silently fails to export `STRROverlay`.
**Fix:** Add `__all__ = ["STRROverlay"]`.

---

## MEDIUM

### M-1: No `_resolve_market` normalization on market param
**File:** `dashboard/routers/data.py` (strr_overlay handler)
**Issue:** The endpoint calls `_resolve_market(market)` but other intel endpoints use `canonical = _resolve_market(target_market)` consistently. The current code uses `canonical, _ = _resolve_market(market)` which works but differs from established convention.
**Fix:** Align variable naming and return checking with VEL pattern.

### M-2: No success logging when STRR stations found
**File:** `crews/board_room.py:530-546`
**Issue:** Only failure is logged. When stations ARE found, there's no log line. Makes operational debugging harder.
**Fix:** Add `logger.info("[board_room] STRR overlay: {} station(s) in {}", len(_strr_stations), market_safe)`.

### M-3: Station data has no `id` or `type` field
**File:** `data/strr_stations.json`
**Issue:** No unique station ID for referencing across the system. No `type` field to distinguish metro/STRR/bus. Adds friction for future integration (e.g., VEL competitive pack includes transit type breakdown).
**Fix:** Add `id` (slug), `type` ("metro"|"suburban") fields.

### M-4: Heterogeneous line naming convention
**File:** `data/strr_stations.json`
**Issue:** Lines mix corridor branding ("Yellow Line"), system name ("STRR"), and phase annotation ("Phase 3"). Creates visual noise in BD Head context and API responses.
**Fix:** Standardize to `{System}: {Corridor/Line} ({Phase})` or use `line_short` + `line_long` fields.

### M-5: No edge case test for transit_demand_signal = "WEAK"
**File:** `tests/test_gate156.py`
**Issue:** Tests cover STRONG (A3 mock at 0.5km) and implicitly MODERATE. WEAK (no stations within 3km) is untested.
**Fix:** Add test with stations all >3km away → assert "WEAK".

### M-6: No edge case test for empty stations response
**File:** `tests/test_gate156.py`
**Issue:** No test that `stations_near` returns `[]` and the endpoint gracefully returns `nearest_station: null, nearest_distance_km: null`.
**Fix:** Add test with `stations_near` returning [].

### M-7: Missing `opening_quarter` in station data
**File:** `data/strr_stations.json`
**Issue:** Year-only granularity is coarse for BD Head analysis. Quarters (Q1/Q2/Q3/Q4) map to project launch windows.
**Fix:** Add `opening_quarter` field where known.

---

## LOW

### L-1: `_haver sine_km` is misspelled (should be `_haversine_km`)
**File:** `utils/strr_overlay.py:39`
**Issue:** Typo in function name. Not a bug (consistent internal usage) but looks unprofessional.
**Fix:** Rename to `_haversine_km`.

### L-2: `STRROverlay` lacks `__repr__`
**File:** `utils/strr_overlay.py:47`
**Issue:** No repr makes debugging harder in interactive sessions.
**Fix:** Add `__repr__` returning `f"<STRROverlay stations={len(_stations)}>"`.

### L-3: No docstring on `_derive_transit_signal`
**File:** `crews/board_room.py:112`
**Issue:** Function is undocumented. Thresholds (1km operational, 3km any) have no rationale.
**Fix:** Add docstring with threshold logic and references.

### L-4: A4 test uses misleading assertion
**File:** `tests/test_gate156.py:127`
**Issue:** Asserts "Transit access" in a manually constructed string. Should assert the literal context format the BD head actually receives.
**Fix:** Assert on the exact template format `[TRANSIT ACCESS — ...]`.

### L-5: No station data validation at module load time
**File:** `utils/strr_overlay.py:23-36`
**Issue:** JSON is loaded and parsed but no schema validation is performed (required fields, types). A malformed station entry silently produces inscrutable errors at query time.
**Fix:** Add `_validate_station(entry: dict) -> bool` called during load with logger warning on each invalid entry.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Station data goes stale (new metro lines) | Medium | Low (wrong proximity) | Annual data review task; static file means zero-ops deployment for updates |
| Signal threshold not calibrated to real deals | Medium | Medium (wrong BD Head recommendation) | Expose thresholds in config.settings; A/B test vs actual deal outcomes in Sprint 160 |
| Market centroid is inaccurate for large markets | Low | Medium (2km radius misses station) | Use real geometry centroids from DB (InfrastructureScorer already has this) |
| _load_stations caches forever in long-running worker | Low | Very Low (would need pod restart for new file) | Add TTL-based reload or file mtime check in R3 |
