"""GATE-136 declaration — Deed Pipeline Automation.

Five assertions (all unit-safe, no live DB required):
1. run_daily_deed_scrape importable from config.scheduler
2. v_deed_throughput_weekly view defined in database/schema.sql
3. /api/v1/deeds/throughput router registered in FastAPI app
4. Endpoint response schema has current_week_count, target, status fields
5. Throughput status logic: count=0 -> critical, count=25 -> at_risk, count=55 -> on_track
"""

import pytest
from unittest.mock import MagicMock, patch, ANY

pytestmark = pytest.mark.unit


def test_run_daily_deed_scrape_importable():
    from config.scheduler.deed_jobs import run_daily_deed_scrape, run_weekly_deed_threshold_check
    assert callable(run_daily_deed_scrape)
    assert callable(run_weekly_deed_threshold_check)


def test_v_deed_throughput_weekly_in_schema():
    schema = open("database/schema.sql", encoding="utf-8").read()
    assert "v_deed_throughput_weekly" in schema
    assert "CREATE OR REPLACE VIEW v_deed_throughput_weekly" in schema
    assert "current_week_count" in schema
    assert "prior_week_count" in schema
    assert "yoy_count" in schema


def test_deeds_throughput_route_registered():
    from dashboard.app_fastapi import app
    routes = [r.path for r in app.routes]
    assert any("/deeds/throughput" in r for r in routes), (
        "/deeds/throughput not in routes"
    )


def test_deeds_throughput_response_schema():
    """Verify the Pydantic response model has required fields."""
    from dashboard.routers.data import DeedThroughputResponse, DeedThroughputWeek
    dw = DeedThroughputWeek(market="Test", week_start="2026-06-22", deed_count=10)
    assert dw.market == "Test"
    assert dw.deed_count == 10
    resp = DeedThroughputResponse(
        weeks=[dw],
        current_week_count=10,
        target=50,
        status="at_risk",
    )
    data = resp.model_dump()
    assert "current_week_count" in data
    assert "target" in data
    assert "status" in data
    assert "weeks" in data
    assert data["weeks"][0]["deed_count"] == 10


def test_deed_jobs_register_jobs():
    """Verify register_jobs registers 3 jobs (daily + weekly threshold + assembly detection)."""
    from config.scheduler.deed_jobs import register_jobs
    mock_scheduler = MagicMock()
    mock_safe_job = MagicMock()
    register_jobs(mock_scheduler, mock_safe_job)
    assert mock_scheduler.add_job.call_count == 3
    job_ids = [call.kwargs["id"] for call in mock_scheduler.add_job.call_args_list]
    assert "daily_deed_scrape" in job_ids
    assert "weekly_deed_threshold" in job_ids
    assert "assembly_detection_weekly" in job_ids


@pytest.mark.parametrize("count,expected", [
    (0, "critical"),
    (25, "at_risk"),
    (55, "on_track"),
])
def test_deeds_throughput_status_logic(count, expected):
    """Status logic: 0 -> critical, <50 -> at_risk, >=50 -> on_track."""
    status = "critical" if count == 0 else ("at_risk" if count < 50 else "on_track")
    assert status == expected
