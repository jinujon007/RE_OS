"""
RE_OS Dashboard — FastAPI web server (v2)

Architecture:
  - FastAPI app with CORS middleware, rate limiting (slowapi/Redis), Prometheus
    /metrics endpoint, SSE log streaming, and security headers.
  - Auth: middleware-based API key gate (X-API-Key header only).
  - DB: SQLAlchemy engine from utils.db.get_engine() (pool_size=10, max_overflow=5).
  - Routes split into domain routers under dashboard/routers/.
  - Shared state, helpers, and constants in dashboard/state.py.
"""


import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager

# Import all metrics so they register with the global Prometheus REGISTRY.
from config.metrics import (  # noqa: F401
    pipeline_runs_total, llm_calls_total, db_upserts_total,
    scrape_success_total, scraper_runs_total, llm_router_fallbacks_total,
    pipeline_stage_duration_seconds, db_query_duration_seconds, digest_runs_total,
    audit_log_writes_total,
)

from dashboard.state import (
    limiter, templates, _is_run_api_authorized,
    _READ_ONLY_PATHS, _READ_ONLY_PREFIXES,
    _get_request_role, _has_role, _ADMIN_PATHS, _WRITE_PATHS,
    _err_resp,
)

# ── Audit log writer (background thread via executor) ────────────────────────

_AUDIT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="audit")
_AUDIT_ENGINE = None
_AUDIT_ENGINE_LOCK = threading.Lock()


def _get_audit_engine():
    global _AUDIT_ENGINE
    if _AUDIT_ENGINE is None:
        with _AUDIT_ENGINE_LOCK:
            if _AUDIT_ENGINE is None:
                from utils.db import get_engine
                _AUDIT_ENGINE = get_engine()
    return _AUDIT_ENGINE


def _write_audit_log(request_id: str, path: str, method: str,
                     role: str, status_code: int, duration_ms: int):
    try:
        engine = _get_audit_engine()
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO api_audit_log (request_id, path, method, role,
                                           status_code, duration_ms)
                VALUES (:rid, :path, :method, :role, :sc, :ms)
            """), {
                "rid": request_id, "path": path, "method": method,
                "role": role, "sc": status_code, "ms": duration_ms,
            })
        audit_log_writes_total.labels(role=role, outcome="success").inc()
        logger.debug("[audit] logged request_id=%s role=%s path=%s status=%d %dms",
                     request_id, role, path, status_code, duration_ms)
    except Exception:
        audit_log_writes_total.labels(role=role, outcome="error").inc()
        logger.warning("[audit] write failed request_id=%s path=%s %dms (non-blocking)",
                       request_id, path, duration_ms, exc_info=True)


# ── Startup validation ───────────────────────────────────────────────────────


def _validate_rbac_config():
    api_key = os.environ.get("DASHBOARD_API_KEY", "")
    read_key = os.environ.get("DASHBOARD_API_KEY_READ", "")
    admin_key = os.environ.get("DASHBOARD_API_KEY_ADMIN", "")
    if api_key and not read_key:
        logging.warning("DASHBOARD_API_KEY set but DASHBOARD_API_KEY_READ is empty "
                        "— read-only consumers will be unable to authenticate. "
                        "Set DASHBOARD_API_KEY_READ for VEL or other read-only integrations.")
    if api_key and not admin_key:
        logging.warning("DASHBOARD_API_KEY set but DASHBOARD_API_KEY_ADMIN is empty "
                        "— admin endpoints are accessible with write key. "
                        "Set DASHBOARD_API_KEY_ADMIN for privileged operations.")


_validate_rbac_config()


# ── FastAPI App ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(app_instance: FastAPI):
    """Startup: launch Redis health-check daemon thread (T-1262).

    Uses daemon thread — exits with the process, no cleanup needed.
    Wrapped in try/except so a failed health-thread start never crashes
    the app server (R1.5).
    """
    from dashboard.redis_health import _redis_health_loop
    try:
        _health_thread = threading.Thread(
            target=_redis_health_loop, daemon=True, name="redis-health"
        )
        _health_thread.start()
        logger.info("[lifespan] Redis health-check thread 'redis-health' started")
    except Exception:
        logger.exception("[lifespan] Failed to start Redis health-check thread — continuing without it")
    yield
    logger.debug("[lifespan] Shutting down")


app = FastAPI(
    title="RE_OS Dashboard",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=_lifespan,
)
# ── CORS ─────────────────────────────────────────────────────────────────────

_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "http://localhost:8050").split(",")
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

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Outer Middleware: Request ID + Security Headers + Audit Logging ───────────
# Registered FIRST → runs outermost.
# Sets request_id on every request (even unauthenticated ones) for traceability.
# After inner middlewares run, writes audit log for authenticated requests.
# MUST NOT raise on any path — errors in this middleware break ALL responses.


@app.middleware("http")
async def _add_request_id_and_headers(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    response.headers["X-Request-ID"] = request_id
    # Rate-limit headers are set by slowapi on @limiter.limit endpoints.
    # Omit fake defaults to avoid misleading consumers.
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
    role = getattr(request.state, "role", None)
    if role is not None:
        _AUDIT_EXECUTOR.submit(
            _write_audit_log,
            request_id=request_id,
            path=request.url.path,
            method=request.method,
            role=role,
            status_code=response.status_code,
            duration_ms=elapsed_ms,
        )
    return response


# ── Inner Middleware: RBAC Auth Gate ─────────────────────────────────────────
# Registered SECOND → runs AFTER _add_request_id_and_headers.
# Determines request role from X-API-Key header, stores in request.state.role.
# Enforces role hierarchy: read < write < admin against path classifications.
# Read-only paths (/health, /market/*) require ≥ read role.
# Mutating paths (evaluate, board/session) require ≥ write role.
# Admin paths (kill-criteria, audit/log) require admin role.
# Telegram webhook and OPTIONS are exempt from auth.
# Legacy /api/{path} routes pass through for 301 redirect to /api/v1/{path}.


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    if not path.startswith("/api") and path != "/metrics":
        return await call_next(request)
    if path == "/metrics":
        return await call_next(request)
    # Legacy /api/{path} routes (non-/api/v1) — pass through to redirect handler
    if path.startswith("/api/") and not path.startswith("/api/v1/"):
        if path not in ("/api/telegram/webhook",):
            return await call_next(request)
    # Telegram webhook — exempt from key auth (HMAC verified in handler)
    if path in ("/api/telegram/webhook", "/api/v1/telegram/webhook"):
        return await call_next(request)
    # Determine role for this request
    role = _get_request_role(request)
    request.state.role = role
    # Admin paths require admin role
    if path in _ADMIN_PATHS:
        if role == "admin":
            return await call_next(request)
        if role is None:
            return _err_resp("unauthorized", request, 401, "Auth")
        return JSONResponse(
            {"error": "insufficient_role", "required": "admin", "provided": role},
            status_code=403,
        )
    # Read-only paths require ≥ read role
    if path in _READ_ONLY_PATHS and request.method in ("GET", "HEAD", "OPTIONS"):
        if role is not None and _has_role(role, "read"):
            return await call_next(request)
        if role is None:
            return _require_key_auth(request)
        return JSONResponse(
            {"error": "insufficient_role", "required": "read", "provided": role},
            status_code=403,
        )
    if any(path.startswith(p) for p in _READ_ONLY_PREFIXES):
        if role is not None and _has_role(role, "read"):
            return await call_next(request)
        if role is None:
            return _require_key_auth(request)
        return JSONResponse(
            {"error": "insufficient_role", "required": "read", "provided": role},
            status_code=403,
        )
    # Write paths require ≥ write role
    if path in _WRITE_PATHS:
        if role is not None and _has_role(role, "write"):
            return await call_next(request)
        if role is None:
            return _require_key_auth(request)
        return JSONResponse(
            {"error": "insufficient_role", "required": "write", "provided": role},
            status_code=403,
        )
    # All other /api paths require ≥ write role
    if role is not None and _has_role(role, "write"):
        return await call_next(request)
    if role is None:
        return _require_key_auth(request)
    return JSONResponse(
        {"error": "insufficient_role", "required": "write", "provided": role},
        status_code=403,
    )


def _require_key_auth(request: Request) -> JSONResponse:
    if not _is_run_api_authorized(request):
        return _err_resp("unauthorized", request, 401, "Auth")
    return _err_resp("unauthorized", request, 401, "Auth")


# ── Logger ───────────────────────────────────────────────────────────────────

logger = logging.getLogger("re_os.dashboard")

# ── Routers ──────────────────────────────────────────────────────────────────

from dashboard.routers.health import router as health_router
from dashboard.routers.board_room import router as board_room_router
from dashboard.routers.pipeline import router as pipeline_router
from dashboard.routers.data import router as data_router, metrics_router
from dashboard.routers.ops import router as ops_router

app.include_router(health_router, prefix="/api/v1")
app.include_router(board_room_router, prefix="/api/v1")
app.include_router(pipeline_router, prefix="/api/v1")
app.include_router(data_router, prefix="/api/v1")
app.include_router(ops_router, prefix="/api/v1")
app.include_router(metrics_router)  # /metrics — no versioning prefix


# ── Legacy API Redirect ──────────────────────────────────────────────────────

_LEGACY_API_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


@app.api_route("/api/{path:path}", methods=list(_LEGACY_API_METHODS), include_in_schema=False)
async def _legacy_api_redirect(path: str, request: Request):
    # Do NOT redirect /api/v1/... paths (prevents redirect loop)
    if path.startswith("v1/"):
        return _err_resp("not_found", request, 404, "Legacy")
    qs = request.url.query
    target = f"/api/v1/{path}"
    if qs:
        target += f"?{qs}"
    return RedirectResponse(url=target, status_code=301)


# ── Root Route ───────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse, tags=["Pages"], summary="Dashboard UI")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


if __name__ == "__main__":
    import uvicorn

    os.makedirs("/app/logs", exist_ok=True)
    logging.basicConfig(
        level=os.environ.get("DASHBOARD_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    uvicorn.run(app, host="0.0.0.0", port=8050, log_level="info")
