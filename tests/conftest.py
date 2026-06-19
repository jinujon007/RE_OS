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
