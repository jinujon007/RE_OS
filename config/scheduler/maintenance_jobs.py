"""
RE_OS — Maintenance Jobs
─────────────────────────
Memory decay, backup, heartbeat, staleness checks, and board session recovery.
"""

import os
from collections.abc import Callable
from datetime import date
from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine
from config.settings import TARGET_MARKETS
from scrapers.mobility_scout import run_mobility_scout
from utils.parcel_linker import run_parcel_linker_nightly, run_parcel_ownership_enrichment
from utils.assembly_detector import run_assembly_detection
from utils.alembic_check import run_alembic_check

_ALEMBIC_CWD = os.environ.get("ALEMBIC_PROJECT_DIR", "/app")
_DLQ_STALE_THRESHOLD = 10
_DLQ_PENDING_STATUS = "pending"
_DLQ_STALE_INTERVAL_DAYS = 7

try:
    from prometheus_client import Counter as _PromCounter
    _dlq_drain_runs = _PromCounter(
        "dlq_drain_runs_total", "DLQ drain check runs", ["status"],
    )
    _alembic_health_runs = _PromCounter(
        "alembic_health_runs_total", "Alembic health check runs", ["status"],
    )
except ImportError:
    _dlq_drain_runs = _alembic_health_runs = None


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


def run_memory_decay():
    """Weekly memory decay — reduce confidence of stale facts, delete below 0.3 (T-298)."""
    from utils.agent_memory import decay_memories

    n = decay_memories(days=30, decay_amount=0.1)
    logger.info(f"[Scheduler] Memory decay: {n} rows deleted")


def run_confidence_decay_check():
    """Weekly confidence decay validation — Monday 04:00 UTC (T-1289).

    Runs after run_memory_decay() (03:00 UTC). Queries agent_memories for
    records updated in the last 7 days with confidence < 1.0.
    If count = 0, sends Discord alert (169h ≈ 7-day + 1h suppression).

    Grace period: skips alerting in the first week after deployment
    (checks agent_runs for any prior memory_decay execution).
    """
    from utils.discord_notifier import send_ops_alert

    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                    SELECT COUNT(*) FROM agent_memories
                    WHERE updated_at > NOW() - INTERVAL '7 days'
                      AND confidence < 1.0
                """)
            ).fetchone()
        count = row[0] if row else 0
    except Exception as exc:
        logger.warning("[Scheduler] Confidence decay check DB error: {}", exc)
        return

    if count == 0:
        # Grace period: check if memory_decay has ever run
        try:
            with get_engine().connect() as conn:
                decay_row = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM agent_runs
                        WHERE agent_name = 'memory_decay'
                    """)
                ).fetchone()
            has_ever_run = (decay_row and decay_row[0] > 0)
        except Exception:
            has_ever_run = True  # fail open: alert rather than silently skip

        if not has_ever_run:
            logger.info(
                "[Scheduler] Confidence decay check: memory_decay never ran — "
                "grace period active, skipping alert"
            )
            return

        title = "CONFIDENCE_DECAY_STALLED"
        # 169h ≈ 7-day interval + 1h margin to prevent race between run and cooldown expiry
        if _ops_already_alerted(title, cooldown_hours=169):
            logger.info("[Scheduler] Confidence decay alert already sent this week — suppressing")
            return
        send_ops_alert(
            title,
            "Confidence decay not running — 0 memory records updated this week. Check scheduler.",
        )
        logger.warning("[Scheduler] Confidence decay check ALERT — 0 records decayed")
    else:
        logger.info("[Scheduler] Confidence decay healthy — {} records decayed this week", count)


def run_seed_staleness_check():
    """Check seed data staleness and remove stale seeds where live data sufficient.
    Runs at 06:05 IST, 5 min after market snapshot.
    """
    logger.info("Scheduler: Checking seed staleness")
    try:
        from utils.data_quality import DataQualityMonitor
        from utils.discord_notifier import send
        from config.gate_criteria import SLO_SEED_MIN_LIVE_LISTINGS

        flags = DataQualityMonitor.check_seed_staleness(
            min_live_listings=SLO_SEED_MIN_LIVE_LISTINGS
        )
        engine = get_engine()

        for flag in flags:
            market = flag["market"]
            if flag["action"] != "remove_seed_and_use_live":
                continue

            live_count = flag["live_listing_count"]
            logger.info(
                f"  {market}: removing seed data ({live_count} live listings available)"
            )

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
                send(
                    "ops",
                    title,
                    f"Seed data removed for {market} — {live_count} live listings available",
                )
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

                msg = (
                    f"BERTScore F1={score:.4f} "
                    f"(delta={delta:+.4f}) — quality regression detected. "
                    f"Candidates: {result['candidates']}, Refs: {result['references']}"
                )
                send("system", "⚠ BERTScore Regression", msg)
            except Exception as exc:
                logger.warning(f"[Scheduler] BERTScore alert failed: {exc}")
        if score is not None:
            logger.info(
                f"[Scheduler] BERTScore eval done — score={score:.4f} "
                f"delta={delta:+.4f} alert={result.get('alert', False)}"
            )
        else:
            logger.info(
                f"[Scheduler] BERTScore eval {result.get('status', '?')} — "
                f"{result.get('candidates', 0)} candidates, {result.get('references', 0)} refs"
            )
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
            result["file"],
            result["size_bytes"],
            obj_count,
            pruned,
            elapsed,
        )
        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_runs
                            (agent_name, micro_market, event_type, status, records_inserted, notes)
                        VALUES ('backup', 'system', 'db_backup', 'success', 0, :notes)
                    """),
                    {
                        "notes": "pg_dump {} ({} bytes, {} objects, {:.1f}s)".format(
                            result["file"], result["size_bytes"], obj_count, elapsed
                        )
                    },
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
                detail = (
                    f"Latest backup {age}h old — file: {latest}"
                    if age
                    else "No backup file found"
                )
            else:
                detail = "No backup file found"
            logger.warning("[BackupStaleness] Stale: {}", detail)
            send_ops_alert("DB_BACKUP_STALE", detail)
        else:
            logger.info("[BackupStaleness] Fresh: {}h old (file: {})", age, latest)
    except Exception as exc:
        logger.warning("[BackupStaleness] Check failed: {}", exc)


def run_offsite_backup_weekly():
    """Weekly offsite backup push — Sunday 05:00 IST.
    Pushes latest local dump to remote, verifies, alerts if stale."""
    from utils.backup import (
        push_to_remote,
        verify_remote_backup,
        check_remote_backup_staleness,
    )
    from utils.discord_notifier import send_ops_alert

    result = push_to_remote()
    if result["status"] == "ok":
        logger.info("[OffsiteBackup] Remote push OK: {}", result["detail"])
        verify = verify_remote_backup()
        if verify.get("valid"):
            logger.info(
                "[OffsiteBackup] Remote backup verified: {} objects",
                verify.get("object_count"),
            )
        else:
            logger.warning(
                "[OffsiteBackup] Remote backup verify failed: {}", verify.get("error")
            )
            send_ops_alert(
                "REMOTE_BACKUP_VERIFY_FAILED", verify.get("error", "unknown")
            )
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


def run_data_floor_check():
    """Data floor + heartbeat staleness check — 06:30 IST = 01:00 UTC (T-1128, T-1158).

    Dual responsibility:
    1. Alerts Discord via send_ops_alert if any market's live RERA count
       drops below its configured floor (auto-computed via get_data_floor()).
    2. Checks scheduler heartbeat staleness — alerts if last heartbeat >2h old
       (silent scheduler death detection).

    Logs combined outcome to agent_runs.
    """
    from config.settings import get_data_floor, TARGET_MARKETS
    from utils.data_quality_monitor import check_live_data_floor

    logger.info("[Scheduler] Data floor + heartbeat check starting")

    # Data floor check per market
    all_ok = True
    markets = TARGET_MARKETS
    for market in markets:
        try:
            floor = get_data_floor(market)
            ok = check_live_data_floor(market, floor=floor)
            if ok:
                logger.info("[Scheduler] Data floor {}: OK (floor={})", market, floor)
            else:
                logger.warning(
                    "[Scheduler] Data floor {}: BREACH (floor={})", market, floor
                )
                all_ok = False
        except Exception as exc:
            logger.warning(
                "[Scheduler] Data floor check failed for {}: {}", market, exc
            )
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
                    "notes": f"checked {len(markets)} markets + heartbeat; all_ok={all_ok}",
                },
            )
    except Exception as exc:
        logger.warning("[Scheduler] Failed to log data floor check: {}", exc)


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


def run_kill_criteria_check():
    """Kill criteria audit — Aug 1 + Dec 1 UTC (GATE-102, T-1201).

    Calls KillCriteriaAuditor on all 3 criteria and sends Discord OPS alert
    with the summary. Safe against any failure (non-fatal for scheduler).

    Error handling:
    - If one criterion raises, the other two still execute.
    - If all three error, a summary alert still fires with ERROR overall.
    - The alert contains per-criterion status so Jinu can triage.
    """
    from utils.discord_notifier import send_ops_alert

    results: list[dict | None] = [None, None, None]
    methods = [
        ("deed_throughput", lambda a: a.check_deed_throughput()),
        ("corridor_accuracy", lambda a: a.check_corridor_accuracy()),
        ("decision_journal", lambda a: a.check_decision_journal()),
    ]

    try:
        from utils.kill_criteria import KillCriteriaAuditor

        auditor = KillCriteriaAuditor()
        for i, (_name, fn) in enumerate(methods):
            try:
                results[i] = fn(auditor)
            except Exception as exc:
                results[i] = {"status": "ERROR", "verdict": f"Check raised: {exc}", "avg_deeds_per_week": 0.0, "entry_count": 0, "tau_proxy": None}
    except Exception as exc:
        logger.warning("[KillCriteria] Failed to import/instantiate auditor: {}", exc)
        results = [
            {"status": "ERROR", "verdict": "Auditor init failed", "avg_deeds_per_week": 0.0, "entry_count": 0, "tau_proxy": None},
        ]

    viable = [r for r in results if r is not None]
    overall = KillCriteriaAuditor.compute_overall(viable)

    deed_r = results[0] or {"status": "ERROR", "avg_deeds_per_week": 0.0}
    corridor_r = results[1] or {"status": "ERROR", "tau_proxy": None}
    journal_r = results[2] or {"status": "ERROR", "entry_count": 0}

    msg = (
        f"\U0001f534 KILL CRITERIA AUDIT \u2014 {overall}\n"
        f"1. Deed throughput: {deed_r['status']} ({deed_r.get('avg_deeds_per_week', 0.0):.1f}/week)\n"
        f"2. Corridor accuracy: {corridor_r['status']} ({corridor_r.get('tau_proxy', 'N/A')})\n"
        f"3. Decision journal: {journal_r['status']} ({journal_r.get('entry_count', 0)} entries)"
    )
    logger.info("[KillCriteria] {}", msg)
    send_ops_alert("KILL_CRITERIA_AUDIT", msg)


def run_data_floor_refresh():
    """Monthly data floor cache refresh — 1st of month 05:00 UTC (T-1290).

    Clears the module-level cache in config.settings so get_data_floor()
    recomputes from live DB counts on next call.

    Uses lazy `import config.settings as _settings` instead of a top-level
    import to avoid circular imports (settings imports scheduler helpers).
    """
    try:
        import config.settings as _settings
        _settings._data_floor_cache.clear()
        logger.info("[Scheduler] Data floor cache cleared — will recompute on next check")
    except Exception as exc:
        logger.warning("[Scheduler] Data floor refresh failed: {}", exc)


def run_check_developer_price_moves():
    """Daily 09:00 IST — Discord + Telegram alert for Grade A price moves > 3%.

    Calls detect_price_moves for each target market. Sends a single
    Discord #competitive-intel message per market if any moves found.
    Also sends via Telegram if TELEGRAM_BOT_TOKEN is configured.

    Suppresses duplicate alerts via _ops_already_alerted (23h cooldown).
    """
    from utils.pricing_tracker import detect_price_moves
    from utils.discord_notifier import send
    from utils.telegram_notifier import send_message as _tg
    from config.metrics import price_move_alerts_total

    for market in TARGET_MARKETS:
        try:
            moves = detect_price_moves(market, threshold_pct=3.0, lookback_days=7)
        except Exception as exc:
            logger.warning(
                "[DevPricing] detect_price_moves failed for {}: {}", market, exc
            )
            continue
        if not isinstance(moves, list):
            logger.warning(
                "[DevPricing] detect_price_moves returned non-list for {}: {!r}",
                market, type(moves).__name__,
            )
            continue
        if not moves:
            continue
        lines = []
        for m in moves:
            prior = m.get("prior_psf")
            curr = m["current_psf"]
            chg = m["change_pct"]
            prior_str = f"₹{prior:,.0f}" if prior else "N/A"
            curr_str = f"₹{curr:,.0f}"
            lines.append(
                f"📈 {m['developer_name']} raised {m['project_name']} "
                f"PSF by {chg:.1f}% in {market} "
                f"({prior_str}→{curr_str})"
            )
        if not lines:
            continue
        title = f"📊 Price Moves — {market}"
        dedup_key = f"price_moves_{market}_{date.today()}"
        if _ops_already_alerted(dedup_key, cooldown_hours=23):
            logger.info("[DevPricing] Alert already sent for {} today — skipping", market)
            continue
        body = "\n".join(lines)
        try:
            send("competitive-intel", title, body)
            price_move_alerts_total.labels(market=market).inc()
            logger.info(
                "[DevPricing] Sent {} price move alerts for {}", len(lines), market
            )
        except Exception as exc:
            logger.warning(
                "[DevPricing] Discord send failed for {}: {}", market, exc
            )
        try:
            _tg(f"{title}\n{body}")
        except Exception as exc:
            logger.debug(
                "[DevPricing] Telegram send skipped for {}: {}", market, exc
            )
        # Log to agent_runs for auditability
        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_runs
                            (agent_name, micro_market, event_type, status,
                             records_inserted, notes)
                        VALUES ('pricing_tracker', :m, 'price_move_alert',
                                'success', :n, :notes)
                    """),
                    {
                        "m": market,
                        "n": len(lines),
                        "notes": f"{len(lines)} price moves >= 3% detected",
                    },
                )
        except Exception as exc:
            logger.warning(
                "[DevPricing] Failed to log price move alert: {}", exc
            )


def run_scraper_health_check():
    """Daily RERA scraper health check — checkpoint mtime staleness (GATE-128, T-1329).

    Checks checkpoint file mtime for each market's RERA scraper.
    Fires RERA_DATA_STALE Discord alert if checkpoint >7 days old.
    Fires RERA_SCRAPER_NEVER_RAN if no checkpoint exists after 7-day grace window.
    """
    import os
    import time as time_mod
    from config.checkpointer import Checkpointer
    from utils.discord_notifier import send_ops_alert

    cp = Checkpointer()
    now = time_mod.time()
    max_age_seconds = 7 * 86400
    _grace_seconds = 7 * 86400  # 7-day grace before alerting "never ran"
    # Track first-seen timestamps per market across function calls
    _first_seen: dict[str, float] = getattr(run_scraper_health_check, "_first_seen", {})
    run_scraper_health_check._first_seen = _first_seen

    for market in ("Yelahanka", "Devanahalli", "Hebbal"):
        try:
            path = cp.path(market, "rera_scraped")
            if not cp.exists(market, "rera_scraped") or not os.path.isfile(path):
                if market not in _first_seen:
                    _first_seen[market] = now
                elapsed = now - _first_seen[market]
                if elapsed > _grace_seconds:
                    send_ops_alert(
                        "RERA_SCRAPER_NEVER_RAN",
                        f"[ScraperHealth] {market} has never had a RERA checkpoint "
                        f"in {elapsed / 86400:.0f} days. Scraper may not be running.",
                    )
                    logger.warning("[ScraperHealth] {} never ran ({:.0f}d)", market, elapsed / 86400)
                else:
                    logger.info("[ScraperHealth] {}: no checkpoint yet ({:.0f}d grace remaining)",
                                market, (_grace_seconds - elapsed) / 86400)
                continue
            mtime = os.path.getmtime(path)
            age_seconds = now - mtime
            if age_seconds > max_age_seconds:
                age_days = age_seconds / 86400
                send_ops_alert(
                    "RERA_DATA_STALE",
                    f"[ScraperHealth] {market} RERA checkpoint is {age_days:.1f} days old "
                    f"(>7d threshold). Scraper may be failing silently.",
                )
                logger.warning("[ScraperHealth] {} stale: {:.1f}d (mtime={})",
                               market, age_days, path)
            else:
                logger.info("[ScraperHealth] {} healthy ({:.1f}d old path={})",
                            market, age_seconds / 86400, path)
        except Exception as exc:
            logger.warning("[ScraperHealth] {} check failed: {}", market, exc)


def run_chromadb_maintenance():
    """Quarterly ChromaDB maintenance — purge stale embeddings >90 days (T-1247).

    Runs every 90 days. Alerts Discord if deleted >5000 (abnormal churn).
    """
    from utils.discord_notifier import send_ops_alert
    from utils.embedder import purge_stale_embeddings

    try:
        deleted = purge_stale_embeddings(days=90)
        logger.info("[ChromaDB Maintenance] Purged {} stale embeddings", deleted)
        if deleted > 5000:
            send_ops_alert(
                "CHROMADB_HIGH_PURGE",
                f"ChromaDB maintenance purged {deleted} embeddings (>5000 threshold) — "
                f"possible abnormal churn or misconfiguration.",
            )
    except Exception as exc:
        logger.warning("[ChromaDB Maintenance] Failed: {}", exc)
        send_ops_alert("CHROMADB_MAINTENANCE_FAILED", str(exc))


def run_failed_record_retry():
    """Re-attempt dead letter queue records — daily job (GATE-108, T-1231).

    Increments retry_count. Max 3 retries per record.
    Fires Discord alert if queue depth exceeds threshold.
    """
    try:
        from utils.dead_letter_queue import (
            retry_failed_records,
            check_queue_depth_and_alert,
        )

        result = retry_failed_records()
        logger.info(
            "[Scheduler] Dead letter retry: {} attempted, {} succeeded, {} failed",
            result["attempted"],
            result["succeeded"],
            result["failed"],
        )
        if result["failed"] > 0 and result.get("errors"):
            for err in result["errors"][:3]:
                logger.warning("[Scheduler] Dead letter retry error: {}", err)

        depth = check_queue_depth_and_alert()
        if depth > 0:
            logger.info("[Scheduler] Dead letter queue depth: {} unprocessed", depth)
    except Exception as exc:
        logger.warning("[Scheduler] Dead letter retry failed: {}", exc)


def run_dlq_purge():
    """Weekly DLQ purge — delete permanently failed records older than 30 days (GATE-117, T-1273).

    Runs via scheduler Sunday 02:00 UTC. Discord alert if deleted > 100.
    """
    try:
        from utils.dead_letter_queue import purge_old_records

        deleted = purge_old_records(max_age_days=30)
        logger.info("[Scheduler] DLQ purge: {} records deleted", deleted)
    except Exception as exc:
        logger.warning("[Scheduler] DLQ purge failed: {}", exc)


def run_corridor_backtest_weekly():
    """Weekly corridor backtest — Monday 03:00 UTC (GATE-116, T-1269).

    Runs backtest for all seeded corridors. Alerts Discord if any corridor's
    verdict changes from PASS to FAIL or INSUFFICIENT_DATA to FAIL.
    """
    from scripts.run_corridor_backtest import run_backtest
    from utils.discord_notifier import send

    engine = get_engine()
    prev_verdicts: dict[str, str] = {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DISTINCT ON (corridor_name) corridor_name, verdict
                FROM corridor_backtest_verdicts
                ORDER BY corridor_name, created_at DESC
            """)).fetchall()
            prev_verdicts = {str(r[0]): str(r[1]) for r in rows if r[1]}
    except Exception as exc:
        logger.warning("[CorridorBacktest] Could not load previous verdicts: {}", exc)

    try:
        results = run_backtest()
    except Exception as exc:
        logger.error("[CorridorBacktest] Backtest run failed: {}", exc)
        return

    alerts: list[str] = []
    for r in results:
        name = r["corridor_name"]
        try:
            with engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT verdict FROM corridor_backtest_verdicts
                    WHERE corridor_name = :name
                    ORDER BY created_at DESC LIMIT 1
                """), {"name": name}).fetchone()
            current_verdict = str(row[0]) if row else None
        except Exception:
            current_verdict = None

        if current_verdict == "FAIL":
            prev = prev_verdicts.get(name)
            if prev and prev != "FAIL":
                alerts.append(
                    f"\u26a0\ufe0f Corridor '{name}' verdict changed: {prev} \u2192 FAIL"
                )
        elif current_verdict == "PASS":
            prev = prev_verdicts.get(name)
            if prev == "FAIL":
                alerts.append(
                    f"\u2705 Corridor '{name}' recovered: FAIL \u2192 PASS"
                )

    if alerts:
        msg = "\n".join(alerts)
        try:
            send("ops", "\u26a0\ufe0f Corridor Backtest Verdict Change", msg)
            logger.info("[CorridorBacktest] Discord alert sent for verdict changes")
        except Exception as exc:
            logger.warning("[CorridorBacktest] Failed to send Discord alert: {}", exc)


def run_corridor_backtest_monthly():
    """Monthly corridor accuracy backtest — 1st of month 08:30 UTC.

    Skips backtest re-run if a verdict already exists within the last
    25 days (avoids duplicating the weekly run), then checks for 3+
    consecutive MONTHLY intervals with rank_correlation < 0.4 before
    firing a Discord kill-threshold alert.

    Monthly intervals are detected via DATE_TRUNC of created_at, not row
    count — this correctly handles both weekly and monthly backtest runs.
    """
    from scripts.run_corridor_backtest import run_backtest
    from utils.discord_notifier import send, send_ops_alert
    from sqlalchemy import text

    engine = get_engine()

    try:
        with engine.connect() as conn:
            recent = conn.execute(text("""
                SELECT 1 FROM corridor_backtest_verdicts
                WHERE created_at > NOW() - INTERVAL '25 days'
                LIMIT 1
            """)).fetchone()
        has_recent_verdict = recent is not None
    except Exception:
        has_recent_verdict = False

    if not has_recent_verdict:
        try:
            run_backtest()
        except Exception as exc:
            logger.error("[CorridorBacktestMonthly] run_backtest failed: {}", exc)
            try:
                send_ops_alert("CORRIDOR_BACKTEST_FAILURE", f"run_backtest failed: {exc}")
            except Exception:
                pass
            return
    else:
        logger.info("[CorridorBacktestMonthly] recent verdict exists — skipping re-run")

    try:
        with engine.connect() as conn:
            latest = conn.execute(text("""
                SELECT rank_correlation
                FROM corridor_backtest_verdicts
                ORDER BY created_at DESC
                LIMIT 1
            """)).fetchone()
    except Exception as exc:
        logger.warning("[CorridorBacktestMonthly] latest query failed: {}", exc)
        return

    if not latest or latest[0] is None:
        logger.info("[CorridorBacktestMonthly] no verdict data yet")
        return

    latest_corr = float(latest[0])
    if latest_corr >= 0.4:
        logger.info("[CorridorBacktestMonthly] rank_correlation={} >= 0.4 — OK", latest_corr)
        return

    try:
        with engine.connect() as conn:
            monthly_corrs = conn.execute(text("""
                SELECT DISTINCT ON (DATE_TRUNC('month', created_at))
                    rank_correlation
                FROM corridor_backtest_verdicts
                WHERE rank_correlation IS NOT NULL
                ORDER BY DATE_TRUNC('month', created_at) DESC
                LIMIT 3
            """)).fetchall()
    except Exception as exc:
        logger.warning("[CorridorBacktestMonthly] monthly corrs query failed: {}", exc)
        return

    consecutive_miss_months = 0
    for r in monthly_corrs:
        val = float(r[0]) if r[0] is not None else 1.0
        if val < 0.4:
            consecutive_miss_months += 1
        else:
            break

    if consecutive_miss_months >= 3:
        msg = (
            f"\u26a0\ufe0f CORRIDOR ACCURACY BELOW KILL THRESHOLD — "
            f"rank_correlation < 0.4 for {consecutive_miss_months} consecutive monthly periods. "
            f"Latest: {latest_corr}. Review corridor scoring model."
        )
        try:
            send("ops", "\u26a0\ufe0f Corridor Accuracy Kill Threshold", msg)
            logger.info("[CorridorBacktestMonthly] Discord alert sent: {}", msg)
        except Exception as exc:
            logger.warning("[CorridorBacktestMonthly] Discord send failed: {}", exc)
    else:
        logger.info(
            "[CorridorBacktestMonthly] rank_correlation={} < 0.4 but only {} consecutive monthly period(s) — not alerting yet",
            latest_corr, consecutive_miss_months,
        )


def run_form17_inbox_scan() -> dict:
    """Scan data/kaveri_deeds/inbox/form17/ and ingest new PDFs into registered_transactions.

    Tracks already-processed files via a watermark file (~/.form17_watermark).
    If no new PDFs since last scan, returns early without DB writes.
    """
    from pathlib import Path
    from scrapers.kaveri_form17 import parse_form17_inbox, Form17Parser
    from ingest.plugins.kaveri_form17_plugin import KaveriForm17Plugin
    from ingest.writer import IngestWriter, WriteResult

    _INBOX_DIR = Path("data/kaveri_deeds/inbox/form17")
    _WATERMARK_FILE = Path("~/.form17_watermark").expanduser()

    if not _INBOX_DIR.exists():
        logger.info("[Form17Scan] inbox/form17 directory not found")
        return {"records_written": 0, "status": "empty", "reason": "no_directory"}

    # Read watermark: store newest modification timestamp from last scan
    last_scan_mtime = 0.0
    if _WATERMARK_FILE.exists():
        try:
            last_scan_mtime = float(_WATERMARK_FILE.read_text().strip())
        except (ValueError, OSError):
            last_scan_mtime = 0.0

    pdf_files = sorted(_INBOX_DIR.glob("*.pdf"))
    new_pdfs = [p for p in pdf_files if p.stat().st_mtime > last_scan_mtime]
    if not new_pdfs:
        logger.info("[Form17Scan] no new PDFs since last scan (watermark: {})", last_scan_mtime)
        return {"records_written": 0, "status": "uptodate", "reason": "watermark", "total_pdfs": len(pdf_files)}

    logger.info("[Form17Scan] {} new PDF(s) out of {} total", len(new_pdfs), len(pdf_files))

    raw_records = parse_form17_inbox()
    if not raw_records:
        # Still update watermark so we don't re-scan next time
        _WATERMARK_FILE.write_text(str(max(p.stat().st_mtime for p in pdf_files)))
        logger.info("[Form17Scan] no records found")
        return {"records_written": 0, "status": "empty", "reason": "no_records"}

    cancelled_docs = set()
    for raw in raw_records:
        cd = raw.get("cancels_doc_number")
        if cd:
            cancelled_docs.add(cd)

    plugin = KaveriForm17Plugin()
    writer = IngestWriter()
    written = 0
    write_errors = 0
    for raw in raw_records:
        record = plugin._build_record(raw, raw.get("village", "all"), cancelled_docs)
        if record is not None:
            try:
                writer.write(record)
                written += 1
            except Exception:
                write_errors += 1
                logger.warning("[Form17Scan] write failed for doc_no={}", raw.get("doc_number"))

    # Update watermark to current time
    _WATERMARK_FILE.write_text(str(max(p.stat().st_mtime for p in pdf_files)))

    logger.info("[Form17Scan] {} records written, {} errors", written, write_errors)
    return {
        "records_written": written,
        "status": "ok" if write_errors == 0 else "partial",
        "write_errors": write_errors,
        "total_raw": len(raw_records),
        "new_pdfs": len(new_pdfs),
    }


_KILL_CRITERIA_MET_SUPPRESSION = "kill_criteria_both_met"
_KILL_CRITERIA_WEEK1_FACT = "kill_criteria_met_week_1"


def _kill_criteria_suppression_key(conn) -> str | None:
    """Check suppression state. Returns 'suppressed' if both criteria met for 2 consecutive Mondays.
    Returns 'week1' if this is the second consecutive Monday with both criteria green (write suppression).
    Returns None if no suppression action needed."""
    from sqlalchemy import text as _st

    suppression_row = conn.execute(
        _st("SELECT id FROM agent_memories WHERE agent_id='system' AND fact=:f LIMIT 1"),
        {"f": _KILL_CRITERIA_MET_SUPPRESSION},
    ).fetchone()
    if suppression_row:
        return "suppressed"

    week1_row = conn.execute(
        _st("SELECT created_at FROM agent_memories WHERE agent_id='system' AND fact=:f AND created_at > NOW() - INTERVAL '10 days' LIMIT 1"),
        {"f": _KILL_CRITERIA_WEEK1_FACT},
    ).fetchone()
    if week1_row:
        return "week2"

    return "week1"


_DEED_DEADLINE = date(2026, 8, 15)
_DJ_DEADLINE = date(2026, 12, 31)
_DEED_TARGET_WEEKLY = 50
_DJ_TARGET_COUNT = 1
_MAX_DISCORD_MSG_LEN = 400


def run_kill_criteria_reminder():
    """Weekly kill criteria deadline reminder — Monday 08:00 IST.

    Queries registered_transactions and decision_journal, sends Discord
    #re-os-health with weekly average and days-remaining counts.

    Suppression logic (2-week confirmation):
      - Week 1 (both criteria green): writes kill_criteria_met_week_1 fact
      - Week 2 (both still green): writes kill_criteria_both_met suppression
      - Week 3+: silenced by suppression check

    Suppression is checked but NOT cleared when criteria regress — once
    both are met for 2 weeks, reminders stop permanently. This prevents
    alert fatigue on already-achieved milestones.
    """
    from utils.discord_notifier import send as _ds
    from sqlalchemy import text as _st
    from datetime import date as _dt

    engine = get_engine()
    today = _dt.today()

    if today > _DEED_DEADLINE and today.weekday() == 0:
        logger.info("[KillCriteriaReminder] Past deed deadline — acknowledging milestone, stopping regular reminders")
    deed_days_left = (_DEED_DEADLINE - today).days
    dj_days_left = (_DJ_DEADLINE - today).days

    try:
        with engine.connect() as conn:
            deed_row = conn.execute(_st("""
                SELECT COUNT(*)::float / GREATEST(
                    EXTRACT(EPOCH FROM NOW()) - EXTRACT(EPOCH FROM MIN(created_at)), 1
                ) * 604800.0 AS weekly_avg
                FROM registered_transactions WHERE deed_type = 'Sale'
            """)).fetchone()
            deed_weekly_avg = round(float(deed_row[0]), 1) if deed_row and deed_row[0] else 0.0
    except Exception as exc:
        logger.warning("[KillCriteriaReminder] deed query failed: {}", exc)
        deed_weekly_avg = 0.0

    try:
        with engine.connect() as conn:
            journal_count = conn.execute(_st("SELECT COUNT(*) FROM decision_journal")).scalar() or 0
    except Exception as exc:
        logger.warning("[KillCriteriaReminder] journal query failed: {}", exc)
        journal_count = 0

    check_key = None
    if deed_weekly_avg >= _DEED_TARGET_WEEKLY and journal_count >= _DJ_TARGET_COUNT:
        try:
            with engine.connect() as conn:
                check_key = _kill_criteria_suppression_key(conn)
        except Exception as exc:
            logger.warning("[KillCriteriaReminder] suppression key check failed: {}", exc)

        if check_key == "suppressed":
            logger.info("[KillCriteriaReminder] Suppressed — criteria already met for 2+ weeks")
            return
        elif check_key == "week2":
            logger.info("[KillCriteriaReminder] Both criteria met 2 weeks running — writing permanent suppression")
            try:
                with engine.begin() as conn:
                    conn.execute(
                        _st("INSERT INTO agent_memories (agent_id, market, fact, confidence, created_at) "
                            "VALUES ('system', 'system', :f, 1.0, NOW()) ON CONFLICT (agent_id, market, fact) DO NOTHING"),
                        {"f": _KILL_CRITERIA_MET_SUPPRESSION},
                    )
                logger.info("[KillCriteriaReminder] Suppression written — future reminders suppressed")
                return
            except Exception as exc:
                logger.warning("[KillCriteriaReminder] suppression write failed: {}", exc)
        elif check_key == "week1":
            logger.info("[KillCriteriaReminder] Both criteria met first week — writing week-1 marker")
            try:
                with engine.begin() as conn:
                    conn.execute(
                        _st("INSERT INTO agent_memories (agent_id, market, fact, confidence, created_at) "
                            "VALUES ('system', 'system', :f, 1.0, NOW()) ON CONFLICT (agent_id, market, fact) DO NOTHING"),
                        {"f": _KILL_CRITERIA_WEEK1_FACT},
                    )
            except Exception as exc:
                logger.warning("[KillCriteriaReminder] week1 marker write failed: {}", exc)

    if check_key == "suppressed":
        return

    msg = (
        f"\U0001f4cb Kill Criteria Weekly Check\n"
        f"\u2022 Deed throughput: {deed_weekly_avg:.0f}/{_DEED_TARGET_WEEKLY} weekly avg — {max(deed_days_left, 0)}d until {_DEED_DEADLINE}\n"
        f"\u2022 Decision journal: {journal_count}/{_DJ_TARGET_COUNT} entries — {max(dj_days_left, 0)}d until {_DJ_DEADLINE}"
    )
    if len(msg) > _MAX_DISCORD_MSG_LEN:
        msg = msg[:_MAX_DISCORD_MSG_LEN] + "…"
    try:
        _ds("re-os-health", "Kill Criteria Weekly Reminder", msg)
        logger.info("[KillCriteriaReminder] Discord message sent")
    except Exception as exc:
        logger.warning("[KillCriteriaReminder] Discord send failed: {}", exc)


_TG_MSG_MAX = 4000  # safe under Telegram's 4096 limit — leave room for encoding


def _send_split(text: str) -> None:
    """Send text, splitting into multiple messages if > _TG_MSG_MAX chars."""
    from utils.telegram_notifier import send_message as _tg
    while len(text) > _TG_MSG_MAX:
        split_at = text.rfind("\n", 0, _TG_MSG_MAX)
        if split_at < _TG_MSG_MAX // 2:
            split_at = _TG_MSG_MAX
        _tg(text[:split_at])
        text = text[split_at:].lstrip("\n")
    if text:
        _tg(text)


def _digest_market_psf(conn, m: str) -> str:
    """Return PSF line for one market. Returns 'N/A' line on any error."""
    from sqlalchemy import text as _st
    emoji_map = {"Yelahanka": "\U0001f4cd", "Devanahalli": "\u2708\ufe0f", "Hebbal": "\U0001f3d8\ufe0f"}
    emoji = emoji_map.get(m, "\U0001f4cc")
    try:
        psf_row = conn.execute(_st("""
            WITH ranked AS (
                SELECT price_min_psf, snapshot_date,
                       ROW_NUMBER() OVER (ORDER BY snapshot_date DESC) AS rn
                FROM project_snapshots ps
                JOIN micro_markets mm ON mm.id = ps.micro_market_id
                WHERE mm.name ILIKE :m AND price_min_psf IS NOT NULL
                ORDER BY snapshot_date DESC LIMIT 4
            )
            SELECT MAX(price_min_psf) FILTER (WHERE rn = 1) AS current,
                   MAX(price_min_psf) FILTER (WHERE rn = 4) AS older
            FROM ranked
        """), {"m": f"%{m}%"}).fetchone()
        if psf_row and psf_row[0]:
            curr = float(psf_row[0])
            older = float(psf_row[1]) if psf_row[1] else curr
            arrow = "\u2191" if curr > older * 1.01 else "\u2193" if curr < older * 0.99 else "\u2192"
            return f"{emoji} {m}: \u20b9{curr:,.0f} {arrow}"
    except Exception:
        pass
    return f"{emoji} {m}: N/A"


_TG_DIGEST_SENT = None  # lazy-imported Prometheus Counter

def _digest_metric(status: str) -> None:
    global _TG_DIGEST_SENT
    if _TG_DIGEST_SENT is None:
        from config.metrics import _counter
        _TG_DIGEST_SENT = _counter("telegram_digest_total", "Weekly Telegram digest send count", ["status"])
    _TG_DIGEST_SENT.labels(status=status).inc()


def send_weekly_telegram_digest():
    """Weekly Telegram digest — Monday 08:30 IST (GATE-142, T-1399).

    Each section is isolated: a single DB failure does not kill the whole digest.
    Messages are split at \n boundaries when >4000 chars to stay under Telegram's 4096 limit.
    """
    engine = get_engine()
    parts: list[str] = ["\U0001f4ca RE_OS Weekly Digest"]

    try:
        with engine.connect() as conn:
            for m in TARGET_MARKETS:
                parts.append(_digest_market_psf(conn, m))

            try:
                opp = conn.execute(text("SELECT survey_no, score, next_action FROM opportunity_scores ORDER BY score DESC LIMIT 1")).fetchone()
                parts.append(f"\n\U0001f3c6 Top: {opp[0]} ({opp[1]:.2f}) \u2014 {opp[2][:60]}" if opp else "\n\U0001f3c6 Top: N/A")
            except Exception:
                parts.append("\n\U0001f3c6 Top: N/A")

            try:
                asm = conn.execute(text("SELECT COUNT(*) FROM assembly_signals WHERE status != 'resolved'")).scalar() or 0
                parts.append(f"\U0001f514 Assemblies: {asm} open")
            except Exception:
                parts.append("\U0001f514 Assemblies: N/A")

            try:
                mape = conn.execute(text("""
                    SELECT AVG(ABS(COALESCE(actual_value, 0) - COALESCE(predicted_value, 0))
                        / NULLIF(ABS(predicted_value), 0))
                    FROM prediction_ledger
                    WHERE verdict IS NOT NULL AND predicted_value IS NOT NULL AND predicted_value != 0
                """)).scalar()
                parts.append(f"\U0001f4ca Prediction MAPE: {float(mape)*100:.0f}%" if mape else "\U0001f4ca Prediction MAPE: N/A")
            except Exception:
                parts.append("\U0001f4ca Prediction MAPE: N/A")

            try:
                deed = conn.execute(text("""
                    SELECT COUNT(*)::float
                        / GREATEST(EXTRACT(EPOCH FROM (NOW() - COALESCE(MIN(created_at), NOW()))), 86400)
                        * 604800.0
                    FROM registered_transactions WHERE deed_type = 'Sale'
                """)).fetchone()
                dw = round(float(deed[0]), 0) if deed and deed[0] else 0
                parts.append(f"\U0001f4c4 Deeds/wk: {dw:.0f} / 50 target")
            except Exception:
                parts.append("\U0001f4c4 Deeds/wk: N/A")
    except Exception as exc:
        logger.warning("[TelegramDigest] Connection failed: {}", exc)
        parts.append("(DB unavailable)")

    try:
        _send_split("\n".join(parts))
        _digest_metric("sent")
    except Exception as exc:
        logger.warning("[TelegramDigest] Send failed: {}", exc)
        _digest_metric("failed")


def _log_agent_run(agent_name: str, event_type: str, status: str, notes: str) -> None:
    """Log job execution to agent_runs for audit trail. Never raises."""
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs
                        (agent_name, micro_market, event_type, status, notes)
                    VALUES (:name, 'system', :event, :status, :notes)
                """),
                {"name": agent_name, "event": event_type, "status": status, "notes": notes[:500]},
            )
    except Exception as exc:
        logger.debug("[AgentRun] Log failed: {}", exc)


def run_alembic_health_check():
    """Alembic migration health check — Monday 06:30 UTC = 12:00 IST (GATE-150, T-1437).

    Runs 'alembic current' and checks the last line of stdout for '(head)' marker.
    Fires Discord ALEMBIC_DRIFT alert if head mismatch. Never raises.
    Uses ALEMBIC_PROJECT_DIR env var (default /app) for alembic.ini discovery.
    Logs execution to agent_runs.
    """
    import shutil as _shutil
    import subprocess as _sp

    if _shutil.which("alembic") is None:
        logger.warning("[AlembicHealth] alembic CLI not found — skipping check")
        if _alembic_health_runs:
            _alembic_health_runs.labels(status="skipped").inc()
        _log_agent_run("alembic_health_check", "alembic_health", "skipped", "alembic CLI not found")
        return

    try:
        result = _sp.run(
            ["alembic", "current"],
            capture_output=True, text=True, timeout=30, cwd=_ALEMBIC_CWD,
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        non_empty = [line for line in stdout.split("\n") if line.strip()]
        last_line = non_empty[-1].strip() if non_empty else ""
        is_head = "(head)" in last_line

        if not is_head:
            detail = stdout or stderr or "(empty output)"
            logger.warning("[AlembicHealth] head mismatch — stdout: %s | stderr: %s", stdout, stderr)
            try:
                if not _ops_already_alerted("alembic_migration_drift", cooldown_hours=168):
                    from utils.discord_notifier import send_ops_alert
                    send_ops_alert("ALEMBIC_DRIFT", f"Alembic head mismatch: {detail}")
            except Exception as _dexc:
                logger.warning("[AlembicHealth] Discord alert failed: %s", _dexc)
            if _alembic_health_runs:
                _alembic_health_runs.labels(status="drift").inc()
            _log_agent_run("alembic_health_check", "alembic_health", "drift", f"head mismatch: {detail}")
        else:
            logger.info("[AlembicHealth] head OK: %s", last_line)
            if _alembic_health_runs:
                _alembic_health_runs.labels(status="ok").inc()
            _log_agent_run("alembic_health_check", "alembic_health", "success", f"head OK: {last_line}")
    except Exception as exc:
        logger.warning("[AlembicHealth] check failed: %s", exc)
        if _alembic_health_runs:
            _alembic_health_runs.labels(status="error").inc()
        _log_agent_run("alembic_health_check", "alembic_health", "failed", str(exc))


def run_dlq_drain_check():
    """DLQ drain check — Monday 09:30 UTC = 15:00 IST (GATE-150, T-1438).

    Queries dead_letter_queue for records stale >{_DLQ_STALE_INTERVAL_DAYS} days
    with pending status. Fires Discord DLQ_STALE alert if count exceeds threshold.
    Uses 168h cooldown to prevent weekly re-alert. Never raises.
    Logs execution to agent_runs.
    """
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text(f"""
                    SELECT COUNT(*) FROM dead_letter_queue
                    WHERE created_at < NOW() - INTERVAL '{_DLQ_STALE_INTERVAL_DAYS} days'
                      AND status = :status
                """),
                {"status": _DLQ_PENDING_STATUS},
            ).fetchone()
        count = row[0] if row else 0

        if count > _DLQ_STALE_THRESHOLD:
            if not _ops_already_alerted("dlq_drain_stale", cooldown_hours=168):
                try:
                    from utils.discord_notifier import send_ops_alert
                    send_ops_alert(
                        "DLQ_STALE",
                        f"DLQ drain check: {count} records stale >{_DLQ_STALE_INTERVAL_DAYS} days "
                        f"(threshold >{_DLQ_STALE_THRESHOLD})",
                    )
                except Exception as _dexc:
                    logger.warning("[DLQDrain] Discord alert failed: %s", _dexc)
                _log_agent_run("dlq_drain_check", "dlq_drain", "alert",
                               f"{count} stale DLQ records (threshold >{_DLQ_STALE_THRESHOLD})")
            else:
                logger.info("[DLQDrain] alert suppressed (cooldown active): {} stale records", count)
            if _dlq_drain_runs:
                _dlq_drain_runs.labels(status="alert").inc()
        else:
            if _dlq_drain_runs:
                _dlq_drain_runs.labels(status="ok").inc()
            _log_agent_run("dlq_drain_check", "dlq_drain", "ok", f"{count} stale records, below threshold")
        logger.info("[DLQDrain] check complete: {} stale records (threshold >{})", count, _DLQ_STALE_THRESHOLD)
    except Exception as exc:
        logger.warning("[DLQDrain] check failed: %s", exc)
        if _dlq_drain_runs:
            _dlq_drain_runs.labels(status="error").inc()
        _log_agent_run("dlq_drain_check", "dlq_drain", "failed", str(exc))


def register_jobs(scheduler: BlockingScheduler, safe_job: Callable[..., object]) -> None:
    """Register maintenance-related scheduler jobs."""
    from apscheduler.triggers.cron import CronTrigger

    # Weekly memory decay — Monday 03:00 UTC (T-298)
    scheduler.add_job(
        lambda: safe_job(run_memory_decay, "memory_decay"),
        CronTrigger(day_of_week="mon", hour=3, minute=0, timezone="UTC"),
        id="memory_decay",
        name="Weekly Agent Memory Decay",
        misfire_grace_time=3600,
    )
    # Weekly confidence decay validation — Monday 04:00 UTC (T-1289)
    scheduler.add_job(
        lambda: safe_job(run_confidence_decay_check, "confidence_decay_check"),
        CronTrigger(day_of_week="mon", hour=4, minute=0, timezone="UTC"),
        id="confidence_decay_check",
        name="Weekly Confidence Decay Validation (alerts if 0 records decayed)",
        misfire_grace_time=3600,
    )
    # Seed staleness check at 6:05 AM IST (5 min after market snapshot)
    scheduler.add_job(
        lambda: safe_job(run_seed_staleness_check, "seed_staleness_check"),
        CronTrigger(hour=6, minute=5),
        id="seed_staleness_check",
        name="Daily Seed Staleness Check",
        misfire_grace_time=3600,
    )
    # Weekly BERTScore evaluation — Monday 03:45 IST
    scheduler.add_job(
        lambda: safe_job(run_bertscore_evaluation, "bertscore_eval"),
        CronTrigger(day_of_week="mon", hour=3, minute=45, timezone="Asia/Kolkata"),
        id="bertscore_eval",
        name="Weekly BERTScore Quality Evaluation",
        misfire_grace_time=7200,
    )
    # Stuck board session recovery — every hour (T-315)
    scheduler.add_job(
        lambda: safe_job(recover_stuck_board_sessions, "recover_board_sessions"),
        "interval",
        hours=1,
        id="recover_board_sessions",
        name="Recover Stuck Board Sessions",
        replace_existing=True,
    )
    # Daily DB backup — 04:00 IST (Sprint 83, GATE-83)
    scheduler.add_job(
        lambda: safe_job(run_db_backup, "db_backup"),
        CronTrigger(hour=4, minute=0),
        id="db_backup",
        name="Daily pg_dump Backup",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    # Daily backup staleness check — 06:00 UTC (GATE-83, T-1100)
    scheduler.add_job(
        lambda: safe_job(run_backup_staleness_check, "backup_staleness_check"),
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="backup_staleness_check",
        name="Daily Backup Staleness Check (Discord alert if >26h old)",
        misfire_grace_time=3600,
    )
    # Weekly offsite backup push — Sunday 05:00 IST (GATE-93, T-1146)
    scheduler.add_job(
        lambda: safe_job(run_offsite_backup_weekly, "offsite_backup_weekly"),
        CronTrigger(day_of_week="sun", hour=5, minute=0),
        id="offsite_backup_weekly",
        name="Weekly Offsite Backup Push (rclone + verify + Discord alert)",
        misfire_grace_time=7200,
    )
    # Daily data floor check — 01:00 UTC = 06:30 IST (GATE-89, T-1128)
    scheduler.add_job(
        lambda: safe_job(run_data_floor_check, "data_floor_check"),
        CronTrigger(hour=1, minute=0, timezone="UTC"),
        id="data_floor_check",
        name="Daily Data Floor Check (Discord alert on live RERA breach)",
        misfire_grace_time=3600,
    )
    # Scheduler heartbeat — every 30 min (T-1158)
    scheduler.add_job(
        lambda: safe_job(run_scheduler_heartbeat, "scheduler_heartbeat"),
        "interval",
        minutes=30,
        id="scheduler_heartbeat",
        name="Scheduler Heartbeat (writes agent_runs every 30min)",
        replace_existing=True,
    )
    # Nightly parcel linker — 02:30 IST (GATE-92, T-1142)
    scheduler.add_job(
        lambda: safe_job(run_parcel_linker_nightly, "parcel_linker_nightly"),
        CronTrigger(hour=2, minute=30),
        id="parcel_linker_nightly",
        name="Nightly Parcel Linker (scan survey_no → parcels upsert)",
        misfire_grace_time=3600,
    )
    # Weekly assembly detection — Sunday 03:30 IST
    scheduler.add_job(
        lambda: safe_job(run_assembly_detection, "assembly_detection"),
        CronTrigger(day_of_week="sun", hour=3, minute=30),
        id="assembly_detection",
        name="Weekly Land Assembly Detection (after Kaveri deed extraction)",
        misfire_grace_time=7200,
    )
    # Weekly parcel ownership enrichment — Monday 04:00 UTC (GATE-99, T-1187)
    scheduler.add_job(
        lambda: safe_job(run_parcel_ownership_enrichment, "parcel_ownership_enrichment"),
        CronTrigger(day_of_week="mon", hour=4, minute=0, timezone="UTC"),
        id="parcel_ownership_enrichment",
        name="Weekly Parcel Ownership Enrichment (RTC chain from Bhoomi)",
        misfire_grace_time=7200,
    )
    # Weekly alembic check — Sunday 03:00 UTC (GATE-88, T-1122)
    scheduler.add_job(
        lambda: safe_job(run_alembic_check, "alembic_weekly_check"),
        CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="UTC"),
        id="alembic_weekly_check",
        name="Weekly Alembic Check (schema drift detection)",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    # Monthly mobility scout — 1st of month at 01:00 IST (Sprint 74, T-1039)
    scheduler.add_job(
        lambda: safe_job(run_mobility_scout, "run_mobility_scout"),
        CronTrigger(day=1, hour=1, minute=0),
        id="run_mobility_scout",
        name="Monthly Mobility Scout (accessibility_scores refresh)",
        misfire_grace_time=7200,
    )
    # Kill criteria audit — Aug 1 + Dec 1 at 09:00 UTC (GATE-102, T-1201)
    # Grace period of 7 days: if scheduler is down for up to a week,
    # the audit still fires when it restarts. Two-audits-per-year cadence
    # means this is safe — at most one missed window.
    scheduler.add_job(
        lambda: safe_job(run_kill_criteria_check, "kill_criteria_check"),
        CronTrigger(month="8,12", day=1, hour=9, minute=0, timezone="UTC"),
        id="kill_criteria_check",
        name="Kill Criteria Audit (deed throughput, corridor accuracy, decision journal)",
        misfire_grace_time=604800,
        replace_existing=True,
    )
    # Dead letter queue retry — daily 04:00 UTC (GATE-108, T-1231)
    scheduler.add_job(
        lambda: safe_job(run_failed_record_retry, "failed_record_retry"),
        CronTrigger(hour=4, minute=0, timezone="UTC"),
        id="failed_record_retry",
        name="Daily Dead Letter Queue Retry (re-attempt failed upserts)",
        misfire_grace_time=3600,
    )
    # Weekly DLQ purge — Sunday 02:00 UTC (GATE-117, T-1273)
    scheduler.add_job(
        lambda: safe_job(run_dlq_purge, "dlq_purge"),
        CronTrigger(day_of_week="sun", hour=2, minute=0, timezone="UTC"),
        id="dlq_purge",
        name="Weekly DLQ Purge (delete permanently failed records >30d old)",
        misfire_grace_time=7200,
    )
    # Weekly corridor backtest — Monday 03:00 UTC = 08:30 IST (GATE-116, T-1269)
    scheduler.add_job(
        lambda: safe_job(run_corridor_backtest_weekly, "corridor_backtest_weekly"),
        CronTrigger(day_of_week="mon", hour=3, minute=0, timezone="UTC"),
        id="corridor_backtest_weekly",
        name="Weekly Corridor Backtest (score vs distance rank correlation)",
        misfire_grace_time=7200,
    )
    # Monthly corridor backtest — 1st of month 08:30 UTC (GATE-123, T-1302)
    scheduler.add_job(
        lambda: safe_job(run_corridor_backtest_monthly, "corridor_backtest_monthly"),
        CronTrigger(day=1, hour=8, minute=30, timezone="UTC"),
        id="corridor_backtest_monthly",
        name="Monthly Corridor Backtest (accuracy kill threshold + consecutive miss tracking)",
        misfire_grace_time=7200,
    )
    # Weekly kill criteria reminder — Monday 08:00 IST (GATE-123, T-1305)
    scheduler.add_job(
        lambda: safe_job(run_kill_criteria_reminder, "kill_criteria_weekly_reminder"),
        CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="kill_criteria_weekly_reminder",
        name="Weekly Kill Criteria Reminder (deed throughput + decision journal deadlines)",
        misfire_grace_time=7200,
    )
    # Monthly data floor cache refresh — 1st of month 05:00 UTC (T-1290)
    scheduler.add_job(
        lambda: safe_job(run_data_floor_refresh, "data_floor_refresh"),
        CronTrigger(day=1, hour=5, minute=0, timezone="UTC"),
        id="data_floor_refresh",
        name="Monthly Data Floor Cache Refresh (recompute from live DB)",
        misfire_grace_time=7200,
    )
    # Quarterly ChromaDB maintenance — every 90 days at 01:00 UTC (T-1247)
    # Grace period = 7 days: if scheduler is down for up to a week, the
    # maintenance still fires. A quarterly job missing one window is acceptable.
    scheduler.add_job(
        lambda: safe_job(run_chromadb_maintenance, "chromadb_maintenance"),
        CronTrigger(day="1", month="3,6,9,12", hour=1, minute=0, timezone="UTC"),
        id="chromadb_maintenance",
        name="Quarterly ChromaDB Maintenance (purge stale embeddings >90d)",
        misfire_grace_time=604800,
    )
    # Weekly Form 17 inbox scan — Sunday 03:15 IST (GATE-122, T-1299)
    scheduler.add_job(
        lambda: safe_job(run_form17_inbox_scan, "kaveri_form17_weekly"),
        CronTrigger(day_of_week="sun", hour=3, minute=15),
        id="kaveri_form17_weekly",
        name="Weekly Form 17 Inbox Scan (ingest new PDFs → registered_transactions)",
        misfire_grace_time=7200,
    )
    # Daily RERA scraper health check — 06:30 UTC = 12:00 IST (GATE-128, T-1329)
    scheduler.add_job(
        lambda: safe_job(run_scraper_health_check, "scraper_health_check"),
        CronTrigger(hour=6, minute=30, timezone="UTC"),
        id="scraper_health_check",
        name="Daily RERA Scraper Health Check (checkpoint mtime, stale alert)",
        misfire_grace_time=3600,
    )
    # Weekly Telegram digest — Monday 08:30 IST (GATE-142, T-1399)
    scheduler.add_job(
        lambda: safe_job(send_weekly_telegram_digest, "weekly_telegram_digest"),
        CronTrigger(day_of_week="mon", hour=8, minute=30),
        id="weekly_telegram_digest",
        name="Weekly Telegram Digest (PSF, top opp, assembly count, prediction MAPE)",
        misfire_grace_time=7200,
    )
    # Daily developer price move check — 09:00 IST (GATE-141, T-1394)
    scheduler.add_job(
        lambda: safe_job(run_check_developer_price_moves, "check_developer_price_moves"),
        CronTrigger(hour=9, minute=0),
        id="check_developer_price_moves",
        name="Daily Developer Price Move Alert (Discord #competitive-intel if >3% change)",
        misfire_grace_time=3600,
    )

    # Weekly Alembic health check — Monday 06:30 UTC = 12:00 IST (GATE-150, T-1437)
    scheduler.add_job(
        lambda: safe_job(run_alembic_health_check, "weekly_alembic_health_check"),
        CronTrigger(day_of_week="mon", hour=6, minute=30, timezone="UTC"),
        id="weekly_alembic_health_check",
        name="Weekly Alembic Migration Health Check (Mon 06:30 UTC / 12:00 IST)",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    # Weekly DLQ drain check — Monday 09:30 UTC = 15:00 IST (GATE-150, T-1438)
    scheduler.add_job(
        lambda: safe_job(run_dlq_drain_check, "weekly_dlq_drain_check"),
        CronTrigger(day_of_week="mon", hour=9, minute=30, timezone="UTC"),
        id="weekly_dlq_drain_check",
        name="Weekly DLQ Drain Check (Mon 09:30 UTC / 15:00 IST)",
        misfire_grace_time=3600,
        replace_existing=True,
    )
