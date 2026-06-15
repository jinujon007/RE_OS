import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


@pytest.fixture
def _auth_env():
    with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
        import importlib
        import dashboard.app_fastapi as _fa

        importlib.reload(_fa)
        yield


class TestDemandPanel:
    def test_demand_route_returns_200(self):
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app

        client = TestClient(app)
        resp = client.get("/demand")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_demand_api_returns_json(self, _auth_env):
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app
        from intelligence.demand_intel import DemandSignals

        client = TestClient(app)
        mock_ds = MagicMock(spec=DemandSignals)
        mock_ds.market = "Yelahanka"
        mock_ds.market_found = True
        mock_ds.collected_at = "2026-06-08T00:00:00"
        mock_ds.avg_listing_psf = 8500.0
        mock_ds.median_listing_psf = 8200.0
        mock_ds.listing_trend_30d_pct = 2.5
        mock_ds.listing_count_30d = 50
        mock_ds.absorption_pct = 55.0
        mock_ds.months_of_supply = 12.0
        mock_ds.demand_signal = "NEUTRAL"
        mock_ds.demand_score = 0.5
        mock_ds.demand_score_v2 = 0.45
        mock_ds.ticket_size_median_cr = 65.5
        mock_ds.days_on_market_p50 = 120.0
        mock_ds.config_absorption = {"1BHK": 70.0, "2BHK": 60.0, "3BHK": 50.0}
        mock_ds.absorption_trend = []
        mock_ds.days_on_market_by_config = {"1BHK": 180, "2BHK": 240}
        mock_ds.avg_news_sentiment = 0.05
        mock_ds.kaveri_monthly_approvals = 4500.0
        mock_ds.signals = ["Market is stable"]
        with patch(
            "intelligence.demand_intel.DemandIntel.get_signals", return_value=mock_ds
        ):
            resp = client.get(
                "/api/demand/Yelahanka", headers={"X-API-Key": "test-key"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["market"] == "Yelahanka"
            assert "demand_score_v2" in data
            assert "config_absorption" in data
