"""
RE_OS — Developer Pricing Tracker
──────────────────────────────────
Queries developer_pricing_history for price move detection and history.

Public API:
  detect_price_moves(market, threshold_pct, lookback_days)
    → list of price moves >= threshold within the window

  get_pricing_history(developer_name, market, weeks)
    → weekly median PSF per developer per market
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence
from sqlalchemy import text
from utils.db import get_engine

__all__: Sequence[str] = [
    "detect_price_moves",
    "get_pricing_history",
]


def detect_price_moves(
    market: str,
    threshold_pct: float = 3.0,
    lookback_days: int = 7,
) -> list[dict]:
    """Return developer price moves >= threshold_pct within lookback_days.

    Args:
        market: Market name (Yelahanka, Devanahalli, Hebbal).
        threshold_pct: Minimum absolute change % to include (default 3.0).
        lookback_days: Rolling window in days (default 7).

    Returns:
        List of dicts with keys: developer_name, project_name,
        prior_psf, current_psf, change_pct, scrape_date.
        Empty list on any error (caller logs independently).
    """
    from config.metrics import pricing_tracker_runs_total

    try:
        engine = get_engine()
        cutoff = date.today() - timedelta(days=lookback_days)
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT developer_name, project_name, prior_psf,
                           psf_listed AS current_psf, change_pct, scrape_date
                    FROM developer_pricing_history
                    WHERE market = :market
                      AND scrape_date >= :cutoff
                      AND change_pct IS NOT NULL
                      AND psf_listed IS NOT NULL
                      AND ABS(change_pct) >= :threshold
                    ORDER BY ABS(change_pct) DESC
                """),
                {
                    "market": market,
                    "cutoff": cutoff,
                    "threshold": threshold_pct,
                },
            ).fetchall()
        pricing_tracker_runs_total.labels(market=market).inc()

        result: list[dict] = []
        for r in rows:
            result.append({
                "developer_name": str(r[0]),
                "project_name": str(r[1]),
                "prior_psf": float(r[2]) if r[2] is not None else None,
                "current_psf": float(r[3]),
                "change_pct": float(r[4]),
                "scrape_date": str(r[5]),
            })
        return result
    except Exception as exc:
        from loguru import logger

        logger.warning(
            "[PricingTracker] detect_price_moves failed: {} [market={}, threshold={}]",
            exc, market, threshold_pct,
        )
        return []


def get_pricing_history(
    developer_name: str,
    market: str,
    weeks: int = 12,
) -> list[dict]:
    """Return weekly median PSF for a developer in a market.

    Args:
        developer_name: Developer name (e.g. 'Brigade Enterprises').
        market: Market name (Yelahanka, Devanahalli, Hebbal).
        weeks: Number of weeks of history (default 12).

    Returns:
        List of dicts with keys: week_start, median_psf (float or None),
        n_projects. Empty list when no data or on error.
    """
    try:
        engine = get_engine()
        cutoff = date.today() - timedelta(weeks=weeks)
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT
                        DATE_TRUNC('week', scrape_date)::date AS week_start,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (
                            ORDER BY psf_listed
                        ) AS median_psf,
                        COUNT(*) AS n_projects
                    FROM developer_pricing_history
                    WHERE developer_name = :dev
                      AND market = :market
                      AND psf_listed IS NOT NULL
                      AND scrape_date >= :cutoff
                    GROUP BY DATE_TRUNC('week', scrape_date)::date
                    ORDER BY week_start
                """),
                {
                    "dev": developer_name,
                    "market": market,
                    "cutoff": cutoff,
                },
            ).fetchall()
        result: list[dict] = []
        for r in rows:
            result.append({
                "week_start": str(r[0]),
                "median_psf": float(r[1]) if r[1] is not None else None,
                "n_projects": int(r[2]),
            })
        return result
    except Exception as exc:
        from loguru import logger

        logger.warning(
            "[PricingTracker] get_pricing_history failed: {} [dev={}, market={}]",
            exc, developer_name, market,
        )
        return []
