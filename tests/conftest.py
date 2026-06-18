"""
Pytest configuration — sets env vars and stubs heavy dependencies before any imports.
"""

import os
import sys
import types
from unittest.mock import MagicMock

# Required by config/settings.py — must be set before any module-level import
os.environ.setdefault("DB_PASSWORD", "test_password_for_pytest")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://re_os_user:test_password_for_pytest@localhost:5432/re_os",
)
os.environ.setdefault("REDIS_URL", "memory://")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")

# ── crewai stub ────────────────────────────────────────────────────────────────
# Stubs LLM, Agent, Task, Crew, Process, and crewai.tools so every module that
# imports from crewai can be imported in tests without a live crewai install.
if "crewai" not in sys.modules:
    _crewai_stub = types.ModuleType("crewai")
    _crewai_stub.LLM = MagicMock
    _crewai_stub.Agent = MagicMock
    _crewai_stub.Task = MagicMock
    _crewai_stub.Crew = MagicMock
    _crewai_stub.Process = types.SimpleNamespace(sequential="sequential")
    sys.modules["crewai"] = _crewai_stub

    _crewai_tools = types.ModuleType("crewai.tools")
    _crewai_tools.BaseTool = MagicMock
    sys.modules["crewai.tools"] = _crewai_tools

    sys.modules["crewai_tools"] = types.ModuleType("crewai_tools")

# ── litellm stub ───────────────────────────────────────────────────────────────
# crewai pulls in litellm; stub it when absent so agent/crew imports don't break.
if "litellm" not in sys.modules:
    _litellm_mod = types.ModuleType("litellm")
    _litellm_exc = types.ModuleType("litellm.exceptions")

    class _RateLimitError(Exception):
        def __init__(self, *args, llm_provider=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.llm_provider = llm_provider

    class _NotFoundError(Exception):
        def __init__(self, *args, llm_provider=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.llm_provider = llm_provider

    _litellm_exc.RateLimitError = _RateLimitError
    _litellm_exc.NotFoundError = _NotFoundError
    _litellm_mod.exceptions = _litellm_exc
    _litellm_mod.completion = MagicMock(return_value=MagicMock())
    _litellm_mod.success_callback = []
    sys.modules["litellm"] = _litellm_mod
    sys.modules["litellm.exceptions"] = _litellm_exc

# ── playwright stub ────────────────────────────────────────────────────────────
if "playwright" not in sys.modules:
    for _mod_name in ("playwright", "playwright.sync_api"):
        _m = types.ModuleType(_mod_name)
        _m.sync_playwright = MagicMock()
        sys.modules[_mod_name] = _m

# ── sqlalchemy stub ────────────────────────────────────────────────────────────
# Stub only when NOT installed — so the stub never fires in CI where sqlalchemy
# is pip-installed. try/except avoids clobbering a real install.
try:
    import sqlalchemy as _sa_check  # noqa: F401
except ImportError:
    _sa = types.ModuleType("sqlalchemy")
    _sa.create_engine = MagicMock(return_value=MagicMock())
    _sa.text = MagicMock(side_effect=lambda s: s)
    sys.modules["sqlalchemy"] = _sa

# ── flask_limiter stub ─────────────────────────────────────────────────────────
try:
    import flask_limiter as _fl_check  # noqa: F401
except ImportError:
    _fl = types.ModuleType("flask_limiter")
    _fl_util = types.ModuleType("flask_limiter.util")
    _fl_util.get_remote_address = MagicMock(return_value="127.0.0.1")

    class _FakeLimiter:
        def __init__(self, *a, **kw):
            pass

        def init_app(self, *a, **kw):
            pass

        def limit(self, *a, **kw):
            def decorator(f):
                return f

            return decorator

        def exempt(self, f):
            return f

    _fl.Limiter = _FakeLimiter
    sys.modules["flask_limiter"] = _fl
    sys.modules["flask_limiter.util"] = _fl_util

# ── flask_cors stub ───────────────────────────────────────────────────────────
try:
    import flask_cors as _fc_check  # noqa: F401
except ImportError:
    _fc = types.ModuleType("flask_cors")
    _fc.CORS = MagicMock()
    sys.modules["flask_cors"] = _fc

# ── psycopg2 stub ──────────────────────────────────────────────────────────────
try:
    import psycopg2 as _pg2_check  # noqa: F401
except ImportError:
    _pg2 = types.ModuleType("psycopg2")
    _pg2_pool = types.ModuleType("psycopg2.pool")
    _pg2.pool = _pg2_pool
    _pg2.OperationalError = Exception
    _pg2.connect = MagicMock()
    _pg2_pool.ThreadedConnectionPool = MagicMock()
    sys.modules["psycopg2"] = _pg2
    sys.modules["psycopg2.pool"] = _pg2_pool

# ── apscheduler stub ─────────────────────────────────────────────────────────
try:
    import apscheduler as _aps_check  # noqa: F401
except ImportError:
    _aps = types.ModuleType("apscheduler")
    _aps_sched = types.ModuleType("apscheduler.schedulers")
    _aps_sched_blocking = types.ModuleType("apscheduler.schedulers.blocking")

    class _FakeBlockingScheduler:
        def __init__(self, *a, **kw):
            pass

        def add_job(self, *a, **kw):
            pass

        def start(self):
            pass

        def get_jobs(self):
            return []

    class _FakeCronTrigger:
        def __init__(self, *a, **kw):
            pass

    _aps_sched_blocking.BlockingScheduler = _FakeBlockingScheduler
    _aps.schedulers = _aps_sched
    _aps_sched.blocking = _aps_sched_blocking

    _aps_triggers = types.ModuleType("apscheduler.triggers")
    _aps_triggers_cron = types.ModuleType("apscheduler.triggers.cron")
    _aps_triggers_cron.CronTrigger = _FakeCronTrigger
    _aps.triggers = _aps_triggers
    _aps_triggers.cron = _aps_triggers_cron

    sys.modules["apscheduler"] = _aps
    sys.modules["apscheduler.schedulers"] = _aps_sched
    sys.modules["apscheduler.schedulers.blocking"] = _aps_sched_blocking
    sys.modules["apscheduler.triggers"] = _aps_triggers
    sys.modules["apscheduler.triggers.cron"] = _aps_triggers_cron

# ── slowapi stub (for FastAPI tests) ──────────────────────────────────────
try:
    import slowapi as _slowapi_check  # noqa: F401
except ImportError:
    _slowapi = types.ModuleType("slowapi")
    _slowapi_util = types.ModuleType("slowapi.util")
    _slowapi_util.get_remote_address = MagicMock(return_value="127.0.0.1")
    _slowapi_errors = types.ModuleType("slowapi.errors")
    _slowapi_errors.RateLimitExceeded = Exception

    class _FakeLimiter:
        def __init__(self, *a, **kw):
            pass

        def init_app(self, *a, **kw):
            pass

        def limit(self, *a, **kw):
            def decorator(f):
                return f

            return decorator

        def exempt(self, f):
            return f

    _slowapi.Limiter = _FakeLimiter
    _slowapi.util = _slowapi_util
    _slowapi.errors = _slowapi_errors
    sys.modules["slowapi"] = _slowapi
    sys.modules["slowapi.util"] = _slowapi_util
    sys.modules["slowapi.errors"] = _slowapi_errors

# ── Integration test fixture: ephemeral PostGIS ───────────────────────────
import os as _os
import socket as _socket
import subprocess as _subprocess
import time as _time
from urllib.parse import urlparse as _urlparse
from uuid import uuid4 as _uuid4

import pytest
from loguru import logger as _logger
from sqlalchemy import create_engine as _create_engine


def _docker_available() -> bool:
    """Return True if the docker CLI is reachable."""
    try:
        r = _subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check whether a TCP port is accepting connections."""
    try:
        with _socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _pg_ready_socket(host: str, port: int) -> bool:
    """Check PostgreSQL readiness via socket (works without pg_isready CLI)."""
    return _port_open(host, port)


@pytest.fixture(scope="session")
def live_engine():
    """Spin up ephemeral PostGIS for integration tests.

    If ``TEST_DATABASE_URL`` is set (CI mode), use the pre-existing DB.
    Otherwise, start a throw-away postgis/postgis:15-3.3 Docker container,
    run Alembic migrations, yield a connected Engine, then tear down.

    **Side effects** (intentional):
    - Sets ``os.environ["DATABASE_URL"]`` and ``config.settings.DATABASE_URL``
    - Clears engine singletons in ``utils.db``, ``utils.db_organizer``,
      and ``utils.agent_memory`` so all ``get_engine()`` callers use the
      test DB.

    **Container lifecycle safety:**
    - Randomized suffix prevents name collisions in parallel CI runners.
    - Socket-level readiness check (no ``pg_isready`` CLI dependency).
    - Alembic stderr captured on failure for debugging.
    - Docker teardown runs even if migrations fail (try/finally via yield).
    - ``docker_available`` guard skips gracefully when Docker is absent.
    """
    url = _os.environ.get("TEST_DATABASE_URL")
    _own_container = False
    container_name = f"re_os_test_db_{_uuid4().hex[:8]}"
    host = "localhost"
    port = 5433

    if not url:
        if not _docker_available():
            pytest.skip("Docker not available — cannot start ephemeral PostGIS")

        _logger.info("Starting ephemeral PostGIS container: {}", container_name)
        _subprocess.run(
            [
                "docker", "run", "-d", "--name", container_name,
                "-e", "POSTGRES_PASSWORD=testpass",
                "-p", f"{port}:5432",
                "postgis/postgis:15-3.3",
            ],
            check=True, capture_output=True,
        )

        for attempt in range(30):
            if _pg_ready_socket(host, port):
                break
            _time.sleep(1)
        else:
            # Last-ditch: try pg_isready in case socket check was wrong
            r = _subprocess.run(
                ["pg_isready", "-h", host, "-p", str(port), "-U", "postgres"],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                _subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
                raise RuntimeError(
                    f"Postgres container {container_name} did not become ready in 30s. "
                    f"pg_isready: {r.stderr.strip()}"
                )

        url = f"postgresql://postgres:testpass@{host}:{port}/postgres"
        _own_container = True

    # ── Force all DB consumers to use the test URL ────────────────────────
    _os.environ["DATABASE_URL"] = url
    import config.settings as _settings
    _settings.DATABASE_URL = url

    _logger.debug("Integration test DB URL: {}", url)

    # Clear ALL known engine singletons
    import utils.db as _udb
    _udb._engine = None
    import utils.db_organizer as _udbo
    _udbo._SHARED_ENGINE = None
    import utils.agent_memory as _uam
    _uam._engine = None

    engine = _create_engine(url)

    if _own_container:
        _logger.info("Running Alembic migrations on test DB")
        result = _subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True, text=True,
            env={**_os.environ, "DATABASE_URL": url, "DB_PASSWORD": "testpass"},
        )
        if result.returncode != 0:
            _subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            raise RuntimeError(
                f"Alembic upgrade failed:\n"
                f"stdout: {result.stdout[-2000:]}\n"
                f"stderr: {result.stderr[-2000:]}"
            )

    yield engine

    engine.dispose()
    if _own_container:
        _subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        _logger.info("Ephemeral PostGIS container removed: {}", container_name)
