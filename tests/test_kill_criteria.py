"""Unit tests for KillCriteriaAuditor (GATE-102).

Coverage:
- deed_throughput: TRIGGER, AT_RISK, OK, consecutive-zero detection, DB error
- corridor_accuracy: INSUFFICIENT_DATA, TRIGGER (FAIL verdict), OK (PASS verdict), exception
- decision_journal: count entries, em-dash vs hyphen dates, missing file
- compute_overall: TRIGGER, AT_RISK, OK aggregation
- endpoint: returns 200 with valid key, overall trigger cascade
- scheduler: job ID present in source
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_engine():
    eng = MagicMock()
    conn = MagicMock()
    eng.connect.return_value.__enter__.return_value = conn
    return eng


def _mock_rows(weeks: list[tuple[str, int]]) -> MagicMock:
    """Return a mock fetchall returning weekly deed counts."""
    m = MagicMock()
    m.fetchall.return_value = [(date.fromisoformat(w), c) for w, c in weeks]
    return m


# ── 1. Deed throughput ──────────────────────────────────────────────────────


def test_deed_throughput_trigger_on_zero_weeks(mock_engine):
    from utils.kill_criteria import KillCriteriaAuditor

    mock_engine.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []
    auditor = KillCriteriaAuditor(engine=mock_engine)
    result = auditor.check_deed_throughput(engine=mock_engine, as_of=date(2026, 8, 15))

    assert result["status"] == "TRIGGER"
    assert result["weeks_with_data"] == 0
    assert result["avg_deeds_per_week"] == 0.0


def test_deed_throughput_trigger_on_consecutive_zeros(mock_engine):
    from utils.kill_criteria import KillCriteriaAuditor

    mock_engine.connect.return_value.__enter__.return_value.execute.return_value = _mock_rows([
        ("2026-07-06", 5),
        ("2026-07-13", 0),
        ("2026-07-20", 0),
        ("2026-07-27", 0),
        ("2026-08-03", 0),
    ])
    auditor = KillCriteriaAuditor(engine=mock_engine)
    result = auditor.check_deed_throughput(engine=mock_engine, as_of=date(2026, 8, 15))

    assert result["status"] == "TRIGGER"
    assert "consecutive" in result["verdict"].lower()


def test_deed_throughput_does_not_trigger_on_nonconsecutive_zeros(mock_engine):
    from utils.kill_criteria import KillCriteriaAuditor

    mock_engine.connect.return_value.__enter__.return_value.execute.return_value = _mock_rows([
        ("2026-07-06", 0),
        ("2026-07-13", 12),
        ("2026-07-20", 0),
        ("2026-07-27", 8),
        ("2026-08-03", 0),
    ])
    auditor = KillCriteriaAuditor(engine=mock_engine)
    result = auditor.check_deed_throughput(engine=mock_engine, as_of=date(2026, 8, 15))

    assert result["status"] == "AT_RISK", f"Expected AT_RISK, got {result['status']}: {result['verdict']}"
    assert result["avg_deeds_per_week"] == 4.0


def test_deed_throughput_at_risk_when_below_threshold(mock_engine):
    from utils.kill_criteria import KillCriteriaAuditor

    mock_engine.connect.return_value.__enter__.return_value.execute.return_value = _mock_rows([
        ("2026-07-06", 3),
        ("2026-07-13", 5),
        ("2026-07-20", 2),
    ])
    auditor = KillCriteriaAuditor(engine=mock_engine)
    result = auditor.check_deed_throughput(engine=mock_engine, as_of=date(2026, 8, 1))

    assert result["status"] == "AT_RISK"
    assert result["avg_deeds_per_week"] < 10


def test_deed_throughput_ok_when_above_threshold(mock_engine):
    from utils.kill_criteria import KillCriteriaAuditor

    mock_engine.connect.return_value.__enter__.return_value.execute.return_value = _mock_rows([
        ("2026-07-06", 15),
        ("2026-07-13", 22),
        ("2026-07-20", 18),
        ("2026-07-27", 25),
    ])
    auditor = KillCriteriaAuditor(engine=mock_engine)
    result = auditor.check_deed_throughput(engine=mock_engine, as_of=date(2026, 8, 1))

    assert result["status"] == "OK"
    assert result["avg_deeds_per_week"] >= 10


def test_deed_throughput_db_error_returns_error_status(mock_engine):
    from utils.kill_criteria import KillCriteriaAuditor

    mock_engine.connect.return_value.__enter__.return_value.execute.side_effect = RuntimeError("DB down")
    auditor = KillCriteriaAuditor(engine=mock_engine)
    result = auditor.check_deed_throughput(engine=mock_engine, as_of=date(2026, 8, 15))

    assert result["status"] == "ERROR"
    assert "DB query failed" in result["verdict"]


# ── 2. Corridor accuracy ────────────────────────────────────────────────────


def test_corridor_accuracy_insufficient_on_empty_db(mock_engine):
    from utils.kill_criteria import KillCriteriaAuditor

    with patch("utils.kill_criteria.CorridorScorerV2") as MockScorer:
        MockScorer.return_value.backtest.return_value = {
            "verdict": "INSUFFICIENT_DATA",
            "rank_correlation": None,
            "accuracy_note": "Only 0 corridors have registered deed data.",
        }
        auditor = KillCriteriaAuditor(engine=mock_engine)
        result = auditor.check_corridor_accuracy(engine=mock_engine)

    assert result["status"] == "INSUFFICIENT_DATA"
    assert result["verdict"] == "INSUFFICIENT_DATA"
    assert result["tau_proxy"] is None


def test_corridor_accuracy_trigger_on_fail(mock_engine):
    from utils.kill_criteria import KillCriteriaAuditor

    with patch("utils.kill_criteria.CorridorScorerV2") as MockScorer:
        MockScorer.return_value.backtest.return_value = {
            "verdict": "FAIL",
            "rank_correlation": 0.33,
            "accuracy_note": "Rank correlation 33% — below 67% threshold.",
        }
        auditor = KillCriteriaAuditor(engine=mock_engine)
        result = auditor.check_corridor_accuracy(engine=mock_engine)

    assert result["status"] == "TRIGGER"
    assert result["tau_proxy"] == 0.33


def test_corridor_accuracy_ok_on_pass(mock_engine):
    from utils.kill_criteria import KillCriteriaAuditor

    with patch("utils.kill_criteria.CorridorScorerV2") as MockScorer:
        MockScorer.return_value.backtest.return_value = {
            "verdict": "PASS",
            "rank_correlation": 0.72,
            "accuracy_note": "Rank correlation 72%.",
        }
        auditor = KillCriteriaAuditor(engine=mock_engine)
        result = auditor.check_corridor_accuracy(engine=mock_engine)

    assert result["status"] == "OK"
    assert result["tau_proxy"] == 0.72


def test_corridor_accuracy_exception_returns_error(mock_engine):
    from utils.kill_criteria import KillCriteriaAuditor

    with patch("utils.kill_criteria.CorridorScorerV2") as MockScorer:
        MockScorer.side_effect = ImportError("CorridorScorerV2 not available")
        auditor = KillCriteriaAuditor(engine=mock_engine)
        result = auditor.check_corridor_accuracy(engine=mock_engine)

    assert result["status"] == "ERROR"


# ── 3. Decision journal ─────────────────────────────────────────────────────


def test_decision_journal_counts_entries(tmp_path: Path):
    from utils.kill_criteria import KillCriteriaAuditor

    journal = tmp_path / "decision_journal.md"
    em_dash = "\u2014"
    journal.write_bytes(
        (
            "# RE_OS Decision Journal\n"
            "## Entries\n"
            f"## 2026-06-01 {em_dash} First entry\n"
            "Some content.\n"
            f"## 2026-07-15 {em_dash} Second decision\n"
            "More content.\n"
        ).encode("utf-8")
    )
    auditor = KillCriteriaAuditor(engine=MagicMock())
    result = auditor.check_decision_journal(journal_path=str(journal))

    assert result["status"] == "OK"
    assert result["entry_count"] == 2
    assert result["last_entry_date"] == "2026-07-15"


def test_decision_journal_accounts_for_empty_entries(tmp_path: Path):
    from utils.kill_criteria import KillCriteriaAuditor

    journal = tmp_path / "decision_journal.md"
    journal.write_text("# RE_OS Decision Journal\n## Entries\n*None yet.*\n")
    auditor = KillCriteriaAuditor(engine=MagicMock())
    result = auditor.check_decision_journal(journal_path=str(journal))

    assert result["status"] == "OK"
    assert result["entry_count"] == 0


def test_decision_journal_missing_file_triggers(mock_engine):
    from utils.kill_criteria import KillCriteriaAuditor

    auditor = KillCriteriaAuditor(engine=mock_engine)
    result = auditor.check_decision_journal(journal_path="/nonexistent/path.md")

    assert result["status"] == "TRIGGER"
    assert result["entry_count"] == 0


def test_decision_journal_parses_hyphen_and_em_dash(tmp_path: Path):
    from utils.kill_criteria import KillCriteriaAuditor

    em = "\u2014"
    en = "\u2013"
    hy = "-"
    journal = tmp_path / "decision_journal.md"
    journal.write_bytes(
        (
            "# RE_OS Decision Journal\n"
            "## Entries\n"
            f"## 2026-06-01 {em} First (em-dash)\n"
            f"## 2026-07-15 {hy} Second (hyphen)\n"
            f"## 2026-08-20 {en} Third (en-dash)\n"
        ).encode("utf-8")
    )
    auditor = KillCriteriaAuditor(engine=MagicMock())
    result = auditor.check_decision_journal(journal_path=str(journal))

    assert result["entry_count"] == 3
    assert result["last_entry_date"] == "2026-08-20"


# ── 4. compute_overall ──────────────────────────────────────────────────────


def test_compute_overall_all_ok():
    from utils.kill_criteria import KillCriteriaAuditor

    results = [
        {"status": "OK"},
        {"status": "OK"},
        {"status": "OK"},
    ]
    assert KillCriteriaAuditor.compute_overall(results) == "OK"


def test_compute_overall_any_trigger():
    from utils.kill_criteria import KillCriteriaAuditor

    results = [
        {"status": "OK"},
        {"status": "TRIGGER"},
        {"status": "OK"},
    ]
    assert KillCriteriaAuditor.compute_overall(results) == "TRIGGER"


def test_compute_overall_at_risk_on_error():
    from utils.kill_criteria import KillCriteriaAuditor

    results = [
        {"status": "OK"},
        {"status": "ERROR"},
        {"status": "INSUFFICIENT_DATA"},
    ]
    assert KillCriteriaAuditor.compute_overall(results) == "AT_RISK"


def test_compute_overall_at_risk_on_at_risk():
    from utils.kill_criteria import KillCriteriaAuditor

    results = [
        {"status": "OK"},
        {"status": "AT_RISK"},
        {"status": "INSUFFICIENT_DATA"},
    ]
    assert KillCriteriaAuditor.compute_overall(results) == "AT_RISK"


def test_compute_overall_trigger_overrides_at_risk():
    from utils.kill_criteria import KillCriteriaAuditor

    results = [
        {"status": "AT_RISK"},
        {"status": "TRIGGER"},
        {"status": "OK"},
    ]
    assert KillCriteriaAuditor.compute_overall(results) == "TRIGGER"


# ── 5. Endpoint — T-1277 (GATE-118) ─────────────────────────────────────────


def test_kill_criteria_endpoint_200():
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"DASHBOARD_API_KEY_ADMIN": "test-key", "DASHBOARD_API_KEY": ""}, clear=False):
        from dashboard.app_fastapi import app
        from starlette.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/v1/ops/kill-criteria", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        assert "deed_throughput" in body
        assert "ledger" in body
        assert "corridor" in body
        assert "deadlines" in body
        assert "decision_journal_entries" in body
        assert body["deed_throughput"]["target"] == 50
        assert body["ledger"]["target_hit_rate"] == 0.6


def test_kill_criteria_deadline_days_remaining():
    from datetime import date
    today = date.today()
    deed_dl = date(2026, 8, 15)
    dj_dl = date(2026, 12, 31)
    dr = (deed_dl - today).days
    djr = (dj_dl - today).days
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"DASHBOARD_API_KEY_ADMIN": "test-key", "DASHBOARD_API_KEY": ""}, clear=False):
        from dashboard.app_fastapi import app
        from starlette.testclient import TestClient

        client = TestClient(app)
        resp = client.get("/api/v1/ops/kill-criteria", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["deadlines"]["days_remaining"] == dr
        assert body["deadlines"]["dj_days_remaining"] == djr
        assert body["deadlines"]["deed_throughput"] == "2026-08-15"
        assert body["deadlines"]["decision_journal"] == "2026-12-31"


def test_kill_criteria_deed_throughput_formula():
    from unittest.mock import MagicMock, patch
    from datetime import datetime

    import os
    with patch.dict(os.environ, {"DASHBOARD_API_KEY_ADMIN": "test-key", "DASHBOARD_API_KEY": ""}, clear=False):
        from dashboard.app_fastapi import app
        from starlette.testclient import TestClient

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        deed_row = (50.0, 150, 3)

        ledger_hit = MagicMock()
        ledger_hit.scalar.return_value = 30
        ledger_miss = MagicMock()
        ledger_miss.scalar.return_value = 10
        corridor_fetch = MagicMock()
        corridor_fetch.fetchall.return_value = []
        dj_count = MagicMock()
        dj_count.scalar.return_value = 0

        mock_conn.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=deed_row)),
            ledger_hit, ledger_miss,
            corridor_fetch,
            dj_count,
        ]

        with patch("dashboard.routers.ops._get_sa_engine", return_value=mock_engine):
            client = TestClient(app)
            resp = client.get("/api/v1/ops/kill-criteria", headers={"X-API-Key": "test-key"})
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert body["deed_throughput"]["weekly_avg_deeds"] == 50.0
            assert body["deed_throughput"]["on_track"] is True


# ── 6. Scheduler job registration ──────────────────────────────────────────


def test_kill_criteria_job_registered_in_scheduler():
    path = Path(__file__).resolve().parent.parent / "config" / "scheduler" / "maintenance_jobs.py"
    assert path.exists(), f"Expected scheduler file at {path}"
    content = path.read_text(encoding="utf-8")
    assert "kill_criteria_check" in content
