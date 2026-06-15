"""Peer Benchmark Engine (Sprint 57 — GATE-65, Investor Readiness).

Computes competitive positioning vs Grade A developers in a market.
Queries rera_projects JOIN developers for Grade A pricing, absorption, and unit data.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger

__all__ = ["PeerBenchmarkResult", "PeerBenchmarkEngine"]


@dataclass
class PeerBenchmarkResult:
    market: str = ""
    as_of: str = ""
    grade_a_count: int = 0
    avg_psf_grade_a: float = 0.0
    median_absorption_pct_grade_a: float = 0.0
    avg_units_grade_a: float = 0.0
    lls_target_psf: float = 0.0
    lls_vs_grade_a_pct: float = 0.0
    positioning: str = "INSUFFICIENT_DATA"
    error: str | None = None


class PeerBenchmarkEngine:
    """Compute peer benchmarks for a market."""

    @staticmethod
    def compute(market: str, lls_target_psf: float = 0.0) -> PeerBenchmarkResult:
        result = PeerBenchmarkResult(
            market=market,
            as_of=datetime.now(timezone.utc).isoformat(),
        )
        try:
            from utils.db import get_engine
            from sqlalchemy import text

            engine = get_engine()
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                    SELECT rp.price_min_psf, rp.price_max_psf, rp.price_avg_psf,
                           rp.absorption_pct, rp.total_units,
                           rp.project_name, d.name AS dev_name
                    FROM rera_projects rp
                    JOIN developers d ON d.id = rp.developer_id
                    WHERE d.grade = 'A'
                      AND rp.price_min_psf IS NOT NULL
                      AND rp.price_min_psf > 0
                      AND rp.micro_market_id IN (
                          SELECT id FROM micro_markets WHERE name ILIKE :mkt
                      )
                    ORDER BY rp.price_min_psf DESC
                """),
                    {"mkt": market},
                ).fetchall()

            if not rows or len(rows) < 3:
                result.positioning = "INSUFFICIENT_DATA"
                result.grade_a_count = len(rows) if rows else 0
                return result

            result.grade_a_count = len(rows)
            prices = [float(r[0]) for r in rows]
            abs_pcts = [float(r[3]) for r in rows if r[3] is not None]
            units = [int(r[4]) for r in rows if r[4] is not None]

            result.avg_psf_grade_a = sum(prices) / len(prices) if prices else 0.0
            sorted_abs = sorted(abs_pcts)
            mid = len(sorted_abs) // 2
            result.median_absorption_pct_grade_a = (
                (
                    sorted_abs[mid]
                    if len(sorted_abs) % 2
                    else (sorted_abs[mid - 1] + sorted_abs[mid]) / 2
                )
                if sorted_abs
                else 0.0
            )
            result.avg_units_grade_a = sum(units) / len(units) if units else 0.0

            result.lls_target_psf = lls_target_psf
            if lls_target_psf > 0 and result.avg_psf_grade_a > 0:
                result.lls_vs_grade_a_pct = (
                    (lls_target_psf - result.avg_psf_grade_a) / result.avg_psf_grade_a
                ) * 100.0

                threshold_high = result.avg_psf_grade_a * 1.10
                threshold_low = result.avg_psf_grade_a * 0.90
                if lls_target_psf > threshold_high:
                    result.positioning = "PREMIUM"
                elif lls_target_psf < threshold_low:
                    result.positioning = "VALUE"
                else:
                    result.positioning = "COMPETITIVE"
            else:
                result.positioning = "INSUFFICIENT_DATA"

        except Exception as exc:
            logger.warning("[PeerBenchmarkEngine] compute failed: {}", exc)
            result.error = str(exc)
            result.positioning = "INSUFFICIENT_DATA"

        return result
