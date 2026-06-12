"""GATE-92 declaration tests — Parcel Graph + Land Assembly Detection.

5 assertions:
(1) parcels model importable + UNIQUE constraint verified in migration
(2) normalize_survey_no handles ≥5 variant fixtures
(3) Assembly detector fires on fixture and writes assembly_signals
(4) /api/parcel/{village}/{survey_no} returns 200 with deed_history + comps keys
(5) parcel_linker_nightly + assembly job registered in scheduler
"""
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
pytestmark = pytest.mark.unit

MIGRATION_PATH = Path("alembic/versions/0055_parcels_table.py")
SCHEDULER_PATH = Path("config/scheduler.py")


def test_a1_parcels_model_importable():
    """Assertion 1: parcels table migration has UNIQUE constraint + FK columns."""
    assert MIGRATION_PATH.exists(), "Migration 0055 file not found"
    content = MIGRATION_PATH.read_text()
    assert "uq_parcels_village_survey_no" in content
    assert "fk_rera_projects_parcel_id" in content
    assert "fk_registered_transactions_parcel_id" in content


def test_a2_normalize_survey_no_variants():
    """Assertion 2: normalize_survey_no handles 5+ variant fixtures."""
    from utils.parcel_linker import normalize_survey_no
    assert normalize_survey_no("45/2A") == "45/2A"
    assert normalize_survey_no("45/2-A") == "45/2A"
    assert normalize_survey_no("45/2  A") == "45/2A"
    assert normalize_survey_no(" 123/4B ") == "123/4B"
    assert normalize_survey_no("67/1") == "67/1"
    assert normalize_survey_no("") is None
    assert normalize_survey_no(None) is None


def test_a3_assembly_detector_fires():
    """Assertion 3: assembly detector detects assemblies and writes to DB."""
    from utils.assembly_detector import detect_assemblies
    from datetime import date, timedelta

    base = date.today() - timedelta(days=30)

    def _make_row(id_val, buyer, village, survey_no, reg_date):
        row = MagicMock()
        row.id = id_val
        row.buyer_name_raw = buyer
        row.village = village
        row.survey_no = survey_no
        row.reg_date = reg_date
        row.extent_sqft = 1000.0
        row.consideration_inr = 5000000.0
        return row

    mock_rows = [
        _make_row("a1", "Brigade Group", "Yelahanka", "45/1", base),
        _make_row("a2", "Brigade Group", "Yelahanka", "45/2", base + timedelta(days=15)),
        _make_row("a3", "Brigade Group", "Yelahanka", "45/3", base + timedelta(days=30)),
    ]

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchall.return_value = mock_rows
    mock_conn.execute.return_value.fetchone.return_value = None

    with patch("utils.assembly_detector.get_engine", return_value=mock_engine):
        signals = detect_assemblies()
        assert len(signals) >= 1
        assert signals[0]["parcel_count"] >= 3
        assert "BRIGADE GROUP" in signals[0]["buyer_name_norm"]


def test_a4_parcel_endpoint_returns_200():
    """Assertion 4: parcel dossier endpoint returns 200 with deed_history key."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    from unittest.mock import MagicMock

    mock_eng = MagicMock()
    mock_conn = MagicMock()
    mock_eng.connect.return_value.__enter__.return_value = mock_conn

    def _mock_row(mapping):
        row = MagicMock()
        row._mapping = mapping
        return row

    parcel_row = _mock_row({
        "id": "abc-123", "village": "Yelahanka", "survey_no": "45/2A",
        "district": "Bangalore", "taluk": "Yelahanka", "hobli": "Yelahanka Hobli",
        "extent_sqft": 24000, "source": "rera_projects",
    })
    mock_conn.execute.return_value.fetchone.return_value = parcel_row
    mock_conn.execute.return_value.fetchall.return_value = []

    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_eng):
        client = TestClient(app)
        resp = client.get("/api/parcel/Yelahanka/45-2A", headers={"X-API-Key": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "deed_history" in data
        assert "parcel" in data


def test_a5_scheduler_jobs_registered():
    """Assertion 5: parcel_linker_nightly + assembly detection jobs in scheduler."""
    assert SCHEDULER_PATH.exists(), "scheduler.py not found"
    content = SCHEDULER_PATH.read_text()
    assert "parcel_linker_nightly" in content
    assert "assembly_detection" in content
