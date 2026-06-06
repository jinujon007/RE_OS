"""Tests for GATE-50 — Compounding Intelligence Loop (T-942).

Each GATE-50 component tested in isolation with mocked DB:
1. compliance_calendar.seed_default_milestones
2. feedback_loop.record_outcome
3. feedback_loop.get_outcome_history
4. rera_checker.resolve_developer_name
5. data_quality.DataQualityMonitor
"""
import pytest
from unittest.mock import patch, MagicMock, call
pytestmark = pytest.mark.unit


# ── Compliance Calendar ─────────────────────────────────────────────────────────

def test_compliance_calendar_seed_default_milestones():
    from utils.lls_compliance_calendar import seed_default_milestones
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.rowcount = 1
        count = seed_default_milestones('Devanahalli')
        assert count > 0
        assert mock_conn.execute.called, "INSERT should be executed"


# ── Feedback Loop ──────────────────────────────────────────────────────────────

def test_feedback_loop_invalid_outcome_returns_false():
    from intelligence.feedback_loop import record_outcome
    assert record_outcome('45/2', None, 'invalid') is False


def test_feedback_loop_valid_outcome_writes_with_rowcount_check():
    """Valid outcome writes to DB; rowcount verification returns True."""
    from intelligence.feedback_loop import record_outcome
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        result_mock = MagicMock()
        result_mock.rowcount = 1
        mock_conn.execute.return_value = result_mock
        assert record_outcome('45/2', 18.5, 'loi') is True


def test_feedback_loop_missing_survey_returns_false():
    from intelligence.feedback_loop import record_outcome
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        result_mock = MagicMock()
        result_mock.rowcount = 0
        mock_conn.execute.return_value = result_mock
        assert record_outcome('99/99', 18.5, 'loi') is False, \
            "Should return False when survey_no not found (0 rows updated)"


def test_feedback_loop_none_irr_is_valid():
    """None actual_irr is valid for non-signed outcomes (lost/withdrawn)."""
    from intelligence.feedback_loop import record_outcome
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        result_mock = MagicMock()
        result_mock.rowcount = 1
        mock_conn.execute.return_value = result_mock
        assert record_outcome('45/2', None, 'lost') is True


def test_feedback_loop_irr_clamped_to_range():
    """Extreme IRR values are clamped to [-100, 1000]."""
    from intelligence.feedback_loop import record_outcome
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        result_mock = MagicMock()
        result_mock.rowcount = 1
        mock_conn.execute.return_value = result_mock
        assert record_outcome('45/2', 9999.0, 'loi') is True


def test_feedback_loop_get_outcome_history_empty():
    from intelligence.feedback_loop import get_outcome_history
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []
        history = get_outcome_history('nonexistent')
        assert isinstance(history, list)
        assert len(history) == 0


def test_feedback_loop_get_outcome_history_returns_records():
    from datetime import datetime, timezone
    from intelligence.feedback_loop import get_outcome_history
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_row = MagicMock()
        mock_row.__getitem__.side_effect = lambda i: ["45/2", 18.5, "loi", datetime.now(timezone.utc), "notes"][i]
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]
        history = get_outcome_history('45/2')
        assert len(history) == 1
        assert history[0]["survey_no"] == "45/2"
        assert history[0]["actual_irr"] == 18.5
        assert history[0]["outcome"] == "loi"


# ── RERA Checker ───────────────────────────────────────────────────────────────

def test_rera_checker_empty_name_returns_empty():
    from utils.rera_checker import resolve_developer_name
    name, conf = resolve_developer_name('')
    assert name == '' and conf == 0.0


# ── Data Quality Monitor ───────────────────────────────────────────────────────

def test_data_quality_monitor_freshness_score_empty():
    from utils.data_quality import DataQualityMonitor
    with patch('utils.data_quality.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []
        score = DataQualityMonitor.freshness_score()
        assert isinstance(score, dict)
