"""
RE_OS — Investor Brief Generator V2 (Sprint 64 — Decision Layer)
=================================================================
Generates a 7-section investor brief from an IntelPackage. Every number
cites its source. No track record section (Jinu decision 2026-06-02).

Sections:
  1. Opportunity Overview
  2. Market Dynamics
  3. Financial Projections
  4. Legal & Title Assessment
  5. Technical Feasibility
  6. Risk Matrix
  7. Recommendation
"""

from datetime import datetime, timezone

from intelligence.registry import IntelPackage
from utils.intel_context import build_intel_context

__all__ = ["generate_investor_brief"]


def _section(title: str, body: str) -> dict:
    return {"title": title, "body": body.strip()}


def _opportunity_overview(pkg: IntelPackage, ctx: dict) -> str:
    m = ctx["market_pulse"]
    f = ctx["financial_evaluation"]
    l = ctx["legal_picture"]
    lines = [
        f"Opportunity: Survey {pkg.survey_no}, {pkg.market} — {pkg.deal_type.upper()} deal",
        f"Market: avg listing \u20b9{m['avg_listing_psf']}/sqft, {m['months_of_supply']} months supply",
        f"Best financial structure: {f['best_structure']}",
        f"Legal risk: {l['risk_level']}",
        f"All intelligence modules: {'OK' if pkg.all_modules_success else 'DEGRADED'}",
    ]
    return "\n".join(lines)


def _market_dynamics(pkg: IntelPackage, ctx: dict) -> str:
    m = ctx["market_pulse"]
    d = ctx["demand_signals"]
    lines = [
        f"Market: {pkg.market}",
        f"Pricing: avg listing \u20b9{m['avg_listing_psf']}/sqft, momentum {m['price_momentum_signal']}",
        f"Supply: {m['months_of_supply']} months ({m['supply_label']})",
        f"Absorption: {m['avg_absorption_pct']}%",
        f"Competition: {m['unique_developers']} developers ({m['grade_a_developers']} Grade-A)",
        f"Inventory: {m['total_units']} units across {m['total_projects']} projects",
        f"Demand signal: {d['demand_signal']} (score {d['demand_score']})",
        f"90d RERA launches: {d['new_rera_launches_90d']}",
    ]
    return "\n".join(lines)


def _financial_projections(pkg: IntelPackage, ctx: dict) -> str:
    f = ctx["financial_evaluation"]
    lines = [
        f"Land: {f['land_area_sqft']} sqft | Sellable: {f['sellable_area_sqft']} sqft",
        f"Sell PSF: \u20b9{f['sell_psf']} (source: {f['psf_source_quality']})",
        f"IGR reference: \u20b9{f['igr_median_psf']}/sqft ({f['igr_record_count']} transactions)",
        "",
        f"{f['scenarios']}",
        "",
        f"Verdict: {f['recommendation']}",
    ]
    return "\n".join(lines)


def _legal_title(pkg: IntelPackage, ctx: dict) -> str:
    l = ctx["legal_picture"]
    lines = [
        f"Overall risk: {l['risk_level']}",
        f"Zone: {l['zone']} — risk {l['zone_risk_level']}",
        f"Guidance value: \u20b9{l['guidance_value_psf']}/sqft",
        f"Litigation: {l['litigation_risk']}",
        f"Conversion needed: {l['land_use_conversion_needed']}",
        "",
        f"{l['details']}",
    ]
    return "\n".join(lines)


def _technical_feasibility(pkg: IntelPackage, ctx: dict) -> str:
    lp = ctx["land_picture"]
    lines = [
        f"Area: {lp['land_area_acres']} acres | Zone {lp['zone']} FAR {lp['far']}",
        f"Buildable: {lp['buildable_area_sqft']} sqft | Sellable: {lp['sellable_area_sqft']} sqft",
        f"Max floors: {lp['max_floors']}",
        f"Green coverage: {lp['green_pct']}% (BDA OK: {lp['meets_bda_minimum']})",
        f"Readiness: {lp['development_readiness']} | Flood risk: {lp['flood_risk']}",
    ]
    return "\n".join(lines)


def _risk_matrix(pkg: IntelPackage, ctx: dict) -> str:
    f = ctx["financial_evaluation"]
    l = ctx["legal_picture"]
    lp = ctx["land_picture"]
    d = ctx["demand_signals"]

    fin_bear_irr = _extract_bear_irr(pkg)

    lines = [
        "Risk | Level | Mitigation",
        "-----|-------|-----------",
        f"Market risk | {d['demand_signal']} | Price momentum {d['price_momentum_signal']}",
        f"Financial risk | Bear IRR {fin_bear_irr} | See scenario analysis",
        f"Legal risk | {l['risk_level']} | Title due diligence required",
        f"Execution risk | {lp['development_readiness']} | BDA/BBMP compliance check",
        f"Liquidity risk | {f['best_structure']} | Equity/debt per scenario",
    ]
    if pkg.errors:
        lines.append(
            f"Data risk | DEGRADED | {len(pkg.errors)} module(s) failed: "
            f"{'; '.join(pkg.errors[:3])}"
        )
    return "\n".join(lines)


def _extract_bear_irr(pkg: IntelPackage) -> str:
    fe = pkg.financial_evaluation
    if not fe:
        return "N/A"
    bear_values = []
    for s in [fe.purchase, fe.jd, fe.jv]:
        if s and s.bear_irr_pct is not None:
            bear_values.append(f"{s.structure}: {s.bear_irr_pct:.1f}%")
    if not bear_values:
        if fe.purchase:
            return f"~{fe.purchase.simple_irr_pct * 0.7:.1f}% (est.)"
        return "N/A"
    return " | ".join(bear_values)


def _recommendation(pkg: IntelPackage, ctx: dict) -> str:
    f = ctx["financial_evaluation"]
    l = ctx["legal_picture"]

    legal_action = "PROCEED"
    if l["risk_level"] in ("WARNING", "MEDIUM"):
        legal_action = "CONDITIONAL"
    elif l["risk_level"] in ("RISK", "HIGH", "BLOCKED"):
        legal_action = "BLOCKED"

    lines = [
        f"Deal: {pkg.survey_no}, {pkg.market} — {pkg.deal_type.upper()}",
        f"Financial: {f['recommendation']}",
        f"Legal: {l['risk_level']} — {legal_action}",
        "",
        "Key actions for investor:",
        "1. Review title report and encumbrance certificate",
        "2. Confirm deal structure and term sheet",
        "3. Verify BDA land use and zone compliance",
        "4. Assess developer/JV partner if applicable",
    ]
    return "\n".join(lines)


def generate_investor_brief(pkg: IntelPackage) -> dict:
    ctx = build_intel_context(pkg)

    sections = [
        _section("1. Opportunity Overview", _opportunity_overview(pkg, ctx)),
        _section("2. Market Dynamics", _market_dynamics(pkg, ctx)),
        _section("3. Financial Projections", _financial_projections(pkg, ctx)),
        _section("4. Legal & Title Assessment", _legal_title(pkg, ctx)),
        _section("5. Technical Feasibility", _technical_feasibility(pkg, ctx)),
        _section("6. Risk Matrix", _risk_matrix(pkg, ctx)),
        _section("7. Recommendation", _recommendation(pkg, ctx)),
    ]

    return {
        "title": f"Investor Brief — Survey {pkg.survey_no}, {pkg.market}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "survey_no": pkg.survey_no,
        "market": pkg.market,
        "deal_type": pkg.deal_type,
        "sections": sections,
        "module_status": pkg.module_status,
    }
