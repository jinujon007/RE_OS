"""GATE-138 behavioral tests — auth, cache, rate limiter."""
import time
from collections import deque
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ── Auth behavior ────────────────────────────────────────────────────────────


@pytest.fixture
def reset_mcp_key():
    import mcp_server.re_os_mcp as mcp
    saved = mcp._MCP_API_KEY
    yield
    mcp._MCP_API_KEY = saved


def test_is_authorized_returns_true_when_no_key_configured(reset_mcp_key):
    """When _MCP_API_KEY is None, all requests pass."""
    import mcp_server.re_os_mcp as mcp
    mcp._MCP_API_KEY = None
    from starlette.datastructures import Headers
    headers = Headers({"x-api-key": ""})
    assert mcp._is_authorized(headers) is True


def test_is_authorized_returns_true_for_correct_key():
    """Correct key → authorized."""
    import mcp_server.re_os_mcp as mcp
    mcp._MCP_API_KEY = "test-key-123"
    from starlette.datastructures import Headers
    headers = Headers({"x-api-key": "test-key-123"})
    assert mcp._is_authorized(headers) is True


def test_is_authorized_returns_false_for_wrong_key():
    """Wrong key → denied."""
    import mcp_server.re_os_mcp as mcp
    mcp._MCP_API_KEY = "real-key"
    from starlette.datastructures import Headers
    headers = Headers({"x-api-key": "wrong-key"})
    assert mcp._is_authorized(headers) is False


def test_is_authorized_returns_false_for_missing_header():
    """Missing header → denied."""
    import mcp_server.re_os_mcp as mcp
    mcp._MCP_API_KEY = "real-key"
    from starlette.datastructures import Headers
    headers = Headers({})
    assert mcp._is_authorized(headers) is False


# ── Cache behavior ───────────────────────────────────────────────────────────


@pytest.fixture
def clear_cache():
    import mcp_server.re_os_mcp as mcp
    mcp._clear_mcp_cache()
    yield
    mcp._clear_mcp_cache()


def test_cache_set_and_get_hit(clear_cache):
    """_mcp_cache_get returns cached value after set."""
    import mcp_server.re_os_mcp as mcp
    assert mcp._mcp_cache_get("psf_forecast", {"a": 1}) is None
    mcp._mcp_cache_set("psf_forecast", {"a": 1}, '{"result": "ok"}')
    assert mcp._mcp_cache_get("psf_forecast", {"a": 1}) == '{"result": "ok"}'


def test_cache_get_returns_none_after_clear(clear_cache):
    """_mcp_cache_get returns None after _clear_mcp_cache runs."""
    import mcp_server.re_os_mcp as mcp
    mcp._mcp_cache_set("psf_forecast", {"x": 2}, '"cached"')
    assert mcp._mcp_cache_get("psf_forecast", {"x": 2}) is not None
    mcp._clear_mcp_cache()
    assert mcp._mcp_cache_get("psf_forecast", {"x": 2}) is None


def test_cache_get_evicts_stale_entry(clear_cache):
    """_mcp_cache_get returns None for entries older than TTL."""
    import mcp_server.re_os_mcp as mcp
    from unittest.mock import patch as _patch

    mcp._mcp_cache_set("corridor_score", {"lat": 12.0, "lon": 77.5}, '"stale"')
    future = time.monotonic() + mcp._MCP_CACHE_TTL + 10
    with _patch("time.monotonic", return_value=future):
        assert mcp._mcp_cache_get("corridor_score", {"lat": 12.0, "lon": 77.5}) is None


def test_cache_respects_max_size(clear_cache):
    """Cache evicts oldest entry when exceeding _MCP_CACHE_MAX."""
    import mcp_server.re_os_mcp as mcp
    mcp._MCP_CACHE_MAX = 3
    mcp._clear_mcp_cache()
    mcp._mcp_cache_set("t", {"i": 1}, '"1"')
    mcp._mcp_cache_set("t", {"i": 2}, '"2"')
    mcp._mcp_cache_set("t", {"i": 3}, '"3"')
    mcp._mcp_cache_set("t", {"i": 4}, '"4"')
    assert mcp._mcp_cache_get("t", {"i": 1}) is None
    assert mcp._mcp_cache_get("t", {"i": 4}) == '"4"'


# ── Rate limiter behavior ────────────────────────────────────────────────────


@pytest.fixture
def reset_rate_limiter():
    import mcp_server.re_os_mcp as mcp
    mcp._RATE_LIMITER.clear()
    mcp._RATE_LIMIT_HITS = 0
    yield


def test_rate_limiter_allows_up_to_limit(reset_rate_limiter):
    """1st through 10th request from same IP all return None (allowed)."""
    import mcp_server.re_os_mcp as mcp
    for _ in range(mcp._RATE_LIMIT_REQS):
        result = mcp._check_rate_limit("1.2.3.4")
        assert result is None, f"Expected None at call {_+1}, got {result!r}"


def test_rate_limiter_rejects_after_limit(reset_rate_limiter):
    """11th request returns retry_after string."""
    import mcp_server.re_os_mcp as mcp
    for _ in range(mcp._RATE_LIMIT_REQS):
        mcp._check_rate_limit("5.6.7.8")
    result = mcp._check_rate_limit("5.6.7.8")
    assert result is not None, "Expected retry_after on 11th request"
    assert result.isdigit(), f"retry_after must be digit string, got {result!r}"


def test_rate_limiter_different_ips_independent(reset_rate_limiter):
    """Two different IPs each get their own bucket."""
    import mcp_server.re_os_mcp as mcp
    for _ in range(mcp._RATE_LIMIT_REQS + 1):
        mcp._check_rate_limit("10.0.0.1")
    assert mcp._check_rate_limit("10.0.0.1") is not None
    assert mcp._check_rate_limit("10.0.0.2") is None


def test_rate_limiter_window_expires(reset_rate_limiter):
    """After window passes, the bucket resets."""
    import mcp_server.re_os_mcp as mcp
    from unittest.mock import patch as _patch

    for _ in range(mcp._RATE_LIMIT_REQS):
        mcp._check_rate_limit("9.9.9.9")
    assert mcp._check_rate_limit("9.9.9.9") is not None
    future = time.monotonic() + mcp._RATE_LIMIT_WINDOW + 1
    with _patch("time.monotonic", return_value=future):
        result = mcp._check_rate_limit("9.9.9.9")
        assert result is None, "Rate limit should reset after window"


def test_rate_limiter_counter_increments(reset_rate_limiter):
    """_RATE_LIMIT_HITS increments on each rejection."""
    import mcp_server.re_os_mcp as mcp
    for _ in range(mcp._RATE_LIMIT_REQS + 2):
        mcp._check_rate_limit("7.7.7.7")
    assert mcp._RATE_LIMIT_HITS > 0
