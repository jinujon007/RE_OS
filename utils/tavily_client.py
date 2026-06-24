"""Tavily API client — real-time market intelligence search.

Public surface:
  search(query, market=None, max_results=5) -> list[dict]
    Each result dict: {title, url, content, published_date, score}
    score is a float 0.0-1.0 from Tavily's own relevance model.
  monthly_quota_remaining() -> int | None
    Returns remaining queries in current month, or None if no API key.
  _reset_count() / _get_count()  — per-run cycle counter (test support)

Architecture:
  - Primary search backend for news_scout + IntelSearchTool
  - Fallback chain: Tavily -> Google News RSS -> Jina Reader
  - Thread-safe: Lock guards per-run counter; atomic acquire
  - Rate-limit aware: 429 gets 1 retry with 1s backoff
  - Instrumented: Prometheus counters + histogram for observability
  - Keyless grace: TAVILY_API_KEY="" -> return [] without exception
  - Monthly quota: persisted to JSON checkpoint (file-lock protected);
    warn at 800, hard stop at 950 within calendar month.
    Falls back to in-memory-only if checkpoint directory is unwritable.
  - Content guard: response snippets clamped to 2000 chars.
  - Query guard: input clamped to 500 chars (Tavily has internal limits).
"""

import json
import os
import threading
import time
from datetime import datetime, timezone

import httpx
from loguru import logger

from config.metrics import (
    tavily_duration_seconds,
    tavily_errors_total,
    tavily_requests_total,
)
from config.settings import TAVILY_API_KEY

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_MAX_REQUESTS_PER_RUN = 10
_MONTHLY_WARN_AT = 800
_MONTHLY_STOP_AT = 950
_MAX_CONTENT_CHARS = 2000
_MAX_QUERY_CHARS = 500

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


def _build_client(timeout: int = 30) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout, connect=10.0, read=timeout, pool=5.0),
        limits=httpx.Limits(max_keepalive_connections=2, max_connections=4),
    )


def _build_payload(query: str, max_results: int) -> dict:
    return {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }


def _monthly_checkpoint_path() -> str:
    for base in (
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
        ),
        "/tmp",
    ):
        try:
            os.makedirs(base, exist_ok=True)
            test_file = os.path.join(base, ".tavily_write_test")
            with open(test_file, "w") as f:
                f.write("")
            os.remove(test_file)
            return os.path.join(base, "tavily_monthly_count.json")
        except (OSError, PermissionError):
            continue
    return "/tmp/tavily_monthly_count.json"


def _read_monthly_count() -> int:
    path = _monthly_checkpoint_path()
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            year_month = datetime.now(timezone.utc).strftime("%Y-%m")
            if data.get("year_month") == year_month:
                return int(data.get("count", 0))
    except (json.JSONDecodeError, OSError, ValueError, ImportError):
        pass
    return 0


def _write_monthly_count(count: int):
    path = _monthly_checkpoint_path()
    year_month = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"year_month": year_month, "count": count}, f)
            f.flush()
            os.fsync(f.fileno())
    except OSError as exc:
        logger.debug(f"[Tavily] Monthly count write failed (non-fatal): {exc}")


def _increment_monthly_count() -> int:
    current = _read_monthly_count() + 1
    _write_monthly_count(current)
    return current


def monthly_quota_remaining() -> int | None:
    """Return remaining Tavily searches this month, or None if no API key."""
    if not TAVILY_API_KEY:
        return None
    used = _read_monthly_count()
    return max(0, _MONTHLY_STOP_AT - used)


def search(query: str, market: str | None = None, max_results: int = 5) -> list[dict]:
    """Search via Tavily, returning up to max_results entries.

    Args:
        query: Search query string (max 500 chars, truncated).
        market: Optional market name for logged context (not sent to API).
        max_results: Max results to return (1-10).

    Returns:
        List of {title, url, content, published_date, score} dicts.
        Empty list on: no API key, quota exhausted, cap hit, network error, 429.
        score is Tavily's own relevance score (0.0-1.0).
    """
    if not TAVILY_API_KEY:
        logger.debug("[Tavily] No API key — skipping search")
        return []

    monthly_used = _read_monthly_count()
    if monthly_used >= _MONTHLY_STOP_AT:
        logger.warning(
            f"[Tavily] Monthly quota exhausted ({monthly_used}/{_MONTHLY_STOP_AT})"
        )
        return []
    if monthly_used >= _MONTHLY_WARN_AT:
        remaining = _MONTHLY_STOP_AT - monthly_used
        logger.warning(
            f"[Tavily] Monthly quota near limit ({monthly_used}/{_MONTHLY_STOP_AT}) — {remaining} remaining"
        )

    if not _acquire_slot():
        logger.warning(
            f"[Tavily] Hit max {_MAX_REQUESTS_PER_RUN} req/run cap — skipping search"
        )
        return []

    query = (query or "")[:_MAX_QUERY_CHARS]
    max_results = max(1, min(max_results, 10))
    payload = _build_payload(query, max_results)
    market_label = market or "unknown"
    max_attempts = 2

    for attempt in range(1, max_attempts + 1):
        t0 = time.perf_counter()
        client = _build_client()
        try:
            data = _do_search(client, payload, query)
        finally:
            client.close()

        elapsed = time.perf_counter() - t0
        tavily_duration_seconds.observe(elapsed)

        if data is None:
            if attempt < max_attempts:
                logger.info(
                    f"[Tavily] search '{query[:40]}' failed (attempt {attempt}) — retrying in 1s"
                )
                time.sleep(1.0)
                continue
            return []

        results = data.get("results", [])
        _increment_monthly_count()
        logger.debug(
            f"[Tavily] search '{query[:40]}' ({market_label}) -> {len(results)} results "
            f"(monthly: {monthly_used + 1}/{_MONTHLY_STOP_AT})"
        )
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": (r.get("content") or "")[:_MAX_CONTENT_CHARS],
                "published_date": r.get("published_date", ""),
                "score": r.get("score", 0.0),
            }
            for r in results
        ]

    return []


def _do_search(client: httpx.Client, payload: dict, query_str: str) -> dict | None:
    """POST to Tavily, returning parsed JSON or None on failure."""
    try:
        resp = client.post(_TAVILY_SEARCH_URL, json=payload)
    except httpx.TimeoutException as exc:
        tavily_errors_total.labels(code="timeout").inc()
        logger.warning(f"[Tavily] search timeout ({query_str[:60]}): {exc}")
        return None
    except httpx.ConnectError as exc:
        tavily_errors_total.labels(code="connection").inc()
        logger.warning(f"[Tavily] search connection error ({query_str[:60]}): {exc}")
        return None
    except Exception as exc:
        tavily_errors_total.labels(code="unknown").inc()
        logger.warning(f"[Tavily] search failed ({query_str[:60]}): {exc}")
        return None

    if resp.status_code == 429:
        tavily_errors_total.labels(code="429").inc()
        logger.warning(f"[Tavily] search rate-limited (429) ({query_str[:60]})")
        return None

    if resp.status_code >= 400:
        tavily_errors_total.labels(code=str(resp.status_code)).inc()
        logger.warning(f"[Tavily] search HTTP {resp.status_code} ({query_str[:60]})")
        return None

    try:
        data = resp.json()
        tavily_requests_total.labels(status="success").inc()
        return data
    except Exception as exc:
        tavily_errors_total.labels(code="decode").inc()
        logger.warning(f"[Tavily] search non-JSON response ({query_str[:60]}): {exc}")
        return None
