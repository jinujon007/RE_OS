"""T-963: IntelPackage partial-failure cache TTL tests."""
import time as real_time
from unittest.mock import patch, MagicMock
import pytest
pytestmark = pytest.mark.unit


def _make_pkg(survey_no="45/2", market="Yelahanka", all_ok=True):
    from intelligence.registry import IntelPackage
    return IntelPackage(
        survey_no=survey_no, market=market,
        collected_at="2026-06-06T00:00:00",
        all_modules_success=all_ok,
    )


def test_partial_failure_cached_5min():
    """all_modules_success=False -> TTL=300s (not 3600s)."""
    from intelligence.registry import _LRUCache, _PARTIAL_TTL, _POSITIVE_TTL
    cache = _LRUCache()
    pkg = _make_pkg(all_ok=False)
    with patch("intelligence.registry.time.time", return_value=1000.0):
        cache.set("k1", pkg)
    entry = cache._store.get("k1")
    assert entry is not None
    expiry, _ = entry
    assert expiry == pytest.approx(1000.0 + _PARTIAL_TTL), "Should use 300s TTL"
    assert expiry < 1000.0 + _POSITIVE_TTL, "Must NOT use 3600s TTL"


def test_full_success_cached_60min():
    """all_modules_success=True -> TTL=3600s."""
    from intelligence.registry import _LRUCache, _POSITIVE_TTL
    cache = _LRUCache()
    pkg = _make_pkg(all_ok=True)
    with patch("intelligence.registry.time.time", return_value=1000.0):
        cache.set("k2", pkg)
    entry = cache._store.get("k2")
    assert entry is not None
    expiry, _ = entry
    assert expiry == pytest.approx(1000.0 + _POSITIVE_TTL), "Should use 3600s TTL"


def test_expired_entry_evicted_by_get():
    from intelligence.registry import _LRUCache
    cache = _LRUCache()
    pkg = _make_pkg(all_ok=False)
    with patch("intelligence.registry.time.time", return_value=1000.0):
        cache.set("k_exp", pkg)
    with patch("intelligence.registry.time.time", return_value=2000.0):
        result = cache.get("k_exp")
    assert result is None, "Expired entry must return None from get()"


def test_force_refresh_clears_partial_cache():
    from intelligence.registry import IntelRegistry

    reg = IntelRegistry()
    with patch.object(reg._cache, "get") as mock_get:
        with patch.object(reg, "_run_module") as mock_run:
            with patch("intelligence._shared.validate_market", return_value={"name": "Yelahanka"}):
                reg.get_full_picture("45/2", "Yelahanka", force_refresh=True)
    mock_get.assert_not_called()
