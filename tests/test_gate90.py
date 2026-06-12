"""GATE-90: V2.0 Operations Baseline — declaration tests.

4 assertions:
(1) /api/ops/v2-readiness returns 200 with v2_ready key
(2) v2_ready=False when scheduler_days_running=0 (mock)
(3) v2_ready=True when all thresholds met (mock)
(4) dashboard/templates/v2_readiness.html exists
"""
import os
from unittest.mock import MagicMock, patch

import pytest
pytestmark = pytest.mark.unit

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)


def _make_mock_fetchone(results):
    it = iter(results)
    return lambda *a, **kw: next(it)


def _test_client(rows):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.fetchone = _make_mock_fetchone(rows)
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    return engine


def test_gate90_assertion_1_endpoint_exists():
    """A1: /api/ops/v2-readiness returns 200 with v2_ready key."""
    engine = _test_client([
        (0,), (0, 0), (0,), (True,), (None,),
    ])
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=engine):
        resp = client.get("/api/ops/v2-readiness")
    assert resp.status_code == 200
    data = resp.json()
    assert "v2_ready" in data


def test_gate90_assertion_2_not_ready():
    """A2: v2_ready=False when scheduler_days_running=0 (mock)."""
    engine = _test_client([
        (0,), (10, 0), (0,), (True,), (None,),
    ])
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=engine):
        resp = client.get("/api/ops/v2-readiness")
    data = resp.json()
    assert data["v2_ready"] is False
    assert data["scheduler_days_running"] == 0


def test_gate90_assertion_3_ready():
    """A3: v2_ready=True when all thresholds met (mock)."""
    engine = _test_client([
        (7,), (10, 9), (2,), (True,), (45.3,),
    ])
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=engine):
        resp = client.get("/api/ops/v2-readiness")
    data = resp.json()
    assert data["v2_ready"] is True
    assert data["scheduler_days_running"] >= 7
    assert data["scheduler_success_rate"] >= 0.8
    assert data["discord_digest_count"] >= 1


def test_gate90_assertion_4_template_exists():
    """A4: dashboard/templates/v2_readiness.html exists."""
    assert os.path.isfile("dashboard/templates/v2_readiness.html")
