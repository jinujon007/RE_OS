"""
RE_OS — Scheduler
──────────────────
Runs the agent crew on schedule. Runs inside Docker as a separate service.

Schedule (post-Sprint-91, diet active):
- 04:00 AM IST — Daily pg_dump backup via DBBackup (Sprint 83, GATE-83)
- 02:00 AM IST — Unified Ingest Engine (all scrapers via DataPlugin adapters)
- 03:00 AM IST — Opportunity scoring (GATE-47 — survey scoring + Discord alert)
- 03:00 AM IST — Portal scout canary check (GATE-79 — zero-listing alert)
- 03:30 AM IST — FinBERT sentiment repair (GATE-79 — null score retry)
- 04:30 AM IST — Intel embedding index (ChromaDB via Ollama nomic-embed-text)
- 05:00 AM IST — News sentiment scoring (FinBERT via HF Inference API)
- 06:00 AM IST — Market snapshots (daily RERA + listing aggregates)
- 06:05 AM IST — Seed staleness check
- 06:10 AM IST — Locality alias validation
- 06:15 AM IST — Distressed developer scan (JD/JV targeting via Discord alert)
- 08:00 AM IST — LLS Compliance Calendar check (Discord #legal-flags if <30 days)
- Every 1 hr   — Stuck board session recovery
- Monday 03:00 UTC — Agent memory decay
- Monday 03:30 UTC — Memory conflict detection (Discord alert)
- Monday 03:45 IST — BERTScore quality evaluation
- Monday 04:00 IST — Weekly memory digest (top-5 facts per market → Discord)
- Monday 05:00 UTC — PSF Forecast update (numpy linear trend, GATE-85)
- Sunday 03:00 IST — Kaveri deed weekly extraction (inbox + live → Discord summary, GATE-91)
- 🧊 PR brief, process audit, CEO letter frozen by default (SCHEDULER_ENABLE_ORG_SIM=False)
"""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
import json
import os
import sys
import threading

from config.settings import TARGET_MARKETS, SCHEDULER_ENABLE_ORG_SIM, SCHEDULER_DRY_RUN
from sqlalchemy import text
from utils.db import get_engine
from utils.scheduler_helpers import safe_job as _safe_job
from scrapers.mobility_scout import run_mobility_scout
from utils.alembic_check import run_alembic_check
from utils.parcel_linker import run_parcel_linker_nightly
from utils.assembly_detector import run_assembly_detection


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

    # Locality validation check after snapshots
    for market in TARGET_MARKETS:
        market = market.strip()
        try:
            from utils.data_quality import DataQualityMonitor
            result = DataQualityMonitor.locality_validation_score(market)
            if result["score"] < 0.80:
                logger.warning(
                    "[Scheduler] Locality validation for %s: score=%.4f, suspect=%d, action=%s",
                    market, result["score"], result["suspect"], result["action"],
                )
            else:
                logger.info(
                    "[Scheduler] Locality validation for %s: score=%.4f (%d/%d valid)",
                    market, result["score"], result["valid"], result["valid"] + result["suspect"],
                )
        except Exception as e:
            logger.warning(f"  Locality validation failed for {market}: {e}")


def _ops_already_alerted(title: str, cooldown_hours: int = 23) -> bool:
    """Return True if an alert with this exact title was already sent to ops
    within cooldown_hours. Prevents daily re-fire of the same signal.
    """
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id FROM alerts
                    WHERE channel = 'ops'
                      AND title = :title
                      AND created_at > NOW() - (:hrs || ' hours')::interval
                    LIMIT 1
                """),
                {"title": title, "hrs": cooldown_hours},
            ).fetchone()
        return row is not None
    except Exception as exc:
        logger.debug("[Ops-Dedup] Check failed — allowing send: {}", exc)
        return False


def run_seed_staleness_check():
    """Check seed data staleness and remove stale seeds where live data sufficient.
    Runs at 06:05 IST, 5 min after market snapshot.
    """
    logger.info("Scheduler: Checking seed staleness")
    try:
        from utils.data_quality import DataQualityMonitor
        from utils.discord_notifier import send
        from config.gate_criteria import SLO_SEED_MIN_LIVE_LISTINGS

        flags = DataQualityMonitor.check_seed_staleness(min_live_listings=SLO_SEED_MIN_LIVE_LISTINGS)
        engine = get_engine()

        for flag in flags:
            market = flag["market"]
            if flag["action"] != "remove_seed_and_use_live":
                continue

            live_count = flag["live_listing_count"]
            logger.info(f"  {market}: removing seed data ({live_count} live listings available)")

            with engine.begin() as conn:
                conn.execute(
                    text("""
                        DELETE FROM listings l
                        USING micro_markets mm
                        WHERE l.micro_market_id = mm.id
                          AND mm.name ILIKE :market
                          AND l.data_source = 'seed_estimated'
                    """),
                    {"market": f"%{market}%"},
                )

            title = f"Seed data removed for {market}"
            if _ops_already_alerted(title):
                logger.info(f"  {market}: alert already sent in last 24h — skipping")
                continue

            try:
                send("ops", title, f"Seed data removed for {market} — {live_count} live listings available")
            except Exception as exc:
                logger.warning(f"  {market}: Discord alert failed: {exc}")

    except Exception as exc:
        logger.warning(f"[Scheduler] Seed staleness check failed: {exc}")


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


def _bd_already_alerted(title: str, cooldown_hours: int = 23) -> bool:
    """Return True if an alert with this exact title was already sent to bd_opportunities
    within cooldown_hours. Prevents daily re-fire of the same signal.
    Fails open (returns False) on any DB error so alerts are never silently dropped.
    """
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id FROM alerts
                    WHERE channel = 'bd_opportunities'
                      AND title = :title
                      AND created_at > NOW() - (:hrs || ' hours')::interval
                    LIMIT 1
                """),
                {"title": title, "hrs": cooldown_hours},
            ).fetchone()
        return row is not None
    except Exception as exc:
        logger.debug("[BD-Dedup] Check failed — allowing send: {}", exc)
        return False


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
    """Scan for distressed developers and alert via Discord if score > 0.6.
    7-day cooldown per developer prevents daily re-fire of unchanged signals.
    Skips if IngestEngine (which also runs DistressedPlugin) is still in progress
    to avoid Discord alerts based on partially-updated scores.
    """
    if _ingest_running.is_set():
        logger.warning(
            "[DistressedDev] IngestEngine still running — standalone scan deferred "
            "to avoid partial-score alerts. Will run at next scheduled trigger."
        )
        return
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
                title = f"Distressed Developer — {dev.developer_name} ({dev.market})"
                if _bd_already_alerted(title, cooldown_hours=168):  # 7-day cooldown
                    logger.info(f"[DistressedDev] Dedup skip: {dev.developer_name} ({dev.market})")
                    continue
                alert = format_distress_alert(dev)
                logger.info(f"[DistressedDev] Alert: {alert}")
                try:
                    send("bd_opportunities", title, alert)
                except Exception as exc:
                    logger.warning(f"[DistressedDev] Discord send failed: {exc}")
    except Exception as exc:
        logger.warning(f"[Scheduler] Distressed developer scan failed: {exc}")


def run_ingest_engine():
    """Combined ingest pipeline — runs at 02:00 IST by default.
    Replaces 6 separate cron jobs (3 RERA + listings + kaveri + IGR).
    Per-plugin schedule overrides in config.settings.PLUGIN_SCHEDULES.

    IMPORTANT: All schedule times in PLUGIN_SCHEDULES are in **IST** (UTC+5:30).
    This function converts current UTC to IST before comparing, so
    ``day_of_week`` and ``hour`` checks match Indian calendar days correctly.

    Sets _ingest_running event for the duration so the standalone distressed
    developer scan (06:15 IST) defers itself if this job overlaps.
    """
    from datetime import datetime, timezone, timedelta
    from ingest.engine import IngestEngine
    from ingest.plugins import (
        RERAPlugin, IGRPlugin, KaveriBhoomiPlugin,
        PortalPlugin, DeveloperPlugin, NewsPlugin,
        DistressedPlugin, BBMPPlugin, KaveriDeedsPlugin,
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
        # Allow up to 5 min early (clock skew); never skip if we are late — a misfired
        # job that fires after its scheduled time must still run all its plugins.
        delta = current_time_minutes - sched_minutes
        return delta >= -5

    engine = IngestEngine(max_workers=3, global_rate=3.0)
    all_plugins = [
        RERAPlugin(), IGRPlugin(), KaveriBhoomiPlugin(),
        PortalPlugin(), DeveloperPlugin(), NewsPlugin(),
        DistressedPlugin(), BBMPPlugin(), KaveriDeedsPlugin(),
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

    _ingest_running.set()
    try:
        report = engine.run_all(markets=TARGET_MARKETS)
        logger.info("[Scheduler] IngestEngine complete: {}", report.summary())
        for s in report.failed_plugins:
            logger.warning("[Scheduler] Plugin failed: {}/{} — {}", s.plugin_id, s.market, s.error_message)
    finally:
        _ingest_running.clear()


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
            title = f"URGENT — {r.survey_no} ({r.micro_market_id[:8]})"
            if _bd_already_alerted(title, cooldown_hours=23):
                logger.info("[Scheduler] BD dedup: skipping URGENT {} (sent within 23h)", r.survey_no)
                continue
            alert_msg = (
                f"**{r.survey_no}**\n"
                f"Score: **{r.score:.4f}** | IRR: {r.components.irr_score:.3f} "
                f"Legal: {r.components.legal_score:.3f} "
                f"Timing: {r.components.timing_score:.3f}\n"
                f"Action: {r.next_action}"
            )
            logger.info("[Scheduler] URGENT opportunity: {} score={:.4f}", r.survey_no, r.score)
            try:
                send("bd_opportunities", title, alert_msg)
            except Exception as exc:
                logger.warning("[Scheduler] URGENT alert Discord failed: {}", exc)

        priority = [r for r in results if 0.60 < r.score < 0.80]
        if priority:
            title_p = "Priority Opportunities — Review"
            if _bd_already_alerted(title_p, cooldown_hours=23):
                logger.info("[Scheduler] BD dedup: skipping PRIORITY summary (sent within 23h)")
            else:
                summary = "\n".join(
                    f"{r.survey_no} — score={r.score:.4f} — {r.next_action[:40]}"
                    for r in sorted(priority, key=lambda x: x.score, reverse=True)[:5]
                )
                try:
                    send("bd_opportunities", title_p, summary)
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


def run_psf_forecast_update():
    """Weekly PSF forecast update — Monday 05:00 UTC.
    Forecasts each market for horizons [3, 6, 12] and upserts to market_forecasts.
    Sends Discord digest with per-market trend summary."""
    from utils.psf_forecaster import PSFForecaster
    from sqlalchemy import text as _text
    from datetime import date

    results = []
    for market in TARGET_MARKETS:
        try:
            forecaster = PSFForecaster()
            result = forecaster.forecast(market)
            results.append(result)

            if result.status == "ok":
                today = date.today()
                upserts = []
                for horizon in [3, 6, 12]:
                    psf_val = getattr(result, f"forecast_{horizon}m", 0)
                    conf_low = getattr(result, f"conf_low_{horizon}m", None) if horizon in (3, 6, 12) else None
                    conf_high = getattr(result, f"conf_high_{horizon}m", None) if horizon in (3, 6, 12) else None
                    upserts.append({
                        "market": market, "fdate": today, "horizon": horizon,
                        "current_psf": result.current_psf,
                        "forecast_psf": psf_val,
                        "conf_low": conf_low, "conf_high": conf_high,
                        "trend": result.trend_direction,
                        "slope": result.slope_pct_per_month,
                        "points": result.data_points, "mae": result.mae_pct,
                    })
                with get_engine().begin() as conn:
                    for u in upserts:
                        conn.execute(
                            _text("""
                                INSERT INTO market_forecasts
                                    (market, forecast_date, horizon_months, current_psf, forecast_psf,
                                     conf_low, conf_high, trend_direction, slope_pct_per_month,
                                     data_points, mae_pct, model_version)
                                VALUES
                                    (:market, :fdate, :horizon, :current_psf, :forecast_psf,
                                     :conf_low, :conf_high, :trend, :slope,
                                     :points, :mae, 'linear_v1')
                                ON CONFLICT (market, forecast_date, horizon_months)
                                DO UPDATE SET
                                    forecast_psf = EXCLUDED.forecast_psf,
                                    conf_low = EXCLUDED.conf_low,
                                    conf_high = EXCLUDED.conf_high,
                                    trend_direction = EXCLUDED.trend_direction,
                                    slope_pct_per_month = EXCLUDED.slope_pct_per_month,
                                    data_points = EXCLUDED.data_points,
                                    mae_pct = EXCLUDED.mae_pct
                            """),
                            u,
                        )
                logger.info("[Scheduler] PSF forecast for {}: trend={}, 6m={}, MAE={:.1f}%",
                           market, result.trend_direction, result.forecast_6m, result.mae_pct)
            else:
                logger.warning("[Scheduler] PSF forecast skipped for {}: status={}", market, result.status)
        except Exception as exc:
            logger.warning("[Scheduler] PSF forecast failed for {}: {}", market, exc)

    if results:
        try:
            from utils.discord_notifier import send_forecast_digest
            send_forecast_digest(results)
        except Exception as exc:
            logger.warning("[Scheduler] PSF forecast digest failed: {}", exc)


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


# Guards against concurrent distress score computation between IngestEngine
# (02:00 IST, contains DistressedPlugin) and the standalone scan (06:15 IST).
# If IngestEngine is still running at 06:15, the standalone scan skips sending
# Discord alerts based on partially-updated scores.
#
# Both use proper threading primitives — APScheduler runs jobs in threads, so
# plain bool flags are subject to read-modify-write races across job threads.
_ingest_running = threading.Event()   # set() while ingest runs, clear() when done

def run_db_backup():
    """Daily pg_dump backup via DBBackup utility (Sprint 83, GATE-83)."""
    from utils.backup import DBBackup
    from utils.discord_notifier import send_ops_alert

    result = DBBackup().run()
    if result["status"] == "ok":
        obj_count = result.get("object_count", "?")
        pruned = result.get("pruned", 0)
        elapsed = result.get("elapsed_s", 0)
        logger.info(
            "[DB-Backup] Complete: {} ({} bytes, {} objects) | pruned {} | {:.1f}s",
            result["file"], result["size_bytes"], obj_count, pruned, elapsed,
        )
        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_runs
                            (agent_name, micro_market, event_type, status, records_inserted, notes)
                        VALUES ('backup', 'system', 'db_backup', 'success', 0, :notes)
                    """),
                    {"notes": "pg_dump {} ({} bytes, {} objects, {:.1f}s)".format(
                        result["file"], result["size_bytes"], obj_count, elapsed)},
                )
        except Exception as exc:
            logger.warning("[DB-Backup] Failed to log backup: {}", exc)
    else:
        error = result.get("error", "Unknown error")
        logger.error("[DB-Backup] Failed: {}", error)
        send_ops_alert("DB_BACKUP_FAILED", error)
        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_runs
                            (agent_name, micro_market, event_type, status, records_inserted, notes)
                        VALUES ('backup', 'system', 'db_backup', 'failed', 0, :notes)
                    """),
                    {"notes": "Backup failed: {}".format(error)},
                )
        except Exception as log_exc:
            logger.warning("[DB-Backup] Failed to log failure: {}", log_exc)


def run_backup_staleness_check():
    """Daily backup staleness check — 06:00 UTC. Alerts Discord if >26h old."""
    try:
        from utils.backup import check_backup_staleness
        from utils.discord_notifier import send_ops_alert

        result = check_backup_staleness()
        age = result.get("age_hours")
        latest = result.get("latest_file")
        if result["stale"]:
            if latest:
                detail = f"Latest backup {age}h old — file: {latest}" if age else "No backup file found"
            else:
                detail = "No backup file found"
            logger.warning("[BackupStaleness] Stale: {}", detail)
            send_ops_alert("DB_BACKUP_STALE", detail)
        else:
            logger.info("[BackupStaleness] Fresh: {}h old (file: {})", age, latest)
    except Exception as exc:
        logger.warning("[BackupStaleness] Check failed: {}", exc)


def run_la_notification_scan():
    """Weekly LA notification gazette scan — Sunday 06:00 IST."""
    try:
        from scrapers.la_gazette_parser import run_la_notification_scan as _run_scan
        count = _run_scan()
        logger.info("[LANotification] Scan complete: {} notifications", count)
    except Exception as exc:
        logger.warning("[LANotification] Scan failed: {}", exc)


def run_tender_daily_scan():
    """Daily eProcurement Karnataka tender scan.
    Scrapes North Bengaluru tenders, fires Discord alert for ≥₹50Cr closed tenders."""
    try:
        from ingest.plugins.tender_plugin import TenderPlugin
        from ingest.writer import IngestWriter
        from utils.discord_notifier import send

        plugin = TenderPlugin()
        writer = IngestWriter()
        all_tenders = plugin.run(market=None)
        written = 0
        high_value = []
        for record in all_tenders:
            if writer.write(record):
                written += 1
                val = record.data.get("value_inr")
                if val and float(val) >= 500000000.0:
                    high_value.append(record)

        logger.info("[TenderScan] {} tenders scraped, {} written", len(all_tenders), written)

        if high_value:
            for t in high_value:
                title_short = t.data.get("title", "")[:100]
                dept = t.data.get("dept", "?")
                val_cr = float(t.data.get("value_inr", 0)) / 10000000
                msg = f"💰 **Tender ≥₹50Cr**\n{title_short}\nDept: {dept} | Value: ₹{val_cr:.0f}Cr"
                try:
                    send("govt_policy_scout", "High-Value Tender Alert", msg)
                except Exception as exc:
                    logger.debug("[TenderScan] Discord send failed: {}", exc)
    except Exception as exc:
        logger.warning("[TenderScan] Failed: {}", exc)


def run_ledger_check_weekly():
    """Weekly prediction ledger check — Monday 06:00 IST.
    Resolves pending claims, posts hit-rate summary to Discord."""
    try:
        from utils.prediction_ledger import get_pending_claims, resolve_verdicts
        from utils.discord_notifier import send

        pending = get_pending_claims()
        if not pending:
            logger.info("[LedgerCheck] No pending claims to resolve")
            return

        summary = resolve_verdicts()
        msg = (
            f"Prediction Ledger Check — {summary['total']} pending\n"
            f"Resolved: {summary['resolved']} | "
            f"Partial: {summary['partial']} | "
            f"Unverifiable: {summary['unverifiable']}"
        )
        logger.info("[LedgerCheck] {}", msg)
        try:
            send("intel_reports", "Prediction Ledger Weekly Check", msg)
        except Exception as discord_exc:
            logger.debug("[LedgerCheck] Discord send skipped: {}", discord_exc)
    except Exception as exc:
        logger.warning("[LedgerCheck] Failed: {}", exc)


def run_offsite_backup_weekly():
    """Weekly offsite backup push — Sunday 05:00 IST.
    Pushes latest local dump to remote, verifies, alerts if stale."""
    from utils.backup import push_to_remote, verify_remote_backup, check_remote_backup_staleness
    from utils.discord_notifier import send_ops_alert

    result = push_to_remote()
    if result["status"] == "ok":
        logger.info("[OffsiteBackup] Remote push OK: {}", result["detail"])
        verify = verify_remote_backup()
        if verify.get("valid"):
            logger.info("[OffsiteBackup] Remote backup verified: {} objects", verify.get("object_count"))
        else:
            logger.warning("[OffsiteBackup] Remote backup verify failed: {}", verify.get("error"))
            send_ops_alert("REMOTE_BACKUP_VERIFY_FAILED", verify.get("error", "unknown"))
    elif result["status"] == "skipped":
        logger.info("[OffsiteBackup] Skipped: {}", result["detail"])
    else:
        logger.error("[OffsiteBackup] Push failed: {}", result["detail"])
        send_ops_alert("REMOTE_BACKUP_PUSH_FAILED", result["detail"])

    # Check remote staleness
    stale_result = check_remote_backup_staleness()
    if stale_result.get("stale") and stale_result.get("latest_file"):
        age = stale_result.get("age_days", "?")
        detail = f"Remote backup >8 days old: {stale_result['latest_file']} ({age}d)"
        logger.warning("[OffsiteBackup] Remote stale: {}", detail)
        send_ops_alert("REMOTE_BACKUP_STALE", detail)
    elif stale_result.get("status") == "ok":
        logger.info("[OffsiteBackup] Remote backup fresh")


def run_locality_validation():
    """Daily locality alias validation — 06:10 IST (after market snapshot at 06:00).
    Checks listings for known alien locality aliases and logs WARNING if >20% suspect."""
    try:
        from utils.data_quality import DataQualityMonitor
        for market in TARGET_MARKETS:
            market = market.strip()
            result = DataQualityMonitor.locality_validation_score(market)
            if result["score"] < 0.80:
                logger.warning(
                    "[Scheduler] Locality validation WARNING for %s: score=%.4f (%d suspect)",
                    market, result["score"], result["suspect"],
                )
            logger.info(
                "[Scheduler] Locality validation for %s: score=%.4f, action=%s",
                market, result["score"], result["action"],
            )
    except Exception as exc:
        logger.warning(f"[Scheduler] Locality validation failed: {exc}")


def run_finbert_sentiment_repair():
    """Nightly retry for null sentiment scores. 03:30 UTC.
    Queries news_articles with NULL sentiment from last 7 days (max FINBERT_REPAIR_BATCH_LIMIT).
    Retries each article 3x with exponential backoff (2s/4s/8s).
    Sets sentinel -99.0 on final failure to prevent re-processing."""
    FINBERT_REPAIR_BATCH_LIMIT = 50
    import time as _time
    from utils.sentiment import score_headline, label_from_score
    engine = get_engine()

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, COALESCE(summary, title, '') AS content FROM news_articles
                WHERE sentiment_score IS NULL
                  AND created_at >= NOW() - INTERVAL '7 days'
                LIMIT :limit
            """), {"limit": FINBERT_REPAIR_BATCH_LIMIT}).fetchall()

        updated = sentinel = 0
        for row in rows:
            article_id, content = row
            text_to_score = (content or "")[:512]
            if not text_to_score.strip():
                continue

            score = None
            for attempt in range(3):
                try:
                    score = score_headline(text_to_score)
                    if score is not None:
                        break
                except Exception:
                    pass
                if attempt < 2:
                    _time.sleep(2 * (2 ** attempt))

            with engine.begin() as conn:
                if score is not None:
                    label = label_from_score(score)
                    conn.execute(
                        text("UPDATE news_articles SET sentiment_score = :s, sentiment_label = :l WHERE id = :id"),
                        {"s": score, "l": label, "id": article_id},
                    )
                    updated += 1
                else:
                    # Sentinel: set score only, leave label as NULL to distinguish from scored articles
                    conn.execute(
                        text("UPDATE news_articles SET sentiment_score = -99.0 WHERE id = :id AND sentiment_score IS NULL"),
                        {"id": article_id},
                    )
                    sentinel += 1

        logger.info(
            f"[Scheduler] FinBERT repair: {updated} scored, {sentinel} sentineled"
        )
    except Exception as exc:
        logger.warning(f"[Scheduler] FinBERT sentiment repair failed: {exc}")


def run_portal_scout_canary_check():
    """Post-ingest canary: query for markets with zero new listings in last 24h.
    Fires Discord alert via send_scraper_alert. Runs at 03:00 UTC."""
    try:
        engine = get_engine()
        markets = [m.strip() for m in TARGET_MARKETS]
        _last_alert_key = "portal_canary_"
        for market in markets:
            # Cooldown: skip if alert already sent within last 23 hours
            title = f"portal_canary_{market}"
            if _digest_already_sent(title, cooldown_hours=23):
                logger.info(f"[Canary] {market}: skipped — alert sent within 23h")
                continue
            with engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT COUNT(*) FROM listings
                    WHERE data_source = 'portal_scout'
                      AND created_at >= NOW() - INTERVAL '24 hours'
                      AND micro_market_id = (SELECT id FROM micro_markets WHERE name ILIKE :m)
                """), {"m": f"%{market}%"}).fetchone()
            count = row[0] if row else 0
            if count == 0:
                from utils.discord_notifier import send_scraper_alert
                send_scraper_alert(market, "portal_scout", "ZERO_LISTINGS_CANARY", record_count=count)
                _mark_digest_sent(f"portal_canary_{market}")
                logger.warning(f"[Canary] {market}: 0 new portal listings in 24h — check portal connectivity; verify proxy/network; alert sent to Discord")
            else:
                logger.info(f"[Canary] {market}: {count} new portal listings in 24h — OK")
    except Exception as exc:
        logger.warning(f"[Scheduler] Portal scout canary check failed: {exc}")


def run_gv_freshness_check():
    """Daily GV freshness check — alerts if gazette data is >18 months stale.
    Runs concurrently across markets for performance."""
    try:
        from utils.data_quality import DataQualityMonitor
        from concurrent.futures import ThreadPoolExecutor, as_completed

        markets = [m.strip() for m in TARGET_MARKETS]
        results = {}

        with ThreadPoolExecutor(max_workers=len(markets)) as pool:
            futures = {pool.submit(DataQualityMonitor.check_gv_freshness, m): m for m in markets}
            for future in as_completed(futures):
                m = futures[future]
                try:
                    results[m] = future.result()
                except Exception as exc:
                    logger.warning("[Scheduler] GV freshness check failed for {}: {}", m, exc)
                    results[m] = {"alert_needed": False, "gazette_year": None, "months_stale": None}

        for market, result in results.items():
            if result.get("alert_needed"):
                logger.warning(
                    "[Scheduler] GV fresh STALE for {}: gazette {}, portal {}, {} months",
                    market, result.get("gazette_year"), result.get("portal_year"),
                    result.get("months_stale"),
                )
            else:
                logger.info(
                    "[Scheduler] GV fresh OK for {}: gazette {}, portal {}, {} months",
                    market, result.get("gazette_year"), result.get("portal_year"),
                    result.get("months_stale"),
                )

        # Track metrics
        try:
            from config.metrics import data_quality_checks_total
            for market, result in results.items():
                status = "stale" if result.get("alert_needed") else "fresh"
                data_quality_checks_total.labels(market=market, source="gv_freshness", status=status).inc()
        except Exception:
            pass
    except Exception as exc:
        logger.warning("[Scheduler] GV freshness check overall failure: {}", exc)


def weekly_competitive_digest():
    """Monday ~07:00 IST competitive pulse — Discord digest to #bd-opportunities.
    Runs at 01:00 UTC (06:30 IST ≈ 07:00 IST). Wraps all failures gracefully."""
    try:
        from intelligence.competitive_intel import CompetitiveIntelEngine
        from utils.discord_notifier import send_competitive_digest

        engine = CompetitiveIntelEngine()
        pulse = engine.pulse(market=None, days=7, top_n=5)
        send_competitive_digest(pulse)
        n_l = len(pulse.get("new_launches", []))
        n_m = len(pulse.get("psf_movers", []))
        n_a = len(pulse.get("absorption_leaders", []))
        logger.info(
            "[Scheduler] Competitive digest sent — {} launches, {} movers, {} absorbers",
            n_l, n_m, n_a,
        )
    except Exception as exc:
        logger.warning("[Scheduler] Competitive digest failed: {}", exc)


def weekly_process_audit():
    """Sunday 03:00 UTC — Process automation audit cycle.
    LogAnalyst → EfficiencyOptimizer → RunbookDocumenter → Discord #ops summary."""
    try:
        from agents.log_analyst_agent import LogAnalystAgent
        from agents.efficiency_optimizer_agent import EfficiencyOptimizerAgent
        from agents.runbook_documenter_agent import RunbookDocumenterAgent
        from utils.discord_notifier import send

        title = "Weekly Process Audit"
        if _ops_already_alerted(title, cooldown_hours=47):
            logger.info("[Scheduler] Process audit dedup: already sent within 47h — skipping")
            return

        log_agent = LogAnalystAgent()
        log_result = log_agent.run()
        report = log_result.get("report", {})

        eff_agent = EfficiencyOptimizerAgent()
        eff_result = eff_agent.run(bottleneck_report=report)
        proposal = eff_result.get("proposal", {})

        doc_agent = RunbookDocumenterAgent()
        doc_result = doc_agent.run(bottleneck_report=report, improvement_proposal=proposal)

        summary = (
            f"Process Audit complete — Bottleneck: {report.get('bottleneck_stage', 'none')} | "
            f"Finding: {report.get('top_finding', '')[:120]} | "
            f"Proposal: {proposal.get('title', '')[:80]} | "
            f"Runbook: {doc_result.get('path', '')}"
        )
        if proposal.get("priority") == "HIGH":
            send("system", "Weekly Process Audit", summary)
        logger.info("[Scheduler] Process audit complete — {}", summary)
    except Exception as exc:
        logger.warning("[Scheduler] Process audit failed (non-fatal): {}", exc)


def weekly_pr_brief():
    """Monday ~07:30 IST PR brief digest — Discord to #bd-opportunities.
    Runs at 02:00 UTC (07:30 IST). Gathers brand mentions, competitor launches,
    and generates LinkedIn preview. Never crashes. 23h dedup guard prevents
    re-firing if scheduler restarts mid-day."""
    try:
        from utils.brand_monitor import BrandMentionMonitor, format_pr_brief_digest
        from intelligence.competitive_intel import CompetitiveIntelEngine
        from utils.discord_notifier import send

        title = "Weekly PR Brief"
        if _ops_already_alerted(title, cooldown_hours=23):
            logger.info("[Scheduler] PR brief dedup: already sent within 23h — skipping")
            return

        monitor = BrandMentionMonitor()
        mentions = monitor.scan_mentions("LLS", 7)

        engine = CompetitiveIntelEngine()
        launches = engine.new_launches(market=None, days=7)

        linkedin_preview = ""
        try:
            from utils.content_pipeline import ContentPipeline
            pipeline = ContentPipeline()
            result = pipeline.run(market="Yelahanka", survey_no="system", deal_type="pr")
            linkedin_preview = result.get("linkedin_post", "")
        except Exception as exc:
            logger.debug("[Scheduler] PR brief LinkedIn preview skipped: {}", exc)

        digest = format_pr_brief_digest(mentions, launches, linkedin_preview)
        send("bd_opportunities", title, digest)

        logger.info(
            "[Scheduler] PR brief sent — {} mentions, {} launches, {} chars",
            len(mentions), len(launches), len(digest),
        )
    except Exception as exc:
        logger.warning("[Scheduler] Weekly PR brief failed (non-fatal): {}", exc)


def monthly_ceo_letter():
    """1st of month 04:00 UTC — Generate monthly CEO letter.

    Gathers PerformanceDigest for the quarter, agent_runs summary, and
    optimizer findings. Writes a lighter CEO letter to outputs/shareholder_letters/.
    Sends 3-line Discord summary to #ops.
    """
    try:
        from utils.performance_digest import PerformanceDigest
        from pathlib import Path
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        month = now.strftime("%Y-%m")
        quarter_num = (now.month - 1) // 3 + 1
        quarter = f"Q{quarter_num}-{now.year}"

        digest = PerformanceDigest.build(quarter)

        total_agent_runs = 0
        try:
            with get_engine().connect() as conn:
                row = conn.execute(
                    text("SELECT COUNT(*) FROM agent_runs WHERE created_at >= DATE_TRUNC('month', NOW())")
                ).fetchone()
                total_agent_runs = row[0] if row else 0
        except Exception:
            pass

        optimizer_note = ""
        try:
            from utils.optimizer_report import OptimizerReport
            report = OptimizerReport.from_last_report()
            if report and report.top_recommendation:
                optimizer_note = report.top_recommendation[:200]
        except Exception:
            pass

        deal_count = digest.get("deal_metrics", {}).get("deal_count", 0)
        avg_irr = digest.get("deal_metrics", {}).get("avg_irr_pct", "N/A")
        new_projects_total = sum(
            p.get("project_count", 0) for p in digest.get("new_projects", [])
        )
        over_budget = digest.get("token_efficiency", {}).get("over_budget_count", 0)

        letter = (
            f"# Monthly CEO Letter — {month}\n\n"
            f"**Quarter:** {quarter}\n"
            f"**Generated:** {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"## Month in Review\n\n"
            f"The system evaluated {deal_count} deal(s) this month "
            f"with an average IRR of {avg_irr}%. "
            f"We tracked {new_projects_total} new project(s) across our markets.\n\n"
            f"## Top Intelligence Moments\n\n"
            f"1. {deal_count} deal(s) processed through the full evaluate pipeline.\n"
            f"2. {new_projects_total} new project(s) detected across target markets.\n"
            f"3. {total_agent_runs} agent run(s) completed this month.\n\n"
            f"## System Health\n\n"
            f"Token budget overruns: {over_budget} agent(s) exceeded budget. "
            f"{optimizer_note if optimizer_note else 'No optimizer recommendations available.'}\n\n"
            f"## Next Month Focus\n\n"
            f"Continue monitoring {quarter} performance targets, "
            f"address token budget optimization recommendations, "
            f"and maintain pipeline throughput.\n\n"
            f"---\n*LLS CEO • Automated monthly brief*"
        )

        output_dir = Path("outputs/shareholder_letters")
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{month}_Monthly_CEO_Letter.md"
        path.write_text(letter, encoding="utf-8")

        summary = (
            f"Monthly CEO letter — {month} | "
            f"{deal_count} deals, {new_projects_total} new projects, "
            f"{over_budget} over-budget agents | "
            f"Letter saved: {path.name}"
        )
        try:
            from utils.discord_notifier import send
            send("system", "Monthly CEO Letter", summary)
        except Exception:
            pass

        logger.info("[Scheduler] Monthly CEO letter saved to {} — {}", path, summary)
    except Exception as exc:
        logger.warning("[Scheduler] Monthly CEO letter failed (non-fatal): {}", exc)


def run_gcc_daily_scan():
    """Ingest new GCC events and fire Discord alerts for Level 1–2 signals.

    1. Runs GCCPlugin for each market to pick up new seed + news events.
    2. IngestEngine writes records to gcc_events table.
    3. GCCIntel.get_pending_alerts() fetches qualifying events.
    4. Fires Discord alert per event, marks discord_alert_fired=True.
    5. Invalidates DemandIntel cache so next demand_score_v2 uses fresh GCC data.
    """
    logger.info("[Scheduler] GCC daily scan starting")
    try:
        from ingest.plugins.gcc_plugin import GCCPlugin
        from intelligence.gcc_intel import GCCIntel
        from utils.discord_notifier import send_gcc_alert
        from utils.db import get_engine
        from sqlalchemy import text as _text
        import dataclasses

        plugin = GCCPlugin()
        engine = get_engine()

        for market in [m.strip() for m in TARGET_MARKETS]:
            try:
                records = plugin.run(market)
                if not records:
                    continue

                with engine.begin() as conn:
                    for rec in records:
                        d = rec.data
                        conn.execute(_text("""
                            INSERT INTO gcc_events (
                                canonical_id, company, sector, country_of_origin,
                                bengaluru_location, nearest_corridor, entrant_type,
                                work_model, signal_maturity_level, is_negative_signal,
                                north_bengaluru_impact_score, investment_cr,
                                planned_headcount, headcount_timeline_months,
                                median_ctc_l, office_sqft,
                                demand_creation_score, residential_impact_score,
                                appreciation_impact_score, rental_impact_score,
                                gcc_signal_score, primary_housing_segment,
                                time_horizon, estimated_demand_units,
                                source_name, source_reliability, announced_at,
                                discord_alert_fired
                            ) VALUES (
                                :canonical_id, :company, :sector, :country_of_origin,
                                :bengaluru_location, :nearest_corridor, :entrant_type,
                                :work_model, :signal_maturity_level, :is_negative_signal,
                                :north_bengaluru_impact_score, :investment_cr,
                                :planned_headcount, :headcount_timeline_months,
                                :median_ctc_l, :office_sqft,
                                :demand_creation_score, :residential_impact_score,
                                :appreciation_impact_score, :rental_impact_score,
                                :gcc_signal_score, :primary_housing_segment,
                                :time_horizon, :estimated_demand_units,
                                :source_name, :source_reliability,
                                CAST(:announced_at AS date), :discord_alert_fired
                            )
                            ON CONFLICT (canonical_id) DO NOTHING
                        """), d)
                logger.info("[Scheduler] GCC scan {}: {} records upserted", market, len(records))
            except Exception as exc:
                logger.warning("[Scheduler] GCC scan failed for {}: {}", market, exc)

        # Fire pending alerts
        intel = GCCIntel(caller="scheduler")
        pending = intel.get_pending_alerts()
        for evt in pending:
            try:
                evt_dict = dataclasses.asdict(evt) if hasattr(dataclasses, "asdict") else evt.__dict__
                send_gcc_alert(evt_dict)
                intel.mark_alert_fired(evt.canonical_id)
            except Exception as exc:
                logger.warning("[Scheduler] GCC alert failed for {}: {}", evt.canonical_id, exc)

        # Invalidate DemandIntel cache for all markets
        from intelligence.demand_intel import DemandIntel
        for market in [m.strip() for m in TARGET_MARKETS]:
            try:
                DemandIntel(caller="scheduler").invalidate_cache(market)
            except Exception:
                pass

        logger.info(
            "[Scheduler] GCC daily scan done — {} pending alerts processed",
            len(pending),
        )
    except Exception as exc:
        logger.error("[Scheduler] GCC daily scan failed: {}", exc)


def run_gcc_weekly_digest():
    """Compile and send weekly GCC pipeline digest to Discord intel channel."""
    logger.info("[Scheduler] GCC weekly digest starting")
    try:
        from intelligence.gcc_intel import GCCIntel, _MARKET_TO_CORRIDOR
        from utils.discord_notifier import send_gcc_weekly_digest
        import dataclasses

        intel = GCCIntel(caller="scheduler")

        # Per-corridor scores
        corridor_scores: dict[str, float] = {}
        for market in [m.strip() for m in TARGET_MARKETS]:
            result = intel.get_gcc_score(market)
            if result.corridor:
                corridor_scores[result.corridor] = result.gcc_north_norm

        # Top 10 recent events across all North BLR corridors
        events = intel.get_events(
            corridors=list(_MARKET_TO_CORRIDOR.values()),
            maturity_levels=[1, 2, 3],
            include_negative=False,
            limit=10,
        )

        events_as_dicts = []
        for evt in events:
            try:
                d = dataclasses.asdict(evt) if hasattr(dataclasses, "asdict") else evt.__dict__
                events_as_dicts.append(d)
            except Exception:
                pass

        send_gcc_weekly_digest(events_as_dicts, corridor_scores)
        logger.info(
            "[Scheduler] GCC weekly digest sent — {} events, {} corridors",
            len(events_as_dicts),
            len(corridor_scores),
        )
    except Exception as exc:
        logger.error("[Scheduler] GCC weekly digest failed: {}", exc)


def run_gcc_hiring_snapshot():
    """Weekly snapshot of Naukri job postings per tracked GCC employer (T-1152)."""
    from ingest.plugins.gcc_hiring_plugin import GccHiringPlugin
    from ingest.writer import IngestWriter
    logger.info("[Scheduler] GCC hiring snapshot starting")
    try:
        plugin = GccHiringPlugin()
        records = plugin.run()
        writer = IngestWriter()
        results = writer.write_batch(records)
        successes = sum(1 for r in results if r.success)
        logger.info("[Scheduler] GCC hiring snapshot done — {}/{} records written", successes, len(results))
    except Exception as exc:
        logger.error("[Scheduler] GCC hiring snapshot failed: {}", exc)


def run_dc_conversion_scan():
    """Daily DC conversion scan — queries Bhoomi portal (T-1153)."""
    from ingest.plugins.dc_conversion_plugin import DCConversionPlugin
    from ingest.writer import IngestWriter
    logger.info("[Scheduler] DC conversion scan starting")
    try:
        plugin = DCConversionPlugin()
        records = plugin.run()
        writer = IngestWriter()
        results = writer.write_batch(records)
        successes = sum(1 for r in results if r.success)
        logger.info("[Scheduler] DC conversion scan done — {}/{} records written", successes, len(results))
    except Exception as exc:
        logger.error("[Scheduler] DC conversion scan failed: {}", exc)


def run_govt_policy_daily_scan():
    """Daily scan for govt/policy/infra events — 06:30 IST = 01:00 UTC."""
    logger.info("[Scheduler] Govt policy daily scan starting")
    try:
        from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin
        from utils.discord_notifier import send_govt_policy_alert
        from utils.db import get_engine
        from sqlalchemy import text as _text

        plugin = GovtPolicyPlugin()
        engine = get_engine()

        for market in [m.strip() for m in TARGET_MARKETS]:
            try:
                records = plugin.run(market)
                if not records:
                    continue

                with engine.begin() as conn:
                    for rec in records:
                        d = rec.data
                        conn.execute(_text("""
                            INSERT INTO govt_policy_events (
                                headline, category, subcategory, location_text,
                                micro_markets, investment_cr, stage, impact_score,
                                signal_strength, demand_type, time_horizon,
                                actionability, summary, why_it_matters,
                                source_urls, published_date, is_north_bengaluru
                            ) VALUES (
                                :headline, :category, :subcategory, :location_text,
                                :micro_markets, :investment_cr, :stage, :impact_score,
                                :signal_strength, :demand_type, :time_horizon,
                                :actionability, :summary, :why_it_matters,
                                :source_urls, CAST(:published_date AS date), :is_north_bengaluru
                            )
                            ON CONFLICT DO NOTHING
                        """), d)
                logger.info(
                    "[Scheduler] Govt policy scan {}: {} records", market, len(records),
                )

                # Fire Discord alerts for high-impact North Bengaluru events
                for rec in records:
                    d = rec.data
                    if d.get("is_north_bengaluru") and (d.get("impact_score") or 0) >= 7:
                        send_govt_policy_alert(d)
            except Exception as exc:
                logger.warning(
                    "[Scheduler] Govt policy scan failed for {}: {}", market, exc,
                )

        logger.info("[Scheduler] Govt policy daily scan done")
    except Exception as exc:
        logger.error("[Scheduler] Govt policy daily scan failed: {}", exc)


def run_govt_policy_weekly_digest():
    """Weekly govt/policy digest — every Monday 08:00 IST = 02:30 UTC."""
    logger.info("[Scheduler] Govt policy weekly digest starting")
    try:
        from intelligence.govt_policy_intel import GovtPolicyIntel
        from utils.discord_notifier import send_govt_policy_digest

        intel = GovtPolicyIntel(caller="scheduler")
        result = intel.compute("north_bengaluru_aggregate")
        send_govt_policy_digest(result)
        logger.info(
            "[Scheduler] Govt policy digest sent — NB score: {}",
            result.north_bengaluru_score,
        )
    except Exception as exc:
        logger.error("[Scheduler] Govt policy weekly digest failed: {}", exc)


def _digest_already_sent(digest_type: str, cooldown_hours: int = 23) -> bool:
    """Check if a digest was already sent within cooldown_hours.
    Uses a dedicated marker alert in the ops channel with title 'intel_digest:{type}'.
    Fails open (returns False) on DB error so alerts are never silently dropped."""
    title = f"intel_digest:{digest_type}"
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT id FROM alerts
                    WHERE channel = 'ops'
                      AND title = :title
                      AND created_at > NOW() - (:hrs || ' hours')::interval
                    LIMIT 1
                """),
                {"title": title, "hrs": cooldown_hours},
            ).fetchone()
        return row is not None
    except Exception as exc:
        logger.debug("[Digest-Dedup] Check failed — allowing send: {}", exc)
        return False


def _mark_digest_sent(digest_type: str) -> None:
    """Write a dedup marker alert to ops channel so subsequent runs can detect duplicates."""
    title = f"intel_digest:{digest_type}"
    try:
        from utils.discord_notifier import send as _discord_send
        _discord_send("ops", title, f"Digest marker — {digest_type} sent")
    except Exception as exc:
        logger.debug("[Digest-Dedup] Failed to write marker: {}", exc)


def run_weekly_intel_digest():
    """Monday 01:30 UTC = 07:00 IST — Weekly intel digest.
    Builds digest for all 3 markets, sends to Discord, optionally exports to Obsidian.
    Dedup guard prevents duplicate sends on scheduler restart within the same 23h window."""
    if _digest_already_sent("weekly", cooldown_hours=23):
        logger.info("[Scheduler] Weekly digest dedup: already sent within 23h — skipping")
        return

    logger.info("[Scheduler] Weekly intel digest starting")
    failure_count = 0
    try:
        from utils.weekly_digest import WeeklyIntelDigest
        from utils.discord_notifier import send_weekly_digest
        from utils.obsidian_export import ObsidianExport
        markets = [m.strip() for m in TARGET_MARKETS]
        results = []
        for market in markets:
            try:
                digest = WeeklyIntelDigest()
                result = digest.build(market)
                results.append(result)
            except Exception as exc:
                failure_count += 1
                logger.warning("[Scheduler] Weekly digest build failed for {}: {}", market, exc)
        if results:
            _mark_digest_sent("weekly")
            send_weekly_digest(results)
            successful = len(results) - failure_count
            logger.info(
                "[Scheduler] Weekly intel digest sent for {}/{} markets ({} failures)",
                successful, len(results), failure_count,
            )
        else:
            logger.warning("[Scheduler] Weekly intel digest: 0 results built — skipping Discord send")
            return
        ObsidianExport.write_weekly(results)
    except Exception as exc:
        logger.warning("[Scheduler] Weekly intel digest failed: {}", exc)


def run_monthly_intel_digest():
    """1st of month 02:00 UTC = 07:30 IST — Monthly intel digest.
    Builds digest for all 3 markets, sends to Discord, optionally exports to Obsidian.
    Dedup guard prevents duplicate sends on scheduler restart within the same 47h window."""
    if _digest_already_sent("monthly", cooldown_hours=47):
        logger.info("[Scheduler] Monthly digest dedup: already sent within 47h — skipping")
        return

    logger.info("[Scheduler] Monthly intel digest starting")
    failure_count = 0
    try:
        from utils.monthly_digest import MonthlyIntelDigest
        from utils.discord_notifier import send_monthly_digest
        from utils.obsidian_export import ObsidianExport
        markets = [m.strip() for m in TARGET_MARKETS]
        results = []
        for market in markets:
            try:
                digest = MonthlyIntelDigest()
                result = digest.build(market)
                results.append(result)
            except Exception as exc:
                failure_count += 1
                logger.warning("[Scheduler] Monthly digest build failed for {}: {}", market, exc)
        if results:
            _mark_digest_sent("monthly")
            send_monthly_digest(results)
            successful = len(results) - failure_count
            logger.info(
                "[Scheduler] Monthly intel digest sent for {}/{} markets ({} failures)",
                successful, len(results), failure_count,
            )
        else:
            logger.warning("[Scheduler] Monthly intel digest: 0 results built — skipping Discord send")
            return
        ObsidianExport.write_monthly(results)
    except Exception as exc:
        logger.warning("[Scheduler] Monthly intel digest failed: {}", exc)


def run_post_crew_optimizer_hook():
    """Run after market_intel_crew completes — generates optimizer report and creates tasks for HIGH findings."""
    logger.info("[Scheduler] Post-crew optimizer hook starting")
    try:
        from utils.optimizer_report import generate_report
        from utils.db import get_engine
        from sqlalchemy import text

        # Generate 1-day report
        report = generate_report(days=1)

        # Check for HIGH severity findings
        high_findings = [f for f in report.redundancy_findings if f.get("severity") == "HIGH"]

        if high_findings:
            # Create project task via API
            for finding in high_findings[:3]:  # cap at 3 tasks per run
                recommendation = finding.get("recommendation", "Review HIGH severity finding")
                try:
                    with get_engine().begin() as conn:
                        conn.execute(
                            text("""
                                INSERT INTO tasks (title, owner, priority, source_type, source_id)
                                VALUES (:t, 'optimizer', 'high', 'optimizer_finding', :sid)
                            """),
                            {"t": recommendation[:100], "sid": finding.get("agent", "unknown")},
                        )
                    report.auto_tasks_created += 1
                except Exception as exc:
                    logger.warning("[Scheduler] Failed to create task for findings: {}", exc)

            # Write report to outputs/optimizer/ (use relative path for dev, /app for prod)
            import os
            output_base = "/app/outputs/optimizer" if os.path.exists("/app") else "outputs/optimizer"
            report_path = os.path.join(output_base, f"{report.report_date}.md")
            os.makedirs(output_base, exist_ok=True)
            report.write(report_path)

        logger.info("[Scheduler] Optimizer hook: {} high findings, {} tasks created",
                   len(high_findings), report.auto_tasks_created)
    except Exception as exc:
        logger.error("[Scheduler] Post-crew optimizer hook failed: {}", exc)


_BHOOMI_DEDUP_PREFIX = "bhoomi_auto_survey:"


def _bhoomi_already_ran(market: str, cooldown_hours: int = 12) -> bool:
    title = f"{_BHOOMI_DEDUP_PREFIX}{market}"
    try:
        with get_engine().connect() as conn:
            row = conn.execute(text("""
                SELECT id FROM alerts
                WHERE channel = 'ops' AND title = :title
                  AND created_at > NOW() - (:hrs || ' hours')::interval
                LIMIT 1
            """), {"title": title, "hrs": cooldown_hours}).fetchone()
        return row is not None
    except Exception as exc:
        logger.debug("[Bhoomi-Dedup] Check failed: {}", exc)
        return False


def _mark_bhoomi_ran(market: str) -> None:
    title = f"{_BHOOMI_DEDUP_PREFIX}{market}"
    try:
        from utils.discord_notifier import send as ds
        ds("ops", title, f"Bhoomi auto-survey ran for {market}")
    except Exception as exc:
        logger.debug("[Bhoomi-Dedup] Marker failed: {}", exc)


def run_bhoomi_auto_survey(market: str = ""):
    from config.settings import TARGET_MARKETS as _M
    from scrapers.bhoomi_scraper import fetch as _bf

    markets = [m.strip() for m in _M] if not market else [market.strip()]
    engine = get_engine()

    for mkt in markets:
        if _bhoomi_already_ran(mkt, cooldown_hours=12):
            logger.info("[BhoomiAutoSurvey] Dedup skip: {}", mkt)
            continue

        try:
            with engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT id, survey_no, developer_name FROM rera_projects
                    WHERE survey_no IS NOT NULL AND survey_no != ''
                      AND bhoomi_checked_at IS NULL
                      AND micro_market_id = (SELECT id FROM micro_markets WHERE name ILIKE :m)
                    LIMIT 20
                """), {"m": f"%{mkt}%"}).fetchall()
        except Exception as exc:
            logger.warning("[BhoomiAutoSurvey] Query failed for {}: {}", mkt, exc)
            continue

        if not rows:
            logger.info("[BhoomiAutoSurvey] No unchecked survey numbers for {}", mkt)
            _mark_bhoomi_ran(mkt)
            continue

        checked = 0
        skipped_429 = False
        for row in rows:
            if skipped_429:
                break
            try:
                result = _bf(row.survey_no, market=mkt)
            except Exception as exc:
                logger.warning("[BhoomiAutoSurvey] Fetch error {}: {}", row.survey_no, exc)
                continue

            if result.get("bhoomi_status") == "unavailable":
                if result.get("error") == "rate_limited":
                    logger.warning("[BhoomiAutoSurvey] 429 on {} — stopping batch", mkt)
                    skipped_429 = True
                continue

            owner = result.get("owner_name", "").strip()
            if owner:
                try:
                    with engine.begin() as conn:
                        existing = conn.execute(text(
                            "SELECT id FROM landowner_contacts WHERE survey_no=:sn AND market=:m"
                        ), {"sn": row.survey_no, "m": mkt}).fetchone()
                        if existing:
                            conn.execute(text(
                                "UPDATE landowner_contacts SET owner_name=:o, updated_at=NOW() WHERE id=:lid"
                            ), {"o": owner, "lid": existing.id})
                        else:
                            conn.execute(text(
                                "INSERT INTO landowner_contacts (survey_no, market, owner_name) VALUES (:sn, :m, :o)"
                            ), {"sn": row.survey_no, "m": mkt, "o": owner})
                except Exception as exc:
                    logger.warning("[BhoomiAutoSurvey] Upsert failed: {}", exc)

            try:
                with engine.begin() as conn:
                    conn.execute(text(
                        "UPDATE rera_projects SET bhoomi_checked_at=NOW() WHERE id=:pid"
                    ), {"pid": row.id})
                checked += 1
            except Exception as exc:
                logger.warning("[BhoomiAutoSurvey] Mark failed: {}", exc)

        _mark_bhoomi_ran(mkt)
        logger.info("[BhoomiAutoSurvey] {}: {}/{} checked{}",
            mkt, checked, len(rows), " (429)" if skipped_429 else "")


def run_data_floor_check():
    """Data floor + heartbeat staleness check — 06:30 IST = 01:00 UTC (T-1128, T-1158).

    Dual responsibility:
    1. Alerts Discord via send_ops_alert if any market's live RERA count
       drops below its configured floor.
    2. Checks scheduler heartbeat staleness — alerts if last heartbeat >2h old
       (silent scheduler death detection).

    Logs combined outcome to agent_runs.
    """
    from config.settings import DATA_FLOOR_MARKETS
    from utils.data_quality_monitor import check_live_data_floor

    logger.info("[Scheduler] Data floor + heartbeat check starting")

    # Data floor check per market
    all_ok = True
    for market, floor in DATA_FLOOR_MARKETS.items():
        try:
            ok = check_live_data_floor(market, floor=floor)
            if ok:
                logger.info("[Scheduler] Data floor {}: OK (floor={})", market, floor)
            else:
                logger.warning("[Scheduler] Data floor {}: BREACH (floor={})", market, floor)
                all_ok = False
        except Exception as exc:
            logger.warning("[Scheduler] Data floor check failed for {}: {}", market, exc)
            all_ok = False

    # Scheduler heartbeat staleness check (T-1158)
    try:
        heartbeat_ok = check_heartbeat_staleness(max_age_hours=2)
        if not heartbeat_ok:
            all_ok = False
    except Exception as exc:
        logger.warning("[Scheduler] Heartbeat staleness check failed: {}", exc)
        all_ok = False

    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs
                        (agent_name, micro_market, event_type, status, notes)
                    VALUES ('data_floor_monitor', 'system', 'data_floor_check', :status, :notes)
                """),
                {
                    "status": "success" if all_ok else "warning",
                    "notes": f"checked {len(DATA_FLOOR_MARKETS)} markets + heartbeat; all_ok={all_ok}",
                },
            )
    except Exception as exc:
        logger.warning("[Scheduler] Failed to log data floor check: {}", exc)


def run_kaveri_deeds_weekly():
    """Weekly Kaveri deed extraction — Sunday 03:00 IST.

    Runs inbox mode always, attempts live mode, sends Discord summary.
    """
    from scrapers.kaveri_deeds import run_inbox_mode, run_live_mode, read_latest_checkpoint

    logger.info("[Scheduler] Kaveri deeds weekly extraction starting")

    inbox_records = run_inbox_mode()
    live_records = run_live_mode()
    total = len(inbox_records) + len(live_records)

    # Count deeds with PSF
    psf_count = sum(
        1 for r in (inbox_records + live_records) if r.get("psf") is not None
    )

    summary = (
        f"KAVERI DEEDS WEEKLY: {total} new deeds extracted "
        f"({len(inbox_records)} inbox, {len(live_records)} live). "
        f"{psf_count} have computed PSF."
    )
    logger.info(summary)

    # Log to agent_runs for observability
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs
                        (agent_name, micro_market, event_type, status, notes)
                    VALUES ('kaveri_deeds_weekly', 'system', 'kaveri_deeds_weekly',
                            :status, :notes)
                """),
                {
                    "status": "success" if total > 0 else "completed",
                    "notes": summary,
                },
            )
    except Exception as exc:
        logger.warning("[Scheduler] Failed to log kaveri_deeds_weekly run: {}", exc)

    try:
        from utils.discord_notifier import send_ops_alert
        send_ops_alert("KAVERI_DEEDS_WEEKLY", summary)
    except Exception as exc:
        logger.warning("[Scheduler] Kaveri deeds Discord alert failed: {}", exc)


def run_scheduler_heartbeat():
    """Interval job: writes agent_runs row to prove scheduler is alive.

    Runs every 30 minutes via interval job (T-1158).
    check_heartbeat_staleness() (called from run_data_floor_check) alerts
    Discord OPS if last heartbeat is >2h old — catches silent scheduler death.

    Safe against concurrent heartbeat writes (each INSERT is a new row).
    Risk: if the scheduler process hangs but the thread running this job still
    executes, the heartbeat will appear alive while other jobs are stuck.
    Acceptable — a hung job would also eventually fail its max-instances guard
    and the data-floor check independently validates per-market data freshness.
    """
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs
                        (agent_name, micro_market, event_type, status, notes)
                    VALUES ('scheduler_heartbeat', 'system', 'heartbeat', 'success', :notes)
                """),
                {"notes": f"Scheduler heartbeat at {now_iso}"},
            )
        logger.debug("[Scheduler] Heartbeat written at {}", now_iso)
    except Exception as exc:
        logger.warning("[Scheduler] Heartbeat failed: {}", exc)


def check_heartbeat_staleness(max_age_hours: int = 2) -> bool:
    """Check if scheduler heartbeat is stale (>max_age_hours since last row).

    Returns True if heartbeat is fresh, False if stale (alert sent to Discord OPS).
    Never raises — returns False on any error.
    """
    from datetime import datetime, timezone
    from utils.discord_notifier import send_ops_alert as _send_alert

    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT created_at FROM agent_runs
                    WHERE agent_name = 'scheduler_heartbeat'
                    ORDER BY created_at DESC LIMIT 1
                """)
            ).fetchone()
        if row is None:
            _send_alert(
                "HEARTBEAT_STALE",
                "Scheduler heartbeat has NEVER been written — possible scheduler failure",
            )
            return False
        last_ts = row[0]
        if last_ts.tzinfo is None:
            from datetime import timezone as _tz
            last_ts = last_ts.replace(tzinfo=_tz.utc)
        age = (datetime.now(timezone.utc) - last_ts).total_seconds() / 3600
        if age > max_age_hours:
            _send_alert(
                "HEARTBEAT_STALE",
                f"Scheduler heartbeat stale: {age:.1f}h old (max {max_age_hours}h)",
            )
            return False
        return True
    except Exception as exc:
        logger.warning("[Scheduler] Heartbeat staleness check failed: {}", exc)
        return False


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

    # Seed staleness check at 6:05 AM IST (5 min after market snapshot) — T-953
    scheduler.add_job(
        lambda: _safe_job(run_seed_staleness_check, "seed_staleness_check"),
        CronTrigger(hour=6, minute=5),
        id="seed_staleness_check",
        name="Daily Seed Staleness Check",
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

    # Weekly PSF forecast — Monday 05:00 UTC (GATE-85, T-1111)
    scheduler.add_job(
        lambda: _safe_job(run_psf_forecast_update, "psf_forecast_update"),
        CronTrigger(day_of_week="mon", hour=5, minute=0),
        id="psf_forecast_update",
        name="Weekly PSF Forecast Update (numpy linear trend)",
        misfire_grace_time=3600,
    )

    # Daily DB backup — 04:00 IST (Sprint 83, GATE-83)
    scheduler.add_job(
        lambda: _safe_job(run_db_backup, "db_backup"),
        CronTrigger(hour=4, minute=0),
        id="db_backup",
        name="Daily pg_dump Backup",
        misfire_grace_time=3600,
        replace_existing=True,
    )

    # Daily backup staleness check — 06:00 UTC (GATE-83, T-1100)
    scheduler.add_job(
        lambda: _safe_job(run_backup_staleness_check, "backup_staleness_check"),
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="backup_staleness_check",
        name="Daily Backup Staleness Check (Discord alert if >26h old)",
        misfire_grace_time=3600,
    )

    # Weekly offsite backup push — Sunday 05:00 IST (GATE-93, T-1146)
    scheduler.add_job(
        lambda: _safe_job(run_offsite_backup_weekly, "offsite_backup_weekly"),
        CronTrigger(day_of_week="sun", hour=5, minute=0),
        id="offsite_backup_weekly",
        name="Weekly Offsite Backup Push (rclone + verify + Discord alert)",
        misfire_grace_time=7200,
    )

    # Weekly prediction ledger check — Monday 06:00 IST (GATE-93, T-1148)
    scheduler.add_job(
        lambda: _safe_job(run_ledger_check_weekly, "ledger_check_weekly"),
        CronTrigger(day_of_week="mon", hour=6, minute=0),
        id="ledger_check_weekly",
        name="Weekly Prediction Ledger Check (resolve + Discord summary)",
        misfire_grace_time=3600,
    )

    # Daily eProcurement Karnataka tender scan — 07:00 IST (GATE-93, T-1149)
    scheduler.add_job(
        lambda: _safe_job(run_tender_daily_scan, "tender_daily_scan"),
        CronTrigger(hour=7, minute=0),
        id="tender_daily_scan",
        name="Daily Karnataka eProcurement Tender Scan",
        misfire_grace_time=3600,
    )

    # Weekly LA notification gazette scan — Sunday 06:00 IST (GATE-93, T-1150)
    scheduler.add_job(
        lambda: _safe_job(run_la_notification_scan, "la_notification_scan"),
        CronTrigger(day_of_week="sun", hour=6, minute=0),
        id="la_notification_scan",
        name="Weekly LA Notification Gazette Scan",
        misfire_grace_time=7200,
    )

    # Daily LLS Compliance Calendar check — 08:00 IST (T-704)
    scheduler.add_job(
        lambda: _safe_job(run_compliance_check, "compliance_check"),
        CronTrigger(hour=8, minute=0),
        id="compliance_check",
        name="Daily LLS Compliance Calendar Check",
        misfire_grace_time=3600,
    )

    # Daily locality validation — 06:10 IST (after market snapshot at 06:00)
    scheduler.add_job(
        lambda: _safe_job(run_locality_validation, "locality_validation"),
        CronTrigger(hour=6, minute=10),
        id="locality_validation",
        name="Daily Locality Alias Validation (R06/R15)",
        misfire_grace_time=3600,
    )

    # FinBERT sentiment repair — 03:30 UTC (GATE-79)
    scheduler.add_job(
        lambda: _safe_job(run_finbert_sentiment_repair, "finbert_sentiment_repair"),
        CronTrigger(hour=3, minute=30, timezone="UTC"),
        id="finbert_sentiment_repair",
        name="FinBERT Sentiment Repair (null score retry)",
        misfire_grace_time=3600,
    )

    # Portal scout canary check — 03:00 UTC (GATE-79)
    scheduler.add_job(
        lambda: _safe_job(run_portal_scout_canary_check, "portal_scout_canary_check"),
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="portal_scout_canary_check",
        name="Portal Scout Canary (zero listing alert)",
        misfire_grace_time=3600,
    )

    # Daily GV freshness check — 06:12 IST (after locality validation) — GATE-78
    scheduler.add_job(
        lambda: _safe_job(run_gv_freshness_check, "gv_freshness_check"),
        CronTrigger(hour=6, minute=12),
        id="gv_freshness_check",
        name="Daily GV Freshness Check (Discord alert on stale data)",
        misfire_grace_time=3600,
    )

    # Weekly competitive pulse digest — Monday 01:00 UTC ≈ 06:30 IST ≈ 07:00 IST (T-976)
    scheduler.add_job(
        lambda: _safe_job(weekly_competitive_digest, "competitive_pulse_monday"),
        CronTrigger(day_of_week="mon", hour=1, minute=0, timezone="UTC"),
        id="competitive_pulse_monday",
        name="Monday Competitive Intel Pulse Digest",
        misfire_grace_time=3600,
    )

    # Weekly PR brief digest — Monday 02:00 UTC ≈ 07:30 IST (Sprint 59, T-999)
    # Gated by SCHEDULER_ENABLE_ORG_SIM (Sprint 91 diet — GATE-91)
    if SCHEDULER_ENABLE_ORG_SIM:
        scheduler.add_job(
            lambda: _safe_job(weekly_pr_brief, "weekly_pr_brief"),
            CronTrigger(day_of_week="mon", hour=2, minute=0, timezone="UTC"),
            id="weekly_pr_brief",
            name="Monday PR Brief Digest (Brand Mentions + LinkedIn)",
            misfire_grace_time=3600,
        )

    # Weekly process audit — Sunday 03:00 UTC (Sprint 61, T-1011)
    # Gated by SCHEDULER_ENABLE_ORG_SIM (Sprint 91 diet — GATE-91)
    if SCHEDULER_ENABLE_ORG_SIM:
        scheduler.add_job(
            lambda: _safe_job(weekly_process_audit, "weekly_process_audit"),
            CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="UTC"),
            id="weekly_process_audit",
            name="Weekly Process Audit (LogAnalyst → Optimizer → Runbook)",
            misfire_grace_time=7200,
        )

    # GCC daily scan — 08:00 IST = 02:30 UTC (Sprint 67 — GATE-71, T-1021)
    scheduler.add_job(
        lambda: _safe_job(run_gcc_daily_scan, "gcc_daily_scan"),
        CronTrigger(hour=2, minute=30, timezone="UTC"),
        id="gcc_daily_scan",
        name="GCC Daily Scan (seed + news scan → discord alerts for L1/L2)",
        misfire_grace_time=3600,
    )

    # GCC weekly digest — Monday 02:00 UTC = 07:30 IST (Sprint 67 — GATE-71, T-1022)
    scheduler.add_job(
        lambda: _safe_job(run_gcc_weekly_digest, "gcc_weekly_digest"),
        CronTrigger(day_of_week="mon", hour=2, minute=0, timezone="UTC"),
        id="gcc_weekly_digest",
        name="Monday GCC Weekly Digest → Discord intel channel",
        misfire_grace_time=3600,
    )

    # GCC hiring snapshot — Thursday 03:00 UTC = 08:30 IST (Sprint 94 — GATE-94, T-1152)
    scheduler.add_job(
        lambda: _safe_job(run_gcc_hiring_snapshot, "gcc_hiring_snapshot"),
        CronTrigger(day_of_week="thu", hour=3, minute=0, timezone="UTC"),
        id="gcc_hiring_snapshot",
        name="Weekly GCC Job Posting Snapshot (Naukri) → gcc_hiring_snapshots table",
        misfire_grace_time=3600,
    )

    # DC conversion scan — Daily 09:30 IST = 04:00 UTC (Sprint 94 — GATE-94, T-1153)
    scheduler.add_job(
        lambda: _safe_job(run_dc_conversion_scan, "dc_conversion_scan"),
        CronTrigger(hour=4, minute=0, timezone="UTC"),
        id="dc_conversion_scan",
        name="Daily DC Conversion Scan (Bhoomi portal → dc_conversions table)",
        misfire_grace_time=3600,
    )

    # Govt policy daily scan — 06:30 IST = 01:00 UTC (Sprint 75 — GATE-75, T-1050)
    scheduler.add_job(
        lambda: _safe_job(run_govt_policy_daily_scan, "govt_policy_daily_scan"),
        CronTrigger(hour=1, minute=0, timezone="UTC"),
        id="govt_policy_daily_scan",
        name="Govt/Policy Daily Scan → upsert events + Discord alerts for high-impact NB events",
        misfire_grace_time=3600,
    )

    # Govt policy weekly digest — Monday 02:30 UTC = 08:00 IST (Sprint 75 — GATE-75, T-1050)
    scheduler.add_job(
        lambda: _safe_job(run_govt_policy_weekly_digest, "govt_policy_weekly_digest"),
        CronTrigger(day_of_week="mon", hour=2, minute=30, timezone="UTC"),
        id="govt_policy_weekly_digest",
        name="Monday Govt/Policy Weekly Digest → Discord govt_policy_scout channel",
        misfire_grace_time=3600,
    )

    # Post-crew optimizer hook — runs after successful crew completion (T-1005)
    # Called explicitly from Stage3 completion via subprocess callback
    scheduler.add_job(
        lambda: _safe_job(run_post_crew_optimizer_hook, "post_crew_optimizer_hook"),
        CronTrigger(hour=4, minute=0),  # fallback: run daily at 4am UTC if not triggered inline
        id="post_crew_optimizer_hook",
        name="Post-Crew Optimizer Hook (daily fallback)",
        misfire_grace_time=3600,
    )

    # Monthly CEO letter — 1st of month at 04:00 UTC (Sprint 62, T-1019)
    # Gated by SCHEDULER_ENABLE_ORG_SIM (Sprint 91 diet — GATE-91)
    if SCHEDULER_ENABLE_ORG_SIM:
        scheduler.add_job(
            lambda: _safe_job(monthly_ceo_letter, "monthly_ceo_letter"),
            CronTrigger(day=1, hour=4, minute=0, timezone="UTC"),
            id="monthly_ceo_letter",
            name="Monthly CEO Letter (PerformanceDigest + agent_runs summary)",
            misfire_grace_time=7200,
        )

    # Monthly mobility scout — 1st of month at 01:00 IST (Sprint 74, T-1039)
    scheduler.add_job(
        lambda: _safe_job(run_mobility_scout, "run_mobility_scout"),
        CronTrigger(day=1, hour=1, minute=0),
        id="run_mobility_scout",
        name="Monthly Mobility Scout (accessibility_scores refresh)",
        misfire_grace_time=7200,
    )

    # Bhoomi auto-survey — daily at 03:30 UTC = 09:00 IST (Sprint 80, T-1080)
    scheduler.add_job(
        lambda: _safe_job(run_bhoomi_auto_survey, "bhoomi_auto_survey"),
        CronTrigger(hour=3, minute=30, timezone="UTC"),
        id="bhoomi_auto_survey",
        name="Daily Bhoomi Auto-Survey from RERA survey numbers (T-1080)",
        misfire_grace_time=3600,
    )

    # Weekly intel digest — Monday 01:30 UTC = 07:00 IST (Sprint 76, T-1057)
    scheduler.add_job(
        lambda: _safe_job(run_weekly_intel_digest, "weekly_intel_digest"),
        CronTrigger(day_of_week="mon", hour=1, minute=30, timezone="UTC"),
        id="weekly_intel_digest",
        name="Monday Weekly Intel Digest → Discord intel_reports",
        misfire_grace_time=3600,
    )

    # Monthly intel digest — 1st of month 02:00 UTC = 07:30 IST (Sprint 76, T-1057)
    scheduler.add_job(
        lambda: _safe_job(run_monthly_intel_digest, "monthly_intel_digest"),
        CronTrigger(day=1, hour=2, minute=0, timezone="UTC"),
        id="monthly_intel_digest",
        name="Monthly Intel Digest → Discord intel_reports",
        misfire_grace_time=7200,
    )

    # Weekly alembic check — Sunday 03:00 UTC (GATE-88, T-1122)
    scheduler.add_job(
        lambda: _safe_job(run_alembic_check, "alembic_weekly_check"),
        CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="UTC"),
        id="alembic_weekly_check",
        name="Weekly Alembic Check (schema drift detection)",
        misfire_grace_time=3600,
        replace_existing=True,
    )

    # Daily data floor check — 01:00 UTC = 06:30 IST (GATE-89, T-1128)
    scheduler.add_job(
        lambda: _safe_job(run_data_floor_check, "data_floor_check"),
        CronTrigger(hour=1, minute=0, timezone="UTC"),
        id="data_floor_check",
        name="Daily Data Floor Check (Discord alert on live RERA breach)",
        misfire_grace_time=3600,
    )

    # Weekly Kaveri deed extraction — Sunday 03:00 IST (GATE-91, T-1139)
    scheduler.add_job(
        lambda: _safe_job(run_kaveri_deeds_weekly, "kaveri_deeds_weekly"),
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="kaveri_deeds_weekly",
        name="Weekly Kaveri Deed Extraction (inbox + live → Discord summary)",
        misfire_grace_time=7200,
    )

    # Nightly parcel linker — 02:30 IST (GATE-92, T-1142)
    scheduler.add_job(
        lambda: _safe_job(run_parcel_linker_nightly, "parcel_linker_nightly"),
        CronTrigger(hour=2, minute=30),
        id="parcel_linker_nightly",
        name="Nightly Parcel Linker (scan survey_no → parcels upsert)",
        misfire_grace_time=3600,
    )

    # Weekly assembly detection — Sunday 03:30 IST (30 min buffer after kaveri_deeds_weekly)
    # 30-min gap ensures deed extraction completes before assembly detection scans new deeds.
    scheduler.add_job(
        lambda: _safe_job(run_assembly_detection, "assembly_detection"),
        CronTrigger(day_of_week="sun", hour=3, minute=30),
        id="assembly_detection",
        name="Weekly Land Assembly Detection (after Kaveri deed extraction)",
        misfire_grace_time=7200,
    )

    # Scheduler heartbeat — every 30 min to prove scheduler is alive (T-1158)
    scheduler.add_job(
        lambda: _safe_job(run_scheduler_heartbeat, "scheduler_heartbeat"),
        "interval", minutes=30,
        id="scheduler_heartbeat",
        name="Scheduler Heartbeat (writes agent_runs every 30min)",
        replace_existing=True,
    )

    if SCHEDULER_DRY_RUN:
        jobs = scheduler.get_jobs()
        logger.info("SCHEDULER_DRY_RUN mode: {} jobs registered, exiting 0", len(jobs))
        print(json.dumps({"status": "dry_run", "job_count": len(jobs)}))
        sys.exit(0)

    logger.info("RE_OS Scheduler started")
    logger.info("Jobs scheduled:")
    logger.info("  01:00 AM IST — Daily pg_dump backup [T-904]")
    logger.info("  02:00 AM IST — Unified Ingest Engine (all scrapers)")
    logger.info("  03:00 AM IST — Opportunity scoring (GATE-47)")
    logger.info("  03:00 AM IST — Portal scout canary check (zero-listing alert) [GATE-79]")
    logger.info("  03:30 AM IST — FinBERT sentiment repair (null score retry) [GATE-79]")
    logger.info("  04:30 AM IST — Intel embedding index (ChromaDB)")
    logger.info("  05:00 AM IST — News sentiment scoring (FinBERT)")
    logger.info("  06:00 AM IST — Market snapshots")
    logger.info("  06:05 AM IST — Seed staleness check (T-953)")
    logger.info("  06:10 AM IST — Locality alias validation (R06/R15)")
    logger.info("  06:15 AM IST — Distressed developer scan (JD/JV targets)")
    logger.info("  08:00 AM IST — LLS Compliance Calendar check [T-704]")
    logger.info("  Sunday 07:00 IST — Weekly PSF forecast (LGBM) [T-765]")
    logger.info("  Every 1 hr  — Board session recovery (T-315)")
    logger.info("  Monday 03:00 UTC — Agent memory decay")
    logger.info("  Monday 03:30 UTC — Memory conflict detection")
    logger.info("  Monday 03:45 IST — BERTScore quality evaluation")
    logger.info("  Monday 04:00 IST — Weekly memory digest (top-5 facts)")
    logger.info("  Monday 06:30 IST — Competitive intel pulse digest [T-976]")
    _frozen_tag = "🧊 FROZEN" if not SCHEDULER_ENABLE_ORG_SIM else ""
    if _frozen_tag:
        logger.info("  Monday 07:30 IST — PR brief digest (brand mentions + LinkedIn) [T-999] 🧊 FROZEN (GATE-91)")
        logger.info("  Sunday 08:30 IST — Process automation audit (LogAnalyst + Optimizer + Runbook) [T-1011] 🧊 FROZEN (GATE-91)")
        logger.info("  1st of month 09:30 IST — Monthly CEO letter (PerformanceDigest + agent_runs) [T-1019] 🧊 FROZEN (GATE-91)")
    logger.info("  Daily 08:00 IST — GCC daily scan (seed + news → L1/L2 alerts) [T-1021]")
    logger.info("  Monday 07:30 IST — GCC weekly digest (pipeline → Discord intel) [T-1022]")
    logger.info("  Thursday 08:30 IST — GCC hiring snapshot (Naukri job postings per employer → gcc_hiring_snapshots) [T-1152]")
    logger.info("  Daily 09:30 IST — DC conversion scan (Bhoomi land-use changes → dc_conversions) [T-1153]")
    logger.info("  1st of month 06:30 IST — Monthly mobility scout (accessibility_scores) [T-1039]")
    logger.info("  06:30 IST daily — Govt/Policy daily scan (events→Discord alerts) [T-1050]")
    logger.info("  Monday 08:00 IST — Govt/Policy weekly digest (north_bengaluru_score→Discord) [T-1050]")
    logger.info("  Monday 07:00 IST — Weekly intel digest (PSF delta + RERA + competitive) → Discord intel_reports [T-1057]")
    logger.info("  1st of month 07:30 IST — Monthly intel digest (MoM PSF + absorption + LLM synthesis) → Discord [T-1057]")
    logger.info("  Daily 09:00 IST — Bhoomi auto-survey from RERA survey numbers (T-1080)")
    logger.info("  06:30 IST daily — Data floor check (Discord alert on live RERA breach) [T-1128]")
    logger.info("  Sunday 03:00 IST — Kaveri deed weekly extraction (inbox + live → Discord) [T-1139]")
    logger.info("  02:30 IST nightly — Parcel linker (survey_no → parcels) [T-1142]")
    logger.info("  Sunday 03:30 IST — Land assembly detection (30 min buffer after deed extraction) [T-1143]")
    logger.info("  Sunday 05:00 IST — Weekly offsite backup push (rclone + verify) [T-1146]")
    logger.info("  Monday 06:00 IST — Weekly prediction ledger check (resolve + Discord) [T-1148]")
    logger.info("  Daily 07:00 IST — Karnataka eProcurement tender scan [T-1149]")
    logger.info("  Sunday 06:00 IST — Weekly LA notification gazette scan [T-1150]")
    logger.info(f"Active jobs: {[j.id for j in scheduler.get_jobs()]}")

    scheduler.start()

