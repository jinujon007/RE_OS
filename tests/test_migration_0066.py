"""Migration 0066 — corridor_backtest_verdicts table (T-1266)."""
import pytest
import pathlib
import re
pytestmark = pytest.mark.unit

MIG_PATH = pathlib.Path("alembic/versions/0066_corridor_backtest_verdicts.py")


def test_migration_file_exists():
    assert MIG_PATH.exists()


def test_migration_contains_table_name():
    content = MIG_PATH.read_text()
    assert "corridor_backtest_verdicts" in content


def test_migration_has_required_columns():
    content = MIG_PATH.read_text()
    assert "corridor_name" in content
    assert "run_date" in content
    assert "rank_correlation" in content
    assert "projects_evaluated" in content
    assert "kill_criterion_met" in content
    assert "verdict" in content
    assert "notes" in content
    assert "created_at" in content


def test_migration_has_verdict_check_constraint():
    content = MIG_PATH.read_text()
    assert "create_check_constraint" in content
    assert "PASS" in content
    assert "FAIL" in content
    assert "INSUFFICIENT_DATA" in content


def test_migration_correct_down_revision():
    content = MIG_PATH.read_text()
    match = re.search(r'down_revision[:\s\w,\[\]None]*=\s*"([^"]+)"', content)
    assert match, "down_revision not found"
    down_rev = match.group(1)
    assert down_rev == "0065_corridor_boundaries_v2"
