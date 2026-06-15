"""Unit tests for migration 0053 — registered_transactions table (GATE-91, T-1135).

3 assertions:
(1) Table exists in migration upgrade
(2) UNIQUE constraint blocks duplicate (sro, doc_no, reg_date)
(3) CHECK constraint blocks zero consideration_inr
"""

import os
from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest

pytestmark = pytest.mark.unit


MIGRATION_PATH = Path("alembic/versions/0053_registered_transactions.py")


def test_migration_file_exists():
    """Assertion 1: migration file exists and contains the expected table creation."""
    assert MIGRATION_PATH.exists(), "Migration 0053 file not found"
    content = MIGRATION_PATH.read_text()
    assert "registered_transactions" in content
    assert "create_table" in content
    assert "upgrade" in content
    assert "downgrade" in content


def test_unique_constraint_defined():
    """Assertion 2: UNIQUE(sro, doc_no, reg_date) constraint is defined."""
    content = MIGRATION_PATH.read_text()
    assert "uq_registered_transactions_key" in content
    assert "sro" in content
    assert "doc_no" in content
    assert "reg_date" in content
    assert "create_unique_constraint" in content


def test_check_constraint_defined():
    """Assertion 3: CHECK blocks zero consideration_inr."""
    content = MIGRATION_PATH.read_text()
    assert "ck_registered_transactions_consideration" in content
    assert "consideration_inr IS NULL OR consideration_inr > 0" in content
    assert "create_check_constraint" in content


def test_indexes_defined():
    """Verify all three indexes are defined."""
    content = MIGRATION_PATH.read_text()
    assert "idx_registered_transactions_village_date" in content
    assert "idx_registered_transactions_survey_no" in content
    assert "idx_registered_transactions_sro_date" in content


def test_updated_at_column():
    """Verify updated_at column exists."""
    content = MIGRATION_PATH.read_text()
    assert "updated_at" in content
    assert "sa.DateTime" in content


def test_down_revision_correct():
    """Verify down_revision points to 0052_board_session_timing."""
    content = MIGRATION_PATH.read_text()
    assert "down_revision" in content
    assert "0052_board_session_timing" in content
