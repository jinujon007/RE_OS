"""Shared test fixtures and helpers (R2 — post GATE-124 R1 audit cleanup)."""

import os
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Mock apscheduler at sys.modules level so config.scheduler submodules
# can be imported outside Docker (apscheduler only available inside container).
try:
    import apscheduler  # noqa: F401
except ImportError:
    _aps_sched = MagicMock()
    sys.modules["apscheduler"] = _aps_sched
    sys.modules["apscheduler.schedulers"] = MagicMock()
    sys.modules["apscheduler.schedulers.blocking"] = MagicMock()
    sys.modules["apscheduler.triggers"] = MagicMock()
    sys.modules["apscheduler.triggers.cron"] = MagicMock()

# Must be set before importing app — rate-limiter uses REDIS_URL at import time.
# These are defaults; individual test files may override via monkeypatch.
os.environ.setdefault("REDIS_URL", "memory://")
os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")

REPO_ROOT = Path(__file__).resolve().parent.parent
"""Absolute path to repository root. All test files should use this instead
of computing their own parent chain."""


def _redis_available(host="127.0.0.1", port=6379, timeout=1.0) -> bool:
    """Check if a Redis server is reachable at host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.error):
        return False


require_redis = pytest.mark.skipif(
    not _redis_available(),
    reason="requires a running Redis server on 127.0.0.1:6379",
)
"""Mark a test as requiring a real Redis server (e.g. rate-limit enforcement tests).
Tests using this mark will be skipped when Docker/Redis is not running.
"""

# Backward-compat alias for task spec name (T-1309)
skip_no_redis = require_redis


def _make_engine(conn: MagicMock) -> MagicMock:
    """Build a mock SQLAlchemy engine that returns *conn* from both
    ``.connect()`` and ``.begin()`` context managers.

    Use in tests that exercise code paths calling either ``get_engine().connect()``
    or ``_get_sa_engine().begin()``.
    """
    eng = MagicMock()
    eng.connect.return_value.__enter__.return_value = conn
    eng.begin.return_value.__enter__.return_value = conn
    return eng


def _make_execute_side_effect(rows: list):
    """Return a ``side_effect`` list for ``MagicMock().execute``.

    Each element in *rows* is a tuple used as the return value for
    ``fetchone()``, ``scalar()``, and ``fetchall()`` on the mock result.

    If an element is ``None`` all three methods return ``None`` (empty result).

    This covers the three SQLAlchemy result patterns used across utils:
      - ``conn.execute(sql).fetchone()``
      - ``conn.execute(sql).scalar()``
      - ``conn.execute(sql).fetchall()``

    For ``fetchall()`` the tuple is wrapped in a list to simulate row iteration.
    """
    results = []
    for r in rows:
        mr = MagicMock()
        mr.fetchone.return_value = r
        mr.scalar.return_value = r[0] if r is not None else None
        mr.fetchall.return_value = [r] if r is not None else []
        results.append(mr)
    return results


@pytest.fixture(scope="module")
def dashboard_client():
    """TestClient for FastAPI app with safe test env (memory:// rate limiter, empty API key allowed).

    Uses ``raise_server_exceptions=False`` so tests that verify error responses
    (500, 422) do not have the test client re-raise the exception.

    Imports are deferred inside the fixture body so that any app-level import
    failure only kills tests that request this fixture, not the entire suite.
    """
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    with TestClient(
        app, raise_server_exceptions=False
    ) as client:
        yield client
