"""GATE-81 declaration — DB Integrity Lock.

Six assertions:
1. alembic heads = 1 head (single chain, no branching)
2. listings FK delete_rule = 'SET NULL'
3. kaveri_registrations FK delete_rule = 'SET NULL'
4. idx_rera_projects_developer_id exists
5. idx_listings_price_psf exists
6. All 6 test_data_integrity.py assertions pass

All pass → GATE-81 ✅.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from utils.db import get_engine

pytestmark = pytest.mark.integration


def _fk_delete_rule(conn, pattern: str) -> str:
    return conn.execute(
        text(
            "SELECT delete_rule FROM information_schema.referential_constraints "
            "WHERE constraint_name LIKE :pattern"
        ),
        {"pattern": pattern},
    ).fetchone()[0]


def _index_exists(conn, tablename: str, indexname: str) -> bool:
    return (
        conn.execute(
            text(
                "SELECT 1 FROM pg_indexes "
                "WHERE tablename=:tablename AND indexname=:indexname"
            ),
            {"tablename": tablename, "indexname": indexname},
        ).fetchone()
        is not None
    )


def test_alembic_single_head():
    """Assertion 1: alembic has exactly 1 head."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_alembic_health.py",
            "-q",
            "--tb=short",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parents[1],
    )
    assert result.returncode == 0, (
        f"Alembic head test failed:\n{result.stdout}\n{result.stderr}"
    )


def test_listings_fk_set_null():
    """Assertion 2: listings FK delete_rule = SET NULL."""
    with get_engine().connect() as conn:
        rule = _fk_delete_rule(conn, "listings_rera%")
    assert rule == "SET NULL", f"Expected SET NULL, got {rule}"


def test_kaveri_registrations_fk_set_null():
    """Assertion 3: kaveri_registrations FK delete_rule = SET NULL."""
    with get_engine().connect() as conn:
        rule = _fk_delete_rule(conn, "kaveri_registrations_rera%")
    assert rule == "SET NULL", f"Expected SET NULL, got {rule}"


def test_developer_id_index_present():
    """Assertion 4: idx_rera_projects_developer_id exists."""
    with get_engine().connect() as conn:
        assert _index_exists(conn, "rera_projects", "idx_rera_projects_developer_id"), (
            "idx_rera_projects_developer_id not found in pg_indexes"
        )


def test_price_psf_index_present():
    """Assertion 5: idx_listings_price_psf exists."""
    with get_engine().connect() as conn:
        assert _index_exists(conn, "listings", "idx_listings_price_psf"), (
            "idx_listings_price_psf not found in pg_indexes"
        )


def test_data_integrity_suite_passes():
    """Assertion 6: all 6 test_data_integrity.py assertions pass."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_data_integrity.py",
            "-m",
            "integration",
            "-q",
            "--tb=short",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parents[1],
    )
    assert result.returncode == 0, (
        f"Data integrity suite failed:\n{result.stdout}\n{result.stderr}"
    )
