"""GATE-120 — Intelligence Confidence Calibration.
5 assertions: (1) mypy blind spots doc exists, (2) k6 script no target:50,
(3) run_confidence_decay_check callable, (4) get_data_floor callable + returns int,
(5) run_data_floor_refresh registered in scheduler.
"""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


def test_gate120_assertion1_mypy_blind_spots_doc_exists():
    doc = Path("docs/solutions/best-practices/mypy_blind_spots.md")
    assert doc.exists()
    content = doc.read_text()
    assert "psycopg2" in content
    assert "chromadb" in content
    assert "yaml" in content


def test_gate120_assertion2_k6_no_target_50():
    script = Path("tests/load/k6_baseline.js")
    assert script.exists()
    content = script.read_text()
    assert "target: 50" not in content, "CI-aggressive VU count must be removed"


def test_gate120_assertion3_confidence_decay_callable():
    content = Path("config/scheduler/maintenance_jobs.py").read_text()
    assert "def run_confidence_decay_check" in content


def test_gate120_assertion4_get_data_floor_callable():
    from config.settings import get_data_floor, _data_floor_cache
    _data_floor_cache.clear()
    assert callable(get_data_floor)
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_row = MagicMock()
        mock_row.__getitem__.return_value = 100
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        result = get_data_floor("Yelahanka")
        assert isinstance(result, int)


def test_gate120_assertion5_data_floor_refresh_registered():
    scheduler_content = Path("config/scheduler/maintenance_jobs.py").read_text()
    assert "data_floor_refresh" in scheduler_content
    assert "id=\"data_floor_refresh\"" in scheduler_content
    assert "CronTrigger(day=1, hour=5, minute=0, timezone=\"UTC\")" in scheduler_content
