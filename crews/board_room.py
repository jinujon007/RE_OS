"""
RE_OS — Board Room Crew (Phase 3 skeleton)
──────────────────────────────────────────
CEO decomposes a pitch → 4 dept heads respond concurrently → actions extracted.

Phase 3 is NOT YET IMPLEMENTED. This skeleton:
  • Defines the session data contract (BoardSession)
  • Creates a board_sessions DB row and returns session_id
  • Stubs run_board_session() so T-258 (concurrent runner) can build on it

See: VISION.md § Phase 3, TASK_QUEUE.md T-218, T-257, T-258, T-259, T-260
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import create_engine, text

from config.settings import DATABASE_URL

# ── Engine ────────────────────────────────────────────────────────────────────

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=2, max_overflow=0)
    return _engine


# ── Data contract ─────────────────────────────────────────────────────────────

@dataclass
class BoardSession:
    session_id: str
    pitch: str
    market: Optional[str] = None
    status: str = "pending"          # pending | active | complete | failed
    ceo_decomposition: Optional[str] = None
    bd_response: Optional[str] = None
    engineering_response: Optional[str] = None
    finance_response: Optional[str] = None
    operations_response: Optional[str] = None
    actions: list = field(default_factory=list)
    created_at: Optional[str] = None


# ── DB helpers ────────────────────────────────────────────────────────────────

def _create_session_row(session_id: str, pitch: str, market: Optional[str]) -> bool:
    """Insert a pending session row into board_sessions. Non-fatal on failure."""
    try:
        with _get_engine().begin() as conn:
            conn.execute(
                text("""
                INSERT INTO board_sessions (
                    session_id, pitch, market, status, transcript, created_at
                ) VALUES (
                    :session_id, :pitch, :market, 'pending',
                    CAST(:transcript AS jsonb), NOW()
                )
                """),
                {
                    "session_id": session_id,
                    "pitch": pitch,
                    "market": market or "",
                    "transcript": json.dumps({"status": "pending", "responses": {}}),
                },
            )
        return True
    except Exception as exc:
        logger.warning(f"board_room: failed to create session row {session_id}: {exc}")
        return False


def _update_session_row(session_id: str, status: str, transcript: dict) -> bool:
    """Update an existing session row with final status + transcript."""
    try:
        with _get_engine().begin() as conn:
            conn.execute(
                text("""
                UPDATE board_sessions
                SET status = :status,
                    transcript = CAST(:transcript AS jsonb),
                    completed_at = NOW()
                WHERE session_id = :session_id
                """),
                {
                    "session_id": session_id,
                    "status": status,
                    "transcript": json.dumps(transcript, default=str),
                },
            )
        return True
    except Exception as exc:
        logger.warning(f"board_room: failed to update session row {session_id}: {exc}")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def run_board_session(pitch: str, market: str) -> dict:
    """Create a board session and return its ID.

    Phase 3 NOT YET IMPLEMENTED — actual dept-head agent calls are in T-257/T-258.
    This stub creates the DB row and returns a valid session_id so the API layer
    (T-260) can track session state.

    Returns:
        {"session_id": str, "status": "pending", "message": str}
    """
    session_id = str(uuid.uuid4())
    created = _create_session_row(session_id, pitch, market)
    status = "pending" if created else "error"
    return {
        "session_id": session_id,
        "status": status,
        "market": market,
        "message": (
            "Session created. Board Room Phase 3 pending T-257/T-258 implementation."
            if created else
            "Session ID generated but DB write failed — check logs."
        ),
    }


def get_board_session(session_id: str) -> Optional[dict]:
    """Fetch a board session from DB by session_id. Returns None if not found."""
    try:
        with _get_engine().connect() as conn:
            row = conn.execute(
                text("""
                SELECT session_id, pitch, market, status, transcript, created_at, completed_at
                FROM board_sessions
                WHERE session_id = :session_id
                """),
                {"session_id": session_id},
            ).fetchone()
            if row is None:
                return None
            return {
                "session_id": row[0],
                "pitch": row[1],
                "market": row[2],
                "status": row[3],
                "transcript": row[4],
                "created_at": str(row[5]),
                "completed_at": str(row[6]) if row[6] else None,
            }
    except Exception as exc:
        logger.warning(f"board_room: get_board_session failed for {session_id}: {exc}")
        return None


# ── Standalone test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = run_board_session(
        pitch="Should LLS enter Yelahanka at PSF 6500?",
        market="Yelahanka",
    )
    print(json.dumps(result, indent=2))
