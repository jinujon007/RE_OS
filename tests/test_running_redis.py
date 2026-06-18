"""T-1246: Redis-backed running pipeline state tests."""
import copy
import json
import threading
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


def test_running_state_stored_in_redis():
    """_set_running stores data in Redis hash; _get_running retrieves it."""
    fake_redis = MagicMock()
    fake_redis.hset.return_value = 1
    fake_redis.hget.return_value = json.dumps({"started": "2026-06-17T12:00:00", "pid": 1234, "state": "running"})

    with patch("dashboard.state._get_redis_client", return_value=fake_redis):
        from dashboard.state import _set_running, _get_running, _clear_running

        _clear_running("test_market")
        _set_running("test_market", state="running", pid=1234, started="2026-06-17T12:00:00")
        fake_redis.hset.assert_called_once()
        called_args = fake_redis.hset.call_args
        assert called_args[0][0] == "re_os:pipeline_running"
        assert called_args[0][1] == "test_market"
        stored = json.loads(called_args[0][2])
        assert stored["pid"] == 1234
        assert stored["state"] == "running"

        result = _get_running("test_market")
        assert result is not None
        assert result["pid"] == 1234
        assert result["state"] == "running"


def test_running_fallback_to_memory_on_redis_error():
    """When Redis is unavailable, running state uses in-memory dict fallback."""
    from dashboard.state import _set_running, _get_running, _clear_running, _lock, _running

    with _lock:
        _running.clear()

    with patch("dashboard.state._get_redis_client", return_value=None):
        _set_running("fallback_market", state="running", pid=5678, started="2026-06-17T12:00:00")
        result = _get_running("fallback_market")
        assert result is not None
        assert result["pid"] == 5678

        _clear_running("fallback_market")
        assert _get_running("fallback_market") is None


def test_running_cleared_on_pipeline_completion():
    """_clear_running removes market from both Redis and in-memory store."""
    fake_redis = MagicMock()
    fake_redis.hdel.return_value = 1

    with patch("dashboard.state._get_redis_client", return_value=fake_redis):
        from dashboard.state import _set_running, _get_running, _clear_running

        with patch("dashboard.state._lock", threading.Lock()):
            _set_running("clear_test", state="running", pid=999, started="2026-06-17T12:00:00")
            _clear_running("clear_test")
            fake_redis.hdel.assert_called_once_with("re_os:pipeline_running", "clear_test")

            result = _get_running("clear_test")
            assert result is None


def test_multiple_workers_can_read_running_state():
    """_get_all_running returns all markets' running states from Redis."""
    fake_redis = MagicMock()
    fake_redis.hgetall.return_value = {
        "Yelahanka": json.dumps({"started": "2026-06-17T12:00:00", "pid": 100, "state": "running"}),
        "Devanahalli": json.dumps({"started": "2026-06-17T12:00:00", "pid": 200, "state": "running"}),
    }

    with patch("dashboard.state._get_redis_client", return_value=fake_redis):
        from dashboard.state import _get_all_running

        all_running = _get_all_running()
        assert len(all_running) == 2
        assert "Yelahanka" in all_running
        assert "Devanahalli" in all_running
        assert all_running["Yelahanka"]["pid"] == 100
        assert all_running["Devanahalli"]["pid"] == 200

    # Fallback test: Redis returns empty → falls to in-memory
    fake_redis_empty = MagicMock()
    fake_redis_empty.hgetall.return_value = {}
    with patch("dashboard.state._get_redis_client", return_value=fake_redis_empty), \
         patch("dashboard.state._running", {
             "Hebbal": {"proc": MagicMock(), "started": "2026-06-17T12:00:00"},
         }):
        all_running = _get_all_running()
        assert "Hebbal" in all_running
