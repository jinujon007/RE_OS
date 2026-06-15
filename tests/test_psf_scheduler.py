"""T-1111: PSF forecast scheduler job + upsert + Discord digest tests."""

import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_psf_forecast_job_registered():
    """Verify run_psf_forecast_update function exists and is callable."""
    from config.scheduler import run_psf_forecast_update

    assert callable(run_psf_forecast_update)


def test_upsert_writes_3_horizon_rows():
    """Verify upsert writes 3 rows per market (3, 6, 12 months)."""
    from config.scheduler import run_psf_forecast_update

    upsert_calls = []

    def _fake_execute(stmt, params):
        upsert_calls.append(params)

    with patch("config.scheduler.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = _fake_execute

        mock_result = MagicMock(
            status="ok",
            market="Yelahanka",
            current_psf=6500.0,
            trend_direction="rising",
            slope_pct_per_month=1.2,
            data_points=6,
            mae_pct=3.5,
            forecast_3m=6800,
            forecast_6m=7100,
            forecast_12m=7700,
            conf_low_6m=6500,
            conf_high_6m=7700,
        )

        with patch("utils.psf_forecaster.PSFForecaster") as mock_fc_cls:
            mock_instance = MagicMock()
            mock_instance.forecast.return_value = mock_result
            mock_fc_cls.return_value = mock_instance

            with patch("config.scheduler.TARGET_MARKETS", ["Yelahanka"]):
                with patch("utils.discord_notifier.send_forecast_digest"):
                    run_psf_forecast_update()

    assert len(upsert_calls) >= 1
    horizons = {c.get("horizon") for c in upsert_calls if c.get("horizon")}
    assert horizons == {3, 6, 12}


def test_send_forecast_digest_under_300_chars():
    """Verify forecast digest format is under 300 chars total."""
    from utils.discord_notifier import format_forecast_digest

    class FakeResult:
        def __init__(self, market, status, trend, psf, f6m, mae):
            self.market = market
            self.status = status
            self.trend_direction = trend
            self.current_psf = psf
            self.forecast_6m = f6m
            self.mae_pct = mae

    results = [
        FakeResult("Yelahanka", "ok", "rising", 6500, 7100, 3.5),
        FakeResult("Devanahalli", "ok", "falling", 8200, 7800, 5.2),
        FakeResult("Hebbal", "insufficient_data", "flat", 7500, 0, 0),
    ]
    msg = format_forecast_digest(results)
    assert len(msg) <= 300
    assert "Yelahanka" in msg
    assert "rising" in msg
