"""
RE_OS — IRR Model (Phase 6 — Finance Department)
LLS standard feasibility model. Assumptions confirmed 2026-05-30.

Standards:
  Construction cost:  ₹2,200/sqft (hard cost, mid-range residential)
  Target IRR:        >=20% = GO | 12-20% = MARGINAL | <12% = NO-GO
  Financing:         60% equity / 40% debt
  Timeline:          18mo land->RERA + 36mo RERA->possession = 54mo total
"""
from dataclasses import dataclass

# -- LLS Standard Assumptions -------------------------------------------------
CONSTRUCTION_COST_PSF: float = 2200.0     # ₹/sqft hard cost
TARGET_IRR_GO:         float = 20.0       # % -- project green-lights above this
TARGET_IRR_MARGINAL:   float = 12.0       # % -- conditional zone
EQUITY_RATIO:          float = 0.60       # 60% equity
DEBT_RATIO:            float = 0.40       # 40% debt
LAND_TO_RERA_MONTHS:   int   = 18
RERA_TO_POSSESSION_MONTHS: int = 36
TOTAL_TIMELINE_MONTHS: int   = LAND_TO_RERA_MONTHS + RERA_TO_POSSESSION_MONTHS


@dataclass
class LandCostResult:
    area_sqft: float
    guidance_value_psf: float
    negotiation_discount_pct: float
    raw_land_cost: float
    negotiated_land_cost: float

@dataclass
class GDVResult:
    sellable_area_sqft: float
    sell_psf: float
    gross_development_value: float
    monthly_revenue: float

@dataclass
class IRRResult:
    land_cost: float
    construction_cost: float
    total_project_cost: float
    gdv: float
    net_profit: float
    profit_margin_pct: float
    simple_irr_pct: float
    equity_required: float
    debt_required: float
    payback_months: int
    verdict: str   # GO | MARGINAL | NO-GO

@dataclass
class ScenarioResult:
    base: IRRResult
    bull: IRRResult
    bear: IRRResult
    recommendation: str


def calc_land_cost(
    area_sqft: float,
    guidance_value_psf: float,
    negotiation_discount_pct: float = 10.0,
) -> LandCostResult:
    area = float(max(area_sqft, 0))
    gv = float(max(guidance_value_psf, 0))
    disc = float(max(0.0, min(negotiation_discount_pct, 50.0)))
    raw = area * gv
    negotiated = raw * (1 - disc / 100)
    return LandCostResult(
        area_sqft=area,
        guidance_value_psf=gv,
        negotiation_discount_pct=disc,
        raw_land_cost=round(raw),
        negotiated_land_cost=round(negotiated),
    )


def calc_gdv(sellable_area_sqft: float, sell_psf: float) -> GDVResult:
    area = float(max(sellable_area_sqft, 0))
    psf  = float(max(sell_psf, 0))
    gdv  = area * psf
    monthly = gdv / max(RERA_TO_POSSESSION_MONTHS, 1)
    return GDVResult(
        sellable_area_sqft=area,
        sell_psf=psf,
        gross_development_value=round(gdv),
        monthly_revenue=round(monthly),
    )


def calc_irr(
    land_cost: float,
    sellable_area_sqft: float,
    sell_psf: float,
    construction_cost_psf: float = CONSTRUCTION_COST_PSF,
    timeline_months: int = TOTAL_TIMELINE_MONTHS,
) -> IRRResult:
    lc   = max(land_cost, 0)
    area = max(sellable_area_sqft, 0)
    gdv_r = calc_gdv(area, sell_psf)
    const_cost = area * max(construction_cost_psf, 0)
    total_cost = lc + const_cost
    profit = gdv_r.gross_development_value - total_cost
    margin = (profit / max(gdv_r.gross_development_value, 1)) * 100
    years  = max(timeline_months, 1) / 12
    irr    = (profit / max(total_cost, 1)) / years * 100

    if irr >= TARGET_IRR_GO:
        verdict = "GO"
    elif irr >= TARGET_IRR_MARGINAL:
        verdict = "MARGINAL"
    else:
        verdict = "NO-GO"

    payback = int(total_cost / max(gdv_r.monthly_revenue, 1)) if gdv_r.monthly_revenue > 0 else 9999

    return IRRResult(
        land_cost=round(lc),
        construction_cost=round(const_cost),
        total_project_cost=round(total_cost),
        gdv=gdv_r.gross_development_value,
        net_profit=round(profit),
        profit_margin_pct=round(margin, 1),
        simple_irr_pct=round(irr, 1),
        equity_required=round(total_cost * EQUITY_RATIO),
        debt_required=round(total_cost * DEBT_RATIO),
        payback_months=payback,
        verdict=verdict,
    )


def compare_scenarios(
    land_cost: float,
    sellable_area_sqft: float,
    base_psf: float,
) -> ScenarioResult:
    bull_psf  = base_psf * 1.10   # +10% optimistic
    bear_psf  = base_psf * 0.90   # -10% downside

    base = calc_irr(land_cost, sellable_area_sqft, base_psf)
    bull = calc_irr(land_cost, sellable_area_sqft, bull_psf)
    bear = calc_irr(land_cost, sellable_area_sqft, bear_psf)

    if base.verdict == "GO" and bear.verdict != "NO-GO":
        rec = "PROCEED — base and bear cases both viable."
    elif base.verdict == "GO" and bear.verdict == "NO-GO":
        # NOTE: This branch is mathematically unreachable with +-10% PSF swing
        # (the fixed construction cost of ₹2,200/sqft makes the gap between
        # 20% and 12% IRR wider than a 10% revenue swing can bridge).
        # Preserved as defensive code for future scenario widening.
        rec = "CONDITIONAL — base GO but bear NO-GO. Negotiate land cost or add JD structure."
    elif base.verdict == "MARGINAL":
        rec = "HOLD — marginal base case. Improve land cost or increase sell PSF before committing."
    else:
        rec = "PASS — base case NO-GO. Economics do not work at current inputs."

    return ScenarioResult(base=base, bull=bull, bear=bear, recommendation=rec)


if __name__ == "__main__":
    print("=== IRR Model Self-Test =========================")
    # 5-acre Yelahanka — typically GO
    area = 5 * 43560
    lc = calc_land_cost(area, 4000, 10.0)
    print("\n[5-acre Yelahanka, ₹6,500 PSF]")
    print("Land cost: ₹{:.2f}Cr (raw: ₹{:.2f}Cr)".format(lc.negotiated_land_cost/1e7, lc.raw_land_cost/1e7))
    sellable = area * 0.65 * 2.5
    gdv = calc_gdv(sellable, 6500)
    print("GDV: ₹{:.2f}Cr".format(gdv.gross_development_value/1e7))
    scenarios = compare_scenarios(lc.negotiated_land_cost, sellable, 6500)
    print("Base: {:.1f}% ({})  Bull: {:.1f}%  Bear: {:.1f}%".format(
        scenarios.base.simple_irr_pct, scenarios.base.verdict,
        scenarios.bull.simple_irr_pct,
        scenarios.bear.simple_irr_pct))
    print("Verdict: {}".format(scenarios.recommendation))

    # NO-GO case — expensive land, low PSF
    print("\n[Small site, high land cost, low PSF — NO-GO]")
    nogo = calc_irr(50_000_000, 5000, 3500)
    print("IRR: {:.1f}% ({})".format(nogo.simple_irr_pct, nogo.verdict))

    # MARGINAL case
    print("\n[Marginal site]")
    marg = calc_irr(10_000_000, 10000, 5500)
    print("IRR: {:.1f}% ({})".format(marg.simple_irr_pct, marg.verdict))

    # Zero-land case — no crash
    print("\n[All zeros — no crash]")
    zero = calc_irr(0, 0, 0)
    print("IRR: {}% ({}) | Equity: ₹{:,.0f} | Payback: {}mo".format(
        zero.simple_irr_pct, zero.verdict, zero.equity_required, zero.payback_months))
