"""T-1502 — Scheduler jobs coverage test (GATE-163 A2).

Asserts scheduler modules are importable, each has __all__ with callable jobs,
register_jobs() works with a mock scheduler, combined job count >= 14,
and no _RUNNING guard starts as True.

Risk notes:
  - MODULE_NAMES must be updated when new scheduler modules are created.
  - register_jobs() signatures vary (scheduler, safe_job) — the test stub
    must match the convention used across all modules.
  - _RUNNING guard detection relies on naming convention (uppercase RUNNING
    in attribute name); non-standard guard names are silently missed.
"""

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

MODULE_NAMES: list[str] = [
    "config.scheduler.deed_jobs",
    "config.scheduler.forecast_jobs",
    "config.scheduler.maintenance_jobs",
]


def _import_module(name: str):
    return __import__(name, fromlist=["__all__"])


def _safe_job_stub(fn, name, *args, **kwargs):
    """Production-safe job wrapper stub.

    Passes only positional args to prevent TypeError from unexpected
    keyword arguments in job handler functions. Follows the same
    contract as utils.scheduler_helpers.safe_job."""
    return fn(*args)


def test_modules_importable():
    for name in MODULE_NAMES:
        try:
            mod = _import_module(name)
            assert mod is not None
        except ImportError as exc:
            pytest.fail(f"ImportError for {name}: {exc}")


def test_all_have_all():
    for name in MODULE_NAMES:
        mod = _import_module(name)
        assert hasattr(mod, "__all__"), f"{name} missing __all__"
        assert isinstance(mod.__all__, list), f"{name}.__all__ is {type(mod.__all__).__name__}, expected list"
        assert len(mod.__all__) > 0, f"{name}.__all__ is empty"


def test_combined_job_count_at_least_14():
    all_jobs: set[str] = set()
    for name in MODULE_NAMES:
        mod = _import_module(name)
        for job in mod.__all__:
            if not job.startswith("_"):
                all_jobs.add(job)
    assert len(all_jobs) >= 14, (
        f"Only {len(all_jobs)} public jobs across {len(MODULE_NAMES)} modules, "
        f"need >= 14. Current: {sorted(all_jobs)}"
    )


def test_all_job_functions_callable():
    non_callable: list[str] = []
    for name in MODULE_NAMES:
        mod = _import_module(name)
        for job_name in mod.__all__:
            attr = getattr(mod, job_name, None)
            if attr is None:
                non_callable.append(f"{name}.{job_name} is None")
            elif not callable(attr):
                non_callable.append(f"{name}.{job_name} ({type(attr).__name__})")
    assert not non_callable, "Non-callable entries in __all__:\n" + "\n".join(non_callable)


def test_register_jobs_works_with_mock():
    for name in MODULE_NAMES:
        mod = _import_module(name)
        assert hasattr(mod, "register_jobs"), f"{name} missing register_jobs"
        mock_scheduler = MagicMock()
        try:
            mod.register_jobs(mock_scheduler, _safe_job_stub)
        except TypeError as exc:
            pytest.fail(f"{name}.register_jobs TypeError: {exc}")
        except Exception as exc:
            pytest.fail(f"{name}.register_jobs raised {type(exc).__name__}: {exc}")


def test_register_jobs_adds_minimum_jobs():
    min_jobs = {
        "config.scheduler.deed_jobs": 5,
        "config.scheduler.forecast_jobs": 3,
        "config.scheduler.maintenance_jobs": 3,
    }
    for name in MODULE_NAMES:
        mod = _import_module(name)
        mock_scheduler = MagicMock()
        mock_scheduler.add_job = MagicMock()
        mod.register_jobs(mock_scheduler, _safe_job_stub)
        actual = mock_scheduler.add_job.call_count
        expected = min_jobs[name]
        assert actual >= expected, (
            f"{name}.register_jobs added {actual} jobs (need >= {expected}). "
            f"New jobs may need to be registered."
        )


def test_register_jobs_passes_callable_and_id():
    for name in MODULE_NAMES:
        mod = _import_module(name)
        mock_scheduler = MagicMock()
        mock_scheduler.add_job = MagicMock()
        mod.register_jobs(mock_scheduler, _safe_job_stub)
        for i, call_args in enumerate(mock_scheduler.add_job.call_args_list):
            args, kwargs = call_args
            assert callable(args[0]), (
                f"{name} add_job call #{i}: first arg not callable"
            )
            assert "id" in kwargs, (
                f"{name} add_job call #{i}: missing 'id' in kwargs"
            )
            assert isinstance(kwargs["id"], str) and len(kwargs["id"]) > 0, (
                f"{name} add_job call #{i}: 'id' is empty or not a string"
            )


def test_running_guards_start_false():
    for name in MODULE_NAMES:
        mod = _import_module(name)
        found = 0
        for attr_name in dir(mod):
            if attr_name.startswith("_") and "RUNNING" in attr_name.upper():
                val = getattr(mod, attr_name, None)
                if isinstance(val, bool):
                    found += 1
                    assert val is False, (
                        f"{name}.{attr_name} starts as True — "
                        f"concurrent-run guard must be False at import time"
                    )
        assert found >= 1, (
            f"{name} has no boolean _RUNNING guard variable — add one "
            f"if the module has concurrency-sensitive jobs"
        )
