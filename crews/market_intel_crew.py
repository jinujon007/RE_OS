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
import sys
import traceback
from datetime import datetime

from crewai import Crew, Task, Process
from loguru import logger
from litellm.exceptions import RateLimitError

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import (
    create_ceo_agent,
    create_scraper_agent,
    create_analyst_agent,
)
from config.settings import TARGET_MARKETS
from config.run_logger import RunLogger
from config.checkpointer import Checkpointer
from config.llm_router import _EXCLUDED
from utils.validator import validate_and_log
from utils.db_organizer import DBOrganizer

# ── Rate-limit retry: exclude failing providers on the fly ─────────────────────

_RATE_LIMIT_RETRIES = 3


def _detect_rate_limited_provider(exc: Exception) -> str | None:
    """Return the provider name if the error is a rate limit from a known provider,
    or None otherwise."""
    # LiteLLM sets llm_provider on its exception objects — check that first
    provider_attr = getattr(exc, "llm_provider", None)
    if provider_attr:
        p = provider_attr.lower()
        for name in ("cerebras", "groq", "nvidia", "openrouter"):
            if name in p:
                return name
        if "gemini" in p or "google" in p:
            return "gemini"

    msg = str(exc).lower()
    if "cerebras" in msg or "token_quota_exceeded" in msg or "tokens per day" in msg:
        return "cerebras"
    if "groq" in msg:
        return "groq"
    if "gemini" in msg or "google" in msg or "aistudio" in msg:
        return "gemini"
    if "nvidia" in msg:
        return "nvidia"
    if ("404" in msg or "page not found" in msg) and "nvidia" not in _EXCLUDED:
        return "nvidia"
    if "openrouter" in msg:
        return "openrouter"
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
        for provider in ("cerebras", "groq", "gemini", "nvidia", "openrouter"):
            if provider not in _EXCLUDED:
                return provider
    return None


# ── Stage banner ───────────────────────────────────────────────────────────────

_WIDTH = 65


def _banner(stage: str, description: str):
    print(f"\n{'─'*_WIDTH}")
    print(f"  RE_OS {stage}  |  {description}")
    print(f"{'─'*_WIDTH}")


def _header(market_name: str, run_id: str):
    print(f"\n{'='*_WIDTH}")
    print("  RE_OS — Market Intelligence Run  (v2)")
    print(f"  Market  : {market_name}")
    print(f"  Run ID  : {run_id}")
    print(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*_WIDTH}")
    print("  PIPELINE: Scrape → (Python) Validate+DB → Analyse → CEO")
    print("  LLMs    : Cerebras 8b (scraper) | Groq Scout (Analyst+CEO)")
    print(f"{'='*_WIDTH}\n")


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
        context=[scrape_rera_detail],
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
        context=[scrape_listings],
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
        context=[scrape_portal],
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
        context=[scrape_developer],
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
        context=[scrape_news],
    )

    return Crew(
        agents=[scraper],
        tasks=[
            scrape_rera, scrape_rera_detail, scrape_listings,
            scrape_portal, scrape_developer, scrape_news, scrape_kaveri,
        ],
        process=Process.sequential,
        verbose=True,
    )


# ── Stage 3: Intel Crew ────────────────────────────────────────────────────────


def _build_intel_crew(market_name: str, db_stats: dict) -> Crew:
    analyst = create_analyst_agent()
    ceo = create_ceo_agent()
    # CEO synthesizes in the intel crew — no re-delegation back to analyst
    ceo.allow_delegation = False

    analyze = Task(
        description=(
            f"Generate a market intelligence brief for {market_name}.\n"
            f"This run wrote {db_stats.get('inserted', 0)} new + "
            f"{db_stats.get('updated', 0)} updated RERA records to the DB.\n\n"
            f"STRICT TOOL CALL SEQUENCE — call each tool EXACTLY ONCE, in order:\n"
            f"  Step 1: market_summary_query with input: {market_name}\n"
            f"  Step 2: competitor_analysis with input: {market_name}\n"
            f"  Step 3: generate_market_report with input: the exact JSON from Step 1\n"
            f"  Step 4: Write Final Answer.\n\n"
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
            f"- Data quality note: state if data is LIVE or FALLBACK SAMPLE"
        ),
        expected_output=(
            "Formatted market brief with: inventory overview, top 5 projects, developer scorecard, "
            "risk flags, 5-signal analyst read (absorption, supply pressure, GV gap, "
            "dominant dev, LLS entry point), data quality note."
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
    max_retries: int = _RATE_LIMIT_RETRIES,
):
    """Kickoff a crew, retrying with excluded providers if a rate limit is hit.
    build_fn is called to rebuild the crew with fallback LLMs after excluding a provider.
    """
    last_error = None
    for attempt in range(1, max_retries + 2):  # first attempt + retries
        try:
            return crew.kickoff()
        except RateLimitError as exc:
            provider = _detect_rate_limited_provider(exc)
            if provider and attempt <= max_retries:
                _EXCLUDED.add(provider)
                logger.warning(
                    f"[Retry] {stage_name}: {provider} rate-limited, excluding and retrying (attempt {attempt}/{max_retries})"
                )
                print(
                    f"\n  [Retry] {provider} quota exhausted → rebuilding crew with fallback LLM..."
                )
                crew = (
                    build_fn()
                )  # rebuild crew so it picks up the new LLM from get_*_llm()
                last_error = exc
            else:
                raise
        except Exception as exc:
            provider = _detect_rate_limited_provider(exc)
            if provider and attempt <= max_retries:
                _EXCLUDED.add(provider)
                logger.warning(
                    f"[Retry] {stage_name}: possible {provider} limit, excluding and retrying (attempt {attempt}/{max_retries})"
                )
                crew = build_fn()
                last_error = exc
            else:
                raise
    raise last_error or RuntimeError(f"{stage_name} failed after {max_retries} retries")


# ── Main run function ──────────────────────────────────────────────────────────


def run_market_intelligence(market_name: str) -> str:
    rl = RunLogger(market=market_name)
    rl.start()
    cp = Checkpointer()

    _header(market_name, rl.run_id)

    try:
        # ── STAGE 1: Data collection ───────────────────────────────────────────
        _banner("STAGE 1/3", "Scraping RERA Karnataka + listings ...")

        # Skip Stage 1 only when ALL scout checkpoints exist from today's run.
        # RERA-only cache skip caused portal/developer/news scouts to never run,
        # leaving listings table at 0 on all subsequent same-day runs.
        scouts_all_cached = (
            cp.exists(market_name, "rera_scraped")
            and cp.exists(market_name, "portal_scout")
            and cp.exists(market_name, "developer_scout")
            and cp.exists(market_name, "news_scout")
        )
        if scouts_all_cached:
            logger.info(
                "[Crew] All scout checkpoints found — using today's cached data, skipping Stage 1"
            )
            print(
                "  [Cache] All scouts cached. Delete outputs/{market}/checkpoints/ to force re-scrape."
            )
            rl.agent_done("scrape_rera")
            rl.agent_done("scrape_listings")
        else:
            data_crew = _build_data_crew(market_name)
            _kickoff_with_fallback(
                data_crew, lambda: _build_data_crew(market_name), "Stage 1 (scrape)"
            )
            rl.agent_done("scrape_rera")
            rl.agent_done("scrape_listings")

        print("  Stage 1 complete.")

        # ── STAGE 2: Pure Python validate + upsert ────────────────────────────
        _banner("STAGE 2/3", "Validating + writing to PostgreSQL (no LLM) ...")

        raw_projects = cp.load(market_name, "rera_scraped") or []
        valid, invalid, val_report = validate_and_log(raw_projects, market_name)

        print(
            f"\n  Validation: {val_report['valid']} valid / "
            f"{val_report['invalid']} rejected / "
            f"{val_report['total']} total  "
            f"({val_report['pass_rate_pct']}% pass rate)"
        )
        if invalid:
            print(
                f"  First rejection: {val_report['error_summary'][0] if val_report['error_summary'] else ''}"
            )

        organizer = DBOrganizer()
        db_stats = organizer.run(market_name, valid)
        cp.save(market_name, "db_stats", db_stats)
        rl.agent_done("organizer")

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
            print(
                f"\n  Kaveri DB: GV {kaveri_stats['gv_inserted']}+{kaveri_stats['gv_updated']}, "
                f"Reg {kaveri_stats['reg_inserted']} inserted "
                f"({kaveri_stats['duration_seconds']}s)"
            )
        else:
            kaveri_stats = {}
            logger.info(
                "[Crew] No Kaveri checkpoints found — skipping Kaveri DB upsert"
            )

        # Scout upserts (portal, developer, news)
        portal_findings = cp.load(market_name, "portal_scout") or []
        if portal_findings:
            portal_stats = organizer.run_portal_scout(market_name, portal_findings)
            print(f"\n  Portal Scout DB: {portal_stats.get('upserted', 0)} listings upserted")
        else:
            logger.info("[Crew] No portal_scout checkpoint — skipping")

        dev_findings = cp.load(market_name, "developer_scout") or []
        if dev_findings:
            dev_stats = organizer.run_developer_scout(market_name, dev_findings)
            print(f"  Developer Scout DB: {dev_stats.get('upserted', 0)} projects upserted")
        else:
            logger.info("[Crew] No developer_scout checkpoint — skipping")

        news_findings = cp.load(market_name, "news_scout") or []
        if news_findings:
            organizer.run_news_scout(market_name, news_findings)
        else:
            logger.info("[Crew] No news_scout checkpoint — skipping")

        rera_detail_findings = cp.load(market_name, "rera_detail_scout") or []
        if rera_detail_findings:
            detail_stats = organizer.run_rera_detail_scout(market_name, rera_detail_findings)
            print(
                f"  RERA Detail Scout: {detail_stats['updated']} updated, "
                f"{detail_stats['inserted']} inserted"
            )
        else:
            logger.info("[Crew] No rera_detail_scout checkpoint — skipping")

        # ── STAGE 3: Intelligence ──────────────────────────────────────────────
        _banner("STAGE 3/3", "Generating market intelligence (Analyst + CEO) ...")

        # Reset provider exclusions — Stage 1 may have excluded Gemini Gemma (LIGHT tier,
        # 15k TPM) which would incorrectly block Gemini Flash (ANALYSIS/HEAVY tier, 250k TPM).
        # Both share the "gemini" exclusion key despite being different models and quotas.
        _EXCLUDED.clear()
        intel_crew = _build_intel_crew(market_name, db_stats)
        result = _kickoff_with_fallback(
            intel_crew,
            lambda: _build_intel_crew(market_name, db_stats),
            "Stage 3 (intel)",
        )
        rl.agent_done("analyst")
        rl.agent_done("ceo")

        # Extract outputs — prefer CEO synthesis; fall back to analyst if CEO returned placeholder
        _PLACEHOLDER = "the final answer to the original input question"
        ceo_raw = ""
        analyst_raw = ""
        if hasattr(result, "tasks_output") and result.tasks_output:
            if len(result.tasks_output) >= 2:
                analyst_raw = result.tasks_output[0].raw or ""
                ceo_raw = result.tasks_output[1].raw or ""
            elif len(result.tasks_output) == 1:
                analyst_raw = result.tasks_output[0].raw or ""
        ceo_raw = ceo_raw or (result.raw if hasattr(result, "raw") else str(result))

        if _PLACEHOLDER in ceo_raw.lower() or len(ceo_raw.strip()) < 50:
            logger.warning("[CEO] Placeholder detected — using analyst output as report body")
            report_body = analyst_raw or str(result)
            ceo_section = "[CEO synthesis unavailable — see analyst report above]"
        else:
            report_body = ceo_raw
            ceo_section = ""

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

        rl.finish(status="success", report_path=report_path)
        print(f"\n  Report saved -> {report_path}\n")
        _EXCLUDED.clear()
        return report_body

    except Exception as exc:
        error_msg = str(exc)
        rl.finish(status="failed", error=error_msg)
        logger.error(f"Run failed for {market_name}: {error_msg}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        _EXCLUDED.clear()
        raise


# ── All-markets sweep ──────────────────────────────────────────────────────────


def run_all_markets():
    markets = [m.strip() for m in TARGET_MARKETS]
    results = {}

    print(f"\n{'='*_WIDTH}")
    print("  RE_OS — Full Market Sweep")
    print(f"  Markets : {', '.join(markets)}")
    print(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*_WIDTH}\n")

    for i, market in enumerate(markets, 1):
        print(f"\n  [{i}/{len(markets)}] Starting: {market}")
        try:
            result = run_market_intelligence(market)
            results[market] = {"status": "success", "summary": result[:300]}
        except Exception as exc:
            results[market] = {"status": "failed", "error": str(exc)}
            logger.error(f"  !! {market} failed: {exc}")

    print(f"\n{'='*_WIDTH}")
    print("  RE_OS — ALL MARKETS COMPLETE")
    print(f"{'='*_WIDTH}")
    ok = sum(1 for r in results.values() if r["status"] == "success")
    bad = sum(1 for r in results.values() if r["status"] == "failed")
    for market, r in results.items():
        icon = "OK" if r["status"] == "success" else "!!"
        print(f"  [{icon}]  {market}: {r['status']}")
    print(f"\n  Summary: {ok} succeeded, {bad} failed")
    print("  Run history -> logs/runs_summary.md")
    print(f"{'='*_WIDTH}\n")

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
    logger.add("logs/crew.log", rotation="50 MB", level="INFO")

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
