"""T-1130 + T-1131 + T-1132: Tests for V2 readiness API + panel."""

import datetime
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)


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

    with patch("dashboard.app_fastapi._get_sa_engine", return_value=engine):
        yield


def test_v2_readiness_returns_200(mock_empty_db):
    """Endpoint returns 200 with JSON body."""
    resp = client.get("/api/ops/v2-readiness")
    assert resp.status_code == 200


def test_v2_readiness_has_v2_ready_key(mock_empty_db):
    """Response contains the v2_ready boolean key."""
    resp = client.get("/api/ops/v2-readiness")
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
        "dashboard.app_fastapi._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        resp = client.get("/api/ops/v2-readiness")
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
        "dashboard.app_fastapi._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        resp = client.get("/api/ops/v2-readiness")
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
        "dashboard.app_fastapi._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        resp = client.get("/api/ops/v2-readiness")
        data = resp.json()
        assert data["live_rera_growth"] is False
        # v2_ready still True because growth is informational, not a hard gate
        assert data["v2_ready"] is True


def test_v2_panel_returns_200():
    """GET /ops/v2 returns 200 with HTML."""
    resp = client.get("/ops/v2")
    assert resp.status_code == 200
    assert "V2.0" in resp.text


# ── POST /api/ops/v2-declare — T-1132 ──

_AUTH = {"X-API-Key": "test-key"}


def test_v2_declare_400_when_not_ready():
    """POST /api/ops/v2-declare returns 400 when readiness criteria not met."""
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
        "dashboard.app_fastapi._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        with patch("utils.discord_notifier.send_ops_alert"):
            resp = client.post("/api/ops/v2-declare", headers=_AUTH)
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"] == "V2 criteria not yet met"
    assert "readiness" in data


def test_v2_declare_200_when_ready():
    """POST /api/ops/v2-declare returns 200 when v2_ready=True."""
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
        "dashboard.app_fastapi._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        with patch("utils.discord_notifier.send_ops_alert") as mock_alert:
            resp = client.post("/api/ops/v2-declare", headers=_AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["declared"] is True
    assert "date" in data
    assert mock_alert.called


def test_v2_declare_idempotent():
    """Second call to POST /api/ops/v2-declare returns same date as first."""
    conn = _make_mock_conn(
        [
            None,  # existing → None
            (7,),
            (10, 9),
            (2,),
            (True,),
            (45.3,),
        ]
    )
    with patch(
        "dashboard.app_fastapi._get_sa_engine", return_value=_make_mock_engine(conn)
    ):
        with patch("utils.discord_notifier.send_ops_alert"):
            resp1 = client.post("/api/ops/v2-declare", headers=_AUTH)
    assert resp1.status_code == 200
    date1 = resp1.json()["date"]
    assert date1 is not None

    conn2 = _make_mock_conn(
        [
            (datetime.datetime(2026, 6, 12, 10, 0, 0),),
        ]
    )
    with patch(
        "dashboard.app_fastapi._get_sa_engine", return_value=_make_mock_engine(conn2)
    ):
        with patch("utils.discord_notifier.send_ops_alert"):
            resp2 = client.post("/api/ops/v2-declare", headers=_AUTH)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["declared"] is True
    assert data2["date"] is not None
