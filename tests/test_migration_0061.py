"""Migration 0061 — parcel_ownership_chain table tests (GATE-99, T-1185)."""

import pytest
import pathlib
pytestmark = pytest.mark.unit

MIG_PATH = pathlib.Path("alembic/versions/0061_parcel_ownership_chain.py")


def test_migration_file_exists():
    assert MIG_PATH.exists(), "Migration file 0061_parcel_ownership_chain.py does not exist"


def test_migration_contains_table_name():
    content = MIG_PATH.read_text()
    assert "parcel_ownership_chain" in content


def test_migration_contains_survey_no_column():
    content = MIG_PATH.read_text()
    assert "survey_no" in content
    assert "sa.String(50)" in content


def test_migration_contains_owner_name():
    content = MIG_PATH.read_text()
    assert "owner_name" in content
    assert "sa.Text()" in content


def test_migration_uses_uuid_pk():
    content = MIG_PATH.read_text()
    assert "sa.UUID()" in content
    assert "gen_random_uuid()" in content


def test_migration_has_parcel_id_fk():
    content = MIG_PATH.read_text()
    assert "parcel_id" in content
    assert "sa.ForeignKey" in content


def test_migration_has_fetched_at_index():
    content = MIG_PATH.read_text()
    assert "idx_parcel_ownership_fetched_at" in content


def test_migration_has_encumbrance_detail():
    content = MIG_PATH.read_text()
    assert "encumbrance_detail" in content


def test_migration_has_govt_acquisition_detail():
    content = MIG_PATH.read_text()
    assert "govt_acquisition_detail" in content


def test_migration_has_parser_completeness_score():
    content = MIG_PATH.read_text()
    assert "parser_completeness_score" in content


def test_migration_unique_constraint():
    content = MIG_PATH.read_text()
    assert "uq_parcel_ownership_chain_daily" in content
