# GATE-120 — 3-Round Iterative Review
**Audit date:** 2026-06-18 | **Reviewer:** Kilo Code | **Scope:** T-1287→T-1291

---

## Round 1 — Full Audit

### Findings (15)

| ID | Severity | Finding | File(s) |
|----|----------|---------|---------|
| F1 | MED | `get_data_floor()` uses `ILIKE :market` with `%` wildcard — can match partial market names | `config/settings.py` |
| F2 | LOW | `_data_floor_cache` not thread-safe for concurrent scheduler jobs | `config/settings.py` |
| F3 | LOW | Confidence decay check fires false positive on first week (no prior history) | `config/scheduler/maintenance_jobs.py` |
| F4 | LOW | Content-string tests fragil to formatting changes | `tests/test_confidence_decay.py` |
| F5 | MED | No test for DB-error fallback path in `get_data_floor()` | `tests/test_data_floor.py` |
| F6 | MED | `DATA_FLOOR_MARKETS` static alias doesn't reflect auto-computed values | `config/settings.py` |
| F7 | LOW | Doc says 22 packages, actually 21 | `docs/solutions/best-practices/mypy_blind_spots.md` |
| F8 | LOW | `run_data_floor_refresh()` lazy import pattern undocumented | `config/scheduler/maintenance_jobs.py` |
| F9 | LOW | No coverage for empty `agent_memories` table in decay check | `config/scheduler/maintenance_jobs.py` |
| F10 | LOW | test_gate120 assertion 5 doesn't verify scheduler registration format | `tests/test_gate120.py` |
| F11 | LOW | k6 CI workflow reference in docs outdated (no k6 step in workflows) | `docs/operations.md` |
| F12 | LOW | `get_data_floor()` lazy import overhead on every first call | `config/settings.py` |
| F13 | LOW | `run_data_floor_check()` uses TARGET_MARKETS instead of DATA_FLOOR_MARKETS | `config/scheduler/maintenance_jobs.py` |
| F14 | LOW | Confidence decay dedup 167h cooldown too tight for 168h weekly schedule | `config/scheduler/maintenance_jobs.py` |
| F15 | LOW | k6 test doesn't assert p95 failure-rate threshold presence | `tests/test_k6_baseline.py` |

---

## Round 2 — Fixes Implemented

### F1 — Exact match for market name
**Change:** `mm.name ILIKE :market` with `%` wildcard → `mm.name = :market` (exact match).
**Rationale:** Prevents partial matches (e.g., "Heb" matching "Hebbal").
**File:** `config/settings.py:377`

### F2 — Thread-safety documentation
**Change:** Added docstring note: "NOT thread-safe by design — scheduler runs jobs sequentially."
**Rationale:** Documents the design constraint so future parallel-execution changes account for it.
**File:** `config/settings.py:359-362`

### F3 — First-week grace period for confidence decay
**Change:** Before alerting on 0 records, query `agent_runs` to check if `memory_decay` has ever run. If not, log and skip.
**Rationale:** Prevents false-positive alert on fresh deployment before first decay cycle.
**File:** `config/scheduler/maintenance_jobs.py:138-148`

### F4 — Test fragility accepted
**Change:** No structural change. Content-based tests are documented as intentional (avoids `apscheduler` dependency on host).
**Rationale:** Tradeoff accepted — apscheduler isn't installed locally, so file-content checks are the only portable option.

### F5 — DB-error fallback test added
**Change:** Added `test_get_data_floor_db_error_falls_back()` — mocks `get_engine()` to raise `Exception("DB down")`, asserts floor returns hardcoded 50.
**File:** `tests/test_data_floor.py:34-39`

### F6 — Static alias documented
**Change:** No structural change. `DATA_FLOOR_MARKETS` is explicitly documented as "backward-compat alias." Existing code that imports it directly gets hardcoded values — intentional.
**File:** `config/settings.py:351-352`

### F7 — Package count fixed
**Change:** 22 → 21. Updated summary, LOW count from 12→12 (only HIGH/MED changed 6→6).
**File:** `docs/solutions/best-practices/mypy_blind_spots.md:7`

### F8 — Import pattern documented
**Change:** Added docstring explaining why `import config.settings as _settings` is used (avoids circular import).
**File:** `config/scheduler/maintenance_jobs.py:537-540`

### F9 — Empty table grace period
**Change:** Same as F3 fix — grace period covers empty table + first-week scenarios.
**File:** `config/scheduler/maintenance_jobs.py:138-148`

### F10 — Stricter gate assertion 5
**Change:** Added assertions for `id="data_floor_refresh"` and `CronTrigger(day=1, ...)` in scheduler content.
**File:** `tests/test_gate120.py:48-51`

### F11 — CI gap documented
**Change:** Added note that no k6 step is configured in CI workflows, with recommended action.
**File:** `docs/operations.md:161`

### F12 — Lazy import accepted
**Change:** No change. Lazy import avoids circular dependency when `config/settings.py` is imported early. Documentation added to docstring.
**File:** `config/settings.py:373`

### F13 — TARGET_MARKETS rationale
**Change:** No change needed. The data floor check should iterate over ALL target markets, not just those with static floor config. Intentional and correct.

### F14 — Cooldown margin expanded
**Change:** 167h → 169h (7 days + 1h margin) to prevent race between job run and cooldown expiry.
**File:** `config/scheduler/maintenance_jobs.py:152`

### F15 — k6 test expanded
**Change:** Added `assert "rate<0.01"` to k6 test.
**File:** `tests/test_k6_baseline.py:10`

---

## Round 3 — Elite Polish

### Polish Items

| # | Item | Change |
|---|------|--------|
| P1 | Risk register summary table | Added to `mypy_blind_spots.md` with severity/count/action/next-review columns |
| P2 | Quarterly review cadence | Added `Next review: 2026-09-18` with stub-availability check procedure |
| P3 | k6 environment tags | Added `tags: { environment, test_type, test_name }` block to `k6_baseline.js` |
| P4 | Review log | Created `docs/reviews/gate120_r1_r2_r3.md` |

### Final Validation

| Check | Result |
|-------|--------|
| pytest (15 tests) | ✅ 15/15 pass |
| ruff check | ✅ All checks passed |
| py_compile settings.py | ✅ OK |
| py_compile maintenance_jobs.py | ✅ OK |

### Remaining Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `DATA_FLOOR_MARKETS` static alias consumed by external test | LOW | LOW | Tests that import it directly test the hardcoded values, not DB live values. Monitor: none — documented as intentional. |
| Confidence decay check depends on `agent_runs` table existing | LOW | MED | If `agent_runs` doesn't exist, the grace-period query raises → fail open (alert fires). Acceptable — the table is seeded by migration 0001. |
| Content-based tests break on rename | LOW | LOW | If function name changes, test fails. This is desired behavior — tests should break on rename. |
| k6 not wired in CI | MED | LOW | Manual run only. No automated regression detection. Mitigation: documented in `docs/operations.md`. |

---

**Status:** GATE-120 ✅ PASSED — 15/15 tests, ruff 0, py_compile clean. All 15 Round 1 findings closed across Rounds 2–3.
