"""T-1130 + T-1131 + T-1132: Tests for V2 readiness API + panel.

Post GATE-124 R1 fixes:
  - V2R-1: test_v2_panel_returns_200 path fixed → /api/v1/ops/v2
  - V2R-2: declare tests use empty header (ALLOW_EMPTY=true)
  - V2R-3: idempotency asserts date1 == date2
  - SEC-1: per-function TestClient avoids env leakage
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

_module_client = TestClient(app)


def _make_mock_fetchone(results):
    it = iter(results)
    return lambda *a, **kw: next(it)


def _make_mock_engine(mock_conn):
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = mock_conn
    engine.begin.return_value.__enter__.return_value = mock_conn
    return engine


def _make_mock_conn(fetchone_results):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.fetchone = _make_mock_fetchone(fetchone_results)
    return conn


@pytest.fixture
def mock_empty_db():
    """Mock _get_sa_engine returning empty/zero results."""
    conn = _make_mock_conn(
        [
            (0,),  # scheduler_days_running
            (0, 0),  # total=0, successes=0
            (0,),  # discord_digest_count
            (True,),  # live_rera_growth
            (None,),  # board_room_avg_response_s
        ]
    )
    engine = _make_mock_engine(conn)

    with patch("dashboard.routers.ops._get_sa_engine", return_value=engine):
        yield


def test_v2_readiness_returns_200(mock_empty_db):
    """Endpoint returns 200 with JSON body."""
    resp = _module_client.get("/api/ops/v2-readiness")
    assert resp.status_code == 200


def test_v2_readiness_has_v2_ready_key(mock_empty_db):
    """Response contains the v2_ready boolean key."""
    resp = _module_client.get("/api/ops/v2-readiness")
    data = resp.json()
    assert "v2_ready" in data
    assert isinstance(data["v2_ready"], bool)


def test_v2_readiness_false_when_success_rate_zero():
    """v2_ready=False when scheduler_success_rate is 0.0."""
    conn = _make_mock_conn(
        [
            (0,),  # scheduler_days_running (0 days)
            (10, 0),  # total=10, successes=0 → rate=0.0
            (0,),  # discord_digest_count
            (True,),  # live_rera_growth
            (None,),  # board_room_avg_response_s
        ]
    )
    with patch(
        "dashboard.routers.ops._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        resp = _module_client.get("/api/ops/v2-readiness")
        data = resp.json()
        assert data["v2_ready"] is False
        assert data["scheduler_success_rate"] == 0.0
        assert data["scheduler_days_running"] == 0


def test_v2_readiness_true_when_all_conditions_met():
    """v2_ready=True when success_rate>=0.8, days>=7, digest>=1."""
    conn = _make_mock_conn(
        [
            (7,),  # scheduler_days_running
            (10, 9),  # total=10, successes=9 → rate=0.9
            (2,),  # discord_digest_count
            (True,),  # live_rera_growth
            (45.3,),  # board_room_avg_response_s
        ]
    )
    with patch(
        "dashboard.routers.ops._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        resp = _module_client.get("/api/ops/v2-readiness")
        data = resp.json()
        assert data["v2_ready"] is True
        assert data["scheduler_days_running"] == 7
        assert data["scheduler_success_rate"] >= 0.8
        assert data["discord_digest_count"] >= 1


def test_v2_readiness_live_rera_growth_false():
    """live_rera_growth=False when no market shows growth over 7d baseline."""
    conn = _make_mock_conn(
        [
            (7,),  # scheduler_days_running
            (10, 9),  # total=10, successes=9
            (2,),  # discord_digest_count
            (False,),  # live_rera_growth — no growth detected
            (45.3,),  # board_room_avg_response_s
        ]
    )
    with patch(
        "dashboard.routers.ops._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        resp = _module_client.get("/api/ops/v2-readiness")
        data = resp.json()
        assert data["live_rera_growth"] is False
        # v2_ready still True because growth is informational, not a hard gate
        assert data["v2_ready"] is True


def test_v2_panel_returns_200():
    """GET /api/v1/ops/v2 returns 200 with HTML panel.

    CONF-1 (R1): was using /ops/v2 which bypasses the /api/* legacy redirect.
    The panel route is registered at @router.get("/ops/v2") under the
    /api/v1 prefix, making the full path /api/v1/ops/v2.
    """
    resp = _module_client.get("/api/v1/ops/v2")
    assert resp.status_code == 200
    assert "V2.0" in resp.text


# ── POST /api/ops/v2-declare — T-1132 ──

# These tests rely on DASHBOARD_API_KEY_ALLOW_EMPTY=true (set in conftest).
# With ALLOW_EMPTY, sending a key that doesn't match DASHBOARD_API_KEY results
# in 401. These tests use a fresh TestClient so env changes don't leak.


@pytest.fixture
def _no_key_client():
    """TestClient with no auth headers — relies on ALLOW_EMPTY=true."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_v2_declare_400_when_not_ready(_no_key_client):
    """POST /api/v1/ops/v2-declare returns 400 when readiness criteria not met.

    Uses the v1-prefixed path directly (not /api/ops/v2-declare) to avoid
    a 301 redirect that would convert POST→GET and miss the endpoint.
    """
    conn = _make_mock_conn(
        [
            None,  # existing declaration check → None
            (0,),  # scheduler_days_running
            (10, 0),  # successes=0/10 → rate=0.0
            (0,),  # discord_digest_count
            (True,),  # live_rera_growth
            (None,),  # board_room_avg_response_s
        ]
    )
    with patch(
        "dashboard.routers.ops._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        with patch("utils.discord_notifier.send_ops_alert"):
            resp = _no_key_client.post("/api/v1/ops/v2-declare")
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"] == "V2 criteria not yet met"
    assert "readiness" in data


def test_v2_declare_200_when_ready(_no_key_client):
    """POST /api/v1/ops/v2-declare returns 200 when v2_ready=True."""
    conn = _make_mock_conn(
        [
            None,  # existing declaration check → None
            (7,),  # scheduler_days_running
            (10, 9),  # successes=9/10 → rate=0.9
            (2,),  # discord_digest_count
            (True,),  # live_rera_growth
            (45.3,),  # board_room_avg_response_s
        ]
    )
    with patch(
        "dashboard.routers.ops._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        with patch("utils.discord_notifier.send_ops_alert") as mock_alert:
            resp = _no_key_client.post("/api/v1/ops/v2-declare")
    assert resp.status_code == 200
    data = resp.json()
    assert data["declared"] is True
    assert "date" in data
    assert mock_alert.called


def test_v2_declare_idempotent(_no_key_client):
    """Second call to POST /api/v1/ops/v2-declare returns same date as first.

    V2R-3 (R1): was checking both dates are non-None but never asserting
    they are equal. Now asserts date1 == date2.

    Uses the date returned by the first call as the mock return value for
    the second call's existing-record check, so the mock chain is consistent
    with the logical database state.
    """
    conn = _make_mock_conn(
        [
            None,  # existing → None (first call — fresh declare)
            (7,),
            (10, 9),
            (2,),
            (True,),
            (45.3,),
        ]
    )
    with patch(
        "dashboard.routers.ops._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        with patch("utils.discord_notifier.send_ops_alert"):
            resp1 = _no_key_client.post("/api/v1/ops/v2-declare")
    assert resp1.status_code == 200, f"First call failed: {resp1.json()}"
    date1 = resp1.json()["date"]
    assert date1 is not None

    # Second call: existing record found — return the same date as the first call
    date_dt = datetime.datetime.fromisoformat(date1)
    conn2 = _make_mock_conn(
        [
            (date_dt,),  # existing = date from first call
        ]
    )
    with patch(
        "dashboard.routers.ops._get_sa_engine", return_value=_make_mock_engine(conn2)
    ):
        with patch("utils.discord_notifier.send_ops_alert"):
            resp2 = _no_key_client.post("/api/v1/ops/v2-declare")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["declared"] is True
    assert data2["date"] == date1, (
        f"Idempotency violation: first call returned {date1}, "
        f"second call returned {data2['date']}"
    )
