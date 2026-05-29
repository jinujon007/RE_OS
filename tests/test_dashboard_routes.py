"""
T-328 — Dashboard route auth smoke tests.

Verifies the before_request auth gate: read-only endpoints bypass the key,
write endpoints require it, and invalid market returns 400.
Uses Flask test client — no real DB or Docker needed.
"""

import os
import sys

import pytest

pytestmark = pytest.mark.unit

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def client(monkeypatch):
    # Ensure no key is set by default so tests start from a known state
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    monkeypatch.delenv("DASHBOARD_API_KEY_PREV", raising=False)
    from dashboard.app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_health_no_auth(client):
    """/api/health is read-only — no key needed."""
    r = client.get("/api/health")
    assert r.status_code == 200


def test_run_trigger_requires_auth(client, monkeypatch):
    """/api/run requires auth when DASHBOARD_API_KEY is set."""
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/run/yelahanka")
    assert r.status_code == 401


def test_run_trigger_with_auth(client, monkeypatch):
    """/api/run accepts request with correct key (200/202/409 — not 401)."""
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/run/yelahanka", headers={"X-API-Key": "secret"})
    assert r.status_code in (200, 202, 409)


def test_db_state_no_auth(client):
    """/api/db/state is read-only — no key needed (may return 500 if DB absent)."""
    r = client.get("/api/db/state")
    assert r.status_code in (200, 500)


def test_run_invalid_market_returns_400(client, monkeypatch):
    """/api/run with unknown market returns 400 before any process starts."""
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/run/fakecity", headers={"X-API-Key": "secret"})
    assert r.status_code == 400
