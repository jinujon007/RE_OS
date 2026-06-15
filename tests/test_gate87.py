"""GATE-87 — LAUNCH GATE declaration.
Six unit-safe assertions. All pass → gate declared."""

import os
import re
import sys
from pathlib import Path

import pytest


@pytest.mark.test_id("G87-A1")
def test_a1_market_intel_crew_and_scouts_importable():
    """(1) market_intel_crew.py and all 6 scout files importable without error."""
    import crews.market_intel_crew  # noqa: F401
    import scrapers.rera_karnataka  # noqa: F401
    import scrapers.rera_detail_scout  # noqa: F401
    import scrapers.portal_scout  # noqa: F401
    import scrapers.developer_scout  # noqa: F401
    import scrapers.news_scout  # noqa: F401
    import scrapers.kaveri_karnataka  # noqa: F401

    # verify 6 distinct scout modules were imported
    scout_count = len(
        {
            m.__name__
            for m in [
                scrapers.rera_karnataka,
                scrapers.rera_detail_scout,
                scrapers.portal_scout,
                scrapers.developer_scout,
                scrapers.news_scout,
                scrapers.kaveri_karnataka,
            ]
        }
    )
    assert scout_count == 6, f"Expected 6 distinct scout modules, got {scout_count}"


@pytest.mark.test_id("G87-A2")
def test_a2_scheduler_job_count_at_least_15():
    """(2) Scheduler module has >= 15 registered jobs, no duplicate IDs."""
    text = Path("config/scheduler.py").read_text(encoding="utf-8")
    # Uses non-greedy match across lines: matches add_job(..., id="job_id", ...)
    ids = re.findall(
        r"""scheduler\.add_job\(  # function call start
        (?:[^i]|i[^d])*?          # any chars before 'id=' (non-greedy, avoid 'in' matches)
        id\s*=\s*"([^"]+)"        # capture: id="job_id"
        """,
        text,
        re.DOTALL | re.VERBOSE,
    )
    assert len(ids) >= 15, f"Found {len(ids)} scheduler jobs, expected >= 15"
    duplicates = [jid for jid in ids if ids.count(jid) > 1]
    assert not duplicates, f"Duplicate job IDs: {set(duplicates)}"


@pytest.mark.test_id("G87-A3")
def test_a3_psf_forecaster_importable():
    """(3) PSFForecaster class importable; ForecastResult has all required fields."""
    from utils.psf_forecaster import PSFForecaster, ForecastResult  # noqa: F401

    fields = list(ForecastResult.__dataclass_fields__.keys())
    required = [
        "market",
        "as_of",
        "data_points",
        "trend_direction",
        "slope_pct_per_month",
        "current_psf",
        "forecast_3m",
        "forecast_6m",
        "forecast_12m",
        "conf_low_6m",
        "conf_high_6m",
        "mae_pct",
        "status",
    ]
    for f in required:
        assert f in fields, f"ForecastResult missing required field: {f}"


@pytest.mark.test_id("G87-A4")
def test_a4_db_backup_importable():
    """(4) DBBackup importable and check_backup_staleness() callable."""
    from utils.backup import DBBackup, check_backup_staleness  # noqa: F401

    # Verify both are callable functions/classes
    assert callable(DBBackup), "DBBackup must be a callable class"
    assert callable(check_backup_staleness), "check_backup_staleness must be callable"


@pytest.mark.test_id("G87-A5")
def test_a5_board_room_v2_importable():
    """(5) Board Room v2 module imports without error."""
    import crews.board_room_v2  # noqa: F401


@pytest.mark.test_id("G87-A6")
@pytest.mark.filterwarnings("ignore::UserWarning")  # suppress LiteLLM bedrock warnings
def test_a6_health_endpoint_returns_200():
    """(6) GET /api/health returns 200 with service status breakdown.

    Sets REDIS_URL=memory:// at module load (pytest conftest-order safe)
    so the rate limiter uses in-process storage instead of a Redis connection.
    """
    # Must set env before importing the module; limiter is created at import time
    os.environ.setdefault("REDIS_URL", "memory://")
    # If already imported in another test, force re-import with new env
    if "dashboard.app_fastapi" in sys.modules:
        import importlib
        import dashboard.app_fastapi  # noqa: F811

        importlib.reload(dashboard.app_fastapi)

    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200, f"Health endpoint returned {resp.status_code}"
    data = resp.json()
    assert "agents" in data, f"Health response missing 'agents' key: {data}"
    assert "postgres" in data, f"Health response missing 'postgres' key: {data}"
    # Additional structure validation — all service fields must be present
    for svc in ("agents", "postgres", "redis", "ollama", "chroma"):
        assert svc in data, f"Health response missing expected service key: {svc}"
    # Verify data_quality block exists (even if errored)
    assert "data_quality" in data, "Health response missing data_quality block"
