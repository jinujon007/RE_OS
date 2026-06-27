"""
RE_OS — Deed Pipeline Jobs (Sprint 136, GATE-136)
─────────────────────────────────────────────────
Daily deed extraction + weekly throughput monitoring.

Watermark: processed PDF basenames are tracked in a JSON checkpoint file
so the same file is never ingested twice across daily/weekly job runs.

Prometheus metrics:
  deed_scrape_records_total — new records extracted per pipeline run (label: source)
  deed_scrape_runs_total    — pipeline runs (label: status)
"""

import json
import os
from collections.abc import Callable
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy import text

from utils.db import get_engine
from utils.discord_notifier import send_ops_alert, send

try:
    from prometheus_client import Counter as _PromCounter
    _deed_records = _PromCounter(
        "deed_scrape_records_total", "Deed scrape records extracted", ["source"],
    )
    _deed_runs = _PromCounter(
        "deed_scrape_runs_total", "Deed pipeline runs", ["status"],
    )
    _assembly_runs = _PromCounter(
        "assembly_detection_runs_total", "Assembly detection pipeline runs", ["status", "market"],
    )
    _assembly_clusters = _PromCounter(
        "assembly_detection_clusters_total", "Assembly clusters detected per run", ["market"],
    )
except ImportError:
    _deed_records = _deed_runs = _assembly_runs = _assembly_clusters = None


__all__ = [
    "run_daily_deed_scrape",
    "run_weekly_deed_threshold_check",
    "run_assembly_detection",
    "register_jobs",
]

_WATERMARK_DIR = Path("data/kaveri_deeds/checkpoints")
_WATERMARK_FILE = _WATERMARK_DIR / "deed_scrape_watermark.json"


def _load_watermark() -> set[str]:
    """Return set of PDF basenames already processed."""
    try:
        if _WATERMARK_FILE.exists():
            data = json.loads(_WATERMARK_FILE.read_text())
            return set(data.get("processed", []))
    except Exception as exc:
        logger.debug("[DeedJobs] Watermark load failed: {}", exc)
    return set()


def _save_watermark(processed: set[str]) -> None:
    """Persist processed PDF basenames to checkpoint file."""
    try:
        _WATERMARK_DIR.mkdir(parents=True, exist_ok=True)
        _WATERMARK_FILE.write_text(
            json.dumps({"processed": sorted(processed)}, indent=2)
        )
    except Exception as exc:
        logger.debug("[DeedJobs] Watermark save failed: {}", exc)


def _filter_new_pdfs(pdf_dir: Path | str, watermark: set[str]) -> list[Path]:
    """Return PDFs in `pdf_dir` whose basename is not in `watermark`."""
    pdf_dir = Path(pdf_dir)
    if not pdf_dir.exists():
        return []
    return sorted(
        p for p in pdf_dir.glob("*.pdf")
        if p.name not in watermark
    )


def _log_deed_run(records: int, status: str, notes: str) -> None:
    """Log deed pipeline run to agent_runs."""
    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs
                        (agent_name, micro_market, event_type, status, notes)
                    VALUES ('daily_deed_scrape', 'system', 'deed_scrape',
                            :status, :notes)
                """),
                {"status": status, "notes": notes},
            )
    except Exception as exc:
        logger.debug("[DeedJobs] agent_runs log failed: {}", exc)


def run_daily_deed_scrape():
    """Daily deed pipeline — scans new inbox files for all markets.

    Uses watermark to process only PDFs not seen before.
    Runs EC Form 15 inbox + Form 17 inbox + live mode stub.
    Logs to agent_runs and fires Discord summary.
    Scheduled: 01:00 IST daily.
    """
    logger.info("[DeedJobs] Daily deed scrape starting")
    watermark = _load_watermark()
    new_watermark = set(watermark)

    inbox_records: list[dict] = []
    form17_records: list[dict] = []
    errors: list[str] = []
    live_records: list[dict] = []

    # EC Form 15 inbox path — only new PDFs
    try:
        from scrapers.kaveri_deeds import parse_inbox_file as _parse_ec
        ec_dir = Path("data/kaveri_deeds/inbox")
        for pdf in _filter_new_pdfs(ec_dir, watermark):
            try:
                records = _parse_ec(str(pdf))
                inbox_records.extend(records)
                new_watermark.add(pdf.name)
            except Exception as exc:
                errors.append(f"EC {pdf.name}: {exc}")
                logger.warning("[DeedJobs] EC parse failed {}: {}", pdf.name, exc)
    except Exception as exc:
        errors.append(f"EC inbox setup: {exc}")
        logger.warning("[DeedJobs] EC inbox failed: {}", exc)

    # Form 17 Index II inbox path — only new PDFs
    try:
        from scrapers.kaveri_form17 import parse_form17 as _parse_form17
        form17_dir = Path("data/kaveri_deeds/inbox/form17")
        for pdf in _filter_new_pdfs(form17_dir, watermark):
            try:
                records = _parse_form17(pdf)
                form17_records.extend(records)
                new_watermark.add(pdf.name)
            except Exception as exc:
                errors.append(f"Form17 {pdf.name}: {exc}")
                logger.warning("[DeedJobs] Form17 parse failed {}: {}", pdf.name, exc)
    except Exception as exc:
        errors.append(f"Form17 setup: {exc}")
        logger.warning("[DeedJobs] Form17 inbox failed: {}", exc)

    # Live mode (stub — replaced when Playwright path is ready)
    try:
        from scrapers.kaveri_deeds import run_live_mode
        live_records = run_live_mode()
    except Exception as exc:
        logger.debug("[DeedJobs] Live mode (stub) skipped: {}", exc)

    # Persist updated watermark (only if new files were found)
    if new_watermark != watermark:
        _save_watermark(new_watermark)

    total = len(inbox_records) + len(form17_records) + len(live_records)
    form17_sale = sum(
        1 for r in form17_records if r.get("is_sale_deed")
    )

    summary = (
        f"Daily deed scrape: {total} new records "
        f"({len(inbox_records)} EC, {len(live_records)} live, "
        f"{len(form17_records)} Form17 [{form17_sale} sales])"
    )
    logger.info("[DeedJobs] {}", summary)

    run_status = "success" if not errors else "partial_success"
    _log_deed_run(total, run_status, summary)

    if _deed_records and _deed_runs:
        _deed_records.labels(source="ec").inc(len(inbox_records))
        _deed_records.labels(source="form17").inc(len(form17_records))
        _deed_records.labels(source="live").inc(len(live_records))
        _deed_runs.labels(status=run_status).inc()

    try:
        send_ops_alert("DAILY_DEED_SCRAPE", summary)
    except Exception as exc:
        logger.debug("[DeedJobs] Discord alert failed: {}", exc)

    return {"total": total, "new_files": len(new_watermark - watermark), "errors": errors}


def run_weekly_deed_threshold_check():
    """Monday 08:00 IST — early warning check on weekly deed throughput.

    Threshold: <20 deeds/week per market triggers an EARLY WARNING Discord
    alert (intentionally lower than the 50/week target — this fires before
    the kill-criteria window closes, giving time to act).

    The 50/week target is the kill-criteria deadline (2026-08-15). This alert
    at <20 provides a ~4-week runway before the deadline triggers.

    Fires Discord alert to #ops-alerts if any market's weekly deed count < 20.
    """
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT COALESCE(m.name, 'Unknown') AS market,
                           COUNT(rt.id) AS deed_count
                    FROM registered_transactions rt
                    LEFT JOIN micro_markets m ON m.name ILIKE rt.village
                    WHERE rt.reg_date >= :week_ago
                      AND rt.deed_type ILIKE '%sale%'
                    GROUP BY m.name
                    ORDER BY deed_count DESC
                """),
                {"week_ago": week_ago},
            ).fetchall()
    except Exception as exc:
        logger.warning("[DeedJobs] Weekly threshold query failed: {}", exc)
        return

    alert_parts: list[str] = []
    for market, deed_count in rows:
        if deed_count < 20:
            alert_parts.append(
                f"⚠ {market}: {deed_count} deeds this week (target: 50)"
            )

    if not rows:
        alert_parts.append("⚠ No deed data found for any market this week")

    if alert_parts:
        msg = (
            "**Weekly Deed Count Below Threshold**\n"
            + "\n".join(alert_parts)
            + "\n\n📊 Throughput API: `/api/v1/deeds/throughput`"
        )
        try:
            send("ops", "DEED_THROUGHPUT_WARNING", msg)
            logger.info("[DeedJobs] Weekly threshold alert sent")
        except Exception as exc:
            logger.debug("[DeedJobs] Discord send failed: {}", exc)


def run_assembly_detection():
    """Weekly assembly detection — Monday 07:00 UTC (GATE-140, T-1388).

    Calls AssemblyDetector.detect_clusters() for all 3 markets.
    Fires Discord #bd-intel alert when confidence > 0.7.
    """
    from config.settings import TARGET_MARKETS
    from utils.discord_notifier import send
    from utils.assembly_detector import AssemblyDetector

    logger.info("[DeedJobs] Assembly detection starting")
    detector = AssemblyDetector()
    total_clusters = 0
    high_conf_alerts = []

    for market in TARGET_MARKETS:
        try:
            clusters = detector.detect_clusters(market, window_months=6, min_parcels=3)
            total_clusters += len(clusters)
            if _assembly_runs:
                _assembly_runs.labels(status="success", market=market).inc()
            if _assembly_clusters:
                _assembly_clusters.labels(market=market).inc(len(clusters))
            for cl in clusters:
                if cl.get("confidence_score", 0) > 0.7:
                    high_conf_alerts.append(cl)
        except Exception as exc:
            logger.warning("[DeedJobs] Assembly detection failed for {}: {}", market, exc)
            if _assembly_runs:
                _assembly_runs.labels(status="error", market=market).inc()

    if high_conf_alerts:
        for cl in high_conf_alerts:
            try:
                send(
                    "bd-intel",
                    f"Assembly: {cl['buyer_name']} — {cl['village']}",
                    (
                        f"\U0001f514 Assembly signal: {cl['buyer_name']} accumulating in "
                        f"{cl['village']}, {cl['parcel_count']} parcels, "
                        f"{cl['total_area_sqm']:.0f} sqm "
                        f"(confidence: {cl['confidence_score']:.0%})"
                    ),
                )
            except Exception as exc:
                logger.warning("[DeedJobs] Discord alert failed: {}", exc)
            try:
                from utils.telegram_notifier import send_message as _tg_send2
                _tg_send2(
                    f"\U0001f514 Assembly signal\n"
                    f"{cl['village']}, {cl['market']}\n"
                    f"{cl['buyer_name']}\n"
                    f"{cl['parcel_count']} parcels \u00b7 {cl['total_area_sqm']:.0f} sqm\n"
                    f"Confidence: {cl['confidence_score']:.0%}"
                )
            except Exception as _tg_exc2:
                logger.warning("[DeedJobs] Telegram alert failed: {}", _tg_exc2)

    logger.info(
        "[DeedJobs] Assembly detection complete — {} clusters, {} high-confidence alerts",
        total_clusters, len(high_conf_alerts),
    )
    return {"total": total_clusters, "alerts": len(high_conf_alerts)}


def register_jobs(scheduler: BlockingScheduler, safe_job: Callable[..., object]) -> None:
    """Register deed pipeline scheduler jobs."""

    # Daily deed pipeline — 01:00 IST (GATE-136, T-1366)
    scheduler.add_job(
        lambda: safe_job(run_daily_deed_scrape, "daily_deed_scrape"),
        CronTrigger(hour=1, minute=0),
        id="daily_deed_scrape",
        name="Daily Deed Pipeline — inbox scan + ingest (01:00 IST)",
        misfire_grace_time=7200,
    )

    # Weekly deed threshold check — Monday 08:00 IST (GATE-136, T-1369)
    scheduler.add_job(
        lambda: safe_job(run_weekly_deed_threshold_check, "weekly_deed_threshold"),
        CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="weekly_deed_threshold",
        name="Weekly Deed Count Threshold Check (Mon 08:00 IST)",
        misfire_grace_time=3600,
    )

    # Weekly assembly detection — Monday 07:00 UTC (GATE-140, T-1388)
    scheduler.add_job(
        lambda: safe_job(run_assembly_detection, "assembly_detection"),
        CronTrigger(day_of_week="mon", hour=7, minute=0),
        id="assembly_detection_weekly",
        name="Weekly Assembly Detection — cluster Kaveri txns (Mon 07:00 UTC)",
        misfire_grace_time=3600,
    )
