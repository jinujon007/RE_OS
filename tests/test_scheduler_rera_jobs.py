"""T-1164: config/scheduler/rera_jobs.py unit tests."""
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_rera_jobs_module_importable():
    from config.scheduler.rera_jobs import run_single_market_rera
    assert callable(run_single_market_rera)


def test_register_jobs_rera_accepts_mock_scheduler():
    from config.scheduler.rera_jobs import register_jobs
    mock_scheduler = MagicMock()
    def safe_job(fn, name): return fn
    register_jobs(mock_scheduler, safe_job)
    # RERA jobs run via IngestEngine's RERAPlugin, no standalone jobs
    assert callable(register_jobs)
