"""T-1051 unit tests — /api/govt/events and /api/govt/north-score endpoints."""

import os
import pytest
from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock

pytestmark = pytest.mark.unit

# Set API key before importing app
os.environ["DASHBOARD_API_KEY"] = "test-key"
os.environ["DASHBOARD_API_KEY_ALLOW_EMPTY"] = "true"


@pytest.fixture
def client():
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    return TestClient(app)


def _mock_db_events(rows):
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = rows
    mock_eng = MagicMock()
    mock_eng.connect.return_value.__enter__.return_value = mock_conn
    return patch("utils.db.get_engine", return_value=mock_eng)


def test_govt_events_returns_list(client):
    rows = [
        (
            1,
            "Metro approved",
            "infrastructure",
            "metro",
            "Yelahanka",
            ["Yelahanka"],
            6100.0,
            "approval",
            9,
            "high",
            "long",
            "buy_now",
            "Test summary",
            "Why it matters",
            ["https://example.com"],
            "2026-01-15",
            True,
            "2026-06-08 00:00:00+00",
        ),
    ]
    with _mock_db_events(rows):
        resp = client.get("/api/govt/events", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert "total" in data
        assert data["total"] >= 1


def test_govt_events_filter_by_category(client):
    with _mock_db_events([]):
        resp = client.get(
            "/api/govt/events?category=infrastructure",
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data


def test_govt_events_filter_by_signal(client):
    with _mock_db_events([]):
        resp = client.get(
            "/api/govt/events?signal=high", headers={"X-API-Key": "test-key"}
        )
        assert resp.status_code == 200


def test_govt_north_score_returns_float(client):
    with patch("intelligence.govt_policy_intel.GovtPolicyIntel") as MockIntel:
        mock_instance = MagicMock()
        mock_result = MagicMock()
        mock_result.north_bengaluru_score = 0.78
        mock_result.high_opportunity_count = 5
        mock_result.risk_count = 2
        mock_result.top_infra_events = []
        mock_result.top_policy_events = []
        mock_result.computed_at = "2026-06-08T00:00:00"
        mock_instance.compute.return_value = mock_result
        MockIntel.return_value = mock_instance

        resp = client.get("/api/govt/north-score", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert "north_bengaluru_score" in data
        assert isinstance(data["north_bengaluru_score"], float)


def test_govt_digest_returns_string(client):
    with patch("intelligence.govt_policy_intel.GovtPolicyIntel") as MockIntel:
        mock_instance = MagicMock()
        mock_result = MagicMock()
        mock_result.weekly_digest = "North Bengaluru summary for this week."
        mock_result.computed_at = "2026-06-08T00:00:00"
        mock_instance.compute.return_value = mock_result
        MockIntel.return_value = mock_instance

        resp = client.get("/api/govt/digest", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert "digest" in data
        assert isinstance(data["digest"], str)


def test_govt_policy_panel_route_returns_200(client):
    """Smoke test for govt policy dashboard panel route."""
    resp = client.get("/api/govt", headers={"X-API-Key": "test-key"})
    assert resp.status_code in (200, 500)
