"""
RE_OS — Scheduler
──────────────────
Runs the agent crew on schedule. Runs inside Docker as a separate service.

Schedule:
- RERA Yelahanka: daily at 2:30 AM IST
- RERA Devanahalli: daily at 3:00 AM IST
- RERA Hebbal: daily at 3:30 AM IST
- Listings scan: every 6 hours
- Market snapshot generation: daily at 6:00 AM IST (before Jinu's morning)
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
import os
import sys

from config.settings import TARGET_MARKETS
from sqlalchemy import text
from utils.db import get_engine
from utils.scheduler_helpers import safe_job as _safe_job


def _send_rera_alert(market: str, job_start) -> None:
    """Query new RERA projects since job_start and send Discord alert."""
    try:
        from utils.discord_notifier import send_rera_alert
        with get_engine().connect() as conn:
            rows = conn.execute(text("""
                SELECT rp.project_name, d.name AS developer_name
                FROM rera_projects rp
                LEFT JOIN developers d ON d.id = rp.developer_id
                LEFT JOIN micro_markets mm ON mm.id = rp.micro_market_id
                WHERE mm.name ILIKE :market
                  AND rp.created_at >= :job_start
                ORDER BY rp.created_at DESC
                LIMIT 20
            """), {"market": f"%{market}%", "job_start": job_start}).fetchall()
        if rows:
            developers = list({r[1] for r in rows if r[1]})
            send_rera_alert(market, len(rows), developers)
    except Exception as e:
        logger.warning(f"  RERA alert failed for {market}: {e}")


def run_single_market_rera(market: str):
    """Independent RERA data pull for a single market."""
    from config.llm_router import _clear_excluded
    from datetime import datetime, timezone
    import subprocess

    _clear_excluded()
    job_start = datetime.now(timezone.utc)
    logger.info(f"Scheduler: Starting RERA refresh for {market}")

    cmd = [sys.executable, "scrapers/rera_karnataka.py", "--market", market]
    slug = market.lower().replace(" ", "_")
    log_path = os.path.join("logs", f"{slug}.log")
    os.makedirs("logs", exist_ok=True)

    # Phase 1: Spawn
    try:
        log_fh = open(log_path, "a")
        proc = subprocess.Popen(cmd, env=os.environ, stdout=log_fh, stderr=log_fh)
        log_fh.close()
        logger.info(f"  Spawned RERA process for {market} (PID {proc.pid}) → {log_path}")
    except Exception as e:
        logger.error(f"  Failed to spawn RERA process for {market}: {e}")
        return

    # Phase 2: Wait with timeout
    try:
        proc.wait(timeout=1800)
    except subprocess.TimeoutExpired:
        proc.kill()
        logger.warning(f"  RERA process for {market} timed out after 1800s — killed")
        return

    # Phase 3: Check exit code
    if proc.returncode != 0:
        logger.warning(f"  RERA process for {market} exited with code {proc.returncode} — skipping alert")
        return

    # Phase 4: Alert on new projects
    _send_rera_alert(market, job_start)


def run_listings_scan():
    """Listings scan — 6-hourly."""
    from scrapers.listings_scraper import ListingsScraper
    from config.checkpointer import Checkpointer

    logger.info("Scheduler: Starting listings scan")
    scraper = ListingsScraper()
    cp = Checkpointer()

    total = 0
    failures = 0

    for market in [m.strip() for m in TARGET_MARKETS]:
        try:
            listings = scraper.scrape_market(market)
            cp.save(market, "listings_scraped", listings)
            count = len(listings or [])
            total += count
            logger.info(f"  Listings scan: {market} -> {count} listings")
        except Exception as e:
            failures += 1
            logger.error(f"  Listings scan failed for {market}: {e}")

    logger.info(
        f"Scheduler: Listings scan complete — total={total}, failures={failures}"
    )


def run_memory_decay():
    """Weekly memory decay — reduce confidence of stale facts, delete below 0.3 (T-298)."""
    from utils.agent_memory import decay_memories
    n = decay_memories(days=30, decay_amount=0.1)
    logger.info(f"[Scheduler] Memory decay: {n} rows deleted")


def run_intel_embedding_index():
    """
    Nightly: index any new intel reports into ChromaDB via nomic-embed-text (Ollama).
    Fires at 4:30 AM IST — after RERA runs (2:30-3:30 AM) and snapshots (6 AM).
    Gracefully no-ops if Ollama is unavailable.
    """
    try:
        from utils.embedder import IntelEmbedder
        embedder = IntelEmbedder()
        stats = embedder.index_intel_reports(outputs_dir="/app/outputs")
        logger.info(
            f"[Scheduler] Intel embedding: indexed={stats['indexed']} "
            f"skipped={stats['skipped']} failed={stats['failed']}"
        )
    except Exception as exc:
        logger.warning(f"[Scheduler] Intel embedding index failed (non-fatal): {exc}")


def _score_one_article(row) -> tuple[str, float | None, str | None]:
    """Score a single article via FinBERT. Returns (article_id, score, label)."""
    from utils.sentiment import score_headline, label_from_score
    article_id, title, key_insight = row
    text_to_score = title or ""
    if key_insight:
        text_to_score = f"{title}. {key_insight}" if title else key_insight
    text_to_score = text_to_score.strip()
    if not text_to_score:
        return (article_id, None, None)
    score = score_headline(text_to_score)
    label = label_from_score(score) if score is not None else None
    return (article_id, score, label)


def run_news_sentiment_scoring():
    """
    Nightly: score any unscored news_articles via FinBERT (HF Inference API).
    Fires at 5:00 AM IST. Non-fatal — sentiment is enrichment, not pipeline-critical.
    Scores articles where sentiment_score IS NULL (new articles from overnight scrapes).
    Uses ThreadPoolExecutor for parallel HF API calls to stay within misfire_grace_time.
    """
    from config.settings import HF_API_KEY
    if not HF_API_KEY:
        logger.debug("[Scheduler] HF_API_KEY not set — skipping sentiment scoring")
        return
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        from concurrent.futures import ThreadPoolExecutor, as_completed

        engine = get_engine()
        written = 0
        failed = 0
        BATCH_LIMIT = 1000
        PAGE_SIZE = 200
        offset = 0

        # Paginate to handle more than 200 articles
        while offset < BATCH_LIMIT:
            with engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT id, title, key_insight
                    FROM news_articles
                    WHERE sentiment_score IS NULL
                      AND title IS NOT NULL
                      AND title != ''
                    ORDER BY created_at DESC
                    LIMIT :lim OFFSET :off
                """), {"lim": PAGE_SIZE, "off": offset}).fetchall()

            if not rows:
                break

            scored_results: list[tuple[str, float, str]] = []
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(_score_one_article, row): row for row in rows}
                for future in as_completed(futures):
                    article_id, score, label = future.result()
                    if score is not None:
                        scored_results.append((article_id, score, label))
                    else:
                        failed += 1

            # Batch DB writes — short transactions every 25 rows
            for i in range(0, len(scored_results), 25):
                batch = scored_results[i:i + 25]
                with engine.begin() as conn:
                    for article_id, score, label in batch:
                        conn.execute(
                            text("UPDATE news_articles SET sentiment_score = :s, sentiment_label = :l WHERE id = :id"),
                            {"s": score, "l": label, "id": article_id},
                        )
                        written += 1

            offset += PAGE_SIZE

        logger.info(
            f"[Scheduler] Sentiment scoring: {written} scored, {failed} failed"
        )
    except Exception as exc:
        logger.warning(f"[Scheduler] Sentiment scoring failed (non-fatal): {exc}")


def run_yelahanka_refresh():
    """
    REMOVED — Yelahanka runs as its own independent job (rera_yelahanka at 2:30 AM IST).
    This function is kept as a no-op stub so any existing cron references don't crash.
    """
    logger.info(
        "Scheduler: run_yelahanka_refresh is a no-op — "
        "Yelahanka handled by independent cron job rera_yelahanka at 2:30 AM IST"
    )


def run_market_snapshot():
    """Generate market snapshots for all active markets."""
    logger.info("Scheduler: Generating market snapshots")

    engine = get_engine()
    for market in TARGET_MARKETS:
        market = market.strip()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                    INSERT INTO market_snapshots (
                        micro_market_id, snapshot_date, period,
                        total_rera_projects, active_rera_projects,
                        total_rera_units, sold_rera_units, unsold_rera_units,
                        avg_absorption_pct, avg_psf_sale
                    )
                    SELECT
                        m.id,
                        CURRENT_DATE,
                        'daily',
                        COUNT(DISTINCT r.id),
                        COUNT(DISTINCT CASE WHEN r.is_active THEN r.id END),
                        SUM(r.total_units),
                        SUM(r.sold_units),
                        SUM(r.unsold_units),
                        ROUND(AVG(r.absorption_pct), 2),
                        ROUND((
                            SELECT AVG(l.price_psf)
                            FROM listings l
                            WHERE l.micro_market_id = m.id
                              AND l.price_psf IS NOT NULL
                              AND l.price_psf > 1000
                              AND l.price_psf < 50000
                        ), 0)
                    FROM micro_markets m
                    LEFT JOIN rera_projects r ON r.micro_market_id = m.id
                    WHERE m.name ILIKE :market
                    GROUP BY m.id
                    ON CONFLICT (micro_market_id, snapshot_date, period) DO UPDATE SET
                        total_rera_projects = EXCLUDED.total_rera_projects,
                        active_rera_projects = EXCLUDED.active_rera_projects,
                        total_rera_units = EXCLUDED.total_rera_units,
                        sold_rera_units = EXCLUDED.sold_rera_units,
                        unsold_rera_units = EXCLUDED.unsold_rera_units,
                        avg_absorption_pct = EXCLUDED.avg_absorption_pct,
                        avg_psf_sale = EXCLUDED.avg_psf_sale
                    """),
                    {"market": f"%{market}%"},
                )
        except Exception as e:
            logger.error(f"  Snapshot failed for {market}: {e}")


def run_bertscore_evaluation():
    """Weekly BERTScore evaluation — Monday 04:00 IST.
    Compares latest intel reports against reference corpus.
    Sends Discord SYSTEM alert if score drops below threshold."""
    try:
        import evaluate  # pre-check: fail fast if missing, before 120s thread pool timeout
        from utils.report_evaluator import ReportEvaluator
        result = ReportEvaluator().evaluate_latest()
        score = result.get("score")
        delta = result.get("delta")
        if result.get("alert") and score is not None:
            try:
                from utils.discord_notifier import send
                msg = (f"BERTScore F1={score:.4f} "
                       f"(delta={delta:+.4f}) — quality regression detected. "
                       f"Candidates: {result['candidates']}, Refs: {result['references']}")
                send("system", "⚠ BERTScore Regression", msg)
            except Exception as exc:
                logger.warning(f"[Scheduler] BERTScore alert failed: {exc}")
        if score is not None:
            logger.info(f"[Scheduler] BERTScore eval done — score={score:.4f} "
                         f"delta={delta:+.4f} alert={result.get('alert', False)}")
        else:
            logger.info(f"[Scheduler] BERTScore eval {result.get('status', '?')} — "
                         f"{result.get('candidates', 0)} candidates, {result.get('references', 0)} refs")
    except Exception as exc:
        logger.warning(f"[Scheduler] BERTScore evaluation failed (non-fatal): {exc}")


def recover_stuck_board_sessions():
    """Set board sessions stuck at 'active' for >30 minutes to 'failed'."""

    try:
        engine = get_engine()
        with engine.begin() as conn:
            result = conn.execute(
                text("""
                UPDATE board_sessions
                SET status = 'failed',
                    completed_at = NOW()
                WHERE status = 'active'
                  AND created_at < NOW() - INTERVAL '30 minutes'
                """)
            )
            rowcount = result.rowcount
        logger.info(f"[Scheduler] Recovered {rowcount} stuck board sessions")
    except Exception as e:
        logger.warning(f"[Scheduler] Failed to recover stuck board sessions: {e}")


def run_distressed_developer_scan():
    """Scan for distressed developers and alert via Discord if score > 0.6."""
    try:
        from utils.distressed_developer import (
            scan_distressed_developers,
            format_distress_alert,
            _DISTRESS_SCORE_THRESHOLD,
        )
        from utils.discord_notifier import send

        for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
            results = scan_distressed_developers(
                market, min_score=_DISTRESS_SCORE_THRESHOLD,
            )
            for dev in results:
                alert = format_distress_alert(dev)
                logger.info(f"[DistressedDev] Alert: {alert}")
                try:
                    send("bd_opportunities", "Distressed Developer Alert", alert)
                except Exception as exc:
                    logger.warning(f"[DistressedDev] Discord send failed: {exc}")
    except Exception as exc:
        logger.warning(f"[Scheduler] Distressed developer scan failed: {exc}")


def run_igr_transaction_scrape():
    """Weekly IGR transaction scrape for all markets — Sunday 05:30 IST."""
    from scrapers.igr_karnataka import IGRTransactionScout
    for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
        try:
            scout = IGRTransactionScout()
            transactions = scout.run(market=market, days_back=30)
            if transactions:
                stats = scout.insert_transactions(transactions, market=market)
                logger.info(
                    f"[IGRScout] {market}: {stats['inserted']} inserted, "
                    f"{stats['skipped']} skipped, {stats['failed']} failed"
                )
            else:
                logger.info(f"[IGRScout] {market}: 0 transactions found")
        except Exception as exc:
            logger.warning(f"[Scheduler] IGR scrape failed for {market}: {exc}")


def run_kaveri_scrape():
    """Weekly Kaveri guidance value scrape for all markets — Sunday 05:00 IST."""
    from scrapers.kaveri_karnataka import KaveriScraper
    for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
        try:
            scraper = KaveriScraper()
            gv = scraper.scrape_guidance_values(market)
            logger.info(f"[KaveriScraper] {market}: {len(gv)} guidance value records")
        except Exception as exc:
            logger.warning(f"[Scheduler] Kaveri scrape failed for {market}: {exc}")


if __name__ == "__main__":
    logger.add("logs/scheduler.log", rotation="50 MB")
    os.makedirs("logs", exist_ok=True)

    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    # Independent RERA cron jobs — one per market, staggered 30 min apart
    scheduler.add_job(
        lambda: _safe_job(lambda: run_single_market_rera("Yelahanka"), "rera_yelahanka"),
        CronTrigger(hour=2, minute=30),
        id="rera_yelahanka",
        name="RERA refresh — Yelahanka",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        lambda: _safe_job(lambda: run_single_market_rera("Devanahalli"), "rera_devanahalli"),
        CronTrigger(hour=3, minute=0),
        id="rera_devanahalli",
        name="RERA refresh — Devanahalli",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        lambda: _safe_job(lambda: run_single_market_rera("Hebbal"), "rera_hebbal"),
        CronTrigger(hour=3, minute=30),
        id="rera_hebbal",
        name="RERA refresh — Hebbal",
        misfire_grace_time=3600,
    )

    # Market snapshots at 6 AM IST (ready for morning)
    scheduler.add_job(
        lambda: _safe_job(run_market_snapshot, "market_snapshot"),
        CronTrigger(hour=6, minute=0),
        id="market_snapshot",
        name="Daily Market Snapshot",
        misfire_grace_time=3600,
    )

    # Listings scan every 6 hours
    scheduler.add_job(
        lambda: _safe_job(run_listings_scan, "listings_scan"),
        CronTrigger(hour="*/6"),
        id="listings_scan",
        name="6-Hourly Listings Scan",
    )

    # Weekly memory decay — Monday 03:00 UTC (T-298)
    scheduler.add_job(
        lambda: _safe_job(run_memory_decay, "memory_decay"),
        CronTrigger(day_of_week="mon", hour=3, minute=0, timezone="UTC"),
        id="memory_decay",
        name="Weekly Agent Memory Decay",
        misfire_grace_time=3600,
    )

    # Stuck board session recovery — every hour (T-315)
    scheduler.add_job(
        lambda: _safe_job(recover_stuck_board_sessions, "recover_board_sessions"),
        "interval", hours=1,
        id="recover_board_sessions",
        name="Recover Stuck Board Sessions",
        replace_existing=True,
    )

    # Nightly intel embedding index — 4:30 AM IST (after RERA runs, before snapshots)
    scheduler.add_job(
        lambda: _safe_job(run_intel_embedding_index, "intel_embedding"),
        CronTrigger(hour=4, minute=30),
        id="intel_embedding",
        name="Nightly Intel Embedding Index (ChromaDB)",
        misfire_grace_time=3600,
    )

    # Nightly news sentiment scoring — 5:00 AM IST (FinBERT via HF Inference API)
    scheduler.add_job(
        lambda: _safe_job(run_news_sentiment_scoring, "news_sentiment"),
        CronTrigger(hour=5, minute=0),
        id="news_sentiment",
        name="Nightly News Sentiment Scoring (FinBERT)",
        misfire_grace_time=3600,
    )

    # Weekly BERTScore evaluation — Monday 04:00 IST (Sun 22:30 UTC)
    scheduler.add_job(
        lambda: _safe_job(run_bertscore_evaluation, "bertscore_eval"),
        CronTrigger(day_of_week="mon", hour=4, minute=0, timezone="Asia/Kolkata"),
        id="bertscore_eval",
        name="Weekly BERTScore Quality Evaluation",
        misfire_grace_time=7200,
    )

    # Weekly Kaveri guidance value scrape — Sunday 05:00 IST
    scheduler.add_job(
        lambda: _safe_job(run_kaveri_scrape, "kaveri_scrape"),
        CronTrigger(day_of_week="sun", hour=5, minute=0, timezone="Asia/Kolkata"),
        id="kaveri_scrape",
        name="Weekly Kaveri Guidance Value Scrape",
        misfire_grace_time=3600,
    )

    # Weekly IGR transaction scrape — Sunday 05:30 IST (after Kaveri)
    scheduler.add_job(
        lambda: _safe_job(run_igr_transaction_scrape, "igr_scrape"),
        CronTrigger(day_of_week="sun", hour=5, minute=30, timezone="Asia/Kolkata"),
        id="igr_scrape",
        name="Weekly IGR Transaction Scrape",
        misfire_grace_time=3600,
    )

    # Daily distressed developer scan — 06:15 IST (after market snapshot at 06:00)
    scheduler.add_job(
        lambda: _safe_job(run_distressed_developer_scan, "distressed_dev_scan"),
        CronTrigger(hour=6, minute=15),
        id="distressed_dev_scan",
        name="Daily Distressed Developer Scan (JD/JV targets)",
        misfire_grace_time=3600,
    )

    logger.info("RE_OS Scheduler started")
    logger.info("Jobs scheduled:")
    logger.info("  2:30 AM IST — RERA Yelahanka")
    logger.info("  3:00 AM IST — RERA Devanahalli")
    logger.info("  3:30 AM IST — RERA Hebbal")
    logger.info("  4:30 AM IST — Intel embedding index (ChromaDB)")
    logger.info("  5:00 AM IST — News sentiment scoring (FinBERT)")
    logger.info("  6:00 AM IST — Market snapshots")
    logger.info("  6:15 AM IST — Distressed developer scan (JD/JV targets)")
    logger.info("  Every 6 hrs — Listings scan")
    logger.info("  Every 1 hr  — Board session recovery (T-315)")
    logger.info("  Monday 03:00 UTC — Agent memory decay")
    logger.info("  Monday 04:00 IST — BERTScore quality evaluation")
    logger.info(f"Active jobs: {[j.id for j in scheduler.get_jobs()]}")

    scheduler.start()
