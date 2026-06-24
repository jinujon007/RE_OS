"""Tests for ScraperCircuitBreaker (T-1330, GATE-128, R2-audit).

12 tests covering all failure modes + edge cases:
1.  Success on first attempt
2.  Retry on first failure, success on second
3.  Cache fallback when all attempts exhausted (fresh cache)
4.  CircuitOpenError when no cache
5.  CircuitOpenError when cache is stale (>7 days) — _stale_cache_dir fixture
6.  Discord alert on cache fallback
7.  Exponential backoff delays with jitter range
8.  Custom base_delay applied correctly
9.  Per-test error type customization
10. Cache fresh boundary (exactly 7.0, 0.0, -1.0, 7.001 days)
11. max_attempts=1 edge case (single attempt, no retry)
12. CircuitOpenError structured fields (market, attempts_made, last_error)
"""

import json
import os
import tempfile
import time as time_mod
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _mock_sleep():
    """Mock time.sleep to prevent actual waits in all tests.

    Tests that verify sleep behavior (test_exponential_backoff_delays,
    test_custom_base_delay) assert against this mock's call_args_list.
    """
    with patch("utils.scraper_circuit_breaker.time.sleep") as mock:
        yield mock


@pytest.fixture
def _fake_cache_dir():
    """Create a temp dir with checkpoint at expected path and return (dir, path)."""
    tmp = tempfile.mkdtemp()
    cp_dir = os.path.join(tmp, "testmarket", "checkpoints")
    os.makedirs(cp_dir, exist_ok=True)
    cp_path = os.path.join(cp_dir, "rera_scraped_2026-06-19.json")
    with open(cp_path, "w", encoding="utf-8") as f:
        json.dump(["cached_data"], f)
    yield tmp
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def _stale_cache_dir():
    """Create a temp dir with checkpoint at expected path, mtime=8 days ago."""
    tmp = tempfile.mkdtemp()
    cp_dir = os.path.join(tmp, "testmarket", "checkpoints")
    os.makedirs(cp_dir, exist_ok=True)
    cp_path = os.path.join(cp_dir, "rera_scraped_2026-06-19.json")
    with open(cp_path, "w", encoding="utf-8") as f:
        json.dump(["stale_data"], f)
    old_ts = time_mod.time() - 86400 * 8
    os.utime(cp_path, (old_ts, old_ts))
    yield tmp
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


def _make_result(data: str = "test_data"):
    return data


def _make_failing(msg: str = "scrape failed"):
    def _fn(*args, **kwargs):
        raise RuntimeError(msg)
    return _fn


_failing_fn = _make_failing()


def test_success_on_first_attempt():
    """1. Success on first attempt returns data with from_cache=False."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=3, base_delay=30.0)

    with patch.object(cb._checkpointer, "base_dir", "/nonexistent"):
        result = cb.run(_make_result)

    assert result.data == "test_data"
    assert result.from_cache is False
    assert result.cache_age_days is None
    assert result.attempts_made == 1


def test_retry_then_success():
    """2. Fail once, succeed on second attempt."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=3, base_delay=30.0)
    call_count = 0

    def flaky_fn():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("first attempt failed")
        return "retry_success"

    with patch.object(cb._checkpointer, "base_dir", "/nonexistent"):
        result = cb.run(flaky_fn)

    assert result.data == "retry_success"
    assert result.from_cache is False
    assert result.attempts_made == 2


def test_cache_fallback(_fake_cache_dir):
    """3. All attempts fail, fresh cache used.

    Verifies from_cache=True and Discord alert dispatched.
    """
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=3, base_delay=30.0)

    with patch.object(cb._checkpointer, "base_dir", _fake_cache_dir):
        with patch("utils.discord_notifier.send_ops_alert") as mock_alert:
            result = cb.run(_failing_fn)

    assert result.from_cache is True
    assert result.attempts_made == 3
    mock_alert.assert_called_once()
    assert mock_alert.call_args[0][0] == "RERA_SCRAPER_FALLBACK"


def test_circuit_open_no_cache():
    """4. All attempts fail, no cache -> CircuitOpenError."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker, CircuitOpenError

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=3, base_delay=30.0)

    with patch.object(cb._checkpointer, "base_dir", "/nonexistent"):
        with pytest.raises(CircuitOpenError) as exc_info:
            cb.run(_failing_fn)

    assert "3 attempts failed" in str(exc_info.value)


def test_cache_fresh_boundary():
    """10. Cache exactly at max_age (7.0 days) is considered fresh."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=3, base_delay=30.0)
    assert cb._is_cache_fresh(7.0) is True, "Exactly 7.0 days must be fresh"
    assert cb._is_cache_fresh(0.0) is True, "0.0 days must be fresh"
    assert cb._is_cache_fresh(7.001) is False, "7.001 days must be stale"
    assert cb._is_cache_fresh(-1.0) is True, "Negative age (clock skew) must be fresh"


def test_max_attempts_one():
    """11. max_attempts=1: single attempt, no retry, immediate cache fallback or error."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker, CircuitOpenError

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=1, base_delay=10.0)
    call_count: list[int] = [0]

    def _fails_once():
        call_count[0] += 1
        raise RuntimeError("fail")

    with patch.object(cb._checkpointer, "base_dir", "/nonexistent"):
        with pytest.raises(CircuitOpenError):
            cb.run(_fails_once)

    assert call_count[0] == 1, f"Expected 1 attempt, got {call_count[0]}"


def test_circuit_open_structured_fields():
    """12. CircuitOpenError carries structured market/attempts/last_error fields."""
    from utils.scraper_circuit_breaker import CircuitOpenError

    err = CircuitOpenError("test msg", market="Yelahanka", attempts_made=3, last_error="timeout")
    assert err.market == "Yelahanka"
    assert err.attempts_made == 3
    assert err.last_error == "timeout"
    assert "test msg" in str(err)


def test_circuit_open_stale_cache(_stale_cache_dir):
    """5. Cache >7 days old -> CircuitOpenError.
    
    Uses _stale_cache_dir fixture with mtime=8 days ago.
    """
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker, CircuitOpenError

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=3, base_delay=30.0)

    with patch.object(cb._checkpointer, "base_dir", _stale_cache_dir):
        with pytest.raises(CircuitOpenError):
            cb.run(_failing_fn)



def test_discord_alert_on_cache_fallback(_fake_cache_dir):
    """6. Discord alert fired when cache fallback used."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=3, base_delay=30.0)

    with patch.object(cb._checkpointer, "base_dir", _fake_cache_dir):
        with patch("utils.discord_notifier.send_ops_alert") as mock_alert:
            result = cb.run(_failing_fn)

    assert result.from_cache is True
    assert cb._discord_alert_fired is True
    mock_alert.assert_called_once()


def test_exponential_backoff_delays(_mock_sleep):
    """7. Backoff delays are ~30s, ~60s with jitter (assert within ±30%)."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=3, base_delay=30.0)
    call_count = 0

    def fail_twice_then_ok():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError(f"attempt {call_count} failed")
        return "ok"

    with patch.object(cb._checkpointer, "base_dir", "/nonexistent"):
        result = cb.run(fail_twice_then_ok)

    assert result.data == "ok"
    assert result.attempts_made == 3
    sleep_calls = _mock_sleep.call_args_list
    assert len(sleep_calls) == 2, f"Expected 2 sleeps, got {len(sleep_calls)}"
    # Jitter = uniform(0.75, 1.25), so expect 30*0.75=22.5 .. 30*1.25=37.5
    assert 22.0 <= sleep_calls[0][0][0] <= 38.0, (
        f"First delay outside expected range [22,38]: {sleep_calls[0][0][0]}"
    )
    # Second delay = 60 * jitter = 45 .. 75
    assert 44.0 <= sleep_calls[1][0][0] <= 76.0, (
        f"Second delay outside expected range [44,76]: {sleep_calls[1][0][0]}"
    )


def test_custom_base_delay(_mock_sleep):
    """8. Custom base_delay=10 gives backoff ~10s, ~20s with jitter."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=3, base_delay=10.0)
    call_count = 0

    def fail_twice_fn():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError(f"attempt {call_count}")
        return "ok"

    with patch.object(cb._checkpointer, "base_dir", "/nonexistent"):
        result = cb.run(fail_twice_fn)

    assert result.data == "ok"
    assert result.attempts_made == 3
    sleep_calls = _mock_sleep.call_args_list
    assert len(sleep_calls) == 2, f"Expected 2 sleeps, got {len(sleep_calls)}"
    # 10 * 0.75 = 7.5 .. 10 * 1.25 = 12.5
    assert 7.0 <= sleep_calls[0][0][0] <= 13.0
    # 20 * 0.75 = 15 .. 20 * 1.25 = 25
    assert 14.0 <= sleep_calls[1][0][0] <= 26.0


def test_custom_error_type():
    """9. Custom exception type from failing function handled."""
    from utils.scraper_circuit_breaker import ScraperCircuitBreaker, CircuitOpenError

    cb = ScraperCircuitBreaker("TestMarket", max_attempts=1, base_delay=10.0)
    with patch.object(cb._checkpointer, "base_dir", "/nonexistent"):
        with pytest.raises(CircuitOpenError) as exc_info:
            cb.run(_make_failing("custom error type"))
    assert "custom error type" in str(exc_info.value)
