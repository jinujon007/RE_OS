"""
RE_OS Dashboard — Board Room routes
"""

import json
import logging
import os
import time

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text as _sa_text

from dashboard.state import limiter, _get_sa_engine, _normalize_market, _VALID_BOARD_MARKETS

logger = logging.getLogger("re_os.dashboard")

router = APIRouter(tags=["Board Room"])


@router.post(
    "/api/board/session",
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
        return JSONResponse(
            {"error": "pitch required and must be under 2000 characters"},
            status_code=400,
        )
    if market not in _VALID_BOARD_MARKETS:
        return JSONResponse(
            {"error": "invalid market - must be Yelahanka, Devanahalli, or Hebbal"},
            status_code=400,
        )
    t0 = time.perf_counter()
    result = run_board_session(pitch, market)
    elapsed = time.perf_counter() - t0
    result["response_time_s"] = round(elapsed, 2)
    return result


@router.get(
    "/api/board/session/{session_id}",
    summary="Get board session by ID",
)
@limiter.limit("120/minute")
async def board_session_get(request: Request, session_id: str):
    from crews.board_room import get_board_session
    session = get_board_session(session_id)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    return session


@router.get(
    "/api/board/sessions",
    summary="List recent board sessions",
)
@limiter.limit("60/minute")
async def board_sessions(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                SELECT session_id, market, status, created_at, pitch_text
                FROM board_sessions ORDER BY created_at DESC LIMIT 20
            """)
            ).fetchall()
        result = []
        for r in rows:
            pitch = r[4] or ""
            result.append({
                "session_id": str(r[0]),
                "market": r[1],
                "status": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
                "pitch_excerpt": pitch[:120] + ("\u2026" if len(pitch) > 120 else ""),
            })
        return {"sessions": result}
    except Exception as e:
        logger.error("[board_sessions] %s", e)
        return JSONResponse({"sessions": [], "error": "database query failed"})


@router.get(
    "/api/engineering/brief",
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
        return JSONResponse({"error": "database query failed"}, status_code=500)


@router.get(
    "/api/alerts",
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
        return JSONResponse({"error": "database query failed"}, status_code=500)


@router.get(
    "/api/finance/brief",
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
        return JSONResponse({"error": "database query failed"}, status_code=500)


@router.get(
    "/api/legal/brief",
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
        return JSONResponse({"error": "database query failed"}, status_code=500)
