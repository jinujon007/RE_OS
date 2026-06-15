"""
RE_OS — Distressed Developer Scanner (Sprint 39 → Sprint 72)
─────────────────────────────────────────────────────────────
Two responsibilities, one canonical score:

1. scan_distressed_developers() — queries rera_projects for raw delay/
   incompletion stats.  Returns a preliminary sort score for ranking only
   (not persisted).  Callers that need the authoritative blended score
   should call compute_developer_distress_score() explicitly.

2. compute_developer_distress_score() — SINGLE CANONICAL formula:
       min(stall_ratio*0.55 + nclt_flag*0.35 + bda_flag*0.10, 1.0)
   Reads from developer_distress_signals; persists under signal_type='computed'.
   All downstream consumers (OpportunityEngine, BD context, Board Room) use
   this function — never the inline scan formula.

Score threshold for alerts: 0.6.  Max score: 1.0.
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


def compute_developer_distress_score(developer_name: str, market: str) -> float:
    """Blend latest stall, NCLT, and BDA auction signals into a [0,1] score.

    Formula:
        min(stall_ratio*0.55 + nclt_flag*0.35 + bda_flag*0.10, 1.0)
    """
    developer_name = " ".join((developer_name or "").split())
    market = " ".join((market or "").split())
    if not developer_name or not market or market.lower() == "unknown":
        return 0.0

    try:
        with get_engine().begin() as conn:
            row = conn.execute(
                text(
                    """
                    WITH latest_stall AS (
                        SELECT stall_ratio
                        FROM developer_distress_signals
                        WHERE developer_name = :developer_name
                          AND market = :market
                          AND signal_type = 'rera_stall'
                        ORDER BY detected_at DESC
                        LIMIT 1
                    ),
                    nclt AS (
                        SELECT CASE WHEN COUNT(*) >= 1 THEN 1.0 ELSE 0.0 END AS nclt_flag
                        FROM developer_distress_signals
                        WHERE developer_name = :developer_name
                          AND market = :market
                          AND signal_type = 'nclt_news'
                          AND detected_at >= NOW() - INTERVAL '180 days'
                    ),
                    bda AS (
                        SELECT CASE WHEN COUNT(*) >= 1 THEN 1.0 ELSE 0.0 END AS bda_flag
                        FROM developer_distress_signals
                        WHERE developer_name = :developer_name
                          AND market = :market
                          AND signal_type = 'bda_auction'
                    )
                    SELECT
                        COALESCE((SELECT stall_ratio FROM latest_stall), 0.0) AS stall_ratio,
                        COALESCE((SELECT nclt_flag FROM nclt), 0.0) AS nclt_flag,
                        COALESCE((SELECT bda_flag FROM bda), 0.0) AS bda_flag
                    """
                ),
                {"developer_name": developer_name, "market": market},
            ).fetchone()
            if row is None:
                return 0.0

            score = min(
                (float(row.stall_ratio or 0.0) * 0.55)
                + (float(row.nclt_flag or 0.0) * 0.35)
                + (float(row.bda_flag or 0.0) * 0.10),
                1.0,
            )
            score = round(max(0.0, min(score, 1.0)), 4)
            conn.execute(
                text(
                    """
                    INSERT INTO developer_distress_signals (
                        developer_name, market, signal_type, distress_score
                    )
                    VALUES (:developer_name, :market, 'computed', :distress_score)
                    ON CONFLICT (developer_name, market, signal_type)
                    DO UPDATE SET distress_score = EXCLUDED.distress_score, detected_at = NOW()
                    """
                ),
                {
                    "developer_name": developer_name,
                    "market": market,
                    "distress_score": score,
                },
            )
            return score
    except Exception as exc:
        logger.warning(
            "[DistressedDev] compute score failed for {} / {}: {}",
            developer_name,
            market,
            exc,
        )
        return 0.0


def scan_distressed_developers(
    market: str | None = None, min_score: float = 0.0, max_results: int = 20
) -> list[DistressedDeveloper]:
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

    Preliminary sort score (delay/overdue/complaint — for ranking only):
        sort_score = LEAST(avg_delay_months / 24.0, 1.0) * 0.4
                   + LEAST(overdue_projects / total_projects, 1.0) * 0.3
                   + LEAST(complaint_count / total_projects, 1.0) * 0.3

    This score is NOT the canonical distress score.  For the authoritative
    blended score (stall_ratio × 0.55 + nclt_flag × 0.35 + bda_flag × 0.10)
    call compute_developer_distress_score(developer_name, market) explicitly.
    DistressedPlugin.run() does this automatically after Phase 4 & 5.
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
                            mm.name AS market,
                            COUNT(r.id) AS total_projects,
                            COUNT(CASE WHEN r.is_active THEN 1 END) AS active_projects,
                            COUNT(CASE WHEN r.delay_months > 0 THEN 1 END) AS delayed_projects,
                            COALESCE(ROUND(AVG(r.delay_months)::numeric, 1), 0) AS avg_delay_months,
                            COUNT(CASE WHEN r.project_status NOT IN ('Completed', 'Cancelled')
                                        AND (r.possession_date IS NULL
                                             OR r.possession_date < NOW()) THEN 1 END)
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
                        -- INNER JOIN enforces a known market; NULL micro_market_id rows
                        -- are excluded rather than silently bucketed as 'Unknown'.
                        JOIN micro_markets mm ON mm.id = r.micro_market_id
                        WHERE mm.name IS NOT NULL
                          AND (:market_name IS NULL OR mm.name ILIKE :market_name)
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
                            LEAST(COALESCE(avg_delay_months, 0) / 24.0, 1.0) * :delay_w
                            + (CASE WHEN total_projects > 0
                                    THEN LEAST((overdue_projects::numeric / NULLIF(total_projects, 0)), 1.0) * :incomplete_w
                                    ELSE 0 END)
                            + (CASE WHEN total_projects > 0
                                    THEN LEAST((complaint_count::numeric / NULLIF(total_projects, 0)), 1.0) * :complaint_w
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

        records.append(
            DistressedDeveloper(
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
            )
        )

    records.sort(key=lambda d: d.distress_score, reverse=True)
    return records[:max_results]


class DistressedDeveloperScanner:
    """Scanner for distressed developers as JD/JV target opportunities.

    Wraps scan_distressed_developers() for use as a CrewAI BaseTool
    or direct programmatic access.
    """

    def scan(
        self, market: str | None = None, min_score: float = 0.0, max_results: int = 20
    ) -> list[DistressedDeveloper]:
        """Scan and return ranked list of distressed developers."""
        return scan_distressed_developers(market, min_score, max_results)

    def top_n(
        self, market: str, n: int = 3, min_score: float = 0.3
    ) -> list[DistressedDeveloper]:
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
            print(
                f"  {dev.developer_name}: {dev.distress_score:.2f} ({dev.alert_level})"
            )
            if dev.distress_score > _DISTRESS_SCORE_THRESHOLD:
                print(f"    → {format_distress_alert(dev)}")
