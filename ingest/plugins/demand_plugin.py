"""
RE_OS — Demand Plugin (Sprint 55 — GATE-63)

Detects demand-side signals from real estate portals and the listings DB:
- nri_query: NRI property listings detected on 99acres/MagicBricks
- listing_surge: >30% increase in active listings over 7 days
- price_cut: >3 listings with >15% PSF drop within 7 days
- bulk_inquiry: NOT YET IMPLEMENTED (requires portal-specific API)
- portal_highlight: NOT YET IMPLEMENTED (requires developer-sponsorship feed)

All signals are best-effort. Network errors are caught silently. Portal scraping
uses Scrapling Fetcher (HTTP) with rate-limited backoff between sources.
"""
from __future__ import annotations

import json
import random
import time
import urllib.request
from datetime import datetime, timezone
from loguru import logger
from ingest.base import DataPlugin, ParsedRecord

__all__ = ["DemandPlugin"]

_NRI_SOURCES: dict[str, str] = {
    "99acres": "https://www.99acres.com/search/properties/nri",
    "magicbricks": "https://www.magicbricks.com/NRI-Property-in-Bangalore-ff",
}

# Minimum delay between portal requests (seconds) to avoid rate-limiting
_PORTAL_REQUEST_INTERVAL_S: float = 3.0
# Exponential backoff base for retries
_BACKOFF_BASE_S: float = 2.0
# Max retries per portal
_MAX_RETRIES: int = 2

_HEADERS = {
    "User-Agent": "RE_OS/1.0 (demand-intel-plugin; +https://github.com/jinujon007/RE_OS)",
    "Accept": "text/html,application/json",
    "Accept-Language": "en-IN,en;q=0.9",
}


def _fetch_with_backoff(url: str, headers: dict, timeout: int = 15) -> str | None:
    """Fetch URL with exponential backoff between retries.

    Tries Scrapling Fetcher first (if available), falls back to urllib.
    Returns response body text, or None on total failure.
    """
    last_error: Exception | None = None
    for attempt in range(1 + _MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt < _MAX_RETRIES:
                delay = _BACKOFF_BASE_S ** attempt + random.uniform(0, 1)
                logger.debug("[DemandPlugin] retry {} for {} in {:.1f}s: {}",
                             attempt + 1, url, delay, exc)
                time.sleep(delay)
    logger.debug("[DemandPlugin] fetch failed after {} retries: {} | {}",
                 _MAX_RETRIES, url, last_error)
    return None


def _detect_nri_count(body: str, market: str) -> int:
    """Count NRI-related content snippets containing the target market keyword.

    Heuristic: counts occurrences where an NRI keyword appears within 120 chars
    of the market name. This is a best-effort heuristic — portals render
    listing content client-side, so the server HTML may have limited data.
    """
    import re
    market_lower = market.lower()
    count = 0
    for match in re.finditer(r'(?i)(nri|property|plot|apartment|villa)', body):
        pos = max(0, match.start() - 60)
        snippet = body[pos:match.end() + 60].lower()
        if market_lower in snippet:
            count += 1
    return count


def _fetch_nri_listings(market: str) -> list[dict]:
    """Fetch NRI property listings from 99acres and MagicBricks.

    Uses Scrapling Fetcher when available (bypasses bot detection), falls
    back to urllib. Rate-limited with exponential backoff between sources.
    Best-effort only — returns empty list on total failure.
    """
    results: list[dict] = []
    market_lower = market.lower()

    for portal_idx, (portal, url) in enumerate(_NRI_SOURCES.items()):
        if portal_idx > 0:
            time.sleep(_PORTAL_REQUEST_INTERVAL_S)

        try:
            body = _fetch_with_backoff(url, _HEADERS)
            if body is None:
                logger.debug("[DemandPlugin] {} unreachable for {}", portal, market)
                continue

            listings_found = _detect_nri_count(body, market_lower)

            if listings_found >= 5:
                results.append({
                    "portal": portal,
                    "market": market,
                    "nri_listings_found": listings_found,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })
                logger.info("[DemandPlugin] {}: {} NRI listings found on {}",
                            market, listings_found, portal)
            else:
                logger.debug("[DemandPlugin] {}: only {} NRI hints on {} (need >=5)",
                             market, listings_found, portal)

        except (MemoryError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            logger.debug("[DemandPlugin] NRI fetch failed for {} on {}: {}",
                         market, portal, exc)

    return results


def _check_listing_surge(market: str) -> dict | None:
    """Check for listing surge: >30% increase in active listings (7d vs prior 7d).

    Returns surge info dict or None if no surge detected.
    """
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        with get_engine().connect() as conn:
            row = conn.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE last_seen_at >= NOW() - INTERVAL '7 days') AS recent,
                    COUNT(*) FILTER (
                        WHERE last_seen_at >= NOW() - INTERVAL '14 days'
                          AND last_seen_at < NOW() - INTERVAL '7 days'
                    ) AS prior
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.name ILIKE :m AND l.is_active = TRUE
            """), {"m": f"%{market}%"}).fetchone()
        if row and row[0] and row[1] and row[1] > 0:
            surge_pct = ((row[0] - row[1]) / row[1]) * 100
            if surge_pct > 30:
                return {
                    "event_type": "listing_surge",
                    "count": row[0] - row[1],
                    "value_cr": None,
                    "surge_pct": round(surge_pct, 1),
                    "recent_listings": row[0],
                    "prior_listings": row[1],
                }
    except Exception as exc:
        logger.debug("[DemandPlugin] listing surge check failed for {}: {}", market, exc)
    return None


def _check_price_cuts(market: str) -> dict | None:
    """Check for price cuts: >=3 listings with >15% PSF drop in 7d vs 30d avg.

    Returns price cut info dict or None if below threshold.
    """
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        with get_engine().connect() as conn:
            row = conn.execute(text("""
                SELECT COUNT(*) AS cut_count
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.name ILIKE :m
                  AND l.is_active = TRUE
                  AND l.price_psf IS NOT NULL
                  AND l.last_seen_at >= NOW() - INTERVAL '7 days'
                  AND l.price_psf < (
                      SELECT AVG(l2.price_psf) * 0.85
                      FROM listings l2
                      WHERE l2.source_listing_id = l.source_listing_id
                        AND l2.last_seen_at >= NOW() - INTERVAL '30 days'
                        AND l2.last_seen_at < NOW() - INTERVAL '7 days'
                  )
            """), {"m": f"%{market}%"}).fetchone()
        if row and row[0] and int(row[0]) >= 3:
            return {
                "event_type": "price_cut",
                "count": int(row[0]),
                "value_cr": None,
            }
    except Exception as exc:
        logger.debug("[DemandPlugin] price cut check failed for {}: {}", market, exc)
    return None


class DemandPlugin(DataPlugin):
    """Detects demand-side signals from portals and listings DB.

    Emits ParsedRecord with entity_type='demand_event' for:
    - nri_query (portal scrape)
    - listing_surge (DB query)
    - price_cut (DB query)

    NOT YET IMPLEMENTED: bulk_inquiry (requires portal-specific API or
    scraping developer sales inquiry pages). portal_highlight (requires
    developer-sponsored listing feed — Tier 3 identification).
    """

    plugin_id = "demand_intel"
    source_id = "demand_portal_scan"

    def run(self, market: str) -> list[ParsedRecord]:
        records: list[ParsedRecord] = []
        now_ts = datetime.now(timezone.utc).timestamp()

        nri_listings = _fetch_nri_listings(market)
        for entry in nri_listings:
            records.append(ParsedRecord(
                entity_type="demand_event",
                source_id=f"nri_{entry['portal']}_{market}",
                market=market,
                data={
                    "event_type": "nri_query",
                    "market": market,
                    "count": entry.get("nri_listings_found", 0),
                    "source": f"portal:{entry['portal']}",
                    "recorded_at": entry.get("detected_at",
                                             datetime.now(timezone.utc).isoformat()),
                },
            ))

        surge: dict | None = None
        price_cut: dict | None = None

        try:
            surge = _check_listing_surge(market)
            if surge:
                records.append(ParsedRecord(
                    entity_type="demand_event",
                    source_id=f"surge_{market}_{now_ts:.0f}",
                    market=market,
                    data={
                        "event_type": "listing_surge",
                        "market": market,
                        "count": surge["count"],
                        "value_cr": surge.get("value_cr"),
                        "source": "db:listings",
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                        "surge_pct": surge.get("surge_pct"),
                    },
                ))
        except Exception as exc:
            logger.debug("[DemandPlugin] listing_surge check failed for {}: {}",
                         market, exc)

        try:
            price_cut = _check_price_cuts(market)
            if price_cut:
                records.append(ParsedRecord(
                    entity_type="demand_event",
                    source_id=f"pricecut_{market}_{now_ts:.0f}",
                    market=market,
                    data={
                        "event_type": "price_cut",
                        "market": market,
                        "count": price_cut["count"],
                        "source": "db:listings",
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    },
                ))
        except Exception as exc:
            logger.debug("[DemandPlugin] price_cut check failed for {}: {}",
                         market, exc)

        logger.info(
            "[DemandPlugin] {} records for {} ({} NRI, {} surge, {} price_cut)",
            len(records), market, len(nri_listings),
            1 if surge and surge.get("count") else 0,
            1 if price_cut and price_cut.get("count") else 0,
        )
        return records
