"""Alembic migration-state integration tests.

All tests are marked ``@pytest.mark.integration`` and auto-skip when
PostgreSQL is unreachable (see ``tests.helpers.db_reachable``).

Created in Sprint 84 (T-1106) to verify the ``alembic check`` command exits
with code 0 after the Sprint 81–83 batch of migrations (0039–0050).
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests.helpers import db_reachable

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not db_reachable(),
    reason="PostgreSQL not reachable — requires live DB (skipped)",
)
def test_alembic_check_passes_post_sprint83() -> None:
    """Verify ``alembic check`` exits 0 — no pending migrations.

    Runs from the repository root directory so Alembic discovers
    ``alembic.ini`` and the ``alembic/`` directory.  Guarded by
    ``db_reachable()`` to skip in CI environments without a running
    PostgreSQL instance.

    The 30-second ``timeout`` parameter prevents indefinite hangs when the
    DB host resolves but rejects connections (e.g., paused Docker container).
    """
    repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"alembic check failed (exit {result.returncode}).\n"
        f"  Fix: docker compose exec agents alembic upgrade head\n"
        f"  --- stdout (last 300 chars) ---\n{result.stdout[-300:]}\n"
        f"  --- stderr (last 300 chars) ---\n{result.stderr[-300:]}"
    )
