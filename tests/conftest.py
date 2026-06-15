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
os.environ.setdefault("DASHBOARD_API_KEY", "test-api-key")

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
