"""Tests for dead letter queue (T-1231 / GATE-108)."""

from pathlib import Path


def test_news_scout_zero_ruff_violations():
    import subprocess
    result = subprocess.run(
        ["ruff", "check", "scrapers/news_scout.py"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"ruff violations in news_scout.py:\n{result.stdout}\n{result.stderr}"


def test_dead_letter_queue_migration_exists():
    migrations_dir = Path("alembic/versions")
    files = list(migrations_dir.glob("0064_*.py"))
    assert len(files) >= 1, "Migration 0064_ingest_failed_records not found"
    content = files[0].read_text()
    assert "ingest_failed_records" in content


def test_dead_letter_queue_module_importable():
    from utils.dead_letter_queue import get_failed_records, retry_failed_records
    assert callable(get_failed_records)
    assert callable(retry_failed_records)


def test_failed_record_retry_registered_in_scheduler():
    content = Path("config/scheduler/maintenance_jobs.py").read_text()
    assert "failed_record_retry" in content


def test_failed_record_retry_exported():
    from config.scheduler import run_failed_record_retry
    assert callable(run_failed_record_retry)


def test_db_organizer_has_dead_letter_wiring():
    content = Path("utils/db_organizer.py").read_text()
    assert "_write_dead_letter" in content
    assert "ingest_failed_records" in content


def test_ops_router_has_failed_records():
    content = Path("dashboard/routers/ops.py").read_text()
    assert "failed_records" in content
    assert "ingest_failed_records" in content
