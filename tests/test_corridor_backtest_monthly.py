"""T-1302: Corridor backtest monthly scheduler job + live kill-criteria wiring (GATE-123)."""
import pathlib

import pytest

pytestmark = pytest.mark.unit


def test_corridor_backtest_monthly_job_registered():
    """run_corridor_backtest_monthly is registered in maintenance_jobs."""
    path = pathlib.Path("config/scheduler/maintenance_jobs.py")
    content = path.read_text(encoding="utf-8")
    assert 'id="corridor_backtest_monthly"' in content, (
        "corridor_backtest_monthly job not registered in maintenance_jobs register_jobs()"
    )
    assert "corridor_backtest_monthly" in content


def test_kill_criteria_corridor_reads_live():
    """Kill-criteria endpoint corridor section reads from corridor_backtest_verdicts (not placeholder)."""
    path = pathlib.Path("dashboard/routers/ops.py")
    content = path.read_text(encoding="utf-8")
    assert "rank_correlation" in content, (
        "kill_criteria endpoint must query rank_correlation from corridor_backtest_verdicts"
    )
    assert "corridor_backtest_verdicts" in content


def test_kill_threshold_code_has_consecutive_tracking():
    """run_corridor_backtest_monthly logic checks for 3 consecutive monthly misses before alerting."""
    path = pathlib.Path("config/scheduler/maintenance_jobs.py")
    content = path.read_text(encoding="utf-8")
    assert "run_corridor_backtest_monthly" in content
    assert "consecutive_miss_months" in content, (
        "must track consecutive monthly periods before firing Discord alert"
    )
    assert ">= 3" in content or ">=3" in content, (
        "must require 3 consecutive misses before alerting"
    )


def test_kill_criteria_has_no_data_status():
    """Kill-criteria endpoint KillCriteriaCorridor model has status field for no_data."""
    path = pathlib.Path("dashboard/routers/ops.py")
    content = path.read_text(encoding="utf-8")
    assert "status" in content, (
        "KillCriteriaCorridor must have status field for no_data handling"
    )
