"""
RE_OS — Portal Plugin (Sprint 61)
Wraps PortalScout to scrape property listings. Adds Nominatim geocoding
with in-memory locality cache and per-second rate limiting to stay within
the OSM usage policy (max 1 req/sec).
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.parse
from loguru import logger
from ingest.base import DataPlugin, ParsedRecord

__all__ = ["PortalPlugin"]

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_HEADERS = {
    "User-Agent": "RE_OS/1.0 (market-intel-system; contact: dev@re-os.local)",
    "Accept": "application/json",
}
_NOMINATIM_MIN_INTERVAL = 1.1


class _Geocoder:
    """Thread-safe Nominatim geocoder with locality cache + rate limiting.

    Caches by ``(locality.lower(), market.lower())`` so repeated localities
    (e.g. 20 listings in "Yelahanka New Town") fire exactly one HTTP call.
    Enforces a 1.1s minimum interval between calls per Nominatim ToS.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()
        self._last_call = 0.0

    def geocode(self, locality: str, market: str) -> dict:
        key = (locality.strip().lower(), market.strip().lower())
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached

        elapsed = time.monotonic() - self._last_call
        if elapsed < _NOMINATIM_MIN_INTERVAL:
            time.sleep(_NOMINATIM_MIN_INTERVAL - elapsed)

        result = self._call_nominatim(locality, market)

        with self._lock:
            self._cache[key] = result
            self._last_call = time.monotonic()
        return result

    @staticmethod
    def _call_nominatim(locality: str, market: str) -> dict:
        try:
            q = f"{locality}, {market}, Bengaluru, Karnataka"
            params = urllib.parse.urlencode({"q": q, "format": "json", "limit": 1})
            url = f"{_NOMINATIM_URL}?{params}"
            req = urllib.request.Request(url, headers=_NOMINATIM_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                results = json.loads(resp.read())
            if results:
                return {
                    "lat": float(results[0].get("lat", 0)),
                    "lon": float(results[0].get("lon", 0)),
                    "display_name": results[0].get("display_name", ""),
                }
        except Exception as exc:
            logger.debug("[PortalPlugin] Nominatim geocode failed for '{}': {}", locality, exc)
        return {}


_geocoder = _Geocoder()


class PortalPlugin(DataPlugin):
    plugin_id = "portal_scout"
    source_id = "property_portals"

    def run(self, market: str) -> list[ParsedRecord]:
        from scrapers.portal_scout import PortalScout

        scout = PortalScout(market=market)
        listings = scout.scout()
        records: list[ParsedRecord] = []
        for listing in listings:
            cid = str(listing.get("cid", "")).strip()
            if not cid:
                continue
            locality = str(listing.get("locality", ""))
            # Deduplicate locality geocoding automatically via _Geocoder cache
            geo = _geocoder.geocode(locality, market) if locality else {}
            data = {
                "source": str(listing.get("source", "")),
                "market": market,
                "project_name": str(listing.get("project_name", "")),
                "developer": str(listing.get("developer", "")),
                "bhk_configs": str(listing.get("bhk_configs", "")),
                "price_display": str(listing.get("price_display", "")),
                "price_min": float(listing.get("price_min", 0) or 0),
                "price_max": float(listing.get("price_max", 0) or 0),
                "area_sqft": float(listing.get("area_sqft", 0) or 0),
                "locality": locality,
                "launch_status": str(listing.get("launch_status", "")),
                "is_new_launch": bool(listing.get("is_new_launch", False)),
                "rera_number": str(listing.get("rera_number", "")),
                "source_url": str(listing.get("source_url", "")),
                "source_listing_id": cid,
                "scraped_at": str(listing.get("scraped_at", "")),
            }
            if geo:
                data["lat"] = geo["lat"]
                data["lon"] = geo["lon"]
                data["geocoded_address"] = geo["display_name"]
            records.append(ParsedRecord(
                entity_type="listing",
                source_id=cid,
                market=market,
                data=data,
            ))
        logger.info("[PortalPlugin] {} listings for {}", len(records), market)
        return records
