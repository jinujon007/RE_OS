"""GATE-57: Production Hardening — PSF unified + circuit breaker + seed staleness + shareholder round."""
import json
import pathlib
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestGate57PSFUnified:

    def test_v_market_brief_has_psf_source_columns(self):
        """Migration 0023 adds psf_source_tier and psf_source_label to v_market_brief."""
        content = pathlib.Path("alembic/versions/0023_unified_psf_view.py").read_text()
        assert "psf_source_tier" in content
        assert "psf_source_label" in content

    def test_psf_tier_coalesce_falls_through_when_no_data(self):
        """When no data in any source table, avg_listing_psf is NULL and tier is NULL."""
        from tests.test_psf_unified import _simulate_psf_tier
        psf, tier, label = _simulate_psf_tier(
            kaveri_count=0, gv_count=0, live_listing_count=0, all_listing_count=0)
        assert psf is None
        assert tier is None
        assert label is None


class TestGate57CircuitBreaker:

    def test_circuit_breaker_shows_open_state(self):
        """After 4 failures, get_circuit_states shows circuit_state='OPEN'."""
        from config.llm_router import _record_failure, get_circuit_states, _CIRCUIT_STATE
        _CIRCUIT_STATE.clear()
        for _ in range(4):
            _record_failure("groq")
        states = get_circuit_states()
        assert states["groq"]["circuit_state"] == "OPEN"

    def test_circuit_breaker_unaffected_providers_default_closed(self):
        """Providers without failures default to CLOSED."""
        from config.llm_router import get_circuit_states, _CIRCUIT_STATE
        _CIRCUIT_STATE.clear()
        states = get_circuit_states()
        for p in ["groq", "cerebras", "gemini", "nvidia", "sambanova", "openrouter", "cloudflare"]:
            assert p in states, f"Missing provider: {p}"
            assert states[p]["circuit_state"] == "CLOSED"

    def test_health_llm_endpoint_includes_circuit_info(self):
        """LLMHealthResponse model handles circuit_state correctly."""
        from dashboard.app_fastapi import LLMHealthResponse
        resp = LLMHealthResponse(
            configured=True,
            providers_available=["groq"],
            providers_failed=[],
            circuit_state={"groq": {"circuit_state": "OPEN", "failure_count": 4, "open_since": None}},
        )
        data = resp.model_dump()
        assert "circuit_state" in data
        assert data["circuit_state"]["groq"]["circuit_state"] == "OPEN"


class TestGate57SeedStaleness:

    def test_seed_staleness_check_removes_seeds_when_live_sufficient(self):
        """DataQualityMonitor.check_seed_staleness flags removal when live >=10."""
        from utils.data_quality import DataQualityMonitor
        with patch('utils.db.get_engine') as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = [
                ("Yelahanka", 15, None, 12),
            ]
            flags = DataQualityMonitor.check_seed_staleness(min_live_listings=10)
            assert len(flags) >= 1
            assert flags[0]["action"] == "remove_seed_and_use_live"

    def test_seed_staleness_noop_when_no_seeds_exist(self):
        """check_seed_staleness returns empty when no seed data exists."""
        from utils.data_quality import DataQualityMonitor
        with patch('utils.db.get_engine') as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = []
            flags = DataQualityMonitor.check_seed_staleness()
            assert len(flags) == 0


class TestGate57ShareholderRound:

    def test_shareholder_round_in_evaluate_response(self):
        """get_evaluate_job returns shareholder_round when present."""
        from crews.evaluate_pipeline import get_evaluate_job, EvaluateJob, _jobs
        _jobs.clear()
        from datetime import datetime, timezone
        job = EvaluateJob(
            job_id="gate57-test-job",
            status="complete",
            survey_no="45/2",
            market="Devanahalli",
            land_area_sqft=5200,
            sell_psf=6500,
            deal_type="compare",
            pitch="",
            created_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            shareholder_round=[
                {"name": "Market Scout", "verdict": "GO", "key_question": "?", "response": "ok"},
                {"name": "Risk Guardian", "verdict": "CONDITIONAL", "key_question": "?", "response": "ok"},
                {"name": "Legacy Builder", "verdict": "GO", "key_question": "?", "response": "ok"},
                {"name": "Financial Maximizer", "verdict": "NO-GO", "key_question": "?", "response": "ok"},
            ],
        )
        _jobs["gate57-test-job"] = job
        result = get_evaluate_job("gate57-test-job")
        assert result is not None
        assert "shareholder_round" in result
        assert len(result["shareholder_round"]) == 4

    def test_shareholder_round_field_in_response_even_when_none(self):
        """get_evaluate_job always includes shareholder_round key even when None."""
        from crews.evaluate_pipeline import get_evaluate_job, EvaluateJob, _jobs
        _jobs.clear()
        from datetime import datetime, timezone
        job = EvaluateJob(
            job_id="gate57-none-job",
            status="running",
            survey_no="45/2", market="Devanahalli",
            land_area_sqft=5200, sell_psf=6500,
            deal_type="compare", pitch="",
            created_at=datetime.now(timezone.utc).isoformat(),
            shareholder_round=None,
        )
        _jobs["gate57-none-job"] = job
        result = get_evaluate_job("gate57-none-job")
        assert result is not None
        assert "shareholder_round" in result
        assert result["shareholder_round"] is None

    def test_all_gate57_artifacts_exist(self):
        """All GATE-57 code artifacts are present on disk."""
        assert pathlib.Path("alembic/versions/0023_unified_psf_view.py").exists()
        assert pathlib.Path("tests/test_llm_circuit_breaker.py").exists()
        assert pathlib.Path("tests/test_seed_staleness.py").exists()
        assert pathlib.Path("tests/test_shareholder_round.py").exists()
        assert pathlib.Path("tests/test_locality_validation.py").exists()
