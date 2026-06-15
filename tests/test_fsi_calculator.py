import pytest

pytestmark = pytest.mark.unit

from utils.fsi_calculator import (
    calculate_fsi,
    recommend_unit_mix,
    _MARKET_ZONE_RULES,
    _ZONE_RULES,
)


class TestCalculateFSI:
    def test_r2_basic(self):
        r = calculate_fsi(10000, "R2")
        assert r.far == 2.50
        assert r.buildable_area_sqft == pytest.approx(25000.0)
        assert r.sellable_area_sqft == pytest.approx(16250.0)

    def test_r1_basic(self):
        r = calculate_fsi(10000, "R1")
        assert r.far == 1.75
        assert r.buildable_area_sqft == pytest.approx(17500.0)

    def test_c1_basic(self):
        r = calculate_fsi(10000, "C1")
        assert r.far == 2.25

    def test_zero_land_area(self):
        r = calculate_fsi(0, "R2")
        assert r.buildable_area_sqft == 0.0
        assert r.sellable_area_sqft == 0.0

    def test_negative_land_area_clamped(self):
        r = calculate_fsi(-5000, "R2")
        assert r.buildable_area_sqft == 0.0
        assert r.land_area_sqft == 0.0

    def test_unknown_zone_defaults_to_r2(self):
        r = calculate_fsi(10000, "UNKNOWN")
        assert r.far == _ZONE_RULES["R2"]["far"]

    def test_efficiency_respected(self):
        r = calculate_fsi(10000, "R2", efficiency=0.70)
        assert r.sellable_area_sqft == pytest.approx(10000 * 2.5 * 0.70)

    def test_efficiency_clamped_max(self):
        r = calculate_fsi(10000, "R2", efficiency=2.0)
        assert r.sellable_area_sqft <= r.buildable_area_sqft

    def test_efficiency_clamped_min(self):
        r = calculate_fsi(10000, "R2", efficiency=0)
        assert r.sellable_area_sqft == pytest.approx(10000 * 2.5 * 0.01)  # floor of 1%

    def test_max_floors_positive(self):
        r = calculate_fsi(10000, "R2")
        assert r.max_floors >= 1

    def test_setbacks_returned(self):
        r = calculate_fsi(10000, "R1")
        assert r.setback_front_m == 3.0
        assert r.setback_side_m == 1.5

    def test_market_parameter_yelahanka(self):
        r = calculate_fsi(10000, "R2", market="Yelahanka")
        assert r.far == _MARKET_ZONE_RULES["Yelahanka"]["R2"]["far"]

    def test_market_parameter_devanahalli(self):
        r = calculate_fsi(10000, "R2", market="Devanahalli")
        assert r.far == _MARKET_ZONE_RULES["Devanahalli"]["R2"]["far"]

    def test_market_parameter_hebbal(self):
        r = calculate_fsi(10000, "R2", market="Hebbal")
        assert r.far == _MARKET_ZONE_RULES["Hebbal"]["R2"]["far"]

    def test_market_unknown_falls_back_to_default(self):
        r = calculate_fsi(10000, "R2", market="UnknownMarket")
        assert r.far == _ZONE_RULES["R2"]["far"]


class TestRecommendUnitMix:
    def test_negative_psf_clamped_to_affordable(self):
        m = recommend_unit_mix(-100)
        assert m.psf_band == "affordable"
        assert m.bhk_1_pct + m.bhk_2_pct + m.bhk_3_pct == 100

    def test_affordable_psf(self):
        m = recommend_unit_mix(3500)
        assert m.psf_band == "affordable"
        assert m.bhk_2_pct > m.bhk_3_pct

    def test_mid_range_psf(self):
        m = recommend_unit_mix(6000)
        assert m.psf_band == "mid-range"

    def test_premium_psf(self):
        m = recommend_unit_mix(8500)
        assert m.psf_band == "premium"
        assert m.bhk_3_pct >= m.bhk_1_pct

    def test_psf_4500_lower_bound_mid_range(self):
        m = recommend_unit_mix(4500)
        assert m.psf_band == "mid-range"

    def test_psf_7000_lower_bound_premium(self):
        m = recommend_unit_mix(7000)
        assert m.psf_band == "premium"

    def test_unit_mix_sums_100(self):
        for psf in [3000, 5500, 9000]:
            m = recommend_unit_mix(psf)
            assert m.bhk_1_pct + m.bhk_2_pct + m.bhk_3_pct == 100

    def test_carpet_affordable_650(self):
        m = recommend_unit_mix(3500)
        assert m.recommended_avg_carpet_sqft == 650

    def test_carpet_mid_range_850(self):
        m = recommend_unit_mix(6000)
        assert m.recommended_avg_carpet_sqft == 850

    def test_carpet_premium_1100(self):
        m = recommend_unit_mix(9000)
        assert m.recommended_avg_carpet_sqft == 1100
