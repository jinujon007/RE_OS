"""
RE_OS — IGR Plugin (Sprint 61)
Wraps IGRTransactionScout to scrape registered sale deed transactions
from the Karnataka IGR portal. Uses a stable composite-source_id
derived from (market, survey_no, consideration_amount, registration_date)
so that re-scrapes produce the same source_id for the same transaction.
"""
from __future__ import annotations

import hashlib
from loguru import logger
from ingest.base import DataPlugin, ParsedRecord

__all__ = ["IGRPlugin"]


def _stable_source_id(txn: dict, market: str) -> str:
    """Deterministic source_id from transaction content — never ordinal."""
    raw = f"{market}|{txn.get('survey_no','')}|{txn.get('consideration_amount',0)}|{txn.get('registration_date','')}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


class IGRPlugin(DataPlugin):
    plugin_id = "igr_karnataka"
    source_id = "igr_portal"

    def run(self, market: str) -> list[ParsedRecord]:
        from scrapers.igr_karnataka import IGRTransactionScout

        scout = IGRTransactionScout()
        transactions = scout.run(market=market, days_back=30)
        records: list[ParsedRecord] = []
        for txn in transactions:
            survey_no = str(txn.get("survey_no", "")).strip()
            source_id = _stable_source_id(txn, market)
            data = {
                "survey_no": survey_no,
                "seller": str(txn.get("seller", ""))[:500],
                "buyer": str(txn.get("buyer", ""))[:500],
                "consideration_amount": int(txn.get("consideration_amount", 0)),
                "area_sqft": float(txn.get("area_sqft", 0)),
                "registration_date": str(txn.get("registration_date", "")),
                "sro_office": str(txn.get("sro_office", ""))[:200],
                "source": str(txn.get("source", "igr_portal")),
                "scraped_at": str(txn.get("scraped_at", "")),
            }
            records.append(ParsedRecord(
                entity_type="igr_transaction",
                source_id=source_id,
                market=market,
                data=data,
            ))
        logger.info("[IGRPlugin] {} transactions for {}", len(records), market)
        return records
