"""GATE-132 — Google Maps CommuteScorer into CorridorScorer.

6 assertions (all code-verifiable without Docker):
A1: commute_scorer importable and CommuteScorer.score callable
A2: graceful no-key path (None) without exception
A3: corridor_scorer source references CommuteScorer
A4: Redis cache key format and write pattern present in commute_scorer
A5: intel_board_room sources reference commute context wiring
A6: commute_scorer test suite passes (imported via pytest)
"""

import pathlib
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_gate132_a1_importable():
    from utils.commute_scorer import CommuteScorer, _reset_count, _get_count
    scorer = CommuteScorer()
    assert hasattr(scorer, "score")
    scorer.close()
    assert callable(_reset_count)
    assert callable(_get_count)


def test_gate132_a2_graceful_no_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    from utils.commute_scorer import CommuteScorer, _reset_count
    _reset_count()
    scorer = CommuteScorer()
    try:
        assert scorer.score(13.1, 77.6) is None
    finally:
        scorer.close()


def test_gate132_a3_corridor_scorer_references_commute():
    src = pathlib.Path("utils/corridor_scorer.py").read_text()
    assert "CommuteScorer" in src, \
        "corridor_scorer.py must reference CommuteScorer"
    assert "_W_COMMUTE" in src, \
        "corridor_scorer.py must define _W_COMMUTE weight"


def test_gate132_a4_redis_caching():
    src = pathlib.Path("utils/commute_scorer.py").read_text()
    assert "_CACHE_KEY_PREFIX" in src, \
        "commute_scorer.py must define cache key prefix"
    assert "_read_cache" in src or "_write_cache" in src, \
        "commute_scorer.py must have Redis cache read/write"
    assert "_CACHE_TTL_SECONDS" in src, \
        "commute_scorer.py must define cache TTL"


def test_gate132_a5_intel_board_room_wiring():
    src = pathlib.Path("crews/intel_board_room.py").read_text()
    assert "commute_context" in src, \
        "intel_board_room.py must reference commute context"
    assert "_get_parcel_latlon" in src, \
        "intel_board_room.py must define _get_parcel_latlon"
    assert "_get_commute_context" in src, \
        "intel_board_room.py must define _get_commute_context"
    assert "commute_text" in src, \
        "intel_board_room.py must inject commute_text into BD head task"


def test_gate132_a6_commute_tests_pass():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header",
         str(pathlib.Path("tests/test_commute_scorer.py"))],
        capture_output=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"commute_scorer tests failed (exit {result.returncode})\n"
        f"{result.stderr.decode()[:500]}"
    )
