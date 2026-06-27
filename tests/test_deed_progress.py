"""T-1412/T-1413 — Deed progress tracker unit tests."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import shutil

pytestmark = pytest.mark.unit


class TestGetInboxProgress:
    @pytest.fixture
    def tmp_inbox(self):
        tmpdir = Path(tempfile.mkdtemp())
        yield tmpdir
        shutil.rmtree(str(tmpdir), ignore_errors=True)

    @pytest.fixture
    def mock_db(self):
        with patch("utils.deed_progress.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn.execute.return_value.scalar.return_value = 0
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            yield

    def test_empty_dir_returns_zeros(self, tmp_inbox, mock_db):
        from utils.deed_progress import get_inbox_progress

        with patch("utils.deed_progress._INBOX_BASE", new=tmp_inbox), \
             patch("utils.deed_progress._FORM17_DIR", new=tmp_inbox / "form17"):
            result = get_inbox_progress()
            assert result["total_pdfs"] == 0
            assert result["ingested"] == 0
            assert result["pending"] == 0
            assert result["pending_files"] == []
            assert result["last_ingested_at"] is None
            assert result["this_week_new_rows"] == 0

    def test_pending_detection_correct(self, tmp_inbox, mock_db):
        from utils.deed_progress import get_inbox_progress

        (tmp_inbox / "new_deed.pdf").touch()
        form17 = tmp_inbox / "form17"
        form17.mkdir()

        with patch("utils.deed_progress._INBOX_BASE", new=tmp_inbox), \
             patch("utils.deed_progress._FORM17_DIR", new=form17):
            result = get_inbox_progress()
            assert result["total_pdfs"] == 1
            assert result["ingested"] == 0
            assert result["pending"] == 1
            assert "new_deed.pdf" in result["pending_files"]

    def test_ingested_dedup_multi_row_pdf(self, tmp_inbox):
        from utils.deed_progress import get_inbox_progress

        (tmp_inbox / "multi.pdf").touch()

        with patch("utils.deed_progress._INBOX_BASE", new=tmp_inbox), \
             patch("utils.deed_progress._FORM17_DIR", new=tmp_inbox / "form17"), \
             patch("utils.deed_progress.get_engine") as mock_eng:
            mock_conn = MagicMock()
            # Same PDF basename from 3 source_refs — should count as 1 ingested
            mock_conn.execute.return_value.fetchall.return_value = [
                ("inbox/multi.pdf", "2026-06-01T00:00:00"),
                ("inbox/multi.pdf", "2026-06-01T01:00:00"),
                ("inbox/multi.pdf", "2026-06-01T02:00:00"),
            ]
            mock_conn.execute.return_value.scalar.return_value = 3
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

            result = get_inbox_progress()
            assert result["total_pdfs"] == 1
            assert result["ingested"] == 1
            assert result["pending"] == 0

    def test_this_week_new_rows_with_market_filter(self, tmp_inbox):
        from utils.deed_progress import get_inbox_progress

        with patch("utils.deed_progress._INBOX_BASE", new=tmp_inbox), \
             patch("utils.deed_progress._FORM17_DIR", new=tmp_inbox / "form17"), \
             patch("utils.deed_progress.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn.execute.return_value.scalar.return_value = 7
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

            result = get_inbox_progress(market="Yelahanka")
            assert result["this_week_new_rows"] == 7

    def test_no_crash_on_missing_inbox_dir(self):
        from utils.deed_progress import get_inbox_progress
        result = get_inbox_progress()
        assert isinstance(result, dict)

    def test_endpoint_registered(self):
        from dashboard.routers.data import router
        found = any(
            hasattr(r, "path") and "/deeds/inbox-progress" in r.path
            for r in router.routes
        )
        assert found

    def test_endpoint_in_read_only_paths(self):
        from dashboard.state import _READ_ONLY_PATHS
        assert "/api/v1/deeds/inbox-progress" in _READ_ONLY_PATHS
        assert "/api/deeds/inbox-progress" in _READ_ONLY_PATHS


class TestComputeThroughputProjection:
    @pytest.mark.parametrize("rows,expected", [
        ([("2026-06-01", 55), ("2026-05-25", 60), ("2026-05-18", 52), ("2026-05-11", 48)], "on_track"),
        ([("2026-06-01", 50), ("2026-05-25", 50), ("2026-05-18", 50), ("2026-05-11", 50)], "on_track"),
        ([("2026-06-01", 45), ("2026-05-25", 44), ("2026-05-18", 40), ("2026-05-11", 42)], "at_risk"),
        ([("2026-06-01", 42), ("2026-05-25", 42), ("2026-05-18", 42), ("2026-05-11", 42)], "at_risk"),
        ([("2026-06-01", 20), ("2026-05-25", 15), ("2026-05-18", 10), ("2026-05-11", 5)], "will_miss"),
        ([("2026-06-01", 41), ("2026-05-25", 41), ("2026-05-18", 41), ("2026-05-11", 41)], "will_miss"),
        ([], "will_miss"),
    ])
    def test_verdict_accuracy(self, rows, expected):
        from utils.deed_progress import compute_throughput_projection
        with patch("utils.deed_progress.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = rows
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            result = compute_throughput_projection()
            assert result["projection_verdict"] == expected

    def test_deadline_constant(self):
        from utils.deed_progress import compute_throughput_projection
        with patch("utils.deed_progress.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            result = compute_throughput_projection()
        assert result["deadline"] == "2026-08-15"
        assert result["required_rate"] == 50
        assert "weeks_remaining" in result

    def test_weeks_to_target_present_when_at_risk(self):
        from utils.deed_progress import compute_throughput_projection
        with patch("utils.deed_progress.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = [
                ("2026-06-01", 45),
                ("2026-05-25", 44),
                ("2026-05-18", 40),
                ("2026-05-11", 42),
            ]
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            result = compute_throughput_projection()
            assert result["projection_verdict"] == "at_risk"
            assert result["weeks_to_target"] is not None
            assert isinstance(result["weeks_to_target"], int)

    def test_endpoint_registered(self):
        from dashboard.routers.data import router
        found = any(
            hasattr(r, "path") and "/deeds/projection" in r.path
            for r in router.routes
        )
        assert found

    def test_projection_in_read_only_paths(self):
        from dashboard.state import _READ_ONLY_PATHS
        assert "/api/v1/deeds/projection" in _READ_ONLY_PATHS
        assert "/api/deeds/projection" in _READ_ONLY_PATHS
