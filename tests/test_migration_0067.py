"""Migration 0067 — decision_journal table (T-1279)."""
import pytest
import pathlib
import re
pytestmark = pytest.mark.unit

MIG_PATH = pathlib.Path("alembic/versions/0067_decision_journal.py")


def test_migration_file_exists():
    assert MIG_PATH.exists()


def test_migration_contains_table_name():
    content = MIG_PATH.read_text()
    assert "decision_journal" in content


def test_migration_has_required_columns():
    content = MIG_PATH.read_text()
    assert "entry_date" in content
    assert "decision_type" in content
    assert "market" in content
    assert "intel_used" in content
    assert "outcome" in content
    assert "notes" in content
    assert "created_at" in content


def test_migration_has_check_constraints():
    content = MIG_PATH.read_text()
    assert "create_check_constraint" in content
    assert "ck_decision_journal_decision_type" in content
    assert "ck_decision_journal_outcome" in content


def test_migration_correct_down_revision():
    content = MIG_PATH.read_text()
    match = re.search(r'down_revision[:\s\w,\[\]None]*=\s*"([^"]+)"', content)
    assert match, "down_revision not found"
    down_rev = match.group(1)
    assert down_rev == "0066_corridor_backtest_verdicts"


def test_migration_0067_compiles():
    import py_compile
    result = py_compile.compile(str(MIG_PATH), doraise=True)
    assert result is not None
