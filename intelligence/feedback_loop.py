"""
RE_OS — Feedback Loop (Sprint 66 — Compounding Intelligence)
Records actual deal outcomes to close the intelligence loop.
Writes actual_irr + outcome to opportunity_scores when a deal closes.
"""
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

__all__ = ["record_outcome", "get_outcome_history"]


def record_outcome(
    survey_no: str,
    actual_irr: Optional[float],
    outcome: str,
    deal_type: Optional[str] = None,
    notes: Optional[str] = None,
) -> bool:
    """Record the actual outcome of a scored opportunity.
    
    Args:
        survey_no: The survey number (e.g. "45/2").
        actual_irr: Actual IRR achieved (None if deal didn't close).
        outcome: One of: "signed", "loi", "lost", "withdrawn", "dropped".
        deal_type: Optional actual deal structure used.
        notes: Optional free-text notes.
    
    Returns:
        True if written, False on error.
    """
    valid_outcomes = {"signed", "loi", "lost", "withdrawn", "dropped"}
    outcome = outcome.lower().strip()
    if outcome not in valid_outcomes:
        logger.warning("[FeedbackLoop] Invalid outcome '%s' — must be one of %s", outcome, valid_outcomes)
        return False
    
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                    UPDATE opportunity_scores
                    SET actual_irr = :irr,
                        actual_outcome = :outcome,
                        deal_type = COALESCE(:deal_type, deal_type),
                        closed_at = NOW(),
                        notes = CASE WHEN :notes IS NOT NULL THEN :notes ELSE notes END
                    WHERE survey_no = :sno
                """),
                {
                    "irr": actual_irr,
                    "outcome": outcome,
                    "deal_type": deal_type,
                    "notes": notes,
                    "sno": survey_no,
                },
            )
            
            conn.execute(
                text("""
                    INSERT INTO agent_runs (agent_id, market, event_type, status, started_at, duration_seconds)
                    VALUES ('feedback_loop', 'system', 'outcome_recorded', :outcome, NOW(), 0)
                """),
                {"outcome": outcome},
            )
        
        logger.info("[FeedbackLoop] Recorded outcome for %s: %s (IRR=%s)", survey_no, outcome, actual_irr)
        
        if outcome == "signed":
            try:
                from utils.discord_notifier import send
                irr_str = f"{actual_irr:.1f}%" if actual_irr is not None else "N/A"
                send("bd_opportunities", f"Deal SIGNED — {survey_no}",
                     f"Survey {survey_no} closed with outcome: SIGNED.\nActual IRR: {irr_str}")
            except Exception as exc:
                logger.warning("[FeedbackLoop] Discord alert failed: %s", exc)
        
        return True
    except Exception as exc:
        logger.error("[FeedbackLoop] Failed to record outcome for %s: %s", survey_no, exc)
        return False


def get_outcome_history(survey_no: Optional[str] = None) -> list[dict]:
    """Query recorded outcomes.
    
    Args:
        survey_no: Optional filter by survey number.
    
    Returns:
        List of outcome dicts sorted by closed_at desc.
    """
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        
        with get_engine().connect() as conn:
            if survey_no:
                rows = conn.execute(
                    text("""
                        SELECT survey_no, actual_irr, actual_outcome, closed_at, notes
                        FROM opportunity_scores
                        WHERE actual_outcome IS NOT NULL AND survey_no = :sno
                        ORDER BY closed_at DESC
                    """),
                    {"sno": survey_no},
                ).fetchall()
            else:
                rows = conn.execute(
                    text("""
                        SELECT survey_no, actual_irr, actual_outcome, closed_at, notes
                        FROM opportunity_scores
                        WHERE actual_outcome IS NOT NULL
                        ORDER BY closed_at DESC
                        LIMIT 50
                    """),
                ).fetchall()
        
        return [
            {
                "survey_no": r[0],
                "actual_irr": float(r[1]) if r[1] is not None else None,
                "outcome": r[2],
                "closed_at": r[3].isoformat() if r[3] else None,
                "notes": r[4],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.error("[FeedbackLoop] Failed to query outcomes: %s", exc)
        return []
