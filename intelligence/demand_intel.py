"""
RE_OS — Demand Intelligence Module (Sprint 55 V2 + Sprint 62 V1)

DemandIntel.get_signals(market): weighted composite demand signal with v1 and v2
scoring. V2 (Sprint 55) adds config_absorption, days_on_market, ticket_size_median,
absorption_trend, days_on_market_by_config, and demand_score_v2 (composite 0-1).

Signal scoring (v1):
  - months_of_supply (2x): <9 undersupply=bullish, >18 oversupply=bearish
  - price_momentum (1.5x): 30d non-overlapping PSF change
  - absorption_rate (1.5x): >60% = bullish, <30% = bearish
  - news_sentiment (1x): avg FinBERT score
  - new_launches (1x): 90d RERA registration velocity
V2 composite (demand_score_v2): absorption_norm×0.40 + kaveri_norm×0.30 +
  listing_norm×0.20 + config_balance×0.10, bounded [0, 1].
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

    # Kaveri 2.0 official registration velocity — SRO-level counts via
    # kaveri.karnataka.gov.in/api/GetCitizenDashboard (ApplicationTypeid=13)
    # All document types at SRO (sale deeds + mortgages + GPA + gifts etc.)
    # State avg ~3,580/SRO/month across 262 SROs — above that = active market
    kaveri_monthly_approvals: float | None = None    # official approvals/month (6-month avg)
    kaveri_registrations_180d: int = 0
    kaveri_velocity_ratio: float | None = None        # vs state avg SRO baseline

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

    # V2 demand intelligence signals (Sprint 55 — GATE-63)
    config_absorption: dict[str, float] = field(default_factory=dict)
    days_on_market_p50: float | None = None
    ticket_size_median_cr: float | None = None
    demand_score_v2: float = 0.0
    absorption_trend: list[dict] = field(default_factory=list)
    days_on_market_by_config: dict[str, float] = field(default_factory=dict)

    # V3 GCC demand signal (Sprint 67 — GATE-71)
    # Forward-looking corporate pipeline pressure — the only leading indicator
    # in demand_score_v2. Rising norm + flat absorption = demand accumulating
    # before listing data has registered it.
    gcc_north_norm: float | None = None

    # Sprint 73 — Land supply pipeline (GATE-73)
    # Future supply from RERA pre-registrations, KIADB tenders, and
    # BDA/BMRDA layout approvals. Feeds _timing_score() penalty.
    pipeline_supply_units: int = 0

    # Sprint 75 — Govt/Infra/Policy pipeline signal (GATE-75)
    # 6th component of demand_score_v2. Captures government infrastructure
    # and policy momentum for North Bengaluru. Derived from GovtPolicyIntel.
    infra_pipeline_norm: float | None = None

    # Sprint 94 — Demand coefficient calibration status (GATE-94, T-1154)
    # "UNCALIBRATED" until Manyata backcast validation passes.
    # Set to "CALIBRATED" by demand_calibration.py once coefficient verified.
    calibration_status: str = "UNCALIBRATED"

    signals: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        trend = f"{(self.listing_trend_30d_pct or 0.0):+.1f}%"
        score = f"{(self.demand_score or 0.0):.1f}"
        score_v2 = f"{(self.demand_score_v2 or 0.0):.2f}"
        mos = self.months_of_supply
        mos_str = f"{mos:.1f}" if mos is not None else "N/A"
        kav = (
            f" | Kaveri {self.kaveri_monthly_approvals:.0f}/mo"
            if self.kaveri_monthly_approvals
            else ""
        )
        signal = self.demand_signal or "UNKNOWN"
        cal_label = f"[{self.calibration_status}]" if self.calibration_status != "CALIBRATED" else ""
        parts = [
            f"[DemandSignals:{self.market}] {cal_label} {signal} (v1={score}, v2={score_v2})".strip(),
            f"PSF momentum {trend}",
            f"{mos_str} MoS{kav}",
        ]
        if self.gcc_north_norm is not None:
            parts.append(f"GCC norm={self.gcc_north_norm:.3f}")
        if self.pipeline_supply_units > 0:
            parts.append(f"pipeline {self.pipeline_supply_units}u")
        if self.infra_pipeline_norm is not None:
            parts.append(f"infra_norm={self.infra_pipeline_norm:.3f}")
        if self.days_on_market_p50 is not None:
            parts.append(f"DoM {self.days_on_market_p50:.0f}d")
        if self.ticket_size_median_cr:
            parts.append(f"ticket ₹{self.ticket_size_median_cr:.2f}Cr")
        if self.config_absorption:
            parts.append(f"config_abs {len(self.config_absorption)} configs")
        if self.absorption_trend:
            parts.append(f"trend {len(self.absorption_trend)}mo")
        if self.days_on_market_by_config:
            parts.append(f"DoM_config {len(self.days_on_market_by_config)} configs")
        return " | ".join(parts)


class DemandIntel:
    """Demand signal analysis with weighted composite scoring.

    Risk Register:
    | Risk | Impact | Mitigation |
    |------|--------|------------|
    | DB connection timeout | Degraded signals (empty fields) | Each _load_* wrapped in try/except; get_signals returns partial data |
    | Portal NRI scrape failure | No nri_query events | _fetch_nri_listings returns empty list, logs debug |
    | Config absorption N+1 | 6 extra roundtrips per market | Optimized to single GROUP BY queries (R2 fix) |
    | Kaveri portal unreachable | No kaveri_velocity_ratio | Silent skip, logs debug |
    | MarketCache stale data | 15-min stale signals | TTL-based expiry; invalidate_cache() available |

    Usage:
        ds = DemandIntel().get_signals("Yelahanka")
        print(ds.demand_signal, ds.signals)
    """

    def __init__(self, caller: str = ""):
        self._cache = MarketCache()
        self._caller = caller or "DemandIntel"

    def _with_db(self, market: str, fn, *args, **kwargs):
        """Execute *fn(conn, mi, *args, **kwargs)* with a validated DB connection.

        Returns fn's return value on success, empty/None on failure.
        Handles sanitization, validation, DB connection, and error logging.
        """
        m = sanitize_market(market)
        if not m:
            return None
        mi = validate_market(m)
        if mi is None:
            return None
        try:
            from utils.db import get_engine
            from sqlalchemy import text
            with get_engine(pool_size=2, max_overflow=1).connect() as conn:
                return fn(conn, mi, *args, **kwargs)
        except Exception as exc:
            logger.warning("[{}] DB op failed for {}: {}", self._caller, market, exc)
        return None

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
                self._load_kaveri_registration_velocity(conn, ds, mi)
                self._load_config_absorption(conn, ds, mi)
                self._load_days_on_market(conn, ds, mi)
                self._load_ticket_size_median(conn, ds, mi)
                self._load_absorption_trend(conn, ds, mi)
                self._load_days_on_market_by_config(conn, ds, mi)
                self._load_pipeline_supply(conn, ds, mi)

            self._load_gcc_signal(ds, mi)
            self._load_govt_pipeline_signal(ds, mi)
            self._compute_price_momentum(ds)
            self._compute_demand_signal(ds)
            self._compute_demand_score_v2(ds)
            self._cache.set(_CACHE_NS, m, ds, is_positive=True)

        except (MemoryError, KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            logger.warning("[{}] get_signals({}) failed: {}", self._caller, m, exc)

        return ds

    def invalidate_cache(self, market: str | None = None):
        self._cache.invalidate(_CACHE_NS, sanitize_market(market) if market else None)

    def get_config_absorption(self, market: str) -> dict[str, float]:
        result = self._with_db(market, self._query_config_absorption)
        return result if result is not None else {}

    # Normalization ceiling for kaveri_velocity_ratio in demand_score_v2.
    # Derived from observed max across 3 monitored SROs (Jala/224, Devanahalli/118, Hebbal/208)
    # relative to state avg 3,580/month. 3.0x means a market doing ~10,740/month (top-decile).
    _KAVERI_VELOCITY_CEILING = 3.0

    def _query_config_absorption(self, conn, mi: dict) -> dict[str, float]:
        from sqlalchemy import text
        with timed_intel_query("demand_config_absorption"):
            rows = conn.execute(text("""
                SELECT
                    CASE
                        WHEN rp.unit_mix::text ILIKE '%1BHK%' OR rp.project_type ILIKE '%1BHK%' THEN '1BHK'
                        WHEN rp.unit_mix::text ILIKE '%2BHK%' OR rp.project_type ILIKE '%2BHK%' THEN '2BHK'
                        WHEN rp.unit_mix::text ILIKE '%3BHK%' OR rp.project_type ILIKE '%3BHK%' THEN '3BHK'
                        ELSE 'OTHER'
                    END AS bhk_label,
                    AVG(rp.absorption_pct) AS avg_absorption
                FROM rera_projects rp
                JOIN micro_markets mm ON mm.id = rp.micro_market_id
                WHERE mm.slug = :slug
                  AND rp.is_active = TRUE
                  AND rp.total_units IS NOT NULL AND rp.total_units > 0
                  AND (
                      rp.unit_mix::text ILIKE '%1BHK%' OR rp.project_type ILIKE '%1BHK%'
                      OR rp.unit_mix::text ILIKE '%2BHK%' OR rp.project_type ILIKE '%2BHK%'
                      OR rp.unit_mix::text ILIKE '%3BHK%' OR rp.project_type ILIKE '%3BHK%'
                  )
                GROUP BY bhk_label
                ORDER BY bhk_label
            """), {"slug": mi["slug"]}).fetchall()
        return {str(r[0]): round(float(r[1]), 2) for r in rows if r[0] and r[1]}

    def _load_config_absorption(self, conn, ds: DemandSignals, mi: dict):
        ds.config_absorption = self._query_config_absorption(conn, mi)

    def _load_days_on_market(self, conn, ds: DemandSignals, mi: dict):
        """Median days to reach 80% absorption across all projects in market.

        Uses launch_date + sold_units/total_units ratio as a proxy for
        absorption velocity. Projects with <80% sold are excluded. Returns
        None when fewer than 3 projects have reached the 80% threshold.
        """
        from sqlalchemy import text
        with timed_intel_query("demand_days_on_market"):
            rows = conn.execute(text("""
                SELECT rp.launch_date, rp.sold_units, rp.total_units
                FROM rera_projects rp
                JOIN micro_markets mm ON mm.id = rp.micro_market_id
                WHERE mm.slug = :slug
                  AND rp.launch_date IS NOT NULL
                  AND rp.total_units IS NOT NULL AND rp.total_units > 0
                  AND rp.sold_units IS NOT NULL
            """), {"slug": mi["slug"]}).fetchall()
        days_list = []
        for row in rows:
            launch_date, sold_units, total_units = row
            if launch_date is None or total_units is None or total_units <= 0:
                continue
            absorption_pct = (sold_units / total_units) * 100
            if absorption_pct < 80:
                continue
            days_since_launch = (datetime.now(timezone.utc).date() - launch_date).days
            if days_since_launch <= 0:
                continue
            days_list.append(days_since_launch)
        if len(days_list) >= 3:
            sorted_days = sorted(days_list)
            ds.days_on_market_p50 = float(sorted_days[len(sorted_days) // 2])

    def _load_ticket_size_median(self, conn, ds: DemandSignals, mi: dict):
        from sqlalchemy import text
        with timed_intel_query("demand_ticket_size_median"):
            row = conn.execute(text("""
                SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY (l.price_psf * 1000.0 / 100.0))
            FROM listings l
            JOIN micro_markets mm ON mm.id = l.micro_market_id
            WHERE mm.slug = :slug
              AND l.price_psf IS NOT NULL AND l.price_psf > 1000 AND l.price_psf < 50000
              AND l.transaction_type = 'Sale'
              AND l.last_seen_at >= NOW() - INTERVAL '90 days'
        """), {"slug": mi["slug"]}).fetchone()
        if row and row[0] is not None:
            ds.ticket_size_median_cr = round(float(row[0]), 2)

    def _compute_demand_score_v2(self, ds: DemandSignals):
        """Composite demand score [0, 1] from up to 6 weighted factors.

        V4 weights (Sprint 75 — GATE-75, 6 components):
          absorption_pct_norm  × 0.30  (was 0.35)
          kaveri_norm          × 0.18  (was 0.25)
          listing_count_norm   × 0.12  (was 0.18)
          config_balance       × 0.12  (was 0.07)
          gcc_north_norm       × 0.13  (was 0.15)
          infra_pipeline_norm  × 0.15  (NEW — govt/infra/policy pipeline)

        gcc_north_norm is the leading indicator for corporate demand.
        infra_pipeline_norm is the leading indicator for government-driven
        demand. Rising infra + flat absorption = demand accumulating from
        infrastructure-led development before listings reflect it.

        Falls back to a clamped transform of v1 demand_score when no
        v2/v3/v4 components are available: max(0, (v1 + 5) / 10, 1).
        """
        components: list[float] = []
        weights: list[float] = []

        if ds.absorption_pct is not None:
            components.append(min(ds.absorption_pct / 100.0, 1.0))
            weights.append(0.30)

        if ds.kaveri_velocity_ratio is not None:
            components.append(min(ds.kaveri_velocity_ratio / self._KAVERI_VELOCITY_CEILING, 1.0))
            weights.append(0.18)

        if ds.listing_count_30d > 0:
            listing_norm = min(ds.listing_count_30d / 200.0, 1.0)
            components.append(listing_norm)
            weights.append(0.12)

        if ds.config_absorption:
            values = [v for v in ds.config_absorption.values() if v is not None]
            if values:
                observed_range = max(values) - min(values)
                if max(values) > min(values):
                    balance = 1.0 - min(observed_range / 100.0, 1.0)
                else:
                    balance = 1.0
                components.append(max(0.0, min(balance, 1.0)))
                weights.append(0.12)

        # 5th component: GCC forward-looking pipeline (Sprint 67)
        if ds.gcc_north_norm is not None and ds.gcc_north_norm >= 0.0:
            components.append(min(ds.gcc_north_norm, 1.0))
            weights.append(0.13)

        # 6th component: Govt/Infra/Policy pipeline (Sprint 75 — GATE-75)
        if ds.infra_pipeline_norm is not None and ds.infra_pipeline_norm >= 0.0:
            components.append(min(ds.infra_pipeline_norm, 1.0))
            weights.append(0.15)

        if components:
            total_weight = sum(weights)
            ds.demand_score_v2 = round(
                sum(c * w for c, w in zip(components, weights)) / total_weight, 4
            )
        else:
            ds.demand_score_v2 = round(max(0.0, min((ds.demand_score + 5.0) / 10.0, 1.0)), 4)

    def get_absorption_trend(self, market: str, months: int = 6) -> list[dict]:
        result = self._with_db(market, self._query_absorption_trend, months)
        return result if result is not None else []

    def _query_absorption_trend(self, conn, mi: dict, months: int = 6) -> list[dict]:
        from sqlalchemy import text
        with timed_intel_query("demand_absorption_trend"):
            rows = conn.execute(text("""
                SELECT
                TO_CHAR(DATE_TRUNC('month', ps.snapshot_date), 'YYYY-MM') AS month,
                AVG(rp.absorption_pct) AS avg_absorption_pct,
                COUNT(DISTINCT ps.rera_project_id) AS project_count
            FROM project_snapshots ps
            JOIN rera_projects rp ON rp.id = ps.rera_project_id
            JOIN micro_markets mm ON mm.id = rp.micro_market_id
            WHERE mm.slug = :slug
              AND ps.snapshot_date >= CURRENT_DATE - (INTERVAL '1 month' * :months)
              AND rp.absorption_pct IS NOT NULL
            GROUP BY DATE_TRUNC('month', ps.snapshot_date)
            ORDER BY month ASC
        """), {"slug": mi["slug"], "months": months}).fetchall()
        return [
            {
                "month": str(r[0]),
                "avg_absorption_pct": round(float(r[1]), 2) if r[1] else 0.0,
                "project_count": int(r[2]) if r[2] else 0,
            }
            for r in rows
        ]

    def _load_absorption_trend(self, conn, ds: DemandSignals, mi: dict):
        ds.absorption_trend = self._query_absorption_trend(conn, mi, months=6)

    def days_on_market_by_config(self, market: str) -> dict[str, float]:
        result = self._with_db(market, self._query_days_on_market_by_config)
        return result if result is not None else {}

    def _query_days_on_market_by_config(self, conn, mi: dict) -> dict[str, float]:
        from sqlalchemy import text
        with timed_intel_query("demand_days_on_market_by_config"):
            rows = conn.execute(text("""
                SELECT
                    CASE
                        WHEN rp.unit_mix::text ILIKE '%1BHK%' OR rp.project_type ILIKE '%1BHK%' THEN '1BHK'
                        WHEN rp.unit_mix::text ILIKE '%2BHK%' OR rp.project_type ILIKE '%2BHK%' THEN '2BHK'
                        WHEN rp.unit_mix::text ILIKE '%3BHK%' OR rp.project_type ILIKE '%3BHK%' THEN '3BHK'
                        ELSE 'OTHER'
                    END AS bhk_label,
                    AVG(EXTRACT(DAY FROM (CURRENT_DATE - rp.launch_date))) AS avg_days
                FROM rera_projects rp
                JOIN micro_markets mm ON mm.id = rp.micro_market_id
                WHERE mm.slug = :slug
                  AND rp.launch_date IS NOT NULL
                  AND rp.total_units IS NOT NULL AND rp.total_units > 0
                  AND (
                      rp.unit_mix::text ILIKE '%1BHK%' OR rp.project_type ILIKE '%1BHK%'
                      OR rp.unit_mix::text ILIKE '%2BHK%' OR rp.project_type ILIKE '%2BHK%'
                      OR rp.unit_mix::text ILIKE '%3BHK%' OR rp.project_type ILIKE '%3BHK%'
                  )
                  AND rp.sold_units IS NOT NULL
                  AND (rp.sold_units::DECIMAL / rp.total_units) >= 0.5
                GROUP BY bhk_label
                ORDER BY bhk_label
            """), {"slug": mi["slug"]}).fetchall()
        return {str(r[0]): float(round(float(r[1]))) for r in rows if r[0] and r[1]}

    def _load_days_on_market_by_config(self, conn, ds: DemandSignals, mi: dict):
        ds.days_on_market_by_config = self._query_days_on_market_by_config(conn, mi)

    def _load_listing_trends(self, conn, ds: DemandSignals, mi: dict):
        from sqlalchemy import text

        with timed_intel_query("demand_listing_30d"):
            row30 = conn.execute(text("""
                SELECT
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY l.price_psf) AS median_psf,
                    AVG(l.price_psf) AS avg_psf,
                    COUNT(*) AS cnt
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.slug = :slug
                  AND l.price_psf IS NOT NULL AND l.price_psf > 1000 AND l.price_psf < 50000
                  AND l.last_seen_at >= NOW() - INTERVAL '30 days'
            """), {"slug": mi["slug"]}).fetchone()

        with timed_intel_query("demand_listing_90d_prior"):
            row90_prior = conn.execute(text("""
                SELECT AVG(l.price_psf) AS avg_psf, COUNT(*) AS cnt
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.slug = :slug
                  AND l.price_psf IS NOT NULL AND l.price_psf > 1000 AND l.price_psf < 50000
                  AND l.last_seen_at >= NOW() - INTERVAL '60 days'
                  AND l.last_seen_at < NOW() - INTERVAL '31 days'
            """), {"slug": mi["slug"]}).fetchone()

        with timed_intel_query("demand_listing_90d"):
            row90 = conn.execute(text("""
                SELECT AVG(l.price_psf) AS avg_psf, COUNT(*) AS cnt
                FROM listings l
                JOIN micro_markets mm ON mm.id = l.micro_market_id
                WHERE mm.slug = :slug
                  AND l.price_psf IS NOT NULL AND l.price_psf > 1000 AND l.price_psf < 50000
                  AND l.last_seen_at >= NOW() - INTERVAL '90 days'
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
                FROM v_market_brief_mat
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

    # Karnataka state avg SRO monthly approvals (2,064,277 approved / 262 SROs / 2.2 months)
    # Derived from unfiltered Kaveri API, FY2025-26 Apr–Jun 2026.
    _KAVERI_STATE_AVG_MONTHLY = 3_580.0

    def _load_kaveri_registration_velocity(self, conn, ds: DemandSignals, mi: dict):
        """
        Fetch 6-month registration approval count from Kaveri 2.0 API.

        Source: kaveri.karnataka.gov.in/api/GetCitizenDashboard (ApplicationTypeid=13)
        SRO codes: Yelahanka→Jala(224), Devanahalli(118), Hebbal(208)

        Counts ALL document types at the SRO (sale deeds, mortgages, GPA, gifts, etc.).
        We express it as a ratio vs the Karnataka state average SRO (~3,580/month)
        to give a market-relative activity signal — not an absolute MoS.

        Signals:
          ratio ≥ 1.5x state avg → market highly active (+0.5 bullish)
          ratio ≤ 0.4x state avg → market quiet (-0.5 bearish)
          otherwise              → neutral data point
        """
        from datetime import date, timedelta

        to_date = date.today().isoformat()
        from_date = (date.today() - timedelta(days=180)).isoformat()

        try:
            from scrapers.kaveri_gazette_parser import GazetteParser
            vol = GazetteParser().scrape_registration_velocity_signal(mi["name"], from_date, to_date)
            if not vol:
                return

            approved = int(vol.get("applications_approved", 0))
            if approved <= 0:
                return

            ds.kaveri_registrations_180d = approved
            monthly = round(approved / 6.0, 1)
            ds.kaveri_monthly_approvals = monthly
            ratio = round(monthly / self._KAVERI_STATE_AVG_MONTHLY, 2)
            ds.kaveri_velocity_ratio = ratio

            if ratio >= 1.5:
                ds.signals.append(
                    f"Kaveri SRO: {monthly:,.0f} registrations/month "
                    f"({ratio:.1f}x state avg) — high market activity"
                )
            elif ratio <= 0.4:
                ds.signals.append(
                    f"Kaveri SRO: {monthly:,.0f} registrations/month "
                    f"({ratio:.1f}x state avg) — below-average activity"
                )
            else:
                logger.debug(
                    "[DemandIntel] Kaveri velocity {}: {}/month ({:.2f}x state avg)",
                    mi["name"], monthly, ratio,
                )

        except Exception as exc:
            logger.debug("[DemandIntel] Kaveri registration velocity failed for {}: {}", mi["name"], exc)

    def _query_pipeline_supply(self, conn, mi: dict) -> int:
        from sqlalchemy import text
        with timed_intel_query("demand_pipeline_supply"):
            row = conn.execute(text("""
                SELECT COALESCE(SUM(estimated_units), 0)
                FROM supply_pipeline sp
                JOIN micro_markets mm ON LOWER(mm.name) ILIKE sp.market
                WHERE mm.slug = :slug
                  AND (
                      sp.expected_completion_year >= EXTRACT(YEAR FROM NOW())
                      OR sp.expected_completion_year IS NULL
                  )
            """), {"slug": mi["slug"]}).fetchone()
        return int(row[0]) if row and row[0] else 0

    def _load_pipeline_supply(self, conn, ds: DemandSignals, mi: dict):
        ds.pipeline_supply_units = self._query_pipeline_supply(conn, mi)

    def _load_gcc_signal(self, ds: DemandSignals, mi: dict):
        """Load gcc_north_norm from GCCIntel — the forward-looking GCC pipeline score."""
        try:
            from intelligence.gcc_intel import GCCIntel
            result = GCCIntel(caller="DemandIntel").get_gcc_score(mi["name"])
            ds.gcc_north_norm = result.gcc_north_norm
            if result.signals:
                ds.signals.extend(result.signals)
        except Exception as exc:
            logger.debug("[DemandIntel] gcc signal load failed for {}: {}", mi["name"], exc)

    def _load_govt_pipeline_signal(self, ds: DemandSignals, mi: dict):
        """Load infra_pipeline_norm from GovtPolicyIntel — the 6th demand component."""
        try:
            from intelligence.govt_policy_intel import GovtPolicyIntel
            result = GovtPolicyIntel(caller="DemandIntel").compute(mi["name"])
            ds.infra_pipeline_norm = result.north_bengaluru_score
        except Exception as exc:
            logger.debug("[DemandIntel] govt pipeline signal load failed for {}: {}", mi["name"], exc)
            ds.infra_pipeline_norm = 0.5  # neutral fallback

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
          - months_of_supply: 2x weight (Kaveri official preferred over listing-derived)
          - price_momentum: 1.5x
          - absorption_rate: 1.5x
          - news_sentiment: 1x
          - new_launches: 1x
        """
        bullish = 0.0
        bearish = 0.0

        mos = ds.months_of_supply
        if mos is not None:
            if mos < 9:
                bullish += 2.0
            elif mos > 18:
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

        # Kaveri official registration velocity (0.5x weight — confirmatory)
        if ds.kaveri_velocity_ratio is not None:
            if ds.kaveri_velocity_ratio >= 1.5:
                bullish += 0.5
            elif ds.kaveri_velocity_ratio <= 0.4:
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
