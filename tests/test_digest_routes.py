import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit
from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)


class TestDigestRoutes:
    def test_weekly_digest_endpoint_returns_json(self):
        from utils.weekly_digest import WeeklyDigestResult
        with patch("utils.weekly_digest.WeeklyIntelDigest") as MockDigest:
            mock_instance = MagicMock()
            mock_instance.build.return_value = WeeklyDigestResult(market="Yelahanka", psf_delta_pct=5.0, psf_direction="up")
            MockDigest.return_value = mock_instance
            resp = client.get("/api/digest/weekly?market=Yelahanka")
            assert resp.status_code == 200
            data = resp.json()
            assert "psf_delta_pct" in data

    def test_monthly_digest_endpoint_returns_json(self):
        from utils.monthly_digest import MonthlyDigestResult
        with patch("utils.monthly_digest.MonthlyIntelDigest") as MockDigest:
            mock_instance = MagicMock()
            mock_instance.build.return_value = MonthlyDigestResult(market="Yelahanka", psf_mom_pct=3.5)
            MockDigest.return_value = mock_instance
            resp = client.get("/api/digest/monthly?market=Yelahanka")
            assert resp.status_code == 200
            data = resp.json()
            assert "psf_mom_pct" in data

    def test_digest_panel_route_200(self):
        resp = client.get("/digest")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
