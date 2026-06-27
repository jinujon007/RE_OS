"""GATE-146 declaration — Assembly Intelligence Production.

5 assertions:
1. write_assembly_signal importable from utils.obsidian_sync; returns (str, str)
2. ASSEMBLY_ALERT_THRESHOLDS importable from config.settings; has 'high' and 'medium' keys
3. /api/v1/intel/assembly/{id}/obsidian-export route registered in dashboard/routers/data.py
4. POST /api/v1/intel/assembly/{id}/resolve route registered
5. assembly context injection: Board Room _build_assembly_context returns string with 'ASSEMBLY SIGNALS'
"""
import pathlib
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.unit


_SAMPLE_CLUSTER = {
    "buyer_name": "Gate Test Buyer",
    "village": "Gate Village",
    "market": "Yelahanka",
    "confidence_score": 0.85,
    "parcel_count": 5,
    "total_area_sqm": 10000.0,
    "first_deed_date": "2026-01-15",
    "detected_at": "2026-06-25",
    "survey_numbers": ["1/1", "2/2"],
    "days_active": 45,
    "total_consideration_inr": 25000000,
}


class TestGate146:
    def test_write_assembly_signal_importable(self):
        from utils.obsidian_sync import write_assembly_signal
        assert callable(write_assembly_signal)
        with patch("utils.obsidian_sync._ensure_sync_dir", return_value=True):
            with patch("utils.obsidian_sync._write_md", return_value="/tmp/t.md"):
                fn, content = write_assembly_signal(_SAMPLE_CLUSTER)
                assert isinstance(fn, str)
                assert isinstance(content, str)

    def test_assembly_alert_thresholds_config(self):
        from config.settings import ASSEMBLY_ALERT_THRESHOLDS
        assert "high" in ASSEMBLY_ALERT_THRESHOLDS
        assert "medium" in ASSEMBLY_ALERT_THRESHOLDS
        assert ASSEMBLY_ALERT_THRESHOLDS["high"] > ASSEMBLY_ALERT_THRESHOLDS["medium"]

    def test_obsidian_export_route_registered(self):
        data_py = pathlib.Path("dashboard/routers/data.py").read_text(encoding="utf-8")
        assert "/intel/assembly/{signal_id}/obsidian-export" in data_py

    def test_resolve_route_registered(self):
        data_py = pathlib.Path("dashboard/routers/data.py").read_text(encoding="utf-8")
        assert "/intel/assembly/{signal_id}/resolve" in data_py

    def test_assembly_context_injection(self):
        from crews.board_room import _build_assembly_context
        class _MR:
            def __init__(self, vals):
                self._vals = vals
            def __getitem__(self, i):
                return self._vals[i]
            def __iter__(self):
                return iter(self._vals)
        mock_rows = [_MR(["Test Co", "TV", 5, 0.85, 10000.0])]
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = mock_eng.return_value.connect.return_value.__enter__.return_value
            mock_conn.execute.return_value.fetchall.return_value = mock_rows
            result = _build_assembly_context("Yelahanka")
            assert "ASSEMBLY SIGNALS" in result.upper()
