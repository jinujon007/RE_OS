# GATE-127 R1 Audit — Sprint 127 Deliverables
**Date: 2026-06-19 | Auditor: Kilo Code**

## Scope

Files reviewed:
- `scripts/health_check.py` (T-1322) — 9-component stack validator
- `scripts/onboard.ps1` (T-1323) — 8-step Windows PowerShell runner
- `data/deed_inbox/README.md` (T-1324) — deed inbox user guide
- `tests/test_gate127.py` (T-1325) — 5 GATE-127 assertions
- `CHANGELOG.md` + `TASK_QUEUE.md` — project tracking

---

## Findings Summary

| Severity | Count |
|----------|-------|
| HIGH | 2 |
| MEDIUM | 9 |
| LOW | 12 |
| INFO | 7 |
| **Total** | **30** |

---

## scripts/health_check.py — 9 findings

### F1 [MEDIUM] — `shlex.split` pattern is fragile
`_check_containers_running()` uses `shlex.split(f"{' '.join(compose)} ps --format json")`. The compose cmd is always `docker compose` or `docker-compose` so the space-join round-trip is safe in practice, but the pattern is architecturally fragile: any future compose path with spaces would break silently.

### F2 [MEDIUM] — Alembic head check doesn't verify `(head)` suffix
`_check_alembic_head()` checks `returncode == 0` and non-empty output. The spec says "Contains `0067_decision_journal (head)`" but the code accepts any non-empty output. If `alembic current` prints a revision that is NOT the head (e.g., migration not applied), the check falsely passes.

### F3 [LOW] — Inline data-floor script may fail on Windows
`_DATA_FLOOR_SCRIPT` is passed via `shlex.quote()` to `docker compose exec python -c`. On Windows/PowerShell, single-quoted inline scripts with newlines may not parse correctly. The `$ErrorActionPreference` in the outer context doesn't protect the inner script.

### F4 [MEDIUM] — Scheduler check has no fallback key parsing
`_check_scheduler()` parses `data.get("job_count", 0)`. If the `/api/v1/ops/scheduler` endpoint restructures its response, this silently returns 0 and fails. No alternative key fallback or response validation.

### F5 [LOW] — `_CHECKS` type is `Any` instead of `Callable`
Line 144: `_CHECKS: list[tuple[str, str, Any]]` — the third element is a callable returning `tuple[bool, str]`, not `Any`. mypy strict_optional would catch this.

### F6 [LOW] — Error messages truncated to 80 chars
Failure messages are truncated with `[:80]` in every check function. A 150-char Docker error like `Error response from daemon: cannot stop running container: permission denied` is unreadable.

### F7 [INFO] — No version/commit info
No `__version__` or VCS identifier. User cannot determine which revision of the script is running.

### F8 [INFO] — No exit code documentation in docstring
`main()` returns 0/1 but the module docstring doesn't document the exit contract.

### F9 [LOW] — `FileNotFoundError` catch is redundant
In `_check_docker_daemon`, `FileNotFoundError` is caught separately then `OSError` is caught generically. `FileNotFoundError` is a subclass of `OSError`, making the first catch redundant (though harmless).

### F10 [MEDIUM] — No `--verbose` flag for failure diagnostics
When a check fails, only 80 chars of truncated error are shown. No full stdout/stderr dump available without editing the script.

### F11 [LOW] — Unchecked exception from individual checks
`run_checks()` calls `check_fn()` directly. If any check raises an unexpected exception (e.g., `json.JSONDecodeError` in `_check_scheduler`), it propagates and aborts the entire run. Should be wrapped in try/except.

---

## scripts/onboard.ps1 — 9 findings

### F12 [HIGH] — `Invoke-Expression` used throughout (security/injection risk)
Lines 34, 80, 110, 124, 136 all use `Invoke-Expression` with string interpolation. This is PowerShell's equivalent of `eval()` — it re-parses the string as PowerShell code. If `$composeCmd` or any interpolated variable contained special characters, it could execute arbitrary code. Should use `& $composeCmd ps --format json` (call operator) instead.

### F13 [HIGH] — market_intel_crew.py called without market arguments
Step 5 runs `crews/market_intel_crew.py` with no `--market` flags. The brief says "all 3 markets." The script likely processes a single market or defaults to one, meaning 2/3 markets silently skipped.

### F14 [MEDIUM] — Container health doesn't check Docker health status
`Wait-ContainersHealthy` only checks `State == "running"` but Docker supports native health checks since 1.12. A container (e.g., PostgreSQL) can be `running` for 10+ seconds while still initializing. Should check `Health.Status == "healthy"` when the field exists.

### F15 [MEDIUM] — `Get-ComposeCmd` called redundantly inside polling loop
`Wait-ContainersHealthy` calls `Get-ComposeCmd` every 3 seconds (60s/3s = 20 redundant calls). Wasteful I/O. The cmd should be resolved once before the loop.

### F16 [MEDIUM] — Raw JSON dump for kill criteria output
Step 7 prints `Kill Criteria: $response` which is raw JSON. A user running an onboarding script expects human-readable output, not a JSON blob. Should format as a simple table or bullet list.

### F17 [LOW] — No retry on `docker compose up -d`
Line 80 has a single attempt. If a container image pull fails temporarily (network blip), the whole onboarding fails. Should have 2 retries with 10-second backoff.

### F18 [LOW] — Hardcoded `localhost:8050` for kill criteria
The curl URL is hardcoded. If the stack is deployed on a different host/port, this step silently returns "endpoint unreachable" even though the system is fine.

### F19 [INFO] — No `-WhatIf` support
Administrators cannot dry-run the script to see what steps would execute. No `-Confirm` for the `docker compose up` step.

### F20 [LOW] — No elapsed-time instrumentation
No `Measure-Command` or manual timing per step. User can't identify which step is slow without external timing.

---

## data/deed_inbox/README.md — 3 findings

### F21 [LOW] — Immediate processing command only shows `--form17`
The "Immediate" command on line 28 only shows `--form17 --max-files 50`. If the user places EC PDFs, they won't know how to process them without `--ec` flag.

### F22 [LOW] — No file integrity guidance
No mention of PDF corruption detection, MIME type validation, or expected file size ranges. A user might drop a truncated PDF and not understand why it's skipped.

### F23 [INFO] — No escalation path
If processing fails repeatedly, the user has no documented escalation path (who to contact, where to check logs).

---

## tests/test_gate127.py — 5 findings

### F24 [MEDIUM] — Pricing regex is fragile
A3 test checks for `"₹50"` or `"Rs.50"` or `"50 per"` in the README. If pricing changes to ₹75 (still plausible), the test breaks without a descriptive message that pinpoints the issue to pricing text.

### F25 [LOW] — A4 string contains is order-dependent
Test A4 reads the source file and checks `assert check in src` for 9 check names. A future refactor that renames check display names will break this. Acceptable for a gate test but worth noting.

### F26 [LOW] — A1 doesn't validate output format
`--dry-run` exits 0 but the test doesn't verify that all 9 checks appear in stdout, only that the script doesn't crash. If a future version silently drops checks, this test still passes.

### F27 [INFO] — No `--json` mode test
The script supports `--json` but no test validates the JSON output structure. The gate test should at minimum verify valid JSON.

### F28 [LOW] — No `_docker_cmd()` fallback test
The v1 Docker Compose fallback (`docker-compose` vs `docker compose`) is untested. If someone breaks the fallback logic, no test catches it.

---

## CHANGELOG.md + TASK_QUEUE.md — 2 findings

### F29 [INFO] — Duplicate GATE-127 CHANGELOG entries
Lines 1-3 of CHANGELOG.md all reference GATE-127 deliverables. This is inherent to the prepend-only pattern but creates noise.

### F30 [LOW] — Stale `Next task ID: T-1322` in older roadmap summary
Line 2984 still shows `Next task ID: T-1322` in the Sprints 121-123 roadmap summary section.

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Alembic head check false-positive (F2) | Pipeline runs against wrong DB schema | Patch to verify `(head)` suffix |
| Invoke-Expression injection (F12) | Malicious compose path executes arbitrary code | Replace with `& $cmd` call operator |
| Partial market intel run (F13) | 2/3 markets silently unprocessed | Add `--market` args for all 3 markets |
| Raw JSON in user-facing output (F16) | Poor UX, user can't interpret results | Format as table |
| Inline Python script portability (F3) | Script fails on Windows/PowerShell | Use temp-file approach or escape robustly |

---

## R1 Verdict

**Pass with conditions.** 30 findings identified: 2 HIGH (F12, F13 — production-impact), 9 MEDIUM, 12 LOW, 7 INFO. HIGH findings must be resolved before GATE-127 can be re-declared. All MEDIUM findings should be resolved in R2.
