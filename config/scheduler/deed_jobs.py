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
from config.settings import ASSEMBLY_ALERT_THRESHOLDS

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
        "assembly_detection_clusters_total", "Assembly clusters detected per run", ["market", "tier"],
    )
    _reminder_runs = _PromCounter(
        "deed_reminder_runs_total", "Kaveri download reminder runs", ["status", "market"],
    )
except ImportError:
    _deed_records = _deed_runs = _assembly_runs = _assembly_clusters = _reminder_runs = None


__all__ = [
    "run_daily_deed_scrape",
    "run_weekly_deed_threshold_check",
    "run_assembly_detection",
    "run_kaveri_download_reminder",
    "run_weekly_kill_criteria_report",
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


from typing import Literal

def _get_tier(confidence: float) -> Literal["high", "medium", "low"]:
    if confidence > ASSEMBLY_ALERT_THRESHOLDS["high"]:
        return "high"
    if confidence >= ASSEMBLY_ALERT_THRESHOLDS["medium"]:
        return "medium"
    return "low"


def run_assembly_detection():
    """Weekly assembly detection — Monday 07:00 UTC (GATE-140, T-1388).

    Three-tier alert system (T-1418):
      HIGH  (>0.75): Discord #intel + Telegram + Obsidian sync
      MEDIUM (0.5-0.75): Discord #intel only
      LOW   (<0.5): DB only (already persisted by detect_clusters)
    """
    from config.settings import TARGET_MARKETS
    from utils.assembly_detector import AssemblyDetector

    logger.info("[DeedJobs] Assembly detection starting")
    detector = AssemblyDetector()
    total_clusters = 0
    tier_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    tier_alerts: dict[str, list[dict]] = {"high": [], "medium": [], "low": []}

    for market in TARGET_MARKETS:
        try:
            clusters = detector.detect_clusters(market, window_months=6, min_parcels=3)
            total_clusters += len(clusters)
            for cl in clusters:
                conf = float(cl.get("confidence_score", 0) or 0)
                tier = _get_tier(conf)
                tier_counts[tier] += 1
                if tier != "low":
                    tier_alerts[tier].append(cl)
                if _assembly_runs:
                    _assembly_runs.labels(status="success", market=market).inc()
                if _assembly_clusters:
                    _assembly_clusters.labels(market=market, tier=tier).inc(1)
        except Exception as exc:
            logger.warning("[DeedJobs] Assembly detection failed for {}: {}", market, exc)
            if _assembly_runs:
                _assembly_runs.labels(status="error", market=market).inc()

    # HIGH tier: Discord + Telegram + Obsidian
    for cl in tier_alerts["high"]:
        try:
            send(
                "intel",
                f"Assembly: {cl['buyer_name']} — {cl['village']}",
                (
                    f"\U0001f514 HIGH Assembly signal: {cl['buyer_name']} accumulating in "
                    f"{cl['village']}, {cl['parcel_count']} parcels, "
                    f"{cl['total_area_sqm']:.0f} sqm "
                    f"(confidence: {cl['confidence_score']:.0%})"
                ),
            )
        except Exception as exc:
            logger.warning("[DeedJobs] Discord alert failed: {}", exc)
        try:
            from utils.telegram_notifier import send_message as _tg_send
            _tg_send(
                f"\U0001f514 HIGH Assembly signal\n"
                f"{cl['village']}, {cl['market']}\n"
                f"{cl['buyer_name']}\n"
                f"{cl['parcel_count']} parcels \u00b7 {cl['total_area_sqm']:.0f} sqm\n"
                f"Confidence: {cl['confidence_score']:.0%}"
            )
        except Exception as _tg_exc:
            logger.warning("[DeedJobs] Telegram alert failed: {}", _tg_exc)
        try:
            from utils.obsidian_sync import write_assembly_signal
            _fn, _content = write_assembly_signal(cl)
            if _content:
                logger.info("[DeedJobs] Assembly signal synced to Obsidian: {}", _fn)
            else:
                logger.debug("[DeedJobs] Obsidian vault not mounted — skipped assembly sync")
        except Exception as _obs_exc:
            logger.warning("[DeedJobs] Obsidian assembly sync failed: {}", _obs_exc)

    # MEDIUM tier: Discord only
    for cl in tier_alerts["medium"]:
        try:
            send(
                "intel",
                f"Assembly: {cl['buyer_name']} — {cl['village']}",
                (
                    f"MEDIUM Assembly signal: {cl['buyer_name']} accumulating in "
                    f"{cl['village']}, {cl['parcel_count']} parcels, "
                    f"{cl['total_area_sqm']:.0f} sqm "
                    f"(confidence: {cl['confidence_score']:.0%})"
                ),
            )
        except Exception as exc:
            logger.warning("[DeedJobs] Discord MEDIUM alert failed: {}", exc)

    # LOW tier: already persisted by detect_clusters — no alert

    logger.info(
        "[DeedJobs] Assembly detection complete — {} total, {} high, {} medium, {} low",
        total_clusters, tier_counts["high"], tier_counts["medium"], tier_counts["low"],
    )
    return {"total": total_clusters, **tier_counts}


def run_kaveri_download_reminder():
    """Monday 09:00 IST — proactive Kaveri Form 17 download reminder.

    Loads market→village mapping from re_os_market_kaveri_map.json.
    Computes per-market last deed seen date from registered_transactions.
    Builds priority-ordered download reminder message.
    Sends via Discord (ops) AND Telegram.
    Falls back to generic reminder if village map is missing.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    target_url = "https://kaverionline.karnataka.gov.in"

    map_path = Path("data/kaveri_jurisdiction/re_os_market_kaveri_map.json")
    if not map_path.exists():
        logger.warning("[DeedJobs] kaveri market map not found — sending generic reminder")
        _send_generic_reminder()
        if _reminder_runs:
            _reminder_runs.labels(status="map_missing", market="all").inc()
        return

    try:
        market_map = json.loads(map_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("[DeedJobs] Failed to parse kaveri market map: {} — sending generic", exc)
        _send_generic_reminder()
        if _reminder_runs:
            _reminder_runs.labels(status="parse_error", market="all").inc()
        return

    priorities: list[tuple[str, str, str, str | None]] = []
    village_skip_patterns = ["other areas", "layout", "town", "nagar"]

    for market_name, mdata in market_map.items():
        sro = mdata.get("kaveri_sro_district", "Unknown")
        villages: list[dict] = list(mdata.get("villages", []))
        if not villages:
            hoblis = mdata.get("all_hobli_villages", {})
            for hvillages in hoblis.values():
                villages.extend(hvillages if isinstance(hvillages, list) else [])
        if not villages:
            continue

        # Pick representative: prefer non-urban, non-layout, non-numbered
        candidates = [
            v for v in villages
            if isinstance(v, dict)
            and not v.get("is_urban", False)
            and not any(skip in (v["name"] or "").lower() for skip in village_skip_patterns)
        ]
        if not candidates:
            candidates = [v for v in villages if isinstance(v, dict)]
        rep_village = candidates[0]["name"] if candidates else "Unknown"
        rep_village_stripped = rep_village.split("(")[0].strip()

        last_deed: str | None = None
        try:
            with get_engine().connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT MAX(rt.reg_date)::text
                        FROM registered_transactions rt
                        WHERE rt.village ILIKE :village
                          AND rt.deed_type ILIKE '%sale%'
                    """),
                    {"village": f"%{rep_village_stripped}%"},
                ).fetchone()
                if row and row[0]:
                    last_deed = row[0]
        except Exception as exc:
            logger.warning("[DeedJobs] Last deed query failed for {}: {}", market_name, exc)

        priorities.append((market_name, rep_village_stripped, sro, last_deed))
        if _reminder_runs:
            _reminder_runs.labels(status="queried", market=market_name.lower().replace(" ", "_")).inc()

    if not priorities:
        logger.warning("[DeedJobs] No market priorities built — sending generic reminder")
        _send_generic_reminder()
        if _reminder_runs:
            _reminder_runs.labels(status="no_priorities", market="all").inc()
        return

    def _sort_key(p):
        d = p[3]
        return "0000-00-00" if d is None else d

    priorities.sort(key=_sort_key)

    # T-1454: append priority villages from assembly signal density
    priority_lines: list[str] = []
    try:
        from utils.deed_progress import get_priority_villages
        top_villages = get_priority_villages(top_n=3)
        if top_villages:
            priority_lines.append("")
            priority_lines.append("**\U0001f4cb Top 3 villages to download this week:**")
            for i, pv in enumerate(top_villages, 1):
                vn = pv.get("village", "Unknown")
                pc = pv.get("assembly_signal_count", 0)
                sc = pv.get("priority_score", 0)
                priority_lines.append(f"{i}. **{vn}** — {pc} signals (score: {sc:.1f})")
            priority_lines.append(
                "Kaveri Online → Form 17 Index II → filter by village name above."
            )
    except Exception as exc:
        logger.warning("[DeedJobs] Failed to fetch priority villages: {}", exc)

    lines = [
        "**Kaveri Form 17 Download Due**",
        "Place new PDFs in `data/kaveri_deeds/inbox/form17/`.\n",
    ]
    if priority_lines:
        lines.extend(priority_lines)
    for i, (mkt, vlg, sro_str, last) in enumerate(priorities, 1):
        last_str = last if last else "*no deeds yet*"
        lines.append(
            f"{i}. **{mkt}** ({vlg}, SRO {sro_str}) — last deed: {last_str}"
        )

    lines.append("")
    lines.append(f"1. Go to {target_url}")
    lines.append("2. Select 'Form of Index 2' (Request for Encumbrance Certificate)")
    lines.append(f"3. Choose village (e.g., {priorities[0][1]}), date range from {priorities[0][3] or 'earliest'} to today")
    lines.append("4. Pay ₹50, download PDF, place in `data/kaveri_deeds/inbox/form17/`")
    msg = "\n".join(lines)

    try:
        send("ops", "KAVERI_DOWNLOAD_REMINDER", msg)
    except Exception as exc:
        logger.warning("[DeedJobs] Discord reminder send failed: {}", exc)

    try:
        from utils.telegram_notifier import send_message as _tg_send_rd
        _tg_send_rd(msg)
    except Exception as exc:
        logger.warning("[DeedJobs] Telegram reminder send failed: {}", exc)

    if _reminder_runs:
        _reminder_runs.labels(status="sent", market="all").inc()
    logger.info("[DeedJobs] Kaveri download reminder sent — {} markets", len(priorities))


def _send_generic_reminder() -> None:
    """Fallback reminder when village map is unavailable.

    Sends hardcoded market list so Jinu always gets a Monday reminder
    even if the jurisdiction file is missing or corrupt.
    """
    msg = (
        "**Kaveri Form 17 Download Due**\n"
        "Place new PDFs in `data/kaveri_deeds/inbox/form17/`.\n\n"
        "Priority markets:\n"
        "1. Yelahanka — Yalahanka Hobli, SRO Gandhinagar\n"
        "2. Devanahalli — Kasaba Hobli, SRO Bangalore Rural\n"
        "3. Hebbal — Bangalore North, SRO Rajajinagar\n\n"
        "URL: https://kaverionline.karnataka.gov.in → Form of Index 2\n"
        "Select: Village, Date range: last_deed to today"
    )
    try:
        send("ops", "KAVERI_DOWNLOAD_REMINDER_GENERIC", msg)
    except Exception as exc:
        logger.warning("[DeedJobs] Generic Discord send failed: {}", exc)
    try:
        from utils.telegram_notifier import send_message as _tg_send_g2
        _tg_send_g2(msg)
    except Exception as exc:
        logger.warning("[DeedJobs] Generic Telegram send failed: {}", exc)
    logger.info("[DeedJobs] Generic Kaveri download reminder sent")


_REPORT_RUNNING = False
_REPORT_LOCK_MSG = "[DeedJobs] kill_criteria_report already running, skipping concurrent invocation"
# ponytail: single global flag blocks all-encompassing. If per-market reports
# are needed (e.g. separate Mon morning report for each of 12 micro-markets),
# replace with a dict[str, bool] keyed by market name + use threading.Lock.

try:
    from prometheus_client import Counter as _PromCounter
    _kill_criteria_report_runs = _PromCounter(
        "kill_criteria_report_runs_total", "Kill criteria weekly report runs", ["status"],
    )
except ImportError:
    _kill_criteria_report_runs = None


def run_weekly_kill_criteria_report() -> None:
    """Weekly kill criteria report — Monday 10:00 IST (GATE-150, T-1436).

    Fetches throughput projection and sends summary to Telegram + Discord.
    Overlap guard prevents concurrent runs.
    """
    global _REPORT_RUNNING
    if _REPORT_RUNNING:
        logger.warning(_REPORT_LOCK_MSG)
        return

    _REPORT_RUNNING = True
    try:
        _do_kill_criteria_report()
    finally:
        _REPORT_RUNNING = False


def _do_kill_criteria_report() -> None:
    """Execute kill criteria report logic — called by overlap-guarded wrapper.

    Fetches throughput projection, sends Telegram + Discord alerts,
    logs to agent_runs. Safe against any failure (non-fatal).
    """
    from utils.deed_progress import compute_throughput_projection
    from utils.telegram_notifier import send_message as _tg_send
    from utils.discord_notifier import send_ops_alert

    try:
        proj = compute_throughput_projection()
    except Exception as exc:
        logger.warning("[DeedJobs] kill_criteria_report throughput projection failed: {}", exc)
        if _kill_criteria_report_runs:
            _kill_criteria_report_runs.labels(status="error").inc()
        try:
            with get_engine().begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_runs
                            (agent_name, micro_market, event_type, status, notes)
                        VALUES ('weekly_kill_criteria_report', 'system', 'kill_criteria_report',
                                'failed', :notes)
                    """),
                    {"notes": f"compute_throughput_projection error: {exc}"},
                )
        except Exception:
            pass
        return

    verdict = proj.get("projection_verdict", "unknown")
    weeks_remaining = proj.get("weeks_remaining") if "weeks_remaining" in proj else None
    avg_4wk = proj.get("avg_4wk", 0.0)

    if weeks_remaining is None:
        deadline_label = "deadline unknown"
    elif weeks_remaining < 0:
        deadline_label = "past deadline"
    else:
        deadline_label = f"{weeks_remaining} weeks to 2026-08-15"

    msg = (
        f"\U0001f4ca **Kill Criteria Report**\n"
        f"\u2022 Throughput: {avg_4wk:.1f}/week (target 50)\n"
        f"\u2022 Verdict: {verdict}\n"
        f"\u2022 Deadline: {deadline_label}"
    )

    try:
        send_ops_alert("KILL_CRITERIA_WEEKLY", msg)
    except Exception as exc:
        logger.warning("[DeedJobs] Discord kill_criteria_report failed: {}", exc)

    try:
        _tg_send(msg)
    except Exception as exc:
        logger.warning("[DeedJobs] Telegram kill_criteria_report failed: {}", exc)

    if _kill_criteria_report_runs:
        _kill_criteria_report_runs.labels(status="sent").inc()

    try:
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO agent_runs
                        (agent_name, micro_market, event_type, status, notes)
                    VALUES ('weekly_kill_criteria_report', 'system', 'kill_criteria_report',
                            'success', :notes)
                """),
                {"notes": msg},
            )
    except Exception as exc:
        logger.debug("[DeedJobs] agent_runs log failed: {}", exc)


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

    # Weekly Kaveri download reminder — Monday 09:00 IST (GATE-145, T-1411)
    scheduler.add_job(
        lambda: safe_job(run_kaveri_download_reminder, "kaveri_download_reminder"),
        CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="kaveri_download_reminder",
        name="Weekly Kaveri Form 17 Download Reminder (Mon 09:00 IST)",
        misfire_grace_time=7200,
    )

    # Weekly kill criteria report — Monday 10:00 IST = 04:30 UTC (GATE-150, T-1436)
    scheduler.add_job(
        lambda: safe_job(run_weekly_kill_criteria_report, "weekly_kill_criteria_report"),
        CronTrigger(day_of_week="mon", hour=4, minute=30, timezone="UTC"),
        id="weekly_kill_criteria_report",
        name="Weekly Kill Criteria Report — Telegram + Discord (Mon 10:00 IST / 04:30 UTC)",
        misfire_grace_time=3600,
        replace_existing=True,
    )
