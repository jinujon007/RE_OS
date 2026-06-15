"""
RE_OS — Form 17 Ingest Plugin (Sprint 95 — T-1160)

Reads Form17Parser output from data/kaveri_deeds/inbox/form17/*.pdf and
upserts to registered_transactions — the same table as the EC Form 15 path.

Key differences vs KaveriDeedsPlugin (EC Form 15):
- Source comes directly from Form17Parser (no intermediate checkpoint file).
  Parse and ingest happen in the same run() call.
- Dedup key: sro + doc_number (Form 17 doc_number is unique per SRO).
  source_id = f"form17_{sro}_{doc_number}" truncated to 100 chars.
- is_sale_deed bool stored via deed_type-in-SALE_DEED_TYPES check.
- Multi-survey records: one ParsedRecord per (doc_number, survey_no) pair.
  Entity unique key in registered_transactions: UNIQUE(sro, doc_no, reg_date)
  already deduplicates correctly since each survey row gets a distinct source_id.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from ingest.base import DataPlugin, ParsedRecord, ValidationResult
from scrapers.kaveri_form17 import parse_form17_inbox

__all__ = ["KaveriForm17Plugin"]

_INBOX_DIR = Path("data/kaveri_deeds/inbox/form17")


class KaveriForm17Plugin(DataPlugin):
    """Ingests Form 17 Index II deed records from Kaveri PDF inbox.

    Runs Form17Parser on every PDF in data/kaveri_deeds/inbox/form17/,
    then produces ParsedRecords for registered_transactions.
    """

    plugin_id = "kaveri_form17"
    source_id = "kaveri_form17_inbox"

    def __init__(self, inbox_dir: str | Path | None = None):
        self._inbox_dir = Path(inbox_dir) if inbox_dir else _INBOX_DIR

    def run(self, market: str) -> list[ParsedRecord]:
        raw_records = parse_form17_inbox(self._inbox_dir)
        records: list[ParsedRecord] = []
        cancelled_docs: set[str] = set()

        # Collect all cancellation references first
        for raw in raw_records:
            cd = raw.get("cancels_doc_number")
            if cd:
                cancelled_docs.add(cd)

        for raw in raw_records:
            record = self._build_record(raw, market, cancelled_docs)
            if record is not None:
                records.append(record)

        logger.info(
            "[KaveriForm17Plugin] {} — {} ParsedRecords from {} raw deed rows",
            market,
            len(records),
            len(raw_records),
        )
        return records

    def validate(self, record: ParsedRecord) -> ValidationResult:
        errors = []
        if not record.data.get("doc_no"):
            errors.append("doc_no required")
        if not record.data.get("reg_date"):
            errors.append("reg_date required")
        if not record.data.get("sro"):
            errors.append("sro required")
        if not record.data.get("data_source"):
            errors.append("data_source required")
        return ValidationResult(valid=not errors, errors=errors)

    # ── Private ──────────────────────────────────────────────────────────────

    def _build_record(
        self,
        raw: dict[str, Any],
        market: str,
        cancelled_docs: set[str],
    ) -> ParsedRecord | None:
        doc_no = raw.get("doc_number") or ""
        sro = raw.get("sro") or ""
        reg_date = raw.get("registration_date") or ""
        deed_type = raw.get("deed_type") or ""

        if not doc_no or not sro:
            return None

        # Mark if this deed itself is cancelled by another deed in the batch
        is_cancelled = doc_no in cancelled_docs

        survey_no = raw.get("survey_no_raw") or ""
        extent_sqft = raw.get("extent_sqft")
        consideration_inr = raw.get("consideration_inr")
        psf = raw.get("psf")
        village = raw.get("village") or ""
        executant = raw.get("executant") or ""
        claimant = raw.get("claimant") or ""
        is_sale_deed = bool(raw.get("is_sale_deed", False))
        extraction_confidence = raw.get("extraction_confidence") or "medium"
        cancels_doc = raw.get("cancels_doc_number")

        # source_id unique per (form17, sro, doc_no, survey_no) — truncated to 100
        survey_tag = ("_" + survey_no[:20]) if survey_no else ""
        raw_source_id = f"form17_{sro}_{doc_no}{survey_tag}"
        source_id = raw_source_id[:100]

        data: dict[str, Any] = {
            "doc_no": doc_no,
            "reg_date": reg_date,
            "sro": sro,
            "district": "",
            "taluk": "",
            "hobli": "",
            "village": village,
            "survey_no": survey_no,
            "extent_sqft": extent_sqft,
            "consideration_inr": consideration_inr,
            "psf": psf,
            "deed_type": deed_type,
            "buyer_name_raw": claimant,
            "seller_name_raw": executant,
            "buyer_type": _infer_buyer_type(claimant),
            "data_source": "kaveri_form17",
            "source_ref": raw.get("source_ref") or "",
            "extraction_confidence": extraction_confidence,
            # Extra form17-specific context stored in source_ref extension
            "is_sale_deed": is_sale_deed,
            "is_cancelled": is_cancelled,
            "cancels_doc_number": cancels_doc,
        }

        confidence_score = 0.95 if extraction_confidence == "high" else 0.75

        return ParsedRecord(
            entity_type="registered_transaction",
            source_id=source_id,
            market=market,
            data=data,
            confidence=confidence_score,
        )


# ── Buyer type inference (mirrors KaveriDeedsPlugin) ─────────────────────────
import re as _re

_COMPANY_PAT = _re.compile(
    r"(?:PVT\s*LTD|LLP|LTD|DEVELOPERS|PROPERTIES|CONSTRUCTIONS|"
    r"REALTY|HOMES|INFRA|ESTATES|VENTURES|CORPORATION|PRIVATE\s+LIMITED|LIMITED)",
    _re.IGNORECASE,
)
_TRUST_PAT = _re.compile(r"(?:TRUST|FOUNDATION|SOCIETY|CHARITABLE)", _re.IGNORECASE)


def _infer_buyer_type(name: str | None) -> str | None:
    if not name:
        return None
    if _TRUST_PAT.search(name):
        return "trust"
    if _COMPANY_PAT.search(name):
        return "company"
    return "individual"
