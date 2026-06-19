# Scheduler Manifest — Registered Jobs
**Last updated: 2026-06-19**

## Kaveri Jobs (config/scheduler/kaveri_jobs.py)

| Job ID | Schedule (IST) | Frequency | Purpose |
|--------|---------------|-----------|---------|
| `kaveri_deeds_weekly` | Sunday 03:00 | Weekly | EC Form 15 + Form 17 inbox parsing + live Kaveri scrape |
| `bhoomi_auto_survey` | 09:00 | Daily | Bhoomi RTC fetch for unchecked survey numbers |
| `la_notification_scan` | Sunday 06:00 | Weekly | Gazette LA notification parser scan |
| `tender_daily_scan` | 07:00 | Daily | Karnataka eProcurement tender scrape |
| `ledger_check_weekly` | Monday 06:00 | Weekly | Resolve prediction_ledger pending claims + Discord digest |

## Intel Jobs (config/scheduler/intel_jobs.py)

| Job ID | Schedule (IST) | Frequency | Purpose |
|--------|---------------|-----------|---------|
| `intel_embedding_index` | Daily | Daily | Rebuild ChromaDB embedding index |
| `market_snapshot` | 06:00 | Daily | Capture project_snapshots for all markets |
| `news_sentiment_scoring` | Post-ingest | Daily | FinBERT sentiment on new news_articles |
| `opportunity_scoring` | Post-ingest | Daily | Run OpportunityEngine.score_all() |
| `conflict_detection` | Post-ingest | Daily | Cross-agent memory conflict detection |
| `psf_forecast_update` | Monday 10:30 | Weekly | PSFForecaster → market_forecasts upsert |
| `finbert_sentiment_repair` | 03:00 UTC | Daily | Retry null-sentiment news articles |
| `portal_scout_canary_check` | Post-ingest | Daily | Zero-listing silent failure detection |
| `gv_freshness_check` | Post-ingest | Daily | Guideline value staleness alert |
| `gcc_daily_scan` | Daily | Daily | GCC hiring snapshot |
| `gcc_weekly_digest` | Monday | Weekly | GCC intel digest |
| `dc_conversion_scan` | Daily | Daily | DC conversion tracker |
| `govt_policy_daily_scan` | Daily | Daily | Government policy events |
| `govt_policy_weekly_digest` | Monday | Weekly | Govt policy digest |
| `competitive_monday_digest` | Monday | Weekly | Competitive intelligence digest |

## Digest Jobs (config/scheduler/digest_jobs.py)

| Job ID | Schedule (IST) | Frequency | Purpose |
|--------|---------------|-----------|---------|
| `weekly_intel_digest` | Monday 07:00 | Weekly | Weekly market intelligence Discord digest |
| `monthly_intel_digest` | 1st 07:30 | Monthly | Monthly market intelligence Discord digest |
| `monthly_ceo_letter` | 1st | Monthly | CEO shareholder letter generation |
| `weekly_pr_brief` | Monday | Weekly | PR brief generation (ORG-SIM — frozen behind env flag) |
| `weekly_process_audit` | Monday | Weekly | Process audit (ORG-SIM — frozen) |
| `compliance_check` | Monday | Weekly | Compliance calendar deadline check |
| `ledger_verdict_digest` | Monthly | Monthly | Ledger hit-rate MD report |

## Maintenance Jobs (config/scheduler/maintenance_jobs.py)

| Job ID | Schedule (IST) | Frequency | Purpose |
|--------|---------------|-----------|---------|
| `memory_decay` | Monday 08:30 | Weekly | Agent memory confidence decay |
| `confidence_decay_check` | Monday 09:30 | Weekly | Validate decay ran (alert if not) |
| `seed_staleness_check` | 06:05 | Daily | Seed data staleness detection |
| `bertscore_eval` | Monday 09:15 | Weekly | BERTScore quality evaluation |
| `recover_board_sessions` | Every hour | Hourly | Stuck board session recovery |
| `db_backup` | 04:00 | Daily | pg_dump backup |
| `backup_staleness_check` | 11:30 | Daily | Backup freshness alert |
| `offsite_backup_weekly` | Sunday 05:00 | Weekly | rclone offsite backup push |
| `data_floor_check` | 06:30 | Daily | Live RERA data floor breach alert |
| `data_floor_refresh` | 1st 10:30 | Monthly | Data floor cache refresh |
| `scheduler_heartbeat` | Every 30min | 30-minute | agent_runs health heartbeat |
| `parcel_linker_nightly` | 02:30 | Daily | Survey_no → parcels upsert |
| `assembly_detection` | Sunday 03:30 | Weekly | Land assembly signal detection |
| `parcel_ownership_enrichment` | Monday 09:30 | Weekly | Bhoomi RTC ownership chain |
| `alembic_weekly_check` | Sunday 08:30 | Weekly | Migration schema drift check |
| `run_mobility_scout` | 1st 01:00 | Monthly | Accessibility score refresh |
| `kill_criteria_check` | Aug 1 + Dec 1 | Biannual | Full kill criteria audit |
| `failed_record_retry` | 09:30 | Daily | DLQ retry |
| `dlq_purge` | Sunday 07:30 | Weekly | DLQ records >30d deletion |
| `corridor_backtest_weekly` | Monday 08:30 | Weekly | Corridor backtest (score vs distance rank corr) |
| `corridor_backtest_monthly` | **1st 14:00** | **Monthly** | **Kill-threshold alert on 3 consecutive misses** |
| `kill_criteria_weekly_reminder` | **Monday 08:00** | **Weekly** | **Deed throughput + decision journal deadline reminder** |

**Bold rows** = added in Sprint 123 (GATE-123, T-1302/T-1305).

## RERA Jobs (config/scheduler/rera_jobs.py)

| Job ID | Schedule (IST) | Frequency | Purpose |
|--------|---------------|-----------|---------|
| `rera_scrape` | Daily | Daily | RERA listing scrape for all markets |
| `market_intel_*` | Per-market | Daily | Full market intel crew pipeline |
| `_cleanup_all_historical` | N/A | On-demand | Historical data cleanup |
