"""
RE_OS — System Health Dashboard
Run from project root: python utils/status.py
Or inside container: docker compose exec agents python utils/status.py
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
LOGS_DIR = ROOT / "logs"
ENV_FILE = ROOT / ".env"

REQUIRED_KEYS = ["GROQ_API_KEY", "CEREBRAS_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY"]

W = 68  # terminal width


def _hr(char="─"):
    print(char * W)


def _section(title):
    print()
    _hr()
    print(f"  {title}")
    _hr()


def _env_keys():
    present = set()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k = line.split("=", 1)[0].strip()
                v = line.split("=", 1)[1].strip()
                if v and v not in ("", '""', "''"):
                    present.add(k)
    return present


def _docker_status():
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True, text=True, timeout=8,
            cwd=str(ROOT)
        )
        if result.returncode != 0:
            return None, result.stderr.strip()
        lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
        containers = []
        for line in lines:
            try:
                containers.append(json.loads(line))
            except Exception:
                pass
        return containers, None
    except FileNotFoundError:
        return None, "docker not found in PATH"
    except subprocess.TimeoutExpired:
        return None, "docker timed out"
    except Exception as e:
        return None, str(e)


def _run_history(last_n=8):
    history_file = LOGS_DIR / "run_history.jsonl"
    if not history_file.exists():
        return []
    runs = []
    for line in history_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                runs.append(json.loads(line))
            except Exception:
                pass
    return sorted(runs, key=lambda r: r.get("start_time", ""), reverse=True)[:last_n]


def _log_health():
    files = {
        "crew.log":         LOGS_DIR / "crew.log",
        "run_history.jsonl": LOGS_DIR / "run_history.jsonl",
        "runs_summary.md":  LOGS_DIR / "runs_summary.md",
        "scheduler.log":    LOGS_DIR / "scheduler.log",
    }
    now = datetime.now().timestamp()
    results = []
    for name, path in files.items():
        if path.exists():
            size_kb = path.stat().st_size // 1024
            age_s = now - path.stat().st_mtime
            if age_s < 3600:
                age_str = f"{int(age_s // 60)}m ago"
            elif age_s < 86400:
                age_str = f"{int(age_s // 3600)}h ago"
            else:
                age_str = f"{int(age_s // 86400)}d ago"
            results.append((name, "OK", f"{size_kb}KB", age_str))
        else:
            results.append((name, "MISSING", "—", "—"))
    return results


def _bar(used, total, width=20):
    if total == 0:
        return "[" + "?" * width + "]"
    filled = int(width * used / total)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {used}/{total}"


def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print()
    print("=" * W)
    print(f"  RE_OS — System Health Dashboard        {now_str}")
    print("=" * W)

    # ── 1. API Keys ──────────────────────────────────────────────────────────
    _section("API KEYS")
    present = _env_keys()
    key_labels = {
        "CEREBRAS_API_KEY":  ("Cerebras", "1M tok/day — Light + Analysis tier PRIMARY"),
        "GEMINI_API_KEY":    ("Gemini",   "250k TPM  — CEO tier BACKUP 1"),
        "GROQ_API_KEY":      ("Groq",     "30k TPM   — CEO tier PRIMARY"),
        "NVIDIA_API_KEY":    ("NVIDIA",   "40 req/m  — backup"),
        "OPENROUTER_API_KEY":("OpenRouter","50-1k/day — last resort"),
    }
    for key, (label, note) in key_labels.items():
        icon = "✓" if key in present else "✗ MISSING"
        marker = "  ←— ADD THIS" if key not in present and key in ("CEREBRAS_API_KEY", "GEMINI_API_KEY") else ""
        print(f"  {icon:12}  {label:12}  {note}{marker}")

    # ── 2. Docker containers ─────────────────────────────────────────────────
    _section("CONTAINERS")
    containers, err = _docker_status()
    if err:
        print(f"  ✗ Cannot reach Docker: {err}")
        print("    Run from project root, or start stack with: docker compose up -d")
    elif not containers:
        print("  ✗ No containers running — run: docker compose up -d")
    else:
        name_map = {
            "re_os_db":        ("PostgreSQL + PostGIS", "5432"),
            "re_os_ollama":    ("Ollama LLM",           "11434"),
            "re_os_redis":     ("Redis queue",          "6379"),
            "re_os_agents":    ("Agent crew",           "—"),
            "re_os_scheduler": ("APScheduler",          "—"),
        }
        for c in containers:
            name = c.get("Name", c.get("Service", "?"))
            state = c.get("State", c.get("Status", "?"))
            health = c.get("Health", "")
            icon = "✓" if "running" in state.lower() else "✗"
            label, port = name_map.get(name, (name, "—"))
            health_str = f" [{health}]" if health else ""
            print(f"  {icon}  {name:22}  {label:22}  {state}{health_str}")

    # ── 3. Run history ───────────────────────────────────────────────────────
    _section("RECENT RUNS  (last 8)")
    runs = _run_history(8)
    if not runs:
        print("  No runs yet — run: docker compose exec agents python crews/market_intel_crew.py --market Yelahanka")
    else:
        total = len(runs)
        ok = sum(1 for r in runs if r.get("status") == "success")
        failed = sum(1 for r in runs if r.get("status") == "failed")
        print(f"  Shown: {total}  |  Success: {ok}  |  Failed: {failed}")
        print()
        for r in runs:
            status = r.get("status", "?")
            icon = "✓" if status == "success" else ("✗" if status == "failed" else "…")
            dur = f"{r.get('duration_seconds')}s" if r.get("duration_seconds") else "—"
            err = r.get("error_type") or ""
            agents = r.get("agents_completed", [])
            agent_bar = _bar(len(agents), 6, width=6)
            market = r.get("market", "?")
            run_id = r.get("run_id", "")[-19:]
            err_str = f"  [{err}]" if err else ""
            print(f"  {icon}  {run_id}  {market:12}  {dur:8}  agents{agent_bar}{err_str}")

    # ── 4. Log health ────────────────────────────────────────────────────────
    _section("LOG FILES")
    for name, status, size, age in _log_health():
        icon = "✓" if status == "OK" else "✗"
        print(f"  {icon}  {name:25}  {status:10}  {size:8}  updated: {age}")

    # ── 5. Last error ────────────────────────────────────────────────────────
    runs_all = _run_history(20)
    last_failed = next((r for r in runs_all if r.get("status") == "failed"), None)
    if last_failed:
        _section("LAST FAILURE")
        print(f"  Run:   {last_failed.get('run_id')}")
        print(f"  Error: {last_failed.get('error_type')}")
        err_msg = last_failed.get("error", "")
        if err_msg:
            short = err_msg[:120].replace("\n", " ")
            print(f"  Msg:   {short}")

    # ── 6. Quick commands ────────────────────────────────────────────────────
    _section("QUICK COMMANDS")
    print("  docker compose up -d                                          start stack")
    print("  docker compose exec agents python crews/market_intel_crew.py  run crew (all markets)")
    print("  docker compose exec agents python crews/market_intel_crew.py --market Yelahanka")
    print("  Get-Content logs/crew.log -Wait -Tail 50                      live log tail")
    print("  python utils/status.py                                        this dashboard")

    print()
    _hr("=")
    print()


if __name__ == "__main__":
    main()
