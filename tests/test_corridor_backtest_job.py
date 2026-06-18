"""Tests for corridor backtest scheduler job (T-1269, GATE-116)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

pytestmark = pytest.mark.unit


def test_corridor_backtest_job_registered():
    """run_corridor_backtest_weekly is registered in maintenance_jobs."""
    from config.scheduler.maintenance_jobs import register_jobs, run_corridor_backtest_weekly

    assert callable(run_corridor_backtest_weekly)

    mock_scheduler = MagicMock()
    register_jobs(mock_scheduler, lambda fn, name: fn())

    job_ids = [call[1]["id"] for call in mock_scheduler.add_job.call_args_list if len(call[1]) > 0 and "id" in call[1]]
    assert "corridor_backtest_weekly" in job_ids, (
        f"corridor_backtest_weekly not registered in jobs: {job_ids}"
    )


def test_backtest_job_alerts_on_verdict_change():
    """Job sends Discord alert when verdict goes to FAIL from PASS."""
    from config.scheduler.maintenance_jobs import run_corridor_backtest_weekly

    with (
        patch("config.scheduler.maintenance_jobs.get_engine") as mock_get_engine,
        patch("utils.discord_notifier.send") as mock_send,
    ):
        engine = MagicMock()
        conn = MagicMock()

        call_count = [0]

        def execute_side_effect(*args, **kwargs):
            call_count[0] += 1
            text_val = str(args[0]) if args else ""

            if "DISTINCT ON" in text_val:
                mock_result = MagicMock()
                mock_result.fetchall.return_value = [("nh44", "PASS")]
                return mock_result
            if "WHERE corridor_name" in text_val:
                mock_row = MagicMock()
                mock_row.__getitem__.return_value = "FAIL"
                mock_row.__iter__.return_value = iter(["FAIL"])
                mock_result = MagicMock()
                mock_result.fetchone.return_value = mock_row
                return mock_result
            mock_result = MagicMock()
            mock_result.fetchall.return_value = []
            return mock_result

        conn.execute = execute_side_effect
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        engine.begin.return_value.__enter__.return_value = conn
        engine.connect.return_value.__enter__.return_value = conn
        mock_get_engine.return_value = engine

        with patch("scripts.run_corridor_backtest.run_backtest") as mock_run:
            mock_run.return_value = [{"corridor_name": "nh44", "score": 0.5, "distance_km": 10.0}]
            run_corridor_backtest_weekly()

        assert mock_run.called, "run_backtest should be called"
        mock_send.assert_called_once()
        args, _kwargs = mock_send.call_args
        assert "change" in args[1].lower() or "recovered" in args[1].lower(), (
            f"Expected alert title containing 'change' or 'recovered', got: {args[1]}"
        )


def test_backtest_job_no_alert_on_first_run():
    """First run (no previous verdicts) should not fire Discord alert."""
    from config.scheduler.maintenance_jobs import run_corridor_backtest_weekly

    with (
        patch("config.scheduler.maintenance_jobs.get_engine") as mock_get_engine,
        patch("utils.discord_notifier.send") as mock_send,
    ):
        engine = MagicMock()
        conn = MagicMock()

        def execute_side_effect(*args, **kwargs):
            text_val = str(args[0]) if args else ""
            if "DISTINCT ON" in text_val:
                mock_result = MagicMock()
                mock_result.fetchall.return_value = []
                return mock_result
            mock_result = MagicMock()
            mock_result.fetchall.return_value = []
            return mock_result

        conn.execute = execute_side_effect
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        engine.begin.return_value.__enter__.return_value = conn
        engine.connect.return_value.__enter__.return_value = conn
        mock_get_engine.return_value = engine

        with patch("scripts.run_corridor_backtest.run_backtest") as mock_run:
            mock_run.return_value = [{"corridor_name": "nh44", "score": 0.5, "distance_km": 10.0}]
            run_corridor_backtest_weekly()

        mock_send.assert_not_called()
