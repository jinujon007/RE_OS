"""
Scheduler healthcheck probe for Docker.

Exit codes:
  0 = healthy   — module imports OK + heartbeat row within 30 min (or DB unreachable)
  1 = unhealthy — module import fails, or heartbeat stale with DB reachable

Three-state logic:
  1. Module import — fails at module load time if scheduler code is corrupt.
     The process crashes with ImportError and Docker sees exit code 1.
  2. Heartbeat freshness — `_check()` probes agent_runs for a row younger than 30 min.
  3. DB unreachable  — `_check()` returns 0 (degraded pass, no restart).
     DB may be in startup race; check_heartbeat_staleness catches persistence
     via Discord OPS alert.

Design rationale:
  - A naive shell ``&& cmd1 || cmd2`` always passes because ``||`` swallows errors.
  - This script is run directly by Docker's ``python config/healthcheck.py`` —
    unhandled exceptions propagate to exit code 1 automatically.
  - Standalone script (not inline ``-c``) so it's testable, maintainable,
    and version-controllable.
"""

import sys

# Module-level import: if scheduler code is corrupt, this raises ImportError
# and the process dies with exit code 1 immediately. No try/except —
# failure at module load is always restart-worthy.
from config.scheduler import start_scheduler  # noqa: F401


def _check() -> int:
    """Probe scheduler heartbeat freshness.

    Returns:
        0 = healthy (heartbeat row within 30 min, or DB unreachable)
        1 = unhealthy (heartbeat stale with DB reachable)
    """
    try:
        from sqlalchemy import text
        from utils.db import get_engine

        with get_engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM agent_runs "
                    "WHERE agent_name = 'scheduler_heartbeat' "
                    "AND created_at > NOW() - INTERVAL '30 minutes' "
                    "LIMIT 1"
                )
            ).fetchone()
        return 0 if row else 1
    except Exception:
        # DB unreachable: degraded pass — container stays up,
        # Discord ops alert will fire via check_heartbeat_staleness if
        # DB returns but heartbeat is still absent.
        return 0


if __name__ == "__main__":
    sys.exit(_check())
