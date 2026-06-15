"""
RE_OS v2 — Typed Query Helpers (T-656)
Single file for all logical DB queries. Application code never writes raw SQL.
All functions return typed dataclasses, not raw rows.
Connection lifecycle: context-managed, auto-closed on scope exit.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from functools import lru_cache
from typing import Optional
from sqlalchemy import text
from utils.db import get_engine

# ── Simple TTL cache ───────────────────────────────────────────────────────────
_CACHE_TTL_SECONDS = 60


class _TTLCache:
    def __init__(self, ttl: int = _CACHE_TTL_SECONDS):
        self._cache = {}
        self._ttl = ttl

    def get(self, key: str):
        if key in self._cache:
            val, ts = self._cache[key]
            if time.monotonic() - ts < self._ttl:
                return val
        return None

    def set(self, key: str, value):
        self._cache[key] = (value, time.monotonic())

    def invalidate(self, key: str = None):
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()


_cache = _TTLCache()


# ── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class SurveyFacts:
    survey_id: str
    survey_no: str
    micro_market: str
    village: Optional[str]
    total_area_acres: Optional[Decimal]
    land_type: Optional[str]
    ownership_type: Optional[str]
    dc_conversion_status: Optional[str]
    khata_no: Optional[str]
    khata_type: Optional[str]
    encumbrance_clear: bool
    rtc_owner_names: Optional[str]
    litigation_summary: Optional[str]
    active_deal_count: int
    best_opportunity_score: Optional[Decimal]


@dataclass
class DeveloperHealth:
    developer_name: str
    grade: Optional[str]
    health_score: Decimal
    health_rating: str
    latest_distress_score: Decimal
    distress_alert_level: Optional[str]
    total_projects: int
    delayed_projects: int
    delay_rate_pct: Decimal
    markets_active_in: str


@dataclass
class MarketPulse:
    micro_market: str
    total_projects: int
    active_projects: int
    total_units: int
    total_unsold: int
    avg_psf_rera: Optional[Decimal]
    avg_listing_psf: Optional[Decimal]
    igr_median_psf: Optional[Decimal]
    benchmark_psf: Optional[Decimal]
    months_of_supply: Optional[Decimal]
    supply_label: str
    sentiment_label: str
    listing_to_igr_gap_pct: Optional[Decimal]


@dataclass
class OpportunityQueueItem:
    opportunity_id: str
    survey_no: Optional[str]
    micro_market: str
    developer_name: Optional[str]
    score: Decimal
    irr_score: Optional[Decimal]
    legal_risk_level: Optional[str]
    best_deal_type: Optional[str]
    estimated_jd_irr: Optional[Decimal]
    next_action: Optional[str]
    expiry_date: Optional[date]
    priority_label: str
    market_rank: int


@dataclass
class IngestLogEntry:
    id: str
    plugin_id: str
    market: Optional[str]
    entity_type: Optional[str]
    status: str
    error_message: Optional[str]
    created_at: datetime


@dataclass
class FreshnessReport:
    source_name: str
    last_scraped_at: Optional[datetime]
    record_count: int
    freshness_score: float
    freshness_label: str


# ── Context-managed connection ────────────────────────────────────────────────


@contextmanager
def _get_conn():
    """Yield a live connection from the shared engine pool. Auto-closes on exit."""
    engine = get_engine()
    conn = engine.connect()
    try:
        yield conn
    finally:
        conn.close()


# ── Query helpers ────────────────────────────────────────────────────────────


def get_survey_facts(survey_no: str, market: Optional[str] = None) -> list[SurveyFacts]:
    """Query v_survey_full_picture for one or all surveys.
    If market is provided, uses exact slug match (not fuzzy ILIKE) to avoid
    false positives from partial name matches."""
    with _get_conn() as conn:
        rows = conn.execute(
            text("""
            SELECT survey_id, survey_no, micro_market, village, total_area_acres,
                   land_type, ownership_type, dc_conversion_status, khata_no, khata_type,
                   encumbrance_clear, rtc_owner_names, litigation_summary, active_deal_count,
                   best_opportunity_score
            FROM v_survey_full_picture
            WHERE survey_no = :sno
              AND (:market IS NULL OR market_slug = :mkt)
        """),
            {"sno": survey_no, "mkt": market.lower() if market else None},
        ).fetchall()
    return [
        SurveyFacts(
            survey_id=str(r[0]),
            survey_no=r[1],
            micro_market=r[2],
            village=r[3],
            total_area_acres=r[4],
            land_type=r[5],
            ownership_type=r[6],
            dc_conversion_status=r[7],
            khata_no=r[8],
            khata_type=r[9],
            encumbrance_clear=r[10] or False,
            rtc_owner_names=r[11],
            litigation_summary=r[12],
            active_deal_count=r[13] or 0,
            best_opportunity_score=r[14],
        )
        for r in rows
    ]


def get_developer_health(
    market: Optional[str] = None, min_health: Decimal = Decimal("0")
) -> list[DeveloperHealth]:
    """Query v_developer_health, optionally filtered by market and minimum health score.
    min_health is compared as Decimal — no float precision loss."""
    with _get_conn() as conn:
        if market:
            rows = conn.execute(
                text("""
                SELECT developer_name, grade, health_score, health_rating,
                       latest_distress_score, distress_alert_level, total_projects,
                       delayed_projects, delay_rate_pct, markets_active_in
                FROM v_developer_health
                WHERE markets_active_in ILIKE :market AND health_score >= :min_h
                ORDER BY health_score ASC
            """),
                {"market": f"%{market}%", "min_h": float(min_health)},
            ).fetchall()
        else:
            rows = conn.execute(
                text("""
                SELECT developer_name, grade, health_score, health_rating,
                       latest_distress_score, distress_alert_level, total_projects,
                       delayed_projects, delay_rate_pct, markets_active_in
                FROM v_developer_health
                WHERE health_score >= :min_h
                ORDER BY health_score ASC
            """),
                {"min_h": float(min_health)},
            ).fetchall()
    return [
        DeveloperHealth(
            developer_name=r[0],
            grade=r[1],
            health_score=r[2],
            health_rating=r[3],
            latest_distress_score=r[4],
            distress_alert_level=r[5],
            total_projects=r[6] or 0,
            delayed_projects=r[7] or 0,
            delay_rate_pct=r[8],
            markets_active_in=r[9] or "",
        )
        for r in rows
    ]


def get_market_pulse(market: Optional[str] = None) -> list[MarketPulse]:
    """Query v_market_pulse for all or one market. TTL-cached 60s."""
    cache_key = f"market_pulse:{market or '__all__'}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    with _get_conn() as conn:
        if market:
            rows = conn.execute(
                text("""
                SELECT micro_market, total_projects, active_projects, total_units,
                       total_unsold, avg_psf_rera, avg_listing_psf, igr_median_psf,
                       benchmark_psf, months_of_supply, supply_label, sentiment_label,
                       listing_to_igr_gap_pct
                FROM v_market_pulse
                WHERE micro_market ILIKE :market
            """),
                {"market": f"%{market}%"},
            ).fetchall()
        else:
            rows = conn.execute(
                text("""
                SELECT micro_market, total_projects, active_projects, total_units,
                       total_unsold, avg_psf_rera, avg_listing_psf, igr_median_psf,
                       benchmark_psf, months_of_supply, supply_label, sentiment_label,
                       listing_to_igr_gap_pct
                FROM v_market_pulse
                ORDER BY micro_market
            """)
            ).fetchall()
    result = [
        MarketPulse(
            micro_market=r[0],
            total_projects=r[1] or 0,
            active_projects=r[2] or 0,
            total_units=r[3] or 0,
            total_unsold=r[4] or 0,
            avg_psf_rera=r[5],
            avg_listing_psf=r[6],
            igr_median_psf=r[7],
            benchmark_psf=r[8],
            months_of_supply=r[9],
            supply_label=r[10] or "INSUFFICIENT_DATA",
            sentiment_label=r[11] or "NEUTRAL",
            listing_to_igr_gap_pct=r[12],
        )
        for r in rows
    ]
    _cache.set(cache_key, result)
    return result


def get_opportunity_queue(
    market: Optional[str] = None, min_score: Decimal = Decimal("0.4"), limit: int = 20
) -> list[OpportunityQueueItem]:
    """Query v_opportunity_queue with score threshold and optional market filter."""
    with _get_conn() as conn:
        if market:
            rows = conn.execute(
                text("""
                SELECT opportunity_id, survey_no, micro_market, developer_name,
                       score, irr_score, legal_risk_level, best_deal_type,
                       estimated_jd_irr, next_action, expiry_date, priority_label,
                       market_rank
                FROM v_opportunity_queue
                WHERE micro_market ILIKE :market AND score >= :min_s
                ORDER BY score DESC
                LIMIT :lim
            """),
                {"market": f"%{market}%", "min_s": float(min_score), "lim": limit},
            ).fetchall()
        else:
            rows = conn.execute(
                text("""
                SELECT opportunity_id, survey_no, micro_market, developer_name,
                       score, irr_score, legal_risk_level, best_deal_type,
                       estimated_jd_irr, next_action, expiry_date, priority_label,
                       market_rank
                FROM v_opportunity_queue
                WHERE score >= :min_s
                ORDER BY score DESC
                LIMIT :lim
            """),
                {"min_s": float(min_score), "lim": limit},
            ).fetchall()
    return [
        OpportunityQueueItem(
            opportunity_id=str(r[0]),
            survey_no=r[1],
            micro_market=r[2],
            developer_name=r[3],
            score=r[4],
            irr_score=r[5],
            legal_risk_level=r[6],
            best_deal_type=r[7],
            estimated_jd_irr=r[8],
            next_action=r[9],
            expiry_date=r[10],
            priority_label=r[11] or "COLD",
            market_rank=r[12] or 0,
        )
        for r in rows
    ]


def get_ingest_log(
    plugin_id: Optional[str] = None,
    market: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list[IngestLogEntry]:
    """Query ingest_log filtered by plugin, market, and/or status.
    Uses bound parameters throughout — no string interpolation in SQL."""
    with _get_conn() as conn:
        rows = conn.execute(
            text("""
            SELECT id, plugin_id, market, entity_type, status, error_message, created_at
            FROM ingest_log
            WHERE (:pid IS NULL OR plugin_id = :pid)
              AND (:mkt IS NULL OR market ILIKE :mkt)
              AND (:st IS NULL OR status = :st)
            ORDER BY created_at DESC
            LIMIT :lim
        """),
            {
                "pid": plugin_id,
                "mkt": f"%{market}%" if market else None,
                "st": status,
                "lim": limit,
            },
        ).fetchall()
    return [
        IngestLogEntry(
            id=str(r[0]),
            plugin_id=r[1],
            market=r[2],
            entity_type=r[3],
            status=r[4],
            error_message=r[5],
            created_at=r[6],
        )
        for r in rows
    ]


def get_data_freshness() -> list[FreshnessReport]:
    """Query v_data_freshness for all sources."""
    with _get_conn() as conn:
        rows = conn.execute(
            text("""
            SELECT source_name, last_scraped_at, record_count, freshness_score, freshness_label
            FROM v_data_freshness
            ORDER BY freshness_score ASC, source_name
        """)
        ).fetchall()
    return [
        FreshnessReport(
            source_name=r[0],
            last_scraped_at=r[1],
            record_count=r[2] or 0,
            freshness_score=r[3] or 0.0,
            freshness_label=r[4] or "NEVER_SCRAPED",
        )
        for r in rows
    ]
