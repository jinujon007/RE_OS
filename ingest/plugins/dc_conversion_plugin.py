"""
RE_OS — DC Conversion Ingest Plugin (GATE-94, T-1153)

Ingests land-use conversion (DC) application records from Bhoomi/landrecords
portal into the dc_conversions table.

Sends Discord alert when a conversion is detected in a covered market village.

Entity type: dc_conversion → dc_conversions table.
"""

from __future__ import annotations

from loguru import logger

from ingest.base import DataPlugin, ParsedRecord, ValidationResult
from scrapers.dc_conversion_scraper import run_scan, market_for_village

try:
    from utils.parcel_linker import normalize_survey_no

    _HAS_PARCEL_LINKER = True
except ImportError:
    _HAS_PARCEL_LINKER = False


class DCConversionPlugin(DataPlugin):
    """Ingests DC conversion applications from Bhoomi land records portal.

    Two modes:
      - live: scrape Bhoomi portal (reuses BhoomiScraper session pattern)
      - inbox: parse manually exported files
    """

    plugin_id = "dc_conversion_tracker"
    source_id = "dc_conversion_bhoomi"

    def run(self, market: str | None = None) -> list[ParsedRecord]:
        records: list[ParsedRecord] = []
        try:
            results = run_scan(mode="live")
        except Exception as exc:
            logger.warning("[DCConversion] live scan failed, trying inbox: {}", exc)
            try:
                results = run_scan(mode="inbox")
            except Exception as exc2:
                logger.warning("[DCConversion] inbox scan also failed: {}", exc2)
                return records

        alerts_by_village: dict[str, list[str]] = {}

        for rec in results:
            app_no = rec.get("application_no", "")
            if not app_no:
                continue

            data = {
                "application_no": app_no,
                "village": rec.get("village", ""),
                "survey_no": normalize_survey_no(rec.get("survey_no", ""))
                if _HAS_PARCEL_LINKER and rec.get("survey_no")
                else rec.get("survey_no", ""),
                "extent_acres": rec.get("extent_acres"),
                "from_use": rec.get("from_use", ""),
                "to_use": rec.get("to_use", ""),
                "applicant_name": rec.get("applicant_name", ""),
                "status": rec.get("status", "unknown"),
                "application_date": rec.get("application_date"),
                "decision_date": rec.get("decision_date"),
                "data_source": rec.get("data_source", "live"),
                "source_ref": rec.get("source_ref", ""),
            }

            village = data["village"]
            target_market = market_for_village(village)
            rec_market = market if market else (target_market or "Bengaluru")

            records.append(
                ParsedRecord(
                    entity_type="dc_conversion",
                    source_id=f"dc_{app_no}",
                    market=rec_market,
                    data=data,
                    confidence=0.7,
                )
            )

            if target_market:
                key = f"{village} ({target_market})"
                alerts_by_village.setdefault(key, [])
                alerts_by_village[key].append(
                    f"{app_no}: → {rec.get('to_use', 'N/A')} ({rec.get('status', 'unknown')})"
                )

        self._send_batched_alerts(alerts_by_village)
        return records

    def validate(self, record: ParsedRecord) -> ValidationResult:
        errors = []
        if not record.data.get("application_no"):
            errors.append("application_no required")
        return ValidationResult(valid=not errors, errors=errors)

    def _send_batched_alerts(self, alerts_by_village: dict[str, list[str]]) -> None:
        """Send one Discord alert per village with all applications batched."""
        if not alerts_by_village:
            return
        try:
            from utils.discord_notifier import send

            for key, lines in alerts_by_village.items():
                send(
                    "bd_opportunities",
                    f"🔄 DC Conversion: {key}",
                    f"{len(lines)} application(s):\n" + "\n".join(lines),
                )
        except Exception as exc:
            logger.warning("[DCConversion] batched Discord alert failed: {}", exc)
