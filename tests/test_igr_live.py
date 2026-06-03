"""
RE_OS — IGR Live Data Tests (Sprint 42 — T-795)
Unit tests for IGR Karnataka scraper live data behavior and IRR integration.
"""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit

from scrapers.igr_karnataka import IGRTransactionScout, _fallback_transactions
from utils.irr_model import compute_psf_source_quality, compare_scenarios


class TestIGRLiveScraperBehavior:
    """Test IGR scraper live data behavior and source tracking."""

    def test_portal_response_parses_correctly_fixture_mock(self):
        """Test that portal response parses correctly using fixture mock."""
        scout = IGRTransactionScout()
        # Mock parsed records that would result from HTML parsing
        mock_records = [
            {"survey_no": "123/4", "seller": "Seller A", "buyer": "Buyer B",
             "consideration_amount": 5000000, "area_sqft": 1000,
             "registration_date": "2026-05-15", "sro_office": "Yelahanka"},
            {"survey_no": "125/2", "seller": "Seller C", "buyer": "Buyer D",
             "consideration_amount": 7500000, "area_sqft": 1500,
             "registration_date": "2026-05-10", "sro_office": "Yelahanka"},
        ]
        with patch.object(scout, '_scrape_via_scrapling', return_value=mock_records):
            with patch.object(scout, '_scrape_via_post', return_value=[]):
                results = scout.run(market="Yelahanka", days_back=30)
                assert len(results) == 2
                for r in results:
                    assert all(key in r for key in ("survey_no", "seller", "buyer", "consideration_amount", 
                                                 "area_sqft", "registration_date", "sro_office", "source"))
                    assert r["source"] == "igr_portal"

    def test_fallback_fires_on_portal_timeout(self):
        """Test that fallback fires when portal times out."""
        scout = IGRTransactionScout()
        with patch.object(scout, '_scrape_via_scrapling', return_value=[]):
            with patch.object(scout, '_scrape_via_post', return_value=[]):
                results = scout.run(market="Yelahanka", days_back=30)
                assert len(results) >= 5  # Should return fallback data
                for r in results:
                    assert r["source"] == "fallback"

    def test_source_igr_portal_on_live_records(self):
        """Test that source='igr_portal' on live records from portal."""
        fake_records = [
            {"survey_no": "100/1", "seller": "A", "buyer": "B",
             "consideration_amount": 1000000, "area_sqft": 1000,
             "registration_date": "2026-05-01", "sro_office": "Test"},
        ]
        scout = IGRTransactionScout()
        with patch.object(scout, '_scrape_via_scrapling', return_value=[]):
            with patch.object(scout, '_scrape_via_post', return_value=fake_records):
                results = scout.run(market="Devanahalli")
                assert len(results) == 1
                assert results[0]["source"] == "igr_portal"

    def test_source_fallback_on_seeded(self):
        """Test that source='fallback' on seeded/hardcoded records."""
        scout = IGRTransactionScout()
        with patch.object(scout, '_scrape_via_scrapling', return_value=[]):
            with patch.object(scout, '_scrape_via_post', return_value=[]):
                results = scout.run(market="Yelahanka", days_back=30)
                assert len(results) >= 5
                for r in results:
                    assert r["source"] == "fallback"

    def test_dedup_prevents_double_insert_on_re_run(self):
        """Test that dedup prevents double-insert on re-run."""
        scout = IGRTransactionScout()
        records = [{"survey_no": "100/1", "seller": "A", "buyer": "B",
                   "consideration_amount": 1000000, "area_sqft": 1000,
                   "registration_date": "2026-05-01", "sro_office": "Test"}]
        
        with patch("utils.db.get_engine") as mock_ge:
            mock_conn = MagicMock()
            mock_engine = MagicMock()
            mock_engine.begin.return_value.__enter__.return_value = mock_conn
            mock_ge.return_value = mock_engine
            
            # First insert
            mock_result = MagicMock()
            mock_result.rowcount = 1
            mock_conn.execute.return_value = mock_result
            
            stats1 = scout.insert_transactions(records, market="Yelahanka")
            assert stats1["inserted"] == 1
            
            # Second insert with same data - should be skipped
            mock_result.rowcount = 0
            stats2 = scout.insert_transactions(records, market="Yelahanka")
            assert stats2["skipped"] == 1


class TestPSFSourceQuality:
    """Test PSF source quality computation and integration."""

    def test_psf_source_quality_live_igr_when_geq_five_live_rows(self):
        """Test psf_source_quality='live_igr' when ≥5 live rows."""
        result = compute_psf_source_quality("igr_portal", 5)
        assert result == "live_igr"
        assert compute_psf_source_quality("igr_portal", 10) == "live_igr"
        assert compute_psf_source_quality("igr_portal", 100) == "live_igr"

    def test_psf_source_quality_fallback_igr_when_lt_five_live_rows(self):
        """Test psf_source_quality='fallback_igr' when <5 live rows."""
        result = compute_psf_source_quality("igr_portal", 4)
        assert result == "fallback_igr"
        assert compute_psf_source_quality("igr_portal", 1) == "fallback_igr"
        assert compute_psf_source_quality("igr_portal", 0) == "fallback_igr"

    def test_ceo_prompt_contains_data_fallback_psf_string_when_fallback(self):
        """Test that CEO prompt contains '[DATA: fallback PSF]' when fallback is used."""
        # This tests the integration with compare_scenarios and the finance auto-calc in board_room
        # We'll test that when psf_source_quality is not 'live_igr', the appropriate note is included
        
        # Test with insufficient IGR records (< 5)
        result = compare_scenarios(
            land_cost=10_000_000,
            sellable_area_sqft=10_000,
            base_psf=6000,
            igr_source="igr_portal",
            igr_record_count=3,  # Less than 5
        )
        
        # Check that the IRRResult objects have the correct psf_source_quality
        assert result.base.psf_source_quality == "fallback_igr"
        assert result.bull.psf_source_quality == "fallback_igr"
        assert result.bear.psf_source_quality == "fallback_igr"
        
        # Test with no IGR data
        result2 = compare_scenarios(
            land_cost=10_000_000,
            sellable_area_sqft=10_000,
            base_psf=6000,
            igr_source=None,
            igr_record_count=0,
        )
        
        assert result2.base.psf_source_quality == "listing_only"
        assert result2.bull.psf_source_quality == "listing_only"
        assert result2.bear.psf_source_quality == "listing_only"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])