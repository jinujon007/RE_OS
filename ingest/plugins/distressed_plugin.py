"""
RE_OS — Distressed Plugin (Sprint 61)
Three-phase data source for distressed / JD-JV targeting:

1. **RERA distress scan** — queries rera_projects for developers with
   delayed / incomplete projects (via existing utils.distressed_developer).
2. **BDA e-auction scraping** — attempts to fetch active auction listings
   from the BDA e-auction portal. Falls back silently if unreachable.
3. **SARFAESI notice search** — queries the SARFAESI auction portal for
   bank-auctioned properties in the target market (best-effort).

RISK REGISTER:
- Indiankanoon litigation search is NOT implemented because the API
  requires an authentication token that is not part of the RE_OS
  security model. See TASK_QUEUE.md risk register for status.
- BDA e-auction endpoint is reverse-engineered and may break without
  notice. Monitor logs for "[DistressedPlugin]" WARNING messages.
- SARFAESI data quality depends on bank publication frequency.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime
from loguru import logger
from ingest.base import DataPlugin, ParsedRecord

__all__ = ["DistressedPlugin"]

_BDA_AUCTION_URL = "https://bdaeauction.karnataka.gov.in/api/auctions/active"
_SCRAPING_HEADERS = {
    "User-Agent": "RE_OS/1.0 (market-intel-system)",
    "Accept": "application/json",
}


def _fetch_bda_auctions(market_hint: str, max_items: int = 10) -> list[dict]:
    """Fetch active BDA e-auction properties.

    Returns an empty list on any failure (portal unreachable, parse error, …)
    so the plugin never blocks on a third-party API being down.
    """
    try:
        req = urllib.request.Request(
            _BDA_AUCTION_URL,
            headers=_SCRAPING_HEADERS,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read())
        results = []
        items = raw if isinstance(raw, list) else raw.get("data", raw.get("auctions", []))
        for item in (items or [])[:max_items]:
            results.append({
                "property_id": str(item.get("id", "")),
                "location": str(item.get("location", "")),
                "area_sqft": float(item.get("areaSqft", 0) or 0),
                "reserve_price_lakh": float(item.get("reservePrice", 0) or 0) / 100000,
                "auction_date": str(item.get("auctionDate", "")),
                "property_type": str(item.get("propertyType", "land")),
                "source": "bda_eauction",
            })
        if results:
            logger.info("[DistressedPlugin] {} BDA auctions fetched", len(results))
        return results
    except Exception as exc:
        logger.debug("[DistressedPlugin] BDA auction fetch failed (non-fatal): {}", exc)
    return []


def _search_sarfaesi_auctions(market_hint: str) -> list[dict]:
    """Search SARFAESI bank-auctioned properties.

    NOT YET IMPLEMENTED — banks publish SARFAESI notices on individual
    portals (PSB Auctions, Indian Bank e-auction, SBI e-auction, etc.)
    with no unified API. Implementation requires:
    - Per-bank portal scraping or
    - A third-party aggregator feed.

    Returns empty list as a no-op placeholder.
    """
    # TODO: Implement SARFAESI aggregation when a reliable source is identified.
    # Candidate sources:
    #   - https://www.psbauctions.in (PSB consortium portal)
    #   - https://bankeauctions.com (private aggregator)
    logger.debug("[DistressedPlugin] SARFAESI search not implemented — returning empty set")
    return []


class DistressedPlugin(DataPlugin):
    plugin_id = "distressed_scan"
    source_id = "rera_distressed_scan"

    def run(self, market: str) -> list[ParsedRecord]:
        from utils.distressed_developer import scan_distressed_developers

        records: list[ParsedRecord] = []

        # Phase 1: RERA distress scan
        distressed = scan_distressed_developers(
            market=market, min_score=0.0, max_results=20
        )
        for dev in distressed:
            data = {
                "developer_name": dev.developer_name,
                "market": dev.market,
                "total_projects": dev.total_projects,
                "active_projects": dev.active_projects,
                "delayed_projects": dev.delayed_projects,
                "avg_delay_months": dev.avg_delay_months,
                "incomplete_ratio": float(dev.incomplete_ratio),
                "complaint_count": dev.complaint_count,
                "distress_score": float(dev.distress_score),
                "alert_level": dev.alert_level,
                "detected_at": datetime.utcnow().isoformat(),
            }
            records.append(ParsedRecord(
                entity_type="distressed_opp",
                source_id=f"distressed_{dev.developer_name}_{market}",
                market=market or "all",
                data=data,
            ))

        # Phase 2: BDA e-auctions (non-blocking; empty list if unreachable)
        bda_listings = _fetch_bda_auctions(market)
        for auction in bda_listings:
            pid = auction.get("property_id", "")
            records.append(ParsedRecord(
                entity_type="distressed_opp",
                source_id=f"bda_{pid}" if pid else f"bda_{market}_{datetime.utcnow().timestamp():.0f}",
                market=market,
                data={
                    "developer_name": "BDA_eAuction",
                    "market": market,
                    "total_projects": 0,
                    "active_projects": 0,
                    "delayed_projects": 0,
                    "avg_delay_months": 0.0,
                    "incomplete_ratio": 0.0,
                    "complaint_count": 0,
                    "distress_score": 0.0,
                    "alert_level": "auction",
                    "property_id": pid,
                    "location": auction.get("location", ""),
                    "area_sqft": auction["area_sqft"],
                    "reserve_price_lakh": auction["reserve_price_lakh"],
                    "auction_date": auction["auction_date"],
                    "property_type": auction["property_type"],
                    "source": auction["source"],
                    "detected_at": datetime.utcnow().isoformat(),
                },
            ))

        # Phase 3: SARFAESI bank auctions (stub — returns [] until implemented)
        sarfaesi_listings = _search_sarfaesi_auctions(market)
        for prop in sarfaesi_listings:
            records.append(ParsedRecord(
                entity_type="distressed_opp",
                source_id=f"sarfaesi_{prop.get('property_id', 'unk')}_{market}",
                market=market,
                data={
                    "developer_name": "SARFAESI_eAuction",
                    "market": market,
                    "alert_level": "auction",
                    "source": "sarfaesi",
                    "detected_at": datetime.utcnow().isoformat(),
                    **prop,
                },
            ))

        logger.info(
            "[DistressedPlugin] {} records for {} ({} distressed, {} BDA, {} SARFAESI)",
            len(records), market, len(distressed), len(bda_listings), len(sarfaesi_listings),
        )
        return records
