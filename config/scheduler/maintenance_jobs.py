"""
RE_OS — Maintenance Jobs
─────────────────────────
Memory decay, backup, heartbeat, staleness checks, and board session recovery.
"""

from collections.abc import Callable
from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine
from config.settings import TARGET_MARKETS
from scrapers.mobility_scout import run_mobility_scout
from utils.parcel_linker import run_parcel_linker_nightly, run_parcel_ownership_enrichment
from utils.assembly_detector import run_assembly_detection
from utils.alembic_check import run_alembic_check


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
                    "notes": f"checked {len(DATA_FLOOR_MARKETS)} markets + heartbeat; all_ok={all_ok}",
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
