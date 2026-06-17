"""
RE_OS — Kaveri Jobs
────────────────────
Kaveri deed extraction, Bhoomi auto-survey, LA notification and
tender scan functions extracted from monolithic scheduler.py.
"""

from collections.abc import Callable
from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger
from sqlalchemy import text
from utils.db import get_engine

_BHOOMI_DEDUP_PREFIX = "bhoomi_auto_survey:"


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
