import pytest
pytestmark = pytest.mark.unit

from utils.irr_model import (
    calc_land_cost, calc_gdv, calc_irr, compare_scenarios,
    TARGET_IRR_GO, TARGET_IRR_MARGINAL, CONSTRUCTION_COST_PSF,
    EQUITY_RATIO, DEBT_RATIO, TOTAL_TIMELINE_MONTHS,
    RERA_TO_POSSESSION_MONTHS,
    LandCostResult, GDVResult, IRRResult, ScenarioResult,
)


class TestCalcLandCost:
    def test_basic(self):
        r = calc_land_cost(43560, 4000, 10.0)
        assert r.raw_land_cost == 43560 * 4000
        assert r.negotiated_land_cost == round(43560 * 4000 * 0.90)

    def test_zero_area(self):
        r = calc_land_cost(0, 4000)
        assert r.raw_land_cost == 0

    def test_discount_clamped_to_50(self):
        r = calc_land_cost(10000, 4000, 99.0)
        assert r.negotiation_discount_pct == 50.0

    def test_no_discount(self):
        r = calc_land_cost(10000, 4000, 0)
        assert r.negotiated_land_cost == r.raw_land_cost

    def test_negative_guidance_clamped(self):
        r = calc_land_cost(10000, -500)
        assert r.guidance_value_psf == 0.0
        assert r.raw_land_cost == 0


class TestCalcGDV:
    def test_basic(self):
        r = calc_gdv(10000, 7000)
        assert r.gross_development_value == 70_000_000

    def test_zero_psf(self):
        r = calc_gdv(10000, 0)
        assert r.gross_development_value == 0

    def test_monthly_revenue_correct(self):
        r = calc_gdv(10000, 7000)
        expected = 70_000_000 / RERA_TO_POSSESSION_MONTHS
        assert r.monthly_revenue == round(expected)

    def test_zero_area(self):
        r = calc_gdv(0, 7000)
        assert r.gross_development_value == 0
        assert r.monthly_revenue == 0

    def test_negative_area_clamped(self):
        r = calc_gdv(-5000, 7000)
        assert r.sellable_area_sqft == 0.0
        assert r.gross_development_value == 0


class TestCalcIRR:
    def test_go_verdict_high_psf(self):
        r = calc_irr(10_000_000, 10000, 9000)
        assert r.verdict == "GO"
        assert r.simple_irr_pct >= TARGET_IRR_GO

    def test_no_go_verdict_low_psf(self):
        r = calc_irr(50_000_000, 10000, 3000)
        assert r.verdict == "NO-GO"

    def test_equity_debt_split(self):
        r = calc_irr(20_000_000, 10000, 7000)
        assert abs(r.equity_required / r.total_project_cost - EQUITY_RATIO) < 0.01
        assert abs(r.debt_required / r.total_project_cost - DEBT_RATIO) < 0.01

    def test_zero_land_cost(self):
        r = calc_irr(0, 10000, 7000)
        assert r.land_cost == 0
        assert r.simple_irr_pct > 0

    def test_profit_margin_positive_when_go(self):
        r = calc_irr(5_000_000, 10000, 9000)
        assert r.profit_margin_pct > 0

    def test_marginal_verdict_boundary(self):
        r = calc_irr(10_000_000, 10000, 5500)
        assert r.verdict == "MARGINAL"
        assert r.simple_irr_pct >= TARGET_IRR_MARGINAL
        assert r.simple_irr_pct < TARGET_IRR_GO

    def test_negative_psf_clamped(self):
        r = calc_irr(10_000_000, 10000, -500)
        assert r.gdv == 0
        assert r.verdict == "NO-GO"

    def test_zero_sellable_area(self):
        r = calc_irr(10_000_000, 0, 7000)
        assert r.construction_cost == 0
        assert r.gdv == 0

    def test_all_zero_inputs_no_crash(self):
        r = calc_irr(0, 0, 0)
        assert r.verdict == "NO-GO"
        assert r.payback_months == 9999

    def test_nondefault_construction_cost(self):
        r = calc_irr(10_000_000, 10000, 7000, construction_cost_psf=1500)
        expected_const = 10000 * 1500
        assert r.construction_cost == expected_const
        assert r.total_project_cost == 10_000_000 + expected_const

    def test_nondefault_timeline(self):
        r = calc_irr(10_000_000, 10000, 7000, timeline_months=24)
        shorter_timeline_irr = r.simple_irr_pct
        r_default = calc_irr(10_000_000, 10000, 7000)
        assert shorter_timeline_irr > r_default.simple_irr_pct


class TestCompareScenarios:
    def test_scenario_structure(self):
        s = compare_scenarios(15_000_000, 10000, 7000)
        assert s.base is not None
        assert s.bull.gdv > s.base.gdv
        assert s.bear.gdv < s.base.gdv

    def test_bull_higher_irr_than_bear(self):
        s = compare_scenarios(15_000_000, 10000, 7000)
        assert s.bull.simple_irr_pct > s.bear.simple_irr_pct

    def test_recommendation_string_present(self):
        s = compare_scenarios(15_000_000, 10000, 7000)
        assert isinstance(s.recommendation, str)
        assert len(s.recommendation) > 0

    def test_proceed_when_base_and_bear_viable(self):
        s = compare_scenarios(5_000_000, 10000, 9000)
        assert "PROCEED" in s.recommendation

    def test_pass_when_base_no_go(self):
        s = compare_scenarios(100_000_000, 5000, 3000)
        assert "PASS" in s.recommendation

    def test_hold_when_base_marginal(self):
        s = compare_scenarios(10_000_000, 10000, 5500)
        assert s.base.verdict == "MARGINAL"
        assert "HOLD" in s.recommendation

    def test_all_verdicts_covered_by_comparator(self):
        """Verify that compare_scenarios produces all reachable verdict branches:
        PROCEED (GO+bear viable), HOLD (MARGINAL), PASS (NO-GO).
        CONDITIONAL (GO+bear NO-GO) is unreachable with +-10% PSF swing —
        kept as defensive code for future scenario widening."""
        s1 = compare_scenarios(5_000_000, 10000, 9000)
        assert "PROCEED" in s1.recommendation
        s2 = compare_scenarios(10_000_000, 10000, 5500)
        assert "HOLD" in s2.recommendation
        s3 = compare_scenarios(100_000_000, 5000, 3000)
        assert "PASS" in s3.recommendation


class TestGDVEstimator:
    """GDVEstimator with mocked DB connection (T-477)."""

    def test_estimate_returns_gdv_result(self):
        from utils.irr_model import GDVEstimator
        est = GDVEstimator()
        result = est.estimate(sellable_area_sqft=10000, market="")
        assert result.sellable_area_sqft == 10000
        assert result.sell_psf == 0.0
        assert result.igr_source is None  # no market → no IGR lookup attempted
        assert result.igr_record_count == 0

    def test_estimate_clamps_max_area(self):
        from utils.irr_model import GDVEstimator
        est = GDVEstimator()
        result = est.estimate(sellable_area_sqft=50_000_000, market="")
        assert result.sellable_area_sqft == 10_000_000

    def test_estimate_clamps_negative_area(self):
        from utils.irr_model import GDVEstimator
        est = GDVEstimator()
        result = est.estimate(sellable_area_sqft=-5000, market="")
        assert result.sellable_area_sqft == 0.0

    def test_estimate_empty_market_returns_zero_psf_no_source(self):
        from utils.irr_model import GDVEstimator
        est = GDVEstimator()
        result = est.estimate(sellable_area_sqft=10000, market="")
        assert result.sell_psf == 0.0
        assert result.igr_source is None

    def test_estimate_market_no_igr_data_passes_source_through(self):
        from unittest.mock import patch
        from utils.irr_model import GDVEstimator
        with patch.object(GDVEstimator, "_query_igr_median_psf", return_value=(None, 2, "insufficient_records")):
            est = GDVEstimator()
            result = est.estimate(sellable_area_sqft=10000, market="Devanahalli")
            assert result.igr_source == "insufficient_records"
            assert result.igr_record_count == 2

    def test_estimate_psf_sanity_rejects_outliers(self):
        from unittest.mock import patch
        from utils.irr_model import GDVEstimator
        est = GDVEstimator()
        est.clear_cache()
        assert est._validate_psf(250) is None   # below ₹500/sqft
        assert est._validate_psf(60000) is None  # above ₹50,000/sqft
        assert est._validate_psf(5000) == 5000   # valid

    def test_clear_cache_empties_cache(self):
        from utils.irr_model import GDVEstimator
        est = GDVEstimator()
        est._cache["test"] = (5000.0, 10, "igr_portal", 9999999999.0)
        assert len(est._cache) == 1
        est.clear_cache()
        assert len(est._cache) == 0

    def test_query_igr_median_psf_db_error_returns_none(self):
        from unittest.mock import patch
        from utils.irr_model import GDVEstimator
        with patch("utils.db.get_engine", side_effect=Exception("DB down")):
            est = GDVEstimator()
            psf, count, source = est._query_igr_median_psf("Yelahanka")
        assert psf is None
        assert count == 0
        assert source == "table_unavailable"

    def test_query_igr_median_psf_zero_rows(self):
        from unittest.mock import MagicMock, patch
        from utils.irr_model import GDVEstimator
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        with patch("utils.db.get_engine", return_value=mock_engine):
            est = GDVEstimator()
            psf, count, source = est._query_igr_median_psf("Yelahanka")
        assert psf is None
        assert count == 0
        assert source == "no_data"

    def test_normalize_market_title_case(self):
        from utils.irr_model import GDVEstimator
        assert GDVEstimator._normalize_market("YELAHANKA") == "Yelahanka"
        assert GDVEstimator._normalize_market("devanahalli") == "Devanahalli"
        assert GDVEstimator._normalize_market("HEBBAL ") == "Hebbal"

    def test_normalize_market_empty(self):
        from utils.irr_model import GDVEstimator
        assert GDVEstimator._normalize_market("") == ""
        assert GDVEstimator._normalize_market("   ") == ""

    def test_normalize_market_truncates_long(self):
        from utils.irr_model import GDVEstimator
        long_name = "A" * 200
        result = GDVEstimator._normalize_market(long_name)
        assert len(result) <= 100

    def test_log_igr_lookup_db_error_does_not_raise(self):
        from utils.irr_model import log_igr_lookup
        from unittest.mock import patch
        with patch("utils.db.get_engine", side_effect=Exception("DB down")):
            log_igr_lookup("Yelahanka", "igr_portal", 10, 5500.0, "TestCaller")

    def test_log_igr_lookup_ignores_empty_market(self):
        from utils.irr_model import log_igr_lookup
        from unittest.mock import patch
        with patch("utils.db.get_engine", side_effect=Exception("DB down")):
            log_igr_lookup("", None, 0, 0.0, "TestCaller")

    def test_query_igr_median_psf_insufficient_records(self):
        from unittest.mock import MagicMock, patch
        from utils.irr_model import GDVEstimator
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (5500.0, 3)
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        with patch("utils.db.get_engine", return_value=mock_engine):
            est = GDVEstimator()
            psf, count, source = est._query_igr_median_psf("Yelahanka")
        assert psf is None
        assert count == 3
        assert source == "insufficient_records"


class TestDataclassContracts:
    def test_land_cost_result_fields(self):
        r = calc_land_cost(43560, 4000, 10.0)
        assert hasattr(r, "area_sqft") and isinstance(r.area_sqft, (int, float))
        assert hasattr(r, "guidance_value_psf") and isinstance(r.guidance_value_psf, (int, float))
        assert hasattr(r, "negotiated_land_cost") and isinstance(r.negotiated_land_cost, (int, float))

    def test_irr_result_fields(self):
        r = calc_irr(10_000_000, 10000, 9000)
        assert hasattr(r, "verdict") and isinstance(r.verdict, str)
        assert hasattr(r, "equity_required") and isinstance(r.equity_required, (int, float))
        assert hasattr(r, "payback_months") and isinstance(r.payback_months, int)

    def test_scenario_result_structure(self):
        s = compare_scenarios(15_000_000, 10000, 7000)
        assert isinstance(s.base, IRRResult)
        assert isinstance(s.bull, IRRResult)
        assert isinstance(s.bear, IRRResult)
        assert isinstance(s.recommendation, str)
