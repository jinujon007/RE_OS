"""
RE_OS — Kaveri Jobs
────────────────────
Kaveri deed extraction, Bhoomi auto-survey, LA notification and
tender scan functions extracted from monolithic scheduler.py.
"""

import json
import threading
from collections.abc import Callable
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine
from utils.prediction_ledger import compute_accuracy_summary as _compute_accuracy_summary
from utils.discord_notifier import send_ops_alert as _send_ops_alert_accuracy

_BHOOMI_DEDUP_PREFIX = "bhoomi_auto_survey:"
_DEED_WEEKLY_TARGET = 50

__all__ = [
    "register_jobs",
    "run_accuracy_degradation_check",
    "run_bhoomi_auto_survey",
    "run_deed_daily_status",
    "run_kaveri_deeds_weekly",
    "run_kaveri_registration_scan",
    "run_kaveri_weekly_orchestration",
    "run_la_notification_scan",
    "run_ledger_check_weekly",
    "run_tender_daily_scan",
]


def _bhoomi_already_ran(market: str, cooldown_hours: int = 12) -> bool:
    title = f"{_BHOOMI_DEDUP_PREFIX}{market}"
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                SELECT id FROM alerts
                WHERE channel = 'ops' AND title = :title
                  AND created_at > NOW() - (:hrs || ' hours')::interval
                LIMIT 1
            """),
                {"title": title, "hrs": cooldown_hours},
            ).fetchone()
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
                rows = conn.execute(
                    text("""
                    SELECT id, survey_no, developer_name FROM rera_projects
                    WHERE survey_no IS NOT NULL AND survey_no != ''
                      AND bhoomi_checked_at IS NULL
                      AND micro_market_id = (SELECT id FROM micro_markets WHERE name ILIKE :m)
                    LIMIT 20
                """),
                    {"m": f"%{mkt}%"},
                ).fetchall()
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
                logger.warning(
                    "[BhoomiAutoSurvey] Fetch error {}: {}", row.survey_no, exc
                )
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
                        existing = conn.execute(
                            text(
                                "SELECT id FROM landowner_contacts WHERE survey_no=:sn AND market=:m"
                            ),
                            {"sn": row.survey_no, "m": mkt},
                        ).fetchone()
                        if existing:
                            conn.execute(
                                text(
                                    "UPDATE landowner_contacts SET owner_name=:o, updated_at=NOW() WHERE id=:lid"
                                ),
                                {"o": owner, "lid": existing.id},
                            )
                        else:
                            conn.execute(
                                text(
                                    "INSERT INTO landowner_contacts (survey_no, market, owner_name) VALUES (:sn, :m, :o)"
                                ),
                                {"sn": row.survey_no, "m": mkt, "o": owner},
                            )
                except Exception as exc:
                    logger.warning("[BhoomiAutoSurvey] Upsert failed: {}", exc)

            try:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "UPDATE rera_projects SET bhoomi_checked_at=NOW() WHERE id=:pid"
                        ),
                        {"pid": row.id},
                    )
                checked += 1
            except Exception as exc:
                logger.warning("[BhoomiAutoSurvey] Mark failed: {}", exc)

        _mark_bhoomi_ran(mkt)
        logger.info(
            "[BhoomiAutoSurvey] {}: {}/{} checked{}",
            mkt,
            checked,
            len(rows),
            " (429)" if skipped_429 else "",
        )


def run_kaveri_deeds_weekly():
    """Weekly Kaveri deed extraction — Sunday 03:00 IST.

    Runs EC Form 15 inbox mode + Form 17 Index II inbox mode, then
    attempts live mode, sends Discord summary.
    """
    from scrapers.kaveri_deeds import (
        run_inbox_mode,
        run_live_mode,
    )
    from scrapers.kaveri_form17 import parse_form17_inbox

    logger.info("[Scheduler] Kaveri deeds weekly extraction starting")

    # EC Form 15 path (property-level ECs)
    inbox_records = run_inbox_mode()
    live_records = run_live_mode()

    # Form 17 Index II path (bulk village deed register — primary throughput path)
    try:
        form17_records = parse_form17_inbox()
    except Exception as exc:
        logger.warning("[Scheduler] Form 17 inbox parse failed: {}", exc)
        form17_records = []

    total = len(inbox_records) + len(live_records) + len(form17_records)
    form17_sale = sum(1 for r in form17_records if r.get("is_sale_deed"))

    # Count deeds with PSF
    psf_count = sum(
        1 for r in (inbox_records + live_records) if r.get("psf") is not None
    ) + sum(1 for r in form17_records if r.get("psf") is not None)

    summary = (
        f"KAVERI DEEDS WEEKLY: {total} new deeds extracted "
        f"({len(inbox_records)} EC inbox, {len(live_records)} live, "
        f"{len(form17_records)} Form17 [{form17_sale} sales]). "
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

        logger.info(
            "[TenderScan] {} tenders scraped, {} written", len(all_tenders), written
        )

        if high_value:
            for t in high_value:
                title_short = t.data.get("title", "")[:100]
                dept = t.data.get("dept", "?")
                val_cr = float(t.data.get("value_inr", 0)) / 10000000
                msg = f"\U0001f4b0 **Tender ≥\u20b950Cr**\n{title_short}\nDept: {dept} | Value: \u20b9{val_cr:.0f}Cr"
                try:
                    send("govt_policy_scout", "High-Value Tender Alert", msg)
                except Exception as exc:
                    logger.debug("[TenderScan] Discord send failed: {}", exc)
    except Exception as exc:
        logger.warning("[TenderScan] Failed: {}", exc)


def run_ledger_check_weekly():
    """Weekly prediction ledger check — Monday 06:00 IST.
    Resolves pending claims, posts hit-rate summary to Discord.
    First Monday of month also sends module-level breakdown."""
    from datetime import date
    try:
        from utils.prediction_ledger import get_pending_claims, resolve_verdicts, build_weekly_digest_discord_message, build_monthly_digest_discord_message
        from utils.discord_notifier import send

        pending = get_pending_claims()
        if pending:
            summary = resolve_verdicts()
            logger.info("[LedgerCheck] {} pending, {} resolved, {} partial, {} unverifiable",
                        summary["total"], summary["resolved"], summary["partial"], summary["unverifiable"])
        else:
            logger.info("[LedgerCheck] No pending claims to resolve")

        weekly_msg = build_weekly_digest_discord_message()
        if weekly_msg:
            try:
                send("intel_reports", "Prediction Ledger Weekly Check", weekly_msg)
                logger.info("[LedgerCheck] Weekly summary sent to Discord")
            except Exception as discord_exc:
                logger.debug("[LedgerCheck] Discord weekly send skipped: {}", discord_exc)

        today = date.today()
        if today.weekday() == 0 and today.day <= 7:
            monthly_msg = build_monthly_digest_discord_message()
            if monthly_msg:
                try:
                    send("intel_reports", "Prediction Ledger Monthly Breakdown", monthly_msg)
                    logger.info("[LedgerCheck] Monthly breakdown sent to Discord")
                except Exception as discord_exc:
                    logger.debug("[LedgerCheck] Discord monthly send skipped: {}", discord_exc)
    except Exception as exc:
        logger.warning("[LedgerCheck] Failed: {}", exc)


def run_kaveri_weekly_orchestration():
    """Weekly Kaveri pipeline: Form17 scan → deed ingestion → assembly detection → throughput check.

    Each step runs in an isolated try/except so one failure doesn't kill the rest.
    Fires Discord summary to #re-os-health after each run.
    Logs to agent_runs for observability.
    """
    import time
    t0 = time.monotonic()

    results = {
        "form17_scanned": 0,
        "deeds_upserted": 0,
        "assembly_signals_checked": 0,
        "deed_weekly_avg": 0.0,
        "errors": [],
    }

    # Step 1 + 2: Form17 inbox scan and ingest (uses watermark dedup)
    try:
        from config.scheduler.maintenance_jobs import run_form17_inbox_scan
        scan_result = run_form17_inbox_scan()
        results["form17_scanned"] = scan_result.get("new_pdfs", 0)
        results["deeds_upserted"] = scan_result.get("records_written", 0)
    except Exception as exc:
        results["errors"].append(f"Form17 scan: {exc}")
        logger.warning("[KaveriWeekly] Form17 scan failed: {}", exc)

    # Step 3: Assembly detection (runs on current DB state regardless of step 1/2)
    try:
        from utils.assembly_detector import run_assembly_detection
        run_assembly_detection()
        results["assembly_signals_checked"] = 1
    except Exception as exc:
        results["errors"].append(f"Assembly detect: {exc}")
        logger.warning("[KaveriWeekly] Assembly detection failed: {}", exc)

    # Step 4: Throughput summary from DB
    try:
        results["deed_weekly_avg"] = _compute_deed_weekly_avg()
    except Exception as exc:
        results["errors"].append(f"Throughput check: {exc}")

    elapsed = time.monotonic() - t0

    # Discord summary
    err_str = f" — Errors: {results['errors']}" if results["errors"] else ""
    msg = (
        f"Kaveri Weekly Run\n"
        f"• Form17 PDFs scanned: {results['form17_scanned']}\n"
        f"• Deeds upserted: {results['deeds_upserted']}\n"
        f"• Assembly detection: {'ran' if results['assembly_signals_checked'] else 'skipped'}\n"
        f"• Deed throughput (4-week avg): {results['deed_weekly_avg']:.1f}/week{err_str}"
    )
    try:
        from utils.discord_notifier import send_ops_alert
        send_ops_alert("KAVERI_WEEKLY", msg)
    except Exception as exc:
        logger.warning("[KaveriWeekly] Discord alert failed: {}", exc)

    # Log to agent_runs for dashboard observability
    try:
        status = "success" if not results["errors"] else "partial_success"
        total_deeds = results["deeds_upserted"]
        notes = (
            f"KAVERI_WEEKLY: {results['form17_scanned']} PDFs, "
            f"{total_deeds} deeds upserted, "
            f"{results['deed_weekly_avg']:.1f}/wk avg, "
            f"{elapsed:.0f}s"
        )
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs
                        (agent_name, micro_market, event_type, status, notes)
                    VALUES ('kaveri_weekly_orchestration', 'system',
                            'kaveri_weekly_orchestration', :status, :notes)
                """),
                {"status": status, "notes": notes},
            )
    except Exception as exc:
        logger.warning("[KaveriWeekly] agent_runs logging failed: {}", exc)

    logger.info("[KaveriWeekly] Complete in {:.0f}s — {} errors", elapsed, len(results["errors"]))
    return results


# ── Accuracy Degradation Check (GATE-126, T-1318) ────────────────────────────

_ACCURACY_MISS_STREAK: dict[str, int] = {}
_ACCURACY_STREAK_LOCK = threading.Lock()
_ACCURACY_THRESHOLD = 0.40
_ACCURACY_STREAK_LIMIT = 3


def _log_accuracy_agent_run(success: bool, modules_fired: int = 0, error: str | None = None) -> None:
    """Write agent_runs row for accuracy check execution."""
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs (agent_id, market, event_type, status, output_data, started_at)
                    VALUES ('accuracy_degradation_check', 'system', 'accuracy_check', :status, :output, NOW())
                """),
                {
                    "status": "success" if success else "error",
                    "output": json.dumps({"modules_fired": modules_fired, "error": error}),
                },
            )
    except Exception as log_exc:
        logger.debug("[AccuracyCheck] agent_runs log failed: {}", log_exc)


def run_accuracy_degradation_check():
    """Weekly accuracy degradation check — Thursday 04:00 UTC / 09:30 IST.

    If any module's hit_rate < 40% for 3 consecutive weeks → Discord alert.
    In-memory streak resets on container restart (intentional — soft signal).
    Skips modules with fewer than 5 total verdicts (insufficient data).

    Fires Discord OPS alert on its own failure (F2 fix — no silent degradation).
    Logs to agent_runs for dashboard visibility (F3 fix).
    """
    try:
        summary = _compute_accuracy_summary(weeks=4)
        modules_fired = 0
        with _ACCURACY_STREAK_LOCK:
            for module, stats in summary.get("by_module", {}).items():
                hr = stats.get("hit_rate", 1.0)
                total = stats.get("total", 0)
                if total < 5:
                    _ACCURACY_MISS_STREAK[module] = 0
                    continue
                if hr < _ACCURACY_THRESHOLD:
                    _ACCURACY_MISS_STREAK[module] = _ACCURACY_MISS_STREAK.get(module, 0) + 1
                else:
                    _ACCURACY_MISS_STREAK[module] = 0

                if _ACCURACY_MISS_STREAK.get(module, 0) >= _ACCURACY_STREAK_LIMIT:
                    modules_fired += 1
                    _ACCURACY_MISS_STREAK[module] = 0

        # Send alerts OUTSIDE the lock — Discord HTTP call is ~500ms+
        if modules_fired > 0:
            _send_ops_alert_accuracy(
                "LEDGER_ACCURACY_DEGRADED",
                f"Prediction accuracy degraded for {modules_fired} module(s). "
                f"Hit rate below {_ACCURACY_THRESHOLD:.0%} "
                f"for {_ACCURACY_STREAK_LIMIT} consecutive weeks. "
                f"Recalibrate thresholds or review claim logic.",
            )

        _log_accuracy_agent_run(success=True, modules_fired=modules_fired)
    except Exception as exc:
        logger.error("[AccuracyCheck] Failed: {}", exc)
        _send_ops_alert_accuracy(
            "ACCURACY_CHECK_FAILED",
            f"Prediction accuracy degradation check failed: {exc}. "
            f"Accuracy gate is blind until this is resolved.",
        )
        _log_accuracy_agent_run(success=False, error=str(exc)[:500])


def _compute_deed_weekly_avg(engine=None, weeks: int = 4) -> float:
    """Return rolling average of Sale deeds registered per week over the last N weeks.

    Uses INTERVAL '1 day' * :weeks for fully parameterized query (no f-string).
    Guards against weeks=0 (division by zero). Returns 0.0 if data is empty or zero.
    """
    weeks = max(weeks, 1)
    if engine is None:
        from utils.db import get_engine
        engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT COUNT(*) / CAST(:weeks AS float)
                FROM registered_transactions
                WHERE reg_date >= NOW() - INTERVAL '1 day' * :weeks
                  AND deed_type ILIKE '%sale%'
            """),
            {"weeks": weeks},
        ).scalar()
    return float(row or 0.0)


def run_deed_daily_status() -> None:
    """Send daily Telegram status on deed throughput.

    Queries registered_transactions for weekly count and inbox for PDF count.
    Sends a Telegram message with the status summary.
    Schedule: Mon-Fri 02:30 UTC (07:00 IST).
    """
    from datetime import datetime, timezone

    from utils.deed_inbox_validator import validate_inbox_pdfs
    from utils.telegram_notifier import send_message as _tg_send

    try:
        with get_engine().connect() as conn:
            this_week_count = conn.execute(
                text("SELECT COUNT(*) FROM registered_transactions WHERE created_at >= date_trunc('week', NOW())"),
            ).scalar() or 0
    except Exception as exc:
        logger.warning("[DeedDailyStatus] DB query failed: {}", exc)
        return

    inbox_dir = Path("data/kaveri_deeds/inbox")
    validation = validate_inbox_pdfs(inbox_dir)
    inbox_count = validation["total"]
    rejected_count = len(validation["invalid"])

    today = datetime.now(timezone.utc)
    day_of_week = today.isoweekday()
    target_by_today = round(_DEED_WEEKLY_TARGET * min(day_of_week, 5) / 7)
    on_track = this_week_count >= target_by_today
    status_icon = "✅ On track" if on_track else "⚠️ At risk"

    msg = (
        f"📋 Deed status (week): {this_week_count}/{_DEED_WEEKLY_TARGET} target. "
        f"Inbox: {inbox_count} PDFs ready ({rejected_count} rejected). "
        f"{status_icon}."
    )
    try:
        _tg_send(msg)
    except Exception as exc:
        logger.warning("[DeedDailyStatus] Telegram send failed: {}", exc)


def run_kaveri_registration_scan() -> None:
    """Scan priority villages for new deed registrations on Kaveri portal.

    Queries v_deed_village_priority for top 10 villages, scans each via
    KaveriRegistrationSearch, upserts new records into
    kaveri_registration_metadata, and sends Telegram alert if new deeds found.
    Schedule: Mon-Fri 00:30 UTC (06:00 IST).
    """
    from utils.telegram_notifier import send_message as _tg_send

    try:
        with get_engine().connect() as conn:
            villages = conn.execute(
                text("""
                    SELECT village, taluk
                    FROM v_deed_village_priority
                    ORDER BY priority_score DESC NULLS LAST
                    LIMIT 10
                """),
            ).fetchall()
    except Exception as exc:
        logger.warning("[KaveriRegScan] Failed to query priority villages: {}", exc)
        return

    if not villages:
        logger.info("[KaveriRegScan] No priority villages found")
        return

    from scrapers.kaveri_registration_search import KaveriRegistrationSearch
    searcher = KaveriRegistrationSearch()

    total_new = 0
    village_new_names: list[str] = []
    doc_summaries: list[str] = []

    for row in villages:
        village = row[0]
        taluk = row[1] or None
        try:
            records = searcher.scan_village(village, taluk, days_back=1)
        except Exception as exc:
            logger.warning("[KaveriRegScan] Scan failed for {}: {}", village, exc)
            continue

        if not records:
            continue

        try:
            with get_engine().begin() as conn:
                for rec in records:
                    existing = conn.execute(
                        text("SELECT id FROM kaveri_registration_metadata WHERE doc_no = :doc AND village = :v"),
                        {"doc": rec["doc_no"], "v": rec["village"]},
                    ).fetchone()
                    if existing:
                        continue
                    conn.execute(
                        text("""
                            INSERT INTO kaveri_registration_metadata
                                (doc_no, village, taluk, reg_date, seller, buyer,
                                 survey_no, property_area, estimated_value, discovered_at)
                            VALUES
                                (:doc, :village, :taluk, :reg_date, :seller, :buyer,
                                 :survey_no, :property_area, :estimated_value, NOW())
                            ON CONFLICT (doc_no, village) DO NOTHING
                        """),
                        {
                            "doc": rec["doc_no"],
                            "village": rec["village"],
                            "taluk": taluk,
                            "reg_date": rec.get("reg_date"),
                            "seller": rec.get("seller", ""),
                            "buyer": rec.get("buyer", ""),
                            "survey_no": rec.get("survey_no", ""),
                            "property_area": rec.get("property_area", ""),
                            "estimated_value": rec.get("estimated_value", ""),
                        },
                    )
                    total_new += 1
                    doc_summaries.append(f"{rec['doc_no']} ({rec.get('seller', '?')} → {rec.get('buyer', '?')})")
                village_new_names.append(village)
        except Exception as exc:
            logger.warning("[KaveriRegScan] Upsert failed for {}: {}", village, exc)

    if total_new > 0:
        village_list = ", ".join(sorted(set(village_new_names)))
        summary_text = "; ".join(doc_summaries[:5])
        if len(doc_summaries) > 5:
            summary_text += f" … and {len(doc_summaries) - 5} more"
        msg = (
            f"🔍 {total_new} new deed(s) in {village_list}: {summary_text}. "
            f"Open discovery queue: /api/v1/deeds/discovery-queue"
        )
        try:
            _tg_send(msg)
        except Exception as exc:
            logger.warning("[KaveriRegScan] Telegram send failed: {}", exc)
    else:
        logger.info("[KaveriRegScan] No new deeds found")


def register_jobs(scheduler: BlockingScheduler, safe_job: Callable[..., object]) -> None:
    """Register Kaveri-related scheduler jobs."""
    from apscheduler.triggers.cron import CronTrigger

    # Weekly Kaveri deed extraction — Sunday 03:00 IST (GATE-91, T-1139)
    scheduler.add_job(
        lambda: safe_job(run_kaveri_deeds_weekly, "kaveri_deeds_weekly"),
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="kaveri_deeds_weekly",
        name="Weekly Kaveri Deed Extraction (inbox + live → Discord summary)",
        misfire_grace_time=7200,
    )
    # Bhoomi auto-survey — daily at 03:30 UTC = 09:00 IST (Sprint 80, T-1080)
    scheduler.add_job(
        lambda: safe_job(run_bhoomi_auto_survey, "bhoomi_auto_survey"),
        CronTrigger(hour=3, minute=30, timezone="UTC"),
        id="bhoomi_auto_survey",
        name="Daily Bhoomi Auto-Survey from RERA survey numbers (T-1080)",
        misfire_grace_time=3600,
    )
    # Weekly LA notification gazette scan — Sunday 06:00 IST (GATE-93, T-1150)
    scheduler.add_job(
        lambda: safe_job(run_la_notification_scan, "la_notification_scan"),
        CronTrigger(day_of_week="sun", hour=6, minute=0),
        id="la_notification_scan",
        name="Weekly LA Notification Gazette Scan",
        misfire_grace_time=7200,
    )
    # Daily eProcurement Karnataka tender scan — 07:00 IST (GATE-93, T-1149)
    scheduler.add_job(
        lambda: safe_job(run_tender_daily_scan, "tender_daily_scan"),
        CronTrigger(hour=7, minute=0),
        id="tender_daily_scan",
        name="Daily Karnataka eProcurement Tender Scan",
        misfire_grace_time=3600,
    )
    # Weekly prediction ledger check — Monday 06:00 IST (GATE-93, T-1148)
    scheduler.add_job(
        lambda: safe_job(run_ledger_check_weekly, "ledger_check_weekly"),
        CronTrigger(day_of_week="mon", hour=6, minute=0),
        id="ledger_check_weekly",
        name="Weekly Prediction Ledger Check (resolve + Discord summary)",
        misfire_grace_time=3600,
    )
    # Weekly Kaveri orchestration — Sunday 23:30 UTC = Monday 05:00 IST (GATE-125, T-1312)
    scheduler.add_job(
        lambda: safe_job(run_kaveri_weekly_orchestration, "kaveri_weekly_orchestration"),
        CronTrigger(day_of_week="sun", hour=23, minute=30, timezone="UTC"),
        id="kaveri_weekly_orchestration",
        name="Weekly Kaveri Orchestration: Form17→ingest→assembly→throughput (Mon 05:00 IST)",
        misfire_grace_time=7200,
    )
    # Weekly accuracy degradation check — Thursday 04:00 UTC = 09:30 IST (GATE-126, T-1318)
    scheduler.add_job(
        lambda: safe_job(run_accuracy_degradation_check, "accuracy_degradation_check"),
        CronTrigger(day_of_week="thu", hour=4, minute=0, timezone="UTC"),
        id="accuracy_degradation_check",
        name="Weekly Prediction Ledger Accuracy Degradation Check (Thu 09:30 IST)",
        misfire_grace_time=3600,
    )
    # Daily deed status Telegram — Mon-Fri 02:30 UTC = 07:00 IST (GATE-169, T-1533)
    scheduler.add_job(
        lambda: safe_job(run_deed_daily_status, "deed_daily_status"),
        CronTrigger(day_of_week="mon-fri", hour=2, minute=30, timezone="UTC"),
        id="deed_daily_status",
        name="Daily Deed Status Telegram (Mon-Fri 07:00 IST)",
        misfire_grace_time=3600,
    )
    # Daily Kaveri registration scan — Mon-Fri 00:30 UTC = 06:00 IST (GATE-173, T-1553)
    scheduler.add_job(
        lambda: safe_job(run_kaveri_registration_scan, "kaveri_registration_scan"),
        CronTrigger(day_of_week="mon-fri", hour=0, minute=30, timezone="UTC"),
        id="kaveri_registration_scan",
        name="Daily Kaveri Registration Scan (Mon-Fri 06:00 IST)",
        misfire_grace_time=3600,
    )
