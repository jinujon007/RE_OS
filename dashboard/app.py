"""
RE_OS Dashboard — Flask web server
Runs inside the agents container. Access at http://localhost:8050
"""

import copy
import glob
import json
import logging
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
import sys
import psycopg2
import psycopg2.pool
from flask import Flask, Response, jsonify, render_template, request

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

app = Flask(__name__, template_folder="templates")

# Read-only endpoints — exempt from API key gate (T-235)
_READ_ONLY_PATHS = frozenset({
    '/api/health', '/api/status', '/api/agents', '/api/intel',
    '/api/intel/cards', '/api/intel/download', '/api/db/state', '/api/sentinel/status',
})
_READ_ONLY_PREFIXES = ('/api/reports/', '/api/logs/')


@app.before_request
def _require_api_key():
    if not request.path.startswith('/api'):
        return None
    if request.path in _READ_ONLY_PATHS:
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
                    minconn=1, maxconn=5, dsn=dsn
                )
    return _db_pool


def _get_db():
    """Return a pooled connection. Caller must call pool.putconn(conn) when done."""
    return _get_pool().getconn()


def _release_db(conn):
    """Return a connection to the pool, rolling back any open transaction first.
    Without this, a mid-query error leaves the pooled connection in InFailedSqlTransaction."""
    try:
        if not conn.autocommit:
            try:
                conn.rollback()
            except Exception:
                pass
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


@app.route("/api/alert/test")
def test_alert():
    from utils.notifier import send_alert
    sent = send_alert("Test from RE_OS", "INFO")
    return jsonify({"sent": sent})


@app.route("/api/health")
def health():
    services = {"agents": "ok"}

    try:
        conn = _get_db()
        _release_db(conn)
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
        services["ollama"] = "warn"  # non-critical — local LLM fallback only

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


# ── Alert Test ───────────────────────────────────────────────────────────────────


@app.route("/api/alert/test", methods=["GET"])
def test_alert():
    from utils.notifier import send_alert
    sent = send_alert("Test from RE_OS", "INFO")
    return jsonify({"sent": sent})


# ── Metrics ─────────────────────────────────────────────────────────────────────

from prometheus_client import generate_latest
from config.metrics import (
    pipeline_runs_total,
    llm_calls_total,
    db_upserts_total,
    scrape_success_total,
)

@app.route('/metrics')
def metrics():
    return generate_latest(), 200, {'Content-Type': 'text/plain; version=0.0.4'}


# ── DB State ───────────────────────────────────────────────────────────────────


@app.route("/api/db/state")
def db_state():
    conn = None
    try:
        conn = _get_db()
        cur = conn.cursor()
        conn.set_session(readonly=True)

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
                   AVG(rp.price_avg_psf)::numeric(10,0) AS avg_psf
            FROM micro_markets mm
            LEFT JOIN rera_projects rp ON rp.micro_market_id = mm.id
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
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            _release_db(conn)


# ── Pipeline Control ───────────────────────────────────────────────────────────


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
    # Try to get live data from database first
    try:
        conn = _get_db()
        cur = conn.cursor()

        # Execute the SQL query as specified in T-166
        cur.execute("""
            SELECT agent_name, status, MAX(created_at) as last_run, COUNT(*) as total_runs
            FROM agent_runs
            GROUP BY agent_name, status
            ORDER BY last_run DESC
        """)

        # Build results in the format specified: {name, status, last_run, total_runs} per agent
        db_agents = {}
        for row in cur.fetchall():
            agent_name, status, last_run, total_runs = row
            # Convert to the expected format matching the original _agent_states structure
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

        # If we got data from DB, use it; otherwise fall back to in-memory
        if db_agents:
            cur.close()
            with _lock:
                states_copy = copy.deepcopy(db_agents)
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

            # Backward + forward compatibility: expose both nested and top-level agent keys.
            response.update(states_copy)

            if not _diag_agents_contract_logged:
                logger.info(
                    "[DIAG agents] /api/agents keys=%s nested_agents=%s (from DB)",
                    sorted(response.keys()),
                    sorted(states_copy.keys()),
                )
                _diag_agents_contract_logged = True

            _release_db(conn)
            return jsonify(response)

        cur.close()
        _release_db(conn)
    except Exception as e:
        logger.warning(f"[DIAG agents] DB query failed, falling back to in-memory: {e}")
        # Fall through to in-memory implementation below

    # Fallback to original in-memory implementation if DB fails or returns no data
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


@app.route("/api/intel/cards", methods=["GET"])
def intel_cards():
    """DB-backed market summary cards for dashboard UI."""
    conn = None
    try:
        conn = _get_db()
        cur = conn.cursor()

        cards = []
        cur.execute(
            """
            SELECT mm.name,
                   COUNT(DISTINCT rp.id) AS projects,
                   AVG(rp.price_avg_psf)::numeric(10,0) AS avg_psf
            FROM micro_markets mm
            LEFT JOIN rera_projects rp ON rp.micro_market_id = mm.id
            GROUP BY mm.name
            ORDER BY mm.name
            """
        )
        for row in cur.fetchall():
            cards.append(
                {
                    "market": row[0],
                    "projects": int(row[1] or 0),
                    "avg_psf": int(row[2]) if row[2] else None,
                    "latest_report": _latest_report_path(row[0]),
                }
            )

        return jsonify({"cards": cards})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            _release_db(conn)


# ── Intel API ──────────────────────────────────────────────────────────────────


@app.route("/api/intel")
def get_intel():
    result = {}
    for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
        slug = MARKET_SLUG.get(market)
        pattern = f"/app/outputs/{slug}/intel_report_*.txt"
        files = sorted(glob.glob(pattern))
        if files:
            latest = files[-1]
            with open(latest, encoding="utf-8") as f:
                content = f.read()
            # Extract timestamp from filename: intel_report_20260519_1430.txt -> "2026-05-19 14:30"
            fname = os.path.basename(latest)
            result[market] = {
                "last_report": fname,
                "summary": content[:500],
                "estimated": "[ESTIMATED DATA" in content,
            }
        else:
            result[market] = {
                "last_report": None,
                "summary": "No reports yet",
                "estimated": False,
            }
    return jsonify(result)


@app.route("/api/intel/download")
def download_intel():
    market_raw = request.args.get("market", "")
    canonical = _normalize_market(market_raw)
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


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs("/app/logs", exist_ok=True)
    logging.basicConfig(
        level=os.environ.get("DASHBOARD_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app.run(host="0.0.0.0", port=8050, debug=False, threaded=True)
