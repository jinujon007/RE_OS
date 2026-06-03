"""
RE_OS — IRR PSF Source Quality Tests (R1-01)
Unit tests for compute_psf_source_quality() function added in T-794.
"""
import pytest

pytestmark = pytest.mark.unit

from utils.irr_model import compute_psf_source_quality


class TestComputePsfSourceQuality:
    """Test compute_psf_source_quality() edge cases and all source types."""

    def test_live_igr_with_sufficient_records(self):
        """Returns 'live_igr' when source is igr_portal and count >= 5."""
        result = compute_psf_source_quality("igr_portal", 5)
        assert result == "live_igr"
        
        result = compute_psf_source_quality("igr_portal", 10)
        assert result == "live_igr"
        
        result = compute_psf_source_quality("igr_portal", 100)
        assert result == "live_igr"

    def test_fallback_igr_with_insufficient_records(self):
        """Returns 'fallback_igr' when source is igr_portal but count < 5."""
        result = compute_psf_source_quality("igr_portal", 4)
        assert result == "fallback_igr"
        
        result = compute_psf_source_quality("igr_portal", 1)
        assert result == "fallback_igr"
        
        result = compute_psf_source_quality("igr_portal", 0)
        assert result == "fallback_igr"

    def test_fallback_igr_with_insufficient_source_labels(self):
        """Returns 'fallback_igr' for insufficient data source labels."""
        result = compute_psf_source_quality("insufficient_igr_records", 0)
        assert result == "fallback_igr"
        
        result = compute_psf_source_quality("insufficient_records", 10)
        assert result == "fallback_igr"
        
        result = compute_psf_source_quality("sanity_rejected", 5)
        assert result == "fallback_igr"

    def test_listing_only_with_listing_source(self):
        """Returns 'listing_only' when using listing PSF."""
        result = compute_psf_source_quality("listing_psf", 0)
        assert result == "listing_only"
        
        result = compute_psf_source_quality("listing_psf", 10)
        assert result == "listing_only"

    def test_listing_only_with_no_data(self):
        """Returns 'listing_only' when no IGR data available."""
        result = compute_psf_source_quality("no_data", 0)
        assert result == "listing_only"
        
        result = compute_psf_source_quality("table_unavailable", 0)
        assert result == "listing_only"

    def test_listing_only_with_none_source(self):
        """Returns 'listing_only' when source is None."""
        result = compute_psf_source_quality(None, 0)
        assert result == "listing_only"
        
        result = compute_psf_source_quality(None, 10)
        assert result == "listing_only"

    def test_unknown_for_unexpected_source(self):
        """Returns 'unknown' for unrecognized source labels."""
        result = compute_psf_source_quality("unknown_source", 5)
        assert result == "unknown"
        
        result = compute_psf_source_quality("new_source_type", 10)
        assert result == "unknown"
        
        result = compute_psf_source_quality("", 5)
        assert result == "unknown"

    def test_negative_record_count(self):
        """Handles negative record counts gracefully."""
        result = compute_psf_source_quality("igr_portal", -1)
        assert result == "fallback_igr"  # -1 < 5, so fallback
        
        result = compute_psf_source_quality("listing_psf", -10)
        assert result == "listing_only"  # listing_psf regardless of count


class TestPsfSourceQualityIntegration:
    """Integration tests for psf_source_quality field in IRR calculations."""

    def test_compare_scenarios_sets_psf_source_quality_live(self):
        """compare_scenarios() sets psf_source_quality='live_igr' when provided."""
        from utils.irr_model import compare_scenarios
        
        result = compare_scenarios(
            land_cost=10_000_000,
            sellable_area_sqft=10_000,
            base_psf=6000,
            igr_source="igr_portal",
            igr_record_count=10,
        )
        
        assert result.base.psf_source_quality == "live_igr"
        assert result.bull.psf_source_quality == "live_igr"
        assert result.bear.psf_source_quality == "live_igr"

    def test_compare_scenarios_sets_psf_source_quality_fallback(self):
        """compare_scenarios() sets psf_source_quality='fallback_igr' when insufficient."""
        from utils.irr_model import compare_scenarios
        
        result = compare_scenarios(
            land_cost=10_000_000,
            sellable_area_sqft=10_000,
            base_psf=6000,
            igr_source="insufficient_igr_records",
            igr_record_count=2,
        )
        
        assert result.base.psf_source_quality == "fallback_igr"
        assert result.bull.psf_source_quality == "fallback_igr"
        assert result.bear.psf_source_quality == "fallback_igr"

    def test_compare_scenarios_sets_psf_source_quality_listing(self):
        """compare_scenarios() sets psf_source_quality='listing_only' when no IGR."""
        from utils.irr_model import compare_scenarios
        
        result = compare_scenarios(
            land_cost=10_000_000,
            sellable_area_sqft=10_000,
            base_psf=6000,
            igr_source=None,
            igr_record_count=0,
        )
        
        assert result.base.psf_source_quality == "listing_only"
        assert result.bull.psf_source_quality == "listing_only"
        assert result.bear.psf_source_quality == "listing_only"

    def test_compare_scenarios_defaults_to_unknown_without_params(self):
        """compare_scenarios() defaults to 'unknown' when IGR params not provided."""
        from utils.irr_model import compare_scenarios
        
        result = compare_scenarios(
            land_cost=10_000_000,
            sellable_area_sqft=10_000,
            base_psf=6000,
        )
        
        # When no igr_source/igr_record_count provided, defaults to None/0 → listing_only
        assert result.base.psf_source_quality == "listing_only"
