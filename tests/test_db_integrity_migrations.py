"""Tests for GATE-81 migration integrity constraints.

All integration tests require live DB with migrations applied.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from utils.db import get_engine

pytestmark = pytest.mark.integration


def _fk_delete_rule(conn, pattern: str) -> str:
    row = conn.execute(
        text(
            "SELECT delete_rule FROM information_schema.referential_constraints "
            "WHERE constraint_name LIKE :pattern"
        ),
        {"pattern": pattern},
    ).fetchone()
    assert row is not None, f"FK constraint matching {pattern!r} not found"
    return row[0]


def _index_exists(conn, tablename: str, indexname: str) -> bool:
    row = conn.execute(
        text(
            "SELECT 1 FROM pg_indexes "
            "WHERE tablename=:tablename AND indexname=:indexname"
        ),
        {"tablename": tablename, "indexname": indexname},
    ).fetchone()
    return row is not None


def test_listings_fk_is_set_null():
    with get_engine().connect() as conn:
        rule = _fk_delete_rule(conn, "listings_rera%")
    assert rule == "SET NULL", f"Expected SET NULL, got {rule}"


def test_kaveri_registrations_fk_is_set_null():
    with get_engine().connect() as conn:
        rule = _fk_delete_rule(conn, "kaveri_registrations_rera%")
    assert rule == "SET NULL", f"Expected SET NULL, got {rule}"


def test_developer_id_index_exists():
    with get_engine().connect() as conn:
        assert _index_exists(conn, "rera_projects", "idx_rera_projects_developer_id")


def test_price_psf_index_exists():
    with get_engine().connect() as conn:
        assert _index_exists(conn, "listings", "idx_listings_price_psf")


def test_zero_psf_guidance_value_rejected():
    with get_engine().begin() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO guidance_values "
                    "(id, market, locality, property_type, sro, guidance_value_psf, data_source) "
                    "VALUES (:id, 'Test', 'TestLoc', 'Site', 'TestSRO', 0, 'manual_entry')"
                ),
                {"id": str(uuid.uuid4())},
            )
            pytest.fail("Expected IntegrityError for zero PSF")
        except IntegrityError:
            pass


def test_empty_string_registration_number_rejected():
    with get_engine().begin() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO kaveri_registrations "
                    "(id, registration_number, transaction_amount) "
                    "VALUES (:id, '', 100000)"
                ),
                {"id": str(uuid.uuid4())},
            )
            pytest.fail("Expected IntegrityError for empty registration number")
        except IntegrityError:
            pass
