"""
RE_OS — Scraper Agent
─────────────────────
Does the grunt work. Pulls raw HTML/JSON from RERA Karnataka,
listings portals, Kaveri. No analysis — just raw data collection.
Uses Ollama (lightweight local model) to handle navigation decisions.
The real intelligence is in the tools, not the LLM here.
"""

from crewai import Agent
from crewai.tools import BaseTool
import requests
import httpx
from bs4 import BeautifulSoup
from loguru import logger
import json
import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import RERA_BASE_URL, MARKET_RERA_KEYWORDS
from config.llm_router import get_light_llm


# ── RERA SCRAPER TOOL ─────────────────────────────────────────────────────────

class RERAScraperTool(BaseTool):
    name: str = "rera_scraper"
    description: str = (
        "Scrapes RERA Karnataka portal for all registered projects in a given "
        "micro-market. Input: micro-market name (e.g., 'Yelahanka'). "
        "Returns: list of RERA projects with number, name, developer, units, status."
    )

    def _run(self, market_name: str) -> str:
        from scrapers.rera_karnataka import RERAKarnatakaScraper
        from config.checkpointer import Checkpointer
        scraper = RERAKarnatakaScraper()
        projects = scraper.scrape_market(market_name)
        # Save checkpoint — organizer reads from here (not from LLM output string)
        Checkpointer().save(market_name, "rera_scraped", projects)
        return json.dumps(projects, indent=2, default=str)


class ListingsScraperTool(BaseTool):
    name: str = "listings_scraper"
    description: str = (
        "Scrapes property listings from 99acres for a given micro-market. "
        "Input: micro-market name. "
        "Returns: list of active sale and rent listings with price, area, BHK config."
    )

    def _run(self, market_name: str) -> str:
        from scrapers.listings_scraper import ListingsScraper
        from config.checkpointer import Checkpointer
        scraper = ListingsScraper()
        listings = scraper.scrape_market(market_name)
        Checkpointer().save(market_name, "listings_scraped", listings)
        return json.dumps(listings, indent=2, default=str)


class GuidanceValueTool(BaseTool):
    name: str = "guidance_value_fetcher"
    description: str = (
        "Fetches current Karnataka government guidance values (circle rates) "
        "for a given micro-market from the Kaveri portal. "
        "Input: micro-market name (e.g., 'Yelahanka'). "
        "Returns: guidance value per sqft by locality and property type."
    )

    def _run(self, market_name: str) -> str:
        from scrapers.kaveri_karnataka import KaveriScraper
        from config.checkpointer import Checkpointer
        try:
            scraper = KaveriScraper()
            records = scraper.scrape_guidance_values(market_name)
            Checkpointer().save(market_name, "kaveri_gv_scraped", records)
            return json.dumps({"market": market_name, "records": len(records), "data": records}, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "market": market_name})


class KaveriRegistrationTool(BaseTool):
    name: str = "kaveri_registration_fetcher"
    description: str = (
        "Fetches recent property registration transactions from the Kaveri Karnataka portal. "
        "These are actual registered sale prices — ground truth for real market values. "
        "Input: micro-market name (e.g., 'Yelahanka'). "
        "Returns: list of recent registrations with transaction amount, area, price-per-sqft."
    )

    def _run(self, market_name: str) -> str:
        from scrapers.kaveri_karnataka import KaveriScraper
        from config.checkpointer import Checkpointer
        try:
            scraper = KaveriScraper()
            records = scraper.scrape_registrations(market_name, months_back=6)
            Checkpointer().save(market_name, "kaveri_reg_scraped", records)
            return json.dumps({"market": market_name, "records": len(records), "data": records}, default=str)
        except Exception as e:
            return json.dumps({"error": str(e), "market": market_name})


def create_scraper_agent() -> Agent:
    return Agent(
        role="Data Acquisition Specialist",
        goal=(
            "Pull complete, raw data from RERA Karnataka, property listing portals, "
            "and government databases for assigned micro-markets. "
            "Maximize coverage — miss nothing. Handle errors gracefully. "
            "Return raw structured data for the Parser Agent to process."
        ),
        backstory=(
            "You are a data extraction expert who knows every corner of India's "
            "government property databases. You know RERA Karnataka's portal structure, "
            "how listing sites load their data, and how to extract clean raw information "
            "from messy web pages. "
            "You don't analyze — you collect. Accuracy and completeness are your metrics. "
            "If a source is down, you log it and move on. Never block the pipeline."
        ),
        tools=[
            RERAScraperTool(),
            ListingsScraperTool(),
            GuidanceValueTool(),
            KaveriRegistrationTool(),
        ],
        llm=get_light_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
