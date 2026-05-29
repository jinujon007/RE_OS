"""
RE_OS — Run History Logger
───────────────────────────
Records every crew run attempt so you can track progress over time,
see which errors recurred, and never repeat the same debugging twice.

Files written:
  logs/run_history.jsonl   — one JSON line per run (machine-readable, append-only)
  logs/runs_summary.md     — human-readable table of all runs with status + notes

Usage:
    from config.run_logger import RunLogger
    rl = RunLogger(market="Yelahanka")
    rl.start()
    ...run crew...
    rl.finish(status="success", report_path="outputs/yelahanka/intel_report_xxx.txt")
    # or on error:
    rl.finish(status="failed", error=str(e))
"""

import json
import os
from datetime import datetime
from pathlib import Path

LOGS_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "logs"
HISTORY_FILE = LOGS_DIR / "run_history.jsonl"
SUMMARY_FILE = LOGS_DIR / "runs_summary.md"


class RunLogger:
    def __init__(self, market: str, run_type: str = "market_intel"):
        LOGS_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_id = f"{ts}_{market.replace(' ', '_')}"
        self.market = market
        self.run_type = run_type
        self.start_time: datetime | None = None
        self.agents_completed: list[str] = []
        self._record: dict = {}

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self):
        self.start_time = datetime.now()
        self._record = {
            "run_id": self.run_id,
            "market": self.market,
            "run_type": self.run_type,
            "start_time": self.start_time.isoformat(),
            "end_time": None,
            "duration_seconds": None,
            "status": "running",
            "error": None,
            "error_type": None,
            "agents_completed": [],
            "report_path": None,
            "notes": [],
        }
        self._append_record()
        self._print_banner("START", f"Run ID: {self.run_id}")

    def agent_done(self, agent_name: str):
        """Call after each agent finishes to track partial progress."""
        self.agents_completed.append(agent_name)
        self._record["agents_completed"] = self.agents_completed
        self._print_progress(agent_name)

    def add_note(self, note: str):
        """Add a free-text note to this run (e.g. 'RERA portal blocked, used fallback')."""
        self._record.setdefault("notes", []).append(note)

    def finish(self, status: str, report_path: str = None, error: str = None):
        end = datetime.now()
        duration = (
            round((end - self.start_time).total_seconds(), 1)
            if self.start_time
            else None
        )

        self._record.update(
            {
                "end_time": end.isoformat(),
                "duration_seconds": duration,
                "status": status,
                "agents_completed": self.agents_completed,
                "report_path": report_path,
                "error": error,
                "error_type": self._classify_error(error) if error else None,
            }
        )

        self._append_record()
        self._update_summary()

        if status == "success":
            self._print_banner(
                "SUCCESS", f"{self.market} — {duration}s — {report_path}"
            )
        else:
            self._print_banner(
                "FAILED", f"{self.market} — {self._classify_error(error)}"
            )

    # ── Error classification ───────────────────────────────────────────────

    def _classify_error(self, error: str) -> str:
        if not error:
            return "unknown"
        e = error.lower()
        if "rate_limit" in e or "tpm" in e or "ratelimit" in e:
            return "GROQ_RATE_LIMIT"
        if "model" in e and ("not found" in e or "decommissioned" in e):
            return "MODEL_DEPRECATED"
        if "no module" in e or "importerror" in e or "modulenotfound" in e:
            return "IMPORT_ERROR"
        if "connection" in e or "timeout" in e or "refused" in e:
            return "CONNECTION_ERROR"
        if "authentication" in e or "api key" in e or "unauthorized" in e:
            return "AUTH_ERROR"
        if "ollama" in e and "not found" in e:
            return "OLLAMA_MODEL_MISSING"
        if "database" in e or "psycopg" in e or "sqlalchemy" in e:
            return "DB_ERROR"
        return "RUNTIME_ERROR"

    # ── File I/O ───────────────────────────────────────────────────────────

    def _append_record(self):
        """Overwrite the last line if run_id matches, else append."""
        lines = []
        if HISTORY_FILE.exists():
            lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()

        # Replace last entry for this run_id if it exists
        new_line = json.dumps(self._record, ensure_ascii=False)
        updated = False
        for i, line in enumerate(lines):
            try:
                rec = json.loads(line)
                if rec.get("run_id") == self.run_id:
                    lines[i] = new_line
                    updated = True
                    break
            except Exception:
                pass

        if not updated:
            lines.append(new_line)

        HISTORY_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _update_summary(self):
        """Regenerate runs_summary.md from run_history.jsonl."""
        if not HISTORY_FILE.exists():
            return

        runs = []
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                runs.append(json.loads(line))
            except Exception:
                pass

        # Sort newest first
        runs.sort(key=lambda r: r.get("start_time", ""), reverse=True)

        lines = [
            "# RE_OS — Run History",
            "",
            f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
            f"Total runs: {len(runs)}  ",
            f"Successful: {sum(1 for r in runs if r.get('status') == 'success')}  ",
            f"Failed: {sum(1 for r in runs if r.get('status') == 'failed')}  ",
            "",
            "---",
            "",
            "| # | Run ID | Market | Status | Duration | Agents Done | Error Type | Notes |",
            "|---|--------|--------|--------|----------|-------------|------------|-------|",
        ]

        for i, r in enumerate(runs, 1):
            status_icon = (
                "✅"
                if r.get("status") == "success"
                else ("❌" if r.get("status") == "failed" else "🔄")
            )
            duration = (
                f"{r.get('duration_seconds', '—')}s"
                if r.get("duration_seconds")
                else "—"
            )
            agents = ", ".join(r.get("agents_completed", [])) or "—"
            error_type = r.get("error_type") or "—"
            notes = "; ".join(r.get("notes", [])) or "—"
            run_id_short = r.get("run_id", "")[-19:]  # last 19 chars
            lines.append(
                f"| {i} | `{run_id_short}` | {r.get('market', '?')} | "
                f"{status_icon} {r.get('status', '?')} | {duration} | "
                f"{agents[:40]} | {error_type} | {notes[:60]} |"
            )

        lines += [
            "",
            "---",
            "",
            "## Error Type Legend",
            "",
            "| Code | Meaning | Fix |",
            "|------|---------|-----|",
            "| `GROQ_RATE_LIMIT` | Groq TPM exceeded | Wait 60s or use Ollama for light agents |",
            "| `MODEL_DEPRECATED` | Groq model decommissioned | Update model name in llm_router.py |",
            "| `IMPORT_ERROR` | Python module missing | Check scrapers/ directory |",
            "| `CONNECTION_ERROR` | Network/Docker issue | Check docker compose ps |",
            "| `OLLAMA_MODEL_MISSING` | Model not pulled | docker compose exec ollama ollama pull llama3.1:8b |",
            "| `DB_ERROR` | PostgreSQL issue | docker compose restart postgres |",
            "| `AUTH_ERROR` | Bad API key | Check .env file |",
            "",
            "## How to view",
            "",
            "```",
            "# Latest run:",
            "tail -1 logs/run_history.jsonl | python -m json.tool",
            "",
            "# All runs as table:",
            "cat logs/runs_summary.md",
            "```",
        ]

        SUMMARY_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ── Terminal output ────────────────────────────────────────────────────

    def _print_banner(self, label: str, msg: str):
        width = 65
        print(f"\n{'=' * width}")
        print(f"  RE_OS [{label}] — {msg}")
        print(f"{'=' * width}\n")

    def _print_progress(self, agent_name: str):
        idx = len(self.agents_completed)
        total = 5  # CEO, Scraper, Parser, Organizer, Analyst
        bar = "█" * idx + "░" * (total - idx)
        print(f"\n  ✓ [{bar}] {idx}/{total} — {agent_name} complete\n")


# ── Convenience functions ──────────────────────────────────────────────────────


def print_run_history(last_n: int = 10):
    """Print the last N runs to terminal. Call standalone to review history."""
    if not HISTORY_FILE.exists():
        print("No run history yet.")
        return

    runs = []
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                runs.append(json.loads(line))
            except Exception:
                pass

    runs = sorted(runs, key=lambda r: r.get("start_time", ""), reverse=True)[:last_n]

    print(f"\n{'=' * 65}")
    print(f"  RE_OS Run History — last {len(runs)} runs")
    print(f"{'=' * 65}")
    for r in runs:
        icon = "✅" if r.get("status") == "success" else "❌"
        dur = f"{r.get('duration_seconds')}s" if r.get("duration_seconds") else "—"
        err = f" [{r.get('error_type')}]" if r.get("error_type") else ""
        print(f"  {icon} {r.get('run_id', '')} | {r.get('market')} | {dur}{err}")
    print()


if __name__ == "__main__":
    print_run_history()
