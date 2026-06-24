"""
RE_OS Dashboard — Board Room routes
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text as _sa_text

from dashboard.state import limiter, _get_sa_engine, _normalize_market, _VALID_BOARD_MARKETS, _err_resp



class ObsidianExportResponse(BaseModel):
    """Pydantic model for ``GET /board/sessions/{id}/obsidian-export``."""

    filename: str
    content: str
    frontmatter: dict
    decision_flag: str | None = None
    dept_count: int = 0

logger = logging.getLogger("re_os.dashboard")

router = APIRouter(tags=["Board Room"])


@router.post(
    "/board/session",
    summary="Create board session",
)
@limiter.limit("20/hour")
async def board_session_create(request: Request):
    from crews.board_room import run_board_session
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    pitch = str(payload.get("pitch") or "").strip()
    market = str(payload.get("market") or "").strip()
    if not pitch or len(pitch) > 2000:
        return _err_resp("pitch required and must be under 2000 characters", request, 400, "Board Room")
    if market not in _VALID_BOARD_MARKETS:
        return _err_resp("invalid market - must be Yelahanka, Devanahalli, or Hebbal", request, 400, "Board Room")
    t0 = time.perf_counter()
    result = run_board_session(pitch, market)
    elapsed = time.perf_counter() - t0
    result["response_time_s"] = round(elapsed, 2)
    return result


@router.get(
    "/board/session/{session_id}",
    summary="Get board session by ID",
)
@limiter.limit("120/minute")
async def board_session_get(request: Request, session_id: str):
    from crews.board_room import get_board_session
    session = get_board_session(session_id)
    if not session:
        return _err_resp("not found", request, 404, "Board Room")
    return session


@router.get(
    "/board/sessions",
    summary="List recent board sessions",
)
@limiter.limit("60/minute")
async def board_sessions(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                SELECT session_id, market, status, created_at, pitch_text, ceo_synthesis
                FROM board_sessions ORDER BY created_at DESC LIMIT 20
            """)
            ).fetchall()
        result = []
        for r in rows:
            pitch = r[4] or ""
            decision_flag = None
            if r[5]:
                try:
                    synth = json.loads(r[5]) if isinstance(r[5], str) else r[5]
                    decision_flag = synth.get("decision_flag")
                except Exception:
                    pass
            result.append({
                "session_id": str(r[0]),
                "market": r[1],
                "status": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
                "pitch_excerpt": pitch[:120] + ("\u2026" if len(pitch) > 120 else ""),
                "decision_flag": decision_flag,
            })
        return {"sessions": result}
    except Exception as e:
        logger.error("[board_sessions] %s", e)
        return JSONResponse({"sessions": [], "error": "database query failed", "code": "INTERNAL_ERROR"})


@router.get(
    "/board/sessions/{session_id}/obsidian-export",
    summary="Get board session formatted for Obsidian paste",
    response_model=ObsidianExportResponse,
)
@limiter.limit("30/minute")
async def board_session_obsidian_export(request: Request, session_id: str):
    # Validate session_id is a UUID before hitting the DB
    try:
        uuid.UUID(session_id)
    except (ValueError, AttributeError):
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_SESSION_ID",
                    "detail": "session_id must be a valid UUID",
                },
                "filename": None, "content": None, "frontmatter": {},
                "decision_flag": None, "dept_count": 0,
            },
            status_code=400,
        )

    try:
        with _get_sa_engine().connect() as conn:
            row = conn.execute(
                _sa_text("""
                SELECT
                    session_id, market, pitch_text, status,
                    bd_response, finance_response, engineering_response,
                    ops_response, legal_response, ceo_synthesis,
                    created_at, completed_at
                FROM board_sessions WHERE session_id = :sid
            """),
                {"sid": session_id},
            ).fetchone()
    except Exception as e:
        logger.error("[board_session_obsidian_export] DB error: %s", e)
        return JSONResponse(
            {
                "error": {"code": "DB_ERROR", "detail": "database query failed"},
                "filename": None, "content": None, "frontmatter": {},
                "decision_flag": None, "dept_count": 0,
            },
            status_code=500,
        )

    if not row:
        return JSONResponse(
            {
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "detail": "No board session with this ID",
                },
                "filename": None, "content": None, "frontmatter": {},
                "decision_flag": None, "dept_count": 0,
            },
            status_code=404,
        )

    mapping = row._mapping
    market = mapping.get("market") or ""
    pitch = mapping.get("pitch_text") or ""
    status_val = mapping.get("status") or "unknown"
    created = mapping["created_at"].isoformat() if mapping.get("created_at") else ""
    completed = mapping["completed_at"].isoformat() if mapping.get("completed_at") else ""

    dept_keys: list[tuple[str, str]] = [
        ("bd_response", "BD Head"),
        ("finance_response", "Finance Head"),
        ("engineering_response", "Engineering Head"),
        ("ops_response", "Operations Head"),
        ("legal_response", "Legal Head"),
    ]

    lines: list[str] = [
        "---",
        "type: crystallization",
        "area: lls",
        "ai_generated: true",
        f"generated_at: {created}",
        f"market: {market}",
        "source: board_room",
        f"pitch: {pitch[:120]}",
        "---",
        "",
        f"# Board Room Session - {market}",
        "",
        f"**Session ID:** {session_id}",
        f"**Status:** {status_val}",
        f"**Pitch:** {pitch}",
        "",
    ]

    dept_count = 0
    for col, label in dept_keys:
        text = mapping.get(col) or ""
        if text:
            dept_count += 1
            lines.append(f"## {label}")
            lines.append("")
            try:
                parsed = json.loads(text) if isinstance(text, str) else text
                if isinstance(parsed, dict):
                    for k, v in parsed.items():
                        lines.append(f"- **{k}:** {v}")
                else:
                    lines.append(str(parsed))
            except (json.JSONDecodeError, TypeError):
                lines.append(str(text))
            lines.append("")

    synth = mapping.get("ceo_synthesis") or ""
    decision_flag: str | None = None
    if synth:
        lines.append("## CEO Synthesis")
        lines.append("")
        try:
            parsed = json.loads(synth) if isinstance(synth, str) else synth
            if isinstance(parsed, dict):
                decision_flag = parsed.get("decision_flag")
                for k, v in parsed.items():
                    lines.append(f"- **{k}:** {v}")
            else:
                lines.append(str(parsed))
        except (json.JSONDecodeError, TypeError):
            lines.append(str(synth))
        lines.append("")

    if completed:
        lines.append(f"**Completed at:** {completed}")

    content = "\n".join(lines)
    frontmatter = {
        "type": "crystallization",
        "area": "lls",
        "ai_generated": True,
        "generated_at": created,
        "market": market,
        "source": "board_room",
    }
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"(AI) Board Room Verdict {market} {date_str}.md"

    from config.metrics import obsidian_export_total
    obsidian_export_total.labels(source="board_export").inc()

    return ObsidianExportResponse(
        filename=filename,
        content=content,
        frontmatter=frontmatter,
        decision_flag=decision_flag,
        dept_count=dept_count,
    )


@router.get(
    "/engineering/brief",
    summary="Latest Engineering Head response",
)
@limiter.limit("30/minute")
async def engineering_brief(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            row = conn.execute(
                _sa_text("""
                SELECT session_id, market, engineering_response, created_at
                FROM board_sessions
                WHERE engineering_response IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
            """)
            ).fetchone()
        if not row:
            return {"brief": None}
        created = row[3].isoformat() if row[3] else None
        return {
            "brief": {
                "session_id": str(row[0]),
                "market": row[1],
                "response": row[2],
                "created_at": created,
            }
        }
    except Exception as e:
        logger.error("[engineering_brief] %s", e)
        return _err_resp("database query failed", request, 500, "Board Room")


@router.get(
    "/alerts",
    summary="List recent alerts",
)
@limiter.limit("30/minute")
async def list_alerts(request: Request, channel: str = Query(None)):
    try:
        with _get_sa_engine().connect() as conn:
            where = "WHERE channel = :ch" if channel else ""
            params = {"ch": channel} if channel else {}
            rows = conn.execute(
                _sa_text(
                    f"SELECT id, channel, title, status, created_at FROM alerts "
                    f"{where} ORDER BY created_at DESC LIMIT 50"
                ),
                params,
            ).fetchall()
        result = [
            {
                "id": str(r[0]), "channel": r[1], "title": r[2],
                "status": r[3], "created_at": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ]
        return {"alerts": result}
    except Exception as e:
        logger.error("[list_alerts] %s", e)
        return _err_resp("database query failed", request, 500, "Board Room")


@router.get(
    "/finance/brief",
    summary="Latest Finance Head response",
)
@limiter.limit("30/minute")
async def finance_brief(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            row = conn.execute(
                _sa_text("""
                SELECT session_id, market, finance_response, created_at
                FROM board_sessions
                WHERE finance_response IS NOT NULL
                ORDER BY created_at DESC LIMIT 1
            """)
            ).fetchone()
        if not row:
            return {"brief": None}
        created = row[3].isoformat() if row[3] else None
        return {
            "brief": {
                "session_id": str(row[0]),
                "market": row[1],
                "response": row[2],
                "created_at": created,
            }
        }
    except Exception as e:
        logger.error("[finance_brief] %s", e)
        return _err_resp("database query failed", request, 500, "Board Room")


@router.get(
    "/legal/brief",
    summary="Latest Legal Head response",
)
@limiter.limit("30/minute")
async def legal_brief(request: Request, market: str = Query(None)):
    canonical = _normalize_market(market)
    try:
        with _get_sa_engine().connect() as conn:
            where = "WHERE legal_response IS NOT NULL"
            params = {}
            if canonical and canonical != "all":
                where += " AND market = :m"
                params["m"] = canonical
            row = conn.execute(
                _sa_text(f"""
                SELECT session_id, market, legal_response, created_at
                FROM board_sessions {where}
                ORDER BY created_at DESC LIMIT 1
            """),
                params,
            ).fetchone()
        if not row:
            return {"brief": None}
        created = row[3].isoformat() if row[3] else None
        return {
            "brief": {
                "session_id": str(row[0]),
                "market": row[1],
                "response": row[2],
                "created_at": created,
            }
        }
    except Exception as e:
        logger.error("[legal_brief] %s", e)
        return _err_resp("database query failed", request, 500, "Board Room")
