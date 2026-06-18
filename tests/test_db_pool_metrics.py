"""T-1248: DB connection pool Prometheus metrics tests."""
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_db_pool_metrics_registered():
    """db_pool_size, db_pool_checkedout, db_pool_overflow are registered gauges."""
    from config.metrics import db_pool_size, db_pool_checkedout, db_pool_overflow

    assert db_pool_size._type == "gauge"
    assert db_pool_checkedout._type == "gauge"
    assert db_pool_overflow._type == "gauge"


def test_health_includes_db_pool():
    """GET /api/v1/health returns db_pool key with size/checked_out/overflow."""
    import os
    mock_pool = MagicMock()
    mock_pool.size.return_value = 10
    mock_pool.checkedout.return_value = 3
    mock_pool.overflow.return_value = 0

    mock_engine = MagicMock()
    mock_engine.pool = mock_pool

    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    with patch("dashboard.routers.health._get_sa_engine", return_value=mock_engine), \
         patch.dict(os.environ, {"DASHBOARD_API_KEY": "test-key-123"}, clear=False):
        resp = client.get("/api/v1/health", headers={"X-API-Key": "test-key-123"})
        assert resp.status_code == 200
        data = resp.json()
        assert "db_pool" in data
        assert data["db_pool"]["size"] == 10
        assert data["db_pool"]["checked_out"] == 3
        assert data["db_pool"]["overflow"] == 0
