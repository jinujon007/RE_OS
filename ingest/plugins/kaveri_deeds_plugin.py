"""
RE_OS — Kaveri Deeds Ingest Plugin (Sprint 91 — GATE-91)

Reads KaveriDeedScout checkpoint → upserts registered_transactions.

Key logic:
- PSF computed where extent + consideration both present
- Sanity bounds ₹500–₹50,000 PSF, else psf=NULL + extraction_confidence='low'
- buyer_type inference: company/trust/individual
- Dedup on UNIQUE(sro, doc_no, reg_date) via writer's ON CONFLICT
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from ingest.base import DataPlugin, ParsedRecord, ValidationResult

__all__ = ["KaveriDeedsPlugin"]

_CHECKPOINT_GLOB = "data/kaveri_deeds/checkpoints/kaveri_deeds_*.json"
_JURISDICTION_INDEX_PATH = Path("data/kaveri_jurisdiction/village_lookup_index.json")

# Lazy-loaded jurisdiction index: village_name.lower() -> [{district, taluk, hobli, name}]
_jurisdiction_index: dict[str, list[dict]] | None = None


def _get_jurisdiction_index() -> dict[str, list[dict]]:
    global _jurisdiction_index
    if _jurisdiction_index is None:
        if _JURISDICTION_INDEX_PATH.exists():
            try:
                _jurisdiction_index = json.loads(_JURISDICTION_INDEX_PATH.read_text(encoding="utf-8"))
                logger.info("[KaveriDeedsPlugin] Loaded jurisdiction index: {} village names", len(_jurisdiction_index))
            except Exception as exc:
                logger.warning("[KaveriDeedsPlugin] Failed to load jurisdiction index: {}", exc)
                _jurisdiction_index = {}
        else:
            logger.warning("[KaveriDeedsPlugin] Jurisdiction index not found at {}", _JURISDICTION_INDEX_PATH)
            _jurisdiction_index = {}
    return _jurisdiction_index


def _enrich_jurisdiction(village: str, raw_district: str, raw_taluk: str, raw_hobli: str) -> tuple[str, str, str]:
    """Fill district/taluk/hobli from village lookup index if not already set."""
    if raw_district and raw_taluk and raw_hobli:
        return raw_district, raw_taluk, raw_hobli
    if not village:
        return raw_district, raw_taluk, raw_hobli
    idx = _get_jurisdiction_index()
    matches = idx.get(village.strip().lower(), [])
    if not matches:
        return raw_district, raw_taluk, raw_hobli
    # Take first match (deterministic; most villages map to one hobli)
    m = matches[0]
    return (
        raw_district or m.get("district", ""),
        raw_taluk or m.get("taluk", ""),
        raw_hobli or m.get("hobli", ""),
    )

# Buyer type inference
_COMPANY_PATTERN = re.compile(
    r"(?:PVT\s*LTD|LLP|LTD|DEVELOPERS|PROPERTIES|CONSTRUCTIONS|"
    r"REALTY|HOMES|INFRA|ESTATES|VENTURES|CORPORATION|INCORPORATED|"
    r"PRIVATE\s+LIMITED|LIMITED|GROUP)",
    re.IGNORECASE,
)
_TRUST_PATTERN = re.compile(r"(?:TRUST|FOUNDATION|SOCIETY|CHARITABLE)", re.IGNORECASE)


def _infer_buyer_type(buyer_name: str | None) -> str | None:
    """Infer buyer entity type from name."""
    if not buyer_name:
        return None
    if _TRUST_PATTERN.search(buyer_name):
        return "trust"
    if _COMPANY_PATTERN.search(buyer_name):
        return "company"
    return "individual"


def _compute_psf(
    consideration_inr: float | None, extent_sqft: float | None
) -> tuple[float | None, str]:
    """Compute PSF with sanity bounds.

    Returns (psf, extraction_confidence).
    Returns (None, 'low') if out of bounds or missing data.
    """
    if consideration_inr is None or extent_sqft is None or extent_sqft <= 0:
        return None, "low"

    psf_val = consideration_inr / extent_sqft
    if 500 <= psf_val <= 50000:
        return round(psf_val, 2), "medium"
    return None, "low"


_CHECKPOINT_TS_RE = re.compile(
    r"kaveri_deeds_\w+_(\d{8})_(\d{6})\.json$"
)


def _sort_checkpoints(paths: list[Path]) -> list[Path]:
    """Sort checkpoint files by extracted timestamp, newest first."""
    def _sort_key(p: Path) -> str:
        m = _CHECKPOINT_TS_RE.search(p.name)
        if m:
            return f"{m.group(1)}{m.group(2)}"
        return "00000000000000"
    return sorted(paths, key=_sort_key, reverse=True)


def _remove_old_checkpoint_progress(paths: list[Path]) -> list[Path]:
    """Filter out write-ahead checkpoint files when a final checkpoint exists.
    Write-ahead files have 'wal_' in their name; final ones don't.
    """
    has_final = any("_inbox_" in p.name and "wal_" not in p.name for p in paths)
    if has_final:
        return [p for p in paths if "wal_" not in p.name]
    return paths


def _read_checkpoint(checkpoint_path: str | None = None) -> list[dict[str, Any]]:
    """Read the latest (or specified) checkpoint file.

    Returns list of deed records.
    Filters out WAL (write-ahead) checkpoints when a final one exists.
    """
    if checkpoint_path:
        paths = [Path(checkpoint_path)]
    else:
        paths = _sort_checkpoints(list(Path().glob(_CHECKPOINT_GLOB)))

    if not paths:
        logger.info("[KaveriDeedsPlugin] No checkpoint files found")
        return []

    paths = _remove_old_checkpoint_progress(paths)
    if not paths:
        logger.info("[KaveriDeedsPlugin] No final checkpoint file found")
        return []

    latest = paths[0]
    try:
        fsize = latest.stat().st_size
        if fsize > 50 * 1024 * 1024:
            logger.error(
                "[KaveriDeedsPlugin] Checkpoint too large ({} MB): {}",
                fsize / (1024 * 1024),
                latest,
            )
            return []

        data = json.loads(latest.read_text())
        records = data.get("records", [])
        logger.info(
            "[KaveriDeedsPlugin] Read {} records from checkpoint: {}",
            len(records),
            latest,
        )
        return records
    except (json.JSONDecodeError, Exception) as exc:
        logger.error(
            "[KaveriDeedsPlugin] Failed to read checkpoint {}: {}", latest, exc
        )
        return []


class KaveriDeedsPlugin(DataPlugin):
    """Ingests Kaveri deed records from scout checkpoint.

    Reads the latest KaveriDeedScout checkpoint and produces ParsedRecords
    for the registered_transactions table.
    """

    plugin_id = "kaveri_deeds"
    source_id = "kaveri_deeds_scout"

    def __init__(self, checkpoint_path: str | None = None):
        self._checkpoint_path = checkpoint_path

    def run(self, market: str) -> list[ParsedRecord]:
        records: list[ParsedRecord] = []
        raw_records = _read_checkpoint(self._checkpoint_path)

        for i, raw in enumerate(raw_records):
            record = self._build_record(raw, market, i)
            if record is not None:
                records.append(record)

        logger.info(
            "[KaveriDeedsPlugin] {} — {} valid records (from {} raw)",
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
        self, raw: dict[str, Any], market: str, idx: int
    ) -> ParsedRecord | None:
        """Transform a raw deed dict into a ParsedRecord."""
        doc_no = str(raw["doc_no"]) if "doc_no" in raw and raw["doc_no"] is not None else ""
        reg_date = str(raw["reg_date"]) if "reg_date" in raw and raw["reg_date"] is not None else ""
        sro = str(raw["sro"]) if "sro" in raw and raw["sro"] is not None else ""
        village = str(raw["village"]) if "village" in raw and raw["village"] is not None else ""
        survey_no = str(raw["survey_no"]) if "survey_no" in raw and raw["survey_no"] is not None else ""
        extent_sqft = raw.get("extent_sqft")
        consideration_inr = raw.get("consideration_inr")
        deed_type = str(raw["deed_type"]) if "deed_type" in raw and raw["deed_type"] is not None else ""
        buyer_name = str(raw["buyer_name_raw"]) if "buyer_name_raw" in raw and raw["buyer_name_raw"] is not None else ""
        seller_name = str(raw["seller_name_raw"]) if "seller_name_raw" in raw and raw["seller_name_raw"] is not None else ""
        data_source = str(raw["data_source"]) if "data_source" in raw and raw["data_source"] is not None else "kaveri_inbox"
        source_ref = str(raw["source_ref"]) if "source_ref" in raw and raw["source_ref"] is not None else ""
        extraction_confidence = str(raw["extraction_confidence"]) if "extraction_confidence" in raw and raw["extraction_confidence"] is not None else "medium"

        # Convert to float if present
        try:
            extent_sqft = float(extent_sqft) if extent_sqft is not None else None
        except (ValueError, TypeError):
            extent_sqft = None
        try:
            consideration_inr = (
                float(consideration_inr) if consideration_inr is not None else None
            )
        except (ValueError, TypeError):
            consideration_inr = None

        # Compute PSF with bounds
        psf, psf_confidence = _compute_psf(consideration_inr, extent_sqft)
        if psf_confidence == "low":
            extraction_confidence = "low"

        # Infer buyer type
        buyer_type = _infer_buyer_type(buyer_name)

        # Enrich district/taluk/hobli from jurisdiction index if scout didn't set them
        district, taluk, hobli = _enrich_jurisdiction(
            village,
            str(raw.get("district") or ""),
            str(raw.get("taluk") or ""),
            str(raw.get("hobli") or ""),
        )

        # Source ID for dedup (within this plugin).
        # Truncated to 100 chars to stay within ingest_log.source_id varchar(100).
        raw_source_id = f"deed_{sro}_{doc_no}_{reg_date}"
        source_id = raw_source_id[:100]

        now_iso = datetime.now(timezone.utc).isoformat()
        data = {
            "doc_no": doc_no,
            "reg_date": reg_date,
            "sro": sro,
            "district": district,
            "taluk": taluk,
            "hobli": hobli,
            "village": village,
            "survey_no": survey_no,
            "extent_sqft": extent_sqft,
            "consideration_inr": consideration_inr,
            "psf": psf,
            "deed_type": deed_type,
            "buyer_name_raw": buyer_name,
            "seller_name_raw": seller_name,
            "buyer_type": buyer_type,
            "data_source": data_source,
            "source_ref": source_ref,
            "extraction_confidence": extraction_confidence,
            "updated_at": now_iso,
        }

        if not doc_no and not reg_date and not sro:
            return None

        return ParsedRecord(
            entity_type="registered_transaction",
            source_id=source_id,
            market=market,
            data=data,
            confidence=0.9 if extraction_confidence == "high" else 0.7,
        )
