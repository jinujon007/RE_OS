"""
RE_OS — Intel Scheduler Jobs
───────────────────────────
Extracted from _old_scheduler.py (brain: Kilo Code).
"""
import threading
from collections.abc import Callable
from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine
from config.settings import TARGET_MARKETS

_ingest_running = threading.Event()

__all__ = [
    "run_intel_embedding_index",
    "run_news_sentiment_scoring",
    "run_market_snapshot",
    "run_distressed_developer_scan",
    "run_ingest_engine",
    "run_vel_weekly_market_update",
    "run_conflict_detection",
    "run_opportunity_scoring",
    "run_psf_forecast_update",
    "run_locality_validation",
    "run_finbert_sentiment_repair",
    "run_portal_scout_canary_check",
    "run_gv_freshness_check",
    "run_gcc_daily_scan",
    "run_gcc_weekly_digest",
    "run_gcc_hiring_snapshot",
    "run_dc_conversion_scan",
    "run_govt_policy_daily_scan",
    "run_govt_policy_weekly_digest",
    "run_post_crew_optimizer_hook",
    "register_jobs",
]


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
        from concurrent.futures import ThreadPoolExecutor, as_completed

        written = 0
        failed = 0
        BATCH_LIMIT = 1000
        PAGE_SIZE = 200
        offset = 0

        while offset < BATCH_LIMIT:
            with get_engine().connect() as conn:
                rows = conn.execute(
                    text("""
                    SELECT id, title, key_insight
                    FROM news_articles
                    WHERE sentiment_score IS NULL
                      AND title IS NOT NULL
                      AND title != ''
                    ORDER BY created_at DESC
                    LIMIT :lim OFFSET :off
                """),
                    {"lim": PAGE_SIZE, "off": offset},
                ).fetchall()

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

            for i in range(0, len(scored_results), 25):
                batch = scored_results[i : i + 25]
                with get_engine().begin() as conn:
                    for article_id, score, label in batch:
                        conn.execute(
                            text(
                                "UPDATE news_articles SET sentiment_score = :s, sentiment_label = :l WHERE id = :id"
                            ),
                            {"s": score, "l": label, "id": article_id},
                        )
                        written += 1

            offset += PAGE_SIZE

        logger.info(f"[Scheduler] Sentiment scoring: {written} scored, {failed} failed")
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

    for market in TARGET_MARKETS:
        market = market.strip()
        try:
            from utils.data_quality import DataQualityMonitor

            result = DataQualityMonitor.locality_validation_score(market)
            if result["score"] < 0.80:
                logger.warning(
                    "[Scheduler] Locality validation for %s: score=%.4f, suspect=%d, action=%s",
                    market,
                    result["score"],
                    result["suspect"],
                    result["action"],
                )
            else:
                logger.info(
                    "[Scheduler] Locality validation for %s: score=%.4f (%d/%d valid)",
                    market,
                    result["score"],
                    result["valid"],
                    result["valid"] + result["suspect"],
                )
        except Exception as e:
            logger.warning(f"  Locality validation failed for {market}: {e}")


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
                market,
                min_score=_DISTRESS_SCORE_THRESHOLD,
            )
            for dev in results:
                title = f"Distressed Developer — {dev.developer_name} ({dev.market})"
                from config.scheduler.maintenance_jobs import _bd_already_alerted
                if _bd_already_alerted(title, cooldown_hours=168):
                    logger.info(
                        f"[DistressedDev] Dedup skip: {dev.developer_name} ({dev.market})"
                    )
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
        RERAPlugin,
        IGRPlugin,
        KaveriBhoomiPlugin,
        PortalPlugin,
        DeveloperPlugin,
        NewsPlugin,
        DistressedPlugin,
        BBMPPlugin,
        KaveriDeedsPlugin,
        KaveriForm17Plugin,
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
        delta = current_time_minutes - sched_minutes
        return delta >= -5  # type: ignore[no-any-return]

    engine = IngestEngine(max_workers=3, global_rate=3.0)
    all_plugins = [
        RERAPlugin(),
        IGRPlugin(),
        KaveriBhoomiPlugin(),
        PortalPlugin(),
        DeveloperPlugin(),
        NewsPlugin(),
        DistressedPlugin(),
        BBMPPlugin(),
        KaveriDeedsPlugin(),
        KaveriForm17Plugin(),
    ]

    for p in all_plugins:
        if _plugin_should_run(p.plugin_id):
            engine.register(p)
            logger.info(
                "[Scheduler] IngestEngine registered: {} (schedule active)", p.plugin_id
            )
        else:
            logger.info(
                "[Scheduler] IngestEngine skipped: {} (not in schedule today)",
                p.plugin_id,
            )

    if not engine.registered_plugins:
        logger.info(
            "[Scheduler] IngestEngine: no plugins scheduled for today at this hour"
        )
        return

    _ingest_running.set()
    try:
        report = engine.run_all(markets=TARGET_MARKETS)
        logger.info("[Scheduler] IngestEngine complete: {}", report.summary())
        for s in report.failed_plugins:
            logger.warning(
                "[Scheduler] Plugin failed: {}/{} — {}",
                s.plugin_id,
                s.market,
                s.error_message,
            )
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
                        logger.warning(
                            f"[ConflictDetection] Discord send failed: {exc}"
                        )
    except Exception as exc:
        logger.warning(f"[Scheduler] Conflict detection failed: {exc}")


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
                "check DB for surveys (surveys table may be empty)",
                elapsed,
                markets,
            )
            return

        logger.info(
            "[Scheduler] Opportunity scoring: {} scored across {} in {:.1f}s",
            len(results),
            markets,
            elapsed,
        )

        urgent = [r for r in results if r.score >= 0.80]
        for r in sorted(urgent, key=lambda x: x.score, reverse=True)[:10]:
            title = f"URGENT — {r.survey_no} ({r.micro_market_id[:8]})"
            from config.scheduler.maintenance_jobs import _bd_already_alerted
            if _bd_already_alerted(title, cooldown_hours=23):
                logger.info(
                    "[Scheduler] BD dedup: skipping URGENT {} (sent within 23h)",
                    r.survey_no,
                )
                continue
            alert_msg = (
                f"**{r.survey_no}**\n"
                f"Score: **{r.score:.4f}** | IRR: {r.components.irr_score:.3f} "
                f"Legal: {r.components.legal_score:.3f} "
                f"Timing: {r.components.timing_score:.3f}\n"
                f"Action: {r.next_action}"
            )
            logger.info(
                "[Scheduler] URGENT opportunity: {} score={:.4f}", r.survey_no, r.score
            )
            try:
                send("bd_opportunities", title, alert_msg)
            except Exception as exc:
                logger.warning("[Scheduler] URGENT alert Discord failed: {}", exc)

        priority = [r for r in results if 0.60 < r.score < 0.80]
        if priority:
            title_p = "Priority Opportunities — Review"
            from config.scheduler.maintenance_jobs import _bd_already_alerted
            if _bd_already_alerted(title_p, cooldown_hours=23):
                logger.info(
                    "[Scheduler] BD dedup: skipping PRIORITY summary (sent within 23h)"
                )
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
            logger.info(
                "[Scheduler] WATCH opportunities: {} — {}",
                len(watch),
                watch_summary[:200],
            )

    except Exception as exc:
        elapsed = _time.time() - job_start
        logger.warning(
            "[Scheduler] Opportunity scoring failed after {:.1f}s: {}", elapsed, exc
        )


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
                    conf_low = (
                        getattr(result, f"conf_low_{horizon}m", None)
                        if horizon in (3, 6, 12)
                        else None
                    )
                    conf_high = (
                        getattr(result, f"conf_high_{horizon}m", None)
                        if horizon in (3, 6, 12)
                        else None
                    )
                    upserts.append(
                        {
                            "market": market,
                            "fdate": today,
                            "horizon": horizon,
                            "current_psf": result.current_psf,
                            "forecast_psf": psf_val,
                            "conf_low": conf_low,
                            "conf_high": conf_high,
                            "trend": result.trend_direction,
                            "slope": result.slope_pct_per_month,
                            "points": result.data_points,
                            "mae": result.mae_pct,
                        }
                    )
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
                logger.info(
                    "[Scheduler] PSF forecast for {}: trend={}, 6m={}, MAE={:.1f}%",
                    market,
                    result.trend_direction,
                    result.forecast_6m,
                    result.mae_pct,
                )
            else:
                logger.warning(
                    "[Scheduler] PSF forecast skipped for {}: status={}",
                    market,
                    result.status,
                )
        except Exception as exc:
            logger.warning("[Scheduler] PSF forecast failed for {}: {}", market, exc)

    if results:
        try:
            from utils.discord_notifier import send_forecast_digest

            send_forecast_digest(results)
        except Exception as exc:
            logger.warning("[Scheduler] PSF forecast digest failed: {}", exc)


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
                    market,
                    result["score"],
                    result["suspect"],
                )
            logger.info(
                "[Scheduler] Locality validation for %s: score=%.4f, action=%s",
                market,
                result["score"],
                result["action"],
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
            rows = conn.execute(
                text("""
                SELECT id, COALESCE(summary, title, '') AS content FROM news_articles
                WHERE sentiment_score IS NULL
                  AND created_at >= NOW() - INTERVAL '7 days'
                LIMIT :limit
            """),
                {"limit": FINBERT_REPAIR_BATCH_LIMIT},
            ).fetchall()

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
                    _time.sleep(2 * (2**attempt))

            with engine.begin() as conn:
                if score is not None:
                    label = label_from_score(score)
                    conn.execute(
                        text(
                            "UPDATE news_articles SET sentiment_score = :s, sentiment_label = :l WHERE id = :id"
                        ),
                        {"s": score, "l": label, "id": article_id},
                    )
                    updated += 1
                else:
                    conn.execute(
                        text(
                            "UPDATE news_articles SET sentiment_score = -99.0 WHERE id = :id AND sentiment_score IS NULL"
                        ),
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
            title = f"portal_canary_{market}"
            from config.scheduler.digest_jobs import _digest_already_sent
            if _digest_already_sent(title, cooldown_hours=23):
                logger.info(f"[Canary] {market}: skipped — alert sent within 23h")
                continue
            with engine.connect() as conn:
                row = conn.execute(
                    text("""
                    SELECT COUNT(*) FROM listings
                    WHERE data_source = 'portal_scout'
                      AND created_at >= NOW() - INTERVAL '24 hours'
                      AND micro_market_id = (SELECT id FROM micro_markets WHERE name ILIKE :m)
                """),
                    {"m": f"%{market}%"},
                ).fetchone()
            count = row[0] if row else 0
            if count == 0:
                from utils.discord_notifier import send_scraper_alert

                send_scraper_alert(
                    market, "portal_scout", "ZERO_LISTINGS_CANARY", record_count=count
                )
                from config.scheduler.digest_jobs import _mark_digest_sent
                _mark_digest_sent(f"portal_canary_{market}")
                logger.warning(
                    f"[Canary] {market}: 0 new portal listings in 24h — check portal connectivity; verify proxy/network; alert sent to Discord"
                )
            else:
                logger.info(
                    f"[Canary] {market}: {count} new portal listings in 24h — OK"
                )
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
            futures = {
                pool.submit(DataQualityMonitor.check_gv_freshness, m): m
                for m in markets
            }
            for future in as_completed(futures):
                m = futures[future]
                try:
                    results[m] = future.result()
                except Exception as exc:
                    logger.warning(
                        "[Scheduler] GV freshness check failed for {}: {}", m, exc
                    )
                    results[m] = {
                        "alert_needed": False,
                        "gazette_year": None,
                        "months_stale": None,
                    }

        for market, result in results.items():
            if result.get("alert_needed"):
                logger.warning(
                    "[Scheduler] GV fresh STALE for {}: gazette {}, portal {}, {} months",
                    market,
                    result.get("gazette_year"),
                    result.get("portal_year"),
                    result.get("months_stale"),
                )
            else:
                logger.info(
                    "[Scheduler] GV fresh OK for {}: gazette {}, portal {}, {} months",
                    market,
                    result.get("gazette_year"),
                    result.get("portal_year"),
                    result.get("months_stale"),
                )

        try:
            from config.metrics import data_quality_checks_total

            for market, result in results.items():
                status = "stale" if result.get("alert_needed") else "fresh"
                data_quality_checks_total.labels(
                    market=market, source="gv_freshness", status=status
                ).inc()
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
            n_l,
            n_m,
            n_a,
        )
    except Exception as exc:
        logger.warning("[Scheduler] Competitive digest failed: {}", exc)


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
                        conn.execute(
                            _text("""
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
                        """),
                            d,
                        )
                logger.info(
                    "[Scheduler] GCC scan {}: {} records upserted", market, len(records)
                )
            except Exception as exc:
                logger.warning("[Scheduler] GCC scan failed for {}: {}", market, exc)

        intel = GCCIntel(caller="scheduler")
        pending = intel.get_pending_alerts()
        for evt in pending:
            try:
                evt_dict = (
                    dataclasses.asdict(evt)
                    if hasattr(dataclasses, "asdict")
                    else evt.__dict__
                )
                send_gcc_alert(evt_dict)
                intel.mark_alert_fired(evt.canonical_id)
            except Exception as exc:
                logger.warning(
                    "[Scheduler] GCC alert failed for {}: {}", evt.canonical_id, exc
                )

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

        corridor_scores: dict[str, float] = {}
        for market in [m.strip() for m in TARGET_MARKETS]:
            result = intel.get_gcc_score(market)
            if result.corridor:
                corridor_scores[result.corridor] = result.gcc_north_norm

        events = intel.get_events(
            corridors=list(_MARKET_TO_CORRIDOR.values()),
            maturity_levels=[1, 2, 3],
            include_negative=False,
            limit=10,
        )

        events_as_dicts = []
        for evt in events:
            try:
                d = (
                    dataclasses.asdict(evt)
                    if hasattr(dataclasses, "asdict")
                    else evt.__dict__
                )
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
        logger.info(
            "[Scheduler] GCC hiring snapshot done — {}/{} records written",
            successes,
            len(results),
        )
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
        logger.info(
            "[Scheduler] DC conversion scan done — {}/{} records written",
            successes,
            len(results),
        )
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
                        conn.execute(
                            _text("""
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
                        """),
                            d,
                        )
                logger.info(
                    "[Scheduler] Govt policy scan {}: {} records",
                    market,
                    len(records),
                )

                for rec in records:
                    d = rec.data
                    if (
                        d.get("is_north_bengaluru")
                        and (d.get("impact_score") or 0) >= 7
                    ):
                        send_govt_policy_alert(d)
            except Exception as exc:
                logger.warning(
                    "[Scheduler] Govt policy scan failed for {}: {}",
                    market,
                    exc,
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


def run_post_crew_optimizer_hook():
    """Run after market_intel_crew completes — generates optimizer report and creates tasks for HIGH findings."""
    logger.info("[Scheduler] Post-crew optimizer hook starting")
    try:
        from utils.optimizer_report import generate_report
        from utils.db import get_engine
        from sqlalchemy import text

        report = generate_report(days=1)

        high_findings = [
            f for f in report.redundancy_findings if f.get("severity") == "HIGH"
        ]

        if high_findings:
            for finding in high_findings[:3]:
                recommendation = finding.get(
                    "recommendation", "Review HIGH severity finding"
                )
                try:
                    with get_engine().begin() as conn:
                        conn.execute(
                            text("""
                                INSERT INTO tasks (title, owner, priority, source_type, source_id)
                                VALUES (:t, 'optimizer', 'high', 'optimizer_finding', :sid)
                            """),
                            {
                                "t": recommendation[:100],
                                "sid": finding.get("agent", "unknown"),
                            },
                        )
                    report.auto_tasks_created += 1
                except Exception as exc:
                    logger.warning(
                        "[Scheduler] Failed to create task for findings: {}", exc
                    )

            import os

            output_base = (
                "/app/outputs/optimizer"
                if os.path.exists("/app")
                else "outputs/optimizer"
            )
            report_path = os.path.join(output_base, f"{report.report_date}.md")
            os.makedirs(output_base, exist_ok=True)
            report.write(report_path)

        logger.info(
            "[Scheduler] Optimizer hook: {} high findings, {} tasks created",
            len(high_findings),
            report.auto_tasks_created,
        )
    except Exception as exc:
        logger.error("[Scheduler] Post-crew optimizer hook failed: {}", exc)


# ── VEL Weekly Market Update (GATE-171, T-1542) ───────────────────────

_VEL_WEEKLY_RUNNING = threading.Event()


def run_vel_weekly_market_update() -> None:
    """Weekly VEL market intelligence update → Obsidian note.

    Gathers PSF trend, competitor data, STRR signal, assembly activity,
    and corridor score for the VEL project. Writes to Obsidian.
    Scheduled Mon 01:30 UTC (07:00 IST).
    Skips if previous run is still in progress.
    """
    if not _VEL_WEEKLY_RUNNING.set():
        logger.info("[VEL Weekly] Previous run still in progress — skipping")
        return
    try:
        _run_vel_weekly_market_update_impl()
    finally:
        _VEL_WEEKLY_RUNNING.clear()


def _run_vel_weekly_market_update_impl() -> None:
    from datetime import date
    from utils.db import get_engine
    from utils.obsidian_sync import write_note

    engine = get_engine()
    today = date.today().isoformat()

    avg_psf: float | None = None
    competitors: list[dict] = []
    strr_signal: str | None = None
    assembly_count: int = 0
    corridor_name: str | None = None
    corridor_composite: float | None = None

    # (0) Resolve villages for Hebbal and Yelahanka
    target_villages: list[str] = []
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT village FROM v_deed_village_priority
                WHERE market IN ('Hebbal', 'Yelahanka')
            """)).fetchall()
            target_villages = [str(r[0]) for r in rows if r[0]]
    except Exception as exc:
        logger.warning("[VEL Weekly] village resolution failed: {}", exc)

    # (1) avg PSF for Hebbal + Yelahanka villages
    if target_villages:
        try:
            with engine.begin() as conn:
                row = conn.execute(text("""
                    SELECT AVG(rt.psf)
                    FROM registered_transactions rt
                    WHERE rt.village = ANY(:villages)
                      AND rt.psf IS NOT NULL
                      AND rt.psf > 1000
                      AND rt.psf < 50000
                """), {"villages": target_villages}).scalar()
                if row is not None:
                    avg_psf = round(float(row), 0)
        except Exception as exc:
            logger.warning("[VEL Weekly] avg PSF query failed: {}", exc)

    # (2) Competitors in Hebbal/Yelahanka markets (T-1543)
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("""
                SELECT rp.project_name, d.name AS developer_name,
                       rp.total_units, rp.price_avg_psf, rp.project_status
                FROM rera_projects rp
                JOIN developers d ON d.id = rp.developer_id
                JOIN micro_markets mm ON mm.id = rp.micro_market_id
                WHERE mm.name IN ('Hebbal', 'Yelahanka')
                  AND (d.grade = 'A' OR rp.total_units > 200)
                ORDER BY rp.total_units DESC
                LIMIT 10
            """)).fetchall()
        competitors = [
            {
                "name": str(r[0] or ""),
                "developer": str(r[1] or ""),
                "units": int(r[2]) if r[2] else 0,
                "avg_psf": round(float(r[3]), 0) if r[3] else None,
                "status": str(r[4] or ""),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("[VEL Weekly] competitor query failed: {}", exc)

    # (3) STRR signal
    try:
        from utils.strr_overlay import STRROverlay
        overlay = STRROverlay()
        stations = overlay.stations_near("Hebbal")
        strr_signal = STRROverlay.transit_signal(stations)
    except Exception as exc:
        logger.warning("[VEL Weekly] STRR signal failed: {}", exc)

    # (4) Assembly clusters
    try:
        from utils.assembly_detector import AssemblyDetector
        detector = AssemblyDetector()
        hc = detector.detect_clusters("Hebbal")
        yc = detector.detect_clusters("Yelahanka")
        assembly_count = len(hc) + len(yc)
    except Exception as exc:
        logger.warning("[VEL Weekly] assembly query failed: {}", exc)

    # (5) Corridor score
    try:
        from utils.corridor_scorer import CorridorScorer
        scorer = CorridorScorer()
        scores = scorer.score_all()
        for s in scores:
            if s.get("market", "").lower() == "hebbal":
                corridor_name = s.get("corridor", "")
                corridor_composite = s.get("composite_score")
                break
    except Exception as exc:
        logger.warning("[VEL Weekly] corridor score failed: {}", exc)

    # Build Obsidian note
    psf_line = f"**Avg PSF:** ₹{avg_psf:,.0f}" if avg_psf else "**Avg PSF:** N/A"
    comp_lines = "\n".join(
        f"| {c['name']} | {c['developer']} | {c['units']} | ₹{c['avg_psf']:,.0f} | {c['status']} |"
        for c in competitors if c.get("avg_psf")
    )
    comp_header = "### Competitors Within Hebbal/Yelahanka\n| Project | Developer | Units | PSF | Status |\n|---|---|---|---|---|"
    comp_section = f"{comp_header}\n{comp_lines}" if comp_lines else f"{comp_header}\nNo competitor data available."
    strr_line = f"**STRR Signal:** {strr_signal}" if strr_signal else "**STRR Signal:** N/A"
    assembly_line = f"**Assembly Clusters:** {assembly_count} (Hebbal + Yelahanka)"
    corridor_line = f"**Hebbal Corridor:** {corridor_name} (composite={corridor_composite})" if corridor_name else "**Hebbal Corridor:** N/A"

    recommended_lo = round(avg_psf * 0.9, 0) if avg_psf else "N/A"
    recommended_hi = round(avg_psf * 1.15, 0) if avg_psf else "N/A"
    pricing_line = f"**Recommended PSF Range:** ₹{recommended_lo} – ₹{recommended_hi}"

    content = f"""---
type: wiki
area: lls
project: VEL
ai_generated: true
last_confirmed: {today}
---

# VEL Weekly Market Update — {today}

{psf_line}

{strr_line}

{assembly_line}

{corridor_line}

{pricing_line}

---

{comp_section}
"""
    # Vault rule: AI-generated files outside 01 Wiki/ carry the (CAI) prefix.
    path = "03 LLS/02 Projects/VEL/(CAI) weekly_intel.md"
    result = write_note(path, content)
    if result:
        logger.info("[VEL Weekly] Obsidian note written: {}", result)
    else:
        logger.warning("[VEL Weekly] Obsidian write returned empty/false")

    # Log to agent_runs
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO agent_runs (agent_name, event_type, status, micro_market, summary)
                VALUES (:agent, :event, :status, :market, :summary)
            """), {
                "agent": "vel_weekly",
                "event": "vel_weekly_market_update",
                "status": "completed",
                "market": "VEL",
                "summary": f"VEL weekly update written. PSF={avg_psf}, competitors={len(competitors)}, STRR={strr_signal}",
            })
    except Exception as exc:
        logger.warning("[VEL Weekly] agent_runs log failed: {}", exc)


def register_jobs(scheduler: BlockingScheduler, safe_job: Callable[..., object]) -> None:
    """Register intelligence-related scheduler jobs."""
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        lambda: safe_job(run_ingest_engine, "ingest_engine"),
        CronTrigger(hour=2, minute=0),
        id="ingest_engine",
        name="Unified Ingest Engine (all plugins)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_opportunity_scoring, "opportunity_scoring"),
        CronTrigger(hour=3, minute=0),
        id="opportunity_scoring",
        name="Daily Opportunity Scoring (GATE-47)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_market_snapshot, "market_snapshot"),
        CronTrigger(hour=6, minute=0),
        id="market_snapshot",
        name="Daily Market Snapshot",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_intel_embedding_index, "intel_embedding"),
        CronTrigger(hour=4, minute=30),
        id="intel_embedding",
        name="Nightly Intel Embedding Index (ChromaDB)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_news_sentiment_scoring, "news_sentiment"),
        CronTrigger(hour=5, minute=0),
        id="news_sentiment",
        name="Nightly News Sentiment Scoring (FinBERT)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_distressed_developer_scan, "distressed_dev_scan"),
        CronTrigger(hour=6, minute=15),
        id="distressed_dev_scan",
        name="Daily Distressed Developer Scan (JD/JV targets)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_conflict_detection, "conflict_detection"),
        CronTrigger(day_of_week="mon", hour=3, minute=30, timezone="UTC"),
        id="conflict_detection",
        name="Weekly Memory Conflict Detection",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_psf_forecast_update, "psf_forecast_update"),
        CronTrigger(day_of_week="mon", hour=5, minute=0),
        id="psf_forecast_update",
        name="Weekly PSF Forecast Update (numpy linear trend)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_locality_validation, "locality_validation"),
        CronTrigger(hour=6, minute=10),
        id="locality_validation",
        name="Daily Locality Alias Validation (R06/R15)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_finbert_sentiment_repair, "finbert_sentiment_repair"),
        CronTrigger(hour=3, minute=30, timezone="UTC"),
        id="finbert_sentiment_repair",
        name="FinBERT Sentiment Repair (null score retry)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_portal_scout_canary_check, "portal_scout_canary_check"),
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="portal_scout_canary_check",
        name="Portal Scout Canary (zero listing alert)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_gv_freshness_check, "gv_freshness_check"),
        CronTrigger(hour=6, minute=12),
        id="gv_freshness_check",
        name="Daily GV Freshness Check (Discord alert on stale data)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(weekly_competitive_digest, "competitive_pulse_monday"),
        CronTrigger(day_of_week="mon", hour=1, minute=0, timezone="UTC"),
        id="competitive_pulse_monday",
        name="Monday Competitive Intel Pulse Digest",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_gcc_daily_scan, "gcc_daily_scan"),
        CronTrigger(hour=2, minute=30, timezone="UTC"),
        id="gcc_daily_scan",
        name="GCC Daily Scan (seed + news scan → discord alerts for L1/L2)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_gcc_weekly_digest, "gcc_weekly_digest"),
        CronTrigger(day_of_week="mon", hour=2, minute=0, timezone="UTC"),
        id="gcc_weekly_digest",
        name="Monday GCC Weekly Digest → Discord intel channel",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_gcc_hiring_snapshot, "gcc_hiring_snapshot"),
        CronTrigger(day_of_week="thu", hour=3, minute=0, timezone="UTC"),
        id="gcc_hiring_snapshot",
        name="Weekly GCC Job Posting Snapshot (Naukri) → gcc_hiring_snapshots table",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_dc_conversion_scan, "dc_conversion_scan"),
        CronTrigger(hour=4, minute=0, timezone="UTC"),
        id="dc_conversion_scan",
        name="Daily DC Conversion Scan (Bhoomi portal → dc_conversions table)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_govt_policy_daily_scan, "govt_policy_daily_scan"),
        CronTrigger(hour=1, minute=0, timezone="UTC"),
        id="govt_policy_daily_scan",
        name="Govt/Policy Daily Scan → upsert events + Discord alerts for high-impact NB events",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_govt_policy_weekly_digest, "govt_policy_weekly_digest"),
        CronTrigger(day_of_week="mon", hour=2, minute=30, timezone="UTC"),
        id="govt_policy_weekly_digest",
        name="Monday Govt/Policy Weekly Digest → Discord govt_policy_scout channel",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_post_crew_optimizer_hook, "post_crew_optimizer_hook"),
        CronTrigger(hour=4, minute=0),
        id="post_crew_optimizer_hook",
        name="Post-Crew Optimizer Hook (daily fallback)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        lambda: safe_job(run_vel_weekly_market_update, "vel_weekly_market_update"),
        CronTrigger(day_of_week="mon", hour=1, minute=30, timezone="UTC"),
        id="vel_weekly_market_update",
        name="VEL Weekly Market Update → Obsidian (Mon 07:00 IST)",
        misfire_grace_time=3600,
    )
