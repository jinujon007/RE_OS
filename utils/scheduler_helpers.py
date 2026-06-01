"""
RE_OS — Scheduler Helpers (Phase 7 — Alerts)
Shared utilities for scheduler job execution and alert routing.
Extracted from config/scheduler.py to avoid apscheduler import in tests.
"""
from loguru import logger


def safe_job(fn, job_name: str, *args, **kwargs):
    """Run a scheduler job. Send Discord system alert on exception."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.error(f"[Scheduler] Job '{job_name}' failed: {exc}")
        try:
            from utils.discord_notifier import send_system_alert
            send_system_alert(job_name, str(exc)[:300])
        except Exception:
            pass
        raise
