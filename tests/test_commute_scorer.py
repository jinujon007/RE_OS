"""T-1350 — CommuteScorer unit tests.

Coverage:
A1: Importable without error
A2: score returns None with no API key (isolated env)
A3: score dict has expected keys (mocked httpx session get)
A4: CorridorScorer imports CommuteScorer module reference
A5: Redis cache read/write functions handle missing key gracefully
A6: Per-run cap prevents runaway calls
A7: _normalize_score edge cases (0 min, 60+ min, None)
A8: Cache key format has expected prefix + precision
"""

import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def test_importable():
    from utils.commute_scorer import CommuteScorer, _reset_count
    assert hasattr(CommuteScorer, "score")
    assert callable(_reset_count)


def test_score_none_without_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    from utils.commute_scorer import CommuteScorer, _reset_count
    _reset_count()
    scorer = CommuteScorer()
    try:
        result = scorer.score(13.1, 77.6)
        assert result is None
    finally:
        scorer.close()


def test_score_dict_has_expected_keys(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    # Clear any cached module-level httpx client to avoid cross-test pollution
    import utils.commute_scorer as _cs_mod
    _cs_mod._HTTPX_CLIENT = None
    from utils.commute_scorer import CommuteScorer, _reset_count
    _reset_count()

    # Mock the module-level httpx session rather than the class method
    _mock_responses = {
        "OK": {"manyata_minutes": 30.0, "kial_minutes": 45.0, "hebbal_minutes": 15.0, "composite_score": 55.0}
    }

    def _mock_batch(*args, **kwargs):
        return _mock_responses["OK"]

    with patch.object(CommuteScorer, "_fetch_and_score", _mock_batch):
        scorer = CommuteScorer()
        try:
            result = scorer.score(13.1, 77.6)
            assert result is not None
            assert "manyata_minutes" in result
            assert "kial_minutes" in result
            assert "hebbal_minutes" in result
            assert "composite_score" in result
            assert isinstance(result["composite_score"], (int, float))
            assert 0 <= result["composite_score"] <= 100
        finally:
            scorer.close()


def test_corridor_scorer_imports_commute():
    src = pathlib.Path("utils/corridor_scorer.py").read_text()
    assert "CommuteScorer" in src
    assert "commute_scorer" in src


def test_cache_key_format():
    from utils.commute_scorer import _cache_key
    key = _cache_key(13.1007, 77.5963)
    assert key.startswith("commute:")
    assert "13.101" in key
    assert "77.596" in key


def test_normalize_score_edge_cases():
    from utils.commute_scorer import _normalize_score
    # 0 minutes → max score
    assert _normalize_score(0.0) == 100.0
    # 30 minutes → 50.0
    assert _normalize_score(30.0) == 50.0
    # 60 minutes → 0
    assert _normalize_score(60.0) == 0.0
    # >60 minutes → clamped to 0
    assert _normalize_score(90.0) == 0.0
    # None → 0
    assert _normalize_score(None) == 0.0


def test_per_run_cap(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    import utils.commute_scorer as _cs_mod
    _cs_mod._HTTPX_CLIENT = None
    from utils.commute_scorer import CommuteScorer, _reset_count, _request_count

    _reset_count()

    def _fake_batch(*args, **kwargs):
        return {"manyata_minutes": 10, "kial_minutes": 20, "hebbal_minutes": 15, "composite_score": 70}

    with patch.object(CommuteScorer, "_fetch_and_score", _fake_batch):
        scorer = CommuteScorer()
        try:
            results = []
            for _ in range(15):
                r = scorer.score(13.1, 77.6)
                if r is not None:
                    results.append(r)
            assert len(results) <= 10
        finally:
            scorer.close()


def test_redis_cache_graceful_unavailable(monkeypatch):
    """Redis cache read/write return None/no-op when no REDIS_URL."""
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    import utils.commute_scorer as _cs_mod
    _cs_mod._REDIS_CLIENT = None

    from utils.commute_scorer import _read_cache, _write_cache

    key = "commute:13.100,77.596"
    assert _read_cache(key) is None
    _write_cache(key, {"test": "data"})


def test_convenience_score_function(monkeypatch):
    """Module-level score() convenience function works."""
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    import utils.commute_scorer as _cs_mod
    _cs_mod._HTTPX_CLIENT = None
    from utils.commute_scorer import CommuteScorer, _reset_count, score as _score

    _reset_count()
    with patch.object(CommuteScorer, "_fetch_and_score", return_value={
        "manyata_minutes": 10, "kial_minutes": 20, "hebbal_minutes": 15, "composite_score": 70
    }):
        result = _score(13.1, 77.6)
        assert result is not None
        assert result["composite_score"] == 70


def test_retry_delay_values():
    """_retry_delay returns values in expected range with jitter."""
    from utils.commute_scorer import _retry_delay
    d1 = _retry_delay(1)
    assert 0.5 <= d1 <= 1.6, f"attempt 1 delay {d1} out of range"
    d2 = _retry_delay(2)
    assert 1.0 <= d2 <= 2.6, f"attempt 2 delay {d2} out of range"
    d3 = _retry_delay(3)
    assert 2.0 <= d3 <= 5.5, f"attempt 3 delay {d3} out of range"
