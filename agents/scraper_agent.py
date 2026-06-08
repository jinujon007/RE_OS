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
import json

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
        projects, _cookies = scraper.scrape_market(market_name)
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
            return json.dumps(
                {"market": market_name, "records": len(records), "data": records},
                default=str,
            )
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
            return json.dumps(
                {"market": market_name, "records": len(records), "data": records},
                default=str,
            )
        except Exception as e:
            return json.dumps({"error": str(e), "market": market_name})


# ── Scout Tools (new) ─────────────────────────────────────────────────────────
# Each scout uses a different model and a different approach to finding properties.
# All scouts share ScoutMemory — cross-source dedup at the agent level.


class PortalScoutTool(BaseTool):
    name: str = "portal_scout"
    description: str = (
        "Scouts 7 property portals (99acres, Housing.com, MagicBricks, PropTiger, "
        "NoBroker, SquareYards) for active project listings and unit pricing. "
        "Uses AI extraction (Cerebras 8b) to parse raw HTML into structured data. "
        "Deduplicates via ScoutMemory — only new discoveries are flagged. "
        "Input: micro-market name. Returns: list of listings with is_new flag."
    )

    def _run(self, market_name: str) -> str:
        from scrapers.portal_scout import PortalScout
        from scrapers.scout_memory import ScoutMemory
        from config.checkpointer import Checkpointer

        try:
            memory = ScoutMemory(market_name)
            scout = PortalScout(market_name, memory)
            findings = scout.scout()
            new_count = sum(1 for f in findings if f.get("is_new"))
            Checkpointer().save(market_name, "portal_scout", findings)
            return json.dumps(
                {
                    "market": market_name,
                    "total": len(findings),
                    "new_discoveries": new_count,
                    "memory_stats": memory.stats(),
                    "data": findings,
                },
                default=str,
            )
        except Exception as e:
            return json.dumps({"error": str(e), "market": market_name})


class RERADetailScoutTool(BaseTool):
    name: str = "rera_detail_scout"
    description: str = (
        "Deep-dives into RERA Karnataka project detail pages to extract unit mix, "
        "project costs, site area, approval numbers, completion stages, and amenities. "
        "Enriches the basic RERA listing data with full project intelligence. "
        "Uses Groq Scout 17b — better at multi-table government page layouts. "
        "Input: micro-market name. Reads RERA checkpoint automatically. "
        "Returns: enriched project list with unit mix, costs, approval details."
    )

    def _run(self, market_name: str) -> str:
        from scrapers.rera_detail_scout import RERADetailScout
        from scrapers.scout_memory import ScoutMemory
        from config.checkpointer import Checkpointer

        try:
            memory = ScoutMemory(market_name)
            scout = RERADetailScout(market_name, memory)
            results = scout.scout()
            new_count = sum(1 for r in results if r.get("is_new"))
            Checkpointer().save(market_name, "rera_detail_scout", results)
            return json.dumps(
                {
                    "market": market_name,
                    "enriched": len(results),
                    "new_detail_dives": new_count,
                    "data": results,
                },
                default=str,
            )
        except Exception as e:
            return json.dumps({"error": str(e), "market": market_name})


class DeveloperScoutTool(BaseTool):
    name: str = "developer_scout"
    description: str = (
        "Crawls developer websites directly (Brigade, Prestige, Sobha, Godrej, Adarsh, "
        "Salarpuria, Shriram, Mantri) for North Bengaluru projects. "
        "Catches pre-launch and soft-launch projects not yet on portals or RERA. "
        "Uses Gemini Flash — full-page marketing content comprehension. "
        "Input: micro-market name. Returns: project list with launch status and highlights."
    )

    def _run(self, market_name: str) -> str:
        from scrapers.developer_scout import DeveloperScout
        from scrapers.scout_memory import ScoutMemory
        from config.checkpointer import Checkpointer

        try:
            memory = ScoutMemory(market_name)
            scout = DeveloperScout(market_name, memory)
            findings = scout.scout()
            new_count = sum(1 for f in findings if f.get("is_new"))
            Checkpointer().save(market_name, "developer_scout", findings)
            return json.dumps(
                {
                    "market": market_name,
                    "total": len(findings),
                    "new_pre_launch": new_count,
                    "data": findings,
                },
                default=str,
            )
        except Exception as e:
            return json.dumps({"error": str(e), "market": market_name})


class NewsScoutTool(BaseTool):
    name: str = "news_scout"
    description: str = (
        "Scans property news from Google News RSS and ET Realty for market signals: "
        "project launches, price changes, regulatory news, developer movements. "
        "Uses Gemini Flash for article comprehension and entity extraction. "
        "Input: micro-market name. Returns: news signals with signal_type and key_insight."
    )

    def _run(self, market_name: str) -> str:
        from scrapers.news_scout import NewsScout
        from scrapers.scout_memory import ScoutMemory
        from config.checkpointer import Checkpointer

        try:
            memory = ScoutMemory(market_name)
            scout = NewsScout(market_name, memory)
            findings = scout.scout(days_back=60)
            new_count = sum(1 for f in findings if f.get("is_new"))
            Checkpointer().save(market_name, "news_scout", findings)
            return json.dumps(
                {
                    "market": market_name,
                    "articles_analyzed": len(findings),
                    "new_signals": new_count,
                    "by_signal_type": {
                        sig: sum(1 for f in findings if f.get("signal_type") == sig)
                        for sig in (
                            "new_launch",
                            "price_change",
                            "regulatory",
                            "developer_news",
                        )
                    },
                    "data": findings,
                },
                default=str,
            )
        except Exception as e:
            return json.dumps({"error": str(e), "market": market_name})


def create_scraper_agent() -> Agent:
    return Agent(
        role="Market Intelligence Scout Commander",
        goal=(
            "Deploy all available scouts to build the most complete picture of a micro-market. "
            "Run RERA, portal, developer, and news scouts in sequence. "
            "Maximize new discovery coverage — every project, every listing, every signal. "
            "Deduplication is handled by ScoutMemory — focus on breadth and fresh data. "
            "Handle errors per scout gracefully. Never block the pipeline on one scout failing."
        ),
        backstory=(
            "You are a seasoned real estate market researcher who thinks like an agent "
            "walking the streets of Yelahanka. You know every developer office, every portal, "
            "every government registry. You read RERA files, check developer websites before "
            "they list on portals, and track news for project announcements. "
            "You run a team of specialized scouts — each with their own angle, their own model, "
            "their own information source. Your job is to coordinate them and bring back "
            "everything that matters. Nothing important gets missed. Nothing duplicate gets "
            "reported twice. The scout discovery log is your audit trail."
        ),
        tools=[
            RERAScraperTool(),
            GuidanceValueTool(),
            KaveriRegistrationTool(),
            PortalScoutTool(),
            RERADetailScoutTool(),
            DeveloperScoutTool(),
            NewsScoutTool(),
        ],
        llm=get_light_llm(),
        verbose=True,
        allow_delegation=False,
        max_iter=8,
    )
