import pytest
pytestmark = pytest.mark.unit

from utils.irr_model import (
    calc_land_cost, calc_gdv, calc_irr, compare_scenarios,
    TARGET_IRR_GO, TARGET_IRR_MARGINAL, CONSTRUCTION_COST_PSF,
    EQUITY_RATIO, DEBT_RATIO, TOTAL_TIMELINE_MONTHS,
    RERA_TO_POSSESSION_MONTHS,
    LandCostResult, GDVResult, IRRResult, ScenarioResult,
    re_sharpe_ratio, _build_monthly_returns, _compute_risk_metrics,
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


class TestRiskMetrics:
    """Risk metric functions: re_sharpe_ratio, _build_monthly_returns, _compute_risk_metrics."""

    def test_re_sharpe_ratio_basic(self):
        """(18% IRR, 7% Gsec, 5% std) = (18-7)/5 = 2.2"""
        assert re_sharpe_ratio(18.0, 0.07, 5.0) == 2.2

    def test_re_sharpe_ratio_negative_irr(self):
        """Negative excess return → negative Sharpe."""
        sr = re_sharpe_ratio(3.0, 0.07, 5.0)
        assert sr < 0

    def test_re_sharpe_ratio_zero_std_returns_zero(self):
        """Zero std (all scenarios identical) → no risk penalty → 0 Sharpe."""
        assert re_sharpe_ratio(18.0, 0.07, 0.0) == 0.0

    def test_re_sharpe_ratio_small_std_clamped(self):
        """Std below _MIN_IRR_STD (0.5) is clamped → returns 0, not inflated."""
        assert re_sharpe_ratio(18.0, 0.07, 0.1) == 0.0

    def test_re_sharpe_ratio_boundary_std(self):
        """Std exactly at _MIN_IRR_STD → still clamped (<=, not <)."""
        assert re_sharpe_ratio(18.0, 0.07, 0.5) == 0.0

    def test_re_sharpe_ratio_nan_input_returns_zero(self):
        """NaN in any parameter → 0 (no crash)."""
        import math
        assert re_sharpe_ratio(math.nan, 0.07, 5.0) == 0.0
        assert re_sharpe_ratio(18.0, math.nan, 5.0) == 0.0
        assert re_sharpe_ratio(18.0, 0.07, math.nan) == 0.0

    def test_re_sharpe_ratio_negative_rf_clamped(self):
        """Negative risk-free rate clamped to 0 → (18-0)/5 = 3.6."""
        assert re_sharpe_ratio(18.0, -0.05, 5.0) == 3.6

    def test_build_monthly_returns_short_timeline(self):
        """Timeline shorter than LAND_TO_RERA_MONTHS produces valid series."""
        mr = _build_monthly_returns(10_000_000, 50_000_000, 100_000_000, 36_000_000, timeline_months=12)
        assert len(mr) >= 1
        # Month 0 still includes land cost
        assert mr.iloc[0] == (-10_000_000 - 50_000_000/12) / 36_000_000

    def test_build_monthly_returns_zero_gdv(self):
        """Zero GDV → empty Series."""
        import pandas as pd
        mr = _build_monthly_returns(10_000_000, 50_000_000, 0, 36_000_000)
        assert isinstance(mr, pd.Series) and len(mr) == 0

    def test_build_monthly_returns_negative_land_capped(self):
        """Negative land cost → treated as 0 (clamped upstream)."""
        import pandas as pd
        mr = _build_monthly_returns(-10_000_000, 50_000_000, 100_000_000, 36_000_000)
        assert isinstance(mr, pd.Series) and len(mr) == TOTAL_TIMELINE_MONTHS

    def test_build_monthly_returns_length(self):
        """A 54-month project produces 54 monthly returns."""
        mr = _build_monthly_returns(10_000_000, 50_000_000, 100_000_000, 36_000_000)
        assert len(mr) == TOTAL_TIMELINE_MONTHS

    def test_build_monthly_returns_zero_equity(self):
        """Zero equity required → empty Series (no division by zero)."""
        import pandas as pd
        mr = _build_monthly_returns(10_000_000, 50_000_000, 100_000_000, 0)
        assert isinstance(mr, pd.Series) and len(mr) == 0

    def test_build_monthly_returns_negative_cashflow_first_month(self):
        """Month 0 should have land cost + construction = most negative."""
        mr = _build_monthly_returns(10_000_000, 50_000_000, 100_000_000, 36_000_000)
        assert mr.iloc[0] < mr.iloc[1]  # land cost makes month 0 more negative

    def test_build_monthly_returns_positive_during_sell(self):
        """Sell-period months should be less negative (or positive) than pre-RERA."""
        mr = _build_monthly_returns(10_000_000, 50_000_000, 100_000_000, 36_000_000)
        sell_start = 18  # LAND_TO_RERA_MONTHS
        # Revenue partially offsets construction in sell phase
        assert mr.iloc[sell_start] > mr.iloc[1]

    def test_compute_risk_metrics_basic(self):
        """Compute risk metrics returns all 4 keys with expected types."""
        r = _compute_risk_metrics(
            land_cost=10_000_000, construction_cost=50_000_000,
            gdv=100_000_000, equity_required=36_000_000,
            simple_irr_pct=10.5, bull_irr_pct=13.8, bear_irr_pct=3.9,
        )
        assert isinstance(r, dict)
        assert "sharpe_ratio" in r
        assert "max_drawdown_pct" in r
        assert "best_case_irr_pct" in r
        assert "worst_case_irr_pct" in r
        assert r["best_case_irr_pct"] == 13.8
        assert r["worst_case_irr_pct"] == 3.9

    def test_compute_risk_metrics_best_worst_rounding(self):
        """Best/worst case IRRs should be rounded to 1 decimal."""
        r = _compute_risk_metrics(
            land_cost=0, construction_cost=0,
            gdv=0, equity_required=0,
            simple_irr_pct=10.555, bull_irr_pct=14.777, bear_irr_pct=4.222,
        )
        assert r["best_case_irr_pct"] == 14.8
        assert r["worst_case_irr_pct"] == 4.2

    def test_compute_risk_metrics_sharpe_with_std(self):
        """With non-zero std across scenarios, Sharpe should be non-zero."""
        r = _compute_risk_metrics(
            land_cost=10_000_000, construction_cost=50_000_000,
            gdv=100_000_000, equity_required=36_000_000,
            simple_irr_pct=10.5, bull_irr_pct=13.8, bear_irr_pct=3.9,
        )
        # std of [10.5, 13.8, 3.9] ≈ 4.97, so (10.5 - 7) / 4.97 ≈ 0.70
        assert r["sharpe_ratio"] > 0
        assert r["sharpe_ratio"] < 1.0

    def test_compute_risk_metrics_identical_scenarios_zero_sharpe(self):
        """All scenarios identical → zero std → Sharpe = 0."""
        r = _compute_risk_metrics(
            land_cost=0, construction_cost=0,
            gdv=0, equity_required=0,
            simple_irr_pct=10.0, bull_irr_pct=10.0, bear_irr_pct=10.0,
        )
        assert r["sharpe_ratio"] == 0.0


class TestCompareScenariosRiskBands:
    """Risk band propagation on compare_scenarios."""

    def test_risk_bands_on_base(self):
        """Base IRRResult after compare_scenarios should have risk bands populated."""
        s = compare_scenarios(15_000_000, 10000, 7000)
        assert s.base.best_case_irr_pct > 0
        assert s.base.worst_case_irr_pct > 0
        assert s.base.sharpe_ratio != 0.0

    def test_risk_bands_all_scenarios_have_same_range(self):
        """All 3 scenarios should share the same risk band range."""
        s = compare_scenarios(15_000_000, 10000, 7000)
        assert s.base.best_case_irr_pct == s.bull.best_case_irr_pct
        assert s.base.worst_case_irr_pct == s.bear.worst_case_irr_pct

    def test_risk_free_rate_default_on_irr_result(self):
        """IRRResult carries a default 7% risk-free rate."""
        r = calc_irr(10_000_000, 10000, 9000)
        assert r.risk_free_return_pct == 7.0

    def test_all_zero_inputs_risk_bands_zero(self):
        """Degenerate inputs should produce zero risk bands (no crash)."""
        s = compare_scenarios(0, 0, 0)
        assert s.base.sharpe_ratio == 0.0
        assert s.base.max_drawdown_pct == 0.0
        assert s.base.best_case_irr_pct == 0.0
        assert s.base.worst_case_irr_pct == 0.0


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

    def test_irr_result_has_risk_fields(self):
        """IRRResult should carry all 5 risk metric fields."""
        r = calc_irr(10_000_000, 10000, 9000)
        assert hasattr(r, "sharpe_ratio")
        assert hasattr(r, "max_drawdown_pct")
        assert hasattr(r, "best_case_irr_pct")
        assert hasattr(r, "worst_case_irr_pct")
        assert hasattr(r, "risk_free_return_pct")

    def test_scenario_result_structure(self):
        s = compare_scenarios(15_000_000, 10000, 7000)
        assert isinstance(s.base, IRRResult)
        assert isinstance(s.bull, IRRResult)
        assert isinstance(s.bear, IRRResult)
        assert isinstance(s.recommendation, str)
