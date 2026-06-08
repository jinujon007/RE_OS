"""Tests for migration 0033_shareholder_sessions."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def mig_mod():
    path = Path("alembic/versions/0033_shareholder_sessions.py")
    spec = importlib.util.spec_from_file_location("mig_0033", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mig_0033"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestShareholderSessionsMigration:
    def test_table_created_in_upgrade(self, mig_mod):
        with patch("alembic.op.create_table") as mock_create, \
             patch("alembic.op.create_check_constraint") as mock_ck, \
             patch("alembic.op.create_index") as mock_idx:
            mig_mod.upgrade()
            mock_create.assert_called_once()
            args, _ = mock_create.call_args
            assert args[0] == "shareholder_sessions"
            assert mock_ck.call_count == 2
            assert mock_idx.call_count == 2

    def test_session_type_constraint_exists(self, mig_mod):
        with patch("alembic.op.create_table"), \
             patch("alembic.op.create_check_constraint") as mock_ck, \
             patch("alembic.op.create_index"):
            mig_mod.upgrade()
            ck_calls = [c[0][0] for c in mock_ck.call_args_list]
            assert "ck_shareholder_sessions_session_type" in ck_calls
            assert "ck_shareholder_sessions_status" in ck_calls

    def test_downgrade_drops_table(self, mig_mod):
        with patch("alembic.op.drop_table") as mock_drop, \
             patch("alembic.op.drop_index"), \
             patch("alembic.op.drop_constraint"):
            mig_mod.downgrade()
            mock_drop.assert_called_once_with("shareholder_sessions")

    def test_migration_revision(self, mig_mod):
        assert mig_mod.revision == "0033_shareholder_sessions"
        assert mig_mod.down_revision == "0032_merge_gcc_token"

    def test_upgrade_is_callable(self, mig_mod):
        assert callable(mig_mod.upgrade)
        assert callable(mig_mod.downgrade)
