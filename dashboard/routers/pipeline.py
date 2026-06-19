"""
RE_OS Dashboard — Pipeline control routes
"""

import copy
import json
import logging
import os
import time

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import text as _sa_text

from dashboard.state import (
    limiter, _get_sa_engine, _normalize_market, _detect_market_from_prompt,
    _latest_report_path, _log_running_lifecycle_MUST_HOLD_LOCK, _prune_finished_running_entries_locked,
    _start_pipeline_for_market, _stop_pipeline_for_market, _running_snapshot,
    _market_go_no_go, _validate_registry_payload, _is_run_api_authorized,
    _agent_states, _lock, AGENT_ACTIONS,
    VALID_MARKETS, MARKET_CANONICAL, MARKET_SLUG, LOG_PATH,
    _running, _diag_agents_contract_logged, _err_resp,
)

logger = logging.getLogger("re_os.dashboard")

router = APIRouter(tags=["Pipeline"])


@router.post(
    "/run/{market}",
    summary="Start pipeline for a market",
)
@limiter.limit("10/hour")
async def run_pipeline(request: Request, market: str):
    canonical = _normalize_market(market)
    if not canonical:
        return _err_resp("invalid market", request, 400, "Pipeline")
    payload, status_code = _start_pipeline_for_market(canonical)
    return JSONResponse(payload, status_code=status_code)


@router.delete(
    "/run/{market}",
    summary="Stop running pipeline",
)
async def stop_pipeline(market: str):
    canonical = _normalize_market(market)
    if not canonical:
        return _err_resp("invalid market", None, 400, "Pipeline")
    payload, status_code = _stop_pipeline_for_market(canonical)
    return JSONResponse(payload, status_code=status_code)


@router.get("/status", summary="Pipeline running status snapshot")
def run_status():
    return _running_snapshot()


@router.get(
    "/agents",
    summary="Full agent state — DB agents + registry + running",
)
def agents_state():
    global _diag_agents_contract_logged
    db_agents = {}
    try:
        with _get_sa_engine().connect() as conn:
            runs = conn.execute(
                _sa_text("""
                SELECT agent_name, status, MAX(started_at) as last_run, COUNT(*) as total_runs
                FROM agent_runs GROUP BY agent_name, status ORDER BY last_run DESC
            """)
            ).fetchall()
            for row in runs:
                agent_name, status, last_run, total_runs = row
                if agent_name not in db_agents:
                    db_agents[agent_name] = {
                        "id": agent_name,
                        "name": agent_name.replace("_", " ").title(),
                        "role": agent_name.replace("_", " ").title(),
                        "label": status.upper() if status else "IDLE",
                        "state": status if status else "idle",
                        "last_action": f"Last run: {last_run}" if last_run else "No recent activity",
                        "started": last_run.isoformat() if hasattr(last_run, "isoformat") else str(last_run) if last_run else None,
                    }
            try:
                reg = conn.execute(
                    _sa_text("""
                    SELECT id, name, role, department, llm_tier, active, hired_on
                    FROM agent_registry ORDER BY department, name
                """)
                ).fetchall()
                for row in reg:
                    aid = row[0]
                    if aid not in db_agents:
                        db_agents[aid] = {
                            "id": aid, "name": row[1], "role": row[2],
                            "department": row[3], "label": "REGISTERED",
                            "state": "idle", "last_action": f"Registered: {row[2]} in {row[3] or '-'}",
                            "started": row[6].isoformat() if row[6] else None, "llm_tier": row[4],
                        }
            except Exception as reg_e:
                logger.warning("[DIAG agents] registry merge failed: %s", reg_e)
    except Exception as e:
        logger.warning("[DIAG agents] DB query failed, falling back to in-memory: %s", e)
    if not db_agents:
        with _lock:
            states_copy = copy.deepcopy(_agent_states)
            running_copy = {}
            for market, entry in _running.items():
                rc = entry["proc"].poll()
                running_copy[market] = {
                    "started": entry.get("started"),
                    "state": "running" if rc is None else ("done" if rc == 0 else "failed"),
                    "returncode": rc, "pid": entry["proc"].pid,
                }
        response = {"agents": states_copy, "running_markets": running_copy}
        response.update(states_copy)
        _diag_agents_contract_logged = True
        return response
    with _lock:
        states_copy = copy.deepcopy(db_agents)
        running_copy = {}
        for market, entry in _running.items():
            rc = entry["proc"].poll()
            running_copy[market] = {
                "started": entry.get("started"),
                "state": "running" if rc is None else ("done" if rc == 0 else "failed"),
                "returncode": rc, "pid": entry["proc"].pid,
            }
    response = {"agents": states_copy, "running_markets": running_copy}
    response.update(states_copy)
    if not _diag_agents_contract_logged:
        source_label = "DB" if db_agents else "in-memory"
        logger.info(
            "[DIAG agents] /agents keys=%s nested_agents=%s (from %s)",
            sorted(response.keys()), sorted(states_copy.keys()), source_label,
        )
        _diag_agents_contract_logged = True
    return response


@router.post(
    "/agents/{agent_id}/command",
    summary="Send command to an agent (run/stop/status)",
)
@limiter.limit("30/hour")
async def agent_command(request: Request, agent_id: str):
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = {}
    prompt = str(body.get("prompt") or "")
    market_from_body = _normalize_market(str(body.get("market") or ""))
    market_from_prompt = _detect_market_from_prompt(prompt)
    chosen_market = market_from_body or market_from_prompt
    if not chosen_market and any(
        k in prompt.lower() for k in ["run", "start", "scrape", "scan", "analyse", "analyze", "stop", "cancel"]
    ):
        chosen_market = "Yelahanka"
    text = prompt.lower()
    if agent_id not in _agent_states:
        return JSONResponse({
            "status": "unknown_command", "action": "invalid_agent",
            "details": f"Unknown agent_id '{agent_id}'",
            "hint": "Try: run [market], stop [market], status",
        }, status_code=404)
    if any(k in text for k in ["run", "start", "scrape", "scan", "analyse", "analyze"]):
        market = chosen_market or "Yelahanka"
        payload, status_code = _start_pipeline_for_market(market)
        return JSONResponse({
            "status": "accepted" if payload.get("status") in {"started", "already_running"} else "unknown_command",
            "action": "run_pipeline", "details": f"{payload.get('status')} for {market}",
            "market": market, "pipeline": payload,
        }, status_code=status_code)
    if any(k in text for k in ["stop", "cancel"]):
        market = chosen_market or "Yelahanka"
        payload, status_code = _stop_pipeline_for_market(market)
        return JSONResponse({
            "status": "accepted" if payload.get("status") in {"stopped", "not_running"} else "unknown_command",
            "action": "stop_pipeline", "details": f"{payload.get('status')} for {market}",
            "market": market, "pipeline": payload,
        }, status_code=status_code)
    if any(k in text for k in ["status", "report", "show"]):
        report_market = chosen_market if chosen_market and chosen_market != "all" else None
        report_path = _latest_report_path(report_market)
        return {
            "status": "accepted", "action": "status_report",
            "details": "Returned current agent state and latest report path",
            "market": chosen_market, "report_path": report_path,
            "agents": copy.deepcopy(_agent_states),
            "running_markets": _running_snapshot(),
        }
    return JSONResponse({
        "status": "unknown_command", "action": "none",
        "details": "No action matched prompt",
        "hint": "Try: run [market], stop [market], status",
    })


@router.get(
    "/agents/{agent_id}/actions",
    summary="List available actions for an agent",
)
def agent_actions(agent_id: str):
    if agent_id not in _agent_states and agent_id not in AGENT_ACTIONS:
        return _err_resp(f"Unknown agent '{agent_id}'", None, 404, "Pipeline")
    return {"agent_id": agent_id, "actions": AGENT_ACTIONS.get(agent_id, [])}


@router.get(
    "/sentinel/status", summary="Current sentinel run status"
)
def sentinel_status():
    try:
        from agents.sentinel_agent import get_last_scheduled_run, get_next_scheduled_run
        last = get_last_scheduled_run()
        nxt = get_next_scheduled_run()
        with _lock:
            if "sentinel" in _agent_states:
                if last and "error" not in last:
                    _agent_states["sentinel"]["last_action"] = (
                        f"Last: {last.get('status', '?')} \u00b7 Next: {nxt.get('label', '?')}"
                    )
                else:
                    _agent_states["sentinel"]["last_action"] = f"Next run: {nxt.get('label', '?')}"
        return {"last_run": last, "next_run": nxt}
    except Exception as e:
        logger.exception("sentinel_status failed")
        with _lock:
            if "sentinel" in _agent_states:
                _agent_states["sentinel"]["last_action"] = "Sentinel error: check logs"
        return JSONResponse({
            "last_run": {"error": str(e)},
            "next_run": {"next_run_utc": None, "in_hours": None, "in_minutes": None, "label": "unavailable"},
        })


@router.get(
    "/logs/stream", tags=["Logs"], summary="SSE log stream for a market pipeline"
)
def stream_logs(market: str = Query(None)):
    market_raw = (market or "").strip().lower()
    canonical = MARKET_CANONICAL.get(market_raw)
    slug = MARKET_SLUG.get(canonical) if canonical else None
    candidate = f"/app/logs/{slug}.log" if slug else None
    log_path = candidate if (candidate and os.path.exists(candidate)) else LOG_PATH

    def generate():
        TAIL_BYTES = 32768
        try:
            while True:
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(0, 2)
                        file_size = f.tell()
                        f.seek(max(0, file_size - TAIL_BYTES))
                        if file_size > TAIL_BYTES:
                            f.readline()
                        for line in f.readlines()[-80:]:
                            yield f"data: {json.dumps(line.rstrip())}\n\n"
                        last_pos = f.tell()
                        while True:
                            line = f.readline()
                            if line:
                                last_pos = f.tell()
                                yield f"data: {json.dumps(line.rstrip())}\n\n"
                            else:
                                f.seek(0, 2)
                                if f.tell() < last_pos:
                                    break
                                f.seek(last_pos)
                                yield ": heartbeat\n\n"
                                time.sleep(0.4)
                except FileNotFoundError:
                    yield f"data: {json.dumps('-- log file not found. Run a pipeline to start. --')}\n\n"
                    time.sleep(3)
        except GeneratorExit:
            pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
