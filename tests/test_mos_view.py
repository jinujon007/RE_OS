"""Tests for v_market_brief months_of_supply fix (migration 0022).

Verifies:
- mos_raw is capped at 120.0 via LEAST (Tier 1/2 hard cap)
- Migration file contains expected SQL patterns
- Supply label uses capped value for classification
"""

import pytest
import os

pytestmark = pytest.mark.unit

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _load_migration_sql() -> str:
    path = os.path.join(_PROJECT_ROOT, "alembic", "versions", "0022_fix_mos_view.py")
    import importlib.util

    spec = importlib.util.spec_from_file_location("migration_0022", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._NEW_VIEW


def test_mos_capped_at_120():
    sql = _load_migration_sql()
    assert "LEAST" in sql and "120.0" in sql


def test_mos_has_tier_1_sufficient_data():
    sql = _load_migration_sql()
    assert "total_count >= 12" in sql


def test_mos_has_tier_2_sparse_cap():
    sql = _load_migration_sql()
    assert "total_count > 0" in sql


def test_mos_has_tier_3_fallback():
    sql = _load_migration_sql()
    assert "mos_fallback" in sql


def test_supply_label_uses_capped_mos():
    sql = _load_migration_sql()
    assert "LEAST(mc.mos_raw, 120.0) < 9" in sql
    assert "LEAST(mc.mos_raw, 120.0) <= 18" in sql


def test_mos_quality_column_present():
    sql = _load_migration_sql()
    assert "mos_quality" in sql
    assert "kaveri_sufficient" in sql
    assert "kaveri_sparse" in sql
    assert "absorption_fallback" in sql
    assert "insufficient_data" in sql


def test_mos_unrestricted_column_present():
    sql = _load_migration_sql()
    assert "mos_unrestricted" in sql
    assert "mos_raw" in sql


def test_zero_inventory_returns_null_mos():
    sql = _load_migration_sql()
    assert "WHEN mc.total_projects = 0" in sql
    assert "THEN NULL::numeric" in sql
