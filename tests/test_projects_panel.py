"""Unit tests for /projects dashboard panel (T-996)."""

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.unit


def test_projects_route_returns_200():
    from dashboard.app_fastapi import app

    client = TestClient(app)
    resp = client.get("/projects", headers={"X-API-Key": "test"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
