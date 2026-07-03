"""GATE-169: Deed Inbox Validation + Daily Status — 5 gate assertions (A1-A5).

A1: validate_inbox_pdfs detects empty PDF, zero-page stub, and renamed-non-PDF
A2: process_deed_inbox.py imports validate_inbox_pdfs from utils.deed_inbox_validator
A3: run_deed_daily_status imports without ImportError
A4: run_deed_daily_status() sends Telegram containing "50 target"
A5: "run_deed_daily_status" is in kaveri_jobs.__all__

Edge cases also tested:
- validate_inbox_pdfs with non-existent directory returns zero counts
- validate_inbox_pdfs with max_files caps validation
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ["DASHBOARD_API_KEY_ALLOW_EMPTY"] = "true"
os.environ["DASHBOARD_API_KEY"] = "test-key"
os.environ["DASHBOARD_API_KEY_READ"] = "test-read-key"
os.environ["DASHBOARD_API_KEY_ADMIN"] = "test-admin-key"

pytestmark = pytest.mark.unit


# ════════════════════════════════════════════════════════════
# A1: validate_inbox_pdfs detects invalid PDFs
# ════════════════════════════════════════════════════════════


def test_gate169_a1_validate_inbox_pdfs_detects_invalid():
    """A1: validate_inbox_pdfs returns exactly 2 invalid + 1 valid from mixed set."""
    from utils.deed_inbox_validator import validate_inbox_pdfs

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # Empty file → invalid: "empty"
        empty_pdf = tmp_dir / "empty.pdf"
        empty_pdf.write_bytes(b"")

        # Valid minimal PDF with 1 page — use pypdf to create legit structure
        valid_pdf = tmp_dir / "valid.pdf"
        _write_valid_minimal_pdf(valid_pdf)

        # Text file with .pdf extension → invalid: "corrupted"
        fake_pdf = tmp_dir / "notpdf.txt.pdf"
        fake_pdf.write_text("this is not a pdf at all")

        result = validate_inbox_pdfs(tmp_dir)
        assert result["valid_count"] == 1, "A1: expected exactly 1 valid PDF"
        assert len(result["invalid"]) == 2, "A1: expected exactly 2 invalid PDFs"
        assert result["total"] == 3, "A1: expected total of 3 PDFs"

        reasons = {inv["reason"] for inv in result["invalid"]}
        assert "empty" in reasons, "A1: empty PDF should be detected as 'empty'"
        assert "corrupted" in reasons, "A1: non-PDF file should be detected as 'corrupted'"


def _write_valid_minimal_pdf(path: Path) -> None:
    """Write a minimal valid 1-page PDF using pypdf internals."""
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    with BytesIO() as buf:
        writer.write(buf)
        buf.seek(0)
        path.write_bytes(buf.read())


# ════════════════════════════════════════════════════════════
# Edge case: non-existent directory returns zeros
# ════════════════════════════════════════════════════════════


def test_gate169_a1_edge_nonexistent_directory():
    """A1 edge: validate_inbox_pdfs returns zeros for non-existent directory."""
    from utils.deed_inbox_validator import validate_inbox_pdfs

    result = validate_inbox_pdfs("/tmp/nonexistent_deed_inbox_xyz")
    assert result["total"] == 0
    assert result["valid_count"] == 0
    assert result["valid"] == []
    assert result["invalid"] == []


# ════════════════════════════════════════════════════════════
# Edge case: max_files limits validation
# ════════════════════════════════════════════════════════════


def test_gate169_a1_edge_max_files_caps_validation():
    """A1 edge: validate_inbox_pdfs with max_files=2 only validates first 2 PDFs."""
    from utils.deed_inbox_validator import validate_inbox_pdfs

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for i in range(5):
            (tmp_dir / f"file{i}.pdf").write_bytes(b"%PDF-1.4 trash")

        result = validate_inbox_pdfs(tmp_dir, max_files=2)
        assert result["total"] == 2, "A1 edge: expected only 2 PDFs validated"
        assert result["valid_count"] == 0
        assert len(result["invalid"]) == 2


# ════════════════════════════════════════════════════════════
# A2: process_deed_inbox.py imports validate_inbox_pdfs
# ════════════════════════════════════════════════════════════


def test_gate169_a2_process_deed_inbox_imports_validator():
    """A2: process_deed_inbox.py source contains validate_inbox_pdfs import."""
    source = Path("scripts/process_deed_inbox.py").read_text(encoding="utf-8")
    assert "validate_inbox_pdfs" in source, (
        "A2: validate_inbox_pdfs must be imported in process_deed_inbox.py"
    )


# ════════════════════════════════════════════════════════════
# A3: run_deed_daily_status importable
# ════════════════════════════════════════════════════════════


def test_gate169_a3_run_deed_daily_status_importable():
    """A3: run_deed_daily_status imports without ImportError."""
    from config.scheduler.kaveri_jobs import run_deed_daily_status

    assert callable(run_deed_daily_status)


# ════════════════════════════════════════════════════════════
# A4: run_deed_daily_status sends Telegram with "50 target"
# ════════════════════════════════════════════════════════════


def test_gate169_a4_run_deed_daily_status_telegram():
    """A4: run_deed_daily_status calls Telegram exactly once with '50 target'."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.scalar.return_value = 10

    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with (
        patch("config.scheduler.kaveri_jobs.get_engine", return_value=mock_engine),
        patch("utils.deed_inbox_validator.validate_inbox_pdfs", return_value={"total": 5, "valid": [], "invalid": [], "valid_count": 0}),
        patch("utils.telegram_notifier.send_message") as mock_tg,
    ):
        from config.scheduler.kaveri_jobs import run_deed_daily_status
        run_deed_daily_status()
        assert mock_tg.call_count == 1, "A4: expected Telegram.send_message called exactly once"
        args, _ = mock_tg.call_args
        assert "50 target" in args[0], "A4: Telegram message must contain '50 target'"
        # Verify the message mentions rejected count
        assert "rejected" in args[0], "A4: Telegram message must mention rejected count"


# ════════════════════════════════════════════════════════════
# A5: run_deed_daily_status in kaveri_jobs.__all__
# ════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════
# Edge case: quarantine_invalid moves files + writes JSONL log
# ════════════════════════════════════════════════════════════


def test_gate169_edge_quarantine_moves_invalid_files():
    """Edge: quarantine_invalid moves files to rejected/YYYY-MM-DD/ and logs JSONL."""
    from utils.deed_inbox_validator import quarantine_invalid

    with tempfile.TemporaryDirectory() as tmp:
        inbox = Path(tmp)

        bad = inbox / "bad.pdf"
        bad.write_bytes(b"")
        ok = inbox / "ok.pdf"
        ok.write_bytes(b"%PDF-1.4 valid")

        invalid_list = [{"path": str(bad), "reason": "empty"}]
        count = quarantine_invalid(invalid_list, inbox)

        assert count == 1, "Expected 1 file moved"
        assert not bad.exists(), "Source file should no longer exist"
        rejected_dirs = list(inbox.glob("rejected/*/"))
        assert len(rejected_dirs) == 1, "Expected dated quarantine subfolder"

        log_file = inbox / "rejected" / "rejection_log.jsonl"
        assert log_file.exists(), "Expected rejection_log.jsonl audit trail"
        log_text = log_file.read_text(encoding="utf-8")
        assert "bad.pdf" in log_text, "Audit trail must reference the quarantined file"
        assert "empty" in log_text, "Audit trail must include the reason"
        assert "moved_at" in log_text, "Audit trail must include timestamp"


# ════════════════════════════════════════════════════════════
# Edge case: agent_runs payload structure
# ════════════════════════════════════════════════════════════


def test_gate169_edge_agent_runs_payload_structure():
    """Edge: process_deed_inbox logs correct payload keys when processing occurs."""
    import json

    source = Path("scripts/process_deed_inbox.py").read_text(encoding="utf-8")
    assert "processed" in source, "agent_runs payload must include 'processed'"
    assert "total" in source, "agent_runs payload must include 'total'"
    assert "rejected" in source, "agent_runs payload must include 'rejected'"
    assert "elapsed_seconds" in source, "agent_runs payload must include 'elapsed_seconds'"


def test_gate169_a5_run_deed_daily_status_in_all():
    """A5: run_deed_daily_status is exported in kaveri_jobs.__all__."""
    import config.scheduler.kaveri_jobs as kaveri_jobs

    assert "run_deed_daily_status" in kaveri_jobs.__all__, (
        "A5: run_deed_daily_status must be in kaveri_jobs.__all__"
    )
