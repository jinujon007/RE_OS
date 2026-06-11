"""T-1122: Alembic check scheduled job (R8) — unit tests."""
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


def test_alembic_check_job_registered():
    """Assert scheduler has alembic_weekly_check job ID in config/scheduler.py."""
    with open("config/scheduler.py") as f:
        content = f.read()
    assert "alembic_weekly_check" in content, \
        "scheduler.py must register job with id='alembic_weekly_check'"
    assert "replace_existing=True" in content, \
        "scheduler job must have replace_existing=True to survive restarts"


def test_migration_0052_down_revision_is_correct():
    """Assert migration 0052's down_revision points to 0051_market_forecasts."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "migration_0052",
        "alembic/versions/0052_board_session_timing.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.down_revision == "0051_market_forecasts", (
        f"Expected down_revision='0051_market_forecasts', "
        f"got '{mod.down_revision}'"
    )


def test_alembic_check_returns_ok_on_success():
    """Assert run_alembic_check returns status='ok' when subprocess succeeds."""
    from utils.alembic_check import run_alembic_check

    with patch("utils.alembic_check.subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "No pending migrations"
        mock_run.return_value = mock_proc

        result = run_alembic_check()

    assert result["status"] == "ok"
    assert "No pending migrations" in result["detail"]


def test_alembic_check_oserror_returns_skipped():
    """Assert run_alembic_check returns status='skipped' on OSError (alembic not found)."""
    from utils.alembic_check import run_alembic_check

    with patch("utils.alembic_check.subprocess.run") as mock_run:
        mock_run.side_effect = OSError("alembic not found")
        result = run_alembic_check()

    assert result["status"] == "skipped"
    assert "alembic CLI not available" in result["detail"] or "not available" in result["detail"]


@patch("utils.alembic_check.subprocess.run")
def test_alembic_check_sends_discord_on_failure(mock_run):
    """Assert send_ops_alert is called when alembic check fails."""
    from utils.alembic_check import run_alembic_check

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stderr = "Migration 0052 is missing down_revision"
    mock_run.return_value = mock_proc

    with patch("utils.discord_notifier.send_ops_alert") as mock_alert:
        result = run_alembic_check()

    assert result["status"] == "failed"
    mock_alert.assert_called_once()
    args, _ = mock_alert.call_args
    assert args[0] == "ALEMBIC_DRIFT"
    assert "Migration 0052" in args[1]
