"""T-1263: Pool-exhaustion Discord alert tests."""

from unittest.mock import patch, MagicMock

import pytest

pytestmark = pytest.mark.unit


class TestPoolExhaustionAlert:
    """T-1263: Pool-exhaustion Discord alert fires when pool is saturated."""

    def _make_mock_engine(self, size=10, overflow=5, checkedout=15):
        mock_engine = MagicMock()
        mock_pool = MagicMock()
        mock_pool.size.return_value = size
        mock_pool.overflow.return_value = overflow
        mock_pool.checkedout.return_value = checkedout
        mock_engine.pool = mock_pool
        return mock_engine

    def test_pool_exhaustion_alert_fires(self):
        from utils.db import _check_pool_exhaustion
        mock_engine = self._make_mock_engine()
        with patch("utils.db._pool_is_exhausted", False), \
             patch("utils.db._pool_exhaustion_lock", MagicMock()), \
             patch("utils.discord_notifier.AlertSuppressor.suppress", return_value=False) as mock_suppress, \
             patch("utils.discord_notifier.send_ops_alert") as mock_alert:
            _check_pool_exhaustion(mock_engine)
            mock_suppress.assert_called_once_with("db_pool_exhausted", cooldown_hours=4)
            mock_alert.assert_called_once()
            assert mock_alert.call_args[0][0] == "db_pool_exhausted"

    def test_pool_exhaustion_alert_suppressed_by_flag(self):
        """R1.13: Uses boolean flag, not real time, so this test is deterministic."""
        from utils.db import _check_pool_exhaustion
        mock_engine = self._make_mock_engine()
        with patch("utils.db._pool_is_exhausted", True), \
             patch("utils.discord_notifier.send_ops_alert") as mock_alert:
            _check_pool_exhaustion(mock_engine)
            mock_alert.assert_not_called()

    def test_pool_exhaustion_clears_flag_when_available(self):
        """Verify _pool_is_exhausted resets when connections free up."""
        from utils.db import _check_pool_exhaustion
        mock_engine = self._make_mock_engine(checkedout=5)
        with patch("utils.db._pool_is_exhausted", True):
            _check_pool_exhaustion(mock_engine)
        from utils.db import _pool_is_exhausted
        assert _pool_is_exhausted is False
