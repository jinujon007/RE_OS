"""Tests for dead letter queue (T-1231 / GATE-108)."""

import os
import pytest
from pathlib import Path
from sqlalchemy import text


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


# ── GATE-117 / T-1272: Schema Drift Validation ─────────────────────────────────


def test_schema_drift_error_importable():
    from utils.dead_letter_queue import SchemaDriftError
    exc = SchemaDriftError("rera_projects", ["new_col"])
    assert exc.table == "rera_projects"
    assert exc.missing_columns == ["new_col"]
    assert "Schema drift" in str(exc)


def test_validate_schema_passes_when_keys_match():
    from unittest.mock import MagicMock
    from utils.dead_letter_queue import _validate_schema
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        ("id",), ("project_name",), ("market",),
    ]
    # Should not raise
    _validate_schema(conn, "rera_projects", {"project_name": "Test", "market": "Yelahanka"})


def test_schema_drift_raises_on_missing_key():
    import pytest
    from unittest.mock import MagicMock
    from utils.dead_letter_queue import _validate_schema, SchemaDriftError

    conn = MagicMock()
    # First call: _fetch_table_columns returns all columns
    # Second call: _fetch_db_generated_columns returns only auto columns (id, created_at)
    conn.execute.side_effect = [
        MagicMock(
            fetchall=lambda: [("id",), ("project_name",), ("developer_id",), ("created_at",)]
        ),
        MagicMock(
            fetchall=lambda: [("id",), ("created_at",)]  # DB-generated
        ),
    ]

    with pytest.raises(SchemaDriftError) as excinfo:
        _validate_schema(conn, "rera_projects", {"project_name": "Test"})
    assert "developer_id" in str(excinfo.value.missing_columns)


def test_validate_schema_skips_unknown_entity():
    from unittest.mock import MagicMock
    from utils.dead_letter_queue import _validate_schema
    conn = MagicMock()
    _validate_schema(conn, "unknown_type", {"a": 1})


# ── GATE-117 / T-1273: DLQ Auto-Purge ──────────────────────────────────────────


def test_dlq_purge_registered_in_scheduler():
    content = Path("config/scheduler/maintenance_jobs.py").read_text()
    assert "dlq_purge" in content
    assert "purge_old_records" in content


def test_dlq_purge_importable():
    from utils.dead_letter_queue import purge_old_records
    assert callable(purge_old_records)


def test_run_dlq_purge_importable():
    from config.scheduler.maintenance_jobs import run_dlq_purge
    assert callable(run_dlq_purge)


@pytest.mark.skip(reason="Requires live PostgreSQL — set DATABASE_URL and start docker compose")  # TRACK: requires live DB
def test_validate_schema_against_live_db():
    """Integration test: _validate_schema against a real PostgreSQL schema.

    Creates a temp table, fetches columns via information_schema, and asserts
    the validation correctly identifies schema drift vs clean records.

    Skipped by default — requires Docker with `docker compose up -d`.
    """
    from utils.db import get_engine
    from utils.dead_letter_queue import _validate_schema, SchemaDriftError

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TEMP TABLE test_dlq_schema (
                id SERIAL PRIMARY KEY,
                project_name TEXT NOT NULL,
                developer_name TEXT,
                price_psf NUMERIC DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        _validate_schema(conn, "rera_projects", {
            "project_name": "Test",
            "developer_name": "Dev",
        })
        import pytest
        with pytest.raises(SchemaDriftError):
            _validate_schema(conn, "rera_projects", {
                "project_name": "Test",
            })
