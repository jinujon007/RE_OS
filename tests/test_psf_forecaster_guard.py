"""T-1109: PSF Forecaster guard tests (updated for numpy forecaster)."""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


def test_forecaster_returns_dataclass():
    from utils.psf_forecaster import ForecastResult
    r = ForecastResult(market="Yelahanka")
    assert r.status == "ok"
    assert r.data_points == 0
    assert r.current_psf == 0.0


def test_forecaster_insufficient_data_when_no_rows():
    from utils.psf_forecaster import PSFForecaster
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []
        f = PSFForecaster()
        result = f.forecast("Yelahanka")
    assert result.status == "insufficient_data"
    assert result.data_points == 0


def test_forecaster_proceeds_when_sufficient_months():
    from datetime import datetime
    from utils.psf_forecaster import PSFForecaster
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            (datetime(2025, m, 1), 6000.0) for m in range(1, 7)
        ]
        f = PSFForecaster()
        result = f.forecast("Yelahanka")
    assert result.status == "ok"
    assert result.data_points == 6
