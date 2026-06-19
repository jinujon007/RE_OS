# GATE-123 — Round 1 Audit: Findings & Flaws
**Date: 2026-06-19 | Auditor: Kilo Code (agent)**

---

## T-1302 — Corridor Backtest Monthly + Kill-Criteria Wiring

| ID | Severity | Finding |
|----|----------|---------|
| R1-1 | MEDIUM | `run_corridor_backtest_monthly` calls `run_backtest()` which duplicates the weekly job's work. Both weekly and monthly write backtest verdicts, but only one should be the authoritative runner. |
| R1-2 | HIGH | Consecutive-miss counter queries last 3 ROWS, not last 3 MONTHS. With both weekly+monthly jobs writing, 3 weeks = 3+ verdicts → false-positive threshold breach in 3 weeks, not 3 months. |
| R1-3 | LOW | `KillCriteriaCorridorItem.status` field is always "data_present" — never set per-item. Dead code on individual items (only parent `KillCriteriaCorridor.status` is set). |
| R1-4 | MEDIUM | No semantic differentiation between "never tested" (new corridor seed) and "tested and failed". Both yield null rank_correlation/run_date. Downstream consumers can't distinguish. |

## T-1303 — Prediction Ledger Verdict Runner

| ID | Severity | Finding |
|----|----------|---------|
| R1-5 | MEDIUM | `resolve_verdicts()` return dict has `resolved` = hit+miss only (excludes partial). Semantic confusion: "12 resolved" but 3 more existing as "partial". Should either include partial in resolved count or rename field. |
| R1-6 | HIGH | Race condition: no `FOR UPDATE` or advisory lock in `get_pending_claims()`. Two concurrent scheduler instances (possible at horizontal scale) will both process the same pending claims and write duplicate verdicts. |
| R1-7 | LOW | `build_weekly_digest_discord_message()` scans ALL prediction_ledger rows. On a large ledger (10K+ claims), this full-table scan is unnecessary for a weekly summary. Should use a recency filter. |
| R1-8 | HIGH | Monthly digest condition `today.weekday() < 7 and today.day <= 7` is always True (all weekdays < 7). Fires EVERY Monday in days 1-7, not just the FIRST Monday. Correct: `today.weekday() == 0 and today.day <= 7`. |
| R1-9 | MEDIUM | `_get_market_median_psf_for_month` falls back to `date.today()` when `check_date=None`. Silent default masks missing data in pending claims. Should log a warning when check_date is absent. |
| R1-10 | LOW | `_get_market_rera_avg_psf()` opens a second connection for listings fallback instead of reusing the first. Wasteful with connection pooling under horizontal scale. |

## T-1304 — Moat Documentation

| ID | Severity | Finding |
|----|----------|---------|
| R1-11 | LOW | `docs/moat.md` uses imprecise "18+ months" claim with no baseline date. Kill criterion threshold ("< 2 signals/month") lacks documented rationale. |
| R1-12 | LOW | CLAUDE.md moat correction was already present; deliverables added no new content. Tests validate existing state rather than new changes. |

## T-1305 — Kill Criteria Weekly Reminder

| ID | Severity | Finding |
|----|----------|---------|
| R1-13 | HIGH | Suppression fires on FIRST Monday both criteria are met, not SECOND as specified. Code writes suppression entry immediately; spec requires 2 consecutive Mondays of green status before suppressing. |
| R1-14 | MEDIUM | No Discord send-level idempotency. Two concurrent `run_kill_criteria_reminder` calls would both send Discord alerts. The INSERT for suppression is idempotent (ON CONFLICT DO NOTHING) but the send is not. |
| R1-15 | MEDIUM | Weekly average wraps on year boundary: `WEEK(2027-01-01) - WEEK(2026-12-25) = 1 - 52 = -51` → nonsensical negative average. Needs `EXTRACT(EPOCH ...)` or safer window calculation. |

## T-1306 — GATE-123 Declaration

| ID | Severity | Finding |
|----|----------|---------|
| R1-16 | LOW | Test file path references are relative without `.resolve()`. Break if test runner changes working directory. |
| R1-17 | MEDIUM | Tests validate source code text (string matching) rather than function behaviour. Tests can pass while functions have bugs. |

## Cross-Cutting

| ID | Severity | Finding |
|----|----------|---------|
| R1-18 | MEDIUM | `docs/launch/scheduler_manifest.md` not updated with `corridor_backtest_monthly` and `kill_criteria_weekly_reminder` jobs. |
| R1-19 | LOW | `_KILL_CRITERIA_MET_SUPPRESSION` constant at module level could conflict. Should be namespaced or in settings. |
| R1-20 | MEDIUM | No failure alerting for the new scheduler jobs. If `run_corridor_backtest_monthly` or `run_kill_criteria_reminder` fails silently, no notification fires. |
| R1-21 | LOW | No Prometheus/OpenTelemetry metrics instrumentation on any new function. Existing codebase has `db_query_duration_seconds` histograms; new code has none. |

---

**Summary: 21 findings (3 HIGH, 8 MEDIUM, 10 LOW).**
- T-1302: 4 findings (1 HIGH, 2 MEDIUM, 1 LOW)
- T-1303: 6 findings (2 HIGH, 2 MEDIUM, 2 LOW)
- T-1304: 2 findings (0 HIGH, 0 MEDIUM, 2 LOW)
- T-1305: 3 findings (1 HIGH, 2 MEDIUM, 0 LOW)
- T-1306: 2 findings (0 HIGH, 1 MEDIUM, 1 LOW)
- Cross-cutting: 4 findings (0 HIGH, 2 MEDIUM, 2 LOW)
