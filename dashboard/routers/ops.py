"""
RE_OS Dashboard — Operations/Tasks/Registry/Deals/Portfolio/Evaluate routes
"""

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, date, timezone

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy import text as _sa_text

from dashboard.state import (
    limiter, _get_sa_engine, templates, _normalize_market,
    _validate_registry_payload, _is_run_api_authorized,
    _registry_cache, _REGISTRY_CACHE_TTL,
    _resolve_market, _all_markets, VALID_MARKETS_DIGEST,
    _err_resp,
)
from config.metrics import db_query_duration_seconds, digest_runs_total
from utils.etag import compute_etag, check_etag, add_etag
from utils.prediction_ledger import compute_accuracy_summary

logger = logging.getLogger("re_os.dashboard")

router = APIRouter(tags=["Ops"])


# ── Tasks ────────────────────────────────────────────────────────────────────


@router.get("/tasks", summary="List tasks with optional status/owner filter")
@limiter.limit("60/minute")
async def list_tasks(request: Request, status: str = Query(None), owner: str = Query(None)):
    try:
        with _get_sa_engine().connect() as conn:
            where_clauses, params = [], {}
            if status:
                where_clauses.append("status = :st")
                params["st"] = status
            if owner:
                where_clauses.append("owner = :ow")
                params["ow"] = owner
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            rows = conn.execute(
                _sa_text(
                    f"SELECT id, title, owner, status, priority, source_type, source_id, created_at "
                    f"FROM tasks {where_sql} ORDER BY created_at DESC LIMIT 200"
                ),
                params,
            ).fetchall()
        return {
            "tasks": [
                {
                    "id": str(r[0]), "title": r[1], "owner": r[2], "status": r[3],
                    "priority": r[4], "source_type": r[5],
                    "source_id": str(r[6]) if r[6] else None,
                    "created_at": r[7].isoformat() if r[7] else None,
                }
                for r in rows
            ]
        }
    except Exception as e:
        logger.error("[list_tasks] %s", e)
        return _err_resp("database query failed", request, 500, "Ops")


@router.post("/tasks", summary="Create a new task", status_code=201)
@limiter.limit("30/minute")
async def create_task(request: Request):
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    title = str(payload.get("title") or "").strip()
    owner = str(payload.get("owner") or "").strip()[:50]
    priority = str(payload.get("priority") or "medium").strip()
    source_type = str(payload.get("source_type") or "").strip()[:30]
    source_id_raw = payload.get("source_id")
    if not title:
        return _err_resp("title required", request, 400, "Ops")
    if priority not in ("high", "medium", "low"):
        priority = "medium"
    source_id = None
    if source_id_raw:
        try:
            source_id = str(uuid.UUID(str(source_id_raw)))
        except (ValueError, AttributeError):
            source_id = None
    try:
        with _get_sa_engine().begin() as conn:
            result = conn.execute(
                _sa_text("""INSERT INTO tasks (title, owner, priority, source_type, source_id)
                   VALUES (:t, :o, :p, :st, :si) RETURNING id"""),
                {"t": title, "o": owner or None, "p": priority, "st": source_type or None, "si": str(source_id) if source_id else None},
            )
            task_id = str(result.fetchone()[0])
        return JSONResponse({"task_id": task_id, "status": "queued"}, status_code=201)
    except Exception as e:
        logger.error("[create_task] %s", e)
        return _err_resp("database query failed", request, 500, "Ops")


@router.patch("/tasks/{task_id}", summary="Update task status")
@limiter.limit("60/minute")
async def update_task(request: Request, task_id: str):
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    new_status = str(payload.get("status") or "").strip()
    if new_status not in ("queued", "active", "done", "failed", "rejected"):
        return _err_resp("invalid status", request, 400, "Ops")
    try:
        tid = str(uuid.UUID(task_id))
    except ValueError:
        return _err_resp("invalid task_id", request, 400, "Ops")
    try:
        with _get_sa_engine().begin() as conn:
            result = conn.execute(
                _sa_text("UPDATE tasks SET status = :s, updated_at = NOW() WHERE id = :tid RETURNING id"),
                {"s": new_status, "tid": tid},
            )
            if result.fetchone() is None:
                return _err_resp("not found", request, 404, "Ops")
        return {"status": new_status}
    except Exception as e:
        logger.error("[update_task] %s", e)
        return _err_resp("database query failed", request, 500, "Ops")


# ── Registry ──────────────────────────────────────────────────────────────────


@router.get("/registry", summary="List registered agents")
@limiter.limit("30/minute")
async def list_registry(request: Request):
    now = time.time()
    cached = _registry_cache.get("all")
    if cached and cached[1] > now:
        return {"agents": cached[0], "cached": True}
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                SELECT id, name, role, department, llm_tier, active, hired_on
                FROM agent_registry ORDER BY department, name
            """)
            ).fetchall()
        result = [
            {
                "id": r[0], "name": r[1], "role": r[2], "department": r[3],
                "llm_tier": r[4], "active": r[5],
                "hired_on": r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ]
        _registry_cache["all"] = (result, now + _REGISTRY_CACHE_TTL)
        return {"agents": result}
    except Exception as e:
        logger.warning("[list_registry] DB query failed: %s", e)
        if cached:
            return {"agents": cached[0], "cached": True, "stale": True}
        return _err_resp("database query failed", request, 500, "Ops")


@router.post("/registry", summary="Hire a new agent from JSON spec", status_code=201)
async def hire_agent(request: Request):
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    validated, err = _validate_registry_payload(payload)
    if err:
        return _err_resp(err, request, 400, "Ops")
    import yaml
    spec_id = str(validated["id"]).strip()
    from agents.agent_factory import _REGISTRY_DIR
    spec_path = str(_REGISTRY_DIR / f"{spec_id}.yaml")
    if os.path.exists(spec_path):
        return _err_resp(f"agent '{spec_id}' already exists", request, 409, "Ops")
    try:
        os.makedirs(os.path.dirname(spec_path), exist_ok=True)
        with open(spec_path, "w", encoding="utf-8") as f:
            yaml.dump(validated, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except Exception as e:
        logger.error("[hire_agent] write failed: %s", e)
        return _err_resp("failed to write spec file", request, 500, "Ops")
    try:
        from agents.agent_factory import sync_registry_to_db
        synced = sync_registry_to_db()
        logger.info("[hire_agent] synced %d agents (including new '%s')", synced, spec_id)
    except Exception as e:
        logger.error("[hire_agent] db sync failed: %s", e)
        return JSONResponse({"warning": "spec written but DB sync failed", "spec_id": spec_id}, status_code=201)
    _registry_cache.pop("all", None)
    return JSONResponse({"status": "hired", "spec_id": spec_id}, status_code=201)


# ── Surveys ────────────────────────────────────────────────────────────────


class SurveyCreate(BaseModel):
    survey_no: str
    market: str
    total_area_acres: float
    land_type: str = "agricultural"
    encumbrance_clear: bool = False
    is_aggregated: bool = False


@router.post("/surveys", summary="Add a new survey for opportunity scoring", status_code=201)
async def create_survey(body: SurveyCreate, request: Request):
    try:
        with _get_sa_engine().begin() as conn:
            market_row = conn.execute(
                _sa_text("SELECT id FROM micro_markets WHERE name ILIKE :m LIMIT 1"),
                {"m": f"%{body.market}%"},
            ).fetchone()
            if not market_row:
                return _err_resp(f"market '{body.market}' not found", request, 404, "Ops")
            market_id = market_row[0]
            total_sqft = body.total_area_acres * 43560.0
            result = conn.execute(
                _sa_text("""INSERT INTO surveys (survey_no, micro_market_id, total_area_acres, total_area_sqft,
                                            land_type, encumbrance_clear, is_aggregated, dc_conversion_status)
                   VALUES (:sn, :mm, :ta, :ts, :lt, :ec, :ia, 'pending')
                   RETURNING id, survey_no, total_area_acres, total_area_sqft, land_type,
                             encumbrance_clear, is_aggregated, dc_conversion_status, created_at"""),
                {"sn": body.survey_no, "mm": market_id, "ta": body.total_area_acres, "ts": total_sqft,
                 "lt": body.land_type, "ec": body.encumbrance_clear, "ia": body.is_aggregated},
            )
            row = result.fetchone()
        return {
            "id": str(row[0]), "survey_no": row[1],
            "total_area_acres": float(row[2]), "total_area_sqft": float(row[3]),
            "land_type": row[4], "encumbrance_clear": row[5],
            "is_aggregated": row[6], "dc_conversion_status": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
        }
    except Exception as exc:
        logger.error("[create_survey] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


# ── Evaluate API ──────────────────────────────────────────────────────────────


_SURVEY_NO_RE = re.compile(r"^\d{1,4}/\d{1,4}$")


def _validate_survey_no(survey_no: str) -> str:
    s = survey_no.strip()
    if not _SURVEY_NO_RE.match(s):
        raise ValueError(f"Invalid survey_no format: '{survey_no}'. Expected pattern 'NNN/NNN' (e.g. '45/2', '102/45')")
    return s


class EvaluateRequest(BaseModel):
    survey_no: str
    market: str
    land_area_sqft: float = 43560.0
    sell_psf: float | None = None
    deal_type: str = "compare"
    pitch: str = ""


class EvaluateStartResponse(BaseModel):
    job_id: str
    status: str
    survey_no: str | None = None
    market: str | None = None
    message: str | None = None


@router.post("/evaluate", response_model=EvaluateStartResponse, summary="Start async deal evaluation pipeline")
@limiter.limit("10/minute")
async def evaluate_start(request: Request):
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    survey_no_raw = str(payload.get("survey_no") or "").strip()
    try:
        survey_no = _validate_survey_no(survey_no_raw)
    except ValueError as exc:
        return _err_resp(str(exc), request, 400, "Ops")
    market_raw = payload.get("market", "")
    market = _normalize_market(market_raw)
    if not market:
        return _err_resp("valid market required (Yelahanka/Devanahalli/Hebbal)", request, 400, "Ops")
    raw_area = payload.get("land_area_sqft", 43560)
    try:
        land_area_sqft = float(raw_area)
    except (ValueError, TypeError):
        return _err_resp("land_area_sqft must be a number", request, 400, "Ops")
    sell_psf = payload.get("sell_psf")
    if sell_psf is not None:
        try:
            sell_psf = float(sell_psf)
        except (ValueError, TypeError):
            return _err_resp("sell_psf must be a number", request, 400, "Ops")
    valid_deal_types = {"purchase", "jd", "jv", "compare"}
    deal_type = str(payload.get("deal_type", "compare")).strip().lower()
    if deal_type not in valid_deal_types:
        return _err_resp(f"deal_type must be one of: {', '.join(sorted(valid_deal_types))}", request, 400, "Ops")
    pitch = str(payload.get("pitch", "")).strip()[:5000]
    from crews.evaluate_pipeline import start_evaluate
    result = start_evaluate(
        survey_no=survey_no, market=market, land_area_sqft=land_area_sqft,
        sell_psf=sell_psf, deal_type=deal_type,
        pitch=pitch or f"Evaluate survey {survey_no} in {market}",
    )
    return result


class EvaluateJobResponse(BaseModel):
    job_id: str
    status: str
    progress_msg: str | None = None
    survey_no: str | None = None
    market: str | None = None
    land_area_sqft: float | None = None
    sell_psf: float | None = None
    deal_type: str | None = None
    pitch: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
    board_session: dict | None = None
    deal_memo: dict | None = None
    investor_brief: dict | None = None
    deal_id: str | None = None
    error: str | None = None


@router.get("/evaluate/{job_id}", response_model=EvaluateJobResponse, summary="Poll async evaluation job status")
@limiter.limit("30/minute")
async def evaluate_status(request: Request, job_id: str):
    from crews.evaluate_pipeline import get_evaluate_job
    job = get_evaluate_job(job_id)
    if job is None:
        return _err_resp("job not found", request, 404, "Ops")
    return job


class OpportunityItem(BaseModel):
    id: str | None = None
    survey_no: str | None = None
    market: str | None = None
    score: float = 0.0
    irr_score: float = 0.0
    legal_score: float = 0.0
    timing_score: float = 0.0
    distress_score: float = 0.0
    exclusivity_score: float = 0.0
    best_deal_type: str | None = None
    estimated_jd_irr: float | None = None
    legal_risk_level: str | None = None
    next_action: str | None = None
    expiry_date: str | None = None
    computed_at: str | None = None
    developer_name: str | None = None


class OpportunityQueueResponse(BaseModel):
    opportunities: list[OpportunityItem]
    count: int


@router.get("/opportunity/queue", response_model=OpportunityQueueResponse, summary="Ranked opportunity queue")
@limiter.limit("30/minute")
async def opportunity_queue(
    request: Request, market: str = Query(None), min_score: float = Query(None), limit: int = Query(default=50),
):
    market_filter = market
    min_score_val = 0.0
    if min_score:
        try:
            min_score_val = max(0.0, min(float(min_score), 1.0))
        except (ValueError, TypeError):
            min_score_val = 0.0
    try:
        limit = max(1, min(int(limit), 200))
    except (ValueError, TypeError):
        limit = 50
    try:
        with _get_sa_engine().connect() as conn:
            where_parts = ["os.is_active = true"]
            params = {}
            if market_filter:
                where_parts.append("mm.name ILIKE :m")
                params["m"] = f"%{market_filter}%"
            if min_score_val > 0:
                where_parts.append("os.score >= :ms")
                params["ms"] = min_score_val
            where_sql = " AND ".join(where_parts) if where_parts else "TRUE"
            params["lim"] = limit
            db_rows = conn.execute(
                _sa_text(f"""
                SELECT os.id, os.survey_no, mm.name AS market,
                       os.score, os.irr_score, os.legal_score, os.timing_score,
                       os.distress_score, os.exclusivity_score,
                       os.best_deal_type, os.estimated_jd_irr,
                       os.legal_risk_level, os.next_action, os.expiry_date,
                       os.computed_at, d.name AS developer_name
                FROM opportunity_scores os
                JOIN micro_markets mm ON mm.id = os.micro_market_id
                LEFT JOIN developers d ON d.id = os.developer_id
                WHERE {where_sql}
                ORDER BY os.score DESC
                LIMIT :lim
            """),
                params,
            ).fetchall()
        return {
            "opportunities": [
                {
                    "id": str(r[0]), "survey_no": r[1], "market": r[2],
                    "score": float(r[3]) if r[3] else 0.0,
                    "irr_score": float(r[4]) if r[4] else 0.0,
                    "legal_score": float(r[5]) if r[5] else 0.0,
                    "timing_score": float(r[6]) if r[6] else 0.0,
                    "distress_score": float(r[7]) if r[7] else 0.0,
                    "exclusivity_score": float(r[8]) if r[8] else 0.0,
                    "best_deal_type": r[9], "estimated_jd_irr": float(r[10]) if r[10] else None,
                    "legal_risk_level": r[11], "next_action": r[12],
                    "expiry_date": r[13].isoformat() if r[13] else None,
                    "computed_at": r[14].isoformat() if r[14] else None,
                    "developer_name": r[15],
                }
                for r in db_rows
            ],
            "count": len(db_rows),
        }
    except Exception as e:
        logger.error("[opportunity_queue] %s", e)
        return _err_resp("database query failed", request, 500, "Ops")


# ── LLM Quota ──────────────────────────────────────────────────────────────


@router.get("/llm/quota", summary="LLM daily token usage per provider")
@limiter.limit("30/minute")
async def llm_quota(request: Request):
    today = date.today().isoformat()
    providers = ["groq", "cerebras", "gemini", "nvidia", "sambanova", "cloudflare", "openrouter"]
    usage = {}
    try:
        import redis as _redis
        from config.settings import REDIS_URL
        r = _redis.from_url(REDIS_URL, decode_responses=True)
        for p in providers:
            val = r.get(f"llm:tokens:{p}:{today}")
            usage[p] = int(val) if val else 0
    except Exception:
        usage = {p: 0 for p in providers}
    return {"date": today, "usage": usage}


# ── Deal Pipeline ──────────────────────────────────────────────────────────


class DealCreate(BaseModel):
    survey_no: str
    market: str
    stage: str | None = None
    ask_psf: float | None = None
    area_acres: float | None = None
    notes: str | None = None
    opportunity_score: float | None = None


class DealUpdate(BaseModel):
    stage: str | None = None
    next_step: str | None = None
    next_step_due: str | None = None
    notes: str | None = None
    assigned_to: str | None = None
    ask_psf: float | None = None
    area_acres: float | None = None


_VALID_DEAL_STAGES = {"prospecting", "diligence", "negotiation", "loi", "signed", "dropped"}


@router.post("/deals", status_code=201, summary="Promote an opportunity to the deal pipeline")
async def create_deal(body: DealCreate, request: Request):
    if body.stage is not None and body.stage not in _VALID_DEAL_STAGES:
        return _err_resp(f"invalid stage: {body.stage}", request, 400, "Ops")
    try:
        with _get_sa_engine().begin() as conn:
            market_row = conn.execute(
                _sa_text("SELECT id FROM micro_markets WHERE name ILIKE :m LIMIT 1"),
                {"m": f"%{body.market}%"},
            ).fetchone()
            if not market_row:
                return _err_resp(f"market '{body.market}' not found", request, 404, "Ops")
            market_id = market_row[0]
            result = conn.execute(
                _sa_text("""INSERT INTO deal_pipeline (survey_no, micro_market_id, stage, opportunity_score, notes)
                   VALUES (:sn, :mm, :st, :os, :nt)
                   RETURNING id, survey_no, stage, opportunity_score, assigned_to,
                             next_step, next_step_due, notes, created_at, updated_at"""),
                {"sn": body.survey_no, "mm": market_id, "st": body.stage or "prospecting",
                 "os": body.opportunity_score, "nt": body.notes},
            )
            row = result.fetchone()
            new_stage = row[2] or ""
        if new_stage in ("loi", "signed"):
            try:
                from utils.discord_notifier import format_deal_alert, send
                msg = format_deal_alert(new_stage, body.market, body.survey_no, body.ask_psf, body.area_acres)
                send("bd_opportunities", f"Deal {new_stage.upper()}: {body.survey_no}", msg)
            except Exception as exc:
                logger.warning("[create_deal] Discord alert failed: %s", exc)
        return {
            "id": str(row[0]), "survey_no": row[1], "stage": row[2],
            "opportunity_score": float(row[3]) if row[3] else None,
            "assigned_to": row[4], "next_step": row[5],
            "next_step_due": row[6].isoformat() if row[6] else None, "notes": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
            "updated_at": row[9].isoformat() if row[9] else None,
        }
    except Exception as exc:
        logger.error("[create_deal] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/deals", summary="List all deals in pipeline")
async def list_deals(request: Request, stage: str = Query(None), market: str = Query(None)):
    try:
        with _get_sa_engine().connect() as conn:
            where_parts, params = [], {}
            if stage:
                where_parts.append("dp.stage = :st")
                params["st"] = stage
            if market:
                where_parts.append("mm.name ILIKE :m")
                params["m"] = f"%{market}%"
            where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            rows = conn.execute(
                _sa_text(f"""
                SELECT dp.id, dp.survey_no, mm.name, dp.stage, dp.opportunity_score,
                       dp.assigned_to, dp.next_step, dp.next_step_due, dp.notes,
                       dp.created_at, dp.updated_at
                FROM deal_pipeline dp
                LEFT JOIN micro_markets mm ON mm.id = dp.micro_market_id
                {where_sql}
                ORDER BY dp.created_at DESC
            """),
                params,
            ).fetchall()
        return [
            {
                "id": str(r[0]), "survey_no": r[1], "market": r[2], "stage": r[3],
                "opportunity_score": float(r[4]) if r[4] else None, "assigned_to": r[5],
                "next_step": r[6], "next_step_due": r[7].isoformat() if r[7] else None,
                "notes": r[8], "created_at": r[9].isoformat() if r[9] else None,
                "updated_at": r[10].isoformat() if r[10] else None,
            }
            for r in rows
        ]
    except Exception as exc:
        logger.error("[list_deals] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.patch("/deals/{deal_id}", summary="Update deal stage or notes")
async def update_deal(deal_id: str, body: DealUpdate, request: Request):
    try:
        tid = str(uuid.UUID(deal_id))
    except ValueError:
        return _err_resp("invalid deal_id", request, 400, "Ops")
    try:
        with _get_sa_engine().begin() as conn:
            existing = conn.execute(
                _sa_text("SELECT dp.id, dp.survey_no, dp.stage, dp.opportunity_score, mm.name FROM deal_pipeline dp LEFT JOIN micro_markets mm ON mm.id = dp.micro_market_id WHERE dp.id = :tid"),
                {"tid": tid},
            ).fetchone()
            if not existing:
                return _err_resp("deal not found", request, 404, "Ops")
            updates, params = [], {}
            if body.stage is not None:
                if body.stage not in _VALID_DEAL_STAGES:
                    return _err_resp(f"invalid stage: {body.stage}", request, 400, "Ops")
                updates.append("stage = :st")
                params["st"] = body.stage
            if body.next_step is not None:
                updates.append("next_step = :ns")
                params["ns"] = body.next_step
            if body.next_step_due is not None:
                updates.append("next_step_due = :nsd")
                params["nsd"] = body.next_step_due
            if body.notes is not None:
                updates.append("notes = :nt")
                params["nt"] = body.notes
            if body.assigned_to is not None:
                updates.append("assigned_to = :at")
                params["at"] = body.assigned_to
            if not updates:
                return _err_resp("no fields to update", request, 400, "Ops")
            updates.append("updated_at = NOW()")
            set_clause = ", ".join(updates)
            params["tid"] = tid
            row = conn.execute(
                _sa_text(f"UPDATE deal_pipeline SET {set_clause} WHERE id = :tid RETURNING id, survey_no, stage, opportunity_score, assigned_to, next_step, next_step_due, notes, created_at, updated_at"),
                params,
            ).fetchone()
        new_stage = body.stage
        if new_stage and new_stage in ("loi", "signed"):
            try:
                from utils.discord_notifier import format_deal_alert, send
                market_name = existing[4] or ""
                msg = format_deal_alert(new_stage, market_name, existing[1], body.ask_psf, body.area_acres)
                send("bd_opportunities", f"Deal {new_stage.upper()}: {existing[1]}", msg)
            except Exception as exc:
                logger.warning("[update_deal] Discord alert failed: %s", exc)
        return {
            "id": str(row[0]), "survey_no": row[1], "stage": row[2],
            "opportunity_score": float(row[3]) if row[3] else None,
            "assigned_to": row[4], "next_step": row[5],
            "next_step_due": row[6].isoformat() if row[6] else None, "notes": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
            "updated_at": row[9].isoformat() if row[9] else None,
        }
    except Exception as exc:
        logger.error("[update_deal] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


# ── Projects & Tasks (Operations) ──────────────────────────────────────────


_VALID_PROJECT_STATUSES = frozenset({"lead", "mou", "loi", "signed", "rera_applied", "construction", "possession", "delivered", "paused"})
_PROJECT_STAGE_ORDER = ["lead", "mou", "loi", "signed", "rera_applied", "construction", "possession", "delivered"]
_STAGE_RANK = {s: i for i, s in enumerate(_PROJECT_STAGE_ORDER)}
_VALID_TRANSITIONS = {
    s: {t for t in _PROJECT_STAGE_ORDER if _STAGE_RANK.get(t, -1) >= _STAGE_RANK.get(s, 0) and t != s} | {"paused"}
    for s in _PROJECT_STAGE_ORDER
}
_VALID_TRANSITIONS["paused"] = set(_PROJECT_STAGE_ORDER)

DEAL_PIPELINE_COLS = "id, survey_no, micro_market_id, stage, opportunity_score, assigned_to, next_step, next_step_due, notes, created_at, updated_at"


@router.post("/projects", status_code=201, summary="Create a new project")
@limiter.limit("30/hour")
async def create_project(request: Request):
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    name = str(payload.get("name") or "").strip()
    if not name:
        return _err_resp("name is required", request, 400, "Ops")
    if len(name) > 200:
        return _err_resp("name too long (max 200 chars)", request, 400, "Ops")
    st = str(payload.get("status") or "lead").lower()
    if st not in _VALID_PROJECT_STATUSES:
        return _err_resp(f"invalid status: {st}", request, 400, "Ops")
    try:
        with _get_sa_engine().begin() as conn:
            row = conn.execute(
                _sa_text("""
                    INSERT INTO projects (name, market, survey_no, deal_type, status, notes,
                                          start_date, target_close_date,
                                          source_deal_id, source_board_session_id)
                    VALUES (:name, :market, :survey_no, :deal_type, :status, :notes,
                            CAST(:start AS date), CAST(:target AS date),
                            CAST(:deal_id AS uuid), CAST(:board_id AS uuid))
                    RETURNING id, name, market, survey_no, deal_type, status, notes,
                              start_date, target_close_date, created_at, updated_at
                """),
                {
                    "name": name, "market": payload.get("market"), "survey_no": payload.get("survey_no"),
                    "deal_type": payload.get("deal_type"), "status": st,
                    "notes": payload.get("notes"), "start": payload.get("start_date"),
                    "target": payload.get("target_close_date"),
                    "deal_id": payload.get("source_deal_id") or None,
                    "board_id": payload.get("source_board_session_id") or None,
                },
            ).fetchone()
        return {
            "id": str(row[0]), "name": row[1], "market": row[2], "survey_no": row[3],
            "deal_type": row[4], "status": row[5], "notes": row[6],
            "start_date": row[7].isoformat() if row[7] else None,
            "target_close_date": row[8].isoformat() if row[8] else None,
            "created_at": row[9].isoformat() if row[9] else None,
            "updated_at": row[10].isoformat() if row[10] else None,
        }
    except Exception as exc:
        logger.error("[create_project] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/projects", summary="List projects with optional filters and pagination")
@limiter.limit("60/minute")
async def list_projects(
    request: Request, status: str = Query(None), market: str = Query(None),
    page: int = Query(default=1, ge=1), per_page: int = Query(default=50, ge=1, le=200),
):
    try:
        with _get_sa_engine().connect() as conn:
            where, params = [], {}
            if status:
                where.append("p.status = :st")
                params["st"] = status
            if market:
                where.append("p.market ILIKE :mkt")
                params["mkt"] = f"%{market}%"
            where_sql = ("WHERE " + " AND ".join(where)) if where else ""
            total = conn.execute(_sa_text(f"SELECT COUNT(*) FROM projects p {where_sql}"), params).scalar() or 0
            offset = (page - 1) * per_page
            rows = conn.execute(
                _sa_text(f"""
                    SELECT p.id, p.name, p.market, p.survey_no, p.deal_type, p.status,
                           p.notes, p.created_at,
                           EXTRACT(DAY FROM NOW() - p.created_at)::int AS days_in_stage,
                           COUNT(pt.id) FILTER (WHERE pt.status IN ('todo','in_progress')) AS open_tasks
                    FROM projects p
                    LEFT JOIN project_tasks pt ON pt.project_id = p.id
                    {where_sql}
                    GROUP BY p.id, p.name, p.market, p.survey_no, p.deal_type, p.status,
                             p.notes, p.created_at
                    ORDER BY p.created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {**params, "limit": per_page, "offset": offset},
            ).fetchall()
        return {
            "projects": [
                {
                    "id": str(r[0]), "name": r[1], "market": r[2], "survey_no": r[3],
                    "deal_type": r[4], "status": r[5], "notes": r[6],
                    "created_at": r[7].isoformat() if r[7] else None,
                    "days_in_stage": int(r[8]) if r[8] else 0,
                    "open_task_count": int(r[9]) if r[9] else 0,
                }
                for r in rows
            ],
            "total": total, "page": page, "per_page": per_page,
        }
    except Exception as exc:
        logger.error("[list_projects] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/projects/{project_id}", summary="Get project detail with tasks and velocity")
@limiter.limit("60/minute")
async def get_project(project_id: str, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
    except ValueError:
        return _err_resp("invalid project_id", request, 400, "Ops")
    try:
        with _get_sa_engine().connect() as conn:
            proj = conn.execute(
                _sa_text("""
                    SELECT id, name, market, survey_no, deal_type, status, notes,
                           start_date, target_close_date, actual_close_date,
                           created_at, updated_at,
                           EXTRACT(DAY FROM NOW() - created_at)::int AS days_in_stage
                    FROM projects WHERE id = :pid
                """),
                {"pid": pid},
            ).fetchone()
            if not proj:
                return _err_resp("project not found", request, 404, "Ops")
            tasks = conn.execute(
                _sa_text("""
                    SELECT id, title, owner_agent_id, dept, status, due_date,
                           completed_at, notes, created_at
                    FROM project_tasks WHERE project_id = :pid
                    ORDER BY due_date ASC NULLS LAST, created_at ASC
                """),
                {"pid": pid},
            ).fetchall()
            velocity = conn.execute(
                _sa_text("""
                    SELECT from_status, to_status, days_elapsed, transitioned_at
                    FROM deal_velocity WHERE project_id = :pid
                    ORDER BY transitioned_at ASC
                """),
                {"pid": pid},
            ).fetchall()
        return {
            "project": {
                "id": str(proj[0]), "name": proj[1], "market": proj[2], "survey_no": proj[3],
                "deal_type": proj[4], "status": proj[5], "notes": proj[6],
                "start_date": proj[7].isoformat() if proj[7] else None,
                "target_close_date": proj[8].isoformat() if proj[8] else None,
                "actual_close_date": proj[9].isoformat() if proj[9] else None,
                "created_at": proj[10].isoformat() if proj[10] else None,
                "updated_at": proj[11].isoformat() if proj[11] else None,
                "days_in_stage": int(proj[12]) if proj[12] else 0,
            },
            "tasks": [
                {
                    "id": str(t[0]), "title": t[1], "owner_agent_id": t[2], "dept": t[3],
                    "status": t[4], "due_date": t[5].isoformat() if t[5] else None,
                    "completed_at": t[6].isoformat() if t[6] else None, "notes": t[7],
                    "created_at": t[8].isoformat() if t[8] else None,
                }
                for t in tasks
            ],
            "velocity": {
                "stages": [
                    {
                        "from_status": v[0], "to_status": v[1],
                        "days_elapsed": int(v[2]) if v[2] else 0,
                        "transitioned_at": v[3].isoformat() if v[3] else None,
                    }
                    for v in velocity
                ],
                "current_stage": str(proj[5] or "lead"),
                "current_stage_days": int(proj[12]) if proj[12] else 0,
            },
        }
    except Exception as exc:
        logger.error("[get_project] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.patch("/projects/{project_id}", summary="Update project metadata")
@limiter.limit("30/hour")
async def update_project(project_id: str, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
    except ValueError:
        return _err_resp("invalid project_id", request, 400, "Ops")
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    try:
        updates, params = [], {"pid": pid}
        for field, col in [("name","name"),("market","market"),("survey_no","survey_no"),("deal_type","deal_type"),("notes","notes"),("start_date","start_date"),("target_close_date","target_close_date")]:
            val = payload.get(field)
            if val is not None:
                updates.append(f"{col} = :{field}")
                params[field] = val
        if not updates:
            return _err_resp("no fields to update", request, 400, "Ops")
        updates.append("updated_at = NOW()")
        set_clause = ", ".join(updates)
        with _get_sa_engine().begin() as conn:
            row = conn.execute(
                _sa_text(f"UPDATE projects SET {set_clause} WHERE id = :pid RETURNING id, name, market, survey_no, deal_type, status, notes, start_date, target_close_date, created_at, updated_at"),
                params,
            ).fetchone()
        if not row:
            return _err_resp("project not found", request, 404, "Ops")
        return {
            "id": str(row[0]), "name": row[1], "market": row[2], "survey_no": row[3],
            "deal_type": row[4], "status": row[5], "notes": row[6],
            "start_date": row[7].isoformat() if row[7] else None,
            "target_close_date": row[8].isoformat() if row[8] else None,
            "created_at": row[9].isoformat() if row[9] else None,
            "updated_at": row[10].isoformat() if row[10] else None,
        }
    except Exception as exc:
        logger.error("[update_project] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.patch("/projects/{project_id}/status", summary="Update project status with deal_velocity tracking")
@limiter.limit("30/hour")
async def update_project_status(project_id: str, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
    except ValueError:
        return _err_resp("invalid project_id", request, 400, "Ops")
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _err_resp("invalid JSON", request, 400, "Ops")
    new_status = str(payload.get("status") or "").strip().lower()
    if new_status not in _VALID_PROJECT_STATUSES:
        return _err_resp(f"invalid status: {new_status}", request, 400, "Ops")
    try:
        with _get_sa_engine().begin() as conn:
            current = conn.execute(
                _sa_text("SELECT id, status, name, market, survey_no, created_at FROM projects WHERE id = :pid"),
                {"pid": pid},
            ).fetchone()
            if not current:
                return _err_resp("project not found", request, 404, "Ops")
            old_status = str(current[1] or "lead")
            market_str = str(current[3] or "")
            survey_str = str(current[4] or "")
            if old_status != new_status and old_status != "paused":
                allowed = _VALID_TRANSITIONS.get(old_status, set())
                if new_status not in allowed:
                    return _err_resp(f"cannot transition from '{old_status}' to '{new_status}'", request, 400, "Ops")
            created = current[5]
            days_elapsed = (datetime.now(timezone.utc) - created).days if created else 0
            if old_status != new_status:
                conn.execute(
                    _sa_text("INSERT INTO deal_velocity (project_id, from_status, to_status, days_elapsed) VALUES (:pid, :from_st, :to_st, :days)"),
                    {"pid": pid, "from_st": old_status, "to_st": new_status, "days": days_elapsed},
                )
                if new_status == "delivered":
                    conn.execute(_sa_text("UPDATE projects SET actual_close_date = CURRENT_DATE WHERE id = :pid"), {"pid": pid})
            row = conn.execute(
                _sa_text("UPDATE projects SET status = :st, updated_at = NOW() WHERE id = :pid RETURNING id, name, market, survey_no, status, notes, created_at, updated_at"),
                {"pid": pid, "st": new_status},
            ).fetchone()
        if new_status in ("loi", "signed"):
            try:
                from utils.discord_notifier import format_deal_alert, send
                msg = format_deal_alert(new_status, market_str, survey_str)
                send("bd_opportunities", f"Project {new_status.upper()}: {current[2]}", msg)
            except Exception as exc:
                logger.warning("[update_project_status] Discord alert failed: %s", exc)
        return {
            "id": str(row[0]), "name": row[1], "market": row[2], "survey_no": row[3],
            "status": row[4], "notes": row[5],
            "created_at": row[6].isoformat() if row[6] else None,
            "updated_at": row[7].isoformat() if row[7] else None,
        }
    except Exception as exc:
        logger.error("[update_project_status] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/projects/{project_id}/velocity", summary="Get deal velocity timeline for a project")
async def get_velocity(project_id: str, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
    except ValueError:
        return _err_resp("invalid project_id", request, 400, "Ops")
    try:
        with _get_sa_engine().connect() as conn:
            proj = conn.execute(_sa_text("SELECT id, status, created_at FROM projects WHERE id = :pid"), {"pid": pid}).fetchone()
            if not proj:
                return _err_resp("project not found", request, 404, "Ops")
            rows = conn.execute(
                _sa_text("SELECT from_status, to_status, days_elapsed, transitioned_at FROM deal_velocity WHERE project_id = :pid ORDER BY transitioned_at ASC"),
                {"pid": pid},
            ).fetchall()
        return {
            "stages": [
                {
                    "from_status": r[0], "to_status": r[1],
                    "days_elapsed": int(r[2]) if r[2] else 0,
                    "transitioned_at": r[3].isoformat() if r[3] else None,
                }
                for r in rows
            ],
            "current_stage": str(proj[1] or "lead"),
            "current_stage_days": (datetime.now(timezone.utc) - proj[2]).days if proj[2] else 0,
        }
    except Exception as exc:
        logger.error("[get_velocity] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/projects/{project_id}/tasks", status_code=201, summary="Add a task to a project")
@limiter.limit("60/hour")
async def create_project_task(project_id: str, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
    except ValueError:
        return _err_resp("invalid project_id", request, 400, "Ops")
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    title = str(payload.get("title") or "").strip()
    if not title:
        return _err_resp("title is required", request, 400, "Ops")
    if len(title) > 500:
        return _err_resp("title too long (max 500 chars)", request, 400, "Ops")
    try:
        with _get_sa_engine().begin() as conn:
            exists = conn.execute(_sa_text("SELECT id FROM projects WHERE id = :pid"), {"pid": pid}).fetchone()
            if not exists:
                return _err_resp("project not found", request, 404, "Ops")
            row = conn.execute(
                _sa_text("""
                    INSERT INTO project_tasks (project_id, title, owner_agent_id, dept, due_date, notes)
                    VALUES (:pid, :title, :owner, :dept, CAST(:due AS date), :notes)
                    RETURNING id, title, owner_agent_id, dept, status, due_date, notes, created_at
                """),
                {"pid": pid, "title": title, "owner": payload.get("owner_agent_id"),
                 "dept": payload.get("dept"), "due": payload.get("due_date"), "notes": payload.get("notes")},
            ).fetchone()
        return {
            "id": str(row[0]), "title": row[1], "owner_agent_id": row[2], "dept": row[3],
            "status": row[4], "due_date": row[5].isoformat() if row[5] else None,
            "notes": row[6], "created_at": row[7].isoformat() if row[7] else None,
        }
    except Exception as exc:
        logger.error("[create_task] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.patch("/projects/{project_id}/tasks/{task_id}", summary="Update task status/notes")
@limiter.limit("60/hour")
async def update_project_task(project_id: str, task_id: str, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
        tid = str(uuid.UUID(task_id))
    except ValueError:
        return _err_resp("invalid id", request, 400, "Ops")
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    updates, params = [], {"pid": pid, "tid": tid}
    new_status = payload.get("status")
    if new_status is not None:
        if new_status not in ("todo", "in_progress", "done", "blocked"):
            return _err_resp(f"invalid status: {new_status}", request, 400, "Ops")
        updates.append("status = :st")
        params["st"] = new_status
        if new_status == "done":
            updates.append("completed_at = NOW()")
    notes = payload.get("notes")
    if notes is not None:
        updates.append("notes = :nt")
        params["nt"] = notes
    if not updates:
        return _err_resp("no fields to update", request, 400, "Ops")
    set_clause = ", ".join(updates)
    try:
        with _get_sa_engine().begin() as conn:
            row = conn.execute(
                _sa_text(f"UPDATE project_tasks SET {set_clause} WHERE id = :tid AND project_id = :pid RETURNING id, title, status, completed_at, notes"),
                params,
            ).fetchone()
        if not row:
            return _err_resp("task not found", request, 404, "Ops")
        return {"id": str(row[0]), "title": row[1], "status": row[2], "completed_at": row[3].isoformat() if row[3] else None, "notes": row[4]}
    except Exception as exc:
        logger.error("[update_task] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.delete("/projects/{project_id}/tasks/{task_id}", summary="Delete a task")
@limiter.limit("30/hour")
async def delete_task(project_id: str, task_id: str, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
        tid = str(uuid.UUID(task_id))
    except ValueError:
        return _err_resp("invalid id", request, 400, "Ops")
    try:
        with _get_sa_engine().begin() as conn:
            result = conn.execute(_sa_text("DELETE FROM project_tasks WHERE id = :tid AND project_id = :pid"), {"pid": pid, "tid": tid})
            if result.rowcount == 0:
                return _err_resp("task not found", request, 404, "Ops")
        return {"status": "deleted", "id": task_id}
    except Exception as exc:
        logger.error("[delete_task] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


# ── Landowner CRM ────────────────────────────────────────────────────────


_LANDOWNER_COLS = "id, survey_no, market, owner_name, contact_phone, contact_type, approach_status, ask_psf, notes, created_at, updated_at"
_VALID_CONTACT_TYPES = {"primary", "agent", "legal_heir", "power_of_attorney"}
_VALID_APPROACH_STATUSES = {"cold", "warm", "meeting_done", "mou", "loi", "closed_won", "closed_lost"}


def _row_to_landowner_dict(r):
    return {
        "id": str(r[0]), "survey_no": r[1], "market": r[2], "owner_name": r[3],
        "contact_phone": r[4], "contact_type": r[5], "approach_status": r[6],
        "ask_psf": float(r[7]) if r[7] else None, "notes": r[8],
        "created_at": r[9].isoformat() if r[9] else None,
        "updated_at": r[10].isoformat() if r[10] else None,
    }


def _fire_landowner_discord(status, survey_no, market, owner_name, ask_psf, notes):
    if status not in ("mou", "loi"):
        return
    from utils.discord_notifier import send_landowner_alert
    send_landowner_alert(status, survey_no, market, owner_name, ask_psf, notes)


@router.post("/landowners", status_code=201, summary="Create a new landowner contact")
@limiter.limit("30/minute")
async def create_landowner(request: Request):
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    contact_type = payload.get("contact_type")
    if contact_type and contact_type not in _VALID_CONTACT_TYPES:
        return _err_resp(f"invalid contact_type: {contact_type}", request, 400, "Ops")
    status = payload.get("approach_status") or "cold"
    if status not in _VALID_APPROACH_STATUSES:
        return _err_resp(f"invalid approach_status: {status}", request, 400, "Ops")
    try:
        with _get_sa_engine().begin() as conn:
            result = conn.execute(
                _sa_text(f"""INSERT INTO landowner_contacts
                    (survey_no, market, owner_name, contact_phone, contact_type, approach_status, ask_psf, notes)
                    VALUES (:sn, :mkt, :on, :cp, :ct, :st, :ap, :nt)
                    RETURNING {_LANDOWNER_COLS}"""),
                {"sn": payload.get("survey_no"), "mkt": payload.get("market"), "on": payload.get("owner_name"),
                 "cp": payload.get("contact_phone"), "ct": contact_type or "primary", "st": status,
                 "ap": payload.get("ask_psf"), "nt": payload.get("notes")},
            )
            row = result.fetchone()
        _fire_landowner_discord(status, payload.get("survey_no"), payload.get("market"), payload.get("owner_name"), payload.get("ask_psf"), payload.get("notes"))
        return _row_to_landowner_dict(row)
    except Exception as exc:
        logger.error("[create_landowner] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/landowners", summary="List landowner contacts with filters")
@limiter.limit("60/minute")
async def list_landowners(
    request: Request, market: str = Query(None), status: str = Query(None),
    page: int = Query(default=1, ge=1), per_page: int = Query(default=50, ge=1, le=200),
):
    try:
        with _get_sa_engine().connect() as conn:
            where_parts, params = [], {}
            if market:
                where_parts.append("lc.market ILIKE :mkt")
                params["mkt"] = f"%{market}%"
            if status:
                where_parts.append("lc.approach_status = :st")
                params["st"] = status
            where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
            total = conn.execute(_sa_text(f"SELECT COUNT(*) FROM landowner_contacts lc {where_sql}"), params).scalar() or 0
            offset = (page - 1) * per_page
            rows = conn.execute(
                _sa_text(f"SELECT {_LANDOWNER_COLS} FROM landowner_contacts lc {where_sql} ORDER BY lc.created_at DESC LIMIT :lim OFFSET :off"),
                {**params, "lim": per_page, "off": offset},
            ).fetchall()
        return {"data": [_row_to_landowner_dict(r) for r in rows], "pagination": {"page": page, "per_page": per_page, "total": total, "total_pages": max(1, (total + per_page - 1) // per_page)}}
    except Exception as exc:
        logger.error("[list_landowners] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/landowners/pipeline", summary="Pipeline summary: counts by status + avg ask_psf per market")
@limiter.limit("30/minute")
async def landowner_pipeline(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            by_status = conn.execute(_sa_text("SELECT approach_status, COUNT(*) as cnt FROM landowner_contacts GROUP BY approach_status ORDER BY cnt DESC")).fetchall()
            by_market = conn.execute(_sa_text("SELECT market, COUNT(*) as cnt, AVG(ask_psf) as avg_psf FROM landowner_contacts GROUP BY market ORDER BY cnt DESC")).fetchall()
        return {
            "by_status": {r[0]: r[1] for r in by_status},
            "by_market": {r[0]: {"count": r[1], "avg_ask_psf": round(float(r[2]), 2) if r[2] else None} for r in by_market},
        }
    except Exception as exc:
        logger.error("[landowner_pipeline] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/landowners/{landowner_id}", summary="Get a single landowner contact")
@limiter.limit("60/minute")
async def get_landowner(landowner_id: str, request: Request):
    try:
        tid = str(uuid.UUID(landowner_id))
    except ValueError:
        return _err_resp("invalid landowner_id", request, 400, "Ops")
    try:
        with _get_sa_engine().connect() as conn:
            row = conn.execute(_sa_text(f"SELECT {_LANDOWNER_COLS} FROM landowner_contacts WHERE id = :tid"), {"tid": tid}).fetchone()
        if not row:
            return _err_resp("landowner not found", request, 404, "Ops")
        return _row_to_landowner_dict(row)
    except Exception as exc:
        logger.error("[get_landowner] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.patch("/landowners/{landowner_id}", summary="Update landowner contact fields")
@limiter.limit("30/minute")
async def update_landowner(landowner_id: str, request: Request):
    try:
        pid = str(uuid.UUID(landowner_id))
    except ValueError:
        return _err_resp("invalid project_id", request, 400, "Ops")
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    try:
        with _get_sa_engine().begin() as conn:
            existing = conn.execute(
                _sa_text("SELECT id, survey_no, market, owner_name, approach_status, ask_psf FROM landowner_contacts WHERE id = :tid"),
                {"tid": pid},
            ).fetchone()
            if not existing:
                return _err_resp("landowner not found", request, 404, "Ops")
            updates, params = {}, {}
            for field, col, valid_set in [("owner_name","owner_name",None),("contact_phone","contact_phone",None),("contact_type","contact_type",_VALID_CONTACT_TYPES),("approach_status","approach_status",_VALID_APPROACH_STATUSES),("ask_psf","ask_psf",None),("notes","notes",None)]:
                val = payload.get(field)
                if val is not None:
                    if valid_set and val not in valid_set:
                        return _err_resp(f"invalid {field}: {val}", request, 400, "Ops")
                    updates[col] = val
                    params[col] = val
            if not updates:
                return _err_resp("no fields to update", request, 400, "Ops")
            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["updated_at"] = "NOW()"
            params["tid"] = pid
            row = conn.execute(
                _sa_text(f"UPDATE landowner_contacts SET {set_clause}, updated_at = NOW() WHERE id = :tid RETURNING {_LANDOWNER_COLS}"),
                {**{k: v for k, v in params.items()}, "tid": pid},
            ).fetchone()
        new_status = payload.get("approach_status") or existing[4]
        _fire_landowner_discord(new_status, existing[1], existing[2], existing[3], payload.get("ask_psf") or float(existing[5]) if existing[5] else None, payload.get("notes"))
        return _row_to_landowner_dict(row)
    except Exception as exc:
        logger.error("[update_landowner] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


# ── Portfolio ──────────────────────────────────────────────────────────────


_PORTFOLIO_COLS = "id, project_name, location, market, segment, total_units, sold_units, launched_date, possession_date, land_cost_cr, gdv_cr, realized_irr_pct, status, rera_no, notes, created_at"


def _row_to_portfolio_dict(r):
    return {
        "id": str(r[0]), "project_name": r[1], "location": r[2], "market": r[3], "segment": r[4],
        "total_units": r[5], "sold_units": r[6],
        "launched_date": r[7].isoformat() if r[7] else None,
        "possession_date": r[8].isoformat() if r[8] else None,
        "land_cost_cr": float(r[9]) if r[9] else None,
        "gdv_cr": float(r[10]) if r[10] else None,
        "realized_irr_pct": float(r[11]) if r[11] else None,
        "status": r[12], "rera_no": r[13],
        "notes": (r[14][:2000] + "...") if r[14] and len(r[14]) > 2000 else r[14],
        "created_at": r[15].isoformat() if r[15] else None,
    }


@router.get("/portfolio", summary="List LLS portfolio")
@limiter.limit("60/minute")
async def list_portfolio(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(_sa_text(f"SELECT {_PORTFOLIO_COLS} FROM lls_portfolio ORDER BY launched_date DESC")).fetchall()
        return {"data": [_row_to_portfolio_dict(r) for r in rows]}
    except Exception as exc:
        logger.error("[list_portfolio] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/portfolio/summary", summary="LLS portfolio summary stats")
@limiter.limit("60/minute")
async def portfolio_summary(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            agg = conn.execute(
                _sa_text("""
                    SELECT COUNT(*) AS total,
                           COUNT(*) FILTER (WHERE status = 'delivered') AS delivered,
                           COALESCE(AVG(realized_irr_pct) FILTER (WHERE status = 'delivered' AND realized_irr_pct IS NOT NULL), 0) AS avg_irr,
                           COALESCE(SUM(total_units) FILTER (WHERE status = 'delivered'), 0) AS total_units
                    FROM lls_portfolio
                """),
            ).fetchone()
            market_rows = conn.execute(_sa_text("SELECT DISTINCT market FROM lls_portfolio WHERE market IS NOT NULL")).fetchall()
        return {
            "total_projects": agg[0] or 0, "delivered_count": agg[1] or 0,
            "total_delivered_sqft_est": (agg[3] or 0) * 1200,
            "avg_realized_irr_pct": round(float(agg[2]), 2) if agg[2] else None,
            "markets_covered": [r[0] for r in market_rows if r[0]],
        }
    except Exception as exc:
        logger.error("[portfolio_summary] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


# ── Content / PR / Brand ──────────────────────────────────────────────────


@router.post("/content/generate", summary="Generate brand content from IntelPackage")
@limiter.limit("5/hour")
async def content_generate(request: Request):
    import asyncio
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    market = str(payload.get("market") or "").strip()
    survey_no = str(payload.get("survey_no") or "").strip()
    deal_type = str(payload.get("deal_type", "compare")).strip().lower()
    job_id = payload.get("job_id")
    if not market or not survey_no:
        return _err_resp("market and survey_no are required", request, 400, "Ops")
    from utils.content_pipeline import ContentPipeline
    pipeline = ContentPipeline()
    result = await asyncio.to_thread(pipeline.run, market=market, survey_no=survey_no, deal_type=deal_type, job_id=job_id)
    return result


@router.get("/pr/mentions", summary="Brand mentions + competitor launches for PR Studio")
@limiter.limit("30/minute")
async def pr_mentions(days: int = Query(default=7), request: Request = None):
    from utils.brand_monitor import BrandMentionMonitor
    monitor = BrandMentionMonitor()
    brand_mentions = monitor.scan_mentions("LLS", days)
    launches = []
    try:
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        launches = engine.new_launches(market=None, days=30)
    except Exception as exc:
        logger.warning("[pr_mentions] Competitor engine failed (non-fatal): %s", exc)
    return {"mentions": brand_mentions, "mention_count": len(brand_mentions), "competitor_launches": launches, "launch_count": len(launches), "days_window": days}


@router.get("/content", summary="Content Studio dashboard panel")
def content_studio(request: Request):
    return templates.TemplateResponse(request, "content_studio.html")


@router.get("/pr", summary="PR Studio dashboard panel")
def pr_studio(request: Request):
    return templates.TemplateResponse(request, "pr_studio.html")


# ── Telegram Webhook ──────────────────────────────────────────────────────


def _send_telegram_message(chat_id: int | str, text: str) -> None:
    from config.settings import TELEGRAM_BOT_TOKEN as _tg_token
    if not _tg_token:
        logger.warning("[Telegram] TELEGRAM_BOT_TOKEN not set — cannot send reply")
        return
    try:
        import requests as _req
        _req.post(f"https://api.telegram.org/bot{_tg_token}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as exc:
        logger.error("[Telegram] sendMessage failed: %s", exc)


@router.post("/telegram/webhook", summary="Telegram bot webhook")
async def telegram_webhook(request: Request):
    import asyncio
    import hmac
    from config.settings import TELEGRAM_WEBHOOK_SECRET as _tg_secret
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if _tg_secret:
        if not secret or not hmac.compare_digest(secret, _tg_secret):
            return _err_resp("unauthorized", request, 403, "Ops")
    else:
        logger.warning("Telegram webhook running without secret verification — set TELEGRAM_WEBHOOK_SECRET in .env")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": True})
    message = body.get("message") or body.get("edited_message") or {}
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    if not text or not chat_id:
        return JSONResponse({"ok": True})
    from interface.telegram_bot import parse_message, dispatch_evaluation
    parsed = parse_message(text)
    if parsed.confidence > 0.5:
        result = await asyncio.to_thread(dispatch_evaluation, parsed)
        status = result.get("status", "unknown")
        job_id = result.get("job_id", "")
        reply = f"Evaluating {parsed.market} ({parsed.area_acres:.1f}ac @ \u20b9{parsed.ask_psf:.0f} PSF, {parsed.deal_type}). Job: {job_id or 'queued'}." if status in ("running", "completed") else f"Evaluation queued for {parsed.market}. Error: {result.get('error', 'unknown')[:100]}"
    else:
        reply = f"Confidence {parsed.confidence:.0%} — too low to evaluate.\nInclude: market (Yelahanka/Devanahalli/Hebbal), area (acres or sqft), ask PSF or crore price, deal type (JD/JV/purchase)."
    await asyncio.to_thread(_send_telegram_message, chat_id, reply)
    return JSONResponse({"ok": True})


# ── Process Audit ─────────────────────────────────────────────────────────


@router.get("/process-audit", summary="Process Audit dashboard panel")
def process_audit_panel(request: Request):
    from pathlib import Path as _Path
    return templates.TemplateResponse(request, "process_audit.html", {"process_audit_dir": _Path(__file__).resolve().parent.parent / "templates"})


@router.get("/process-audit/report", summary="Latest BottleneckReport + ImprovementProposal")
@limiter.limit("30/minute")
async def process_audit_report(request: Request):
    from agents.log_analyst_agent import LogAnalystAgent
    from agents.efficiency_optimizer_agent import EfficiencyOptimizerAgent
    from agents.runbook_documenter_agent import RunbookDocumenterAgent
    from pathlib import Path
    log_agent = LogAnalystAgent()
    log_result = log_agent.run()
    report = log_result.get("report", {})
    eff_agent = EfficiencyOptimizerAgent()
    eff_result = eff_agent.run(bottleneck_report=report)
    proposal = eff_result.get("proposal", {})
    doc_agent = RunbookDocumenterAgent()
    doc_result = doc_agent.run(bottleneck_report=report, improvement_proposal=proposal)
    runbook_path = doc_result.get("path", "")
    sol_dir = Path(__file__).resolve().parent.parent.parent / "docs" / "solutions" / "process-automation"
    runbooks = sorted([str(p.relative_to(sol_dir.parent.parent)) for p in sol_dir.glob("*.md")]) if sol_dir.exists() else []
    return {"report": report, "proposal": proposal, "runbook_path": runbook_path, "runbooks": runbooks}


# ── Shareholder Board ─────────────────────────────────────────────────────


@router.post("/shareholders/trigger", summary="Trigger quarterly board review")
@limiter.limit("5/hour")
async def trigger_shareholder_review(request: Request):
    from crews.shareholder_review import ShareholderBoardCrew
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _err_resp("invalid JSON body", request, 400, "Ops")
    quarter = str(payload.get("quarter") or "").strip()
    trigger_reason = str(payload.get("trigger_reason") or "Manual trigger").strip()
    if not quarter:
        return _err_resp("quarter required (e.g. Q2-2026)", request, 400, "Ops")
    session_id = str(uuid.uuid4())
    try:
        with _get_sa_engine().connect() as conn:
            active = conn.execute(
                _sa_text("SELECT COUNT(*) FROM shareholder_sessions WHERE quarter = :q AND status IN ('pending','in_progress')"),
                {"q": quarter},
            ).scalar() or 0
            if active > 0:
                return _err_resp(f"A review for {quarter} is already in progress. Wait for it to complete before triggering another.", request, 429, "Ops")
    except Exception:
        pass
    try:
        with _get_sa_engine().begin() as conn:
            conn.execute(
                _sa_text("INSERT INTO shareholder_sessions (id, session_type, quarter, trigger_reason, status, created_at) VALUES (:id, 'quarterly_board', :quarter, :reason, 'in_progress', NOW())"),
                {"id": session_id, "quarter": quarter, "reason": trigger_reason},
            )
    except Exception as exc:
        logger.warning("[API] POST /shareholders/trigger session create failed: %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")

    def _run_and_update():
        try:
            result = ShareholderBoardCrew.run_quarterly_review(quarter)
            letter_text = result.get("ceo_letter_text", "")
            ShareholderBoardCrew.save_letter(session_id, letter_text)
            with _get_sa_engine().begin() as conn:
                conn.execute(
                    _sa_text("""
                        UPDATE shareholder_sessions
                        SET status = 'complete',
                            shareholder_responses = CAST(:responses AS jsonb),
                            debate_transcript = :transcript,
                            ceo_synthesis = :synthesis,
                            verdict = :verdict,
                            completed_at = NOW()
                        WHERE id = :id
                    """),
                    {
                        "id": session_id,
                        "responses": json.dumps(result.get("shareholder_responses", [])),
                        "transcript": json.dumps({"debate_triggered": result.get("debate_triggered", False), "debate_round": result.get("debate_round")}),
                        "synthesis": result.get("ceo_letter_text", ""),
                        "verdict": result.get("quarter_verdict", ""),
                    },
                )
        except Exception as exc:
            logger.warning("[Shareholders] Review failed: %s | %s", session_id, exc)
            try:
                with _get_sa_engine().begin() as conn:
                    conn.execute(_sa_text("UPDATE shareholder_sessions SET status = 'failed' WHERE id = :id"), {"id": session_id})
            except Exception:
                pass

    threading.Thread(target=_run_and_update, daemon=True).start()
    return JSONResponse({"session_id": session_id, "status": "in_progress", "quarter": quarter, "message": "Quarterly board review triggered. Check /shareholders for results."}, status_code=202)


@router.get("/shareholders/sessions", summary="List all shareholder sessions")
@limiter.limit("30/minute")
async def list_shareholder_sessions(request: Request, session_type: str | None = None, status: str | None = None, quarter: str | None = None):
    try:
        where_clauses, params = [], {}
        if session_type:
            where_clauses.append("session_type = :session_type")
            params["session_type"] = session_type
        if status:
            where_clauses.append("status = :status")
            params["status"] = status
        if quarter:
            where_clauses.append("quarter = :quarter")
            params["quarter"] = quarter
        where_sql = " AND ".join(where_clauses)
        if where_sql:
            where_sql = "WHERE " + where_sql
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text(f"SELECT id, session_type, quarter, trigger_reason, status, verdict, created_at, completed_at FROM shareholder_sessions {where_sql} ORDER BY created_at DESC LIMIT 50"),
                params,
            ).fetchall()
        return {"data": [{"id": str(r[0]), "session_type": r[1], "quarter": r[2], "trigger_reason": r[3], "status": r[4], "verdict": r[5], "created_at": r[6].isoformat() if r[6] else None, "completed_at": r[7].isoformat() if r[7] else None} for r in rows]}
    except Exception as exc:
        logger.warning("[API] GET /shareholders/sessions failed: %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/shareholders", summary="Dashboard Shareholder Room Panel")
@limiter.limit("20/hour")
async def shareholders_panel(request: Request):
    try:
        return templates.TemplateResponse(request, "shareholders.html")
    except Exception as exc:
        logger.error("[shareholders_panel] %s", exc)
        return _err_resp("template not found", request, 500, "Ops")


# ── Optimizer ─────────────────────────────────────────────────────────────


@router.get("/optimizer", summary="Dashboard Optimizer Panel")
@limiter.limit("20/hour")
async def optimizer_panel(request: Request):
    try:
        return templates.TemplateResponse(request, "optimizer.html")
    except Exception as exc:
        logger.error("[optimizer_panel] %s", exc)
        return _err_resp("template not found", request, 500, "Ops")


@router.get("/optimizer/report", summary="Latest optimizer report JSON")
@limiter.limit("20/hour")
async def optimizer_report(request: Request):
    try:
        from utils.optimizer_report import generate_report
        report = generate_report(7)
        return report.to_dict() if hasattr(report, "to_dict") else report
    except Exception as exc:
        logger.error("[optimizer_report] %s", exc)
        return {"report_date": "", "token_summary": [], "redundancy_findings": [], "cache_hit_rate": 0.0, "top_recommendation": "Unable to generate report - see logs", "auto_tasks_created": 0}


# ── Digest Routes ─────────────────────────────────────────────────────────


@router.get("/digest/weekly", tags=["Digest"], summary="Weekly intelligence digest")
@limiter.limit("20/hour")
async def digest_weekly(request: Request, market: str = Query(None)):
    from utils.weekly_digest import WeeklyIntelDigest
    resolved = _resolve_market(market) if market else None
    if market and not resolved:
        digest_runs_total.labels(type="weekly", status="invalid_market").inc()
        return _err_resp(f"Unknown market '{market}'. Valid: {sorted(VALID_MARKETS_DIGEST)}", request, 404, "Ops")
    digest = WeeklyIntelDigest()
    if resolved:
        result = digest.build(resolved)
        digest_runs_total.labels(type="weekly", status="ok").inc()
        return {k: v for k, v in result.__dict__.items()}
    results = [digest.build(m) for m in _all_markets()]
    digest_runs_total.labels(type="weekly", status="ok").inc()
    return {"results": [{k: v for k, v in r.__dict__.items()} for r in results]}


@router.get("/digest/monthly", tags=["Digest"], summary="Monthly intelligence digest")
@limiter.limit("20/hour")
async def digest_monthly(request: Request, market: str = Query(None)):
    from utils.monthly_digest import MonthlyIntelDigest
    resolved = _resolve_market(market) if market else None
    if market and not resolved:
        digest_runs_total.labels(type="monthly", status="invalid_market").inc()
        return _err_resp(f"Unknown market '{market}'. Valid: {sorted(VALID_MARKETS_DIGEST)}", request, 404, "Ops")
    digest = MonthlyIntelDigest()
    if resolved:
        result = digest.build(resolved)
        digest_runs_total.labels(type="monthly", status="ok").inc()
        return {k: v for k, v in result.__dict__.items()}
    results = [digest.build(m) for m in _all_markets()]
    digest_runs_total.labels(type="monthly", status="ok").inc()
    return {"results": [{k: v for k, v in r.__dict__.items()} for r in results]}


@router.post("/digest/weekly/send", tags=["Digest"], summary="Send weekly digest to Discord now")
@limiter.limit("1/hour")
async def digest_weekly_send(request: Request):
    if not _is_run_api_authorized(request):
        return _err_resp("unauthorized", request, 401, "Ops")
    from utils.weekly_digest import WeeklyIntelDigest
    from utils.discord_notifier import send_weekly_digest
    digest = WeeklyIntelDigest()
    results = [digest.build(m) for m in _all_markets()]
    send_weekly_digest(results)
    digest_runs_total.labels(type="weekly_send", status="sent").inc()
    return {"status": "sent", "markets": len(results)}


@router.post("/digest/monthly/send", tags=["Digest"], summary="Send monthly digest to Discord now")
@limiter.limit("1/hour")
async def digest_monthly_send(request: Request):
    if not _is_run_api_authorized(request):
        return _err_resp("unauthorized", request, 401, "Ops")
    from utils.monthly_digest import MonthlyIntelDigest
    from utils.discord_notifier import send_monthly_digest
    digest = MonthlyIntelDigest()
    results = [digest.build(m) for m in _all_markets()]
    send_monthly_digest(results)
    digest_runs_total.labels(type="monthly_send", status="sent").inc()
    return {"status": "sent", "markets": len(results)}


# ── V2 Routes ─────────────────────────────────────────────────────────────


from pydantic import BaseModel as _BM  # alias avoids shadowing local model names


class V2ReadinessResponse(_BM):
    v2_ready: bool
    scheduler_days_running: int
    scheduler_success_rate: float
    discord_digest_count: int
    live_rera_growth: bool
    board_room_avg_response_s: float | None = None
    model_config = {"extra": "forbid", "frozen": True}


class V2DeclareResponse(_BM):
    declared: bool
    date: str | None = None
    model_config = {"extra": "forbid", "frozen": True}


_DECLARE_FACT = "RE_OS V2.0 declared"


def _compute_v2_readiness(conn) -> V2ReadinessResponse:
    with db_query_duration_seconds.labels(query_name="v2_scheduler_days").time():
        days_row = conn.execute(
            _sa_text("""
                SELECT CASE WHEN COUNT(*) = 0 THEN 0 ELSE EXTRACT(DAY FROM NOW() - MIN(created_at))::int END
                FROM agent_runs WHERE created_at > NOW() - INTERVAL '30 days'
            """)
        ).fetchone()
        scheduler_days_running = days_row[0] if days_row else 0
    with db_query_duration_seconds.labels(query_name="v2_success_rate").time():
        rate_row = conn.execute(
            _sa_text("""
                SELECT COUNT(*) AS total, SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes
                FROM agent_runs WHERE created_at > NOW() - INTERVAL '7 days'
            """)
        ).fetchone()
        total_runs = rate_row[0] if rate_row else 0
        successes = rate_row[1] if rate_row else 0
        scheduler_success_rate = round(successes / total_runs, 4) if total_runs > 0 else 0.0
    with db_query_duration_seconds.labels(query_name="v2_digest_count").time():
        digest_row = conn.execute(
            _sa_text("SELECT COUNT(*) FROM alerts WHERE alert_type ILIKE '%digest%' AND created_at > NOW() - INTERVAL '7 days'")
        ).fetchone()
        discord_digest_count = digest_row[0] if digest_row else 0
    with db_query_duration_seconds.labels(query_name="v2_live_growth").time():
        growth_row = conn.execute(
            _sa_text("""
                WITH live_counts_7d_ago AS (
                    SELECT mm.name, COUNT(*) AS cnt
                    FROM rera_projects rp JOIN micro_markets mm ON mm.id = rp.micro_market_id
                    WHERE rp.data_source != 'seed_estimated' AND rp.created_at <= NOW() - INTERVAL '7 days'
                    GROUP BY mm.name
                ), current_live_counts AS (
                    SELECT mm.name, COUNT(*) AS cnt
                    FROM rera_projects rp JOIN micro_markets mm ON mm.id = rp.micro_market_id
                    WHERE rp.data_source != 'seed_estimated'
                    GROUP BY mm.name
                )
                SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM current_live_counts) THEN TRUE
                            WHEN NOT EXISTS (SELECT 1 FROM live_counts_7d_ago) THEN TRUE
                            WHEN EXISTS (SELECT 1 FROM current_live_counts cl
                                LEFT JOIN live_counts_7d_ago old ON old.name = cl.name
                                WHERE cl.cnt > COALESCE(old.cnt, 0)) THEN TRUE
                            ELSE FALSE END
            """)
        ).fetchone()
        live_rera_growth = growth_row[0] if growth_row else True
    with db_query_duration_seconds.labels(query_name="v2_br_response").time():
        br_row = conn.execute(
            _sa_text("SELECT AVG(response_time_s) FROM board_sessions WHERE completed_at IS NOT NULL AND created_at > NOW() - INTERVAL '7 days'")
        ).fetchone()
        board_room_avg_response_s = round(float(br_row[0]), 2) if br_row and br_row[0] is not None else None
    v2_ready = scheduler_success_rate >= 0.8 and scheduler_days_running >= 7 and discord_digest_count >= 1
    return V2ReadinessResponse(
        v2_ready=v2_ready, scheduler_days_running=scheduler_days_running,
        scheduler_success_rate=scheduler_success_rate, discord_digest_count=discord_digest_count,
        live_rera_growth=live_rera_growth, board_room_avg_response_s=board_room_avg_response_s,
    )


# ── SLO ──────────────────────────────────────────────────────────────────


class SLOMetricsResponse(BaseModel):
    scheduler_success_rate: float
    scheduler_target: float
    scheduler_ok: bool
    board_room_p95_s: float | None = None
    board_room_target_s: float
    board_room_ok: bool | None = None
    window_days: int = 7
    computed_at: str


# Prometheus gauges for SLO values (scraped by re_os_prometheus)
from config.metrics import _gauge as _slo_gauge

_slo_scheduler_rate_gauge = _slo_gauge(
    "slo_scheduler_success_rate",
    "Scheduler success rate over 7d rolling window [0.0, 1.0]",
)
_slo_board_p95_gauge = _slo_gauge(
    "slo_board_room_p95_s",
    "Board Room p95 response time in seconds over 7d rolling window",
)


def _compute_slo_metrics(conn) -> SLOMetricsResponse:
    from config.settings import (
        SLO_SCHEDULER_TARGET,
        SLO_BOARD_ROOM_P95_TARGET_S,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    with db_query_duration_seconds.labels(query_name="slo_scheduler_rate").time():
        rate_row = conn.execute(
            _sa_text("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes
                FROM agent_runs
                WHERE created_at > NOW() - INTERVAL '7 days'
            """)
        ).fetchone()
        total_runs = rate_row[0] if rate_row else 0
        successes = rate_row[1] if rate_row else 0
        scheduler_success_rate = round(successes / total_runs, 4) if total_runs > 0 else 0.0
    with db_query_duration_seconds.labels(query_name="slo_board_p95").time():
        p95_row = conn.execute(
            _sa_text("""
                SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time_s)
                FROM board_sessions
                WHERE response_time_s IS NOT NULL
                  AND created_at > NOW() - INTERVAL '7 days'
            """)
        ).fetchone()
        board_room_p95_s = round(float(p95_row[0]), 2) if p95_row and p95_row[0] is not None else None
    # Update Prometheus gauges for Grafana visibility
    _slo_scheduler_rate_gauge.set(scheduler_success_rate)
    _slo_board_p95_gauge.set(board_room_p95_s if board_room_p95_s is not None else -1.0)
    scheduler_ok = scheduler_success_rate >= SLO_SCHEDULER_TARGET
    board_room_ok = board_room_p95_s is not None and board_room_p95_s < SLO_BOARD_ROOM_P95_TARGET_S
    return SLOMetricsResponse(
        scheduler_success_rate=scheduler_success_rate,
        scheduler_target=SLO_SCHEDULER_TARGET,
        scheduler_ok=scheduler_ok,
        board_room_p95_s=board_room_p95_s,
        board_room_target_s=SLO_BOARD_ROOM_P95_TARGET_S,
        board_room_ok=board_room_ok,
        computed_at=now_iso,
    )


@router.get("/ops/slo", response_model=SLOMetricsResponse, summary="Live SLO measurement")
@limiter.limit("60/hour")
async def ops_slo(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            return _compute_slo_metrics(conn)
    except Exception as exc:
        logger.error("[ops_slo] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/ops/v2-readiness", response_model=V2ReadinessResponse, summary="V2.0 readiness check")
@limiter.limit("60/hour")
async def v2_readiness(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            return _compute_v2_readiness(conn)
    except Exception as exc:
        logger.error("[v2_readiness] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.post("/ops/v2-declare", response_model=V2DeclareResponse, summary="Declare V2.0")
@limiter.limit("10/hour")
async def v2_declare(request: Request):
    if not _is_run_api_authorized(request):
        return _err_resp("unauthorized", request, 401, "Ops")
    try:
        with _get_sa_engine().begin() as conn:
            existing = conn.execute(
                _sa_text("SELECT created_at FROM agent_memories WHERE agent_id = 'system' AND market = 'system' AND fact = :fact ORDER BY created_at DESC LIMIT 1"),
                {"fact": _DECLARE_FACT},
            ).fetchone()
            if existing:
                return V2DeclareResponse(declared=True, date=existing[0].isoformat() if existing[0] else None)
            readiness = _compute_v2_readiness(conn)
            if not readiness.v2_ready:
                return JSONResponse({"error": "V2 criteria not yet met", "code": "PRECONDITION_FAILED", "readiness": readiness.model_dump()}, status_code=400)
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                _sa_text("INSERT INTO agent_memories (agent_id, market, fact, confidence, created_at) VALUES ('system', 'system', :fact, 1.0, NOW()) ON CONFLICT (agent_id, market, fact) DO NOTHING"),
                {"fact": _DECLARE_FACT},
            )
            from utils.discord_notifier import send_ops_alert
            send_ops_alert("V2_DECLARED", f"RE_OS V2.0 declared ✅ — {now_iso}. {readiness.scheduler_days_running} days live. {readiness.discord_digest_count} weekly digests delivered.")
            return V2DeclareResponse(declared=True, date=now_iso)
    except Exception as exc:
        logger.error("[v2_declare] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get("/ops/v2", response_class=HTMLResponse, summary="V2.0 Operations Readiness panel")
async def v2_panel(request: Request):
    try:
        return templates.TemplateResponse(request, "v2_readiness.html")
    except Exception as exc:
        logger.error("[v2_panel] %s", exc)
        return _err_resp("template not found", request, 500, "Ops")


# ── SLO Endpoint (GATE-105) ────────────────────────────────────────────────


class SLOResponse(BaseModel):
    scheduler_slo: dict
    board_room_slo: dict
    as_of: str


@router.get("/ops/slo", summary="SLO status: scheduler + board room")
@limiter.limit("30/minute")
async def slo(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            # Scheduler SLO: success_rate >= 0.95 over 7d rolling
            rate_row = conn.execute(
                _sa_text("""
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS successes
                    FROM agent_runs WHERE created_at > NOW() - INTERVAL '7 days'
                """)
            ).fetchone()
            total_runs = rate_row[0] if rate_row else 0
            successes = rate_row[1] if rate_row else 0
            current_rate = round(successes / total_runs, 4) if total_runs > 0 else 0.0
            scheduler_slo = {
                "target": 0.95,
                "current": current_rate,
                "status": "MET" if current_rate >= 0.95 else "BREACHED",
            }
            # Board Room SLO: p95 response < 90s over 7d rolling
            p95_row = conn.execute(
                _sa_text("""
                    SELECT response_time_s FROM board_sessions
                    WHERE completed_at IS NOT NULL AND created_at > NOW() - INTERVAL '7 days'
                    ORDER BY response_time_s ASC
                """)
            ).fetchall()
            p95_values = [float(r[0]) for r in p95_row if r[0] is not None]
            p95_val = None
            if p95_values:
                n = len(p95_values)
                idx = max(0, min(int(n * 0.95), n - 1))
                p95_val = round(p95_values[idx], 2)
            board_room_slo = {
                "target_s": 90,
                "p95_s": p95_val,
                "status": "MET" if p95_val is not None and p95_val < 90 else ("BREACHED" if p95_val is not None else "NO_DATA"),
            }
        slo_data = {"scheduler_slo": scheduler_slo, "board_room_slo": board_room_slo, "as_of": datetime.now(timezone.utc).isoformat()}
        etag = compute_etag(slo_data)
        _check = check_etag(request, etag)
        if _check:
            return _check
        return JSONResponse(content=slo_data, headers={"ETag": f'"{etag}"'})
    except Exception as exc:
        logger.error("[slo] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


# ── Prediction Ledger Accuracy (GATE-126) ────────────────────────────────────


@router.get("/ops/ledger/accuracy", summary="Prediction accuracy by module over last N weeks")
@limiter.limit("60/hour")
async def ledger_accuracy(
    request: Request,
    weeks: int = Query(default=12, ge=1, le=52, description="Look-back window in weeks"),
):
    try:
        t0 = time.perf_counter()
        data = compute_accuracy_summary(weeks=weeks)
        try:
            db_query_duration_seconds.labels(query_name="ledger_accuracy").observe(time.perf_counter() - t0)
        except Exception:
            pass
        etag = compute_etag(data)
        _check = check_etag(request, etag)
        if _check:
            return _check
        return JSONResponse(content=data, headers={"ETag": f'"{etag}"'})
    except Exception as exc:
        logger.error("[ledger_accuracy] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


# ── Failed Records (GATE-108 dead letter queue) ─────────────────────────────


@router.get("/ops/failed-records", summary="Dead letter queue for failed ingest records")
@limiter.limit("30/minute")
async def failed_records(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT id, entity_type, source_id, error_text, plugin_id, retry_count, failed_at
                    FROM ingest_failed_records
                    ORDER BY failed_at DESC
                    LIMIT :lim
                """),
                {"lim": limit},
            ).fetchall()
        return {
            "records": [
                {
                    "id": str(r[0]), "entity_type": r[1], "source_id": r[2],
                    "error": (r[3][:500] + "...") if r[3] and len(r[3]) > 500 else r[3],
                    "plugin_id": r[4], "retry_count": r[5],
                    "failed_at": r[6].isoformat() if r[6] else None,
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception:
        return {"records": [], "count": 0}


# ── API Audit Log (GATE-107) ────────────────────────────────────────────────


@router.get("/audit/log", summary="API audit log (admin only)")
@limiter.limit("30/minute")
async def audit_log(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT id, request_id, path, method, role, status_code, duration_ms, created_at
                    FROM api_audit_log
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"lim": limit},
            ).fetchall()
        return {
            "entries": [
                {
                    "id": str(r[0]), "request_id": r[1], "path": r[2],
                    "method": r[3], "role": r[4], "status_code": r[5],
                    "duration_ms": r[6],
                    "created_at": r[7].isoformat() if r[7] else None,
                }
                for r in rows
            ],
            "count": len(rows),
        }
    except Exception:
        return {"entries": [], "count": 0}


# ── Kill Criteria Dashboard (GATE-118, T-1277) ─────────────────────────────


class KillCriteriaDeedThroughput(BaseModel):
    weekly_avg_deeds: float = 0.0
    weeks_measured: int = 0
    target: int = 50
    on_track: bool = False


class KillCriteriaLedger(BaseModel):
    hit_rate: float = 0.0
    total_verdicts: int = 0
    target_hit_rate: float = 0.6


class KillCriteriaCorridorItem(BaseModel):
    name: str
    verdict: str = "INSUFFICIENT_DATA"
    rank_correlation: float | None = None
    projects_evaluated: int | None = None
    run_date: str | None = None
    status: str = "data_present"


class KillCriteriaCorridor(BaseModel):
    corridors: list[KillCriteriaCorridorItem] = []
    status: str = "data_present"


class KillCriteriaDeadlines(BaseModel):
    deed_throughput: str = "2026-08-15"
    days_remaining: int = 0
    decision_journal: str = "2026-12-31"
    dj_days_remaining: int = 0


class NewKillCriteriaResponse(BaseModel):
    deed_throughput: KillCriteriaDeedThroughput
    ledger: KillCriteriaLedger
    corridor: KillCriteriaCorridor
    deadlines: KillCriteriaDeadlines
    decision_journal_entries: int = 0


@router.get(
    "/ops/kill-criteria",
    response_model=NewKillCriteriaResponse,
    summary="Kill criteria dashboard (deed throughput, ledger hit-rate, corridor verdicts, deadlines)",
)
@limiter.limit("10/hour")
async def kill_criteria(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            deed_row = conn.execute(_sa_text("""
                SELECT
                    COUNT(*)::float / NULLIF(EXTRACT(WEEK FROM NOW()) - EXTRACT(WEEK FROM MIN(created_at)), 0) AS weekly_avg,
                    COUNT(*)::int AS total_deeds,
                    EXTRACT(WEEK FROM NOW())::int - EXTRACT(WEEK FROM MIN(created_at))::int AS weeks
                FROM registered_transactions WHERE deed_type = 'Sale'
            """)).fetchone()
            weekly_avg = round(float(deed_row[0]), 1) if deed_row and deed_row[0] else 0.0
            weeks_measured = int(deed_row[2]) if deed_row and deed_row[2] else 0

            hit = conn.execute(_sa_text("SELECT COUNT(*) FROM prediction_ledger WHERE verdict = 'hit'")).scalar() or 0
            miss = conn.execute(_sa_text("SELECT COUNT(*) FROM prediction_ledger WHERE verdict = 'miss'")).scalar() or 0
            total_verdicts = hit + miss
            hit_rate = round(hit / max(total_verdicts, 1), 4)

            corridor_rows = conn.execute(_sa_text("""
                SELECT DISTINCT ON (corridor_name)
                    corridor_name, verdict, rank_correlation,
                    projects_evaluated, run_date
                FROM corridor_backtest_verdicts
                ORDER BY corridor_name, created_at DESC
            """)).fetchall()
            corridor_map: dict[str, dict] = {}
            for r in corridor_rows:
                name = str(r[0])
                corridor_map[name] = {
                    "verdict": str(r[1]) if r[1] else "INSUFFICIENT_DATA",
                    "rank_correlation": float(r[2]) if r[2] is not None else None,
                    "projects_evaluated": int(r[3]) if r[3] is not None else None,
                    "run_date": str(r[4]) if r[4] else None,
                }
            from utils.corridor_scorer_v2 import _CORRIDOR_SEEDS
            _KNOWN_CORRIDOR_NAMES = [s.corridor_id for s in _CORRIDOR_SEEDS]
            has_data = len(corridor_rows) > 0
            _corridor_verdicts = []
            for name in _KNOWN_CORRIDOR_NAMES:
                entry = corridor_map.get(name, {})
                if not entry:
                    _corridor_verdicts.append(KillCriteriaCorridorItem(
                        name=name,
                        verdict="INSUFFICIENT_DATA",
                        rank_correlation=None,
                        projects_evaluated=None,
                        run_date=None,
                        status="no_data",
                    ))
                else:
                    _corridor_verdicts.append(KillCriteriaCorridorItem(
                        name=name,
                        verdict=entry.get("verdict", "INSUFFICIENT_DATA"),
                        rank_correlation=entry.get("rank_correlation"),
                        projects_evaluated=entry.get("projects_evaluated"),
                        run_date=entry.get("run_date"),
                        status="data_present",
                    ))

            try:
                dj_count = conn.execute(_sa_text("SELECT COUNT(*) FROM decision_journal")).scalar() or 0
            except Exception as _dj_exc:
                _dj_str = str(_dj_exc)
                if "relation" in _dj_str and "does not exist" in _dj_str:
                    dj_count = 0
                else:
                    raise

        today = date.today()
        deed_deadline = date(2026, 8, 15)
        dj_deadline = date(2026, 12, 31)

        data = NewKillCriteriaResponse(
            deed_throughput=KillCriteriaDeedThroughput(
                weekly_avg_deeds=weekly_avg,
                weeks_measured=weeks_measured,
                target=50,
                on_track=weekly_avg >= 50,
            ),
            ledger=KillCriteriaLedger(
                hit_rate=hit_rate,
                total_verdicts=total_verdicts,
                target_hit_rate=0.6,
            ),
            corridor=KillCriteriaCorridor(corridors=_corridor_verdicts, status="no_data" if not has_data else "data_present"),
            deadlines=KillCriteriaDeadlines(
                deed_throughput="2026-08-15",
                days_remaining=(deed_deadline - today).days,
                decision_journal="2026-12-31",
                dj_days_remaining=(dj_deadline - today).days,
            ),
            decision_journal_entries=dj_count,
        )
        etag = compute_etag(data.model_dump())
        _check = check_etag(request, etag)
        if _check:
            return _check
        return JSONResponse(content=data.model_dump(), headers={"ETag": f'"{etag}"'})
    except Exception as exc:
        logger.error("[kill_criteria] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


# ── Conditional Gates (GATE-122, T-1298) ─────────────────────────────────────


class ConditionalGateSubCheck(BaseModel):
    description: str
    actual: int = 0
    required: int = 0
    passed: bool = False


class ConditionalGateItem(BaseModel):
    gate: str
    label: str
    actual: int = 0
    required: int = 0
    checks: list[ConditionalGateSubCheck] = []
    status: str = "FAIL"


class ConditionalGatesResponse(BaseModel):
    gates: list[ConditionalGateItem]


# For consistent handling with kill_criteria — registered in _READ_ONLY_PATHS via module init
_CONDITIONAL_GATE_CHECKS: list[dict] = [
    {"gate": "GATE-91", "label": "registered_transactions (Yelahanka hobli)", "checks": [
        ("registered_transactions (Yelahanka hobli)", "SELECT COUNT(*) FROM registered_transactions WHERE hobli ILIKE '%Yalahanka%'", 200),
    ]},
    {"gate": "GATE-92", "label": "parcels", "checks": [
        ("parcels", "SELECT COUNT(*) FROM parcels", 100),
    ]},
    {"gate": "GATE-93", "label": "prediction_ledger + tenders", "checks": [
        ("prediction_ledger", "SELECT COUNT(*) FROM prediction_ledger", 10),
        ("tenders", "SELECT COUNT(*) FROM tenders", 20),
    ]},
    {"gate": "GATE-94", "label": "gcc_hiring_snapshots + dc_conversions", "checks": [
        ("gcc_hiring_snapshots", "SELECT COUNT(*) FROM gcc_hiring_snapshots", 10),
        ("dc_conversions", "SELECT COUNT(*) FROM dc_conversions", 10),
    ]},
    {"gate": "GATE-95", "label": "registered_transactions (form17_inbox)", "checks": [
        ("registered_transactions (kaveri_form17)", "SELECT COUNT(*) FROM registered_transactions WHERE data_source = 'kaveri_form17'", 10),
    ]},
]


@router.get(
    "/ops/conditional-gates",
    response_model=ConditionalGatesResponse,
    summary="Evaluate conditional gate integration criteria against live DB",
)
@limiter.limit("30/hour")
async def conditional_gates(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            gates: list[ConditionalGateItem] = []
            for gd in _CONDITIONAL_GATE_CHECKS:
                sub_results: list[ConditionalGateSubCheck] = []
                for desc, query, required in gd["checks"]:
                    try:
                        row = conn.execute(_sa_text(query)).fetchone()
                        actual = int(row[0]) if row else 0
                        passed = actual >= required
                    except Exception:
                        actual = 0
                        passed = False
                    sub_results.append(ConditionalGateSubCheck(
                        description=desc, actual=actual, required=required, passed=passed,
                    ))
                all_pass = all(sr.passed for sr in sub_results)
                total_actual = sum(sr.actual for sr in sub_results)
                total_required = sum(sr.required for sr in sub_results)
                gates.append(ConditionalGateItem(
                    gate=gd["gate"], label=gd["label"],
                    actual=total_actual, required=total_required,
                    checks=sub_results,
                    status="PASS" if all_pass else "FAIL",
                ))
        data = ConditionalGatesResponse(gates=gates)
        etag = compute_etag(data.model_dump())
        _check = check_etag(request, etag)
        if _check:
            return _check
        return JSONResponse(
            content=data.model_dump(),
            headers={
                "ETag": f'"{etag}"',
                "Cache-Control": "private, max-age=30, must-revalidate",
            },
        )
    except Exception as exc:
        logger.error("[conditional_gates] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


# ── Decision Journal (GATE-118, T-1280) ─────────────────────────────────────
# Decision type/outcome values MUST match CHECK constraints in
# alembic/versions/0067_decision_journal.py — update both in sync.

_DECISION_TYPES = frozenset({"land_acquisition", "pricing", "jv_jd_target", "market_exit", "product_decision"})
_DECISION_OUTCOMES = frozenset({"acted", "deferred", "rejected"})


class DecisionJournalEntry(BaseModel):
    entry_date: date
    decision_type: str
    market: str | None = None
    intel_used: str | None = None
    outcome: str | None = None
    notes: str | None = None


class DecisionJournalCreateResponse(BaseModel):
    id: int
    created_at: str


class DecisionJournalItem(BaseModel):
    id: int
    entry_date: str | None = None
    decision_type: str
    market: str | None = None
    intel_used: str | None = None
    outcome: str | None = None
    notes: str | None = None
    created_at: str | None = None


class DecisionJournalGetResponse(BaseModel):
    total: int
    entries: list[DecisionJournalItem]


@router.post(
    "/ops/decision-journal",
    response_model=DecisionJournalCreateResponse,
    summary="Record a decision journal entry",
    status_code=201,
)
@limiter.limit("30/minute")
async def create_decision_journal(body: DecisionJournalEntry, request: Request):
    from dashboard.state import _has_role
    if not _has_role(request.state.role, "admin"):
        return _err_resp("insufficient_role — admin required", request, 403, "Ops")
    if body.decision_type not in _DECISION_TYPES:
        return _err_resp(f"invalid decision_type: {body.decision_type}", request, 422, "Ops")
    if body.outcome is not None and body.outcome not in _DECISION_OUTCOMES:
        return _err_resp(f"invalid outcome: {body.outcome}", request, 422, "Ops")
    try:
        with _get_sa_engine().begin() as conn:
            row = conn.execute(
                _sa_text("""
                    INSERT INTO decision_journal (entry_date, decision_type, market, intel_used, outcome, notes)
                    VALUES (:entry_date, :decision_type, :market, :intel_used, :outcome, :notes)
                    RETURNING id, created_at
                """),
                {
                    "entry_date": body.entry_date.isoformat(),
                    "decision_type": body.decision_type,
                    "market": body.market,
                    "intel_used": body.intel_used,
                    "outcome": body.outcome,
                    "notes": body.notes,
                },
            ).fetchone()
        return DecisionJournalCreateResponse(
            id=int(row[0]),
            created_at=row[1].isoformat() if row[1] else "",
        )
    except Exception as exc:
        logger.error("[create_decision_journal] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


@router.get(
    "/ops/decision-journal",
    response_model=DecisionJournalGetResponse,
    summary="List decision journal entries, paginated",
)
@limiter.limit("60/minute")
async def list_decision_journal(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    market: str | None = Query(default=None, description="Filter by market (case-insensitive)"),
    decision_type: str | None = Query(default=None, description="Filter by decision type"),
):
    try:
        with _get_sa_engine().connect() as conn:
            where_clauses: list[str] = []
            params: dict[str, object] = {"lim": limit, "off": offset}
            if market:
                where_clauses.append("market ILIKE :mkt")
                params["mkt"] = f"%{market}%"
            if decision_type:
                if decision_type not in _DECISION_TYPES:
                    return _err_resp(f"invalid decision_type filter: {decision_type}", request, 422, "Ops")
                where_clauses.append("decision_type = :dt")
                params["dt"] = decision_type
            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            count_params = {k: v for k, v in params.items() if k not in ("lim", "off")}
            total = conn.execute(
                _sa_text(f"SELECT COUNT(*) FROM decision_journal{where_sql}"), count_params
            ).scalar() or 0
            rows = conn.execute(
                _sa_text(f"""
                    SELECT id, entry_date, decision_type, market, intel_used, outcome, notes, created_at
                    FROM decision_journal{where_sql}
                    ORDER BY entry_date DESC, id DESC
                    LIMIT :lim OFFSET :off
                """),
                params,
            ).fetchall()
        return DecisionJournalGetResponse(
            total=total,
            entries=[
                DecisionJournalItem(
                    id=int(r[0]),
                    entry_date=r[1].isoformat() if r[1] else None,
                    decision_type=r[2] or "",
                    market=r[3],
                    intel_used=r[4],
                    outcome=r[5],
                    notes=r[6],
                    created_at=r[7].isoformat() if r[7] else None,
                )
                for r in rows
            ],
        )
    except Exception as exc:
        logger.error("[list_decision_journal] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


# ── Prediction Ledger (GATE-111, T-1242) ─────────────────────────────────────


class ModuleBreakdownEntry(BaseModel):
    hit: int = 0
    miss: int = 0


class LedgerResponse(BaseModel):
    total_claims: int
    pending: int
    hit: int
    miss: int
    partial: int
    unverifiable: int
    hit_rate: float
    markets: list[str]
    module_breakdown: dict[str, ModuleBreakdownEntry]
    as_of: str


@router.get(
    "/ops/ledger",
    response_model=LedgerResponse,
    summary="Prediction ledger verdict breakdown across all modules and markets",
    description="Returns aggregated hit/miss/pending counts by verdict and by source module. "
    "hit_rate = hits / (hits + misses). Read-only, readable by any authenticated role.",
)
@limiter.limit("60/minute")
async def ops_ledger(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            verdict_counts = conn.execute(
                _sa_text("""
                    SELECT COALESCE(verdict, 'pending') AS v, COUNT(*) AS cnt
                    FROM prediction_ledger
                    GROUP BY v
                """)
            ).fetchall()
            markets = conn.execute(
                _sa_text("""
                    SELECT DISTINCT market FROM prediction_ledger
                    WHERE market IS NOT NULL ORDER BY market
                """)
            ).fetchall()
            module_rows = conn.execute(
                _sa_text("""
                    SELECT source_module, verdict, COUNT(*) AS cnt
                    FROM prediction_ledger
                    GROUP BY source_module, verdict
                """)
            ).fetchall()

        counts: dict[str, int] = {"pending": 0, "hit": 0, "miss": 0, "partial": 0, "unverifiable": 0}
        for r in verdict_counts:
            key = str(r[0])
            if key in counts:
                counts[key] = int(r[1])

        total = sum(counts.values())
        hit_rate = counts["hit"] / max(counts["hit"] + counts["miss"], 1)

        module_bd: dict[str, dict[str, int]] = {}
        for r in module_rows:
            mod = str(r[0])
            v = str(r[1]) if r[1] else "pending"
            if mod not in module_bd:
                module_bd[mod] = {"hit": 0, "miss": 0}
            if v in ("hit", "miss"):
                module_bd[mod][v] += int(r[2])

        data = LedgerResponse(
            total_claims=total,
            pending=counts["pending"],
            hit=counts["hit"],
            miss=counts["miss"],
            partial=counts["partial"],
            unverifiable=counts["unverifiable"],
            hit_rate=round(hit_rate, 4),
            markets=[str(r[0]) for r in markets],
            module_breakdown={k: ModuleBreakdownEntry(**v) for k, v in module_bd.items()},
            as_of=datetime.now(timezone.utc).isoformat(),
        )
        etag = compute_etag(data.model_dump())
        _check = check_etag(request, etag)
        if _check:
            return _check
        return JSONResponse(content=data.model_dump(), headers={"ETag": f'"{etag}"'})
    except Exception as exc:
        logger.error("[ops_ledger] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


class LedgerFullItem(BaseModel):
    claim_type: str
    market: str | None = None
    total: int
    hit: int
    miss: int
    pending: int
    hit_rate_pct: float | None = None


class LedgerFullResponse(BaseModel):
    items: list[LedgerFullItem]
    as_of: str


@router.get(
    "/ops/ledger/full",
    response_model=LedgerFullResponse,
    summary="All-module prediction ledger grouped by claim_type + market + verdict",
    description="Returns grouped prediction counts from prediction_ledger (all claim types: "
    "psf_forecast, opportunity_score, assembly_alert, corridor_call). "
    "Supports optional claim_type, market, verdict filters via query params.",
)
@limiter.limit("30/minute")
async def ops_ledger_full(
    request: Request,
    claim_type: str | None = Query(default=None, description="Filter by claim_type"),
    market: str | None = Query(default=None, description="Filter by market"),
    verdict: str | None = Query(default=None, description="Filter by verdict"),
):
    rid = getattr(request.state, "rid", None)
    try:
        with _get_sa_engine().connect() as conn:
            where_parts: list[str] = []
            params: dict = {}
            if claim_type:
                where_parts.append("claim_type = :claim_type")
                params["claim_type"] = claim_type
            if market:
                where_parts.append("market = :market")
                params["market"] = market
            if verdict:
                where_parts.append("verdict = :verdict")
                params["verdict"] = verdict
            where_sql = " AND ".join(where_parts) if where_parts else "TRUE"

            rows = conn.execute(
                _sa_text(f"""
                    SELECT
                        claim_type,
                        market,
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE verdict = 'hit') AS hit,
                        COUNT(*) FILTER (WHERE verdict = 'miss') AS miss,
                        COUNT(*) FILTER (WHERE verdict IS NULL OR verdict NOT IN ('hit', 'miss')) AS pending
                    FROM prediction_ledger
                    WHERE {where_sql}
                    GROUP BY claim_type, market
                    ORDER BY claim_type, market
                """),
                params,
            ).fetchall()

        items = []
        for r in rows:
            hit = int(r[2])
            miss = int(r[3])
            total_hit_miss = hit + miss
            hit_rate_pct = round(hit / total_hit_miss * 100, 1) if total_hit_miss > 0 else None
            items.append(LedgerFullItem(
                claim_type=str(r[0]),
                market=str(r[1]) if r[1] else None,
                total=int(r[2]),
                hit=hit,
                miss=miss,
                pending=int(r[4]),
                hit_rate_pct=hit_rate_pct,
            ))

        data = LedgerFullResponse(items=items, as_of=datetime.now(timezone.utc).isoformat())
        etag = compute_etag(data.model_dump())
        _check = check_etag(request, etag)
        if _check:
            return _check
        return JSONResponse(content=data.model_dump(), headers={"ETag": f'"{etag}"'})
    except Exception as exc:
        logger.error("[ops_ledger_full] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


try:
    from prometheus_client import Counter as _LedgerVerdictCounter
    _ledger_manual_verdicts = _LedgerVerdictCounter(
        "ledger_manual_verdicts_total",
        "Manual verdict entries on prediction_ledger",
    )
except ImportError:
    _ledger_manual_verdicts = None


class VerdictEntryRequest(BaseModel):
    ledger_id: int
    verdict: str
    actual_value: float | None = None


@router.post(
    "/ops/ledger/verdict",
    summary="Manually set a verdict on a prediction_ledger row",
    description="Admin-only. Updates the verdict (hit/miss/partial/unverifiable) "
    "and optional actual_value for a single prediction_ledger row.",
)
@limiter.limit("10/minute")
async def ops_ledger_verdict(request: Request, body: VerdictEntryRequest):
    try:
        valid_verdicts = {"hit", "miss", "partial", "unverifiable"}
        if body.verdict not in valid_verdicts:
            return _err_resp(f"Invalid verdict '{body.verdict}'. Valid: {valid_verdicts}", request, 400, "Ops")

        with _get_sa_engine().begin() as conn:
            result = conn.execute(
                _sa_text("""
                    UPDATE prediction_ledger
                    SET verdict = :verdict,
                        actual_value = :actual_value
                    WHERE id = :id
                """),
                {
                    "id": body.ledger_id,
                    "verdict": body.verdict,
                    "actual_value": body.actual_value,
                },
            )
            if result.rowcount == 0:
                return _err_resp(f"Ledger row {body.ledger_id} not found", request, 404, "Ops")

        if _ledger_manual_verdicts is not None:
            _ledger_manual_verdicts.inc()

        return {"status": "ok", "updated_id": body.ledger_id, "verdict": body.verdict}
    except Exception as exc:
        logger.error("[ops_ledger_verdict] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")


# ── Corridor Backtest Verdicts (GATE-116, T-1270) ────────────────────────────


class CorridorBacktestVerdict(BaseModel):
    corridor_name: str
    last_run_date: str | None = None
    rank_correlation: float | None = None
    kill_criterion_met: bool | None = None
    verdict: str | None = None


class CorridorBacktestResponse(BaseModel):
    corridors: list[CorridorBacktestVerdict]
    as_of: str


@router.get(
    "/ops/corridor-backtest",
    response_model=CorridorBacktestResponse,
    summary="Latest corridor backtest verdicts per corridor",
    description="Returns the most recent backtest verdict for each seeded corridor. "
    "Read-only, readable by any authenticated role.",
)
@limiter.limit("60/minute")
async def ops_corridor_backtest(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT DISTINCT ON (corridor_name)
                        corridor_name,
                        run_date,
                        rank_correlation,
                        kill_criterion_met,
                        verdict
                    FROM corridor_backtest_verdicts
                    ORDER BY corridor_name, created_at DESC
                """)
            ).fetchall()

        corridors = [
            CorridorBacktestVerdict(
                corridor_name=str(r[0]),
                last_run_date=str(r[1]) if r[1] else None,
                rank_correlation=float(r[2]) if r[2] is not None else None,
                kill_criterion_met=bool(r[3]) if r[3] is not None else None,
                verdict=str(r[4]) if r[4] else None,
            )
            for r in rows
        ]

        if not corridors:
            from utils.corridor_scorer_v2 import _CORRIDOR_SEEDS
            corridors = [
                CorridorBacktestVerdict(corridor_name=s.corridor_id)
                for s in _CORRIDOR_SEEDS
            ]

        data = CorridorBacktestResponse(
            corridors=corridors,
            as_of=datetime.now(timezone.utc).isoformat(),
        )
        etag = compute_etag(data.model_dump())
        _check = check_etag(request, etag)
        if _check:
            return _check
        return JSONResponse(content=data.model_dump(), headers={"ETag": f'"{etag}"'})
    except Exception as exc:
        logger.error("[ops_corridor_backtest] %s", exc)
        return _err_resp(str(exc), request, 500, "Ops")
