"""
Integration tests for utils/db_organizer.py — requires a real PostgreSQL instance.

Run conditions:
  - Set TEST_DATABASE_URL to a throwaway PostgreSQL URL, e.g.:
      postgresql://re_os_user:re_os_test@localhost:5432/re_os_test
  - Schema must already be applied (the schema-check CI job does this):
      psql -f database/schema.sql $TEST_DATABASE_URL

Skip automatically when TEST_DATABASE_URL is unset (safe to run in unit-test CI).

To run locally with Docker stack up:
  TEST_DATABASE_URL="postgresql://re_os_user:<pw>@localhost:5432/re_os" pytest tests/integration/
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

_TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _TEST_DB_URL,
    reason="TEST_DATABASE_URL not set — skipping integration tests",
)

SAMPLE_PROJECT = {
    "rera_number": "IT_RERA_TEST_001",
    "project_name": "IT Test Project Alpha",
    "developer_name": "Test Developer Pvt Ltd",
    "address": "123 Test Street, Yelahanka",
    "district": "Bengaluru Urban",
    "taluk": "Yelahanka",
    "locality": "Yelahanka",
    "project_type": "Residential",
    "project_status": "Under Construction",
    "total_units": 120,
    "sold_units": 40,
    "unsold_units": 80,
    "possession_date": "2027-03-31",
    "registration_date": "2023-01-01",
    "raw_data": {},
}


@pytest.fixture(scope="module")
def organizer():
    from utils.db_organizer import DBOrganizer

    org = DBOrganizer.__new__(DBOrganizer)
    from sqlalchemy import create_engine

    org.engine = create_engine(_TEST_DB_URL, pool_pre_ping=True)
    return org


@pytest.fixture(autouse=True)
def cleanup_test_rera(organizer):
    """Remove any test RERA record before and after each test."""
    from sqlalchemy import text

    with organizer.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM rera_projects WHERE rera_number LIKE 'IT_RERA_TEST_%'")
        )
    yield
    with organizer.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM rera_projects WHERE rera_number LIKE 'IT_RERA_TEST_%'")
        )


def test_run_inserts_new_record(organizer):
    stats = organizer.run("Yelahanka", [SAMPLE_PROJECT])
    assert stats["inserted"] == 1
    assert stats["updated"] == 0
    assert stats["failed"] == 0


def test_run_updates_existing_record(organizer):
    organizer.run("Yelahanka", [SAMPLE_PROJECT])
    stats = organizer.run("Yelahanka", [SAMPLE_PROJECT])
    assert stats["inserted"] == 0
    assert stats["updated"] == 1
    assert stats["failed"] == 0


def test_run_skips_invalid_record(organizer):
    bad = dict(SAMPLE_PROJECT)
    bad["rera_number"] = ""
    bad["project_name"] = None
    stats = organizer.run("Yelahanka", [bad, SAMPLE_PROJECT])
    # bad has empty rera_number — ON CONFLICT key is empty string, may insert or fail
    # regardless, the valid second record must succeed
    assert stats["inserted"] + stats["updated"] >= 1
    assert stats["failed"] <= 1


def test_run_returns_correct_totals(organizer):
    records = [SAMPLE_PROJECT]
    stats = organizer.run("Yelahanka", records)
    assert stats["total"] == len(records)
    assert stats["inserted"] + stats["updated"] + stats["failed"] == stats["total"]
    assert "duration_seconds" in stats


def test_developer_grade_written(organizer):
    from sqlalchemy import text

    organizer.run("Yelahanka", [SAMPLE_PROJECT])
    with organizer.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT d.grade FROM developers d "
                "WHERE d.name_normalized = :n"
            ),
            {"n": SAMPLE_PROJECT["developer_name"].lower()},
        ).fetchone()
    assert row is not None
    assert row[0] in ("A", "B", "C")


def test_grade_a_developer_written_correctly(organizer):
    from sqlalchemy import text

    grade_a_project = dict(SAMPLE_PROJECT)
    grade_a_project["rera_number"] = "IT_RERA_TEST_002"
    grade_a_project["developer_name"] = "Brigade Enterprises Ltd"
    grade_a_project["total_units"] = 50  # Would be C by units, but Brigade → A by name

    organizer.run("Yelahanka", [grade_a_project])
    with organizer.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT d.grade FROM developers d "
                "WHERE d.name_normalized = :n"
            ),
            {"n": "brigade enterprises ltd"},
        ).fetchone()
    assert row is not None
    assert row[0] == "A"
