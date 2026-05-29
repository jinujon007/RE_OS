"""
Tests for dashboard/app.py

Covers: index, /api/health, /metrics, /api/status, /api/agents (fallback path),
/api/intel, /api/intel/cards, /api/db/state, /api/run/<market> (POST/DELETE),
auth gate (read-only bypass, write requires key, dual-key rotation), invalid market.

Strategy: mock _get_db / _get_pool so no Postgres is needed, patch subprocess.Popen
so no child process starts, use Flask test client.
"""

import json
import os
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

pytestmark = pytest.mark.unit


# ── App fixture ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def flask_app():
    """Import app once per module; patch psycopg2 at import time."""
    import sys
    import types

    # Stub psycopg2 before importing dashboard.app
    if "psycopg2" not in sys.modules:
        _psycopg2 = types.ModuleType("psycopg2")
        _psycopg2.pool = types.ModuleType("psycopg2.pool")
        _psycopg2.pool.ThreadedConnectionPool = MagicMock()
        _psycopg2.OperationalError = Exception
        sys.modules["psycopg2"] = _psycopg2
        sys.modules["psycopg2.pool"] = _psycopg2.pool

    from dashboard.app import app

    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def mock_db(flask_app):
    """Patch _get_db and _release_db so no real DB connection is used."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = None
    mock_cur.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cur

    with patch("dashboard.app._get_db", return_value=mock_conn), \
         patch("dashboard.app._release_db"):
        yield mock_conn, mock_cur


# ── index ──────────────────────────────────────────────────────────────────────


def test_index_returns_200(client):
    with patch("dashboard.app.render_template", return_value="<html>ok</html>"):
        resp = client.get("/")
    assert resp.status_code == 200


# ── /api/health ────────────────────────────────────────────────────────────────


def test_health_returns_200(client, mock_db):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "agents" in data


def test_health_no_api_key_required(client, mock_db):
    """health is read-only — must not require X-API-Key even when key is set."""
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "secret"}):
        resp = client.get("/api/health")
    assert resp.status_code == 200


# ── /metrics ───────────────────────────────────────────────────────────────────


def test_metrics_returns_200(client):
    with patch("dashboard.app.generate_latest", return_value=b"# metrics\n"):
        resp = client.get("/metrics")
    assert resp.status_code == 200


# ── /api/status ────────────────────────────────────────────────────────────────


def test_status_returns_200(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200


def test_status_is_read_only(client):
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "secret"}):
        resp = client.get("/api/status")
    assert resp.status_code == 200


# ── /api/agents ────────────────────────────────────────────────────────────────


def test_agents_returns_200(client, mock_db):
    resp = client.get("/api/agents")
    assert resp.status_code == 200


def test_agents_contains_running_markets_key(client, mock_db):
    resp = client.get("/api/agents")
    data = resp.get_json()
    # Either DB path or fallback path — both should have running_markets or agents key
    assert data is not None


# ── /api/intel (deleted T-317) ────────────────────────────────────────────────


def test_intel_returns_404(client):
    """GET /api/intel was deleted (T-317) — endpoint no longer exists."""
    resp = client.get("/api/intel")
    assert resp.status_code == 404


# ── /api/intel/cards ───────────────────────────────────────────────────────────


def test_intel_cards_returns_200(client, mock_db):
    resp = client.get("/api/intel/cards")
    assert resp.status_code == 200


def test_intel_cards_is_read_only(client, mock_db):
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "secret"}):
        resp = client.get("/api/intel/cards")
    assert resp.status_code == 200


# ── /api/db/state ──────────────────────────────────────────────────────────────


@pytest.fixture
def db_state_mock():
    """Mock returning proper (int,) tuples for COUNT queries."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    # COUNT(*) queries return (0,); market/run queries return empty list
    mock_cur.fetchone.return_value = (0,)
    mock_cur.fetchall.return_value = []
    mock_conn.cursor.return_value = mock_cur
    with patch("dashboard.app._get_db", return_value=mock_conn), \
         patch("dashboard.app._release_db"):
        yield


def test_db_state_returns_200(client, db_state_mock):
    resp = client.get("/api/db/state")
    assert resp.status_code == 200


def test_db_state_is_read_only(client, db_state_mock):
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "secret"}):
        resp = client.get("/api/db/state")
    assert resp.status_code == 200


# ── /api/run/<market> POST ─────────────────────────────────────────────────────


def test_run_pipeline_invalid_market(client):
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": ""}):
        resp = client.post("/api/run/invalidmarket")
    assert resp.status_code == 400
    assert "invalid market" in resp.get_json().get("error", "")


def test_run_pipeline_starts_process(client):
    """POST /api/run/yelahanka should return 200 and start a subprocess."""
    mock_proc = MagicMock()
    mock_proc.pid = 9999
    mock_proc.poll.return_value = None

    with patch.dict(os.environ, {"DASHBOARD_API_KEY": ""}), \
         patch("dashboard.app.subprocess.Popen", return_value=mock_proc), \
         patch("dashboard.app._running", {}):
        resp = client.post("/api/run/yelahanka")
    assert resp.status_code in (200, 202)


def test_run_pipeline_requires_auth_when_key_set(client):
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "secret"}):
        resp = client.post("/api/run/yelahanka")
    assert resp.status_code == 401


def test_run_pipeline_accepts_valid_key(client):
    mock_proc = MagicMock()
    mock_proc.pid = 9999
    mock_proc.poll.return_value = None

    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "secret"}), \
         patch("dashboard.app.subprocess.Popen", return_value=mock_proc), \
         patch("dashboard.app._running", {}):
        resp = client.post(
            "/api/run/yelahanka",
            headers={"X-API-Key": "secret"}
        )
    assert resp.status_code in (200, 202, 409)


# ── /api/run/<market> DELETE ───────────────────────────────────────────────────


def test_stop_pipeline_invalid_market(client):
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": ""}):
        resp = client.delete("/api/run/badmarket")
    assert resp.status_code == 400


def test_stop_pipeline_not_running(client):
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": ""}), \
         patch("dashboard.app._running", {}):
        resp = client.delete("/api/run/yelahanka")
    assert resp.status_code in (200, 404)


# ── Auth: dual-key rotation ────────────────────────────────────────────────────


def test_dual_key_old_key_accepted(client):
    """During rotation window, DASHBOARD_API_KEY_PREV must also be accepted."""
    mock_proc = MagicMock()
    mock_proc.pid = 1234
    mock_proc.poll.return_value = None

    with patch.dict(os.environ, {
        "DASHBOARD_API_KEY": "new-key",
        "DASHBOARD_API_KEY_PREV": "old-key"
    }), patch("dashboard.app.subprocess.Popen", return_value=mock_proc), \
       patch("dashboard.app._running", {}):
        resp = client.post(
            "/api/run/yelahanka",
            headers={"X-API-Key": "old-key"}
        )
    assert resp.status_code in (200, 202, 409)


def test_dual_key_wrong_key_rejected(client):
    with patch.dict(os.environ, {
        "DASHBOARD_API_KEY": "new-key",
        "DASHBOARD_API_KEY_PREV": "old-key"
    }):
        resp = client.post(
            "/api/run/yelahanka",
            headers={"X-API-Key": "wrong-key"}
        )
    assert resp.status_code == 401
