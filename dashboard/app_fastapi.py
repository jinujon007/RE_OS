"""
RE_OS Dashboard — FastAPI web server (v2)

Flask → FastAPI migration (T-727–T-730, T-828–T-829, T-900). 50+ routes with exact API
contract: same paths, same response shapes, same auth/rate-limit/security-headers
behavior. Auto-generated OpenAPI docs at /docs and /redoc.
Foundation Hardening (T-904–T-924): backup, deals, surveys, LLM quota, data freshness.

Architecture:
  - FastAPI app with CORS middleware, rate limiting (slowapi/Redis), Prometheus
    /metrics endpoint, SSE log streaming, and security headers.
  - Auth: middleware-based API key gate (X-API-Key header only — query param
    removed to prevent key exposure in server access logs),
    with read-only path exemptions and DASHBOARD_API_KEY_PREV rotation support.
   - DB: SQLAlchemy engine from utils.db.get_engine() (pool_size=10, max_overflow=5).
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
  | DB pool exhaustion          | SQLAlchemy pool_size=10, max_overflow=5     |
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

from fastapi import FastAPI, Request, Response, Query
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_client import generate_latest
from sqlalchemy import text as _sa_text

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
    digest_runs_total,
)
from utils.discord_notifier import _CHANNEL_ENV_MAP

# ── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="RE_OS Dashboard",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

# ── CORS ─────────────────────────────────────────────────────────────────────

_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "http://localhost:8050").split(
        ","
    )
    if o.strip()
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

_READ_ONLY_PATHS = frozenset(
    {
        "/api/health",
        "/api/status",
        "/api/agents",
        "/api/intel/cards",
        "/api/intel/download",
        "/api/intel/search",
        "/api/db/state",
        "/api/sentinel/status",
        "/api/board/sessions",
        "/api/db/tables",
        "/api/tasks",
        "/api/engineering/brief",
        "/api/finance/brief",
        "/api/legal/brief",
        "/api/alerts",
        "/api/registry",
        "/api/opportunity/queue",
        "/api/health/backup",
        "/api/scheduler/health",
        "/api/competitive/pulse",
        "/api/portfolio",
        "/api/portfolio/summary",
        "/api/pr/mentions",
        "/api/optimizer/report",
        "/api/digest/weekly",
        "/api/digest/monthly",
        "/optimizer",
    }
)
_READ_ONLY_PREFIXES = (
    "/api/reports/",
    "/api/logs/",
    "/api/market/",
    "/api/evaluate/",
    "/api/data/",
    "/api/memory/",
    "/api/demand/",
    "/api/distress/",
    "/api/scraper/",
)


def _is_run_api_authorized(req: Request) -> bool:
    api_key = os.environ.get("DASHBOARD_API_KEY", "")
    if not api_key:
        return True
    provided = req.headers.get("X-API-Key", "")
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
    if not path.startswith("/api") and path != "/metrics":
        return await call_next(request)

    if path == "/metrics":
        return await call_next(request)

    if path in _READ_ONLY_PATHS and request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    if any(path.startswith(p) for p in _READ_ONLY_PREFIXES):
        return await call_next(request)
    # Telegram webhook uses its own secret-token validation — exempt from API key
    if path == "/api/telegram/webhook":
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

from utils.db import get_engine as _get_sa_engine

# ── API Key check ────────────────────────────────────────────────────────────

_API_KEY = os.environ.get("DASHBOARD_API_KEY", "")
if not _API_KEY:
    _allow_empty = os.environ.get("DASHBOARD_API_KEY_ALLOW_EMPTY", "").lower() in ("1", "true", "yes")
    if _allow_empty:
        logging.warning(
            "[RE_OS] DASHBOARD_API_KEY is not set — DASHBOARD_API_KEY_ALLOW_EMPTY=true "
            "overrides the hard error. Port 8050 is publicly accessible."
        )
    else:
        raise RuntimeError(
            "DASHBOARD_API_KEY is not set. All /api endpoints would be publicly accessible. "
            "Set DASHBOARD_API_KEY in .env, or set DASHBOARD_API_KEY_ALLOW_EMPTY=true to "
            "explicitly permit unauthenticated access (e.g. local dev only)."
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
        with open(log_dest, "a") as _log_fh:
            proc = subprocess.Popen(
                cmd,
                cwd="/app",
                shell=False,
                stdout=_log_fh,
                stderr=_log_fh,
            )
        started = datetime.now().isoformat()
        _running[market] = {"proc": proc, "started": started}
        logger.info(
            "[DIAG running] started market=%s pid=%s started=%s",
            market,
            proc.pid,
            started,
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
                market,
                entry["proc"].pid,
            )
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
                    "state": "running"
                    if rc is None
                    else ("done" if rc == 0 else "failed"),
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
        return (
            None,
            "invalid id - must start with lowercase letter, contain only [a-z0-9_-]",
        )
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
        return (
            None,
            f"field 'max_iter' must be an integer, got {type(max_iter).__name__}",
        )
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


class DataQualityHealth(BaseModel):
    slo_pass: int = 0
    slo_fail: int = 0
    freshness: dict | None = None
    seed_stale_warnings: list[dict] = []


class HealthResponse(HealthServiceStatus):
    last_run: dict | None = None
    data_quality: DataQualityHealth | None = None
    llm: dict | None = None


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


class FreshnessItem(BaseModel):
    source: str
    plugin_id: str | None = None
    market: str
    last_scraped_at: str | None = None
    record_count: int = 0
    freshness_score: float = 0.0
    label: str = "STALE"
    is_stale: bool = True


class FreshnessResponse(BaseModel):
    freshness: list[FreshnessItem]


class MemoryItem(BaseModel):
    id: str
    agent_id: str
    market: str
    fact: str
    fact_truncated: bool = False
    confidence: float = 0.0
    source_count: int = 0
    last_updated: str | None = None
    created_at: str | None = None


class MemoryExplorerResponse(BaseModel):
    total: int
    page: int
    per_page: int
    memories: list[MemoryItem]


class ConflictCountResponse(BaseModel):
    unresolved_conflicts: int


class BackupHealthResponse(BaseModel):
    last_backup: str | None = None
    status: str


class ProvenanceMarketInfo(BaseModel):
    total: int
    live: int
    seed: int
    manual: int = 0
    live_pct: float
    guidance: str = ""


class ScraperReliabilityInfo(BaseModel):
    scraper: str
    runs: int
    successes: int
    reliability_score: float
    last_run: str | None = None


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse, tags=["Pages"], summary="Dashboard UI")
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get(
    "/api/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Full health check",
    responses={503: {"model": ErrorResponse}},
)
@limiter.limit("60/minute")
async def health(request: Request):
    services = {"agents": "ok"}
    try:
        with _get_sa_engine().connect() as conn:
            conn.execute(_sa_text("SELECT 1"))
        services["postgres"] = "ok"
    except Exception:
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
        with _get_sa_engine().connect() as conn:
            row = conn.execute(
                _sa_text("""
                SELECT micro_market, status, started_at, duration_seconds
                FROM agent_runs ORDER BY started_at DESC LIMIT 1
            """)
            ).fetchone()
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
    discord_status = {}
    for channel, env_key in _CHANNEL_ENV_MAP.items():
        discord_status[channel] = bool(os.environ.get(env_key, "").strip())
    general_webhook = bool(os.environ.get("DISCORD_WEBHOOK_URL", "").strip())
    channels_missing = [
        ch
        for ch, configured in discord_status.items()
        if not configured and not general_webhook
    ]
    services["discord"] = {
        "configured": general_webhook or any(discord_status.values()),
        "general_webhook": general_webhook,
        "channels_missing": channels_missing,
    }

    try:
        from utils.data_quality import DataQualityMonitor
        from config.slos import all_slo_status
        freshness = DataQualityMonitor.freshness_score()
        slo_result = all_slo_status(freshness)
        seed_stale = DataQualityMonitor.check_seed_staleness()
        locality_scores = {}
        try:
            from config.locality_aliases import KNOWN_ALIEN_LOCALITIES
            from config.settings import TARGET_MARKETS
            for m in TARGET_MARKETS:
                locality_scores[m] = DataQualityMonitor.locality_validation_score(m.strip())
        except Exception as exc:
            logger.warning("[health] locality_score check failed: %s", exc)
        try:
            with _get_sa_engine().connect() as conn:
                null_rate = conn.execute(
                    _sa_text("""
                        SELECT ROUND(
                            COUNT(CASE WHEN sentiment_score IS NULL THEN 1 END)::numeric
                            / NULLIF(COUNT(*), 0), 3
                        )
                        FROM news_articles
                        WHERE created_at >= NOW() - INTERVAL '7 days'
                    """)
                ).scalar()
            sentiment_null_rate = float(null_rate) if null_rate is not None else None
        except Exception:
            sentiment_null_rate = None

        services["data_quality"] = {
            "slo_pass": slo_result["slo_pass"],
            "slo_fail": slo_result["slo_fail"],
            "freshness": freshness if freshness else None,
            "seed_stale_warnings": seed_stale[:5],
            "locality_scores": locality_scores,
            "sentiment_null_rate": sentiment_null_rate,
        }
    except Exception as exc:
        logger.warning("[health] data_quality check failed: %s", exc)
        services["data_quality"] = {"slo_pass": 0, "slo_fail": 0, "freshness": None, "seed_stale_warnings": [], "locality_scores": {}, "sentiment_null_rate": None}

    # T-1064: Per-market scraper health from agent_runs
    try:
        with _get_sa_engine().connect() as conn:
            scraper_health = {}
            for mkt in ["Yelahanka", "Hebbal", "Devanahalli"]:
                row = conn.execute(
                    _sa_text("""
                        SELECT metadata, completed_at FROM agent_runs
                        WHERE agent_name = 'rera_scraper'
                          AND micro_market = :market
                          AND task_type = 'scrape_complete'
                        ORDER BY completed_at DESC LIMIT 1
                    """),
                    {"market": mkt},
                ).fetchone()
                if row:
                    md = row[0]
                    scraper_health[mkt] = {
                        "record_count": md.get("record_count") if isinstance(md, dict) else None,
                        "fallback_triggered": md.get("fallback_triggered") if isinstance(md, dict) else None,
                        "path_used": md.get("path_used") if isinstance(md, dict) else None,
                        "run_at": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]) if row[1] else None,
                    }
                else:
                    scraper_health[mkt] = None
            services["scraper_health"] = scraper_health
    except Exception as exc:
        logger.warning("[health] scraper_health check failed: %s", exc)
        services["scraper_health"] = {"error": str(exc)}

    # T-1100: Backup staleness status
    try:
        from utils.backup import check_backup_staleness, get_backup_dir
        stale_info = check_backup_staleness()
        backup_status = {
            "stale": stale_info["stale"],
            "latest_backup_age_hours": stale_info["age_hours"],
            "latest_backup_file": stale_info["latest_file"],
            "backup_dir": get_backup_dir(),
        }
        # Also fetch last backup timestamp from agent_runs
        try:
            with _get_sa_engine().connect() as conn:
                ts_row = conn.execute(
                    _sa_text("""
                        SELECT created_at FROM agent_runs
                        WHERE agent_name = 'backup' AND event_type = 'db_backup' AND status = 'success'
                        ORDER BY created_at DESC LIMIT 1
                    """)
                ).fetchone()
                backup_status["latest_backup_timestamp"] = ts_row[0].isoformat() if ts_row else None
        except Exception:
            backup_status["latest_backup_timestamp"] = None
        backup_status["backup_ok"] = (
            not backup_status["stale"]
            and backup_status["latest_backup_timestamp"] is not None
        )
        services["backup_status"] = backup_status
    except Exception as exc:
        logger.warning("[health] backup_status check failed: %s", exc)
        services["backup_status"] = {
            "backup_ok": False,
            "stale": True,
            "latest_backup_age_hours": None,
            "latest_backup_timestamp": None,
        }

    try:
        from config.llm_router import get_router_status, get_circuit_states
        router_status = get_router_status()
        circuit_states = get_circuit_states()
        services["llm"] = {
            "configured": any(router_status.get("providers", {}).values()),
            "heavy_providers": sum(1 for p in ["groq", "gemini", "nvidia", "sambanova", "openrouter", "cloudflare"]
                                   if router_status.get("providers", {}).get(p)),
            "circuit_states": circuit_states,
        }
    except Exception as exc:
        logger.warning("[health] llm check failed: %s", exc)
        services["llm"] = {"configured": False, "heavy_providers": 0, "circuit_states": {}}

    return services


@app.get(
    "/api/health/live",
    tags=["Health"],
    summary="Lightweight liveness probe (no deps)",
    response_model=HealthServiceStatus,
)
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


@app.post(
    "/api/board/session",
    tags=["Board Room"],
    summary="Create board session",
    responses={400: {"model": ErrorResponse}},
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


@app.get(
    "/api/board/session/{session_id}",
    tags=["Board Room"],
    summary="Get board session by ID",
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("120/minute")
async def board_session_get(request: Request, session_id: str):
    from crews.board_room import get_board_session

    session = get_board_session(session_id)
    if not session:
        return JSONResponse({"error": "not found"}, status_code=404)
    return session


@app.get(
    "/api/board/sessions",
    response_model=BoardSessionsResponse,
    tags=["Board Room"],
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
            result.append(
                {
                    "session_id": str(r[0]),
                    "market": r[1],
                    "status": r[2],
                    "created_at": r[3].isoformat() if r[3] else None,
                    "pitch_excerpt": pitch[:120]
                    + ("\u2026" if len(pitch) > 120 else ""),
                }
            )
        return {"sessions": result}
    except Exception as e:
        logger.error("[board_sessions] %s", e)
        return JSONResponse({"sessions": [], "error": "database query failed"})


@app.get(
    "/api/engineering/brief",
    response_model=BriefResponse,
    tags=["Briefs"],
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
            logger.info(
                "[engineering_brief] No board sessions with engineering_response found"
            )
            return {"brief": None}
        created = row[3].isoformat() if row[3] else None
        logger.info(
            "[engineering_brief] session=%s market=%s created=%s",
            row[0][:8],
            row[1],
            created,
        )
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


@app.get(
    "/api/alerts",
    response_model=AlertsResponse,
    tags=["Alerts"],
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
                "id": str(r[0]),
                "channel": r[1],
                "title": r[2],
                "status": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ]
        logger.info("[list_alerts] channel=%s count=%d", channel or "all", len(result))
        return {"alerts": result}
    except Exception as e:
        logger.error("[list_alerts] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)


@app.get(
    "/api/finance/brief",
    response_model=BriefResponse,
    tags=["Briefs"],
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
            logger.info("[finance_brief] No board sessions with finance_response found")
            return {"brief": None}
        created = row[3].isoformat() if row[3] else None
        logger.info(
            "[finance_brief] session=%s market=%s created=%s",
            row[0][:8],
            row[1],
            created,
        )
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


@app.get(
    "/api/legal/brief",
    response_model=BriefResponse,
    tags=["Briefs"],
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
            logger.info("[legal_brief] No board sessions with legal_response found")
            return {"brief": None}
        created = row[3].isoformat() if row[3] else None
        logger.info(
            "[legal_brief] session=%s market=%s created=%s", row[0][:8], row[1], created
        )
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


# ── Tasks ────────────────────────────────────────────────────────────────────


@app.get(
    "/api/tasks",
    response_model=TasksResponse,
    tags=["Tasks"],
    summary="List tasks with optional status/owner filter",
)
@limiter.limit("60/minute")
async def list_tasks(
    request: Request, status: str = Query(None), owner: str = Query(None)
):
    try:
        with _get_sa_engine().connect() as conn:
            where_clauses, params = [], {}
            if status:
                where_clauses.append("status = :st")
                params["st"] = status
            if owner:
                where_clauses.append("owner = :ow")
                params["ow"] = owner
            where_sql = (
                ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            )
            rows = conn.execute(
                _sa_text(
                    f"SELECT id, title, owner, status, priority, source_type, source_id, created_at "
                    f"FROM tasks {where_sql} ORDER BY created_at DESC LIMIT 200"
                ),
                params,
            ).fetchall()
        result = [
            {
                "id": str(r[0]),
                "title": r[1],
                "owner": r[2],
                "status": r[3],
                "priority": r[4],
                "source_type": r[5],
                "source_id": str(r[6]) if r[6] else None,
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
        return {"tasks": result}
    except Exception as e:
        logger.error("[list_tasks] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)


@app.post(
    "/api/tasks",
    tags=["Tasks"],
    summary="Create a new task",
    responses={400: {"model": ErrorResponse}, 201: {"description": "Task created"}},
)
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
    try:
        with _get_sa_engine().begin() as conn:
            result = conn.execute(
                _sa_text("""INSERT INTO tasks (title, owner, priority, source_type, source_id)
                   VALUES (:t, :o, :p, :st, :si) RETURNING id"""),
                {
                    "t": title,
                    "o": owner or None,
                    "p": priority,
                    "st": source_type or None,
                    "si": str(source_id) if source_id else None,
                },
            )
            task_id = str(result.fetchone()[0])
        return JSONResponse({"task_id": task_id, "status": "queued"}, status_code=201)
    except Exception as e:
        logger.error("[create_task] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)


@app.patch(
    "/api/tasks/{task_id}",
    tags=["Tasks"],
    summary="Update task status",
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
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
    try:
        with _get_sa_engine().begin() as conn:
            result = conn.execute(
                _sa_text(
                    "UPDATE tasks SET status = :s, updated_at = NOW() WHERE id = :tid RETURNING id"
                ),
                {"s": new_status, "tid": tid},
            )
            if result.fetchone() is None:
                return JSONResponse({"error": "not found"}, status_code=404)
        return {"status": new_status}
    except Exception as e:
        logger.error("[update_task] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)


# ── Registry ──────────────────────────────────────────────────────────────────

_registry_cache: dict[str, tuple[list[dict], float]] = {}
_REGISTRY_CACHE_TTL = 15


@app.get(
    "/api/registry",
    response_model=RegistryResponse,
    tags=["Registry"],
    summary="List registered agents",
)
@limiter.limit("30/minute")
async def list_registry(request: Request):
    now = time.time()
    cached = _registry_cache.get("all")
    if cached and cached[1] > now:
        logger.debug("[list_registry] cache hit (%d agents)", len(cached[0]))
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
                "id": r[0],
                "name": r[1],
                "role": r[2],
                "department": r[3],
                "llm_tier": r[4],
                "active": r[5],
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
        return JSONResponse({"error": "database query failed"}, status_code=500)


@app.post(
    "/api/registry",
    tags=["Registry"],
    summary="Hire a new agent from JSON spec",
    responses={400: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
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
        return JSONResponse(
            {"error": f"agent '{spec_id}' already exists"}, status_code=409
        )
    try:
        os.makedirs(os.path.dirname(spec_path), exist_ok=True)
        with open(spec_path, "w", encoding="utf-8") as f:
            yaml.dump(
                validated,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
    except Exception as e:
        logger.error("[hire_agent] write failed: %s", e)
        return JSONResponse({"error": "failed to write spec file"}, status_code=500)
    try:
        from agents.agent_factory import sync_registry_to_db

        synced = sync_registry_to_db()
        logger.info(
            "[hire_agent] synced %d agents (including new '%s')", synced, spec_id
        )
    except Exception as e:
        logger.error("[hire_agent] db sync failed: %s", e)
        return JSONResponse(
            {"warning": "spec written but DB sync failed", "spec_id": spec_id},
            status_code=201,
        )
    _registry_cache.pop("all", None)
    return JSONResponse({"status": "hired", "spec_id": spec_id}, status_code=201)


# ── Metrics ───────────────────────────────────────────────────────────────────


@app.get(
    "/metrics",
    tags=["Metrics"],
    summary="Prometheus metrics endpoint",
    include_in_schema=False,
)
def metrics():
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4",
    )


# ── DB State ─────────────────────────────────────────────────────────────────


@app.get(
    "/api/db/state",
    tags=["DB State"],
    summary="Database record counts and market summary",
)
@limiter.limit("60/minute")
async def db_state(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            state = {}
            state["rera_projects"] = conn.execute(
                _sa_text("SELECT COUNT(*) FROM rera_projects")
            ).fetchone()[0]
            state["listings"] = conn.execute(
                _sa_text("SELECT COUNT(*) FROM listings")
            ).fetchone()[0]
            state["kaveri_registrations"] = conn.execute(
                _sa_text("SELECT COUNT(*) FROM kaveri_registrations")
            ).fetchone()[0]
            state["guidance_values"] = conn.execute(
                _sa_text("SELECT COUNT(*) FROM guidance_values")
            ).fetchone()[0]
            markets = conn.execute(
                _sa_text("""
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
            ).fetchall()
            state["markets"] = [
                {"name": r[0], "projects": r[1], "avg_psf": int(r[2]) if r[2] else None}
                for r in markets
            ]
            recent = conn.execute(
                _sa_text("""
                SELECT micro_market, started_at, status, duration_seconds
                FROM agent_runs ORDER BY started_at DESC LIMIT 5
            """)
            ).fetchall()
            state["recent_runs"] = [
                {
                    "market": r[0],
                    "start_time": r[1].isoformat() if r[1] else None,
                    "status": r[2],
                    "duration": r[3],
                }
                for r in recent
            ]
        return state
    except Exception as e:
        logger.error("[db_state] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)


@app.get("/api/db/tables", tags=["DB State"], summary="View contents of key DB views")
@limiter.limit("30/minute")
async def db_tables(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            with db_query_duration_seconds.labels(
                query_name="v_market_inventory"
            ).time():
                mi_rows = conn.execute(
                    _sa_text("SELECT * FROM v_market_inventory")
                ).fetchall()
                mi_cols = mi_rows[0]._mapping.keys() if mi_rows else []
                market_inventory = [dict(zip(mi_cols, r)) for r in mi_rows]
            with db_query_duration_seconds.labels(
                query_name="v_developer_scorecard"
            ).time():
                ds_rows = conn.execute(
                    _sa_text("""
                    SELECT developer, grade, total_projects, total_units,
                           avg_absorption_pct, completed, delayed, markets_active_in
                    FROM v_developer_scorecard LIMIT 50
                """)
                ).fetchall()
                ds_cols = ds_rows[0]._mapping.keys() if ds_rows else []
                developer_scorecard = [dict(zip(ds_cols, r)) for r in ds_rows]
            with db_query_duration_seconds.labels(
                query_name="v_active_projects"
            ).time():
                ap_rows = conn.execute(
                    _sa_text("""
                    SELECT project_name, developer_name, micro_market, project_status,
                           total_units, unsold_units, absorption_pct
                    FROM v_active_projects LIMIT 100
                """)
                ).fetchall()
                ap_cols = ap_rows[0]._mapping.keys() if ap_rows else []
                active_projects = [dict(zip(ap_cols, r)) for r in ap_rows]
        return {
            "market_inventory": market_inventory,
            "developer_scorecard": developer_scorecard,
            "active_projects": active_projects,
        }
    except Exception as e:
        logger.error("[db_tables] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)


# ── Pipeline Control ─────────────────────────────────────────────────────────


@app.post(
    "/api/run/{market}",
    response_model=RunResponse,
    tags=["Pipeline"],
    summary="Start pipeline for a market",
    responses={400: {"model": ErrorResponse}},
)
@limiter.limit("10/hour")
async def run_pipeline(request: Request, market: str):
    canonical = _normalize_market(market)
    if not canonical:
        return JSONResponse({"error": "invalid market"}, status_code=400)
    payload, status_code = _start_pipeline_for_market(canonical)
    return JSONResponse(payload, status_code=status_code)


@app.delete(
    "/api/run/{market}",
    tags=["Pipeline"],
    summary="Stop running pipeline",
    responses={400: {"model": ErrorResponse}},
)
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


@app.get(
    "/api/agents",
    tags=["Agents"],
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
                        "last_action": f"Last run: {last_run}"
                        if last_run
                        else "No recent activity",
                        "started": last_run.isoformat()
                        if hasattr(last_run, "isoformat")
                        else str(last_run)
                        if last_run
                        else None,
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
    except Exception as e:
        logger.warning(
            "[DIAG agents] DB query failed, falling back to in-memory: %s", e
        )
    if not db_agents:
        with _lock:
            states_copy = copy.deepcopy(_agent_states)
            running_copy = {}
            for market, entry in _running.items():
                rc = entry["proc"].poll()
                running_copy[market] = {
                    "started": entry.get("started"),
                    "state": "running"
                    if rc is None
                    else ("done" if rc == 0 else "failed"),
                    "returncode": rc,
                    "pid": entry["proc"].pid,
                }
        response = {"agents": states_copy, "running_markets": running_copy}
        response.update(states_copy)
        if not _diag_agents_contract_logged:
            logger.info(
                "[DIAG agents] /api/agents keys=%s nested_agents=%s (fallback)",
                sorted(response.keys()),
                sorted(states_copy.keys()),
            )
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
                "returncode": rc,
                "pid": entry["proc"].pid,
            }
    response = {"agents": states_copy, "running_markets": running_copy}
    response.update(states_copy)
    if not _diag_agents_contract_logged:
        source_label = "DB" if db_agents else "in-memory"
        logger.info(
            "[DIAG agents] /api/agents keys=%s nested_agents=%s (from %s)",
            sorted(response.keys()),
            sorted(states_copy.keys()),
            source_label,
        )
        _diag_agents_contract_logged = True
    return response


@app.post(
    "/api/agents/{agent_id}/command",
    tags=["Agents"],
    summary="Send command to an agent (run/stop/status)",
    responses={404: {"model": ErrorResponse}},
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
        k in prompt.lower()
        for k in [
            "run",
            "start",
            "scrape",
            "scan",
            "analyse",
            "analyze",
            "stop",
            "cancel",
        ]
    ):
        chosen_market = "Yelahanka"
    text = prompt.lower()
    if agent_id not in _agent_states:
        return JSONResponse(
            {
                "status": "unknown_command",
                "action": "invalid_agent",
                "details": f"Unknown agent_id '{agent_id}'",
                "hint": "Try: run [market], stop [market], status",
            },
            status_code=404,
        )
    if any(k in text for k in ["run", "start", "scrape", "scan", "analyse", "analyze"]):
        market = chosen_market or "Yelahanka"
        payload, status_code = _start_pipeline_for_market(market)
        return JSONResponse(
            {
                "status": "accepted"
                if payload.get("status") in {"started", "already_running"}
                else "unknown_command",
                "action": "run_pipeline",
                "details": f"{payload.get('status')} for {market}",
                "market": market,
                "pipeline": payload,
            },
            status_code=status_code,
        )
    if any(k in text for k in ["stop", "cancel"]):
        market = chosen_market or "Yelahanka"
        payload, status_code = _stop_pipeline_for_market(market)
        return JSONResponse(
            {
                "status": "accepted"
                if payload.get("status") in {"stopped", "not_running"}
                else "unknown_command",
                "action": "stop_pipeline",
                "details": f"{payload.get('status')} for {market}",
                "market": market,
                "pipeline": payload,
            },
            status_code=status_code,
        )
    if any(k in text for k in ["status", "report", "show"]):
        report_market = (
            chosen_market if chosen_market and chosen_market != "all" else None
        )
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
    return JSONResponse(
        {
            "status": "unknown_command",
            "action": "none",
            "details": "No action matched prompt",
            "hint": "Try: run [market], stop [market], status",
        }
    )


@app.get(
    "/api/agents/{agent_id}/actions",
    tags=["Agents"],
    summary="List available actions for an agent",
)
def agent_actions(agent_id: str):
    if agent_id not in _agent_states and agent_id not in AGENT_ACTIONS:
        return JSONResponse({"error": f"Unknown agent '{agent_id}'"}, status_code=404)
    return {"agent_id": agent_id, "actions": AGENT_ACTIONS.get(agent_id, [])}


@app.get(
    "/api/sentinel/status", tags=["Sentinel"], summary="Current sentinel run status"
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
                    _agent_states["sentinel"]["last_action"] = (
                        f"Next run: {nxt.get('label', '?')}"
                    )
        return {"last_run": last, "next_run": nxt}
    except Exception as e:
        logger.exception("sentinel_status failed")
        with _lock:
            if "sentinel" in _agent_states:
                _agent_states["sentinel"]["last_action"] = "Sentinel error: check logs"
        return JSONResponse(
            {
                "last_run": {"error": str(e)},
                "next_run": {
                    "next_run_utc": None,
                    "in_hours": None,
                    "in_minutes": None,
                    "label": "unavailable",
                },
            }
        )


# ── Log Streaming (SSE) ──────────────────────────────────────────────────────


@app.get(
    "/api/logs/stream", tags=["Logs"], summary="SSE log stream for a market pipeline"
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


# ── Reports ──────────────────────────────────────────────────────────────────


@app.get(
    "/api/reports/{market}",
    tags=["Reports"],
    summary="Latest intel report text for a market",
    responses={400: {"model": ErrorResponse}},
)
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


@app.get(
    "/api/intel/cards",
    response_model=CardsResponse,
    tags=["Reports"],
    summary="Market summary cards for dashboard UI",
)
@limiter.limit("60/minute")
async def intel_cards(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
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
            ).fetchall()
        now = time.time()
        cards = []
        for row in rows:
            market_name = row[0]
            slug = MARKET_SLUG.get(market_name, market_name.lower())
            cached = _estimated_cache.get(market_name)
            if cached and cached[1] > now:
                is_estimated = cached[0]
            else:
                report_files = sorted(
                    glob.glob(f"/app/outputs/{slug}/intel_report_*.txt")
                )
                is_estimated = False
                if report_files:
                    try:
                        with open(report_files[-1], encoding="utf-8") as rf:
                            is_estimated = "[ESTIMATED DATA" in rf.read(4096)
                    except Exception:
                        pass
                _estimated_cache[market_name] = (
                    is_estimated,
                    now + _ESTIMATED_CACHE_TTL,
                )
            cards.append(
                {
                    "market": market_name,
                    "active_projects": int(row[1] or 0),
                    "projects": int(row[1] or 0),
                    "avg_psf": int(row[2]) if row[2] else None,
                    "go_no_go": _market_go_no_go(
                        int(row[1] or 0), int(row[2]) if row[2] else None, is_estimated
                    ),
                    "download_url": f"/api/intel/download?market={slug}"
                    if slug
                    else None,
                    "estimated": is_estimated,
                }
            )
        return {"cards": cards}
    except Exception as e:
        logger.error("[intel_cards] %s", e)
        return JSONResponse({"error": "failed to load market cards"}, status_code=500)


@app.get(
    "/api/intel/search",
    tags=["Reports"],
    summary="Semantic search over past intel reports",
    responses={400: {"model": ErrorResponse}},
)
@limiter.limit("20/minute")
async def intel_search(request: Request, q: str = Query(""), market: str = Query("")):
    query_text = (q or "").strip()[:200]
    market_param = _normalize_market(market)
    if any(ord(c) < 32 and c not in "\t\n\r" for c in query_text):
        return JSONResponse(
            {
                "results": [],
                "query": query_text[:50],
                "error": "invalid characters in query",
            },
            status_code=400,
        )
    if not query_text:
        return {"results": [], "query": query_text}
    market_filter = market_param if market_param and market_param != "all" else None
    cache_key = f"{query_text}:::{market_filter or ''}"
    now = time.time()
    cached = _cache_get(cache_key)
    if cached and cached[1] > now:
        logger.debug(
            "[intel_search] cache hit for q=%s market=%s",
            query_text[:40],
            market_filter,
        )
        return {
            "results": cached[0],
            "query": query_text,
            "market": market,
            "cached": True,
        }
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
        logger.warning(
            "[intel_search] search failed: q=%s market=%s: %s",
            query_text[:40],
            market_filter,
            e,
        )
        return {
            "results": [],
            "query": query_text,
            "error": "search unavailable - index not built yet",
        }


@app.get(
    "/api/intel/download",
    tags=["Reports"],
    summary="Download intel report as txt or csv",
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
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
    try:
        with _get_sa_engine().connect() as conn:
            params = {}
            where = ""
            if canonical != "all":
                where = "WHERE mm.name = :m"
                params["m"] = canonical
            db_rows = conn.execute(
                _sa_text(f"""
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
            """),
                params,
            ).fetchall()
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(
            ["market", "active_projects", "avg_psf", "go_no_go", "estimated"]
        )
        now = time.time()
        for market_name, active_projects, avg_psf in db_rows:
            slug = MARKET_SLUG.get(market_name, market_name.lower())
            cached = _estimated_cache.get(market_name)
            if cached and cached[1] > now:
                estimated = cached[0]
            else:
                report_files = sorted(
                    glob.glob(f"/app/outputs/{slug}/intel_report_*.txt")
                )
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
            writer.writerow(
                [
                    market_name,
                    projects,
                    psf or "",
                    _market_go_no_go(projects, psf, estimated),
                    estimated,
                ]
            )
        filename = (
            "intel_cards.csv"
            if canonical == "all"
            else f"intel_{MARKET_SLUG.get(canonical, canonical.lower())}.csv"
        )
        return Response(
            content=out.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error("[download_intel_csv] %s", e)
        return JSONResponse({"error": "failed to export intel csv"}, status_code=500)


# ── Market Map (Visualization Layer — T-771/T-774/T-778) ─────────────────────


@app.get(
    "/api/market/map/{market}",
    tags=["Market"],
    summary="Folium map HTML with project markers and PSF color gradient",
)
async def market_map(market: str):
    try:
        import folium
        from folium.plugins import MarkerCluster
        from utils.db import get_engine
        from sqlalchemy import text

        canonical = _normalize_market(market)
        if not canonical:
            return JSONResponse({"error": "invalid market"}, status_code=400)

        with get_engine().connect() as conn:
            center = conn.execute(
                text(
                    "SELECT ST_X(centroid), ST_Y(centroid) FROM micro_markets WHERE name ILIKE :m LIMIT 1"
                ),
                {"m": f"%{canonical}%"},
            ).fetchone()

        if not center:
            return JSONResponse({"error": "market not found"}, status_code=404)

        m = folium.Map(
            location=[center[1], center[0]], zoom_start=13, tiles="CartoDB dark_matter"
        )

        with get_engine().connect() as conn:
            projects = conn.execute(
                text("""
                    SELECT rp.project_name, d.name, ST_X(rp.geom), ST_Y(rp.geom),
                           rp.price_min_psf, rp.price_max_psf
                    FROM rera_projects rp
                    JOIN developers d ON d.id = rp.developer_id
                    JOIN micro_markets m ON m.id = rp.micro_market_id
                    WHERE m.name ILIKE :m AND rp.geom IS NOT NULL
                    LIMIT 200
                """),
                {"m": f"%{canonical}%"},
            ).fetchall()

        marker_cluster = MarkerCluster().add_to(m)
        for proj in projects:
            name, dev, lon, lat, psf_min, psf_max = proj
            if lon and lat:
                avg_psf = (
                    (float(psf_min or 0) + float(psf_max or 0)) / 2
                    if psf_min or psf_max
                    else 0
                )
                if avg_psf < 4000:
                    color = "#3fb950"
                elif avg_psf < 6000:
                    color = "#f0a020"
                elif avg_psf < 10000:
                    color = "#f85149"
                else:
                    color = "#9b7ec7"
                psf_str = f"\u20b9{avg_psf:,.0f} PSF" if avg_psf else "PSF unknown"
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=8,
                    color=color,
                    fill=True,
                    fill_opacity=0.7,
                    popup=f"<b>{name}</b><br>{dev}<br>{psf_str}",
                ).add_to(marker_cluster)

        legend_html = """
        <div style="position:fixed;bottom:20px;left:20px;z-index:1000;background:#0f1520;border:1px solid #2a3a55;border-radius:4px;padding:8px;font-family:'Courier New',monospace;font-size:10px;">
            <div style="color:#c9d1d9;margin-bottom:4px;">PSF Range</div>
            <div><span style="color:#3fb950;">\u25cf</span> &lt; \u20b94,000</div>
            <div><span style="color:#f0a020;">\u25cf</span> \u20b94,000\u20136,000</div>
            <div><span style="color:#f85149;">\u25cf</span> \u20b96,000\u201310,000</div>
            <div><span style="color:#9b7ec7;">\u25cf</span> &gt; \u20b910,000</div>
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

        return HTMLResponse(content=m._repr_html_())
    except ImportError as exc:
        logger.warning("[market_map] folium not installed: %s", exc)
        return JSONResponse({"error": "folium not installed"}, status_code=500)
    except Exception as exc:
        logger.warning("[market_map] Failed for %s: %s", market, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get(
    "/api/market/psf-trend/{market}",
    tags=["Market"],
    summary="Monthly PSF trend data for Chart.js line chart",
)
async def psf_trend(market: str):
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        canonical = _normalize_market(market)
        if not canonical:
            return JSONResponse({"error": "invalid market"}, status_code=400)

        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT DATE_TRUNC('month', snapshot_date) AS month,
                           ROUND(AVG(avg_psf)::numeric, 0) AS avg_psf
                    FROM project_snapshots ps
                    JOIN micro_markets m ON m.id = ps.micro_market_id
                    WHERE m.name ILIKE :m AND ps.avg_psf IS NOT NULL
                    GROUP BY DATE_TRUNC('month', snapshot_date)
                    ORDER BY month
                """),
                {"m": f"%{canonical}%"},
            ).fetchall()

        data = [
            {
                "month": r[0].strftime("%Y-%m")
                if hasattr(r[0], "strftime")
                else str(r[0])[:7],
                "psf": float(r[1]),
            }
            for r in rows
        ]
        return {"market": canonical, "trend": data}
    except Exception as exc:
        logger.warning("[psf_trend] Failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get(
    "/api/market/kepler-data/{market}",
    tags=["Market"],
    summary="GeoJSON FeatureCollection for Kepler.gl density map",
)
async def kepler_data(market: str):
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        canonical = _normalize_market(market)
        if not canonical:
            return JSONResponse({"error": "invalid market"}, status_code=400)

        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT rp.project_name, d.name, rp.price_min_psf, rp.price_max_psf,
                           rp.total_units, rp.project_status,
                           ST_AsGeoJSON(rp.geom) AS geojson
                    FROM rera_projects rp
                    JOIN developers d ON d.id = rp.developer_id
                    JOIN micro_markets m ON m.id = rp.micro_market_id
                    WHERE m.name ILIKE :m AND rp.geom IS NOT NULL
                    LIMIT 1000
                """),
                {"m": f"%{canonical}%"},
            ).fetchall()

        features = []
        for r in rows:
            geom = json.loads(r[6]) if r[6] else None
            if geom:
                features.append(
                    {
                        "type": "Feature",
                        "geometry": geom,
                        "properties": {
                            "project": r[0],
                            "developer": r[1],
                            "price_min_psf": float(r[2]) if r[2] else None,
                            "price_max_psf": float(r[3]) if r[3] else None,
                            "total_units": r[4],
                            "status": r[5],
                        },
                    }
                )

        return {
            "type": "FeatureCollection",
            "features": features,
        }
    except Exception as exc:
        logger.warning("[kepler_data] Failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Accessibility (Sprint 74 — GATE-74) ────────────────────────────────────


@app.get(
    "/api/market/accessibility",
    tags=["Market"],
    summary="Travel-time accessibility scores for a market",
)
async def market_accessibility(market: str = Query(default="Yelahanka", description="Market name")):
    try:
        from utils.db import get_engine
        from sqlalchemy import text as sa_text

        canonical = _normalize_market(market)
        if not canonical:
            return JSONResponse({"error": "invalid market"}, status_code=400)

        with get_engine().connect() as conn:
            rows = conn.execute(
                sa_text("""
                    SELECT destination_name, travel_time_min, distance_km, measured_at, accessibility_score
                    FROM accessibility_scores
                    WHERE market = :market
                      AND measured_at > NOW() - INTERVAL '30 days'
                    ORDER BY measured_at DESC
                """),
                {"market": canonical},
            ).fetchall()

        if not rows:
            return JSONResponse({"error": "no accessibility data for market"}, status_code=404)

        latest: dict[str, dict] = {}
        latest_dt: dict[str, datetime] = {}
        for r in rows:
            dest = str(r[0])
            if dest not in latest:
                measured = r[3]
                if hasattr(measured, "isoformat"):
                    measured_iso = measured.isoformat()
                    latest_dt[dest] = measured
                else:
                    measured_iso = str(measured)
                    latest_dt[dest] = measured
                latest[dest] = {
                    "name": dest,
                    "travel_time_min": float(r[1]),
                    "distance_km": float(r[2]) if r[2] else None,
                    "measured_at": measured_iso,
                    "accessibility_score": float(r[4]) if r[4] else 0.0,
                }

        destinations = list(latest.values())
        total_score = sum(d["accessibility_score"] for d in destinations)

        last_updated = None
        if latest_dt:
            last_updated = max(latest_dt.values())
            last_updated = last_updated.isoformat() if hasattr(last_updated, "isoformat") else str(last_updated)

        return {
            "market": canonical,
            "accessibility_score": round(total_score, 4),
            "destinations": destinations,
            "last_updated": last_updated,
        }
    except Exception as exc:
        logger.warning("[market_accessibility] Failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Surveys ────────────────────────────────────────────────────────────────


class SurveyCreate(BaseModel):
    survey_no: str
    market: str
    total_area_acres: float
    land_type: str = "agricultural"
    encumbrance_clear: bool = False
    is_aggregated: bool = False


@app.post(
    "/api/surveys",
    tags=["Surveys"],
    summary="Add a new survey for opportunity scoring",
    status_code=201,
)
async def create_survey(body: SurveyCreate, request: Request):
    try:
        with _get_sa_engine().begin() as conn:
            market_row = conn.execute(
                _sa_text("SELECT id FROM micro_markets WHERE name ILIKE :m LIMIT 1"),
                {"m": f"%{body.market}%"},
            ).fetchone()
            if not market_row:
                return JSONResponse(
                    {"error": f"market '{body.market}' not found"}, status_code=404
                )
            market_id = market_row[0]
            total_sqft = body.total_area_acres * 43560.0
            result = conn.execute(
                _sa_text("""INSERT INTO surveys (survey_no, micro_market_id, total_area_acres, total_area_sqft,
                                        land_type, encumbrance_clear, is_aggregated, dc_conversion_status)
                   VALUES (:sn, :mm, :ta, :ts, :lt, :ec, :ia, 'pending')
                   RETURNING id, survey_no, total_area_acres, total_area_sqft, land_type,
                             encumbrance_clear, is_aggregated, dc_conversion_status, created_at"""),
                {
                    "sn": body.survey_no,
                    "mm": market_id,
                    "ta": body.total_area_acres,
                    "ts": total_sqft,
                    "lt": body.land_type,
                    "ec": body.encumbrance_clear,
                    "ia": body.is_aggregated,
                },
            )
            row = result.fetchone()
        return {
            "id": str(row[0]),
            "survey_no": row[1],
            "total_area_acres": float(row[2]),
            "total_area_sqft": float(row[3]),
            "land_type": row[4],
            "encumbrance_clear": row[5],
            "is_aggregated": row[6],
            "dc_conversion_status": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
        }
    except Exception as exc:
        logger.error("[create_survey] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Evaluate API (Sprint 64 — Decision Layer) ────────────────────────────────────


_SURVEY_NO_RE = re.compile(r"^\d{1,4}/\d{1,4}$")


def _validate_survey_no(survey_no: str) -> str:
    s = survey_no.strip()
    if not _SURVEY_NO_RE.match(s):
        raise ValueError(
            f"Invalid survey_no format: '{survey_no}'. "
            f"Expected pattern 'NNN/NNN' (e.g. '45/2', '102/45')"
        )
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


@app.post(
    "/api/evaluate",
    response_model=EvaluateStartResponse,
    tags=["Evaluate"],
    summary="Start async deal evaluation pipeline",
    responses={400: {"model": ErrorResponse}},
)
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
        return JSONResponse({"error": str(exc)}, status_code=400)
    market_raw = payload.get("market", "")
    market = _normalize_market(market_raw)
    if not market:
        return JSONResponse(
            {"error": "valid market required (Yelahanka/Devanahalli/Hebbal)"},
            status_code=400,
        )

    raw_area = payload.get("land_area_sqft", 43560)
    try:
        land_area_sqft = float(raw_area)
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": "land_area_sqft must be a number"}, status_code=400
        )

    sell_psf = payload.get("sell_psf")
    if sell_psf is not None:
        try:
            sell_psf = float(sell_psf)
        except (ValueError, TypeError):
            return JSONResponse({"error": "sell_psf must be a number"}, status_code=400)

    valid_deal_types = {"purchase", "jd", "jv", "compare"}
    deal_type = str(payload.get("deal_type", "compare")).strip().lower()
    if deal_type not in valid_deal_types:
        return JSONResponse(
            {
                "error": f"deal_type must be one of: {', '.join(sorted(valid_deal_types))}"
            },
            status_code=400,
        )

    pitch = str(payload.get("pitch", "")).strip()[:5000]

    from crews.evaluate_pipeline import start_evaluate

    result = start_evaluate(
        survey_no=survey_no,
        market=market,
        land_area_sqft=land_area_sqft,
        sell_psf=sell_psf,
        deal_type=deal_type,
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


@app.get(
    "/api/evaluate/{job_id}",
    response_model=EvaluateJobResponse,
    tags=["Evaluate"],
    summary="Poll async evaluation job status",
    responses={404: {"model": ErrorResponse}},
)
@limiter.limit("30/minute")
async def evaluate_status(request: Request, job_id: str):
    from crews.evaluate_pipeline import get_evaluate_job

    job = get_evaluate_job(job_id)
    if job is None:
        return JSONResponse({"error": "job not found"}, status_code=404)
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


@app.get(
    "/api/opportunity/queue",
    response_model=OpportunityQueueResponse,
    tags=["Opportunity"],
    summary="Ranked opportunity queue",
)
@limiter.limit("30/minute")
async def opportunity_queue(
    request: Request,
    market: str = Query(None),
    min_score: float = Query(None),
    limit: int = Query(default=50),
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
                       os.computed_at,
                       d.name AS developer_name
                FROM opportunity_scores os
                JOIN micro_markets mm ON mm.id = os.micro_market_id
                LEFT JOIN developers d ON d.id = os.developer_id
                WHERE {where_sql}
                ORDER BY os.score DESC
                LIMIT :lim
            """),
                params,
            ).fetchall()

        rows = []
        for r in db_rows:
            rows.append(
                {
                    "id": str(r[0]),
                    "survey_no": r[1],
                    "market": r[2],
                    "score": float(r[3]) if r[3] else 0.0,
                    "irr_score": float(r[4]) if r[4] else 0.0,
                    "legal_score": float(r[5]) if r[5] else 0.0,
                    "timing_score": float(r[6]) if r[6] else 0.0,
                    "distress_score": float(r[7]) if r[7] else 0.0,
                    "exclusivity_score": float(r[8]) if r[8] else 0.0,
                    "best_deal_type": r[9],
                    "estimated_jd_irr": float(r[10]) if r[10] else None,
                    "legal_risk_level": r[11],
                    "next_action": r[12],
                    "expiry_date": r[13].isoformat() if r[13] else None,
                    "computed_at": r[14].isoformat() if r[14] else None,
                    "developer_name": r[15],
                }
            )
        return {"opportunities": rows, "count": len(rows)}
    except Exception as e:
        logger.error("[opportunity_queue] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)


# ── Data Freshness (Sprint 41) ──────────────────────────────────────────────


@app.get(
    "/api/data/freshness",
    response_model=FreshnessResponse,
    tags=["Data"],
    summary="Data freshness per source per market",
)
@limiter.limit("30/minute")
async def data_freshness(request: Request, market: str = Query(None)):
    from utils.data_freshness import get_source_status

    market_filter = market.strip() if market else None
    rows = get_source_status(market=market_filter)
    return {"freshness": rows}


# ── Memory Explorer (Sprint 86 — T-86A) ────────────────────────────────────


@app.get(
    "/api/memory/explorer",
    response_model=MemoryExplorerResponse,
    tags=["Memory"],
    summary="Paginated agent memory explorer with filters",
)
@limiter.limit("60/hour")
async def memory_explorer(
    request: Request,
    market: str = Query(default=None, description="Market filter"),
    agent_id: str = Query(default=None, description="Agent ID filter"),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0, description="Minimum confidence threshold"),
    days: int = Query(default=30, ge=7, le=365, description="Lookback window in days"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=20, ge=1, le=100, description="Items per page"),
):
    market_filter = _normalize_market(market) if market else None
    offset = (page - 1) * per_page
    # ── Safety limits ──
    MAX_FACT_LENGTH = 10000  # truncate fact to prevent response bloat
    MAX_PER_PAGE = 100
    SAFE_PER_PAGE = min(per_page, MAX_PER_PAGE)
    safe_offset = (page - 1) * SAFE_PER_PAGE
    # NOTE: where_sql uses f-string for dynamic column name construction only.
    # All user-supplied filter VALUES use bound parameters (:m, :aid) —
    # never string interpolation of user input. This pattern is reviewed
    # and approved as injection-safe per OWASP ASVS 5.1.
    try:
        with _get_sa_engine().connect() as conn:
            where = ["confidence >= :mc", "last_updated >= NOW() - :days * INTERVAL '1 day'"]
            params: dict = {"mc": min_confidence, "days": days}

            if market_filter:
                where.append("market ILIKE :m")
                params["m"] = f"%{market_filter}%"
            if agent_id:
                where.append("agent_id = :aid")
                params["aid"] = agent_id

            where_sql = " AND ".join(where)
            params["lim"] = SAFE_PER_PAGE
            params["off"] = safe_offset

            total = conn.execute(
                _sa_text(f"SELECT COUNT(*) FROM agent_memories WHERE {where_sql}"),
                {k: v for k, v in params.items() if k not in ("lim", "off")},
            ).scalar() or 0

            rows = conn.execute(
                _sa_text(f"""
                SELECT id, agent_id, market, fact, confidence,
                       COALESCE(source_count, 0) as source_count,
                       last_updated, created_at
                FROM agent_memories
                WHERE {where_sql}
                ORDER BY confidence DESC, last_updated DESC
                LIMIT :lim OFFSET :off
            """),
                params,
            ).fetchall()

        memories = []
        for r in rows:
            fact_raw = str(r[3]) if r[3] else ""
            memories.append({
                "id": str(r[0]),
                "agent_id": str(r[1]) if r[1] else "",
                "market": str(r[2]) if r[2] else "",
                "fact": fact_raw[:MAX_FACT_LENGTH],
                "fact_truncated": len(fact_raw) > MAX_FACT_LENGTH,
                "confidence": round(float(r[4]), 3) if r[4] is not None else 0.0,
                "source_count": int(r[5]) if r[5] is not None else 0,
                "last_updated": r[6].isoformat() if r[6] else None,
                "created_at": r[7].isoformat() if r[7] else None,
            })
        return {"total": total, "page": page, "per_page": SAFE_PER_PAGE, "memories": memories}
    except Exception as e:
        logger.error("[memory_explorer] page=%s market=%s agent=%s err=%s", page, market_filter, agent_id, e)
        return JSONResponse(
            {"error": "failed to query agent memories", "detail": "database query error"},
            status_code=500,
        )


@app.get(
    "/api/memory/conflict-count",
    response_model=ConflictCountResponse,
    tags=["Memory"],
    summary="Unresolved conflict count for nav badge",
)
@limiter.limit("60/hour")
async def memory_conflict_count(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            count = conn.execute(
                _sa_text("""
                    SELECT COUNT(*) FROM agent_memories
                    WHERE fact ILIKE '%CONFLICT%' OR fact ILIKE '%conflict%'
                """),
            ).scalar() or 0
        return {"unresolved_conflicts": int(count)}
    except Exception:
        logger.warning("[memory_conflict_count] DB unavailable — returning 0")
        return {"unresolved_conflicts": 0}


# ── LLM Provider Health ───────────────────────────────────────────────────


class LLMHealthResponse(BaseModel):
    configured: bool
    providers_available: list[str]
    providers_failed: list[str]
    circuit_state: dict[str, dict] = {}
    recommended_model: str | None = None


@app.get(
    "/api/health/llm",
    response_model=LLMHealthResponse,
    tags=["Health"],
    summary="LLM provider health — circuit breaker states + provider availability",
)
@limiter.limit("30/minute")
async def health_llm(request: Request):
    try:
        from config.llm_router import get_router_status, get_circuit_states
        status = get_router_status()
        circuits = get_circuit_states()
        providers = status.get("providers", {})
        available = [p for p, cfg in providers.items() if cfg]
        failed = [p for p, cfg in providers.items() if not cfg]
        return LLMHealthResponse(
            configured=len(available) > 0,
            providers_available=available,
            providers_failed=failed,
            circuit_state=circuits,
            recommended_model=available[0] if available else None,
        )
    except Exception as exc:
        logger.warning("[health_llm] %s", exc)
        return LLMHealthResponse(configured=False, providers_available=[], providers_failed=["router_error"])


# ── Backup Health (T-904) ──────────────────────────────────────────────────


@app.get(
    "/api/health/backup",
    response_model=BackupHealthResponse,
    tags=["Health"],
    summary="Last DB backup timestamp",
)
@limiter.limit("30/minute")
async def health_backup(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            row = conn.execute(
                _sa_text("""
                SELECT created_at FROM agent_runs
                WHERE agent_id = 'backup' AND event_type = 'db_backup'
                ORDER BY created_at DESC LIMIT 1
            """)
            ).fetchone()
        if row:
            return {
                "last_backup": row[0].isoformat() if row[0] else None,
                "status": "ok",
            }
        return {"last_backup": None, "status": "never_run"}
    except Exception as e:
        logger.error("[health_backup] %s", e)
        return {"last_backup": None, "status": "never_run"}


# ── Data Provenance (T-1126) ──────────────────────────────────────────


@app.get(
    "/api/data/provenance",
    response_model=dict[str, ProvenanceMarketInfo],
    tags=["Data Quality"],
    summary="Data provenance breakdown per market (live vs seed)",
)
@limiter.limit("60/hour")
async def data_provenance(
    request: Request,
    market: str = Query(default=None, description="Optional market filter"),
):
    try:
        with _get_sa_engine().connect() as conn:
            where = []
            params: dict = {}
            if market:
                where.append("mm.name ILIKE :mkt")
                params["mkt"] = f"%{market}%"
            where_clause = (" WHERE " + " AND ".join(where)) if where else ""
            rows = conn.execute(_sa_text(f"""
                SELECT mm.name, rp.data_source, COUNT(*) as cnt
                FROM rera_projects rp
                JOIN micro_markets mm ON mm.id = rp.micro_market_id
                {where_clause}
                GROUP BY mm.name, rp.data_source
                ORDER BY mm.name
            """), params).fetchall()

        markets: dict[str, dict] = {}
        for row in rows:
            mkt = str(row[0]) if row[0] else "Unknown"
            ds = str(row[1]) if row[1] else "seed_estimated"
            cnt = int(row[2]) if row[2] else 0
            if mkt not in markets:
                markets[mkt] = {"total": 0, "live": 0, "seed": 0, "manual": 0, "live_pct": 0.0}
            markets[mkt]["total"] += cnt
            if ds == "portal_scraped":
                markets[mkt]["live"] += cnt
            elif ds == "manual_entry":
                markets[mkt]["manual"] += cnt
            else:
                markets[mkt]["seed"] += cnt

        for data in markets.values():
            total = data["total"]
            live = data["live"]
            data["live_pct"] = round((live / total) * 100, 1) if total > 0 else 0.0
            if data["live_pct"] < 30:
                data["guidance"] = "Run RERA scraper — live data below 30% threshold"
            elif data["live_pct"] < 70:
                data["guidance"] = "Monitor — live data moderate, continue scraping"
            else:
                data["guidance"] = "Healthy — live data above 70%"

        if market and not markets:
            return {market: {"total": 0, "live": 0, "seed": 0, "manual": 0, "live_pct": 0.0, "guidance": "No data for this market"}}

        return markets
    except Exception as e:
        logger.error("[data_provenance] err=%s", e)
        return JSONResponse({"error": "failed to query data provenance"}, status_code=500)


# ── Scheduler Health (R6 — T-1125) ────────────────────────────────────


@app.get(
    "/api/scheduler/health",
    tags=["Health"],
    summary="Scheduler job health — last run status per job ID (7d window)",
)
@limiter.limit("30/minute")
async def scheduler_health(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT agent_name, event_type, status, started_at, completed_at,
                           CASE WHEN started_at > NOW() - INTERVAL '24 hours' THEN 1 ELSE 0 END AS in_last_24h
                    FROM agent_runs
                    WHERE started_at > NOW() - INTERVAL '7 days'
                    ORDER BY started_at DESC
                    LIMIT 500
                """)
            ).fetchall()
        jobs: dict[str, dict] = {}
        for r in rows:
            jid = str(r[0]) if r[0] else "unknown"
            if jid not in jobs:
                jobs[jid] = {
                    "job_id": jid,
                    "event_type": r[1],
                    "last_status": r[2],
                    "last_run": r[3].isoformat() if r[3] else None,
                    "completed_at": r[4].isoformat() if r[4] else None,
                    "last_24h_passes": 0,
                    "last_24h_failures": 0,
                }
            if r[5]:  # in_last_24h
                status = r[2]
                if status == "success":
                    jobs[jid]["last_24h_passes"] += 1
                elif status in ("failed", "error"):
                    jobs[jid]["last_24h_failures"] += 1
        return {
            "jobs": sorted(jobs.values(), key=lambda j: j["last_run"] or "", reverse=True),
            "total_jobs": len(jobs),
        }
    except Exception as e:
        logger.error("[scheduler_health] %s", e)
        return JSONResponse({"error": "database query failed"}, status_code=500)


# ── Scraper Reliability (T-1127) ──────────────────────────────────────


@app.get(
    "/api/scraper/reliability",
    response_model=dict[str, ScraperReliabilityInfo],
    tags=["Data Quality"],
    summary="Scraper reliability scores for all scouts",
)
@limiter.limit("60/hour")
async def scraper_reliability(request: Request, days: int = Query(default=30, ge=1, le=365)):
    try:
        from config.scraper_registry import SCRAPER_NAMES
        from utils.scraper_reliability import compute_scraper_reliability

        results = []
        for name in SCRAPER_NAMES:
            try:
                result = compute_scraper_reliability(name, days=days)
                results.append(result)
            except Exception as exc:
                logger.warning("[scraper_reliability] %s: %s", name, exc)
                results.append({"scraper": name, "runs": 0, "successes": 0, "reliability_score": 0.0, "last_run": None})

        return {r["scraper"]: r for r in results}
    except Exception as e:
        logger.error("[scraper_reliability] err=%s", e)
        return JSONResponse({"error": "failed to query scraper reliability"}, status_code=500)


# ── Competitive Intelligence Pulse (T-974) ──────────────────────────────

_pulse_cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_pulse_cache_lock = threading.Lock()
_PULSE_CACHE_TTL = 14400  # 4 hours
_PULSE_CACHE_MAX = 500


@app.get(
    "/api/competitive/pulse",
    tags=["Competitive Intelligence"],
    summary="Competitive pulse — new launches, PSF movers, absorption leaders",
)
@limiter.limit("20/hour")
async def competitive_pulse(
    request: Request,
    market: str | None = Query(default=None, description="Market filter"),
    days: int = Query(default=7, ge=1, le=365, description="New launch window days"),
    top_n: int = Query(default=5, ge=1, le=50, description="Absorption leader count"),
):
    import time as _time_now
    safe_market = market or ""
    cache_key = f"{safe_market}:{days}:{top_n}"

    with _pulse_cache_lock:
        cached = _pulse_cache.get(cache_key)
        if cached is not None:
            ts, data = cached
            if _time_now.time() < ts:
                _pulse_cache.move_to_end(cache_key)
                return data

    try:
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        result = engine.pulse(market=market, days=days, top_n=top_n)
        with _pulse_cache_lock:
            _pulse_cache[cache_key] = (_time_now.time() + _PULSE_CACHE_TTL, result)
            if len(_pulse_cache) > _PULSE_CACHE_MAX:
                _pulse_cache.popitem(last=False)
        return result
    except Exception as exc:
        logger.error("[competitive_pulse] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Deal Pipeline (T-917) ────────────────────────────────────────────────


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


_VALID_DEAL_STAGES = {
    "prospecting",
    "diligence",
    "negotiation",
    "loi",
    "signed",
    "dropped",
}


@app.post(
    "/api/deals",
    tags=["Deals"],
    status_code=201,
    summary="Promote an opportunity to the deal pipeline",
)
async def create_deal(body: DealCreate, request: Request):
    if body.stage is not None and body.stage not in _VALID_DEAL_STAGES:
        return JSONResponse({"error": f"invalid stage: {body.stage}"}, status_code=400)
    try:
        with _get_sa_engine().begin() as conn:
            market_row = conn.execute(
                _sa_text("SELECT id FROM micro_markets WHERE name ILIKE :m LIMIT 1"),
                {"m": f"%{body.market}%"},
            ).fetchone()
            if not market_row:
                return JSONResponse(
                    {"error": f"market '{body.market}' not found"}, status_code=404
                )
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
            "id": str(row[0]),
            "survey_no": row[1],
            "stage": row[2],
            "opportunity_score": float(row[3]) if row[3] else None,
            "assigned_to": row[4],
            "next_step": row[5],
            "next_step_due": row[6].isoformat() if row[6] else None,
            "notes": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
            "updated_at": row[9].isoformat() if row[9] else None,
        }
    except Exception as exc:
        logger.error("[create_deal] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/deals", tags=["Deals"], summary="List all deals in pipeline")
async def list_deals(
    request: Request,
    stage: str = Query(default=None),
    market: str = Query(default=None),
):
    try:
        with _get_sa_engine().connect() as conn:
            where_parts = []
            params = {}
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
        result = []
        for r in rows:
            result.append(
                {
                    "id": str(r[0]),
                    "survey_no": r[1],
                    "market": r[2],
                    "stage": r[3],
                    "opportunity_score": float(r[4]) if r[4] else None,
                    "assigned_to": r[5],
                    "next_step": r[6],
                    "next_step_due": r[7].isoformat() if r[7] else None,
                    "notes": r[8],
                    "created_at": r[9].isoformat() if r[9] else None,
                    "updated_at": r[10].isoformat() if r[10] else None,
                }
            )
        return result
    except Exception as exc:
        logger.error("[list_deals] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.patch("/api/deals/{deal_id}", tags=["Deals"], summary="Update deal stage or notes")
async def update_deal(deal_id: str, body: DealUpdate, request: Request):
    try:
        tid = str(uuid.UUID(deal_id))
    except ValueError:
        return JSONResponse({"error": "invalid deal_id"}, status_code=400)
    try:
        with _get_sa_engine().begin() as conn:
            existing = conn.execute(
                _sa_text(
                    "SELECT dp.id, dp.survey_no, dp.stage, dp.opportunity_score, mm.name FROM deal_pipeline dp LEFT JOIN micro_markets mm ON mm.id = dp.micro_market_id WHERE dp.id = :tid"
                ),
                {"tid": tid},
            ).fetchone()
            if not existing:
                return JSONResponse({"error": "deal not found"}, status_code=404)

            updates = []
            params = {}
            if body.stage is not None:
                if body.stage not in _VALID_DEAL_STAGES:
                    return JSONResponse(
                        {"error": f"invalid stage: {body.stage}"}, status_code=400
                    )
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
                return JSONResponse({"error": "no fields to update"}, status_code=400)

            updates.append("updated_at = NOW()")
            set_clause = ", ".join(updates)
            params["tid"] = tid
            row = conn.execute(
                _sa_text(
                    f"UPDATE deal_pipeline SET {set_clause} WHERE id = :tid RETURNING id, survey_no, stage, opportunity_score, assigned_to, next_step, next_step_due, notes, created_at, updated_at"
                ),
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
            "id": str(row[0]),
            "survey_no": row[1],
            "stage": row[2],
            "opportunity_score": float(row[3]) if row[3] else None,
            "assigned_to": row[4],
            "next_step": row[5],
            "next_step_due": row[6].isoformat() if row[6] else None,
            "notes": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
            "updated_at": row[9].isoformat() if row[9] else None,
        }
    except Exception as exc:
        logger.error("[update_deal] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Projects & Tasks (Sprint 58 — T-995) ───────────────────────────────────


_VALID_PROJECT_STATUSES = frozenset({
    "lead", "mou", "loi", "signed", "rera_applied",
    "construction", "possession", "delivered", "paused",
})

# Forward progression: projects move linearly through these stages.
# paused and delivered are terminal. No backward jumps.
_PROJECT_STAGE_ORDER = [
    "lead", "mou", "loi", "signed", "rera_applied",
    "construction", "possession", "delivered",
]
_STAGE_RANK = {s: i for i, s in enumerate(_PROJECT_STAGE_ORDER)}
_VALID_TRANSITIONS = {
    s: {t for t in _PROJECT_STAGE_ORDER if _STAGE_RANK.get(t, -1) >= _STAGE_RANK.get(s, 0) and t != s}
    | {"paused"}
    for s in _PROJECT_STAGE_ORDER
}
_VALID_TRANSITIONS["paused"] = set(_PROJECT_STAGE_ORDER)


class ProjectCreate(BaseModel):
    name: str
    market: str | None = None
    survey_no: str | None = None
    deal_type: str | None = None
    status: str | None = None
    notes: str | None = None
    start_date: str | None = None
    target_close_date: str | None = None
    source_deal_id: str | None = None
    source_board_session_id: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    market: str | None = None
    survey_no: str | None = None
    deal_type: str | None = None
    notes: str | None = None
    start_date: str | None = None
    target_close_date: str | None = None


class ProjectStatusUpdate(BaseModel):
    status: str


class TaskCreate(BaseModel):
    title: str
    owner_agent_id: str | None = None
    dept: str | None = None
    due_date: str | None = None
    notes: str | None = None


class TaskUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None


@app.post("/api/projects", tags=["Operations"], status_code=201,
          summary="Create a new project")
@limiter.limit("30/hour")
async def create_project(body: ProjectCreate, request: Request):
    try:
        st = (body.status or "lead").lower()
        if st not in _VALID_PROJECT_STATUSES:
            return JSONResponse({"error": f"invalid status: {st}"}, status_code=400)
        if not body.name or len(body.name.strip()) < 1:
            return JSONResponse({"error": "name is required"}, status_code=400)
        if len(body.name) > 200:
            return JSONResponse({"error": "name too long (max 200 chars)"}, status_code=400)
        if body.notes and len(body.notes) > 5000:
            return JSONResponse({"error": "notes too long (max 5000 chars)"}, status_code=400)

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
                    "name": body.name, "market": body.market,
                    "survey_no": body.survey_no, "deal_type": body.deal_type,
                    "status": st, "notes": body.notes,
                    "start": body.start_date, "target": body.target_close_date,
                    "deal_id": body.source_deal_id or None,
                    "board_id": body.source_board_session_id or None,
                },
            ).fetchone()
        return {
            "id": str(row[0]), "name": row[1], "market": row[2],
            "survey_no": row[3], "deal_type": row[4], "status": row[5],
            "notes": row[6],
            "start_date": row[7].isoformat() if row[7] else None,
            "target_close_date": row[8].isoformat() if row[8] else None,
            "created_at": row[9].isoformat() if row[9] else None,
            "updated_at": row[10].isoformat() if row[10] else None,
        }
    except Exception as exc:
        logger.error("[create_project] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/projects", tags=["Operations"],
         summary="List projects with optional filters and pagination")
@limiter.limit("60/minute")
async def list_projects(
    request: Request,
    status: str = Query(default=None),
    market: str = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
):
    try:
        with _get_sa_engine().connect() as conn:
            where = []
            params = {}
            if status:
                where.append("p.status = :st")
                params["st"] = status
            if market:
                where.append("p.market ILIKE :mkt")
                params["mkt"] = f"%{market}%"
            where_sql = ("WHERE " + " AND ".join(where)) if where else ""

            # Count total for pagination
            total = conn.execute(
                _sa_text(f"SELECT COUNT(*) FROM projects p {where_sql}"),
                params,
            ).scalar() or 0

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

        result = []
        for r in rows:
            result.append({
                "id": str(r[0]), "name": r[1], "market": r[2],
                "survey_no": r[3], "deal_type": r[4], "status": r[5],
                "notes": r[6],
                "created_at": r[7].isoformat() if r[7] else None,
                "days_in_stage": int(r[8]) if r[8] else 0,
                "open_task_count": int(r[9]) if r[9] else 0,
            })
        return {"projects": result, "total": total, "page": page, "per_page": per_page}
    except Exception as exc:
        logger.error("[list_projects] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/projects/{project_id}", tags=["Operations"],
         summary="Get project detail with tasks and velocity")
@limiter.limit("60/minute")
async def get_project(project_id: str, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
    except ValueError:
        return JSONResponse({"error": "invalid project_id"}, status_code=400)
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
                return JSONResponse({"error": "project not found"}, status_code=404)

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

        tasks_list = []
        for t in tasks:
            tasks_list.append({
                "id": str(t[0]), "title": t[1], "owner_agent_id": t[2],
                "dept": t[3], "status": t[4],
                "due_date": t[5].isoformat() if t[5] else None,
                "completed_at": t[6].isoformat() if t[6] else None,
                "notes": t[7],
                "created_at": t[8].isoformat() if t[8] else None,
            })

        stages = []
        for v in velocity:
            stages.append({
                "from_status": v[0], "to_status": v[1],
                "days_elapsed": int(v[2]) if v[2] else 0,
                "transitioned_at": v[3].isoformat() if v[3] else None,
            })

        current_stage = str(proj[5] or "lead")
        current_stage_days = int(proj[12]) if proj[12] else 0

        return {
            "project": {
                "id": str(proj[0]), "name": proj[1], "market": proj[2],
                "survey_no": proj[3], "deal_type": proj[4], "status": current_stage,
                "notes": proj[6],
                "start_date": proj[7].isoformat() if proj[7] else None,
                "target_close_date": proj[8].isoformat() if proj[8] else None,
                "actual_close_date": proj[9].isoformat() if proj[9] else None,
                "created_at": proj[10].isoformat() if proj[10] else None,
                "updated_at": proj[11].isoformat() if proj[11] else None,
                "days_in_stage": current_stage_days,
            },
            "tasks": tasks_list,
            "velocity": {"stages": stages, "current_stage": current_stage,
                          "current_stage_days": current_stage_days},
        }
    except Exception as exc:
        logger.error("[get_project] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.patch("/api/projects/{project_id}", tags=["Operations"],
           summary="Update project metadata (name, market, notes, dates)")
@limiter.limit("30/hour")
async def update_project(project_id: str, body: ProjectUpdate, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
    except ValueError:
        return JSONResponse({"error": "invalid project_id"}, status_code=400)
    try:
        updates = []
        params = {"pid": pid}
        for field, col, cast in [
            ("name", "name", None),
            ("market", "market", None),
            ("survey_no", "survey_no", None),
            ("deal_type", "deal_type", None),
            ("notes", "notes", None),
            ("start_date", "start_date", "date"),
            ("target_close_date", "target_close_date", "date"),
        ]:
            val = getattr(body, field, None)
            if val is not None:
                updates.append(f"{col} = :{field}")
                params[field] = val

        if not updates:
            return JSONResponse({"error": "no fields to update"}, status_code=400)

        updates.append("updated_at = NOW()")
        set_clause = ", ".join(updates)
        with _get_sa_engine().begin() as conn:
            row = conn.execute(
                _sa_text(f"""
                    UPDATE projects SET {set_clause} WHERE id = :pid
                    RETURNING id, name, market, survey_no, deal_type, status, notes,
                              start_date, target_close_date, created_at, updated_at
                """),
                params,
            ).fetchone()
        if not row:
            return JSONResponse({"error": "project not found"}, status_code=404)
        return {
            "id": str(row[0]), "name": row[1], "market": row[2],
            "survey_no": row[3], "deal_type": row[4], "status": row[5],
            "notes": row[6],
            "start_date": row[7].isoformat() if row[7] else None,
            "target_close_date": row[8].isoformat() if row[8] else None,
            "created_at": row[9].isoformat() if row[9] else None,
            "updated_at": row[10].isoformat() if row[10] else None,
        }
    except Exception as exc:
        logger.error("[update_project] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/projects/{project_id}/tasks", tags=["Operations"],
          status_code=201, summary="Add a task to a project")
@limiter.limit("60/hour")
async def create_task(project_id: str, body: TaskCreate, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
    except ValueError:
        return JSONResponse({"error": "invalid project_id"}, status_code=400)
    if not body.title or len(body.title.strip()) < 1:
        return JSONResponse({"error": "title is required"}, status_code=400)
    if len(body.title) > 500:
        return JSONResponse({"error": "title too long (max 500 chars)"}, status_code=400)
    try:
        with _get_sa_engine().begin() as conn:
            exists = conn.execute(
                _sa_text("SELECT id FROM projects WHERE id = :pid"),
                {"pid": pid},
            ).fetchone()
            if not exists:
                return JSONResponse({"error": "project not found"}, status_code=404)

            row = conn.execute(
                _sa_text("""
                    INSERT INTO project_tasks (project_id, title, owner_agent_id, dept, due_date, notes)
                    VALUES (:pid, :title, :owner, :dept, CAST(:due AS date), :notes)
                    RETURNING id, title, owner_agent_id, dept, status, due_date, notes, created_at
                """),
                {
                    "pid": pid, "title": body.title,
                    "owner": body.owner_agent_id, "dept": body.dept,
                    "due": body.due_date, "notes": body.notes,
                },
            ).fetchone()
        return {
            "id": str(row[0]), "title": row[1], "owner_agent_id": row[2],
            "dept": row[3], "status": row[4],
            "due_date": row[5].isoformat() if row[5] else None,
            "notes": row[6],
            "created_at": row[7].isoformat() if row[7] else None,
        }
    except Exception as exc:
        logger.error("[create_task] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.patch("/api/projects/{project_id}/tasks/{task_id}", tags=["Operations"],
           summary="Update task status/notes (sets completed_at on done)")
@limiter.limit("60/hour")
async def update_task(project_id: str, task_id: str, body: TaskUpdate, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
        tid = str(uuid.UUID(task_id))
    except ValueError:
        return JSONResponse({"error": "invalid id"}, status_code=400)
    try:
        updates = []
        params = {"pid": pid, "tid": tid}
        if body.status is not None:
            if body.status not in ("todo", "in_progress", "done", "blocked"):
                return JSONResponse({"error": f"invalid status: {body.status}"}, status_code=400)
            updates.append("status = :st")
            params["st"] = body.status
            if body.status == "done":
                updates.append("completed_at = NOW()")
        if body.notes is not None:
            updates.append("notes = :nt")
            params["nt"] = body.notes
        if not updates:
            return JSONResponse({"error": "no fields to update"}, status_code=400)

        set_clause = ", ".join(updates)
        with _get_sa_engine().begin() as conn:
            row = conn.execute(
                _sa_text(f"""
                    UPDATE project_tasks SET {set_clause}
                    WHERE id = :tid AND project_id = :pid
                    RETURNING id, title, status, completed_at, notes
                """),
                params,
            ).fetchone()
        if not row:
            return JSONResponse({"error": "task not found"}, status_code=404)
        return {
            "id": str(row[0]), "title": row[1], "status": row[2],
            "completed_at": row[3].isoformat() if row[3] else None,
            "notes": row[4],
        }
    except Exception as exc:
        logger.error("[update_task] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.patch("/api/projects/{project_id}/status", tags=["Operations"],
           summary="Update project status (writes deal_velocity row, Discord on loi/signed)")
@limiter.limit("30/hour")
async def update_project_status(project_id: str, body: ProjectStatusUpdate, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
    except ValueError:
        return JSONResponse({"error": "invalid project_id"}, status_code=400)

    new_status = body.status.lower()
    if new_status not in _VALID_PROJECT_STATUSES:
        return JSONResponse({"error": f"invalid status: {new_status}"}, status_code=400)

    try:
        with _get_sa_engine().begin() as conn:
            current = conn.execute(
                _sa_text("SELECT id, status, name, market, survey_no, created_at FROM projects WHERE id = :pid"),
                {"pid": pid},
            ).fetchone()
            if not current:
                return JSONResponse({"error": "project not found"}, status_code=404)

            old_status = str(current[1] or "lead")
            market_str = str(current[3] or "")
            survey_str = str(current[4] or "")

            # Guard: reject backward stage transitions
            if old_status != new_status and old_status != "paused":
                allowed = _VALID_TRANSITIONS.get(old_status, set())
                if new_status not in allowed:
                    return JSONResponse(
                        {"error": f"cannot transition from '{old_status}' to '{new_status}'"},
                        status_code=400,
                    )

            created = current[5]
            days_elapsed = 0
            if created:
                from datetime import timezone
                delta = datetime.now(timezone.utc) - created
                days_elapsed = delta.days

            if old_status != new_status:
                conn.execute(
                    _sa_text("""
                        INSERT INTO deal_velocity (project_id, from_status, to_status, days_elapsed)
                        VALUES (:pid, :from_st, :to_st, :days)
                    """),
                    {"pid": pid, "from_st": old_status, "to_st": new_status,
                     "days": days_elapsed},
                )

                if new_status == "delivered":
                    conn.execute(
                        _sa_text("UPDATE projects SET actual_close_date = CURRENT_DATE WHERE id = :pid"),
                        {"pid": pid},
                    )

            row = conn.execute(
                _sa_text("""
                    UPDATE projects SET status = :st, updated_at = NOW()
                    WHERE id = :pid
                    RETURNING id, name, market, survey_no, status, notes, created_at, updated_at
                """),
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
            "id": str(row[0]), "name": row[1], "market": row[2],
            "survey_no": row[3], "status": row[4], "notes": row[5],
            "created_at": row[6].isoformat() if row[6] else None,
            "updated_at": row[7].isoformat() if row[7] else None,
        }
    except Exception as exc:
        logger.error("[update_project_status] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/projects/{project_id}/velocity", tags=["Operations"],
         summary="Get deal velocity timeline for a project")
async def get_velocity(project_id: str, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
    except ValueError:
        return JSONResponse({"error": "invalid project_id"}, status_code=400)
    try:
        with _get_sa_engine().connect() as conn:
            proj = conn.execute(
                _sa_text("SELECT id, status, created_at FROM projects WHERE id = :pid"),
                {"pid": pid},
            ).fetchone()
            if not proj:
                return JSONResponse({"error": "project not found"}, status_code=404)

            rows = conn.execute(
                _sa_text("""
                    SELECT from_status, to_status, days_elapsed, transitioned_at
                    FROM deal_velocity WHERE project_id = :pid
                    ORDER BY transitioned_at ASC
                """),
                {"pid": pid},
            ).fetchall()

        stages = []
        for r in rows:
            stages.append({
                "from_status": r[0], "to_status": r[1],
                "days_elapsed": int(r[2]) if r[2] else 0,
                "transitioned_at": r[3].isoformat() if r[3] else None,
            })

        created = proj[2]
        current_stage_days = 0
        if created:
            from datetime import timezone as _tz
            delta = datetime.now(_tz.utc) - created
            current_stage_days = delta.days

        return {
            "stages": stages,
            "current_stage": str(proj[1] or "lead"),
            "current_stage_days": current_stage_days,
        }
    except Exception as exc:
        logger.error("[get_velocity] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.delete("/api/projects/{project_id}/tasks/{task_id}", tags=["Operations"],
            summary="Delete a task")
@limiter.limit("30/hour")
async def delete_task(project_id: str, task_id: str, request: Request):
    try:
        pid = str(uuid.UUID(project_id))
        tid = str(uuid.UUID(task_id))
    except ValueError:
        return JSONResponse({"error": "invalid id"}, status_code=400)
    try:
        with _get_sa_engine().begin() as conn:
            result = conn.execute(
                _sa_text("DELETE FROM project_tasks WHERE id = :tid AND project_id = :pid"),
                {"pid": pid, "tid": tid},
            )
            if result.rowcount == 0:
                return JSONResponse({"error": "task not found"}, status_code=404)
        return {"status": "deleted", "id": task_id}
    except Exception as exc:
        logger.error("[delete_task] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── LLM Quota (T-924) ──────────────────────────────────────────────────────


@app.get(
    "/api/llm/quota",
    tags=["Observability"],
    summary="LLM daily token usage per provider",
)
@limiter.limit("30/minute")
async def llm_quota(request: Request):
    from datetime import date

    today = date.today().isoformat()
    providers = [
        "groq",
        "cerebras",
        "gemini",
        "nvidia",
        "sambanova",
        "cloudflare",
        "openrouter",
    ]
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


# ── PR & Brand Department (Sprint 53 — GATE-61) ──────────────────────────────


class ContentGenerateRequest(BaseModel):
    market: str
    survey_no: str
    deal_type: str = "compare"
    job_id: str | None = None


class ContentGenerateResponse(BaseModel):
    job_id: str
    status: str
    linkedin_post: str | None = None
    instagram_caption: str | None = None
    project_brief_sections: list[dict] | None = None
    investor_narrative: str | None = None
    key_differentiators: list[str] | None = None
    email_subject: str | None = None
    project_tagline: str | None = None
    target_segment: str | None = None
    risk_acknowledgements: list[str] | None = None
    generated_at: str | None = None


@app.post(
    "/api/content/generate",
    response_model=ContentGenerateResponse,
    tags=["PR & Brand"],
    summary="Generate brand content (LinkedIn, Instagram, narrative) from IntelPackage",
    responses={400: {"model": ErrorResponse}},
)
@limiter.limit("5/hour")
async def content_generate(request: Request):
    """Run PR Head + Content Writer pipeline to produce investor-ready content.
    Optionally reuse a completed evaluate job_id for context.
    """
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
        return JSONResponse(
            {"error": "market and survey_no are required"}, status_code=400
        )

    from utils.content_pipeline import ContentPipeline

    pipeline = ContentPipeline()

    result = await asyncio.to_thread(
        pipeline.run,
        market=market,
        survey_no=survey_no,
        deal_type=deal_type,
        job_id=job_id,
    )
    return result


# ── Landowner CRM (Sprint 56 — T-986) ──────────────────────────────────────


class LandownerCreate(BaseModel):
    survey_no: str
    market: str
    owner_name: str
    contact_phone: str | None = None
    contact_type: str | None = None
    approach_status: str | None = None
    ask_psf: float | None = None
    notes: str | None = None


class LandownerUpdate(BaseModel):
    owner_name: str | None = None
    contact_phone: str | None = None
    contact_type: str | None = None
    approach_status: str | None = None
    ask_psf: float | None = None
    notes: str | None = None


_VALID_CONTACT_TYPES = {"primary", "agent", "legal_heir", "power_of_attorney"}
_VALID_APPROACH_STATUSES = {"cold", "warm", "meeting_done", "mou", "loi", "closed_won", "closed_lost"}


_LANDOWNER_COLS = (
    "id, survey_no, market, owner_name, contact_phone, "
    "contact_type, approach_status, ask_psf, notes, created_at, updated_at"
)


def _row_to_landowner_dict(r) -> dict:
    return {
        "id": str(r[0]),
        "survey_no": r[1],
        "market": r[2],
        "owner_name": r[3],
        "contact_phone": r[4],
        "contact_type": r[5],
        "approach_status": r[6],
        "ask_psf": float(r[7]) if r[7] else None,
        "notes": r[8],
        "created_at": r[9].isoformat() if r[9] else None,
        "updated_at": r[10].isoformat() if r[10] else None,
    }


def _fire_landowner_discord(status: str, survey_no: str, market: str, owner_name: str,
                              ask_psf: float | None, notes: str | None) -> None:
    if status not in ("mou", "loi"):
        return
    from utils.discord_notifier import send_landowner_alert
    send_landowner_alert(status, survey_no, market, owner_name, ask_psf, notes)


@app.post("/api/landowners", tags=["Landowner CRM"], status_code=201,
          summary="Create a new landowner contact")
@limiter.limit("30/minute")
async def create_landowner(body: LandownerCreate, request: Request):
    if body.contact_type and body.contact_type not in _VALID_CONTACT_TYPES:
        return JSONResponse({"error": f"invalid contact_type: {body.contact_type}"}, status_code=400)
    status = body.approach_status or "cold"
    if status not in _VALID_APPROACH_STATUSES:
        return JSONResponse({"error": f"invalid approach_status: {status}"}, status_code=400)
    try:
        with _get_sa_engine().begin() as conn:
            result = conn.execute(
                _sa_text(f"""INSERT INTO landowner_contacts
                    (survey_no, market, owner_name, contact_phone, contact_type, approach_status, ask_psf, notes)
                    VALUES (:sn, :mkt, :on, :cp, :ct, :st, :ap, :nt)
                    RETURNING {_LANDOWNER_COLS}"""),
                {"sn": body.survey_no, "mkt": body.market, "on": body.owner_name,
                 "cp": body.contact_phone, "ct": body.contact_type or "primary",
                 "st": status, "ap": body.ask_psf, "nt": body.notes},
            )
            row = result.fetchone()
        _fire_landowner_discord(status, body.survey_no, body.market, body.owner_name,
                                body.ask_psf, body.notes)
        return _row_to_landowner_dict(row)
    except Exception as exc:
        logger.error("[create_landowner] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/landowners", tags=["Landowner CRM"],
         summary="List landowner contacts with filters")
@limiter.limit("60/minute")
async def list_landowners(
    request: Request,
    market: str = Query(default=None),
    status: str = Query(default=None),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=50, ge=1, le=200, description="Items per page"),
):
    try:
        with _get_sa_engine().connect() as conn:
            where_parts = []
            params = {}
            if market:
                where_parts.append("lc.market ILIKE :mkt")
                params["mkt"] = f"%{market}%"
            if status:
                where_parts.append("lc.approach_status = :st")
                params["st"] = status
            where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

            count_row = conn.execute(
                _sa_text(f"SELECT COUNT(*) FROM landowner_contacts lc {where_sql}"),
                params,
            ).scalar()
            total = count_row or 0

            offset = (page - 1) * per_page
            rows = conn.execute(
                _sa_text(f"""SELECT {_LANDOWNER_COLS}
                     FROM landowner_contacts lc
                     {where_sql}
                     ORDER BY lc.created_at DESC
                     LIMIT :lim OFFSET :off"""),
                {**params, "lim": per_page, "off": offset},
            ).fetchall()
        return {
            "data": [_row_to_landowner_dict(r) for r in rows],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": max(1, (total + per_page - 1) // per_page),
            },
        }
    except Exception as exc:
        logger.error("[list_landowners] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/landowners/pipeline", tags=["Landowner CRM"],
         summary="Pipeline summary: counts by status + avg ask_psf per market")
@limiter.limit("30/minute")
async def landowner_pipeline(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            by_status = conn.execute(
                _sa_text("""SELECT approach_status, COUNT(*) as cnt
                     FROM landowner_contacts
                     GROUP BY approach_status
                     ORDER BY cnt DESC"""),
            ).fetchall()
            by_market = conn.execute(
                _sa_text("""SELECT market, COUNT(*) as cnt, AVG(ask_psf) as avg_psf
                     FROM landowner_contacts
                     GROUP BY market
                     ORDER BY cnt DESC"""),
            ).fetchall()
        return {
            "by_status": {r[0]: r[1] for r in by_status},
            "by_market": {
                r[0]: {"count": r[1], "avg_ask_psf": round(float(r[2]), 2) if r[2] else None}
                for r in by_market
            },
        }
    except Exception as exc:
        logger.error("[landowner_pipeline] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/landowners/{landowner_id}", tags=["Landowner CRM"],
         summary="Get a single landowner contact")
@limiter.limit("60/minute")
async def get_landowner(landowner_id: str, request: Request):
    try:
        tid = str(uuid.UUID(landowner_id))
    except ValueError:
        return JSONResponse({"error": "invalid landowner_id"}, status_code=400)
    try:
        with _get_sa_engine().connect() as conn:
            row = conn.execute(
                _sa_text(f"SELECT {_LANDOWNER_COLS} FROM landowner_contacts WHERE id = :tid"),
                {"tid": tid},
            ).fetchone()
        if not row:
            return JSONResponse({"error": "landowner not found"}, status_code=404)
        return _row_to_landowner_dict(row)
    except Exception as exc:
        logger.error("[get_landowner] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.patch("/api/landowners/{landowner_id}", tags=["Landowner CRM"],
           summary="Update landowner contact fields")
@limiter.limit("30/minute")
async def update_landowner(landowner_id: str, body: LandownerUpdate, request: Request):
    try:
        tid = str(uuid.UUID(landowner_id))
    except ValueError:
        return JSONResponse({"error": "invalid landowner_id"}, status_code=400)
    try:
        with _get_sa_engine().begin() as conn:
            existing = conn.execute(
                _sa_text("SELECT id, survey_no, market, owner_name, approach_status, ask_psf FROM landowner_contacts WHERE id = :tid"),
                {"tid": tid},
            ).fetchone()
            if not existing:
                return JSONResponse({"error": "landowner not found"}, status_code=404)
            updates = []
            params = {}
            if body.owner_name is not None:
                updates.append("owner_name = :on")
                params["on"] = body.owner_name
            if body.contact_phone is not None:
                updates.append("contact_phone = :cp")
                params["cp"] = body.contact_phone
            if body.contact_type is not None:
                if body.contact_type not in _VALID_CONTACT_TYPES:
                    return JSONResponse({"error": f"invalid contact_type: {body.contact_type}"}, status_code=400)
                updates.append("contact_type = :ct")
                params["ct"] = body.contact_type
            if body.approach_status is not None:
                if body.approach_status not in _VALID_APPROACH_STATUSES:
                    return JSONResponse({"error": f"invalid approach_status: {body.approach_status}"}, status_code=400)
                updates.append("approach_status = :st")
                params["st"] = body.approach_status
            if body.ask_psf is not None:
                updates.append("ask_psf = :ap")
                params["ap"] = body.ask_psf
                new_ask_psf = body.ask_psf
            else:
                new_ask_psf = float(existing[5]) if existing[5] else None
            if body.notes is not None:
                updates.append("notes = :nt")
                params["nt"] = body.notes
            if not updates:
                return JSONResponse({"error": "no fields to update"}, status_code=400)
            updates.append("updated_at = NOW()")
            set_clause = ", ".join(updates)
            params["tid"] = tid
            row = conn.execute(
                _sa_text(f"UPDATE landowner_contacts SET {set_clause} WHERE id = :tid RETURNING {_LANDOWNER_COLS}"),
                params,
            ).fetchone()
        new_status = body.approach_status or existing[4]
        _fire_landowner_discord(new_status, existing[1], existing[2], existing[3],
                                new_ask_psf, body.notes)
        return _row_to_landowner_dict(row)
    except Exception as exc:
        logger.error("[update_landowner] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Demand Intelligence Panel ──────────────────────────────────────────────────


@app.get("/api/demand/{market}", tags=["Demand Intelligence"],
         summary="Demand signals for a market")
async def demand_api(market: str, request: Request):
    from intelligence.demand_intel import DemandIntel
    di = DemandIntel(caller="api")
    ds = di.get_signals(market)
    return {
        "market": ds.market,
        "market_found": ds.market_found,
        "collected_at": ds.collected_at,
        "avg_listing_psf": ds.avg_listing_psf,
        "median_listing_psf": ds.median_listing_psf,
        "listing_trend_30d_pct": ds.listing_trend_30d_pct,
        "listing_count_30d": ds.listing_count_30d,
        "absorption_pct": ds.absorption_pct,
        "months_of_supply": ds.months_of_supply,
        "demand_signal": ds.demand_signal,
        "demand_score": ds.demand_score,
        "demand_score_v2": ds.demand_score_v2,
        "ticket_size_median_cr": ds.ticket_size_median_cr,
        "days_on_market_p50": ds.days_on_market_p50,
        "config_absorption": ds.config_absorption,
        "absorption_trend": ds.absorption_trend,
        "days_on_market_by_config": ds.days_on_market_by_config,
        "avg_news_sentiment": ds.avg_news_sentiment,
        "kaveri_monthly_approvals": ds.kaveri_monthly_approvals,
        "signals": ds.signals,
    }


@app.get("/memory", tags=["Memory"], summary="Agent Memory Explorer dashboard panel")
def memory_explorer_panel(request: Request):
    return templates.TemplateResponse(request, "memory_explorer.html")


@app.get("/data-quality", tags=["Data Quality"], summary="Data Quality dashboard panel")
def data_quality_panel(request: Request):
    return templates.TemplateResponse(request, "data_quality.html")


@app.get("/demand", tags=["Demand Intelligence"],
         summary="Demand Intelligence dashboard panel")
def demand_panel(request: Request):
    return templates.TemplateResponse(request, "demand_intelligence.html")


# ── Projects Page (Sprint 58) ───────────────────────────────────────────────


@app.get("/projects", tags=["Operations"],
         summary="Operations Projects dashboard panel")
def projects_panel(request: Request):
    return templates.TemplateResponse(request, "projects.html")


# ── Content Studio Page ──────────────────────────────────────────────────────


@app.get("/content", tags=["PR & Brand"], summary="Content Studio dashboard panel")
def content_studio(request: Request):
    return templates.TemplateResponse(request, "content_studio.html")


# ── PR Studio Panel (Sprint 59) ─────────────────────────────────────────────


@app.get("/pr", tags=["PR & Brand"], summary="PR Studio dashboard panel")
def pr_studio(request: Request):
    return templates.TemplateResponse(request, "pr_studio.html")


@app.get("/api/pr/mentions", tags=["PR & Brand"],
         summary="Brand mentions + competitor launches for PR Studio")
@limiter.limit("30/minute")
async def pr_mentions(
    days: int = Query(default=7, description="Days to look back"),
    request: Request = None,
):
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

    return {
        "mentions": brand_mentions,
        "mention_count": len(brand_mentions),
        "competitor_launches": launches,
        "launch_count": len(launches),
        "days_window": days,
    }


# ── Process Audit Panel (Sprint 61) ──────────────────────────────────────────


@app.get("/process-audit", tags=["Process Automation"],
         summary="Process Audit dashboard panel")
def process_audit_panel(request: Request):
    import os as _os
    from pathlib import Path as _Path
    return templates.TemplateResponse(request, "process_audit.html", {
        "process_audit_dir": _Path(__file__).resolve().parent / "templates",
    })


@app.get("/api/process-audit/report", tags=["Process Automation"],
         summary="Latest BottleneckReport + ImprovementProposal")
@limiter.limit("30/minute")
async def process_audit_report(request: Request):
    from agents.log_analyst_agent import LogAnalystAgent
    from agents.efficiency_optimizer_agent import EfficiencyOptimizerAgent
    from agents.runbook_documenter_agent import RunbookDocumenterAgent
    from pathlib import Path
    import os

    log_agent = LogAnalystAgent()
    log_result = log_agent.run()
    report = log_result.get("report", {})

    eff_agent = EfficiencyOptimizerAgent()
    eff_result = eff_agent.run(bottleneck_report=report)
    proposal = eff_result.get("proposal", {})

    doc_agent = RunbookDocumenterAgent()
    doc_result = doc_agent.run(bottleneck_report=report, improvement_proposal=proposal)
    runbook_path = doc_result.get("path", "")

    sol_dir = Path(__file__).resolve().parent.parent / "docs" / "solutions" / "process-automation"
    runbooks = []
    if sol_dir.exists():
        runbooks = sorted([str(p.relative_to(sol_dir.parent.parent)) for p in sol_dir.glob("*.md")])

    return {
        "report": report,
        "proposal": proposal,
        "runbook_path": runbook_path,
        "runbooks": runbooks,
    }


# ── Portfolio (LLS Track Record) ──────────────────────────────────────────────

_PORTFOLIO_COLS = (
    "id, project_name, location, market, segment, total_units, sold_units, "
    "launched_date, possession_date, land_cost_cr, gdv_cr, realized_irr_pct, "
    "status, rera_no, notes, created_at"
)


def _row_to_portfolio_dict(r) -> dict:
    return {
        "id": str(r[0]),
        "project_name": r[1],
        "location": r[2],
        "market": r[3],
        "segment": r[4],
        "total_units": r[5],
        "sold_units": r[6],
        "launched_date": r[7].isoformat() if r[7] else None,
        "possession_date": r[8].isoformat() if r[8] else None,
        "land_cost_cr": float(r[9]) if r[9] else None,
        "gdv_cr": float(r[10]) if r[10] else None,
        "realized_irr_pct": float(r[11]) if r[11] else None,
        "status": r[12],
        "rera_no": r[13],
        "notes": (r[14][:2000] + "...") if r[14] and len(r[14]) > 2000 else r[14],
        "created_at": r[15].isoformat() if r[15] else None,
    }


@app.get("/api/portfolio", tags=["Portfolio"],
         summary="List LLS portfolio (ordered by launch date DESC)")
@limiter.limit("60/minute")
async def list_portfolio(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text(f"SELECT {_PORTFOLIO_COLS} FROM lls_portfolio ORDER BY launched_date DESC"),
            ).fetchall()
        items = [_row_to_portfolio_dict(r) for r in rows]
        logger.info("[list_portfolio] returned %d projects", len(items))
        return {"data": items}
    except Exception as exc:
        logger.error("[list_portfolio] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/portfolio/summary", tags=["Portfolio"],
         summary="LLS portfolio summary stats (single-query batched)")
@limiter.limit("60/minute")
async def portfolio_summary(request: Request):
    try:
        with _get_sa_engine().connect() as conn:
            agg = conn.execute(
                _sa_text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'delivered') AS delivered,
                        COALESCE(AVG(realized_irr_pct) FILTER (WHERE status = 'delivered' AND realized_irr_pct IS NOT NULL), 0) AS avg_irr,
                        COALESCE(SUM(total_units) FILTER (WHERE status = 'delivered'), 0) AS total_units
                    FROM lls_portfolio
                """),
            ).fetchone()
            total = agg[0] or 0
            delivered = agg[1] or 0
            avg_irr = agg[2] or None
            total_units = agg[3] or 0
            market_rows = conn.execute(
                _sa_text("SELECT DISTINCT market FROM lls_portfolio WHERE market IS NOT NULL"),
            ).fetchall()
        markets = [r[0] for r in market_rows if r[0]]
        logger.info("[portfolio_summary] %d/%d delivered, %.1f%% avg IRR",
                     delivered, total, avg_irr or 0)
        return {
            "total_projects": total,
            "delivered_count": delivered,
            "total_delivered_sqft_est": total_units * 1200,
            "avg_realized_irr_pct": round(float(avg_irr), 2) if avg_irr else None,
            "markets_covered": markets,
        }
    except Exception as exc:
        logger.error("[portfolio_summary] %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Telegram Webhook ──────────────────────────────────────────────────────────


def _send_telegram_message(chat_id: int | str, text: str) -> None:
    from config.settings import TELEGRAM_BOT_TOKEN as _tg_token
    if not _tg_token:
        logger.warning("[Telegram] TELEGRAM_BOT_TOKEN not set — cannot send reply")
        return
    try:
        import requests as _req
        _req.post(
            f"https://api.telegram.org/bot{_tg_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
    except Exception as exc:
        logger.error("[Telegram] sendMessage failed: %s", exc)


@app.post("/api/telegram/webhook", tags=["Telegram"], summary="Telegram bot webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram updates. Validated by X-Telegram-Bot-Api-Secret-Token header."""
    import asyncio
    from config.settings import TELEGRAM_WEBHOOK_SECRET as _tg_secret
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if _tg_secret and secret != _tg_secret:
        return JSONResponse({"error": "unauthorized"}, status_code=403)

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
        # Run blocking httpx.post in a thread — must not block the event loop.
        result = await asyncio.to_thread(dispatch_evaluation, parsed)
        status = result.get("status", "unknown")
        job_id = result.get("job_id", "")
        if status in ("running", "completed"):
            reply = (
                f"Evaluating {parsed.market} "
                f"({parsed.area_acres:.1f}ac @ ₹{parsed.ask_psf:.0f} PSF, {parsed.deal_type}). "
                f"Job: {job_id or 'queued'}."
            )
        else:
            reply = (
                f"Evaluation queued for {parsed.market}. "
                f"Error: {result.get('error', 'unknown')[:100]}"
            )
    else:
        reply = (
            f"Confidence {parsed.confidence:.0%} — too low to evaluate.\n"
            f"Include: market (Yelahanka/Devanahalli/Hebbal), area (acres or sqft), "
            f"ask PSF or crore price, deal type (JD/JV/purchase)."
        )

    # Run blocking requests.post in a thread — must not block the event loop.
    await asyncio.to_thread(_send_telegram_message, chat_id, reply)
    logger.info(
        "[Telegram] webhook: market=%s conf=%.2f", parsed.market, parsed.confidence
    )
    return JSONResponse({"ok": True})


# ── GCC Demand Scout routes (Sprint 67 — GATE-71) ────────────────────────────

@app.get("/api/gcc/events")
async def gcc_events(
    request: Request,
    market: str | None = Query(None, description="Filter by market (Yelahanka / Devanahalli / Hebbal)"),
    corridor: str | None = Query(None, description="Filter by corridor slug"),
    maturity: str | None = Query(None, description="Comma-separated maturity levels e.g. 1,2"),
    include_negative: bool = Query(True),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List GCC demand events with optional corridor / maturity filters.

    Returns:
        { "events": [...], "total": N, "gcc_north_norm": {market: float} }
    """
    try:
        from intelligence.gcc_intel import GCCIntel, _MARKET_TO_CORRIDOR

        maturity_levels: list[int] | None = None
        if maturity:
            try:
                maturity_levels = [int(x.strip()) for x in maturity.split(",") if x.strip()]
            except ValueError:
                return JSONResponse({"error": "maturity must be comma-separated integers"}, status_code=400)

        corridors: list[str] | None = None
        if corridor:
            corridors = [c.strip() for c in corridor.split(",") if c.strip()]

        intel = GCCIntel()
        events = intel.get_events(
            market=market,
            corridors=corridors,
            maturity_levels=maturity_levels,
            include_negative=include_negative,
            limit=limit,
            offset=offset,
        )

        # Per-market gcc_north_norm summary
        north_scores: dict[str, float] = {}
        for mkt in ("Yelahanka", "Devanahalli", "Hebbal"):
            try:
                r = intel.get_gcc_score(mkt)
                north_scores[mkt] = r.gcc_north_norm
            except Exception:
                pass

        return JSONResponse({
            "events": [
                {
                    "id": e.id,
                    "canonical_id": e.canonical_id,
                    "company": e.company,
                    "sector": e.sector,
                    "country_of_origin": e.country_of_origin,
                    "bengaluru_location": e.bengaluru_location,
                    "nearest_corridor": e.nearest_corridor,
                    "entrant_type": e.entrant_type,
                    "work_model": e.work_model,
                    "signal_maturity_level": e.signal_maturity_level,
                    "is_negative_signal": e.is_negative_signal,
                    "north_bengaluru_impact_score": e.north_bengaluru_impact_score,
                    "planned_headcount": e.planned_headcount,
                    "median_ctc_l": e.median_ctc_l,
                    "gcc_signal_score": e.gcc_signal_score,
                    "primary_housing_segment": e.primary_housing_segment,
                    "time_horizon": e.time_horizon,
                    "estimated_demand_units": e.estimated_demand_units,
                    "source_name": e.source_name,
                    "source_reliability": e.source_reliability,
                    "announced_at": str(e.announced_at) if e.announced_at else None,
                    "discord_alert_fired": e.discord_alert_fired,
                }
                for e in events
            ],
            "total": len(events),
            "gcc_north_norm": north_scores,
        })
    except Exception as exc:
        logger.warning("[API] /api/gcc/events failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/gcc/north-score")
async def gcc_north_score(request: Request):
    """Return gcc_north_norm for all three primary markets.

    This is the value that feeds demand_score_v2 as the 5th (GCC) component.
    Rising norm + flat absorption = demand accumulating before listing data shows it.

    Returns:
        {
          "Yelahanka": { "gcc_north_norm": 0.42, "event_count_12m": 4, ... },
          ...
        }
    """
    try:
        from intelligence.gcc_intel import GCCIntel
        intel = GCCIntel()
        result = {}
        for mkt in ("Yelahanka", "Devanahalli", "Hebbal"):
            r = intel.get_gcc_score(mkt)
            result[mkt] = {
                "gcc_north_norm": r.gcc_north_norm,
                "corridor": r.corridor,
                "event_count_12m": r.event_count_12m,
                "event_count_90d": r.event_count_90d,
                "total_headcount_12m": r.total_headcount_12m,
                "avg_gcc_signal_score": r.avg_gcc_signal_score,
                "top_sectors": r.top_sectors,
                "dominant_housing_segment": r.dominant_housing_segment,
                "has_level1_signal": r.has_level1_signal,
                "negative_suppressor_applied": r.negative_suppressor_applied,
                "signals": r.signals,
                "collected_at": r.collected_at,
            }
        return JSONResponse(result)
    except Exception as exc:
        logger.warning("[API] /api/gcc/north-score failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/govt/events", tags=["Govt/Policy"],
         summary="List government/infrastructure/policy events")
@limiter.limit("30/minute")
async def govt_events(
    request: Request,
    market: str | None = Query(None, description="Filter by market"),
    category: str | None = Query(None, description="Filter by category (infrastructure/govt_project/policy)"),
    signal: str | None = Query(None, description="Filter by signal_strength (high/emerging/risk)"),
    limit: int = Query(20, ge=1, le=100),
):
    """List govt/policy events with optional filters."""
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        where_clauses = []
        params: dict = {}

        if category:
            where_clauses.append("category = :category")
            params["category"] = category
        if signal:
            where_clauses.append("signal_strength = :signal")
            params["signal"] = signal
        if market:
            where_clauses.append(":market = ANY(micro_markets)")
            params["market"] = market

        where_sql = " AND ".join(where_clauses)
        if where_sql:
            where_sql = "WHERE " + where_sql

        engine = get_engine()
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT id, headline, category, subcategory, location_text,
                       micro_markets, investment_cr, stage, impact_score,
                       signal_strength, time_horizon, actionability,
                       summary, why_it_matters, source_urls,
                       published_date, is_north_bengaluru, scraped_at
                FROM govt_policy_events
                {where_sql}
                ORDER BY impact_score DESC NULLS LAST, scraped_at DESC
                LIMIT :lim
            """), {**params, "lim": limit}).fetchall()

        nb_count = sum(1 for r in rows if r[16])
        events = []
        for r in rows:
            events.append({
                "id": r[0],
                "headline": r[1],
                "category": r[2],
                "subcategory": r[3],
                "location_text": r[4],
                "micro_markets": r[5] or [],
                "investment_cr": float(r[6]) if r[6] else None,
                "stage": r[7],
                "impact_score": r[8],
                "signal_strength": r[9],
                "time_horizon": r[10],
                "actionability": r[11],
                "summary": r[12],
                "why_it_matters": r[13],
                "source_urls": r[14] or [],
                "published_date": str(r[15]) if r[15] else None,
                "is_north_bengaluru": bool(r[16]),
                "scraped_at": str(r[17]) if r[17] else None,
            })

        return JSONResponse({
            "events": events,
            "total": len(events),
            "north_bengaluru_count": nb_count,
        })
    except Exception as exc:
        logger.warning("[API] /api/govt/events failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/govt/north-score", tags=["Govt/Policy"],
         summary="North Bengaluru govt/infra/policy pipeline score")
@limiter.limit("30/minute")
async def govt_north_score(request: Request):
    """Return north_bengaluru_score — the value feeding demand_score_v2.

    Returns:
        {
            "north_bengaluru_score": float [0,1],
            "high_opportunity_count": int,
            "risk_count": int,
            "top_events": [...],
            "computed_at": ISO8601
        }
    """
    try:
        from intelligence.govt_policy_intel import GovtPolicyIntel
        intel = GovtPolicyIntel(caller="api")
        result = intel.compute("north_bengaluru_aggregate")
        return JSONResponse({
            "north_bengaluru_score": result.north_bengaluru_score,
            "high_opportunity_count": result.high_opportunity_count,
            "risk_count": result.risk_count,
            "top_infra_events": result.top_infra_events,
            "top_policy_events": result.top_policy_events,
            "computed_at": result.computed_at,
        })
    except Exception as exc:
        logger.warning("[API] /api/govt/north-score failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/govt/digest", tags=["Govt/Policy"],
         summary="Weekly govt/policy digest for North Bengaluru")
@limiter.limit("30/minute")
async def govt_digest(request: Request):
    """Return LLM-generated weekly digest of govt/policy developments."""
    try:
        from intelligence.govt_policy_intel import GovtPolicyIntel
        intel = GovtPolicyIntel(caller="api")
        result = intel.compute("north_bengaluru_aggregate")
        return JSONResponse({
            "digest": result.weekly_digest,
            "computed_at": result.computed_at,
        })
    except Exception as exc:
        logger.warning("[API] /api/govt/digest failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/govt", tags=["Govt/Policy"],
         summary="Govt/Policy dashboard page")
@limiter.limit("20/minute")
async def govt_policy_panel(request: Request):
    """Render govt policy intelligence dashboard panel."""
    try:
        return templates.TemplateResponse(request, "govt_policy.html")
    except Exception as exc:
        logger.error("[govt_policy_panel] %s", exc)
        return JSONResponse({"error": "template not found"}, status_code=500)


@app.get("/api/distress/signals")
async def distress_signals(
    request: Request,
    market: str = Query("Yelahanka", description="Market name"),
    limit: int = Query(50, ge=1, le=200),
):
    """List developer distress signals for a market."""
    market = (market or "").strip()
    if not market:
        return JSONResponse({"error": "market is required"}, status_code=400)
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text(
                    """
                    SELECT developer_name, market, signal_type, stall_count, stall_ratio,
                           mention_count, distress_score, detected_at
                    FROM developer_distress_signals
                    WHERE market = :market
                    ORDER BY detected_at DESC, distress_score DESC, developer_name ASC
                    LIMIT :limit
                    """
                ),
                {"market": market, "limit": limit},
            ).fetchall()
        return JSONResponse({
            "market": market,
            "count": len(rows),
            "signals": [
                {
                    "developer_name": row.developer_name,
                    "market": row.market,
                    "signal_type": row.signal_type,
                    "stall_count": int(row.stall_count or 0),
                    "stall_ratio": float(row.stall_ratio or 0.0),
                    "mention_count": int(row.mention_count or 0),
                    "distress_score": float(row.distress_score or 0.0),
                    "detected_at": row.detected_at.isoformat() if row.detected_at else None,
                }
                for row in rows
            ],
        })
    except Exception as exc:
        logger.warning("[API] /api/distress/signals failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/market/supply", tags=["Market"],
         summary="Pipeline supply for a market")
async def market_supply(
    request: Request,
    market: str = Query("Yelahanka", description="Market name"),
):
    """Return total pipeline supply units and per-record breakdown."""
    market = (market or "").strip()
    if not market:
        return JSONResponse({"error": "market is required"}, status_code=400)
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT project_name, developer_name, estimated_units,
                           estimated_acres, source, approval_date,
                           expected_completion_year, raw_snippet, created_at
                    FROM supply_pipeline
                    WHERE market ILIKE :market
                    ORDER BY created_at DESC, estimated_units DESC
                    LIMIT 100
                """),
                {"market": f"%{market}%"},
            ).fetchall()
            total = conn.execute(
                _sa_text("""
                    SELECT COALESCE(SUM(estimated_units), 0)
                    FROM supply_pipeline WHERE market ILIKE :market
                """),
                {"market": f"%{market}%"},
            ).scalar() or 0
        records = []
        for row in rows:
            records.append({
                "project_name": row.project_name,
                "developer_name": row.developer_name,
                "estimated_units": int(row.estimated_units or 0),
                "estimated_acres": float(row.estimated_acres) if row.estimated_acres else None,
                "source": row.source,
                "approval_date": str(row.approval_date) if row.approval_date else None,
                "expected_completion_year": row.expected_completion_year,
                "raw_snippet": row.raw_snippet,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            })
        return JSONResponse({
            "market": market,
            "total_pipeline_units": int(total),
            "count": len(records),
            "records": records,
        })
    except Exception as exc:
        logger.warning("[API] /api/market/supply failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/market/forecast/{market}", tags=["Market"],
         summary="PSF forecast for a market (3/6/12-month horizons)")
@limiter.limit("30/hour")
async def market_forecast(
    market: str,
    request: Request = None,
):
    """Return latest PSF forecast from market_forecasts table.
    Falls back to on-demand PSFForecaster call if no rows exist."""
    from utils.psf_forecaster import PSFForecaster
    from config.settings import TARGET_MARKETS as _VALID_MARKETS
    market = (market or "").strip()
    if not market:
        return JSONResponse({"error": "market is required"}, status_code=400)
    valid = [m.strip().lower() for m in _VALID_MARKETS]
    if market.lower() not in valid:
        return JSONResponse(
            {"error": f"Unknown market '{market}'. Valid: {sorted(set(m.strip() for m in _VALID_MARKETS))}"},
            status_code=400,
        )
    try:
        with _get_sa_engine().connect() as conn:
            rows = conn.execute(
                _sa_text("""
                    SELECT horizon_months, current_psf, forecast_psf,
                           conf_low, conf_high, trend_direction,
                           slope_pct_per_month, data_points, mae_pct,
                           model_version, forecast_date
                    FROM market_forecasts
                    WHERE market ILIKE :market
                    ORDER BY forecast_date DESC, horizon_months
                    LIMIT 3
                """),
                {"market": f"%{market}%"},
            ).fetchall()

        if rows:
            best = rows[0]
            resp = {
                "market": market,
                "as_of": str(best.forecast_date) if best.forecast_date else "",
                "trend_direction": best.trend_direction or "unknown",
                "current_psf": float(best.current_psf) if best.current_psf else 0,
                "slope_pct_per_month": float(best.slope_pct_per_month) if best.slope_pct_per_month else 0,
                "data_points": best.data_points or 0,
                "mae_pct": float(best.mae_pct) if best.mae_pct else 0,
                "model_version": best.model_version or "linear_v1",
            }
            for r in rows:
                h = int(r.horizon_months)
                resp[f"forecast_{h}m"] = float(r.forecast_psf) if r.forecast_psf else 0
                resp[f"conf_low_{h}m"] = float(r.conf_low) if r.conf_low else 0
                resp[f"conf_high_{h}m"] = float(r.conf_high) if r.conf_high else 0
            return resp

        fallback = PSFForecaster().forecast(market)
        return {
            "market": fallback.market,
            "as_of": fallback.as_of,
            "trend_direction": fallback.trend_direction,
            "current_psf": fallback.current_psf,
            "forecast_3m": fallback.forecast_3m,
            "forecast_6m": fallback.forecast_6m,
            "forecast_12m": fallback.forecast_12m,
            "conf_low_3m": fallback.conf_low_3m,
            "conf_high_3m": fallback.conf_high_3m,
            "conf_low_6m": fallback.conf_low_6m,
            "conf_high_6m": fallback.conf_high_6m,
            "conf_low_12m": fallback.conf_low_12m,
            "conf_high_12m": fallback.conf_high_12m,
            "mae_pct": fallback.mae_pct,
            "data_points": fallback.data_points,
            "model_version": fallback.model_version,
        }
    except Exception as exc:
        logger.warning("[API] /api/market/forecast/{} failed: {}", market, exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/gcc/events")
async def gcc_create_event(request: Request):
    """Manually ingest a single GCC event.

    Body: GCC event dict matching gcc_events schema. gcc_signal_score is
    computed server-side from sub-scores if not supplied.

    Returns: { "canonical_id": "...", "gcc_signal_score": 7.2 }
    """
    try:
        body: dict = await request.json()
    except Exception:
        body = {}

    if not body.get("company") or not body.get("bengaluru_location"):
        return JSONResponse(
            {"error": "company and bengaluru_location are required"},
            status_code=400,
        )

    try:
        from ingest.plugins.gcc_plugin import (
            _make_canonical_id, _resolve_corridor, _compute_gcc_score,
            _CORRIDOR_NB_IMPACT,
        )
        from utils.db import get_engine
        from sqlalchemy import text as _t

        announced = body.get("announced_at") or str(__import__("datetime").date.today())
        cid = _make_canonical_id(
            body["company"],
            body.get("bengaluru_location", "Bengaluru"),
            announced,
        )

        corridor, nb_impact = _resolve_corridor(body.get("bengaluru_location", ""))
        if not body.get("nearest_corridor"):
            body["nearest_corridor"] = corridor
        if body.get("north_bengaluru_impact_score") is None:
            body["north_bengaluru_impact_score"] = nb_impact

        gcc_score = _compute_gcc_score(body)

        with get_engine().begin() as conn:
            conn.execute(_t("""
                INSERT INTO gcc_events (
                    canonical_id, company, sector, country_of_origin,
                    bengaluru_location, nearest_corridor, entrant_type,
                    work_model, signal_maturity_level, is_negative_signal,
                    north_bengaluru_impact_score, investment_cr,
                    planned_headcount, headcount_timeline_months,
                    median_ctc_l, office_sqft,
                    demand_creation_score, residential_impact_score,
                    appreciation_impact_score, rental_impact_score,
                    gcc_signal_score, primary_housing_segment,
                    time_horizon, source_name, source_reliability,
                    announced_at, discord_alert_fired
                ) VALUES (
                    :canonical_id, :company, :sector, :country_of_origin,
                    :bengaluru_location, :nearest_corridor, :entrant_type,
                    :work_model, :signal_maturity_level, :is_negative_signal,
                    :nb_impact, :investment_cr,
                    :planned_headcount, :headcount_timeline_months,
                    :median_ctc_l, :office_sqft,
                    :demand_creation_score, :residential_impact_score,
                    :appreciation_impact_score, :rental_impact_score,
                    :gcc_signal_score, :primary_housing_segment,
                    :time_horizon, :source_name, :source_reliability,
                    CAST(:announced_at AS date), FALSE
                )
                ON CONFLICT (canonical_id) DO NOTHING
            """), {
                "canonical_id": cid,
                "company": body["company"],
                "sector": body.get("sector"),
                "country_of_origin": body.get("country_of_origin"),
                "bengaluru_location": body.get("bengaluru_location"),
                "nearest_corridor": body.get("nearest_corridor"),
                "entrant_type": body.get("entrant_type", "EXPANSION"),
                "work_model": body.get("work_model", "HYBRID"),
                "signal_maturity_level": body.get("signal_maturity_level", 3),
                "is_negative_signal": bool(body.get("is_negative_signal", False)),
                "nb_impact": body["north_bengaluru_impact_score"],
                "investment_cr": body.get("investment_cr"),
                "planned_headcount": body.get("planned_headcount"),
                "headcount_timeline_months": body.get("headcount_timeline_months"),
                "median_ctc_l": body.get("median_ctc_l"),
                "office_sqft": body.get("office_sqft"),
                "demand_creation_score": body.get("demand_creation_score"),
                "residential_impact_score": body.get("residential_impact_score"),
                "appreciation_impact_score": body.get("appreciation_impact_score"),
                "rental_impact_score": body.get("rental_impact_score"),
                "gcc_signal_score": gcc_score,
                "primary_housing_segment": body.get("primary_housing_segment"),
                "time_horizon": body.get("time_horizon"),
                "source_name": body.get("source_name"),
                "source_reliability": body.get("source_reliability", "PRESS"),
                "announced_at": announced,
            })

        from intelligence.gcc_intel import GCCIntel
        for mkt in ("Yelahanka", "Devanahalli", "Hebbal"):
            GCCIntel().invalidate_cache(mkt)

        return JSONResponse(
            {"canonical_id": cid, "gcc_signal_score": gcc_score},
            status_code=201,
        )
    except Exception as exc:
        logger.warning("[API] POST /api/gcc/events failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Optimizer Routes (T-1005) ─────────────────────────────────────────────────


@app.get("/optimizer", tags=["Optimizer"], summary="Dashboard Optimizer Panel")
@limiter.limit("20/hour")
async def optimizer_panel(request: Request):
    """Render optimizer dashboard panel."""
    try:
        return templates.TemplateResponse(request, "optimizer.html")
    except Exception as exc:
        logger.error("[optimizer_panel] %s", exc)
        return JSONResponse({"error": "template not found"}, status_code=500)


@app.get("/api/optimizer/report", tags=["Optimizer"], summary="Latest optimizer report JSON")
@limiter.limit("20/hour")
async def optimizer_report(request: Request):
    """Return latest optimizer report as JSON."""
    try:
        from utils.optimizer_report import generate_report

        report = generate_report(7)
        return report.to_dict()
    except Exception as exc:
        logger.error("[optimizer_report] %s", exc)
        return JSONResponse({
            "report_date": "",
            "token_summary": [],
            "redundancy_findings": [],
            "cache_hit_rate": 0.0,
            "top_recommendation": "Unable to generate report - see logs",
            "auto_tasks_created": 0,
        })


# ── Shareholder Board Routes (Phase 14 - Sprint 62) ───────────────────────────


@app.post("/api/shareholders/trigger", tags=["Shareholders"],
          summary="Trigger quarterly board review")
@limiter.limit("5/hour")
async def trigger_shareholder_review(request: Request):
    """Trigger a quarterly board review. Creates session, runs shareholders, saves result."""
    from crews.shareholder_review import ShareholderBoardCrew
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    quarter = str(payload.get("quarter") or "").strip()
    trigger_reason = str(payload.get("trigger_reason") or "Manual trigger").strip()
    if not quarter:
        return JSONResponse({"error": "quarter required (e.g. Q2-2026)"}, status_code=400)

    import uuid as _uuid
    session_id = str(_uuid.uuid4())

    # Cooldown guard: prevent >1 concurrent trigger per quarter
    try:
        with _get_sa_engine().connect() as conn:
            active = conn.execute(
                _sa_text("SELECT COUNT(*) FROM shareholder_sessions "
                         "WHERE quarter = :q AND status IN ('pending','in_progress')"),
                {"q": quarter},
            ).scalar() or 0
            if active > 0:
                return JSONResponse({
                    "error": f"A review for {quarter} is already in progress. "
                             "Wait for it to complete before triggering another.",
                }, status_code=429)
    except Exception:
        pass

    try:
        with _get_sa_engine().begin() as conn:
            conn.execute(
                _sa_text("""
                    INSERT INTO shareholder_sessions
                    (id, session_type, quarter, trigger_reason, status, created_at)
                    VALUES (:id, 'quarterly_board', :quarter, :reason, 'in_progress', NOW())
                """),
                {"id": session_id, "quarter": quarter, "reason": trigger_reason},
            )
    except Exception as exc:
        logger.warning("[API] POST /api/shareholders/trigger session create failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)

    def _run_and_update():
        try:
            result = ShareholderBoardCrew.run_quarterly_review(quarter)
            letter_text = result.get("ceo_letter_text", "")
            letter_path = ShareholderBoardCrew.save_letter(session_id, letter_text)
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
                        "transcript": json.dumps({
                            "debate_triggered": result.get("debate_triggered", False),
                            "debate_round": result.get("debate_round"),
                        }),
                        "synthesis": result.get("ceo_letter_text", ""),
                        "verdict": result.get("quarter_verdict", ""),
                    },
                )
            logger.info("[Shareholders] Review complete: {} | letter={}", session_id, letter_path)
        except Exception as exc:
            logger.warning("[Shareholders] Review failed: {} | {}", session_id, exc)
            try:
                with _get_sa_engine().begin() as conn:
                    conn.execute(
                        _sa_text("UPDATE shareholder_sessions SET status = 'failed' WHERE id = :id"),
                        {"id": session_id},
                    )
            except Exception:
                pass

    import threading
    threading.Thread(target=_run_and_update, daemon=True).start()

    return JSONResponse({
        "session_id": session_id,
        "status": "in_progress",
        "quarter": quarter,
        "message": "Quarterly board review triggered. Check /shareholders for results.",
    }, status_code=202)


@app.get("/api/shareholders/sessions", tags=["Shareholders"],
         summary="List all shareholder sessions")
@limiter.limit("30/minute")
async def list_shareholder_sessions(
    request: Request,
    session_type: str | None = None,
    status: str | None = None,
    quarter: str | None = None,
):
    try:
        where_clauses = []
        params = {}
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
                _sa_text(f"""
                    SELECT id, session_type, quarter, trigger_reason, status, verdict,
                           created_at, completed_at
                    FROM shareholder_sessions
                    {where_sql}
                    ORDER BY created_at DESC
                    LIMIT 50
                """),
                params,
            ).fetchall()
        sessions = []
        for r in rows:
            sessions.append({
                "id": str(r[0]),
                "session_type": r[1],
                "quarter": r[2],
                "trigger_reason": r[3],
                "status": r[4],
                "verdict": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
                "completed_at": r[7].isoformat() if r[7] else None,
            })
        return {"data": sessions}
    except Exception as exc:
        logger.warning("[API] GET /api/shareholders/sessions failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/shareholders", tags=["Shareholders"], summary="Dashboard Shareholder Room Panel")
@limiter.limit("20/hour")
async def shareholders_panel(request: Request):
    """Render shareholder room dashboard panel."""
    try:
        return templates.TemplateResponse(request, "shareholders.html")
    except Exception as exc:
        logger.error("[shareholders_panel] %s", exc)
        return JSONResponse({"error": "template not found"}, status_code=500)


# ── Digest Routes (Sprint 76 — T-1058) ─────────────────────────────────────

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


@app.get("/api/digest/weekly", tags=["Digest"], summary="Weekly intelligence digest")
@limiter.limit("20/hour")
async def digest_weekly(request: Request, market: str = Query(default=None, description="Market name (omit for all)")):
    from utils.weekly_digest import WeeklyIntelDigest
    resolved = _resolve_market(market) if market else None
    if market and not resolved:
        digest_runs_total.labels(type="weekly", status="invalid_market").inc()
        return JSONResponse({"error": f"Unknown market '{market}'. Valid: {sorted(VALID_MARKETS_DIGEST)}"}, status_code=404)
    digest = WeeklyIntelDigest()
    if resolved:
        result = digest.build(resolved)
        digest_runs_total.labels(type="weekly", status="ok").inc()
        return {k: v for k, v in result.__dict__.items()}
    results = [digest.build(m) for m in _all_markets()]
    digest_runs_total.labels(type="weekly", status="ok").inc()
    return {"results": [{k: v for k, v in r.__dict__.items()} for r in results]}


@app.get("/api/digest/monthly", tags=["Digest"], summary="Monthly intelligence digest")
@limiter.limit("20/hour")
async def digest_monthly(request: Request, market: str = Query(default=None, description="Market name (omit for all)")):
    from utils.monthly_digest import MonthlyIntelDigest
    resolved = _resolve_market(market) if market else None
    if market and not resolved:
        digest_runs_total.labels(type="monthly", status="invalid_market").inc()
        return JSONResponse({"error": f"Unknown market '{market}'. Valid: {sorted(VALID_MARKETS_DIGEST)}"}, status_code=404)
    digest = MonthlyIntelDigest()
    if resolved:
        result = digest.build(resolved)
        digest_runs_total.labels(type="monthly", status="ok").inc()
        return {k: v for k, v in result.__dict__.items()}
    results = [digest.build(m) for m in _all_markets()]
    digest_runs_total.labels(type="monthly", status="ok").inc()
    return {"results": [{k: v for k, v in r.__dict__.items()} for r in results]}


@app.post("/api/digest/weekly/send", tags=["Digest"], summary="Send weekly digest to Discord now")
@limiter.limit("1/hour")
async def digest_weekly_send(request: Request):
    if not _is_run_api_authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from utils.weekly_digest import WeeklyIntelDigest
    from utils.discord_notifier import send_weekly_digest
    digest = WeeklyIntelDigest()
    results = [digest.build(m) for m in _all_markets()]
    send_weekly_digest(results)
    digest_runs_total.labels(type="weekly_send", status="sent").inc()
    return {"status": "sent", "markets": len(results)}


@app.post("/api/digest/monthly/send", tags=["Digest"], summary="Send monthly digest to Discord now")
@limiter.limit("1/hour")
async def digest_monthly_send(request: Request):
    if not _is_run_api_authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    from utils.monthly_digest import MonthlyIntelDigest
    from utils.discord_notifier import send_monthly_digest
    digest = MonthlyIntelDigest()
    results = [digest.build(m) for m in _all_markets()]
    send_monthly_digest(results)
    digest_runs_total.labels(type="monthly_send", status="sent").inc()
    return {"status": "sent", "markets": len(results)}


@app.get("/digest", response_class=HTMLResponse, tags=["Pages"], summary="Intelligence Digest panel")
async def digest_panel(request: Request):
    try:
        return templates.TemplateResponse(request, "digest.html")
    except Exception as exc:
        logger.error("[digest_panel] %s", exc)
        return JSONResponse({"error": "template not found"}, status_code=500)


if __name__ == "__main__":
    import uvicorn

    os.makedirs("/app/logs", exist_ok=True)
    logging.basicConfig(
        level=os.environ.get("DASHBOARD_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=8050, log_level="info")
