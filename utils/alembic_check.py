"""Weekly alembic check — runs `alembic check` and alerts on schema drift.

Risk (R8, GATE-88): without this check, a schema drift between Alembic's
migration chain and the live DB could go undetected for weeks, causing
runtime SQL errors in every pipeline stage. This function runs as a weekly
scheduler job (Sunday 03:00 UTC) and fires a Discord OPS alert on drift.
"""
import os
import subprocess
from loguru import logger


# Alembic CLI runs against the project root where alembic.ini lives.
# In Docker, this is /app; in dev, it's the repo root.
_ALEMBIC_CWD = os.environ.get("ALEMBIC_PROJECT_DIR", "/app")


def run_alembic_check() -> dict:
    """Run `alembic check` and return result dict.

    On failure, sends OPS alert via Discord.
    On success, returns ok (no-news-is-good-news pattern — ops silence = health).

    Alembic runs from ALEMBIC_PROJECT_DIR (default /app in Docker,
    repo root in dev) where alembic.ini is expected. Uses subprocess for
    full CLI fidelity rather than embedding alembic.config directly.
    """
    try:
        result = subprocess.run(
            ["alembic", "check"],
            capture_output=True,
            timeout=int(os.environ.get("ALEMBIC_CHECK_TIMEOUT", "30")),
            text=True,
            cwd=_ALEMBIC_CWD,
        )
        if result.returncode == 0:
            logger.info("[AlembicCheck] OK — no pending migrations")
            return {"status": "ok", "detail": result.stdout.strip()}
        else:
            stderr = (result.stderr or "")[:500]
            logger.warning(f"[AlembicCheck] FAILED — schema drift: {stderr}")
            try:
                from utils.discord_notifier import send_ops_alert
                send_ops_alert("ALEMBIC_DRIFT", f"alembic check failed — migration schema drifted: {stderr}")
            except Exception:
                pass
            return {"status": "failed", "detail": stderr}
    except subprocess.TimeoutExpired:
        logger.warning("[AlembicCheck] TIMEOUT — alembic check exceeded 30s")
        return {"status": "timeout", "detail": "alembic check exceeded 30s"}
    except OSError:
        logger.warning("[AlembicCheck] alembic not found — skipping check")
        return {"status": "skipped", "detail": "alembic CLI not available"}
    except Exception as exc:
        logger.warning(f"[AlembicCheck] ERROR — {exc}")
        return {"status": "error", "detail": str(exc)}
