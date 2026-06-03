"""
RE_OS — BBMP Plugin (Sprint 61)
BBMP Khata record lookup for BBMP jurisdiction wards.

Scraping strategy (3-tier):
1. Primary   → BBMP public API (guessed endpoint; may change without notice)
2. Fallback  → RERA detail pages (bbmp_approval_no field extracted from RERA project records)
3. Last      → returns empty set (logged as warning)

The API endpoint is **not officially documented** and may require future
adjustment if BBMP changes their portal. Monitor logs for "[BBMPPlugin]"
WARNING messages indicating all sources failed.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime
from loguru import logger
from ingest.base import DataPlugin, ParsedRecord

__all__ = ["BBMPPlugin"]

_BBMP_API_URL = "https://bbmp.karnataka.gov.in/api/khata/search"
_BBMP_HEADERS = {
    "User-Agent": "RE_OS/1.0 (market-intel-system)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _search_via_api(ward: str) -> list[dict]:
    """Attempt BBMP public API khata search.

    This is a best-effort probe. The BBMP portal does not publish API docs.
    """
    try:
        payload = json.dumps({"searchText": ward, "limit": 10}).encode("utf-8")
        req = urllib.request.Request(
            _BBMP_API_URL,
            data=payload,
            headers=_BBMP_HEADERS,
            method="POST",
            timeout=15,
        )
        with urllib.request.urlopen(req) as resp:
            results = json.loads(resp.read())
        records = []
        items = results if isinstance(results, list) else results.get("data", [])
        for item in items[:10]:
            records.append({
                "khata_no": str(item.get("khataNo", "")),
                "khata_type": str(item.get("khataType", "A")),
                "property_address": str(item.get("propertyAddress", "")),
                "owner_name": str(item.get("ownerName", "")),
                "property_usage": str(item.get("propertyUsage", "")),
                "zone": str(item.get("zone", "")),
                "ward": str(item.get("ward", "")),
                "survey_no": str(item.get("surveyNo", "")),
                "is_active": bool(item.get("isActive", True)),
            })
        return records
    except Exception as exc:
        logger.debug("[BBMPPlugin] API search failed for '{}': {}", ward, exc)
    return []


def _extract_from_rera(market: str) -> list[dict]:
    """Fallback: pull BBMP approval numbers from existing RERA detail records."""
    try:
        from scrapers.rera_detail_scout import RERADetailScout
        from utils.db import get_engine
        from sqlalchemy import text

        engine = get_engine()
        records: list[dict] = []
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT rd.bbmp_approval_no, rd.rera_number, rd.project_name
                    FROM rera_details rd
                    JOIN rera_projects rp ON rp.rera_number = rd.rera_number
                    JOIN micro_markets mm ON mm.id = rp.micro_market_id
                    WHERE mm.name ILIKE :market
                      AND rd.bbmp_approval_no IS NOT NULL
                      AND rd.bbmp_approval_no != ''
                    LIMIT 50
                """),
                {"market": f"%{market}%"},
            ).fetchall()
        for row in rows:
            records.append({
                "khata_no": str(row.bbmp_approval_no),
                "khata_type": "B",
                "property_address": str(row.project_name or ""),
                "owner_name": "",
                "property_usage": "residential",
                "zone": "",
                "ward": "",
                "survey_no": "",
                "is_active": True,
            })
        logger.info("[BBMPPlugin] {} khata records extracted from RERA details", len(records))
        return records
    except Exception as exc:
        logger.debug("[BBMPPlugin] RERA fallback failed: {}", exc)
    return []


class BBMPPlugin(DataPlugin):
    plugin_id = "bbmp_khata"
    source_id = "bbmp_portal"

    def run(self, market: str) -> list[ParsedRecord]:
        records: list[ParsedRecord] = []

        wards = _market_wards(market)
        for ward in wards:
            khata_results = _search_via_api(ward)
            if not khata_results:
                logger.info("[BBMPPlugin] API returned 0 results for '{}' — trying RERA fallback", ward)
                khata_results = _extract_from_rera(market)
            if not khata_results:
                logger.warning("[BBMPPlugin] All sources returned 0 results for '{}'", ward)

            for khata in khata_results:
                khata_no = khata.get("khata_no", "")
                if not khata_no:
                    continue
                data = {
                    "khata_no": khata_no,
                    "khata_type": khata.get("khata_type", "A"),
                    "survey_no": khata.get("survey_no", ""),
                    "property_address": khata.get("property_address", ""),
                    "owner_name": khata.get("owner_name", ""),
                    "property_usage": khata.get("property_usage", ""),
                    "zone": khata.get("zone", ""),
                    "ward": khata.get("ward", ward),
                    "is_active": khata.get("is_active", True),
                    "source": "bbmp_portal",
                    "scraped_at": datetime.utcnow().isoformat(),
                }
                records.append(ParsedRecord(
                    entity_type="khata_record",
                    source_id=khata_no,
                    market=market,
                    data=data,
                ))

        logger.info("[BBMPPlugin] {} khata records for {}", len(records), market)
        return records


def _market_wards(market: str) -> list[str]:
    """Map market names to BBMP ward / locality names for khata search.

    These are best-effort heuristics. Wards change with BBMP delimitation.
    """
    mapping = {
        "Yelahanka": ["Yelahanka", "Yelahanka New Town", "Yelahanka Satellite Town"],
        "Devanahalli": ["Devanahalli", "Vijayapura"],
        "Hebbal": ["Hebbal", "Mathikere", "Yeshwanthpur"],
    }
    return mapping.get(market, [market])
