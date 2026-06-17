"""T-1167: config/scheduler/digest_jobs.py unit tests."""
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_digest_jobs_module_importable():
    from config.scheduler.digest_jobs import (
        run_weekly_digest,
        run_weekly_intel_digest,
        run_monthly_intel_digest,
        monthly_ceo_letter,
        run_compliance_check,
    )
    assert callable(run_weekly_digest)
    assert callable(run_weekly_intel_digest)
    assert callable(run_monthly_intel_digest)
    assert callable(monthly_ceo_letter)
    assert callable(run_compliance_check)


def test_register_jobs_digest_accepts_mock_scheduler():
    from config.scheduler.digest_jobs import register_jobs
    mock_scheduler = MagicMock()
    def safe_job(fn, name): return fn
    with patch("config.settings.SCHEDULER_ENABLE_ORG_SIM", True):
        register_jobs(mock_scheduler, safe_job)
    assert mock_scheduler.add_job.call_count >= 7
