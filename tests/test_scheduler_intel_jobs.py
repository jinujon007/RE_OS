"""T-1166: config/scheduler/intel_jobs.py unit tests."""
import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


def test_intel_jobs_module_importable():
    from config.scheduler.intel_jobs import (
        run_intel_embedding_index,
        run_news_sentiment_scoring,
        run_market_snapshot,
        run_ingest_engine,
        run_conflict_detection,
        run_opportunity_scoring,
        run_psf_forecast_update,
        weekly_competitive_digest,
        run_gcc_daily_scan,
    )
    assert callable(run_intel_embedding_index)
    assert callable(run_news_sentiment_scoring)
    assert callable(run_market_snapshot)
    assert callable(run_ingest_engine)
    assert callable(run_opportunity_scoring)
    assert callable(weekly_competitive_digest)


def test_register_jobs_intel_accepts_mock_scheduler():
    from config.scheduler.intel_jobs import register_jobs
    mock_scheduler = MagicMock()
    def safe_job(fn, name): return fn
    register_jobs(mock_scheduler, safe_job)
    assert mock_scheduler.add_job.call_count >= 14
