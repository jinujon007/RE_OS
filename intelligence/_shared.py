"""
RE_OS — Intelligence Layer Shared Utilities (Sprint 62)
Single source of truth for sanitization, caching, type coercion, and Prometheus timing.

Risk Register:
| Risk | Impact | Mitigation |
|------|--------|------------|
| DB connection timeout stalls module | Module hangs 30-75s per connect | pool_size=2/3, connect timeout in pool_pre_ping; all modules degrade gracefully |
| Cache memory leak (infinite keys) | OOM on long-running scheduler | MarketCache capped per-namespace; caller sets bounded namespace keys (market names) |
| SQL injection via market/survey name | Unauthorized DB read | regex sanitization strips non-word chars; survey limited to 50 chars |
| Prometheus import failure | Module crash | timed_intel_query is a safe no-op with nullcontext fallback |
| validate_market deadlock | Two modules call get_engine simultaneously | engine is thread-safe singleton; each module uses its own connection context |
"""

import re
import threading
import time as _time
from typing import Any
from loguru import logger

__all__ = [
    "fval",
    "sanitize_market",
    "sanitize_survey",
    "validate_market",
    "MarketCache",
    "timed_intel_query",
]


def fval(val: Any) -> float | None:
    """Safely coerce a DB value to float or None.

    Handles None, Decimal, int, str, and float inputs.
    OverflowError caught (e.g. PostgreSQL numeric(30,0) exceeding Python float range).

    Args:
        val: Any DB value (None, Decimal, int, str, float).

    Returns:
        float rounded to 2dp, or None if input is None or uncoercible.
    """
    if val is None:
        return None
    try:
        return round(float(val), 2)
    except (ValueError, TypeError, OverflowError):
        return None


_RE_SANITIZE_MARKET = re.compile(r"[^\w\s-]", re.UNICODE)


def sanitize_market(market: str) -> str:
    """Normalize and sanitize a market name.

    Pipeline: strip → truncate 120 → remove non-[word/space/hyphen] → strip → truncate 100.

    Args:
        market: Raw market name from user input.

    Returns:
        Sanitized market name suitable for slug/ILIKE lookup. Empty string on invalid input.
    """
    if not market or not isinstance(market, str):
        return ""
    cleaned = _RE_SANITIZE_MARKET.sub("", market.strip().title()[:120])
    return cleaned.strip()[:100]


_RE_SANITIZE_SURVEY = re.compile(r"[^\w\s/.-]", re.UNICODE)


def sanitize_survey(survey_no: str) -> str:
    """Sanitize a survey number.

    Allows word chars, whitespace, slashes, dots, hyphens.
    Rejects SQL metacharacters, angle brackets, quotes.

    Args:
        survey_no: Raw survey number string.

    Returns:
        Sanitized survey number, max 50 chars. Empty string on invalid input.
    """
    if not survey_no or not isinstance(survey_no, str):
        return ""
    cleaned = _RE_SANITIZE_SURVEY.sub("", survey_no.strip()[:60])
    return cleaned.strip()[:50]


def validate_market(market: str) -> dict | None:
    """Look up a market in micro_markets and return {id, name, slug} or None.

    Two-phase lookup:
      1. name ILIKE exact match (after sanitize_market normalization)
      2. slug exact match

    Args:
        market: Market name (Yelahanka, Devanahalli, Hebbal, etc.)

    Returns:
        dict with id(UUID), name(str), slug(str), or None if not found/DB error.
        Never raises.
    """
    if not market:
        return None
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine(pool_size=2, max_overflow=1).connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, name, slug FROM micro_markets WHERE name ILIKE :m LIMIT 1"
                ),
                {"m": market},
            ).fetchone()
            if row:
                return {"id": row[0], "name": str(row[1]), "slug": str(row[2])}
            slug = sanitize_market(market).lower().replace(" ", "-")
            row = conn.execute(
                text(
                    "SELECT id, name, slug FROM micro_markets WHERE slug = :slug LIMIT 1"
                ),
                {"slug": slug},
            ).fetchone()
            if row:
                return {"id": row[0], "name": str(row[1]), "slug": str(row[2])}
    except Exception as exc:
        logger.warning("[validate_market] lookup failed for '{}': {}", market, exc)
    return None


class MarketCache:
    """Dict-based TTL cache for intel module results. Thread-safe.

    Replicates the GDVEstimator pattern from utils/irr_model.py.
    Positive results: 15min TTL. Negative/empty results: 5min TTL.

    Thread-safety: all public methods hold a reentrant lock.
    Memory bound: callers use bounded namespace keys (market names), so
    worst-case is len(known_markets) * len(modules) ≈ 20 * 5 = 100 entries.

    Usage:
        cache = MarketCache()
        data = cache.get("market_pulse", "Yelahanka")
        if data is None:
            data = compute(...)
            cache.set("market_pulse", "Yelahanka", data)
    """

    POSITIVE_TTL: float = 900.0
    NEGATIVE_TTL: float = 300.0

    def __init__(self):
        self._lock = threading.RLock()
        self._store: dict[str, dict[str, tuple[float, Any]]] = {}

    def get(self, namespace: str, key: str) -> Any:
        with self._lock:
            ns = self._store.get(namespace)
            if ns is None:
                return None
            entry = ns.get(key)
            if entry is None:
                return None
            expiry, value = entry
            if _time.time() >= expiry:
                ns.pop(key, None)
                if not ns:
                    self._store.pop(namespace, None)
                return None
            return value

    def set(self, namespace: str, key: str, value: Any, is_positive: bool = True):
        with self._lock:
            ns = self._store.setdefault(namespace, {})
            ttl = self.POSITIVE_TTL if is_positive else self.NEGATIVE_TTL
            ns[key] = (_time.time() + ttl, value)

    def invalidate(self, namespace: str, key: str | None = None):
        with self._lock:
            if key is None:
                self._store.pop(namespace, None)
            else:
                ns = self._store.get(namespace)
                if ns:
                    ns.pop(key, None)
                    if not ns:
                        self._store.pop(namespace, None)

    def clear(self):
        with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return sum(len(ns) for ns in self._store.values())


def timed_intel_query(query_name: str):
    """Wrap a query block with Prometheus timing label.

    Gracefully degrades to nullcontext when Prometheus/metrics not configured.
    Never raises.

    Args:
        query_name: Label for the Prometheus histogram (e.g. "market_brief").

    Returns:
        Context manager that records query duration.
    """
    try:
        from utils.db import timed_query

        return timed_query(query_name)
    except (ImportError, Exception):
        from contextlib import nullcontext

        return nullcontext()
