"""Tests for Sprint 66 — Compounding Intelligence"""
import pytest
from unittest.mock import patch, MagicMock, ANY
pytestmark = pytest.mark.unit


class TestShareholderAgent:
    def test_load_shareholder_specs_empty_dir(self, tmp_path):
        from agents.shareholder_agent import load_shareholder_specs
        with patch("agents.shareholder_agent._REGISTRY_DIR", tmp_path):
            specs = load_shareholder_specs()
            assert specs == []

    def test_load_shareholder_specs_with_file(self, tmp_path):
        import yaml
        spec_file = tmp_path / "shareholder_test.yaml"
        spec_file.write_text(yaml.dump({"id": "test_s1", "name": "Test", "role": "Tester", "persona": "Test persona", "llm_tier": "analysis"}))
        from agents.shareholder_agent import load_shareholder_specs
        with patch("agents.shareholder_agent._REGISTRY_DIR", tmp_path):
            specs = load_shareholder_specs()
            assert len(specs) == 1
            assert specs[0]["id"] == "test_s1"

    def test_create_shareholder_agent(self):
        from agents.shareholder_agent import create_shareholder_agent
        spec = {"id": "s1", "name": "Investor A", "role": "Value Investor", "persona": "Long-term investor", "llm_tier": "analysis", "investment_thesis": "Value growth"}
        agent = create_shareholder_agent(spec)
        assert agent is not None

    def test_get_shareholder_questions_empty(self):
        from agents.shareholder_agent import get_shareholder_questions
        with patch("agents.shareholder_agent.load_shareholder_specs", return_value=[]):
            qs = get_shareholder_questions("Yelahanka", "Deal summary")
            assert len(qs) > 0
            assert "No Shareholders" in qs[0]["name"] or "J-2" in qs[0]["question"]


class TestFeedbackLoop:
    def test_record_outcome_invalid(self):
        from intelligence.feedback_loop import record_outcome
        result = record_outcome("45/2", None, "invalid_outcome")
        assert result is False

    def test_record_outcome_valid_no_db(self):
        from intelligence.feedback_loop import record_outcome
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            result = record_outcome("45/2", 18.5, "signed")
            assert result is True

    def test_get_outcome_history_empty(self):
        from intelligence.feedback_loop import get_outcome_history
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = []
            results = get_outcome_history()
            assert results == []


class TestComplianceCalendar:
    def test_seed_default_milestones(self):
        from utils.lls_compliance_calendar import seed_default_milestones
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            mock_result = MagicMock()
            mock_result.rowcount = 1
            mock_conn.execute.return_value = mock_result
            count = seed_default_milestones("Yelahanka")
            assert count > 0

    def test_check_upcoming_no_alerts(self):
        from utils.lls_compliance_calendar import check_upcoming_deadlines
        from config.settings import TARGET_MARKETS
        with patch("utils.lls_compliance_calendar.get_milestones", return_value=[]):
            alerts = check_upcoming_deadlines()
            assert alerts == []


class TestDeveloperChecker:
    def test_resolve_no_match(self):
        from utils.rera_checker import resolve_developer_name
        name, conf = resolve_developer_name("")
        assert name == ""
        assert conf == 0.0

    def test_resolve_db_error(self):
        from utils.rera_checker import resolve_developer_name
        with patch("utils.db.get_engine", side_effect=Exception("DB down")):
            name, conf = resolve_developer_name("Brigade")
            assert name == "Brigade"
            assert conf == 0.5


class TestDataQualityMonitor:
    def test_freshness_score_empty(self):
        from utils.data_quality import DataQualityMonitor
        with patch("utils.data_quality.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = []
            score = DataQualityMonitor.freshness_score()
            assert score == {}

    def test_stale_flag_empty(self):
        from utils.data_quality import DataQualityMonitor
        with patch.object(DataQualityMonitor, "freshness_score", return_value={}):
            stale = DataQualityMonitor.stale_flag()
            assert stale == []

    def test_psf_divergence_no_data(self):
        from utils.data_quality import DataQualityMonitor
        with patch("utils.data_quality.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = None
            flags = DataQualityMonitor.check_psf_divergence("Yelahanka")
            assert flags == []
