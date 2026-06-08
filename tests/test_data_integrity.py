"""Structural DB invariant checks — all against live DB.

All tests marked integration. Each assertion names the exact violation
for CI/debugging traceability.
"""
import ast
from pathlib import Path

import pytest
from sqlalchemy import text

from utils.db import get_engine

pytestmark = pytest.mark.integration


def test_no_duplicate_rera_numbers():
    """Every rera_number in rera_projects must be unique."""
    with get_engine().connect() as conn:
        dupes = conn.execute(
            text(
                "SELECT rera_number, COUNT(*) AS cnt "
                "FROM rera_projects "
                "WHERE rera_number IS NOT NULL "
                "GROUP BY rera_number "
                "HAVING COUNT(*) > 1"
            )
        ).fetchall()
    assert len(dupes) == 0, (
        f"Found {len(dupes)} duplicate rera_number(s): "
        + "; ".join(f"{r[0]} (count={r[1]})" for r in dupes[:10])
    )


def test_no_orphaned_listings():
    """listings.rera_project_id must reference existing rera_projects."""
    with get_engine().connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM listings "
                "WHERE rera_project_id IS NOT NULL "
                "AND rera_project_id NOT IN (SELECT id FROM rera_projects)"
            )
        ).scalar()
    assert count == 0, f"Found {count} orphaned listings (rera_project_id missing from rera_projects)"


def test_no_orphaned_kaveri_registrations():
    """kaveri_registrations.rera_project_id must reference existing rera_projects."""
    with get_engine().connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM kaveri_registrations "
                "WHERE rera_project_id IS NOT NULL "
                "AND rera_project_id NOT IN (SELECT id FROM rera_projects)"
            )
        ).scalar()
    assert count == 0, (
        f"Found {count} orphaned kaveri_registrations (rera_project_id missing from rera_projects)"
    )


def test_no_zero_psf_guidance_values():
    """guidance_values must not have zero or negative PSF (CHECK constraint)."""
    with get_engine().connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM guidance_values "
                "WHERE guidance_value_psf IS NOT NULL AND guidance_value_psf <= 0"
            )
        ).scalar()
    assert count == 0, f"Found {count} guidance_values with PSF <= 0"


def test_no_empty_string_registration_numbers():
    """kaveri_registrations must not have empty string registration_number."""
    with get_engine().connect() as conn:
        count = conn.execute(
            text(
                "SELECT COUNT(*) FROM kaveri_registrations "
                "WHERE registration_number = ''"
            )
        ).scalar()
    assert count == 0, f"Found {count} kaveri_registrations with empty registration_number"


def test_developer_name_normalized_unique():
    """developers.name_normalized must be unique (no duplicates)."""
    with get_engine().connect() as conn:
        dupes = conn.execute(
            text(
                "SELECT name_normalized, COUNT(*) AS cnt "
                "FROM developers "
                "WHERE name_normalized IS NOT NULL "
                "GROUP BY name_normalized "
                "HAVING COUNT(*) > 1"
            )
        ).fetchall()
    assert len(dupes) == 0, (
        f"Found {len(dupes)} duplicate name_normalized value(s): "
        + "; ".join(f"{r[0]} (count={r[1]})" for r in dupes[:10])
    )


@pytest.mark.unit
def test_integrity_test_file_has_six_assertions():
    """Meta-test: verify the file defines exactly 6 test functions."""
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    test_fns = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    assert len(test_fns) == 6, f"Expected 6 test functions, got {len(test_fns)}: {test_fns}"
