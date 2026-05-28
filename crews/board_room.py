"""
RE_OS — Board Room Crew
───────────────────────
POST /api/board/session → creates session row, fires 4 dept-head agents in
a background thread, returns session_id immediately.
GET  /api/board/session/<id> → polls DB for pending|active|complete|failed.

Dept heads: BD, Finance, Engineering, Ops — each a single-agent CrewAI Crew
running concurrently via ThreadPoolExecutor with a 90-second timeout guard.

Action extraction (T-259) is next. See TASK_QUEUE.md.
"""

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import create_engine, text

from config.settings import DATABASE_URL
from config.llm_router import get_heavy_llm

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


def _ceo_decompose(pitch: str, market: str) -> Optional[dict]:
    """Use the CEO agent to decompose the pitch into 4 dept-specific sub-questions.
    Returns a dict with keys 'bd', 'finance', 'engineering', 'ops' or None on failure.
    """
    try:
        llm = get_heavy_llm()
        prompt = (
            f"You are the CEO of a real estate investment firm. Given the following pitch for a market, "
            f"decompose it into four specific sub-questions, one for each department head: "
            f"Business Development (BD), Finance, Engineering, and Operations. "
            f"Each sub-question should be tailored to that department's expertise and concerns. "
            f"Return ONLY a JSON object with exactly four keys: 'bd', 'finance', 'engineering', 'ops'. "
            f"Each value should be a string containing the sub-question for that department. "
            f"Do not include any extra text or explanation.\n\n"
            f"Market: {market}\n"
            f"Pitch: {pitch}\n"
        )
        response = llm.call(prompt)
        # Try to parse the JSON
        decomposed = json.loads(response)
        # Validate that we have the four keys and they are strings
        if isinstance(decomposed, dict) and all(k in decomposed for k in ("bd", "finance", "engineering", "ops")):
            # Ensure each value is a string (or convert to string)
            for key in ("bd", "finance", "engineering", "ops"):
                if not isinstance(decomposed[key], str):
                    decomposed[key] = str(decomposed[key])
            return decomposed
        else:
            logger.warning(f"board_room: CEO decomposition returned invalid structure: {decomposed}")
            return None
    except Exception as exc:
        logger.warning(f"board_room: CEO decomposition failed: {exc}")
        return None


# ── DB helpers ────────────────────────────────────────────────────────────────

def _run_dept_heads(pitch: str, market: str, decomposition: Optional[dict] = None) -> dict:
    """Run the four department-head agents concurrently via single-agent Crews.
    Returns a dict with keys 'bd', 'finance', 'engineering', 'ops'.
    Enforces a 90-second timeout guard.
    """
    from crewai import Task, Crew, Process
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from agents.board_room.bd_head import build_bd_head_agent
    from agents.board_room.finance_head import build_finance_head_agent
    from agents.board_room.engineering_head import build_engineering_head_agent
    from agents.board_room.ops_head import build_ops_head_agent

    def run_single_agent(builder_fn, key: str) -> str:
        agent = builder_fn()
        # Build task description: if decomposition is available and has the key, use it; else use default.
        if decomposition and key in decomposition and isinstance(decomposition[key], str) and decomposition[key].strip():
            dept_specific = decomposition[key]
            task_description = (
                f"Market: {market}\n"
                f"Sub-question for {key.upper()}: {dept_specific}\n\n"
                "Provide your department's full assessment of this sub-question."
            )
        else:
            # Fallback to original
            task_description = (
                f"Market: {market}\nPitch: {pitch}\n\n"
                "Provide your department's full assessment of this pitch."
            )
        task = Task(
            description=task_description,
            expected_output=(
                "A structured one-page assessment with a clear verdict "
                "(e.g. GO/NO-GO or VIABLE/CONDITIONAL/UNVIABLE) and supporting points."
            ),
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        result = crew.kickoff()
        if hasattr(result, "tasks_output") and result.tasks_output:
            return result.tasks_output[0].raw or ""
        return getattr(result, "raw", str(result))

    builders = {
        "bd": build_bd_head_agent,
        "finance": build_finance_head_agent,
        "engineering": build_engineering_head_agent,
        "ops": build_ops_head_agent,
    }
    responses: dict = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_key = {executor.submit(run_single_agent, fn, key): key for key, fn in builders.items()}
        try:
            for future in as_completed(future_to_key, timeout=90):
                key = future_to_key[future]
                try:
                    responses[key] = future.result()
                except Exception as exc:
                    responses[key] = f"Error: {exc}"
                    logger.warning(f"board_room: dept-head '{key}' raised: {exc}")
        except TimeoutError:
            for f in future_to_key:
                f.cancel()
            logger.warning("board_room: dept-head timeout — partial responses returned")
    return responses

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
    """Update session row. Sets completed_at only on terminal states."""
    is_terminal = status in ("complete", "failed")
    try:
        with _get_engine().begin() as conn:
            conn.execute(
                text("""
                UPDATE board_sessions
                SET status = :status,
                    transcript = CAST(:transcript AS jsonb),
                    completed_at = CASE WHEN :is_terminal THEN NOW() ELSE completed_at END
                WHERE session_id = :session_id
                """),
                {
                    "session_id": session_id,
                    "status": status,
                    "transcript": json.dumps(transcript, default=str),
                    "is_terminal": is_terminal,
                },
            )
        return True
    except Exception as exc:
        logger.warning(f"board_room: failed to update session row {session_id}: {exc}")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def _extract_actions(dept_responses: dict, pitch: str, market: str) -> list:
    """Extract concrete actions from department responses using Cerebras 8b (LIGHT tier).
    Returns a list of action dicts or empty list on failure.
    """
    try:
        from litellm import completion
        from config.settings import CEREBRAS_API_KEY, CEREBRAS_BASE_URL, CEREBRAS_MODEL

        prompt = (
            "Extract 3-5 concrete actions from these board department responses. "
            "Return ONLY a JSON array, each item: {\"action\": \"...\", \"owner\": \"bd|finance|engineering|ops\", \"priority\": \"high|medium|low\"}. "
            "If insufficient information, return [].\n\n"
            f"Market: {market}\nPitch: {pitch}\n"
            f"BD: {dept_responses.get('bd', '')[:500]}\n"
            f"Finance: {dept_responses.get('finance', '')[:500]}\n"
            f"Engineering: {dept_responses.get('engineering', '')[:500]}\n"
            f"Ops: {dept_responses.get('ops', '')[:500]}\n"
        )
        response = completion(
            model=f"openai/{CEREBRAS_MODEL}",
            api_key=CEREBRAS_API_KEY,
            base_url=CEREBRAS_BASE_URL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=600,
        )
        raw = response.choices[0].message.content
        actions = json.loads(raw)
        if isinstance(actions, list):
            return actions
        logger.warning(f"board_room: action extraction returned non-list: {actions}")
        return []
    except Exception as exc:
        logger.warning(f"board_room: action extraction failed: {exc}")
        return []

def _run_board_session_bg(session_id: str, pitch: str, market: str) -> None:
    """Background worker: run dept heads, extract actions, update session row to complete or failed."""
    try:
        _update_session_row(session_id, "active", {"status": "active", "responses": {}})
        decomposition = _ceo_decompose(pitch, market)
        dept_responses = _run_dept_heads(pitch, market, decomposition)
        actions = _extract_actions(dept_responses, pitch, market)
        transcript = {"status": "complete", "responses": dept_responses, "actions": actions}
        if decomposition is not None:
            transcript["ceo_decomposition"] = decomposition
        _update_session_row(session_id, "complete", transcript)
    except Exception as exc:
        logger.error(f"board_room bg worker failed for {session_id}: {exc}")
        _update_session_row(session_id, "failed", {"status": "failed", "error": str(exc)})


def run_board_session(pitch: str, market: str) -> dict:
    """Create a board session row, start dept-head agents in a background thread, return immediately.

    Callers poll GET /api/board/session/{session_id} for status changes:
      pending → active → complete | failed
    """
    session_id = str(uuid.uuid4())
    created = _create_session_row(session_id, pitch, market)
    if not created:
        return {
            "session_id": session_id,
            "status": "error",
            "market": market,
            "message": "DB row creation failed — check logs.",
        }
    t = threading.Thread(
        target=_run_board_session_bg,
        args=(session_id, pitch, market),
        daemon=True,
        name=f"board-{session_id[:8]}",
    )
    t.start()
    return {
        "session_id": session_id,
        "status": "pending",
        "market": market,
        "message": "Session created. Poll GET /api/board/session/{session_id} for results.",
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
            ).mappings().fetchone()
            if row is None:
                return None
            return {
                "session_id": row["session_id"],
                "pitch": row["pitch"],
                "market": row["market"],
                "status": row["status"],
                "transcript": row["transcript"],
                "created_at": str(row["created_at"]),
                "completed_at": str(row["completed_at"]) if row["completed_at"] else None,
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
