"""GATE-88 — Operational Excellence (Post-Launch Risk Closure).
Five assertions: (1) alembic_weekly_check job registered, (2) redis_fallback test exists,
(3) migration 0052 exists, (4) migration adds response_time_s column, (5) scheduler/health endpoint.
"""
import pytest
import os
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


@pytest.mark.test_id("G88-A1")
def test_a1_alembic_weekly_check_job_registered():
    """(1) config/scheduler.py contains id='alembic_weekly_check'."""
    with open("config/scheduler.py") as f:
        content = f.read()
    assert "alembic_weekly_check" in content, \
        "scheduler.py must register alembic_weekly_check job"


@pytest.mark.test_id("G88-A2")
def test_a2_redis_fallback_test_exists():
    """(2) tests/test_redis_fallback.py exists and is non-empty."""
    path = "tests/test_redis_fallback.py"
    assert os.path.exists(path), f"{path} does not exist"
    size = os.path.getsize(path)
    assert size > 0, f"{path} is empty (size={size})"


@pytest.mark.test_id("G88-A3")
def test_a3_migration_0052_exists():
    """(3) alembic/versions/0052_board_session_timing.py exists."""
    path = "alembic/versions/0052_board_session_timing.py"
    assert os.path.exists(path), f"{path} does not exist"


@pytest.mark.test_id("G88-A4")
@pytest.mark.test_id("G88-A5")
def test_a5_scheduler_health_endpoint_exists():
    """(5) /api/scheduler/health route exists and returns valid JSON structure."""
    with open("dashboard/app_fastapi.py") as f:
        content = f.read()
    assert "/api/scheduler/health" in content, \
        "app_fastapi.py must define /api/scheduler/health route"

    import os as _os
    _os.environ["REDIS_URL"] = "memory://"
    try:
        import sys as _sys
        if "dashboard.app_fastapi" in _sys.modules:
            import importlib as _il
            import dashboard.app_fastapi  # noqa: F811
            _il.reload(dashboard.app_fastapi)
        from starlette.testclient import TestClient  # noqa: F811
        from dashboard.app_fastapi import app  # noqa: F811

        client = TestClient(app)
        with patch("dashboard.app_fastapi._get_sa_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = []
            resp = client.get("/api/scheduler/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert "total_jobs" in data
        assert isinstance(data["jobs"], list)
    finally:
        _os.environ["REDIS_URL"] = "memory://"


@pytest.mark.test_id("G88-A4")
def test_a4_migration_has_response_time_s():
    """(4) Migration 0052 adds response_time_s column to board_sessions + index."""
    path = "alembic/versions/0052_board_session_timing.py"
    with open(path) as f:
        content = f.read()
    assert "response_time_s" in content, \
        "Migration must define response_time_s column"
    assert "board_sessions" in content, \
        "Migration must reference board_sessions table"
    assert "idx_board_sessions_response_time" in content, \
        "Migration must create btree index on response_time_s"
