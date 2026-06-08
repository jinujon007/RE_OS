"""Tests for ShareholderBoardCrew — quarterly board review."""
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from crews.shareholder_review import (
    ShareholderBoardCrew,
    _build_quarterly_prompt,
    _make_llm_call,
    _needs_debate,
    _parse_json_response,
    _fallback_ceo_synthesis,
)


class TestHelpers:
    def test_parse_json_response_extracts_json(self):
        text = 'Some text {"verdict": "GO_ON_PLAN", "top_concern": "All good"} trailing'
        parsed = _parse_json_response(text)
        assert parsed.get("verdict") == "GO_ON_PLAN"
        assert parsed.get("top_concern") == "All good"

    def test_parse_json_empty_returns_empty(self):
        assert _parse_json_response("") == {}
        assert _parse_json_response(None) == {}

    def test_needs_debate_true_when_2_concerning(self):
        responses = [
            {"verdict": "GO_ON_PLAN"},
            {"verdict": "NEEDS_CORRECTION"},
            {"verdict": "UNDERPERFORMING"},
            {"verdict": "GO_ON_PLAN"},
        ]
        assert _needs_debate(responses) is True

    def test_needs_debate_false_when_1_concerning(self):
        responses = [
            {"verdict": "GO_ON_PLAN"},
            {"verdict": "NEEDS_CORRECTION"},
            {"verdict": "GO_ON_PLAN"},
            {"verdict": "GO_ON_PLAN"},
        ]
        assert _needs_debate(responses) is False

    def test_needs_debate_false_when_none_concerning(self):
        responses = [
            {"verdict": "GO_ON_PLAN"},
            {"verdict": "GO_ON_PLAN"},
            {"verdict": "GO_ON_PLAN"},
            {"verdict": "ABSTAIN"},
        ]
        assert _needs_debate(responses) is False

    def test_build_quarterly_prompt_contains_role(self):
        spec = {"name": "Test", "role": "Risk Guardian", "persona": "Risk-focused",
                "investment_thesis": "Safety first"}
        prompt = _build_quarterly_prompt(spec, "Q2-2026", "Good quarter", 1)
        assert "Test" in prompt
        assert "Q2-2026" in prompt
        assert "Good quarter" in prompt

    def test_fallback_ceo_synthesis_has_all_fields(self):
        responses = [
            {"name": "A", "verdict": "GO_ON_PLAN", "top_concern": "Growth good"},
            {"name": "B", "verdict": "NEEDS_CORRECTION", "top_concern": "Risk rising"},
            {"name": "C", "verdict": "GO_ON_PLAN", "top_concern": "Cash ok"},
            {"name": "D", "verdict": "ABSTAIN", "top_concern": ""},
        ]
        synth = _fallback_ceo_synthesis("Q2-2026", responses, False)
        assert "quarter_verdict" in synth
        assert "key_theme" in synth
        assert "strategic_direction" in synth
        assert "ceo_letter_text" in synth
        assert len(synth["ceo_letter_text"]) > 100

    def test_fallback_debate_mention(self):
        responses = [{"name": "A", "verdict": "NEEDS_CORRECTION", "top_concern": "Risk"}]
        synth = _fallback_ceo_synthesis("Q2-2026", responses, True)
        assert "debate" in synth["ceo_letter_text"].lower()

    def test_make_llm_call_when_agent_unavailable(self):
        with patch("crews.shareholder_review.create_shareholder_agent", None):
            result = _make_llm_call({"name": "A"}, "prompt")
            assert result["verdict"] == "ABSTAIN"


class TestMakeLLMCall:
    @patch("crews.shareholder_review.create_shareholder_agent")
    def test_make_llm_call_returns_verdict(self, mock_create):
        mock_agent = MagicMock()
        mock_agent.execute.return_value = '{"verdict": "GO_ON_PLAN", "top_concern": "All good"}'
        mock_create.return_value = mock_agent
        spec = {"name": "Arjun", "role": "Market Scout", "persona": "", "investment_thesis": ""}
        result = _make_llm_call(spec, "Test prompt")
        assert result["verdict"] == "GO_ON_PLAN"
        assert result["name"] == "Arjun"

    @patch("crews.shareholder_review.create_shareholder_agent",
           side_effect=Exception("LLM down"))
    def test_llm_failure_returns_abstain(self, mock_create):
        spec = {"name": "Arjun", "role": "", "persona": "", "investment_thesis": ""}
        result = _make_llm_call(spec, "Test prompt")
        assert result["verdict"] == "ABSTAIN"
        assert "Error" in result["top_concern"]


class TestShareholderBoardCrew:
    @patch("crews.shareholder_review.PerformanceDigest.build")
    @patch("crews.shareholder_review.DecisionAuditor.audit_quarter")
    @patch("crews.shareholder_review.load_shareholder_specs")
    @patch("crews.shareholder_review._save_session")
    @patch("crews.shareholder_review.get_engine")
    def test_quarterly_review_returns_dict(self, mock_eng, mock_save,
                                            mock_specs, mock_audit, mock_digest):
        mock_digest.return_value = {
            "deal_metrics": {"deal_count": 5, "avg_irr_pct": 12.5},
            "new_projects": [{"market": "Yelahanka", "project_count": 3}],
            "absorption_trend": {"snapshot_count": 2, "avg_absorption_pct": 45.0},
            "token_efficiency": {"total_token_usage_records": 50, "over_budget_count": 3},
        }
        mock_audit.return_value = []
        mock_specs.return_value = []
        mock_save.return_value = "mock-session-id"
        result = ShareholderBoardCrew.run_quarterly_review("Q2-2026")
        assert isinstance(result, dict)
        assert "quarter" in result
        assert "shareholder_responses" in result
        assert "ceo_letter_text" in result

    def test_all_4_fallback_shareholders_respond(self):
        from crews.shareholder_review import _fallback_responses
        responses = _fallback_responses()
        assert len(responses) == 4
        for r in responses:
            assert r.get("name")
            assert r.get("verdict") in ("GO_ON_PLAN", "NEEDS_CORRECTION",
                                         "UNDERPERFORMING", "ABSTAIN")

    def test_debate_triggered_on_opposing_verdicts(self):
        responses = [
            {"verdict": "GO_ON_PLAN"},
            {"verdict": "NEEDS_CORRECTION"},
            {"verdict": "GO_ON_PLAN"},
            {"verdict": "UNDERPERFORMING"},
        ]
        assert _needs_debate(responses) is True

    @patch("crews.shareholder_review.PerformanceDigest.build")
    @patch("crews.shareholder_review.DecisionAuditor.audit_quarter")
    @patch("crews.shareholder_review.load_shareholder_specs")
    @patch("crews.shareholder_review._save_session")
    @patch("crews.shareholder_review.get_engine")
    def test_ceo_synthesis_non_empty(self, mock_eng, mock_save,
                                      mock_specs, mock_audit, mock_digest):
        mock_digest.return_value = {
            "deal_metrics": {"deal_count": 0, "avg_irr_pct": None},
            "new_projects": [],
            "absorption_trend": {},
            "token_efficiency": {},
        }
        mock_audit.return_value = []
        mock_specs.return_value = []
        mock_save.return_value = "id"
        result = ShareholderBoardCrew.run_quarterly_review("Q1-2026")
        assert len(result["ceo_letter_text"]) > 50
        assert result["quarter_verdict"] in ("GO_ON_PLAN", "NEEDS_CORRECTION",
                                               "UNDERPERFORMING")

    def test_save_letter_creates_file(self, tmp_path):
        with patch("crews.shareholder_review.get_engine") as mock_eng:
            with patch("pathlib.Path.write_text") as mock_write, \
                 patch("pathlib.Path.mkdir") as mock_mkdir:
                file_path = ShareholderBoardCrew.save_letter("test-id", "CEO Letter Text", "Q2-2026")
                assert file_path is not None
                assert "CEO_Letter" in str(file_path)
