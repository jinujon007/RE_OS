"""Intelligence Calibrator (GATE-157, T-1471).
Runs calibration checks for a market: MAPE accuracy, confidence distribution,
stale memories, news coverage. Each query wrapped in try/except.

Prometheus: calibration_mape_4wk / calibration_mape_26wk gauges per market.
"""

from __future__ import annotations

from datetime import datetime, timezone
from loguru import logger
from sqlalchemy import text

from utils.db import get_engine

__all__ = ["run_calibration_check"]

_NEWS_WINDOW_DAYS = 7
_STALE_MEMORY_DAYS = 30
_MAPE_TREND_DEGRADE_THRESHOLD_PP = 5.0

try:
    from prometheus_client import Gauge as _PromGauge
    _cal_mape_4wk = _PromGauge(
        "calibration_mape_4wk",
        "4-week MAPE per market from calibration snapshots",
        ["market"],
    )
    _cal_mape_26wk = _PromGauge(
        "calibration_mape_26wk",
        "26-week MAPE per market from calibration snapshots",
        ["market"],
    )
    _cal_stale_memories = _PromGauge(
        "calibration_stale_memories",
        "Stale memory count per market from calibration snapshots",
        ["market"],
    )
except ImportError:
    _cal_mape_4wk = _cal_mape_26wk = _cal_stale_memories = None


def _validate_market(market: str) -> str:
    m = (market or "").strip()
    if not m:
        raise ValueError("market must be a non-empty string")
    return m


def _empty_calibration_result() -> dict:
    return {
        "mape_4wk": None,
        "mape_26wk": None,
        "mape_trend": "unknown",
        "confidence_distribution": {},
        "stale_memory_count": 0,
        "news_coverage_pct": None,
    }


def _query_mape_trend(market: str) -> str:
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT mape_4wk
                    FROM calibration_snapshots
                    WHERE market = :market
                    ORDER BY computed_at DESC
                    LIMIT 4
                """),
                {"market": market},
            ).fetchall()
        if len(rows) < 2:
            return "unknown"
        current = rows[0][0]
        last = rows[1][0]
        if current is None or last is None:
            return "unknown"
        current_f = float(current)
        last_f = float(last)
        if last_f > current_f:
            return "improving"
        if current_f - last_f > _MAPE_TREND_DEGRADE_THRESHOLD_PP:
            return "degrading"
        return "stable"
    except Exception as exc:
        logger.debug("[Calibrator] mape_trend query failed for {}: {}", market, exc)
        return "unknown"


def _query_confidence_distribution(market: str) -> dict[str, int]:
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT confidence_band, COUNT(*) AS cnt
                    FROM (
                        SELECT CASE
                            WHEN confidence >= 0.8 THEN 'high'
                            WHEN confidence >= 0.5 THEN 'medium'
                            ELSE 'low'
                        END AS confidence_band
                        FROM agent_memories
                        WHERE market = :market
                    ) sub
                    GROUP BY confidence_band
                """),
                {"market": market},
            ).fetchall()
        return {str(r[0]): int(r[1]) for r in rows}
    except Exception as exc:
        logger.debug("[Calibrator] confidence_distribution failed for {}: {}", market, exc)
        return {}


def _query_stale_memory_count(market: str) -> int:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT COUNT(*)
                    FROM agent_memories
                    WHERE last_updated < NOW() - INTERVAL '30 days'
                      AND market = :market
                """),
                {"market": market},
            ).scalar()
        return int(row) if row is not None else 0
    except Exception as exc:
        logger.debug("[Calibrator] stale_memory_count failed for {}: {}", market, exc)
        return 0


def _query_news_coverage_pct(market: str) -> float | None:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT
                        COUNT(*) FILTER (WHERE sentiment_label IS NOT NULL) * 100.0
                        / NULLIF(COUNT(*), 0)
                    FROM news_articles
                    WHERE micro_market ILIKE :market
                      AND created_at > NOW() - INTERVAL '7 days'
                """),
                {"market": f"%{market}%"},
            ).scalar()
        return float(row) if row is not None else None
    except Exception as exc:
        logger.debug("[Calibrator] news_coverage_pct failed for {}: {}", market, exc)
        return None


def run_calibration_check(market: str) -> dict:
    """Run all 6 calibration queries for a market. Returns dict, never raises."""
    try:
        market = _validate_market(market)
    except ValueError as exc:
        logger.warning("[Calibrator] invalid market: {}", exc)
        return _empty_calibration_result()

    from utils.prediction_tracker import compute_mape

    mape_4wk = None
    mape_26wk = None
    try:
        mape_4wk = compute_mape(market, min_samples=2, model_version="v1_4wk")
    except Exception as exc:
        logger.debug("[Calibrator] mape_4wk failed for {}: {}", market, exc)
    try:
        mape_26wk = compute_mape(market, min_samples=2)
    except Exception as exc:
        logger.debug("[Calibrator] mape_26wk failed for {}: {}", market, exc)

    mape_trend = _query_mape_trend(market)
    confidence_distribution = _query_confidence_distribution(market)
    stale_memory_count = _query_stale_memory_count(market)
    news_coverage_pct = _query_news_coverage_pct(market)

    # Update Prometheus gauges for Grafana visibility
    if _cal_mape_4wk is not None and mape_4wk is not None:
        _cal_mape_4wk.labels(market=market).set(mape_4wk)
    if _cal_mape_26wk is not None and mape_26wk is not None:
        _cal_mape_26wk.labels(market=market).set(mape_26wk)
    if _cal_stale_memories is not None:
        _cal_stale_memories.labels(market=market).set(stale_memory_count)

    return {
        "mape_4wk": mape_4wk,
        "mape_26wk": mape_26wk,
        "mape_trend": mape_trend,
        "confidence_distribution": confidence_distribution,
        "stale_memory_count": stale_memory_count,
        "news_coverage_pct": news_coverage_pct,
    }
