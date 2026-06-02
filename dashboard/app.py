"""
RE_OS Dashboard — Flask web server
Runs inside the agents container. Access at http://localhost:8050
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
from datetime import datetime
import psycopg2
import psycopg2.pool
from flask import Flask, Response, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__, template_folder="templates")

# CORS configuration – allowlist via env var
from flask_cors import CORS
_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "http://localhost:8050").split(",") if o.strip()]
CORS(app, origins=_ALLOWED_ORIGINS)

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri=_REDIS_URL,
    strategy="fixed-window",
)


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "rate limit exceeded"}), 429


@app.after_request
def _add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "0"
    # Restrict resource loading to same origin — prevents XSS data exfiltration
    # CSP: self + CDN sources for v2 Leaflet.js, Chart.js, OpenStreetMap tiles.
    # unsafe-inline kept for inline scripts/styles in the single-file dashboard template.
    # Tighten to nonces when the dashboard migrates to a proper template engine.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; "
        "img-src 'self' data: https://*.tile.openstreetmap.org https://*.basemaps.cartocdn.com; "
        "connect-src 'self' https://nominatim.openstreetmap.org"
    )
    return response


# Read-only endpoints — exempt from API key gate (T-235)
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
    '/api/data/freshness',
})
_READ_ONLY_PREFIXES = ('/api/reports/', '/api/logs/')


@app.before_request
def _require_api_key():
    if not request.path.startswith('/api') and request.path != '/metrics':
        return None
    # /metrics leaks pipeline telemetry — gate it when a key is configured (T-296)
    if request.path == '/metrics':
        return None
    if request.path in _READ_ONLY_PATHS and request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if any(request.path.startswith(p) for p in _READ_ONLY_PREFIXES):
        return None
    if not _is_run_api_authorized(request):
        return jsonify({"error": "unauthorized"}), 401


logger = logging.getLogger("re_os.dashboard")

# market -> {'proc': Popen, 'started': iso-str}
_running: dict = {}
_lock = threading.Lock()

_diag_agents_contract_logged = False
_diag_running_last_signature = None

# TTL cache for intel/cards estimated flag — avoids opening report files on every poll
_estimated_cache: dict[str, tuple[bool, float]] = {}  # market → (is_estimated, expiry_ts)
_ESTIMATED_CACHE_TTL = 120  # seconds

# Singleton IntelEmbedder — ChromaDB init has file I/O overhead; reuse across requests
_embedder_instance = None
_embedder_lock = threading.Lock()

# Search result cache: query → (results, expiry) — reduces ChromaDB queries for repeated searches
# OrderedDict preserves insertion order for LRU eviction at `_SEARCH_CACHE_MAX`
from collections import OrderedDict
_search_cache: OrderedDict[str, tuple[list[dict], float]] = OrderedDict()
_SEARCH_CACHE_TTL = 45  # seconds — short enough for freshness, long enough for repeated clicks
_SEARCH_CACHE_MAX = 200  # max entries — prevents unbounded memory growth

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
# Canonical market name lookup — only keys in this map are valid URL path segments
MARKET_CANONICAL = {
    "yelahanka": "Yelahanka",
    "devanahalli": "Devanahalli",
    "hebbal": "Hebbal",
    "all": "all",
}
# Safe slug map used for filesystem paths — derived from canonical names only
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
        {"label": "▶ Yelahanka", "prompt": "run Yelahanka"},
        {"label": "▶ Devanahalli", "prompt": "run Devanahalli"},
        {"label": "▶ Hebbal", "prompt": "run Hebbal"},
        {"label": "⏹ Stop", "prompt": "stop all"},
        {"label": "? Status", "prompt": "status"},
    ],
    "scraper": [
        {"label": "▶ Yelahanka", "prompt": "scrape Yelahanka"},
        {"label": "▶ Devanahalli", "prompt": "scrape Devanahalli"},
        {"label": "▶ Hebbal", "prompt": "scrape Hebbal"},
    ],
    "analyst": [
        {"label": "📊 Yelahanka", "prompt": "analyze Yelahanka"},
        {"label": "📊 Devanahalli", "prompt": "analyze Devanahalli"},
        {"label": "📊 Hebbal", "prompt": "analyze Hebbal"},
    ],
    "processor": [],
    "sentinel": [],
}

# Connection pool — avoids opening a raw connection per request.
# Initialised lazily on first use so the app starts even if DB is briefly unavailable.
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
                # connect_timeout=5 prevents a brief Postgres outage from hanging
                # Flask threads for 30s each (T-234)
                dsn = url if "connect_timeout" in url else (
                    url + ("&" if "?" in url else "?") + "connect_timeout=5"
                )
                _db_pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn=1, maxconn=10, dsn=dsn
                )
    return _db_pool


def _get_db():
    """Return a pooled connection. Caller must call pool.putconn(conn) when done."""
    return _get_pool().getconn()


def _release_db(conn, reset: bool = False):
    """Return a connection to the pool, rolling back any open transaction first.
    Without this, a mid-query error leaves the pooled connection in InFailedSqlTransaction.
    Set reset=True to force-close the connection instead of returning to pool.
    Always closes if the connection is broken (handles server-side terminations)."""
    try:
        if reset:
            _get_pool().putconn(conn, close=True)
            return
        # Check connection health before returning to pool
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
    except Exception:
        pass


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
                entry["proc"].wait(timeout=0)  # reap zombie (T-233)
            except Exception:
                pass
    if finished:
        logger.info("[DIAG running] pruned finished markets=%s", finished)


def _normalize_market(market_raw: str):
    if not market_raw:
        return None
    key = market_raw.strip().lower()
    return MARKET_CANONICAL.get(key)


_API_KEY = os.environ.get("DASHBOARD_API_KEY", "")
if not _API_KEY:
    logging.warning(
        "[RE_OS] DASHBOARD_API_KEY is not set — all /api endpoints are publicly "
        "accessible. Set DASHBOARD_API_KEY in .env before exposing port 8050."
    )


def _is_run_api_authorized(req) -> bool:
    """Opt-in API key gate. Auth disabled when DASHBOARD_API_KEY is unset (local mode).
    Supports DASHBOARD_API_KEY_PREV for zero-downtime rotation (T-250)."""
    api_key = os.environ.get("DASHBOARD_API_KEY", "")
    if not api_key:
        return True
    provided = req.headers.get("X-API-Key", "") or req.args.get("api_key", "")
    if provided == api_key:
        return True
    api_key_prev = os.environ.get("DASHBOARD_API_KEY_PREV", "")
    return bool(api_key_prev and provided == api_key_prev)


def _detect_market_from_prompt(prompt: str):
    text = (prompt or "").lower()
    for key, canonical in MARKET_CANONICAL.items():
        if key in text and key != "all":
            return canonical
    return None


def _start_pipeline_for_market(market: str):
    if market not in VALID_MARKETS:
        return {"error": "invalid market"}, 400

    with _lock:
        existing = _running.get(market)
        if existing and existing["proc"].poll() is None:
            return {"status": "already_running", "market": market}, 200

        cmd = ["python", "crews/market_intel_crew.py"]
        if market != "all":
            cmd += ["--market", market]

        # Route output to the per-market log file so SSE /api/logs/stream can tail it.
        # Parent closes its handle immediately; subprocess keeps its inherited fd open.
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
        _log_fh.close()  # parent releases; subprocess holds its own copy of the fd
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


def _stop_pipeline_for_market(market: str):
    with _lock:
        entry = _running.get(market)
        if entry and "proc" in entry and entry["proc"].poll() is None:
            entry["proc"].terminate()
            try:
                entry["proc"].wait(timeout=2)  # reap; kill if stuck (T-233)
            except subprocess.TimeoutExpired:
                entry["proc"].kill()
            logger.info(
                "[DIAG running] terminate requested market=%s pid=%s",
                market,
                entry["proc"].pid,
            )
            return {"status": "stopped", "market": market}, 200
    return {"status": "not_running"}, 200


def _running_snapshot():
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


# ── Pages ──────────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")


# ── Health ─────────────────────────────────────────────────────────────────────


@limiter.limit("5 per hour")
@app.route("/api/alert/test")
def test_alert():
    from utils.notifier import send_alert
    sent = send_alert("Test from RE_OS", "INFO")
    return jsonify({"sent": sent})


@app.route("/api/health")
def health():
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
        services["ollama"] = "warn"  # non-critical — local LLM fallback only

    # ChromaDB health
    try:
        from chromadb import PersistentClient
        _chroma_path = os.environ.get("CHROMA_DB_PATH", "/app/data/chroma")
        _test_client = PersistentClient(path=_chroma_path)
        _test_client.heartbeat()
        services["chroma"] = "ok"
    except Exception:
        services["chroma"] = "error"

    # Last pipeline run info from agent_runs table
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT micro_market, status, started_at, duration_seconds
            FROM agent_runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        )
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

    return jsonify(services)


# ── Board Room API

_VALID_BOARD_MARKETS = {"Yelahanka", "Devanahalli", "Hebbal", ""}

@limiter.limit("20 per hour")
@app.route("/api/board/session", methods=["POST"])
def board_session_create():
    from crews.board_room import run_board_session
    payload = request.get_json() or {}
    pitch = str(payload.get("pitch") or "").strip()
    market = str(payload.get("market") or "").strip()
    if not pitch or len(pitch) > 2000:
        return jsonify({"error": "pitch required and must be under 2000 characters"}), 400
    if market not in _VALID_BOARD_MARKETS:
        return jsonify({"error": "invalid market — must be Yelahanka, Devanahalli, or Hebbal"}), 400
    result = run_board_session(pitch, market)
    return jsonify(result), 200

@limiter.limit("120 per minute")
@app.route("/api/board/session/<session_id>", methods=["GET"])
def board_session_get(session_id):
    from crews.board_room import get_board_session
    session = get_board_session(session_id)
    if not session:
        return jsonify({"error": "not found"}), 404
    return jsonify(session), 200


@limiter.limit("60 per minute")
@app.route("/api/board/sessions", methods=["GET"])
def board_sessions():
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT session_id, market, status, created_at, pitch_text
            FROM board_sessions
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = []
        for r in cur.fetchall():
            pitch = r[4] or ""
            rows.append({
                "session_id": str(r[0]),
                "market": r[1],
                "status": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
                "pitch_excerpt": pitch[:120] + ("…" if len(pitch) > 120 else ""),
            })
        cur.close()
        return jsonify({"sessions": rows})
    except Exception as e:
        exc = True
        logger.error("[board_sessions] %s", e)
        return jsonify({"sessions": [], "error": "database query failed"})
    finally:
        if conn:
            _release_db(conn, reset=exc)


# ── Engineering Brief ──────────────────────────────────────────────────────────


@limiter.limit("30 per minute")
@app.route("/api/engineering/brief", methods=["GET"])
def engineering_brief():
    """Return the most recent Engineering Head response from board_sessions."""
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT session_id, market, engineering_response, created_at
            FROM board_sessions
            WHERE engineering_response IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        if not row:
            logger.info("[engineering_brief] No board sessions with engineering_response found")
            return jsonify({"brief": None})
        created = row[3].isoformat() if row[3] else None
        logger.info("[engineering_brief] session=%s market=%s created=%s",
                     row[0][:8], row[1], created)
        return jsonify({
            "brief": {
                "session_id": str(row[0]),
                "market": row[1],
                "response": row[2],
                "created_at": created,
            }
        })
    except Exception as e:
        exc = True
        logger.error("[engineering_brief] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


# ── Alerts ──────────────────────────────────────────────────────────────────────


@limiter.limit("30 per minute")
@app.route("/api/alerts", methods=["GET"])
def list_alerts():
    channel_filter = (request.args.get("channel") or "").strip() or None
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        where = "WHERE channel = %s" if channel_filter else ""
        params = [channel_filter] if channel_filter else []
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
        logger.info("[list_alerts] channel=%s count=%d", channel_filter or "all", len(rows))
        return jsonify({"alerts": rows})
    except Exception as e:
        exc = True
        logger.error("[list_alerts] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


@limiter.limit("30 per minute")
@app.route("/api/data/freshness", methods=["GET"])
def data_freshness():
    market_filter = (request.args.get("market") or "").strip() or None
    try:
        from utils.data_freshness import get_source_status
        rows = get_source_status(market=market_filter)
        return jsonify({"freshness": rows})
    except Exception as e:
        logger.error("[data_freshness] %s", e)
        return jsonify({"error": "freshness query failed"}), 500


# ── Finance Brief ───────────────────────────────────────────────────────────────


@limiter.limit("30 per minute")
@app.route("/api/finance/brief", methods=["GET"])
def finance_brief():
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT session_id, market, finance_response, created_at
            FROM board_sessions
            WHERE finance_response IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        if not row:
            logger.info("[finance_brief] No board sessions with finance_response found")
            return jsonify({"brief": None})
        created = row[3].isoformat() if row[3] else None
        logger.info("[finance_brief] session=%s market=%s created=%s",
                     row[0][:8], row[1], created)
        return jsonify({"brief": {
            "session_id": str(row[0]),
            "market": row[1],
            "response": row[2],
            "created_at": created,
        }})
    except Exception as e:
        exc = True
        logger.error("[finance_brief] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


# ── Legal Brief ────────────────────────────────────────────────────────────────


@limiter.limit("30 per minute")
@app.route("/api/legal/brief", methods=["GET"])
def legal_brief():
    market = _normalize_market(request.args.get("market", ""))
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        where = "WHERE legal_response IS NOT NULL"
        params = []
        if market and market != "all":
            where += " AND market = %s"
            params.append(market)
        cur.execute(f"""
            SELECT session_id, market, legal_response, created_at
            FROM board_sessions
            {where}
            ORDER BY created_at DESC
            LIMIT 1
        """, params)
        row = cur.fetchone()
        cur.close()
        if not row:
            logger.info("[legal_brief] No board sessions with legal_response found")
            return jsonify({"brief": None})
        created = row[3].isoformat() if row[3] else None
        logger.info("[legal_brief] session=%s market=%s created=%s",
                     row[0][:8], row[1], created)
        return jsonify({"brief": {
            "session_id": str(row[0]),
            "market": row[1],
            "response": row[2],
            "created_at": created,
        }})
    except Exception as e:
        exc = True
        logger.error("[legal_brief] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


# ── Tasks ──────────────────────────────────────────────────────────────────────


@limiter.limit("60 per minute")
@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    status_filter = request.args.get("status")
    owner_filter  = request.args.get("owner")
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()
        where_clauses, params = [], []
        if status_filter:
            where_clauses.append("status = %s")
            params.append(status_filter)
        if owner_filter:
            where_clauses.append("owner = %s")
            params.append(owner_filter)
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
        return jsonify({"tasks": rows})
    except Exception as e:
        exc = True
        logger.error("[list_tasks] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


@limiter.limit("30 per minute")
@app.route("/api/tasks", methods=["POST"])
def create_task():
    payload = request.get_json() or {}
    title    = str(payload.get("title") or "").strip()
    owner    = str(payload.get("owner") or "").strip()[:50]
    priority = str(payload.get("priority") or "medium").strip()
    source_type = str(payload.get("source_type") or "").strip()[:30]
    source_id_raw = payload.get("source_id")

    if not title:
        return jsonify({"error": "title required"}), 400
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
        return jsonify({"task_id": task_id, "status": "queued"}), 201
    except Exception as e:
        exc = True
        logger.error("[create_task] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


@limiter.limit("60 per minute")
@app.route("/api/tasks/<task_id>", methods=["PATCH"])
def update_task(task_id):
    payload = request.get_json() or {}
    new_status = str(payload.get("status") or "").strip()
    if new_status not in ("queued", "active", "done", "failed", "rejected"):
        return jsonify({"error": "invalid status"}), 400
    try:
        tid = str(uuid.UUID(task_id))
    except ValueError:
        return jsonify({"error": "invalid task_id"}), 400
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
            return jsonify({"error": "not found"}), 404
        conn.commit()
        cur.close()
        return jsonify({"status": new_status})
    except Exception as e:
        exc = True
        logger.error("[update_task] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


# ── Registry API ────────────────────────────────────────────────────────────────


@limiter.limit("30 per minute")
@app.route("/api/registry", methods=["GET", "POST"])
def handle_registry():
    if request.method == "GET":
        return _list_registry()
    return _hire_agent()


_registry_cache: dict[str, tuple[list[dict], float]] = {}  # "all" → (agents, expiry)
_REGISTRY_CACHE_TTL = 15  # seconds — long enough to absorb dashboard poll bursts, short enough for freshness


def _list_registry():
    now = time.time()
    cached = _registry_cache.get("all")
    if cached and cached[1] > now:
        logger.debug("[list_registry] cache hit (%d agents)", len(cached[0]))
        return jsonify({"agents": cached[0], "cached": True})
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
        return jsonify({"agents": rows})
    except Exception as e:
        exc = True
        logger.warning("[list_registry] DB query failed: %s", e)
        # Return stale cache if available
        if cached:
            return jsonify({"agents": cached[0], "cached": True, "stale": True})
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


def _validate_registry_payload(payload: dict) -> tuple[dict | None, str | None]:
    """Validate incoming agent spec payload. Returns (validated_payload, error_message)."""
    required = ("id", "name", "role", "persona", "llm_tier")
    for field in required:
        val = payload.get(field)
        if not val:
            return None, f"missing required field: '{field}'"
        if not isinstance(val, str):
            return None, f"field '{field}' must be a string, got {type(val).__name__}"

    spec_id = str(payload["id"]).strip()
    if not re.match(r"^[a-z][a-z0-9_-]*$", spec_id):
        return None, ("invalid id — must start with lowercase letter, "
                       "contain only [a-z0-9_-]")
    if len(spec_id) > 100:
        return None, f"id too long ({len(spec_id)} chars) — max 100"

    tier = payload["llm_tier"]
    if tier not in ("heavy", "analysis", "light"):
        return None, f"invalid llm_tier '{tier}' — must be heavy, analysis, or light"

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


def _hire_agent():
    """Accept JSON spec, write YAML to agents/registry/, sync to DB."""
    payload = request.get_json(silent=True) or {}
    validated, err = _validate_registry_payload(payload)
    if err:
        return jsonify({"error": err}), 400

    import yaml
    spec_id = str(validated["id"]).strip()
    from agents.agent_factory import _REGISTRY_DIR
    spec_path = str(_REGISTRY_DIR / f"{spec_id}.yaml")
    if os.path.exists(spec_path):
        return jsonify({"error": f"agent '{spec_id}' already exists"}), 409

    try:
        os.makedirs(os.path.dirname(spec_path), exist_ok=True)
        with open(spec_path, "w", encoding="utf-8") as f:
            yaml.dump(validated, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except Exception as e:
        logger.error("[hire_agent] write failed: %s", e)
        return jsonify({"error": "failed to write spec file"}), 500

    try:
        from agents.agent_factory import sync_registry_to_db
        synced = sync_registry_to_db()
        logger.info("[hire_agent] synced %d agents (including new '%s')", synced, spec_id)
    except Exception as e:
        logger.error("[hire_agent] db sync failed: %s", e)
        return jsonify({"warning": "spec written but DB sync failed", "spec_id": spec_id}), 201

    _registry_cache.pop("all", None)
    return jsonify({"status": "hired", "spec_id": spec_id}), 201


# ── Metrics ─────────────────────────────────────────────────────────────────────

from prometheus_client import generate_latest
from config.metrics import (
    pipeline_runs_total,
    llm_calls_total,
    db_upserts_total,
    scrape_success_total,
    db_query_duration_seconds,
)

@app.route('/metrics')
def metrics():
    return generate_latest(), 200, {'Content-Type': 'text/plain; version=0.0.4'}


# ── DB State ───────────────────────────────────────────────────────────────────


@limiter.limit("60 per minute")
@app.route("/api/db/state")
def db_state():
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
            GROUP BY mm.name
            ORDER BY mm.name
        """)
        state["markets"] = [
            {"name": r[0], "projects": r[1], "avg_psf": int(r[2]) if r[2] else None}
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT micro_market, started_at, status, duration_seconds
            FROM agent_runs
            ORDER BY started_at DESC LIMIT 5
        """)
        state["recent_runs"] = [
            {
                "market": r[0],
                "start_time": r[1].isoformat() if r[1] else None,
                "status": r[2],
                "duration": r[3],
            }
            for r in cur.fetchall()
        ]

        return jsonify(state)
    except Exception as e:
        exc = True
        logger.error("[db_state] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


@limiter.limit("30 per minute")
@app.route("/api/db/tables", methods=["GET"])
def db_tables():
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()

        # market_inventory
        with db_query_duration_seconds.labels(query_name="v_market_inventory").time():
            cur.execute("SELECT * FROM v_market_inventory")
            columns = [desc[0] for desc in cur.description]
            market_inventory = [dict(zip(columns, row)) for row in cur.fetchall()]

        # developer_scorecard — columns match v_developer_scorecard: developer, grade, total_projects, …
        with db_query_duration_seconds.labels(query_name="v_developer_scorecard").time():
            cur.execute("""
                SELECT developer, grade, total_projects, total_units,
                       avg_absorption_pct, completed, delayed, markets_active_in
                FROM v_developer_scorecard LIMIT 50
            """)
            columns = [desc[0] for desc in cur.description]
            developer_scorecard = [dict(zip(columns, row)) for row in cur.fetchall()]

        # active_projects — columns match v_active_projects: micro_market, project_status, …
        with db_query_duration_seconds.labels(query_name="v_active_projects").time():
            cur.execute("""
                SELECT project_name, developer_name, micro_market, project_status,
                       total_units, unsold_units, absorption_pct
                FROM v_active_projects LIMIT 100
            """)
            columns = [desc[0] for desc in cur.description]
            active_projects = [dict(zip(columns, row)) for row in cur.fetchall()]

        return jsonify({
            "market_inventory": market_inventory,
            "developer_scorecard": developer_scorecard,
            "active_projects": active_projects
        })
    except Exception as e:
        exc = True
        logger.error("[db_tables] %s", e)
        return jsonify({"error": "database query failed"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


# ── Pipeline Control ───────────────────────────────────────────────────────────


@limiter.limit("10 per hour")
@app.route("/api/run/<market>", methods=["POST"])
def run_pipeline(market):
    canonical = _normalize_market(market)
    if not canonical:
        return jsonify({"error": "invalid market"}), 400
    payload, status_code = _start_pipeline_for_market(canonical)
    return jsonify(payload), status_code


@app.route("/api/run/<market>", methods=["DELETE"])
def stop_pipeline(market):
    canonical = _normalize_market(market)
    if not canonical:
        return jsonify({"error": "invalid market"}), 400
    payload, status_code = _stop_pipeline_for_market(canonical)
    return jsonify(payload), status_code


@app.route("/api/status")
def run_status():
    return jsonify(_running_snapshot())


# ── Agent Control / State ──────────────────────────────────────────────────────


@app.route("/api/agents", methods=["GET"])
def agents_state():
    global _diag_agents_contract_logged
    conn = None
    _conn_exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT agent_name, status, MAX(started_at) as last_run, COUNT(*) as total_runs
            FROM agent_runs
            GROUP BY agent_name, status
            ORDER BY last_run DESC
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

        # Merge registry agents on the same connection — always, for full org chart
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
                        "last_action": f"Registered: {row[2]} in {row[3] or '—'}",
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
        return jsonify(response)

    except Exception as e:
        _conn_exc = True
        logger.warning(f"[DIAG agents] DB query failed, falling back to in-memory: {e}")
    finally:
        if conn and _conn_exc:
            _release_db(conn, reset=True)

    # Fallback — only reached if DB connection itself failed
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

    # Backward + forward compatibility: expose both nested and top-level agent keys.
    response.update(states_copy)

    if not _diag_agents_contract_logged:
        logger.info(
            "[DIAG agents] /api/agents keys=%s nested_agents=%s (fallback)",
            sorted(response.keys()),
            sorted(states_copy.keys()),
        )
        _diag_agents_contract_logged = True

    return jsonify(response)


@limiter.limit("30 per hour")
@app.route("/api/agents/<agent_id>/command", methods=["POST"])
def agent_command(agent_id):
    body = request.get_json(silent=True) or {}
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
        return jsonify(
            {
                "status": "unknown_command",
                "action": "invalid_agent",
                "details": f"Unknown agent_id '{agent_id}'",
                "hint": "Try: run [market], stop [market], status",
            }
        ), 404

    if any(k in text for k in ["run", "start", "scrape", "scan", "analyse", "analyze"]):
        market = chosen_market or "Yelahanka"
        payload, status_code = _start_pipeline_for_market(market)
        status = (
            "accepted"
            if payload.get("status") in {"started", "already_running"}
            else "unknown_command"
        )
        return (
            jsonify(
                {
                    "status": status,
                    "action": "run_pipeline",
                    "details": f"{payload.get('status')} for {market}",
                    "market": market,
                    "pipeline": payload,
                }
            ),
            status_code,
        )

    if any(k in text for k in ["stop", "cancel"]):
        market = chosen_market or "Yelahanka"
        payload, status_code = _stop_pipeline_for_market(market)
        status = (
            "accepted"
            if payload.get("status") in {"stopped", "not_running"}
            else "unknown_command"
        )
        return (
            jsonify(
                {
                    "status": status,
                    "action": "stop_pipeline",
                    "details": f"{payload.get('status')} for {market}",
                    "market": market,
                    "pipeline": payload,
                }
            ),
            status_code,
        )

    if any(k in text for k in ["status", "report", "show"]):
        report_market = (
            chosen_market if chosen_market and chosen_market != "all" else None
        )
        report_path = _latest_report_path(report_market)
        return jsonify(
            {
                "status": "accepted",
                "action": "status_report",
                "details": "Returned current agent state and latest report path",
                "market": chosen_market,
                "report_path": report_path,
                "agents": copy.deepcopy(_agent_states),
                "running_markets": _running_snapshot(),
            }
        )

    return jsonify(
        {
            "status": "unknown_command",
            "action": "none",
            "details": "No action matched prompt",
            "hint": "Try: run [market], stop [market], status",
        }
    )


@app.route("/api/agents/<agent_id>/actions", methods=["GET"])
def agent_actions(agent_id):
    if agent_id not in _agent_states and agent_id not in AGENT_ACTIONS:
        return jsonify({"error": f"Unknown agent '{agent_id}'"}), 404
    return jsonify({"agent_id": agent_id, "actions": AGENT_ACTIONS.get(agent_id, [])})


@app.route("/api/sentinel/status", methods=["GET"])
def sentinel_status():
    try:
        from agents.sentinel_agent import get_last_scheduled_run, get_next_scheduled_run

        last = get_last_scheduled_run()
        nxt = get_next_scheduled_run()

        with _lock:
            if "sentinel" in _agent_states:
                if last and "error" not in last:
                    _agent_states["sentinel"]["last_action"] = (
                        f"Last: {last.get('status', '?')} · Next: {nxt.get('label', '?')}"
                    )
                else:
                    _agent_states["sentinel"]["last_action"] = (
                        f"Next run: {nxt.get('label', '?')}"
                    )

        return jsonify({"last_run": last, "next_run": nxt})
    except Exception as e:
        logger.exception("sentinel_status failed")
        with _lock:
            if "sentinel" in _agent_states:
                _agent_states["sentinel"]["last_action"] = "Sentinel error: check logs"
        return jsonify(
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


# ── Log Streaming (SSE) ────────────────────────────────────────────────────────


@app.route("/api/logs/stream")
def stream_logs():
    # Validate market against known canonical names — prevents path traversal
    market_raw = request.args.get("market", "").strip().lower()
    canonical = MARKET_CANONICAL.get(market_raw)
    slug = MARKET_SLUG.get(canonical) if canonical else None
    candidate = f"/app/logs/{slug}.log" if slug else None
    log_path = candidate if (candidate and os.path.exists(candidate)) else LOG_PATH

    def generate():
        # Read at most 32KB from end of file for initial replay (~200 typical log lines).
        # Prevents loading the full file into memory on every client connect/reconnect.
        TAIL_BYTES = 32768
        try:
            while True:
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(0, 2)
                        file_size = f.tell()
                        f.seek(max(0, file_size - TAIL_BYTES))
                        if file_size > TAIL_BYTES:
                            f.readline()  # discard partial first line after mid-file seek
                        for line in f.readlines()[-80:]:
                            yield f"data: {json.dumps(line.rstrip())}\n\n"
                        last_pos = f.tell()
                        while True:
                            line = f.readline()
                            if line:
                                last_pos = f.tell()
                                yield f"data: {json.dumps(line.rstrip())}\n\n"
                            else:
                                # Detect log rotation: file shrank → break to reopen new file
                                f.seek(0, 2)
                                if f.tell() < last_pos:
                                    break
                                f.seek(last_pos)
                                yield ": heartbeat\n\n"
                                time.sleep(0.4)
                except FileNotFoundError:
                    yield f"data: {json.dumps('— log file not found. Run a pipeline to start. —')}\n\n"
                    time.sleep(3)
        except GeneratorExit:
            pass  # client disconnected — exit cleanly without leaking the file handle

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Reports ────────────────────────────────────────────────────────────────────


@limiter.limit("30 per minute")
@app.route("/api/reports/<market>")
def get_report(market):
    canonical = _normalize_market(market)
    if not canonical or canonical == "all":
        return jsonify({"error": "invalid market"}), 400
    slug = MARKET_SLUG.get(canonical)
    if not slug:
        return jsonify({"error": "invalid market"}), 400
    pattern = f"/app/outputs/{slug}/intel_report_*.txt"
    files = sorted(glob.glob(pattern))
    if not files:
        return jsonify({"content": None, "file": None})
    latest = files[-1]
    with open(latest, encoding="utf-8") as f:
        content = f.read()
    return jsonify({"content": content, "file": os.path.basename(latest)})


@limiter.limit("60 per minute")
@app.route("/api/intel/cards", methods=["GET"])
def intel_cards():
    """DB-backed market summary cards for dashboard UI."""
    conn = None
    exc = False
    try:
        conn = _get_db()
        cur = conn.cursor()

        cards = []
        cur.execute(
            """
            SELECT mm.name,
                   COUNT(DISTINCT rp.id)              AS projects,
                   ROUND(AVG(l.price_psf)::numeric, 0) AS avg_psf
            FROM micro_markets mm
            LEFT JOIN rera_projects rp ON rp.micro_market_id = mm.id
            LEFT JOIN listings l ON l.micro_market_id = mm.id
                                AND l.price_psf IS NOT NULL
                                AND l.price_psf > 1000
                                AND l.price_psf < 50000
            GROUP BY mm.name
            ORDER BY mm.name
            """
        )
        now = time.time()
        for row in cur.fetchall():
            market_name = row[0]
            slug = MARKET_SLUG.get(market_name, market_name.lower())

            # TTL-cached estimated flag — avoids reading report files on every poll
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

            cards.append(
                {
                    "market": market_name,
                    "active_projects": int(row[1] or 0),
                    "projects": int(row[1] or 0),
                    "avg_psf": int(row[2]) if row[2] else None,
                    "go_no_go": _market_go_no_go(int(row[1] or 0), int(row[2]) if row[2] else None, is_estimated),
                    "download_url": f"/api/intel/download?market={slug}" if slug else None,
                    "estimated": is_estimated,
                }
            )

        return jsonify({"cards": cards})
    except Exception as e:
        exc = True
        logger.error("[intel_cards] %s", e)
        return jsonify({"error": "failed to load market cards"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


def _market_go_no_go(active_projects: int, avg_psf: int | None, estimated: bool) -> str:
    if estimated or active_projects < 3 or avg_psf is None:
        return "WATCH"
    if 3500 <= avg_psf <= 9000 and active_projects >= 8:
        return "GO"
    return "NO-GO"


# ── Intel API ──────────────────────────────────────────────────────────────────


@limiter.limit("20 per minute")
@app.route("/api/intel/search", methods=["GET"])
def intel_search():
    q = (request.args.get("q") or "").strip()[:200]
    market = _normalize_market(request.args.get("market", ""))
    # Reject queries with non-printable control characters (injection vector for ChromaDB)
    if any(ord(c) < 32 and c not in "\t\n\r" for c in q):
        return jsonify({"results": [], "query": q[:50], "error": "invalid characters in query"}), 400
    if not q:
        return jsonify({"results": [], "query": q})
    market_param = market if market and market != "all" else None
    cache_key = f"{q}:::{market_param or ''}"
    now = time.time()
    cached = _cache_get(cache_key)
    if cached and cached[1] > now:
        logger.debug(f"[intel_search] cache hit for q={q[:40]} market={market_param}")
        return jsonify({"results": cached[0], "query": q, "market": market, "cached": True})
    logger.debug(f"[intel_search] q={q[:60]} market={market_param}")
    try:
        global _embedder_instance, _embedder_lock
        if _embedder_instance is None:
            with _embedder_lock:
                if _embedder_instance is None:
                    from utils.embedder import IntelEmbedder
                    _embedder_instance = IntelEmbedder()
        results = _embedder_instance.search(q, market=market_param, n=5)
        _cache_put(cache_key, (results, now + _SEARCH_CACHE_TTL))
        return jsonify({"results": results, "query": q, "market": market})
    except Exception as e:
        logger.warning(f"[intel_search] search failed: q={q[:40]} market={market_param}: {e}")
        return jsonify({"results": [], "query": q, "error": "search unavailable — index not built yet"})


@app.route("/api/intel/download")
def download_intel():
    market_raw = request.args.get("market", "")
    canonical = _normalize_market(market_raw)
    fmt = request.args.get("format", "txt").lower()

    if fmt == "csv":
        return _download_intel_csv(canonical)

    if not canonical or canonical == "all":
        return jsonify({"error": "invalid market"}), 400
    slug = MARKET_SLUG.get(canonical)
    pattern = f"/app/outputs/{slug}/intel_report_*.txt"
    files = sorted(glob.glob(pattern))
    if not files:
        return jsonify({"error": "no report found"}), 404
    with open(files[-1], encoding="utf-8") as f:
        content = f.read()
    return Response(content, mimetype="text/plain")


def _download_intel_csv(canonical: str | None):
    if not canonical:
        return jsonify({"error": "invalid market"}), 400

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

        cur.execute(
            f"""
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
            GROUP BY mm.name
            ORDER BY mm.name
            """,
            params,
        )

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
        return Response(
            out.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        exc = True
        logger.error("[download_intel_csv] %s", e)
        return jsonify({"error": "failed to export intel csv"}), 500
    finally:
        if conn:
            _release_db(conn, reset=exc)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs("/app/logs", exist_ok=True)
    logging.basicConfig(
        level=os.environ.get("DASHBOARD_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app.run(host="0.0.0.0", port=8050, debug=False, threaded=True)
