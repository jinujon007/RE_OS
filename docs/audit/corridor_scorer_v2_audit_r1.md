# Round 1 Audit — Corridor Scorer v2 (T-1190–T-1193)
**Date: 2026-06-16 | Reviewer: Kilo Code | Gate: GATE-100**

## 31 Findings

### Migration 0062 (F1–F5)
| ID | Severity | Finding | Fix |
|----|----------|---------|-----|
| F1 | MEDIUM | PostGIS `CREATE EXTENSION` not guarded — fails if extension already created by template or user lacks permissions | Wrap in try/except with info log |
| F2 | LOW | No `geom` CHECK constraint (`ST_IsValid`) — manual WKT could have degenerate polygons | Add CHECK constraint in migration |
| F3 | LOW | No `updated_at` column — boundary edits untracked | Add `updated_at TIMESTAMPTZ` column |
| F4 | MEDIUM | `down_revision` hardcoded string — no test verifies chain | Add migration chain test |
| F5 | LOW | GiST index creation uses `postgresql_using` w/ Alembic — not all Alembic versions support it | Use `op.execute()` for GiST index |

### CorridorScorerV2 (F6–F16)
| ID | Severity | Finding | Fix |
|----|----------|---------|-----|
| F6 | HIGH | Duplicate `CORRIDOR_DEFINITIONS` import (lines 23 + 26) | Remove duplicate |
| F7 | MEDIUM | Unused imports: `uuid4`, `datetime`, `timezone` | Remove |
| F8 | HIGH | `__import__("datetime").timedelta(...)` — unprofessional internal import | Use `from datetime import timedelta` |
| F9 | LOW | Return type `-> list[CorridorScore]` but returns `CorridorScoreV2` instances | Change to `-> list[CorridorScoreV2]` |
| F10 | HIGH | No GeoJSON boundary cache — `_load_boundary_geojsons()` queries DB on every `score_all()` call | Add TTL cache with configurable expiry |
| F11 | MEDIUM | No Prometheus instrumentation — blind to scoring frequency/latency/fallback rate | Add Prometheus metrics |
| F12 | LOW | No `__slots__` on `CorridorScoreV2` — suboptimal memory for DTO | Add `__slots__` |
| F13 | MEDIUM | Bare `except Exception` in `_get_corridor_villages` — swallows programming errors | Catch specific DB exceptions |
| F14 | LOW | No null lat/lng guard — query processes cases that can't match | Add `AND r.longitude IS NOT NULL AND r.latitude IS NOT NULL` |
| F15 | LOW | No retry before v1 fallback — transient connection blips trigger silent downgrade | Add 1-retry with log |
| F16 | LOW | `CorridorScoreV2.__init__` repeats parent signature — fragile to parent changes | Use `**kwargs` pattern |

### API Endpoint (F17–F22)
| ID | Severity | Finding | Fix |
|----|----------|---------|-----|
| F17 | HIGH | No try/except — unhandled exception returns raw 500 | Add structured error handler |
| F18 | MEDIUM | No Pydantic response model — no schema in OpenAPI docs | Add response model |
| F19 | LOW | No `Cache-Control` headers — response is fresh-data but cache-able for seconds | Add `Cache-Control: max-age=30` |
| F20 | LOW | No market filter — consumer can't scope results | Accept `market` query param |
| F21 | LOW | Empty results not distinguished from error | Return structured empty response |
| F22 | LOW | No `_require_auth` decorator pattern — relies on middleware path-based allowlist | Document intent in summary |

### Tests (F23–F29)
| ID | Severity | Finding | Fix |
|----|----------|---------|-----|
| F23 | MEDIUM | Migration geom test can false-positive on docstring containing "Polygon" | Check for `postgresql.GEOMETRY` OR `GEOMETRY` in op.create_table |
| F24 | LOW | Migration test missing `down_revision` chain check | Add test |
| F25 | LOW | Migration test missing `seeded_at` column check | Add test |
| F26 | LOW | Migration test missing `gcc_hubs` (ARRAY) column check | Add test |
| F27 | HIGH | v2 test `test_v2_corridor_boundaries_table_queried` is tautological (`len(villages) >= 0` always True) | Rewrite to verify ST_Within SQL contains correct column references |
| F28 | MEDIUM | Missing endpoint error handling test | Add 500 simulation test |
| F29 | LOW | Missing `window_months` passthrough test | Add test verifying param propagation |

### Cross-Cutting (F30–F31)
| ID | Severity | Finding | Fix |
|----|----------|---------|-----|
| F30 | MEDIUM | No Prometheus metrics registered for corridor scoring | Add counters/histograms |
| F31 | LOW | `utils/__init__.py` missing `CorridorScorerV2` re-export | Add re-export |

---

*End of Round 1 audit. 31 findings: 4 HIGH, 12 MEDIUM, 15 LOW.*
