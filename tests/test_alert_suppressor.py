"""Tests for AlertSuppressor (GATE-105 T-1216)."""
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit

from utils.discord_notifier import AlertSuppressor


class TestAlertSuppressor:
    def setup_method(self):
        AlertSuppressor._IN_MEMORY.clear()

    def test_suppressor_blocks_repeat_within_cooldown(self):
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = ("existing_id",)
            assert AlertSuppressor.suppress("TEST_ALERT", cooldown_hours=1) is True

    def test_suppressor_allows_after_cooldown(self):
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = None
            assert AlertSuppressor.suppress("TEST_ALERT_AFTER", cooldown_hours=1) is False

    def test_suppressor_first_alert_always_fires(self):
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = None
            assert AlertSuppressor.suppress("FIRST_ALERT", cooldown_hours=24) is False

    def test_suppressor_in_memory_fallback_on_db_failure(self):
        with patch("utils.db.get_engine", side_effect=Exception("DB down")):
            result = AlertSuppressor.suppress("MEM_FALLBACK", cooldown_hours=1)
            assert result is False, "Should NOT suppress when no previous alert in memory"

    def test_suppressor_in_memory_blocks_repeat_within_cooldown(self):
        AlertSuppressor._IN_MEMORY["MEM_DUP"] = 1000.0
        with patch("utils.db.get_engine", side_effect=Exception("DB down")):
            with patch("utils.discord_notifier._time.time", return_value=1600.0):
                result = AlertSuppressor.suppress("MEM_DUP", cooldown_hours=1)
                assert result is True, "Should suppress when last fire was 600s ago (within 1h cooldown)"

    def test_suppressor_in_memory_allows_after_cooldown(self):
        AlertSuppressor._IN_MEMORY["MEM_EXPIRED"] = 1000.0
        with patch("utils.db.get_engine", side_effect=Exception("DB down")):
            with patch("utils.discord_notifier._time.time", return_value=10000.0):
                result = AlertSuppressor.suppress("MEM_EXPIRED", cooldown_hours=1)
                assert result is False, "Should NOT suppress when last fire was 9000s ago (past 1h cooldown)"

    def test_suppressor_does_not_update_memory_when_db_works(self):
        AlertSuppressor._IN_MEMORY.clear()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = None
            result = AlertSuppressor.suppress("DB_OK_CHECK", cooldown_hours=1)
            assert result is False
            assert AlertSuppressor._IN_MEMORY.get("DB_OK_CHECK") is None, "In-memory should NOT be updated when DB works"
