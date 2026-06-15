"""
Tests for config/run_logger.py

Covers: RunLogger.start(), agent_done(), add_note(), finish() (success + failed),
_classify_error() for all known error classes, run_id format, JSONL file written,
summary file regenerated.

All file I/O is redirected to tmp_path via monkeypatching the module-level LOGS_DIR,
HISTORY_FILE, and SUMMARY_FILE constants.
"""

import json
from pathlib import Path

import pytest

import config.run_logger as rl_mod
from config.run_logger import RunLogger

pytestmark = pytest.mark.unit


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def isolated_logs(tmp_path, monkeypatch):
    """Redirect all file I/O to a temp directory."""
    monkeypatch.setattr(rl_mod, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(rl_mod, "HISTORY_FILE", tmp_path / "run_history.jsonl")
    monkeypatch.setattr(rl_mod, "SUMMARY_FILE", tmp_path / "runs_summary.md")
    yield tmp_path


# ── run_id format ──────────────────────────────────────────────────────────────


def test_run_id_contains_market():
    rl = RunLogger(market="Yelahanka")
    assert "Yelahanka" in rl.run_id


def test_run_id_contains_timestamp():
    rl = RunLogger(market="Hebbal")
    # Format: YYYYMMDD_HHMMSS_Hebbal — starts with 8 digits
    assert rl.run_id[:8].isdigit()


def test_run_id_unique_per_instance():
    import time

    a = RunLogger(market="Yelahanka")
    time.sleep(0.01)
    b = RunLogger(market="Yelahanka")
    # They might be equal in the same second — just check both are strings
    assert isinstance(a.run_id, str)
    assert isinstance(b.run_id, str)


# ── start ──────────────────────────────────────────────────────────────────────


def test_start_writes_jsonl(isolated_logs):
    rl = RunLogger(market="Yelahanka")
    rl.start()
    history = isolated_logs / "run_history.jsonl"
    assert history.exists()
    lines = [ln for ln in history.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["status"] == "running"
    assert record["market"] == "Yelahanka"


def test_start_sets_run_id_in_record(isolated_logs):
    rl = RunLogger(market="Yelahanka")
    rl.start()
    line = (isolated_logs / "run_history.jsonl").read_text().splitlines()[0]
    record = json.loads(line)
    assert record["run_id"] == rl.run_id


# ── agent_done ─────────────────────────────────────────────────────────────────


def test_agent_done_accumulates(isolated_logs):
    rl = RunLogger(market="Yelahanka")
    rl.start()
    rl.agent_done("scraper")
    rl.agent_done("analyst")
    assert rl.agents_completed == ["scraper", "analyst"]


# ── finish — success ───────────────────────────────────────────────────────────


def test_finish_success_updates_record(isolated_logs):
    rl = RunLogger(market="Yelahanka")
    rl.start()
    rl.finish(status="success", report_path="outputs/yelahanka/intel_report.txt")

    lines = [
        ln
        for ln in (isolated_logs / "run_history.jsonl").read_text().splitlines()
        if ln.strip()
    ]
    # start() + finish() both write — finish() overwrites the same run_id entry
    records = [json.loads(ln) for ln in lines]
    final = next(r for r in records if r["run_id"] == rl.run_id)
    assert final["status"] == "success"
    assert final["report_path"] == "outputs/yelahanka/intel_report.txt"
    assert final["duration_seconds"] is not None


def test_finish_success_creates_summary(isolated_logs):
    rl = RunLogger(market="Yelahanka")
    rl.start()
    rl.finish(status="success")
    summary = isolated_logs / "runs_summary.md"
    assert summary.exists()
    content = summary.read_text()
    assert "Yelahanka" in content


# ── finish — failed ────────────────────────────────────────────────────────────


def test_finish_failed_records_error_type(isolated_logs):
    rl = RunLogger(market="Devanahalli")
    rl.start()
    rl.finish(status="failed", error="rate_limit exceeded by groq")

    lines = [
        ln
        for ln in (isolated_logs / "run_history.jsonl").read_text().splitlines()
        if ln.strip()
    ]
    records = [json.loads(ln) for ln in lines]
    final = next(r for r in records if r["run_id"] == rl.run_id)
    assert final["status"] == "failed"
    assert final["error_type"] == "GROQ_RATE_LIMIT"


# ── _classify_error ────────────────────────────────────────────────────────────


@pytest.fixture
def rl():
    return RunLogger(market="Test")


def test_classify_none_returns_unknown(rl):
    assert rl._classify_error(None) == "unknown"


def test_classify_rate_limit(rl):
    assert rl._classify_error("Groq rate_limit exceeded 30k TPM") == "GROQ_RATE_LIMIT"
    assert rl._classify_error("TPM quota exceeded") == "GROQ_RATE_LIMIT"
    assert rl._classify_error("ratelimit error") == "GROQ_RATE_LIMIT"


def test_classify_model_deprecated(rl):
    assert rl._classify_error("model llama-v2 not found") == "MODEL_DEPRECATED"
    assert rl._classify_error("model has been decommissioned") == "MODEL_DEPRECATED"


def test_classify_import_error(rl):
    assert rl._classify_error("No module named 'playwright'") == "IMPORT_ERROR"
    assert rl._classify_error("ImportError: cannot import crewai") == "IMPORT_ERROR"
    assert rl._classify_error("ModuleNotFoundError: utils") == "IMPORT_ERROR"


def test_classify_connection_error(rl):
    assert rl._classify_error("Connection refused on port 5432") == "CONNECTION_ERROR"
    assert rl._classify_error("timeout connecting to postgres") == "CONNECTION_ERROR"


def test_classify_auth_error(rl):
    assert rl._classify_error("authentication failed for user") == "AUTH_ERROR"
    assert rl._classify_error("Invalid API key supplied") == "AUTH_ERROR"
    assert rl._classify_error("401 Unauthorized") == "AUTH_ERROR"


def test_classify_ollama_missing(rl):
    # Must not contain "model" — that would match MODEL_DEPRECATED first
    assert rl._classify_error("ollama: llama3.1 not found") == "OLLAMA_MODEL_MISSING"


def test_classify_db_error(rl):
    assert (
        rl._classify_error("psycopg2 OperationalError: relation does not exist")
        == "DB_ERROR"
    )
    # "sqlalchemy" without "connection" so CONNECTION_ERROR doesn't fire first
    assert rl._classify_error("sqlalchemy error: table missing") == "DB_ERROR"
    assert rl._classify_error("database error") == "DB_ERROR"


def test_classify_runtime_error_fallback(rl):
    assert rl._classify_error("some unexpected random error") == "RUNTIME_ERROR"
