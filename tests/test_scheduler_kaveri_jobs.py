"""T-1165: config/scheduler/kaveri_jobs.py unit tests."""
import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


def test_kaveri_jobs_module_importable():
    from config.scheduler.kaveri_jobs import (
        run_kaveri_deeds_weekly,
        run_bhoomi_auto_survey,
        run_la_notification_scan,
        run_tender_daily_scan,
        run_ledger_check_weekly,
    )
    assert callable(run_kaveri_deeds_weekly)
    assert callable(run_bhoomi_auto_survey)
    assert callable(run_la_notification_scan)
    assert callable(run_tender_daily_scan)
    assert callable(run_ledger_check_weekly)


def test_register_jobs_kaveri_accepts_mock_scheduler():
    from config.scheduler.kaveri_jobs import register_jobs
    mock_scheduler = MagicMock()
    def safe_job(fn, name): return fn
    register_jobs(mock_scheduler, safe_job)
    assert mock_scheduler.add_job.call_count >= 4
