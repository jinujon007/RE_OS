"""
RE_OS Dashboard — shared state and helpers extracted from app_fastapi.py.

All routers import from this module — never from dashboard.app_fastapi.
app_fastapi.py imports from here for middleware and startup.
"""

from __future__ import annotations

import copy
import glob
import json
import logging
import os
import re
import subprocess
import threading
import time
from collections import OrderedDict
from datetime import datetime

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import text as _sa_text


class ErrorResponse(BaseModel):
    error: str
    code: str = "INTERNAL_ERROR"
    request_id: str = ""
    docs_url: str = ""


_ERROR_CODES: dict[int, str] = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
}


def _error_json(error: str, status_code: int = 400, request_id: str = "", tag: str = "") -> dict:
    code = _ERROR_CODES.get(status_code, "INTERNAL_ERROR")
    docs_url = f"/docs#tag/{tag}" if tag else ""
    return ErrorResponse(
        error=error,
        code=code,
        request_id=request_id,
        docs_url=docs_url,
    ).model_dump()


def _err_resp(error: str, request: "Request | None" = None, status_code: int = 400, tag: str = "") -> JSONResponse:
    rid = request.state.request_id if request and hasattr(request.state, "request_id") else ""
    return JSONResponse(content=_error_json(error, status_code=status_code, request_id=rid, tag=tag), status_code=status_code)


class HealthServiceStatus(BaseModel):
    agents: str = "ok"
    postgres: str = "ok"
    redis: str = "ok"
    ollama: str = "warn"
    chroma: str = "error"

logger = logging.getLogger("re_os.dashboard")

from utils.db import get_engine as _get_sa_engine

# ── Redis password enforcement (lazy — fires at first access, not module import) ──

_REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
_REDIS_URL = os.environ.get("REDIS_URL", "")


def _validate_redis_config() -> str:
    """Validate Redis config and return storage URI.

    Raises RuntimeError if Redis is configured without a password (non-memory://).
    Called at module load by Limiter() — if REDIS_PASSWORD is unset and REDIS_URL
    is not memory://, this raises at import time and crashes the FastAPI process.
    """
    url = _REDIS_URL
    if not url:
        url = f"redis://:{_REDIS_PASSWORD}@localhost:6379" if _REDIS_PASSWORD else "memory://"
    if not _REDIS_PASSWORD and not url.startswith("memory://"):
        raise RuntimeError(
            "REDIS_PASSWORD must be set when using Redis. "
            "Set REDIS_PASSWORD in .env or use REDIS_URL=memory:// for development."
        )
    return url


# ── Rate Limiter ─────────────────────────────────────────────────────────────

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_validate_redis_config(),
    strategy="fixed-window",
)

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

# ── Logger ───────────────────────────────────────────────────────────────────

# ── Redis-backed running store (T-1246) ──────────────────────────────────────
# Stores pipeline running state in Redis so uvicorn --workers N can share state.
# Falls back to in-memory dict if Redis unavailable.

_REDIS_HASH_KEY = "re_os:pipeline_running"
_REDIS_TTL_SECONDS = 3600  # 1h — prevents stale entries on pod crash
_REDIS_CLIENT_INSTANCE = None
_REDIS_CLIENT_LOCK = threading.Lock()
_REDIS_RECONNECT_COOLDOWN = 30  # seconds between reconnect attempts
_last_redis_attempt = 0.0  # sentinel: 0.0 always triggers first attempt (monotonic clock floor)


def _attempt_redis_connect():
    """Attempt to create a Redis client. Sets instance on success, False on failure.
    Thread-safe: only call while holding _REDIS_CLIENT_LOCK."""
    global _REDIS_CLIENT_INSTANCE, _last_redis_attempt
    _last_redis_attempt = time.monotonic()
    try:
        import redis as _redis_mod
        from config.settings import REDIS_URL as _redis_url
        _REDIS_CLIENT_INSTANCE = _redis_mod.from_url(
            _redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_keepalive=True,
            health_check_interval=30,
        )
    except _redis_mod.ConnectionError as exc:
        logger.warning("[Redis running] Connection pool exhausted or unavailable: %s — using in-memory fallback", exc)
        _REDIS_CLIENT_INSTANCE = False
    except Exception as exc:
        logger.debug("[Redis running] Client init failed: %s — using in-memory fallback", exc)
        _REDIS_CLIENT_INSTANCE = False


def _reset_redis_client() -> None:
    """Reset Redis connection state under lock, forcing reconnect on next call.

    Thread-safe: acquires _REDIS_CLIENT_LOCK before mutating
    _REDIS_CLIENT_INSTANCE and _last_redis_attempt.

    Clearing _last_redis_attempt to 0.0 bypasses the cooldown timer so the
    next _get_redis_client() call immediately attempts reconnection rather
    than waiting _REDIS_RECONNECT_COOLDOWN seconds.

    Called by redis_health.py on ping failure — the health check loop
    is the sole external caller. All mutations of _REDIS_CLIENT_INSTANCE
    must go through this function or _attempt_redis_connect() (both lock-
    protected). No code outside state.py should assign to
    _REDIS_CLIENT_INSTANCE directly.
    """
    global _REDIS_CLIENT_INSTANCE, _last_redis_attempt
    with _REDIS_CLIENT_LOCK:
        _REDIS_CLIENT_INSTANCE = False
        _last_redis_attempt = 0.0


def _get_redis_client():
    """Module-level lazy singleton Redis client with connection pool.

    Returns None if Redis is unavailable (triggers in-memory fallback).
    Automatically retries connection every _REDIS_RECONNECT_COOLDOWN seconds
    after a failure (T-1261). Connection reused — safe for --workers N.

    Thread-safe: uses double-checked locking with a single cooldown gate
    inside the lock to prevent thundering-herd reconnect attempts.
    """
    global _REDIS_CLIENT_INSTANCE, _last_redis_attempt
    if _REDIS_CLIENT_INSTANCE is None:
        with _REDIS_CLIENT_LOCK:
            if _REDIS_CLIENT_INSTANCE is None:
                _attempt_redis_connect()
    elif _REDIS_CLIENT_INSTANCE is False:
        with _REDIS_CLIENT_LOCK:
            if _REDIS_CLIENT_INSTANCE is False:
                now = time.monotonic()
                if now - _last_redis_attempt > _REDIS_RECONNECT_COOLDOWN:
                    _attempt_redis_connect()
    return _REDIS_CLIENT_INSTANCE if _REDIS_CLIENT_INSTANCE is not False else None


def _redis_expiry(r):
    """Set TTL on the running hash after each write to prevent stale accumulation."""
    try:
        r.expire(_REDIS_HASH_KEY, _REDIS_TTL_SECONDS)
    except Exception:
        pass


def _set_running(market: str, state: str = "running", pid: int = 0, started: str = "") -> None:
    """Store running state — tries Redis first, falls back to in-memory.

    Args:
        market: Market name (Yelahanka, Devanahalli, Hebbal).
        state: One of 'running', 'done', 'failed'.
        pid: OS process ID of the pipeline subprocess.
        started: ISO-8601 timestamp of when the pipeline started.
    """
    payload = {"state": state, "pid": pid, "started": started}
    r = _get_redis_client()
    if r is not None:
        try:
            r.hset(_REDIS_HASH_KEY, market, json.dumps(payload))
            _redis_expiry(r)
            return
        except Exception as exc:
            logger.debug("[Redis running] hset failed: %s — falling back to in-memory", exc)
    with _lock:
        _running[market] = payload


def _get_running(market: str) -> dict | None:
    """Get running state for a market."""
    r = _get_redis_client()
    if r is not None:
        try:
            raw = r.hget(_REDIS_HASH_KEY, market)
            if raw is not None:
                result: dict = json.loads(raw)
                return result
        except Exception:
            pass
    with _lock:
        val = _running.get(market)
        return val if isinstance(val, dict) else None


def _clear_running(market: str) -> None:
    """Remove running state for a market."""
    r = _get_redis_client()
    if r is not None:
        try:
            r.hdel(_REDIS_HASH_KEY, market)
            return
        except Exception:
            pass
    with _lock:
        _running.pop(market, None)


def _get_all_running() -> dict:
    """Get all running states.

    Returns Redis state if available, falling back to in-memory.
    Filters out stale Redis entries (older than TTL with 'done'/'failed' state)
    to prevent phantom-pipeline artifacts across worker restarts.
    """
    r = _get_redis_client()
    if r is not None:
        try:
            raw = r.hgetall(_REDIS_HASH_KEY)
            if raw:
                parsed = {}
                for k, v in raw.items():
                    try:
                        parsed[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        continue
                now_ts = time.time()
                for market, entry in list(parsed.items()):
                    if entry.get("state") in ("done", "failed"):
                        started = entry.get("started")
                        if started:
                            try:
                                age = now_ts - datetime.fromisoformat(started).timestamp()
                                if age > _REDIS_TTL_SECONDS:
                                    r.hdel(_REDIS_HASH_KEY, market)
                                    del parsed[market]
                            except (ValueError, TypeError):
                                pass
                if parsed:
                    return parsed
        except Exception:
            pass
    with _lock:
        return dict(_running)


# ── State ────────────────────────────────────────────────────────────────────

_running: dict = {}
_lock = threading.Lock()

_diag_agents_contract_logged = False
_diag_running_last_signature = None

_estimated_cache: dict[str, tuple[bool, float]] = {}
_ESTIMATED_CACHE_TTL = 120

_embedder_instance = None
_embedder_lock = threading.Lock()

_search_cache: OrderedDict[str, tuple[list[dict], float]] = OrderedDict()
_SEARCH_CACHE_TTL = 45
_SEARCH_CACHE_MAX = 200


def _cache_get(key: str) -> tuple[list[dict], float] | None:
    val = _search_cache.get(key)
    if val is not None:
        _search_cache.move_to_end(key)
    return val


def _cache_put(key: str, val: tuple[list[dict], float]) -> None:
    _search_cache[key] = val
    if len(_search_cache) > _SEARCH_CACHE_MAX:
        _search_cache.popitem(last=False)


LOG_PATH = "/app/logs/crew.log"
VALID_MARKETS = {"Yelahanka", "Devanahalli", "Hebbal", "all"}
MARKET_CANONICAL = {
    "yelahanka": "Yelahanka",
    "devanahalli": "Devanahalli",
    "hebbal": "Hebbal",
    "all": "all",
}
MARKET_SLUG = {
    "Yelahanka": "yelahanka",
    "Devanahalli": "devanahalli",
    "Hebbal": "hebbal",
}

_agent_states = {
    "ceo": {
        "id": "ceo", "name": "The Director", "role": "Orchestrator",
        "label": "IDLE", "state": "idle", "last_action": "Awaiting pipeline trigger",
        "started": None,
    },
    "scraper": {
        "id": "scraper", "name": "The Scout", "role": "Field Researcher",
        "label": "IDLE", "state": "idle", "last_action": "No recent scrape",
        "started": None,
        "terminals": {"rera": "idle", "listings": "idle", "kaveri": "idle"},
    },
    "analyst": {
        "id": "analyst", "name": "The Analyst", "role": "Market Analyst",
        "label": "IDLE", "state": "idle", "last_action": "No recent analysis",
        "started": None,
    },
    "processor": {
        "id": "processor", "name": "The Processor", "role": "Document Handler",
        "label": "STANDBY", "state": "standby", "last_action": "Standalone mode only",
        "started": None,
    },
    "sentinel": {
        "id": "sentinel", "name": "The Sentinel", "role": "Scheduler Monitor",
        "label": "WATCHING", "state": "idle", "last_action": "Checking schedule...",
        "started": None,
    },
}

AGENT_ACTIONS: dict[str, list[dict]] = {
    "ceo": [
        {"label": "\u25b6 Yelahanka", "prompt": "run Yelahanka"},
        {"label": "\u25b6 Devanahalli", "prompt": "run Devanahalli"},
        {"label": "\u25b6 Hebbal", "prompt": "run Hebbal"},
        {"label": "\u23f9 Stop", "prompt": "stop all"},
        {"label": "? Status", "prompt": "status"},
    ],
    "scraper": [
        {"label": "\u25b6 Yelahanka", "prompt": "scrape Yelahanka"},
        {"label": "\u25b6 Devanahalli", "prompt": "scrape Devanahalli"},
        {"label": "\u25b6 Hebbal", "prompt": "scrape Hebbal"},
    ],
    "analyst": [
        {"label": "\U0001f4ca Yelahanka", "prompt": "analyze Yelahanka"},
        {"label": "\U0001f4ca Devanahalli", "prompt": "analyze Devanahalli"},
        {"label": "\U0001f4ca Hebbal", "prompt": "analyze Hebbal"},
    ],
    "processor": [],
    "sentinel": [],
}

# ── API Key check (cached globals for speed, patchable for tests) ──────────

_API_KEY_WARNED: bool = False
_API_KEY: str | None = None
_API_KEY_READ: str | None = None
_API_KEY_ADMIN: str | None = None


def _reset_api_keys():
    global _API_KEY, _API_KEY_READ, _API_KEY_ADMIN, _API_KEY_WARNED
    _API_KEY = None
    _API_KEY_READ = None
    _API_KEY_ADMIN = None
    _API_KEY_WARNED = False


def _ensure_api_keys():
    global _API_KEY, _API_KEY_READ, _API_KEY_ADMIN, _API_KEY_WARNED
    if _API_KEY is not None:
        return
    _API_KEY = os.environ.get("DASHBOARD_API_KEY", "") or None
    _API_KEY_READ = os.environ.get("DASHBOARD_API_KEY_READ", "") or None
    _API_KEY_ADMIN = os.environ.get("DASHBOARD_API_KEY_ADMIN", "") or None
    if not _API_KEY:
        if _API_KEY_WARNED:
            return
        _allow_empty = os.environ.get("DASHBOARD_API_KEY_ALLOW_EMPTY", "").lower() in (
            "1", "true", "yes",
        )
        if _allow_empty:
            logging.warning(
                "[RE_OS] DASHBOARD_API_KEY is not set — DASHBOARD_API_KEY_ALLOW_EMPTY=true "
                "overrides the hard error. Port 8050 is publicly accessible."
            )
            _API_KEY_WARNED = True
        else:
            raise RuntimeError(
                "DASHBOARD_API_KEY is not set. All /api endpoints would be publicly accessible. "
                "Set DASHBOARD_API_KEY in .env, or set DASHBOARD_API_KEY_ALLOW_EMPTY=true to "
                "explicitly permit unauthenticated access (e.g. local dev only)."
            )


_ROLE_HIERARCHY = {"read": 1, "write": 2, "admin": 3}


def _get_request_role(request: Request) -> str | None:
    try:
        _ensure_api_keys()
    except RuntimeError:
        return "admin"
    provided = request.headers.get("X-API-Key", "")
    if provided and _API_KEY_ADMIN and provided == _API_KEY_ADMIN:
        return "admin"
    if provided and _API_KEY and provided == _API_KEY:
        return "write"
    if provided and _API_KEY_READ and provided == _API_KEY_READ:
        return "read"
    if not provided and not _API_KEY:
        return "admin"
    return None


def _has_role(role: str | None, required: str) -> bool:
    if role is None:
        return False
    return _ROLE_HIERARCHY.get(role, 0) >= _ROLE_HIERARCHY.get(required, 0)


_ADMIN_PATHS = frozenset({
    "/api/v1/ops/kill-criteria",
    "/api/v1/ops/failed-records",
    "/api/v1/audit/log",
})

_WRITE_PATHS = frozenset({
    "/api/v1/evaluate",
    "/api/v1/board/session",
    "/api/v1/ops/v2-declare",
})

# ── Auth ──────────────────────────────────────────────────────────────────────

_READ_ONLY_PATHS = frozenset(
    {
        "/api/health", "/api/health/live", "/api/health/llm", "/api/health/backup",
        "/api/status", "/api/agents", "/api/intel/cards",
        "/api/intel/download", "/api/intel/search", "/api/db/state",
        "/api/sentinel/status", "/api/board/sessions", "/api/db/tables",
        "/api/tasks", "/api/engineering/brief", "/api/finance/brief",
        "/api/legal/brief", "/api/alerts", "/api/registry",
        "/api/opportunity/queue", "/api/scheduler/health",
        "/api/competitive/pulse", "/api/portfolio", "/api/portfolio/summary",
        "/api/pr/mentions", "/api/optimizer/report", "/api/digest/weekly",
        "/api/digest/monthly", "/api/llm/quota", "/optimizer",
        "/api/ops/v2-readiness",
        "/api/v1/ops/slo",
        "/api/corridor/score",
        # v1 prefix aliases — every /api/ path must have a /api/v1/ twin
        "/api/v1/health", "/api/v1/health/live", "/api/v1/health/llm", "/api/v1/health/backup",
        "/api/v1/status", "/api/v1/agents", "/api/v1/intel/cards",
        "/api/v1/intel/download", "/api/v1/intel/search", "/api/v1/db/state",
        "/api/v1/sentinel/status", "/api/v1/board/sessions", "/api/v1/db/tables",
        "/api/v1/tasks", "/api/v1/engineering/brief", "/api/v1/finance/brief",
        "/api/v1/legal/brief", "/api/v1/alerts", "/api/v1/registry",
        "/api/v1/opportunity/queue", "/api/v1/scheduler/health",
        "/api/v1/competitive/pulse", "/api/v1/portfolio", "/api/v1/portfolio/summary",
        "/api/v1/pr/mentions", "/api/v1/optimizer/report", "/api/v1/digest/weekly",
        "/api/v1/digest/monthly", "/api/v1/llm/quota",
        "/api/v1/ops/v2-readiness",
        "/api/v1/ops/kill-criteria",
        "/api/v1/ops/corridor-backtest",
        "/api/ops/corridor-backtest",
        "/api/v1/ops/ledger",
        "/api/ops/slo",
        "/api/v1/ops/slo",
        "/api/v1/ops/corridor-backtest",
        "/api/v1/ops/decision-journal",
        "/api/ops/decision-journal",
        "/api/v1/ops/conditional-gates",
        "/api/ops/conditional-gates",
        "/api/v1/ops/ledger/accuracy",
        "/api/ops/ledger/accuracy",
        "/api/v1/mcp/health",
        "/api/mcp/health",
        "/api/v1/deeds/throughput",
        "/api/deeds/throughput",
    }
)
_READ_ONLY_PREFIXES = (
    "/api/reports/", "/api/logs/", "/api/market/", "/api/evaluate/",
    "/api/data/", "/api/memory/", "/api/demand/", "/api/distress/",
    "/api/scraper/", "/api/parcel/", "/api/finance/", "/api/board/sessions/",
    "/api/content/", "/api/process-audit/", "/api/shareholders/",
    "/api/govt/", "/api/competitive/", "/api/portfolio/",
    "/api/pr/", "/api/optimizer/", "/api/llm/",
    # v1 prefix aliases
    "/api/v1/reports/", "/api/v1/logs/", "/api/v1/market/", "/api/v1/evaluate/",
    "/api/v1/data/", "/api/v1/memory/", "/api/v1/demand/", "/api/v1/distress/",
    "/api/v1/scraper/", "/api/v1/parcel/", "/api/v1/finance/", "/api/v1/board/sessions/",
    "/api/v1/content/", "/api/v1/process-audit/", "/api/v1/shareholders/",
    "/api/v1/govt/", "/api/v1/competitive/", "/api/v1/portfolio/",
    "/api/v1/pr/", "/api/v1/optimizer/", "/api/v1/llm/",
    "/api/v1/intel/", "/api/intel/",
    "/api/v1/investor/", "/api/investor/",
)


def _is_run_api_authorized(req: Request) -> bool:
    try:
        _ensure_api_keys()
    except RuntimeError:
        return True
    if not _API_KEY:
        return True
    role = _get_request_role(req)
    if role is not None:
        return True
    api_key_prev = os.environ.get("DASHBOARD_API_KEY_PREV", "")
    provided = req.headers.get("X-API-Key", "")
    return bool(api_key_prev and provided == api_key_prev)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _normalize_market(market_raw: str | None) -> str | None:
    if not market_raw:
        return None
    key = market_raw.strip().lower()
    return MARKET_CANONICAL.get(key)


def _detect_market_from_prompt(prompt: str) -> str | None:
    text = (prompt or "").lower()
    for key, canonical in MARKET_CANONICAL.items():
        if key in text and key != "all":
            return canonical
    return None


def _latest_report_path(market: str | None = None) -> str | None:
    markets = [market] if market else ["Yelahanka", "Devanahalli", "Hebbal"]
    latest_file = None
    for m in markets:
        pattern = f"/app/outputs/{m.lower()}/intel_report_*.txt"
        files = sorted(glob.glob(pattern))
        if files:
            cand = files[-1]
            if latest_file is None or cand > latest_file:
                latest_file = cand
    return latest_file


# Lock-invariant convention: functions with _MUST_HOLD_LOCK suffix require the
# caller to hold _lock before calling. This is a naming convention for
# threading.Lock (which lacks _is_owned()) — greppable and self-documenting.

def _log_running_lifecycle_MUST_HOLD_LOCK(context: str):
    global _diag_running_last_signature
    signature = []
    for market, entry in sorted(_running.items()):
        rc = entry["proc"].poll()
        signature.append((market, rc, entry.get("started"), entry["proc"].pid))
    signature_t = tuple(signature)
    if signature_t != _diag_running_last_signature:
        logger.info("[DIAG running] %s snapshot=%s", context, signature)
        _diag_running_last_signature = signature_t


def _prune_finished_running_entries_locked():
    finished = [
        market for market, entry in _running.items() if entry["proc"].poll() is not None
    ]
    for market in finished:
        entry = _running.pop(market, None)
        _clear_running(market)
        if entry and "proc" in entry:
            try:
                entry["proc"].wait(timeout=0)
            except Exception:
                pass
    if finished:
        logger.info("[DIAG running] pruned finished markets=%s", finished)


def _start_pipeline_for_market(market: str) -> tuple[dict, int]:
    if market not in VALID_MARKETS:
        return {"error": "invalid market"}, 400
    with _lock:
        existing = _running.get(market)
        if existing and existing["proc"].poll() is None:
            return {"status": "already_running", "market": market}, 200
        cmd = ["python", "crews/market_intel_crew.py"]
        if market != "all":
            cmd += ["--market", market]
        os.makedirs("/app/logs", exist_ok=True)
        if market == "all":
            log_dest = LOG_PATH
        else:
            slug = MARKET_SLUG.get(market, market.lower())
            log_dest = f"/app/logs/{slug}.log"
        with open(log_dest, "a") as _log_fh:
            proc = subprocess.Popen(
                cmd, cwd="/app", shell=False, stdout=_log_fh, stderr=_log_fh,
            )
        started = datetime.now().isoformat()
        entry = {"proc": proc, "started": started}
        _running[market] = entry
        _set_running(market, state="running", pid=proc.pid, started=started)
        logger.info(
            "[DIAG running] started market=%s pid=%s started=%s",
            market, proc.pid, started,
        )
        for aid in ["scraper", "analyst", "ceo"]:
            _agent_states[aid]["started"] = started
    return {"status": "started", "market": market}, 200


def _stop_pipeline_for_market(market: str) -> tuple[dict, int]:
    with _lock:
        entry = _running.get(market)
        if entry and "proc" in entry and entry["proc"].poll() is None:
            entry["proc"].terminate()
            try:
                entry["proc"].wait(timeout=2)
            except subprocess.TimeoutExpired:
                entry["proc"].kill()
            logger.info(
                "[DIAG running] terminate requested market=%s pid=%s",
                market, entry["proc"].pid,
            )
            _clear_running(market)
            return {"status": "stopped", "market": market}, 200
    _clear_running(market)
    return {"status": "not_running"}, 200


def _running_snapshot() -> dict:
    snapshot = {}
    all_running = _get_all_running()
    for market, entry_data in all_running.items():
        if not isinstance(entry_data, dict):
            continue
        snapshot[market] = {
            "started": entry_data.get("started"),
            "state": entry_data.get("state", "unknown"),
            "pid": entry_data.get("pid"),
        }
        with _lock:
            local = _running.get(market)
            if local and "proc" in local:
                rc = local["proc"].poll()
                snapshot[market]["returncode"] = rc
                if rc is not None:
                    snapshot[market]["state"] = "done" if rc == 0 else "failed"
    with _lock:
        for market, entry in _running.items():
            if market not in snapshot and "proc" in entry:
                rc = entry["proc"].poll()
                snapshot[market] = {
                    "started": entry.get("started"),
                    "state": "running" if rc is None else ("done" if rc == 0 else "failed"),
                    "returncode": rc,
                    "pid": entry["proc"].pid,
                }
    return snapshot


def _market_go_no_go(active_projects: int, avg_psf: int | None, estimated: bool) -> str:
    if estimated or active_projects < 3 or avg_psf is None:
        return "WATCH"
    if 3500 <= avg_psf <= 9000 and active_projects >= 8:
        return "GO"
    return "NO-GO"


def _validate_registry_payload(payload: dict) -> tuple[dict | None, str | None]:
    required = ("id", "name", "role", "persona", "llm_tier")
    for field in required:
        val = payload.get(field)
        if not val:
            return None, f"missing required field: '{field}'"
        if not isinstance(val, str):
            return None, f"field '{field}' must be a string, got {type(val).__name__}"
    spec_id = str(payload["id"]).strip()
    if not re.match(r"^[a-z][a-z0-9_-]*$", spec_id):
        return None, "invalid id - must start with lowercase letter, contain only [a-z0-9_-]"
    if len(spec_id) > 100:
        return None, f"id too long ({len(spec_id)} chars) - max 100"
    tier = payload["llm_tier"]
    if tier not in ("heavy", "analysis", "light"):
        return None, f"invalid llm_tier '{tier}' - must be heavy, analysis, or light"
    goal = payload.get("goal")
    if goal is not None and not isinstance(goal, str):
        return None, f"field 'goal' must be a string, got {type(goal).__name__}"
    tools_val = payload.get("tools")
    if tools_val is not None and not isinstance(tools_val, list):
        return None, f"field 'tools' must be a list, got {type(tools_val).__name__}"
    markets_val = payload.get("markets")
    if markets_val is not None and not isinstance(markets_val, list):
        return None, f"field 'markets' must be a list, got {type(markets_val).__name__}"
    max_iter = payload.get("max_iter")
    if max_iter is not None and not isinstance(max_iter, int):
        return None, f"field 'max_iter' must be an integer, got {type(max_iter).__name__}"
    active = payload.get("active")
    if active is not None and not isinstance(active, bool):
        return None, f"field 'active' must be a boolean, got {type(active).__name__}"
    return payload, None


# ── Digest helpers (used by ops.py) ──────────────────────────────────────────

VALID_MARKETS_DIGEST = frozenset({"Yelahanka", "Devanahalli", "Hebbal"})


def _resolve_market(market: str | None) -> str | None:
    if market is None:
        return None
    canonical = market.strip().lower()
    for valid in VALID_MARKETS_DIGEST:
        if valid.lower() == canonical:
            return valid
    return None


def _all_markets() -> list[str]:
    from config.settings import TARGET_MARKETS
    return [m.strip() for m in TARGET_MARKETS]


# ── Pulse cache (used by board_room.py) ──────────────────────────────────────

_pulse_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_pulse_cache_lock = threading.Lock()
_PULSE_CACHE_TTL = 14400
_PULSE_CACHE_MAX = 500

# ── Registry cache (used by ops.py) ──────────────────────────────────────────

_registry_cache: dict[str, tuple[list[dict], float]] = {}
_REGISTRY_CACHE_TTL = 15

# ── Valid board markets ──────────────────────────────────────────────────────

_VALID_BOARD_MARKETS = {"Yelahanka", "Devanahalli", "Hebbal", ""}

# ── Agent states access ──────────────────────────────────────────────────────

def get_agent_states() -> dict:
    return _agent_states


def get_lock():
    return _lock
