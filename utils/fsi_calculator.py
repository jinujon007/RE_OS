"""RE_OS — FSI Calculator + Typology Recommender (Phase 5 — Engineering).
Pure Python. No LLM dependency. Market-aware BDA zone rules."""
from copy import deepcopy
from dataclasses import dataclass
from typing import Optional

_MARKET_ZONE_RULES: dict[str, dict[str, dict]] = {
    "Yelahanka": {
        "R1": {"far": 1.75, "max_height_m": 11,  "plot_coverage": 0.50, "setback_front": 3.0, "setback_side": 1.5},
        "R2": {"far": 2.50, "max_height_m": 18,  "plot_coverage": 0.55, "setback_front": 4.5, "setback_side": 1.5},
        "C1": {"far": 2.25, "max_height_m": 15,  "plot_coverage": 0.60, "setback_front": 6.0, "setback_side": 3.0},
    },
    "Devanahalli": {
        "R1": {"far": 2.00, "max_height_m": 14,  "plot_coverage": 0.50, "setback_front": 3.0, "setback_side": 1.5},
        "R2": {"far": 3.00, "max_height_m": 24,  "plot_coverage": 0.60, "setback_front": 4.5, "setback_side": 1.5},
        "C1": {"far": 2.50, "max_height_m": 18,  "plot_coverage": 0.65, "setback_front": 6.0, "setback_side": 3.0},
    },
    "Hebbal": {
        "R1": {"far": 1.75, "max_height_m": 14,  "plot_coverage": 0.50, "setback_front": 3.0, "setback_side": 1.5},
        "R2": {"far": 2.75, "max_height_m": 21,  "plot_coverage": 0.58, "setback_front": 4.5, "setback_side": 1.5},
        "C1": {"far": 2.50, "max_height_m": 18,  "plot_coverage": 0.60, "setback_front": 6.0, "setback_side": 3.0},
    },
}

_ZONE_RULES: dict[str, dict] = deepcopy(_MARKET_ZONE_RULES["Yelahanka"])

_PSF_UNIT_MIX: list[tuple[int, int, str, dict]] = [
    (0,    4500, "affordable", {"1bhk": 30, "2bhk": 55, "3bhk": 15}),
    (4500, 7000, "mid-range",  {"1bhk": 15, "2bhk": 55, "3bhk": 30}),
    (7000, 9999999, "premium", {"1bhk": 5,  "2bhk": 45, "3bhk": 50}),
]
_CARPET_BY_BAND = {"affordable": 650, "mid-range": 850, "premium": 1100}

@dataclass
class FSIResult:
    zone: str
    land_area_sqft: float
    far: float
    buildable_area_sqft: float
    sellable_area_sqft: float
    max_floors: int
    plot_coverage: float
    setback_front_m: float
    setback_side_m: float

@dataclass
class UnitMix:
    psf_band: str
    bhk_1_pct: int
    bhk_2_pct: int
    bhk_3_pct: int
    recommended_avg_carpet_sqft: int

def calculate_fsi(land_area_sqft: float, zone: str = "R2",
                  efficiency: float = 0.65,
                  market: Optional[str] = None) -> FSIResult:
    zone = zone.upper()
    rules = _ZONE_RULES.get(zone, _ZONE_RULES["R2"])
    market = str(market).strip() if market else None
    if market:
        market_rules = _MARKET_ZONE_RULES.get(market.title(), _ZONE_RULES)
        rules = market_rules.get(zone, market_rules.get("R2", _ZONE_RULES["R2"]))
    buildable = max(land_area_sqft, 0) * rules["far"]
    sellable  = buildable * max(0.01, min(efficiency, 1.0))
    safe_area   = max(land_area_sqft, 0)
    floor_plate = safe_area * rules["plot_coverage"]
    max_floors  = max(1, int(buildable / max(floor_plate, 1)))
    return FSIResult(
        zone=zone,
        land_area_sqft=safe_area,
        far=rules["far"],
        buildable_area_sqft=round(buildable, 1),
        sellable_area_sqft=round(sellable, 1),
        max_floors=max_floors,
        plot_coverage=rules["plot_coverage"],
        setback_front_m=rules["setback_front"],
        setback_side_m=rules["setback_side"],
    )

def recommend_unit_mix(avg_listing_psf: float) -> UnitMix:
    avg_listing_psf = max(avg_listing_psf, 0)
    mix, band = _PSF_UNIT_MIX[-1][3], _PSF_UNIT_MIX[-1][2]
    for lo, hi, name, m in _PSF_UNIT_MIX:
        if lo <= avg_listing_psf < hi:
            mix, band = m, name
            break
    avg_carpet = _CARPET_BY_BAND[band]
    return UnitMix(
        psf_band=band,
        bhk_1_pct=mix["1bhk"],
        bhk_2_pct=mix["2bhk"],
        bhk_3_pct=mix["3bhk"],
        recommended_avg_carpet_sqft=avg_carpet,
    )
