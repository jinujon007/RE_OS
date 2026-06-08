"""
RE_OS — Market Intelligence Module (Sprint 62)
MarketIntel.get_pulse(market): consolidated market snapshot from
v_market_brief_mat, IGR transactions, news sentiment, and portal listing trends.

Returns MarketPulse with pricing, absorption, supply, developer activity,
and news signals. Gracefully degrades on DB failure.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from loguru import logger

from intelligence._shared import (
    __all__ as _,
    fval, sanitize_market, validate_market, MarketCache, timed_intel_query,
)

__all__ = ["MarketIntel", "MarketPulse"]

_CACHE_NS = "market_intel"
_CACHE_TTL_POS = 900
_CACHE_TTL_NEG = 300


@dataclass
class MarketPulse:
    market: str
    collected_at: str
    market_found: bool = True
    market_slug: str = ""

    avg_listing_psf: float | None = None
    floor_psf: float | None = None
    ceiling_psf: float | None = None
    median_igr_psf: float | None = None
    igr_record_count: int = 0

    total_projects: int = 0
    total_units: int = 0
    total_sold: int = 0
    total_unsold: int = 0
    avg_absorption_pct: float | None = None
    months_of_supply: float | None = None
    supply_label: str = "INSUFFICIENT_DATA"

    unique_developers: int = 0
    grade_a_developers: int = 0
    new_listings_30d: int = 0
    news_articles_30d: int = 0
    avg_news_sentiment: float | None = None
    active_listings: int = 0

    developer_activity_score: float | None = None
    price_momentum_30d: float | None = None
    price_momentum_signal: str = "NEUTRAL"
    data_as_of: str | None = None

    def __str__(self) -> str:
        psf = f"₹{self.avg_listing_psf:,.0f}" if self.avg_listing_psf else "N/A"
        return (
            f"[MarketPulse:{self.market}] {psf} PSF | "
            f"{self.total_projects} projects | {self.months_of_supply} MoS | "
            f"{self.price_momentum_signal}"
        )


_MIN_LISTINGS_FOR_TREND = 5


class MarketIntel:
    """Consolidated market snapshot. Cached 15min per market.

    Usage:
        pulse = MarketIntel().get_pulse("Yelahanka")
        print(pulse.avg_listing_psf, pulse.supply_label)
    """

    def __init__(self, caller: str = ""):
        self._cache = MarketCache()
        self._caller = caller or "MarketIntel"

    def get_pulse(self, market: str) -> MarketPulse:
        m = sanitize_market(market)
        if not m:
            return MarketPulse(
                market=market or "", collected_at=datetime.now(timezone.utc).isoformat(),
                market_found=False,
            )

        cached = self._cache.get(_CACHE_NS, m)
        if cached is not None:
            return cached

        market_info = validate_market(m)
        if market_info is None:
            pulse = MarketPulse(
                market=m, collected_at=datetime.now(timezone.utc).isoformat(),
                market_found=False,
            )
            self._cache.set(_CACHE_NS, m, pulse, is_positive=False)
            return pulse

        pulse = MarketPulse(
            market=market_info["name"], collected_at=datetime.now(timezone.utc).isoformat(),
            market_found=True, market_slug=market_info["slug"],
        )

        try:
            from utils.db import get_engine
            from sqlalchemy import text
            engine = get_engine(pool_size=3, max_overflow=1)
            with engine.connect() as conn:
                self._load_market_brief(conn, pulse, market_info)
                self._load_igr_stats(conn, pulse, market_info)
                self._load_news_sentiment(conn, pulse, market_info)
                self._load_listing_trend(conn, pulse, market_info)
                self._load_active_listings(conn, pulse, market_info)

            self._compute_derived(pulse)
            self._cache.set(_CACHE_NS, m, pulse, is_positive=True)

        except Exception as exc:
            logger.warning("[{}] get_pulse({}) failed: {}", self._caller, m, exc)

        return pulse

    def invalidate_cache(self, market: str | None = None):
        self._cache.invalidate(_CACHE_NS, sanitize_market(market) if market else None)

    def _load_market_brief(self, conn, pulse: MarketPulse, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("market_brief"):
            row = conn.execute(text("""
                SELECT micro_market, total_projects, total_units, total_sold, total_unsold,
                       avg_absorption_pct, avg_listing_psf, floor_psf, ceiling_psf,
                       months_of_supply, supply_label, unique_developers, grade_a_developers,
                       data_as_of
                FROM v_market_brief_mat
                WHERE micro_market ILIKE :m
                LIMIT 1
            """), {"m": mi["name"]}).fetchone()
        if row:
            pulse.avg_listing_psf = fval(row[6])
            pulse.floor_psf = fval(row[7])
            pulse.ceiling_psf = fval(row[8])
            pulse.total_projects = int(row[1]) if row[1] else 0
            pulse.total_units = int(row[2]) if row[2] else 0
            pulse.total_sold = int(row[3]) if row[3] else 0
            pulse.total_unsold = int(row[4]) if row[4] else 0
            pulse.avg_absorption_pct = fval(row[5])
            pulse.months_of_supply = fval(row[9])
            pulse.supply_label = str(row[10]) if row[10] else "INSUFFICIENT_DATA"
            pulse.unique_developers = int(row[11]) if row[11] else 0
            pulse.grade_a_developers = int(row[12]) if row[12] else 0
            pulse.data_as_of = str(row[13]) if row[13] else None

    def _load_igr_stats(self, conn, pulse: MarketPulse, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("market_igr_psf"):
            row = conn.execute(text("""
                SELECT
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY transaction_psf) AS median_psf,
                    COUNT(*) AS cnt
                FROM igr_transactions
                WHERE market ILIKE :m
                  AND transaction_psf IS NOT NULL
                  AND transaction_psf > 0
                  AND registration_date >= NOW() - INTERVAL '90 days'
            """), {"m": mi["name"]}).fetchone()
        if row and row[1] and int(row[1]) > 0:
            pulse.median_igr_psf = fval(row[0])
            pulse.igr_record_count = int(row[1])

    def _load_news_sentiment(self, conn, pulse: MarketPulse, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("market_news_sentiment"):
            row = conn.execute(text("""
                SELECT
                    COUNT(*) AS total,
                    AVG(sentiment_score) AS avg_sentiment
                FROM news_articles na
                JOIN micro_markets mm ON mm.id = na.micro_market_id
                WHERE mm.slug = :slug
                  AND (na.published_at >= CURRENT_DATE - INTERVAL '30 days'
                       OR na.created_at >= NOW() - INTERVAL '30 days')
            """), {"slug": mi["slug"]}).fetchone()
        if row:
            pulse.news_articles_30d = int(row[0]) if row[0] else 0
            pulse.avg_news_sentiment = fval(row[1])

    def _load_listing_trend(self, conn, pulse: MarketPulse, mi: dict):
        from sqlalchemy import text
        non_overlapping_start = "NOW() - INTERVAL '60 days'"
        non_overlapping_end = "NOW() - INTERVAL '31 days'"
        with timed_intel_query("market_listing_trend"):
            row_period = conn.execute(text(f"""
                SELECT
                    AVG(l.price_psf) AS avg_psf,
                    COUNT(*) AS cnt
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.slug = :slug
                  AND l.price_psf IS NOT NULL AND l.price_psf > 1000 AND l.price_psf < 50000
                  AND l.last_seen_at >= {non_overlapping_start}
                  AND l.last_seen_at < {non_overlapping_end}
            """), {"slug": mi["slug"]}).fetchone()

            row_recent = conn.execute(text("""
                SELECT
                    AVG(l.price_psf) AS avg_psf,
                    COUNT(*) AS cnt
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.slug = :slug
                  AND l.price_psf IS NOT NULL AND l.price_psf > 1000 AND l.price_psf < 50000
                  AND l.last_seen_at >= NOW() - INTERVAL '30 days'
            """), {"slug": mi["slug"]}).fetchone()

        if row_recent:
            pulse.new_listings_30d = int(row_recent[1]) if row_recent[1] else 0

        if (row_period and row_recent
                and row_period[1] and int(row_period[1]) >= _MIN_LISTINGS_FOR_TREND
                and row_recent[1] and int(row_recent[1]) >= _MIN_LISTINGS_FOR_TREND):
            avg_period = fval(row_period[0])
            avg_recent = fval(row_recent[0])
            if avg_period and avg_recent and avg_period > 0:
                pulse.price_momentum_30d = round(
                    (avg_recent - avg_period) / avg_period * 100, 2
                )

    def _load_active_listings(self, conn, pulse: MarketPulse, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("market_active_listings"):
            row = conn.execute(text("""
                SELECT COUNT(*)
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.slug = :slug
                  AND l.is_active = TRUE
            """), {"slug": mi["slug"]}).fetchone()
        if row:
            pulse.active_listings = int(row[0]) if row[0] else 0

    def _compute_derived(self, pulse: MarketPulse):
        if pulse.unique_developers > 0 and pulse.grade_a_developers > 0:
            pulse.developer_activity_score = round(
                pulse.grade_a_developers / max(pulse.unique_developers, 1), 2
            )
        if pulse.price_momentum_30d is not None:
            if pulse.price_momentum_30d > 3.0:
                pulse.price_momentum_signal = "BULLISH"
            elif pulse.price_momentum_30d < -3.0:
                pulse.price_momentum_signal = "BEARISH"
            else:
                pulse.price_momentum_signal = "NEUTRAL"


if __name__ == "__main__":
    import json
    pulse = MarketIntel(caller="self_test").get_pulse("Yelahanka")
    print(json.dumps({
        "market": pulse.market,
        "market_found": pulse.market_found,
        "avg_listing_psf": pulse.avg_listing_psf,
        "total_projects": pulse.total_projects,
        "months_of_supply": pulse.months_of_supply,
        "supply_label": pulse.supply_label,
        "signal": pulse.price_momentum_signal,
    }, indent=2, default=str))
