"""Google Maps Distance Matrix commute scorer for CorridorScorer.

Public surface:
  CommuteScorer.score(lat, lon) -> dict | None
    Returns {manyata_minutes, kial_minutes, hebbal_minutes, composite_score}
    or None if GOOGLE_MAPS_API_KEY is not set.

Architecture:
  - Batched API: all 3 destinations in one Distance Matrix call (not 3 sequential)
  - Connection pooling: module-level httpx + Redis singletons, no per-call overhead
  - Thread-safe: Lock guards the per-run counter; shared-state design documented
  - Instrumented: Prometheus counters + histogram for observability
  - Keyless grace: GOOGLE_MAPS_API_KEY="" -> return None without exception
  - Redis cache: keyed by lat/lon rounded to 3 decimals, TTL 7 days
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from typing import Any

import httpx
from loguru import logger

from config.metrics import (
    google_maps_duration_seconds,
    google_maps_errors_total,
    google_maps_requests_total,
)

__all__ = [
    "CommuteScorer",
    "score",
    "_reset_count",
    "_get_count",
]

# ── Destination definitions ───────────────────────────────────────────────────
# Coordinates from scrapers/mobility_scout.py (verified Google Maps coords).
_DESTINATIONS: list[dict[str, Any]] = [
    {
        "key": "manyata_minutes",
        "name": "Manyata Tech Park",
        "lat": 13.0535,
        "lng": 77.6184,
        "weight": 0.40,
    },
    {
        "key": "kial_minutes",
        "name": "KIAL (BIAL Airport)",
        "lat": 13.1979,
        "lng": 77.7063,
        "weight": 0.35,
    },
    {
        "key": "hebbal_minutes",
        "name": "Hebbal",
        "lat": 13.0440,
        "lng": 77.5920,
        "weight": 0.25,
    },
]

# Guard: weights must sum to 1.0 for composit scoring to be valid.
assert abs(sum(d["weight"] for d in _DESTINATIONS) - 1.0) < 0.001, (
    f"CommuteScorer destination weights must sum to 1.0, got "
    f"{sum(d['weight'] for d in _DESTINATIONS)}"
)

_BASE_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
_CACHE_KEY_PREFIX = "commute"
_MAX_RETRIES = 2
_MAX_REQUESTS_PER_RUN = 10
_BASE_RETRY_DELAY_S = 1.0
_MAX_RETRY_DELAY_S = 5.0

# ── Singleton connections ────────────────────────────────────────────────────
# Module-level singletons for connection pooling. _HTTPX_CLIENT is shared across
# all CommuteScorer instances within a process. _get_redis() returns a lazy
# singleton Redis client. Both degrade gracefully on failure.
_HTTPX_CLIENT: httpx.Client | None = None
_HTTPX_LOCK = threading.Lock()
_REDIS_CLIENT: Any = None
_REDIS_LOCK = threading.Lock()

# ── Run-level counter (shared across all instances in a process) ─────────────
# This is intentionally module-level: the per-run cap applies to the entire
# process, not per instance. Two CommuteScorer instances within one pipeline
# run share the 10-request budget.
_request_count = 0
_request_lock = threading.Lock()


def _reset_count():
    global _request_count
    with _request_lock:
        _request_count = 0


def _get_count() -> int:
    with _request_lock:
        return _request_count


def _acquire_slot() -> bool:
    global _request_count
    with _request_lock:
        if _request_count >= _MAX_REQUESTS_PER_RUN:
            return False
        _request_count += 1
        return True


def _get_httpx() -> httpx.Client | None:
    """Return module-level httpx session, creating on first call.

    Thread-safe: lock guards creation. Never closed by callers — lives
    for process lifetime. Degrades: returns None on connection error.
    """
    global _HTTPX_CLIENT
    if _HTTPX_CLIENT is not None:
        return _HTTPX_CLIENT
    with _HTTPX_LOCK:
        if _HTTPX_CLIENT is not None:
            return _HTTPX_CLIENT
        try:
            _HTTPX_CLIENT = httpx.Client(
                timeout=httpx.Timeout(15.0, connect=10.0),
                limits=httpx.Limits(
                    max_keepalive_connections=2, max_connections=4
                ),
            )
        except Exception:
            return None
    return _HTTPX_CLIENT


def _get_redis():
    """Return module-level Redis client, creating on first call.

    Thread-safe: lock guards creation. Returns None if Redis is
    unavailable or REDIS_URL is not set — callers must handle None.
    """
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT
    with _REDIS_LOCK:
        if _REDIS_CLIENT is not None:
            return _REDIS_CLIENT
        try:
            from config.settings import REDIS_URL as _REDIS_URL

            if _REDIS_URL:
                import redis as _redis_mod

                _REDIS_CLIENT = _redis_mod.from_url(
                    _REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
        except Exception:
            pass
    return _REDIS_CLIENT


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter: base * 2^(attempt-1) + random(0, 0.5).

    Prevents thundering herd on rate-limit recovery. Caps at _MAX_RETRY_DELAY_S.
    """
    delay = min(_MAX_RETRY_DELAY_S, _BASE_RETRY_DELAY_S * (2 ** (attempt - 1)))
    jitter = random.uniform(0, 0.5)
    return round(delay + jitter, 2)


def _api_key() -> str:
    return os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()


def _cache_key(lat: float, lon: float) -> str:
    lat_s = f"{lat:.3f}"
    lon_s = f"{lon:.3f}"
    return f"{_CACHE_KEY_PREFIX}:{lat_s},{lon_s}"


def _read_cache(key: str) -> dict | None:
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def _write_cache(key: str, data: dict):
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(key, _CACHE_TTL_SECONDS, json.dumps(data))
    except Exception:
        pass


def _extract_minutes(element: dict) -> float | None:
    """Extract drive-time minutes from a single Distance Matrix element.

    Returns None on any status other than OK, or if duration is missing.
    ZERO_RESULTS is a valid API response meaning no route exists — logs at
    debug level, returns None.
    """
    status = element.get("status")
    if status != "OK":
        if status == "ZERO_RESULTS":
            logger.debug(
                "[CommuteScorer] no route found (ZERO_RESULTS) for element"
            )
        return None
    duration = element.get("duration", {})
    seconds = duration.get("value")
    if seconds is None:
        return None
    return round(seconds / 60, 1)


def _normalize_score(minutes: float | None) -> float:
    """Minutes → 0-100 score. 0 min = 100, 60+ min = 0, linear interpolation."""
    if minutes is None:
        return 0.0
    score = max(0.0, 100.0 - minutes * (100.0 / 60.0))
    return round(score, 1)


def score(lat: float, lon: float) -> dict | None:
    """Convenience function: create a CommuteScorer, score, close.

    Prefer this when you need a single score call. Use the class directly
    when you need to score multiple locations in sequence.
    """
    scorer = CommuteScorer()
    try:
        return scorer.score(lat, lon)
    finally:
        scorer.close()


class CommuteScorer:
    """Score a parcel's location by commute time to key employment hubs.

    Uses Google Maps Distance Matrix API. All 3 destinations (Manyata,
    KIAL, Hebbal) are queried in a single batched API call. Returns None
    when key is not set; Redis cache hit bypasses API.

    Connection reuse:
      - httpx session: module-level singleton, shared across all instances
      - Redis client: module-level singleton, shared across all instances
      - Both degrade gracefully on failure (return None)

    Thread safety:
      - Per-run counter is module-level, shared by all instances in the
        same process — intentional, acts as a global circuit breaker.
        Two simultaneous sessions share the 10-request budget.
      - Singleton connections are created once under lock, then read-only.
    """

    def __init__(self):
        self.api_key = _api_key()

    # ── Public API ────────────────────────────────────────────────────────

    def score(self, lat: float, lon: float) -> dict | None:
        """Score a lat/lon by commute time to Manyata, KIAL, Hebbal.

        Args:
            lat: Latitude of parcel or point.
            lon: Longitude of parcel or point.

        Returns:
            dict with keys: manyata_minutes, kial_minutes, hebbal_minutes,
            composite_score (0-100). Returns None if GOOGLE_MAPS_API_KEY
            is not set or all destinations failed.

        Scoring scale (composite_score, 0-100):
            ≥70: Excellent commute — within 18 min avg to all 3 hubs
            ≥50: Good — within 30 min avg
            ≥30: Moderate — within 42 min avg
            <30: Poor — beyond 42 min avg
        """
        if not self.api_key:
            logger.debug("[CommuteScorer] No API key — returning None")
            return None

        if not _acquire_slot():
            logger.warning(
                f"[CommuteScorer] Hit max {_MAX_REQUESTS_PER_RUN} req/run cap"
            )
            return None

        key = _cache_key(lat, lon)
        cached = _read_cache(key)
        if cached is not None:
            logger.debug(f"[CommuteScorer] Cache hit for {key}")
            return cached

        result = self._fetch_and_score(lat, lon)
        if result is not None:
            _write_cache(key, result)
        return result

    # ── Private implementation ────────────────────────────────────────────

    def _fetch_and_score(self, lat: float, lon: float) -> dict | None:
        """Call Distance Matrix API (batched: all 3 destinations in one call).

        Returns:
            dict with per-destination minutes + composite_score, or None if
            the API call failed entirely.
        """
        minutes = self._query_batch(lat, lon)

        if minutes is None or all(v is None for v in minutes.values()):
            logger.warning(
                "[CommuteScorer] All destination queries failed for ({}, {})",
                lat,
                lon,
            )
            return None

        composite = 0.0
        for dest in _DESTINATIONS:
            val = minutes.get(dest["key"])
            norm = _normalize_score(val)
            composite += norm * dest["weight"]
        composite = round(composite, 1)

        result = {
            "manyata_minutes": minutes.get("manyata_minutes"),
            "kial_minutes": minutes.get("kial_minutes"),
            "hebbal_minutes": minutes.get("hebbal_minutes"),
            "composite_score": composite,
        }
        logger.info(
            "[CommuteScorer] ({:.4f}, {:.4f}) → composite {}",
            lat,
            lon,
            composite,
        )
        return result

    def _query_batch(
        self, origin_lat: float, origin_lon: float
    ) -> dict[str, float | None] | None:
        """Query Distance Matrix with all 3 destinations in one batched call.

        Uses pipe-delimited destinations format:
          origins=lat,lon&destinations=lat1,lon1|lat2,lon2|lat3,lon3

        Applies exponential backoff with jitter on retryable errors (timeout,
        connection reset, 429, OVER_QUERY_LIMIT). Non-retryable errors (4xx,
        REQUEST_DENIED, INVALID_REQUEST) return None immediately.

        Returns dict mapping destination keys to minutes, or None on total
        failure. Partial failures (some destinations return ZERO_RESULTS)
        still return a dict with None for failed destinations.
        """
        dest_labels = ", ".join(d["name"] for d in _DESTINATIONS)
        logger.debug(
            "[CommuteScorer] querying {} destinations from ({}, {}): {}",
            len(_DESTINATIONS), origin_lat, origin_lon, dest_labels,
        )

        dest_str = "|".join(
            f"{d['lat']},{d['lng']}" for d in _DESTINATIONS
        )
        params = {
            "origins": f"{origin_lat},{origin_lon}",
            "destinations": dest_str,
            "key": self.api_key,
            "mode": "driving",
        }

        client = _get_httpx()
        if client is None:
            logger.error("[CommuteScorer] httpx client unavailable")
            return None

        for attempt in range(1, _MAX_RETRIES + 1):
            t0 = time.perf_counter()
            try:
                resp = client.get(_BASE_URL, params=params)
            except httpx.TimeoutException as exc:
                google_maps_errors_total.labels(code="timeout").inc()
                if attempt < _MAX_RETRIES:
                    delay = _retry_delay(attempt)
                    logger.warning(
                        "[CommuteScorer] timeout ({}, {}) attempt {} — retry in {:.1f}s: {}",
                        origin_lat, origin_lon, attempt, delay, exc,
                    )
                    time.sleep(delay)
                    continue
                logger.warning(
                    "[CommuteScorer] timeout ({}, {}) — exhausted retries",
                    origin_lat, origin_lon,
                )
                return None
            except httpx.ConnectError as exc:
                google_maps_errors_total.labels(code="connection").inc()
                if attempt < _MAX_RETRIES:
                    delay = _retry_delay(attempt)
                    logger.warning(
                        "[CommuteScorer] connection error ({}, {}) attempt {} — retry in {:.1f}s: {}",
                        origin_lat, origin_lon, attempt, delay, exc,
                    )
                    time.sleep(delay)
                    continue
                logger.warning(
                    "[CommuteScorer] connection error ({}, {}) — exhausted retries",
                    origin_lat, origin_lon,
                )
                return None
            except Exception as exc:
                google_maps_errors_total.labels(code="unknown").inc()
                logger.warning(
                    "[CommuteScorer] request failed ({}, {}): {}",
                    origin_lat, origin_lon, exc,
                )
                return None

            elapsed = time.perf_counter() - t0
            google_maps_duration_seconds.observe(elapsed)

            if resp.status_code == 429:
                google_maps_errors_total.labels(code="429").inc()
                if attempt < _MAX_RETRIES:
                    delay = _retry_delay(attempt)
                    logger.warning(
                        "[CommuteScorer] rate-limited (429) — retry in {:.1f}s",
                        delay,
                    )
                    time.sleep(delay)
                    continue
                logger.warning(
                    "[CommuteScorer] rate-limited (429) — exhausted retries"
                )
                return None

            if resp.status_code >= 400:
                google_maps_errors_total.labels(
                    code=str(resp.status_code)
                ).inc()
                logger.warning(
                    "[CommuteScorer] HTTP {} ({}, {}) — not retried",
                    resp.status_code, origin_lat, origin_lon,
                )
                return None

            try:
                data = resp.json()
                google_maps_requests_total.labels(status="success").inc()
            except Exception as exc:
                google_maps_errors_total.labels(code="decode").inc()
                logger.warning(
                    "[CommuteScorer] non-JSON response: {}", exc,
                )
                return None

            api_status = data.get("status")
            if api_status == "OVER_QUERY_LIMIT":
                google_maps_errors_total.labels(code="over_query_limit").inc()
                if attempt < _MAX_RETRIES:
                    delay = _retry_delay(attempt)
                    logger.warning(
                        "[CommuteScorer] OVER_QUERY_LIMIT — retry in {:.1f}s",
                        delay,
                    )
                    time.sleep(delay)
                    continue
                logger.warning(
                    "[CommuteScorer] OVER_QUERY_LIMIT — exhausted retries"
                )
                return None

            if api_status == "MAX_ELEMENTS_EXCEEDED":
                google_maps_errors_total.labels(
                    code="max_elements_exceeded"
                ).inc()
                logger.error(
                    "[CommuteScorer] MAX_ELEMENTS_EXCEEDED for 3 destinations "
                    "— unlikely with current config, check API plan"
                )
                return None

            if api_status not in ("OK",):
                google_maps_errors_total.labels(code="api_error").inc()
                logger.warning(
                    "[CommuteScorer] API status {}: {}",
                    api_status, data.get("error_message", ""),
                )
                return None

            rows = data.get("rows", [])
            if not rows:
                logger.debug(
                    "[CommuteScorer] no rows in API response ({}, {})",
                    origin_lat, origin_lon,
                )
                return None

            elements = rows[0].get("elements", [])
            if not elements:
                logger.debug(
                    "[CommuteScorer] no elements in API response ({}, {})",
                    origin_lat, origin_lon,
                )
                return None

            if len(elements) < len(_DESTINATIONS):
                logger.warning(
                    "[CommuteScorer] expected {} elements, got {} — some destinations missing",
                    len(_DESTINATIONS), len(elements),
                )

            result: dict[str, float | None] = {}
            for i, dest in enumerate(_DESTINATIONS):
                if i < len(elements):
                    result[dest["key"]] = _extract_minutes(elements[i])
                else:
                    result[dest["key"]] = None

            return result

        return None

    def close(self):
        """No-op: httpx session is module-level and process-scoped.

        Kept for backward compatibility with code that calls close().
        """
        pass
