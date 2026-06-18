"""
RE_OS — Scheduler Package
──────────────────────────
Refactored from monolithic config/scheduler.py into submodules.

Exports all public job functions for backward compatibility with
existing code importing from config.scheduler.
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
import json
import os
import sys

from config.settings import TARGET_MARKETS, SCHEDULER_DRY_RUN
from utils.scheduler_helpers import safe_job as _safe_job

from config.scheduler.rera_jobs import run_single_market_rera

from config.scheduler.kaveri_jobs import (
    run_kaveri_deeds_weekly,
    run_bhoomi_auto_survey,
    _bhoomi_already_ran,
    _mark_bhoomi_ran,
    run_la_notification_scan,
    run_tender_daily_scan,
    run_ledger_check_weekly,
)

from config.scheduler.intel_jobs import (
    run_intel_embedding_index,
    run_news_sentiment_scoring,
    run_market_snapshot,
    run_distressed_developer_scan,
    run_ingest_engine,
    run_conflict_detection,
    run_opportunity_scoring,
    run_psf_forecast_update,
    run_locality_validation,
    run_finbert_sentiment_repair,
    run_portal_scout_canary_check,
    run_gv_freshness_check,
    weekly_competitive_digest,
    run_gcc_daily_scan,
    run_gcc_weekly_digest,
    run_gcc_hiring_snapshot,
    run_dc_conversion_scan,
    run_govt_policy_daily_scan,
    run_govt_policy_weekly_digest,
    run_post_crew_optimizer_hook,
)

from config.scheduler.digest_jobs import (
    run_weekly_digest,
    _digest_already_sent,
    _mark_digest_sent,
    run_weekly_intel_digest,
    run_monthly_intel_digest,
    monthly_ceo_letter,
    weekly_pr_brief,
    weekly_process_audit,
    run_compliance_check,
    run_ledger_verdict_digest,
)

from config.scheduler.maintenance_jobs import (
    run_memory_decay,
    run_seed_staleness_check,
    run_bertscore_evaluation,
    run_db_backup,
    run_backup_staleness_check,
    run_offsite_backup_weekly,
    run_data_floor_check,
    run_scheduler_heartbeat,
    check_heartbeat_staleness,
    recover_stuck_board_sessions,
    run_failed_record_retry,
    run_chromadb_maintenance,
    _ops_already_alerted,
    _bd_already_alerted,
)

__all__ = [
    "run_single_market_rera",
    "run_kaveri_deeds_weekly",
    "run_bhoomi_auto_survey",
    "run_la_notification_scan",
    "run_tender_daily_scan",
    "run_ledger_check_weekly",
    "run_intel_embedding_index",
    "run_news_sentiment_scoring",
    "run_market_snapshot",
    "run_distressed_developer_scan",
    "run_ingest_engine",
    "run_conflict_detection",
    "run_opportunity_scoring",
    "run_psf_forecast_update",
    "run_locality_validation",
    "run_finbert_sentiment_repair",
    "run_portal_scout_canary_check",
    "run_gv_freshness_check",
    "weekly_competitive_digest",
    "run_gcc_daily_scan",
    "run_gcc_weekly_digest",
    "run_gcc_hiring_snapshot",
    "run_dc_conversion_scan",
    "run_govt_policy_daily_scan",
    "run_govt_policy_weekly_digest",
    "run_post_crew_optimizer_hook",
    "run_weekly_digest",
    "run_weekly_intel_digest",
    "run_monthly_intel_digest",
    "monthly_ceo_letter",
    "weekly_pr_brief",
    "weekly_process_audit",
    "run_compliance_check",
    "run_ledger_verdict_digest",
    "run_memory_decay",
    "run_seed_staleness_check",
    "run_bertscore_evaluation",
    "run_db_backup",
    "run_backup_staleness_check",
    "run_offsite_backup_weekly",
    "run_data_floor_check",
    "run_scheduler_heartbeat",
    "check_heartbeat_staleness",
    "recover_stuck_board_sessions",
    "run_failed_record_retry",
    "run_chromadb_maintenance",
    "start_scheduler",
]


def start_scheduler():
    """Create and start the APScheduler instance with all registered jobs."""
    logger.add("logs/scheduler.log", rotation="50 MB")
    os.makedirs("logs", exist_ok=True)

    for market in TARGET_MARKETS:
        slug = market.lower().replace(" ", "_")
        os.makedirs(os.path.join("outputs", slug, "checkpoints"), exist_ok=True)
        logger.info(f"Scheduler: ensured output dir for {market}")

    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    from config.scheduler.rera_jobs import register_jobs as _register_rera
    from config.scheduler.kaveri_jobs import register_jobs as _register_kaveri
    from config.scheduler.intel_jobs import register_jobs as _register_intel
    from config.scheduler.digest_jobs import register_jobs as _register_digest
    from config.scheduler.maintenance_jobs import register_jobs as _register_maintenance

    _register_rera(scheduler, _safe_job)
    _register_kaveri(scheduler, _safe_job)
    _register_intel(scheduler, _safe_job)
    _register_digest(scheduler, _safe_job)
    _register_maintenance(scheduler, _safe_job)

    if SCHEDULER_DRY_RUN:
        jobs = scheduler.get_jobs()
        logger.info("SCHEDULER_DRY_RUN mode: {} jobs registered, exiting 0", len(jobs))
        print(json.dumps({"status": "dry_run", "job_count": len(jobs)}))
        sys.exit(0)

    logger.info("RE_OS Scheduler started — {} active jobs", len(scheduler.get_jobs()))
    logger.info(f"Active jobs: {[j.id for j in scheduler.get_jobs()]}")

    scheduler.start()


if __name__ == "__main__":
    start_scheduler()
