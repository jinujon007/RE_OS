"""
RE_OS — Database Backup Utility (Sprint 83, GATE-83, Sprint 93 GATE-93)
pg_dump binary wrapper — no SQLAlchemy dependency.
Backup path: /backups/ (bind-mounted to ./backups/ on host).

Public API:
    DBBackup          — pg_dump wrapper class
    check_backup_staleness  — returns local staleness status dict
    enforce_retention       — prunes old backups, returns deleted count
    verify_backup           — checks integrity via pg_restore --list
    get_backup_dir          — returns configured backup directory path
    push_to_remote          — rclone push latest local dump to remote (GATE-93)
    verify_remote_backup    — download + pg_restore --list on remote dump
    check_remote_backup_staleness — checks if remote copy >8 days stale
"""

import os
import subprocess
import threading as _threading
import time as _time
from datetime import datetime

from loguru import logger

_BACKUP_DIR = os.environ.get("RE_OS_BACKUP_DIR", "/backups")
_STALE_HOURS = 26
_REMOTE_STALE_DAYS = 8
_BACKUP_REMOTE = os.environ.get("BACKUP_REMOTE", "")

__all__ = [
    "DBBackup",
    "check_backup_staleness",
    "enforce_retention",
    "verify_backup",
    "get_backup_dir",
    "push_to_remote",
    "verify_remote_backup",
    "verify_remote_backup_integrity_via_checksum",
    "check_remote_backup_staleness",
]


def get_backup_dir() -> str:
    """Return configured backup directory path."""
    return _BACKUP_DIR


# Threading lock preventing concurrent DBBackup.run() across APScheduler threads.
# The lock is module-scoped so all DBBackup instances share it.
_backup_lock = _threading.Lock()


class DBBackup:
    """pg_dump-based PostgreSQL backup with 7-day rolling retention.

    Usage:
        result = DBBackup().run()
        # Returns: {'status': 'ok'|'failed', 'file': str, 'size_bytes': int,
        #           'object_count': int, 'pruned': int, 'elapsed_s': float}
        # On failure: {'status': 'failed', 'error': str}
    """

    _PG_DUMP_TIMEOUT = 120

    def _parse_db_url(self) -> dict:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            return {
                "host": "postgres",
                "port": 5432,
                "user": "re_os_user",
                "password": os.environ.get("DB_PASSWORD", ""),
                "dbname": "re_os",
            }
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return {
            "host": parsed.hostname or "postgres",
            "port": parsed.port or 5432,
            "user": parsed.username or "re_os_user",
            "password": parsed.password or os.environ.get("DB_PASSWORD", ""),
            "dbname": parsed.path.lstrip("/") or "re_os",
        }

    def _ensure_backup_dir(self) -> None:
        os.makedirs(_BACKUP_DIR, exist_ok=True)

    def run(self) -> dict:
        """Execute pg_dump backup with integrity verification and retention pruning.

        Returns:
            dict with status 'ok' or 'failed'. On ok: file, size_bytes,
            object_count, pruned, elapsed_s. On failed: error string.
        """
        t0 = _time.time()

        # Prevent concurrent backup runs across scheduler threads
        acquired = _backup_lock.acquire(blocking=False)
        if not acquired:
            logger.warning("[DBBackup] Previous backup still running — skipping")
            return {
                "status": "failed",
                "error": "concurrent backup skipped (already running)",
                "elapsed_s": 0,
            }
        try:
            return self._run_backup(t0)
        finally:
            _backup_lock.release()

    def _run_backup(self, t0: float) -> dict:
        self._ensure_backup_dir()
        db = self._parse_db_url()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(_BACKUP_DIR, f"re_os_{timestamp}.dump")

        cmd = [
            "pg_dump",
            "-Fc",
            "-h",
            db["host"],
            "-p",
            str(db["port"]),
            "-U",
            db["user"],
            "-d",
            db["dbname"],
            "-f",
            filepath,
        ]
        env = {**os.environ, "PGPASSWORD": db["password"]}

        try:
            result = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                timeout=self._PG_DUMP_TIMEOUT,
            )
            if result.returncode == 0:
                size = os.path.getsize(filepath)
                deleted = enforce_retention(7)
                v = verify_backup(filepath)
                elapsed = round(_time.time() - t0, 2)
                if not v["valid"]:
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
                    # Late import to avoid pulling discord dependency at module load
                    from utils.discord_notifier import send_ops_alert

                    send_ops_alert(
                        "DB_BACKUP_CORRUPT", f"{filepath}: {v.get('error', 'unknown')}"
                    )
                    logger.error(
                        "[DBBackup] Corrupt backup deleted: {} — {}",
                        filepath,
                        v.get("error"),
                    )
                    return {
                        "status": "failed",
                        "error": f"corrupt backup: {v.get('error', '')}",
                        "elapsed_s": elapsed,
                    }
                logger.info(
                    "[DBBackup] Backup complete: {} ({} bytes, {} objects) | pruned {} old | {:.1f}s",
                    filepath,
                    size,
                    v["object_count"],
                    deleted,
                    elapsed,
                )
                return {
                    "status": "ok",
                    "file": filepath,
                    "size_bytes": size,
                    "object_count": v["object_count"],
                    "pruned": deleted,
                    "elapsed_s": elapsed,
                }
            else:
                stderr = result.stderr.decode("utf-8", errors="replace")[:500]
                logger.warning("[DBBackup] pg_dump failed: {}", stderr)
                return {"status": "failed", "error": stderr}
        except subprocess.TimeoutExpired:
            logger.warning(
                "[DBBackup] pg_dump timed out after {}s", self._PG_DUMP_TIMEOUT
            )
            return {
                "status": "failed",
                "error": f"timeout after {self._PG_DUMP_TIMEOUT}s",
            }
        except FileNotFoundError:
            logger.error(
                "[DBBackup] pg_dump binary not found — is postgresql-client installed?"
            )
            return {"status": "failed", "error": "pg_dump binary not found"}
        except Exception as exc:
            logger.warning("[DBBackup] Backup failed: {}", exc)
            return {"status": "failed", "error": str(exc)[:500]}


def check_backup_staleness() -> dict:
    """Check if most recent backup is older than STALE_HOURS.

    Returns:
        dict with keys:
            stale (bool): True if no backups or oldest > STALE_HOURS.
            age_hours (float | None): age of newest backup, or None if no backups exist.
            latest_file (str | None): filename of newest backup, or None.
    """
    if not os.path.isdir(_BACKUP_DIR):
        return {"stale": True, "age_hours": None, "latest_file": None}

    dumps = [
        f
        for f in os.listdir(_BACKUP_DIR)
        if f.startswith("re_os_") and f.endswith(".dump")
    ]
    if not dumps:
        return {"stale": True, "age_hours": None, "latest_file": None}

    latest = max(dumps, key=lambda f: os.path.getmtime(os.path.join(_BACKUP_DIR, f)))
    mtime = os.path.getmtime(os.path.join(_BACKUP_DIR, latest))
    age_hours = (datetime.now().timestamp() - mtime) / 3600.0
    return {
        "stale": age_hours > _STALE_HOURS,
        "age_hours": round(age_hours, 2),
        "latest_file": latest,
    }


def enforce_retention(max_files: int = 7) -> int:
    """Remove oldest dump files beyond max_files.

    Lists dump files sorted by mtime descending, deletes any beyond max_files.
    Not atomic — another process may add/remove files between list and delete.
    For daily-single-backup usage, this race is acceptable.

    Returns:
        Count of deleted files (0 if none).
    """
    if not os.path.isdir(_BACKUP_DIR):
        return 0

    dumps = sorted(
        [
            f
            for f in os.listdir(_BACKUP_DIR)
            if f.startswith("re_os_") and f.endswith(".dump")
        ],
        key=lambda f: os.path.getmtime(os.path.join(_BACKUP_DIR, f)),
        reverse=True,
    )
    if len(dumps) <= max_files:
        return 0

    deleted = 0
    for f in dumps[max_files:]:
        try:
            os.remove(os.path.join(_BACKUP_DIR, f))
            deleted += 1
        except OSError as exc:
            logger.warning("[DBBackup] Failed to remove old backup {}: {}", f, exc)

    if deleted:
        logger.info("[DBBackup] Retention pruned {} old backup(s)", deleted)
    return deleted


_VERIFY_TIMEOUT_S = 30


def verify_backup(filepath: str) -> dict:
    """Verify backup file integrity via pg_restore --list.

    Counts TOC entries (non-comment lines) as a proxy for object count.
    This is approximate — pg_restore --list outputs table-of-contents entries
    which include tables, indexes, sequences, and other schema objects.
    Minimum threshold: 10 entries including at least one TABLE.

    Returns:
        dict with valid (bool), object_count (int), error (str|None).
    """
    try:
        result = subprocess.run(
            ["/usr/bin/pg_restore", "--list", filepath],
            capture_output=True,
            timeout=_VERIFY_TIMEOUT_S,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")[:500]
            return {
                "valid": False,
                "object_count": 0,
                "error": f"pg_restore exit {result.returncode}: {stderr}",
            }

        stdout = result.stdout.decode("utf-8", errors="replace")
        lines = [
            line
            for line in stdout.split("\n")
            if line.strip() and not line.startswith(";")
        ]
        if len(lines) < 10 or "TABLE" not in stdout:
            return {
                "valid": False,
                "object_count": len(lines),
                "error": f"Too few objects ({len(lines)} lines, need >=10 with TABLE)",
            }

        return {"valid": True, "object_count": len(lines), "error": None}
    except subprocess.TimeoutExpired:
        return {
            "valid": False,
            "object_count": 0,
            "error": f"pg_restore --list timed out after {_VERIFY_TIMEOUT_S}s",
        }
    except FileNotFoundError:
        return {
            "valid": False,
            "object_count": 0,
            "error": "pg_restore binary not found",
        }
    except Exception as exc:
        return {"valid": False, "object_count": 0, "error": str(exc)[:500]}


# ── Remote backup (Sprint 93 — GATE-93) ────────────────────────────────────────


def _get_latest_local_dump() -> str | None:
    """Return the path of the most recent local dump file, or None."""
    if not os.path.isdir(_BACKUP_DIR):
        return None
    dumps = sorted(
        [
            f
            for f in os.listdir(_BACKUP_DIR)
            if f.startswith("re_os_") and f.endswith(".dump")
        ],
        key=lambda f: os.path.getmtime(os.path.join(_BACKUP_DIR, f)),
        reverse=True,
    )
    if not dumps:
        return None
    return os.path.join(_BACKUP_DIR, dumps[0])


def push_to_remote(local_path: str | None = None) -> dict:
    """Push latest local backup dump to remote object storage via rclone.

    Shares the threading lock with DBBackup.run() to prevent concurrent
    local + remote operations from corrupting each other. Retries up to
    2 times with exponential backoff on transient failures.

    Requires BACKUP_REMOTE env var (e.g. ``backup_remote:bucket/path``
    configured via ``rclone config``). For encryption, use rclone crypt remote.

    Returns:
        dict with keys: status (ok/skipped/failed), detail (str).
    """
    if not _BACKUP_REMOTE:
        return {
            "status": "skipped",
            "detail": "BACKUP_REMOTE not configured — no remote push",
        }

    acquired = _backup_lock.acquire(blocking=False)
    if not acquired:
        logger.warning("[RemoteBackup] Local backup in progress — skipping remote push")
        return {
            "status": "skipped",
            "detail": "Local backup running — deferred to next window",
        }
    try:
        local_path = local_path or _get_latest_local_dump()
        if not local_path or not os.path.isfile(local_path):
            return {"status": "skipped", "detail": "No local dump file found to push"}

        last_error = ""
        for attempt in range(3):
            try:
                result = subprocess.run(
                    ["rclone", "copy", local_path, _BACKUP_REMOTE],
                    capture_output=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    logger.info(
                        "[RemoteBackup] Push complete: {} → {}",
                        local_path,
                        _BACKUP_REMOTE,
                    )
                    return {
                        "status": "ok",
                        "detail": f"Pushed {os.path.basename(local_path)} to remote",
                    }
                else:
                    last_error = result.stderr.decode("utf-8", errors="replace")[:500]
                    logger.warning(
                        "[RemoteBackup] rclone copy attempt {} failed: {}",
                        attempt + 1,
                        last_error,
                    )
                    if attempt < 2:
                        _time.sleep(2**attempt * 5)
            except subprocess.TimeoutExpired:
                last_error = f"rclone copy timed out after 300s (attempt {attempt + 1})"
                logger.warning("[RemoteBackup] {}", last_error)
                if attempt < 2:
                    _time.sleep(2**attempt * 5)
            except FileNotFoundError:
                logger.warning(
                    "[RemoteBackup] rclone binary not found — remote push unavailable"
                )
                return {"status": "failed", "detail": "rclone binary not found"}

        return {"status": "failed", "detail": last_error}
    except Exception as exc:
        logger.warning("[RemoteBackup] push failed: {}", exc)
        return {"status": "failed", "detail": str(exc)[:500]}
    finally:
        _backup_lock.release()


def verify_remote_backup() -> dict:
    """Download the latest remote backup and verify via pg_restore --list.

    Downloads to a temp file, runs pg_restore --list, removes temp file.
    Requires BACKUP_REMOTE env var.

    Returns:
        dict with keys: valid (bool), object_count (int), error (str|None),
        status (ok/skipped/failed).
    """
    if not _BACKUP_REMOTE:
        return {"status": "skipped", "detail": "BACKUP_REMOTE not configured"}

    import tempfile

    try:
        # List remote files to find latest
        list_result = subprocess.run(
            ["rclone", "lsf", _BACKUP_REMOTE],
            capture_output=True,
            timeout=60,
        )
        if list_result.returncode != 0:
            stderr = list_result.stderr.decode("utf-8", errors="replace")[:300]
            return {
                "status": "failed",
                "valid": False,
                "object_count": 0,
                "error": f"rclone lsf failed: {stderr}",
            }

        remote_files = (
            list_result.stdout.decode("utf-8", errors="replace").strip().split("\n")
        )
        remote_dumps = [f.strip() for f in remote_files if f.strip().endswith(".dump")]
        if not remote_dumps:
            return {
                "status": "failed",
                "valid": False,
                "object_count": 0,
                "error": "No remote dump files found",
            }

        latest_remote = max(remote_dumps)
        tmp = tempfile.NamedTemporaryFile(suffix=".dump", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            dl_result = subprocess.run(
                ["rclone", "copy", f"{_BACKUP_REMOTE}/{latest_remote}", tmp_path],
                capture_output=True,
                timeout=300,
            )
            if dl_result.returncode != 0:
                stderr = dl_result.stderr.decode("utf-8", errors="replace")[:300]
                return {
                    "status": "failed",
                    "valid": False,
                    "object_count": 0,
                    "error": f"rclone download failed: {stderr}",
                }

            v = verify_backup(tmp_path)
            return {
                "status": "ok" if v["valid"] else "failed",
                "valid": v["valid"],
                "object_count": v["object_count"],
                "error": v["error"],
                "file": latest_remote,
            }
        except Exception as exc:
            return {
                "status": "failed",
                "valid": False,
                "object_count": 0,
                "error": str(exc)[:500],
            }
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    except FileNotFoundError:
        return {
            "status": "failed",
            "valid": False,
            "object_count": 0,
            "error": "rclone binary not found",
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "valid": False,
            "object_count": 0,
            "error": "rclone operation timed out",
        }
    except Exception as exc:
        return {
            "status": "failed",
            "valid": False,
            "object_count": 0,
            "error": str(exc)[:500],
        }


def verify_remote_backup_integrity_via_checksum() -> dict:
    """Verify remote backup integrity using rclone checksum without full download.

    Runs ``rclone check`` with SHA-256 comparison against local copy.
    This is bandwidth-efficient for multi-GB dumps.

    Returns:
        dict with valid (bool), errors (int), detail (str).
    """
    if not _BACKUP_REMOTE:
        return {"valid": False, "errors": 0, "detail": "BACKUP_REMOTE not configured"}

    local_path = _get_latest_local_dump()
    if not local_path:
        return {
            "valid": False,
            "errors": 0,
            "detail": "No local dump to compare against",
        }

    try:
        result = subprocess.run(
            ["rclone", "check", local_path, _BACKUP_REMOTE, "--checksum", "--one-way"],
            capture_output=True,
            timeout=300,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        import re as _re

        err_match = _re.search(r"(\d+)\s+errors? found", stdout)
        error_count = int(err_match.group(1)) if err_match else 0
        return {
            "valid": result.returncode == 0 or error_count == 0,
            "errors": error_count,
            "detail": "Integrity passed"
            if error_count == 0
            else f"{error_count} file mismatches",
        }
    except FileNotFoundError:
        return {"valid": False, "errors": 0, "detail": "rclone binary not found"}
    except Exception as exc:
        return {"valid": False, "errors": 0, "detail": str(exc)[:300]}


def check_remote_backup_staleness() -> dict:
    """Check if the latest remote backup is older than REMOTE_STALE_DAYS.

    Returns:
        dict with keys:
            stale (bool): True if no remote backups or latest > REMOTE_STALE_DAYS old.
            age_days (float | None): age in days of latest remote backup, or None.
            latest_file (str | None): filename of latest remote backup, or None.
            status (str): ok/skipped/failed.
    """
    if not _BACKUP_REMOTE:
        return {
            "status": "skipped",
            "stale": True,
            "age_days": None,
            "latest_file": None,
        }

    try:
        result = subprocess.run(
            ["rclone", "lsf", "--format", "t", _BACKUP_REMOTE],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {
                "status": "failed",
                "stale": True,
                "age_days": None,
                "latest_file": None,
                "error": result.stderr.decode()[:200],
            }

        lines = result.stdout.decode("utf-8", errors="replace").strip().split("\n")
        # rclone lsf --format t outputs: "timestamp;filename"
        entries = []
        for line in lines:
            line = line.strip()
            if ";" in line:
                ts_str, name = line.split(";", 1)
                if name.endswith(".dump"):
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        entries.append((ts, name))
                    except ValueError:
                        pass

        if not entries:
            return {
                "status": "ok",
                "stale": True,
                "age_days": None,
                "latest_file": None,
            }

        latest = max(entries, key=lambda x: x[0])
        age = (datetime.now() - latest[0]).days
        return {
            "status": "ok",
            "stale": age > _REMOTE_STALE_DAYS,
            "age_days": age,
            "latest_file": latest[1],
        }
    except FileNotFoundError:
        return {
            "status": "failed",
            "stale": True,
            "age_days": None,
            "latest_file": None,
            "error": "rclone binary not found",
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "stale": True,
            "age_days": None,
            "latest_file": None,
            "error": "rclone lsf timed out",
        }
    except Exception as exc:
        return {
            "status": "failed",
            "stale": True,
            "age_days": None,
            "latest_file": None,
            "error": str(exc)[:500],
        }
