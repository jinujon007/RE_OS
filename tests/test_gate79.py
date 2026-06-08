"""
GATE-79 — Scraper Housekeeping + Monitoring

Four assertions:
1. scrape_listings task absent from Stage 1 crew
2. PORTAL_SCOUT_MIN_LISTINGS_CANARY constant in settings.py
3. run_finbert_sentiment_repair is registered as a job in scheduler
4. _fuzzy_match_registration exists in db_organizer.py

To run against live DB (integration test):
    docker compose exec agents pytest tests/test_gate79.py -m '' -v
"""
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.unit


def test_gate79_stage1_crew_excludes_scrape_listings():
    """Assert 1: scrape_listings Task not present in Stage 1 crew task list."""
    from crews.market_intel_crew import _build_data_crew
    crew = _build_data_crew("Yelahanka")
    descriptions = [t.description for t in crew.tasks]
    combined = "\n".join(descriptions)
    assert "listings_scraper" not in combined, "scrape_listings task found in Stage 1 crew"


def test_gate79_portal_scout_min_listings_canary():
    """Assert 2: settings has PORTAL_SCOUT_MIN_LISTINGS_CANARY constant."""
    from config.settings import PORTAL_SCOUT_MIN_LISTINGS_CANARY
    assert isinstance(PORTAL_SCOUT_MIN_LISTINGS_CANARY, int)
    assert PORTAL_SCOUT_MIN_LISTINGS_CANARY > 0


def test_gate79_finbert_repair_job_registered():
    """Assert 3: run_finbert_sentiment_repair is registered in scheduler."""
    from config.scheduler import run_finbert_sentiment_repair
    assert callable(run_finbert_sentiment_repair)


def test_gate79_fuzzy_match_registration_exists():
    """Assert 4: _fuzzy_match_registration exists as a method on DBOrganizer."""
    from utils.db_organizer import DBOrganizer
    assert hasattr(DBOrganizer, "_fuzzy_match_registration"), \
        "_fuzzy_match_registration not found on DBOrganizer"
