"""GATE-111 declaration — Prediction Ledger: First Real Verdicts.

4 assertions:
1. /api/v1/ops/ledger returns 200 with hit_rate key
2. run_ledger_verdict_digest registered in scheduler
3. prediction_ledger migration importable with verdict field
4. hit_rate formula: hit / max(hit + miss, 1) (assert specific value on mock data)
"""

import os
os.environ.setdefault("REDIS_URL", "memory://")

import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_ledger_endpoint_returns_200_with_hit_rate(monkeypatch):
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        MagicMock(fetchall=lambda: [("pending", 3), ("hit", 10), ("miss", 2)]),
        MagicMock(fetchall=lambda: [("Yelahanka",)]),
        MagicMock(fetchall=lambda: [("psf_forecast", "hit", 8), ("psf_forecast", "miss", 1)]),
    ]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.routers.ops._get_sa_engine", return_value=mock_engine):
        r = client.get("/api/v1/ops/ledger")
    assert r.status_code == 200
    body = r.json()
    assert "hit_rate" in body


def test_ledger_verdict_digest_job_registered_in_scheduler():
    """run_ledger_verdict_digest is callable from config.scheduler."""
    import config.scheduler
    assert callable(config.scheduler.run_ledger_verdict_digest)

    with patch("config.scheduler.digest_jobs.BlockingScheduler") as MockSched:
        from config.scheduler.digest_jobs import register_jobs
        sched = MockSched()
        register_jobs(sched, lambda fn, name: fn())
        ids = [call[1].get("id") for call in sched.add_job.call_args_list]
        assert "ledger_verdict_digest" in ids


def test_prediction_ledger_migration_has_verdict_field():
    """Migration 0057 defines verdict column on prediction_ledger."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "migration_0057",
        "alembic/versions/0057_prediction_ledger.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    upgrade_code = mod.upgrade.__code__
    with open(mod.upgrade.__code__.co_filename) as f:
        source = f.read()
    assert "verdict" in source, "verdict column must be defined in migration 0057"


def test_hit_rate_formula(monkeypatch):
    """hit_rate = hit / max(hit + miss, 1)."""
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        MagicMock(fetchall=lambda: [("pending", 0), ("hit", 15), ("miss", 5)]),
        MagicMock(fetchall=lambda: []),
        MagicMock(fetchall=lambda: [("psf_forecast", "hit", 12), ("psf_forecast", "miss", 3)]),
    ]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.routers.ops._get_sa_engine", return_value=mock_engine):
        r = client.get("/api/v1/ops/ledger")
    assert r.status_code == 200
    body = r.json()
    expected = 15 / (15 + 5)
    assert body["hit_rate"] == pytest.approx(expected, rel=0.01)
    assert body["hit"] == 15
    assert body["miss"] == 5
