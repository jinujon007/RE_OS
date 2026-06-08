"""
RE_OS — IntelPackage Context Builder (Shared)
===============================================
Single source of truth for converting an IntelPackage to a formatted context dict.
Used by board_room_v2, deal_memo_v2, and investor_brief_v2 to avoid DRY violations.

All formatting helpers are here — every module that needs IntelPackage data
as human-readable text calls ``build_intel_context(pkg)``.
"""

from intelligence.registry import IntelPackage

__all__ = ["build_intel_context", "_v", "_deal_scenarios_str", "_legal_flags_str"]


def _v(val, fmt: str = "") -> str:
    if val is None:
        return "N/A"
    if fmt:
        return f"{val:{fmt}}"
    return str(val)


def _deal_scenarios_str(fe) -> str:
    if not fe:
        return "No financial evaluation available."
    parts = []
    for s in [fe.purchase, fe.jd, fe.jv]:
        if s:
            parts.append(
                f"  {s.structure.upper()}: IRR {s.simple_irr_pct:.1f}% "
                f"({s.verdict}), equity \u20b9{s.equity_required:,.0f}, "
                f"GDV \u20b9{s.gross_development_value:,.0f}, "
                f"payback {s.payback_months}mo"
            )
    parts.append(f"  Best structure: {fe.best_structure}")
    parts.append(f"  Recommendation: {fe.recommendation}")
    parts.append(f"  PSF source: {fe.psf_source_quality}")
    return "\n".join(parts)


def _legal_flags_str(lp) -> str:
    if not lp:
        return "No legal picture available."
    lines = []
    for f in lp.title_risk_flags:
        lines.append(f"  [{f.status}] {f.flag}: {f.detail}")
    if lp.overlay_risks:
        lines.append(f"  Overlays: {', '.join(lp.overlay_risks)}")
    return "\n".join(lines) if lines else "No flags."


def _legal_details_teaser(lp, max_lines: int = 3) -> str:
    if not lp:
        return "No legal picture available."
    lines = []
    for f in lp.title_risk_flags:
        lines.append(f"[{f.status}] {f.flag}")
    if lp.overlay_risks:
        lines.append(f"Overlays: {', '.join(lp.overlay_risks)}")
    teaser = " | ".join(lines[:max_lines])
    if len(lines) > max_lines:
        teaser += f" | … +{len(lines) - max_lines} more"
    return teaser or "No flags."


def build_intel_context(pkg: IntelPackage) -> dict:
    pulse = pkg.market_pulse
    fin = pkg.financial_evaluation
    legal = pkg.legal_picture
    land = pkg.land_picture
    demand = pkg.demand_signals

    return {
        "market": pkg.market,
        "survey_no": pkg.survey_no,
        "deal_type": pkg.deal_type,
        "all_modules_ok": pkg.all_modules_success,
        "module_errors": pkg.errors,
        "market_pulse": {
            "avg_listing_psf": _v(pulse.avg_listing_psf, ",.0f") if pulse else "N/A",
            "median_igr_psf": _v(pulse.median_igr_psf, ",.0f") if pulse else "N/A",
            "months_of_supply": _v(pulse.months_of_supply, ".1f") if pulse else "N/A",
            "supply_label": pulse.supply_label if pulse else "N/A",
            "total_projects": _v(pulse.total_projects) if pulse else "N/A",
            "total_units": _v(pulse.total_units) if pulse else "N/A",
            "avg_absorption_pct": _v(pulse.avg_absorption_pct, ".1f") if pulse else "N/A",
            "unique_developers": _v(pulse.unique_developers) if pulse else "N/A",
            "grade_a_developers": _v(pulse.grade_a_developers) if pulse else "N/A",
            "price_momentum_signal": pulse.price_momentum_signal if pulse else "N/A",
        },
        "financial_evaluation": {
            "land_area_sqft": _v(fin.land_area_sqft, ",.0f") if fin else "N/A",
            "sellable_area_sqft": _v(fin.sellable_area_sqft, ",.0f") if fin else "N/A",
            "sell_psf": _v(fin.sell_psf, ",.0f") if fin else "N/A",
            "psf_source_quality": fin.psf_source_quality if fin else "N/A",
            "igr_median_psf": _v(fin.igr_median_psf, ",.0f") if fin else "N/A",
            "igr_record_count": _v(fin.igr_record_count) if fin else "N/A",
            "best_structure": fin.best_structure if fin else "N/A",
            "recommendation": fin.recommendation if fin else "N/A",
            "scenarios": _deal_scenarios_str(fin),
        },
        "legal_picture": {
            "risk_level": legal.risk_level if legal else "N/A",
            "zone": legal.zone if legal else "N/A",
            "zone_risk_level": legal.zone_risk_level if legal else "N/A",
            "guidance_value_psf": _v(legal.guidance_value_psf, ",.0f") if legal else "N/A",
            "litigation_risk": legal.litigation_risk if legal else "N/A",
            "land_use_conversion_needed": legal.land_use_conversion_needed if legal else "N/A",
            "inheritance_risk": legal.inheritance_risk if legal else "N/A",
            "details": _legal_flags_str(legal),
            "details_teaser": _legal_details_teaser(legal),
        },
        "land_picture": {
            "land_area_acres": _v(land.land_area_acres, ".2f") if land else "N/A",
            "zone": land.zone if land else "N/A",
            "far": _v(land.far, ".2f") if land else "N/A",
            "buildable_area_sqft": _v(land.buildable_area_sqft, ",.0f") if land else "N/A",
            "sellable_area_sqft": _v(land.sellable_area_sqft, ",.0f") if land else "N/A",
            "max_floors": _v(land.max_floors) if land else "N/A",
            "green_pct": _v(land.green_pct, ".1f") if land else "N/A",
            "meets_bda_minimum": land.meets_bda_minimum if land else "N/A",
            "development_readiness": land.development_readiness if land else "N/A",
            "flood_risk": land.flood_risk if land else "N/A",
            "flags": land.flags if land else [],
        },
        "demand_signals": {
            "demand_signal": demand.demand_signal if demand else "N/A",
            "demand_score": _v(demand.demand_score, ".2f") if demand else "N/A",
            "price_momentum_signal": demand.price_momentum_signal if demand else "N/A",
            "absorption_pct": _v(demand.absorption_pct, ".1f") if demand else "N/A",
            "listing_trend_30d_pct": _v(demand.listing_trend_30d_pct, ".1f") if demand else "N/A",
            "listing_trend_90d_pct": _v(demand.listing_trend_90d_pct, ".1f") if demand else "N/A",
            "new_rera_launches_90d": _v(demand.new_rera_launches_90d) if demand else "N/A",
            "developer_confidence_pct": _v(demand.developer_confidence_pct, ".1f") if demand else "N/A",
            "signals": demand.signals if demand else [],
        },
        "jdv_jv_targets": [],
    }
