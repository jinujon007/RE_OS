"""
RE_OS — Market Intelligence Crew  (v2 — 2026-05-13)
─────────────────────────────────────────────────────
Pipeline split into three stages to remove LLM from DB writes:

  STAGE 1 — Data Crew     (scraper agent, LLM-assisted navigation)
              ↓ checkpoint saved by tools
  STAGE 2 — Python Org    (pure Python: validate → batch upsert → log)
              ↓ DB now has real data
  STAGE 3 — Intel Crew    (analyst + CEO, query DB, produce report)

Benefits over v1 (single 6-task crew):
  - Organizer is 100× faster (no per-record LLM round-trips)
  - No hallucination risk on DB writes
  - Checkpoints survive failures — restart from last successful stage
  - Groq TPM saved ~40% (organizer no longer in LLM budget)

Run:
    python crews/market_intel_crew.py --market Yelahanka
    python crews/market_intel_crew.py --market Devanahalli
    python crews/market_intel_crew.py          # all markets
    python crews/market_intel_crew.py --history
"""

import argparse
import json
import os
import subprocess
import sys
import time as _time
import traceback
from datetime import datetime

from crewai import Crew, Task, Process
from loguru import logger

from agents import (
    create_ceo_agent,
    create_scraper_agent,
    create_analyst_agent,
)
from utils.agent_memory import read_memories, write_memory
from utils.appreciation_model import get_pincodes_for_market, get_appreciation_forecast
from config.settings import TARGET_MARKETS, GEMINI_CEO_MODEL, GEMINI_LIGHT_MODEL
from config.run_logger import RunLogger
from sqlalchemy import create_engine
from config.settings import DATABASE_URL
from config.checkpointer import Checkpointer
from config.llm_router import _exclude, _clear_excluded, _is_excluded, get_router_status
from config.metrics import (
    pipeline_runs_total,
    llm_calls_total,
    db_upserts_total,
    scrape_success_total,
)
from utils.validator import validate_and_log
from utils.db_organizer import DBOrganizer, _write_stage_event
from utils.obsidian_sync import sync_to_obsidian

# ── Rate-limit retry: exclude failing providers on the fly ─────────────────────

_RATE_LIMIT_RETRIES = 3

_DB_STATS_DEFAULT = {"inserted": 0, "updated": 0, "failed": 0, "duration_seconds": 0}
_MARKET_LOG_SINKS = {}


def _market_slug(market: str) -> str:
    return (market or "all").strip().lower().replace(" ", "_")


def _ensure_market_log_sink(market: str) -> None:
    """Route loguru records bound with market=<market> to /app/logs/{slug}.log."""
    slug = _market_slug(market)
    if slug in _MARKET_LOG_SINKS:
        return
    log_dir = "/app/logs" if os.path.isdir("/app") else "logs"
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"{slug}.log")
    sink_id = logger.add(
        path,
        rotation="5 MB",
        retention=5,
        level="INFO",
        filter=lambda record, m=market: record["extra"].get("market") == m,
    )
    _MARKET_LOG_SINKS[slug] = sink_id


def _extract_and_write_memories(agent_id: str, market: str, text: str) -> None:
    """Extract 3 key facts from text and persist them to agent_memories table.
    Uses Cerebras 8b (LIGHT tier). Non-fatal — logged at WARNING on failure."""
    from litellm import completion as litellm_completion
    from config.settings import CEREBRAS_API_KEY as _CKEY, CEREBRAS_BASE_URL as _CBASE, CEREBRAS_MODEL as _CMODEL
    try:
        extraction_prompt = (
            f"From this market brief, extract exactly 3 key facts as JSON list.\n"
            f"Each fact: one sentence, specific number included if available.\n"
            f'Format: [{{"fact": "...", "confidence": 0.6}}, ...]\n'
            f"Brief: {text[:2000]}"
        )
        response = litellm_completion(
            model=f"openai/{_CMODEL}",
            api_key=_CKEY,
            base_url=_CBASE,
            messages=[{"role": "user", "content": extraction_prompt}],
            temperature=0.2,
            max_tokens=500,
        )
        facts = json.loads(response.choices[0].message.content)
        if not isinstance(facts, list):
            return
        for fact_dict in facts:
            if isinstance(fact_dict, dict) and "fact" in fact_dict and "confidence" in fact_dict:
                write_memory(
                    agent_id,
                    market,
                    str(fact_dict["fact"]),
                    max(0.0, min(1.0, float(fact_dict["confidence"]))),
                )
    except Exception as exc:
        logger.warning(f"[Memory] {agent_id} write failed for {market}: {exc}")


# Single engine shared across all stage event writes in this process.
# Avoids creating a new connection pool for every one of the 8 stage events per run.
_stage_event_engine = None


def _get_stage_event_engine():
    global _stage_event_engine
    if _stage_event_engine is None:
        # SQLAlchemy engines are thread-safe; a brief duplicate-create race is harmless.
        _stage_event_engine = create_engine(
            DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=2
        )
    return _stage_event_engine


def _write_stage_event_to_db(run_id: str, market: str, event_name: str, status: str, stage: int = 0, **fields):
    """Fire-and-forget write to agent_runs. DB failure must NOT abort pipeline."""
    try:
        with _get_stage_event_engine().begin() as conn:
            _write_stage_event(conn, run_id, market, event_name, status, stage, **fields)
    except Exception as exc:
        logger.warning(f"Failed to write stage event {event_name} for {market}: {exc}")


def _log_event(run_id: str, market: str, stage: str, status: str, **fields):
    _ensure_market_log_sink(market)
    payload = {
        "event": "pipeline_stage",
        "run_id": run_id,
        "market": market,
        "stage": stage,
        "status": status,
    }
    payload.update(fields)
    logger.bind(market=market).info("pipeline_event | {}", json.dumps(payload))


def _gemini_exclusion_key(model_str: str) -> str:
    """Return the split exclusion key for a Gemini model."""
    if "gemma" in model_str.lower():
        return "gemini_gemma"
    return "gemini_flash"


def _detect_api_error_provider(exc: Exception) -> str | None:
    """Return the provider name if the error is a known API failure (rate limit, 404, auth),
    or None otherwise.
    Handles: RateLimitError, NotFoundError, AuthenticationError, and generic failures."""
    provider_attr = getattr(exc, "llm_provider", None)
    if provider_attr:
        p = provider_attr.lower()
        for name in ("cerebras", "groq", "nvidia", "openrouter"):
            if name in p:
                return name
        if "gemini" in p or "google" in p:
            return _gemini_exclusion_key(getattr(exc, "model", "") or "")
        # litellm maps Cerebras to "openai" since it's OpenAI-compatible
        if p == "openai":
            model_prefix = getattr(exc, "model", "") or ""
            KNOWN_OPENAI_MODELS = ("llama3.1-8b", "llama3.1-70b", "llama-3.3-70b")
            if any(m in model_prefix for m in KNOWN_OPENAI_MODELS):
                return "cerebras"
            model_base = getattr(exc, "base_url", None) or ""
            if "cerebras" in model_base:
                return "cerebras"

    model = getattr(exc, "model", None) or ""
    model_base = getattr(exc, "base_url", None) or ""
    msg = str(exc).lower()
    full_msg = str(exc)
    if "cerebras" in msg or "token_quota_exceeded" in msg or "tokens per day" in msg:
        return "cerebras"
    if "groq" in msg:
        return "groq"
    if "gemini" in msg or "google" in msg or "aistudio" in msg:
        return _gemini_exclusion_key(model)
    if "nvidia" in msg:
        return "nvidia"
    if "openrouter" in msg:
        return "openrouter"
    # NotFoundError with "model does not exist" or "model not found": extract provider from URL
    if type(exc).__name__ in ("NotFoundError", "AuthenticationError", "BadRequestError"):
        if "cerebras" in full_msg or "cerebras" in model:
            return "cerebras"
        if "api.cerebras.ai" in full_msg or "api.cerebras" in full_msg:
            return "cerebras"
        if "groq" in full_msg or "groq" in model:
            return "groq"
        if "api.groq.com" in full_msg:
            return "groq"
        if "gemini" in full_msg or "google" in full_msg or "aistudio" in full_msg:
            return _gemini_exclusion_key(model)
    # Generic 404 — infer provider from model prefix first, else first non-excluded
    if "404" in msg or "not found" in msg or "model does not exist" in msg:
        prefix_to_provider = {
            "openai/": "cerebras",
            "groq/": "groq",
            "google/": "gemini_flash",
            "gemini/": "gemini_flash",
            "nvidia/": "nvidia",
            "openrouter/": "openrouter",
        }
        for prefix, provider in prefix_to_provider.items():
            if prefix in model and not _is_excluded(provider):
                return provider
        for provider in ("cerebras", "groq", "gemini_flash", "gemini_gemma", "nvidia", "openrouter"):
            if not _is_excluded(provider):
                return provider
    # Cerebras rate limit says "OpenAIException - Requests per minute limit exceeded" (no
    # "cerebras" in the message). Groq sometimes returns "Invalid response from LLM call -
    # None or empty" instead of a 429 when overloaded or output is truncated. Treat both as
    # transient provider failures and attribute to the first non-excluded active provider.
    if (
        "requests per minute" in msg
        or "too many requests" in msg
        or "rate limit" in msg
        or "none or empty" in msg
        or "invalid response from llm" in msg
    ):
        for provider in ("cerebras", "groq", "gemini_flash", "gemini_gemma", "nvidia", "openrouter"):
            if not _is_excluded(provider):
                return provider
    return None


# Alias for backward compatibility with tests and external callers
_detect_rate_limited_provider = _detect_api_error_provider


# ── Stage banner ───────────────────────────────────────────────────────────────

_WIDTH = 65


def _banner(stage: str, description: str):
    print(f"\n{'─' * _WIDTH}")
    print(f"  RE_OS {stage}  |  {description}")
    print(f"{'─' * _WIDTH}")


def _header(market_name: str, run_id: str):
    print(f"\n{'=' * _WIDTH}")
    print("  RE_OS — Market Intelligence Run  (v2)")
    print(f"  Market  : {market_name}")
    print(f"  Run ID  : {run_id}")
    print(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * _WIDTH}")
    print("  PIPELINE: Scrape → (Python) Validate+DB → Analyse → CEO")
    print("  LLMs    : Cerebras 8b (scraper) | Groq Scout (Analyst+CEO)")
    print(f"{'=' * _WIDTH}\n")


# ── Stage 1: Data Crew ─────────────────────────────────────────────────────────


def _build_data_crew(market_name: str) -> Crew:
    scraper = create_scraper_agent()

    scrape_rera = Task(
        description=(
            f"Scrape ALL RERA Karnataka registered projects for: {market_name}. "
            f"Call the rera_scraper tool with input '{market_name}'. "
            f"The tool saves the data to disk automatically — do NOT repeat that JSON here. "
            f"Return only a brief summary: how many projects found and their source."
        ),
        expected_output=(
            f"One line: 'Found N RERA projects for {market_name} (source: live or fallback).'"
        ),
        agent=scraper,
    )

    scrape_rera_detail = Task(
        description=(
            f"Enrich RERA project records for {market_name} with full detail page data. "
            f"Call the rera_detail_scout tool with input '{market_name}'. "
            f"The tool reads the RERA checkpoint automatically — do NOT pass a file path. "
            f"It extracts unit mix, project costs, approval numbers, and completion stages. "
            f"Return a brief summary: how many projects enriched."
        ),
        expected_output=(
            f"One line: 'Enriched N RERA projects for {market_name} with detail data.'"
        ),
        agent=scraper,
        context=[scrape_rera],
    )

    scrape_listings = Task(
        description=(
            f"Scrape current property listings for: {market_name}. "
            f"Call the listings_scraper tool with input '{market_name}'. "
            f"Return a brief summary of how many listings found."
        ),
        expected_output=(f"One line: 'Found N listings for {market_name}.'"),
        agent=scraper,
    )

    scrape_portal = Task(
        description=(
            f"Scout 7 property portals for active {market_name} listings. "
            f"Call the portal_scout tool with input '{market_name}'. "
            f"The tool covers 99acres, Housing.com, MagicBricks, PropTiger, NoBroker, SquareYards. "
            f"It saves data to disk automatically. Return a brief summary: "
            f"how many listings found and how many are new discoveries."
        ),
        expected_output=(
            f"One line: 'Found N portal listings for {market_name} (X new discoveries).'"
        ),
        agent=scraper,
    )

    scrape_developer = Task(
        description=(
            f"Scout developer websites for {market_name} pre-launch and new projects. "
            f"Call the developer_scout tool with input '{market_name}'. "
            f"Covers Brigade, Prestige, Sobha, Godrej, Adarsh, Salarpuria, Shriram, Mantri. "
            f"Catches pre-launch projects not yet on portals or RERA. "
            f"Return a brief summary: how many developer projects found and how many are new."
        ),
        expected_output=(
            f"One line: 'Found N developer projects for {market_name} (X new pre-launch).'"
        ),
        agent=scraper,
    )

    scrape_news = Task(
        description=(
            f"Scout property news for {market_name} market signals (last 60 days). "
            f"Call the news_scout tool with input '{market_name}'. "
            f"Signal types: new_launch, price_change, regulatory, developer_news, infrastructure. "
            f"Return a brief summary: how many articles analyzed and which signal types found."
        ),
        expected_output=(
            f"One line: 'Analyzed N articles for {market_name}. Signals: [list signal types found].'"
        ),
        agent=scraper,
    )

    scrape_kaveri = Task(
        description=(
            f"Fetch Kaveri Karnataka data for: {market_name}. "
            f"Step 1: Call the guidance_value_fetcher tool with input '{market_name}' "
            f"to get current government circle rates (guidance values). "
            f"Step 2: Call the kaveri_registration_fetcher tool with input '{market_name}' "
            f"to get recent actual property registration transactions. "
            f"Both tools save data to disk automatically — do NOT repeat the full JSON here. "
            f"Return a brief summary: how many GV records and how many registrations found."
        ),
        expected_output=(
            f"Two lines: 'Found N guidance value records for {market_name}.' "
            f"and 'Found N Kaveri registrations for {market_name}.'"
        ),
        agent=scraper,
    )

    return Crew(
        agents=[scraper],
        tasks=[
            scrape_rera,
            scrape_rera_detail,
            scrape_listings,
            scrape_portal,
            scrape_developer,
            scrape_news,
            scrape_kaveri,
        ],
        process=Process.sequential,
        verbose=True,
    )


# ── Stage 3: Intel Crew ────────────────────────────────────────────────────────


def _build_intel_crew(market_name: str, db_stats: dict, has_fallback_data: bool = False,
                      ceo_memory_context: str = "", analyst_memory_context: str = "",
                      appreciation_forecasts_json: str = "") -> Crew:
    analyst = create_analyst_agent()
    ceo = create_ceo_agent()
    # CEO synthesizes in the intel crew — no re-delegation back to analyst
    ceo.allow_delegation = False
    
    # Inject memory contexts into agent backstories
    if ceo_memory_context:
        ceo.backstory += f"\n\nINSTITUTIONAL MEMORY — confirmed facts from previous runs:\n{ceo_memory_context}"
    if analyst_memory_context:
        analyst.backstory += f"\n\nINSTITUTIONAL MEMORY — confirmed facts from previous runs:\n{analyst_memory_context}"

    analyze = Task(
        description=(
            f"Generate a market intelligence brief for {market_name}.\n"
            f"This run wrote {db_stats.get('inserted', 0)} new + "
            f"{db_stats.get('updated', 0)} updated RERA records to the DB.\n\n"
            f"STRICT TOOL CALL SEQUENCE — call each tool EXACTLY ONCE, in order:\n"
            f"  Step 1: market_summary_query with input: {market_name}\n"
            f"  Step 2: competitor_analysis with input: {market_name}\n"
            f"  Step 3: distressed_developer_list with input: {market_name}\n"
            f"  Step 4: generate_market_report with input: the exact JSON from Step 1\n"
            f"  Step 5: Write Final Answer.\n\n"
            f"DO NOT call any tool more than once. DO NOT call market_summary_query again "
            f"after Step 1. Proceed directly from tool output to Final Answer.\n\n"
            f"For generate_market_report, pass the JSON string from market_summary_query "
            f"as the value of the key 'market_data_json'.\n\n"
            f"After the formatted report, add your analyst read:\n"
            f"- Absorption signal (what rate means for the market)\n"
            f"- Supply pressure (months of inventory remaining at current velocity)\n"
            f"- GV gap signal (market vs circle rate — what it means for LLS land cost)\n"
            f"- Dominant developer and their positioning\n"
            f"- Pricing white space where LLS could enter\n"
            f"- Distressed/JD-JV signal from distressed_developer_list "
            f"(stalled_project_count, debt_flagged_projects, last_launch_date)\n"
            f"- Data quality note: state if data is LIVE or FALLBACK SAMPLE"
            + (f"\n\n## Appreciation Forecasts (pre-computed)\n{appreciation_forecasts_json}\n\n"
               f"Use the pre-computed appreciation forecasts in the context. "
               f"Do not invent PSF projections — cite the forecast data."
               if appreciation_forecasts_json else "")
        ),
        expected_output=(
            "Formatted market brief with: inventory overview, top 5 projects, developer scorecard, "
            "risk flags, 6-signal analyst read (absorption, supply pressure, GV gap, "
            "dominant dev, LLS entry point, distressed/JD-JV signal), data quality note."
        ),
        agent=analyst,
    )

    ceo_synthesis = Task(
        description=(
            f"The analyst has produced a complete market intelligence brief for {market_name}. "
            f"It is in your context. Read it and write a 6-section CEO brief.\n\n"
            f"IMPORTANT: You have NO tools. Do NOT delegate. Do NOT ask questions. "
            f"Just read the analyst context and write the 6 sections below.\n\n"
            f"SECTION 1 — MARKET PULSE\n"
            f"  3 numbers: absorption rate, average PSF range, active project count.\n"
            f"  One sentence: is this market hot, stable, or cooling?\n\n"
            f"SECTION 2 — SUPPLY ANALYSIS\n"
            f"  Months of inventory at current velocity. New supply risk. Grade mix.\n\n"
            f"SECTION 3 — COMPETITOR ACTIVITY\n"
            f"  Who are the Grade A players? What are they doing? Any distressed signals?\n\n"
            f"SECTION 4 — DEMAND SIGNALS\n"
            f"  Kaveri registration count. GV gap (market vs circle rate). What it means.\n\n"
            f"SECTION 5 — RISK FLAGS\n"
            f"  Max 3 risks. Each one line: what the risk is and who it affects.\n\n"
            f"SECTION 6 — LLS ACTION\n"
            f"  One sentence. Specific. Actionable. With a number.\n"
            f"  Example: 'Acquire land in Yelahanka North at <₹X/sqft before Brigade "
            f"  prices it higher in next launch.'\n"
            f"  If data is fallback/sample: say so and note confidence is LOW.\n\n"
            f"FALLBACK_FLAG: {'TRUE' if has_fallback_data else 'FALSE'}\n"
            f"If FALLBACK_FLAG is TRUE, treat all numeric outputs as estimated. "
            f"Prefix every number with [ESTIMATED] and add a warning at the top.\n\n"
            f"DATA QUALITY CHECK: If the analyst report says data is FALLBACK SAMPLE, "
            f"prefix every number with [ESTIMATED] and add a warning at the top."
        ),
        expected_output=(
            "Six-section CEO brief: Market Pulse | Supply Analysis | Competitor Activity | "
            "Demand Signals | Risk Flags | LLS Action. Each section clearly labelled. "
            "LLS Action is one specific sentence with a number."
        ),
        agent=ceo,
        context=[analyze],
    )

    return Crew(
        agents=[analyst, ceo],
        tasks=[analyze, ceo_synthesis],
        process=Process.sequential,
        verbose=True,
    )


# ── Retry wrapper for crew kickoffs with rate-limit fallback ──────────────────


def _kickoff_with_fallback(
    crew: Crew,
    build_fn,  # callable that returns a new Crew (e.g. lambda: _build_data_crew(market_name))
    stage_name: str,
    market_name: str,
    max_retries: int = _RATE_LIMIT_RETRIES,
):
    """Kickoff a crew, retrying with excluded providers if a rate limit or API error is hit.
    build_fn is called to rebuild the crew with fallback LLMs after excluding a provider.
    """
    from litellm.exceptions import RateLimitError, NotFoundError
    last_error = None
    for attempt in range(1, max_retries + 2):  # first attempt + retries
        try:
            llm_calls_total.labels(stage=stage_name, market=market_name).inc()
            return crew.kickoff()
        except (RateLimitError, NotFoundError) as exc:
            provider = _detect_api_error_provider(exc)
            if provider and attempt <= max_retries:
                _exclude(provider)
                logger.warning(
                    f"[Retry] {stage_name}: {provider} failed ({type(exc).__name__}), excluding and retrying (attempt {attempt}/{max_retries})"
                )
                print(
                    f"\n  [Retry] {provider} unavailable → rebuilding crew with fallback LLM..."
                )
                crew = build_fn()
                last_error = exc
            else:
                raise
        except Exception as exc:
            provider = _detect_api_error_provider(exc)
            if provider and attempt <= max_retries:
                _exclude(provider)
                logger.warning(
                    f"[Retry] {stage_name}: possible {provider} failure ({type(exc).__name__}), excluding and retrying (attempt {attempt}/{max_retries})"
                )
                crew = build_fn()
                last_error = exc
            else:
                raise
    raise last_error or RuntimeError(f"{stage_name} failed after {max_retries} retries")


# ── Output extraction helper ───────────────────────────────────────────────────


def _extract_report_body(result) -> tuple[str, str, str, str]:
    """Extract analyst_raw, ceo_raw, report_body, ceo_section from a crew result.

    CEO output shorter than 100 chars is treated as a failed/placeholder synthesis —
    report falls back to the analyst output.

    Returns:
        (analyst_raw, ceo_raw, report_body, ceo_section)
    """
    ceo_raw = ""
    analyst_raw = ""
    if hasattr(result, "tasks_output") and result.tasks_output:
        if len(result.tasks_output) >= 2:
            analyst_raw = result.tasks_output[0].raw or ""
            ceo_raw = result.tasks_output[1].raw or ""
        elif len(result.tasks_output) == 1:
            analyst_raw = result.tasks_output[0].raw or ""
    ceo_raw = ceo_raw or (result.raw if hasattr(result, "raw") else str(result))

    if len(ceo_raw.strip()) < 100:
        logger.warning("[CEO] Short/placeholder output — falling back to analyst report")
        report_body = analyst_raw or str(result)
        ceo_section = "[CEO synthesis unavailable — see analyst report above]"
    else:
        report_body = ceo_raw
        ceo_section = ""

    return analyst_raw, ceo_raw, report_body, ceo_section


# ── Main run function ──────────────────────────────────────────────────────────


def run_market_intelligence(market_name: str) -> str:
    _ensure_market_log_sink(market_name)
    market_logger = logger.bind(market=market_name)
    rl = RunLogger(market=market_name)
    rl.start()
    pipeline_runs_total.labels(market=market_name).inc()
    run_id = rl.run_id
    cp = Checkpointer()

    _header(market_name, run_id)
    _log_event(run_id, market_name, "pipeline", "start")
    _write_stage_event_to_db(run_id, market_name, "pipeline_start", "start", stage=0, metadata={})

    try:
        # ── STAGE 1: Data collection ───────────────────────────────────────────
        _banner("STAGE 1/3", "Scraping RERA Karnataka + listings ...")
        stage1_started = datetime.now()
        _log_event(run_id, market_name, "stage_1_scrape", "start")
        _write_stage_event_to_db(run_id, market_name, "stage_1_start", "start", stage=1)

        # Skip Stage 1 only when ALL scout checkpoints exist from today's run.
        # RERA-only cache skip caused portal/developer/news scouts to never run,
        # leaving listings table at 0 on all subsequent same-day runs.
        scouts_all_cached = (
            cp.exists(market_name, "rera_scraped")
            and cp.exists(market_name, "portal_scout")
            and cp.exists(market_name, "developer_scout")
            and cp.exists(market_name, "news_scout")
            and cp.exists(market_name, "kaveri_gv_scraped")
        )
        stage1_ok = False
        records_scraped = 0  # Initialize records scraped counter
        if scouts_all_cached:
            _log_event(
                run_id,
                market_name,
                "stage_1_scrape",
                "skip",
                reason="all_checkpoints_cached",
            )
            _write_stage_event_to_db(
                run_id,
                market_name,
                "stage_1_end",
                "skip",
                stage=1,
                reason="all_checkpoints_cached",
                metadata={"records_scraped": records_scraped},
            )
            print(
                "  [Cache] All scouts cached. Delete outputs/{market}/checkpoints/ to force re-scrape."
            )
            rl.agent_done("scrape_rera")
            rl.agent_done("scrape_listings")
            stage1_ok = True
            raw_projects = cp.load(market_name, "rera_scraped") or []
            records_scraped = len(raw_projects)
        else:
            try:
                data_crew = _build_data_crew(market_name)
                _kickoff_with_fallback(
                    data_crew,
                    lambda: _build_data_crew(market_name),
                    "Stage 1 (scrape)",
                    market_name,
                )
                rl.agent_done("scrape_rera")
                rl.agent_done("scrape_listings")
                stage1_ok = True
            except Exception as s1_exc:
                _log_event(
                    run_id,
                    market_name,
                    "stage_1_scrape",
                    "failed",
                    error=str(s1_exc),
                    duration_seconds=round((datetime.now() - stage1_started).total_seconds(), 2),
                )
                _write_stage_event_to_db(
                    run_id,
                    market_name,
                    "stage_1_end",
                    "failed",
                    stage=1,
                    error=str(s1_exc),
                    duration_seconds=round((datetime.now() - stage1_started).total_seconds(), 2),
                    metadata={"records_scraped": records_scraped},
                )
                print(f"\n  [!!] Stage 1 failed: {s1_exc}")
                print(
                    "  [!!] Continuing with Stage 2/3 using any cached checkpoints..."
                )

        print(
            "  Stage 1 complete."
            if stage1_ok
            else "  Stage 1 partial (fallback to cache)."
        )
        if stage1_ok:
            scrape_success_total.labels(market=market_name).inc()
            _log_event(
                run_id,
                market_name,
                "stage_1_scrape",
                "success",
                duration_seconds=round((datetime.now() - stage1_started).total_seconds(), 2),
            )
            _write_stage_event_to_db(
                run_id,
                market_name,
                "stage_1_end",
                "success",
                stage=1,
                duration_seconds=round((datetime.now() - stage1_started).total_seconds(), 2),
                metadata={"records_scraped": records_scraped},
            )

        # ── STAGE 2: Pure Python validate + upsert ────────────────────────────
        _banner("STAGE 2/3", "Validating + writing to PostgreSQL (no LLM) ...")
        stage2_started = datetime.now()
        _log_event(run_id, market_name, "stage_2_db", "start")
        _write_stage_event_to_db(run_id, market_name, "stage_2_start", "start", stage=2)

        raw_projects = cp.load(market_name, "rera_scraped") or []
        valid, invalid, val_report = validate_and_log(raw_projects, market_name)

        pass_rate = val_report.get('pass_rate_pct', 0)
        print(
            f"\n  Validation: {val_report['valid']} valid / "
            f"{val_report['invalid']} rejected / "
            f"{val_report['total']} total  "
            f"({pass_rate}% pass rate)"
        )
        if invalid:
            print(
                f"  First rejection: {val_report['error_summary'][0] if val_report['error_summary'] else ''}"
            )

        organizer = DBOrganizer()
        try:
            db_stats = organizer.run(market_name, valid)
        except Exception as s2_exc:
            _log_event(
                run_id,
                market_name,
                "stage_2_db",
                "failed",
                error=str(s2_exc),
                duration_seconds=round((datetime.now() - stage2_started).total_seconds(), 2),
            )
            _write_stage_event_to_db(
                run_id,
                market_name,
                "stage_2_end",
                "failed",
                stage=2,
                error=str(s2_exc),
                duration_seconds=round((datetime.now() - stage2_started).total_seconds(), 2),
                metadata={"inserted": db_stats.get("inserted", 0), "updated": db_stats.get("updated", 0), "failed": db_stats.get("failed", 0)},
            )
            market_logger.error(f"[run:{run_id}] STAGE 2 DB write FAILED: {s2_exc}\n{traceback.format_exc()}")
            print(f"\n  [!!] Stage 2 DB write failed: {s2_exc}")
            print("  [!!] Continuing to Stage 3 with cached/empty data...")
            db_stats = _DB_STATS_DEFAULT
        cp.save(market_name, "db_stats", db_stats)
        rl.agent_done("organizer")
        db_upserts_total.labels(source="rera", market=market_name).inc(
            db_stats.get("inserted", 0) + db_stats.get("updated", 0)
        )

        print(
            f"\n  DB write done: {db_stats['inserted']} inserted, "
            f"{db_stats['updated']} updated, {db_stats['failed']} failed "
            f"({db_stats['duration_seconds']}s)"
        )

        # Kaveri upsert (guidance values + registrations)
        gv_records = cp.load(market_name, "kaveri_gv_scraped") or []
        reg_records = cp.load(market_name, "kaveri_reg_scraped") or []
        if gv_records or reg_records:
            kaveri_stats = organizer.run_kaveri(market_name, gv_records, reg_records)
            cp.save(market_name, "kaveri_db_stats", kaveri_stats)
            db_upserts_total.labels(source="kaveri_gv", market=market_name).inc(
                kaveri_stats.get("gv_inserted", 0) + kaveri_stats.get("gv_updated", 0)
            )
            db_upserts_total.labels(source="kaveri_reg", market=market_name).inc(
                kaveri_stats.get("reg_inserted", 0)
            )
            print(
                f"\n  Kaveri DB: GV {kaveri_stats['gv_inserted']}+{kaveri_stats['gv_updated']}, "
                f"Reg {kaveri_stats['reg_inserted']} inserted "
                f"({kaveri_stats['duration_seconds']}s)"
            )
        else:
            kaveri_stats = {}
            market_logger.info(
                "[Crew] No Kaveri checkpoints found — skipping Kaveri DB upsert"
            )

        # Scout upserts (portal, developer, news)
        portal_findings = cp.load(market_name, "portal_scout") or []
        if portal_findings:
            portal_stats = organizer.run_portal_scout(market_name, portal_findings)
            db_upserts_total.labels(source="portal", market=market_name).inc(
                portal_stats.get("upserted", 0)
            )
            print(
                f"\n  Portal Scout DB: {portal_stats.get('upserted', 0)} listings upserted"
            )
        else:
            logger.info("[Crew] No portal_scout checkpoint — skipping")

        dev_findings = cp.load(market_name, "developer_scout") or []
        if dev_findings:
            dev_stats = organizer.run_developer_scout(market_name, dev_findings)
            db_upserts_total.labels(source="developer", market=market_name).inc(
                dev_stats.get("upserted", 0)
            )
            print(
                f"  Developer Scout DB: {dev_stats.get('upserted', 0)} projects upserted"
            )
        else:
            logger.info("[Crew] No developer_scout checkpoint — skipping")

        news_findings = cp.load(market_name, "news_scout") or []
        if news_findings:
            news_stats = organizer.run_news_scout(market_name, news_findings)
            db_upserts_total.labels(source="news", market=market_name).inc(
                news_stats.get("inserted", 0)
            )
        else:
            logger.info("[Crew] No news_scout checkpoint — skipping")

        rera_detail_findings = cp.load(market_name, "rera_detail_scout") or []
        if rera_detail_findings:
            detail_stats = organizer.run_rera_detail_scout(
                market_name, rera_detail_findings
            )
            db_upserts_total.labels(source="rera_detail", market=market_name).inc(
                detail_stats.get("inserted", 0) + detail_stats.get("updated", 0)
            )
            print(
                f"  RERA Detail Scout: {detail_stats['updated']} updated, "
                f"{detail_stats['inserted']} inserted"
            )
        else:
            logger.info("[Crew] No rera_detail_scout checkpoint — skipping")

        _log_event(
            run_id,
            market_name,
            "stage_2_db",
            "success",
            duration_seconds=round((datetime.now() - stage2_started).total_seconds(), 2),
            rera_inserted=db_stats.get("inserted", 0),
            rera_updated=db_stats.get("updated", 0),
        )
        _write_stage_event_to_db(
            run_id,
            market_name,
            "stage_2_end",
            "success",
            stage=2,
            duration_seconds=round((datetime.now() - stage2_started).total_seconds(), 2),
            rera_inserted=db_stats.get("inserted", 0),
            rera_updated=db_stats.get("updated", 0),
            metadata={"inserted": db_stats.get("inserted", 0), "updated": db_stats.get("updated", 0), "failed": db_stats.get("failed", 0)},
        )

        # ── STAGE 3: Intelligence ──────────────────────────────────────────────
        _banner("STAGE 3/3", "Generating market intelligence (Analyst + CEO) ...")
        stage3_started = datetime.now()
        _log_event(run_id, market_name, "stage_3_intel", "start")
        _write_stage_event_to_db(run_id, market_name, "stage_3_start", "start", stage=3)

        has_fallback_data = any(
            str(r.get("data_source", r.get("source", ""))).strip().lower()
            in {"fallback_sample", "seed_estimated"}
            for r in raw_projects
            if isinstance(r, dict)
        )

        # Load institutional memory for CEO + Analyst agents (T-255)
        ceo_memories = read_memories("ceo", market_name, limit=5)
        analyst_memories = read_memories("analyst", market_name, limit=5)
        ceo_memory_context = ""
        analyst_memory_context = ""
        if ceo_memories:
            ceo_memory_context = "\n".join(
                [f"- {m['fact']} (confidence: {m['confidence']:.2f})" for m in ceo_memories]
            )
        if analyst_memories:
            analyst_memory_context = "\n".join(
                [f"- {m['fact']} (confidence: {m['confidence']:.2f})" for m in analyst_memories]
            )

        # Compute appreciation forecasts for market pincodes (T-313)
        pincodes = get_pincodes_for_market(market_name)
        forecasts = []
        for pincode in pincodes[:5]:
            try:
                forecasts.append(get_appreciation_forecast(pincode))
            except Exception:
                pass
        appreciation_forecasts_json = json.dumps(forecasts, indent=2) if forecasts else ""

        try:
            intel_crew = _build_intel_crew(market_name, db_stats, has_fallback_data=has_fallback_data,
                                         ceo_memory_context=ceo_memory_context,
                                         analyst_memory_context=analyst_memory_context,
                                         appreciation_forecasts_json=appreciation_forecasts_json)
            result = _kickoff_with_fallback(
                intel_crew,
                lambda: _build_intel_crew(market_name, db_stats, has_fallback_data=has_fallback_data,
                                        ceo_memory_context=ceo_memory_context,
                                        analyst_memory_context=analyst_memory_context,
                                        appreciation_forecasts_json=appreciation_forecasts_json),
                "Stage 3 (intel)",
                market_name,
            )
        except Exception as s3_exc:
            _log_event(
                run_id,
                market_name,
                "stage_3_intel",
                "failed",
                error=str(s3_exc),
                duration_seconds=round((datetime.now() - stage3_started).total_seconds(), 2),
            )
            _write_stage_event_to_db(
                run_id,
                market_name,
                "stage_3_end",
                "failed",
                stage=3,
                error=str(s3_exc),
                duration_seconds=round((datetime.now() - stage3_started).total_seconds(), 2),
                metadata={"has_fallback": has_fallback_data},
            )
            logger.error(f"[run:{run_id}] STAGE 3 FAILED: {s3_exc}\n{traceback.format_exc()}")
            rl.finish(status="failed", error=f"Stage 3: {s3_exc}")
            _clear_excluded()
            raise RuntimeError(
                f"Stage 3 (intel) failed for {market_name}: {s3_exc}"
            ) from s3_exc
        rl.agent_done("analyst")
        rl.agent_done("ceo")
        _log_event(
            run_id,
            market_name,
            "stage_3_intel",
            "success",
            duration_seconds=round((datetime.now() - stage3_started).total_seconds(), 2),
        )
        _write_stage_event_to_db(
            run_id,
            market_name,
            "stage_3_end",
            "success",
            stage=3,
            duration_seconds=round((datetime.now() - stage3_started).total_seconds(), 2),
            metadata={"has_fallback": has_fallback_data},
        )

        # Extract outputs — prefer CEO synthesis; fall back to analyst if CEO returned placeholder
        analyst_raw, ceo_raw, report_body, ceo_section = _extract_report_body(result)

        # --- Analyst memory write (T-285) ---
        if analyst_raw and len(analyst_raw.strip()) >= 50:
            _extract_and_write_memories("analyst", market_name, analyst_raw)

         # ── Save report ────────────────────────────────────────────────────────
        output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "outputs",
            market_name.lower().replace(" ", "_"),
        )
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        report_path = os.path.join(output_dir, f"intel_report_{timestamp}.txt")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("RE_OS Market Intelligence Report\n")
            f.write(f"Market    : {market_name}\n")
            f.write(f"Generated : {datetime.now().isoformat()}\n")
            f.write(f"Run ID    : {rl.run_id}\n")
            f.write(
                f"DB        : {db_stats['inserted']} inserted, {db_stats['updated']} updated\n"
            )
            f.write(
                f"Validated : {val_report['valid']}/{val_report['total']} records\n"
            )
            f.write("=" * 60 + "\n\n")
            f.write(report_body)
            if ceo_section:
                f.write(f"\n\n{ceo_section}\n")

        # Sync to Obsidian vault after CEO synthesis — non-fatal (vault may not be mounted)
        try:
            sync_to_obsidian(
                market_name,
                report_body,
                confidence=0.5 if has_fallback_data else 0.8,
                sources=db_stats.get("inserted", 0) + db_stats.get("updated", 0),
                is_estimated=has_fallback_data,
            )
        except Exception as obs_exc:
            logger.warning(f"[Obsidian] sync failed (non-fatal): {obs_exc}")

        # --- CEO memory write post-synthesis (T-256) ---
        if len(ceo_raw.strip()) >= 100:
            _extract_and_write_memories("ceo", market_name, ceo_raw)

        rl.finish(status="success", report_path=report_path)
        _log_event(run_id, market_name, "pipeline", "success", report_path=report_path)
        _write_stage_event_to_db(run_id, market_name, "pipeline_end", "success", stage=0)
        print(f"\n  Report saved -> {report_path}\n")
        _clear_excluded()
        logger.info("[Router] Daily counts: {}", get_router_status().get("excluded", "n/a"))
        return report_body

    except Exception as exc:
        error_msg = str(exc)
        rl.finish(status="failed", error=error_msg)
        _log_event(run_id, market_name, "pipeline", "failed", error=error_msg)
        _write_stage_event_to_db(
            run_id,
            market_name,
            "pipeline_end",
            "failed",
            stage=0,
            error=error_msg,
        )
        logger.error(f"[run:{run_id}] traceback:\n{traceback.format_exc()}")
        _clear_excluded()
        logger.info("[Router] Daily counts: {}", get_router_status().get("excluded", "n/a"))
        raise


# ── All-markets sweep ──────────────────────────────────────────────────────────


def run_all_markets(markets=None):
    markets = markets or [m.strip() for m in TARGET_MARKETS]

    print(f"\n{'=' * _WIDTH}")
    print("  RE_OS — Full Market Sweep (parallel)")
    print(f"  Markets : {', '.join(markets)}")
    print(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * _WIDTH}\n")

    procs = {}
    log_handles = {}

    for market in markets:
        market_slug = market.lower().replace(" ", "_")
        log_path = f"logs/{market_slug}.log"
        os.makedirs("logs", exist_ok=True)
        fh = open(log_path, "a")
        cmd = [sys.executable, __file__, "--market", market]
        p = subprocess.Popen(cmd, stdout=fh, stderr=fh,
                             env={**os.environ})
        procs[market] = p
        log_handles[market] = fh
        logger.info(f"Launched {market} PID {p.pid} -> {log_path}")
        print(f"  [>>] {market} started (PID {p.pid})")

    # Wait with 45-minute timeout per market
    TIMEOUT = 45 * 60
    deadline = _time.time() + TIMEOUT
    results = {}

    while procs:
        for market in list(procs):
            p = procs[market]
            ret = p.poll()
            if ret is not None:
                log_handles[market].close()
                results[market] = "success" if ret == 0 else f"failed({ret})"
                logger.info(f"{market} complete: {results[market]}")
                print(f"  [{'OK' if ret == 0 else '!!'}] {market}: {results[market]}")
                del procs[market]
        if procs and _time.time() > deadline:
            for market, p in procs.items():
                p.terminate()
                log_handles[market].close()
                results[market] = "timeout"
                logger.error(f"{market} killed after 45min timeout")
                print(f"  [!!] {market}: TIMEOUT — killed")
            break
        if procs:
            _time.sleep(5)

    print(f"\n{'=' * _WIDTH}")
    ok = sum(1 for r in results.values() if r == "success")
    bad = len(results) - ok
    print(f"  Summary: {ok} succeeded, {bad} failed/timeout")
    print(f"{'=' * _WIDTH}\n")
    return results


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RE_OS Market Intelligence Crew v2")
    parser.add_argument("--market", help="Run for specific market (e.g. Yelahanka)")
    parser.add_argument(
        "--report-only", metavar="MARKET", help="Report from existing DB, no scraping"
    )
    parser.add_argument(
        "--history", action="store_true", help="Show last 10 run entries"
    )
    args = parser.parse_args()

    os.makedirs("logs", exist_ok=True)
    logger.add("logs/crew.log", rotation="5 MB", retention=5, level="INFO")
    if args.market:
        market_slug = args.market.lower().replace(" ", "_")
        logger.add(f"logs/{market_slug}.log", rotation="5 MB", retention=5, level="INFO")

    if args.history:
        from config.run_logger import print_run_history

        print_run_history(last_n=10)

    elif args.report_only:
        from agents.analyst_agent import MarketSummaryTool, ReportGeneratorTool

        data = MarketSummaryTool()._run(args.report_only)
        report = ReportGeneratorTool()._run(data)
        print(report)

    elif args.market:
        result = run_market_intelligence(args.market)
        print(result)

    else:
        run_all_markets()
