"""
RE_OS — LLS Compliance Calendar (Sprint 66 — Compounding Intelligence)
8-milestone VEL (Vesting, Escrow, Legal) tracker.
Daily 08:00 IST check; Discord #legal-flags when deadline <30 days.
"""

import time as _time_mod
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from loguru import logger
from utils.discord_notifier import send as _discord_send

__all__ = ["get_milestones", "check_upcoming_deadlines", "seed_default_milestones"]

_VEL_MILESTONES = [
    "DC Conversion Application",
    "DC Conversion Approval",
    "Sale Deed Registration",
    "Encumbrance Certificate Obtained",
    "Khata Transfer Application",
    "Khata Transfer Approval",
    "Building Plan Approval",
    "Occupancy Certificate",
]

_DEFAULT_LEAD_TIME_DAYS = 90


def get_milestones(market: str) -> list[dict]:
    """Query VEL milestones for a market from the DB.

    Returns up-to-8 milestone dicts with deadline, days_remaining, status.
    Returns empty list on DB error (logged).
    """
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT milestone, deadline, status, notes
                    FROM compliance_milestones
                    WHERE market ILIKE :m
                    ORDER BY deadline ASC
                """),
                {"m": f"%{market}%"},
            ).fetchall()

        today = datetime.now(timezone.utc).date()
        results = []
        for r in rows:
            deadline_val = r[1]
            if isinstance(deadline_val, date):
                deadline = deadline_val
            elif hasattr(deadline_val, "date"):
                deadline = deadline_val.date()
            else:
                deadline = (
                    datetime.fromisoformat(str(deadline_val)).date()
                    if deadline_val
                    else None
                )
            days_remaining = (deadline - today).days if deadline else None
            results.append(
                {
                    "milestone": r[0],
                    "deadline": deadline.isoformat() if deadline else None,
                    "status": r[2] or "pending",
                    "days_remaining": days_remaining,
                    "notes": r[3],
                }
            )
        if not results:
            logger.info("[ComplianceCalendar] No milestones found for {}", market)
        return results
    except Exception as exc:
        logger.warning("[ComplianceCalendar] Query failed for {}: {}", market, exc)
        return []


def check_upcoming_deadlines() -> list[dict]:
    """Check all target markets for deadlines <30 days.
    Sends Discord #legal-flags alert per qualifying milestone.

    Returns:
        List of alert dicts with market, milestone, deadline, days_remaining.
    """
    from config.settings import TARGET_MARKETS

    t0 = _time_mod.time()
    alerts = []
    for market in TARGET_MARKETS:
        try:
            milestones = get_milestones(market)
            if not milestones:
                logger.info(
                    "[ComplianceCalendar] No milestones tracked for {} — seed_default_milestones() may be needed",
                    market,
                )
            for ms in milestones:
                days = ms.get("days_remaining")
                if (
                    days is not None
                    and 0 <= days <= 30
                    and ms.get("status", "") in ("pending", "in_progress", "")
                ):
                    alerts.append(
                        {
                            "market": market,
                            "milestone": ms["milestone"],
                            "deadline": ms["deadline"],
                            "days_remaining": days,
                        }
                    )
        except Exception as exc:
            logger.warning("[ComplianceCalendar] Check failed for {}: {}", market, exc)

    if alerts:
        for alert in alerts:
            try:
                msg = (
                    f"**{alert['milestone']}** for **{alert['market']}**\n"
                    f"Deadline: {alert['deadline']} ({alert['days_remaining']} days remaining)"
                )
                _discord_send("system", f"VEL Deadline — {alert['market']}", msg)
                logger.info(
                    "[ComplianceCalendar] Alert sent: {} | {} | {}d remaining",
                    alert["market"],
                    alert["milestone"],
                    alert["days_remaining"],
                )
            except Exception as exc:
                logger.warning(
                    "[ComplianceCalendar] Discord send failed for {}: {}",
                    alert["market"],
                    exc,
                )

    elapsed = _time_mod.time() - t0
    logger.info(
        "[ComplianceCalendar] check_upcoming_deadlines: {} alerts in {:.1f}s",
        len(alerts),
        elapsed,
    )
    return alerts


def seed_default_milestones(market: str) -> int:
    """Seed the 8 VEL milestones for a market with default 90-day-spaced deadlines.
    Skips existing entries (ON CONFLICT DO NOTHING).

    Returns:
        Count of new milestones inserted (0 if all already exist or market invalid).
    """
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        from config.settings import TARGET_MARKETS

        if market not in TARGET_MARKETS:
            logger.warning(
                "[ComplianceCalendar] Unknown market: {} (not in TARGET_MARKETS)",
                market,
            )
            return 0

        t0 = _time_mod.time()
        today = datetime.now(timezone.utc).date()
        inserted = 0
        with get_engine().begin() as conn:
            for i, milestone in enumerate(_VEL_MILESTONES):
                deadline = today + timedelta(days=(i + 1) * _DEFAULT_LEAD_TIME_DAYS)
                result = conn.execute(
                    text("""
                        INSERT INTO compliance_milestones (market, milestone, deadline, status)
                        VALUES (:m, :ms, :dl, 'pending')
                        ON CONFLICT (market, milestone) DO NOTHING
                    """),
                    {"m": market, "ms": milestone, "dl": deadline.isoformat()},
                )
                if result.rowcount > 0:
                    inserted += 1

        elapsed = _time_mod.time() - t0
        logger.info(
            "[ComplianceCalendar] Seeded {} new milestones for {} ({:.1f}s)",
            inserted,
            market,
            elapsed,
        )
        return inserted
    except Exception as exc:
        logger.error("[ComplianceCalendar] Seed failed for {}: {}", market, exc)
        return 0
