"""
RE_OS — Corridor Scorer v2 (Sprint 100 — T-1191, GATE-116)

Overrides `_get_corridor_villages()` to use PostGIS ST_Buffer spatial queries
around corridor centroid points, replacing the AABB approach (ST_MakeEnvelope).
Centroid seeds are defined in `_CORRIDOR_SEEDS` (1km circular buffer).
Falls back to v1 static village list or corridor_boundaries table.

Adds `as_geojson` parameter to `score_all()` — boundary is computed from
ST_Buffer for seeded corridors, or loaded from corridor_boundaries table.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import text

from config.metrics import _counter, _histogram

from utils.corridor_scorer import CORRIDOR_DEFINITIONS, CorridorScore, CorridorScorer

__all__ = [
    "CorridorScorerV2",
    "CorridorScoreV2",
    "CorridorBoundaryV2",
    "get_corridor_seed",
]

# ── Prometheus Metrics ───────────────────────────────────────────────────────

_corridor_scoring_total = _counter(
    "corridor_scoring_total",
    "Total corridor scoring operations (v2)",
    ["corridor_id", "mode"],
)
_corridor_scoring_duration = _histogram(
    "corridor_scoring_duration_seconds",
    "Corridor scoring duration in seconds",
    ["corridor_id"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
_corridor_village_source = _counter(
    "corridor_village_source_total",
    "Village resolution source: buffer/table/retry/fallback",
    ["corridor_id", "source"],
)
_corridor_boundary_cache_hits = _counter(
    "corridor_boundary_cache_hits_total",
    "GeoJSON boundary cache hits",
    ["corridor_id"],
)
_corridor_boundary_cache_misses = _counter(
    "corridor_boundary_cache_misses_total",
    "GeoJSON boundary cache misses",
    ["corridor_id"],
)

# ── Cache Configuration ──────────────────────────────────────────────────────

_BOUNDARY_CACHE_TTL_SECONDS = 300
_boundary_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

# ── Corridor Centroid Seeds (ST_Buffer, not AABB) ────────────────────────────
# Centroids from OSM data (Gate-109 R3 audit). Replaces AABB bounding boxes
# with circular ST_Buffer polygons. Radius 1km (~0.009° at Bangalore latitude
# 13°N) chosen as the typical catchment: a 10-min walk or 2-min auto-rickshaw
# reach from the corridor centre line. For NH-44's diagonal alignment, this
# eliminates the ~2.8km corner overreach that AABB produced (the AABB rectangle
# around NH-44 extended 2.8km beyond the road at diagonal corners).
#
# Corridor definitions and centroids:
#   nh44 (Bellary Road / NH-44): 13.13, 77.60 — Yelahanka junction,
#         midway along N-Blr corridor
#   hebbal_yelahanka (SH-104):   13.05, 77.57 — Hebbal flyover area,
#         densest GCC employment cluster
#   doddaballapur:                13.22, 77.59 — midpoint on Doddaballapur
#         Road, ~5km N of Yelahanka, distinct from NH-44


@dataclass
class CorridorBoundaryV2:
    corridor_id: str
    centroid_lon: float
    centroid_lat: float
    radius_m: int = 1000


_CORRIDOR_SEEDS: list[CorridorBoundaryV2] = [
    CorridorBoundaryV2("nh44", 13.13, 77.60),
    CorridorBoundaryV2("hebbal_yelahanka", 13.05, 77.57),
    CorridorBoundaryV2("doddaballapur", 13.22, 77.59),
]


def _get_corridor_seed(corridor_id: str) -> CorridorBoundaryV2 | None:
    for s in _CORRIDOR_SEEDS:
        if s.corridor_id == corridor_id:
            return s
    return None


def get_corridor_seed(corridor_id: str) -> CorridorBoundaryV2 | None:
    """Public wrapper — return centroid seed for a corridor ID, or None."""
    return _get_corridor_seed(corridor_id)


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

    def score_all(  # type: ignore[override]
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
                seed = _get_corridor_seed(corridor_id)
                source = "v2_spatial_buffer" if seed is not None else "v2_spatial_table"
                _corridor_village_source.labels(
                    corridor_id=corridor_id, source=source
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
                    seed = _get_corridor_seed(corridor_id)
                    source = "v2_spatial_buffer_retry" if seed is not None else "v2_spatial_table_retry"
                    _corridor_village_source.labels(
                        corridor_id=corridor_id, source=source
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
        """Execute ST_Buffer spatial query around corridor centroid.

        Uses circular buffer (ST_Buffer) around the corridor's centroid point
        instead of AABB bounding boxes (ST_MakeEnvelope). For NH-44's diagonal
        alignment, this eliminates the ~2.8km corner overreach that AABB produced.

        Falls back to corridor_boundaries table join if no centroid seed exists
        for the given corridor_id (backward compat).
        """
        if not corridor_id or not corridor_id.strip():
            notes.append("v2-spatial: empty corridor_id — returning no villages")
            return []

        seed = _get_corridor_seed(corridor_id)

        engine = self._get_engine()

        if seed is not None:
            query = text("""
                SELECT DISTINCT r.village
                FROM registered_transactions r
                WHERE ST_Within(
                      ST_SetSRID(ST_MakePoint(r.longitude, r.latitude), 4326),
                      ST_Buffer(
                          ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                          :radius_m
                      )::geometry
                  )
                  AND r.village IS NOT NULL
                  AND r.village != ''
                  AND r.longitude IS NOT NULL
                  AND r.latitude IS NOT NULL
            """)
            params: dict[str, Any] = {
                "lon": seed.centroid_lon,
                "lat": seed.centroid_lat,
                "radius_m": seed.radius_m,
            }
            source_label = "v2_spatial_buffer"
        else:
            query = text("""
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
            """)
            params = {"cid": corridor_id}
            source_label = "v2_spatial_table"

        with engine.connect() as conn:
            rows = conn.execute(query, params).fetchall()

        villages = [str(r[0]) for r in rows if r[0]]
        if villages:
            notes.append(
                f"v2-spatial: {len(villages)} villages resolved via {source_label} "
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
        """Load corridor boundary polygons as GeoJSON Features with TTL cache.

        For seeded corridors (ST_Buffer centroids), computes the buffer polygon
        dynamically. For non-seeded corridors, falls back to corridor_boundaries
        table (AABB geometry, backward compat).

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

            for cdef in CORRIDOR_DEFINITIONS:
                cid = cdef["id"]
                seed = _get_corridor_seed(cid)
                if seed is not None:
                    with engine.connect() as conn:
                        row = conn.execute(
                            text("""
                                SELECT ST_AsGeoJSON(
                                    ST_Buffer(
                                        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                                        :radius_m
                                    )::geometry
                                )
                            """),
                            {"lon": seed.centroid_lon, "lat": seed.centroid_lat,
                             "radius_m": seed.radius_m},
                        ).fetchone()
                    geojson_str = row[0] if row else None
                    if geojson_str:
                        try:
                            geom_dict = json.loads(geojson_str)
                            result[cid] = {
                                "type": "Feature",
                                "geometry": geom_dict,
                                "properties": {
                                    "corridor_id": cid,
                                    "data_source": "st_buffer",
                                    "centroid_lon": seed.centroid_lon,
                                    "centroid_lat": seed.centroid_lat,
                                    "radius_m": seed.radius_m,
                                },
                            }
                        except (json.JSONDecodeError, TypeError):
                            result[cid] = None
                    else:
                        result[cid] = None
                else:
                    result[cid] = None

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
                if cid in result and result[cid] is not None:
                    continue
                geojson_str = row[1]
                if geojson_str:
                    try:
                        geom_dict = json.loads(geojson_str)
                        result[cid] = {
                            "type": "Feature",
                            "geometry": geom_dict,
                            "properties": {"corridor_id": cid, "data_source": "aabb_table"},
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
