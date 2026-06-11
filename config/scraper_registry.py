"""
RE_OS — Scraper Registry (GATE-89)
Single source of truth for all scraper/agent IDs used in reliability scoring.
Add a new scraper here once; it propagates to the API, dashboard, and tests.
"""

SCRAPER_NAMES: list[str] = [
    "rera_karnataka",
    "portal_scout",
    "news_scout",
    "kaveri_bhoomi",
    "bbmp_scout",
    "distressed_scout",
]
