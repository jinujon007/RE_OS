import os
from unittest.mock import MagicMock, patch
import pytest
pytestmark = pytest.mark.unit

# Use in-memory rate limiter storage (avoid Redis requirement for tests)
os.environ.setdefault("REDIS_URL", "memory://")

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)


@pytest.fixture
def mock_db():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = None
    mock_cur.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cur
    with patch("dashboard.app_fastapi._get_sa_engine") as mock_engine:
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        yield mock_conn, mock_cur


def test_index_returns_200():
    r = client.get("/")
    assert r.status_code == 200


def test_health_returns_200(mock_db):
    r = client.get("/api/health")
    assert r.status_code == 200


def test_health_no_api_key_required(mock_db):
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "secret"}):
        r = client.get("/api/health")
    assert r.status_code == 200


def test_metrics_returns_200():
    with patch("dashboard.app_fastapi.generate_latest", return_value=b"# metrics\n"):
        r = client.get("/metrics")
    assert r.status_code == 200


def test_status_returns_200():
    r = client.get("/api/status")
    assert r.status_code == 200


def test_run_pipeline_invalid_market():
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": ""}):
        r = client.post("/api/run/invalidmarket")
    assert r.status_code == 400
    assert "invalid market" in r.json().get("error", "")


def test_run_pipeline_requires_auth_when_key_set():
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "secret"}):
        r = client.post("/api/run/yelahanka")
    assert r.status_code == 401


def test_stop_pipeline_invalid_market():
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": ""}):
        r = client.delete("/api/run/badmarket")
    assert r.status_code == 400


def test_dual_key_old_key_accepted(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "new-key")
    monkeypatch.setenv("DASHBOARD_API_KEY_PREV", "old-key")
    r = client.post("/api/run/yelahanka", headers={"X-API-Key": "old-key"})
    assert r.status_code in (200, 202, 409)


def test_dual_key_wrong_key_rejected(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "new-key")
    monkeypatch.setenv("DASHBOARD_API_KEY_PREV", "old-key")
    r = client.post("/api/run/yelahanka", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401
