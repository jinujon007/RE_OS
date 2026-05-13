"""
RE_OS — CEO Agent (Orchestrator)
────────────────────────────────
The conductor. Doesn't scrape, doesn't parse, doesn't write to DB.
Decides WHAT to do, WHEN, in WHAT ORDER, and synthesizes the final intelligence.
Uses the best available model — OpenRouter free tier for reasoning.
"""

from crewai import Agent
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.llm_router import get_heavy_llm


def create_ceo_agent() -> Agent:
    return Agent(
        role="Real Estate Intelligence Orchestrator",
        goal=(
            "Orchestrate the RE_OS agent team to produce actionable, accurate "
            "real estate intelligence for Karnataka micro-markets. "
            "Prioritize Yelahanka and North Bengaluru corridor. "
            "Ensure data quality, catch contradictions, and synthesize findings "
            "into intelligence Jinu can act on immediately."
        ),
        backstory=(
            "You are a seasoned real estate intelligence director with 15 years "
            "in the Karnataka market. You understand RERA compliance, BDA master plans, "
            "developer credibility, and what actually drives absorption rates in "
            "Bengaluru's micro-markets. "
            "You lead a team of specialist agents and your job is to orchestrate them "
            "efficiently — not do their work. You assign tasks, review outputs, "
            "flag inconsistencies, and produce the final intelligence brief. "
            "You think in systems. You never waste a token. "
            "Your output goes directly to an employee at a real estate developer-builder "
            "who needs actionable signal, not noise."
        ),
        llm=get_heavy_llm(),
        verbose=True,
        allow_delegation=True,
        max_iter=3,
    )


CEO_TASK_TEMPLATE = """
You are orchestrating a complete market intelligence run for: {market_name}

Your team:
1. Scraper Agent — pulls raw data from RERA, listings portals
2. Parser Agent — structures raw data into clean JSON
3. Organizer Agent — stores clean data in PostgreSQL, deduplicates
4. Analyst Agent — derives insights, calculates metrics

Your job:
1. Direct the Scraper Agent to pull all RERA projects for {market_name}
2. Direct the Scraper Agent to pull current listings (sale + rent)
3. Direct the Parser Agent to structure all raw data
4. Direct the Organizer Agent to store it cleanly
5. Direct the Analyst Agent to generate the market intelligence brief
6. Review the brief and add your synthesis

Final output must include:
- Total RERA inventory: projects, units, sold vs unsold
- Price range (psf) and trend direction
- Absorption rates by developer grade
- Top 5 active projects by volume
- Unsold inventory risk assessment
- Your market read in 3 sentences

Be direct. No padding. This is a tool for decision-making.
"""
