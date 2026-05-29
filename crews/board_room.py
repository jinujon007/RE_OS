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
from config.llm_router import get_analysis_llm, get_heavy_llm

# ── Engine ────────────────────────────────────────────────────────────────────

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=2)
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


def _ceo_decompose(pitch: str, market: str, _session_excluded: set) -> Optional[dict]:
    """Use the CEO agent to decompose the pitch into 4 dept-specific sub-questions.
    Returns a dict with keys 'bd', 'finance', 'engineering', 'ops' or None on failure.
    _session_excluded: per-session provider exclusion set — never touches the global _EXCLUDED.
    """
    try:
        llm = get_heavy_llm(excluded=_session_excluded)
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

_DEPT_TASK_TEMPLATES = {
    "bd": (
        "You are the BD Head reviewing a real estate pitch.\n"
        "Market: {market}\n"
        "CEO Sub-question: {dept_question}\n\n"
        "Deliver:\n"
        "1. GO / NO-GO verdict with one-sentence rationale\n"
        "2. Absorption rate signal for this market (cite a number)\n"
        "3. Three specific risks (each: risk + who it hurts)\n"
        "4. Three specific upsides (each: upside + magnitude estimate)\n"
        "5. Recommended entry PSF range for LLS"
    ),
    "finance": (
        "You are the Finance Head reviewing a real estate pitch.\n"
        "Market: {market}\n"
        "CEO Sub-question: {dept_question}\n\n"
        "Deliver:\n"
        "1. VIABLE / CONDITIONAL / UNVIABLE verdict\n"
        "2. Break-even PSF calculation (land cost + construction + margin)\n"
        "3. IRR range estimate (base / bull / bear scenario)\n"
        "4. Key financial risk and its quantified impact\n"
        "5. Recommended financial structure (equity/debt split)"
    ),
    "engineering": (
        "You are the Engineering Head reviewing a real estate pitch.\n"
        "Market: {market}\n"
        "CEO Sub-question: {dept_question}\n\n"
        "Deliver:\n"
        "1. FEASIBLE / CONDITIONAL / NOT_FEASIBLE verdict\n"
        "2. Top 3 regulatory or approval blockers (RERA, BDA, BBMP, STRR)\n"
        "3. Construction cost risk (₹/sqft range + key driver)\n"
        "4. Recommended product mix (1BHK/2BHK/3BHK % split) for this market\n"
        "5. Timeline estimate from land acquisition to RERA registration"
    ),
    "ops": (
        "You are the Operations Head reviewing a real estate pitch.\n"
        "Market: {market}\n"
        "CEO Sub-question: {dept_question}\n\n"
        "Deliver:\n"
        "1. Recommended channel mix (channel partner % / direct % / digital %)\n"
        "2. Quarterly sales velocity assumption (units/quarter)\n"
        "3. Three launch KPIs with target numbers\n"
        "4. Biggest operational risk in this market\n"
        "5. Suggested launch window (month + rationale)"
    ),
}


def _build_bd_agent():
    from crewai import Agent

    return Agent(
        role="VP — Business Development & Investment Decisions",
        goal="Evaluate market pitch and deliver GO/NO-GO with 3 risks and 3 upsides.",
        backstory="""Sharp, numbers-first real-estate operator who turns noisy market intelligence into investment decisions.
        Tracks absorption, competitor launches, developer credibility, pricing power, and land-entry timing.
        Challenges every optimistic assumption and converts field signals into a clear GO/NO-GO recommendation.""",
        llm=get_analysis_llm(),
        max_iter=2,
        allow_delegation=False,
        verbose=False,
    )


def _build_finance_agent():
    from crewai import Agent

    return Agent(
        role="VP — Finance & Capital Strategy",
        goal="Assess deal viability, break-even PSF, IRR range, downside risk, and funding structure.",
        backstory="""Conservative finance leader focused on margin of safety, cash conversion, land-cost discipline,
        debt exposure, and scenario-adjusted returns. Converts market pitch assumptions into capital allocation logic.""",
        llm=get_analysis_llm(),
        max_iter=2,
        allow_delegation=False,
        verbose=False,
    )


def _build_engineering_agent():
    from crewai import Agent

    return Agent(
        role="VP — Engineering & Technical Delivery",
        goal="Assess feasibility and technical risks of land pitches, providing FEASIBLE/CONDITIONAL/NOT_FEASIBLE verdict with engineering budget delta.",
        backstory="""Principal architect-engineer who translates market intel into buildable reality.
        Understands FAR, setbacks, septic systems, road access constraints, BDA masterplan zones, and RERA compliance.
        Flags approval bottlenecks and design assumptions that could consume margin before ground is broken.""",
        llm=get_analysis_llm(),
        max_iter=2,
        allow_delegation=False,
        verbose=False,
    )


def _build_ops_agent():
    from crewai import Agent

    return Agent(
        role="VP — Operations & Market Execution",
        goal="Define the go-to-market playbook: channel strategy, sales velocity assumption, partner network, and KPIs.",
        backstory="""Operations director experienced in Bengaluru residential launches. Treats every project as a sales problem first
        and construction problem second. Interrogates buyer profile, launch differentiation, channel mix, partner readiness,
        quarterly sales velocity, and Day-1 execution KPIs.""",
        llm=get_analysis_llm(),
        max_iter=2,
        allow_delegation=False,
        verbose=False,
    )


def _run_dept_heads(pitch: str, market: str, decomposition: Optional[dict] = None,
                    _session_excluded: set = None) -> dict:
    """Run the four department-head agents concurrently via single-agent Crews.
    Returns a dict with keys 'bd', 'finance', 'engineering', 'ops'.
    Enforces a 90-second timeout guard.
    _session_excluded: per-session exclusion set — never mutates global _EXCLUDED.
    """
    from crewai import Task, Crew, Process
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

    _excl = _session_excluded if _session_excluded is not None else set()

    def run_single_agent(builder_fn, key: str) -> str:
        agent = builder_fn()
        dept_question = (
            decomposition.get(key, "").strip()
            if decomposition and isinstance(decomposition.get(key), str)
            else ""
        ) or pitch

        template = _DEPT_TASK_TEMPLATES.get(key)
        task_description = template.format(market=market, dept_question=dept_question) if template else (
            f"Market: {market}\nSub-question: {dept_question}\n\n"
            "Provide a structured one-page assessment with a clear verdict."
        )

        task = Task(
            description=task_description,
            expected_output=(
                "A structured assessment with: verdict (GO/NO-GO or VIABLE/CONDITIONAL/UNVIABLE or FEASIBLE/CONDITIONAL/NOT_FEASIBLE), "
                "numbered supporting points, and at least one specific number per point."
            ),
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        result = crew.kickoff()
        if hasattr(result, "tasks_output") and result.tasks_output:
            return result.tasks_output[0].raw or ""
        return getattr(result, "raw", str(result))

    builders = {
        "bd": _build_bd_agent,
        "finance": _build_finance_agent,
        "engineering": _build_engineering_agent,
        "ops": _build_ops_agent,
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
        except FuturesTimeoutError:
            for f in future_to_key:
                f.cancel()
            logger.warning("board_room: dept-head timeout — partial responses returned")
    return responses

def _to_uuid(s: str):
    from uuid import UUID
    return UUID(s)


def _create_session_row(session_id: str, pitch: str, market: Optional[str]) -> bool:
    """Insert a pending session row into board_sessions. Non-fatal on failure.

    Schema: pitch_text, individual dept columns, no JSONB transcript.
    Passes session_id as uuid.UUID object — psycopg2 handles the type mapping.
    """
    try:
        with _get_engine().begin() as conn:
            conn.execute(
                text("""
                INSERT INTO board_sessions (
                    session_id, pitch_text, market, status, initiated_by, created_at
                ) VALUES (
                    :session_id, :pitch_text, :market, 'pending', 'ceo', NOW()
                )
                """),
                {
                    "session_id": _to_uuid(session_id),
                    "pitch_text": pitch,
                    "market": market or "",
                },
            )
        return True
    except Exception as exc:
        logger.warning(f"board_room: failed to create session row {session_id}: {exc}")
        return False


def _update_session_row(session_id: str, status: str, transcript: dict) -> bool:
    """Update session row with individual dept-head column values.

    transcript dict keys: status, responses (bd/finance/engineering/ops),
    actions (list), ceo_decomposition (optional).
    Sets completed_at only on terminal states (complete/failed).
    """
    is_terminal = status in ("complete", "failed")
    responses = transcript.get("responses", {})
    ceo_extra = {
        "actions": transcript.get("actions", []),
        "ceo_decomposition": transcript.get("ceo_decomposition"),
        "error": transcript.get("error"),
    }
    ceo_synthesis = json.dumps(ceo_extra, default=str) if any(ceo_extra.values()) else None
    try:
        with _get_engine().begin() as conn:
            conn.execute(
                text("""
                UPDATE board_sessions
                SET status               = :status,
                    bd_response          = :bd,
                    finance_response     = :finance,
                    engineering_response = :engineering,
                    ops_response         = :ops,
                    ceo_synthesis        = :ceo_synthesis,
                    completed_at         = CASE WHEN :is_terminal THEN NOW() ELSE completed_at END
                WHERE session_id = :session_id
                """),
                {
                    "session_id": _to_uuid(session_id),
                    "status": status,
                    "bd": responses.get("bd") or None,
                    "finance": responses.get("finance") or None,
                    "engineering": responses.get("engineering") or None,
                    "ops": responses.get("ops") or None,
                    "ceo_synthesis": ceo_synthesis,
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
            "Return ONLY a JSON array, each item: {\"action\": \"...\", \"owner\": \"bd|finance|engineering|ops\", \"priority\": \"high|medium|low\", \"timeline\": \"...\"}. "
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
            cleaned = []
            for item in actions:
                if not isinstance(item, dict):
                    continue
                cleaned.append({
                    "owner": str(item.get("owner") or ""),
                    "action": str(item.get("action") or ""),
                    "priority": str(item.get("priority") or "medium"),
                    "timeline": str(item.get("timeline") or "TBD"),
                })
            return cleaned
        logger.warning(f"board_room: action extraction returned non-list: {actions}")
        return []
    except Exception as exc:
        logger.warning(f"board_room: action extraction failed: {exc}")
        return []

def _run_board_session_bg(session_id: str, pitch: str, market: str) -> None:
    """Background worker: run dept heads, extract actions, update session row to complete or failed.
    Uses a per-session provider exclusion set — never touches the global pipeline _EXCLUDED."""
    _session_excluded: set = set()
    try:
        _update_session_row(session_id, "active", {"status": "active", "responses": {}})
        decomposition = _ceo_decompose(pitch, market, _session_excluded)
        dept_responses = _run_dept_heads(pitch, market, decomposition, _session_excluded)
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
    """Fetch a board session from DB by session_id. Returns None if not found.

    Synthesises a 'transcript' dict from individual dept-head columns so the
    API response matches the shape the dashboard JS expects.
    """
    try:
        with _get_engine().connect() as conn:
            row = conn.execute(
                text("""
                SELECT session_id, pitch_text, market, status,
                       bd_response, finance_response, engineering_response,
                       ops_response, ceo_synthesis,
                       created_at, completed_at
                FROM board_sessions
                WHERE session_id = :session_id
                """),
                {"session_id": _to_uuid(session_id)},
            ).mappings().fetchone()
            if row is None:
                return None

            # Build transcript dict for API/dashboard compatibility
            responses = {
                "bd": row["bd_response"],
                "finance": row["finance_response"],
                "engineering": row["engineering_response"],
                "ops": row["ops_response"],
            }
            ceo_extra = {}
            if row["ceo_synthesis"]:
                try:
                    ceo_extra = json.loads(row["ceo_synthesis"]) if isinstance(row["ceo_synthesis"], str) else dict(row["ceo_synthesis"])
                except Exception:
                    pass

            transcript = {
                "status": row["status"],
                "responses": {k: v for k, v in responses.items() if v},
                "actions": ceo_extra.get("actions", []),
            }
            if ceo_extra.get("ceo_decomposition"):
                transcript["ceo_decomposition"] = ceo_extra["ceo_decomposition"]
            if ceo_extra.get("error"):
                transcript["error"] = ceo_extra["error"]

            return {
                "session_id": str(row["session_id"]),
                "pitch": row["pitch_text"],
                "market": row["market"],
                "status": row["status"],
                "transcript": transcript,
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
