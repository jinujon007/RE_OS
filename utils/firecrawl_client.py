"""Firecrawl API client — thread-safe, instrumented, rate-limited.

Public surface:
  scrape_url(url, timeout=30) -> str | None
  search_query(query, max_results=5, timeout=30) -> list[dict]
  _reset_count() -> None        (reset per-run cap)
  _get_count() -> int            (current request count)

Architecture:
  - Fallback-only: called after Scrapling/Playwright/requests all fail
  - Thread-safe: Lock guards the per-run counter; atomic acquire operation
  - Rate-limit aware: 429/5xx get 1 retry with 1s backoff
  - Instrumented: Prometheus counters + histogram for SLO observability
  - Keyless grace: FIRECRAWL_API_KEY="" -> return None/[] without exception
"""

import threading
import time
from contextlib import contextmanager

import httpx
from loguru import logger

from config.metrics import (
    firecrawl_duration_seconds,
    firecrawl_errors_total,
    firecrawl_requests_total,
)
from config.settings import FIRECRAWL_API_KEY, FIRECRAWL_BASE_URL

_MAX_REQUESTS_PER_RUN = 10
_request_count = 0
_request_lock = threading.Lock()


def _reset_count():
    global _request_count
    with _request_lock:
        _request_count = 0


def _get_count() -> int:
    with _request_lock:
        return _request_count


@contextmanager
def _acquire_slot():
    """Atomically check + claim one request slot.

    Yields True if slot available, False if at capacity.
    Thread-safe: lock held across check and increment.
    """
    global _request_count
    with _request_lock:
        if _request_count >= _MAX_REQUESTS_PER_RUN:
            yield False
            return
        _request_count += 1
        yield True


def _build_client(timeout: int = 30) -> httpx.Client:
    """Create a Firecrawl HTTP client with sane defaults.

    Uses short keepalive pool (2 conns) since this is a low-volume fallback.
    Split connect/read timeouts for better error diagnostics.
    """
    base = FIRECRAWL_BASE_URL.rstrip("/")
    return httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"},
        timeout=httpx.Timeout(timeout, connect=10.0, read=timeout, pool=5.0),
        limits=httpx.Limits(max_keepalive_connections=2, max_connections=4),
    )


def _should_retry(status_code: int, attempt: int, max_attempts: int) -> bool:
    """Return True if we should retry this status code."""
    return attempt < max_attempts and status_code in {429, 502, 503, 504}


def _safe_post(
    client: httpx.Client, endpoint: str, payload: dict, operation: str, url_or_query: str
) -> dict | None:
    """POST to Firecrawl, returning parsed JSON or None on failure.

    Handles HTTP errors, connection errors, timeouts, and non-JSON responses.
    All error paths increment Prometheus error counters.
    """
    try:
        resp = client.post(endpoint, json=payload)
    except httpx.TimeoutException as exc:
        firecrawl_errors_total.labels(operation=operation, code="timeout").inc()
        logger.warning(f"[Firecrawl] {operation} timeout ({url_or_query[:60]}): {exc}")
        return None
    except httpx.ConnectError as exc:
        firecrawl_errors_total.labels(operation=operation, code="connection").inc()
        logger.warning(f"[Firecrawl] {operation} connection error ({url_or_query[:60]}): {exc}")
        return None
    except Exception as exc:
        firecrawl_errors_total.labels(operation=operation, code="unknown").inc()
        logger.warning(f"[Firecrawl] {operation} failed ({url_or_query[:60]}): {exc}")
        return None

    if resp.status_code >= 400:
        firecrawl_errors_total.labels(operation=operation, code=str(resp.status_code)).inc()
        logger.warning(
            f"[Firecrawl] {operation} HTTP {resp.status_code} ({url_or_query[:60]})"
        )
        return None

    try:
        data = resp.json()
        firecrawl_requests_total.labels(operation=operation, status="success").inc()
        return data
    except Exception as exc:
        firecrawl_errors_total.labels(operation=operation, code="decode").inc()
        logger.warning(f"[Firecrawl] {operation} non-JSON response ({url_or_query[:60]}): {exc}")
        return None


def scrape_url(url: str, timeout: int = 30) -> str | None:
    """Scrape a URL via Firecrawl, returning clean markdown.

    Returns None if: no API key, cap reached, empty content, or any error.
    Retries once on 429/5xx with 1s backoff.
    """
    if not FIRECRAWL_API_KEY:
        logger.debug("[Firecrawl] No API key — skipping scrape")
        return None

    with _acquire_slot() as acquired:
        if not acquired:
            logger.warning(f"[Firecrawl] Hit max {_MAX_REQUESTS_PER_RUN} req/run cap — skipping {url}")
            return None

    payload = {"url": url, "formats": ["markdown"]}
    max_attempts = 2

    for attempt in range(1, max_attempts + 1):
        t0 = time.perf_counter()
        client = _build_client(timeout)
        try:
            data = _safe_post(client, "/v1/scrape", payload, "scrape", url)
        finally:
            client.close()

        elapsed = time.perf_counter() - t0
        firecrawl_duration_seconds.labels(operation="scrape").observe(elapsed)

        if data is None:
            if attempt < max_attempts:
                logger.info(f"[Firecrawl] scrape {url} failed (attempt {attempt}) — retrying in 1s")
                time.sleep(1.0)
                continue
            return None

        content = data.get("data", {}).get("markdown", "")
        if content:
            logger.debug(f"[Firecrawl] scrape {url} -> {len(content)} chars")
            return content
        logger.debug(f"[Firecrawl] scrape {url} returned empty content")
        return None

    return None


def search_query(query: str, max_results: int = 5, timeout: int = 30) -> list[dict]:
    """Search via Firecrawl, returning up to max_results entries.

    Returns [] if: no API key, cap reached, or any error.
    Retries once on 429/5xx with 1s backoff.
    """
    if not FIRECRAWL_API_KEY:
        logger.debug("[Firecrawl] No API key — skipping search")
        return []

    with _acquire_slot() as acquired:
        if not acquired:
            logger.warning(f"[Firecrawl] Hit max {_MAX_REQUESTS_PER_RUN} req/run cap — skipping search")
            return []

    payload = {"query": query, "maxResults": max_results, "formats": ["markdown"]}
    max_attempts = 2

    for attempt in range(1, max_attempts + 1):
        t0 = time.perf_counter()
        client = _build_client(timeout)
        try:
            data = _safe_post(client, "/v1/search", payload, "search", query)
        finally:
            client.close()

        elapsed = time.perf_counter() - t0
        firecrawl_duration_seconds.labels(operation="search").observe(elapsed)

        if data is None:
            if attempt < max_attempts:
                logger.info(f"[Firecrawl] search '{query[:40]}' failed (attempt {attempt}) — retrying in 1s")
                time.sleep(1.0)
                continue
            return []

        results = data.get("data", [])
        logger.debug(f"[Firecrawl] search '{query[:40]}' -> {len(results)} results")
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("markdown", ""),
            }
            for r in results
        ]

    return []
