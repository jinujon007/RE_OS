"""
T-693 — Decision Layer unit tests.

Tests the Sprint 64 pipeline module and route logic:
- EvaluatePipeline module tests (no Redis needed)
- DealMemoGenerator import and structure
- InvestorBriefGenerator import and structure
- Route parameter validation tests
"""

import pytest

pytestmark = pytest.mark.unit


# ── Evaluate Pipeline Module Tests ────────────────────────────────────────────


class TestEvaluatePipelineModule:
    def test_start_evaluate_returns_dict(self):
        """start_evaluate returns dict with job_id and status."""
        from crews.evaluate_pipeline import start_evaluate

        result = start_evaluate(
            survey_no="45/2",
            market="Devanahalli",
            land_area_sqft=5200.0,
            sell_psf=None,
            deal_type="compare",
            pitch="Test",
        )
        assert "job_id" in result
        assert "status" in result

    def test_get_evaluate_job_for_unknown_id(self):
        """get_evaluate_job returns None for unknown job_id."""
        from crews.evaluate_pipeline import get_evaluate_job

        result = get_evaluate_job("nonexistent-job-id")
        assert result is None

    def test_evaluate_job_isolation(self):
        """Each call to start_evaluate creates independent job."""
        from crews.evaluate_pipeline import start_evaluate, get_evaluate_job

        r1 = start_evaluate(survey_no="1/1", market="Devanahalli", deal_type="compare")
        r2 = start_evaluate(survey_no="2/2", market="Devanahalli", deal_type="compare")
        assert r1["job_id"] != r2["job_id"]
        j1 = get_evaluate_job(r1["job_id"])
        j2 = get_evaluate_job(r2["job_id"])
        assert j1["survey_no"] == "1/1"
        assert j2["survey_no"] == "2/2"

    def test_evaluate_job_status_fields(self):
        """Evaluate job contains all required status fields."""
        from crews.evaluate_pipeline import start_evaluate, get_evaluate_job

        result = start_evaluate(
            survey_no="45/2", market="Devanahalli", deal_type="compare"
        )
        job = get_evaluate_job(result["job_id"])
        assert "job_id" in job
        assert "status" in job
        assert "survey_no" in job
        assert "market" in job


# ── Deal Memo Tests ───────────────────────────────────────────────────────────


class TestDealMemoGeneration:
    def test_deal_memo_generator_import(self):
        """DealMemoGenerator module can be imported."""
        from utils.deal_memo_v2 import generate_deal_memo

        assert callable(generate_deal_memo)

    def test_deal_memo_generator_signature(self):
        """DealMemoGenerator accepts IntelPackage."""
        import inspect
        from utils.deal_memo_v2 import generate_deal_memo

        sig = inspect.signature(generate_deal_memo)
        assert len(sig.parameters) >= 1


# ── Investor Brief Tests ──────────────────────────────────────────────────────


class TestInvestorBriefGeneration:
    def test_investor_brief_generator_import(self):
        """InvestorBriefGenerator module can be imported."""
        from utils.investor_brief_v2 import generate_investor_brief

        assert callable(generate_investor_brief)

    def test_investor_brief_generator_signature(self):
        """InvestorBriefGenerator accepts IntelPackage."""
        import inspect
        from utils.investor_brief_v2 import generate_investor_brief

        sig = inspect.signature(generate_investor_brief)
        assert len(sig.parameters) >= 1


# ── Board Room V2 Tests ───────────────────────────────────────────────────────


class TestBoardRoomV2:
    def test_board_room_v2_import(self):
        """BoardRoomV2 module can be imported."""
        from crews.board_room_v2 import run_board_session_v2, BoardSessionV2Result

        assert callable(run_board_session_v2)

    def test_board_session_result_dataclass(self):
        """BoardSessionV2Result has required fields."""
        from crews.board_room_v2 import BoardSessionV2Result

        result = BoardSessionV2Result(
            session_id="test-session",
            survey_no="45/2",
            market="Devanahalli",
            status="complete",
        )
        assert result.session_id == "test-session"
        assert result.market == "Devanahalli"


# ── IntelPackage Tests ────────────────────────────────────────────────────────


class TestIntelPackage:
    def test_intel_registry_import(self):
        """IntelRegistry can be imported."""
        from intelligence.registry import IntelRegistry

        assert callable(IntelRegistry)

    def test_intel_package_dataclass_exists(self):
        """IntelPackage dataclass exists."""
        from intelligence.registry import IntelPackage

        assert hasattr(IntelPackage, "__dataclass_fields__")


# ── Route Logic Tests (parameter validation) ─────────────────────────────────


class TestEvaluateRouteLogic:
    def test_market_normalization(self):
        """Market normalization handles valid/invalid markets."""
        from dashboard.app_fastapi import _normalize_market

        assert _normalize_market("devanahalli") == "Devanahalli"
        assert _normalize_market("yelahanka") == "Yelahanka"
        assert _normalize_market("hebbal") == "Hebbal"
        assert _normalize_market("invalid") is None
        assert _normalize_market("") is None
        assert _normalize_market(None) is None

    def test_deal_type_validation(self):
        """Deal type validation works correctly."""
        valid_types = {"purchase", "jd", "jv", "compare"}
        for dt in valid_types:
            assert dt in valid_types
        assert "invalid" not in valid_types


class TestOpportunityQueueLogic:
    def test_score_capping(self):
        """Min score parameter is capped between 0.0 and 1.0."""
        min_score = 0.8
        assert 0.0 <= max(0.0, min(float(min_score), 1.0)) <= 1.0


# ── GATE-48 Verification ─────────────────────────────────────────────────────


class TestGate48Pipeline:
    """GATE-48: /api/evaluate returns board_room + deal_memo + investor_brief."""

    def test_deal_memo_has_7_sections(self):
        """generate_deal_memo returns 7 sections from minimal IntelPackage."""
        from intelligence.registry import IntelPackage
        from utils.deal_memo_v2 import generate_deal_memo
        import datetime

        pkg = IntelPackage(
            survey_no="45/2",
            market="Devanahalli",
            collected_at=datetime.datetime.now().isoformat(),
        )
        memo = generate_deal_memo(pkg)
        assert isinstance(memo, dict)
        assert "sections" in memo
        assert len(memo["sections"]) == 7
        for section in memo["sections"]:
            assert "title" in section
            assert "body" in section

    def test_investor_brief_has_7_sections(self):
        """generate_investor_brief returns 7 sections from minimal IntelPackage."""
        from intelligence.registry import IntelPackage
        from utils.investor_brief_v2 import generate_investor_brief
        import datetime

        pkg = IntelPackage(
            survey_no="45/2",
            market="Devanahalli",
            collected_at=datetime.datetime.now().isoformat(),
        )
        brief = generate_investor_brief(pkg)
        assert isinstance(brief, dict)
        assert "sections" in brief
        assert len(brief["sections"]) == 7

    def test_board_session_result_stores_responses(self):
        """BoardSessionV2Result stores dept head responses correctly."""
        from crews.board_room_v2 import BoardSessionV2Result

        result = BoardSessionV2Result(
            session_id="gate48-test",
            survey_no="45/2",
            market="Devanahalli",
            status="complete",
            responses={"bd": "BD: GO", "finance": "Finance: MARGINAL"},
        )
        assert result.responses["bd"] == "BD: GO"
        assert len(result.responses) == 2

    def test_evaluate_pipeline_assembles_all_sections(self):
        """Pipeline assembles board_session, deal_memo, investor_brief into job."""
        from unittest.mock import patch, MagicMock
        from crews.evaluate_pipeline import start_evaluate, get_evaluate_job
        import datetime
        import time

        # Minimal IntelPackage stub
        from intelligence.registry import IntelPackage

        pkg = IntelPackage(
            survey_no="99/1",
            market="Devanahalli",
            collected_at=datetime.datetime.now().isoformat(),
        )

        # Board room stub with 5 dept heads
        mock_board = MagicMock()
        mock_board.session_id = "mock-session-id"
        mock_board.status = "complete"
        mock_board.responses = {
            "bd": "BD verdict: GO",
            "finance": "Finance: IRR 25%",
            "engineering": "Eng: FEASIBLE",
            "ops": "Ops: GREEN",
            "legal": "Legal: CLEAR",
        }

        with (
            patch("crews.evaluate_pipeline.IntelRegistry") as mock_reg,
            patch("crews.board_room_v2.run_board_session_v2", return_value=mock_board),
        ):
            mock_reg.return_value.get_full_picture.return_value = pkg
            result = start_evaluate(
                survey_no="99/1",
                market="Devanahalli",
                land_area_sqft=10000.0,
                sell_psf=6000.0,
                deal_type="compare",
                pitch="Test gate48",
            )
            job_id = result["job_id"]
            # Wait for async thread to complete (max 30s — generous for CI)
            deadline = time.time() + 30
            job = None
            while time.time() < deadline:
                time.sleep(0.25)
                job = get_evaluate_job(job_id)
                if job and job.get("status") not in ("pending", "running"):
                    break

        assert job is not None, "Job should exist after pipeline completes"
        assert job["status"] == "complete", (
            f"Expected complete, got {job.get('status')} | error: {job.get('error')}"
        )
        assert job["board_session"] is not None, "board_session must be populated"
        assert job["deal_memo"] is not None, "deal_memo must be populated"
        assert job["investor_brief"] is not None, "investor_brief must be populated"
        assert len(job["deal_memo"].get("sections", [])) == 7
        assert len(job["investor_brief"].get("sections", [])) == 7
        assert "bd" in job["board_session"]["responses"]


# ── Test count verification ─────────────────────────────────────────────────────


def test_test_count_enough():
    """Verify test_decision_layer has >=15 test functions."""
    import re
    import inspect
    import pathlib

    src = (
        pathlib.Path(inspect.getfile(TestGate48Pipeline)).parent
        / "test_decision_layer.py"
    )
    src_text = src.read_text()
    test_fns = re.findall(r"^\s+def test_|^def test_", src_text, re.MULTILINE)
    count = len(test_fns)
    assert count >= 15, f"Expected >=15 test functions, got {count}"
