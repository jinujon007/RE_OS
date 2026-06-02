"""Tests for rera_export.py (Sprint 36 — RERA Training Data Export)"""
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
pytestmark = pytest.mark.unit


class TestExportRERARecords:
    def test_successful_export(self, tmp_path):
        """Test basic export returns records correctly."""
        mock_rows = [
            MagicMock(
                project_name="Test Project",
                developer_name="Brigade",
                total_units=120,
                completion_date="2025-12-31",
                market="Devanahalli",
                rera_registration_no="RERA/001",
            )
        ]
        with patch("utils.db.get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = mock_rows
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            from data.training.rera_export import export_rera_records
            records = export_rera_records("Devanahalli")
            assert len(records) == 1
            assert records[0]["project_name"] == "Test Project"
            assert records[0]["developer_name"] == "Brigade"
            assert records[0]["total_units"] == 120

    def test_export_empty_db(self):
        """Test graceful handling of empty DB."""
        with patch("utils.db.get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            from data.training.rera_export import export_rera_records
            records = export_rera_records("Devanahalli")
            assert records == []

    def test_export_null_fields_handled(self):
        """Test NULL fields are handled gracefully (B-1 fix)."""
        mock_rows = [
            MagicMock(
                project_name=None,
                developer_name=None,
                total_units=None,
                completion_date=None,
                market="Devanahalli",
                rera_registration_no=None,
            )
        ]
        with patch("utils.db.get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = mock_rows
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            from data.training.rera_export import export_rera_records
            records = export_rera_records("Devanahalli")
            assert len(records) == 1
            assert records[0]["project_name"] == ""
            assert records[0]["total_units"] == 0

    def test_db_query_failure(self):
        """Test graceful handling of DB connection failure."""
        with patch("utils.db.get_engine", side_effect=Exception("DB down")):
            from data.training.rera_export import export_rera_records
            records = export_rera_records("Devanahalli")
            assert records == []
