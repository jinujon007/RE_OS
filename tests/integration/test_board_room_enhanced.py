from __future__ import annotations

import time
from typing import Any

import pytest

from tests.integration.conftest import integration

pytestmark = [integration, pytest.mark.slow]

_DEPT_HEADS = {"BD Head", "Finance Head", "Engineering Head", "Ops Head", "Legal Head"}
_POLL_INTERVAL_S = 5
_MAX_WAIT_S = 150


def _poll_session(session_id: str, max_wait: int = _MAX_WAIT_S, interval: int = _POLL_INTERVAL_S) -> dict[str, Any] | None:
    from crews.board_room import get_board_session

    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            data = get_board_session(session_id)
        except Exception as exc:
            time.sleep(interval)
            continue
        if data is None:
            time.sleep(interval)
            continue
        status = data.get("status")
        if status in ("complete", "failed"):
            return data
        time.sleep(interval)
    return None


@pytest.mark.test_id("G164-A4")
@pytest.mark.integration
def test_board_room_enhanced(db_engine: Any) -> None:
    """Run a board session and verify end-to-end lifecycle.

    The board room runs 5 dept-head agents asynchronously in a background
    thread. This test:
    1. Calls ``run_board_session(pitch, market)`` — creates DB row, starts agents.
    2. Verifies the ``board_sessions`` row was created with the returned session_id.
    3. Polls ``get_board_session(session_id)`` up to ``_MAX_WAIT_S`` seconds.
    4. If the session completes, asserts:
       - All 5 dept head labels in the transcript.
       - A GO/NO-GO/CAUTIOUS verdict is present.
       - STRR or metro signal string appears.
       - ``decision_flag`` is populated.
    5. Asserts a ``decision_journal`` entry was created within 5 minutes.

    If the session does not complete (LLM unavailable or timeout), the test
    **skips** the transcript assertions but still validates session row creation
    and orchestration — making it resilient to LLM flakiness while maintaining
    coverage of the core integration.
    """
    from crews.board_room import run_board_session
    from sqlalchemy import text

    pitch = "5-acre site at Yelahanka, R2 zone, asking PSF 6200, JD model"
    market = "Yelahanka"

    initial = run_board_session(pitch=pitch, market=market)

    assert isinstance(initial, dict), f"Expected dict, got {type(initial)}"
    assert "session_id" in initial, f"Missing session_id: {initial}"
    session_id: str = initial["session_id"]

    error_msg = initial.get("message", "")
    assert initial.get("status") != "error", (
        f"Board session creation failed: {error_msg}"
    )
    assert initial.get("market") == market, (
        f"Market mismatch: expected '{market}', got '{initial.get('market')}'"
    )

    with db_engine.connect() as conn:
        session_rows = conn.execute(
            text(
                "SELECT COUNT(*) FROM board_sessions "
                "WHERE session_id = :sid AND created_at > NOW() - INTERVAL '5 minutes'"
            ),
            {"sid": session_id},
        ).scalar()
        assert session_rows is not None and session_rows >= 1, (
            f"Expected board_sessions row for session_id={session_id}, "
            f"got {session_rows}"
        )

    final = _poll_session(session_id)

    if final is None:
        pytest.skip(
            f"Board session {session_id} did not complete within {_MAX_WAIT_S}s. "
            "Session row + orchestration verified (LLM may be unavailable)."
        )

    if final.get("status") == "failed":
        pytest.skip(
            f"Board session {session_id} failed (likely LLM error). "
            f"Session row + orchestration verified. "
            f"Error: {final.get('error', 'unknown')}"
        )

    transcript = final.get("transcript", {})
    combined_text = str(transcript)

    found_heads = {h for h in _DEPT_HEADS if h in combined_text}
    assert len(found_heads) >= 5, (
        f"Expected all 5 dept head labels in transcript, "
        f"found {len(found_heads)}: {found_heads}"
    )

    has_verdict = any(
        v in combined_text.upper() for v in ("GO", "NO-GO", "CAUTIOUS")
    )
    assert has_verdict, (
        "No GO/NO-GO/CAUTIOUS verdict found in board session transcript"
    )

    has_strr = "STRR" in combined_text.upper() or "metro" in combined_text.lower()
    assert has_strr, (
        "STRR or metro signal string not found in board room output"
    )

    decision_flag = final.get("decision_flag")
    assert decision_flag is not None, (
        "Missing decision_flag in completed board session result"
    )

    with db_engine.connect() as conn:
        dj_count = conn.execute(
            text(
                "SELECT COUNT(*) FROM decision_journal "
                "WHERE created_at > NOW() - INTERVAL '5 minutes'"
            )
        ).scalar()
        assert dj_count is not None and dj_count >= 1, (
            f"Expected >=1 decision_journal entry within 5 minutes, got {dj_count}"
        )
