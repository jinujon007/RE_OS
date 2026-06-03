"""
RE_OS — Developer Plugin (Sprint 61)
Wraps DeveloperScout to collect developer portfolio data from property portals.
Emits records as ``developer_health`` entity type, mapping portal-scraped
project data to the developer-health schema.

Records are deduplicated by developer name per market run.
"""
from __future__ import annotations

from loguru import logger
from ingest.base import DataPlugin, ParsedRecord

__all__ = ["DeveloperPlugin"]


class DeveloperPlugin(DataPlugin):
    plugin_id = "developer_scout"
    source_id = "developer_portals"

    def run(self, market: str) -> list[ParsedRecord]:
        from scrapers.developer_scout import DeveloperScout

        scout = DeveloperScout(market=market)
        dev_data = scout.scout()
        records: list[ParsedRecord] = []
        seen_developers: set[str] = set()
        for entry in dev_data:
            dev_name = str(entry.get("developer", "")).strip()
            if not dev_name or dev_name.lower() in seen_developers:
                continue
            seen_developers.add(dev_name.lower())
            rera_no = str(entry.get("rera_number", ""))
            data = {
                "developer_name": dev_name,
                "market": market,
                "project_name": str(entry.get("project_name", "")),
                "bhk_configs": str(entry.get("bhk_configs", "")),
                "price_min": float(entry.get("price_min", 0) or 0),
                "area_sqft": float(entry.get("area_sqft", 0) or 0),
                "locality": str(entry.get("locality", "")),
                "launch_status": str(entry.get("launch_status", "")),
                "possession_date": str(entry.get("possession_date", "")),
                "rera_number": rera_no,
                "source": str(entry.get("source", "")),
                "source_url": str(entry.get("source_url", "")),
                "scraped_at": str(entry.get("scraped_at", "")),
            }
            records.append(ParsedRecord(
                entity_type="developer_health",
                source_id=rera_no or f"dev_{dev_name}_{market}",
                market=market,
                data=data,
            ))
        logger.info("[DeveloperPlugin] {} developers for {}", len(records), market)
        return records
