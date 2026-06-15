"""Tests for utils.data_quality_monitor (T-1128 / R3)."""

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_count_db():
    from unittest.mock import MagicMock, patch

    mock_row = MagicMock()
    mock_row.__getitem__.return_value = 10
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("utils.data_quality_monitor.get_engine", return_value=mock_engine):
        yield


def test_get_live_rera_count_returns_int(mock_count_db):
    from utils.data_quality_monitor import get_live_rera_count

    count = get_live_rera_count("Yelahanka")
    assert isinstance(count, int)
    assert count == 10


def test_get_live_rera_count_zero_on_empty():
    from unittest.mock import MagicMock, patch

    mock_row = MagicMock()
    mock_row.__getitem__.return_value = 0
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("utils.data_quality_monitor.get_engine", return_value=mock_engine):
        from utils.data_quality_monitor import get_live_rera_count

        assert get_live_rera_count("Unknown") == 0


def test_get_live_rera_count_zero_on_db_error():
    from unittest.mock import MagicMock, patch

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = Exception("DB down")
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("utils.data_quality_monitor.get_engine", return_value=mock_engine):
        from utils.data_quality_monitor import get_live_rera_count

        assert get_live_rera_count("Yelahanka") == 0


def test_data_floor_breach_triggers_alert():
    from unittest.mock import MagicMock, patch

    mock_send = MagicMock()
    with (
        patch("utils.data_quality_monitor.get_live_rera_count", return_value=10),
        patch("utils.discord_notifier.send_ops_alert", mock_send),
    ):
        from utils.data_quality_monitor import check_live_data_floor

        result = check_live_data_floor("Yelahanka", floor=50)
        assert result is False
        mock_send.assert_called_once()
        args, _ = mock_send.call_args
        assert args[0] == "DATA_FLOOR_BREACH"


def test_data_floor_no_alert_when_above_floor():
    from unittest.mock import MagicMock, patch

    mock_send = MagicMock()
    with (
        patch("utils.data_quality_monitor.get_live_rera_count", return_value=200),
        patch("utils.discord_notifier.send_ops_alert", mock_send),
    ):
        from utils.data_quality_monitor import check_live_data_floor

        result = check_live_data_floor("Yelahanka", floor=50)
        assert result is True
        mock_send.assert_not_called()


def test_data_floor_check_runs_for_all_markets():
    """Verify run_data_floor_check calls check_live_data_floor once per market."""
    from unittest.mock import patch, MagicMock
    from config.settings import DATA_FLOOR_MARKETS

    mock_fn = MagicMock(return_value=True)
    with (
        patch("utils.data_quality_monitor.check_live_data_floor", mock_fn),
        patch("config.scheduler.get_engine"),
    ):
        from config.scheduler import run_data_floor_check

        run_data_floor_check()
        assert mock_fn.call_count == len(DATA_FLOOR_MARKETS)
        for market, floor in DATA_FLOOR_MARKETS.items():
            mock_fn.assert_any_call(market, floor=floor)


def test_data_floor_job_registered_in_scheduler():
    with open("config/scheduler.py", encoding="utf-8") as f:
        content = f.read()
    assert 'id="data_floor_check"' in content or "id='data_floor_check'" in content
