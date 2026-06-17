"""
RE_OS Dashboard — shared state and helpers extracted from app_fastapi.py.

All routers import from this module — never from dashboard.app_fastapi.
app_fastapi.py imports from here for middleware and startup.
"""

import copy
import glob
import logging
import os
import re
import subprocess
import threading
import time
from collections import OrderedDict
from datetime import datetime

from fastapi import Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import text as _sa_text


class ErrorResponse(BaseModel):
    error: str


class HealthServiceStatus(BaseModel):
    agents: str = "ok"
    postgres: str = "ok"
    redis: str = "ok"
    ollama: str = "warn"
    chroma: str = "error"

logger = logging.getLogger("re_os.dashboard")

from utils.db import get_engine as _get_sa_engine

# ── Rate Limiter ─────────────────────────────────────────────────────────────

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_REDIS_URL,
    strategy="fixed-window",
)

templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)

# ── Logger ───────────────────────────────────────────────────────────────────

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

# ── API Key check (eval at first use, not import time) ──────────────────────

_API_KEY: str | None = None


def _ensure_api_key():
    global _API_KEY
    if _API_KEY is not None:
        return
    _API_KEY = os.environ.get("DASHBOARD_API_KEY", "")
    if not _API_KEY:
        _allow_empty = os.environ.get("DASHBOARD_API_KEY_ALLOW_EMPTY", "").lower() in (
            "1", "true", "yes",
        )
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
        "/api/ops/kill-criteria",
        "/api/corridor/score",
    }
)
_READ_ONLY_PREFIXES = (
    "/api/reports/", "/api/logs/", "/api/market/", "/api/evaluate/",
    "/api/data/", "/api/memory/", "/api/demand/", "/api/distress/",
    "/api/scraper/", "/api/parcel/", "/api/finance/",
)


def _is_run_api_authorized(req: Request) -> bool:
    _ensure_api_key()
    if not _API_KEY:
        return True
    provided = req.headers.get("X-API-Key", "")
    if provided == _API_KEY:
        return True
    api_key_prev = os.environ.get("DASHBOARD_API_KEY_PREV", "")
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
                cmd, cwd="/app", shell=False, stdout=_log_fh, stderr=_log_fh,
            )
        started = datetime.now().isoformat()
        _running[market] = {"proc": proc, "started": started}
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
