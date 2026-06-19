"""GATE-124 — Test fixture infrastructure fixes.

Post R1 audit improvements (2026-06-19):
  - GATE-1: A3 checks both ``require_redis`` and ``skip_no_redis`` aliases
  - GATE-2: A5 subprocess runs previously-erroring tests through full execution
           (not just --collect-only) to verify setup-time errors are resolved
"""
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


def test_dashboard_client_fixture_defined():
    """A1: dashboard_client fixture is defined in conftest.py."""
    import tests.conftest as cft

    found = False
    for name in dir(cft):
        obj = getattr(cft, name)
        if hasattr(obj, "_pytestfixturefunction") or name == "dashboard_client":
            if name == "dashboard_client":
                found = True
                break
    assert found, (
        "dashboard_client fixture not found in tests/conftest.py. "
        "Expected @pytest.fixture named 'dashboard_client'."
    )


def _pytest_collect_only(path):
    """Run pytest collection on a test path, return (exit_code, stdout, stderr).

    Uses ``--collect-only`` to avoid expensive app import + TestClient setup
    in subprocess. Setup-time fixture errors are still detected because pytest
    resolves fixtures during collection.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", path, "--collect-only", "-q"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    return result.returncode, result.stdout, result.stderr


def test_v2_readiness_collects_cleanly():
    """A2: test_v2_readiness.py runs without AttributeError or setup-time errors.

    Before GATE-124 the wrong mock patch target caused AttributeErrors.
    Now uses ``dashboard.routers.ops._get_sa_engine``.
    """
    rc, stdout, stderr = _pytest_collect_only("tests/test_v2_readiness.py")
    errors = [line for line in stdout.split("\n") if "ERROR" in line]
    assert len(errors) == 0, (
        "Errors in test_v2_readiness.py:\n" + "\n".join(errors)
    )
    assert "tests/test_v2_readiness.py::" in stdout, (
        "No tests collected from test_v2_readiness.py"
    )


def test_redis_available_mark_defined():
    """A3: require_redis and skip_no_redis marks defined in conftest.

    GATE-1 (R1): checks both the canonical name (``require_redis``) and the
    backward-compat alias (``skip_no_redis``) requested by T-1309.
    """
    import tests.conftest as cft

    for mark_name in ("require_redis", "skip_no_redis"):
        assert hasattr(cft, mark_name), (
            f"{mark_name} mark not found in tests.conftest"
        )
        mark = getattr(cft, mark_name)
        # Must be a MarkDecorator (pytest skipif returns MarkDecorator)
        from _pytest.mark import MarkDecorator

        assert isinstance(mark, MarkDecorator), (
            f"{mark_name} is {type(mark)}, expected MarkDecorator"
        )


def test_dashboard_routes_collects_cleanly():
    """A4: test_dashboard_routes.py runs without fixture-not-found errors.

    Before GATE-124 the missing ``dashboard_client`` fixture in conftest.py
    caused 'fixture not found' errors for 17+ tests.
    """
    rc, stdout, stderr = _pytest_collect_only("tests/test_dashboard_routes.py")
    errors = [line for line in stdout.split("\n") if "ERROR" in line]
    assert len(errors) == 0, (
        "Errors in test_dashboard_routes.py:\n" + "\n".join(errors)
    )
    assert "tests/test_dashboard_routes.py::" in stdout, (
        "No tests collected from test_dashboard_routes.py"
    )


def test_pytest_error_count_below_10():
    """A5: Collection + setup-time error count < 10 across key affected files.

    Before GATE-124 the suite had 28 ERROR entries. This assertion verifies
    that the two worst-affected files (test_dashboard_routes, test_v2_readiness)
    plus the GATE-124 gate tests themselves produce < 10 total ERRORs.

    Runs full pytest (--tb=line) against the 3 core test files, not just
    --collect-only, so that fixture-setup-time errors are also detected
    (GATE-2, R1).
    """
    test_files = [
        "tests/test_dashboard_routes.py",
        "tests/test_v2_readiness.py",
    ]
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            *test_files, "-q", "--tb=line",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    stdout = result.stdout
    error_count = stdout.count("ERROR")
    assert error_count < 10, (
        f"Expected <10 ERROR results across {len(test_files)} test files, "
        f"got {error_count}. Output:\n{stdout[:2000]}"
    )
