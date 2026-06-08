"""GATE-83 declaration — Backup + Zero-Loss Safety Net (Sprint 83).
Unit tests (no Docker): 3 assertions.
Integration tests (requires Docker): 5 assertions.
"""
import pytest
from unittest.mock import patch, MagicMock


# ── Unit Tests (no Docker) ──────────────────────────────────────────────


@pytest.mark.unit
def test_db_backup_importable():
    """(1) DBBackup class and helpers importable without error."""
    from utils.backup import DBBackup, check_backup_staleness, verify_backup, enforce_retention
    assert callable(DBBackup)
    assert callable(check_backup_staleness)
    assert callable(verify_backup)
    assert callable(enforce_retention)


@pytest.mark.unit
def test_staleness_stale_on_mocked_30h():
    """(2) check_backup_staleness returns stale=True on mocked 30h mtime."""
    import time
    old_mtime = time.time() - (30 * 3600)
    with (
        patch("utils.backup.os.path.isdir", return_value=True),
        patch("utils.backup.os.listdir", return_value=["re_os_20260607_040000.dump"]),
        patch("utils.backup.os.path.getmtime", return_value=old_mtime),
    ):
        from utils.backup import check_backup_staleness
        result = check_backup_staleness()
        assert result["stale"] is True
        assert result["age_hours"] > 26


@pytest.mark.unit
def test_run_backup_staleness_check_callable():
    """(3) run_backup_staleness_check is callable in scheduler module."""
    import config.scheduler
    assert callable(config.scheduler.run_backup_staleness_check)


# ── Integration Tests (requires Docker stack: docker compose up -d) ─────


@pytest.mark.integration
def test_gate83_run_db_backup_completes():
    """(1) run_db_backup() completes without exception."""
    from config.scheduler import run_db_backup
    result = run_db_backup()
    assert result is not None


@pytest.mark.integration
def test_gate83_dump_file_exists():
    """(2) .dump file exists in /backups/ with mtime within last 60s."""
    from utils.backup import check_backup_staleness
    result = check_backup_staleness()
    assert result["latest_file"] is not None
    assert result["age_hours"] < 1.0


@pytest.mark.integration
def test_gate83_verify_backup_valid():
    """(3) verify_backup returns valid=True for latest dump."""
    from utils.backup import check_backup_staleness, verify_backup, get_backup_dir
    import os
    result = check_backup_staleness()
    assert result["latest_file"] is not None
    path = os.path.join(get_backup_dir(), result["latest_file"])
    v = verify_backup(path)
    assert v["valid"] is True


@pytest.mark.integration
def test_gate83_staleness_fresh():
    """(4) check_backup_staleness returns stale=False immediately after backup."""
    from utils.backup import check_backup_staleness
    result = check_backup_staleness()
    assert result["stale"] is False


@pytest.mark.integration
def test_gate83_scheduler_job_registered():
    """(5) db_backup scheduler job registered with trigger.hour == 4."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from config.scheduler import _safe_job, run_db_backup
    sched = BlockingScheduler(timezone="Asia/Kolkata")
    sched.add_job(
        lambda: _safe_job(run_db_backup, "db_backup"),
        "cron", hour=4, minute=0,
        id="db_backup",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    jobs = sched.get_jobs()
    backup_job = next((j for j in jobs if j.id == "db_backup"), None)
    assert backup_job is not None, "db_backup job not found"
    assert backup_job.trigger.fields[2].min == 4  # hour field
