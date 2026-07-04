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


# ── Pool exhaustion check regression (boot deadlock 2026-07-03) ──────────────


def _fake_engine(size=10, max_overflow=5, checked_out=1):
    pool = MagicMock()
    pool.size.return_value = size
    pool._max_overflow = max_overflow
    pool.checkedout.return_value = checked_out
    # current-overflow counter starts at -pool_size on a fresh QueuePool
    pool.overflow.return_value = checked_out - size
    eng = MagicMock()
    eng.pool = pool
    return eng


def test_exhaustion_not_flagged_on_first_checkout():
    """A brand-new pool's first connection must NOT be treated as exhaustion.

    Regression: capacity was computed as size() + overflow() where overflow()
    is the CURRENT counter (starts at -pool_size), making capacity 1 on the
    first checkout — which fired AlertSuppressor.suppress(), whose own DB
    connection re-entered the checkout event and self-deadlocked on the
    non-reentrant _pool_exhaustion_lock. Every container boot hung forever.
    """
    from utils import db as db_mod

    db_mod._pool_is_exhausted = False
    with patch("utils.discord_notifier.AlertSuppressor") as sup:
        db_mod._check_pool_exhaustion(_fake_engine(checked_out=1))
        sup.suppress.assert_not_called()
    assert db_mod._pool_is_exhausted is False


def test_exhaustion_reentry_does_not_deadlock():
    """suppress()'s own DB connection re-fires the checkout event on the same
    thread; the reentrancy guard must return immediately instead of
    re-acquiring _pool_exhaustion_lock."""
    from utils import db as db_mod

    db_mod._pool_is_exhausted = False
    eng = _fake_engine(checked_out=15)  # 15 >= 10+5 → genuinely exhausted

    def reentrant_suppress(*a, **k):
        # simulate the recursive checkout event during suppress()'s query
        db_mod._check_pool_exhaustion(eng)
        return True  # suppressed → no Discord send

    with patch("utils.discord_notifier.AlertSuppressor") as sup, \
         patch("utils.discord_notifier.send_ops_alert") as send:
        sup.suppress.side_effect = reentrant_suppress
        db_mod._check_pool_exhaustion(eng)  # must complete, not deadlock
        assert sup.suppress.call_count == 1
        send.assert_not_called()
    assert db_mod._pool_is_exhausted is True
    db_mod._pool_is_exhausted = False
