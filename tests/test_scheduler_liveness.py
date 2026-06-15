"""Unit tests for scheduler liveness guard (T-1158).

6 tests:
1. SCHEDULER_DRY_RUN env var parsed correctly
2. run_scheduler_heartbeat writes to agent_runs
3. check_heartbeat_staleness detects missing heartbeat
4. check_heartbeat_staleness detects stale heartbeat (>2h old)
5. check_heartbeat_staleness passes on fresh heartbeat
6. scheduler job count includes heartbeat when registered
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

pytestmark = pytest.mark.unit


def test_scheduler_dry_run_env_parsed():
    """SCHEDULER_DRY_RUN env var parsed correctly."""
    import os
    from config.settings import SCHEDULER_DRY_RUN

    # Default is False (not set)
    assert SCHEDULER_DRY_RUN is False
    # Set and re-parse (simulate via direct check)
    os.environ["SCHEDULER_DRY_RUN"] = "true"
    # Reimport to pick up new env
    from importlib import reload
    import config.settings

    reload(config.settings)
    assert config.settings.SCHEDULER_DRY_RUN is True
    # Clean up
    del os.environ["SCHEDULER_DRY_RUN"]
    reload(config.settings)


def test_run_scheduler_heartbeat_writes():
    """run_scheduler_heartbeat writes agent_runs row."""
    from config.scheduler import run_scheduler_heartbeat

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    with patch("config.scheduler.get_engine", return_value=mock_engine):
        run_scheduler_heartbeat()

    # Assert execute was called (the INSERT)
    assert mock_conn.execute.called, "Heartbeat should execute INSERT"
    call_args = mock_conn.execute.call_args[0][0].text
    assert "scheduler_heartbeat" in call_args


def test_heartbeat_staleness_detects_missing():
    """check_heartbeat_staleness returns False on missing heartbeat."""
    from config.scheduler import check_heartbeat_staleness

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("config.scheduler.get_engine", return_value=mock_engine):
        with patch("utils.discord_notifier.send_ops_alert") as mock_alert:
            result = check_heartbeat_staleness()

    assert result is False
    assert mock_alert.called


def test_heartbeat_staleness_detects_stale():
    """check_heartbeat_staleness returns False when heartbeat >2h old."""
    from config.scheduler import check_heartbeat_staleness

    old_time = datetime.now(timezone.utc) - timedelta(hours=3)

    # Create a proper row mock that acts like a tuple (row[0] returns first element)
    mock_row = MagicMock()
    mock_row.__getitem__.side_effect = lambda idx: old_time if idx == 0 else None

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("config.scheduler.get_engine", return_value=mock_engine):
        with patch("utils.discord_notifier.send_ops_alert") as mock_alert:
            result = check_heartbeat_staleness()

    assert result is False
    assert mock_alert.called


def test_heartbeat_staleness_passes_fresh():
    """check_heartbeat_staleness returns True on fresh heartbeat."""
    from config.scheduler import check_heartbeat_staleness

    fresh_time = datetime.now(timezone.utc) - timedelta(minutes=30)

    mock_row = MagicMock()
    mock_row.__getitem__.side_effect = lambda idx: fresh_time if idx == 0 else None

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("config.scheduler.get_engine", return_value=mock_engine):
        with patch("utils.discord_notifier.send_ops_alert") as mock_alert:
            result = check_heartbeat_staleness()

    assert result is True
    assert not mock_alert.called


def test_scheduler_has_heartbeat_job():
    """Assert scheduler.py contains the heartbeat job registration."""
    content = open("config/scheduler.py", encoding="utf-8").read()
    assert "scheduler_heartbeat" in content
    assert "minutes=30" in content
    assert "SCHEDULER_DRY_RUN" in content
