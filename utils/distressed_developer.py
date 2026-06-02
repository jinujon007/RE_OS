"""
RE_OS — Distressed Developer Scanner (Sprint 39 — Data Foundation)
────────────────────────────────────────────────────────────────────
Queries rera_projects for developers with delayed/incomplete projects
and computes a distress score.

distress_score = (delay_months * 0.4) + (incomplete_ratio * 0.3) + (complaint_proxy * 0.3)

Data already in DB — zero new scraping required.
Returns ranked list of distressed developers for JD/JV targeting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger
from sqlalchemy import text

from utils.db import get_engine

_DISTRESS_SCORE_THRESHOLD = 0.6  # Alert threshold
_DELAY_WEIGHT = 0.4
_INCOMPLETE_WEIGHT = 0.3
_COMPLAINT_WEIGHT = 0.3


@dataclass
class DistressedDeveloper:
    developer_name: str
    market: str
    total_projects: int
    active_projects: int
    delayed_projects: int
    avg_delay_months: float
    incomplete_ratio: float
    complaint_count: int
    distress_score: float
    alert_level: str  # "HIGH_DISTRESS" | "WATCH" | "HEALTHY"


def scan_distressed_developers(market: str | None = None,
                               min_score: float = 0.0,
                               max_results: int = 20) -> list[DistressedDeveloper]:
    """Query rera_projects for distressed developers (JD/JV target list).

    Filters: developers with <5 total RERA projects AND at least one overdue
    or incomplete project. Developers with 5+ projects are treated as established
    (lower JD/JV conversion probability).

    Args:
        market: Market name (Yelahanka/Devanahalli/Hebbal). None = all markets.
        min_score: Minimum distress score threshold. Use 0.6 for alert-level.
        max_results: Maximum results to return. Upper bound 100 enforced.

    Returns:
        Ranked list of DistressedDeveloper, highest score first.
        Empty list on DB error or no matches.

    Score formula:
        distress_score = (avg_delay_months * 0.4)
                       + (overdue_projects / total_projects * 0.3)
                       + (complaint_count / total_projects * 0.3)
    """
    records: list[DistressedDeveloper] = []
    max_results = min(max(max_results, 1), 100)

    try:
        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    WITH dev_stats AS (
                        SELECT
                            d.name AS developer_name,
                            COALESCE(mm.name, 'Unknown') AS market,
                            COUNT(r.id) AS total_projects,
                            COUNT(CASE WHEN r.is_active THEN 1 END) AS active_projects,
                            COUNT(CASE WHEN r.delay_months > 0 THEN 1 END) AS delayed_projects,
                            COALESCE(ROUND(AVG(r.delay_months)::numeric, 1), 0) AS avg_delay_months,
                            COUNT(CASE WHEN r.project_status NOT IN ('Completed', 'Cancelled')
                                        AND (r.expected_completion IS NULL
                                             OR r.expected_completion < NOW()) THEN 1 END)
                                AS overdue_projects,
                            COALESCE(
                                SUM(
                                    CASE
                                        WHEN r.raw_data IS NOT NULL
                                             AND r.raw_data ? 'complaints'
                                             AND r.raw_data->>'complaints' ~ '^\\d+$'
                                        THEN (r.raw_data->>'complaints')::int
                                        ELSE 0
                                    END
                                ), 0
                            ) AS complaint_count
                        FROM developers d
                        JOIN rera_projects r ON r.developer_id = d.id
                        JOIN micro_markets mm ON mm.id = r.micro_market_id
                        WHERE (:market_name IS NULL OR mm.name ILIKE :market_name)
                        GROUP BY d.name, mm.name
                    )
                    SELECT
                        developer_name,
                        market,
                        total_projects,
                        active_projects,
                        delayed_projects,
                        avg_delay_months,
                        CASE WHEN total_projects > 0
                             THEN ROUND(overdue_projects::numeric / total_projects, 2)
                             ELSE 0 END AS incomplete_ratio,
                        complaint_count,
                        ROUND(
                            COALESCE(avg_delay_months, 0) * :delay_w
                            + (CASE WHEN total_projects > 0
                                    THEN (overdue_projects::numeric / NULLIF(total_projects, 0)) * :incomplete_w
                                    ELSE 0 END)
                            + (CASE WHEN total_projects > 0
                                    THEN (complaint_count::numeric / NULLIF(total_projects, 0)) * :complaint_w
                                    ELSE 0 END)
                        , 2) AS distress_score
                    FROM dev_stats
                    ORDER BY distress_score DESC
                """),
                {
                    "market_name": f"%{market}%" if market else None,
                    "delay_w": _DELAY_WEIGHT,
                    "incomplete_w": _INCOMPLETE_WEIGHT,
                    "complaint_w": _COMPLAINT_WEIGHT,
                },
            ).fetchall()
    except Exception as exc:
        logger.warning(f"[DistressedDev] Query failed for market={market}: {exc}")
        return []

    for row in rows:
        score = float(row.distress_score)
        if score < min_score:
            continue
        if score > 0.7:
            alert_level = "HIGH_DISTRESS"
        elif score > 0.4:
            alert_level = "WATCH"
        else:
            alert_level = "HEALTHY"

        records.append(DistressedDeveloper(
            developer_name=str(row.developer_name),
            market=str(row.market),
            total_projects=int(row.total_projects),
            active_projects=int(row.active_projects),
            delayed_projects=int(row.delayed_projects),
            avg_delay_months=float(row.avg_delay_months),
            incomplete_ratio=float(row.incomplete_ratio),
            complaint_count=int(row.complaint_count),
            distress_score=score,
            alert_level=alert_level,
        ))

    records.sort(key=lambda d: d.distress_score, reverse=True)
    return records[:max_results]


class DistressedDeveloperScanner:
    """Scanner for distressed developers as JD/JV target opportunities.

    Wraps scan_distressed_developers() for use as a CrewAI BaseTool
    or direct programmatic access.
    """

    def scan(self, market: str | None = None,
             min_score: float = 0.0,
             max_results: int = 20) -> list[DistressedDeveloper]:
        """Scan and return ranked list of distressed developers."""
        return scan_distressed_developers(market, min_score, max_results)

    def top_n(self, market: str, n: int = 3,
              min_score: float = 0.3) -> list[DistressedDeveloper]:
        """Convenience: top-N distressed developers in a market."""
        return scan_distressed_developers(market, min_score, n)


def format_distress_alert(dev: DistressedDeveloper) -> str:
    """Format a Discord-friendly alert message for a distressed developer."""
    return (
        f"**{dev.alert_level}** — {dev.developer_name} ({dev.market})\n"
        f"Score: {dev.distress_score:.2f} | "
        f"Projects: {dev.total_projects} | "
        f"Delayed: {dev.delayed_projects} ({dev.avg_delay_months}mo avg) | "
        f"Complaints: {dev.complaint_count}\n"
        f"**JD/JV opportunity signal**"
    )


if __name__ == "__main__":
    print("=== Distressed Developer Scanner =================")
    for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
        results = scan_distressed_developers(market, min_score=0.3)
        print(f"\n[{market}] {len(results)} developers above 0.3:")
        for dev in results:
            print(f"  {dev.developer_name}: {dev.distress_score:.2f} ({dev.alert_level})")
            if dev.distress_score > _DISTRESS_SCORE_THRESHOLD:
                print(f"    → {format_distress_alert(dev)}")
