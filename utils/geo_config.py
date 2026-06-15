"""
RE_OS — Shared Geographic Configuration (Tier 1 — Geospatial Foundation)
Single source of truth for market coordinates and OSM place names.
Used by: osm_download.py, infrastructure_scorer.py, and any future geospatial modules.
"""

from dataclasses import dataclass


@dataclass
class MarketGeo:
    name: str
    osm_place: str  # OSMnx query string for graph_from_place
    metro_lat: float | None  # nearest metro station latitude
    metro_lng: float | None  # nearest metro station longitude


# North Bengaluru primary markets
_MARKETS: dict[str, MarketGeo] = {
    "Yelahanka": MarketGeo(
        name="Yelahanka",
        osm_place="Yelahanka, Bengaluru, Karnataka, India",
        metro_lat=13.1007,
        metro_lng=77.5963,
    ),
    "Devanahalli": MarketGeo(
        name="Devanahalli",
        osm_place="Devanahalli, Bengaluru, Karnataka, India",
        metro_lat=13.2465,
        metro_lng=77.7083,
    ),
    "Hebbal": MarketGeo(
        name="Hebbal",
        osm_place="Hebbal, Bengaluru, Karnataka, India",
        metro_lat=13.0358,
        metro_lng=77.5970,
    ),
}

# Reference infrastructure points (lat, lng)
NH44_POINT = (13.0200, 77.5800)  # NH-44 intersection near Hebbal flyover
BIAL_COORDS = (13.1986, 77.7066)  # Kempegowda International Airport
CBD_COORDS = (12.9716, 77.5946)  # MG Road / CBD Bengaluru


def get_market_names() -> list[str]:
    return list(_MARKETS.keys())


def get_osm_place(market: str) -> str | None:
    m = _MARKETS.get(market)
    return m.osm_place if m else None


def get_metro_coords(market: str) -> tuple[float, float] | None:
    m = _MARKETS.get(market)
    if m and m.metro_lat is not None and m.metro_lng is not None:
        return (m.metro_lat, m.metro_lng)
    return None
