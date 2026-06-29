# GATE-150 Round 2 — Resolutions Applied
**Date:** 2026-06-27
**Files:** `config/scheduler/deed_jobs.py`, `config/scheduler/maintenance_jobs.py`, `tests/test_gate150.py`

---

## Changes Applied

### C1 — Alembic subprocess CWD guard (CRITICAL)
`run_alembic_health_check()` now passes `cwd=_ALEMBIC_CWD` to `subprocess.run`, using `ALEMBIC_PROJECT_DIR` env var (default `/app`). Mirrors the existing `utils/alembic_check.py` pattern exactly. Without this, `alembic.ini` discovery depends on the scheduler process CWD, which differs between Docker (`/app`) and dev environments.

### C2 — Prometheus counter for DLQ drain check (CRITICAL)
Added `dlq_drain_runs_total` counter with `status` label (`ok`/`alert`/`error`). Enables ops dashboards for DLQ stagnation trending — parity with `run_failed_record_retry` and `run_dlq_purge` which already expose metrics.

### C3 — Prometheus counter for kill criteria report (CRITICAL)
Added `kill_criteria_report_runs_total` counter with `status` label (`sent`/`error`). Parity with `_deed_runs`, `_reminder_runs` in same file.

### C4 — Alert dedup via `_ops_already_alerted` (CRITICAL)
Both `run_alembic_health_check()` and `run_dlq_drain_check()` now call `_ops_already_alerted(title, cooldown_hours=168)` before firing Discord alerts. 168h = 1 week cooldown matches the weekly schedule. On cooldown hit, the alert is suppressed and logged at INFO level. Reuses the existing dedup infrastructure in `maintenance_jobs.py`.

### H1 — Last-line `(head)` detection (HIGH)
Changed from naive `"(head)" in stdout` substring check to parsing only the last non-empty line: `last_line = [l for l in stdout.split("\\n") if l.strip()][-1]` then `"(head)" in last_line`. This prevents false positives from migration comments containing "(head)" (e.g. "Add column head count").

### H2 — stderr capture in alembic check (HIGH)
`result.stderr` is now included in the warning log message: `"stdout: %s | stderr: %s"`. Critical for debugging alembic configuration or connection errors.

### H3 — Parameterized DLQ query + status constant (HIGH)
Replaced raw string `'pending'` in SQL with parameterized `:status` bound to `_DLQ_PENDING_STATUS` module constant. If the status column value changes, only one constant needs updating.

### H4 — `__all__` assertions in A2/A3 tests (HIGH)
Both `test_gate150_a2_alembic_health_check_importable` and `test_gate150_a3_dlq_drain_check_importable` now assert `in config.scheduler.__all__` (matching A1's pattern). A missing `__all__` entry will now cause test failure.

### M1 — `shutil.which("alembic")` guard (MEDIUM)
Added `shutil.which("alembic")` check before `subprocess.run`. If alembic CLI is not installed, logs a clear "[AlembicHealth] alembic CLI not found — skipping check" message and increments a `skipped` counter. Avoids cryptic subprocess failure. New test `test_gate150_a2_alembic_health_check_skipped_when_cli_missing` verifies this path.

### M2 — stderr in warning message (MEDIUM)
Covered by H2 fix — both stdout and stderr are logged in the head mismatch warning.

### M3 — FastAPI audit noise suppression (MEDIUM)
Test A4 now wraps `TestClient(app)` in `patch("dashboard.app_fastapi._write_audit_log")` to suppress DB connection errors from the audit middleware. Tests produce clean output.

### M4 — Negative `weeks_remaining` edge case (MEDIUM)
`_do_kill_criteria_report()` now checks `if weeks_remaining < 0` and renders the label as `"past deadline"` instead of e.g. `"-3 weeks to 2026-08-15"`. New test `test_gate150_a1_kill_criteria_report_sends_past_deadline_label` verifies.

### L2 — Named constant for DLQ threshold (LOW)
Extracted `_DLQ_STALE_THRESHOLD = 10` at module level. Alert message now interpolates the constant: `f"(threshold >{_DLQ_STALE_THRESHOLD})"` so the message stays correct if the threshold changes.

### L3 — Return type annotation (LOW)
`run_weekly_kill_criteria_report()` now annotated as `-> None`.

### Ponytail comments
Added ponytail ceiling comment to `_REPORT_RUNNING` noting the upgrade path to per-market dict + `threading.Lock` if the feature is extended.

---

## Test Coverage Added

| Test | What it covers |
|------|---------------|
| `test_gate150_a1_kill_criteria_report_sends_past_deadline_label` | Negative `weeks_remaining` → `"past deadline"` |
| `test_gate150_a2_alembic_health_check_skipped_when_cli_missing` | `shutil.which` returns None → silent skip |
| `test_gate150_a3_dlq_drain_check_cooldown_suppresses_duplicate` | `_ops_already_alerted` returns True → alert suppressed |

---

## Files Changed

| File | Changes |
|------|---------|
| `config/scheduler/deed_jobs.py` | Prometheus counter, `-> None`, negative weeks guard, ponytail comment |
| `config/scheduler/maintenance_jobs.py` | `import os`, `_ALEMBIC_CWD`, `_DLQ_STALE_THRESHOLD`, `_DLQ_PENDING_STATUS`, 2 Prometheus counters, `shutil.which` guard, last-line parsing, stderr logging, dedup via `_ops_already_alerted`, parameterized SQL |
| `tests/test_gate150.py` | 3 new tests, `__all__` assertions on A2/A3, `shutil.which` patch on A2 tests, `_ops_already_alerted` patch on A3 tests, `_write_audit_log` patch on A4 |
