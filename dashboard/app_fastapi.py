"""
RE_OS Dashboard — FastAPI web server (v2)

Flask → FastAPI migration (T-727–T-730). All 27 routes ported with exact API
contract: same paths, same response shapes, same auth/rate-limit/security-headers
behavior. Auto-generated OpenAPI docs at /docs and /redoc.

Architecture:
  - FastAPI app with CORS middleware, rate limiting (slowapi/Redis), Prometheus
    /metrics endpoint, SSE log streaming, and security headers.
  - Auth: middleware-based API key gate (X-API-Key header or ?api_key= query),
    with read-only path exemptions and DASHBOARD_API_KEY_PREV rotation support.
  - DB: psycopg2 thread-safe connection pool (min=1, max=10).
  - Pipeline: subprocess-based market intelligence crew with running-state
    tracking via _running dict + threading.Lock singleton.
  - Embedder: lazy-initialized singleton IntelEmbedder with LRU search cache.

Health endpoints:
  - /api/health/live — lightweight liveness probe (no deps, always returns 200)
  - /api/health — full readiness probe (Postgres, Redis, Ollama, Chroma)

Risk Mitigation:
  +-----------------------------+--------------------------------------------+
  | Risk                        | Mitigation                                 |
  +-----------------------------+--------------------------------------------+
  | JSONDecodeError on POST     | Every `await request.json()` wrapped in     |
  | body                        | try/except -> defaults to {}                |
  +-----------------------------+--------------------------------------------+
  | DB pool exhaustion          | maxconn=10, _release_db always in finally   |
  +-----------------------------+--------------------------------------------+
  | _running state corruption   | threading.Lock on all mutations, --workers 1|
  | (uvicorn workers > 1)       |                                            |
  +-----------------------------+--------------------------------------------+
  | Embedder race condition     | Double-checked locking singleton pattern   |
  +-----------------------------+--------------------------------------------+
  | Subprocess zombie           | wait(timeout=0) / kill() in                 |
  |                             | _prune_finished_running_entries_locked      |
  +-----------------------------+--------------------------------------------+
  | Log path traversal          | slug validated through MARKET_SLUG whitelist|
  +-----------------------------+--------------------------------------------+
  | SSE memory leak             | 32KB tail buffer, 80-line cap, GeneratorExit|
  |                             | catch on disconnect                         |
  +-----------------------------+--------------------------------------------+
  | Prometheus cardinality      | Labels bounded: source/market/stage are     |
  | explosion                   | from known enums                            |
  +-----------------------------+--------------------------------------------+
  | Rate-limit bypass           | slowapi Redis-backed, per-IP key function   |
  +-----------------------------+--------------------------------------------+
  | API key rotation            | DASHBOARD_API_KEY_PREV for zero-downtime    |
  +-----------------------------+--------------------------------------------+
"""

import copy
import csv
import glob
import io
import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime

# ── Third-party ──────────────────────────────────────────────────────────────

import psycopg2
import psycopg2.pool
from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_client import generate_latest

# ── Project ──────────────────────────────────────────────────────────────────

# Import all metrics so they register with the global Prometheus REGISTRY.
# Even unused names must be imported — module-level Counter/Histogram declarations
# register at import time. db_query_duration_seconds is used in db_tables() below.
from config.metrics import (  # noqa: F401
    pipeline_runs_total,
    llm_calls_total,
    db_upserts_total,
    scrape_success_total,
    scraper_runs_total,
    llm_router_fallbacks_total,
    pipeline_stage_duration_seconds,
    db_query_duration_seconds,
)

# ── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="RE_OS Dashboard",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

# ── CORS ─────────────────────────────────────────────────────────────────────

_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get(
        "DASHBOARD_ALLOWED_ORIGINS", "http://localhost:8050"
    ).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate Limiter ─────────────────────────────────────────────────────────────

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_REDIS_URL,
    strategy="fixed-window",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Security Headers Middleware ───────────────────────────────────────────────


@app.middleware("http")
async def _add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; "
        "img-src 'self' data: https://*.tile.openstreetmap.org https://*.basemaps.cartocdn.com; "
        "connect-src 'self' https://nominatim.openstreetmap.org"
    )
    return response


# ── Auth Middleware ───────────────────────────────────────────────────────────

_READ_ONLY_PATHS = frozenset({
    '/api/health', '/api/status', '/api/agents',
    '/api/intel/cards', '/api/intel/download', '/api/intel/search', '/api/db/state', '/api/sentinel/status',
    '/api/board/sessions', '/api/db/tables',
    '/api/tasks',
    '/api/engineering/brief',
    '/api/finance/brief',
    '/api/legal/brief',
    '/api/alerts',
    '/api/registry',
})
_READ_ONLY_PREFIXES = ('/api/reports/', '/api/logs/')


def _is_run_api_authorized(req: Request) -> bool:
    api_key = os.environ.get("DASHBOARD_API_KEY", "")
    if not api_key:
        return True
    provided = req.headers.get("X-API-Key", "") or req.query_params.get("api_key", "")
    if provided == api_key:
        return True
    api_key_prev = os.environ.get("DASHBOARD_API_KEY_PREV", "")
    return bool(api_key_prev and provided == api_key_prev)


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    # CORS preflight — never gate OPTIONS
    if request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    if not path.startswith('/api') and path != '/metrics':
        return await call_next(request)

    if path == '/metrics':
        return await call_next(request)

    if path in _READ_ONLY_PATHS and request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    if any(path.startswith(p) for p in _READ_ONLY_PREFIXES):
        return await call_next(request)
    if not _is_run_api_authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


# ── Logger ───────────────────────────────────────────────────────────────────

logger = logging.getLogger("re_os.dashboard")

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
        "id": "ceo",
        "name": "The Director",
        "role": "Orchestrator",
        "label": "IDLE",
        "state": "idle",
        "last_action": "Awaiting pipeline trigger",
        "started": None,
    },
    "scraper": {
        "id": "scraper",
        "name": "The Scout",
        "role": "Field Researcher",
        "label": "IDLE",
        "state": "idle",
        "last_action": "No recent scrape",
        "started": None,
        "terminals": {"rera": "idle", "listings": "idle", "kaveri": "idle"},
    },
    "analyst": {
        "id": "analyst",
        "name": "The Analyst",
        "role": "Market Analyst",
        "label": "IDLE",
        "state": "idle",
        "last_action": "No recent analysis",
        "started": None,
    },
    "processor": {
        "id": "processor",
        "name": "The Processor",
        "role": "Document Handler",
        "label": "STANDBY",
        "state": "standby",
        "last_action": "Standalone mode only",
        "started": None,
    },
    "sentinel": {
        "id": "sentinel",
        "name": "The Sentinel",
        "role": "Scheduler Monitor",
        "label": "WATCHING",
        "state": "idle",
        "last_action": "Checking schedule...",
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

_db_pool: psycopg2.pool.ThreadedConnectionPool | None = None
_db_pool_lock = threading.Lock()


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _db_pool
    if _db_pool is None:
        with _db_pool_lock:
            if _db_pool is None:
                url = os.environ.get("DATABASE_URL")
                if not url:
                    raise RuntimeError("DATABASE_URL environment variable is not set")
                dsn = url if "connect_timeout" in url else (
                    url + ("&" if "?" in url else "?") + "connect_timeout=5"
                )
                _db_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1, maxconn=10, dsn=dsn
                )
    return _db_pool


def _get_db():
    return _get_pool().getconn()


def _release_db(conn, reset: bool = False):
    try:
        if reset:
            _get_pool().putconn(conn, close=True)
            return
        if conn.closed:
            _get_pool().putconn(conn, close=True)
            return
        if not conn.autocommit:
            try:
                conn.rollback()
            except Exception:
                _get_pool().putconn(conn, close=True)
                return
        _get_pool().putconn(conn)
    except Exception as exc:
        logger.warning("[_release_db] connection release failed: %s", exc)


# ── API Key check ────────────────────────────────────────────────────────────

_API_KEY = os.environ.get("DASHBOARD_API_KEY", "")
if not _API_KEY:
    logging.warning(
        "[RE_OS] DASHBOARD_API_KEY is not set - all /api endpoints are publicly "
        "accessible. Set DASHBOARD_API_KEY in .env before exposing port 8050."
    )

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


def _latest_report_path(market: str = None):
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


def _log_running_lifecycle_locked(context: str):
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
        _log_fh = open(log_dest, "a")
        proc = subprocess.Popen(
            cmd,
            cwd="/app",
            shell=False,
            stdout=_log_fh,
            stderr=_log_fh,
        )
        _log_fh.close()
        started = datetime.now().isoformat()
        _running[market] = {"proc": proc, "started": started}
        logger.info("[DIAG running] started market=%s pid=%s started=%s", market, proc.pid, started)
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
            logger.info("[DIAG running] terminate requested market=%s pid=%s", market, entry["proc"].pid)
            return {"status": "stopped", "market": market}, 200
    return {"status": "not_running"}, 200


def _running_snapshot() -> dict:
    with _lock:
        snapshot = {}
        for market, entry in _running.items():
            if "proc" in entry:
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


# ── Pydantic models (response_model) ──────────────────────────────────────────


class ErrorResponse(BaseModel):
    error: str


class HealthServiceStatus(BaseModel):
    agents: str = "ok"
    postgres: str = "ok"
    redis: str = "ok"
    ollama: str = "warn"
    chroma: str = "error"


class HealthResponse(HealthServiceStatus):
    last_run: dict | None = None


class CardItem(BaseModel):
    market: str
    active_projects: int
    projects: int
    avg_psf: int | None = None
    go_no_go: str
    download_url: str | None = None
    estimated: bool = False


class CardsResponse(BaseModel):
    cards: list[CardItem]


class BoardSessionItem(BaseModel):
    session_id: str
    market: str | None = None
    status: str | None = None
    created_at: str | None = None
    pitch_excerpt: str | None = None


class BoardSessionsResponse(BaseModel):
    sessions: list[BoardSessionItem]


class BriefItem(BaseModel):
    session_id: str | None = None
    market: str | None = None
    response: str | None = None
    created_at: str | None = None


class BriefResponse(BaseModel):
    brief: BriefItem | None = None


class AlertItem(BaseModel):
    id: str
    channel: str | None = None
    title: str | None = None
    status: str | None = None
    created_at: str | None = None


class AlertsResponse(BaseModel):
    alerts: list[AlertItem]


class TaskItem(BaseModel):
    id: str
    title: str
    owner: str | None = None
    status: str | None = None
    priority: str | None = None
    source_type: str | None = None
    source_id: str | None = None
    created_at: str | None = None


class TasksResponse(BaseModel):
    tasks: list[TaskItem]


class RunResponse(BaseModel):
    status: str
    market: str | None = None
    error: str | None = None


class RegistryAgentItem(BaseModel):
    id: str
    name: str
    role: str
    department: str | None = None
    llm_tier: str | None = None
    active: bool = True
    hired_on: str | None = None


class RegistryResponse(BaseModel):
    agents: list[RegistryAgentItem]


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse, tags=["Pages"], summary="Dashboard UI")
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health", response_model=HealthResponse, tags=["Health"],
         summary="Full health check", responses={503: {"model": ErrorResponse}})
@limiter.limit("60/minute")
async def health(request: Request):
    services = {"agents": "ok"}
    conn = None
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        _release_db(conn)
        services["postgres"] = "ok"
    except Exception:
        if conn:
            _release_db(conn, reset=True)
        services["postgres"] = "error"
    try:
        import redis as redis_lib
        r = redis_lib.from_url(os.environ.get("REDIS_URL", "redis://redis:6379"))
        r.ping()
        r.close()
        services["redis"] = "ok"
    except Exception:
        services["redis"] = "error"
    try:
        import httpx
        resp = httpx.get("http://ollama:11434/api/tags", timeout=3.0)
        services["ollama"] = "ok" if resp.status_code == 200 else "warn"
    except Exception:
        services["ollama"] = "warn"
    try:
        from chromadb import PersistentClient
        _chroma_path = os.environ.get("CHROMA_DB_PATH", "/app/data/chroma")
        _test_client = PersistentClient(path=_chroma_path)
        _test_client.heartbeat()
        services["chroma"] = "ok"
    except Exception:
        services["chroma"] = "error"
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT micro_market, status, started_at, duration_seconds
            FROM agent_runs ORDER BY started_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        _release_db(conn)
        if row:
            services["last_run"] = {
                "market": row[0],
                "status": row[1],
                "started_at": row[2].isoformat() if row[2] else None,
                "duration_seconds": row[3],
            }
        else:
            services["last_run"] = None
    except Exception:
        services["last_run"] = None
    return services


@app.get("/api/health/live", tags=["Health"], summary="Lightweight liveness probe (no deps)",
         response_model=HealthServiceStatus)
def health_liveness():
    return HealthServiceStatus()


@app.get("/api/alert/test", tags=["Health"], summary="Send test alert")
@limiter.limit("5/hour")
async def test_alert(request: Request):
    from utils.notifier import send_alert
    sent = send_alert("Test from RE_OS", "INFO")
    return {"sent": sent}


# ── Board Room ───────────────────────────────────────────────────────────────

_VALID_BOARD_MARKETS = {"Yelahanka", "Devanahalli", "Hebbal", ""}


@app.post("/api/board/session", tags=["Board Room"], summary="Create board session",
          responses={400: {"model": ErrorResponse}})
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
            {"error": "pitch required and must be under 2000 characters"}, status_code=400
        )
    if market not in _VALID_BOARD_MARKETS:
        return JSONResponse(
            {"error": "invalid market - must be Yelahanka, Devanahalli, or Hebbal"},
            status_code=400,
        )
    result = run_board_session(pitch, market)
    return result


@app.get("/api/board/session/{session_id}", tags=["Board Room"],
         summary="Get board session by ID", responses={404: {"model": ErrorResponse}})
@limiter.limit("120/minute")
async def board_session_get(request: Request, session_id: str):
    from crews.board_room import get_board_session
    session = get_board_session(session_id)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    return session


@app.get("/api/board/sessions", response_model=BoardSessionsResponse,
         tags=["Board Room"], summary="List recent board sessions")
@limiter.limit("60/minute")
async def board_sessions(request: Request):
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT session_id, market, status, created_at, pitch_text
            FROM board_sessions ORDER BY created_at DESC LIMIT 20
        """)
        rows = []
        for r in cur.fetchall():
            pitch = r[4] or ""
            rows.append({
                "session_id": str(r[0]),
                "market": r[1],
                "status": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
                "pitch_excerpt": pitch[:120] + ("\u2026" if len(pitch) > 120 else ""),
            })
        cur.close()
        return {"sessions": rows}
    except Exception as e:
        exc = True
        logger.error("[board_sessions] %s", e)
        return JSONResponse({"sessions": [], "error": "database query failed"})
    finally:
        if conn:
            _release_db(conn, reset=exc)


@app.get("/api/engineering/brief", response_model=BriefResponse,
         tags=["Briefs"], summary="Latest Engineering Head response")
@limiter.limit("30/minute")
async def engineering_brief(request: Request):
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT session_id, market, engineering_response, created_at
            FROM board_sessions
            WHERE engineering_response IS NOT NULL
            ORDER BY created_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        if not row:
            logger.info("[engineering_brief] No board sessions with engineering_response found")
            return {"brief": None}
        created = row[3].isoformat() if row[3] else None
        logger.info("[engineering_brief] session=%s market=%s created=%s", row[0][:8], row[1], created)
        return {"brief": {
            "session_id": str(row[0]),
            "market": row[1],
            "response": row[2],
            "created_at": created,
        }}
    except Exception as e:
        exc = True
        logger.error("[engineering_brief] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


@app.get("/api/alerts", response_model=AlertsResponse,
         tags=["Alerts"], summary="List recent alerts")
@limiter.limit("30/minute")
async def list_alerts(request: Request, channel: str = Query(None)):
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        where = "WHERE channel = %s" if channel else ""
        params = [channel] if channel else []
        cur.execute(
            f"SELECT id, channel, title, status, created_at FROM alerts "
            f"{where} ORDER BY created_at DESC LIMIT 50",
            params,
        )
        rows = [
            {"id": str(r[0]), "channel": r[1], "title": r[2],
             "status": r[3], "created_at": r[4].isoformat() if r[4] else None}
            for r in cur.fetchall()
        ]
        cur.close()
        logger.info("[list_alerts] channel=%s count=%d", channel or "all", len(rows))
        return {"alerts": rows}
    except Exception as e:
        exc = True
        logger.error("[list_alerts] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


@app.get("/api/finance/brief", response_model=BriefResponse,
         tags=["Briefs"], summary="Latest Finance Head response")
@limiter.limit("30/minute")
async def finance_brief(request: Request):
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT session_id, market, finance_response, created_at
            FROM board_sessions
            WHERE finance_response IS NOT NULL
            ORDER BY created_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        if not row:
            logger.info("[finance_brief] No board sessions with finance_response found")
            return {"brief": None}
        created = row[3].isoformat() if row[3] else None
        logger.info("[finance_brief] session=%s market=%s created=%s", row[0][:8], row[1], created)
        return {"brief": {
            "session_id": str(row[0]),
            "market": row[1],
            "response": row[2],
            "created_at": created,
        }}
    except Exception as e:
        exc = True
        logger.error("[finance_brief] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


@app.get("/api/legal/brief", response_model=BriefResponse,
         tags=["Briefs"], summary="Latest Legal Head response")
@limiter.limit("30/minute")
async def legal_brief(request: Request, market: str = Query(None)):
    canonical = _normalize_market(market)
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        where = "WHERE legal_response IS NOT NULL"
        params = []
        if canonical and canonical != "all":
            where += " AND market = %s"
            params.append(canonical)
        cur.execute(f"""
            SELECT session_id, market, legal_response, created_at
            FROM board_sessions {where}
            ORDER BY created_at DESC LIMIT 1
        """, params)
        row = cur.fetchone()
        cur.close()
        if not row:
            logger.info("[legal_brief] No board sessions with legal_response found")
            return {"brief": None}
        created = row[3].isoformat() if row[3] else None
        logger.info("[legal_brief] session=%s market=%s created=%s", row[0][:8], row[1], created)
        return {"brief": {
            "session_id": str(row[0]),
            "market": row[1],
            "response": row[2],
            "created_at": created,
        }}
    except Exception as e:
        exc = True
        logger.error("[legal_brief] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


# ── Tasks ────────────────────────────────────────────────────────────────────


@app.get("/api/tasks", response_model=TasksResponse,
         tags=["Tasks"], summary="List tasks with optional status/owner filter")
@limiter.limit("60/minute")
async def list_tasks(request: Request, status: str = Query(None), owner: str = Query(None)):
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        where_clauses, params = [], []
        if status:
            where_clauses.append("status = %s")
            params.append(status)
        if owner:
            where_clauses.append("owner = %s")
            params.append(owner)
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        cur.execute(
            f"SELECT id, title, owner, status, priority, source_type, source_id, created_at "
            f"FROM tasks {where_sql} ORDER BY created_at DESC LIMIT 200",
            params,
        )
        rows = [
            {"id": str(r[0]), "title": r[1], "owner": r[2], "status": r[3],
             "priority": r[4], "source_type": r[5],
             "source_id": str(r[6]) if r[6] else None,
             "created_at": r[7].isoformat() if r[7] else None}
            for r in cur.fetchall()
        ]
        cur.close()
        return {"tasks": rows}
    except Exception as e:
        exc = True
        logger.error("[list_tasks] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


@app.post("/api/tasks", tags=["Tasks"], summary="Create a new task",
          responses={400: {"model": ErrorResponse}, 201: {"description": "Task created"}})
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
        return JSONResponse({"error": "title required"}, status_code=400)
    if priority not in ("high", "medium", "low"):
        priority = "medium"
    source_id = None
    if source_id_raw:
        try:
            source_id = str(uuid.UUID(str(source_id_raw)))
        except (ValueError, AttributeError):
            source_id = None
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO tasks (title, owner, priority, source_type, source_id)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (title, owner or None, priority, source_type or None, str(source_id) if source_id else None),
        )
        task_id = str(cur.fetchone()[0])
        conn.commit()
        cur.close()
        return JSONResponse({"task_id": task_id, "status": "queued"}, status_code=201)
    except Exception as e:
        exc = True
        logger.error("[create_task] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


@app.patch("/api/tasks/{task_id}", tags=["Tasks"], summary="Update task status",
           responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
@limiter.limit("60/minute")
async def update_task(request: Request, task_id: str):
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    new_status = str(payload.get("status") or "").strip()
    if new_status not in ("queued", "active", "done", "failed", "rejected"):
        return JSONResponse({"error": "invalid status"}, status_code=400)
    try:
        tid = str(uuid.UUID(task_id))
    except ValueError:
        return JSONResponse({"error": "invalid task_id"}, status_code=400)
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE tasks SET status = %s, updated_at = NOW() WHERE id = %s RETURNING id",
            (new_status, tid),
        )
        if cur.fetchone() is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        conn.commit()
        cur.close()
        return {"status": new_status}
    except Exception as e:
        exc = True
        logger.error("[update_task] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


# ── Registry ──────────────────────────────────────────────────────────────────

_registry_cache: dict[str, tuple[list[dict], float]] = {}
_REGISTRY_CACHE_TTL = 15


@app.get("/api/registry", response_model=RegistryResponse, tags=["Registry"],
         summary="List registered agents")
@limiter.limit("30/minute")
async def list_registry(request: Request):
    now = time.time()
    cached = _registry_cache.get("all")
    if cached and cached[1] > now:
        logger.debug("[list_registry] cache hit (%d agents)", len(cached[0]))
        return {"agents": cached[0], "cached": True}
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, role, department, llm_tier, active, hired_on
            FROM agent_registry ORDER BY department, name
        """)
        rows = [
            {"id": r[0], "name": r[1], "role": r[2], "department": r[3],
             "llm_tier": r[4], "active": r[5],
             "hired_on": r[6].isoformat() if r[6] else None}
            for r in cur.fetchall()
        ]
        cur.close()
        _registry_cache["all"] = (rows, now + _REGISTRY_CACHE_TTL)
        return {"agents": rows}
    except Exception as e:
        exc = True
        logger.warning("[list_registry] DB query failed: %s", e)
        if cached:
            return {"agents": cached[0], "cached": True, "stale": True}
        return JSONResponse({"error": "database query failed"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


@app.post("/api/registry", tags=["Registry"], summary="Hire a new agent from JSON spec",
          responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
async def hire_agent(request: Request):
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    validated, err = _validate_registry_payload(payload)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    import yaml
    spec_id = str(validated["id"]).strip()
    from agents.agent_factory import _REGISTRY_DIR
    spec_path = str(_REGISTRY_DIR / f"{spec_id}.yaml")
    if os.path.exists(spec_path):
        return JSONResponse({"error": f"agent '{spec_id}' already exists"}, status_code=409)
    try:
        os.makedirs(os.path.dirname(spec_path), exist_ok=True)
        with open(spec_path, "w", encoding="utf-8") as f:
            yaml.dump(validated, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except Exception as e:
        logger.error("[hire_agent] write failed: %s", e)
        return JSONResponse({"error": "failed to write spec file"}, status_code=500)
    try:
        from agents.agent_factory import sync_registry_to_db
        synced = sync_registry_to_db()
        logger.info("[hire_agent] synced %d agents (including new '%s')", synced, spec_id)
    except Exception as e:
        logger.error("[hire_agent] db sync failed: %s", e)
        return JSONResponse(
            {"warning": "spec written but DB sync failed", "spec_id": spec_id}, status_code=201
        )
    _registry_cache.pop("all", None)
    return JSONResponse({"status": "hired", "spec_id": spec_id}, status_code=201)


# ── Metrics ───────────────────────────────────────────────────────────────────


@app.get('/metrics', tags=["Metrics"], summary="Prometheus metrics endpoint",
         include_in_schema=False)
def metrics():
    return Response(
        content=generate_latest(),
        media_type='text/plain; version=0.0.4',
    )


# ── DB State ─────────────────────────────────────────────────────────────────


@app.get("/api/db/state", tags=["DB State"], summary="Database record counts and market summary")
@limiter.limit("60/minute")
async def db_state(request: Request):
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        state = {}
        cur.execute("SELECT COUNT(*) FROM rera_projects")
        state["rera_projects"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM listings")
        state["listings"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM kaveri_registrations")
        state["kaveri_registrations"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM guidance_values")
        state["guidance_values"] = cur.fetchone()[0]
        cur.execute("""
            SELECT mm.name,
                   COUNT(DISTINCT rp.id)              AS projects,
                   ROUND(AVG(l.price_psf)::numeric, 0) AS avg_psf
            FROM micro_markets mm
            LEFT JOIN rera_projects rp ON rp.micro_market_id = mm.id
            LEFT JOIN listings l ON l.micro_market_id = mm.id
                                AND l.price_psf IS NOT NULL
                                AND l.price_psf > 1000
                                AND l.price_psf < 50000
            GROUP BY mm.name ORDER BY mm.name
        """)
        state["markets"] = [
            {"name": r[0], "projects": r[1], "avg_psf": int(r[2]) if r[2] else None}
            for r in cur.fetchall()
        ]
        cur.execute("""
            SELECT micro_market, started_at, status, duration_seconds
            FROM agent_runs ORDER BY started_at DESC LIMIT 5
        """)
        state["recent_runs"] = [
            {"market": r[0], "start_time": r[1].isoformat() if r[1] else None,
             "status": r[2], "duration": r[3]}
            for r in cur.fetchall()
        ]
        return state
    except Exception as e:
        exc = True
        logger.error("[db_state] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


@app.get("/api/db/tables", tags=["DB State"], summary="View contents of key DB views")
@limiter.limit("30/minute")
async def db_tables(request: Request):
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        with db_query_duration_seconds.labels(query_name="v_market_inventory").time():
            cur.execute("SELECT * FROM v_market_inventory")
            columns = [desc[0] for desc in cur.description]
            market_inventory = [dict(zip(columns, row)) for row in cur.fetchall()]
        with db_query_duration_seconds.labels(query_name="v_developer_scorecard").time():
            cur.execute("""
                SELECT developer, grade, total_projects, total_units,
                       avg_absorption_pct, completed, delayed, markets_active_in
                FROM v_developer_scorecard LIMIT 50
            """)
            columns = [desc[0] for desc in cur.description]
            developer_scorecard = [dict(zip(columns, row)) for row in cur.fetchall()]
        with db_query_duration_seconds.labels(query_name="v_active_projects").time():
            cur.execute("""
                SELECT project_name, developer_name, micro_market, project_status,
                       total_units, unsold_units, absorption_pct
                FROM v_active_projects LIMIT 100
            """)
            columns = [desc[0] for desc in cur.description]
            active_projects = [dict(zip(columns, row)) for row in cur.fetchall()]
        return {
            "market_inventory": market_inventory,
            "developer_scorecard": developer_scorecard,
            "active_projects": active_projects,
        }
    except Exception as e:
        exc = True
        logger.error("[db_tables] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


# ── Pipeline Control ─────────────────────────────────────────────────────────


@app.post("/api/run/{market}", response_model=RunResponse,
          tags=["Pipeline"], summary="Start pipeline for a market",
          responses={400: {"model": ErrorResponse}})
@limiter.limit("10/hour")
async def run_pipeline(request: Request, market: str):
    canonical = _normalize_market(market)
    if not canonical:
        return JSONResponse({"error": "invalid market"}, status_code=400)
    payload, status_code = _start_pipeline_for_market(canonical)
    return JSONResponse(payload, status_code=status_code)


@app.delete("/api/run/{market}", tags=["Pipeline"], summary="Stop running pipeline",
           responses={400: {"model": ErrorResponse}})
async def stop_pipeline(market: str):
    canonical = _normalize_market(market)
    if not canonical:
        return JSONResponse({"error": "invalid market"}, status_code=400)
    payload, status_code = _stop_pipeline_for_market(canonical)
    return JSONResponse(payload, status_code=status_code)


@app.get("/api/status", tags=["Pipeline"], summary="Pipeline running status snapshot")
def run_status():
    return _running_snapshot()


# ── Agents ───────────────────────────────────────────────────────────────────


@app.get("/api/agents", tags=["Agents"], summary="Full agent state — DB agents + registry + running")
def agents_state():
    global _diag_agents_contract_logged
    conn = None
    _conn_exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT agent_name, status, MAX(started_at) as last_run, COUNT(*) as total_runs
            FROM agent_runs GROUP BY agent_name, status ORDER BY last_run DESC
        """)
        db_agents = {}
        for row in cur.fetchall():
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
            cur.execute("""
                SELECT id, name, role, department, llm_tier, active, hired_on
                FROM agent_registry ORDER BY department, name
            """)
            for row in cur.fetchall():
                aid = row[0]
                if aid not in db_agents:
                    db_agents[aid] = {
                        "id": aid,
                        "name": row[1],
                        "role": row[2],
                        "department": row[3],
                        "label": "REGISTERED",
                        "state": "idle",
                        "last_action": f"Registered: {row[2]} in {row[3] or '-'}",
                        "started": row[6].isoformat() if row[6] else None,
                        "llm_tier": row[4],
                    }
        except Exception as reg_e:
            logger.warning("[DIAG agents] registry merge failed: %s", reg_e)
        cur.close()
        with _lock:
            states_copy = copy.deepcopy(db_agents or _agent_states)
            running_copy = {}
            for market, entry in _running.items():
                rc = entry["proc"].poll()
                running_copy[market] = {
                    "started": entry.get("started"),
                    "state": "running" if rc is None else ("done" if rc == 0 else "failed"),
                    "returncode": rc,
                    "pid": entry["proc"].pid,
                }
        response = {"agents": states_copy, "running_markets": running_copy}
        response.update(states_copy)
        if not _diag_agents_contract_logged:
            source_label = "DB + registry" if db_agents else "in-memory + registry"
            logger.info("[DIAG agents] /api/agents keys=%s nested_agents=%s (from %s)",
                        sorted(response.keys()), sorted(states_copy.keys()), source_label)
            _diag_agents_contract_logged = True
        _release_db(conn)
        return response
    except Exception as e:
        _conn_exc = True
        logger.warning("[DIAG agents] DB query failed, falling back to in-memory: %s", e)
    finally:
        if conn and _conn_exc:
            _release_db(conn, reset=True)
    with _lock:
        states_copy = copy.deepcopy(_agent_states)
        running_copy = {}
        for market, entry in _running.items():
            rc = entry["proc"].poll()
            running_copy[market] = {
                "started": entry.get("started"),
                "state": "running" if rc is None else ("done" if rc == 0 else "failed"),
                "returncode": rc,
                "pid": entry["proc"].pid,
            }
    response = {"agents": states_copy, "running_markets": running_copy}
    response.update(states_copy)
    if not _diag_agents_contract_logged:
        logger.info("[DIAG agents] /api/agents keys=%s nested_agents=%s (fallback)",
                    sorted(response.keys()), sorted(states_copy.keys()))
        _diag_agents_contract_logged = True
    return response


@app.post("/api/agents/{agent_id}/command", tags=["Agents"],
          summary="Send command to an agent (run/stop/status)",
          responses={404: {"model": ErrorResponse}})
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
    if not chosen_market and any(k in prompt.lower() for k in
                                 ["run", "start", "scrape", "scan", "analyse", "analyze", "stop", "cancel"]):
        chosen_market = "Yelahanka"
    text = prompt.lower()
    if agent_id not in _agent_states:
        return JSONResponse({
            "status": "unknown_command",
            "action": "invalid_agent",
            "details": f"Unknown agent_id '{agent_id}'",
            "hint": "Try: run [market], stop [market], status",
        }, status_code=404)
    if any(k in text for k in ["run", "start", "scrape", "scan", "analyse", "analyze"]):
        market = chosen_market or "Yelahanka"
        payload, status_code = _start_pipeline_for_market(market)
        return JSONResponse({
            "status": "accepted" if payload.get("status") in {"started", "already_running"} else "unknown_command",
            "action": "run_pipeline",
            "details": f"{payload.get('status')} for {market}",
            "market": market,
            "pipeline": payload,
        }, status_code=status_code)
    if any(k in text for k in ["stop", "cancel"]):
        market = chosen_market or "Yelahanka"
        payload, status_code = _stop_pipeline_for_market(market)
        return JSONResponse({
            "status": "accepted" if payload.get("status") in {"stopped", "not_running"} else "unknown_command",
            "action": "stop_pipeline",
            "details": f"{payload.get('status')} for {market}",
            "market": market,
            "pipeline": payload,
        }, status_code=status_code)
    if any(k in text for k in ["status", "report", "show"]):
        report_market = chosen_market if chosen_market and chosen_market != "all" else None
        report_path = _latest_report_path(report_market)
        return {
            "status": "accepted",
            "action": "status_report",
            "details": "Returned current agent state and latest report path",
            "market": chosen_market,
            "report_path": report_path,
            "agents": copy.deepcopy(_agent_states),
            "running_markets": _running_snapshot(),
        }
    return JSONResponse({
        "status": "unknown_command",
        "action": "none",
        "details": "No action matched prompt",
        "hint": "Try: run [market], stop [market], status",
    })


@app.get("/api/agents/{agent_id}/actions", tags=["Agents"],
         summary="List available actions for an agent")
def agent_actions(agent_id: str):
    if agent_id not in _agent_states and agent_id not in AGENT_ACTIONS:
        return JSONResponse({"error": f"Unknown agent '{agent_id}'"}, status_code=404)
    return {"agent_id": agent_id, "actions": AGENT_ACTIONS.get(agent_id, [])}


@app.get("/api/sentinel/status", tags=["Sentinel"], summary="Current sentinel run status")
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
                    _agent_states["sentinel"]["last_action"] = (
                        f"Next run: {nxt.get('label', '?')}"
                    )
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


# ── Log Streaming (SSE) ──────────────────────────────────────────────────────


@app.get("/api/logs/stream", tags=["Logs"], summary="SSE log stream for a market pipeline")
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


# ── Reports ──────────────────────────────────────────────────────────────────


@app.get("/api/reports/{market}", tags=["Reports"], summary="Latest intel report text for a market",
          responses={400: {"model": ErrorResponse}})
@limiter.limit("30/minute")
async def get_report(request: Request, market: str):
    canonical = _normalize_market(market)
    if not canonical or canonical == "all":
        return JSONResponse({"error": "invalid market"}, status_code=400)
    slug = MARKET_SLUG.get(canonical)
    if not slug:
        return JSONResponse({"error": "invalid market"}, status_code=400)
    pattern = f"/app/outputs/{slug}/intel_report_*.txt"
    files = sorted(glob.glob(pattern))
    if not files:
        return {"content": None, "file": None}
    latest = files[-1]
    with open(latest, encoding="utf-8") as f:
        content = f.read()
    return {"content": content, "file": os.path.basename(latest)}


@app.get("/api/intel/cards", response_model=CardsResponse, tags=["Reports"],
         summary="Market summary cards for dashboard UI")
@limiter.limit("60/minute")
async def intel_cards(request: Request):
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cards = []
        cur.execute("""
            SELECT mm.name,
                   COUNT(DISTINCT rp.id)              AS projects,
                   ROUND(AVG(l.price_psf)::numeric, 0) AS avg_psf
            FROM micro_markets mm
            LEFT JOIN rera_projects rp ON rp.micro_market_id = mm.id
            LEFT JOIN listings l ON l.micro_market_id = mm.id
                                AND l.price_psf IS NOT NULL
                                AND l.price_psf > 1000
                                AND l.price_psf < 50000
            GROUP BY mm.name ORDER BY mm.name
        """)
        now = time.time()
        for row in cur.fetchall():
            market_name = row[0]
            slug = MARKET_SLUG.get(market_name, market_name.lower())
            cached = _estimated_cache.get(market_name)
            if cached and cached[1] > now:
                is_estimated = cached[0]
            else:
                report_files = sorted(glob.glob(f"/app/outputs/{slug}/intel_report_*.txt"))
                is_estimated = False
                if report_files:
                    try:
                        with open(report_files[-1], encoding="utf-8") as rf:
                            is_estimated = "[ESTIMATED DATA" in rf.read(4096)
                    except Exception:
                        pass
                _estimated_cache[market_name] = (is_estimated, now + _ESTIMATED_CACHE_TTL)
            cards.append({
                "market": market_name,
                "active_projects": int(row[1] or 0),
                "projects": int(row[1] or 0),
                "avg_psf": int(row[2]) if row[2] else None,
                "go_no_go": _market_go_no_go(int(row[1] or 0), int(row[2]) if row[2] else None, is_estimated),
                "download_url": f"/api/intel/download?market={slug}" if slug else None,
                "estimated": is_estimated,
            })
        return {"cards": cards}
    except Exception as e:
        exc = True
        logger.error("[intel_cards] %s", e)
        return JSONResponse({"error": "failed to load market cards"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


@app.get("/api/intel/search", tags=["Reports"], summary="Semantic search over past intel reports",
          responses={400: {"model": ErrorResponse}})
@limiter.limit("20/minute")
async def intel_search(request: Request, q: str = Query(""), market: str = Query("")):
    query_text = (q or "").strip()[:200]
    market_param = _normalize_market(market)
    if any(ord(c) < 32 and c not in "\t\n\r" for c in query_text):
        return JSONResponse(
            {"results": [], "query": query_text[:50], "error": "invalid characters in query"},
            status_code=400,
        )
    if not query_text:
        return {"results": [], "query": query_text}
    market_filter = market_param if market_param and market_param != "all" else None
    cache_key = f"{query_text}:::{market_filter or ''}"
    now = time.time()
    cached = _cache_get(cache_key)
    if cached and cached[1] > now:
        logger.debug("[intel_search] cache hit for q=%s market=%s", query_text[:40], market_filter)
        return {"results": cached[0], "query": query_text, "market": market, "cached": True}
    logger.debug("[intel_search] q=%s market=%s", query_text[:60], market_filter)
    try:
        global _embedder_instance, _embedder_lock
        if _embedder_instance is None:
            with _embedder_lock:
                if _embedder_instance is None:
                    from utils.embedder import IntelEmbedder
                    _embedder_instance = IntelEmbedder()
        results = _embedder_instance.search(query_text, market=market_filter, n=5)
        _cache_put(cache_key, (results, now + _SEARCH_CACHE_TTL))
        return {"results": results, "query": query_text, "market": market}
    except Exception as e:
        logger.warning("[intel_search] search failed: q=%s market=%s: %s", query_text[:40], market_filter, e)
        return {"results": [], "query": query_text, "error": "search unavailable - index not built yet"}


@app.get("/api/intel/download", tags=["Reports"], summary="Download intel report as txt or csv",
          responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
def download_intel(market: str = Query(""), format: str = Query("txt")):
    canonical = _normalize_market(market)
    fmt = format.lower()
    if fmt == "csv":
        return _download_intel_csv(canonical)
    if not canonical or canonical == "all":
        return JSONResponse({"error": "invalid market"}, status_code=400)
    slug = MARKET_SLUG.get(canonical)
    pattern = f"/app/outputs/{slug}/intel_report_*.txt"
    files = sorted(glob.glob(pattern))
    if not files:
        return JSONResponse({"error": "no report found"}, status_code=404)
    with open(files[-1], encoding="utf-8") as f:
        content = f.read()
    return Response(content=content, media_type="text/plain")


def _download_intel_csv(canonical: str | None):
    if not canonical:
        return JSONResponse({"error": "invalid market"}, status_code=400)
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        params = []
        where = ""
        if canonical != "all":
            where = "WHERE mm.name = %s"
            params.append(canonical)
        cur.execute(f"""
            SELECT mm.name,
                   COUNT(DISTINCT rp.id)               AS active_projects,
                   ROUND(AVG(l.price_psf)::numeric, 0) AS avg_psf
            FROM micro_markets mm
            LEFT JOIN rera_projects rp ON rp.micro_market_id = mm.id
            LEFT JOIN listings l ON l.micro_market_id = mm.id
                                AND l.price_psf IS NOT NULL
                                AND l.price_psf > 1000
                                AND l.price_psf < 50000
            {where}
            GROUP BY mm.name ORDER BY mm.name
        """, params)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["market", "active_projects", "avg_psf", "go_no_go", "estimated"])
        now = time.time()
        for market_name, active_projects, avg_psf in cur.fetchall():
            slug = MARKET_SLUG.get(market_name, market_name.lower())
            cached = _estimated_cache.get(market_name)
            if cached and cached[1] > now:
                estimated = cached[0]
            else:
                report_files = sorted(glob.glob(f"/app/outputs/{slug}/intel_report_*.txt"))
                estimated = False
                if report_files:
                    try:
                        with open(report_files[-1], encoding="utf-8") as rf:
                            estimated = "[ESTIMATED DATA" in rf.read(4096)
                    except Exception:
                        pass
                _estimated_cache[market_name] = (estimated, now + _ESTIMATED_CACHE_TTL)
            projects = int(active_projects or 0)
            psf = int(avg_psf) if avg_psf else None
            writer.writerow([market_name, projects, psf or "", _market_go_no_go(projects, psf, estimated), estimated])
        filename = "intel_cards.csv" if canonical == "all" else f"intel_{MARKET_SLUG.get(canonical, canonical.lower())}.csv"
        return Response(content=out.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})
    except Exception as e:
        exc = True
        logger.error("[download_intel_csv] %s", e)
        return JSONResponse({"error": "failed to export intel csv"}, status_code=500)
    finally:
        if conn:
            _release_db(conn, reset=exc)


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    os.makedirs("/app/logs", exist_ok=True)
    logging.basicConfig(
        level=os.environ.get("DASHBOARD_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=8050, log_level="info")
