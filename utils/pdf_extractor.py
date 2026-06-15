"""
RE_OS — PDF Extractor
──────────────────────
Extracts structured text and tables from machine-readable PDFs.
Uses pdfplumber (MIT license) — pure Python, no OCR, no ML, no GPU.

Designed for:
  - RERA Karnataka approval letters (machine-readable, structured tables)
  - Encumbrance certificates from Kaveri
  - Sale deeds (when machine-readable, not scanned)
  - Developer brochures with pricing tables

For scanned documents (images as PDF), this extractor will return minimal text.
Surya OCR integration is the future path for scanned docs (Phase 12 Legal).

Usage:
  from utils.pdf_extractor import extract_pdf, extract_rera_fields
  result = extract_pdf("/path/to/rera_approval.pdf")
  fields = extract_rera_fields(result["text"])
"""

import re
from pathlib import Path

from loguru import logger

try:
    import pdfplumber

    _PDF_AVAILABLE = True
except ImportError:
    _PDF_AVAILABLE = False
    logger.warning("[PDFExtractor] pdfplumber not installed — PDF extraction disabled")


def extract_pdf(path: str | Path) -> dict:
    """
    Extract text and tables from a machine-readable PDF.

    Returns:
      {
        "text": str,           # full concatenated text
        "pages": int,          # page count
        "tables": list[list],  # all tables found (rows as lists of strings)
        "error": str | None,   # set if extraction failed
      }
    """
    if not _PDF_AVAILABLE:
        return {
            "text": "",
            "pages": 0,
            "tables": [],
            "error": "pdfplumber not installed",
        }

    path = Path(path)
    if not path.exists():
        return {
            "text": "",
            "pages": 0,
            "tables": [],
            "error": f"File not found: {path}",
        }

    try:
        all_text = []
        all_tables = []

        with pdfplumber.open(str(path)) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages:
                # Extract text with layout preservation
                page_text = page.extract_text(layout=True) or ""
                if page_text.strip():
                    all_text.append(page_text)

                # Extract tables — pdfplumber handles bordered and borderless tables
                tables = page.extract_tables()
                for table in tables:
                    # Normalise: flatten None cells to empty string
                    clean = [
                        [str(cell).strip() if cell is not None else "" for cell in row]
                        for row in table
                        if any(cell for cell in row)
                    ]
                    if clean:
                        all_tables.append(clean)

        return {
            "text": "\n\n".join(all_text),
            "pages": pages,
            "tables": all_tables,
            "error": None,
        }

    except Exception as exc:
        logger.error(f"[PDFExtractor] Failed to extract {path}: {exc}")
        return {"text": "", "pages": 0, "tables": [], "error": str(exc)}


def extract_rera_fields(text: str) -> dict:
    """
    Parse RERA Karnataka approval letter text for key fields.
    Uses regex — fast, deterministic, no LLM needed for structured RERA docs.

    Returns dict with extracted fields (empty string where not found).
    Pass the output to Qwen2.5:7b only if regex extraction is incomplete.
    """

    def _find(patterns: list[str], txt: str) -> str:
        for pattern in patterns:
            m = re.search(pattern, txt, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    rera_number = _find(
        [
            r"Registration\s+No[.:\s]+([A-Z0-9/\-]+)",
            r"RERA\s+No[.:\s]+([A-Z0-9/\-]+)",
            r"PRM/KA/RERA/[A-Z0-9/\-]+",
        ],
        text,
    )
    if not rera_number:
        # Try to extract the full RERA number directly
        m = re.search(r"(PRM/KA/RERA/[^\s,]+)", text)
        rera_number = m.group(1) if m else ""

    project_name = _find(
        [
            r"Project\s+Name[:\s]+([^\n]+)",
            r"Name\s+of\s+(?:the\s+)?[Pp]roject[:\s]+([^\n]+)",
        ],
        text,
    )

    promoter = _find(
        [
            r"Promoter(?:'s)?\s+Name[:\s]+([^\n]+)",
            r"Name\s+of\s+Promoter[:\s]+([^\n]+)",
            r"Developer[:\s]+([^\n]+)",
        ],
        text,
    )

    # Total units — look for numbers near "unit" or "flat" or "apartment"
    total_units = _find(
        [
            r"Total\s+(?:No\.?\s+of\s+)?(?:Units?|Flats?|Apartments?)[:\s]+(\d+)",
            r"(\d+)\s+(?:units?|flats?|apartments?)\s+(?:are\s+)?proposed",
        ],
        text,
    )

    land_area = _find(
        [
            r"(?:Land|Plot|Site)\s+Area[:\s]+([\d.,]+\s*(?:acres?|sq\.?\s*ft\.?|sqft|guntas?))",
            r"Total\s+(?:Land|Plot)\s+Area[:\s]+([\d.,]+\s*(?:acres?|sq\.?\s*ft\.?|sqft|guntas?))",
        ],
        text,
    )

    survey_number = _find(
        [
            r"Survey\s+(?:No\.?|Number)[:\s]+([\d/A-Za-z, ]+?)(?:\n|,|\.)",
            r"Sy\.?\s*No\.?\s*[:\s]+([\d/A-Za-z, ]+?)(?:\n|,|\.)",
        ],
        text,
    )

    taluk = _find(
        [r"Taluk[:\s]+([A-Za-z ]+?)(?:\n|,)", r"Taluq[:\s]+([A-Za-z ]+?)(?:\n|,)"],
        text,
    )

    district = _find(
        [r"District[:\s]+([A-Za-z ]+?)(?:\n|,)"],
        text,
    )

    possession_date = _find(
        [
            r"(?:Expected\s+)?(?:Completion|Possession)\s+Date[:\s]+([\d\-/A-Za-z ]+?)(?:\n|,)",
            r"Date\s+of\s+(?:Completion|Possession)[:\s]+([\d\-/A-Za-z ]+?)(?:\n|,)",
        ],
        text,
    )

    return {
        "rera_number": rera_number,
        "project_name": project_name,
        "promoter": promoter,
        "total_units": total_units,
        "land_area": land_area,
        "survey_number": survey_number,
        "taluk": taluk,
        "district": district,
        "possession_date": possession_date,
    }


def tables_to_text(tables: list[list]) -> str:
    """Convert extracted tables to readable text for LLM processing."""
    lines = []
    for i, table in enumerate(tables):
        lines.append(f"[Table {i + 1}]")
        for row in table:
            lines.append(" | ".join(cell for cell in row if cell))
        lines.append("")
    return "\n".join(lines)


def extract_pdf_for_llm(path: str | Path, max_chars: int = 6000) -> str:
    """
    Extract PDF content as a single string ready to feed into an LLM prompt.
    Combines text + tables, truncated to max_chars.
    """
    result = extract_pdf(path)
    if result["error"]:
        return f"[PDF extraction failed: {result['error']}]"

    parts = []
    if result["text"]:
        parts.append(result["text"])
    if result["tables"]:
        parts.append(tables_to_text(result["tables"]))

    combined = "\n\n".join(parts)
    if len(combined) > max_chars:
        combined = combined[:max_chars] + f"\n...[truncated at {max_chars} chars]"
    return combined


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python utils/pdf_extractor.py <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    print(f"Extracting: {pdf_path}\n")
    result = extract_pdf(pdf_path)

    if result["error"]:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"Pages: {result['pages']}")
    print(f"Tables found: {len(result['tables'])}")
    print(f"Text length: {len(result['text'])} chars\n")

    print("=== RERA FIELDS (regex) ===")
    fields = extract_rera_fields(result["text"])
    for k, v in fields.items():
        if v:
            print(f"  {k}: {v}")

    print("\n=== TEXT PREVIEW (first 500 chars) ===")
    print(result["text"][:500])
