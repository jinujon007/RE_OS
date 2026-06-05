import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit

def test_compliance_calendar_seed_default_milestones():
    from utils.lls_compliance_calendar import seed_default_milestones
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.rowcount = 1
        count = seed_default_milestones('Devanahalli')
        assert count > 0

def test_feedback_loop_invalid_outcome_returns_false():
    from intelligence.feedback_loop import record_outcome
    assert record_outcome('45/2', None, 'invalid') is False

def test_feedback_loop_valid_outcome_writes():
    from intelligence.feedback_loop import record_outcome
    with patch('utils.db.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        assert record_outcome('45/2', 18.5, 'loi') is True

def test_rera_checker_empty_name_returns_empty():
    from utils.rera_checker import resolve_developer_name
    name, conf = resolve_developer_name('')
    assert name == '' and conf == 0.0

def test_data_quality_monitor_freshness_score_empty():
    from utils.data_quality import DataQualityMonitor
    with patch('utils.data_quality.get_engine') as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []
        score = DataQualityMonitor.freshness_score()
        assert isinstance(score, dict)
