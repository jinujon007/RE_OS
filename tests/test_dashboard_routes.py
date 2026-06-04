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
