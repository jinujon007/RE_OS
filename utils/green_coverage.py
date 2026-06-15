"""
RE_OS — Green Coverage Estimator (Phase 5 — Engineering / BDA Compliance)
Pure Python calculation of landscape area, tree count, and BDA minimum green
coverage compliance. No LLM dependency.
"""

from dataclasses import dataclass

_SQFT_PER_TREE = 200
_MIN_GREEN_PCT_BDA = 15.0


@dataclass
class GreenCoverageResult:
    land_area_sqft: float
    built_coverage_pct: float
    landscape_area_sqft: float
    green_pct: float
    tree_count: int
    meets_bda_minimum: bool


def calculate_green_coverage(
    land_area_sqft: float,
    built_coverage_pct: float = 0.55,
) -> GreenCoverageResult:
    land = float(max(land_area_sqft, 0))
    coverage = max(0.0, min(float(built_coverage_pct), 1.0))
    landscape = land * (1.0 - coverage)
    green_pct = (landscape / max(land, 1)) * 100
    rounded_green_pct = round(green_pct, 1)
    tree_count = max(1, int(landscape / _SQFT_PER_TREE))
    return GreenCoverageResult(
        land_area_sqft=land,
        built_coverage_pct=coverage,
        landscape_area_sqft=round(landscape, 1),
        green_pct=rounded_green_pct,
        tree_count=tree_count,
        meets_bda_minimum=rounded_green_pct >= _MIN_GREEN_PCT_BDA,
    )
