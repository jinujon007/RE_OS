# GATE-156 — R2 Resolutions
**Date:** 2026-06-29 | **Round:** 2 (Fixes)

## Changes Applied

### C-1: Transit signal DRY violation
**Fix:** Moved `_derive_transit_signal` logic into `STRROverlay.transit_signal()` staticmethod in `utils/strr_overlay.py`. Endpoint (`data.py`) and board room (`crews/board_room.py`) both call `STRROverlay.transit_signal(stations)` — single source of truth.

### C-2: Board Room A4 test mocks wrong injection point
**Fix:** Changed `patch("crews.board_room.STRROverlay")` to `patch("utils.strr_overlay.STRROverlay")` — the actual import site used by `crews.board_room` via local import.

### H-1: Missing Prometheus metrics
**Fix:** Added `_strr_overlay_requests_total` counter (market+status labels), `_strr_overlay_duration_seconds` histogram (5 buckets), `_strr_overlay_cache_hits_total` counter.

### H-2: Missing thread-safe cache
**Fix:** Added `_STRR_OVERLAY_CACHE_LOCK = threading.Lock()`, `_cached_strr()` and `_set_cached_strr()` helper functions with LRU eviction (max 50 entries), matching `_vel_competitive_report_cache` pattern.

### H-3: Missing Cache-Control headers
**Fix:** Both hit and miss responses now return `Cache-Control: private, max-age=300, stale-while-revalidate=60`.

### H-4: Missing `__all__` in strr_overlay.py
**Fix:** Added `__all__ = ["STRROverlay"]`.

### M-1: _resolve_market unpack bug
**Fix:** Changed `canonical, _ = _resolve_market(market)` → `canonical = _resolve_market(market)`. All test patching corrected from tuple `("Yelahanka", "yelahanka")` to bare string `"Yelahanka"`.

### M-2: Missing success logging in board room
**Fix:** Added `logger.info("[board_room] STRR overlay: %d station(s)...")` when stations are found.

### M-3+M-4+M-7: Station data enrichment
**Fix:** Added `id` (slug), `type` ("metro"|"suburban"), `opening_quarter` fields. Standardized line naming to `{System}: {Corridor}` format.

### M-5+M-6: Edge case test coverage
**Fix:** Added `test_gate156_a3_strr_overlay_weak_signal`, `test_gate156_a3_strr_overlay_empty_response`, `test_gate156_a5_strr_overlay_unknown_market_endpoint`, transit_signal unit tests (STRONG/MODERATE/WEAK/empty), `__repr__` test.

### L-1: Typo fix
**Fix:** `_haver sine_km` → `_haversine_km`.

### L-2: Missing `__repr__`
**Fix:** Added `STRROverlay.__repr__` returning `f"<STRROverlay stations={n}>"`.

### L-5: Station validation
**Fix:** Added `_validate_station()` called during `_load_stations()` — checks required fields, lat/lon types, status enum. Invalid entries skipped with warning.

## Cache Issue Discovered
TestClient shares module-level cache state across tests. Empty-response test was hitting previous test's cached result. Fixed: clear cache + use unique `radius_km` per edge case test.
