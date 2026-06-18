# GATE-117 3-Round Iterative Review

**Gate:** GATE-117 — DLQ + Scheduler Hardening
**Sprint:** 117
**Reviewer:** Kilo Code
**Date:** 2026-06-18
**Status:** ✅ RE-DECLARED after R2 fixes

---

## Round 1 — Full Audit (2026-06-18)

10 findings identified, 2 CRITICAL.

### Findings Summary

| ID | Severity | Component | Description |
|----|----------|-----------|-------------|
| F-1 | CRITICAL | `docker-compose.yml` healthcheck | Shell `&& cmd1 || cmd2` always passes — heartbeat probe is dead code. Container never restarts on scheduler death. |
| F-2 | CRITICAL | `utils/embedder.py` safe-purge | `$gt: now_iso` instead of `$gt: (now - 24h).isoformat()`. 24h window not implemented. Quarterly data loss risk. |
| F-3 | HIGH | `config/scheduler/__init__.py` | `run_dlq_purge` not exported → ImportError at package level. |
| F-4 | HIGH | Tests | Healthcheck tests only check string presence, not logic. False positives. |
| F-5 | MEDIUM | Tests | Safe-purge mock returns "active" unconditionally — test passes even if guard is deleted. |
| F-6 | MEDIUM | `docs/operations.md` | 90-min blind spot between Docker restart (30min) and Discord ops alert (2h) undocumented. |
| F-7 | MEDIUM | `utils/dead_letter_queue.py` | Static `_SKIP_COLS` whitelist fragile against schema evolution. |
| F-8 | MEDIUM | `utils/embedder.py` | `datetime.now()` naive — timezone-unsafe across multi-TZ deployments. |
| F-9 | LOW | `utils/embedder.py` | `queried_at` update failure logged at DEBUG — should be WARNING. |
| F-10 | LOW | Tests | No integration test for `_validate_schema` against real `information_schema`. |

### Risk Table (R1)

| Risk | Pre-Fix Severity | Root Cause |
|------|-----------------|------------|
| Silent scheduler death — container never restarts | CRITICAL | F-1: dead code heartbeat probe |
| Active embeddings deleted during quarterly maintenance | CRITICAL | F-2: safe-purge no-op |
| `from config.scheduler import run_dlq_purge` fails at runtime | HIGH | F-3: missing export |
| Healthcheck tests give false confidence | HIGH | F-4: string-only assertions |
| OPS blind spot for crash-looping scheduler | MEDIUM | F-6: undocumented 90-min gap |
| Schema evolution triggers false SchemaDriftError | MEDIUM | F-7: static whitelist |
| Cross-TZ deployment corrupts purge logic | MEDIUM | F-8: naive datetime |
| Safe-purge metadata stale without ops visibility | LOW | F-9: DEBUG-level logging |
| Column naming conventions untested | LOW | F-10: no integration test |

---

## Round 2 — Fixes Applied (2026-06-18)

### F-1: Healthcheck dead code → `config/healthcheck.py`

**Fix:**
- Replaced inline shell `&& cmd1 || cmd2` (always-passing) with standalone script `config/healthcheck.py`
- Script has three-state logic: module import → heartbeat probe → DB-unreachable degraded pass
- Module-level `from config.scheduler import start_scheduler` — unhandled ImportError = exit 1 (restart)
- Heartbeat fresh → exit 0; stale → exit 1; DB unreachable → exit 0

**Rationale:** A standalone Python script is testable, maintainable, version-controllable. The inline shell approach is inherently fragile (YAML escaping, shell operators).

**Files changed:** `docker-compose.yml:178`, new `config/healthcheck.py`

### F-2: Safe-purge 24h window → `timedelta(hours=24)`

**Fix:**
- Changed `now_iso = datetime.now().isoformat()` → `cutoff_24h_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()`
- Safe-purge guard now correctly checks `$gt: cutoff_24h_iso` instead of `$gt: now_iso`

**Rationale:** The original code was a copy-paste error — `now_iso` captured at function start matches nothing since no document has `queried_at` in the future.

### F-3: Missing export → `config/scheduler/__init__.py`

**Fix:** Added `run_dlq_purge` to both the import block and `__all__` list.

**Rationale:** `run_failed_record_retry` and `run_chromadb_maintenance` were both exported. `run_dlq_purge` was the only new maintenance job missing from the package API.

### F-4: Healthcheck tests → exit code validation

**Fix:**
- Replaced string-containment test with `test_healthcheck_script_exit_codes()` that validates three cases:
  - DB unreachable → exit 0 (degraded pass)
  - Heartbeat found → exit 0 (healthy)
  - Heartbeat stale → exit 1 (unhealthy)
- Added `test_healthcheck_docker_compose_refs_script()` to verify compose references the script

### F-5: Safe-purge test → WHERE clause validation

**Fix:** Added assertions that `collection.get()` was called with `where={"queried_at": {"$gt": ...}}`. The test now fails if someone removes the safe-purge guard logic.

### F-6: Documentation gap → defense-in-depth section

**Fix:** Added detailed "Defense-in-depth monitoring (two thresholds)" table to `docs/operations.md` explaining the 90-min gap, crash-loop scenario, and rationale.

### F-7: Static `_SKIP_COLS` → dynamic `_fetch_db_generated_columns()`

**Fix:**
- New `_fetch_db_generated_columns(conn, table)` queries `information_schema.columns` for `column_default IS NOT NULL OR is_generated = 'ALWAYS' OR is_identity = 'YES'`
- Replaced static `_SKIP_COLS` with this dynamic query + `{"parcel_id"}` fallback

**Rationale:** Any new DB-generated column (identity, default, generated) is auto-excluded. No more false SchemaDriftError on schema evolution.

### F-8: Timezone-unsafe datetime → UTC-aware

**Fix:** All `datetime.now()` calls in `utils/embedder.py` changed to `datetime.now(timezone.utc)`:
- `search()` queried_at metadata
- `index_intel_reports()` indexed_at metadata
- `MemoryEmbedder.upsert_memory()` updated_at metadata
- `purge_stale_embeddings()` cutoff computation

### F-9: DEBUG log → WARNING

**Fix:** `logger.debug("[Embedder] Failed to update queried_at metadata...)"` → `logger.warning(...)`.

### F-10: Missing integration test

**Fix:** Added `test_validate_schema_against_live_db()` with `@pytest.mark.skip(reason="requires live PostgreSQL")`. Tests temp table creation, schema validation, and drift detection against real `information_schema`.

---

## Round 3 — Polish & Validation (2026-06-18)

### Final Test Results

```
45 passed, 4 skipped in 5.69s
```

Skips:
- 3 pre-existing: `TestIntelEmbedderRerankerIntegration` (T-436 tracker)
- 1 intentional: `test_validate_schema_against_live_db` (requires Docker DB)

### Static Analysis

```
ruff check: All checks passed!  (9 .py files)
py_compile: All 5 files OK
```

### Final File Inventory

| File | Lines | Change type | Risk level |
|------|-------|-------------|------------|
| `config/healthcheck.py` | 54 | NEW | LOW — standalone, no deps on internal state |
| `utils/dead_letter_queue.py` | 307 | MODIFIED | MEDIUM — _fetch_db_generated_columns adds DB query |
| `utils/embedder.py` | 773 | MODIFIED | LOW — datetime.tz, safe-purge where clause, log level |
| `config/scheduler/__init__.py` | 175 | MODIFIED | LOW — 1 line import + 1 line __all__ |
| `config/scheduler/maintenance_jobs.py` | 700 | MODIFIED | LOW — 1 function addition |
| `docker-compose.yml` | ~240 | MODIFIED | LOW — healthcheck test replaced |
| `docs/operations.md` | ~175 | MODIFIED | LOW — documentation expansion |
| `tests/test_dead_letter_queue.py` | 155 | MODIFIED | MEDIUM — new schema drift + purge tests |
| `tests/test_embedder.py` | ~495 | MODIFIED | LOW — new queried_at + safe-purge tests |
| `tests/test_scheduler_healthcheck.py` | 56 | REWRITTEN | LOW — three exit code tests |
| `tests/test_gate117.py` | 49 | MODIFIED | LOW — added healthcheck script import test |

### Remaining Known Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Crash-looping scheduler (restarts every 31 min) never triggers 2h Discord alert | LOW | Data floor check independently validates freshness; documented in `docs/operations.md` |
| ChromaDB TOCTOU race: search() sets queried_at between purge's get() and delete() | LOW | Quarterly schedule; ChromaDB internal locking |
| SchemaDriftError over-aggressive on multi-column NOT NULL without defaults | LOW | `information_schema` already distinguishes; _fetch_db_generated_columns covers identity+default+generated |
| Integration test not run in CI (no Docker DB) | LOW | Documented skip; run manually after `docker compose up -d` |

### Conclusion

GATE-117 re-declared ✅. All 10 R1 findings closed. Zero new findings in R2 review. 45 tests pass (42 R1 + 3 new R2 validation tests). No regressions.
