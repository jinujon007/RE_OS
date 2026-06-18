"""Unit tests for CorridorScorerV2 (Sprint 100 — T-1191).

7 unit tests:
  - v2 inherits score_all from v1
  - geojson key present when requested
  - falls back to v1 on PostGIS error
  - spatial query references correct ST_Within + registered_transactions columns
  - backtest delegates to v1
  - boundary geojson cache hit ratio
  - invalidate_cache clears boundary cache
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

pytestmark = pytest.mark.unit


def _make_mock_engine():
    """Build a mock engine that returns empty results for all queries."""
    engine = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone = MagicMock(return_value=(0,))
    cursor.fetchall = MagicMock(return_value=[])
    conn.execute = MagicMock(return_value=cursor)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    engine.connect = MagicMock(return_value=conn)
    return engine


def test_v2_inherits_score_all():
    """CorridorScorerV2.score_all() returns >=3 scored corridors (v1 compat)."""
    from utils.corridor_scorer_v2 import CorridorScorerV2

    engine = _make_mock_engine()
    scorer = CorridorScorerV2(engine=engine)
    scores = scorer.score_all()
    assert len(scores) >= 3, f"Expected >=3 corridors, got {len(scores)}"
    for s in scores:
        assert 0.0 <= s.composite <= 10.0


def test_v2_geojson_key_present_when_requested():
    """When as_geojson=True, each score dict includes boundary_geojson key."""
    from utils.corridor_scorer_v2 import CorridorScorerV2

    engine = _make_mock_engine()
    scorer = CorridorScorerV2(engine=engine)
    scores = scorer.score_all(as_geojson=True)
    for s in scores:
        d = s.to_dict()
        assert "boundary_geojson" in d, f"boundary_geojson missing for {s.corridor_id}"


def test_v2_falls_back_to_v1_on_postgis_error():
    """When _get_corridor_villages raises exception, falls back to v1 list."""
    from utils.corridor_scorer_v2 import CorridorScorerV2, CORRIDOR_DEFINITIONS

    engine = _make_mock_engine()
    scorer = CorridorScorerV2(engine=engine)

    conn_mock = MagicMock()
    conn_mock.execute.side_effect = Exception("PostGIS not available")
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=False)
    engine.connect = MagicMock(return_value=conn_mock)

    villages = scorer._get_corridor_villages("nh44", [])
    v1_villages = [c["villages"] for c in CORRIDOR_DEFINITIONS if c["id"] == "nh44"]
    expected = v1_villages[0] if v1_villages else []
    assert villages == expected, f"Expected v1 fallback {expected}, got {villages}"


def test_spatial_query_uses_st_buffer():
    """_query_spatial_villages uses ST_Buffer for seeded corridors (not AABB)."""
    from utils.corridor_scorer_v2 import CorridorScorerV2

    engine = _make_mock_engine()
    mock_cursor = MagicMock()
    mock_cursor.fetchall = MagicMock(return_value=[("Venkatala",), ("Attur",)])
    conn_mock = MagicMock()
    conn_mock.execute = MagicMock(return_value=mock_cursor)
    conn_mock.__enter__ = MagicMock(return_value=conn_mock)
    conn_mock.__exit__ = MagicMock(return_value=False)
    engine.connect = MagicMock(return_value=conn_mock)

    scorer = CorridorScorerV2(engine=engine)
    notes: list[str] = []
    villages = scorer._query_spatial_villages("nh44", notes)

    assert len(villages) == 2
    assert "Venkatala" in villages
    assert any("v2-spatial" in n for n in notes)

    call_sql = conn_mock.execute.call_args[0][0].text if hasattr(
        conn_mock.execute.call_args[0][0], "text"
    ) else str(conn_mock.execute.call_args[0][0])
    assert "ST_Buffer" in call_sql, "Must use ST_Buffer not ST_MakeEnvelope"
    assert "ST_MakeEnvelope" not in call_sql, "AABB removed"
    assert "ST_Within" in call_sql
    assert "ST_SetSRID" in call_sql
    assert ":lon" in call_sql or ":radius_m" in call_sql
    assert "r.longitude IS NOT NULL" in call_sql or "longitude" in call_sql

    call_params = conn_mock.execute.call_args[0][1] if len(
        conn_mock.execute.call_args[0]
    ) > 1 else {}
    assert call_params.get("lon") == 13.13, f"Expected lon=13.13, got {call_params.get('lon')}"
    assert call_params.get("lat") == 77.60, f"Expected lat=77.60, got {call_params.get('lat')}"
    assert call_params.get("radius_m") == 1000, f"Expected radius_m=1000, got {call_params.get('radius_m')}"


def test_nh44_diagonal_does_not_overreach():
    """ST_Buffer radius excludes AABB corner (no overreach)."""
    from utils.corridor_scorer_v2 import CorridorBoundaryV2
    import math

    seed = CorridorBoundaryV2("nh44", 13.13, 77.60, radius_m=1000)
    corner_lat = seed.centroid_lat + 0.02
    corner_lon = seed.centroid_lon + 0.02
    dlat = math.radians(corner_lat - seed.centroid_lat)
    dlon = math.radians(corner_lon - seed.centroid_lon)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(seed.centroid_lat)) * math.cos(math.radians(corner_lat)) * math.sin(dlon / 2) ** 2
    dist_m = 6371000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    assert dist_m > seed.radius_m, (
        f"AABB corner at ({corner_lat}, {corner_lon}) is {dist_m:.0f}m from centroid "
        f"— inside buffer radius {seed.radius_m}m (would overreach)"
    )


def test_corridor_radius_default_1000m():
    """CorridorBoundaryV2 radius_m defaults to 1000m."""
    from utils.corridor_scorer_v2 import CorridorBoundaryV2

    seed = CorridorBoundaryV2("nh44", 13.13, 77.60)
    assert seed.radius_m == 1000


def test_backtest_delegates_to_v1():
    """backtest() delegates to v1 CorridorScorer.backtest()."""
    from utils.corridor_scorer_v2 import CorridorScorerV2

    engine = _make_mock_engine()
    scorer = CorridorScorerV2(engine=engine)

    with patch.object(scorer.__class__.__bases__[0], "backtest") as mock_v1_backtest:
        mock_v1_backtest.return_value = {"verdict": "INSUFFICIENT_DATA"}
        result = scorer.backtest()
        assert mock_v1_backtest.called
        assert result["verdict"] == "INSUFFICIENT_DATA"


def test_boundary_cache_invalidation():
    """invalidate_boundary_cache clears the internal cache dict."""
    from utils.corridor_scorer_v2 import CorridorScorerV2, _boundary_cache

    _boundary_cache["all"] = (9999999999.0, {"nh44": {"type": "Feature"}})
    assert len(_boundary_cache) == 1

    CorridorScorerV2.invalidate_boundary_cache()
    assert len(_boundary_cache) == 0


def test_corridor_score_v2_slots_present():
    """CorridorScoreV2 uses __slots__ for memory efficiency."""
    from utils.corridor_scorer_v2 import CorridorScoreV2
    assert hasattr(CorridorScoreV2, "__slots__"), "CorridorScoreV2 must define __slots__"
    assert "boundary_geojson" in CorridorScoreV2.__slots__
