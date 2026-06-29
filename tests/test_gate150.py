"""GATE-150: Post-V2 Operations Baseline — 5 gate assertions (A1-A5).

A1: run_weekly_kill_criteria_report importable + in deed_jobs.__all__
A2: run_alembic_health_check importable + in config.scheduler.__all__
A3: run_dlq_drain_check importable + in config.scheduler.__all__
A4: GET /api/v1/ops/kill-criteria includes deed_throughput.weeks_remaining_label
A5: All 3 new jobs registered in scheduler
"""

from unittest.mock import patch, MagicMock

import pytest

pytestmark = pytest.mark.unit


# ── A1: Weekly kill criteria report job ────────────────────────────────────


def test_gate150_a1_kill_criteria_report_importable():
    """A1: run_weekly_kill_criteria_report importable + in deed_jobs.__all__."""
    from config.scheduler.deed_jobs import run_weekly_kill_criteria_report, __all__

    assert callable(run_weekly_kill_criteria_report)
    assert "run_weekly_kill_criteria_report" in __all__


def test_gate150_a1_kill_criteria_report_sends_alerts():
    """A1: run_weekly_kill_criteria_report sends Telegram + Discord on success."""
    from config.scheduler.deed_jobs import run_weekly_kill_criteria_report

    with (
        patch("utils.deed_progress.compute_throughput_projection") as mock_proj,
        patch("utils.discord_notifier.send_ops_alert") as mock_discord,
        patch("utils.telegram_notifier.send_message") as mock_tg,
    ):
        mock_proj.return_value = {
            "avg_4wk": 12.5,
            "projection_verdict": "at_risk",
            "weeks_remaining": 7,
        }

        run_weekly_kill_criteria_report()

        mock_discord.assert_called_once()
        args, _ = mock_discord.call_args
        assert args[0] == "KILL_CRITERIA_WEEKLY"
        assert "12.5" in str(args[1])
        assert "at_risk" in str(args[1])

        mock_tg.assert_called_once()
        tg_msg = str(mock_tg.call_args[0][0])
        assert "12.5" in tg_msg
        assert "at_risk" in tg_msg


def test_gate150_a1_kill_criteria_report_sends_past_deadline_label():
    """A1: uses 'past deadline' label when weeks_remaining is negative."""
    from config.scheduler.deed_jobs import run_weekly_kill_criteria_report

    with (
        patch("utils.deed_progress.compute_throughput_projection") as mock_proj,
        patch("utils.discord_notifier.send_ops_alert") as mock_discord,
        patch("utils.telegram_notifier.send_message") as mock_tg,
    ):
        mock_proj.return_value = {
            "avg_4wk": 52.0,
            "projection_verdict": "on_track",
            "weeks_remaining": -3,
        }

        run_weekly_kill_criteria_report()

        msg = str(mock_discord.call_args[0][1])
        assert "past deadline" in msg
        msg2 = str(mock_tg.call_args[0][0])
        assert "past deadline" in msg2


def test_gate150_a1_kill_criteria_report_skip_on_concurrent():
    """A1: skip if _REPORT_RUNNING flag is set."""
    import config.scheduler.deed_jobs as _dj

    original = _dj._REPORT_RUNNING
    _dj._REPORT_RUNNING = True
    try:
        with patch("utils.deed_progress.compute_throughput_projection") as mock_proj:
            _dj.run_weekly_kill_criteria_report()
            mock_proj.assert_not_called()
    finally:
        _dj._REPORT_RUNNING = original


# ── A2: Alembic health check job ───────────────────────────────────────────


def test_gate150_a2_alembic_health_check_importable():
    """A2: run_alembic_health_check importable + in config.scheduler.__all__."""
    from config.scheduler.maintenance_jobs import run_alembic_health_check
    from config.scheduler import __all__ as scheduler_all

    assert callable(run_alembic_health_check)
    assert "run_alembic_health_check" in scheduler_all


def test_gate150_a2_alembic_health_check_head_ok():
    """A2: alembic health check logs OK when (head) is in last output line."""
    import shutil
    from config.scheduler.maintenance_jobs import run_alembic_health_check

    with (
        patch("shutil.which", return_value="/usr/bin/alembic"),
        patch("subprocess.run") as mock_run,
        patch("config.scheduler.maintenance_jobs.logger") as mock_log,
    ):
        mock_proc = MagicMock()
        mock_proc.stdout = "abc123 (head)"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        run_alembic_health_check()

        mock_log.info.assert_called_once()


def test_gate150_a2_alembic_health_check_mismatch():
    """A2: alembic health check sends Discord alert when head mismatched."""
    from config.scheduler.maintenance_jobs import run_alembic_health_check

    with (
        patch("shutil.which", return_value="/usr/bin/alembic"),
        patch("subprocess.run") as mock_run,
        patch("config.scheduler.maintenance_jobs._ops_already_alerted", return_value=False),
        patch("utils.discord_notifier.send_ops_alert") as mock_alert,
        patch("config.scheduler.maintenance_jobs.logger") as mock_log,
    ):
        mock_proc = MagicMock()
        mock_proc.stdout = "abc123 (no head)"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        run_alembic_health_check()

        mock_alert.assert_called_once()
        args, _ = mock_alert.call_args
        assert args[0] == "ALEMBIC_DRIFT"
        assert "no head" in args[1]


def test_gate150_a2_alembic_health_check_no_raise():
    """A2: alembic health check never raises on failure."""
    from config.scheduler.maintenance_jobs import run_alembic_health_check

    with (
        patch("shutil.which", return_value="/usr/bin/alembic"),
        patch("subprocess.run", side_effect=RuntimeError("alembic not found")),
    ):
        run_alembic_health_check()


def test_gate150_a2_alembic_health_check_skipped_when_cli_missing():
    """A2: skips silently when alembic CLI is not installed."""
    from config.scheduler.maintenance_jobs import run_alembic_health_check

    with (
        patch("shutil.which", return_value=None),
        patch("subprocess.run") as mock_run,
    ):
        run_alembic_health_check()
        mock_run.assert_not_called()


# ── A3: DLQ drain check job ────────────────────────────────────────────────


def test_gate150_a3_dlq_drain_check_importable():
    """A3: run_dlq_drain_check importable + in config.scheduler.__all__."""
    from config.scheduler.maintenance_jobs import run_dlq_drain_check
    from config.scheduler import __all__ as scheduler_all

    assert callable(run_dlq_drain_check)
    assert "run_dlq_drain_check" in scheduler_all


def test_gate150_a3_dlq_drain_check_under_threshold():
    """A3: no alert when DLQ stale count <= threshold."""
    from config.scheduler.maintenance_jobs import run_dlq_drain_check

    mock_conn = MagicMock()
    mock_row = MagicMock()
    mock_row.__getitem__.return_value = 3
    mock_conn.execute.return_value.fetchone.return_value = mock_row

    with (
        patch("config.scheduler.maintenance_jobs.get_engine") as mock_eng,
        patch("utils.discord_notifier.send_ops_alert") as mock_alert,
    ):
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        run_dlq_drain_check()
        mock_alert.assert_not_called()


def test_gate150_a3_dlq_drain_check_over_threshold():
    """A3: Discord alert when DLQ stale count > threshold."""
    from config.scheduler.maintenance_jobs import run_dlq_drain_check

    mock_conn = MagicMock()
    mock_row = MagicMock()
    mock_row.__getitem__.return_value = 15
    mock_conn.execute.return_value.fetchone.return_value = mock_row

    with (
        patch("config.scheduler.maintenance_jobs.get_engine") as mock_eng,
        patch("config.scheduler.maintenance_jobs._ops_already_alerted", return_value=False),
        patch("utils.discord_notifier.send_ops_alert") as mock_alert,
    ):
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        run_dlq_drain_check()
        mock_alert.assert_called_once()
        args, _ = mock_alert.call_args
        assert args[0] == "DLQ_STALE"


def test_gate150_a3_dlq_drain_check_no_raise():
    """A3: DLQ drain check never raises on DB failure."""
    from config.scheduler.maintenance_jobs import run_dlq_drain_check

    with patch("config.scheduler.maintenance_jobs.get_engine", side_effect=RuntimeError("no db")):
        run_dlq_drain_check()


def test_gate150_a3_dlq_drain_check_cooldown_suppresses_duplicate():
    """A3: alert suppressed when _ops_already_alerted returns True."""
    from config.scheduler.maintenance_jobs import run_dlq_drain_check

    mock_conn = MagicMock()
    mock_row = MagicMock()
    mock_row.__getitem__.return_value = 15
    mock_conn.execute.return_value.fetchone.return_value = mock_row

    with (
        patch("config.scheduler.maintenance_jobs.get_engine") as mock_eng,
        patch("config.scheduler.maintenance_jobs._ops_already_alerted", return_value=True),
        patch("utils.discord_notifier.send_ops_alert") as mock_alert,
    ):
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        run_dlq_drain_check()
        mock_alert.assert_not_called()


# ── A4: kill-criteria endpoint has weeks_remaining_label ────────────────────


def test_gate150_a4_kill_criteria_has_weeks_remaining_label():
    """A4: GET /api/v1/ops/kill-criteria returns deed_throughput.weeks_remaining_label."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    with patch("dashboard.app_fastapi._write_audit_log"):
        client = TestClient(app)

        with (
            patch("utils.deed_progress.compute_throughput_projection") as mock_proj,
            patch("utils.decision_journal.list_entries") as mock_list,
        ):
            mock_proj.return_value = {
                "avg_4wk": 12.5,
                "weeks_remaining": 7,
                "projection_verdict": "at_risk",
            }
            mock_list.return_value = [{"id": 1}]

            resp = client.get("/api/v1/ops/kill-criteria")

        assert resp.status_code == 200
        data = resp.json()
        assert "deed_throughput" in data
        assert "weeks_remaining_label" in data["deed_throughput"]
        assert data["deed_throughput"]["weeks_remaining_label"] == "7 weeks (2026-08-15)"


def test_gate150_a4_kill_criteria_label_past_deadline():
    """A4: weeks_remaining_label shows 'past deadline' when weeks_remaining is negative."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    with patch("dashboard.app_fastapi._write_audit_log"):
        client = TestClient(app)

        with (
            patch("utils.deed_progress.compute_throughput_projection") as mock_proj,
            patch("utils.decision_journal.list_entries") as mock_list,
        ):
            mock_proj.return_value = {
                "avg_4wk": 52.0,
                "weeks_remaining": -3,
                "projection_verdict": "on_track",
            }
            mock_list.return_value = [{"id": 1}]

            resp = client.get("/api/v1/ops/kill-criteria")

        assert resp.status_code == 200
        data = resp.json()
        assert data["deed_throughput"]["weeks_remaining_label"] == "past deadline"


def test_gate150_a4_kill_criteria_label_unknown():
    """A4: weeks_remaining_label shows 'unknown' when weeks_remaining is absent."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    with patch("dashboard.app_fastapi._write_audit_log"):
        client = TestClient(app)

        with (
            patch("utils.deed_progress.compute_throughput_projection") as mock_proj,
            patch("utils.decision_journal.list_entries") as mock_list,
        ):
            mock_proj.return_value = {
                "avg_4wk": 0.0,
                "projection_verdict": "unknown",
            }
            mock_list.return_value = [{"id": 1}]

            resp = client.get("/api/v1/ops/kill-criteria")

        assert resp.status_code == 200
        data = resp.json()
        assert data["deed_throughput"]["weeks_remaining_label"] == "unknown"


# ── A5: All 3 new jobs registered in scheduler ─────────────────────────────


def test_gate150_a5_all_jobs_registered():
    """A5: Verify all 3 new jobs are registered via the scheduler register_jobs functions."""
    mock_scheduler = MagicMock()
    mock_scheduler.add_job = MagicMock()

    from config.scheduler.deed_jobs import register_jobs as deed_register
    from config.scheduler.maintenance_jobs import register_jobs as maint_register

    def safe_job(fn, name):
        return lambda: None

    deed_register(mock_scheduler, safe_job)
    maint_register(mock_scheduler, safe_job)

    added_ids = [call.kwargs.get("id") for call in mock_scheduler.add_job.call_args_list]
    assert "weekly_kill_criteria_report" in added_ids, "job weekly_kill_criteria_report not registered"
    assert "weekly_alembic_health_check" in added_ids, "job weekly_alembic_health_check not registered"
    assert "weekly_dlq_drain_check" in added_ids, "job weekly_dlq_drain_check not registered"


def test_gate150_a5_job_ids_in_scheduler_init():
    """A5: All 3 new function names appear in config.scheduler.__all__."""
    from config.scheduler import __all__

    assert "run_weekly_kill_criteria_report" in __all__
    assert "run_alembic_health_check" in __all__
    assert "run_dlq_drain_check" in __all__
