"""
RE_OS — Analyst Agent
──────────────────────
The intelligence layer. Queries the database and produces market intelligence
that Jinu can act on. Uses OpenRouter free models for reasoning — saves
Claude tokens for strategic decisions.
"""

from crewai import Agent
from crewai.tools import BaseTool
from sqlalchemy import text
import json

from config.llm_router import get_analysis_llm
from utils.db import get_engine
from utils.feasibility import LandFeasibility, feasibility_summary
from utils.fsi_calculator import calculate_fsi
from utils.irr_model import calc_land_cost, calc_gdv, calc_irr, compare_scenarios
from agents.architect_agent import FSICalculatorTool, TypologyRecommenderTool, GreenCoverageTool


class MarketSummaryTool(BaseTool):
    name: str = "market_summary_query"
    description: str = (
        "Queries the database for a complete market intelligence summary "
        "for a given micro-market. Input: market name (e.g., 'Yelahanka'). "
        "Returns: inventory stats, pricing data, developer activity, absorption rates."
    )

    def _run(self, market_name: str) -> str:
        engine = get_engine()
        with engine.connect() as conn:
            # v_market_brief: one query for inventory + grade breakdown + risk counts
            # avg_listing_psf is the authoritative PSF from portal listings (RERA has no pricing)
            brief_row = conn.execute(
                text("""
                SELECT
                    total_projects,
                    total_units,
                    total_sold      AS sold_units,
                    total_unsold    AS unsold_units,
                    avg_absorption_pct,
                    avg_min_psf,
                    avg_max_psf,
                    avg_listing_psf,
                    unique_developers,
                    grade_a_developers,
                    grade_b_developers,
                    low_absorption_projects,
                    overdue_high_unsold_projects,
                    floor_psf,
                    ceiling_psf,
                    data_as_of
                FROM v_market_brief
                WHERE micro_market ILIKE :market
                LIMIT 1
            """),
                {"market": f"%{market_name}%"},
            ).fetchone()

            # Top projects by volume
            top_projects = conn.execute(
                text("""
                SELECT
                    r.project_name,
                    d.name as developer,
                    d.grade,
                    r.total_units,
                    r.sold_units,
                    r.unsold_units,
                    r.absorption_pct,
                    r.price_min_psf,
                    r.price_max_psf,
                    r.project_status,
                    r.possession_date
                FROM rera_projects r
                JOIN micro_markets m ON r.micro_market_id = m.id
                LEFT JOIN developers d ON r.developer_id = d.id
                WHERE m.name ILIKE :market AND r.is_active = TRUE
                ORDER BY r.total_units DESC NULLS LAST
                LIMIT 10
            """),
                {"market": f"%{market_name}%"},
            ).fetchall()

            # Risk flags: distressed projects with detail (names + risk type)
            risk_projects = conn.execute(
                text("""
                SELECT
                    r.project_name,
                    d.name as developer,
                    r.unsold_units,
                    r.absorption_pct,
                    r.possession_date,
                    CASE
                        WHEN r.possession_date < CURRENT_DATE AND r.unsold_units > 50
                        THEN 'OVERDUE + HIGH UNSOLD'
                        WHEN r.absorption_pct < 30 AND r.total_units > 100
                        THEN 'LOW ABSORPTION'
                        ELSE 'WATCH'
                    END as risk_type
                FROM rera_projects r
                JOIN micro_markets m ON r.micro_market_id = m.id
                LEFT JOIN developers d ON r.developer_id = d.id
                WHERE m.name ILIKE :market
                  AND r.is_active = TRUE
                  AND (r.absorption_pct < 40 OR r.possession_date < CURRENT_DATE)
                ORDER BY r.unsold_units DESC
                LIMIT 5
            """),
                {"market": f"%{market_name}%"},
            ).fetchall()

            # Kaveri — actual registered transaction prices (ground truth)
            kaveri_data = conn.execute(
                text("""
                SELECT
                    ROUND(AVG(kr.transaction_amount / NULLIF(kr.area_sqft, 0)), 0)
                        AS avg_actual_psf,
                    ROUND(AVG(CASE
                        WHEN kr.guidance_value > 0
                        THEN ((kr.transaction_amount - kr.guidance_value) / kr.guidance_value) * 100
                        ELSE NULL END), 1)
                        AS avg_guidance_gap_pct,
                    ROUND(AVG(kr.guidance_value / NULLIF(kr.area_sqft, 0)), 0)
                        AS avg_guidance_psf,
                    COUNT(kr.id)                         AS recent_registrations,
                    MAX(kr.transaction_date)             AS latest_registration_date,
                    MIN(kr.transaction_amount / NULLIF(kr.area_sqft, 0))
                        AS min_actual_psf,
                    MAX(kr.transaction_amount / NULLIF(kr.area_sqft, 0))
                        AS max_actual_psf
                FROM kaveri_registrations kr
                JOIN micro_markets m ON kr.micro_market_id = m.id
                WHERE m.name ILIKE :market
                  AND kr.transaction_date >= CURRENT_DATE - INTERVAL '180 days'
            """),
                {"market": f"%{market_name}%"},
            ).fetchone()

            # Guidance values — current circle rates
            gv_summary = conn.execute(
                text("""
                SELECT
                    locality,
                    property_type,
                    road_type,
                    guidance_value_psf,
                    effective_from
                FROM guidance_values gv
                JOIN micro_markets m ON gv.micro_market_id = m.id
                WHERE m.name ILIKE :market
                ORDER BY guidance_value_psf DESC
                LIMIT 10
            """),
                {"market": f"%{market_name}%"},
            ).fetchall()

            result = {
                "market": market_name,
                "inventory": dict(brief_row._mapping) if brief_row else {},
                "top_projects": [dict(r._mapping) for r in top_projects],
                "risk_flags": [dict(r._mapping) for r in risk_projects],
                "kaveri_transactions": (
                    dict(kaveri_data._mapping) if kaveri_data else {}
                ),
                "guidance_values": [dict(r._mapping) for r in gv_summary],
            }

            return json.dumps(result, indent=2, default=str)


class CompetitorAnalysisTool(BaseTool):
    name: str = "competitor_analysis"
    description: str = (
        "Analyzes competitor developer activity in a micro-market. "
        "Input: market name. "
        "Returns: ranked competitor scorecard with units, absorption, pricing, delays."
    )

    def _run(self, market_name: str) -> str:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                SELECT
                    d.name as developer,
                    d.grade,
                    COUNT(r.id) as projects_in_market,
                    SUM(r.total_units) as total_units,
                    SUM(r.sold_units) as sold_units,
                    ROUND(AVG(r.absorption_pct), 1) as avg_absorption_pct,
                    ROUND(AVG(r.price_min_psf), 0) as avg_min_psf,
                    ROUND(AVG(r.price_max_psf), 0) as avg_max_psf,
                    ROUND(AVG(r.delay_months), 1) as avg_delay_months
                FROM rera_projects r
                JOIN micro_markets m ON r.micro_market_id = m.id
                LEFT JOIN developers d ON r.developer_id = d.id
                WHERE m.name ILIKE :market AND r.is_active = TRUE
                GROUP BY d.id, d.name, d.grade
                ORDER BY total_units DESC
            """),
                {"market": f"%{market_name}%"},
            ).fetchall()

            return json.dumps([dict(r._mapping) for r in result], indent=2, default=str)


class DistressedDeveloperListTool(BaseTool):
    name: str = "distressed_developer_list"
    description: str = (
        "Finds potential distressed/JD-JV target developers in a micro-market. "
        "Input: market name. "
        "Returns: stalled project count, debt/distress flags, and last launch date by developer."
    )

    def _run(self, market_name: str) -> str:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                SELECT
                    d.name AS developer,
                    d.grade,
                    COUNT(r.id) FILTER (
                        WHERE COALESCE(r.delay_months, 0) >= 12
                           OR (r.possession_date < CURRENT_DATE AND COALESCE(r.unsold_units, 0) > 50)
                           OR (COALESCE(r.absorption_pct, 100) < 35 AND COALESCE(r.total_units, 0) >= 100)
                    ) AS stalled_project_count,
                    COUNT(r.id) FILTER (
                        WHERE LOWER(COALESCE(r.risk_flags::text, '')) ~ '(debt|insolvency|nclt|default|restructur|cashflow|liquidity|distress)'
                    ) AS debt_flagged_projects,
                    MAX(r.launch_date) AS last_launch_date,
                    ROUND(AVG(r.delay_months), 1) AS avg_delay_months,
                    SUM(COALESCE(r.unsold_units, 0)) AS total_unsold_units
                FROM rera_projects r
                JOIN micro_markets m ON r.micro_market_id = m.id
                LEFT JOIN developers d ON r.developer_id = d.id
                WHERE m.name ILIKE :market
                  AND r.is_active = TRUE
                  AND d.name IS NOT NULL
                GROUP BY d.id, d.name, d.grade
                HAVING COUNT(r.id) > 0
                ORDER BY stalled_project_count DESC, debt_flagged_projects DESC, total_unsold_units DESC
                LIMIT 15
            """),
                {"market": f"%{market_name}%"},
            ).fetchall()

            return json.dumps([dict(r._mapping) for r in rows], indent=2, default=str)


class ReportGeneratorTool(BaseTool):
    name: str = "generate_market_report"
    description: str = (
        "Generates a formatted market intelligence brief for a micro-market. "
        "Input: JSON string with market data (from market_summary_query). "
        "Output: formatted text report ready for Jinu."
    )

    def _run(self, market_data_json: str) -> str:
        try:
            data = json.loads(market_data_json)
        except (json.JSONDecodeError, TypeError):
            return (
                "RE_OS Market Intelligence Report\n\n"
                "No data available — the query returned empty results. "
                "Try running the pipeline again after more data has been scraped."
            )
        market = data.get("market", "Unknown")
        inv = data.get("inventory", {})
        projects = data.get("top_projects", [])
        risks = data.get("risk_flags", [])

        def _fmt(val, fmt=",.0f"):
            """Format a value safely — returns 'N/A' if None."""
            if val is None:
                return "N/A"
            try:
                # If the value is a whole number, show it without decimals
                if isinstance(val, (int, float)) and val == int(val):
                    return f"{int(val):,}"
                v = float(val)
                if fmt == ",.0f":
                    return f"{v:,.0f}"
                elif fmt == ",":
                    return f"{v:,}"
                else:
                    return str(v)
            except (ValueError, TypeError):
                return str(val)

        lines = [
            f"═══ RE_OS | {market.upper()} MARKET INTELLIGENCE ═══",
            f"Generated: {__import__('datetime').datetime.now().strftime('%d %b %Y, %H:%M IST')}",
            "",
            "── INVENTORY OVERVIEW ──",
            f"Active projects:    {_fmt(inv.get('total_projects', 0))}",
            f"Total units:        {_fmt(inv.get('total_units', 0), ',')}",
            f"Sold:               {_fmt(inv.get('sold_units', 0), ',')}",
            f"Unsold:             {_fmt(inv.get('unsold_units', 0), ',')}",
            f"Avg absorption:     {_fmt(inv.get('avg_absorption_pct', 0), '.1f')}%",
            f"Price range:        ₹{_fmt(inv.get('avg_min_psf', 0))} – ₹{_fmt(inv.get('avg_max_psf', 0))} psf",
            f"Active developers:  {_fmt(inv.get('unique_developers', 0))}",
            "",
            "── TOP PROJECTS ──",
        ]

        for p in projects[:5]:
            lines.append(
                f"• {p.get('project_name', 'N/A')} | {p.get('developer', 'N/A')} [{p.get('grade', '?')}]"
            )
            lines.append(
                f"  {_fmt(p.get('sold_units', 0), ',')}/{_fmt(p.get('total_units', 0), ',')} units sold "
                f"({_fmt(p.get('absorption_pct', 0), '.1f')}%) | "
                f"₹{_fmt(p.get('price_min_psf', 0))}–{_fmt(p.get('price_max_psf', 0))} psf"
            )

        if risks:
            lines.extend(["", "── RISK FLAGS ──"])
            for r in risks:
                lines.append(
                    f"⚠ {r.get('project_name', 'N/A')} — {r.get('risk_type', 'WATCH')}"
                )
                lines.append(
                    f"  {r.get('unsold_units', 0)} unsold | {r.get('absorption_pct', 0)}% absorbed"
                )

        return "\n".join(lines)


class FeasibilityTool(BaseTool):
    name: str = "land_feasibility"
    description: str = (
        "Runs a quick land acquisition feasibility check. "
        "Input: JSON with keys 'land_area_sqft' (float), 'land_cost_psf' (float), "
        "'target_sell_psf' (float, use avg_listing_psf from market_summary_query), "
        "and optionally 'construction_cost_psf', 'efficiency_ratio', 'fsi', "
        "'timeline_months'. "
        "Returns: land cost, construction cost, GDV, break-even PSF, profit margin %, "
        "simple IRR %, and GO / MARGINAL / NO-GO verdict."
    )

    def _run(self, params_json: str) -> str:
        try:
            params = json.loads(params_json)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "Invalid JSON input"})
        f = LandFeasibility(
            land_area_sqft=float(params.get("land_area_sqft", 0)),
            land_cost_psf=float(params.get("land_cost_psf", 0)),
            construction_cost_psf=float(params.get("construction_cost_psf", 2200)),
            target_sell_psf=float(params.get("target_sell_psf", 0)),
            efficiency_ratio=float(params.get("efficiency_ratio", 0.65)),
            fsi=float(params.get("fsi", 2.0)),
            timeline_months=int(params.get("timeline_months", 36)),
        )
        return json.dumps(feasibility_summary(f), indent=2)


class IntelSearchTool(BaseTool):
    name: str = "intel_search"
    description: str = (
        "Search past intel reports for relevant context. "
        "Input: JSON with 'query' (str — e.g. 'Yelahanka absorption trend Q1 2026'), "
        "'market' (optional — Yelahanka/Devanahalli/Hebbal). "
        "Returns top-5 excerpts from past reports with source and relevance score. "
        "Call before forming your market assessment to leverage accumulated intelligence."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({
                "error": "intel_search expects a JSON object with 'query' (str) and optional 'market' (str)",
                "results": [],
            })
        try:
            from utils.embedder import IntelEmbedder
            q = str(params.get("query", "")).strip()
            market = params.get("market")
            if not q:
                return json.dumps({"results": [], "note": "intel_search: empty query — provide a 'query' string"})
            if market and market.lower() not in ("yelahanka", "devanahalli", "hebbal"):
                return json.dumps({"results": [], "note": f"intel_search: unknown market '{market}' — use Yelahanka, Devanahalli, or Hebbal"})
            results = IntelEmbedder().search(q, market=market, n=5)
            return json.dumps({"results": results, "count": len(results)}, indent=2)
        except Exception as e:
            return json.dumps({"error": f"intel_search failed: {e}", "results": []})


class FeasibilityAnalystTool(BaseTool):
    name: str = "full_feasibility"
    description: str = (
        "Run a complete LLS feasibility model for a land parcel. "
        "Input: JSON with 'land_area_sqft' (float), 'sell_psf' (float -- use avg_listing_psf from "
        "market_summary_query), 'guidance_value_psf' (float -- from kaveri data, or use 4000 as default "
        "for Yelahanka), 'negotiation_discount_pct' (float, default 10), 'efficiency_ratio' (default 0.65), "
        "'zone' (default R2), 'market' (market name). "
        "Returns: land cost, construction cost, GDV, base/bull/bear IRR, verdict, recommendation."
    )

    def _run(self, input_str: str) -> str:
        try:
            params = json.loads(input_str)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "invalid JSON input"})
        try:
            land_area   = float(params.get("land_area_sqft", 0))
            sell_psf    = float(params.get("sell_psf", 0))
            if sell_psf <= 0:
                return json.dumps({"error": "sell_psf must be > 0 — use avg_listing_psf from market_summary_query"})
            gv_psf      = float(params.get("guidance_value_psf", 4000))
            disc        = float(params.get("negotiation_discount_pct", 10.0))
            efficiency  = float(params.get("efficiency_ratio", 0.65))
            zone        = str(params.get("zone", "R2"))
            market      = params.get("market")

            fsi_r       = calculate_fsi(land_area, zone, efficiency, market)
            lc_r        = calc_land_cost(land_area, gv_psf, disc)
            scenarios   = compare_scenarios(lc_r.negotiated_land_cost, fsi_r.sellable_area_sqft, sell_psf)

            return json.dumps({
                "inputs": {
                    "land_area_sqft": land_area,
                    "zone": zone,
                    "market": market,
                    "sell_psf": sell_psf,
                    "guidance_value_psf": gv_psf,
                    "negotiation_discount_pct": disc,
                },
                "fsi": {
                    "buildable_sqft": fsi_r.buildable_area_sqft,
                    "sellable_sqft": fsi_r.sellable_area_sqft,
                    "max_floors": fsi_r.max_floors,
                },
                "financials": {
                    "land_cost": scenarios.base.land_cost,
                    "construction_cost": scenarios.base.construction_cost,
                    "total_project_cost": scenarios.base.total_project_cost,
                    "equity_required": scenarios.base.equity_required,
                    "gdv": scenarios.base.gdv,
                },
                "scenarios": {
                    "base":  {"irr_pct": scenarios.base.simple_irr_pct,  "verdict": scenarios.base.verdict},
                    "bull":  {"irr_pct": scenarios.bull.simple_irr_pct,  "verdict": scenarios.bull.verdict},
                    "bear":  {"irr_pct": scenarios.bear.simple_irr_pct,  "verdict": scenarios.bear.verdict},
                },
                "recommendation": scenarios.recommendation,
            }, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})


def create_analyst_agent() -> Agent:
    return Agent(
        role="Real Estate Market Intelligence Analyst",
        goal=(
            "Transform raw database records into market intelligence that a "
            "real estate developer-builder can act on immediately. "
            "Identify absorption trends, price movements, developer weaknesses, "
            "market white space, and risk flags. "
            "Be precise. Be specific. No vague observations."
        ),
        backstory=(
            "You are a Karnataka real estate analyst with deep domain knowledge. "
            "You've tracked Bengaluru micro-markets for a decade. "
            "You know that Yelahanka's north corridor is a different market from "
            "Yelahanka New Town. You know what an absorption rate below 40% signals. "
            "You know the difference between Grade A developer unsold inventory "
            "(pricing issue) vs Grade C developer unsold inventory (product/trust issue). "
            "You produce intelligence that leads to decisions, not reports that get filed. "
            "STRICT TOOL CALL SEQUENCE: Always call tools in this exact order with no skips "
            "and no repeats: (1) market_summary_query, (2) competitor_analysis, "
            "(3) distressed_developer_list, (4) generate_market_report. "
            "If a tool returns empty data, continue to the next tool once; do not retry. "
            "ADJUNCT TOOL — land_feasibility: Call only when asked to evaluate a specific "
            "land acquisition. Use avg_listing_psf from market_summary_query as "
            "target_sell_psf. Not part of the standard pipeline sequence. "
            "ADJUNCT TOOLS — fsi_calculator / typology_recommender / green_coverage: Call only when evaluating a specific land parcel. Use avg_listing_psf from market_summary_query as input to typology_recommender. Not part of standard pipeline sequence. "
            "ADJUNCT TOOL — full_feasibility: Call when financial feasibility of a specific land parcel is requested. "
            "Returns base/bull/bear IRR with GO/MARGINAL/NO-GO verdict. "
            "ADJUNCT TOOL — intel_search: Search past intel reports for relevant context before forming market assessment."
        ),
        tools=[
            MarketSummaryTool(),
            CompetitorAnalysisTool(),
            DistressedDeveloperListTool(),
            ReportGeneratorTool(),
            FeasibilityTool(),
            FSICalculatorTool(),
            TypologyRecommenderTool(),
            GreenCoverageTool(),
            FeasibilityAnalystTool(),
            IntelSearchTool(),
        ],
        llm=get_analysis_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=3,
    )
