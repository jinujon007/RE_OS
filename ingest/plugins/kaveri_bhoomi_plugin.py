"""
RE_OS — Kaveri Bhoomi Plugin (Sprint 61)
Three data sources for a single market:

1. **Guidance values** — circle rates per locality (KaveriScraper).
2. **Property registrations** — deed-level sale transactions (KaveriTransactionScout).
3. **RTC records** — Bhoomi land-record extracts (direct HTTP to Bhoomi portal).

All three use stable deterministic source_ids derived from content hashes
so re-scrapes produce the same IDs and dedup works correctly across runs.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime
from loguru import logger
from ingest.base import DataPlugin, ParsedRecord

__all__ = ["KaveriBhoomiPlugin"]

_BHOOMI_SEARCH_URL = "https://bhoomi.karnataka.gov.in/api/rtc/search"
_BHOOMI_HEADERS = {
    "User-Agent": "RE_OS/1.0 (market-intel-system)",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _search_rtc(survey_no: str, village: str) -> list[dict]:
    """Query Bhoomi RTC records for a survey number.

    Returns empty list on failure — never blocks the pipeline.
    """
    try:
        payload = json.dumps({
            "surveyNumber": survey_no,
            "village": village,
            "limit": 5,
        }).encode("utf-8")
        req = urllib.request.Request(
            _BHOOMI_SEARCH_URL,
            data=payload,
            headers=_BHOOMI_HEADERS,
            method="POST",
            timeout=15,
        )
        with urllib.request.urlopen(req) as resp:
            raw = json.loads(resp.read())
        records = []
        items = raw if isinstance(raw, list) else raw.get("data", [])
        for item in items[:5]:
            records.append({
                "survey_no": str(item.get("surveyNumber", survey_no)),
                "village": str(item.get("village", village)),
                "rtc_period": str(item.get("period", "")),
                "rtc_year": str(item.get("year", "")),
                "cultivator": str(item.get("cultivator", "")),
                "area_acres": float(item.get("area", 0) or 0),
                "crop": str(item.get("crop", "")),
                "source": "bhoomi_portal",
            })
        return records
    except Exception as exc:
        logger.debug("[KaveriBhoomiPlugin] Bhoomi RTC search failed: {}", exc)
    return []


def _content_hash(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


class KaveriBhoomiPlugin(DataPlugin):
    plugin_id = "kaveri_bhoomi"
    source_id = "kaveri_portal"

    def run(self, market: str) -> list[ParsedRecord]:
        records: list[ParsedRecord] = []

        records.extend(self._scrape_guidance_values(market))
        records.extend(self._scrape_registrations(market))
        records.extend(self._scrape_rtc_records(market))

        logger.info("[KaveriBhoomiPlugin] {} total records for {}", len(records), market)
        return records

    def _scrape_guidance_values(self, market: str) -> list[ParsedRecord]:
        from scrapers.kaveri_karnataka import KaveriScraper

        scraper = KaveriScraper()
        gv_records = scraper.scrape_guidance_values(market)
        parsed: list[ParsedRecord] = []
        for gv in gv_records:
            locality = str(gv.get("locality", ""))
            prop_type = str(gv.get("property_type", "Residential"))
            road_type = str(gv.get("road_type", "Main Road"))
            data_source = str(gv.get("source") or gv.get("data_source") or "kaveri_portal")
            data = {
                "locality": locality,
                "property_type": prop_type,
                "road_type": road_type,
                "guidance_value_psf": float(gv.get("guidance_value_psf", 0)),
                "guidance_value_per_sqm": float(gv.get("guidance_value_per_sqm", 0) or 0),
                "effective_from": str(gv.get("effective_from", "")),
                "source_document": str(gv.get("source_document", "")),
                "data_source": data_source,
            }
            sid = _content_hash(
                "gv", market, locality, prop_type, road_type, data_source,
            )
            parsed.append(ParsedRecord(
                entity_type="guidance_value",
                source_id=sid,
                market=market,
                data=data,
            ))
        return parsed

    def _scrape_registrations(self, market: str) -> list[ParsedRecord]:
        from scrapers.kaveri_transaction_scout import KaveriTransactionScout

        scout = KaveriTransactionScout()
        reg_records = scout.run(market=market, days_back=90)
        prs: list[ParsedRecord] = []
        for reg in reg_records:
            sale_value = float(reg.get("sale_value_lakh", 0))
            area = float(reg.get("area_sqft", 0))
            data = {
                "survey_number": str(reg.get("survey_number", "")),
                "village": str(reg.get("village", "")),
                "taluk": str(reg.get("taluk", "")),
                "registration_date": str(reg.get("registration_date", "")),
                "sale_value_lakh": sale_value,
                "area_sqft": area,
                "derived_psf": sale_value / area if area > 0 else 0,
                "document_type": str(reg.get("document_type", "Sale Deed")),
                "buyer_type": str(reg.get("buyer_type", "individual")),
                "source": "kaveri_portal",
            }
            sid = _content_hash(
                "reg", market,
                data["survey_number"], data["registration_date"],
            )
            prs.append(ParsedRecord(
                entity_type="kaveri_registration",
                source_id=sid,
                market=market,
                data=data,
            ))
        return prs

    def _scrape_rtc_records(self, market: str) -> list[ParsedRecord]:
        """Attempt RTC (Record of Rights, Tenancy & Crops) lookup.

        Uses survey numbers from kaveri registrations if available,
        otherwise searches by market-level village names.
        """
        from scrapers.kaveri_transaction_scout import KaveriTransactionScout

        scout = KaveriTransactionScout()
        registrations = scout.run(market=market, days_back=90)

        seen_surveys: set[str] = set()
        records: list[ParsedRecord] = []
        for reg in registrations:
            survey_no = str(reg.get("survey_number", "")).strip()
            village = str(reg.get("village", "")).strip()
            if not survey_no or survey_no in seen_surveys:
                continue
            seen_surveys.add(survey_no)
            rtc_results = _search_rtc(survey_no, village or market)
            for rtc in rtc_results:
                data = {
                    "survey_no": rtc["survey_no"],
                    "village": rtc["village"],
                    "rtc_period": rtc["rtc_period"],
                    "rtc_year": rtc["rtc_year"],
                    "cultivator": rtc["cultivator"],
                    "area_acres": rtc["area_acres"],
                    "crop": rtc["crop"],
                    "source": rtc["source"],
                    "scraped_at": datetime.utcnow().isoformat(),
                }
                sid = _content_hash(
                    "rtc", market,
                    data["survey_no"], data["rtc_period"], data["rtc_year"],
                )
                records.append(ParsedRecord(
                    entity_type="rtc_record",
                    source_id=sid,
                    market=market,
                    data=data,
                ))
        return records
