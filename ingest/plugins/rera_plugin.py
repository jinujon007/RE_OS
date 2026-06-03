"""
RE_OS — RERA Plugin (Sprint 61)
Thin adapter over RERAKarnatakaScraper. Calls scrape_market() for the given
market and wraps each project dict into a ParsedRecord with stable source_id
equal to the RERA registration number.
"""
from __future__ import annotations

from datetime import datetime
from loguru import logger
from ingest.base import DataPlugin, ParsedRecord

__all__ = ["RERAPlugin"]


class RERAPlugin(DataPlugin):
    plugin_id = "rera_karnataka"
    source_id = "rera_karnataka_portal"

    def run(self, market: str) -> list[ParsedRecord]:
        from scrapers.rera_karnataka import RERAKarnatakaScraper

        scraper = RERAKarnatakaScraper()
        projects, _cookies = scraper.scrape_market(market)
        records: list[ParsedRecord] = []
        for proj in projects:
            rera_no = str(proj.get("rera_number", "")).strip()
            if not rera_no:
                continue
            data = {
                "rera_number": rera_no,
                "project_name": str(proj.get("project_name", "")),
                "developer_name": str(proj.get("developer_name", "")),
                "total_units": int(proj.get("total_units", 0)),
                "possession_date": str(proj.get("possession_date", "")),
                "data_source": str(proj.get("data_source", "rera_karnataka_live")),
                "scraped_at": str(proj.get("scraped_at", datetime.utcnow().isoformat())),
            }
            if proj.get("is_active") is not None:
                data["is_active"] = bool(proj["is_active"])
            if proj.get("project_status"):
                data["project_status"] = str(proj["project_status"])
            records.append(ParsedRecord(
                entity_type="rera_project",
                source_id=rera_no,
                market=market,
                data=data,
            ))
        logger.info("[RERAPlugin] {} projects for {}", len(records), market)
        return records
