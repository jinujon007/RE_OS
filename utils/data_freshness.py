import time
from datetime import datetime, timedelta, timezone

from loguru import logger
from sqlalchemy import text

from utils.db import get_engine

_CACHE_TTL: int = 60
_cache: dict = {"timestamp": 0.0, "data": None}
"""In-memory cache for unfiltered freshness queries.

Cache is invalidated automatically after _CACHE_TTL seconds.
Call _invalidate_cache() to force refresh (e.g. after a scrape).
Market-filtered calls always bypass cache.
"""

_FRESHNESS_WINDOWS = {
    "live": timedelta(hours=24),
    "aging": timedelta(hours=72),
}

_PLUGIN_SOURCE_MAP = {
    "news_scout": ("News", "news"),
    "kaveri_bhoomi": ("Kaveri", "kaveri"),
    "rera_karnataka": ("RERA", "rera"),
    "igr_karnataka": ("IGR", "igr"),
    "portal_plugin": ("Listings", "portal"),
    "developer_plugin": ("Developer", "developer"),
    "distressed_plugin": ("Distressed", "distressed"),
    "bbmp_plugin": ("BBMP", "bbmp"),
}


def _classify_freshness(last_scraped_at) -> tuple[str, float, bool]:
    """Classify a timestamp into LIVE/AGING/STALE with score."""
    if last_scraped_at is None:
        return "STALE", 0.0, True
    ref = (
        last_scraped_at
        if last_scraped_at.tzinfo
        else last_scraped_at.replace(tzinfo=timezone.utc)
    )
    now = datetime.now(timezone.utc)
    age = now - ref
    if age <= _FRESHNESS_WINDOWS["live"]:
        return "LIVE", 1.0, False
    if age <= _FRESHNESS_WINDOWS["aging"]:
        return "AGING", 0.5, False
    return "STALE", 0.0, True


def _invalidate_cache():
    """Force cache refresh on next call."""
    _cache["timestamp"] = 0.0


def get_source_status(market: str | None = None) -> list[dict]:
    """Return freshness dicts for every (plugin_id, market) pair in ingest_log.

    Queries ingest_log for per-plugin scrape recency and volume.
    Falls back to agent_runs for legacy task types not yet in ingest_log.

    Caches unfiltered (market=None) results for 60s. Market-filtered calls
    always hit the DB — they are assumed to be ad-hoc queries.
    """
    now = time.time()
    if (
        market is None
        and (now - _cache["timestamp"]) < _CACHE_TTL
        and _cache["data"] is not None
    ):
        return _cache["data"]

    plugin_ids = list(_PLUGIN_SOURCE_MAP.keys())
    params: dict = {"plugin_ids": tuple(plugin_ids)}
    market_clause = ""
    if market:
        market_clause = " AND il.market ILIKE :market"
        params["market"] = f"%{market}%"

    sql = f"""
        SELECT
            il.plugin_id                                          AS source_key,
            il.market                                             AS market,
            MAX(il.scraped_at)                                    AS last_scraped_at,
            COUNT(*)                                              AS record_count
        FROM ingest_log il
        WHERE il.plugin_id IN :plugin_ids
          {market_clause}
        GROUP BY il.plugin_id, il.market
        ORDER BY il.plugin_id, il.market
    """

    results = []
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()
    except Exception as exc:
        logger.warning("[DataFreshness] ingest_log query failed: {}", exc)
        return []

    for row in rows:
        plugin_id = row[0] or "unknown"
        market_name = row[1] or "unknown"
        last_scraped = row[2]
        record_count = row[3] or 0
        label, score, is_stale = _classify_freshness(last_scraped)
        display_name, _icon = _PLUGIN_SOURCE_MAP.get(plugin_id, (plugin_id, ""))

        results.append(
            {
                "source": display_name,
                "plugin_id": plugin_id,
                "market": market_name,
                "last_scraped_at": last_scraped.isoformat() if last_scraped else None,
                "record_count": record_count,
                "freshness_score": score,
                "label": label,
                "is_stale": is_stale,
            }
        )

    results.sort(key=lambda r: (r["label"] != "LIVE", r["source"], r["market"]))
    if market is None:
        _cache["timestamp"] = time.time()
        _cache["data"] = results
    return results
