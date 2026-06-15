"""Unit tests for migration 0055 — parcels table (GATE-92, T-1141).

3 assertions:
(1) Migration file exists with parcels table and FK columns
(2) UNIQUE constraint (village, survey_no) defined
(3) FK columns parcel_id on both rera_projects and registered_transactions
"""

from pathlib import Path
import pytest

pytestmark = pytest.mark.unit

MIGRATION_PATH = Path("alembic/versions/0055_parcels_table.py")


def test_migration_file_exists():
    """Assertion 1: migration file exists with parcels table and FKs."""
    assert MIGRATION_PATH.exists(), "Migration 0055 file not found"
    content = MIGRATION_PATH.read_text()
    assert "parcels" in content
    assert "create_table" in content
    assert "upgrade" in content
    assert "downgrade" in content
    assert "fk_rera_projects_parcel_id" in content


def test_unique_constraint_defined():
    """Assertion 2: UNIQUE(village, survey_no) constraint is defined."""
    content = MIGRATION_PATH.read_text()
    assert "uq_parcels_village_survey_no" in content
    assert "village" in content
    assert "survey_no" in content
    assert "UniqueConstraint" in content


def test_fk_columns_wired():
    """Assertion 3: parcel_id FK columns on rera_projects and registered_transactions."""
    content = MIGRATION_PATH.read_text()
    assert "fk_rera_projects_parcel_id" in content
    assert "fk_registered_transactions_parcel_id" in content
    assert "rera_projects" in content
    assert "registered_transactions" in content
    assert "SET NULL" in content
