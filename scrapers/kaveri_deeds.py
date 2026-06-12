"""
RE_OS — KaveriDeedScout (Sprint 91 — GATE-91)

Two-path architecture for Kaveri Online Services deed-level transaction data:

    --mode inbox (primary): Parse PDF/HTML files placed in data/kaveri_deeds/inbox/
        by Jinu (manual export from Kaveri EC search results).

    --mode live (secondary): Playwright-assisted automated extraction using
        Sprint 77 session-cookie pattern. Graceful stop on CAPTCHA.

Output: JSON checkpoint file (Stage 1 checkpoint pattern).
Survey numbers extracted from property-description text using Sprint 80 regex.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from prometheus_client import Counter, Histogram

from utils.pdf_extractor import extract_pdf

# Prometheus metrics
_deed_records_parsed = Counter(
    "kaveri_deeds_records_parsed_total",
    "Total Kaveri deed records parsed",
    ["mode"],
)
_deed_parse_errors = Counter(
    "kaveri_deeds_parse_errors_total",
    "Total Kaveri deed parse errors",
    ["file_type"],
)
_deed_parse_duration = Histogram(
    "kaveri_deeds_parse_duration_seconds",
    "Time to parse Kaveri deed files",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

__all__ = [
    "parse_inbox_file", "parse_inbox_all", "write_checkpoint",
    "read_latest_checkpoint", "run_inbox_mode", "run_live_mode",
]

# Paths
_DATA_DIR = Path("data/kaveri_deeds")
_INBOX_DIR = _DATA_DIR / "inbox"
_SAMPLES_DIR = _DATA_DIR / "samples"
_CHECKPOINT_DIR = _DATA_DIR / "checkpoints"

# Safety limits
_MAX_CHECKPOINT_BYTES = 50 * 1024 * 1024  # 50 MB — prevent OOM on corrupt files
_MAX_INBOX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB per inbox file

# Survey number regex — Sprint 80 pattern, extended for hyphen variants
_SURVEY_NO_RE = re.compile(
    r"(?:[Ss]y\.?\s*[Nn]o\.?|[Ss]urvey\s+[Nn]o\.?|S\.\s*[Nn]o\.?|"
    r"[Ss]urvey\s*[Nn]umber|[Ss]\.?\s*[Nn]o\.?)"
    r"\s*[:.]?\s*([\d]+/[\dA-Za-z]+(?:[-/][\dA-Za-z]+)*)"
)

# Fallback: directly match survey number pattern in free text
# Narrow context: matched only inside a property-description scope.
# Rejects pincodes (560/102), dates (15/05/2026), and year-like numbers.
_SURVEY_NO_DIRECT_RE = re.compile(
    r"(?<!\w)(\d{1,4}/(?:[\dA-Za-z]{1,3}(?:[-/][\dA-Za-z]{1,3})*))(?:\s|,|;|\.|$)"
)
# Negative patterns to filter out false positives
_SURVEY_NO_FALSE_POSITIVES = re.compile(
    r"^\d{3}/\d{3}$|^\d{2}/\d{2}/\d{4}$|^\d{1,2}/\d{1,2}/\d{2,4}$"
)

# Kannada digit ranges (0-9 in Kannada)
_KANNADA_DIGITS_RE = re.compile(r"[\u0CE0-\u0CEF\u0C66-\u0C6F]")

# Consideration regex — Indian number format with ₹, Rs, Lakh, Crore
_CONSIDERATION_RE = re.compile(
    r"(?:Rs\.?|INR|₹|Rupees?|Consideration|Amount)[\s:.]*"
    r"([\d,]+(?:\.\d+)?)\s*(Crore|Lakh|lak|lacs|lakhs|Thousand)?",
    re.IGNORECASE,
)

# Extent regex
_EXTENT_RE = re.compile(
    r"([\d,]+(?:\.\d+)?)\s*(?:Sq\.?\s*[Ff]t|sqft|Sq\.?[Ff]t\.?|square\s+feet)",
)

# Date regex (DD/MM/YYYY or DD-MM-YYYY)
_DATE_RE = re.compile(r"(\d{2})[/-](\d{2})[/-](\d{4})")

# Document number regex
_DOC_NO_RE = re.compile(
    r"(?:Document\s*No|Doc\s*No|DEED\s*No)[.:\s]*([\d/]+)", re.IGNORECASE
)

# SRO office name regex
_SRO_RE = re.compile(
    r"(?:SRO|Sub\s*Registrar|Office)[.:\s]*(.+?)(?=\n(?:[A-Z][a-z]+|[A-Z]{2,})\s*[:\n]|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# Village name regex
_VILLAGE_RE = re.compile(r"(?:Village|Vill)[.:\s]*(.+?)(?:\n|$)", re.IGNORECASE)

# Buyer/Seller regex
_BUYER_RE = re.compile(r"(?:Buyer|Purchaser)[.:\s]*(.+?)(?:\n|$)", re.IGNORECASE)
_SELLER_RE = re.compile(
    r"(?:Seller|Vendor|Transferor)[.:\s]*(.+?)(?:\n|$)", re.IGNORECASE
)

# Deed type
_DEED_TYPE_RE = re.compile(
    r"(?:Deed\s*Type|Type\s*of\s*Deed)[.:\s]*(.+?)(?:\n|$)", re.IGNORECASE
)


def _extract_survey_no(text: str) -> tuple[str | None, str]:
    """Extract survey number from property description text.

    Returns (survey_no, extraction_confidence).
    confidence='low' if extracted via direct pattern or Kannada digits present.
    """
    # Check for Kannada digits
    has_kannada = bool(_KANNADA_DIGITS_RE.search(text))

    # Primary: use the structured survey number regex
    match = _SURVEY_NO_RE.search(text)
    if match:
        raw = match.group(1).strip()
        normalized = _normalize_survey_no(raw)
        if normalized:
            confidence = "low" if has_kannada else "high"
            return normalized, confidence

    # Fallback: direct pattern match with false-positive filtering
    match = _SURVEY_NO_DIRECT_RE.search(text)
    if match:
        raw = match.group(1).strip()
        # Reject pincodes, date patterns, and known false positives
        if _SURVEY_NO_FALSE_POSITIVES.match(raw):
            return None, "low"
        normalized = _normalize_survey_no(raw)
        if normalized:
            return normalized, "low"

    return None, "low"


def _normalize_survey_no(raw: str) -> str | None:
    """Normalize survey number: uppercase, strip spaces, unify separators."""
    raw = raw.strip().upper()
    # Normalize hyphens between parts (e.g., 45/2-A → 45/2A)
    raw = re.sub(r"([\d])-([A-Z])", r"\1\2", raw)
    raw = re.sub(r"([A-Z])-([\d])", r"\1\2", raw)
    # Remove leading/trailing non-alphanumeric
    raw = raw.strip(" ./\\-")
    if not raw or raw in ("N/A", "NA", "NIL", "NONE", "-"):
        return None
    return raw


def _parse_consideration(text: str) -> float | None:
    """Parse consideration amount from text. Handles Crore/Lakh formats."""
    match = _CONSIDERATION_RE.search(text)
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(",", ""))
        unit = (match.group(2) or "").lower()
        if unit in ("crore",):
            amount *= 10_000_000
        elif unit in ("lakh", "lak", "lacs", "lakhs"):
            amount *= 100_000
        elif unit == "thousand":
            amount *= 1_000
        return round(amount, 2)
    except (ValueError, IndexError):
        return None


def _parse_extent_sqft(text: str) -> float | None:
    """Parse extent in square feet."""
    match = _EXTENT_RE.search(text)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except (ValueError, IndexError):
            return None
    return None


def _parse_date(text: str) -> str | None:
    """Parse date in DD/MM/YYYY or DD-MM-YYYY format. Returns ISO date string."""
    match = _DATE_RE.search(text)
    if match:
        day, month, year = match.group(1), match.group(2), match.group(3)
        try:
            dt = datetime(int(year), int(month), int(day))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def _extract_field(text: str, regex: re.Pattern, group: int = 1) -> str | None:
    """Extract a field using a regex pattern."""
    match = regex.search(text)
    if match:
        val = match.group(group).strip()
        if val and val not in ("N/A", "NA", "NIL", "-"):
            return val
    return None


_DOC_BOUNDARY_RE = re.compile(
    r"(?=Document\s+(?:No|Number|No\.)[.:\s]*[\d/]+)", re.IGNORECASE
)


def _split_deed_sections(full_text: str) -> list[str]:
    """Split a multi-deed EC document into per-deed text sections.
    Uses 'Document No' as the boundary marker.
    """
    sections = _DOC_BOUNDARY_RE.split(full_text)
    return [s.strip() for s in sections if s.strip()]


def _parse_single_deed(text: str) -> dict[str, Any] | None:
    """Extract deed fields from a single deed text section."""
    doc_no = _extract_field(text, _DOC_NO_RE)
    reg_date = _parse_date(text)
    sro = _extract_field(text, _SRO_RE)
    village = _extract_field(text, _VILLAGE_RE)
    buyer = _extract_field(text, _BUYER_RE)
    seller = _extract_field(text, _SELLER_RE)
    deed_type = _extract_field(text, _DEED_TYPE_RE)

    prop_desc = ""
    prop_match = re.search(
        r"(?:Property\s*Description|Schedule\s*of\s*Property|Property\s*Details)"
        r"[:\s]*(.*?)(?=Consideration|Registration|Stamp|Rs\.|INR|₹|Document\s+(?:No|Number))",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if prop_match:
        prop_desc = prop_match.group(1).strip()

    search_text = prop_desc or text
    survey_no, sn_confidence = _extract_survey_no(search_text)
    extent = _parse_extent_sqft(search_text)
    consideration = _parse_consideration(text)

    psf = None
    if consideration is not None and extent is not None and extent > 0:
        psf_val = consideration / extent
        if 500 <= psf_val <= 50000:
            psf = round(psf_val, 2)

    record: dict[str, Any] = {
        "doc_no": doc_no or "",
        "reg_date": reg_date or "",
        "sro": sro or "",
        "village": village or "",
        "survey_no": survey_no or "",
        "extent_sqft": extent,
        "consideration_inr": consideration,
        "psf": psf,
        "deed_type": deed_type or "",
        "buyer_name_raw": buyer or "",
        "seller_name_raw": seller or "",
        "extraction_confidence": sn_confidence,
    }

    if any(v for v in [doc_no, reg_date, village, survey_no]):
        return record
    return None


def _parse_pdf_text(pdf_text: str) -> list[dict[str, Any]]:
    """Parse PDF-extracted text into one or more deed records.

    Splits on document-number boundaries to handle multi-deed EC PDFs.
    """
    sections = _split_deed_sections(pdf_text)
    records: list[dict[str, Any]] = []
    for section in sections:
        record = _parse_single_deed(section)
        if record is not None:
            records.append(record)
    if not records:
        # Fallback: treat entire text as one deed (no boundary found)
        single = _parse_single_deed(pdf_text)
        if single is not None:
            records.append(single)
    return records


def parse_inbox_file(filepath: Path) -> list[dict[str, Any]]:
    """Parse a single file from the inbox directory. Supports .pdf and .txt/.html.

    Returns a list of deed record dicts.
    """
    suffix = filepath.suffix.lower()
    if suffix == ".pdf":
        result = extract_pdf(str(filepath))
        pdf_text = result.get("text", "")
        if not pdf_text.strip():
            logger.warning("[KaveriDeedScout] Empty PDF text: {}", filepath.name)
            return []
        records = _parse_pdf_text(pdf_text)
    elif suffix in (".txt", ".html", ".htm"):
        text = filepath.read_text(encoding="utf-8", errors="replace")
        records = _parse_pdf_text(text)
    else:
        logger.warning("[KaveriDeedScout] Unsupported file type: {}", filepath)
        return []

    for rec in records:
        rec["source_ref"] = filepath.name
        rec["data_source"] = "kaveri_inbox"

    return records


def parse_inbox_all() -> list[dict[str, Any]]:
    """Parse all files in the inbox directory.

    Uses write-ahead checkpointing: writes a partial checkpoint after each
    file so partial progress is preserved if the process crashes mid-batch.
    Enforces a 10 MB file size limit per inbox file.

    Returns a combined list of all deed records from all files.
    """
    if not _INBOX_DIR.exists():
        _INBOX_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("[KaveriDeedScout] Created inbox directory: {}", _INBOX_DIR)
        return []

    all_records: list[dict[str, Any]] = []
    files = sorted(_INBOX_DIR.iterdir())
    for fpath in files:
        if fpath.is_file() and fpath.suffix.lower() in (".pdf", ".txt", ".html"):
            # Size guardrail
            try:
                fsize = fpath.stat().st_size
                if fsize > _MAX_INBOX_FILE_BYTES:
                    logger.warning(
                        "[KaveriDeedScout] Skipping oversized file {} ({} MB > {} MB)",
                        fpath.name,
                        fsize / (1024 * 1024),
                        _MAX_INBOX_FILE_BYTES / (1024 * 1024),
                    )
                    continue
            except OSError:
                logger.warning("[KaveriDeedScout] Cannot stat file: {}", fpath.name)
                continue

            try:
                records = parse_inbox_file(fpath)
                if records:
                    all_records.extend(records)
                    # Write-ahead: partial checkpoint after each successful file
                    write_checkpoint(all_records, f"inbox_wal_{fpath.stem}")
                logger.info(
                    "[KaveriDeedScout] Parsed {}: {} records",
                    fpath.name,
                    len(records),
                )
            except Exception as exc:
                logger.error(
                    "[KaveriDeedScout] Failed to parse {}: {}",
                    fpath.name,
                    exc,
                )

    return all_records


def write_checkpoint(records: list[dict[str, Any]], mode: str) -> Path:
    """Write records to a JSON checkpoint file (Stage 1 pattern).

    Cleans up stale WAL (write-ahead) checkpoints after a final checkpoint.
    Returns the path to the checkpoint file.
    """
    _CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    fname = f"kaveri_deeds_{mode}_{timestamp}.json"
    fpath = _CHECKPOINT_DIR / fname

    checkpoint = {
        "meta": {
            "mode": mode,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "record_count": len(records),
            "source": "kaveri_deeds_scout",
        },
        "records": records,
    }
    fpath.write_text(json.dumps(checkpoint, indent=2, default=str))
    n = len(records)
    logger.info("[KaveriDeedScout] Checkpoint written: {} ({} records)", fpath, n)

    # Clean up WAL checkpoints after final checkpoint
    if "wal_" not in mode:
        for f in _CHECKPOINT_DIR.glob("kaveri_deeds_inbox_wal_*.json"):
            try:
                f.unlink()
                logger.debug("[KaveriDeedScout] Cleaned up WAL checkpoint: {}", f.name)
            except OSError:
                pass

    return fpath


def read_latest_checkpoint() -> list[dict[str, Any]] | None:
    """Read the latest checkpoint file. Returns records list or None."""
    if not _CHECKPOINT_DIR.exists():
        return None
    files = sorted(_CHECKPOINT_DIR.glob("kaveri_deeds_*.json"))
    if not files:
        return None
    latest = files[-1]
    try:
        data = json.loads(latest.read_text())
        return data.get("records", [])
    except (json.JSONDecodeError, Exception) as exc:
        logger.error("[KaveriDeedScout] Failed to read checkpoint: {}", exc)
        return None


def run_live_mode() -> list[dict[str, Any]]:
    """Run Playwright-assisted live extraction from Kaveri Online Services.

    Currently a stub — live mode will be implemented when Playwright
    environment is available in the agents container. Returns empty list.
    """
    logger.warning("[KaveriDeedScout] Live mode not yet implemented — returning empty")
    return []


def run_inbox_mode() -> list[dict[str, Any]]:
    """Run inbox mode: parse files and write checkpoint."""
    records = parse_inbox_all()
    if records:
        write_checkpoint(records, "inbox")
    else:
        logger.info("[KaveriDeedScout] No records found in inbox")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Kaveri Deed Scout")
    parser.add_argument(
        "--mode",
        choices=["inbox", "live", "both"],
        default="inbox",
        help="Scraping mode: inbox (parse manual exports), live (Playwright), both",
    )
    parser.add_argument(
        "--checkpoint",
        action="store_true",
        help="Read and print latest checkpoint",
    )
    args = parser.parse_args()

    if args.checkpoint:
        records = read_latest_checkpoint()
        if records:
            print(json.dumps(records, indent=2, default=str))
        else:
            print("No checkpoint found")
        return

    all_records: list[dict[str, Any]] = []

    if args.mode in ("inbox", "both"):
        inbox_records = run_inbox_mode()
        all_records.extend(inbox_records)
        logger.info("[KaveriDeedScout] Inbox mode: {} records", len(inbox_records))

    if args.mode in ("live", "both"):
        live_records = run_live_mode()
        all_records.extend(live_records)
        logger.info("[KaveriDeedScout] Live mode: {} records", len(live_records))

    # Final checkpoint for --mode both
    if args.mode == "both" and all_records:
        write_checkpoint(all_records, "both")

    print(json.dumps({"status": "ok", "total_records": len(all_records)}, indent=2))


if __name__ == "__main__":
    main()
