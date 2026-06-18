"""GATE-118 — Kill Criteria Dashboard.

5 assertions:
1. /api/v1/ops/kill-criteria returns 200 with all 5 top-level keys
2. run_deed_throughput_digest callable from config.scheduler.digest_jobs
3. Migration 0067_decision_journal compiles
4. /api/v1/ops/decision-journal GET returns 200 + POST returns 201
5. days_remaining computed from (deadline - today).days, not hardcoded
"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient


MIG_0067 = Path("alembic/versions/0067_decision_journal.py")
OPS_SRC = Path("dashboard/routers/ops.py")


def test_kill_criteria_route_returns_all_keys():
    with patch.dict("os.environ", {"DASHBOARD_API_KEY_ADMIN": "tk", "DASHBOARD_API_KEY": ""}, clear=False):
        from dashboard.app_fastapi import app
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        deed_row = (20.0, 60, 3)
        ledger_hit = MagicMock()
        ledger_hit.scalar.return_value = 5
        ledger_miss = MagicMock()
        ledger_miss.scalar.return_value = 3
        corridor_fetch = MagicMock()
        corridor_fetch.fetchall.return_value = []
        dj_count = MagicMock()
        dj_count.scalar.return_value = 1

        mock_conn.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=deed_row)),
            ledger_hit, ledger_miss,
            corridor_fetch, dj_count,
        ]

        with patch("dashboard.routers.ops._get_sa_engine", return_value=mock_engine):
            client = TestClient(app)
            resp = client.get("/api/v1/ops/kill-criteria", headers={"X-API-Key": "tk"})
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "deed_throughput" in body
            assert "ledger" in body
            assert "corridor" in body
            assert "deadlines" in body
            assert "decision_journal_entries" in body
            assert body["deed_throughput"]["target"] == 50
            assert body["ledger"]["target_hit_rate"] == 0.6
            assert body["decision_journal_entries"] == 1


def test_deed_throughput_digest_callable():
    from config.scheduler.digest_jobs import run_deed_throughput_digest
    assert callable(run_deed_throughput_digest)


def test_migration_0067_compiles():
    import py_compile
    result = py_compile.compile(str(MIG_0067), doraise=True)
    assert result is not None


def test_decision_journal_get_post():
    from datetime import datetime, timezone
    with patch.dict("os.environ", {"DASHBOARD_API_KEY": "tk"}, clear=False):
        from dashboard.app_fastapi import app

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        created_dt = datetime(2026, 6, 18, 14, 0, 0, tzinfo=timezone.utc)
        insert_row = (1, created_dt)

        def _side_effect(*a, **kw):
            if "RETURNING" in str(a):
                return MagicMock(fetchone=MagicMock(return_value=insert_row))
            if "COUNT" in str(a):
                return MagicMock(scalar=MagicMock(return_value=2))
            return MagicMock(fetchall=MagicMock(return_value=[
                (1, date(2026, 6, 18), "pricing", "Hebbal", "PSF data", "acted", "test", created_dt),
            ]))

        mock_conn.execute.side_effect = _side_effect

        with patch("dashboard.routers.ops._get_sa_engine", return_value=mock_engine):
            client = TestClient(app)
            post_resp = client.post(
                "/api/v1/ops/decision-journal",
                headers={"X-API-Key": "tk"},
                json={"entry_date": "2026-06-18", "decision_type": "pricing", "market": "Hebbal"},
            )
            assert post_resp.status_code == 201, f"POST expected 201, got {post_resp.status_code}: {post_resp.text}"
            assert "id" in post_resp.json()
            assert "created_at" in post_resp.json()

            get_resp = client.get("/api/v1/ops/decision-journal", headers={"X-API-Key": "tk"})
            assert get_resp.status_code == 200
            body = get_resp.json()
            assert body["total"] == 2
            assert len(body["entries"]) == 1


def test_days_remaining_formula():
    today = date.today()
    dl = date(2026, 8, 15)
    dr = (dl - today).days
    content = OPS_SRC.read_text()
    assert "(deed_deadline - today).days" in content
    assert dr > 0, f"Expected positive days remaining, got {dr}"
