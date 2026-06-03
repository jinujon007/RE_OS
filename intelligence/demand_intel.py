"""
RE_OS — Demand Intelligence Module (Sprint 62)
DemandIntel.get_signals(market): analyses listing trends, absorption velocity,
news sentiment, RERA launch velocity, and developer confidence to produce a
composite BULLISH/BEARISH/NEUTRAL demand signal with explainer flags.

Signal scoring uses weighted factors:
  - months_of_supply (2x): <9 undersupply=bullish, >18 oversupply=bearish
  - price_momentum (1.5x): 30d non-overlapping PSF change
  - absorption_rate (1.5x): >60% = bullish, <30% = bearish
  - news_sentiment (1x): avg FinBERT score
  - new_launches (1x): 90d RERA registration velocity
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from loguru import logger

from intelligence._shared import (
    __all__ as _,
    fval, sanitize_market, validate_market, MarketCache, timed_intel_query,
)

__all__ = ["DemandIntel", "DemandSignals"]

_CACHE_NS = "demand_intel"
_MIN_SAMPLES_FOR_TREND = 5


@dataclass
class DemandSignals:
    market: str
    collected_at: str
    market_found: bool = True

    avg_listing_psf: float | None = None
    median_listing_psf: float | None = None

    listing_trend_30d_pct: float | None = None
    listing_count_30d: int = 0
    listing_trend_90d_pct: float | None = None
    listing_count_90d: int = 0

    absorption_pct: float | None = None
    months_of_supply: float | None = None
    supply_label: str = "INSUFFICIENT_DATA"
    monthly_absorption_rate_units: float | None = None

    avg_news_sentiment: float | None = None
    news_volume_30d: int = 0
    positive_news_pct: float | None = None
    negative_news_pct: float | None = None

    new_rera_launches_90d: int = 0
    new_launch_units: int = 0

    developer_confidence_pct: float | None = None
    grade_a_share_pct: float | None = None
    underconstruction_pct: float | None = None

    price_momentum_signal: str = "NEUTRAL"
    demand_signal: str = "NEUTRAL"
    demand_score: float = 0.0

    signals: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"[DemandSignals:{self.market}] "
            f"{self.demand_signal} (score={self.demand_score:.1f}) | "
            f"PSF momentum {self.listing_trend_30d_pct:+.1f}% | "
            f"{self.months_of_supply} MoS"
        )


class DemandIntel:
    """Demand signal analysis with weighted composite scoring.

    Usage:
        ds = DemandIntel().get_signals("Yelahanka")
        print(ds.demand_signal, ds.signals)
    """

    def __init__(self, caller: str = ""):
        self._cache = MarketCache()
        self._caller = caller or "DemandIntel"

    def get_signals(self, market: str) -> DemandSignals:
        m = sanitize_market(market)
        if not m:
            return DemandSignals(
                market=market or "", collected_at=datetime.now(timezone.utc).isoformat(),
                market_found=False,
            )

        cached = self._cache.get(_CACHE_NS, m)
        if cached is not None:
            return cached

        mi = validate_market(m)
        if mi is None:
            ds = DemandSignals(
                market=m, collected_at=datetime.now(timezone.utc).isoformat(),
                market_found=False,
            )
            self._cache.set(_CACHE_NS, m, ds, is_positive=False)
            return ds

        ds = DemandSignals(
            market=mi["name"], collected_at=datetime.now(timezone.utc).isoformat(),
            market_found=True,
        )

        try:
            from utils.db import get_engine
            from sqlalchemy import text
            engine = get_engine(pool_size=3, max_overflow=1)
            with engine.connect() as conn:
                self._load_listing_trends(conn, ds, mi)
                self._load_absorption_data(conn, ds, mi)
                self._load_news_signals(conn, ds, mi)
                self._load_rera_launches(conn, ds, mi)
                self._load_developer_activity(conn, ds, mi)
                self._load_absorption_velocity(conn, ds, mi)

            self._compute_price_momentum(ds)
            self._compute_demand_signal(ds)
            self._cache.set(_CACHE_NS, m, ds, is_positive=True)

        except Exception as exc:
            logger.warning("[{}] get_signals({}) failed: {}", self._caller, m, exc)

        return ds

    def invalidate_cache(self, market: str | None = None):
        self._cache.invalidate(_CACHE_NS, sanitize_market(market) if market else None)

    def _load_listing_trends(self, conn, ds: DemandSignals, mi: dict):
        from sqlalchemy import text
        period_90_start = "NOW() - INTERVAL '90 days'"
        period_30_start = "NOW() - INTERVAL '30 days'"
        period_60_start = "NOW() - INTERVAL '60 days'"
        period_31_start = "NOW() - INTERVAL '31 days'"

        with timed_intel_query("demand_listing_30d"):
            row30 = conn.execute(text(f"""
                SELECT
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY l.price_psf) AS median_psf,
                    AVG(l.price_psf) AS avg_psf,
                    COUNT(*) AS cnt
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.slug = :slug
                  AND l.price_psf IS NOT NULL AND l.price_psf > 1000 AND l.price_psf < 50000
                  AND l.last_seen_at >= {period_30_start}
            """), {"slug": mi["slug"]}).fetchone()

        with timed_intel_query("demand_listing_90d_prior"):
            row90_prior = conn.execute(text(f"""
                SELECT AVG(l.price_psf) AS avg_psf, COUNT(*) AS cnt
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.slug = :slug
                  AND l.price_psf IS NOT NULL AND l.price_psf > 1000 AND l.price_psf < 50000
                  AND l.last_seen_at >= {period_60_start}
                  AND l.last_seen_at < {period_31_start}
            """), {"slug": mi["slug"]}).fetchone()

        with timed_intel_query("demand_listing_90d"):
            row90 = conn.execute(text(f"""
                SELECT AVG(l.price_psf) AS avg_psf, COUNT(*) AS cnt
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.slug = :slug
                  AND l.price_psf IS NOT NULL AND l.price_psf > 1000 AND l.price_psf < 50000
                  AND l.last_seen_at >= {period_90_start}
            """), {"slug": mi["slug"]}).fetchone()

        if row30:
            ds.listing_count_30d = int(row30[2]) if row30[2] else 0
            ds.avg_listing_psf = fval(row30[1])
            ds.median_listing_psf = fval(row30[0])

        if row90:
            ds.listing_count_90d = int(row90[1]) if row90[1] else 0

        if (row90_prior and row30
                and row90_prior[1] and int(row90_prior[1]) >= _MIN_SAMPLES_FOR_TREND
                and row30[1] and int(row30[1]) >= _MIN_SAMPLES_FOR_TREND):
            avg_prior = fval(row90_prior[0])
            avg_recent = fval(row30[1])
            if avg_prior and avg_recent and avg_prior > 0:
                ds.listing_trend_30d_pct = round(
                    (avg_recent - avg_prior) / avg_prior * 100, 2
                )

    def _load_absorption_data(self, conn, ds: DemandSignals, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("demand_absorption"):
            row = conn.execute(text("""
                SELECT micro_market, avg_absorption_pct, months_of_supply, supply_label
                FROM v_market_brief
                WHERE micro_market ILIKE :m
                LIMIT 1
            """), {"m": mi["name"]}).fetchone()
        if row:
            ds.absorption_pct = fval(row[1])
            ds.months_of_supply = fval(row[2])
            ds.supply_label = str(row[3]) if row[3] else "INSUFFICIENT_DATA"

    def _load_news_signals(self, conn, ds: DemandSignals, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("demand_news"):
            rows = conn.execute(text("""
                SELECT sentiment_score, sentiment_label
                FROM news_articles na
                JOIN micro_markets mm ON mm.id = na.micro_market_id
                WHERE mm.slug = :slug
                  AND na.sentiment_score IS NOT NULL
                  AND (na.published_at >= CURRENT_DATE - INTERVAL '30 days'
                       OR na.created_at >= NOW() - INTERVAL '30 days')
            """), {"slug": mi["slug"]}).fetchall()

        if rows:
            scores = [float(r[0]) for r in rows if r[0] is not None]
            pos = sum(1 for r in rows if r[1] and str(r[1]) == "positive")
            neg = sum(1 for r in rows if r[1] and str(r[1]) == "negative")
            ds.news_volume_30d = len(scores)
            if scores:
                ds.avg_news_sentiment = round(sum(scores) / len(scores), 4)
            labeled = pos + neg
            if labeled > 0:
                ds.positive_news_pct = round(pos / labeled * 100, 1)
                ds.negative_news_pct = round(neg / labeled * 100, 1)

    def _load_rera_launches(self, conn, ds: DemandSignals, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("demand_rera_launches"):
            row = conn.execute(text("""
                SELECT COUNT(*) AS projects, COALESCE(SUM(r.total_units), 0) AS units
                FROM rera_projects r
                JOIN micro_markets mm ON mm.id = r.micro_market_id
                WHERE mm.slug = :slug
                  AND r.launch_date >= CURRENT_DATE - INTERVAL '90 days'
            """), {"slug": mi["slug"]}).fetchone()
        if row:
            ds.new_rera_launches_90d = int(row[0]) if row[0] else 0
            ds.new_launch_units = int(row[1]) if row[1] else 0

    def _load_developer_activity(self, conn, ds: DemandSignals, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("demand_developer"):
            row = conn.execute(text("""
                SELECT
                    COUNT(DISTINCT r.developer_id) AS total_devs,
                    COUNT(DISTINCT CASE WHEN d.grade = 'A' THEN d.id END) AS grade_a,
                    COUNT(CASE WHEN r.project_status = 'Under Construction' THEN 1 END) * 100.0
                        / NULLIF(COUNT(*), 0) AS under_construction_pct
                FROM rera_projects r
                JOIN micro_markets mm ON mm.id = r.micro_market_id
                LEFT JOIN developers d ON r.developer_id = d.id
                WHERE mm.slug = :slug AND r.is_active = TRUE
            """), {"slug": mi["slug"]}).fetchone()
        if row:
            total_devs = int(row[0]) if row[0] else 0
            grade_a = int(row[1]) if row[1] else 0
            if total_devs > 0:
                ds.grade_a_share_pct = round(grade_a / total_devs * 100, 1)
                ds.developer_confidence_pct = round(grade_a / total_devs * 100, 1)
            ds.underconstruction_pct = fval(row[2])

    def _load_absorption_velocity(self, conn, ds: DemandSignals, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("demand_absorption_velocity"):
            row = conn.execute(text("""
                SELECT AVG(ps.units_sold_this_period) AS avg_monthly_abs
                FROM project_snapshots ps
                JOIN rera_projects r ON r.id = ps.rera_project_id
                JOIN micro_markets mm ON mm.id = r.micro_market_id
                WHERE mm.slug = :slug
                  AND ps.units_sold_this_period IS NOT NULL
                  AND ps.snapshot_date >= CURRENT_DATE - INTERVAL '12 months'
            """), {"slug": mi["slug"]}).fetchone()
        if row and row[0]:
            ds.monthly_absorption_rate_units = round(float(row[0]), 1)

    def _compute_price_momentum(self, ds: DemandSignals):
        if ds.listing_trend_30d_pct is not None:
            if ds.listing_trend_30d_pct > 3.0:
                ds.price_momentum_signal = "BULLISH"
                ds.signals.append(
                    f"Price momentum {ds.listing_trend_30d_pct:+.1f}% (30d) — market heating up"
                )
            elif ds.listing_trend_30d_pct < -3.0:
                ds.price_momentum_signal = "BEARISH"
                ds.signals.append(
                    f"Price momentum {ds.listing_trend_30d_pct:+.1f}% (30d) — softness detected"
                )
            else:
                ds.price_momentum_signal = "NEUTRAL"

    def _compute_demand_signal(self, ds: DemandSignals):
        """Weighted composite scoring:
          - months_of_supply: 2x weight
          - price_momentum: 1.5x
          - absorption_rate: 1.5x
          - news_sentiment: 1x
          - new_launches: 1x
        """
        bullish = 0.0
        bearish = 0.0

        if ds.months_of_supply is not None:
            if ds.months_of_supply < 9:
                bullish += 2.0
            elif ds.months_of_supply > 18:
                bearish += 2.0

        if ds.price_momentum_signal == "BULLISH":
            bullish += 1.5
        elif ds.price_momentum_signal == "BEARISH":
            bearish += 1.5

        if ds.absorption_pct is not None:
            if ds.absorption_pct > 60:
                bullish += 1.5
            elif ds.absorption_pct < 30:
                bearish += 1.5

        if ds.avg_news_sentiment is not None:
            if ds.avg_news_sentiment > 0.1:
                bullish += 1.0
            elif ds.avg_news_sentiment < -0.1:
                bearish += 1.0

        if ds.new_rera_launches_90d > 5:
            bearish += 1.0
        elif ds.new_rera_launches_90d == 0:
            bullish += 0.5
        else:
            bearish += 0.5

        ds.demand_score = round(bullish - bearish, 1)

        if ds.demand_score > 1.5:
            ds.demand_signal = "BULLISH"
            ds.signals.append(
                f"Overall: BULLISH (score {ds.demand_score:+.1f}) — market favouring sellers"
            )
        elif ds.demand_score < -1.5:
            ds.demand_signal = "BEARISH"
            ds.signals.append(
                f"Overall: BEARISH (score {ds.demand_score:+.1f}) — market favouring buyers"
            )
        else:
            ds.demand_signal = "NEUTRAL"
            ds.signals.append(
                f"Overall: NEUTRAL (score {ds.demand_score:+.1f}) — balanced market"
            )


if __name__ == "__main__":
    import json
    ds = DemandIntel(caller="self_test").get_signals("Yelahanka")
    print(json.dumps({
        "market": ds.market,
        "market_found": ds.market_found,
        "demand_signal": ds.demand_signal,
        "demand_score": ds.demand_score,
        "price_momentum": ds.listing_trend_30d_pct,
        "avg_psf": ds.avg_listing_psf,
        "absorption": ds.absorption_pct,
        "mos": ds.months_of_supply,
        "news_sentiment": ds.avg_news_sentiment,
        "signals": ds.signals,
    }, indent=2, default=str))
