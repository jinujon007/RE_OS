import json

import pytest

pytestmark = pytest.mark.unit

from utils.feasibility import (
    LandFeasibility,
    calc_breakeven_psf,
    calc_construction_cost,
    calc_gdv,
    calc_land_cost,
    calc_profit_margin,
    calc_simple_irr,
    feasibility_summary,
)


def _sample(
    target_sell_psf: float = 6500,
    land_cost_psf: float = 1500,
    efficiency_ratio: float = 0.65,
    fsi: float = 2.0,
    construction_cost_psf: float = 2200,
    land_area_sqft: float = 10000,
    timeline_months: int = 36,
) -> LandFeasibility:
    return LandFeasibility(
        land_area_sqft=land_area_sqft,
        land_cost_psf=land_cost_psf,
        construction_cost_psf=construction_cost_psf,
        target_sell_psf=target_sell_psf,
        efficiency_ratio=efficiency_ratio,
        fsi=fsi,
        timeline_months=timeline_months,
    )


class TestCalcLandCost:
    def test_basic(self):
        f = _sample()
        assert calc_land_cost(f) == 15_000_000

    def test_zero_area(self):
        f = _sample(land_area_sqft=0)
        assert calc_land_cost(f) == 0


class TestCalcGDV:
    def test_basic(self):
        f = _sample()
        built = 10000 * 2.0
        sellable = built * 0.65
        assert calc_gdv(f) == sellable * 6500

    def test_zero_sell_price(self):
        f = _sample(target_sell_psf=0)
        assert calc_gdv(f) == 0


class TestCalcConstructionCost:
    def test_basic(self):
        f = _sample()
        assert calc_construction_cost(f) == 10000 * 2.0 * 2200

    def test_zero_area(self):
        f = _sample(land_area_sqft=0)
        assert calc_construction_cost(f) == 0


class TestCalcBreakevenPsf:
    def test_basic(self):
        f = _sample()
        total_cost = calc_land_cost(f) + calc_construction_cost(f)
        sellable = 10000 * 2.0 * 0.65
        expected = total_cost / sellable
        assert calc_breakeven_psf(f) == pytest.approx(expected, rel=1e-6)

    def test_min_efficiency_no_zerodivision(self):
        f = _sample(efficiency_ratio=0.01)
        result = calc_breakeven_psf(f)
        assert result > 0
        assert result < 1e12


class TestCalcProfitMargin:
    def test_basic(self):
        f = _sample()
        gdv = calc_gdv(f)
        total = calc_land_cost(f) + calc_construction_cost(f)
        expected = (gdv - total) / gdv * 100
        assert calc_profit_margin(f) == pytest.approx(expected, rel=1e-6)

    def test_negative_margin(self):
        f = _sample(target_sell_psf=3500)
        assert calc_profit_margin(f) < 0


class TestCalcSimpleIrr:
    def test_basic(self):
        f = _sample()
        gdv = calc_gdv(f)
        total = calc_land_cost(f) + calc_construction_cost(f)
        profit = gdv - total
        expected = (profit / total) / 3 * 100
        assert calc_simple_irr(f) == pytest.approx(expected, rel=1e-6)


class TestFeasibilitySummaryVerdict:
    def test_go_verdict_when_margin_ge_20(self):
        f = _sample(target_sell_psf=6500)
        result = feasibility_summary(f)
        margin = calc_profit_margin(f)
        assert margin >= 20
        assert result["verdict"] == "GO"

    def test_marginal_verdict_when_margin_12_to_20(self):
        f = _sample(target_sell_psf=5500)
        result = feasibility_summary(f)
        margin = calc_profit_margin(f)
        assert 12 <= margin < 20
        assert result["verdict"] == "MARGINAL"

    def test_no_go_verdict_when_margin_below_12(self):
        f = _sample(target_sell_psf=4000)
        result = feasibility_summary(f)
        margin = calc_profit_margin(f)
        assert margin < 12
        assert result["verdict"] == "NO-GO"

    def test_summary_includes_all_keys(self):
        f = _sample()
        result = feasibility_summary(f)
        keys = {
            "land_cost_total", "construction_cost_total", "gdv",
            "breakeven_psf", "profit_margin_pct", "simple_irr_pct", "verdict",
        }
        assert set(result.keys()) == keys


class TestInputSanitization:
    def test_negative_land_area_clamped_to_zero(self):
        f = LandFeasibility(land_area_sqft=-5000, land_cost_psf=1500)
        assert f.land_area_sqft == 0
        assert calc_land_cost(f) == 0

    def test_negative_land_cost_clamped_to_zero(self):
        f = LandFeasibility(land_area_sqft=10000, land_cost_psf=-500)
        assert f.land_cost_psf == 0
        assert calc_land_cost(f) == 0

    def test_efficiency_ratio_clamped_to_max_1(self):
        f = LandFeasibility(
            land_area_sqft=10000, land_cost_psf=1500,
            target_sell_psf=6500, efficiency_ratio=2.0,
        )
        assert f.efficiency_ratio == 1.0

    def test_efficiency_ratio_clamped_to_min_0_01(self):
        f = LandFeasibility(
            land_area_sqft=10000, land_cost_psf=1500,
            target_sell_psf=6500, efficiency_ratio=0,
        )
        assert f.efficiency_ratio == 0.01

    def test_fsi_clamped_to_min_0_1(self):
        f = LandFeasibility(
            land_area_sqft=10000, land_cost_psf=1500,
            target_sell_psf=6500, fsi=0,
        )
        assert f.fsi == 0.1

    def test_timeline_months_min_1(self):
        f = LandFeasibility(
            land_area_sqft=10000, land_cost_psf=1500,
            target_sell_psf=6500, timeline_months=0,
        )
        assert f.timeline_months == 1


class TestFeasibilityToolJsonParsing:
    """Verify the FeasibilityTool _run path works with valid/invalid JSON."""

    def test_valid_json_produces_all_keys(self):
        from agents.analyst_agent import FeasibilityTool
        tool = FeasibilityTool()
        result = json.loads(tool._run(
            '{"land_area_sqft": 10000, "land_cost_psf": 1500, "target_sell_psf": 6500}'
        ))
        assert "verdict" in result
        assert "gdv" in result
        assert "breakeven_psf" in result
        assert isinstance(result["verdict"], str)

    def test_invalid_json_returns_error(self):
        from agents.analyst_agent import FeasibilityTool
        tool = FeasibilityTool()
        result = json.loads(tool._run("not-json"))
        assert "error" in result

    def test_empty_json_uses_defaults(self):
        from agents.analyst_agent import FeasibilityTool
        tool = FeasibilityTool()
        result = json.loads(tool._run("{}"))
        assert "verdict" in result
