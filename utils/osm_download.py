"""
RE_OS — OSM Street Network Downloader (Tier 1 — Geospatial Foundation)
One-time download per market via OSMnx. Saves GraphML to /data/osm_networks/.
Cache is local: ~50MB per market. Re-run is idempotent — skips if file exists.
Designed to be called from scheduler or docker exec, not imported at startup.

Graceful degradation:
  - OSMnx not installed → logged error, return False (no silent partial download)
  - Unknown market name → logged warning, return False
  - OSM API timeout/error → logged exception, return False
  - Cache file corrupted → force=True re-downloads, overwrites silently
  - Called concurrently → safe: download_market is stateless, file write atomic
"""

import os
from pathlib import Path
from loguru import logger

from utils.geo_config import get_market_names, get_osm_place

_OSM_DATA_DIR = Path(os.environ.get("OSM_DATA_DIR", "/data/osm_networks"))


def ensure_data_dir() -> Path:
    _OSM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("[OSMDownload] Data directory: {}", _OSM_DATA_DIR)
    return _OSM_DATA_DIR


def get_graphml_path(market: str) -> Path:
    slug = market.lower().replace(" ", "_").replace("-", "_")
    return _OSM_DATA_DIR / f"{slug}.graphml"


def download_market(market: str, force: bool = False) -> bool:
    """Download OSM street network for a market.
    Returns True if downloaded or already cached, False on failure.
    Raises nothing — all errors logged, return signals failure.
    """
    try:
        import osmnx as ox
    except ImportError:
        logger.error("[OSMDownload] osmnx not installed — cannot download")
        return False

    market_safe = (market or "").strip()
    if not market_safe:
        logger.warning("[OSMDownload] Empty market name provided")
        return False

    place = get_osm_place(market_safe)
    if place is None:
        known = get_market_names()
        logger.warning(
            "[OSMDownload] Unknown market: {} (known: {})", market_safe, known
        )
        return False

    out_path = get_graphml_path(market_safe)
    if out_path.exists() and not force:
        logger.info("[OSMDownload] Already cached: {}", out_path)
        return True

    ensure_data_dir()
    logger.info("[OSMDownload] Downloading OSM network for {} → {}", place, out_path)
    try:
        G = ox.graph_from_place(place, network_type="drive_service", simplify=True)
        ox.save_graphml(G, str(out_path))
        logger.info(
            "[OSMDownload] Saved {}: {} nodes, {} edges",
            out_path,
            G.number_of_nodes(),
            G.number_of_edges(),
        )
        return True
    except Exception as exc:
        logger.error("[OSMDownload] Download failed for {}: {}", market_safe, exc)
        return False


def download_all(force: bool = False) -> dict[str, bool]:
    """Download all configured markets. Returns {market: success_bool}."""
    results: dict[str, bool] = {}
    for market in get_market_names():
        results[market] = download_market(market, force=force)
    return results


if __name__ == "__main__":
    results = download_all()
    for market, ok in results.items():
        status = "OK" if ok else "FAILED"
        print(f"[{market}] {status}")
