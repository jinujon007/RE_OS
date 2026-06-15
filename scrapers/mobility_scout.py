"""
RE_OS — Mobility Scout (Sprint 74 — GATE-74)
─────────────────────────────────────────────
Measures travel times from each market centroid to 5 key employment hubs
using Google Maps Distance Matrix API. Populates accessibility_scores table
for continuous accessibility scoring in the Opportunity Engine.

Market centroids (hardcoded):
  Yelahanka:    13.1007, 77.5963
  Devanahalli:  13.2497, 77.7144
  Hebbal:       13.0450, 77.5980

Destinations (5 employment hubs):
  Manyata Tech Park      (13.0535, 77.6184) — weight 0.30
  BIAL                   (13.1979, 77.7063) — weight 0.25
  Hebbal ORR             (13.0440, 77.5920) — weight 0.20
  Whitefield ITPB        (12.9793, 77.7413) — weight 0.15
  Nagawara               (13.0437, 77.6187) — weight 0.10

Thread safety:
  run_mobility_scout() uses a threading lock to prevent concurrent execution
  from the scheduler overlapping with manual CLI runs.

API key:
  Set GOOGLE_MAPS_API_KEY in .env. Free tier covers 1,000 elements/month
  (our usage = 3 markets x 5 destinations x 1 call = 15 elements/month).
  Without the key, the scout logs a warning and returns empty — the system
  relies on seed data until the API is configured.

Run standalone:
  python scrapers/mobility_scout.py --market Yelahanka
  python scrapers/mobility_scout.py  (runs all markets)
"""

import argparse
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests
from loguru import logger

from config.metrics import scraper_runs_total

_run_lock = threading.Lock()

MARKET_CENTROIDS: dict[str, tuple[float, float]] = {
    "Yelahanka": (13.1007, 77.5963),
    "Devanahalli": (13.2497, 77.7144),
    "Hebbal": (13.0450, 77.5980),
}

DESTINATIONS: list[dict[str, Any]] = [
    {"name": "Manyata Tech Park", "lat": 13.0535, "lng": 77.6184, "weight": 0.30},
    {"name": "BIAL", "lat": 13.1979, "lng": 77.7063, "weight": 0.25},
    {"name": "Hebbal ORR", "lat": 13.0440, "lng": 77.5920, "weight": 0.20},
    {"name": "Whitefield ITPB", "lat": 12.9793, "lng": 77.7413, "weight": 0.15},
    {"name": "Nagawara", "lat": 13.0437, "lng": 77.6187, "weight": 0.10},
]

DESTINATION_WEIGHTS: dict[str, float] = {d["name"]: d["weight"] for d in DESTINATIONS}

_RETRYABLE_STATUSES = {"OVER_QUERY_LIMIT", "OVER_DAILY_LIMIT"}
_MAX_RETRIES = 3
_INITIAL_RETRY_DELAY_S = 2.0


class MobilityScout:
    def __init__(self):
        self.api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
        self._session = requests.Session()

    def measure_travel_times(self, market: str) -> list[dict]:
        if not self.api_key:
            logger.warning(
                "[MobilityScout] GOOGLE_MAPS_API_KEY not set — returning empty"
            )
            return []

        centroid = MARKET_CENTROIDS.get(market)
        if not centroid:
            logger.warning("[MobilityScout] Unknown market: {}", market)
            return []

        results = []
        for dest in DESTINATIONS:
            row = self._query_distance_matrix_with_retry(centroid, dest)
            if row:
                results.append(row)

        logger.info(
            "[MobilityScout] {}: {}/{} destinations measured",
            market,
            len(results),
            len(DESTINATIONS),
        )
        return results

    def _query_distance_matrix_with_retry(
        self, origin: tuple[float, float], dest: dict
    ) -> dict | None:
        last_error = None
        delay = _INITIAL_RETRY_DELAY_S

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                result, should_retry = self._query_distance_matrix(origin, dest)
                if result is not None:
                    return result
                if should_retry and attempt < _MAX_RETRIES:
                    logger.info(
                        "[MobilityScout] Retry {}/{} for {} in {}s",
                        attempt,
                        _MAX_RETRIES,
                        dest["name"],
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2.0
                    last_error = result
                else:
                    break
            except requests.exceptions.Timeout:
                if attempt < _MAX_RETRIES:
                    logger.info(
                        "[MobilityScout] Timeout {}/{} for {}, retrying",
                        attempt,
                        _MAX_RETRIES,
                        dest["name"],
                    )
                    time.sleep(delay)
                    delay *= 2.0
                else:
                    logger.warning(
                        "[MobilityScout] All {} retries exhausted for {} (timeout)",
                        _MAX_RETRIES,
                        dest["name"],
                    )
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "[MobilityScout] Request failed for {}: {} — not retrying",
                    dest["name"],
                    exc,
                )
                break

        return None

    def _query_distance_matrix(
        self, origin: tuple[float, float], dest: dict
    ) -> tuple[dict | None, bool]:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": f"{origin[0]},{origin[1]}",
            "destinations": f"{dest['lat']},{dest['lng']}",
            "mode": "driving",
            "key": self.api_key,
        }

        resp = self._session.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            logger.warning(
                "[MobilityScout] Distance Matrix API HTTP {} for {}",
                resp.status_code,
                dest["name"],
            )
            return (None, False)

        data = resp.json()
        api_status = data.get("status")

        if api_status == "OK":
            try:
                element = data["rows"][0]["elements"][0]
                if element["status"] != "OK":
                    logger.debug(
                        "[MobilityScout] Element status {} for {}",
                        element.get("status"),
                        dest["name"],
                    )
                    return (None, False)

                travel_seconds = element["duration"]["value"]
                distance_metres = element["distance"]["value"]
                travel_min = round(travel_seconds / 60.0, 1)
                distance_km = round(distance_metres / 1000.0, 1)

                return (
                    {
                        "destination_name": dest["name"],
                        "travel_time_min": travel_min,
                        "distance_km": distance_km,
                        "mode": "driving",
                        "traffic_condition": "typical",
                        "measured_at": datetime.now(timezone.utc).isoformat(),
                    },
                    False,
                )

            except (KeyError, IndexError, TypeError) as exc:
                logger.warning(
                    "[MobilityScout] Parse error for {}: {}", dest["name"], exc
                )
                return (None, False)

        if api_status in _RETRYABLE_STATUSES:
            logger.warning(
                "[MobilityScout] {} for {} — retryable", api_status, dest["name"]
            )
            return (None, True)

        if api_status in ("INVALID_REQUEST", "NOT_FOUND", "ZERO_RESULTS"):
            logger.info(
                "[MobilityScout] Non-retryable status {} for {}",
                api_status,
                dest["name"],
            )
            return (None, False)

        logger.warning(
            "[MobilityScout] Unknown API status {} for {}", api_status, dest["name"]
        )
        return (None, False)


_accessibility_cache: dict[str, tuple[float, float]] = {}
_ACCESSIBILITY_CACHE_TTL = 300.0


def _cache_key(market: str) -> str:
    return f"acc:{market}"


def compute_market_accessibility(market: str, conn=None) -> float:
    """Compute weighted accessibility score for a market [0.0, 1.0].

    Uses the latest measurement for each of the 5 destinations within the
    last 30 days. Accepts an optional SQLAlchemy connection for reuse when
    called from within an existing DB transaction.

    Cached in-process for _ACCESSIBILITY_CACHE_TTL seconds to avoid
    repeated DB queries within a single IntelRegistry call cycle.

    Returns 0.0 on empty DB or any error (never raises).
    """
    now = time.time()
    ck = _cache_key(market)
    cached = _accessibility_cache.get(ck)
    if cached and (now - cached[1]) < _ACCESSIBILITY_CACHE_TTL:
        return cached[0]

    try:
        if conn is None:
            from utils.db import get_engine
            from sqlalchemy import text as sa_text

            engine = get_engine(pool_size=2, max_overflow=1)
            with engine.connect() as db_conn:
                score = _compute_from_db(db_conn, market)
        else:
            score = _compute_from_db(conn, market)

        _accessibility_cache[ck] = (score, now)
        return score
    except Exception as exc:
        logger.warning(
            "[MobilityScout] compute_market_accessibility failed for {}: {}",
            market,
            exc,
        )
        return 0.0


def _compute_from_db(conn, market: str) -> float:
    from sqlalchemy import text as sa_text

    rows = conn.execute(
        sa_text("""
            SELECT destination_name, travel_time_min
            FROM accessibility_scores
            WHERE market = :market
              AND measured_at > NOW() - INTERVAL '30 days'
            ORDER BY measured_at DESC
        """),
        {"market": market},
    ).fetchall()

    if not rows:
        return 0.0

    latest_per_dest: dict[str, float] = {}
    for r in rows:
        dest_name = str(r[0])
        if dest_name not in latest_per_dest:
            latest_per_dest[dest_name] = float(r[1])

    score = 0.0
    for dest_name, travel_min in latest_per_dest.items():
        weight = DESTINATION_WEIGHTS.get(dest_name, 0.0)
        component = weight * (1.0 - min(travel_min / 60.0, 1.0))
        score += component

    return round(max(0.0, min(score, 1.0)), 4)


def check_api_key_configured() -> dict:
    """Diagnostic: check if Google Maps API key is available and report status.

    Returns a dict with 'configured' bool and 'sources_available' count for
    use in /api/health responses.
    """
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        return {
            "configured": False,
            "message": "GOOGLE_MAPS_API_KEY not set in environment",
        }
    if key == "test_key" or key.startswith("AIza"):
        return {"configured": True, "message": "API key present"}
    return {"configured": True, "message": "API key set (unknown format)"}


def _compute_row_component(dest_name: str, travel_minutes: float) -> float:
    """Compute a single destination's contribution to the accessibility score.

    Returns the weighted component (not the total market score), used for
    per-row persistence in the accessibility_scores table.
    """
    weight = DESTINATION_WEIGHTS.get(dest_name, 0.0)
    return round(weight * (1.0 - min(travel_minutes / 60.0, 1.0)), 4)


def run_mobility_scout():
    """Scheduled job: measure travel times for all markets and persist.

    Thread-safe: uses a module-level threading lock to prevent concurrent
    execution (e.g., scheduler + manual CLI overlap).

    Runs 15 API calls (3 markets × 5 destinations) and inserts results
    into accessibility_scores. Designed for monthly execution on 1st of month.
    """
    if not _run_lock.acquire(blocking=False):
        logger.warning(
            "[MobilityScout] run_mobility_scout already in progress — skipping"
        )
        return

    try:
        success_count = 0
        total_markets = len(MARKET_CENTROIDS)
        failed_markets: list[str] = []

        for market in MARKET_CENTROIDS:
            try:
                scout = MobilityScout()
                results = scout.measure_travel_times(market)
                if results:
                    _persist_results(market, results)
                    success_count += 1
                    logger.info(
                        "[MobilityScout] {} results persisted for {}",
                        len(results),
                        market,
                    )
                else:
                    msg = (
                        "API key not configured"
                        if not scout.api_key
                        else "all destinations returned empty"
                    )
                    logger.info("[MobilityScout] No results for {}: {}", market, msg)
                    failed_markets.append(market)
            except Exception as exc:
                logger.warning("[MobilityScout] run failed for {}: {}", market, exc)
                failed_markets.append(market)

        try:
            scraper_runs_total.labels(
                source="mobility",
                market="all",
                status="success" if success_count == total_markets else "partial",
            ).inc()
        except Exception as exc:
            logger.debug("[MobilityScout] Metrics increment skipped: {}", exc)

        if failed_markets:
            logger.warning(
                "[MobilityScout] Completed: {}/{} markets updated. Failed: {}",
                success_count,
                total_markets,
                failed_markets,
            )
        else:
            logger.info(
                "[MobilityScout] Completed: {}/{} markets updated",
                success_count,
                total_markets,
            )
    finally:
        _run_lock.release()


def _persist_results(market: str, results: list[dict]):
    from utils.db import get_engine
    from sqlalchemy import text as sa_text

    with get_engine().begin() as conn:
        for r in results:
            component = _compute_row_component(
                r["destination_name"], r["travel_time_min"]
            )
            conn.execute(
                sa_text("""
                    INSERT INTO accessibility_scores
                        (market, destination_name, travel_time_min, distance_km,
                         mode, traffic_condition, measured_at, accessibility_score)
                    VALUES
                        (:market, :destination_name, :travel_time_min, :distance_km,
                         :mode, :traffic_condition, :measured_at, :accessibility_score)
                    ON CONFLICT (market, destination_name, mode, (measured_at AT TIME ZONE 'Asia/Kolkata')::DATE)
                    DO UPDATE SET
                        travel_time_min = EXCLUDED.travel_time_min,
                        distance_km = EXCLUDED.distance_km,
                        accessibility_score = EXCLUDED.accessibility_score,
                        measured_at = EXCLUDED.measured_at
                """),
                {
                    "market": market,
                    "destination_name": r["destination_name"],
                    "travel_time_min": r["travel_time_min"],
                    "distance_km": r["distance_km"],
                    "mode": r["mode"],
                    "traffic_condition": r["traffic_condition"],
                    "measured_at": r["measured_at"],
                    "accessibility_score": component,
                },
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Mobility Scout — travel time measurement"
    )
    parser.add_argument(
        "--market",
        default=None,
        choices=list(MARKET_CENTROIDS.keys()),
        help="Market name (default: run all markets)",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug-level logging"
    )
    args = parser.parse_args()

    if args.debug:
        logger.remove()
        logger.add(
            lambda msg: print(msg, end=""),
            level="DEBUG",
            format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}",
        )
        logger.debug("[MobilityScout] Debug mode enabled")

    if args.market:
        scout = MobilityScout()
        results = scout.measure_travel_times(args.market)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        slug = args.market.lower().replace(" ", "_")
        out_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "outputs",
            slug,
        )
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"mobility_{ts}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)

        print(f"\nMobility Scout — {args.market.upper()}")
        print(f"  Results: {len(results)} destinations")
        print(f"  Output:  {out_path}")
        for r in results:
            acc = _compute_row_component(r["destination_name"], r["travel_time_min"])
            geo_type = "API" if scout.api_key else "simulated"
            print(
                f"  {r['destination_name']:20s} → {r['travel_time_min']:5.1f} min, "
                f"{r['distance_km']:5.1f} km (acc={acc:.4f}, source={geo_type})"
            )
    else:
        run_mobility_scout()
