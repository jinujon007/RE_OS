"""T-1112: PSF forecast API endpoint tests."""
import pytest
import os
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient
pytestmark = pytest.mark.unit


@pytest.fixture
def client():
    os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
    from dashboard.app_fastapi import app
    return TestClient(app)


def test_forecast_endpoint_returns_200(client):
    with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            MagicMock(horizon_months=3, current_psf=6500.0, forecast_psf=6800.0,
                      conf_low=None, conf_high=None, trend_direction="rising",
                      slope_pct_per_month=1.2, data_points=6, mae_pct=3.5,
                      model_version="linear_v1", forecast_date="2026-06-11"),
            MagicMock(horizon_months=6, current_psf=6500.0, forecast_psf=7100.0,
                      conf_low=6500.0, conf_high=7700.0, trend_direction="rising",
                      slope_pct_per_month=1.2, data_points=6, mae_pct=3.5,
                      model_version="linear_v1", forecast_date="2026-06-11"),
            MagicMock(horizon_months=12, current_psf=6500.0, forecast_psf=7700.0,
                      conf_low=None, conf_high=None, trend_direction="rising",
                      slope_pct_per_month=1.2, data_points=6, mae_pct=3.5,
                      model_version="linear_v1", forecast_date="2026-06-11"),
        ]
        resp = client.get("/api/market/forecast/Yelahanka", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200


def test_forecast_endpoint_has_all_keys(client):
    with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            MagicMock(horizon_months=3, current_psf=6500.0, forecast_psf=6800.0,
                      conf_low=None, conf_high=None, trend_direction="rising",
                      slope_pct_per_month=1.2, data_points=6, mae_pct=3.5,
                      model_version="linear_v1", forecast_date="2026-06-11"),
            MagicMock(horizon_months=6, current_psf=6500.0, forecast_psf=7100.0,
                      conf_low=6500.0, conf_high=7700.0, trend_direction="rising",
                      slope_pct_per_month=1.2, data_points=6, mae_pct=3.5,
                      model_version="linear_v1", forecast_date="2026-06-11"),
            MagicMock(horizon_months=12, current_psf=6500.0, forecast_psf=7700.0,
                      conf_low=None, conf_high=None, trend_direction="rising",
                      slope_pct_per_month=1.2, data_points=6, mae_pct=3.5,
                      model_version="linear_v1", forecast_date="2026-06-11"),
        ]
        resp = client.get("/api/market/forecast/Yelahanka", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    data = resp.json()
    required = {"market", "as_of", "trend_direction", "current_psf",
                "forecast_3m", "forecast_6m", "forecast_12m",
                "conf_low_6m", "conf_high_6m", "mae_pct", "data_points", "model_version"}
    assert required.issubset(data.keys()), f"Missing keys: {required - data.keys()}"
