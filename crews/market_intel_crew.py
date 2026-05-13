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
from config.settings import TARGET_MARKETS, CEREBRAS_API_KEY
from config.run_logger import RunLogger
from config.checkpointer import Checkpointer
from config.llm_router import _EXCLUDED
from utils.validator import validate_and_log
from utils.db_organizer import DBOrganizer

# ── Rate-limit retry: exclude failing providers on the fly ─────────────────────

_RATE_LIMIT_RETRIES = 2


def _detect_rate_limited_provider(exc: Exception) -> str | None:
    """Return the provider name if the error is a rate limit from a known provider,
    or None otherwise."""
    msg = str(exc).lower()
    if "cerebras" in msg or "token_quota_exceeded" in msg:
        return "cerebras"
    if "groq" in msg:
        return "groq"
    if "gemini" in msg or "google" in msg or "aistudio" in msg:
        return "gemini"
    if "nvidia" in msg:
        return "nvidia"
    if "openrouter" in msg:
        return "openrouter"
    return None


# ── Stage banner ───────────────────────────────────────────────────────────────

_WIDTH = 65


def _banner(stage: str, description: str):
    print(f"\n{'─'*_WIDTH}")
    print(f"  RE_OS {stage}  |  {description}")
    print(f"{'─'*_WIDTH}")


def _header(market_name: str, run_id: str):
    print(f"\n{'='*_WIDTH}")
    print(f"  RE_OS — Market Intelligence Run  (v2)")
    print(f"  Market  : {market_name}")
    print(f"  Run ID  : {run_id}")
    print(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*_WIDTH}")
    print(f"  PIPELINE: Scrape → (Python) Validate+DB → Analyse → CEO")
    print(f"  LLMs    : Cerebras 70B (scraper) | Groq Scout (Analyst+CEO)")
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

    scrape_listings = Task(
        description=(
            f"Scrape current property listings for: {market_name}. "
            f"Call the listings_scraper tool with input '{market_name}'. "
            f"Return a brief summary of how many listings found."
        ),
        expected_output=(f"One line: 'Found N listings for {market_name}.'"),
        agent=scraper,
        context=[scrape_rera],
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
        context=[scrape_listings],
    )

    return Crew(
        agents=[scraper],
        tasks=[scrape_rera, scrape_listings, scrape_kaveri],
        process=Process.sequential,
        verbose=True,
    )


# ── Stage 3: Intel Crew ────────────────────────────────────────────────────────


def _build_intel_crew(market_name: str, db_stats: dict) -> Crew:
    analyst = create_analyst_agent()
    ceo = create_ceo_agent()

    analyze = Task(
        description=(
            f"Generate a complete market intelligence brief for: {market_name}. "
            f"This run wrote {db_stats.get('inserted', 0)} new + "
            f"{db_stats.get('updated', 0)} updated RERA records to the DB. "
            f"Steps: "
            f"1. Call market_summary_query('{market_name}') — inventory stats from DB. "
            f"2. Call competitor_analysis('{market_name}') — developer breakdown. "
            f"3. Call generate_market_report with the summary data — formatted report. "
            f"4. Add your read: absorption rate signal, dominant developer, "
            f"   pricing white space where LLS could enter. "
            f"Be specific. Real numbers. No vague observations.\n\n"
            f"IMPORTANT FORMAT RULES for step 3 — generate_market_report:\n"
            f"The Action Input must be a single key 'market_data_json' whose value is the "
            f"COMPLETE JSON string returned by market_summary_query, with all quotes properly "
            f"escaped for JSON.\n"
            f"Correct example:\n"
            f"Action: generate_market_report\n"
            f'Action Input: {{"market_data_json": "{{\\"market\\": \\"{market_name}\\", \\"inventory\\": ...}}"}}\n'
            f"WRONG (do NOT do this):\n"
            f'Action Input: {{"market_data_json": "{{\\"market\\": \\"{market_name}\\"}}"}}\n'
            f"Make sure the JSON is valid — use the exact string returned by market_summary_query."
        ),
        expected_output=(
            "Complete intelligence report: inventory overview (projects/units/absorption/psf), "
            "top 5 projects, developer scorecard, risk flags, 3-sentence analyst read."
        ),
        agent=analyst,
    )

    ceo_synthesis = Task(
        description=(
            f"Review the market intelligence for {market_name}. "
            f"1. Flag any data anomalies. "
            f"2. Strategic read: what does this mean for LLS right now? "
            f"3. The single most important signal in this data. "
            f"4. One specific action for LLS. Direct. One action, not five."
        ),
        expected_output=(
            "Strategic brief: data check, CEO read (3-4 sentences), key signal, one action."
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

        if cp.exists(market_name, "rera_scraped"):
            logger.info(
                "[Crew] RERA checkpoint found — using today's cached data, skipping scrape"
            )
            print(
                "  [Cache] Using today's RERA checkpoint. Delete outputs/{market}/checkpoints/ to force re-scrape."
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

        print(f"  Stage 1 complete.")

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

        # ── STAGE 3: Intelligence ──────────────────────────────────────────────
        _banner("STAGE 3/3", "Generating market intelligence (Analyst + CEO) ...")

        intel_crew = _build_intel_crew(market_name, db_stats)
        result = intel_crew.kickoff()
        rl.agent_done("analyst")
        rl.agent_done("ceo")

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
            f.write(str(result))

        rl.finish(status="success", report_path=report_path)
        print(f"\n  Report saved -> {report_path}\n")

        return str(result)

    except Exception as exc:
        error_msg = str(exc)
        rl.finish(status="failed", error=error_msg)
        logger.error(f"Run failed for {market_name}: {error_msg}")
        raise


# ── All-markets sweep ──────────────────────────────────────────────────────────


def run_all_markets():
    markets = [m.strip() for m in TARGET_MARKETS]
    results = {}

    print(f"\n{'='*_WIDTH}")
    print(f"  RE_OS — Full Market Sweep")
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
    print(f"  Run history -> logs/runs_summary.md")
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
