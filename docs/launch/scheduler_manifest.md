# Scheduler Job Manifest — T-1116
**Date:** 2026-06-11 (R2 audit)
**Task:** T-1116 — Scheduler job registry audit
**Total registered jobs:** 33
**Minimum required:** 15

---

## Registered Jobs

Time zones: IST = UTC+5:30. "Previous day" means the day before in UTC.

| # | ID | Name | IST Trigger | UTC Trigger | Sprint | Failure Mode |
|---|----|------|------------|-------------|--------|-------------|
| 1 | `ingest_engine` | Unified Ingest Engine (all plugins) | Daily 02:00 | Prev day 20:30 | Sprint 61 | Misfire → retry 1h window |
| 2 | `opportunity_scoring` | Daily Opportunity Scoring (GATE-47) | Daily 03:00 | Prev day 21:30 | Sprint 63 | Misfire → retry 1h window |
| 3 | `market_snapshot` | Daily Market Snapshot | Daily 06:00 | Daily 00:30 | General | Misfire → retry 1h window |
| 4 | `seed_staleness_check` | Daily Seed Staleness Check | Daily 06:05 | Daily 00:35 | Sprint 64 | Misfire → retry 1h window |
| 5 | `memory_decay` | Weekly Agent Memory Decay | Monday 08:30 | Monday 03:00 | Sprint 66 | Misfire → retry 1h window |
| 6 | `recover_board_sessions` | Recover Stuck Board Sessions | Every 1 hour | Every 1 hour | Sprint 48 | Self-healing; runs every cycle |
| 7 | `intel_embedding` | Nightly Intel Embedding Index (ChromaDB) | Daily 04:30 | Prev day 23:00 | General | Misfire → retry 1h window |
| 8 | `news_sentiment` | Nightly News Sentiment Scoring (FinBERT) | Daily 05:00 | Prev day 23:30 | General | Misfire → retry 1h window |
| 9 | `bertscore_eval` | Weekly BERTScore Quality Evaluation | Monday 03:45 IST | Sunday 22:15 UTC | Sprint 66 | Misfire → retry 2h window |
| 10 | `distressed_dev_scan` | Daily Distressed Developer Scan (JD/JV targets) | Daily 06:15 | Daily 00:45 | Sprint 72 | Misfire → retry 1h window |
| 11 | `conflict_detection` | Weekly Memory Conflict Detection | Monday 09:00 | Monday 03:30 UTC | Sprint 55 | Misfire → retry 1h window |
| 12 | `weekly_digest` | Weekly Memory Digest (top-5 facts per market) | Monday 04:00 IST | Sunday 22:30 UTC | Sprint 66 | Misfire → retry 1h window |
| 13 | `psf_forecast_update` | Weekly PSF Forecast Update (numpy linear trend) | Monday 10:30 | Monday 05:00 UTC | Sprint 85 | Misfire → retry 1h window |
| 14 | `db_backup` | Daily pg_dump Backup | Daily 04:00 | Prev day 22:30 | Sprint 83 | Misfire → retry 1h; `replace_existing` prevents duplicates |
| 15 | `backup_staleness_check` | Daily Backup Staleness Check | Daily 11:30 | Daily 06:00 UTC | Sprint 83 | Misfire → retry 1h window |
| 16 | `compliance_check` | Daily LLS Compliance Calendar Check | Daily 08:00 | Daily 02:30 UTC | Sprint 66 | Misfire → retry 1h window |
| 17 | `locality_validation` | Daily Locality Alias Validation (R06/R15) | Daily 06:10 | Daily 00:40 | Sprint 64 | Misfire → retry 1h window |
| 18 | `finbert_sentiment_repair` | FinBERT Sentiment Repair (null score retry) | Daily 09:00 | Daily 03:30 UTC | Sprint 79 | Misfire → retry 1h window |
| 19 | `portal_scout_canary_check` | Portal Scout Canary (zero listing alert) | Daily 08:30 | Daily 03:00 UTC | Sprint 79 | Misfire → retry 1h window |
| 20 | `gv_freshness_check` | Daily GV Freshness Check (Discord alert) | Daily 06:12 | Daily 00:42 | Sprint 78 | Misfire → retry 1h window |
| 21 | `competitive_pulse_monday` | Monday Competitive Intel Pulse Digest | Monday 06:30 | Monday 01:00 UTC | Sprint 54 | Misfire → retry 1h window |
| 22 | `weekly_pr_brief` | Monday PR Brief Digest (Brand Mentions + LinkedIn) | Monday 07:30 | Monday 02:00 UTC | Sprint 59 | Misfire → retry 1h window |
| 23 | `weekly_process_audit` | Weekly Process Audit (LogAnalyst→Optimizer→Runbook) | Sunday 08:30 | Sunday 03:00 UTC | Sprint 61 | Misfire → retry 2h window |
| 24 | `gcc_daily_scan` | GCC Daily Scan (seed + news → L1/L2 alerts) | Daily 08:00 | Daily 02:30 UTC | Sprint 67 | Misfire → retry 1h window |
| 25 | `gcc_weekly_digest` | Monday GCC Weekly Digest → Discord intel | Monday 07:30 | Monday 02:00 UTC | Sprint 67 | Misfire → retry 1h window |
| 26 | `govt_policy_daily_scan` | Govt/Policy Daily Scan → events + Discord | Daily 06:30 | Daily 01:00 UTC | Sprint 75 | Misfire → retry 1h window |
| 27 | `govt_policy_weekly_digest` | Monday Govt/Policy Weekly Digest → Discord | Monday 08:00 | Monday 02:30 UTC | Sprint 75 | Misfire → retry 1h window |
| 28 | `post_crew_optimizer_hook` | Post-Crew Optimizer Hook (daily fallback) | Daily 09:30 | Daily 04:00 UTC | Sprint 60 | Fallback triggered by crew completion callback; daily cron is safety net |
| 29 | `monthly_ceo_letter` | Monthly CEO Letter (PerformanceDigest) | 1st 09:30 | 1st 04:00 UTC | Sprint 62 | Misfire → retry 2h window |
| 30 | `run_mobility_scout` | Monthly Mobility Scout (accessibility_scores) | 1st 01:00 | 1st 19:30 UTC (-1d) | Sprint 74 | Misfire → retry 2h window |
| 31 | `bhoomi_auto_survey` | Daily Bhoomi Auto-Survey from RERA survey numbers | Daily 09:00 | Daily 03:30 UTC | Sprint 80 | Misfire → retry 1h window |
| 32 | `weekly_intel_digest` | Monday Weekly Intel Digest → Discord intel_reports | Monday 07:00 | Monday 01:30 UTC | Sprint 76 | Misfire → retry 1h window |
| 33 | `monthly_intel_digest` | Monthly Intel Digest → Discord intel_reports | 1st 07:30 | 1st 02:00 UTC | Sprint 76 | Misfire → retry 2h window |

---

## Scheduling Rules

- **All daily jobs** use `Asia/Kolkata` timezone unless marked `timezone="UTC"`.
- **Interval jobs** (`recover_board_sessions`) run every 3600s regardless of timezone.
- **`replace_existing=True`** applied to `db_backup` only — prevents pile-up on Docker restart.
- **`misfire_grace_time`** varies: 3600s for most (1h), 7200s for monthly/quality jobs (2h).

---

## Job Count by Category

| Category | Count | Jobs |
|----------|-------|------|
| **Data Pipeline & Intel** | 10 | ingest_engine, opportunity_scoring, market_snapshot, intel_embedding, news_sentiment, distressed_dev_scan, gcc_daily_scan, govt_policy_daily_scan, bhoomi_auto_survey, post_crew_optimizer_hook |
| **Maintenance & Quality** | 8 | memory_decay, bertscore_eval, conflict_detection, seed_staleness_check, locality_validation, finbert_sentiment_repair, portal_scout_canary_check, gv_freshness_check |
| **Board Room & Ops** | 8 | recover_board_sessions, weekly_digest, db_backup, backup_staleness_check, compliance_check, weekly_process_audit, monthly_ceo_letter, run_mobility_scout |
| **Market Intelligence** | 4 | psf_forecast_update, competitive_pulse_monday, gcc_weekly_digest, govt_policy_weekly_digest |
| **Notifications & Reports** | 3 | weekly_pr_brief, weekly_intel_digest, monthly_intel_digest |
| **Total** | **33** | |

---

## Webhook Dependencies

| Job(s) | Discord Channel | Env Variable | Configured |
|--------|----------------|-------------|------------|
| `competitive_pulse_monday` | `competitor` | `DISCORD_WEBHOOK_COMPETITOR` | ✅ |
| `gcc_daily_scan`, `gcc_weekly_digest` | `gcc_intel` | `DISCORD_WEBHOOK_GCC_INTEL` | ✅ |
| `govt_policy_daily_scan`, `govt_policy_weekly_digest` | `govt_policy_scout` | `DISCORD_WEBHOOK_GOVT_POLICY` | ❌ Not set (uses `DISCORD_WEBHOOK_URL` fallback) |
| `weekly_intel_digest`, `monthly_intel_digest` | `intel_reports` | `DISCORD_WEBHOOK_INTEL_REPORTS` | ❌ Not set (uses `DISCORD_WEBHOOK_URL` fallback) |
| `weekly_pr_brief` | N/A (file output) | — | ✅ |
| `backup_staleness_check` | `system` | `DISCORD_WEBHOOK_SYSTEM` | ✅ |
| `db_backup` (on failure) | `system` | `DISCORD_WEBHOOK_SYSTEM` | ✅ |

---

## Validation

| Check | Result |
|-------|--------|
| `scheduler.add_job()` call count | ✅ 33 (≥15 minimum) |
| Job ID uniqueness | ✅ All 33 unique, no duplicates |
| `_safe_job()` wrapping | ✅ Every job wrapped in `_safe_job()` for error isolation |
| `replace_existing` on interval jobs | ✅ Applied to `db_backup` and `recover_board_sessions` |
| Misfire grace time set | ✅ All jobs have `misfire_grace_time` (3600s or 7200s) |

### Jobs Beyond the Sprint 87 Baseline of 15

The Sprint 87 spec listed a minimum of 15 jobs. The current 33 includes these additional jobs added in subsequent sprints:

| Extra Job | Sprint Added | Purpose |
|-----------|-------------|---------|
| `recover_board_sessions` | Sprint 48 | Board session stuck detection |
| `distressed_dev_scan` | Sprint 72 | JD/JV target detection |
| `compliance_check` | Sprint 66 | LLS regulatory compliance |
| `gv_freshness_check` | Sprint 78 | Kaveri guidance value staleness |
| `weekly_pr_brief` | Sprint 59 | PR/Brand digest |
| `weekly_process_audit` | Sprint 61 | Log analyst + optimizer |
| `govt_policy_*` | Sprint 75 | Government policy monitoring |
| `post_crew_optimizer_hook` | Sprint 60 | Crew-level optimization reporting |
| `run_mobility_scout` | Sprint 74 | Transit accessibility scores |
| `bertscore_eval` | Sprint 66 | Quality evaluation |
| `news_sentiment` | General | FinBERT scoring |
| `intel_embedding` | General | ChromaDB embedding |
| `market_snapshot` | General | Aggregate snapshots |

---

## Integration Notes

- **Startup order:** All jobs log their schedule at startup (lines 1964-1995 in `config/scheduler.py`).
- **Failure isolation:** `_safe_job()` catches all exceptions, logs them, and prevents a single job failure from crashing the scheduler process.
- **Resource contention:** Daily pipeline jobs (02:00-06:00 IST cluster) share DB/LLM resources. No mutex is applied — jobs may overlap during backlog recovery.
- **Backup scheduling:** `db_backup` (04:00 IST) and `backup_staleness_check` (11:30 IST) are intentionally separated by 7.5h to give the backup time to complete before being checked.

---
*Audited by Kilo Code for T-1116 (Sprint 87 — LAUNCH GATE). R2 corrected: IST↔UTC conversions, added failure mode + webhook dependency columns.*
