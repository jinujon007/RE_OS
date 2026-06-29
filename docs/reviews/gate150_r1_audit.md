# GATE-150 Review — Post-V2 Operations Baseline (R1 Complete)
**Date:** 2026-06-27
**Reviewer:** Kilo Code → Elite Polish Pass
**Files:** `config/scheduler/deed_jobs.py`, `config/scheduler/maintenance_jobs.py`, `dashboard/routers/ops.py`, `config/scheduler/__init__.py`, `tests/test_gate150.py`

---

## Summary

GATE-150 delivers 3 new scheduler jobs + 1 new API field + 14 unit tests. R1 audit found 11 actionable findings: 4 CRITICAL (severity: operations blind spots, alert spam), 4 HIGH (subprocess safety, missing coverage), 4 MEDIUM (diagnostics, noise, edge cases), 3 LOW (style, constants). All findings documented with RFC-spec-level rationale.

---

## Round 1 Findings (15 total)

### CRITICAL (4)
| ID | Finding | File:Line | Rationale |
|----|---------|-----------|-----------|
| C1 | `run_alembic_health_check` — subprocess `alembic current` has no `cwd` parameter | `maintenance_jobs.py:1281` | `alembic.ini` discovery depends on process CWD. Docker scheduler container's CWD may not contain `alembic.ini`. If CWD is `/app/`, alembic fails silently (unexpected empty stdout → "head mismatch" alarm, or worse, wrong migration state). Every other subprocess call in the codebase that needs config-relative execution specifies `cwd`. |
| C2 | `run_dlq_drain_check` — no Prometheus counter | `maintenance_jobs.py:1299` | `run_dlq_purge`, `run_failed_record_retry`, and all deed jobs expose Prometheus metrics. DLQ drain has no counter → ops cannot build dashboards or set alerting rules on DLQ stagnation trend. |
| C3 | `run_weekly_kill_criteria_report` — no Prometheus counter | `deed_jobs.py:539` | Same pattern as `_deed_runs`, `_reminder_runs` in same file. Missing `_kill_criteria_report_runs` Prometheus counter means no observability into whether this weekly job is firing. |
| C4 | No alert dedup — both report and drain check fire every run without cooldown | `deed_jobs.py:560`, `maintenance_jobs.py:1316` | `kill_criteria_report` fires `KILL_CRITERIA_WEEKLY` every Monday even if the verdict hasn't changed for 6 consecutive weeks. `dlq_drain_check` fires `DLQ_STALE` every Monday. The codebase already has `_ops_already_alerted()` with 23h cooldown in the same `maintenance_jobs.py` — should be reused. This is alert-fatigue waiting to happen. |

### HIGH (4)
| ID | Finding | File:Line | Rationale |
|----|---------|-----------|-----------|
| H1 | `(head)` substring detection is naive — matches in migration comments | `maintenance_jobs.py:1286` | `"(head)" in stdout` matches any line that contains `(head)`, including migration names or comments like `"Add column (head count)"`. Alembic output appends `(head)` as a suffix marker on the last line only (e.g. `abc123 (head)`). Should check the last non-empty line specifically. |
| H2 | stderr silently discarded in alembic subprocess | `maintenance_jobs.py:1282-1287` | `result.stdout` is used but `result.stderr` is never logged. If alembic prints an error to stderr (e.g., "alembic.ini not found"), the diagnostic disappears from logs. |
| H3 | DLQ status string `'pending'` hardcoded with no validation | `maintenance_jobs.py:1311` | If the `dead_letter_queue` schema changes (column renamed, enum values changed), the query silently returns 0 and no alert fires. Should be a named constant and ideally validated against known values. |
| H4 | A2/A3 tests missing `__all__` assertion | `test_gate150.py:74-133` | A1 correctly asserts `run_weekly_kill_criteria_report in __all__`. A2 and A3 test importability but never check `in __all__`. Inconsistent — a maintainer could remove the function from `__all__` without a test failure. |

### MEDIUM (4)
| ID | Finding | File:Line | Rationale |
|----|---------|-----------|-----------|
| M1 | No `shutil.which("alembic")` guard before subprocess | `maintenance_jobs.py:1280` | If `alembic` is not in PATH, `subprocess.run` raises `FileNotFoundError`. Caught by broad `except Exception` but error message says "check failed" not "alembic binary not found" — wasting debug time. |
| M2 | stderr not included in warning log message | `maintenance_jobs.py:1287` | Warning includes `stdout` but not `stderr`. For actionable ops debugging, both streams should be present. |
| M3 | Test A4 triggers FastAPI audit DB writes → stderr noise | `test_gate150.py:185` | `TestClient(app)` triggers `_write_audit_log` middleware which attempts DB writes. No DB → repeated `Connection refused` messages in test output, masking real failures. |
| M4 | Negative `weeks_remaining` edge case not handled in message | `deed_jobs.py:555` | After 2026-08-15, `weeks_remaining` from `compute_throughput_projection` could be negative. Message reads "Kill criteria update: 12.5/week avg (target 50). Verdict: at_risk. -3 weeks to 2026-08-15." — unclear semantics. |

### LOW (3)
| ID | Finding | File:Line | Rationale |
|----|---------|-----------|-----------|
| L1 | `_REPORT_RUNNING` flag is per-module, not per-market | `deed_jobs.py:517` | Blocking all markets with a single flag. Fine for the single-market weekly job today, but creates a coupling if this is extended to per-market reports. |
| L2 | DLQ drain threshold `10` should be a named constant | `maintenance_jobs.py:1315` | Magic number. `_DLQ_STALE_THRESHOLD = 10` at module level would self-document and make tuning easier. |
| L3 | No return type annotation on `run_weekly_kill_criteria_report` | `deed_jobs.py:521` | Other functions in the same file (`run_daily_deed_scrape` line 110) return `dict` but this one returns `None`. Not annotated — inconsistent with codebase style for job functions. |

---

## Round 2 Planned Fixes

All 11 code-level findings targeted. C1-C4 are non-negotiable (data loss / alert fatigue vectors). H1-H2 improve diagnostics reliability. H3 hardens schema awareness. H4 closes coverage gap. M1-M3 improve debuggability. M4 handles deadline edge case.

---

## Remaining Observations (deferred)

| Observation | Rationale |
|-------------|-----------|
| Exposing `_REPORT_RUNNING` flag for test access (module-level mutation) | Accepted pattern — `_JOB_RUNNING` in `forecast_jobs.py` does the same. |
| Dedup across kill_criteria_report and kill_criteria_reminder (2 different jobs) | Deliberate: report fires at 10:00 IST, reminder at 08:00 IST — different channels (Telegram+Discord vs Discord-only) and different content (report has avg_4wk, reminder has weekly query). |
| No integration tests for actual subprocess or DB | These are unit-mocked; integration tests require `docker compose up` which is outside scope. |
