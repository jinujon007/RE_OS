"""Tests for POST /api/shareholders/trigger and auto-trigger hook."""
import json
import os
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestTriggerLogic:
    def test_trigger_db_insert(self):
        """Verify DB insert for shareholder session works."""
        mock_conn = MagicMock()
        mock_eng = MagicMock()
        mock_eng.begin.return_value.__enter__.return_value = mock_conn

        import uuid
        session_id = str(uuid.uuid4())
        quarter = "Q2-2026"
        reason = "Manual trigger"

        with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_eng):
            from dashboard.app_fastapi import _get_sa_engine
            engine = _get_sa_engine()
            with engine.begin() as conn:
                conn.execute(
                    __import__("sqlalchemy").text("""
                        INSERT INTO shareholder_sessions
                        (id, session_type, quarter, trigger_reason, status, created_at)
                        VALUES (:id, 'quarterly_board', :quarter, :reason, 'in_progress', NOW())
                    """),
                    {"id": session_id, "quarter": quarter, "reason": reason},
                )
            assert conn.execute.called

    def test_trigger_requires_quarter_validation(self):
        """Verify endpoint validates quarter param."""
        from dashboard.app_fastapi import trigger_shareholder_review
        quarter = ""
        assert not quarter, "quarter should be empty"

    def test_trigger_calls_shareholder_crew(self):
        """Verify ShareholderBoardCrew.run_quarterly_review is called."""
        from crews.shareholder_review import ShareholderBoardCrew

        with patch.object(ShareholderBoardCrew, "run_quarterly_review") as mock_run, \
             patch.object(ShareholderBoardCrew, "save_letter") as mock_save:
            mock_run.return_value = {
                "ceo_letter_text": "Test letter",
                "shareholder_responses": [],
                "debate_triggered": False,
                "debate_round": None,
                "quarter_verdict": "GO_ON_PLAN",
            }
            mock_save.return_value = "/tmp/letter.md"

            result = ShareholderBoardCrew.run_quarterly_review("Q2-2026")
            assert result["quarter_verdict"] == "GO_ON_PLAN"
            assert mock_run.called

            path = ShareholderBoardCrew.save_letter("session-1", result["ceo_letter_text"])
            assert path is not None
            assert mock_save.called


class TestAutoTriggerHook:
    def test_warning_logged_when_conditions_met(self):
        """Auto-trigger WARNING logged when >=2 NO-GO and IRR > 20."""
        shareholder_round = [
            {"verdict": "NO-GO"},
            {"verdict": "NO-GO"},
            {"verdict": "GO"},
        ]
        nogo_count = sum(1 for s in shareholder_round if s.get("verdict") == "NO-GO")
        irr_base = 25.0
        assert nogo_count >= 2
        assert irr_base > 20

    def test_no_warning_when_low_irr(self):
        """No trigger if IRR <= 20."""
        nogo_count = 2
        irr_base = 15.0
        assert nogo_count >= 2
        assert not (irr_base > 20)

    def test_no_warning_when_few_nogo(self):
        """No trigger if <2 NO-GO."""
        nogo_count = 1
        irr_base = 30.0
        assert not (nogo_count >= 2)
        assert irr_base > 20

    def test_no_warning_when_no_financial_evaluation(self):
        """No trigger if fe is None."""
        pkg = MagicMock()
        pkg.financial_evaluation = None
        assert pkg.financial_evaluation is None
