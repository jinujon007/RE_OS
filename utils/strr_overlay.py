"""
STRROverlay — STRR / Namma Metro station proximity intelligence.

Provides Haversine-based proximity search against a static station dataset.
Transit demand signal logic is consolidated here (single source of truth)
rather than duplicated in the API endpoint and board room context builder.

Usage:
    overlay = STRROverlay()
    stations = overlay.stations_near("Yelahanka", radius_km=3.0)
    signal = STRROverlay.transit_signal(stations)  # "STRONG" | "MODERATE" | "WEAK"
"""

from __future__ import annotations

import json
import logging
import math
import pathlib
import threading
import time

from config.metrics import _counter

logger = logging.getLogger("re_os.strr_overlay")

_centroid_failures_total = _counter(
    "strr_centroid_failures_total",
    "STRR centroid DB lookup failures",
    ["reason"],
)

__all__ = ["STRROverlay"]

_STATIONS_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "strr_stations.json"

_STATIONS: list[dict] | None = None
_STATIONS_MTIME: float = 0.0
_STATIONS_RELOAD_INTERVAL: float = 3600.0
_STATIONS_LOCK = threading.Lock()
_STATION_REQUIRED_FIELDS = frozenset({"name", "line", "lat", "lon", "status"})

_MARKET_COORDS: dict[str, tuple[float, float]] = {
    "yelahanka": (13.100, 77.594),
    "devanahalli": (13.248, 77.712),
    "hebbal": (13.058, 77.597),
    "thanisandra": (13.047, 77.632),
    "bagalur": (13.218, 77.728),
}


def _market_key(raw: str) -> str:
    return raw.strip().lower()


def _db_centroid(market: str) -> tuple[float, float] | None:
    """Query geometry centroid from micro_markets table.

    Returns (lat, lon) or None if DB unavailable, no matching row,
    or centroid_geom is NULL.
    """
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT ST_Y(centroid_geom), ST_X(centroid_geom) FROM micro_markets WHERE name ILIKE :m LIMIT 1"),
                {"m": _market_key(market)},
            ).fetchone()
        if row and row[0] is not None and row[1] is not None:
            return (float(row[0]), float(row[1]))
        _centroid_failures_total.labels(reason="null_geometry").inc()
        logger.debug("[STRR] _db_centroid: row missing or NULL geometry for %s", market)
    except Exception as exc:
        _centroid_failures_total.labels(reason="query_failed").inc()
        logger.debug("[STRR] _db_centroid query failed for %s: %s", market, exc)
    return None


def _validate_station(entry: dict) -> bool:
    missing = _STATION_REQUIRED_FIELDS - entry.keys()
    if missing:
        logger.warning("[STRR] Station entry missing fields %s: %s", missing, entry.get("name", "?"))
        return False
    if not isinstance(entry["lat"], (int, float)):
        logger.warning("[STRR] Station %s has non-numeric lat", entry.get("name", "?"))
        return False
    if not isinstance(entry["lon"], (int, float)):
        logger.warning("[STRR] Station %s has non-numeric lon", entry.get("name", "?"))
        return False
    if entry["status"] not in ("operational", "under_construction", "planned"):
        logger.warning("[STRR] Station %s has unknown status: %s", entry.get("name", "?"), entry["status"])
        return False
    return True


def _load_stations() -> list[dict]:
    global _STATIONS, _STATIONS_MTIME

    with _STATIONS_LOCK:
        if _STATIONS is not None:
            if time.time() - _STATIONS_MTIME > _STATIONS_RELOAD_INTERVAL:
                _STATIONS = None
                logger.debug("[STRR] TTL expired — forcing station reload")
            else:
                try:
                    current_mtime = _STATIONS_PATH.stat().st_mtime
                    if current_mtime <= _STATIONS_MTIME:
                        return _STATIONS
                except OSError:
                    return _STATIONS

        try:
            if not _STATIONS_PATH.exists():
                _STATIONS = []
                logger.warning("[STRR] Stations file not found at %s", _STATIONS_PATH)
                return _STATIONS

            raw = json.loads(_STATIONS_PATH.read_text(encoding="utf-8"))
            valid = [s for s in raw if _validate_station(s)]
            invalid_count = len(raw) - len(valid)
            if invalid_count:
                logger.warning("[STRR] Skipped %d invalid station entries", invalid_count)

            _STATIONS = valid
            _STATIONS_MTIME = _STATIONS_PATH.stat().st_mtime
            logger.info("[STRR] Loaded %d stations (skipped %d invalid)", len(valid), invalid_count)
        except Exception as exc:
            if _STATIONS is None:
                _STATIONS = []
            logger.warning("[STRR] Failed to load stations: %s", exc)
        return _STATIONS


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R_EARTH_KM = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R_EARTH_KM * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class STRROverlay:
    @staticmethod
    def transit_signal(stations: list[dict]) -> str:
        """Return transit demand signal strength for a list of nearby stations.

        Thresholds read from ``config.settings.STRR_STRONG_KM`` and
        ``config.settings.STRR_MODERATE_KM`` (defaults: 1.0 and 3.0 km).

        Threshold mapping:
            STRONG   — at least one operational station within STRR_STRONG_KM
            MODERATE — at least one station (any status) within STRR_MODERATE_KM
            WEAK     — no stations within STRR_MODERATE_KM or empty list

        These thresholds are calibrated for North Bengaluru urban morphology;
        revisit if applying to denser (CBD) or sparser (rural) markets.
        """
        from config.settings import STRR_STRONG_KM, STRR_MODERATE_KM
        if any(s["distance_km"] < STRR_STRONG_KM and s["status"] == "operational" for s in stations):
            return "STRONG"
        if any(s["distance_km"] < STRR_MODERATE_KM for s in stations):
            return "MODERATE"
        return "WEAK"

    def stations_near(self, market: str, radius_km: float = 2.0) -> list[dict]:
        """Return sorted list of stations within `radius_km` of `market` centroid.

        Each result dict: {name, line, distance_km, opening_year, opening_quarter, status}.
        Returns [] if market is unknown, stations file is missing/empty, or no stations
        are within radius.
        """
        market_key = _market_key(market)
        db_coords = _db_centroid(market)
        if db_coords is not None:
            lat, lon = db_coords
        else:
            coords = _MARKET_COORDS.get(market_key)
            if coords is None:
                return []
            lat, lon = coords
        stations = _load_stations()
        if not stations:
            return []
        result = []
        for s in stations:
            d = _haversine_km(lat, lon, s["lat"], s["lon"])
            if d <= radius_km:
                result.append({
                    "name": s["name"],
                    "line": s["line"],
                    "lat": s["lat"],
                    "lon": s["lon"],
                    "distance_km": round(d, 2),
                    "opening_year": s.get("opening_year"),
                    "opening_quarter": s.get("opening_quarter"),
                    "status": s["status"],
                })
        result.sort(key=lambda x: x["distance_km"])
        return result

    def __repr__(self) -> str:
        n = len(_load_stations())
        return f"<STRROverlay stations={n}>"
