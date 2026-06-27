from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from sqlalchemy import text

from utils.db import get_engine

__all__ = [
    "create_entry",
    "list_entries",
    "get_entry",
]

logger = logging.getLogger("re_os.decision_journal")


_VALID_FLAGS = frozenset({"GO", "NO-GO", "CONDITIONAL", "NEUTRAL"})
_MAX_SUMMARY_LENGTH = 2000


def create_entry(
    market: str,
    decision_flag: str,
    context_summary: str,
    board_session_id: Optional[str] = None,
) -> int:
    market = (market or "").strip()
    if not market:
        logger.warning("[decision_journal] create_entry rejected: empty market")
        return -1
    if decision_flag not in _VALID_FLAGS:
        logger.warning(
            "[decision_journal] create_entry rejected: invalid decision_flag=%r for market=%s",
            decision_flag, market,
        )
        return -1
    try:
        with get_engine().begin() as conn:
            row = conn.execute(
                text("""
                INSERT INTO decision_journal
                    (entry_date, market, decision_flag, context_summary, board_session_id, notes)
                VALUES
                    (:entry_date, :market, :decision_flag, :context_summary, :board_session_id, :context_summary)
                RETURNING id
                """),
                {
                    "entry_date": date.today(),
                    "market": market,
                    "decision_flag": decision_flag,
                    "context_summary": (context_summary or "")[:_MAX_SUMMARY_LENGTH],
                    "board_session_id": board_session_id,
                },
            ).fetchone()
            entry_id = int(row[0]) if row else -1
            if entry_id > 0:
                logger.info(
                    "[decision_journal] Entry %d created: market=%s flag=%s session=%s",
                    entry_id, market, decision_flag, board_session_id,
                )
                try:
                    from config.metrics import decision_journal_entries_total
                    decision_journal_entries_total.labels(market=market, flag=decision_flag).inc()
                except Exception:
                    pass
            return entry_id
    except Exception as exc:
        logger.warning("[decision_journal] create_entry failed for market=%s: %s", market, exc)
        return -1


def list_entries(market: Optional[str] = None, limit: int = 20) -> list[dict]:
    try:
        with get_engine().connect() as conn:
            where = ""
            params: dict = {"lim": min(limit, 100)}
            if market:
                where = "WHERE market = :market"
                params["market"] = market
            rows = conn.execute(
                text(f"""
                SELECT id, entry_date, market, decision_flag, context_summary,
                       board_session_id, created_at
                FROM decision_journal
                {where}
                ORDER BY created_at DESC
                LIMIT :lim
                """),
                params,
            ).fetchall()
        return [
            {
                "id": int(r[0]),
                "entry_date": str(r[1]) if r[1] else None,
                "market": r[2],
                "decision_flag": r[3],
                "context_summary": r[4],
                "board_session_id": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("[decision_journal] list_entries failed: %s", exc)
        return []


def get_entry(entry_id: int) -> Optional[dict]:
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("""
                SELECT id, entry_date, market, decision_flag, context_summary,
                       board_session_id, notes, created_at
                FROM decision_journal
                WHERE id = :id
                """),
                {"id": entry_id},
            ).fetchone()
        if not row:
            return None
        return {
            "id": int(row[0]),
            "entry_date": str(row[1]) if row[1] else None,
            "market": row[2],
            "decision_flag": row[3],
            "context_summary": row[4],
            "board_session_id": row[5],
            "notes": row[6],
            "created_at": row[7].isoformat() if row[7] else None,
        }
    except Exception as exc:
        logger.warning("[decision_journal] get_entry(%s) failed: %s", entry_id, exc)
        return None
