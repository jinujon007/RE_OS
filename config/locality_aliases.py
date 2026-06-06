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


KNOWN_ALIEN_LOCALITIES: dict[str, list[str]] = {
    "yelahanka": [
        "electronic city", "whitefield", "koramangala", "indiranagar",
        "mg road", "brigade road", "jayanagar", "jp nagar",
        "banashankari", "bannerghatta", "e city",
    ],
    "devanahalli": [
        "electronic city", "whitefield", "koramangala", "indiranagar",
        "mg road", "jayanagar", "jp nagar", "banashankari",
        "bannerghatta", "e city", "marathahalli", "sarjapur",
    ],
    "hebbal": [
        "electronic city", "whitefield", "koramangala", "indiranagar",
        "mg road", "jayanagar", "bannerghatta", "e city",
        "banashankari", "jp nagar", "sarjapur",
    ],
}


def is_alien_locality(market: str, locality_text: str) -> bool:
    """Check if a locality string contains known alien locality aliases for a market.
    
    Returns True if locality_text (lowercased) contains any alien substring.
    """
    key = market.strip().lower()
    aliens = KNOWN_ALIEN_LOCALITIES.get(key, [])
    text_lower = locality_text.lower()
    return any(alien in text_lower for alien in aliens)
