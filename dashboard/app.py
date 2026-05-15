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
from flask import Flask, Response, jsonify, render_template, request

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

app = Flask(__name__, template_folder="templates")
logger = logging.getLogger("re_os.dashboard")

# market -> {'proc': Popen, 'started': iso-str}
_running: dict = {}
_lock = threading.Lock()

_diag_agents_contract_logged = False
_diag_running_last_signature = None

LOG_PATH = "/app/logs/crew.log"
VALID_MARKETS = {"Yelahanka", "Devanahalli", "Hebbal", "all"}
MARKET_CANONICAL = {
    "yelahanka": "Yelahanka",
    "devanahalli": "Devanahalli",
    "hebbal": "Hebbal",
    "all": "all",
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

_monitor_thread = None


def _get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def _read_last_lines(path: str, limit: int = 20):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return lines[-limit:]
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _clean_log_line(line: str):
    text = (line or "").strip()
    if not text:
        return ""
    text = re.sub(r"^\[[^\]]+\]\s*", "", text)
    text = re.sub(r"^\d{4}-\d{2}-\d{2}[T\s][^\s]+\s*[-|]\s*", "", text)
    text = re.sub(r"^\d{2}:\d{2}:\d{2}\s*[-|]\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text[:60]


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


def _set_agent_working(agent_id: str, label: str, started: str, action_line: str):
    agent = _agent_states[agent_id]
    agent["state"] = "working"
    agent["label"] = label
    agent["started"] = started
    if action_line:
        agent["last_action"] = action_line


def _reset_pipeline_agents(final_state: str):
    if final_state == "done":
        ceo_label = scraper_label = analyst_label = "DONE"
        ceo_state = scraper_state = analyst_state = "done"
    elif final_state == "failed":
        ceo_label = scraper_label = analyst_label = "FAILED"
        ceo_state = scraper_state = analyst_state = "failed"
    else:
        ceo_label = scraper_label = analyst_label = "IDLE"
        ceo_state = scraper_state = analyst_state = "idle"

    _agent_states["ceo"]["state"] = ceo_state
    _agent_states["ceo"]["label"] = ceo_label
    _agent_states["ceo"]["started"] = None
    if final_state == "idle":
        _agent_states["ceo"]["last_action"] = "Awaiting pipeline trigger"

    _agent_states["scraper"]["state"] = scraper_state
    _agent_states["scraper"]["label"] = scraper_label
    _agent_states["scraper"]["started"] = None
    _agent_states["scraper"]["terminals"] = {
        "rera": "idle",
        "listings": "idle",
        "kaveri": "idle",
    }
    if final_state == "idle":
        _agent_states["scraper"]["last_action"] = "No recent scrape"

    _agent_states["analyst"]["state"] = analyst_state
    _agent_states["analyst"]["label"] = analyst_label
    _agent_states["analyst"]["started"] = None
    if final_state == "idle":
        _agent_states["analyst"]["last_action"] = "No recent analysis"


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
        _running.pop(market, None)
    if finished:
        logger.info("[DIAG running] pruned finished markets=%s", finished)


def _monitor_agent_states_loop():
    while True:
        try:
            lines = _read_last_lines(LOG_PATH, limit=20)
            blob = "\n".join(lines).lower()

            recent_line = ""
            for ln in reversed(lines):
                cleaned = _clean_log_line(ln)
                if cleaned:
                    recent_line = cleaned
                    break

            with _lock:
                _log_running_lifecycle_locked("monitor.loop.start")

                active_entries = {
                    m: e for m, e in _running.items() if e["proc"].poll() is None
                }
                completed_entries = {
                    m: e for m, e in _running.items() if e["proc"].poll() is not None
                }
                any_active = len(active_entries) > 0
                started_ref = None
                if any_active:
                    started_candidates = [
                        e["started"]
                        for e in active_entries.values()
                        if e.get("started")
                    ]
                    started_ref = (
                        sorted(started_candidates)[0] if started_candidates else None
                    )

                stage1_hit = (
                    "stage 1" in blob
                    or "rera" in blob
                    or "listings" in blob
                    or "kaveri" in blob
                )
                stage3_analyst_hit = "stage 3" in blob or "analyst" in blob
                ceo_hit = "ceo" in blob or "synthesis" in blob

                if any_active and stage1_hit:
                    _set_agent_working("scraper", "SCRAPING", started_ref, recent_line)
                    _agent_states["scraper"]["terminals"] = {
                        "rera": (
                            "working" if "rera" in blob or "stage 1" in blob else "idle"
                        ),
                        "listings": (
                            "working"
                            if "listings" in blob or "stage 1" in blob
                            else "idle"
                        ),
                        "kaveri": (
                            "working"
                            if "kaveri" in blob or "stage 1" in blob
                            else "idle"
                        ),
                    }

                if any_active and stage3_analyst_hit:
                    _set_agent_working("analyst", "ANALYZING", started_ref, recent_line)

                if any_active and ceo_hit:
                    _set_agent_working("ceo", "DIRECTING", started_ref, recent_line)

                # Stage 2 / upsert / organizer: intentionally no label change.
                # Requirement: keep labels as-is during organizer phase.

                if not any_active:
                    if completed_entries:
                        failed = any(
                            (e["proc"].poll() or 0) != 0
                            for e in completed_entries.values()
                        )
                        if failed:
                            _reset_pipeline_agents("failed")
                            logger.info("[DIAG running] resolved terminal state=failed")
                        else:
                            _reset_pipeline_agents("done")
                            logger.info("[DIAG running] resolved terminal state=done")
                    else:
                        _reset_pipeline_agents("idle")

                # Always prune completed from _running to prevent stale-failure carryover.
                _prune_finished_running_entries_locked()
                _log_running_lifecycle_locked("monitor.loop.end")

                if recent_line:
                    if any(
                        k in blob for k in ["stage 1", "rera", "listings", "kaveri"]
                    ):
                        _agent_states["scraper"]["last_action"] = recent_line
                    if any(k in blob for k in ["stage 3", "analyst"]):
                        _agent_states["analyst"]["last_action"] = recent_line
                    if any(k in blob for k in ["ceo", "synthesis"]):
                        _agent_states["ceo"]["last_action"] = recent_line

        except Exception:
            pass

        time.sleep(2)


def _start_monitor_thread_once():
    global _monitor_thread
    if _monitor_thread and _monitor_thread.is_alive():
        return
    _monitor_thread = threading.Thread(target=_monitor_agent_states_loop, daemon=True)
    _monitor_thread.start()


def _normalize_market(market_raw: str):
    if not market_raw:
        return None
    key = market_raw.strip().lower()
    return MARKET_CANONICAL.get(key)


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

        proc = subprocess.Popen(cmd, cwd="/app")
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
        if entry and entry["proc"].poll() is None:
            entry["proc"].terminate()
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


@app.route("/api/health")
def health():
    services = {"agents": "ok"}

    try:
        conn = _get_db()
        conn.close()
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

    return jsonify(services)


# ── DB State ───────────────────────────────────────────────────────────────────


@app.route("/api/db/state")
def db_state():
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

        conn.close()
        return jsonify(state)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Pipeline Control ───────────────────────────────────────────────────────────


@app.route("/api/run/<market>", methods=["POST"])
def run_pipeline(market):
    payload, status_code = _start_pipeline_for_market(market)
    return jsonify(payload), status_code


@app.route("/api/run/<market>", methods=["DELETE"])
def stop_pipeline(market):
    payload, status_code = _stop_pipeline_for_market(market)
    return jsonify(payload), status_code


@app.route("/api/status")
def run_status():
    with _lock:
        result = {}
        for market, entry in _running.items():
            rc = entry["proc"].poll()
            if rc is None:
                result[market] = {"state": "running", "started": entry["started"]}
            elif rc == 0:
                result[market] = {"state": "done", "started": entry["started"]}
            else:
                result[market] = {
                    "state": "failed",
                    "started": entry["started"],
                    "rc": rc,
                }
    return jsonify(result)


# ── Agent Control / State ──────────────────────────────────────────────────────


@app.route("/api/agents", methods=["GET"])
def agents_state():
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

    global _diag_agents_contract_logged
    if not _diag_agents_contract_logged:
        logger.info(
            "[DIAG agents] /api/agents keys=%s nested_agents=%s",
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
        )

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
                    _agent_states["sentinel"][
                        "last_action"
                    ] = f"Last: {last.get('status', '?')} · Next: {nxt.get('label', '?')}"
                else:
                    _agent_states["sentinel"][
                        "last_action"
                    ] = f"Next run: {nxt.get('label', '?')}"

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
    def generate():
        log_path = "/app/logs/crew.log"
        while True:
            try:
                with open(log_path, "r") as f:
                    # replay last 80 lines on connect
                    lines = f.readlines()
                    for line in lines[-80:]:
                        yield f"data: {json.dumps(line.rstrip())}\n\n"
                    # then tail
                    while True:
                        line = f.readline()
                        if line:
                            yield f"data: {json.dumps(line.rstrip())}\n\n"
                        else:
                            yield ": heartbeat\n\n"
                            time.sleep(0.4)
            except FileNotFoundError:
                yield f"data: {json.dumps('— log file not found. Run a pipeline to start. —')}\n\n"
                time.sleep(3)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Reports ────────────────────────────────────────────────────────────────────


@app.route("/api/reports/<market>")
def get_report(market):
    pattern = f"/app/outputs/{market.lower()}/intel_report_*.txt"
    files = sorted(glob.glob(pattern))
    if not files:
        return jsonify({"content": None, "file": None})
    latest = files[-1]
    with open(latest) as f:
        content = f.read()
    return jsonify({"content": content, "file": os.path.basename(latest)})


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs("/app/logs", exist_ok=True)
    logging.basicConfig(
        level=os.environ.get("DASHBOARD_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _start_monitor_thread_once()
    app.run(host="0.0.0.0", port=8050, debug=False, threaded=True)
