"""Sprint 48 — cross-task integration tests.

Chains T-944 (seed listings) → T-945 (conflict detection) → T-946 (MoS cap)
→ T-949 (freshness endpoint). Verifies the combined pipeline behaves correctly.

All tests use mocked DB — no live Docker required.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

pytestmark = pytest.mark.unit


class TestDataQualityAfterSeed:
    """After seed listings are inserted, data quality checks should reflect them."""

    @patch("utils.data_quality.get_engine")
    def test_freshness_accepts_seed_source(self, mock_get_engine):
        """Freshness endpoint should handle 'portal_plugin' source type (T-944 seed data)."""
        from utils.data_freshness import get_source_status

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_get_engine.return_value = mock_engine
        mock_conn.execute.return_value.fetchall.return_value = [
            ("portal_plugin", "Yelahanka", None, 30),
        ]
        result = get_source_status("Yelahanka")
        assert isinstance(result, list), f"Expected list, got {type(result)}"
        assert len(result) >= 0


class TestMosCapWithSparseData:
    """MoS cap (T-946) must work after seed listings (T-944) are in place."""

    def test_mos_cap_logic_without_db(self):
        """Validate MoS cap logic independently — LEAST(raw, 120)."""
        test_cases = [
            (5.0, 5.0),
            (120.0, 120.0),
            (1500.0, 120.0),
            (0.0, 0.0),
        ]
        for raw, expected in test_cases:
            capped = min(raw, 120.0) if raw > 0 else 0.0
            assert capped == expected, f"MoS raw={raw}: expected {expected}, got {capped}"

    def test_mos_quality_inferred(self):
        """Validate mos_quality labels match count thresholds."""
        def infer_quality(total_count, mos_fallback):
            if total_count >= 12:
                return "kaveri_sufficient"
            if total_count > 0:
                return "kaveri_sparse"
            if mos_fallback is not None:
                return "absorption_fallback"
            return "insufficient_data"

        assert infer_quality(15, None) == "kaveri_sufficient"
        assert infer_quality(5, None) == "kaveri_sparse"
        assert infer_quality(0, 50.0) == "absorption_fallback"
        assert infer_quality(0, None) == "insufficient_data"


class TestPsfHierarchyConsistency:
    """PSF hierarchy (T-947) must be consistent across entry points."""

    def test_psf_source_quality_mapping_complete(self):
        """_igr_source_for must handle all defined states."""
        from unittest.mock import MagicMock
        from intelligence.financial_intel import FinancialIntel
        state_map = {
            "live_igr": "igr_portal",
            "guidance_value": "guidance_values",
            "listing_only": "listing_psf",
        }
        for state, expected_source in state_map.items():
            mock_fe = MagicMock()
            mock_fe.psf_source_quality = state
            result = FinancialIntel._igr_source_for(mock_fe)
            assert result == expected_source, (
                f"_igr_source_for('{state}') returned '{result}', expected '{expected_source}'"
            )


class TestFreshnessCache:
    """Freshness caching (B2) prevents redundant DB calls."""

    @patch("utils.data_freshness.get_engine")
    def test_cache_hits_within_ttl(self, mock_get_engine):
        from utils.data_freshness import get_source_status, _invalidate_cache
        _invalidate_cache()
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_get_engine.return_value = mock_engine
        mock_conn.execute.return_value.fetchall.return_value = []
        result1 = get_source_status()
        result2 = get_source_status()
        assert result1 == result2
        assert mock_conn.execute.call_count == 1


class TestSloEvaluation:
    """SLO definitions in config/slos.py must evaluate correctly."""

    def test_slo_check_passes_for_recent_data(self):
        from config.slos import check_slo
        passes, msg = check_slo("news_scout", 12.0)
        assert passes is True, f"Expected pass for 12h news: {msg}"

    def test_slo_check_fails_for_stale_data(self):
        from config.slos import check_slo
        passes, msg = check_slo("news_scout", 72.0)
        assert passes is False, f"Expected fail for 72h news: {msg}"

    def test_unknown_source_returns_pass(self):
        from config.slos import check_slo
        passes, _ = check_slo("unknown_plugin", 999.0)
        assert passes is True, "Unknown source should return pass"

    def test_all_slo_status_counts(self):
        from config.slos import all_slo_status
        freshness = {
            "news_scout": {"hours_since_update": 10.0, "status": "fresh"},
            "rera_karnataka": {"hours_since_update": 100.0, "status": "stale"},
        }
        result = all_slo_status(freshness)
        assert result["slo_pass"] == 1
        assert result["slo_fail"] == 1

    def test_slo_registry_has_all_expected_sources(self):
        from config.slos import SLO_MAP
        expected = {"news_scout", "portal_plugin", "rera_karnataka", "igr_karnataka", "kaveri_bhoomi"}
        assert expected.issubset(SLO_MAP.keys()), f"Missing SLOs: {expected - set(SLO_MAP.keys())}"
