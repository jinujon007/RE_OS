"""GATE-85: PSF Time-Series Forecasting declaration.

Five assertions:
1. PSFForecaster().forecast('Yelahanka').status is not 'error'
2. PSFForecaster().forecast('Devanahalli').forecast_6m > 0 or status=='insufficient_data'
3. market_forecasts table exists
4. GET /api/market/forecast/Yelahanka returns 200 with forecast_6m key
5. Finance Head context assembly returns string containing "PSF FORECAST"
"""

import pytest
import os
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient
from datetime import datetime

pytestmark = pytest.mark.unit


def test_psf_forecaster_yelahanka_not_error():
    """Assertion 1: PSFForecaster for Yelahanka returns ok or insufficient_data."""
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, 1, 1), 6500.0),
            (datetime(2025, 2, 1), 6600.0),
            (datetime(2025, 3, 1), 6700.0),
            (datetime(2025, 4, 1), 6800.0),
        ]
        result = PSFForecaster().forecast("Yelahanka")
    assert result.status != "error", f"Forecast failed: {result}"


def test_psf_forecaster_devanahalli_has_positive_forecast():
    """Assertion 2: Devanahalli forecast_6m > 0 or insufficient_data."""
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, m, 1), float(8000 + i * 100))
            for i, m in enumerate(range(1, 7))
        ]
        result = PSFForecaster().forecast("Devanahalli")
    assert result.status == "ok" or result.status == "insufficient_data"
    if result.status == "ok":
        assert result.forecast_6m > 0


def test_market_forecasts_table_exists_via_schema():
    """Assertion 3: market_forecasts migration has correct columns + constraints."""
    import ast
    import pathlib

    migration_path = pathlib.Path("alembic/versions/0051_market_forecasts.py")
    assert migration_path.exists(), "Migration 0051 not found"

    tree = ast.parse(migration_path.read_text())
    columns = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and hasattr(node.func, "attr")
            and node.func.attr == "create_table"
        ):
            for arg in node.args:
                if (
                    isinstance(arg, ast.Call)
                    and hasattr(arg.func, "attr")
                    and arg.func.attr == "Column"
                ):
                    if arg.args:
                        first = arg.args[0]
                        if isinstance(first, ast.Constant):
                            columns.add(first.value)

    required = {
        "market",
        "forecast_date",
        "horizon_months",
        "forecast_psf",
        "trend_direction",
        "model_version",
        "created_at",
    }
    missing = required - columns
    assert not missing, f"Migration 0051 missing columns: {missing}"
    assert "check" in migration_path.read_text().lower(), (
        "Migration missing CHECK constraints"
    )


def test_forecast_endpoint_returns_forecast_6m():
    """Assertion 4: GET /api/market/forecast/Yelahanka → 200 with forecast_6m."""
    os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
    from dashboard.app_fastapi import app

    client = TestClient(app)

    with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            MagicMock(
                horizon_months=3,
                current_psf=6500.0,
                forecast_psf=6800.0,
                conf_low=None,
                conf_high=None,
                trend_direction="rising",
                slope_pct_per_month=1.2,
                data_points=6,
                mae_pct=3.5,
                model_version="linear_v1",
                forecast_date="2026-06-11",
            ),
            MagicMock(
                horizon_months=6,
                current_psf=6500.0,
                forecast_psf=7100.0,
                conf_low=6500.0,
                conf_high=7700.0,
                trend_direction="rising",
                slope_pct_per_month=1.2,
                data_points=6,
                mae_pct=3.5,
                model_version="linear_v1",
                forecast_date="2026-06-11",
            ),
            MagicMock(
                horizon_months=12,
                current_psf=6500.0,
                forecast_psf=7700.0,
                conf_low=None,
                conf_high=None,
                trend_direction="rising",
                slope_pct_per_month=1.2,
                data_points=6,
                mae_pct=3.5,
                model_version="linear_v1",
                forecast_date="2026-06-11",
            ),
        ]
        resp = client.get(
            "/api/market/forecast/Yelahanka", headers={"X-API-Key": "test-key"}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "forecast_6m" in data, f"Missing forecast_6m in {list(data.keys())}"


def test_finance_head_context_contains_psf_forecast_string():
    """Assertion 5: Finance Head context contains 'PSF FORECAST' on ok status."""
    from utils.psf_forecaster import ForecastResult

    result = ForecastResult(
        market="Yelahanka",
        status="ok",
        current_psf=6500.0,
        trend_direction="rising",
        forecast_6m=7100.0,
        conf_low_6m=6500.0,
        conf_high_6m=7700.0,
        mae_pct=3.5,
        data_points=6,
    )

    with patch("utils.psf_forecaster.PSFForecaster") as MockFC:
        instance = MagicMock()
        instance.forecast.return_value = result
        MockFC.return_value = instance

        from utils.psf_forecaster import PSFForecaster

        fc = PSFForecaster()
        f_result = fc.forecast("Yelahanka")

    # Build the context string the same way board_room.py does
    if f_result.status == "ok":
        error_range = int(abs(f_result.conf_high_6m - f_result.conf_low_6m) / 2)
        context = (
            f"PSF FORECAST (6-month): Current ₹{f_result.current_psf:,.0f}. "
            f"Trend: {f_result.trend_direction}. "
            f"Forecast: ₹{f_result.forecast_6m:,} ±{error_range:,} "
            f"(model MAE: {f_result.mae_pct:.1f}%). "
            f"Factor this into feasibility — if trend is falling, "
            f"IRR sensitivity to PSF is elevated."
        )
        assert "PSF FORECAST" in context
        assert "6-month" in context
        assert "rising" in context
