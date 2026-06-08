"""Unit tests for FSI Calculator v2 — AIZ height caps + parking deduction (T-987)."""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestFSIWithAIZ:
    def test_aiz_caps_height_when_zone_exists(self):
        from utils.fsi_calculator import calculate_fsi
        result = calculate_fsi(43560, zone="R2", market="Devanahalli",
                               _aiz_override=(45.0, "BIAL approach funnel"))
        assert result.aiz_height_limit_m == 45.0
        assert result.aiz_note == "BIAL approach funnel"
        assert result.max_floors >= 1

    def test_aiz_no_cap_when_no_zone_row(self):
        from utils.fsi_calculator import calculate_fsi
        result = calculate_fsi(43560, zone="R2", market="Yelahanka",
                               _aiz_override=(None, None))
        assert result.aiz_height_limit_m is None
        assert result.aiz_note is None

    def test_aiz_no_override_uses_db_lookup(self):
        with patch("utils.fsi_calculator._lookup_aiz_height", return_value=(45.0, "BIAL funnel")):
            from utils.fsi_calculator import calculate_fsi
            result = calculate_fsi(43560, zone="R2", market="Devanahalli")
            assert result.aiz_height_limit_m == 45.0

    def test_aiz_db_error_returns_none(self):
        with patch("utils.fsi_calculator._lookup_aiz_height", return_value=(None, None)):
            from utils.fsi_calculator import calculate_fsi
            result = calculate_fsi(43560, zone="R1", market="Yelahanka")
            assert result.aiz_height_limit_m is None

    def test_parking_deducted_from_sellable(self):
        from utils.fsi_calculator import TypologyRecommender
        rec = TypologyRecommender(total_units=100, avg_listing_psf=7000, efficiency=0.65)
        result = rec.recommend()
        assert result.parking_area_sqft > 0
        assert result.actual_sellable_sqft < result.gross_sellable_sqft
        assert result.gdv_cr > 0

    def test_parking_proportional_to_units(self):
        from utils.fsi_calculator import TypologyRecommender
        r1 = TypologyRecommender(total_units=50, avg_listing_psf=7000).recommend()
        r2 = TypologyRecommender(total_units=100, avg_listing_psf=7000).recommend()
        assert r2.parking_area_sqft == 2 * r1.parking_area_sqft

    def test_typology_reject_zero_units(self):
        from utils.fsi_calculator import TypologyRecommender
        with pytest.raises(ValueError, match="total_units must be >= 1"):
            TypologyRecommender(total_units=0)

    def test_typology_uses_market_in_recommend(self):
        from utils.fsi_calculator import TypologyRecommender
        with patch("utils.fsi_calculator.calculate_fsi") as mock_calc:
            mock_calc.return_value.aiz_height_limit_m = None
            mock_calc.return_value.aiz_note = None
            rec = TypologyRecommender(total_units=100, avg_listing_psf=7000, market="Devanahalli", zone="R2")
            rec.recommend()
            mock_calc.assert_called_once()
            _, kwargs = mock_calc.call_args
            assert kwargs["market"] == "Devanahalli"
            assert kwargs["zone"] == "R2"
