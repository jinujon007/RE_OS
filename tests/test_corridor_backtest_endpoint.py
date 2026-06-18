"""Tests for GET /api/v1/ops/corridor-backtest endpoint (T-1270, GATE-116)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture
def app():
    """Import app after resetting auth to prevent stale API key state."""
    from dashboard import state as _ds
    _ds._API_KEY = None
    _ds._API_KEY_READ = None
    _ds._API_KEY_ADMIN = None
    _ds._API_KEY_WARNED = False
    import os
    os.environ["DASHBOARD_API_KEY"] = "test-key-for-pytest"
    os.environ["DASHBOARD_API_KEY_READ"] = "test-read-key"
    from dashboard.app_fastapi import app as _app
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


def _mock_db(rows):
    """Patch _get_sa_engine to return given rows."""
    engine = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = rows
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value.__enter__.return_value = conn
    return patch("dashboard.routers.ops._get_sa_engine", return_value=engine)


def test_corridor_backtest_endpoint_200(client):
    """Endpoint returns 200 when corridor_backtest_verdicts has data."""
    with _mock_db([
        ("nh44", "2026-06-18", 0.72, True, "PASS"),
        ("hebbal_yelahanka", "2026-06-18", 0.45, False, "FAIL"),
    ]):
        resp = client.get(
            "/api/v1/ops/corridor-backtest",
            headers={"X-API-Key": "test-key-for-pytest"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"
        body = resp.json()
        assert "corridors" in body
        assert len(body["corridors"]) == 2
        assert body["corridors"][0]["corridor_name"] == "nh44"
        assert body["corridors"][0]["rank_correlation"] == 0.72
        assert body["corridors"][0]["kill_criterion_met"] is True
        assert body["corridors"][0]["verdict"] == "PASS"


def test_corridor_backtest_verdict_schema():
    """Verdict schema has all required fields."""
    from dashboard.routers.ops import CorridorBacktestVerdict, CorridorBacktestResponse

    v = CorridorBacktestVerdict(
        corridor_name="nh44",
        last_run_date="2026-06-18",
        rank_correlation=0.72,
        kill_criterion_met=True,
        verdict="PASS",
    )
    d = v.model_dump()
    assert d["corridor_name"] == "nh44"
    assert d["rank_correlation"] == 0.72
    assert d["kill_criterion_met"] is True
    assert d["verdict"] == "PASS"

    resp = CorridorBacktestResponse(corridors=[v], as_of="2026-06-18T00:00:00")
    assert len(resp.corridors) == 1
    assert resp.corridors[0].corridor_name == "nh44"


def test_corridor_backtest_empty_returns_seeds(client):
    """When verdicts table is empty, returns seed corridors with null verdicts."""
    with _mock_db([]):
        resp = client.get(
            "/api/v1/ops/corridor-backtest",
            headers={"X-API-Key": "test-key-for-pytest"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["corridors"]) >= 3
        assert all(
            c["verdict"] is None for c in body["corridors"]
        ), "Empty verdicts should return null verdicts"


def test_corridor_backtest_cli_smoke():
    """Backtest script's main() can be imported and described."""
    import scripts.run_corridor_backtest as _mod
    assert callable(_mod.main)
    assert callable(_mod.run_backtest)
