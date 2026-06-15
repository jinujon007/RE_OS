"""
RE_OS — Performance Digest (Phase 14 - Sprint 62)
Quarterly performance aggregator for shareholder board review.
"""

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from utils.db import get_engine

logger = logging.getLogger(__name__)

_QUARTER_PATTERN = re.compile(r"^Q[1-4]-\d{4}$")


def parse_quarter(quarter: str) -> tuple[date, date]:
    """Parse 'Q2-2026' into (start_date, end_date) inclusive.

    Raises ValueError if format is invalid.
    """
    if not _QUARTER_PATTERN.match(quarter.upper()):
        raise ValueError(
            f"Invalid quarter format: '{quarter}'. Expected 'Q<N>-<YYYY>' (e.g. Q2-2026)"
        )
    clean = quarter.upper().replace("Q", "")
    parts = clean.split("-")
    q = int(parts[0])
    year = int(parts[1])
    start_month = (q - 1) * 3 + 1
    end_month = start_month + 2
    start_date_ = date(year, start_month, 1)
    if end_month == 12:
        end_date_ = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date_ = date(year, end_month + 1, 1) - timedelta(days=1)
    return start_date_, end_date_


def safe_query(query: str, params: dict | None = None) -> list[Any]:
    """Execute query safely — return empty list on any DB error."""
    try:
        with get_engine().connect() as conn:
            return list(conn.execute(text(query), params or {}).fetchall())
    except Exception as exc:
        logger.warning("PerformanceDigest query failed: %s", exc)
        return []


def _end_param(end: date) -> date:
    """Return end + 1 day for SQL '<' comparison."""
    return end + timedelta(days=1)


def _deal_metrics(start: date, end: date) -> dict[str, Any]:
    rows = safe_query(
        "SELECT COUNT(*) AS deal_count, AVG(irr_base) AS avg_irr_pct "
        "FROM deals WHERE created_at >= :start AND created_at < :end_date",
        {"start": start, "end_date": _end_param(end)},
    )
    if rows:
        return {
            "deal_count": rows[0][0] or 0,
            "avg_irr_pct": float(rows[0][1]) if rows[0][1] is not None else None,
        }
    return {"deal_count": 0, "avg_irr_pct": None}


def _new_projects(start: date, end: date) -> list[dict[str, Any]]:
    rows = safe_query(
        "SELECT m.name AS market, COUNT(rp.id) AS project_count "
        "FROM rera_projects rp "
        "JOIN micro_markets m ON m.id = rp.micro_market_id "
        "WHERE rp.created_at >= :start AND rp.created_at < :end_date "
        "GROUP BY m.name ORDER BY project_count DESC",
        {"start": start, "end_date": _end_param(end)},
    )
    return [{"market": r[0], "project_count": r[1]} for r in rows]


def _absorption_trend(start: date, end: date) -> dict[str, Any]:
    rows = safe_query(
        "SELECT COUNT(*) AS snapshot_count, AVG(avg_absorption_pct) AS avg_absorption_pct "
        "FROM market_snapshots WHERE snapshot_date >= :start AND snapshot_date <= :end_date",
        {"start": start, "end_date": end},
    )
    if rows:
        return {
            "snapshot_count": rows[0][0] or 0,
            "avg_absorption_pct": float(rows[0][1]) if rows[0][1] is not None else None,
        }
    return {"snapshot_count": 0, "avg_absorption_pct": None}


def _deal_velocity_summary(start: date, end: date) -> list[dict[str, Any]]:
    rows = safe_query(
        "SELECT from_status, to_status, AVG(days_elapsed) AS avg_days_elapsed "
        "FROM deal_velocity "
        "WHERE transitioned_at >= :start AND transitioned_at < :end_date "
        "GROUP BY from_status, to_status ORDER BY from_status, to_status",
        {"start": start, "end_date": _end_param(end)},
    )
    return [
        {
            "from_status": r[0],
            "to_status": r[1],
            "avg_days_elapsed": float(r[2]) if r[2] is not None else None,
        }
        for r in rows
    ]


def _token_efficiency(start: date, end: date) -> dict[str, Any]:
    rows = safe_query(
        "SELECT COUNT(*) FILTER (WHERE over_budget) AS over_budget_count, "
        "COUNT(*) AS total_count "
        "FROM token_usage "
        "WHERE recorded_at >= :start AND recorded_at < :end_date",
        {"start": start, "end_date": _end_param(end)},
    )
    if rows:
        total = rows[0][1] or 0
        over_budget = rows[0][0] or 0
    else:
        total = 0
        over_budget = 0
    return {
        "total_token_usage_records": total,
        "over_budget_count": over_budget,
        "over_budget_pct": round(over_budget / total * 100, 1) if total > 0 else 0.0,
    }


class PerformanceDigest:
    """Quarterly performance aggregator for shareholder board review."""

    @staticmethod
    def build(quarter: str) -> dict[str, Any]:
        """Build a performance digest for the given quarter.

        Args:
            quarter: Format 'Q2-2026'.

        Returns:
            Dict with 5 sections: deal_metrics, new_projects, absorption_trend,
            deal_velocity_summary, token_efficiency.
        """
        start_date_, end_date_ = parse_quarter(quarter)
        return {
            "quarter": quarter,
            "period": {"start": start_date_.isoformat(), "end": end_date_.isoformat()},
            "deal_metrics": _deal_metrics(start_date_, end_date_),
            "new_projects": _new_projects(start_date_, end_date_),
            "absorption_trend": _absorption_trend(start_date_, end_date_),
            "deal_velocity_summary": _deal_velocity_summary(start_date_, end_date_),
            "token_efficiency": _token_efficiency(start_date_, end_date_),
        }
