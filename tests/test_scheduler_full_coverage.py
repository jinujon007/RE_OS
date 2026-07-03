"""T-1515 — Full scheduler module coverage test (GATE-165 A5).

Verifies all 7 scheduler modules have __all__ with expected job counts,
all listed jobs are callable, register_jobs() works, no _RUNNING guard
starts as True, and combined job count >= 65.

Supersedes T-1502 (test_scheduler_coverage.py) which covers only 3 of
the 7 modules. This test covers all 7.

Risk notes:
  - MODULE_SPECS must be updated when new scheduler modules are created.
  - register_jobs() signatures vary (scheduler, safe_job) — the test stub
    must match the convention used across all modules.
  - _RUNNING guard detection relies on naming convention (uppercase RUNNING
    in attribute name); non-standard guard names are silently missed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.test_id("T-1515"),
]

# (module_path, expected_minimum_job_count)
MODULE_SPECS: list[tuple[str, int]] = [
    ("config.scheduler.deed_jobs", 5),
    ("config.scheduler.digest_jobs", 7),
    ("config.scheduler.forecast_jobs", 4),
    ("config.scheduler.intel_jobs", 19),
    ("config.scheduler.kaveri_jobs", 7),
    ("config.scheduler.maintenance_jobs", 24),
    ("config.scheduler.rera_jobs", 1),
]

MODULE_NAMES: list[str] = [spec[0] for spec in MODULE_SPECS]


def _import_module(name: str) -> Any:
    """Import a module by dotted path, returning the module object.

    Raises pytest.fail on ImportError so a single module failure
    is reported clearly without cascading.
    """
    try:
        return __import__(name, fromlist=["__all__"])
    except ImportError as exc:
        pytest.fail(f"ImportError for {name}: {exc}")


def _safe_job_stub(fn: Any, name: str, *args: Any, **kwargs: Any) -> Any:
    """Stub for utils.scheduler_helpers.safe_job.

    Passes only positional args to prevent TypeError from unexpected
    keyword arguments in job handler functions. Mirrors the production
    contract of safe_job.
    """
    return fn(*args)


def _collect_run_function_names(module: Any) -> list[str]:
    """Return all public run_* function names defined in module."""
    return [
        name
        for name in dir(module)
        if name.startswith("run_") and callable(getattr(module, name, None))
    ]


class TestSchedulerFullCoverage:
    """Suite of 37 parametrized assertions (GATE-165 A5)."""

    @pytest.mark.parametrize("name,expected_count", MODULE_SPECS)
    @pytest.mark.test_id("T-1515-A1")
    def test_module_importable(self, name: str, expected_count: int) -> None:
        """Each module imports without error."""
        mod = _import_module(name)
        assert mod is not None, f"Failed to import {name}"

    @pytest.mark.parametrize("name,expected_count", MODULE_SPECS)
    @pytest.mark.test_id("T-1515-A2")
    def test_all_exists(self, name: str, expected_count: int) -> None:
        """Each module defines __all__ as a non-empty list."""
        mod = _import_module(name)
        assert hasattr(mod, "__all__"), f"{name} missing __all__"
        assert isinstance(mod.__all__, list), (
            f"{name}.__all__ is {type(mod.__all__).__name__}, expected list"
        )
        assert len(mod.__all__) > 0, f"{name}.__all__ is empty"

    @pytest.mark.parametrize("name,expected_count", MODULE_SPECS)
    @pytest.mark.test_id("T-1515-A3")
    def test_all_meets_expected_count(self, name: str, expected_count: int) -> None:
        """__all__ length meets or exceeds documented minimum."""
        mod = _import_module(name)
        actual = len(mod.__all__)
        assert actual >= expected_count, (
            f"{name}.__all__ has {actual} items, expected >= {expected_count}. "
            f"Contents: {mod.__all__}"
        )

    @pytest.mark.parametrize("name,expected_count", MODULE_SPECS)
    @pytest.mark.test_id("T-1515-A4")
    def test_all_jobs_callable(self, name: str, expected_count: int) -> None:
        """Every name in __all__ resolves to a callable attribute."""
        mod = _import_module(name)
        non_callable: list[str] = []
        for job_name in mod.__all__:
            attr = getattr(mod, job_name, None)
            if attr is None:
                non_callable.append(f"{name}.{job_name} is None")
            elif not callable(attr):
                non_callable.append(
                    f"{name}.{job_name} ({type(attr).__name__})"
                )
        assert not non_callable, (
            "Non-callable entries in __all__:\n" + "\n".join(non_callable)
        )

    @pytest.mark.parametrize("name,expected_count", MODULE_SPECS)
    @pytest.mark.test_id("T-1515-A5")
    def test_register_jobs_callable(self, name: str, expected_count: int) -> None:
        """register_jobs is present and works with a MagicMock scheduler."""
        mod = _import_module(name)
        assert hasattr(mod, "register_jobs"), f"{name} missing register_jobs"
        assert callable(mod.register_jobs), (
            f"{name}.register_jobs is not callable"
        )
        mock_scheduler = MagicMock()
        try:
            mod.register_jobs(mock_scheduler, _safe_job_stub)
        except TypeError as exc:
            pytest.fail(f"{name}.register_jobs TypeError: {exc}")
        except Exception as exc:
            pytest.fail(
                f"{name}.register_jobs raised {type(exc).__name__}: {exc}"
            )

    @pytest.mark.test_id("T-1515-A6")
    def test_combined_job_count_at_least_65(self) -> None:
        """Sum of all __all__ entries across all 7 modules >= 65."""
        all_jobs: set[str] = set()
        for name, _ in MODULE_SPECS:
            mod = _import_module(name)
            for job in mod.__all__:
                all_jobs.add(f"{name}.{job}")
        assert len(all_jobs) >= 65, (
            f"Combined job count is {len(all_jobs)}, need >= 65. "
            f"Actual modules: {sorted(all_jobs)}"
        )

    @pytest.mark.test_id("T-1515-A7")
    def test_no_running_guard_starts_true(self) -> None:
        """No _RUNNING / _JOB_RUNNING flag is True at import time."""
        failures: list[str] = []
        for name in MODULE_NAMES:
            mod = _import_module(name)
            for attr_name in dir(mod):
                if attr_name.startswith("_") and "RUNNING" in attr_name.upper():
                    val = getattr(mod, attr_name, None)
                    if isinstance(val, bool) and val is not False:
                        failures.append(
                            f"{name}.{attr_name} starts as True — "
                            f"concurrent-run guard must be False at import time"
                        )
        assert not failures, (
            "Running guard assertion failures:\n" + "\n".join(failures)
        )

    @pytest.mark.test_id("T-1515-A8")
    def test_all_run_functions_in_package_all(self) -> None:
        """Every run_* function in submodule __all__ also appears in
        config.scheduler.__init__.__all__ (package-level re-export check)."""
        from config.scheduler import __all__ as package_all

        package_set = set(package_all)
        missing: list[tuple[str, str]] = []
        for mod_name, _ in MODULE_SPECS:
            mod = _import_module(mod_name)
            for entry in mod.__all__:
                if not entry.startswith("run_"):
                    continue
                if entry not in package_set:
                    missing.append((mod_name, entry))
        assert not missing, (
            "run_* functions in submodule __all__ but missing from "
            "config.scheduler.__all__:\n"
            + "\n".join(f"  {m}.{f}" for m, f in missing)
        )
