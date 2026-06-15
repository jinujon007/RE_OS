"""T-1109: PSFForecaster unit tests (numpy linear trend)."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

pytestmark = pytest.mark.unit


def test_forecast_returns_dataclass():
    from utils.psf_forecaster import PSFForecaster, ForecastResult

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, 1, 1), 6500.0),
            (datetime(2025, 2, 1), 6600.0),
            (datetime(2025, 3, 1), 6700.0),
            (datetime(2025, 4, 1), 6800.0),
        ]
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert isinstance(result, ForecastResult)
    assert result.market == "Yelahanka"
    assert result.status in ("ok", "error")
    assert result.as_of.endswith("+00:00") or "+" in result.as_of or "Z" in result.as_of


def test_insufficient_data_when_fewer_than_4_points():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, 1, 1), 6500.0),
        ]
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert result.status == "insufficient_data"
    assert result.data_points == 1
    assert result.current_psf == 6500.0
    assert result.forecast_3m == result.current_psf
    assert result.forecast_6m == result.current_psf
    assert result.forecast_12m == result.current_psf


def test_trend_direction_rising_on_positive_slope():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, m, 1), float(6000 + i * 150))
            for i, m in enumerate(range(1, 7))
        ]
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert result.status == "ok"
    assert result.trend_direction == "rising"
    assert result.slope_pct_per_month > 0.5


def test_trend_direction_falling_on_negative_slope():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, m, 1), float(7000 - i * 120))
            for i, m in enumerate(range(1, 7))
        ]
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert result.status == "ok"
    assert result.trend_direction == "falling"
    assert result.slope_pct_per_month < -0.5


def test_forecast_3m_extrapolates_correctly():
    from utils.psf_forecaster import PSFForecaster

    slope_per_month = 100.0
    base = 6000.0
    months = [
        (datetime(2025, m, 1), base + i * slope_per_month)
        for i, m in enumerate(range(1, 7))
    ]

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = months
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert result.status == "ok"
    expected_3m = base + (5 + 3) * slope_per_month
    assert abs(result.forecast_3m - expected_3m) / expected_3m < 0.05


def test_conf_high_always_gte_conf_low():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, m, 1), float(6000 + i * 50))
            for i, m in enumerate(range(1, 7))
        ]
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert result.conf_high_3m >= result.conf_low_3m
    assert result.conf_high_6m >= result.conf_low_6m
    assert result.conf_high_12m >= result.conf_low_12m
    assert result.conf_low_6m >= 0


def test_conf_low_clamped_to_zero():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, m, 1), float(2000 - i * 200))
            for i, m in enumerate(range(1, 7))
        ]
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert result.conf_low_3m >= 0
    assert result.conf_low_6m >= 0
    assert result.conf_low_12m >= 0


def test_mae_bounded_0_to_100():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, m, 1), float(6000 + i * 50))
            for i, m in enumerate(range(1, 13))
        ]
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert 0.0 <= result.mae_pct <= 100.0


def test_empty_series_returns_insufficient_data():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = []
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert result.status == "insufficient_data"
    assert result.current_psf == 0.0


def test_unknown_market_returns_insufficient_data():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = None
        f = PSFForecaster()
        result = f.forecast("NonExistent")

    assert result.status == "insufficient_data"
    assert result.data_points == 0


def test_exactly_6_points_walkforward_edge():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, m, 1), float(6000.0 + m * 50)) for m in range(1, 7)
        ]
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert result.status == "ok"
    assert result.data_points == 6
    assert 0 <= result.mae_pct <= 100


def test_flat_trend_detected():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, m, 1), 6500.0) for m in range(1, 7)
        ]
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert result.trend_direction == "flat"
    assert abs(result.slope_pct_per_month) < 0.5


def test_model_version_present_on_ok():
    from utils.psf_forecaster import PSFForecaster

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = __import__("uuid").uuid4()
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, m, 1), float(6000 + i * 100))
            for i, m in enumerate(range(1, 7))
        ]
        f = PSFForecaster()
        result = f.forecast("Yelahanka")

    assert result.status == "ok"
    assert result.model_version == "linear_v1"
