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

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import TARGET_MARKETS


def run_rera_refresh():
    """Daily RERA data pull for all target markets."""
    from crews.market_intel_crew import run_all_markets
    from config.llm_router import _clear_excluded
    # Reset provider exclusions so stale rate-limit state from the previous
    # run doesn't carry over — each scheduled run starts with a clean slate.
    _clear_excluded()
    logger.info("Scheduler: Starting daily RERA refresh")
    try:
        run_all_markets()
        logger.info("Scheduler: RERA refresh complete")
    except Exception as e:
        logger.error(f"Scheduler: RERA refresh failed — {e}")


def run_listings_scan():
    """Listings scan — 6-hourly."""
    from scrapers.rera_karnataka import RERAKarnatakaScraper
    logger.info("Scheduler: Starting listings scan")
    # Listings scraper runs separately here
    # Implement listings_scraper.py for this


def run_market_snapshot():
    """Generate market snapshots for all active markets."""
    logger.info("Scheduler: Generating market snapshots")
    from sqlalchemy import create_engine, text
    from config.settings import DATABASE_URL
    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:
        for market in TARGET_MARKETS:
            market = market.strip()
            try:
                # Compute and insert snapshot
                conn.execute(text("""
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
                        COUNT(r.id),
                        COUNT(CASE WHEN r.is_active THEN 1 END),
                        SUM(r.total_units),
                        SUM(r.sold_units),
                        SUM(r.unsold_units),
                        ROUND(AVG(r.absorption_pct), 2),
                        ROUND(AVG(r.price_avg_psf), 0)
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
                """), {"market": f"%{market}%"})
                logger.info(f"  Snapshot created for: {market}")
            except Exception as e:
                logger.error(f"  Snapshot failed for {market}: {e}")


if __name__ == "__main__":
    logger.add("logs/scheduler.log", rotation="50 MB")
    os.makedirs("logs", exist_ok=True)

    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    # Daily RERA refresh at 2 AM IST
    scheduler.add_job(
        run_rera_refresh,
        CronTrigger(hour=2, minute=0),
        id="rera_refresh",
        name="Daily RERA Data Refresh",
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

    logger.info("RE_OS Scheduler started")
    logger.info("Jobs scheduled:")
    logger.info("  2:00 AM IST — RERA full refresh")
    logger.info("  6:00 AM IST — Market snapshots")
    logger.info("  Every 6 hrs — Listings scan")

    scheduler.start()
