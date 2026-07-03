"""RE_OS — Deed Inbox PDF Validator (T-1531, T-1534, GATE-169).

Validates PDF files in the deed inbox directory before processing.
Provides quarantine functionality for invalid PDFs.

Usage:
    from utils.deed_inbox_validator import validate_inbox_pdfs, quarantine_invalid

    result = validate_inbox_pdfs("/path/to/inbox", max_files=50)
    for inv in result["invalid"]:
        logger.warning("Rejected {}: {}", inv["path"], inv["reason"])
    moved = quarantine_invalid(result["invalid"], Path("/path/to/inbox"))
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pypdf
from loguru import logger

__all__ = [
    "INVALID_EMPTY",
    "INVALID_CORRUPTED",
    "INVALID_ZERO_PAGES",
    "INVALID_UNREADABLE",
    "INVALID_TOO_LARGE",
    "quarantine_invalid",
    "validate_inbox_pdfs",
]

# Machine-readable invalidation reason constants.
# Consumers can compare against these instead of string literals.
INVALID_EMPTY = "empty"
INVALID_CORRUPTED = "corrupted"
INVALID_ZERO_PAGES = "zero_pages"
INVALID_UNREADABLE = "unreadable"
INVALID_TOO_LARGE = "too_large"

# Maximum PDF file size allowed (500 MB). Files beyond this are rejected
# before being handed to pypdf.PdfReader, preventing OOM on malformed files.
_MAX_PDF_BYTES = 500 * 1024 * 1024

_LOG_PREFIX = "[DeedValidator]"


def validate_inbox_pdfs(inbox_dir: str | Path, max_files: int = 0) -> dict:
    """Validate PDFs in the inbox directory (non-recursive), up to max_files.

    Each PDF is checked for:
        - Emptiness (0 bytes)
        - File size (>500 MB is rejected outright)
        - Readability (OS-level access)
        - PDF validity (pypdf.PdfReader can parse it)
        - Has at least 1 page

    Args:
        inbox_dir: Path to directory containing PDF files to validate.
        max_files: Maximum PDFs to validate. 0 = unlimited.

    Returns:
        dict with keys:
            - valid: list of valid Path objects
            - invalid: list of {"path": str, "reason": str} dicts
            - total: total file count
            - valid_count: count of valid files
    """
    inbox = Path(inbox_dir)
    if not inbox.exists():
        logger.debug("{} Inbox directory does not exist: {}", _LOG_PREFIX, inbox_dir)
        return {"valid": [], "invalid": [], "total": 0, "valid_count": 0}

    valid: list[Path] = []
    invalid: list[dict[str, str]] = []

    pdfs = sorted(inbox.glob("*.pdf"))
    if max_files > 0:
        pdfs = pdfs[:max_files]

    for pdf in pdfs:
        reason = _check_pdf(pdf)
        if reason:
            invalid.append({"path": str(pdf), "reason": reason})
        else:
            valid.append(pdf)

    return {
        "valid": valid,
        "invalid": invalid,
        "total": len(valid) + len(invalid),
        "valid_count": len(valid),
    }


def _check_pdf(path: Path) -> str | None:
    """Validate a single PDF. Returns reason string if invalid, None if valid."""
    try:
        stat = path.stat()
        if stat.st_size == 0:
            return INVALID_EMPTY
        if stat.st_size > _MAX_PDF_BYTES:
            logger.warning("{} {} exceeds {} MB limit", _LOG_PREFIX, path.name, _MAX_PDF_BYTES / (1024 * 1024))
            return INVALID_TOO_LARGE
    except (OSError, PermissionError) as exc:
        logger.debug("{} Cannot stat {}: {}", _LOG_PREFIX, path.name, exc)
        return INVALID_UNREADABLE

    try:
        reader = pypdf.PdfReader(path, strict=False)
    except pypdf.errors.PdfReadError:
        return INVALID_CORRUPTED
    except Exception as exc:
        logger.debug("{} Unexpected error reading {}: {}", _LOG_PREFIX, path.name, exc)
        return INVALID_UNREADABLE

    if len(reader.pages) == 0:
        return INVALID_ZERO_PAGES

    return None


def quarantine_invalid(
    invalid_list: list[dict[str, str]],
    inbox_dir: Path,
) -> int:
    """Move invalid PDF files to a dated quarantine subdirectory.

    Writes a JSONL audit trail at inbox/rejected/rejection_log.jsonl
    with one record per quarantined file.

    Args:
        invalid_list: list of {"path": str, "reason": str} from validate_inbox_pdfs.
        inbox_dir: Root inbox directory.

    Returns:
        Number of files successfully moved.
    """
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    quarantine_dir = inbox_dir / "rejected" / today_str
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    log_path = inbox_dir / "rejected" / "rejection_log.jsonl"
    count = 0

    for entry in invalid_list:
        src = Path(entry["path"])
        if not src.exists():
            logger.debug("{} Skipping already-moved {}", _LOG_PREFIX, entry["path"])
            continue
        try:
            dst = quarantine_dir / src.name
            if dst.exists():
                stem = src.stem
                suffix = src.suffix
                dst = quarantine_dir / f"{stem}_{now_utc.strftime('%H%M%S')}{suffix}"
            shutil.move(str(src), str(dst))
            count += 1
            _append_rejection_log(log_path, entry["path"], entry["reason"], now_utc)
        except OSError as exc:
            logger.warning("{} Failed to quarantine {}: {}", _LOG_PREFIX, src.name, exc)

    return count


def _append_rejection_log(log_path: Path, path: str, reason: str, timestamp: datetime) -> None:
    """Append one rejection record to the JSONL audit trail.

    Uses atomic append (O_APPEND) which is safe for concurrent writes
    as long as each record is below the OS pipe buffer size (~4KB).
    """
    record: dict[str, Any] = {
        "path": path,
        "reason": reason,
        "moved_at": timestamp.isoformat(),
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
        f.flush()
