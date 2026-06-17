"""T-1168: config/scheduler/maintenance_jobs.py unit tests."""
import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


def test_maintenance_jobs_module_importable():
    from config.scheduler.maintenance_jobs import (
        run_memory_decay,
        run_seed_staleness_check,
        run_bertscore_evaluation,
        run_db_backup,
        run_backup_staleness_check,
        run_offsite_backup_weekly,
        run_data_floor_check,
        run_scheduler_heartbeat,
        recover_stuck_board_sessions,
    )
    assert callable(run_memory_decay)
    assert callable(run_seed_staleness_check)
    assert callable(run_db_backup)
    assert callable(run_backup_staleness_check)
    assert callable(run_scheduler_heartbeat)
    assert callable(recover_stuck_board_sessions)


def test_register_jobs_maintenance_accepts_mock_scheduler():
    from config.scheduler.maintenance_jobs import register_jobs
    mock_scheduler = MagicMock()
    def safe_job(fn, name): return fn
    register_jobs(mock_scheduler, safe_job)
    assert mock_scheduler.add_job.call_count >= 8
