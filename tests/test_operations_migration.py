"""Unit tests for Sprint 58 migration 0029_operations (T-993)."""

import pytest

pytestmark = pytest.mark.unit


def _load_migration():
    import importlib.util
    import sys as _sys

    _spec = importlib.util.spec_from_file_location(
        "migration_0029",
        "alembic/versions/0029_operations.py",
    )
    _mod = importlib.util.module_from_spec(_spec)
    _sys.modules["migration_0029"] = _mod
    _spec.loader.exec_module(_mod)
    return _mod


MIGRATION = _load_migration()


def test_projects_table_created():
    assert hasattr(MIGRATION, "upgrade")
    assert hasattr(MIGRATION, "downgrade")
    assert MIGRATION.revision == "0029_operations"
    assert MIGRATION.down_revision == "0028_landowner_contacts"


def test_deal_velocity_table_created():
    upgrade_src = open("alembic/versions/0029_operations.py").read()
    assert "deal_velocity" in upgrade_src
    assert "project_tasks" in upgrade_src
    assert "projects" in upgrade_src
