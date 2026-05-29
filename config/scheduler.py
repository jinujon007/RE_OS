"""
RE_OS — Scheduler
──────────────────
Runs the agent crew on schedule. Runs inside Docker as a separate service.

Schedule:
- RERA data refresh: daily at 2:00 AM IST
- Listings scan: every 6 hours
- Market snapshot generation: daily at 6:00 AM IST (before Jinu's morning)
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
import os
import sys

from config.settings import TARGET_MARKETS
from sqlalchemy import create_engine, text
from config.settings import DATABASE_URL
import threading

_scheduler_engine = None
_scheduler_engine_lock = threading.Lock()


def _get_scheduler_engine():
    global _scheduler_engine
    if _scheduler_engine is None:
        with _scheduler_engine_lock:
            if _scheduler_engine is None:
                _scheduler_engine = create_engine(
                    DATABASE_URL,
                    pool_pre_ping=True,
                    pool_size=3,
                    max_overflow=1,
                )
    return _scheduler_engine


def run_rera_refresh():
    """Daily RERA data pull for all target markets."""
    from config.llm_router import _clear_excluded
    import subprocess
    import sys
    import os

    # Reset provider exclusions so stale rate-limit state from the previous
    # run doesn't carry over — each scheduled run starts with a clean slate.
    _clear_excluded()
    logger.info("Scheduler: Starting daily RERA refresh (spawning per-market processes)")

    # Launch a separate process for each market to avoid blocking the scheduler thread.
    # Each process writes to its own log file under logs/{slug}.log
    for market in TARGET_MARKETS:
        market_slug = market.strip().lower().replace(" ", "_")
        log_path = f"logs/{market_slug}.log"
        cmd = [sys.executable, "-m", "crews.market_intel_crew", "--market", market]
        try:
            with open(log_path, "a") as fh:
                subprocess.Popen(cmd, stdout=fh, stderr=fh, env=os.environ)
            logger.info(f"Spawned market process: {market} -> {log_path}")
        except Exception as e:
            logger.error(f"Failed to spawn process for {market}: {e}")

    logger.info("Scheduler: daily RERA refresh spawned — returning immediately")


def run_listings_scan():
    """Listings scan — 6-hourly."""
    from scrapers.listings_scraper import ListingsScraper
    from config.checkpointer import Checkpointer

    logger.info("Scheduler: Starting listings scan")
    scraper = ListingsScraper()
    cp = Checkpointer()

    total = 0
    failures = 0

    for market in [m.strip() for m in TARGET_MARKETS]:
        try:
            listings = scraper.scrape_market(market)
            cp.save(market, "listings_scraped", listings)
            count = len(listings or [])
            total += count
            logger.info(f"  Listings scan: {market} -> {count} listings")
        except Exception as e:
            failures += 1
            logger.error(f"  Listings scan failed for {market}: {e}")

    logger.info(
        f"Scheduler: Listings scan complete — total={total}, failures={failures}"
    )


def run_memory_decay():
    """Weekly memory decay — reduce confidence of stale facts, delete below 0.3 (T-298)."""
    from utils.agent_memory import decay_memories
    n = decay_memories(days=30, decay_amount=0.1)
    logger.info(f"[Scheduler] Memory decay: {n} rows deleted")


def run_yelahanka_refresh():
    """
    REMOVED — Yelahanka already runs as the first market in run_rera_refresh()
    at 2:00 AM IST (TARGET_MARKETS order: Yelahanka, Devanahalli, Hebbal).
    Running it again at 2:30 AM caused double LLM cost and checkpoint overwrites.
    This function is kept as a no-op stub so any existing cron references don't crash.
    """
    logger.info(
        "Scheduler: run_yelahanka_refresh is a no-op — "
        "Yelahanka already covered by run_rera_refresh at 2:00 AM IST"
    )


def run_market_snapshot():
    """Generate market snapshots for all active markets."""
    logger.info("Scheduler: Generating market snapshots")

    for market in TARGET_MARKETS:
        market = market.strip()
        engine = _get_scheduler_engine()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                    INSERT INTO market_snapshots (
                        micro_market_id, snapshot_date, period,
                        total_rera_projects, active_rera_projects,
                        total_rera_units, sold_rera_units, unsold_rera_units,
                        avg_absorption_pct, avg_psf_sale
                    )
                    SELECT
                        m.id,
                        CURRENT_DATE,
                        'daily',
                        COUNT(DISTINCT r.id),
                        COUNT(DISTINCT CASE WHEN r.is_active THEN r.id END),
                        SUM(r.total_units),
                        SUM(r.sold_units),
                        SUM(r.unsold_units),
                        ROUND(AVG(r.absorption_pct), 2),
                        ROUND((
                            SELECT AVG(l.price_psf)
                            FROM listings l
                            WHERE l.micro_market_id = m.id
                              AND l.price_psf IS NOT NULL
                              AND l.price_psf > 1000
                              AND l.price_psf < 50000
                        ), 0)
                    FROM micro_markets m
                    LEFT JOIN rera_projects r ON r.micro_market_id = m.id
                    WHERE m.name ILIKE :market
                    GROUP BY m.id
                    ON CONFLICT (micro_market_id, snapshot_date, period) DO UPDATE SET
                        total_rera_projects = EXCLUDED.total_rera_projects,
                        active_rera_projects = EXCLUDED.active_rera_projects,
                        total_rera_units = EXCLUDED.total_rera_units,
                        sold_rera_units = EXCLUDED.sold_rera_units,
                        unsold_rera_units = EXCLUDED.unsold_rera_units,
                        avg_absorption_pct = EXCLUDED.avg_absorption_pct,
                        avg_psf_sale = EXCLUDED.avg_psf_sale
                    """),
                    {"market": f"%{market}%"},
                )
        except Exception as e:
            logger.error(f"  Snapshot failed for {market}: {e}")


def recover_stuck_board_sessions():
    """Set board sessions stuck at 'active' for >30 minutes to 'failed'."""

    try:
        engine = _get_scheduler_engine()
        with engine.begin() as conn:
            result = conn.execute(
                text("""
                UPDATE board_sessions
                SET status = 'failed',
                    completed_at = NOW()
                WHERE status = 'active'
                  AND created_at < NOW() - INTERVAL '30 minutes'
                """)
            )
            rowcount = result.rowcount
        logger.info(f"[Scheduler] Recovered {rowcount} stuck board sessions")
    except Exception as e:
        logger.warning(f"[Scheduler] Failed to recover stuck board sessions: {e}")


if __name__ == "__main__":
    logger.add("logs/scheduler.log", rotation="50 MB")
    os.makedirs("logs", exist_ok=True)

    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    # Daily RERA refresh — all markets at 2 AM IST
    scheduler.add_job(
        run_rera_refresh,
        CronTrigger(hour=2, minute=0),
        id="rera_refresh",
        name="Daily RERA Data Refresh (all markets)",
        misfire_grace_time=3600,
    )

    # Market snapshots at 6 AM IST (ready for morning)
    scheduler.add_job(
        run_market_snapshot,
        CronTrigger(hour=6, minute=0),
        id="market_snapshot",
        name="Daily Market Snapshot",
        misfire_grace_time=3600,
    )

    # Listings scan every 6 hours
    scheduler.add_job(
        run_listings_scan,
        CronTrigger(hour="*/6"),
        id="listings_scan",
        name="6-Hourly Listings Scan",
    )

    # Weekly memory decay — Monday 03:00 UTC (T-298)
    scheduler.add_job(
        run_memory_decay,
        CronTrigger(day_of_week="mon", hour=3, minute=0, timezone="UTC"),
        id="memory_decay",
        name="Weekly Agent Memory Decay",
        misfire_grace_time=3600,
    )

    # Stuck board session recovery — every hour (T-315)
    scheduler.add_job(
        recover_stuck_board_sessions,
        "interval", hours=1,
        id="recover_board_sessions",
        name="Recover Stuck Board Sessions",
        replace_existing=True,
    )

    logger.info("RE_OS Scheduler started")
    logger.info("Jobs scheduled:")
    logger.info("  2:00 AM IST — RERA full refresh (all markets)")
    logger.info("  6:00 AM IST — Market snapshots")
    logger.info("  Every 6 hrs — Listings scan")
    logger.info("  Every 1 hr  — Board session recovery (T-315)")
    logger.info("  Monday 03:00 UTC — Agent memory decay")
    logger.info(f"Active jobs: {[j.id for j in scheduler.get_jobs()]}")

    scheduler.start()
