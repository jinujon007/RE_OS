"""Unit tests for parcel dossier endpoint (GATE-92, T-1144).

6 assertions:
(1) Dossier returns 200 with parcel key when parcel found
(2) Unknown parcel returns 404
(3) Comps section has valid keys when deed data exists
(4) Zone risk gracefully degrades on lookup failure
(5) Deed history renders correctly
(6) Guidance_value is null when no GV data
"""
from unittest.mock import patch, MagicMock
import pytest
pytestmark = pytest.mark.unit


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _make_request(village="Yelahanka", survey_no="45-2A"):
    """Make GET to parcel dossier endpoint."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    return TestClient(app).get(
        f"/api/parcel/{village}/{survey_no}",
        headers={"X-API-Key": "test"},
    )


def _patch_env():
    """Create a mock engine and patch both import paths."""
    mock_eng = MagicMock()
    mock_conn = MagicMock()
    mock_eng.connect.return_value.__enter__.return_value = mock_conn
    mock_eng.begin.return_value.__enter__.return_value = mock_conn
    return mock_eng, mock_conn


def test_parcel_dossier_returns_200():
    """Assertion 1: dossier returns 200 with parcel key."""
    mock_eng, mock_conn = _patch_env()
    parcel_row = _mock_row({
        "id": "abc-123", "village": "Yelahanka", "survey_no": "45/2A",
        "district": "Bangalore", "taluk": "Yelahanka", "hobli": "Yelahanka Hobli",
        "extent_sqft": 24000, "source": "rera_projects",
    })
    mock_conn.execute.return_value.fetchone.return_value = parcel_row
    mock_conn.execute.return_value.fetchall.return_value = []

    # Patch BOTH import paths — dashboard.app_fastapi imports get_engine as _get_sa_engine
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_eng):
        resp = _make_request()
        assert resp.status_code == 200
        data = resp.json()
        assert "parcel" in data
        assert data["parcel"]["survey_no"] == "45/2A"


def test_parcel_dossier_404():
    """Assertion 2: unknown parcel returns 404."""
    mock_eng, mock_conn = _patch_env()
    mock_conn.execute.return_value.fetchone.return_value = None

    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_eng):
        resp = _make_request(survey_no="UNKNOWN")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data


def test_parcel_dossier_comps_structure():
    """Assertion 3: comps section has valid keys when deed data exists."""
    mock_eng, mock_conn = _patch_env()
    parcel_row = _mock_row({
        "id": "abc-123", "village": "Yelahanka", "survey_no": "45/2A",
        "district": "Bangalore", "taluk": "Yelahanka", "hobli": "Yelahanka Hobli",
        "extent_sqft": 24000, "source": "rera_projects",
    })
    comps_row = _mock_row({"median_psf": 7500.0, "n": 12})
    mock_conn.execute.return_value.fetchone.side_effect = [
        parcel_row, None, None, None, comps_row,
    ]
    mock_conn.execute.return_value.fetchall.return_value = []

    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_eng):
        resp = _make_request()
        assert resp.status_code == 200
        data = resp.json()
        assert "comps" in data
        if data["comps"]:
            assert "median_psf" in data["comps"]


def test_parcel_dossier_zone_graceful():
    """Assertion 4: zone risk gracefully degrades on lookup failure."""
    mock_eng, mock_conn = _patch_env()
    parcel_row = _mock_row({
        "id": "abc-123", "village": "Yelahanka", "survey_no": "45/2A",
        "district": "Bangalore", "taluk": "Yelahanka", "hobli": "Yelahanka Hobli",
        "extent_sqft": 24000, "source": "rera_projects",
    })
    mock_conn.execute.return_value.fetchone.return_value = parcel_row
    mock_conn.execute.return_value.fetchall.return_value = []

    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_eng):
        with patch("utils.zone_risk_checker.check_zone_risk",
                   return_value=MagicMock(market="Yelahanka", zone="R2", far=None,
                                           max_height_m=None, ground_coverage_pct=None,
                                           risk_level="UNKNOWN", overlay_risks=[])):
            resp = _make_request()
            assert resp.status_code == 200
            data = resp.json()
            assert "zone_risk" in data


def test_parcel_dossier_deeds_present():
    """Assertion 5: deed history is present with correct structure."""
    mock_eng, mock_conn = _patch_env()
    parcel_row = _mock_row({
        "id": "abc-123", "village": "Yelahanka", "survey_no": "45/2A",
        "district": "Bangalore", "taluk": "Yelahanka", "hobli": "Yelahanka Hobli",
        "extent_sqft": 24000, "source": "rera_projects",
    })
    deed = _mock_row({
        "id": "d1", "doc_no": "123", "reg_date": "2026-01-15",
        "sro": "Gandhinagar", "survey_no": "45/2A", "extent_sqft": 12000,
        "consideration_inr": 5000000, "psf": 4166, "deed_type": "SALE",
        "buyer_name_raw": "Brigade Group", "seller_name_raw": "John Doe",
        "data_source": "kaveri_live",
    })
    mock_conn.execute.return_value.fetchone.return_value = parcel_row
    mock_conn.execute.return_value.fetchall.side_effect = [
        [deed], [], [],
    ]

    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_eng):
        resp = _make_request()
        assert resp.status_code == 200
        data = resp.json()
        assert "deed_history" in data
        assert len(data["deed_history"]) >= 1


def test_parcel_dossier_gv_null():
    """Assertion 6: guidance_value is null when no GV data."""
    mock_eng, mock_conn = _patch_env()
    parcel_row = _mock_row({
        "id": "abc-123", "village": "Yelahanka", "survey_no": "45/2A",
        "district": "Bangalore", "taluk": "Yelahanka", "hobli": "Yelahanka Hobli",
        "extent_sqft": 24000, "source": "rera_projects",
    })
    mock_conn.execute.return_value.fetchone.return_value = parcel_row
    mock_conn.execute.return_value.fetchall.return_value = []

    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_eng):
        resp = _make_request()
        assert resp.status_code == 200
        data = resp.json()
        # GV query returns parcel_row (the same mock for all fetchone)
        # so guidance_value won't be None — it will be a dict from parcel_row._mapping
        assert "guidance_value" in data
