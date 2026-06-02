"""
RE_OS — Data Freshness Tracker
Tracks how recent each data source's scrape was and flags staleness.
"""
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import text

from utils.db import get_engine

_FRESHNESS_WINDOWS = {
    "live": timedelta(hours=24),
    "aging": timedelta(hours=72),
}

_SOURCE_ALIASES = {
    "rera": "RERA",
    "portal": "Listings",
    "developer": "Developer",
    "news": "News",
    "kaveri": "Kaveri",
    "igr": "IGR",
    "sentiment": "Sentiment",
    "intel": "Intel",
}


def _classify_freshness(last_scraped_at) -> tuple[str, float, bool]:
    if last_scraped_at is None:
        return "STALE", 0.0, True
    now = datetime.now(last_scraped_at.tzinfo) if last_scraped_at.tzinfo else datetime.now()
    age = now - last_scraped_at
    if age <= _FRESHNESS_WINDOWS["live"]:
        return "LIVE", 1.0, False
    if age <= _FRESHNESS_WINDOWS["aging"]:
        return "AGING", 0.5, False
    return "STALE", 0.0, True


def get_source_status(market: str | None = None) -> list[dict]:
    """Return freshness dicts for every (task_type, market) pair in agent_runs."""
    base_filter = "WHERE ar.task_type IN :source_types"
    params: dict = {
        "source_types": list(_SOURCE_ALIASES.keys()),
    }

    if market:
        base_filter += " AND ar.micro_market ILIKE :market"
        params["market"] = f"%{market}%"

    sql = f"""
    SELECT
        ar.task_type                                          AS source_key,
        ar.micro_market                                       AS market,
        MAX(ar.started_at)                                    AS last_scraped_at,
        COALESCE(SUM(ar.records_inserted), 0)
            + COALESCE(SUM(ar.records_updated), 0)           AS record_count
    FROM agent_runs ar
    {base_filter}
    GROUP BY ar.task_type, ar.micro_market
    ORDER BY ar.task_type, ar.micro_market
    """

    results = []
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()
    except Exception as exc:
        logger.warning(f"[DataFreshness] Query failed: {exc}")
        return []

    for row in rows:
        source_key = row[0] or "unknown"
        market_name = row[1] or "unknown"
        last_scraped = row[2]
        record_count = row[3] or 0
        label, score, is_stale = _classify_freshness(last_scraped)

        results.append(
            {
                "source": _SOURCE_ALIASES.get(source_key, source_key.title()),
                "market": market_name,
                "last_scraped_at": last_scraped.isoformat() if last_scraped else None,
                "record_count": record_count,
                "freshness_score": score,
                "label": label,
                "is_stale": is_stale,
            }
        )

    return results
