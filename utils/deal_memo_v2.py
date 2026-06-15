"""
RE_OS — Deal Memo Generator V2 (Sprint 64 — Decision Layer)
============================================================
Generates a 7-section deal memo from an IntelPackage. Every number cites
its source within the IntelPackage. No DB calls, no external tools —
pure transformation of structured intelligence into a formatted deal memo.

Sections:
  1. Executive Summary
  2. Market Assessment
  3. Financial Analysis (purchase/JD/JV scenarios)
  4. Legal & Regulatory Assessment
  5. Land & Technical Assessment
  6. Demand & Timing Assessment
  7. Recommendation & Next Steps
"""

from datetime import datetime, timezone

from intelligence.registry import IntelPackage
from utils.intel_context import build_intel_context

__all__ = ["generate_deal_memo"]


def _section(title: str, body: str) -> dict:
    return {"title": title, "body": body.strip()}


def _executive_summary(pkg: IntelPackage, ctx: dict) -> str:
    m = ctx["market_pulse"]
    f = ctx["financial_evaluation"]
    legal = ctx["legal_picture"]
    d = ctx["demand_signals"]
    lines = [
        f"Survey {pkg.survey_no} in {pkg.market} — Deal type: {pkg.deal_type}.",
        f"Market pulse: avg listing \u20b9{m['avg_listing_psf']}/sqft, "
        f"{m['months_of_supply']} months of supply ({m['supply_label']}).",
        f"Financial: best structure is {f['best_structure']} — "
        f"see Financial Analysis section for IRR details.",
        f"Legal risk: {legal['risk_level']} — {legal['details_teaser']}.",
        f"Demand signal: {d['demand_signal']} (score {d['demand_score']}).",
        f"Source: IntelPackage collected at {pkg.collected_at}.",
    ]
    return "\n".join(lines)


def _market_assessment(pkg: IntelPackage, ctx: dict) -> str:
    m = ctx["market_pulse"]
    d = ctx["demand_signals"]
    lines = [
        f"Market: {pkg.market}",
        f"Avg listing PSF: \u20b9{m['avg_listing_psf']} (source: market_pulse.avg_listing_psf)",
        f"Median IGR PSF: \u20b9{m['median_igr_psf']} (source: market_pulse.median_igr_psf)",
        f"Total projects: {m['total_projects']} (source: market_pulse.total_projects)",
        f"Total units: {m['total_units']} (source: market_pulse.total_units)",
        f"Avg absorption: {m['avg_absorption_pct']}% (source: market_pulse.avg_absorption_pct)",
        f"Months of supply: {m['months_of_supply']} ({m['supply_label']})",
        f"Unique developers: {m['unique_developers']} (Grade-A: {m['grade_a_developers']})",
        f"Price momentum: {m['price_momentum_signal']}",
        f"Demand signal: {d['demand_signal']} (score: {d['demand_score']})",
        f"90-day RERA launches: {d['new_rera_launches_90d']}",
        f"Developer confidence: {d['developer_confidence_pct']}%",
    ]
    return "\n".join(lines)


def _financial_analysis(pkg: IntelPackage, ctx: dict) -> str:
    f = ctx["financial_evaluation"]
    lines = [
        f"Land area: {f['land_area_sqft']} sqft",
        f"Sellable area: {f['sellable_area_sqft']} sqft",
        f"Sell PSF: \u20b9{f['sell_psf']} (source: {f['psf_source_quality']})",
        f"IGR median PSF: \u20b9{f['igr_median_psf']} ({f['igr_record_count']} records)",
        "",
        "Deal scenarios:",
        f"{f['scenarios']}",
        "",
        f"Best structure: {f['best_structure']}",
        f"Recommendation: {f['recommendation']}",
    ]
    return "\n".join(lines)


def _legal_regulatory(pkg: IntelPackage, ctx: dict) -> str:
    legal = ctx["legal_picture"]
    lines = [
        f"Risk level: {legal['risk_level']} (source: legal_picture.risk_level)",
        f"Zone: {legal['zone']} — risk: {legal['zone_risk_level']}",
        f"Guidance value PSF: \u20b9{legal['guidance_value_psf']}",
        f"Litigation risk: {legal['litigation_risk']}",
        f"Land use conversion needed: {legal['land_use_conversion_needed']}",
        f"Inheritance risk: {legal['inheritance_risk']}",
        "",
        "Title risk details:",
        f"{legal['details']}",
    ]
    return "\n".join(lines)


def _land_technical(pkg: IntelPackage, ctx: dict) -> str:
    lp = ctx["land_picture"]
    lines = [
        f"Area: {lp['land_area_acres']} acres",
        f"Zone: {lp['zone']} — FAR: {lp['far']}",
        f"Buildable area: {lp['buildable_area_sqft']} sqft",
        f"Sellable area: {lp['sellable_area_sqft']} sqft",
        f"Max floors: {lp['max_floors']}",
        f"Green coverage: {lp['green_pct']}% (BDA min met: {lp['meets_bda_minimum']})",
        f"Development readiness: {lp['development_readiness']}",
        f"Flood risk: {lp['flood_risk']}",
    ]
    if lp["flags"]:
        lines.append(f"Flags: {'; '.join(lp['flags'])}")
    return "\n".join(lines)


def _demand_timing(pkg: IntelPackage, ctx: dict) -> str:
    d = ctx["demand_signals"]
    m = ctx["market_pulse"]
    lines = [
        f"Demand signal: {d['demand_signal']} (score: {d['demand_score']})",
        f"Price momentum: {d['price_momentum_signal']}",
        f"Absorption rate: {d['absorption_pct']}%",
        f"30d listing trend: {d['listing_trend_30d_pct']}%",
        f"Supply: {m['months_of_supply']} months ({m['supply_label']})",
        f"New RERA launches (90d): {d['new_rera_launches_90d']}",
    ]
    if d["signals"]:
        lines.append(f"Signals: {'; '.join(d['signals'])}")
    return "\n".join(lines)


def _recommendation(pkg: IntelPackage, ctx: dict) -> str:
    f = ctx["financial_evaluation"]
    legal = ctx["legal_picture"]
    lines = []
    if f["best_structure"] != "N/A":
        lines.append(f"Recommended structure: {f['best_structure']}")
        lines.append(f"Financial verdict: {f['recommendation']}")
    lines.append(f"Legal risk level: {legal['risk_level']}")
    lines.append(_legal_verdict_line(legal["risk_level"]))
    lines.append("")
    lines.append("Next steps:")
    lines.append("1. Confirm deal structure with landowner.")
    lines.append("2. Engage legal counsel for title due diligence.")
    lines.append("3. Verify development compliance with BDA/BBMP.")
    lines.append("4. Prepare term sheet based on financial analysis.")
    return "\n".join(lines)


def _legal_verdict_line(risk_level: str) -> str:
    if risk_level in ("CLEAR", "LOW"):
        return "Legal: PROCEED with standard due diligence."
    if risk_level in ("WARNING", "MEDIUM"):
        return "Legal: CONDITIONAL — resolve flagged items before closing."
    return "Legal: BLOCKED — do not proceed without legal resolution."


def generate_deal_memo(pkg: IntelPackage) -> dict:
    ctx = build_intel_context(pkg)

    sections = [
        _section("1. Executive Summary", _executive_summary(pkg, ctx)),
        _section("2. Market Assessment", _market_assessment(pkg, ctx)),
        _section("3. Financial Analysis", _financial_analysis(pkg, ctx)),
        _section("4. Legal & Regulatory Assessment", _legal_regulatory(pkg, ctx)),
        _section("5. Land & Technical Assessment", _land_technical(pkg, ctx)),
        _section("6. Demand & Timing Assessment", _demand_timing(pkg, ctx)),
        _section("7. Recommendation & Next Steps", _recommendation(pkg, ctx)),
    ]

    return {
        "title": f"Deal Memo — Survey {pkg.survey_no}, {pkg.market}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "survey_no": pkg.survey_no,
        "market": pkg.market,
        "deal_type": pkg.deal_type,
        "sections": sections,
        "module_status": pkg.module_status,
        "all_modules_success": pkg.all_modules_success,
    }
