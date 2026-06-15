"""Tests for utils/backup.py + scheduler backup job (Sprint 83, GATE-83)."""

import subprocess
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_backup_constructs_correct_pg_dump_args():
    """DBBackup._parse_db_url returns correct host/user/dbname from DATABASE_URL."""
    with patch.dict(
        "os.environ",
        {
            "DATABASE_URL": "postgresql://re_os_user:secret123@myhost:5999/re_os_db",
        },
    ):
        from utils.backup import DBBackup

        db = DBBackup()._parse_db_url()
        assert db["host"] == "myhost"
        assert db["port"] == 5999
        assert db["user"] == "re_os_user"
        assert db["password"] == "secret123"
        assert db["dbname"] == "re_os_db"


def test_backup_returns_ok_on_success():
    """DBBackup.run() returns status='ok' when subprocess exits 0."""
    with (
        patch("utils.backup.subprocess.run") as mock_run,
        patch("utils.backup.os.path.getsize", return_value=12345),
        patch("utils.backup.os.makedirs"),
        patch(
            "utils.backup.verify_backup",
            return_value={"valid": True, "object_count": 15, "error": None},
        ),
    ):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = b""
        mock_run.return_value = mock_proc

        from utils.backup import DBBackup

        result = DBBackup().run()

        assert result["status"] == "ok"
        assert result["file"].endswith(".dump")
        assert result["size_bytes"] == 12345
        # Verify pg_dump was called with -Fc flag
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == "pg_dump"
        assert "-Fc" in call_args
        assert "-f" in call_args


def test_backup_returns_failed_on_nonzero_exit():
    """DBBackup.run() returns status='failed' when subprocess exits non-zero."""
    with (
        patch("utils.backup.subprocess.run") as mock_run,
        patch("utils.backup.os.makedirs"),
    ):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = b"pg_dump: error: connection to server failed"
        mock_run.return_value = mock_proc

        from utils.backup import DBBackup

        result = DBBackup().run()

        assert result["status"] == "failed"
        assert "connection to server failed" in result["error"]


def test_backup_handles_missing_database_url():
    """DBBackup.run() uses defaults when DATABASE_URL is missing or empty."""
    with patch.dict("os.environ", {}, clear=True):
        from utils.backup import DBBackup

        db = DBBackup()._parse_db_url()
        assert db["host"] == "postgres"
        assert db["port"] == 5432
        assert db["user"] == "re_os_user"
        assert db["dbname"] == "re_os"


def test_backup_returns_failed_on_timeout():
    """DBBackup.run() returns status='failed' on subprocess timeout."""
    with (
        patch(
            "utils.backup.subprocess.run",
            side_effect=subprocess.TimeoutExpired("pg_dump", 120),
        ),
        patch("utils.backup.os.makedirs"),
    ):
        from utils.backup import DBBackup

        result = DBBackup().run()
        assert result["status"] == "failed"
        assert "timeout after" in result["error"]


def test_backup_returns_failed_when_pg_dump_missing():
    """DBBackup.run() returns status='failed' when pg_dump not found."""
    with (
        patch(
            "utils.backup.subprocess.run",
            side_effect=FileNotFoundError("pg_dump: not found"),
        ),
        patch("utils.backup.os.makedirs"),
    ):
        from utils.backup import DBBackup

        result = DBBackup().run()
        assert result["status"] == "failed"
        assert "pg_dump binary not found" in result["error"]


def test_run_db_backup_function_exists():
    """config.scheduler has callable run_db_backup function."""
    import config.scheduler

    assert callable(config.scheduler.run_db_backup)


def test_send_ops_alert_posts_to_webhook():
    """send_ops_alert calls discord_notifier.send with correct args."""
    with patch("utils.discord_notifier.send") as mock_send:
        from utils.discord_notifier import send_ops_alert

        send_ops_alert("DB_BACKUP_FAILED", "connection lost")
        assert mock_send.called
        call_args = mock_send.call_args[0]
        assert call_args[0] == "system"
        assert "DB_BACKUP_FAILED" in call_args[2]


def test_staleness_stale_when_no_files():
    """check_backup_staleness returns stale=True, age_hours=None when no dumps."""
    with patch("utils.backup.os.path.isdir", return_value=True):
        with patch("utils.backup.os.listdir", return_value=["other.txt"]):
            from utils.backup import check_backup_staleness

            result = check_backup_staleness()
            assert result["stale"] is True
            assert result["age_hours"] is None
            assert result["latest_file"] is None


def test_staleness_stale_when_file_over_26h():
    """check_backup_staleness returns stale=True when most recent dump >26h old."""
    import time

    old_mtime = time.time() - (27 * 3600)
    with (
        patch("utils.backup.os.path.isdir", return_value=True),
        patch("utils.backup.os.listdir", return_value=["re_os_20260608_040000.dump"]),
        patch("utils.backup.os.path.getmtime", return_value=old_mtime),
    ):
        from utils.backup import check_backup_staleness

        result = check_backup_staleness()
        assert result["stale"] is True
        assert result["age_hours"] > 26


def test_staleness_fresh_when_recent():
    """check_backup_staleness returns stale=False when recent dump exists."""
    import time

    recent_mtime = time.time() - (2 * 3600)
    with (
        patch("utils.backup.os.path.isdir", return_value=True),
        patch("utils.backup.os.listdir", return_value=["re_os_20260608_040000.dump"]),
        patch("utils.backup.os.path.getmtime", return_value=recent_mtime),
    ):
        from utils.backup import check_backup_staleness

        result = check_backup_staleness()
        assert result["stale"] is False
        assert result["age_hours"] < 26


def test_retention_deletes_oldest_when_over_7():
    """enforce_retention removes oldest files when count > 7."""
    import time

    now = time.time()
    files = [f"re_os_{i:08d}_040000.dump" for i in range(9)]
    mtimes = {f: now - (i * 3600) for i, f in enumerate(files)}

    def fake_getmtime(path):
        import os as _os

        fname = _os.path.basename(path)
        return mtimes[fname]

    with (
        patch("utils.backup.os.path.isdir", return_value=True),
        patch("utils.backup.os.listdir", return_value=files),
        patch("utils.backup.os.path.getmtime", side_effect=fake_getmtime),
        patch("utils.backup.os.remove") as mock_remove,
    ):
        from utils.backup import enforce_retention

        deleted = enforce_retention(7)
        assert deleted == 2, f"Expected 2 deletions, got {deleted}"
        assert mock_remove.call_count == 2


def test_retention_does_nothing_when_under_7():
    """enforce_retention does nothing when count <= 7."""
    import time

    now = time.time()
    files = [f"re_os_{i:08d}_040000.dump" for i in range(5)]

    with (
        patch("utils.backup.os.path.isdir", return_value=True),
        patch("utils.backup.os.listdir", return_value=files),
        patch("utils.backup.os.path.getmtime", return_value=now),
        patch("utils.backup.os.remove") as mock_remove,
    ):
        from utils.backup import enforce_retention

        deleted = enforce_retention(7)
        assert deleted == 0
        assert mock_remove.call_count == 0


def test_verify_valid_on_good_output():
    """verify_backup returns valid=True when pg_restore --list returns TABLE."""
    lines = [f"; comment {i}" for i in range(5)]
    lines.extend([f"TABLE public.table_{i}" for i in range(12)])
    mock_stdout = "\n".join(lines)
    with patch("utils.backup.subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = mock_stdout.encode()
        mock_proc.stderr = b""
        mock_run.return_value = mock_proc

        from utils.backup import verify_backup

        result = verify_backup("/backups/test.dump")
        assert result["valid"] is True
        assert result["object_count"] >= 10
        assert result["error"] is None


def test_verify_invalid_on_empty_output():
    """verify_backup returns valid=False when pg_restore --list returns empty."""
    with patch("utils.backup.subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = b";;\n;;\n"
        mock_proc.stderr = b""
        mock_run.return_value = mock_proc

        from utils.backup import verify_backup

        result = verify_backup("/backups/test.dump")
        assert result["valid"] is False
        assert "too few objects" in result["error"].lower()


def test_run_backup_deletes_corrupt_file_and_alerts():
    """DBBackup.run() deletes corrupt backup and sends alert."""
    mock_stdout = b";;\n;;\n"
    with (
        patch("utils.backup.subprocess.run") as mock_run,
        patch("utils.backup.os.path.getsize", return_value=12345),
        patch("utils.backup.os.makedirs"),
        patch("utils.backup.os.remove") as mock_remove,
        patch("utils.backup.enforce_retention", return_value=0),
        patch("utils.discord_notifier.send_ops_alert") as mock_alert,
    ):
        # First call = pg_dump success, second call = pg_restore with bad output
        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            mock = MagicMock()
            if "pg_dump" in str(cmd):
                mock.returncode = 0
                mock.stdout = b""
                mock.stderr = b""
            else:
                mock.returncode = 0
                mock.stdout = mock_stdout
                mock.stderr = b""
            return mock

        mock_run.side_effect = side_effect

        from utils.backup import DBBackup

        result = DBBackup().run()

        assert result["status"] == "failed"
        assert "corrupt" in result["error"]
        assert mock_remove.called
        assert mock_alert.called


# ── T-1146: Off-site backup (Sprint 93 — GATE-93) ──────────────────────────────


def test_push_to_remote_skipped_when_not_configured():
    """push_to_remote returns skipped when BACKUP_REMOTE is not set."""
    from utils.backup import push_to_remote

    with patch.dict("os.environ", {}, clear=True):
        result = push_to_remote("/fake/path.dump")
    assert result["status"] == "skipped"
    assert "not configured" in result["detail"]


def test_push_to_remote_ok():
    """push_to_remote returns ok on successful rclone copy."""
    with (
        patch("utils.backup.subprocess.run") as mock_run,
        patch("utils.backup._BACKUP_REMOTE", "remote:bucket"),
        patch("utils.backup._backup_lock") as mock_lock,
        patch("utils.backup.os.path.isfile", return_value=True),
    ):
        mock_lock.acquire.return_value = True
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = b""
        mock_run.return_value = mock_proc

        from utils.backup import push_to_remote

        result = push_to_remote("/backups/re_os_20260613_050000.dump")
        assert result["status"] == "ok"
        assert "Pushed" in result["detail"]


def test_push_to_remote_failed_on_rclone_error():
    """push_to_remote returns failed when rclone exits non-zero."""
    with (
        patch("utils.backup.subprocess.run") as mock_run,
        patch("utils.backup._BACKUP_REMOTE", "remote:bucket"),
        patch("utils.backup._backup_lock") as mock_lock,
        patch("utils.backup.os.path.isfile", return_value=True),
    ):
        mock_lock.acquire.return_value = True
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = b"rclone: error: authentication failed"
        mock_run.return_value = mock_proc

        from utils.backup import push_to_remote

        result = push_to_remote("/backups/test.dump")
        assert result["status"] == "failed"
        assert "authentication" in result["detail"]


def test_push_to_remote_skipped_when_no_local_dump():
    """push_to_remote returns skipped when no local dump file found."""
    from utils.backup import push_to_remote

    with (
        patch("utils.backup._BACKUP_REMOTE", "remote:bucket"),
        patch("utils.backup._backup_lock") as mock_lock,
        patch("utils.backup._get_latest_local_dump", return_value=None),
    ):
        mock_lock.acquire.return_value = True
        result = push_to_remote(None)
    assert result["status"] == "skipped"
    assert "No local dump" in result["detail"]


def test_verify_remote_backup_skipped_when_not_configured():
    """verify_remote_backup returns skipped when BACKUP_REMOTE is not set."""
    from utils.backup import verify_remote_backup

    with patch.dict("os.environ", {}, clear=True):
        result = verify_remote_backup()
    assert result["status"] == "skipped"


def test_check_remote_backup_staleness_skipped_when_not_configured():
    """check_remote_backup_staleness returns skipped when BACKUP_REMOTE not set."""
    from utils.backup import check_remote_backup_staleness

    with patch.dict("os.environ", {}, clear=True):
        result = check_remote_backup_staleness()
    assert result["status"] == "skipped"
    assert result["stale"] is True
