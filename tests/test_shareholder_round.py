"""T-955: Shareholder round integration tests."""
import json
import pytest
from unittest.mock import patch, MagicMock, ANY
pytestmark = pytest.mark.unit


def _make_mock_pkg(market="Yelahanka", survey_no="45/2", deal_type="compare"):
    pkg = MagicMock()
    pkg.market = market
    pkg.survey_no = survey_no
    pkg.deal_type = deal_type
    pkg.all_modules_success = True
    pkg.module_status = {}
    pkg.financial_evaluation = MagicMock()
    pkg.financial_evaluation.psf_source_quality = "guidance_value"
    pkg.financial_evaluation.sell_psf = 6500.0
    pkg.land_picture = MagicMock()
    pkg.land_picture.land_area_acres = 5.0
    return pkg


def _make_mock_spec(name="Test Shareholder"):
    spec = {
        "name": name,
        "role": "Test Investor",
        "investment_thesis": "Growth",
        "signature_question": "Is this good?",
    }
    return spec


class TestShareholderRound:

    def test_shareholder_round_has_4_entries(self):
        from crews.evaluate_pipeline import run_shareholder_round
        with patch('agents.shareholder_agent.build_all_shareholders') as mock_build:
            mock_build.return_value = [
                (_make_mock_spec("Market Scout"), MagicMock()),
                (_make_mock_spec("Risk Guardian"), MagicMock()),
                (_make_mock_spec("Legacy Builder"), MagicMock()),
                (_make_mock_spec("Financial Maximizer"), MagicMock()),
            ]
            pkg = _make_mock_pkg()
            results = run_shareholder_round(pkg)
            assert len(results) == 4
            assert all(r["name"] != "No Shareholders" for r in results)

    def test_shareholder_verdicts_are_valid(self):
        from crews.evaluate_pipeline import run_shareholder_round
        with patch('agents.shareholder_agent.build_all_shareholders') as mock_build:
            mock_agent = MagicMock()
            mock_agent.execute.return_value = json.dumps({
                "verdict": "GO",
                "key_question": "What is the exit strategy?",
                "response": "Strong market fundamentals.",
            })
            mock_build.return_value = [
                (_make_mock_spec("Market Scout"), mock_agent),
            ]
            pkg = _make_mock_pkg()
            results = run_shareholder_round(pkg)
            assert len(results) == 1
            assert results[0]["verdict"] in ("GO", "NO-GO", "CONDITIONAL", "ABSTAIN")
            assert results[0]["key_question"] == "What is the exit strategy?"

    def test_shareholder_timeout_returns_abstain(self):
        from crews.evaluate_pipeline import run_shareholder_round
        with patch('agents.shareholder_agent.build_all_shareholders') as mock_build:
            mock_agent = MagicMock()
            mock_agent.execute.side_effect = TimeoutError("call timed out")
            mock_build.return_value = [
                (_make_mock_spec("Risk Guardian"), mock_agent),
            ]
            pkg = _make_mock_pkg()
            results = run_shareholder_round(pkg)
            assert len(results) == 1
            assert results[0]["verdict"] == "ABSTAIN"
            assert "timeout" in results[0]["error"].lower()

    def test_evaluate_response_includes_shareholder_round(self):
        from crews.evaluate_pipeline import get_evaluate_job, _jobs
        _jobs.clear()
        from crews.evaluate_pipeline import EvaluateJob
        from datetime import datetime, timezone
        job = EvaluateJob(
            job_id="test-job-1", status="complete",
            survey_no="45/2", market="Devanahalli",
            land_area_sqft=5200, sell_psf=6500,
            deal_type="compare", pitch="",
            created_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            shareholder_round=[{"name": "Test", "verdict": "GO", "key_question": "?", "response": "ok"}],
        )
        _jobs["test-job-1"] = job
        result = get_evaluate_job("test-job-1")
        assert result is not None
        assert "shareholder_round" in result
        assert len(result["shareholder_round"]) == 1

    def test_evaluate_empty_shareholders_returns_abstain(self):
        from crews.evaluate_pipeline import run_shareholder_round
        with patch('agents.shareholder_agent.build_all_shareholders') as mock_build:
            mock_build.return_value = []
            pkg = _make_mock_pkg()
            results = run_shareholder_round(pkg)
            assert len(results) == 1
            assert results[0]["verdict"] == "ABSTAIN"
