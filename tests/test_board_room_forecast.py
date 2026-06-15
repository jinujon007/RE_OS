"""T-1113: Finance Head Board Room PSF forecast context tests."""

import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_finance_head_context_contains_psf_forecast_on_ok_status():
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

    error_range = f_result.error_range_6m
    text = (
        f"PSF FORECAST (6-month): Current ₹{f_result.current_psf:,.0f}. "
        f"Trend: {f_result.trend_direction}. "
        f"Forecast: ₹{f_result.forecast_6m:,} ±{error_range:,} "
        f"(model MAE: {f_result.mae_pct:.1f}%)"
    )
    assert "PSF FORECAST" in text
    assert "rising" in text
    assert "6-month" in text
    assert "±" in text


def test_finance_head_context_contains_insufficient_data_message_on_failure():
    from utils.psf_forecaster import ForecastResult

    result = ForecastResult(
        market="Yelahanka",
        status="insufficient_data",
        current_psf=6500.0,
        data_points=2,
    )

    with patch("utils.psf_forecaster.PSFForecaster") as MockFC:
        instance = MagicMock()
        instance.forecast.return_value = result
        MockFC.return_value = instance

        from utils.psf_forecaster import PSFForecaster

        fc = PSFForecaster()
        f_result = fc.forecast("Yelahanka")

    text = (
        "PSF FORECAST: Insufficient data for trend projection "
        "— use current market PSF as static estimate."
    )
    assert "Insufficient data" in text
    assert "static estimate" in text
