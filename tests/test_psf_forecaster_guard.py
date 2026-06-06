"""T-960: PSF Forecaster weekly job guard tests."""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


def test_forecaster_returns_skip_status_dict():
    from utils.psf_forecaster import ForecastResult
    r = ForecastResult(market="Yelahanka")
    assert r.status == "ok"
    assert r.months_available == 0
    assert r.error is None


def test_forecaster_skips_when_insufficient_snapshots():
    from utils.psf_forecaster import PSFForecaster
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = 3
        f = PSFForecaster()
        result = f.train("Yelahanka")
    assert result.status == "skipped"
    assert "insufficient_data" in (result.error or "")
    assert result.months_available == 3


def test_forecaster_proceeds_when_sufficient_snapshots():
    from utils.psf_forecaster import PSFForecaster
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = 8
        mock_conn.execute.return_value.fetchall.return_value = []
        f = PSFForecaster()
        result = f.train("Yelahanka")
    assert result.status != "skipped"
    assert result.months_available == 8


def test_forecaster_discord_alert_on_high_mape():
    from utils.psf_forecaster import _send_mape_alert
    with patch("utils.discord_notifier.send") as mock_send:
        _send_mape_alert("Yelahanka", 22.5, "up", 8000.0)
    mock_send.assert_called_once()
    args, _ = mock_send.call_args
    assert args[0] == "bd_opportunities"
    assert "MAPE" in str(args)
    assert "22.5" in str(args)
