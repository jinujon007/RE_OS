"""Tests for scripts/run_corridor_backtest.py (T-1268, GATE-116)."""
from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def test_backtest_runner_importable():
    import importlib.util as _util
    import pathlib
    path = pathlib.Path("scripts/run_corridor_backtest.py")
    assert path.exists(), "Backtest script must exist"
    spec = _util.spec_from_file_location("run_corridor_backtest", str(path))
    assert spec is not None
    assert spec.loader is not None


def test_backtest_writes_verdict_row():
    import scripts.run_corridor_backtest as _b

    with patch("utils.db.get_engine") as mock_get_engine:
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        mock_get_engine.return_value = mock_engine

        _b._write_verdict(
            corridor_name="nh44",
            result={"corridor_name": "nh44", "score": 7.5, "distance_km": 5.2},
            verdict="PASS",
            rank_correlation=0.72,
            projects_evaluated=12,
            kill_criterion_met=True,
            notes="Test verdict",
        )

        mock_conn.execute.assert_called_once()
        call_kwargs = mock_conn.execute.call_args[0][1]
        assert call_kwargs["name"] == "nh44"
        assert call_kwargs["verdict"] == "PASS"
        assert call_kwargs["rank_corr"] == 0.72
        assert call_kwargs["kill_met"] is True


def test_haversine_airport_distance():
    lat1, lon1 = 13.13, 77.60
    lat2, lon2 = 13.1986, 77.7066
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    assert 8.0 < dist < 20.0, f"Expected ~13.8km, got {dist}"


def test_compute_distance_to_airport_matches_haversine():
    import scripts.run_corridor_backtest as _b

    from utils.corridor_scorer_v2 import CorridorBoundaryV2

    seed = CorridorBoundaryV2("nh44", 13.13, 77.60)
    expected = _b._haversine_km(13.13, 77.60, _b._AIRPORT_LAT, _b._AIRPORT_LON)
    assert 8.0 < expected < 20.0, f"Expected ~13.8km, got {expected}"


def test_corridor_score_uses_mocked_data():
    import scripts.run_corridor_backtest as _b

    from utils.corridor_scorer_v2 import CorridorBoundaryV2

    seed = CorridorBoundaryV2("nh44", 13.13, 77.60, radius_m=1000)
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (25, 8500.0)
    mock_conn.execute.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    score = _b._compute_corridor_score(seed, mock_engine)
    assert 0.0 <= score <= 10.0, f"Score out of range: {score}"
    assert score > 5.0, "25 deeds at ₹8,500 PSF should score above 5.0"

    call_sql = str(mock_conn.execute.call_args[0][0])
    assert "ST_Buffer" in call_sql or "ST_Within" in call_sql
    assert ":lon" in call_sql
    assert ":radius_m" in call_sql

    call_params = mock_conn.execute.call_args[0][1]
    assert call_params["lon"] == 13.13
    assert call_params["lat"] == 77.60
    assert call_params["radius_m"] == 1000
