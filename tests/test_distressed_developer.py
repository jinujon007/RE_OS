"""
Tests for Distressed Developer Scanner (Sprint 39 — T-479, T-482).
All tests mock the DB connection — no live database required.
"""

import pytest
from unittest.mock import patch

pytestmark = pytest.mark.unit

from tests.helpers import make_mock_engine


class TestDistressedDeveloperScanner:
    """DB query, scoring formula, filtering, sorting."""

    def test_empty_market_returns_empty(self):
        engine = make_mock_engine([])
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers("Yelahanka")
            assert results == []

    def test_all_completed_returns_empty(self):
        engine = make_mock_engine([])
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers("Devanahalli")
            assert results == []

    def test_score_calculation_correct(self):
        engine = make_mock_engine(
            [
                ("Test Builder", "Yelahanka", 3, 2, 2, 12.0, 0.33, 1, 0.65),
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers("Yelahanka")
            assert len(results) == 1
            assert results[0].distress_score == 0.65

    def test_sorted_desc_by_distress_score(self):
        engine = make_mock_engine(
            [
                ("Builder B", "Devanahalli", 2, 1, 1, 18.0, 0.50, 2, 0.82),
                ("Builder A", "Devanahalli", 4, 3, 1, 6.0, 0.25, 0, 0.35),
                ("Builder C", "Devanahalli", 3, 2, 2, 9.0, 0.67, 1, 0.55),
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers("Devanahalli")
            scores = [d.distress_score for d in results]
            assert scores == sorted(scores, reverse=True)

    def test_min_score_threshold(self):
        engine = make_mock_engine(
            [
                ("Builder A", "Hebbal", 3, 1, 2, 15.0, 0.40, 1, 0.75),
                ("Builder B", "Hebbal", 2, 1, 0, 0.0, 0.0, 0, 0.10),
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers("Hebbal", min_score=0.3)
            assert len(results) == 1
            assert results[0].developer_name == "Builder A"

    def test_max_results_limit(self):
        engine = make_mock_engine(
            [
                (f"Builder {i}", "Yelahanka", i, i - 1, 0, 1.0, 0.0, 0, 0.2 * i)
                for i in range(1, 11)
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers("Yelahanka", max_results=3)
            assert len(results) == 3

    def test_db_error_returns_empty(self):
        with patch(
            "utils.distressed_developer.get_engine", side_effect=Exception("DB down")
        ):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers("Yelahanka")
            assert results == []

    def test_distress_score_zero_when_no_delays(self):
        engine = make_mock_engine(
            [
                ("Clean Builder", "Yelahanka", 4, 4, 0, 0.0, 0.0, 0, 0.0),
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers("Yelahanka")
            assert len(results) == 1
            assert results[0].distress_score == 0.0

    def test_alert_level_high_above_07(self):
        engine = make_mock_engine(
            [
                ("Distressed Co", "Yelahanka", 1, 1, 1, 24.0, 1.0, 5, 0.85),
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers("Yelahanka")
            assert results[0].alert_level == "HIGH_DISTRESS"

    def test_alert_level_threshold_boundary(self):
        engine = make_mock_engine(
            [
                ("Builder A", "Yelahanka", 3, 2, 1, 5.0, 0.3, 1, 0.41),
                ("Builder B", "Yelahanka", 3, 2, 1, 6.0, 0.4, 1, 0.39),
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers("Yelahanka", min_score=0.0)
            a = next(d for d in results if d.developer_name == "Builder A")
            b = next(d for d in results if d.developer_name == "Builder B")
            assert a.alert_level == "WATCH"
            assert b.alert_level == "HEALTHY"


class TestDistressedDeveloperScannerClass:
    """DistressedDeveloperScanner class wrapper."""

    def test_scan_returns_list(self):
        engine = make_mock_engine(
            [
                ("Builder A", "Yelahanka", 3, 2, 1, 6.0, 0.3, 1, 0.45),
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import DistressedDeveloperScanner

            scanner = DistressedDeveloperScanner()
            results = scanner.scan("Yelahanka")
            assert len(results) == 1
            assert results[0].developer_name == "Builder A"

    def test_top_n_returns_n(self):
        engine = make_mock_engine(
            [
                (f"Builder {i}", "Yelahanka", 3, 1, 2, 10.0, 0.5, 1, 0.3 * i)
                for i in range(1, 6)
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import DistressedDeveloperScanner

            scanner = DistressedDeveloperScanner()
            results = scanner.top_n("Yelahanka", n=3)
            assert len(results) == 3

    def test_top_n_min_score_filter(self):
        engine = make_mock_engine(
            [
                ("Builder A", "Yelahanka", 2, 1, 1, 12.0, 0.5, 2, 0.65),
                ("Builder B", "Yelahanka", 2, 2, 0, 0.0, 0.0, 0, 0.10),
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import DistressedDeveloperScanner

            scanner = DistressedDeveloperScanner()
            results = scanner.top_n("Yelahanka", n=3, min_score=0.3)
            assert len(results) == 1
            assert results[0].developer_name == "Builder A"

    def test_scanner_no_market_returns_all(self):
        engine = make_mock_engine(
            [
                ("Builder A", "Yelahanka", 2, 1, 1, 6.0, 0.3, 0, 0.35),
                ("Builder B", "Devanahalli", 3, 2, 2, 12.0, 0.4, 1, 0.55),
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import DistressedDeveloperScanner

            scanner = DistressedDeveloperScanner()
            results = scanner.scan(min_score=0.0)
            assert len(results) == 2


class TestFormatDistressAlert:
    """Discord-friendly alert formatting."""

    def test_scan_with_none_market_returns_all(self):
        engine = make_mock_engine(
            [
                ("Builder A", "Yelahanka", 2, 1, 1, 6.0, 0.3, 0, 0.1),
                ("Builder B", "Devanahalli", 3, 2, 2, 12.0, 0.4, 1, 0.2),
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers(market=None, min_score=0.0)
            assert len(results) == 2

    def test_scan_empty_market_name_returns_all(self):
        engine = make_mock_engine(
            [
                ("Builder A", "Yelahanka", 2, 1, 0, 0.0, 0.0, 0, 0.0),
            ]
        )
        with patch("utils.distressed_developer.get_engine", return_value=engine):
            from utils.distressed_developer import scan_distressed_developers

            results = scan_distressed_developers(market="", min_score=0.0)
            assert len(results) == 1

    def test_format_contains_score_and_name(self):
        from utils.distressed_developer import (
            DistressedDeveloper,
            format_distress_alert,
        )

        dev = DistressedDeveloper(
            developer_name="Test Builder",
            market="Yelahanka",
            total_projects=3,
            active_projects=1,
            delayed_projects=2,
            avg_delay_months=12.0,
            incomplete_ratio=0.5,
            complaint_count=2,
            distress_score=0.72,
            alert_level="HIGH_DISTRESS",
        )
        msg = format_distress_alert(dev)
        assert "Test Builder" in msg
        assert "0.72" in msg
        assert "HIGH_DISTRESS" in msg
        assert "JD/JV" in msg
