"""
RE_OS — InfrastructureScorer (Tier 1 — Geospatial Foundation)
Uses OSMnx + Pandana to compute infrastructure distances and walkability
for a given (lat, lng) in a market. Every number is computable from open data, not estimated.

Graceful degradation chain:
  1. OSM road network cached → road distances + Pandana walkability
  2. OSM network absent → haversine (great-circle) distances, no walkability
  3. OSMnx import fails → haversine only
"""
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
import os

from loguru import logger

from utils.geo_config import get_metro_coords, NH44_POINT, BIAL_COORDS, CBD_COORDS

_OSM_DATA_DIR = Path(os.environ.get("OSM_DATA_DIR", "/data/osm_networks"))


@dataclass
class InfrastructureScore:
    lat: float
    lng: float
    market: str
    dist_to_nearest_metro_m: float | None = None
    dist_to_nh44_m: float | None = None
    dist_to_bial_km: float | None = None
    dist_to_cbd_km: float | None = None
    walkability_score: float | None = None
    poi_count_15min: int | None = None
    road_distances_available: bool = False
    errors: list[str] = field(default_factory=list)


# ── Haversine (great-circle) distance — always available ───────────────────────

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    c = 2 * asin(sqrt(a))
    return 6371.0 * c


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return _haversine_km(lat1, lng1, lat2, lng2) * 1000.0


# ── OSMnx graph helpers (lazy — import at call site) ─────────────────────────

def _load_graph(market: str):
    """Load cached OSMnx graph for a market. Returns None on failure."""
    try:
        import osmnx as ox
    except ImportError:
        logger.warning("[InfraScore] osmnx not installed")
        return None
    slug = market.lower().replace(" ", "_").replace("-", "_")
    graphml_path = _OSM_DATA_DIR / f"{slug}.graphml"
    if not graphml_path.exists():
        logger.warning("[InfraScore] No cached graph for {} at {}", market, graphml_path)
        return None
    try:
        G = ox.load_graphml(str(graphml_path))
        logger.debug("[InfraScore] Loaded graph {}: {} nodes, {} edges",
                      graphml_path, G.number_of_nodes(), G.number_of_edges())
        return G
    except Exception as exc:
        logger.warning("[InfraScore] Failed to load graph for {}: {}", market, exc)
        return None


def _nearest_node(G, lat: float, lng: float):
    """Find nearest OSM node to (lat, lng). Returns node ID or None."""
    try:
        import osmnx as ox
        return ox.distance.nearest_nodes(G, lng, lat)
    except Exception as exc:
        logger.debug("[InfraScore] nearest_nodes failed: {}", exc)
        return None


def _road_distance_m(G, from_node: int, to_lat: float, to_lng: float) -> float | None:
    """Shortest driving distance in metres between from_node and target coords."""
    try:
        import osmnx as ox
        to_node = ox.distance.nearest_nodes(G, to_lng, to_lat)
        if to_node == from_node:
            return 0.0
        length = ox.distance.shortest_path_length(G, from_node, to_node, weight="length")
        return float(length) if length is not None else None
    except Exception as exc:
        logger.debug("[InfraScore] road_distance failed: {}", exc)
        return None


# ── Walkability via Pandana ─────────────────────────────────────────────────

def _compute_walkability(G, node: int, radius_m: float = 1000) -> tuple:
    """Walkability score based on POI count within walking distance.
    Returns (score_0_10, poi_count).
    Uses Pandana Network with OSMnx-derived nodes + edges.
    Falls back gracefully if Pandana unavailable.
    """
    try:
        import osmnx as ox
        import pandas as pd
        import pandana as pdna

        nodes_df, edges_df = ox.graph_to_gdfs(G, nodes=True, edges=True)
        if nodes_df.empty or edges_df.empty:
            return 0.0, 0

        node_ids = nodes_df.index.values

        net = pdna.Network(
            node_x=nodes_df["x"].values,
            node_y=nodes_df["y"].values,
            edge_df=pd.DataFrame({
                "from": edges_df["u"].values,
                "to": edges_df["v"].values,
                "weight": edges_df["length"].values,
            }),
            node_ids=node_ids,
        )
        net.precompute(distance=radius_m)

        poi_count = _count_pois_nearby(G, node, radius_m)
        score = min(10.0, poi_count / 5.0)
        return round(score, 1), poi_count

    except ImportError:
        logger.debug("[InfraScore] Pandana unavailable — walkability approximate")
        return None, None
    except Exception as exc:
        logger.debug("[InfraScore] walkability failed: {}", exc)
        return None, None


def _count_pois_nearby(G, node: int, radius_m: float) -> int:
    """Count OSM amenities (schools, hospitals, transit, shops) within radius_m
    walking distance of node. Uses OSMnx geometries_from_point for POI query."""
    try:
        import osmnx as ox
        import networkx as nx

        node_point = (G.nodes[node]["y"], G.nodes[node]["x"])

        tags = {
            "amenity": ["school", "hospital", "clinic", "pharmacy",
                        "bank", "restaurant", "cafe", "supermarket",
                        "marketplace", "post_office", "police", "library",
                        "place_of_worship", "community_centre", "theatre"],
            "shop": ["supermarket", "convenience", "mall", "department_store"],
            "public_transport": ["station", "stop_position"],
            "railway": ["station", "halt"],
            "leisure": ["park", "playground", "fitness_centre", "sports_centre"],
        }
        pois = ox.geometries_from_point(node_point, tags=tags, dist=radius_m)
        return len(pois)

    except ImportError:
        logger.debug("[InfraScore] osmnx geometries query unavailable")
        return 0
    except Exception as exc:
        logger.debug("[InfraScore] POI count failed: {}", exc)
        return 0


# ── Scorer ──────────────────────────────────────────────────────────────────

class InfrastructureScorer:
    """Score infrastructure proximity and walkability for a (lat, lng) in a market.

    Graceful degradation matrix:
    ┌─────────────────────────┬────────────────────┬──────────────────────────┐
    │ Condition               │ metro/NH44/BIAL/CBD │ walkability              │
    ├─────────────────────────┼────────────────────┼──────────────────────────┤
    │ All deps available      │ OSM road distance  │ Pandana POI count / 5.0  │
    │ OSM graph not cached    │ Haversine (straight │ None (no network data)   │
    │                         │ line)              │                          │
    │ osmnx import fails      │ Haversine          │ None (no geometry query) │
    │ Pandana import fails    │ OSM road (if graph │ None (no network model)  │
    │                         │ cached)            │                          │
    │ All deps fail           │ Haversine          │ None                     │
    └─────────────────────────┴────────────────────┴──────────────────────────┘
    road_distances_available=True indicates OSMnx graph was loaded successfully.
    walkability_score=None when Pandana or OSM graph unavailable (not "0").
    Callers MUST handle None and road_distances_available=False gracefully.

    Usage:
        scorer = InfrastructureScorer()
        result = scorer.score(13.1007, 77.5963, "Yelahanka")
        scorer.write_to_db(result)
    """

    MIN_IGR_RECORDS: int = 5  # match GDVEstimator convention for consistency

    def score(self, lat: float, lng: float, market: str) -> InfrastructureScore:
        """Compute all infrastructure metrics for a point in a market.

        Args:
            lat, lng: WGS84 coordinates of the site.
            market: Market name (Yelahanka/Devanahalli/Hebbal). Case-sensitive.

        Returns:
            InfrastructureScore with haversine baselines, OSM road distances
            if cached graph available, and walkability score if Pandana loaded.
        """
        market_safe = (market or "").strip()
        result = InfrastructureScore(lat=lat, lng=lng, market=market_safe)

        # Haversine baselines — always available, zero-dependency
        metro_coords = get_metro_coords(market_safe)
        if metro_coords:
            mlat, mlng = metro_coords
            result.dist_to_nearest_metro_m = round(_haversine_m(lat, lng, mlat, mlng), 1)

        result.dist_to_nh44_m = round(_haversine_m(lat, lng, *NH44_POINT), 1)
        result.dist_to_bial_km = round(_haversine_km(lat, lng, *BIAL_COORDS), 2)
        result.dist_to_cbd_km = round(_haversine_km(lat, lng, *CBD_COORDS), 2)

        # OSMnx road distances — upgrade haversine to road distance when graph cached
        G = _load_graph(market_safe)
        if G is not None:
            node = _nearest_node(G, lat, lng)
            if node is not None:
                result.road_distances_available = True

                if metro_coords:
                    mlat, mlng = metro_coords
                    rd = _road_distance_m(G, node, mlat, mlng)
                    if rd is not None:
                        result.dist_to_nearest_metro_m = round(rd, 1)

                rd = _road_distance_m(G, node, *NH44_POINT)
                if rd is not None:
                    result.dist_to_nh44_m = round(rd, 1)

                rd = _road_distance_m(G, node, *BIAL_COORDS)
                if rd is not None:
                    result.dist_to_bial_km = round(rd / 1000.0, 2)

                rd = _road_distance_m(G, node, *CBD_COORDS)
                if rd is not None:
                    result.dist_to_cbd_km = round(rd / 1000.0, 2)

            score_val, poi_count = _compute_walkability(G, node if node else 0)
            result.walkability_score = score_val
            result.poi_count_15min = poi_count

        logger.info("[InfraScore] {} ({:.4f}, {:.4f}): metro={}m NH44={}m BIAL={}km CBD={}km walk={}",
                     market_safe, lat, lng,
                     result.dist_to_nearest_metro_m or "N/A",
                     result.dist_to_nh44_m or "N/A",
                     result.dist_to_bial_km or "N/A",
                     result.dist_to_cbd_km or "N/A",
                     result.walkability_score or "N/A")
        return result

    def write_to_db(self, result: InfrastructureScore) -> bool:
        """Write infrastructure score to the infrastructure_pipeline table."""
        try:
            from utils.db import get_engine
            from sqlalchemy import text

            with get_engine().begin() as conn:
                conn.execute(text("""
                    INSERT INTO infrastructure_pipeline
                        (name, infra_type, authority, project_status, description, geom)
                    VALUES
                        (:name, :infra_type, :authority, :project_status, :description,
                         ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
                """), {
                    "name": f"InfraScore_{result.market}_{result.lat:.4f}_{result.lng:.4f}",
                    "infra_type": "accessibility",
                    "authority": "RE_OS",
                    "project_status": "Completed",
                    "description": (
                        f"Infrastructure score for {result.market}: "
                        f"metro={result.dist_to_nearest_metro_m}m, "
                        f"NH44={result.dist_to_nh44_m}m, "
                        f"BIAL={result.dist_to_bial_km}km, "
                        f"CBD={result.dist_to_cbd_km}km, "
                        f"walkability={result.walkability_score}/10, "
                        f"road_distances={result.road_distances_available}"
                    ),
                    "lat": result.lat,
                    "lng": result.lng,
                })
            logger.info("[InfraScore] Wrote to DB: {}", result.market)
            return True
        except Exception as exc:
            logger.warning("[InfraScore] DB write failed for {}: {}", result.market, exc)
            return False


if __name__ == "__main__":
    import json
    scorer = InfrastructureScorer()
    for market in ("Yelahanka", "Devanahalli", "Hebbal"):
        coords = get_metro_coords(market)
        if coords:
            lat, lng = coords
            r = scorer.score(lat, lng, market)
            print(json.dumps(
                {k: v for k, v in r.__dict__.items() if not k.startswith("_")},
                indent=2, default=str,
            ))
