"""Tests for utils/infrastructure_scorer.py — T-717 infrastructure proximity scorer."""

import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


class TestHaversine:
    def test_haversine_km_known_distance(self):
        """Yelahanka centre to BIAL is ~16km crow flies."""
        from utils.infrastructure_scorer import _haversine_km

        d = _haversine_km(13.1007, 77.5963, 13.1986, 77.7066)
        assert 14 < d < 18, f"Expected ~16km, got {d}"

    def test_haversine_m_zero_distance(self):
        from utils.infrastructure_scorer import _haversine_m

        d = _haversine_m(13.1, 77.6, 13.1, 77.6)
        assert d == 0.0

    def test_haversine_m_conversion(self):
        from utils.infrastructure_scorer import _haversine_km, _haversine_m

        d_km = _haversine_km(13.1, 77.6, 13.2, 77.7)
        d_m = _haversine_m(13.1, 77.6, 13.2, 77.7)
        assert abs(d_m - d_km * 1000) < 0.01


class TestInfrastructureScorer:
    def _make_scorer(self):
        from utils.infrastructure_scorer import InfrastructureScorer

        return InfrastructureScorer()

    def test_score_returns_dataclass(self):
        scorer = self._make_scorer()
        r = scorer.score(13.1007, 77.5963, "Yelahanka")
        assert r.market == "Yelahanka"
        assert r.lat == 13.1007
        assert r.lng == 77.5963

    def test_distances_populated(self):
        """Score from a point offset from metro, verify positive distances."""
        scorer = self._make_scorer()
        r = scorer.score(13.1100, 77.6000, "Yelahanka")
        assert r.dist_to_nearest_metro_m is not None
        assert r.dist_to_nearest_metro_m > 200
        assert r.dist_to_nh44_m is not None
        assert r.dist_to_bial_km is not None
        assert r.dist_to_cbd_km is not None

    def test_empty_market_returns_none_metro(self):
        scorer = self._make_scorer()
        r = scorer.score(0, 0, "")
        assert r.dist_to_nearest_metro_m is None
        assert r.dist_to_nh44_m is not None  # global refs always computed

    def test_unknown_market_returns_no_metro(self):
        scorer = self._make_scorer()
        r = scorer.score(12.0, 77.0, "Nonexistent")
        assert r.dist_to_nearest_metro_m is None

    def test_hebbal_distances_realistic(self):
        scorer = self._make_scorer()
        r = scorer.score(13.0358, 77.5970, "Hebbal")
        assert r.dist_to_nh44_m is not None
        assert 1000 < r.dist_to_nh44_m < 5000
        # Hebbal to BIAL ~22km crow flies
        assert r.dist_to_bial_km is not None
        assert 18 < r.dist_to_bial_km < 28

    def test_road_distances_flag_false_when_no_graph(self):
        scorer = self._make_scorer()
        r = scorer.score(13.1007, 77.5963, "Yelahanka")
        assert r.road_distances_available is False

    def test_road_distances_flag_true_when_graph_loaded(self):
        mock_G = MagicMock()
        mock_G.nodes.__getitem__.return_value = {"y": 13.1, "x": 77.6}
        with (
            patch("utils.infrastructure_scorer._load_graph", return_value=mock_G),
            patch("utils.infrastructure_scorer._nearest_node", return_value=12345),
            patch("utils.infrastructure_scorer._road_distance_m", return_value=500.0),
            patch(
                "utils.infrastructure_scorer._compute_walkability",
                return_value=(7.5, 35),
            ),
        ):
            scorer = self._make_scorer()
            r = scorer.score(13.1007, 77.5963, "Yelahanka")
            assert r.road_distances_available is True
            assert r.dist_to_nearest_metro_m == 500.0
            assert r.walkability_score == 7.5
            assert r.poi_count_15min == 35

    def test_graph_load_failure_falls_back_to_haversine(self):
        with patch("utils.infrastructure_scorer._load_graph", return_value=None):
            scorer = self._make_scorer()
            r = scorer.score(13.1007, 77.5963, "Yelahanka")
            assert r.road_distances_available is False
            assert r.dist_to_nearest_metro_m is not None  # haversine still works

    def test_nearest_node_none_uses_haversine(self):
        mock_G = MagicMock()
        with (
            patch("utils.infrastructure_scorer._load_graph", return_value=mock_G),
            patch("utils.infrastructure_scorer._nearest_node", return_value=None),
        ):
            scorer = self._make_scorer()
            r = scorer.score(13.1007, 77.5963, "Yelahanka")
            assert r.road_distances_available is False


class TestWriteToDb:
    def test_write_to_db_returns_bool(self):
        from utils.infrastructure_scorer import (
            InfrastructureScorer,
            InfrastructureScore,
        )

        s = InfrastructureScore(
            lat=13.1, lng=77.6, market="Yelahanka", dist_to_nearest_metro_m=500.0
        )
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            mock_eng.return_value.begin.return_value.__exit__.return_value = False
            scorer = InfrastructureScorer()
            assert scorer.write_to_db(s) is True

    def test_write_to_db_db_failure_returns_false(self):
        from utils.infrastructure_scorer import (
            InfrastructureScorer,
            InfrastructureScore,
        )

        s = InfrastructureScore(lat=13.1, lng=77.6, market="Yelahanka")
        with patch("utils.db.get_engine", side_effect=Exception("DB down")):
            scorer = InfrastructureScorer()
            assert scorer.write_to_db(s) is False
