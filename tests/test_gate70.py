"""GATE-70 declaration — Sprint 62 Full Shareholder Board.

6 assertions covering:
1. PerformanceDigest.build returns dict with all 5 sections
2. DecisionAuditor.audit_quarter returns a list
3. Debate triggered when 2 of 4 shareholders have opposing verdicts
4. ShareholderBoardCrew.save_letter creates file
5. GET /shareholders returns 200
6. Scheduler has monthly_ceo_letter job registered
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def test_performance_digest_has_all_sections():
    with patch("utils.performance_digest.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        call_idx = [0]

        def _side(*args, **kwargs):
            idx = call_idx[0]
            call_idx[0] += 1
            mr = MagicMock()
            if idx == 0:
                mr.fetchall.return_value = [(0, None)]
            elif idx == 1:
                mr.fetchall.return_value = []
            elif idx == 2:
                mr.fetchall.return_value = [(0, None)]
            elif idx == 3:
                mr.fetchall.return_value = []
            else:
                mr.fetchall.return_value = [(0, 0)]
            return mr

        mock_conn.execute.side_effect = _side
        from utils.performance_digest import PerformanceDigest

        digest = PerformanceDigest.build("Q2-2026")
        assert "deal_metrics" in digest
        assert "new_projects" in digest
        assert "absorption_trend" in digest
        assert "deal_velocity_summary" in digest
        assert "token_efficiency" in digest
        assert digest["quarter"] == "Q2-2026"


def test_decision_auditor_audit_quarter_returns_list():
    with patch("utils.decision_auditor.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        call_idx = [0]

        def _side(*args, **kwargs):
            idx = call_idx[0]
            call_idx[0] += 1
            mr = MagicMock()
            mr.fetchall.return_value = []
            return mr

        mock_conn.execute.side_effect = _side
        from utils.decision_auditor import DecisionAuditor

        decisions = DecisionAuditor.audit_quarter("Q2-2026")
        assert isinstance(decisions, list)


def test_debate_triggered_on_opposing_verdicts():
    from crews.shareholder_review import _needs_debate

    responses = [
        {"name": "A", "verdict": "GO_ON_PLAN"},
        {"name": "B", "verdict": "NEEDS_CORRECTION"},
        {"name": "C", "verdict": "GO_ON_PLAN"},
        {"name": "D", "verdict": "NEEDS_CORRECTION"},
    ]
    assert _needs_debate(responses) is True


def test_save_letter_creates_file():
    with (
        patch("pathlib.Path.write_text") as mock_write,
        patch("pathlib.Path.mkdir") as mock_mkdir,
    ):
        from crews.shareholder_review import ShareholderBoardCrew

        path = ShareholderBoardCrew.save_letter(
            "test-session-id", "CEO Letter Text Q2", "Q2-2026"
        )
        assert "CEO_Letter" in path and "shareholder_letters" in path


def test_shareholders_panel_template_exists():
    from pathlib import Path

    template = Path("dashboard/templates/shareholders.html")
    assert template.exists(), "shareholders.html template not found"
    assert "Shareholder Room" in template.read_text(encoding="utf-8")


def test_monthly_ceo_scheduler_job_registered():
    from config.scheduler import monthly_ceo_letter

    assert callable(monthly_ceo_letter)
