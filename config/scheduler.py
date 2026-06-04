"""
RE_OS — Scheduler
──────────────────
Runs the agent crew on schedule. Runs inside Docker as a separate service.

Schedule (post-Sprint-66):
- 01:00 AM IST — Daily pg_dump backup (T-904)
- 02:00 AM IST — Unified Ingest Engine (all scrapers via DataPlugin adapters)
- 03:00 AM IST — Opportunity scoring (GATE-47 — survey scoring + Discord alert)
- 04:30 AM IST — Intel embedding index (ChromaDB via Ollama nomic-embed-text)
- 05:00 AM IST — News sentiment scoring (FinBERT via HF Inference API)
- 06:00 AM IST — Market snapshots (daily RERA + listing aggregates)
- 06:15 AM IST — Distressed developer scan (JD/JV targeting via Discord alert)
- 08:00 AM IST — LLS Compliance Calendar check (Discord #legal-flags if <30 days)
- Every 1 hr   — Stuck board session recovery
- Monday 03:00 UTC — Agent memory decay
- Monday 03:30 UTC — Memory conflict detection (Discord alert)
- Monday 03:45 IST — BERTScore quality evaluation
- Monday 04:00 IST — Weekly memory digest (top-5 facts per market → Discord)
- Sunday 07:00 IST — PSF Forecast (LGBM walk-forward validation)
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
    """DEPRECATED — superseded by IngestEngine (T-671). No longer registered as a scheduler job."""
    logger.warning("[Scheduler] run_listings_scan() called directly — use IngestEngine instead")
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
    """DEPRECATED — superseded by IngestEngine (T-671). No longer registered as a scheduler job."""
    logger.warning("[Scheduler] run_yelahanka_refresh() called directly — use IngestEngine instead")


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
    """DEPRECATED — superseded by IngestEngine (T-671). No longer registered as a scheduler job."""
    logger.warning("[Scheduler] run_igr_transaction_scrape() called directly — use IngestEngine instead")
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
    """DEPRECATED — superseded by IngestEngine (T-671). No longer registered as a scheduler job."""
    logger.warning("[Scheduler] run_kaveri_scrape() called directly — use IngestEngine instead")
    from scrapers.kaveri_karnataka import KaveriScraper
    for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
        try:
            scraper = KaveriScraper()
            gv = scraper.scrape_guidance_values(market)
            logger.info(f"[KaveriScraper] {market}: {len(gv)} guidance value records")
        except Exception as exc:
            logger.warning(f"[Scheduler] Kaveri scrape failed for {market}: {exc}")


def run_ingest_engine():
    """Combined ingest pipeline — runs at 02:00 IST by default.
    Replaces 6 separate cron jobs (3 RERA + listings + kaveri + IGR).
    Per-plugin schedule overrides in config.settings.PLUGIN_SCHEDULES.

    IMPORTANT: All schedule times in PLUGIN_SCHEDULES are in **IST** (UTC+5:30).
    This function converts current UTC to IST before comparing, so
    ``day_of_week`` and ``hour`` checks match Indian calendar days correctly.
    """
    from datetime import datetime, timezone, timedelta
    from ingest.engine import IngestEngine
    from ingest.plugins import (
        RERAPlugin, IGRPlugin, KaveriBhoomiPlugin,
        PortalPlugin, DeveloperPlugin, NewsPlugin,
        DistressedPlugin, BBMPPlugin,
    )
    from config.settings import PLUGIN_SCHEDULES, TARGET_MARKETS

    _IST_OFFSET = timedelta(hours=5, minutes=30)
    now_ist = datetime.now(timezone.utc) + _IST_OFFSET
    today_ist = now_ist.strftime("%a").lower()
    current_time_minutes = now_ist.hour * 60 + now_ist.minute

    def _plugin_should_run(plugin_id: str) -> bool:
        schedule = PLUGIN_SCHEDULES.get(plugin_id)
        if schedule is None:
            return True
        days_str = schedule.get("day_of_week", today_ist)
        days = [d.strip().lower()[:3] for d in days_str.split(",")]
        if today_ist not in days:
            return False
        sched_minutes = schedule.get("hour", 2) * 60 + schedule.get("minute", 0)
        return abs(current_time_minutes - sched_minutes) < 10

    engine = IngestEngine(max_workers=3, global_rate=3.0)
    all_plugins = [
        RERAPlugin(), IGRPlugin(), KaveriBhoomiPlugin(),
        PortalPlugin(), DeveloperPlugin(), NewsPlugin(),
        DistressedPlugin(), BBMPPlugin(),
    ]
    for p in all_plugins:
        if _plugin_should_run(p.plugin_id):
            engine.register(p)
            logger.info("[Scheduler] IngestEngine registered: {} (schedule active)", p.plugin_id)
        else:
            logger.info("[Scheduler] IngestEngine skipped: {} (not in schedule today)", p.plugin_id)

    if not engine.registered_plugins:
        logger.info("[Scheduler] IngestEngine: no plugins scheduled for today at this hour")
        return

    report = engine.run_all(markets=TARGET_MARKETS)
    logger.info("[Scheduler] IngestEngine complete: {}", report.summary())
    for s in report.failed_plugins:
        logger.warning("[Scheduler] Plugin failed: {}/{} — {}", s.plugin_id, s.market, s.error_message)


def run_conflict_detection():
    """Weekly memory conflict detection — Monday 03:30 UTC (after memory decay).
    Detects contradictory facts in agent_memories and alerts via Discord."""
    try:
        from utils.agent_memory import detect_conflicts
        from utils.discord_notifier import send
        
        for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
            conflicts = detect_conflicts(market)
            if conflicts:
                for conflict in conflicts:
                    alert_msg = (
                        f"CONFLICT {conflict['market']}/{conflict['fact_prefix'][:30]}: "
                        f"{conflict['agent_a']}:₹{conflict['value_a']:,.0f} vs "
                        f"{conflict['agent_b']}:₹{conflict['value_b']:,.0f} "
                        f"({conflict['pct_gap']:.0f}% gap) — verify source"
                    )
                    logger.info(f"[ConflictDetection] {alert_msg}")
                    try:
                        send("system", "Memory Conflict Detected", alert_msg)
                    except Exception as exc:
                        logger.warning(f"[ConflictDetection] Discord send failed: {exc}")
    except Exception as exc:
        logger.warning(f"[Scheduler] Conflict detection failed: {exc}")


def run_weekly_digest():
    """Weekly digest generation — Monday 04:00 IST (after conflict detection).
    Generates top-5 highest-confidence facts for each market and logs them.
    Sends Discord summary to intel channel. Fact text truncated to 200 chars."""
    try:
        from utils.agent_memory import generate_weekly_digest
        from utils.discord_notifier import send

        for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
            _MAX_FACT_LEN = 200
            facts = generate_weekly_digest(market, max_fact_length=_MAX_FACT_LEN)
            if facts:
                lines = [f"**{market} — Weekly Digest**"]
                for f in facts:
                    lines.append(
                        f"- [{f['agent_id']}] {f['fact']} "
                        f"(conf: {f['confidence']:.1%})"
                    )
                summary = "\n".join(lines)
                logger.info(f"[Scheduler] Weekly digest generated for {market}: {len(facts)} facts")
                try:
                    send("intel", f"📋 Weekly Digest — {market}", summary)
                except Exception as exc:
                    logger.warning(f"[Scheduler] Weekly digest Discord failed for {market}: {exc}")
            else:
                logger.info(f"[Scheduler] Weekly digest: no facts for {market}")
    except Exception as exc:
        logger.warning(f"[Scheduler] Weekly digest generation failed: {exc}")


def run_opportunity_scoring():
    """Daily opportunity scoring — 03:00 IST (after ingest completes at 02:00).
    Scores all active surveys via OpportunityEngine per market and sends Discord
    alerts per band: URGENT (≥0.80 individual), PRIORITY (>0.60 summary),
    WATCH (>0.40 summary). Logs elapsed time and empty-result diagnostics.
    """
    import time as _time
    from intelligence.opportunity_engine import OpportunityEngine
    from utils.discord_notifier import send
    from config.settings import TARGET_MARKETS

    markets = [m.strip() for m in TARGET_MARKETS]
    job_start = _time.time()

    try:
        engine = OpportunityEngine(caller="scheduler")
        results = engine.score_all(markets)
        elapsed = _time.time() - job_start

        if not results:
            logger.info(
                "[Scheduler] Opportunity scoring completed in {:.1f}s: 0 scored across {} — "
                "check DB for surveys (surveys table may be empty)", elapsed, markets
            )
            return

        logger.info(
            "[Scheduler] Opportunity scoring: {} scored across {} in {:.1f}s",
            len(results), markets, elapsed,
        )

        urgent = [r for r in results if r.score >= 0.80]
        for r in sorted(urgent, key=lambda x: x.score, reverse=True)[:10]:
            alert_msg = (
                f"**{r.survey_no}**\n"
                f"Score: **{r.score:.4f}** | IRR: {r.components.irr_score:.3f} "
                f"Legal: {r.components.legal_score:.3f} "
                f"Timing: {r.components.timing_score:.3f}\n"
                f"Action: {r.next_action}"
            )
            logger.info("[Scheduler] URGENT opportunity: {} score={:.4f}", r.survey_no, r.score)
            try:
                send("bd_opportunities", f"URGENT — {r.survey_no}", alert_msg)
            except Exception as exc:
                logger.warning("[Scheduler] URGENT alert Discord failed: {}", exc)

        priority = [r for r in results if 0.60 < r.score < 0.80]
        if priority:
            summary = "\n".join(
                f"{r.survey_no} — score={r.score:.4f} — {r.next_action[:40]}"
                for r in sorted(priority, key=lambda x: x.score, reverse=True)[:5]
            )
            try:
                send("bd_opportunities", "Priority Opportunities — Review", summary)
            except Exception as exc:
                logger.warning("[Scheduler] PRIORITY alert Discord failed: {}", exc)

        watch = [r for r in results if 0.40 < r.score <= 0.60]
        if watch:
            watch_summary = "\n".join(
                f"{r.survey_no} — score={r.score:.4f} — legal={r.legal_risk_level}"
                for r in sorted(watch, key=lambda x: x.score, reverse=True)[:3]
            )
            logger.info("[Scheduler] WATCH opportunities: {} — {}", len(watch), watch_summary[:200])

    except Exception as exc:
        elapsed = _time.time() - job_start
        logger.warning("[Scheduler] Opportunity scoring failed after {:.1f}s: {}", elapsed, exc)


def run_psf_forecast():
    """Weekly PSF forecast for all markets. Discord alert if MAPE >15%.
    Runs Sunday 07:00 IST."""
    from utils.psf_forecaster import PSFForecaster
    from utils.discord_notifier import send

    for market in TARGET_MARKETS:
        try:
            forecaster = PSFForecaster()
            result = forecaster.train(market)
            if result.error:
                logger.info("[Scheduler] PSF forecast skipped for %s: %s", market, result.error)
                continue

            logger.info("[Scheduler] PSF forecast for %s: direction=%s, next_3mo=%.0f, MAPE=%s",
                       market, result.direction, result.next_3mo_avg or 0,
                       f"{result.mape:.1f}%" if result.mape else "N/A")

            # Discord alert if MAPE > 15%
            if result.mape is not None and result.mape > 15.0:
                send("system", f"PSF Forecast Warning — {market}",
                     f"MAPE of {result.mape:.1f}% exceeds 15% threshold. "
                     f"Direction: {result.direction}. "
                     f"Next 3mo avg: ₹{result.next_3mo_avg:,.0f}")
        except Exception as exc:
            logger.warning("[Scheduler] PSF forecast failed for %s: %s", market, exc)


def run_compliance_check():
    """Daily LLS Compliance Calendar check — 08:00 IST (T-704).
    check_upcoming_deadlines() handles Discord internally; this wrapper logs outcome."""
    try:
        from utils.lls_compliance_calendar import check_upcoming_deadlines
        alerts = check_upcoming_deadlines()
        logger.info(
            "[ComplianceCalendar] Daily check done — {} deadline(s) within 30 days",
            len(alerts),
        )
    except Exception as exc:
        logger.warning("[Scheduler] Compliance check failed (non-fatal): {}", exc)


_backup_lock = False

def run_db_backup():
    """Daily pg_dump backup at 01:00 IST. 7-day retention.
    
    Uses PGPASSWORD env var for auth (never passes password on command line).
    Guarded by module-level lock to prevent concurrent backup runs.
    Logs to agent_runs table with status 'success' or 'failed'.
    """
    global _backup_lock
    if _backup_lock:
        logger.warning("[DB-Backup] Previous backup still running — skipping")
        return

    import gzip
    import shutil
    import subprocess as _subprocess
    from datetime import datetime, timedelta
    from urllib.parse import urlparse

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = "/app/backups"
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, f"re_os_{timestamp}.sql")
    gz_path = backup_path + ".gz"

    parsed = urlparse(os.environ["DATABASE_URL"])
    db_env = {**os.environ, "PGPASSWORD": parsed.password or ""}

    try:
        _backup_lock = True
        _subprocess.run(
            [
                "pg_dump",
                "--host", parsed.hostname or "localhost",
                "--port", str(parsed.port or 5432),
                "--username", parsed.username or "re_os_user",
                f"--dbname={parsed.path.lstrip('/')}",
                "--no-owner",
                "--no-acl",
                "--format", "custom",
                "--file", backup_path,
            ],
            check=True, capture_output=True, timeout=600, env=db_env,
        )
        with open(backup_path, "rb") as f_in:
            with gzip.open(gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.remove(backup_path)

        size_mb = os.path.getsize(gz_path) / (1024 * 1024)
        logger.info("[DB-Backup] Created {} ({:.1f} MB)", gz_path, size_mb)

        cutoff = datetime.now() - timedelta(days=7)
        removed = 0
        for fname in os.listdir(backup_dir):
            fpath = os.path.join(backup_dir, fname)
            if not fname.endswith(".sql.gz"):
                continue
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                os.remove(fpath)
                removed += 1
        if removed:
            logger.info("[DB-Backup] Cleaned {} old backups (>7 days)", removed)

        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_runs
                            (agent_name, micro_market, event_type, status, records_inserted, notes)
                        VALUES ('backup', 'system', 'db_backup', 'success', 0, :notes)
                    """),
                    {"notes": "pg_dump backup {} ({:.1f} MB)".format(timestamp, size_mb)},
                )
        except Exception as exc:
            logger.warning("[DB-Backup] Failed to log backup: {}", exc)

    except Exception as exc:
        logger.error("[DB-Backup] Failed: {}", exc)
        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_runs
                            (agent_name, micro_market, event_type, status, records_inserted, notes)
                        VALUES ('backup', 'system', 'db_backup', 'failed', 0, :notes)
                    """),
                    {"notes": "Backup failed: {}".format(exc)},
                )
        except Exception as log_exc:
            logger.warning("[DB-Backup] Failed to log failure: {}", log_exc)
    finally:
        _backup_lock = False


if __name__ == "__main__":
    logger.add("logs/scheduler.log", rotation="50 MB")
    os.makedirs("logs", exist_ok=True)

    # Startup guard: ensure output directories exist for every market
    # Prevents permission denied / checkpoint write failures at runtime
    for market in TARGET_MARKETS:
        slug = market.lower().replace(" ", "_")
        os.makedirs(os.path.join("outputs", slug, "checkpoints"), exist_ok=True)
        logger.info(f"Scheduler: ensured output dir for {market}")

    scheduler = BlockingScheduler(timezone="Asia/Kolkata")

    # Unified Ingest Engine — replaces 6 separate cron jobs
    # Per-plugin schedule overrides in config.settings.PLUGIN_SCHEDULES
    scheduler.add_job(
        lambda: _safe_job(run_ingest_engine, "ingest_engine"),
        CronTrigger(hour=2, minute=0),
        id="ingest_engine",
        name="Unified Ingest Engine (all plugins)",
        misfire_grace_time=3600,
    )

    # Daily opportunity scoring at 3 AM IST (after ingest engine at 2 AM)
    scheduler.add_job(
        lambda: _safe_job(run_opportunity_scoring, "opportunity_scoring"),
        CronTrigger(hour=3, minute=0),
        id="opportunity_scoring",
        name="Daily Opportunity Scoring (GATE-47)",
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

    # Weekly BERTScore evaluation — Monday 03:45 IST (Sun 22:15 UTC)
    # Runs before weekly digest (04:00 IST) to avoid time-slot conflict
    scheduler.add_job(
        lambda: _safe_job(run_bertscore_evaluation, "bertscore_eval"),
        CronTrigger(day_of_week="mon", hour=3, minute=45, timezone="Asia/Kolkata"),
        id="bertscore_eval",
        name="Weekly BERTScore Quality Evaluation",
        misfire_grace_time=7200,
    )

    # Daily distressed developer scan — 06:15 IST (after market snapshot at 06:00)
    scheduler.add_job(
        lambda: _safe_job(run_distressed_developer_scan, "distressed_dev_scan"),
        CronTrigger(hour=6, minute=15),
        id="distressed_dev_scan",
        name="Daily Distressed Developer Scan (JD/JV targets)",
        misfire_grace_time=3600,
    )

    # Weekly memory conflict detection — Monday 03:30 UTC (after memory decay at 03:00)
    scheduler.add_job(
        lambda: _safe_job(run_conflict_detection, "conflict_detection"),
        CronTrigger(day_of_week="mon", hour=3, minute=30, timezone="UTC"),
        id="conflict_detection",
        name="Weekly Memory Conflict Detection",
        misfire_grace_time=3600,
    )

    # Weekly digest — Monday 04:00 IST (after conflict detection)
    scheduler.add_job(
        lambda: _safe_job(run_weekly_digest, "weekly_digest"),
        CronTrigger(day_of_week="mon", hour=4, minute=0, timezone="Asia/Kolkata"),
        id="weekly_digest",
        name="Weekly Memory Digest (top-5 facts per market)",
        misfire_grace_time=3600,
    )

    # Weekly PSF forecast — Sunday 07:00 IST (T-765)
    scheduler.add_job(
        lambda: _safe_job(run_psf_forecast, "psf_forecast"),
        CronTrigger(day_of_week="sun", hour=7, minute=0),
        id="psf_forecast",
        name="Weekly PSF Forecast (LGBM)",
        misfire_grace_time=3600,
    )

    # Daily DB backup — 01:00 IST (T-904)
    scheduler.add_job(
        lambda: _safe_job(run_db_backup, "db_backup"),
        CronTrigger(hour=1, minute=0),
        id="db_backup",
        name="Daily pg_dump Backup",
        misfire_grace_time=3600,
    )

    # Daily LLS Compliance Calendar check — 08:00 IST (T-704)
    scheduler.add_job(
        lambda: _safe_job(run_compliance_check, "compliance_check"),
        CronTrigger(hour=8, minute=0),
        id="compliance_check",
        name="Daily LLS Compliance Calendar Check",
        misfire_grace_time=3600,
    )

    logger.info("RE_OS Scheduler started")
    logger.info("Jobs scheduled:")
    logger.info("  01:00 AM IST — Daily pg_dump backup [T-904]")
    logger.info("  02:00 AM IST — Unified Ingest Engine (all scrapers)")
    logger.info("  03:00 AM IST — Opportunity scoring (GATE-47)")
    logger.info("  04:30 AM IST — Intel embedding index (ChromaDB)")
    logger.info("  05:00 AM IST — News sentiment scoring (FinBERT)")
    logger.info("  06:00 AM IST — Market snapshots")
    logger.info("  06:15 AM IST — Distressed developer scan (JD/JV targets)")
    logger.info("  08:00 AM IST — LLS Compliance Calendar check [T-704]")
    logger.info("  Sunday 07:00 IST — Weekly PSF forecast (LGBM) [T-765]")
    logger.info("  Every 1 hr  — Board session recovery (T-315)")
    logger.info("  Monday 03:00 UTC — Agent memory decay")
    logger.info("  Monday 03:30 UTC — Memory conflict detection")
    logger.info("  Monday 03:45 IST — BERTScore quality evaluation")
    logger.info("  Monday 04:00 IST — Weekly memory digest (top-5 facts)")
    logger.info(f"Active jobs: {[j.id for j in scheduler.get_jobs()]}")

    scheduler.start()
