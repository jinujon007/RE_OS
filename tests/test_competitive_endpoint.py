"""Unit tests for GET /api/competitive/pulse (T-974)."""

import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from dashboard.app_fastapi import app, _pulse_cache, _pulse_cache_lock

pytestmark = pytest.mark.unit

client = TestClient(app)


class TestCompetitivePulseEndpoint:
    def setup_method(self):
        with _pulse_cache_lock:
            _pulse_cache.clear()

    def test_competitive_pulse_returns_200(self):
        with patch(
            "intelligence.competitive_intel.CompetitiveIntelEngine"
        ) as MockEngine:
            mock_instance = MagicMock()
            mock_instance.pulse.return_value = {
                "new_launches": [],
                "psf_movers": [],
                "absorption_leaders": [],
                "generated_at": "2026-06-06T12:00:00",
                "market_filter": None,
                "days_window": 7,
            }
            MockEngine.return_value = mock_instance
            resp = client.get("/api/competitive/pulse")
        assert resp.status_code == 200

    def test_competitive_pulse_has_all_3_sections(self):
        with patch(
            "intelligence.competitive_intel.CompetitiveIntelEngine"
        ) as MockEngine:
            mock_instance = MagicMock()
            mock_instance.pulse.return_value = {
                "new_launches": [{"project_name": "A", "market": "Yelahanka"}],
                "psf_movers": [{"project_name": "B", "change_pct": 10.0}],
                "absorption_leaders": [{"project_name": "C", "absorption_pct": 80.0}],
                "generated_at": "2026-06-06T12:00:00",
                "market_filter": "Yelahanka",
                "days_window": 7,
            }
            MockEngine.return_value = mock_instance
            resp = client.get("/api/competitive/pulse?market=Yelahanka")
        data = resp.json()
        assert "new_launches" in data
        assert "psf_movers" in data
        assert "absorption_leaders" in data

    def test_competitive_pulse_market_filter_applied(self):
        with patch(
            "intelligence.competitive_intel.CompetitiveIntelEngine"
        ) as MockEngine:
            mock_instance = MagicMock()
            mock_instance.pulse.return_value = {
                "new_launches": [{"project_name": "A", "market": "Devanahalli"}],
                "psf_movers": [],
                "absorption_leaders": [],
                "generated_at": "2026-06-06T12:00:00",
                "market_filter": "Devanahalli",
                "days_window": 30,
            }
            MockEngine.return_value = mock_instance
            resp = client.get("/api/competitive/pulse?market=Devanahalli&days=30")
        data = resp.json()
        assert data["market_filter"] == "Devanahalli"
        assert data["days_window"] == 30

    def test_competitive_pulse_cache_hit_returns_cached(self):
        from dashboard.app_fastapi import _PULSE_CACHE_TTL
        import time as _time

        test_data = {
            "new_launches": [],
            "psf_movers": [],
            "absorption_leaders": [],
            "generated_at": "2026-06-06T12:00:00",
            "market_filter": "Yelahanka",
            "days_window": 7,
        }
        with _pulse_cache_lock:
            _pulse_cache["Yelahanka:7:5"] = (_time.time() + _PULSE_CACHE_TTL, test_data)
        resp = client.get("/api/competitive/pulse?market=Yelahanka&days=7&top_n=5")
        assert resp.status_code == 200
        assert resp.json()["market_filter"] == "Yelahanka"

    def test_competitive_pulse_error_returns_500(self):
        with patch(
            "intelligence.competitive_intel.CompetitiveIntelEngine"
        ) as MockEngine:
            MockEngine.side_effect = Exception("Engine crash")
            resp = client.get("/api/competitive/pulse")
        assert resp.status_code == 500
        assert "error" in resp.json()
