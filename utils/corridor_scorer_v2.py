"""
RE_OS — Corridor Scorer v2 (Sprint 100 — T-1191)

Extends CorridorScorer v1 with PostGIS spatial joins for corridor village
membership. Overrides `_get_corridor_villages()` to query `registered_transactions`
lat/lng against `corridor_boundaries` polygons via ST_Within, falling back to
the v1 static village list on PostGIS error.

Adds `as_geojson` parameter to `score_all()` so each CorridorScore includes
the corridor's boundary polygon as a GeoJSON Feature.
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Any

from loguru import logger
from prometheus_client import Counter, Histogram

from utils.corridor_scorer import CORRIDOR_DEFINITIONS, CorridorScore, CorridorScorer

__all__ = [
    "CorridorScorerV2",
    "CorridorScoreV2",
]

# ── Prometheus Metrics ───────────────────────────────────────────────────────

_corridor_scoring_total = Counter(
    "corridor_scoring_total",
    "Total corridor scoring operations (v2)",
    ["corridor_id", "mode"],
)
_corridor_scoring_duration = Histogram(
    "corridor_scoring_duration_seconds",
    "Corridor scoring duration in seconds",
    ["corridor_id"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
_corridor_village_source = Counter(
    "corridor_village_source_total",
    "Village resolution source: v2_spatial, v2_fallback_no_results, v1_fallback_error",
    ["corridor_id", "source"],
)
_corridor_boundary_cache_hits = Counter(
    "corridor_boundary_cache_hits_total",
    "GeoJSON boundary cache hits",
    ["corridor_id"],
)
_corridor_boundary_cache_misses = Counter(
    "corridor_boundary_cache_misses_total",
    "GeoJSON boundary cache misses",
    ["corridor_id"],
)

# ── Cache Configuration ──────────────────────────────────────────────────────

_BOUNDARY_CACHE_TTL_SECONDS = 300
_boundary_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


class CorridorScoreV2(CorridorScore):
    """CorridorScore with optional boundary_geojson field (lightweight DTO)."""

    __slots__ = ("boundary_geojson",)

    def __init__(
        self,
        corridor_id: str,
        corridor_name: str,
        velocity_score: float,
        psf_trend_score: float,
        gcc_score: float,
        infra_score: float,
        n_transactions: int,
        avg_psf: float | None,
        psf_mom: float | None,
        data_window: str,
        notes: list[str],
        boundary_geojson: dict[str, Any] | None = None,
    ):
        super().__init__(
            corridor_id=corridor_id,
            corridor_name=corridor_name,
            velocity_score=velocity_score,
            psf_trend_score=psf_trend_score,
            gcc_score=gcc_score,
            infra_score=infra_score,
            n_transactions=n_transactions,
            avg_psf=avg_psf,
            psf_mom=psf_mom,
            data_window=data_window,
            notes=notes,
        )
        self.boundary_geojson = boundary_geojson

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["boundary_geojson"] = self.boundary_geojson
        return d


class CorridorScorerV2(CorridorScorer):
    """V2 scorer using PostGIS spatial join for corridor village membership.

    Falls back to v1 static village list if PostGIS query fails
    (e.g., registered_transactions has no lat/lng columns yet).

    Thread-safe for concurrent scoring requests. Cache is process-local
    with TTL (5 min default).
    """

    def __init__(self, engine=None):
        super().__init__(engine=engine)

    # ── Public API ────────────────────────────────────────────────────────────

    def score_all(
        self,
        window_months: int = 3,
        as_of: date | None = None,
        as_geojson: bool = False,
    ) -> list[CorridorScoreV2]:
        """Score all corridors with optional GeoJSON boundary.

        Args:
            window_months: Lookback window in months.
            as_of: Date to score as-of (default today).
            as_geojson: If True, include boundary_geojson in each score.

        Returns list sorted by composite score descending.
        """
        if as_of is None:
            as_of = date.today()
        window_start = as_of - timedelta(days=window_months * 30)
        window_label = f"{window_start.isoformat()} => {as_of.isoformat()}"

        boundary_cache: dict[str, dict[str, Any] | None] = {}
        if as_geojson:
            boundary_cache = self._load_boundary_geojsons()

        scores: list[CorridorScoreV2] = []
        for corridor in CORRIDOR_DEFINITIONS:
            with _corridor_scoring_duration.labels(corridor_id=corridor["id"]).time():
                score = self._score_corridor_v2(
                    corridor, window_start, as_of, window_label, boundary_cache,
                )
                scores.append(score)

        scores.sort(key=lambda s: s.composite, reverse=True)
        _corridor_scoring_total.labels(corridor_id="all", mode="score_all").inc()

        if scores:
            logger.info(
                "[CorridorScorerV2] Scored {} corridors — top: {} (composite {:.2f})",
                len(scores), scores[0].corridor_name, scores[0].composite,
            )
        return scores

    def backtest(
        self,
        train_start: date | None = None,
        train_end: date | None = None,
        test_start: date | None = None,
        test_end: date | None = None,
        output_path: str | Any | None = None,
    ) -> dict[str, Any]:
        """Run backtest using v1 village lists (backward-compatible).

        V2 spatial join is not needed for backtest — the v1 village list
        membership is sufficient. Delegates to v1 CorridorScorer.backtest().
        """
        logger.info("[CorridorScorerV2] Delegating backtest to v1 CorridorScorer")
        return super().backtest(
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            output_path=output_path,
        )

    # ── Private: V2 helpers ───────────────────────────────────────────────────

    def _score_corridor_v2(
        self,
        corridor: dict[str, Any],
        start: date,
        end: date,
        window_label: str,
        boundary_cache: dict[str, dict[str, Any] | None],
    ) -> CorridorScoreV2:
        notes: list[str] = []
        gcc_hubs = corridor["gcc_hubs"]
        infra_kws = corridor["infra_keywords"]

        villages = self._get_corridor_villages(corridor["id"], notes)

        velocity_score, n_tx = self._score_velocity(villages, start, end, notes)
        psf_trend_score, avg_psf, psf_mom = self._score_psf_trend(
            villages, start, end, notes,
        )
        gcc_score = self._score_gcc(gcc_hubs, notes)
        infra_score = self._score_infra(infra_kws, notes)

        boundary_geojson = boundary_cache.get(corridor["id"])

        return CorridorScoreV2(
            corridor_id=corridor["id"],
            corridor_name=corridor["name"],
            velocity_score=velocity_score,
            psf_trend_score=psf_trend_score,
            gcc_score=gcc_score,
            infra_score=infra_score,
            n_transactions=n_tx,
            avg_psf=avg_psf,
            psf_mom=psf_mom,
            data_window=window_label,
            notes=notes,
            boundary_geojson=boundary_geojson,
        )

    def _get_corridor_villages(
        self,
        corridor_id: str,
        notes: list[str],
    ) -> list[str]:
        """Get villages for a corridor via PostGIS spatial join.

        Returns villages from registered_transactions whose lat/lng falls
        inside the corridor's polygon boundary. Falls back to v1 static
        list if PostGIS query fails or returns no results.

        Implements one retry on transient DB errors before falling back.
        """
        try:
            villages = self._query_spatial_villages(corridor_id, notes)
            if villages:
                _corridor_village_source.labels(
                    corridor_id=corridor_id, source="v2_spatial"
                ).inc()
                return villages

            fallback = self._get_v1_villages(corridor_id)
            notes.append(
                f"v2-spatial: no villages found via ST_Within for '{corridor_id}' "
                f"— falling back to v1 static list ({len(fallback)} villages)"
            )
            _corridor_village_source.labels(
                corridor_id=corridor_id, source="v2_fallback_no_results"
            ).inc()
            return fallback

        except Exception as exc:
            logger.warning(
                "[CorridorScorerV2] Spatial query failed for corridor "
                "'{}': {} — falling back to v1 with 1 retry", corridor_id, exc,
            )
            try:
                logger.info(
                    "[CorridorScorerV2] Retry 1/1 for corridor '{}'", corridor_id
                )
                villages = self._query_spatial_villages(corridor_id, notes)
                if villages:
                    _corridor_village_source.labels(
                        corridor_id=corridor_id, source="v2_spatial_retry"
                    ).inc()
                    return villages
            except Exception as retry_exc:
                logger.warning(
                    "[CorridorScorerV2] Retry also failed for '{}': {}",
                    corridor_id, retry_exc,
                )

            notes.append(
                f"v2-spatial: PostGIS query failed after retry ({exc}) — "
                f"falling back to v1 static village list"
            )
            _corridor_village_source.labels(
                corridor_id=corridor_id, source="v1_fallback_error"
            ).inc()
            return self._get_v1_villages(corridor_id)

    def _query_spatial_villages(
        self,
        corridor_id: str,
        notes: list[str],
    ) -> list[str]:
        """Execute ST_Within spatial join query.

        Raises on DB error; returns empty list on no matches.
        Returns empty list immediately if corridor_id is empty.
        """
        if not corridor_id or not corridor_id.strip():
            notes.append("v2-spatial: empty corridor_id — returning no villages")
            return []

        engine = self._get_engine()
        from sqlalchemy import text

        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT DISTINCT r.village
                    FROM registered_transactions r
                    JOIN corridor_boundaries cb
                      ON ST_Within(
                           ST_SetSRID(ST_MakePoint(r.longitude, r.latitude), 4326),
                           cb.geom
                         )
                    WHERE cb.corridor_id = :cid
                      AND r.village IS NOT NULL
                      AND r.village != ''
                      AND r.longitude IS NOT NULL
                      AND r.latitude IS NOT NULL
                """),
                {"cid": corridor_id},
            ).fetchall()

        villages = [str(r[0]) for r in rows if r[0]]
        if villages:
            notes.append(
                f"v2-spatial: {len(villages)} villages resolved via PostGIS "
                f"for corridor '{corridor_id}'"
            )
        return villages

    def _get_v1_villages(self, corridor_id: str) -> list[str]:
        """Return v1 static village list for a corridor ID."""
        for c in CORRIDOR_DEFINITIONS:
            if c["id"] == corridor_id:
                return list(c.get("villages", []))
        return []

    def _load_boundary_geojsons(self) -> dict[str, dict[str, Any] | None]:
        """Load all corridor boundary polygons as GeoJSON Features with TTL cache.

        Cache TTL is configured via _BOUNDARY_CACHE_TTL_SECONDS (default 300s).
        Thread-safe for concurrent readers.
        """
        now = time.time()
        cached = _boundary_cache.get("all")
        if cached is not None and now < cached[0]:
            for c in CORRIDOR_DEFINITIONS:
                cid = c["id"]
                if cid in cached[1] if isinstance(cached[1], dict) else False:
                    _corridor_boundary_cache_hits.labels(corridor_id=cid).inc()
            return cached[1] if isinstance(cached[1], dict) else {}

        result: dict[str, dict[str, Any] | None] = {}
        try:
            engine = self._get_engine()
            from sqlalchemy import text

            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT corridor_id, ST_AsGeoJSON(geom) AS geojson
                        FROM corridor_boundaries
                        WHERE geom IS NOT NULL
                    """)
                ).fetchall()

            for row in rows:
                cid = str(row[0])
                geojson_str = row[1]
                if geojson_str:
                    try:
                        geom_dict = json.loads(geojson_str)
                        result[cid] = {
                            "type": "Feature",
                            "geometry": geom_dict,
                            "properties": {"corridor_id": cid},
                        }
                    except (json.JSONDecodeError, TypeError):
                        result[cid] = None
                else:
                    result[cid] = None

            _boundary_cache["all"] = (now + _BOUNDARY_CACHE_TTL_SECONDS, result)

            for cid in result:
                _corridor_boundary_cache_misses.labels(corridor_id=cid).inc()

            return result

        except Exception as exc:
            logger.warning(
                "[CorridorScorerV2] Failed to load boundary geojsons: {}", exc
            )
            return {}

    @classmethod
    def invalidate_boundary_cache(cls) -> None:
        """Clear the GeoJSON boundary cache. Call after corridor_boundaries mutation."""
        _boundary_cache.clear()
        logger.info("[CorridorScorerV2] Boundary cache invalidated")
