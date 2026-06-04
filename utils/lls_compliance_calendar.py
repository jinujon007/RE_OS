"""
RE_OS — LLS Compliance Calendar (Sprint 66 — Compounding Intelligence)
8-milestone VEL (Vesting, Escrow, Legal) tracker.
Daily 08:00 IST check; Discord #legal-flags when deadline <30 days.
"""
from datetime import datetime, date, timedelta, timezone
from typing import Optional
from loguru import logger

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
    Returns list of {milestone, deadline, status, days_remaining}."""
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
            deadline = r[1].date() if hasattr(r[1], 'date') else r[1]
            days_remaining = (deadline - today).days if deadline else None
            results.append({
                "milestone": r[0],
                "deadline": deadline.isoformat() if deadline else None,
                "status": r[2] or "pending",
                "days_remaining": days_remaining,
                "notes": r[3],
            })
        return results
    except Exception as exc:
        logger.warning("[ComplianceCalendar] Query failed: %s", exc)
        return []


def check_upcoming_deadlines() -> list[dict]:
    """Check all markets for deadlines <30 days.
    Sends Discord #legal-flags alert for each.
    
    Returns:
        List of dicts with market, milestone, deadline, days_remaining.
    """
    from config.settings import TARGET_MARKETS
    
    alerts = []
    for market in TARGET_MARKETS:
        try:
            milestones = get_milestones(market)
            for ms in milestones:
                days = ms.get("days_remaining")
                if days is not None and 0 <= days <= 30 and ms.get("status", "") in ("pending", "in_progress", ""):
                    alerts.append({
                        "market": market,
                        "milestone": ms["milestone"],
                        "deadline": ms["deadline"],
                        "days_remaining": days,
                    })
        except Exception as exc:
            logger.warning("[ComplianceCalendar] Check failed for %s: %s", market, exc)
    
    if alerts:
        for alert in alerts:
            try:
                from utils.discord_notifier import send
                msg = (
                    f"**{alert['milestone']}** for **{alert['market']}**\n"
                    f"Deadline: {alert['deadline']} ({alert['days_remaining']} days remaining)"
                )
                send("system", f"VEL Deadline — {alert['market']}", msg)
                logger.info("[ComplianceCalendar] Alert sent: %s %s", alert['market'], alert['milestone'])
            except Exception as exc:
                logger.warning("[ComplianceCalendar] Discord send failed: %s", exc)
    
    return alerts


def seed_default_milestones(market: str) -> int:
    """Seed the 8 VEL milestones for a market with default deadlines.
    Skips existing entries. Returns count inserted."""
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        
        from config.settings import TARGET_MARKETS
        if market not in TARGET_MARKETS:
            logger.warning("[ComplianceCalendar] Unknown market: %s", market)
            return 0
        
        inserted = 0
        with get_engine().begin() as conn:
            for i, milestone in enumerate(_VEL_MILESTONES):
                deadline = datetime.now(timezone.utc).date() + timedelta(days=(i + 1) * _DEFAULT_LEAD_TIME_DAYS)
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
        
        logger.info("[ComplianceCalendar] Seeded %d milestones for %s", inserted, market)
        return inserted
    except Exception as exc:
        logger.error("[ComplianceCalendar] Seed failed for %s: %s", market, exc)
        return 0
