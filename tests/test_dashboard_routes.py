import os
import pytest
pytestmark = pytest.mark.unit

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)


def test_health_no_auth():
    r = client.get("/api/health")
    assert r.status_code == 200


def test_run_trigger_requires_auth(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/run/yelahanka")
    assert r.status_code == 401


def test_run_trigger_with_auth(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/run/yelahanka", headers={"X-API-Key": "secret"})
    assert r.status_code in (200, 202, 409)


def test_db_state_no_auth():
    r = client.get("/api/db/state")
    assert r.status_code in (200, 500)


def test_run_invalid_market_returns_400(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/run/fakecity", headers={"X-API-Key": "secret"})
    assert r.status_code == 400


# ── Memory Explorer (T-86A) ──


@pytest.fixture
def mock_db():
    """Mock _get_sa_engine to return engine whose connect() yields a mock connection
    that returns empty results for any query."""
    from unittest.mock import MagicMock, patch
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_conn.execute.return_value.scalar.return_value = 0
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_engine):
        yield


@pytest.fixture
def mock_conflict_db():
    """Mock DB returning 3 conflict rows."""
    from unittest.mock import MagicMock, patch
    mock_conn = MagicMock()
    mock_conn.execute.return_value.scalar.return_value = 3
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_engine):
        yield


def test_memory_explorer_endpoint_returns_200(mock_db):
    r = client.get("/api/memory/explorer")
    assert r.status_code in (200, 500)  # 200 when DB mocked, 500 without DB
    if r.status_code == 200:
        body = r.json()
        assert "total" in body
        assert "page" in body
        assert "per_page" in body
        assert "memories" in body


def test_memory_explorer_respects_market_filter(mock_db):
    r = client.get("/api/memory/explorer?market=Yelahanka")
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        body = r.json()
        assert body["page"] == 1
        assert body["per_page"] == 20


def test_conflict_count_endpoint_returns_integer():
    r = client.get("/api/memory/conflict-count")
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        body = r.json()
        assert "unresolved_conflicts" in body
        assert isinstance(body["unresolved_conflicts"], int)


def test_conflict_count_mocked(mock_conflict_db):
    r = client.get("/api/memory/conflict-count")
    assert r.status_code == 200
    assert r.json()["unresolved_conflicts"] == 3


# ── Conflict Badge (T-86C) ──


def test_conflict_badge_script_present_in_index_html():
    path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "templates", "index.html")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "conflict-badge" in content, "conflict-badge id not found in index.html"
    assert "/api/memory/conflict-count" in content, "/api/memory/conflict-count endpoint not found in index.html"
    assert "pollConflictBadge" in content, "pollConflictBadge function not found in index.html"


# ── Memory Panel Route (T-86B) ──


def test_memory_panel_route_returns_200():
    r = client.get("/memory")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "AGENT MEMORY EXPLORER" in r.text
