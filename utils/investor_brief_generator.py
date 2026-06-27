"""
RE_OS — Investor Brief Generator (Sprint 143, GATE-143)

Reads from DB only — no LLM calls. Deterministic, fast, cacheable.
Produces 6-section dict for API responses and markdown formatting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text as _sa_text

logger = logging.getLogger("re_os.investor_brief")

_SELLABLE_FSI = 0.65
_FSI_FACTOR = 2.5
_QUERY_TIMEOUT_S = 10.0
_DEPT_DISPLAY: dict[str, str] = {
    "bd": "BD",
    "finance": "Finance",
    "legal": "Legal",
    "ops": "Ops",
    "engineering": "Engineering",
}


@dataclass
class InvestorBrief:
    market_overview: dict[str, Any]
    competitive_landscape: dict[str, Any]
    financial_summary: dict[str, Any]
    supply_risk: dict[str, Any]
    assembly_alerts: list[dict[str, Any]]
    board_verdict: dict[str, Any]
    generated_at: str = ""
    project_name: str = ""
    market: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "project_name": self.project_name,
            "generated_at": self.generated_at,
            "market_overview": self.market_overview,
            "competitive_landscape": self.competitive_landscape,
            "financial_summary": self.financial_summary,
            "supply_risk": self.supply_risk,
            "assembly_alerts": self.assembly_alerts,
            "board_verdict": self.board_verdict,
        }


class InvestorBriefGenerator:
    """Generates investor-ready brief sections from live DB data."""

    def generate(
        self,
        market: str,
        project_name: str = "RE_OS Query",
        land_cost_cr: float = 0.0,
        area_acres: float = 0.0,
    ) -> InvestorBrief:
        now = datetime.now(timezone.utc)
        from utils.db import get_engine

        engine = get_engine()

        with engine.connect() as conn:
            conn = conn.execution_options(timeout=_QUERY_TIMEOUT_S)
            market_overview = self._market_overview(conn, market)
            competitive = self._competitive_landscape(conn, market)
            supply = self._supply_risk(conn, market)
            assembly = self._assembly_alerts(conn, market)
            board = self._board_verdict(conn, market)
            avg_psf = market_overview.get("avg_psf", 0.0) or 0.0
            financial = self._financial_summary(
                land_cost_cr, area_acres, avg_psf, market, conn
            )

        return InvestorBrief(
            market=market,
            project_name=project_name,
            generated_at=now.isoformat(timespec="seconds"),
            market_overview=market_overview,
            competitive_landscape=competitive,
            financial_summary=financial,
            supply_risk=supply,
            assembly_alerts=assembly,
            board_verdict=board,
        )

    # ── Section builders ──────────────────────────────────────────────────

    def _market_overview(
        self, conn, market: str
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        row = conn.execute(
            _sa_text("""
                SELECT
                    ROUND(MIN(l.price_psf)::numeric, 0) AS psf_min,
                    ROUND(AVG(l.price_psf)::numeric, 0) AS avg_psf,
                    ROUND(MAX(l.price_psf)::numeric, 0) AS psf_max,
                    COUNT(l.id) AS listing_count
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.name = :m AND l.price_psf > 0
            """),
            {"m": market},
        ).fetchone()
        if row:
            result["psf_min"] = float(row[0]) if row[0] else None
            result["avg_psf"] = float(row[1]) if row[1] else None
            result["psf_max"] = float(row[2]) if row[2] else None
            result["listing_count"] = int(row[3]) if row[3] else 0

        rera_row = conn.execute(
            _sa_text("""
                SELECT COUNT(*), COUNT(*) FILTER (WHERE status ILIKE 'active')
                FROM rera_projects rp
                JOIN micro_markets mm ON mm.id = rp.micro_market_id
                WHERE mm.name = :m
            """),
            {"m": market},
        ).fetchone()
        result["rera_projects"] = int(rera_row[0]) if rera_row else 0
        result["active_projects"] = int(rera_row[1]) if rera_row else 0

        result["psf_trend"] = self._psf_trend(conn, market)

        return result

    def _psf_trend(self, conn, market: str) -> dict[str, Any]:
        try:
            from utils.psf_forecaster import PSFForecaster

            f = PSFForecaster()
            forecast = f.forecast(market)
            trend = getattr(forecast, "trend_direction", None) or "unknown"
            current = getattr(forecast, "current_psf", None)
            f6m = getattr(forecast, "forecast_6m", None)
            return {
                "direction": trend,
                "current_psf": float(current) if current else None,
                "forecast_6m": float(f6m) if f6m else None,
            }
        except Exception:
            return {"direction": "unknown", "current_psf": None, "forecast_6m": None}

    def _competitive_landscape(
        self, conn, market: str
    ) -> dict[str, Any]:
        rows = conn.execute(
            _sa_text("""
                SELECT d.name, d.grade,
                       ROUND(AVG(rp.price_min_psf)::numeric, 0) AS min_psf,
                       ROUND(AVG(rp.price_max_psf)::numeric, 0) AS max_psf,
                       COUNT(rp.id) AS projects
                FROM developers d
                JOIN rera_projects rp ON rp.developer_id = d.id
                JOIN micro_markets mm ON mm.id = rp.micro_market_id
                WHERE mm.name = :m
                  AND d.grade IN ('A', 'A+')
                  AND rp.price_min_psf IS NOT NULL
                GROUP BY d.name, d.grade
                ORDER BY d.grade, d.name
            """),
            {"m": market},
        ).fetchall()

        return {
            "grade_a_count": len(rows),
            "developers": [
                {
                    "name": r[0],
                    "grade": r[1],
                    "psf_range": (float(r[2]) if r[2] else None, float(r[3]) if r[3] else None),
                    "projects": int(r[4]),
                }
                for r in rows
            ],
        }

    def _financial_summary(
        self,
        land_cost_cr: float,
        area_acres: float,
        avg_psf: float,
        market: str,
        conn,
    ) -> dict[str, Any]:
        if not land_cost_cr or not area_acres or not avg_psf:
            return {
                "status": "insufficient_inputs",
                "note": "Provide land_cost_cr and area_acres with a market that has PSF data",
            }

        from utils.irr_model import calc_irr

        sellable = area_acres * 43560 * _SELLABLE_FSI * _FSI_FACTOR
        land_cost_abs = land_cost_cr * 1_00_00_000

        scenarios = {}
        for label, multiplier in [("bear", 0.8), ("base", 1.0), ("bull", 1.2)]:
            psf = avg_psf * multiplier
            r = calc_irr(land_cost_abs, sellable, psf)
            scenarios[label] = {
                "land_cost_cr": land_cost_cr,
                "sell_psf": round(psf, 0),
                "irr_pct": r.simple_irr_pct,
                "payback_months": r.payback_months,
                "verdict": r.verdict,
                "profit_margin_pct": r.profit_margin_pct,
                "gdv_cr": round(r.gdv / 1_00_00_000, 2),
                "equity_required_cr": round(r.equity_required / 1_00_00_000, 2),
            }

        return {
            "status": "computed",
            "land_cost_cr": land_cost_cr,
            "area_acres": area_acres,
            "sellable_sqft": round(sellable, 0),
            "avg_market_psf": round(avg_psf, 0),
            "scenarios": scenarios,
        }

    def _supply_risk(
        self, conn, market: str
    ) -> dict[str, Any]:
        row = conn.execute(
            _sa_text("""
                SELECT COALESCE(SUM(estimated_units), 0)
                FROM supply_pipeline
                WHERE market = :m
            """),
            {"m": market},
        ).fetchone()
        pipeline_units = int(row[0]) if row and row[0] else 0

        active_row = conn.execute(
            _sa_text("""
                SELECT COALESCE(SUM(rp.total_units - rp.unsold_units), 0)
                FROM rera_projects rp
                JOIN micro_markets mm ON mm.id = rp.micro_market_id
                WHERE mm.name = :m
                  AND rp.total_units IS NOT NULL
                  AND rp.unsold_units IS NOT NULL
            """),
            {"m": market},
        ).fetchone()
        active_units = int(active_row[0]) if active_row and active_row[0] else 0

        weeks_of_inventory = 0.0
        if active_units > 0:
            weeks_of_inventory = round((pipeline_units / active_units) * 52, 1)

        return {
            "pipeline_units": pipeline_units,
            "active_units": active_units,
            "weeks_of_inventory": weeks_of_inventory,
        }

    def _assembly_alerts(
        self, conn, market: str
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            _sa_text("""
                SELECT buyer_name_norm, village, parcel_count,
                       total_extent_sqft, total_consideration_inr,
                       first_deed_date, last_deed_date, confidence,
                       survey_nos
                FROM assembly_signals
                WHERE market = :m
                  AND status = 'open'
                ORDER BY confidence DESC
                LIMIT 20
            """),
            {"m": market},
        ).fetchall()

        return [
            {
                "buyer": r[0],
                "village": r[1],
                "parcel_count": int(r[2]) if r[2] else 0,
                "total_extent_sqft": float(r[3]) if r[3] else 0,
                "total_consideration_cr": round(float(r[4] or 0) / 1_00_00_000, 2) if r[4] else None,
                "first_deed": str(r[5]) if r[5] else "",
                "last_deed": str(r[6]) if r[6] else "",
                "confidence": float(r[7]) if r[7] else 0,
                "survey_nos": r[8] if r[8] else [],
            }
            for r in rows
        ]

    def _board_verdict(
        self, conn, market: str
    ) -> dict[str, Any]:
        row = conn.execute(
            _sa_text("""
                SELECT decision_flag, context_summary, created_at,
                       response_time_s, bd_assessment, finance_assessment,
                       legal_assessment, ops_assessment, engineering_assessment
                FROM board_sessions
                WHERE market = :m
                  AND decision_flag IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"m": market},
        ).fetchone()

        if not row:
            return {"status": "no_verdict"}

        return {
            "status": "found",
            "decision_flag": row[0],
            "context_summary": (row[1] or "")[:500],
            "created_at": str(row[2]) if row[2] else "",
            "response_time_s": float(row[3]) if row[3] else None,
            "assessments": {
                "bd": (row[4] or "")[:200],
                "finance": (row[5] or "")[:200],
                "legal": (row[6] or "")[:200],
                "ops": (row[7] or "")[:200],
                "engineering": (row[8] or "")[:200],
            },
        }


# ── Formatters ──────────────────────────────────────────────────────────────


def _fmt_psf(val: object) -> str:
    if val is None or val == 0:
        return "N/A"
    try:
        return f"\u20b9{float(val):,.0f}"
    except (ValueError, TypeError):
        return "N/A"


def _fmt_cr(val: object) -> str:
    if val is None or val == 0:
        return "N/A"
    try:
        return f"\u20b9{float(val):.1f} Cr"
    except (ValueError, TypeError):
        return "N/A"


def _fmt_verdict(val: object) -> str:
    if val is None or val == "" or val == "no_verdict":
        return "None on record"
    return str(val)


def format_markdown(brief: InvestorBrief) -> str:
    lines = [
        f"# RE_OS Market Intelligence \u2014 {brief.market}",
        f"**Land & Life Space** | {brief.generated_at[:10]}",
        f"**Project:** {brief.project_name}",
        "",
        "---",
        "",
        "## 1. Market Overview",
        "",
    ]
    mo = brief.market_overview
    lines.append(f"- **PSF Range:** {_fmt_psf(mo.get('psf_min'))} \u2013 {_fmt_psf(mo.get('psf_max'))}")
    lines.append(f"- **Average PSF:** {_fmt_psf(mo.get('avg_psf'))}")
    lines.append(f"- **Listings:** {mo.get('listing_count', 0)}")
    lines.append(f"- **RERA Projects:** {mo.get('rera_projects', 0)} total, {mo.get('active_projects', 0)} active")

    trend = mo.get("psf_trend", {})
    if trend:
        dir_text = trend.get("direction", "unknown")
        current = trend.get("current_psf")
        f6m = trend.get("forecast_6m")
        if dir_text == "unknown":
            lines.append("- **PSF Trend:** \u2139\ufe0f Insufficient data to determine PSF trend.")
        else:
            lines.append(f"- **PSF Trend:** {dir_text}")
        lines.append(f"- **Current PSF (model):** {_fmt_psf(current)}")
        lines.append(f"- **6-Month Forecast:** {_fmt_psf(f6m)}")

    lines += [
        "",
        "## 2. Competitive Landscape",
        "",
    ]
    cl = brief.competitive_landscape
    lines.append(f"- **Grade A Developers Active:** {cl.get('grade_a_count', 0)}")
    for d in cl.get("developers", []):
        psf_range = d.get("psf_range")
        if psf_range and psf_range[0] and psf_range[1]:
            lines.append(
                f"  - **{d['name']}** (Grade {d['grade']}) \u2014 "
                f"{_fmt_psf(psf_range[0])}\u2013{_fmt_psf(psf_range[1])}, "
                f"{d['projects']} projects"
            )
        else:
            lines.append(f"  - **{d['name']}** (Grade {d['grade']}) \u2014 {d['projects']} projects")

    lines += [
        "",
        "## 3. Financial Summary",
        "",
    ]
    fs = brief.financial_summary
    if fs.get("status") == "insufficient_inputs":
        lines.append(f"*{fs.get('note', 'Provide inputs to compute financial summary.')}*")
    else:
        scenarios = fs.get("scenarios", {})
        lines.append(f"- **Land Cost:** {_fmt_cr(fs.get('land_cost_cr'))}")
        lines.append(f"- **Area:** {fs.get('area_acres', 0):.1f} acres ({fs.get('sellable_sqft', 0):,.0f} sellable sqft)")
        lines.append(f"- **Market Average PSF:** {_fmt_psf(fs.get('avg_market_psf'))}")
        lines.append("")
        lines.append("| Scenario | Sell PSF | IRR | Payback | Verdict | Margin |")
        lines.append("|----------|----------|-----|---------|---------|--------|")
        for label in ("bear", "base", "bull"):
            s = scenarios.get(label, {})
            lines.append(
                f"| {label.title()} | {_fmt_psf(s.get('sell_psf'))} | "
                f"{s.get('irr_pct', 'N/A')}% | {s.get('payback_months', 'N/A')}mo | "
                f"{s.get('verdict', 'N/A')} | {s.get('profit_margin_pct', 'N/A')}% |"
            )
        lines.append("")
        base = scenarios.get("base", {})
        lines.append(f"- **GDV (base):** {_fmt_cr(base.get('gdv_cr'))}")
        lines.append(f"- **Equity Required (base):** {_fmt_cr(base.get('equity_required_cr'))}")

    lines += [
        "",
        "## 4. Supply Risk",
        "",
    ]
    sr = brief.supply_risk
    lines.append(f"- **Pipeline Units:** {sr.get('pipeline_units', 0):,}")
    lines.append(f"- **Active Units:** {sr.get('active_units', 0):,}")
    lines.append(f"- **Weeks of Inventory:** {sr.get('weeks_of_inventory', 0)}")

    lines += [
        "",
        "## 5. Assembly Alerts",
        "",
    ]
    alerts = brief.assembly_alerts
    if not alerts:
        lines.append("*No active assembly signals in this market.*")
    else:
        for a in alerts:
            extent = a.get("total_extent_sqft", 0) or 0
            extent_acres = round(extent / 43560, 2) if extent else 0
            lines.append(
                f"- **{a['buyer']}** \u2014 {a['parcel_count']} parcels in "
                f"{a['village']} ({extent_acres} acres, "
                f"{_fmt_cr(a.get('total_consideration_cr'))}, "
                f"confidence {a['confidence']:.2f})"
            )

    lines += [
        "",
        "## 6. Board Verdict",
        "",
    ]
    bv = brief.board_verdict
    if bv.get("status") == "no_verdict":
        lines.append("*No prior Board Room verdict for this market.*")
    else:
        lines.append(f"- **Decision Flag:** {_fmt_verdict(bv.get('decision_flag'))}")
        lines.append(f"- **Context:** {bv.get('context_summary', '')}")
        for dept_key, text in bv.get("assessments", {}).items():
            if text:
                display = _DEPT_DISPLAY.get(dept_key, dept_key.title())
                lines.append(f"- **{display}:** {text}")

    return "\n".join(lines)
