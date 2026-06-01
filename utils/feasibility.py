from dataclasses import dataclass


def _clamp(value, lo=0, hi=None):
    if hi is not None:
        return max(lo, min(value, hi))
    return max(lo, value)


@dataclass
class LandFeasibility:
    land_area_sqft: float
    land_cost_psf: float
    construction_cost_psf: float = 2200
    target_sell_psf: float = 0
    efficiency_ratio: float = 0.65
    fsi: float = 2.0
    timeline_months: int = 36

    def __post_init__(self):
        self.land_area_sqft = _clamp(self.land_area_sqft)
        self.land_cost_psf = _clamp(self.land_cost_psf)
        self.construction_cost_psf = _clamp(self.construction_cost_psf)
        self.target_sell_psf = _clamp(self.target_sell_psf)
        self.efficiency_ratio = _clamp(self.efficiency_ratio, 0.01, 1.0)
        self.fsi = _clamp(self.fsi, 0.1)
        self.timeline_months = max(int(_clamp(self.timeline_months, 1)), 1)


def calc_land_cost(f: LandFeasibility) -> float:
    return f.land_area_sqft * f.land_cost_psf


def calc_gdv(f: LandFeasibility) -> float:
    built_area = f.land_area_sqft * f.fsi
    sellable_area = built_area * f.efficiency_ratio
    return sellable_area * f.target_sell_psf


def calc_construction_cost(f: LandFeasibility) -> float:
    return f.land_area_sqft * f.fsi * f.construction_cost_psf


def calc_breakeven_psf(f: LandFeasibility) -> float:
    total_cost = calc_land_cost(f) + calc_construction_cost(f)
    sellable_area = f.land_area_sqft * f.fsi * f.efficiency_ratio
    return total_cost / max(sellable_area, 1)


def calc_profit_margin(f: LandFeasibility) -> float:
    gdv = calc_gdv(f)
    total_cost = calc_land_cost(f) + calc_construction_cost(f)
    return (gdv - total_cost) / max(gdv, 1) * 100


def calc_simple_irr(f: LandFeasibility) -> float:
    gdv = calc_gdv(f)
    total_cost = calc_land_cost(f) + calc_construction_cost(f)
    profit = gdv - total_cost
    years = f.timeline_months / 12
    return (profit / max(total_cost, 1)) / max(years, 0.5) * 100


def feasibility_summary(f: LandFeasibility) -> dict:
    margin = calc_profit_margin(f)
    if margin >= 20:
        verdict = "GO"
    elif margin >= 12:
        verdict = "MARGINAL"
    else:
        verdict = "NO-GO"
    return {
        "land_cost_total": round(calc_land_cost(f)),
        "construction_cost_total": round(calc_construction_cost(f)),
        "gdv": round(calc_gdv(f)),
        "breakeven_psf": round(calc_breakeven_psf(f)),
        "profit_margin_pct": round(margin, 1),
        "simple_irr_pct": round(calc_simple_irr(f), 1),
        "verdict": verdict,
    }
