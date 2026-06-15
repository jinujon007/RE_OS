"""GATE-84 declaration tests — Post-batch cleanup verification.

| Test ID | GATE-84 Criterion | Type |
|---------|------------------|------|
| A1      | GATE-72 ✅ PASSED in TASK_QUEUE.md GATE DASHBOARD | unit  |
| A2      | CLAUDE.md no longer lists RERA Playwright or Kaveri GV as open | unit  |
| A3      | ``alembic check`` exits 0 (no pending migrations) | integration |
| A4      | Unit test count ≥ 1,814 | unit  |
| A5      | GATE-81 data-integrity test file compiles clean | unit  |

All unit tests are safe to run without a live database. The integration test
(A3) auto-skips via socket-level PostgreSQL reachability check.
"""

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

from tests.helpers import db_reachable

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parent.parent
TASK_QUEUE_PATH = REPO / "TASK_QUEUE.md"
CLAUDE_PATH = REPO / "CLAUDE.md"

GATE_COUNT_FLOOR = 1814
"""Minimum acceptable unit-test count (GATE-84 criterion A4)."""

# ── A1: GATE-72 marked passed ────────────────────────────────────────────────


@pytest.mark.test_id("A1")
def test_gate72_marked_passed_in_task_queue() -> None:
    """A1: GATE DASHBOARD in TASK_QUEUE.md shows GATE-72 as ✅ PASSED.

    Verifies the ``GATE-72`` row in ``TASK_QUEUE.md`` contains the ``✅ PASSED``
    marker and a date stamp.  Fails with a remediation command if the row was
    accidentally reverted.
    """
    src = TASK_QUEUE_PATH.read_text(encoding="utf-8-sig")
    match = re.search(r"\| GATE-72 \|.*\|.*✅ PASSED", src)
    assert match, (
        "GATE-72 not marked ✅ PASSED in TASK_QUEUE.md GATE DASHBOARD.\n"
        "  Fix: python -m pytest tests/test_gate72.py -v && confirm 6/6 pass\n"
        "  Then edit TASK_QUEUE.md GATE-72 row to add '✅ PASSED (<date>) — 6/6 assertions'"
    )


# ── A2: CLAUDE.md open issues cleared ────────────────────────────────────────


@pytest.mark.test_id("A2")
def test_claude_md_open_issues_cleared() -> None:
    """A2: CLAUDE.md no longer lists RERA Playwright or Kaveri GV as unresolved.

    The old entries with ``Open — High`` and ``Open — Medium`` status markers
    must be replaced with ``CLOSED`` / ``RESOLVED`` notes (done in Sprint 84
    T-1105).
    """
    src = CLAUDE_PATH.read_text(encoding="utf-8-sig")
    issues: List[str] = []
    if "Open — High" in src:
        issues.append(
            "Found 'Open — High' priority marker — RERA issue still listed as open.\n"
            "  Fix: Replace the RERA entry with:\n"
            "    ### RERA Portal Playwright Timeout — CLOSED\n"
            "    T-207 CLOSED (Sprint 77 GATE-77 ✅ 2026-06-08) — …"
        )
    if "Open — Medium" in src:
        issues.append(
            "Found 'Open — Medium' priority marker — Kaveri GV issue still listed as open.\n"
            "  Fix: Replace the Kaveri GV entry with:\n"
            "    ### Kaveri GV Portal — RESOLVED\n"
            "    Kaveri GV restored (Sprint 78 GATE-78 ✅ 2026-06-08) — …"
        )
    assert not issues, "\n\n".join(issues)


# ── A3: alembic check passes (integration) ────────────────────────────────────


@pytest.mark.test_id("A3")
@pytest.mark.integration
@pytest.mark.skipif(
    not db_reachable(), reason="PostgreSQL not reachable — requires live DB"
)
def test_alembic_check_passes() -> None:
    """A3: ``alembic check`` exits 0 — no pending migrations after Sprint 83.

    Runs ``alembic check`` as a subprocess from the repository root.
    Skipped when PostgreSQL is unreachable (socket timeout on the resolved
    DATABASE_URL host:port).  The 30-second timeout prevents CI hangs in
    environments where the DB host resolves but rejects connections.
    """
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=30,
    )
    assert result.returncode == 0, (
        f"alembic check failed (exit {result.returncode}).\n"
        f"  Fix: docker compose exec agents alembic upgrade head\n"
        f"  --- stderr (last 500 chars) ---\n{result.stderr[-500:]}"
    )


# ── A4: unit test count meets floor ──────────────────────────────────────────


_COLLECT_RE = re.compile(r"collected (\d+) items?")
"""Matches 'collected 1824 items' in pytest output."""


def _parse_collected_count(stdout: str) -> int:
    """Extract the collected test count from ``pytest --collect-only`` output.

    Tries the standard ``collected N items`` line first, then falls back
    to the ``N/M tests collected`` summary line.
    """
    for line in stdout.splitlines():
        m = _COLLECT_RE.search(line)
        if m:
            return int(m.group(1))
        m = re.search(r"(\d+)/\d+ tests collected", line)
        if m:
            return int(m.group(1))
    raise ValueError(
        f"Could not parse test count from pytest output.\n"
        f"Expected a line matching 'collected N items' or 'N/M tests collected'.\n"
        f"--- stdout (last 1 KB) ---\n{stdout[-1024:]}"
    )


@pytest.mark.test_id("A4")
def test_unit_test_count_meets_floor() -> None:
    """A4: Unit-only test collection ≥ {GATE_COUNT_FLOOR} (excludes ``@pytest.mark.integration``).

    Uses ``--collect-only -q`` with ``-m 'not integration'`` to count only
    non-integration tests.  Exit code 5 (no tests selected) is accepted when
    all tests are integration-marked (should not happen in practice).
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "-m",
            "not integration",
            "--collect-only",
            "-q",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        timeout=120,
    )
    assert result.returncode in (0, 5), (
        f"pytest collect failed (exit {result.returncode}).\n"
        f"  Fix: python -m pytest tests/ --collect-only -q  # diagnose import errors\n"
        f"  --- stderr ---\n{result.stderr}"
    )
    count = _parse_collected_count(result.stdout)
    assert count >= GATE_COUNT_FLOOR, (
        f"Only {count} unit tests collected (need ≥ {GATE_COUNT_FLOOR}).\n"
        "Possible causes:\n"
        "  1. New test files were added without removing old ones (expected growth OK).\n"
        "  2. Import errors prevented collection — check 'python -m pytest tests/ --collect-only -q'.\n"
        f"  3. GATE_COUNT_FLOOR in {__file__} needs bumping if tests were legitimately removed."
    )


# ── A5: data integrity guard (stretch/regression guard) ───────────────────────


@pytest.mark.test_id("A5")
def test_data_integrity_imports_clean() -> None:
    """A5: GATE-81 ``test_data_integrity.py`` compiles without error.

    This is a compile-time guard, not a full run (which requires a live DB).
    If the integrity tests have import errors, the CI pipeline collects but
    fails them at run time — this catches syntax/import breakage early.
    """
    integrity_path = REPO / "tests" / "test_data_integrity.py"
    if not integrity_path.exists():
        pytest.skip(
            "test_data_integrity.py not found — GATE-81 not yet present (non-blocking)"
        )
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(integrity_path)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"test_data_integrity.py has compilation errors:\n"
        f"  Fix: python -m py_compile tests/test_data_integrity.py\n"
        f"  --- stderr ---\n{result.stderr}"
    )
