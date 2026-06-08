"""Tests for DecisionAuditor — past decision review."""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from utils.decision_auditor import DecisionAuditor, _infer_verdict


def _make_mock_conn(seq_results: list[list]) -> MagicMock:
    mock_conn = MagicMock()
    call_idx = [0]

    def _side(*args, **kwargs):
        idx = call_idx[0]
        call_idx[0] += 1
        if idx < len(seq_results):
            data = seq_results[idx]
        else:
            data = []
        mr = MagicMock()
        mr.fetchall.return_value = data
        return mr

    mock_conn.execute.side_effect = _side
    return mock_conn


class TestInferVerdict:
    def test_no_go_detected(self):
        assert _infer_verdict("Recommend NO-GO on this deal") == "NO-GO"

    def test_go_detected(self):
        assert _infer_verdict("Approved. Proceed with MOU.") == "GO"

    def test_conditional_detected(self):
        assert _infer_verdict("Conditional approval subject to title clear") == "CONDITIONAL"

    def test_unknown_when_ambiguous(self):
        assert _infer_verdict("Discussed the deal at length") == "UNKNOWN"


class TestDecisionAuditor:
    @patch("utils.performance_digest.get_engine")
    def test_audit_returns_decisions_list(self, mock_eng):
        mock_conn = _make_mock_conn([
            [("uuid-1", "Yelahanka", "complete", "Go ahead", date(2026, 5, 15))],
            [("d1", "Deal", "45/2", "jd", 15.5, "GO", date(2026, 5, 15), [{"text": "good deal"}]),
             ("d2", "Deal 2", "33/1", "purchase", 12.0, "CONDITIONAL", date(2026, 6, 1), [])],
        ])
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        decisions = DecisionAuditor.audit_quarter("Q2-2026")
        assert isinstance(decisions, list)
        assert len(decisions) >= 2

    @patch("utils.performance_digest.get_engine")
    def test_contested_identified_on_split(self, mock_eng):
        mock_conn = _make_mock_conn([
            [],
            [("d1", "Deal", "45/2", "jd", 15.5, "GO", date(2026, 5, 15), [{"text": "good deal"}]),
             ("d2", "Deal 2", "33/1", "purchase", None, "NO-GO", date(2026, 6, 1), [])],
        ])
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        decisions = DecisionAuditor.audit_quarter("Q2-2026")
        assert isinstance(decisions, list)
        assert len(decisions) == 2

    @patch("utils.performance_digest.get_engine")
    def test_audit_handles_empty_quarter(self, mock_eng):
        mock_conn = _make_mock_conn([[], []])
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        decisions = DecisionAuditor.audit_quarter("Q1-2025")
        assert isinstance(decisions, list)
        assert len(decisions) == 0

    def test_contested_filter_no_shareholder_data(self):
        auditor = DecisionAuditor()
        with patch.object(auditor, "audit_quarter", return_value=[
            {"shareholder_verdicts": [{"verdict": "GO"}, {"verdict": "GO"}]},
            {"shareholder_verdicts": None},
            {},
        ]):
            contested = auditor.get_contested("Q2-2026")
            assert isinstance(contested, list)
            assert len(contested) == 0
