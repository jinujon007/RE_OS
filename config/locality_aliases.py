"""
RE_OS — Locality Alias Configuration (T-947)

Maps each micro-market to known locality names/suburbs.
Used by portal_scout.py to filter out mis-geocoded listings
returned by property portals (e.g., Electronic City listing
classified as Devanahalli).

Add new aliases here — no code change needed.
"""
LOCALITY_ALIASES: dict[str, list[str]] = {
    "yelahanka": [
        "yelahanka",
        "yelahanka new town",
        "yelahanka old town",
        "yelahanka satellite town",
        "kodigehalli",
        "sahakara nagar",
        "vidyaranyapura",
        "jalahalli",
        "jalahalli east",
        "jalahalli west",
        "attur",
        "attur layout",
        "yelahanka air force base",
    ],
    "devanahalli": [
        "devanahalli",
        "devanahalli international airport",
        "kempegowda international airport",
        "vijayapura",
        "chikkaballapur",
        "nandi",
        "nandi hills",
        "nandigudi",
        "sulibele",
        "dodda gattiganabbe",
    ],
    "hebbal": [
        "hebbal",
        "hebbal lake",
        "hennur",
        "hennur cross",
        "sahakara nagar",
        "manyata tech park",
        "manyata embassy business park",
        "nagavara",
        "nagavara lake",
        "estancia",
        "byatarayanapura",
        "thanisandra",
        "thanisandra main road",
        "kothanur",
        "jakkur",
        "jakkur plantation",
    ],
    # Fallback: if market not listed, only exact match passes
}


def get_locality_aliases(market: str) -> list[str]:
    """Return the list of valid locality substrings for a given market.

    Falls back to [market.lower()] if no explicit aliases are configured.
    This ensures unknown markets still get basic filtering.
    """
    key = market.strip().lower()
    return LOCALITY_ALIASES.get(key, [key])
