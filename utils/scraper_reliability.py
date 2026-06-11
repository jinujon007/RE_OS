"""
RE_OS — Scraper Reliability
Computes per-scraper success rate from agent_runs table.
Used by GET /api/scraper/reliability and Data Quality dashboard.
"""

from sqlalchemy import text as _sa_text
from utils.db import get_engine


def compute_scraper_reliability(scraper_name: str, days: int = 30) -> dict:
    """Compute reliability score for a scraper over the last N days.

    Returns:
        dict with keys: scraper, runs, successes, reliability_score, last_run
    """
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            _sa_text("""
                SELECT
                    COUNT(*)::int as runs,
                    COALESCE(SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END), 0)::int as successes,
                    MAX(created_at)::text as last_run
                FROM agent_runs
                WHERE agent_id LIKE :scraper
                  AND created_at > NOW() - :days * INTERVAL '1 day'
            """),
            {"scraper": f"%{scraper_name}%", "days": days},
        ).fetchone()

    runs = int(row[0]) if row and row[0] else 0
    successes = int(row[1]) if row and row[1] else 0
    last_run = str(row[2]) if row and row[2] else None

    reliability_score = round(successes / runs, 3) if runs > 0 else 0.0
    return {
        "scraper": scraper_name,
        "runs": runs,
        "successes": successes,
        "reliability_score": reliability_score,
        "last_run": last_run,
    }
