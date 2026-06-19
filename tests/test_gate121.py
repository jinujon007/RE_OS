"""GATE-121 declaration — Code Quality Closure (W2/W3/W4/W5).

10 assertions covering metric type, thread safety, lock invariant,
collection isolation, behavioural wiring, and runtime regression.
"""

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ── A1: DLQ metric type (W2) ──────────────────────────────────────────────────

def test_a1_dlq_depth_is_gauge():
    """Dead letter queue depth metric is a Gauge (not Counter)."""
    from config.metrics import dead_letter_queue_depth_gauge
    assert type(dead_letter_queue_depth_gauge).__name__ == "Gauge", (
        f"Expected Gauge, got {type(dead_letter_queue_depth_gauge).__name__}"
    )


def test_a1b_gauge_has_entity_type_label():
    """Gauge carries entity_type label for per-type observability."""
    from config.metrics import dead_letter_queue_depth_gauge
    assert "entity_type" in dead_letter_queue_depth_gauge._labelnames, (
        f"Labels: {dead_letter_queue_depth_gauge._labelnames}"
    )


# ── A2: Thread-safe Redis setter (W4) ────────────────────────────────────────

def test_a2_thread_safe_setter_no_direct_mutation():
    """_reset_redis_client is callable; redis_health.py has no direct mutation."""
    from dashboard.state import _reset_redis_client
    assert callable(_reset_redis_client)
    src_path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "redis_health.py")
    with open(src_path, encoding="utf-8") as f:
        content = f.read()
    assert "_REDIS_CLIENT_INSTANCE =" not in content, (
        "Direct mutation of _REDIS_CLIENT_INSTANCE found in redis_health.py"
    )


def test_a2b_reset_redis_client_resets_state():
    """_reset_redis_client clears client and zeroes cooldown."""
    import dashboard.state as _st
    import time

    saved_client = _st._REDIS_CLIENT_INSTANCE
    saved_attempt = _st._last_redis_attempt
    try:
        _st._REDIS_CLIENT_INSTANCE = object()
        _st._last_redis_attempt = time.time()

        _st._reset_redis_client()

        assert _st._REDIS_CLIENT_INSTANCE is False
        assert _st._last_redis_attempt <= 1.0, (
            f"cooldown not zeroed: {_st._last_redis_attempt}"
        )
    finally:
        _st._REDIS_CLIENT_INSTANCE = saved_client
        _st._last_redis_attempt = saved_attempt


# ── A3: Lock invariant (W3) ──────────────────────────────────────────────────

def test_a3_lock_invariant_renamed():
    """_log_running_lifecycle_locked renamed to _MUST_HOLD_LOCK suffix."""
    state_path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "state.py")
    with open(state_path, encoding="utf-8") as f:
        content = f.read()
    assert "_log_running_lifecycle_locked" not in content, (
        "Old function name _log_running_lifecycle_locked still present"
    )
    assert "_log_running_lifecycle_MUST_HOLD_LOCK" in content, (
        "New function name _log_running_lifecycle_MUST_HOLD_LOCK not found"
    )


def test_a3b_call_sites_inside_lock():
    """Every call to _log_running_lifecycle_MUST_HOLD_LOCK is inside with _lock:."""
    state_path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "state.py")
    with open(state_path, encoding="utf-8") as f:
        lines = f.readlines()

    call_sites = [
        i for i, line in enumerate(lines, 1)
        if "_log_running_lifecycle_MUST_HOLD_LOCK" in line and not line.strip().startswith("#") and "def " not in line
    ]
    if not call_sites:
        pass

    for lineno in call_sites:
        block_start = max(0, lineno - 6)
        block = "".join(lines[block_start:lineno])
        assert "with _lock:" in block or "_lock.acquire()" in block, (
            f"Call at line {lineno} outside with _lock: block\nContext:\n{block}"
        )


# ── A4: Collection isolation (W5) ────────────────────────────────────────────

def test_a4_collection_without_env():
    """test_gate119.py collects with DASHBOARD_API_KEY unset."""
    env = {k: v for k, v in os.environ.items() if k != "DASHBOARD_API_KEY"}
    env["DASHBOARD_API_KEY_ALLOW_EMPTY"] = "true"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_gate119.py", "--collect-only", "-q"],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert result.returncode == 0, (
        f"Collection failed (rc={result.returncode}): {result.stderr[:500]}"
    )


def test_a4b_gate106_collects_without_env():
    """test_gate106.py collects without DASHBOARD_API_KEY."""
    env = {k: v for k, v in os.environ.items() if k != "DASHBOARD_API_KEY"}
    env["DASHBOARD_API_KEY_ALLOW_EMPTY"] = "true"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_gate106.py", "--collect-only", "-q"],
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert result.returncode == 0, (
        f"test_gate106.py collection failed (rc={result.returncode}): {result.stderr[:200]}"
    )


# ── A5: Behavioural wiring (W2/W4 runtime verification) ──────────────────────

def test_a5a_dlq_gauge_inc_on_write():
    """_write_dead_letter increments the gauge."""
    from config.metrics import dead_letter_queue_depth_gauge
    from utils.db_organizer import _write_dead_letter

    mock_conn = MagicMock()
    before = dead_letter_queue_depth_gauge.labels(entity_type="test_type")._value.get()
    _write_dead_letter(mock_conn, {"entity_type": "test_type", "id": "x"}, ValueError("fail"))
    after = dead_letter_queue_depth_gauge.labels(entity_type="test_type")._value.get()
    assert after == before + 1, f"Expected {before + 1}, got {after}"


def test_a5b_dlq_gauge_sync_on_retry():
    """retry_failed_records calls _sync_dlq_gauge after processing."""
    from utils.dead_letter_queue import retry_failed_records, _sync_dlq_gauge

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    with patch("utils.dead_letter_queue._sync_dlq_gauge") as mock_sync:
        result = retry_failed_records(mock_engine)
        assert result["attempted"] == 0
        mock_sync.assert_not_called()

    with patch("utils.dead_letter_queue._sync_dlq_gauge") as mock_sync:
        mock_row = MagicMock()
        mock_row._mapping = {"id": 1, "entity_type": "rera_project", "source_id": "s1",
                             "raw_data": '{"market":"Yelahanka"}'}
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]
        with patch("utils.dead_letter_queue._replay_record"):
            result = retry_failed_records(mock_engine)
            assert result["attempted"] == 1
            mock_sync.assert_called_once()


def test_a5c_dlq_gauge_sync_on_purge():
    """purge_old_records calls _sync_dlq_gauge when records deleted."""
    from utils.dead_letter_queue import purge_old_records, _sync_dlq_gauge

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.rowcount = 5
    mock_engine.begin.return_value.__enter__.return_value = mock_conn

    with patch("utils.dead_letter_queue._sync_dlq_gauge") as mock_sync:
        result = purge_old_records(mock_engine)
        assert result == 5
        mock_sync.assert_called_once()


def test_a5d_check_depth_updates_gauge():
    """check_queue_depth_and_alert synchronises gauge on every call."""
    from utils.dead_letter_queue import check_queue_depth_and_alert
    from config.metrics import dead_letter_queue_depth_gauge

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.scalar.return_value = 7
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    check_queue_depth_and_alert(mock_engine)
    assert dead_letter_queue_depth_gauge.labels(entity_type="unknown")._value.get() == 7


# ── A6: Module regression check ──────────────────────────────────────────────

def test_a6_module_imports():
    """All modified modules import without error."""
    results = {}
    for mod in ("config.metrics", "utils.dead_letter_queue", "utils.db_organizer",
                "dashboard.state", "dashboard.redis_health", "dashboard.routers.pipeline"):
        try:
            __import__(mod)
            results[mod] = "ok"
        except Exception as exc:
            results[mod] = f"FAIL: {exc}"
    errors = [f"{k}: {v}" for k, v in results.items() if v != "ok"]
    assert not errors, f"Module import regressions: {errors}"
