# GATE-150 Round 1 — Full Deep Audit (v2)
**Date:** 2026-06-27
**Auditor:** Kilo Code — Engineering Lead
**Scope:** All 5 deliverables (T-1436→T-1440) + integration boundaries

---

## Executive Summary

15 findings across 4 tiers: 2 CRITICAL (data integrity, observability), 3 HIGH (inconsistency, code organization), 5 MEDIUM (UX, architecture, auditability), 5 LOW (style, docs). 3 findings are carry-forwards from prior fixed-before-v2 release.

---

## R1 Findings

### CRITICAL (2)

**C5 — `_do_kill_criteria_report` assumes weeks_remaining always present**
`deed_jobs.py:565` | `proj.get("weeks_remaining", 0)` defaults to 0 when `compute_throughput_projection()` returns partial data without the key. Message reads "0 weeks to 2026-08-15" which is factually incorrect (would mean deadline is today). The function already handles projection failure at L555-561; but if projection returns a partial dict, the get-default silently misleads.
**Fix:** Check `"weeks_remaining" in proj` before accessing; if absent, fall back to `weeks_remaining = None` and use generic deadline label.

**C6 — No agent_runs audit log for any of the 3 new jobs**
`deed_jobs.py`, `maintenance_jobs.py` | Every other job in the codebase (deed_scrape, backup, heartbeat, pricing_tracker) writes execution status to `agent_runs` table for audit trail and scheduler health visibility. The 3 new jobs don't — ops has no way to confirm the weekly jobs ran without reading Prometheus counters (if configured) or log files.
**Fix:** Add `_log_agent_run(name, market, event, status, notes)` call in each function, consistent with existing `_log_deed_run` pattern. Fail silently on DB error (already the pattern).

---

### HIGH (3)

**H5 — ops.py weeks_remaining_label doesn't handle negative deadline**
`dashboard/routers/ops.py:2071` | `weeks_remaining_label` always set to `f"{weeks_rem} weeks (2026-08-15)"`. After 2026-08-15, this reads "-3 weeks (2026-08-15)" while `deed_jobs.py` correctly renders "past deadline". Two code paths, two different renderings of the same underlying value.
**Fix:** Apply same negative guard: `f"{weeks_rem} weeks (2026-08-15)" if weeks_rem >= 0 else "past deadline"`.

**H6 — Module-level constants interleaved between function bodies**
`maintenance_jobs.py:1273-1275` | `_ALEMBIC_CWD`, `_DLQ_STALE_THRESHOLD`, `_DLQ_PENDING_STATUS` are placed between `send_weekly_telegram_digest()` and `run_alembic_health_check()`. Visual scanning doesn't find them — violates "constants at module top" convention used elsewhere (e.g., `_DEED_DEADLINE` at L1051, `_TG_MSG_MAX` at L1158).
**Fix:** Consolidate at module top with other named constants.

**H7 — `_do_kill_criteria_report` missing return type annotation**
`deed_jobs.py:550` | Public wrapper `run_weekly_kill_criteria_report()` has `-> None` but private impl does not. Inconsistent — type checkers won't catch return value misuse.
**Fix:** Add `-> None` to `_do_kill_criteria_report`.

---

### MEDIUM (5)

**M5 — Kill criteria report Discord message has no formatting**
`deed_jobs.py:572` | Other Discord alerts use markdown bold (`**`), emoji prefixes, or bullet lists. The kill criteria report is plain text: `"Kill criteria update: 12.5/week..."`. Reduces scannability in busy ops channels.
**Fix:** Add `📊` prefix + `**Kill Criteria Report**` header + format avg with number emoji.

**M6 — `_ops_already_alerted` queries DB on every invocation**
`maintenance_jobs.py:21` | Every run of any alerting job queries the `alerts` table. For high-frequency jobs like heartbeat (8/min peak), this adds ~480 DB queries/day just for dedup. Fresnel: weekly jobs (alembic/DLQ) fire once/week — noise fraction is negligible for these, but the architectural pattern should be documented.
**Fix:** No code change needed for this sprint (weekly cadence, DB overhead is ~2 queries/week). Document as ponytail comment on `_ops_already_alerted`.

**M7 — Kill criteria report should log to agent_runs for audit trail**
`deed_jobs.py:550` | Already covered by C6 — specifically, the kill criteria report should log `status=sent` to `agent_runs` (or `status=error` on failure) to create a permanent record.
**Fix:** Part of C6 batch fix.

**M8 — DLQ drain check has hardcoded `7 days` interval in SQL**
`maintenance_jobs.py:1349` | `INTERVAL '7 days'` is a magic string — unlike `_DLQ_STALE_THRESHOLD` and `_DLQ_PENDING_STATUS` which are extracted as constants. If the interval changes, only the SQL string changes (not self-documenting).
**Fix:** Extract `_DLQ_STALE_INTERVAL = "7 days"` constant.

**M9 — No `replace_existing=True` on new GATE-150 jobs**
`maintenance_jobs.py:1612-1627` | Several existing maintenance jobs (`db_backup`, `scheduler_heartbeat`, `kill_criteria_check`, `alembic_weekly_check`) use `replace_existing=True`. The new jobs don't — if the scheduler restarts mid-week and re-registers, duplicate jobs could accumulate. True only if `register_jobs` is called more than once (it isn't in production), but defensive pattern.
**Fix:** Add `replace_existing=True` to all 3 new job registrations.

---

### LOW (5)

**L4 — Unused `import inspect` in test_gate150.py**
`test_gate150.py:288` | `import inspect` at line 288 — never referenced in the test function.
**Fix:** Remove unused import.

**L5 — Docstrings lack IST equivalent for UTC schedules**
`maintenance_jobs.py:1290` | `run_alembic_health_check` docstring: "Monday 06:30 UTC" — no parenthetical IST equivalent. Other functions (e.g., `run_data_floor_check`) include both.
**Fix:** Add `"= 12:00 IST"` to docstrings and job names.

**L6 — `_do_kill_criteria_report` docstring incomplete**
`deed_jobs.py:550` | The private function has no docstring. The public wrapper docstring describes behavior, but the private function carries the actual execution logic. Missing `:raises` or `:return` documentation.
**Fix:** Add minimal docstring.

**L7 — Test A4 covers only positive weeks_remaining in API**
`test_gate150.py:267-280` | Tests `weeks_remaining_label` with `weeks_remaining: 7`. No test for negative (past deadline) or error (status=unknown) path in the API response.
**Fix:** Add 2 edge case tests for A4.

**L8 — Job registration IDs for new jobs don't include `weekly_` prefix consistently**
`deed_jobs.py:613` | Job ID `"weekly_kill_criteria_report"` (consistent with naming). But `"alembic_health_check"` and `"dlq_drain_check"` in `maintenance_jobs.py:1616,1622` don't have a frequency prefix. Other jobs use `"memory_decay"` (no prefix), `"kill_criteria_weekly_reminder"` (mixed). Not a blocker but reduces discoverability in scheduler logs.
**Fix:** Add `"weekly_alembic_health_check"` and `"weekly_dlq_drain_check"` for clarity. Update test assertions accordingly.
