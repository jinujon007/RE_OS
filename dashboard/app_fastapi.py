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
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# Import all metrics so they register with the global Prometheus REGISTRY.
from config.metrics import (  # noqa: F401
    pipeline_runs_total, llm_calls_total, db_upserts_total,
    scrape_success_total, scraper_runs_total, llm_router_fallbacks_total,
    pipeline_stage_duration_seconds, db_query_duration_seconds, digest_runs_total,
)

from dashboard.state import limiter, templates, _is_run_api_authorized, _READ_ONLY_PATHS, _READ_ONLY_PREFIXES

# ── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="RE_OS Dashboard",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
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

# ── Request ID + Security Headers Middleware ──────────────────────────────────


@app.middleware("http")
async def _add_request_id_and_headers(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
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


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
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
    if path == "/api/telegram/webhook":
        return await call_next(request)
    if not _is_run_api_authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


# ── Logger ───────────────────────────────────────────────────────────────────

logger = logging.getLogger("re_os.dashboard")

# ── Routers ──────────────────────────────────────────────────────────────────

from dashboard.routers.health import router as health_router
from dashboard.routers.board_room import router as board_room_router
from dashboard.routers.pipeline import router as pipeline_router
from dashboard.routers.data import router as data_router
from dashboard.routers.ops import router as ops_router

app.include_router(health_router)
app.include_router(board_room_router)
app.include_router(pipeline_router)
app.include_router(data_router)
app.include_router(ops_router)


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
