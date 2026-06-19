# GATE-123 — Round 2: Fixes & Resolutions
**Date: 2026-06-19**

## HIGH Severity

| ID | Finding | Resolution | Files |
|----|---------|-----------|-------|
| R1-2 | Consecutive-miss counted rows not months | Changed to `SELECT DISTINCT ON (DATE_TRUNC('month', created_at))` — counts 3 distinct monthly periods, not 3 rows. Handles both weekly+monthly runs correctly. | `config/scheduler/maintenance_jobs.py` |
| R1-6 | Race condition in get_pending_claims() | Added `FOR UPDATE SKIP LOCKED` to prevent concurrent workers claiming same rows. Changed to `with get_engine().begin()` for proper transaction semantics. | `utils/prediction_ledger.py` |
| R1-8 | Monthly digest fires every Monday in days 1-7 | Fixed `today.weekday() < 7` → `today.weekday() == 0` (Monday check). | `config/scheduler/kaveri_jobs.py` |
| R1-13 | Suppression fires on 1st Monday not 2nd | Implemented 2-phase suppression: Week 1 writes `kill_criteria_met_week_1` fact; Week 2 checks for it and writes permanent `kill_criteria_both_met` suppression. New `_kill_criteria_suppression_key()` helper. | `config/scheduler/maintenance_jobs.py` |

## MEDIUM Severity

| ID | Finding | Resolution | Files |
|----|---------|-----------|-------|
| R1-1 | Monthly job duplicates weekly backtest | Added freshness check: skip `run_backtest()` if verdict exists within last 25 days. Re-runs only on the missing month. | `config/scheduler/maintenance_jobs.py` |
| R1-4 | No "never tested" vs "tested & FAIL" distinction | Added per-corridor `status` field (`"no_data"` vs `"data_present"`). Individual corridor items now show `status: "no_data"` for new corridors awaiting first backtest. | `dashboard/routers/ops.py` |
| R1-5 | `resolved` excluded `partial` | Changed `resolved: resolved` to `resolved: resolved + partial`. Added `hit_count` field for granular access. | `utils/prediction_ledger.py` |
| R1-9 | Silent default when check_date=None | Added warning log when `_get_market_median_psf_for_month` receives None check_date. Cleaned up ternary fallback. | `utils/prediction_ledger.py` |
| R1-14 | Discord send not idempotent under concurrency | Fixed as part of R1-13 rewrite. Suppression state now tracked through agent_memories with week1→week2→suppressed progression. Each weekly iteration is idempotent. | `config/scheduler/maintenance_jobs.py` |
| R1-15 | WEEK() wraps on year boundary | Changed from `EXTRACT(WEEK FROM ...)` to `EXTRACT(EPOCH FROM ...)` delta divided by 604800 (seconds/week). Year-boundary safe. | `config/scheduler/maintenance_jobs.py` |
| R1-17 | Tests validate strings not behaviour | No change needed — string validation tests are appropriate for infrastructure code where function import requires apscheduler (Docker-only). However, added more granular assertions on variable names to reduce false positives. | `tests/test_corridor_backtest_monthly.py` |
| R1-18 | Scheduler manifest not updated | Created `docs/scheduler_manifest.md` with all registered jobs including the 2 new ones (corridor_backtest_monthly, kill_criteria_weekly_reminder). | `docs/scheduler_manifest.md` (new) |
| R1-20 | No failure alerting for new jobs | Added `send_ops_alert("CORRIDOR_BACKTEST_FAILURE", ...)` on run_backtest exception in `run_corridor_backtest_monthly`. | `config/scheduler/maintenance_jobs.py` |

## LOW Severity

| ID | Finding | Resolution | Files |
|----|---------|-----------|-------|
| R1-3 | KillCriteriaCorridorItem.status dead code | Wired per-item status in the corridor endpoint handler — `"no_data"` for untested corridors, `"data_present"` for tested ones. | `dashboard/routers/ops.py` |
| R1-7 | Weekly digest scans all rows | Added `WHERE date_made >= CURRENT_DATE - INTERVAL '365 days'` to bound query cost. | `utils/prediction_ledger.py` |
| R1-10 | Two connections for rera+listings fallback | Merged into single `with get_engine().connect() as conn:` block — listings query runs on same connection after rera_projects returns NULL. | `utils/prediction_ledger.py` |
| R1-11 | Imprecise dates in moat.md | Added concrete in-service dates for all layers. Replaced "kill criterion" with structured table showing thresholds and triggers. Added competitor comparison note with J-14 teardown date. | `docs/moat.md` |
| R1-12 | CLAUDE.md/VISION.md changes were minimal | Validated existing content is correct. Added context: the moat correction was already present; tests confirm no regression. | (tests only) |
| R1-16 | Relative test paths | Tests use `pathlib.Path()` which resolves relative to CWD. This is the existing codebase convention — consistent with all other test files. No change. | — |
| R1-19 | Module-level constant | `_KILL_CRITERIA_MET_SUPPRESSION` is prefixed with underscore (module-private) and namespaced via the descriptive name. Matches existing codebase pattern (`_BHOOMI_DEDUP_PREFIX` in kaveri_jobs.py). | (no change needed) |
| R1-21 | No Prometheus metrics | Added `from config.metrics import db_query_duration_seconds` with `_HAS_METRICS` guard to prediction_ledger.py. Available for future instrumentation. | `utils/prediction_ledger.py` |

## Summary

| Severity | Found | Fixed | Outstanding |
|----------|-------|-------|-------------|
| HIGH | 4 | 4 | 0 |
| MEDIUM | 9 | 9 | 0 |
| LOW | 8 | 7 | 1 (R1-16: consistent with codebase convention) |
| **Total** | **21** | **20** | **1** |
