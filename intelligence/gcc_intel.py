"""
RE_OS — GCC Demand Scout Intelligence Module (Sprint 67 — GATE-71)

GCCIntel.get_gcc_score(market) returns a GCCIntelResult with a gcc_north_norm
value [0,1] that feeds demand_score_v2 as its 5th component (weight 0.15).

The score captures the rolling 12-month GCC pipeline pressure on North Bengaluru
corridors — a forward-looking signal invisible in listing, absorption, and
registration data. Rising gcc_north_norm + flat absorption = demand accumulating
before the market has noticed.

Architecture:
    gcc_events table → GCCIntel.get_gcc_score() → DemandSignals.gcc_north_norm
    → demand_score_v2 (5-component, Sprint 67)

Corridor → market slug mapping:
    Each micro-market has one primary employment corridor. The corridor's
    north_bengaluru_impact_score (0–1) is baked into each gcc_event row at
    ingestion time by GCCPlugin. GCCIntel reads those stored scores rather
    than recomputing them, so the mapping logic lives in one place (gcc_plugin.py).

Negative signal suppressor:
    If negative GCC demand in a corridor (CONSOLIDATION events) exceeds 30% of
    positive demand in the same 12-month window, gcc_north_norm is halved.
    This prevents a market from looking bullish when a large employer is leaving.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from intelligence._shared import (
    MarketCache,
    sanitize_market,
    timed_intel_query,
    validate_market,
)

__all__ = ["GCCIntel", "GCCIntelResult", "GCCEvent"]

_CACHE_NS = "gcc_intel"

# Corridor names that are primary for North Bengaluru markets.
# Used to restrict which events count toward a given market's gcc_north_norm.
_NORTH_BENGALURU_CORRIDORS = frozenset(
    {
        "kiadb_aerospace_park",
        "devanahalli_nh44",
        "manyata_tech_park",
        "yelahanka_jakkur",
        "hebbal_orn_north",
        "nagawara_hm_tech",
        "thanisandra_strr",
    }
)

# Market slug → primary corridor. Determines which corridor's GCC events
# feed the market's gcc_north_norm.
_MARKET_TO_CORRIDOR: dict[str, str] = {
    "yelahanka": "yelahanka_jakkur",
    "devanahalli": "devanahalli_nh44",
    "hebbal": "hebbal_orn_north",
}

# Normalisation ceiling: gcc_signal_score × north_bengaluru_impact_score of
# 10.0 = maximum possible corridor pressure. Divide by this to get [0, 1].
_GCC_SCORE_CEILING = 10.0

# Negative suppressor threshold: if negative demand > this fraction of positive,
# halve gcc_north_norm.
_NEGATIVE_SUPPRESSOR_THRESHOLD = 0.30


@dataclass
class GCCEvent:
    """Single GCC announcement record from the gcc_events table."""

    id: str
    canonical_id: str
    company: str
    sector: str | None
    country_of_origin: str | None
    bengaluru_location: str | None
    nearest_corridor: str | None
    entrant_type: str | None
    work_model: str | None
    signal_maturity_level: int | None
    is_negative_signal: bool
    north_bengaluru_impact_score: float | None
    investment_cr: float | None
    planned_headcount: int | None
    headcount_timeline_months: int | None
    median_ctc_l: float | None
    office_sqft: int | None
    demand_creation_score: int | None
    residential_impact_score: int | None
    appreciation_impact_score: int | None
    rental_impact_score: int | None
    gcc_signal_score: float | None
    primary_housing_segment: str | None
    time_horizon: str | None
    estimated_demand_units: int | None
    source_name: str | None
    source_reliability: str | None
    announced_at: Any | None
    discord_alert_fired: bool
    created_at: Any | None


@dataclass
class GCCIntelResult:
    """Composite GCC demand signal for a single micro-market.

    gcc_north_norm [0.0, 1.0] is the value consumed by DemandIntel to produce
    demand_score_v2. All other fields are informational context for the dashboard
    and weekly digest.
    """

    market: str
    collected_at: str
    corridor: str | None = None

    gcc_north_norm: float = 0.0  # the component that feeds demand_score_v2
    event_count_12m: int = 0
    event_count_90d: int = 0
    total_headcount_12m: int = 0
    avg_gcc_signal_score: float = 0.0
    top_sectors: list[str] = field(default_factory=list)
    dominant_housing_segment: str | None = None
    has_level1_signal: bool = False
    negative_suppressor_applied: bool = False
    signals: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        sup = " [NEG SUPPRESSOR]" if self.negative_suppressor_applied else ""
        return (
            f"[GCCIntel:{self.market}] norm={self.gcc_north_norm:.3f}{sup} | "
            f"events_12m={self.event_count_12m} | "
            f"headcount={self.total_headcount_12m:,} | "
            f"sectors={self.top_sectors[:3]}"
        )


class GCCIntel:
    """Forward-looking GCC demand signal layer for DemandIntel.

    Primary consumer: DemandIntel._load_gcc_signal() which calls
    get_gcc_score(market) and writes result.gcc_north_norm into DemandSignals.

    Secondary consumers:
        - /api/gcc/events (dashboard list view)
        - /api/gcc/north-score (per-market score endpoint)
        - Discord alert job (scheduler)
        - Weekly digest job (scheduler)

    Risk Register:
    | Risk | Impact | Mitigation |
    |------|--------|------------|
    | gcc_events table missing (pre-migration) | gcc_north_norm stays 0.0 | try/except around all DB ops; graceful degrade |
    | No gcc_events for a corridor | gcc_north_norm = 0.0 | Silent; demand_score_v2 uses remaining 4 components renormalised |
    | CONSOLIDATION events dominate | Artificially high positive score | Negative suppressor halves norm when negatives > 30% of positives |
    | Cache stale during alert window | Alert fires on old data | alert path bypasses cache (force_refresh=True) |
    """

    def __init__(self, caller: str = ""):
        self._cache = MarketCache()
        self._caller = caller or "GCCIntel"

    def get_gcc_score(self, market: str, force_refresh: bool = False) -> GCCIntelResult:
        """Return GCC demand signal for *market*.

        Never raises. Returns result with gcc_north_norm=0.0 on any failure.
        """
        m = sanitize_market(market)
        if not m:
            return GCCIntelResult(
                market=market or "",
                collected_at=datetime.now(timezone.utc).isoformat(),
            )

        if not force_refresh:
            cached = self._cache.get(_CACHE_NS, m)
            if cached is not None:
                return cached

        corridor = _MARKET_TO_CORRIDOR.get(m.lower())
        result = GCCIntelResult(
            market=m,
            collected_at=datetime.now(timezone.utc).isoformat(),
            corridor=corridor,
        )

        if not corridor:
            logger.debug("[{}] no corridor mapping for {}", self._caller, m)
            self._cache.set(_CACHE_NS, m, result, is_positive=False)
            return result

        try:
            from utils.db import get_engine
            from sqlalchemy import text

            with get_engine(pool_size=2, max_overflow=1).connect() as conn:
                self._load_positive_score(conn, result, corridor)
                self._load_negative_score(conn, result, corridor)
                self._load_event_stats(conn, result, corridor)
                self._apply_negative_suppressor(result)
                self._build_signals(result)
        except Exception as exc:
            logger.warning("[{}] get_gcc_score({}) failed: {}", self._caller, m, exc)

        self._cache.set(_CACHE_NS, m, result, is_positive=result.event_count_12m > 0)
        return result

    def get_events(
        self,
        market: str | None = None,
        corridors: list[str] | None = None,
        maturity_levels: list[int] | None = None,
        include_negative: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GCCEvent]:
        """Fetch gcc_events with optional filters. Used by /api/gcc/events."""
        try:
            from utils.db import get_engine
            from sqlalchemy import text

            corridor = None
            if market:
                m = sanitize_market(market)
                corridor = _MARKET_TO_CORRIDOR.get((m or "").lower())

            conditions = ["TRUE"]
            params: dict = {"limit": limit, "offset": offset}

            if corridor and not corridors:
                conditions.append("nearest_corridor = :corridor")
                params["corridor"] = corridor
            elif corridors:
                placeholders = ", ".join(f":c{i}" for i, _ in enumerate(corridors))
                conditions.append(f"nearest_corridor IN ({placeholders})")
                for i, c in enumerate(corridors):
                    params[f"c{i}"] = c

            if maturity_levels:
                placeholders = ", ".join(
                    f":ml{i}" for i, _ in enumerate(maturity_levels)
                )
                conditions.append(f"signal_maturity_level IN ({placeholders})")
                for i, lvl in enumerate(maturity_levels):
                    params[f"ml{i}"] = lvl

            if not include_negative:
                conditions.append("is_negative_signal = FALSE")

            where = " AND ".join(conditions)
            sql = text(f"""
                SELECT
                    id::text, canonical_id, company, sector, country_of_origin,
                    bengaluru_location, nearest_corridor, entrant_type, work_model,
                    signal_maturity_level, is_negative_signal,
                    north_bengaluru_impact_score::float,
                    investment_cr::float, planned_headcount,
                    headcount_timeline_months, median_ctc_l::float,
                    office_sqft, demand_creation_score, residential_impact_score,
                    appreciation_impact_score, rental_impact_score,
                    gcc_signal_score::float, primary_housing_segment,
                    time_horizon, estimated_demand_units,
                    source_name, source_reliability, announced_at,
                    discord_alert_fired, created_at
                FROM gcc_events
                WHERE {where}
                ORDER BY announced_at DESC NULLS LAST, created_at DESC
                LIMIT :limit OFFSET :offset
            """)

            with get_engine(pool_size=2, max_overflow=1).connect() as conn:
                rows = conn.execute(sql, params).fetchall()

            return [
                GCCEvent(
                    id=r[0],
                    canonical_id=r[1],
                    company=r[2],
                    sector=r[3],
                    country_of_origin=r[4],
                    bengaluru_location=r[5],
                    nearest_corridor=r[6],
                    entrant_type=r[7],
                    work_model=r[8],
                    signal_maturity_level=r[9],
                    is_negative_signal=bool(r[10]),
                    north_bengaluru_impact_score=r[11],
                    investment_cr=r[12],
                    planned_headcount=r[13],
                    headcount_timeline_months=r[14],
                    median_ctc_l=r[15],
                    office_sqft=r[16],
                    demand_creation_score=r[17],
                    residential_impact_score=r[18],
                    appreciation_impact_score=r[19],
                    rental_impact_score=r[20],
                    gcc_signal_score=r[21],
                    primary_housing_segment=r[22],
                    time_horizon=r[23],
                    estimated_demand_units=r[24],
                    source_name=r[25],
                    source_reliability=r[26],
                    announced_at=r[27],
                    discord_alert_fired=bool(r[28]),
                    created_at=r[29],
                )
                for r in rows
            ]
        except Exception as exc:
            logger.warning("[{}] get_events failed: {}", self._caller, exc)
            return []

    def get_pending_alerts(self) -> list[GCCEvent]:
        """Return events that qualify for Discord alert but haven't fired yet."""
        try:
            from utils.db import get_engine
            from sqlalchemy import text

            with get_engine(pool_size=2, max_overflow=1).connect() as conn:
                rows = conn.execute(
                    text("""
                    SELECT
                        id::text, canonical_id, company, sector, country_of_origin,
                        bengaluru_location, nearest_corridor, entrant_type, work_model,
                        signal_maturity_level, is_negative_signal,
                        north_bengaluru_impact_score::float,
                        investment_cr::float, planned_headcount,
                        headcount_timeline_months, median_ctc_l::float,
                        office_sqft, demand_creation_score, residential_impact_score,
                        appreciation_impact_score, rental_impact_score,
                        gcc_signal_score::float, primary_housing_segment,
                        time_horizon, estimated_demand_units,
                        source_name, source_reliability, announced_at,
                        discord_alert_fired, created_at
                    FROM gcc_events
                    WHERE discord_alert_fired = FALSE
                      AND is_negative_signal = FALSE
                      AND gcc_signal_score >= 7.0
                      AND north_bengaluru_impact_score >= 0.70
                      AND signal_maturity_level <= 2
                    ORDER BY gcc_signal_score DESC
                """)
                ).fetchall()
            return [
                GCCEvent(
                    id=r[0],
                    canonical_id=r[1],
                    company=r[2],
                    sector=r[3],
                    country_of_origin=r[4],
                    bengaluru_location=r[5],
                    nearest_corridor=r[6],
                    entrant_type=r[7],
                    work_model=r[8],
                    signal_maturity_level=r[9],
                    is_negative_signal=bool(r[10]),
                    north_bengaluru_impact_score=r[11],
                    investment_cr=r[12],
                    planned_headcount=r[13],
                    headcount_timeline_months=r[14],
                    median_ctc_l=r[15],
                    office_sqft=r[16],
                    demand_creation_score=r[17],
                    residential_impact_score=r[18],
                    appreciation_impact_score=r[19],
                    rental_impact_score=r[20],
                    gcc_signal_score=r[21],
                    primary_housing_segment=r[22],
                    time_horizon=r[23],
                    estimated_demand_units=r[24],
                    source_name=r[25],
                    source_reliability=r[26],
                    announced_at=r[27],
                    discord_alert_fired=bool(r[28]),
                    created_at=r[29],
                )
                for r in rows
            ]
        except Exception as exc:
            logger.warning("[{}] get_pending_alerts failed: {}", self._caller, exc)
            return []

    def mark_alert_fired(self, canonical_id: str) -> bool:
        """Mark a gcc_event as having had its Discord alert sent."""
        try:
            from utils.db import get_engine
            from sqlalchemy import text

            with get_engine(pool_size=2, max_overflow=1).connect() as conn:
                result = conn.execute(
                    text("""
                    UPDATE gcc_events
                    SET discord_alert_fired = TRUE,
                        updated_at = NOW()
                    WHERE canonical_id = :cid
                """),
                    {"cid": canonical_id},
                )
                conn.commit()
                return (result.rowcount or 0) > 0
        except Exception as exc:
            logger.warning("[{}] mark_alert_fired failed: {}", self._caller, exc)
            return False

    def invalidate_cache(self, market: str | None = None):
        self._cache.invalidate(_CACHE_NS, sanitize_market(market) if market else None)

    # ── Private DB loaders ────────────────────────────────────────────────────

    def _load_positive_score(self, conn, result: GCCIntelResult, corridor: str):
        from sqlalchemy import text

        with timed_intel_query("gcc_positive_score"):
            row = conn.execute(
                text("""
                SELECT
                    COALESCE(
                        AVG(gcc_signal_score * north_bengaluru_impact_score),
                        0.0
                    ) AS raw_score,
                    COUNT(*) AS event_count
                FROM gcc_events
                WHERE nearest_corridor = :corridor
                  AND signal_maturity_level IN (1, 2, 3)
                  AND is_negative_signal = FALSE
                  AND announced_at >= CURRENT_DATE - INTERVAL '12 months'
                  AND gcc_signal_score IS NOT NULL
                  AND north_bengaluru_impact_score IS NOT NULL
            """),
                {"corridor": corridor},
            ).fetchone()

        if row and row[0]:
            raw = float(row[0])
            result.gcc_north_norm = round(
                max(0.0, min(raw / _GCC_SCORE_CEILING, 1.0)), 4
            )
            result.event_count_12m = int(row[1]) if row[1] else 0

    def _load_negative_score(self, conn, result: GCCIntelResult, corridor: str):
        """Store raw negative demand total for suppressor calculation."""
        from sqlalchemy import text

        with timed_intel_query("gcc_negative_score"):
            row = conn.execute(
                text("""
                SELECT
                    COALESCE(
                        ABS(AVG(gcc_signal_score * north_bengaluru_impact_score)),
                        0.0
                    ) AS neg_raw
                FROM gcc_events
                WHERE nearest_corridor = :corridor
                  AND is_negative_signal = TRUE
                  AND announced_at >= CURRENT_DATE - INTERVAL '12 months'
                  AND gcc_signal_score IS NOT NULL
                  AND north_bengaluru_impact_score IS NOT NULL
            """),
                {"corridor": corridor},
            ).fetchone()
        # Store on result for _apply_negative_suppressor
        result._neg_raw = float(row[0]) if row and row[0] else 0.0  # type: ignore[attr-defined]

    def _load_event_stats(self, conn, result: GCCIntelResult, corridor: str):
        from sqlalchemy import text

        with timed_intel_query("gcc_event_stats"):
            row = conn.execute(
                text("""
                SELECT
                    COALESCE(SUM(planned_headcount), 0) AS total_headcount,
                    COALESCE(AVG(gcc_signal_score), 0.0) AS avg_score,
                    BOOL_OR(signal_maturity_level = 1) AS has_level1,
                    COUNT(*) FILTER (
                        WHERE announced_at >= CURRENT_DATE - INTERVAL '90 days'
                    ) AS count_90d
                FROM gcc_events
                WHERE nearest_corridor = :corridor
                  AND is_negative_signal = FALSE
                  AND announced_at >= CURRENT_DATE - INTERVAL '12 months'
            """),
                {"corridor": corridor},
            ).fetchone()

        if row:
            result.total_headcount_12m = int(row[0]) if row[0] else 0
            result.avg_gcc_signal_score = round(float(row[1] or 0.0), 2)
            result.has_level1_signal = bool(row[2])
            result.event_count_90d = int(row[3]) if row[3] else 0

        with timed_intel_query("gcc_top_sectors"):
            sector_rows = conn.execute(
                text("""
                SELECT sector, COUNT(*) AS cnt
                FROM gcc_events
                WHERE nearest_corridor = :corridor
                  AND is_negative_signal = FALSE
                  AND sector IS NOT NULL
                  AND announced_at >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY sector
                ORDER BY cnt DESC
                LIMIT 5
            """),
                {"corridor": corridor},
            ).fetchall()
        result.top_sectors = [str(r[0]) for r in sector_rows if r[0]]

        with timed_intel_query("gcc_housing_segment"):
            seg_row = conn.execute(
                text("""
                SELECT primary_housing_segment
                FROM gcc_events
                WHERE nearest_corridor = :corridor
                  AND is_negative_signal = FALSE
                  AND primary_housing_segment IS NOT NULL
                  AND announced_at >= CURRENT_DATE - INTERVAL '12 months'
                GROUP BY primary_housing_segment
                ORDER BY COUNT(*) DESC
                LIMIT 1
            """),
                {"corridor": corridor},
            ).fetchone()
        result.dominant_housing_segment = str(seg_row[0]) if seg_row else None

    def _apply_negative_suppressor(self, result: GCCIntelResult):
        neg_raw = getattr(result, "_neg_raw", 0.0)
        positive_raw = result.gcc_north_norm * _GCC_SCORE_CEILING
        if positive_raw > 0 and neg_raw / positive_raw > _NEGATIVE_SUPPRESSOR_THRESHOLD:
            result.gcc_north_norm = round(result.gcc_north_norm * 0.5, 4)
            result.negative_suppressor_applied = True
        # Clean up temporary attribute
        try:
            del result._neg_raw  # type: ignore[attr-defined]
        except AttributeError:
            pass

    def _build_signals(self, result: GCCIntelResult):
        if result.gcc_north_norm >= 0.7:
            result.signals.append(
                f"GCC pipeline STRONG: norm={result.gcc_north_norm:.2f} — "
                f"{result.event_count_12m} events, "
                f"{result.total_headcount_12m:,} planned hires in 12m"
            )
        elif result.gcc_north_norm >= 0.4:
            result.signals.append(
                f"GCC pipeline BUILDING: norm={result.gcc_north_norm:.2f} — "
                f"{result.event_count_12m} events tracked"
            )
        elif result.event_count_12m > 0:
            result.signals.append(
                f"GCC pipeline EARLY: norm={result.gcc_north_norm:.2f} — "
                f"{result.event_count_12m} events, low signal density"
            )

        if result.has_level1_signal:
            result.signals.append(
                "Level-1 signal present — pre-public GCC activity in corridor"
            )

        if result.negative_suppressor_applied:
            result.signals.append(
                "Negative suppressor applied — departures offset arrivals ≥30%"
            )

        if result.dominant_housing_segment:
            result.signals.append(
                f"Primary demand segment: {result.dominant_housing_segment}"
            )


if __name__ == "__main__":
    import json

    for mkt in ("Yelahanka", "Devanahalli", "Hebbal"):
        r = GCCIntel(caller="self_test").get_gcc_score(mkt)
        print(
            json.dumps(
                {
                    "market": r.market,
                    "corridor": r.corridor,
                    "gcc_north_norm": r.gcc_north_norm,
                    "event_count_12m": r.event_count_12m,
                    "total_headcount_12m": r.total_headcount_12m,
                    "has_level1": r.has_level1_signal,
                    "signals": r.signals,
                },
                indent=2,
                default=str,
            )
        )
