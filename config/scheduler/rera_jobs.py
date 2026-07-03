"""
RE_OS — RERA Jobs
─────────────────
RERA scraper + alert functions extracted from monolithic scheduler.py.
"""

from collections.abc import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime, timezone
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine

__all__ = [
    "run_single_market_rera",
    "register_jobs",
]


def _send_rera_alert(market: str, job_start: datetime) -> None:
    """Query new RERA projects since job_start and send Discord alert."""
    try:
        from utils.discord_notifier import send_rera_alert

        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                SELECT rp.project_name, d.name AS developer_name
                FROM rera_projects rp
                LEFT JOIN developers d ON d.id = rp.developer_id
                LEFT JOIN micro_markets mm ON mm.id = rp.micro_market_id
                WHERE mm.name ILIKE :market
                  AND rp.created_at >= :job_start
                ORDER BY rp.created_at DESC
                LIMIT 20
            """),
                {"market": f"%{market}%", "job_start": job_start},
            ).fetchall()
        if rows:
            developers = list({r[1] for r in rows if r[1]})
            send_rera_alert(market, len(rows), developers)
    except Exception as e:
        logger.warning(f"  RERA alert failed for {market}: {e}")


def run_single_market_rera(market: str):
    """Independent RERA data pull for a single market."""
    from config.llm_router import _clear_excluded
    import subprocess
    import os
    import sys

    _clear_excluded()
    job_start = datetime.now(timezone.utc)
    logger.info(f"Scheduler: Starting RERA refresh for {market}")

    cmd = [sys.executable, "scrapers/rera_karnataka.py", "--market", market]
    slug = market.lower().replace(" ", "_")
    log_path = os.path.join("logs", f"{slug}.log")
    os.makedirs("logs", exist_ok=True)

    try:
        log_fh = open(log_path, "a")
        proc = subprocess.Popen(cmd, env=os.environ, stdout=log_fh, stderr=log_fh)
        log_fh.close()
        logger.info(f"  Spawned RERA process for {market} (PID {proc.pid}) → {log_path}")
    except Exception as e:
        logger.error(f"  Failed to spawn RERA process for {market}: {e}")
        return

    try:
        proc.wait(timeout=1800)
    except subprocess.TimeoutExpired:
        proc.kill()
        logger.warning(f"  RERA process for {market} timed out after 1800s — killed")
        return

    if proc.returncode != 0:
        logger.warning(
            f"  RERA process for {market} exited with code {proc.returncode} — skipping alert"
        )
        return

    _send_rera_alert(market, job_start)


def register_jobs(scheduler, safe_job) -> None:
    """Register RERA scheduler jobs.

    RERA scraping runs via the IngestEngine's RERAPlugin
    (scheduled as part of ingest_engine). Direct per-market RERA
    jobs are intentionally not registered — the unified IngestEngine
    replaces the old per-market RERA cron approach.
    """
    pass
