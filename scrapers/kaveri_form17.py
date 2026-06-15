"""
RE_OS — Form17Parser (Sprint 95 — T-1159)

Parses Kaveri Form 17 Index II PDFs (bulk deed register).

Form 17 (Form of Index No. II) is the official SRO day-book: all registered
documents for a village in a date range. Significantly cleaner than EC Form 15:
no multi-page row continuation per property, no masked survey numbers, no
property-description cell to excavate.

11-column structure (from J-16 live screenshots, Devanahalli Div 1):
  Col 1   village              — sub-division name (e.g. "Division 1")
  Col 2   deed_type_raw        — "{DEED_TYPE} - ₹{AMOUNT}" combined
  Col 3   survey_no_raw        — multi-value, comma-separated
  Col 4   area_raw             — "NNN.NN Sq.Metre"
  Col 5   assessment           — almost always blank
  Col 6   executant            — seller; may span rows; mixed Unicode
  Col 7   claimant             — buyer; same
  Col 8   sro                  — e.g. "Devanahalli"
  Col 9a  execution_date       — DD-MM-YYYY
  Col 9b  registration_date    — DD-MM-YYYY (in same cell or adjacent)
  Col 10  doc_number           — e.g. "DNH-1-13888-2023-24"
  Col 11  remarks              — cancellation references

Multi-row handling:
  1. Long executant/claimant text overflows to next row — same doc_number.
     Merge by concatenating executant/claimant.
  2. Multi-survey deeds — one deed appears on multiple rows with different
     survey numbers, same doc_number. Emit one record per survey number.

Deduplication key: doc_number (unique per registered deed at an SRO).

Inbox path: data/kaveri_deeds/inbox/form17/*.pdf
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from loguru import logger

__all__ = [
    "Form17Parser",
    "parse_form17",
    "parse_form17_inbox",
]

# ── Column index constants ────────────────────────────────────────────────────
_COL_VILLAGE = 0
_COL_DEED_RAW = 1
_COL_SURVEY = 2
_COL_AREA = 3
_COL_ASSESSMENT = 4
_COL_EXECUTANT = 5
_COL_CLAIMANT = 6
_COL_SRO = 7
_COL_EXEC_DATE = 8
_COL_REG_DATE = 9
_COL_DOC_NO = 10
_COL_REMARKS = 11
_MIN_COLS = 10  # doc_number always present when row is real

# ── Regex patterns ────────────────────────────────────────────────────────────

# Deed type + consideration: "Sale - ₹21,00,000.00" or "DTD - ₹1,12,42,000.00"
# Also handles "Sale - ₹.00" (zero consideration) and "Sale - ₹ 21,00,000"
_DEED_CONSIDERATION_RE = re.compile(
    r"^(.+?)\s*-\s*₹\s*([\d,]*\.?\d*)\s*$",
    re.UNICODE | re.DOTALL,
)

# Doc number: e.g. "DNH-1-13888-2023-24", "BYP-1-06807-2020-21"
_DOC_NO_RE = re.compile(r"([A-Z]{2,4}-\d{1,2}-\d{4,6}-\d{4}-\d{2})", re.IGNORECASE)

# Date: DD-MM-YYYY
_DATE_RE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")

# Area in Sq.Metre: "111.42 Sq.Metre" or "108.00 Sq.Metre" or "111.42 Sq. Metre"
_AREA_SQM_RE = re.compile(r"([\d.]+)\s*Sq\.?\s*Metre", re.IGNORECASE)

# Area in Guntas / Acres (some older deeds use traditional units)
_AREA_GUNTA_RE = re.compile(
    r"(\d+)\s*Acre(?:s)?\s*(?:(\d+(?:\.\d+)?)\s*Guntas?)?", re.IGNORECASE
)
_AREA_GUNTA_ONLY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*Guntas?", re.IGNORECASE)

# Sq.ft direct
_AREA_SQFT_RE = re.compile(r"([\d,]+)\s*Sq\.?\s*[Ff]t", re.IGNORECASE)

# Cancellation reference in remarks: "Cancels Document No. DNH-1-XXXXX-YYYY-YY"
_CANCELS_RE = re.compile(
    r"(?:Cancels|Cancel)\s+(?:Document\s+No\.?|Doc\.?\s*No\.?)\s+([A-Z]{2,4}-\d{1,2}-\d{4,6}-\d{4}-\d{2})",
    re.IGNORECASE,
)

# Sq.Metre → Sq.Ft conversion
_SQM_TO_SQFT = 10.7639

_ACRE_TO_SQFT = 43_560
_GUNTA_TO_SQFT = 1_089


def _parse_date(raw: str | None) -> date | None:
    """Parse DD-MM-YYYY → date object."""
    if not raw:
        return None
    m = _DATE_RE.search(raw.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date()
    except ValueError:
        return None


def _parse_consideration(deed_raw: str | None) -> tuple[str, float | None]:
    """Split 'Sale - ₹21,00,000.00' into ('Sale', 2100000.0).

    Returns (deed_type, consideration_inr). consideration_inr is None if
    the amount is missing or zero/blank.
    """
    if not deed_raw:
        return "", None
    deed_raw = deed_raw.strip()
    m = _DEED_CONSIDERATION_RE.match(deed_raw)
    if not m:
        # No ₹ separator — just deed type, no consideration
        return deed_raw, None
    deed_type = m.group(1).strip()
    amt_raw = m.group(2).replace(",", "").strip()
    try:
        amt = float(amt_raw) if amt_raw and amt_raw != "." else 0.0
        return deed_type, (amt if amt > 0 else None)
    except ValueError:
        return deed_type, None


def _parse_area(area_raw: str | None) -> tuple[float | None, str]:
    """Parse area → (sqft, source_unit).

    Returns (None, 'unknown') if unparseable.
    """
    if not area_raw:
        return None, "unknown"
    raw = area_raw.strip()

    # Sq.Metre (primary for Form 17)
    m = _AREA_SQM_RE.search(raw)
    if m:
        try:
            sqm = float(m.group(1))
            sqft = round(sqm * _SQM_TO_SQFT, 2)
            if sqft >= 40:
                return sqft, "sqm"
        except ValueError:
            pass

    # Sq.Ft direct
    m = _AREA_SQFT_RE.search(raw)
    if m:
        try:
            sqft = float(m.group(1).replace(",", ""))
            if sqft >= 40:
                return sqft, "sqft"
        except ValueError:
            pass

    # Acres + Guntas
    m = _AREA_GUNTA_RE.search(raw)
    if m:
        try:
            acres = float(m.group(1))
            guntas = float(m.group(2)) if m.group(2) else 0.0
            sqft = acres * _ACRE_TO_SQFT + guntas * _GUNTA_TO_SQFT
            if sqft >= 40:
                return sqft, "acre_gunta"
        except ValueError:
            pass

    # Guntas only
    m = _AREA_GUNTA_ONLY_RE.search(raw)
    if m:
        try:
            guntas = float(m.group(1))
            sqft = guntas * _GUNTA_TO_SQFT
            if sqft >= 40:
                return sqft, "gunta"
        except ValueError:
            pass

    return None, "unknown"


def _parse_doc_no(raw: str | None) -> str | None:
    """Extract and normalize doc number."""
    if not raw:
        return None
    m = _DOC_NO_RE.search(raw.strip())
    if m:
        return m.group(1).upper()
    return None


def _parse_survey_nos(raw: str | None) -> list[str]:
    """Extract one or more survey numbers from the survey column.

    Form 17 can have comma-separated values or multi-line survey numbers.
    Returns list of normalized survey numbers.
    """
    if not raw:
        return []
    # Split on comma or newline
    parts = re.split(r"[,\n]+", raw)
    result = []
    for part in parts:
        cleaned = part.strip()
        if not cleaned:
            continue
        # Normalize: uppercase, strip separators
        cleaned = cleaned.upper()
        cleaned = re.sub(r"\s+", "", cleaned)
        # Filter garbage (assessment codes like "37-573-99/64" that look like addresses)
        # Accept standard survey patterns: digits, /, letters up to 15 chars
        if re.match(r"^[\dA-Z/\-]{1,20}$", cleaned) and not cleaned.startswith("37-"):
            result.append(cleaned)
    return result


def _is_data_row(row: list[str | None]) -> bool:
    """A data row has a doc_number in the expected column."""
    doc_col = (row[_COL_DOC_NO] or "") if len(row) > _COL_DOC_NO else ""
    return bool(_DOC_NO_RE.search(doc_col))


def _is_header_row(row: list[str | None]) -> bool:
    """Detect header rows: contain column header text."""
    text = " ".join(str(c or "") for c in row[:4]).lower()
    return any(
        kw in text
        for kw in (
            "name of village",
            "nature of deed",
            "survey no",
            "sl no",
            "serial no",
            "village",
        )
    )


def _cell(row: list[str | None], idx: int) -> str:
    """Safe cell access — returns empty string if out of bounds."""
    if idx < len(row):
        return (row[idx] or "").strip()
    return ""


def _compute_psf(consideration_inr: float | None, extent_sqft: float | None) -> float | None:
    """PSF with sanity bounds ₹500–₹50,000."""
    if consideration_inr and extent_sqft and extent_sqft > 0:
        psf = consideration_inr / extent_sqft
        if 500 <= psf <= 50_000:
            return round(psf, 2)
    return None


class Form17Parser:
    """Parses Kaveri Form 17 Index II PDFs.

    Usage:
        parser = Form17Parser()
        records = parser.parse("path/to/form17.pdf")
        # records is a list of dicts, one per unique (doc_number, survey_no)
    """

    def parse(self, filepath: str | Path) -> list[dict[str, Any]]:
        """Parse a Form 17 PDF. Returns list of deed record dicts.

        Each dict has keys:
            village, deed_type, consideration_inr, survey_no_raw, area_sqm,
            extent_sqft, executant, claimant, sro, execution_date,
            registration_date, doc_number, remarks, is_sale_deed,
            cancels_doc_number, psf, data_source, source_ref,
            extraction_confidence
        """
        filepath = Path(filepath)
        logger.info("[Form17Parser] Parsing: {}", filepath.name)

        rows = self._extract_rows(filepath)
        if not rows:
            logger.warning("[Form17Parser] No rows extracted from {}", filepath.name)
            return []

        records = self._build_records(rows, source_ref=filepath.name)
        logger.info(
            "[Form17Parser] {} → {} deed records ({} sale deeds)",
            filepath.name,
            len(records),
            sum(1 for r in records if r.get("is_sale_deed")),
        )
        return records

    # ── Private ──────────────────────────────────────────────────────────────

    def _extract_rows(self, filepath: Path) -> list[list[str | None]]:
        """Extract all table rows from all pages using pdfplumber."""
        try:
            import pdfplumber
        except ImportError:
            logger.error("[Form17Parser] pdfplumber not installed")
            return []

        all_rows: list[list[str | None]] = []
        try:
            with pdfplumber.open(str(filepath)) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    tables = page.extract_tables()
                    for table in tables:
                        for row in table:
                            if row:
                                # Pad to at least _MIN_COLS
                                padded: list[str | None] = list(row)
                                while len(padded) < _MIN_COLS:
                                    padded.append(None)
                                all_rows.append(padded)
        except Exception as exc:
            logger.error("[Form17Parser] PDF extraction failed {}: {}", filepath, exc)
            raise

        return all_rows

    def _build_records(
        self, rows: list[list[str | None]], source_ref: str
    ) -> list[dict[str, Any]]:
        """Build deed records from extracted rows.

        Groups rows by doc_number, merges executant/claimant continuations,
        expands multi-survey rows.
        """
        # Step 1: group rows by doc_number
        groups: dict[str, dict[str, Any]] = {}
        order: list[str] = []  # preserve insertion order

        for row in rows:
            if _is_header_row(row):
                continue

            doc_no = _parse_doc_no(_cell(row, _COL_DOC_NO))

            if doc_no:
                if doc_no not in groups:
                    order.append(doc_no)
                    groups[doc_no] = {
                        "_rows": [],
                        "doc_number": doc_no,
                        "village": _cell(row, _COL_VILLAGE),
                        "deed_type_raw": _cell(row, _COL_DEED_RAW),
                        "survey_no_raw": _cell(row, _COL_SURVEY),
                        "area_raw": _cell(row, _COL_AREA),
                        "sro": _cell(row, _COL_SRO),
                        "execution_date_raw": _cell(row, _COL_EXEC_DATE),
                        "registration_date_raw": _cell(row, _COL_REG_DATE),
                        "remarks_raw": _cell(row, _COL_REMARKS),
                        "executant_parts": [_cell(row, _COL_EXECUTANT)],
                        "claimant_parts": [_cell(row, _COL_CLAIMANT)],
                    }
                else:
                    # Same doc_number again — multi-survey row: collect extra survey
                    existing = groups[doc_no]
                    extra_survey = _cell(row, _COL_SURVEY)
                    if extra_survey:
                        existing["survey_no_raw"] = (
                            existing["survey_no_raw"] + ", " + extra_survey
                        ).strip(", ")
                    extra_exec = _cell(row, _COL_EXECUTANT)
                    if extra_exec:
                        existing["executant_parts"].append(extra_exec)
                    extra_claim = _cell(row, _COL_CLAIMANT)
                    if extra_claim:
                        existing["claimant_parts"].append(extra_claim)
            else:
                # Continuation row — append executant/claimant to last group
                if order:
                    last = groups[order[-1]]
                    extra_exec = _cell(row, _COL_EXECUTANT)
                    if extra_exec:
                        last["executant_parts"].append(extra_exec)
                    extra_claim = _cell(row, _COL_CLAIMANT)
                    if extra_claim:
                        last["claimant_parts"].append(extra_claim)

        # Step 2: flatten groups into records
        records: list[dict[str, Any]] = []
        from config.settings import SALE_DEED_TYPES

        for doc_no in order:
            g = groups[doc_no]

            deed_type, consideration_inr = _parse_consideration(g["deed_type_raw"])
            extent_sqft, _area_unit = _parse_area(g["area_raw"])
            exec_date = _parse_date(g["execution_date_raw"])
            reg_date = _parse_date(g["registration_date_raw"])
            survey_nos = _parse_survey_nos(g["survey_no_raw"])
            executant = " ".join(p for p in g["executant_parts"] if p).strip()
            claimant = " ".join(p for p in g["claimant_parts"] if p).strip()
            remarks = g["remarks_raw"]

            cancels_doc = None
            if remarks:
                m = _CANCELS_RE.search(remarks)
                if m:
                    cancels_doc = m.group(1).upper()

            is_sale = deed_type in SALE_DEED_TYPES

            psf = _compute_psf(consideration_inr, extent_sqft)

            confidence = "medium"
            if is_sale and consideration_inr and consideration_inr >= 100_000 and reg_date:
                confidence = "high"
            elif not deed_type or not reg_date:
                confidence = "low"

            # Emit one record per survey number (or one with empty survey_no)
            emit_surveys = survey_nos if survey_nos else [""]
            for sv in emit_surveys:
                records.append(
                    {
                        "doc_number": doc_no,
                        "sro": g["sro"],
                        "village": g["village"],
                        "deed_type": deed_type,
                        "deed_type_raw": g["deed_type_raw"],
                        "consideration_inr": consideration_inr,
                        "survey_no_raw": sv,
                        "area_raw": g["area_raw"],
                        "extent_sqft": extent_sqft,
                        "executant": executant,
                        "claimant": claimant,
                        "execution_date": exec_date.isoformat() if exec_date else None,
                        "registration_date": reg_date.isoformat() if reg_date else None,
                        "remarks": remarks,
                        "is_sale_deed": is_sale,
                        "cancels_doc_number": cancels_doc,
                        "psf": psf,
                        "data_source": "kaveri_form17",
                        "source_ref": source_ref,
                        "extraction_confidence": confidence,
                    }
                )

        return records


def parse_form17(filepath: str | Path) -> list[dict[str, Any]]:
    """Module-level convenience wrapper."""
    return Form17Parser().parse(filepath)


def parse_form17_inbox(
    inbox_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Parse all PDFs in data/kaveri_deeds/inbox/form17/.

    Returns combined list of all deed records.
    """
    if inbox_dir is None:
        inbox_dir = Path("data/kaveri_deeds/inbox/form17")
    inbox_dir = Path(inbox_dir)

    if not inbox_dir.exists():
        logger.warning("[Form17Parser] inbox/form17 directory not found: {}", inbox_dir)
        return []

    pdf_files = sorted(inbox_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning("[Form17Parser] No PDF files in {}", inbox_dir)
        return []

    all_records: list[dict[str, Any]] = []
    for pdf in pdf_files:
        try:
            records = parse_form17(pdf)
            all_records.extend(records)
        except Exception as exc:
            logger.error("[Form17Parser] Failed to parse {}: {}", pdf.name, exc)

    logger.info("[Form17Parser] inbox/form17: {} total records", len(all_records))
    return all_records


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "data/kaveri_deeds/inbox/form17/devanahalli_div1_2024_2026.pdf"
    records = parse_form17(path)
    sale_records = [r for r in records if r.get("is_sale_deed")]
    print(f"Total records: {len(records)}, Sale deeds: {len(sale_records)}")
    print(json.dumps(sale_records[:5], indent=2, default=str))
