"""GATE-125 declaration — Kaveri Weekly Orchestration.

Five assertions — all code-verifiable without live DB:
1. A1: job registered in scheduler __init__.py
2. A2: run_kaveri_weekly_orchestration importable + callable
3. A3: error isolation — step1 failure does not propagate exception
4. A4: Discord fires on completion
5. A5: _compute_deed_weekly_avg returns mocked value
"""
import pathlib
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def test_a1_job_registered():
    """A1: kaveri_weekly_orchestration exported from __init__.py + registered in kaveri_jobs.py."""
    init_content = pathlib.Path("config/scheduler/__init__.py").read_text(encoding="utf-8")
    assert "run_kaveri_weekly_orchestration" in init_content, "must be imported in __init__.py"

    jobs_content = pathlib.Path("config/scheduler/kaveri_jobs.py").read_text(encoding="utf-8")
    assert 'id="kaveri_weekly_orchestration"' in jobs_content, "job must be registered in register_jobs()"


def test_a2_orchestration_importable():
    """A2: run_kaveri_weekly_orchestration importable and callable."""
    from config.scheduler.kaveri_jobs import run_kaveri_weekly_orchestration

    assert callable(run_kaveri_weekly_orchestration)


def test_a3_error_isolation():
    """A3: step1 raises; no exception propagates; errors list populated."""
    from config.scheduler.kaveri_jobs import run_kaveri_weekly_orchestration

    with patch("config.scheduler.maintenance_jobs.run_form17_inbox_scan", side_effect=RuntimeError("boom")):
        with patch("utils.assembly_detector.run_assembly_detection"):
            with patch("config.scheduler.kaveri_jobs._compute_deed_weekly_avg", return_value=0.0):
                with patch("utils.discord_notifier.send_ops_alert"):
                    with patch("config.scheduler.kaveri_jobs.get_engine"):
                        result = run_kaveri_weekly_orchestration()

    assert isinstance(result, dict)
    assert len(result["errors"]) > 0, "errors must be populated when step fails"


def test_a4_discord_fires():
    """A4: send_ops_alert called with KAVERI_WEEKLY event."""
    from config.scheduler.kaveri_jobs import run_kaveri_weekly_orchestration

    with patch("config.scheduler.maintenance_jobs.run_form17_inbox_scan", return_value={"new_pdfs": 0, "records_written": 0}):
        with patch("utils.assembly_detector.run_assembly_detection"):
            with patch("config.scheduler.kaveri_jobs._compute_deed_weekly_avg", return_value=0.0):
                with patch("utils.discord_notifier.send_ops_alert") as mock_alert:
                    with patch("config.scheduler.kaveri_jobs.get_engine"):
                        run_kaveri_weekly_orchestration()

    mock_alert.assert_called_once()
    assert mock_alert.call_args[0][0] == "KAVERI_WEEKLY"


def test_a5_deed_weekly_avg_helper():
    """A5: _compute_deed_weekly_avg returns 28.0 from mocked engine scalar."""
    from config.scheduler.kaveri_jobs import _compute_deed_weekly_avg

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.scalar.return_value = 28

    result = _compute_deed_weekly_avg(engine=mock_engine)
    assert result == 28.0


def test_a5_deed_weekly_avg_zero_when_no_data():
    """A5b: _compute_deed_weekly_avg returns 0.0 when DB returns None."""
    from config.scheduler.kaveri_jobs import _compute_deed_weekly_avg

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.scalar.return_value = None

    result = _compute_deed_weekly_avg(engine=mock_engine)
    assert result == 0.0


def test_a5_deed_weekly_avg_guard_weeks_zero():
    """A5c: weeks=0 is clamped to 1 to prevent division by zero."""
    from config.scheduler.kaveri_jobs import _compute_deed_weekly_avg

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.scalar.return_value = 12

    result = _compute_deed_weekly_avg(engine=mock_engine, weeks=0)
    assert result == 12.0, "weeks=0 must be clamped to 1 (no ZeroDivisionError)"
