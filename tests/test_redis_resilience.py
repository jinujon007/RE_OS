"""T-1261/T-1262/T-1264: Redis resilience tests."""

import threading
import time
from unittest.mock import patch, MagicMock

import pytest

pytestmark = pytest.mark.unit


class TestRedisLazyReconnect:
    """T-1261: Lazy reconnect on _REDIS_CLIENT_INSTANCE = False."""

    def _reset_state(self):
        from dashboard import state as s
        s._REDIS_CLIENT_INSTANCE = None
        s._last_redis_attempt = 0.0

    def test_redis_reconnects_after_false_sentinel(self):
        self._reset_state()
        from dashboard.state import _get_redis_client
        from dashboard import state as s
        s._REDIS_CLIENT_INSTANCE = False
        with patch("dashboard.state._attempt_redis_connect") as mock_attempt:
            mock_attempt.side_effect = lambda: setattr(s, "_REDIS_CLIENT_INSTANCE", MagicMock())
            result = _get_redis_client()
            assert result is not None
            mock_attempt.assert_called_once()

    def test_redis_reconnect_not_attempted_within_30s(self):
        from dashboard import state as s
        s._REDIS_CLIENT_INSTANCE = False
        s._last_redis_attempt = time.monotonic()
        with patch("dashboard.state._attempt_redis_connect") as mock_attempt:
            from dashboard.state import _get_redis_client
            result = _get_redis_client()
            assert result is None
            mock_attempt.assert_not_called()

    def test_redis_returns_false_if_reconnect_fails(self):
        self._reset_state()
        from dashboard.state import _get_redis_client
        from dashboard import state as s
        s._REDIS_CLIENT_INSTANCE = False
        with patch("dashboard.state._attempt_redis_connect") as mock_attempt:
            mock_attempt.side_effect = lambda: setattr(s, "_REDIS_CLIENT_INSTANCE", False)
            result = _get_redis_client()
            assert result is None
            mock_attempt.assert_called_once()

    def test_redis_returns_existing_client_when_connected(self):
        """R1.12: Positive test — returns the existing valid client unchanged."""
        self._reset_state()
        from dashboard.state import _get_redis_client
        from dashboard import state as s
        fake_client = MagicMock()
        s._REDIS_CLIENT_INSTANCE = fake_client
        with patch("dashboard.state._attempt_redis_connect") as mock_attempt:
            result = _get_redis_client()
            assert result is fake_client
            mock_attempt.assert_not_called()


class TestRedisHealthCheck:
    """T-1262: Tests use _run_health_check() directly — deterministic, no thread flakiness (R1.10)."""

    def _reset_state(self):
        from dashboard import state as s
        s._REDIS_CLIENT_INSTANCE = None
        s._last_redis_attempt = 0.0

    def test_redis_health_loop_defined(self):
        from dashboard.redis_health import _redis_health_loop, _run_health_check
        assert callable(_redis_health_loop)
        assert callable(_run_health_check)

    def test_run_health_check_resets_client_on_ping_failure(self):
        self._reset_state()
        from dashboard.redis_health import _run_health_check
        from dashboard import state as s
        fake_redis = MagicMock()
        fake_redis.ping.side_effect = Exception("ping failed")
        s._REDIS_CLIENT_INSTANCE = fake_redis
        _run_health_check()
        assert s._REDIS_CLIENT_INSTANCE is False

    def test_run_health_check_resets_gauge_on_ping_failure(self):
        self._reset_state()
        from dashboard.redis_health import _run_health_check
        from dashboard import state as s
        fake_redis = MagicMock()
        fake_redis.ping.side_effect = Exception("ping failed")
        s._REDIS_CLIENT_INSTANCE = fake_redis
        with patch("dashboard.redis_health._redis_gauge") as mock_gauge:
            _run_health_check()
            mock_gauge.set.assert_called_with(0)

    def test_run_health_check_logs_reconnect(self):
        self._reset_state()
        from dashboard.redis_health import _run_health_check
        from dashboard import state as s
        import logging
        s._REDIS_CLIENT_INSTANCE = False
        s._last_redis_attempt = 0.0
        fake_redis = MagicMock()
        def reconnect_side_effect():
            s._REDIS_CLIENT_INSTANCE = fake_redis
        with patch("dashboard.state._attempt_redis_connect", side_effect=reconnect_side_effect), \
             patch.object(logging.getLogger("re_os.dashboard"), "info") as mock_log:
            _run_health_check()
            mock_log.assert_any_call("Redis reconnected")

    def test_run_health_check_sets_gauge_true_on_reconnect(self):
        self._reset_state()
        from dashboard.redis_health import _run_health_check
        from dashboard import state as s
        s._REDIS_CLIENT_INSTANCE = False
        s._last_redis_attempt = 0.0
        fake_redis = MagicMock()
        def reconnect_side_effect():
            s._REDIS_CLIENT_INSTANCE = fake_redis
        with patch("dashboard.state._attempt_redis_connect", side_effect=reconnect_side_effect), \
             patch("dashboard.redis_health._redis_gauge") as mock_gauge:
            _run_health_check()
            mock_gauge.set.assert_called_with(1)


class TestRedisExhaustionGracefulDegradation:
    """T-1264: Redis pool-exhaustion graceful degradation."""

    def _reset_state(self):
        from dashboard import state as s
        s._REDIS_CLIENT_INSTANCE = None
        s._last_redis_attempt = 0.0

    def test_redis_exhaustion_returns_false(self):
        self._reset_state()
        from dashboard import state as s
        import redis
        with patch("redis.from_url") as mock_from_url, \
             patch("dashboard.state._REDIS_CLIENT_LOCK", threading.Lock()):
            mock_from_url.side_effect = redis.ConnectionError("Connection pool exhausted")
            from dashboard.state import _attempt_redis_connect
            _attempt_redis_connect()
            assert s._REDIS_CLIENT_INSTANCE is False

    def test_redis_exhaustion_logs_warning(self):
        self._reset_state()
        from dashboard import state as s
        import redis
        import logging
        with patch("redis.from_url") as mock_from_url, \
             patch("dashboard.state._REDIS_CLIENT_LOCK", threading.Lock()), \
             patch.object(logging.getLogger("re_os.dashboard"), "warning") as mock_log:
            mock_from_url.side_effect = redis.ConnectionError("all connections busy")
            from dashboard.state import _attempt_redis_connect
            _attempt_redis_connect()
            assert any("Connection pool exhausted or unavailable" in str(c) for c in mock_log.call_args_list)
