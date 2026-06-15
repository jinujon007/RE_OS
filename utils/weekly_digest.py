from dataclasses import dataclass, field
from typing import Any
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine
from config.settings import GRADE_A_DEVELOPERS

PSF_DIRECTION_THRESHOLD_PCT = 3.0


@dataclass
class WeeklyDigestResult:
    market: str
    psf_delta_pct: float = 0.0
    psf_direction: str = "flat"
    new_rera_count: int = 0
    competitor_launches: list[dict[str, Any]] = field(default_factory=list)
    distressed_developers: list[dict[str, Any]] = field(default_factory=list)
    top_opportunity: dict[str, Any] | None = None

    def __repr__(self) -> str:
        return (
            f"WeeklyDigestResult(market={self.market}, psf={self.psf_delta_pct:+.2f}% "
            f"({self.psf_direction}), rera={self.new_rera_count}, "
            f"competitors={len(self.competitor_launches)}, "
            f"distressed={len(self.distressed_developers)}, "
            f"top_opp={self.top_opportunity['survey_no'] if self.top_opportunity else None})"
        )


class WeeklyIntelDigest:
    def build(self, market: str) -> WeeklyDigestResult:
        result = WeeklyDigestResult(market=market)
        try:
            engine = get_engine()
            with engine.connect() as conn:
                self._load_psf_delta(conn, market, result)
                self._load_new_rera(conn, market, result)
                self._load_competitor_launches(conn, market, result)
                self._load_distressed_developers(conn, market, result)
                self._load_top_opportunity(conn, market, result)
        except Exception as exc:
            logger.warning(f"[WeeklyIntelDigest] Build failed for {market}: {exc}")
        return result

    def _load_psf_delta(self, conn, market: str, result: WeeklyDigestResult) -> None:
        try:
            row = conn.execute(
                text("""
                SELECT
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_min_psf)
                    FILTER (WHERE snapshot_date >= NOW() - INTERVAL '8 days'),
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_min_psf)
                    FILTER (WHERE snapshot_date >= NOW() - INTERVAL '15 days'
                            AND snapshot_date < NOW() - INTERVAL '8 days')
                FROM project_snapshots
                WHERE micro_market_id = (SELECT id FROM micro_markets WHERE name = :market)
            """),
                {"market": market},
            ).fetchone()
            if row:
                current_psf, prior_psf = row
                if current_psf is not None and prior_psf is not None and prior_psf != 0:
                    result.psf_delta_pct = round(
                        ((current_psf - prior_psf) / prior_psf) * 100, 2
                    )
                    if result.psf_delta_pct >= PSF_DIRECTION_THRESHOLD_PCT:
                        result.psf_direction = "up"
                    elif result.psf_delta_pct <= -PSF_DIRECTION_THRESHOLD_PCT:
                        result.psf_direction = "down"
        except Exception as exc:
            logger.warning(f"[WeeklyIntelDigest] PSF delta failed for {market}: {exc}")

    def _load_new_rera(self, conn, market: str, result: WeeklyDigestResult) -> None:
        try:
            result.new_rera_count = (
                conn.execute(
                    text("""
                SELECT COUNT(*)
                FROM rera_projects
                WHERE micro_market_id = (SELECT id FROM micro_markets WHERE name = :market)
                  AND created_at >= NOW() - INTERVAL '7 days'
            """),
                    {"market": market},
                ).scalar()
                or 0
            )
        except Exception as exc:
            logger.warning(f"[WeeklyIntelDigest] RERA count failed for {market}: {exc}")

    def _load_competitor_launches(
        self, conn, market: str, result: WeeklyDigestResult
    ) -> None:
        try:
            rows = conn.execute(
                text("""
                SELECT rp.project_name, COALESCE(d.name, 'Unknown') AS developer_name,
                       CASE WHEN LOWER(d.name) = ANY(:grade_a) THEN 'A' ELSE 'B' END AS grade,
                       rp.total_units
                FROM rera_projects rp
                LEFT JOIN developers d ON d.id = rp.developer_id
                WHERE rp.micro_market_id = (SELECT id FROM micro_markets WHERE name = :market)
                  AND rp.created_at >= NOW() - INTERVAL '7 days'
                ORDER BY rp.created_at DESC
                LIMIT 20
            """),
                {"market": market, "grade_a": [d.lower() for d in GRADE_A_DEVELOPERS]},
            ).fetchall()
            result.competitor_launches = [
                {
                    "developer_name": r[1],
                    "project_name": r[0],
                    "grade": r[2],
                    "units": r[3] or 0,
                }
                for r in rows
            ]
        except Exception as exc:
            logger.warning(
                f"[WeeklyIntelDigest] Competitor launches failed for {market}: {exc}"
            )

    def _load_distressed_developers(
        self, conn, market: str, result: WeeklyDigestResult
    ) -> None:
        try:
            rows = conn.execute(
                text("""
                SELECT developer_name, market, distress_score
                FROM developer_distress_signals
                WHERE market = :market AND signal_type = 'computed' AND distress_score > 0.5
                ORDER BY distress_score DESC
                LIMIT 5
            """),
                {"market": market},
            ).fetchall()
            result.distressed_developers = [
                {"developer_name": r[0], "market": r[1], "distress_score": float(r[2])}
                for r in rows
            ]
        except Exception as exc:
            logger.warning(
                f"[WeeklyIntelDigest] Distressed devs failed for {market}: {exc}"
            )

    def _load_top_opportunity(
        self, conn, market: str, result: WeeklyDigestResult
    ) -> None:
        try:
            row = conn.execute(
                text("""
                SELECT survey_no, micro_market, composite_score, timing_score
                FROM opportunity_scores
                WHERE micro_market = :market
                ORDER BY composite_score DESC
                LIMIT 1
            """),
                {"market": market},
            ).fetchone()
            if row:
                result.top_opportunity = {
                    "survey_no": row[0],
                    "market": row[1],
                    "composite_score": float(row[2]),
                    "timing_score": float(row[3]),
                }
        except Exception as exc:
            logger.warning(
                f"[WeeklyIntelDigest] Top opportunity failed for {market}: {exc}"
            )
