"""
RE_OS — KaveriDeedScout (Sprint 91.5 — T-1156)

EC Form 15 PDF parser using pdfplumber table extraction.

Real EC Form 15 (encoded EC from Kaveri Online Services) has a 9-column table:

  Column   Row index  Content
  col1     0          Serial number (sl no)
  col2     1          Property description (village, hobli, survey_no, extent)
  col3     2          Execution date (dd-mm-yyyy)
  col4     3          Article Name / Market Value / Consideration Amount
  col5     4          Seller / Executant
  col6     5          Buyer / Claimant
  col7     6          Volume
  col8     7          Page / CD no
  col9     8          Registration reference (doc_no)

Multi-page continuation rows (empty sl no / date) are stitched to the previous
transaction's property description. Header rows (Kannada text, column numbers)
and header artifacts (Kannada overflow text like "F\\ny") are filtered out.

Known limitations:
- SRO prefix map covers only 5 test-market prefixes (BYP, YAN, HBB, HSR, BDA).
  Karnataka-scope usage needs full 35-district prefix mapping.
- Village extraction relies on "Index-II Village:" label — some ECs omit this
  label and use header-level village names (not yet extracted).
- Buyer/seller names with Kannada text or (cid:NNN) encoding get low confidence
  but the raw text is preserved for downstream fuzzy matching.
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

__all__ = [
    "parse_pdf_file", "parse_inbox_file", "parse_inbox_all",
    "write_checkpoint", "read_latest_checkpoint",
    "run_inbox_mode", "run_live_mode",
]

# Paths
_DATA_DIR = Path("data/kaveri_deeds")
_INBOX_DIR = _DATA_DIR / "inbox"
_CHECKPOINT_DIR = _DATA_DIR / "checkpoints"

# Safety limits
_MAX_CHECKPOINT_BYTES = 50 * 1024 * 1024
_MAX_INBOX_FILE_BYTES = 10 * 1024 * 1024

# ── Regex patterns for EC Form 15 column extraction ─────────────────────────

# Doc_no: column 9 — e.g. BYP-1-14551-2022-23, YAN-1-06807-2020-21
_DOC_NO_RE = re.compile(r"([A-Z]{2,4}-\d-\d{4,6}-\d{4}-\d{2})")

# Date: column 3 — dd-mm-yyyy
_DATE_RE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")

# Article Name / Deed type from col4
_ARTICLE_NAME_RE = re.compile(r"Article\s*Name:\s*([^;]+)")

# Market Value from col4
_MARKET_VALUE_RE = re.compile(r"Market\s*Value:\s*([\d,]+)", re.IGNORECASE)

# Consideration Amount from col4
_CONSIDERATION_RE = re.compile(
    r"Consideration\s*Amount\s*:?\s*([\d,]+)", re.IGNORECASE
)

# Village from col2: "Index-II Village: Venkatala"
_VILLAGE_RE = re.compile(r"Index-II\s*Village:\s*([^,\n]+)")

# Hobli from col2: "Hobli Name: Yalahanka 1"
_HOBLI_RE = re.compile(r"Hobli\s*Name:\s*([^,\n]+)")

# Survey number from col2: "Sy No 3", "Sy. No. 45/2", "Survey No. 101/1A", "Sy No 26", "Sy. No. 45/2-A"
_SURVEY_NO_RE = re.compile(
    r"(?:(?:Sy|Survey)(?:\.| No\.?|)\s*No[:.\s]*([\d]{1,4}(?:/[\dA-Za-z]+)*(?:-?[A-Z])?))",
)

# Extent from col2: "in all measuring 250 x 29 ft" or "Measurement: 2400 Sq.Feet"
_EXTENT_RE = re.compile(
    r"(?:in\s+all\s+measuring\s+([\d,]+)\s*Sq\s*\.?\s*ft"
    r"|Measurement:\s*([\d,]+)\s*Sq\.?\s*Feet?)",
    re.IGNORECASE,
)

# Extent in guntas / acres: "1 Acre 10 Guntas"
_EXTENT_GUNTA_RE = re.compile(
    r"(?:measuring\s+)?(\d+)\s*Acre(?:s)?\s*(?:(\d+)\s*Guntas?)?",
    re.IGNORECASE,
)
_ACRE_TO_SQFT = 43560
_GUNTA_TO_SQFT = 1089  # 1 gunta = 1089 sqft

# Kannada character detection — buyer/seller names with >30% non-ASCII get low confidence
_KANNADA_RE = re.compile(r"[\u0C80-\u0CFF\u0D80-\u0DFF\u200C-\u200F]")
_CID_RE = re.compile(r"\(cid:\d+\)")

# ── Header detection ────────────────────────────────────────────────────────

# Row 0 of every page has Kannada header text
_HEADER_ROW_0_PATTERN = re.compile(r"ಕಪ್ರ", re.UNICODE)

# ── Document number pattern validation ──────────────────────────────────────
_DOC_NO_PATTERN = re.compile(r"^[A-Z]{2,4}-\d-\d{4,6}-\d{4}-\d{2}$")


def _is_header_row(row: list[str | None]) -> bool:
    """Detect if a table row is a header row (skip)."""
    sl_no_cell = (row[0] or "").strip()
    doc_no_cell = (row[8] or "").strip() if len(row) > 8 else ""
    sl_no_clean = re.sub(r"\(cid:\d+\)", "", sl_no_cell)

    # Row 0: Kannada header
    if _HEADER_ROW_0_PATTERN.search(sl_no_clean):
        return True
    # Row 2: column numbers (col1="1", col9="9")
    if sl_no_cell == "1" and doc_no_cell == "9":
        return True
    # Row 1: sub-header — col5/col6 may have Kannada sub-header text
    if not sl_no_cell and doc_no_cell == "" and len(row) > 4:
        col5_raw = (row[4] or "").strip()
        col6_raw = (row[5] or "").strip()
        if _CID_RE.search(col5_raw + col6_raw):
            return True
    return False


def _is_header_artifact(row: list[str | None]) -> bool:
    """Detect table rows that are page-header overflow artifacts (not continuation)."""
    sl_no_cell = (row[0] or "").strip()
    date_cell = (row[2] or "").strip() if len(row) > 2 else ""
    doc_no_cell = (row[8] or "").strip() if len(row) > 8 else ""
    prop_desc_cell = (row[1] or "").strip() if len(row) > 1 else ""

    if doc_no_cell or sl_no_cell:
        return False
    date_clean = date_cell.replace("\n", "").strip()
    if date_clean and len(date_clean) <= 3 and not prop_desc_cell:
        return True
    if not prop_desc_cell and not date_clean:
        return True
    return False


def _extract_doc_no(col9: str) -> str | None:
    """Extract doc_no from column 9."""
    if not col9:
        return None
    m = _DOC_NO_RE.search(col9)
    if m:
        doc = m.group(1)
        if _DOC_NO_PATTERN.match(doc):
            return doc
    return None


def _extract_date(col3: str) -> str | None:
    """Extract date from column 3 (dd-mm-yyyy). Returns ISO date."""
    if not col3:
        return None
    m = _DATE_RE.search(col3)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def _extract_deed_type(col4: str) -> str:
    """Extract deed type from column 4."""
    if not col4:
        return ""
    m = _ARTICLE_NAME_RE.search(col4)
    if m:
        return m.group(1).strip()
    return ""


def _extract_market_value(col4: str) -> float | None:
    """Extract market value from column 4."""
    if not col4:
        return None
    m = _MARKET_VALUE_RE.search(col4)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except (ValueError, IndexError):
            return None
    return None


def _extract_consideration(col4: str) -> float | None:
    """Extract consideration amount from column 4."""
    if not col4:
        return None
    m = _CONSIDERATION_RE.search(col4)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except (ValueError, IndexError):
            return None
    return None


def _extract_village(col2: str) -> str:
    """Extract village name from column 2."""
    if not col2:
        return ""
    m = _VILLAGE_RE.search(col2)
    if m:
        return m.group(1).strip()
    return ""


def _extract_hobli(col2: str) -> str:
    """Extract hobli name from column 2."""
    if not col2:
        return ""
    m = _HOBLI_RE.search(col2)
    if m:
        return m.group(1).strip()
    return ""


def _extract_survey_no(col2: str) -> tuple[str | None, str]:
    """Extract survey number from column 2.

    Returns (survey_no, extraction_confidence).
    """
    if not col2:
        return None, "low"
    has_kannada = bool(_KANNADA_RE.search(col2))
    m = _SURVEY_NO_RE.search(col2)
    if m:
        raw = m.group(1).strip()
        normalized = _normalize_survey_no(raw)
        if normalized:
            confidence = "low" if has_kannada else "high"
            return normalized, confidence
    # Fallback free-text pattern
    direct = re.search(
        r"(?:Sy\s+No|Survey\s+No)[.:\s]*([\d]{1,4}/[\dA-Za-z]+)", col2, re.IGNORECASE
    )
    if direct:
        normalized = _normalize_survey_no(direct.group(1))
        if normalized:
            return normalized, "low"
    return None, "low"


def _normalize_survey_no(raw: str) -> str | None:
    """Normalize survey number: uppercase, strip spaces, unify separators."""
    raw = raw.strip().upper()
    raw = re.sub(r"([\d])-([A-Z])", r"\1\2", raw)
    raw = re.sub(r"([A-Z])-([\d])", r"\1\2", raw)
    raw = raw.strip(" ./\\-")
    if not raw or raw in ("N/A", "NA", "NIL", "NONE", "-", "NULL"):
        return None
    return raw


def _extract_extent(col2: str) -> float | None:
    """Extent in sqft from column 2.

    Prefers 'in all measuring N Sq.ft' (actual land extent) over
    'Measurement: N Sq.Feet' (road frontage / BBMP measurement).
    Returns None if no valid extent found.
    """
    if not col2:
        return None

    # Prefer "in all measuring" pattern (actual land extent)
    m_inall = re.search(
        r"in\s+all\s+measuring\s+([\d,]+)\s*Sq\s*\.?\s*ft",
        col2, re.IGNORECASE,
    )
    if m_inall:
        try:
            return float(m_inall.group(1).replace(",", ""))
        except ValueError:
            pass

    # Fallback: "Measurement: N Sq.Feet" (may be road frontage, not total extent)
    m = _EXTENT_RE.search(col2)
    if m:
        val = m.group(1) or m.group(2)
        if val:
            try:
                return float(val.replace(",", ""))
            except ValueError:
                pass

    # Check for acres/guntas
    m = _EXTENT_GUNTA_RE.search(col2)
    if m:
        acres = int(m.group(1))
        guntas = int(m.group(2)) if m.group(2) else 0
        total_sqft = acres * _ACRE_TO_SQFT + guntas * _GUNTA_TO_SQFT
        if total_sqft >= 40:
            return float(total_sqft)
    return None


def _extract_parties(
    col5: str, col6: str,
) -> tuple[str, str, str]:
    """Extract seller/buyer from columns 5/6.

    Returns (seller_raw, buyer_raw, extraction_confidence_adjustment).
    confidence='low' if >30% non-ASCII or (cid: present.
    """
    seller = (col5 or "").strip()
    buyer = (col6 or "").strip()

    seller_has_cid = bool(_CID_RE.search(seller))
    buyer_has_cid = bool(_CID_RE.search(buyer))

    seller_has_kannada = bool(_KANNADA_RE.search(seller))
    buyer_has_kannada = bool(_KANNADA_RE.search(buyer))

    seller_clean = _CID_RE.sub("", seller).strip()
    buyer_clean = _CID_RE.sub("", buyer).strip()

    if seller_has_cid or buyer_has_cid or seller_has_kannada or buyer_has_kannada:
        return seller_clean, buyer_clean, "low"

    return seller_clean, buyer_clean, "medium"


def _extract_psf(
    consideration_inr: float | None, extent_sqft: float | None
) -> tuple[float | None, str]:
    """Compute PSF with bounds ₹500–₹50,000."""
    if consideration_inr is None or extent_sqft is None or extent_sqft <= 0:
        return None, "low"
    psf_val = consideration_inr / extent_sqft
    if 500 <= psf_val <= 50_000:
        return round(psf_val, 2), "medium"
    return None, "low"


def _parse_ec_form15_rows(all_rows: list[list[str | None]]) -> list[dict[str, Any]]:
    """Parse extracted table rows from EC Form 15 PDF into deed records.

    Handles header rows, continuation rows (multi-page property descriptions),
    and header artifacts.
    """
    data_rows: list[list[str | None]] = []
    for row in all_rows:
        if not row:
            continue
        while len(row) < 9:
            row.append(None)
        if _is_header_row(row):
            continue
        if _is_header_artifact(row):
            continue
        data_rows.append(row)

    transactions: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    prev_desc_parts: list[str] = []

    for row in data_rows:
        sl_no_col = (row[0] or "").strip()        # column 1 — serial no
        prop_desc = (row[1] or "").strip()         # column 2 — property description
        date_col = (row[2] or "").strip()          # column 3 — execution date
        deed_val_col = (row[3] or "").strip()      # column 4 — deed type + values
        doc_no_col = (row[8] or "").strip()        # column 9 — doc_no
        doc_no = _extract_doc_no(doc_no_col)

        has_sl_no = bool(sl_no_col) and sl_no_col.isdigit()
        is_new = doc_no is not None and has_sl_no

        if is_new:
            if current is not None:
                _finalize_transaction(current, prev_desc_parts)
                transactions.append(current)
            prev_desc_parts = [prop_desc] if prop_desc else []

            deed_type = _extract_deed_type(deed_val_col)
            market_value = _extract_market_value(deed_val_col)
            consideration = _extract_consideration(deed_val_col)
            village = _extract_village(prop_desc)
            hobli = _extract_hobli(prop_desc)

            # Preliminary survey_no from first col2 (may update after stitching)
            survey_no, sn_confidence = _extract_survey_no(prop_desc)
            extent = _extract_extent(prop_desc)
            reg_date = _extract_date(date_col)

            seller, buyer, party_confidence = _extract_parties(
                (row[4] or "") if len(row) > 4 else "",
                (row[5] or "") if len(row) > 5 else "",
            )

            current = {
                "doc_no": doc_no,
                "reg_date": reg_date or "",
                "sro": _extract_sro_from_doc_no(doc_no) or "",
                "district": "",
                "taluk": "",
                "hobli": hobli,
                "village": village,
                "survey_no": survey_no or "",
                "extent_sqft": extent,
                "market_value_inr": market_value,
                "consideration_inr": consideration,
                "psf": None,
                "deed_type": deed_type,
                "buyer_name_raw": buyer,
                "seller_name_raw": seller,
                "extraction_confidence": "low",
                "property_description": "",
            }
        else:
            if prop_desc:
                prev_desc_parts.append(prop_desc)

    if current is not None:
        _finalize_transaction(current, prev_desc_parts)
        transactions.append(current)

    return transactions


def _finalize_transaction(
    current: dict[str, Any], desc_parts: list[str]
) -> None:
    """Stitch property description parts and re-extract fields from full text."""
    if not desc_parts:
        return
    full_desc = " ".join(desc_parts)
    current["property_description"] = full_desc

    if not current.get("survey_no"):
        survey_no, sn_confidence = _extract_survey_no(full_desc)
        current["survey_no"] = survey_no or ""

    # Re-extract extent from full description (prefers 'in all measuring' pattern)
    full_extent = _extract_extent(full_desc)
    if full_extent is not None:
        current["extent_sqft"] = full_extent

    if not current.get("village"):
        village = _extract_village(full_desc)
        current["village"] = village

    if not current.get("hobli"):
        hobli = _extract_hobli(full_desc)
        current["hobli"] = hobli

    consideration = current.get("consideration_inr")
    extent = current.get("extent_sqft")
    psf, psf_confidence = _extract_psf(consideration, extent)
    current["psf"] = psf

    sn_ok = bool(current.get("survey_no"))
    has_consideration = consideration is not None and consideration > 0
    if sn_ok and has_consideration and psf is not None:
        current["extraction_confidence"] = "high"
    elif sn_ok or has_consideration:
        current["extraction_confidence"] = "medium"


def _extract_sro_from_doc_no(doc_no: str) -> str | None:
    """Map doc_no prefix (e.g. BYP, YAN, HSR) to SRO name."""
    if not doc_no:
        return None
    prefix = doc_no.split("-")[0]
    # SRO prefixes — maps doc_no prefix chars to SRO office name.
    # Complete for test markets (Yelahanka/Gandhinagar, Hebbal/Rajajinagar, Devanahalli/Bangalore Rural).
    # Extend for Karnataka scope: add entry per SRO district.
    sro_map = {
        "BYP": "Gandhinagar",    # Yelahanka SRO
        "YAN": "Gandhinagar",    # Yelahanka SRO (alternate)
        "HBB": "Rajajinagar",    # Hebbal SRO
        "HSR": "Rajajinagar",    # Hebbal (Hesaraghatta) SRO
        "BDA": "Bangalore Rural",  # Devanahalli SRO
    }
    return sro_map.get(prefix)


def _extract_tables_from_pdf(pdf_path: str) -> list[list[str | None]]:
    """Extract all table rows from all pages of an EC Form 15 PDF using pdfplumber.
    Returns a flat list of rows (each row is a list of 9 column strings).
    """
    import pdfplumber

    all_rows: list[list[str | None]] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        # Ensure 9 columns
                        padded = list(row) if row else []
                        while len(padded) < 9:
                            padded.append(None)
                        all_rows.append(padded)
    except Exception as exc:
        logger.error("[KaveriDeedScout] Failed to extract tables from {}: {}", pdf_path, exc)
        raise
    return all_rows


def parse_pdf_file(filepath: Path) -> list[dict[str, Any]]:
    """Parse an EC Form 15 PDF file using pdfplumber table extraction.

    Returns a list of deed record dicts.
    """
    all_rows = _extract_tables_from_pdf(str(filepath))
    records = _parse_ec_form15_rows(all_rows)
    for rec in records:
        rec["source_ref"] = filepath.name
        rec["data_source"] = "kaveri_inbox"
    return records


def parse_inbox_file(filepath: Path) -> list[dict[str, Any]]:
    """Parse a single file from the inbox directory. Supports .pdf and .txt/.html.

    Returns a list of deed record dicts.
    """
    suffix = filepath.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf_file(filepath)
    elif suffix in (".txt", ".html", ".htm"):
        logger.warning(
            "[KaveriDeedScout] TXT/HTML fallback not supported for EC Form 15 -- "
            "Table extraction requires PDF. File: {}",
            filepath.name,
        )
        return []
    else:
        logger.warning("[KaveriDeedScout] Unsupported file type: {}", filepath)
        return []


def parse_inbox_all() -> list[dict[str, Any]]:
    """Parse all PDF files in the inbox directory.

    Uses write-ahead checkpointing to preserve partial progress.
    Enforces 10 MB file size limit per inbox file.
    Returns a combined list of all deed records from all files.
    """
    if not _INBOX_DIR.exists():
        _INBOX_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("[KaveriDeedScout] Created inbox directory: {}", _INBOX_DIR)
        return []

    all_records: list[dict[str, Any]] = []
    files = sorted(_INBOX_DIR.iterdir())
    pdf_files = [f for f in files if f.is_file() and f.suffix.lower() == ".pdf"]
    if not pdf_files:
        logger.warning("[KaveriDeedScout] No PDF files found in inbox: {}", _INBOX_DIR)
        return []
    for fpath in pdf_files:
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
            records = parse_pdf_file(fpath)
            if records:
                all_records.extend(records)
                write_checkpoint(all_records, f"inbox_wal_{fpath.stem}")
            logger.info(
                "[KaveriDeedScout] Parsed {}: {} records",
                fpath.name,
                len(records),
            )
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            logger.error(
                "[KaveriDeedScout] Failed to parse {}: {}",
                fpath.name,
                exc,
            )

    return all_records


def write_checkpoint(records: list[dict[str, Any]], mode: str) -> Path:
    """Write records to a JSON checkpoint file (Stage 1 pattern)."""
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
    logger.info("[KaveriDeedScout] Checkpoint written: {} ({} records)", fpath, len(records))

    if "wal_" not in mode:
        for f in _CHECKPOINT_DIR.glob("kaveri_deeds_inbox_wal_*.json"):
            try:
                f.unlink()
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
    """Run Playwright-assisted live extraction (stub)."""
    logger.warning("[KaveriDeedScout] Live mode not yet implemented -- returning empty")
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

    if args.mode == "both" and all_records:
        write_checkpoint(all_records, "both")

    print(json.dumps({"status": "ok", "total_records": len(all_records)}, indent=2))


if __name__ == "__main__":
    main()
