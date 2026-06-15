"""GATE-64 declaration — Land Intelligence Depth (Sprint 56).

Verification criteria:
1. BhoomiScraper().fetch() returns dict with 'bhoomi_status' key
2. POST /api/landowners returns 201
3. TypologyRecommender(total_units=100).recommend().parking_area_sqft > 0
4. GET /api/landowners/pipeline returns 200 with 'by_status' key
"""

import pytest
from unittest.mock import patch, MagicMock
import importlib

pytestmark = pytest.mark.unit


def _fresh_client():
    from dashboard import app_fastapi

    importlib.reload(app_fastapi)
    from starlette.testclient import TestClient

    return TestClient(app_fastapi.app)


def test_bhoomi_scraper_returns_status_key():
    from scrapers.bhoomi_scraper import fetch

    with patch("urllib.request.urlopen", side_effect=Exception("Portal down")):
        result = fetch("45/2", "Devanahalli")
        assert "bhoomi_status" in result
        assert result["bhoomi_status"] == "unavailable"


def test_create_landowner_returns_201():
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = (
            "u1",
            "45/2",
            "Devanahalli",
            "Test Owner",
            None,
            "primary",
            "cold",
            None,
            None,
            None,
            None,
        )
        client = _fresh_client()
        resp = client.post(
            "/api/landowners",
            json={
                "survey_no": "45/2",
                "market": "Devanahalli",
                "owner_name": "Test Owner",
            },
            headers={"X-API-Key": "test"},
        )
        assert resp.status_code == 201


def test_parking_deducted_from_sellable():
    from utils.fsi_calculator import TypologyRecommender

    result = TypologyRecommender(total_units=100, avg_listing_psf=7000).recommend()
    assert result.parking_area_sqft > 0
    assert result.gdv_cr > 0


def test_landowners_pipeline_returns_by_status():
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.side_effect = [
            [("cold", 5), ("warm", 3)],
            [("Devanahalli", 4, 7500.0)],
        ]
        client = _fresh_client()
        resp = client.get("/api/landowners/pipeline", headers={"X-API-Key": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "by_status" in data
        assert data["by_status"]["cold"] == 5
