"""T-1038/T-1040 — MobilityScout + compute_market_accessibility tests (GATE-74)."""

import types
from unittest.mock import MagicMock, patch, call

import pytest

pytestmark = pytest.mark.unit


class TestMobilityScout:
    def test_returns_empty_without_api_key(self):
        from scrapers.mobility_scout import MobilityScout

        scout = MobilityScout()
        scout.api_key = ""
        results = scout.measure_travel_times("Yelahanka")
        assert results == []

    def test_returns_empty_for_unknown_market(self):
        from scrapers.mobility_scout import MobilityScout

        scout = MobilityScout()
        scout.api_key = "test_key"
        results = scout.measure_travel_times("UnknownCity")
        assert results == []

    def test_travel_time_seconds_to_minutes_conversion(self):
        from scrapers.mobility_scout import MobilityScout

        scout = MobilityScout()
        scout.api_key = "test_key"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 1500},
                            "distance": {"value": 25000},
                        }
                    ]
                }
            ],
        }

        with patch(
            "scrapers.mobility_scout.requests.Session.get", return_value=mock_resp
        ):
            results = scout.measure_travel_times("Yelahanka")
            assert len(results) > 0
            assert results[0]["travel_time_min"] == 25.0
            assert results[0]["distance_km"] == 25.0

    def test_returns_empty_on_api_error(self):
        from scrapers.mobility_scout import MobilityScout

        scout = MobilityScout()
        scout.api_key = "test_key"
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch(
            "scrapers.mobility_scout.requests.Session.get", return_value=mock_resp
        ):
            results = scout.measure_travel_times("Hebbal")
            assert results == []

    def test_retries_on_over_query_limit(self):
        from scrapers.mobility_scout import MobilityScout

        fail_resp = MagicMock()
        fail_resp.status_code = 200
        fail_resp.json.return_value = {"status": "OVER_QUERY_LIMIT", "rows": []}

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 900},
                            "distance": {"value": 12000},
                        }
                    ]
                }
            ],
        }

        call_count = {"n": 0}

        def get_side_effect(url, params=None, timeout=15):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return fail_resp
            return ok_resp

        scout = MobilityScout()
        scout.api_key = "test_key"
        with (
            patch.object(scout, "_session") as mock_session,
            patch("scrapers.mobility_scout.time.sleep"),
        ):
            mock_session.get.side_effect = get_side_effect
            results = scout.measure_travel_times("Yelahanka")
            assert len(results) > 0
            assert results[0]["travel_time_min"] == 15.0

    def test_unknown_api_status_not_retried(self):
        from scrapers.mobility_scout import MobilityScout

        scout = MobilityScout()
        scout.api_key = "test_key"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "INVALID_REQUEST", "rows": []}

        with patch(
            "scrapers.mobility_scout.requests.Session.get", return_value=mock_resp
        ):
            results = scout.measure_travel_times("Yelahanka")
            assert results == []

    def test_element_status_not_ok_returns_none(self):
        from scrapers.mobility_scout import MobilityScout

        scout = MobilityScout()
        scout.api_key = "test_key"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "OK",
            "rows": [{"elements": [{"status": "NOT_FOUND"}]}],
        }

        with patch(
            "scrapers.mobility_scout.requests.Session.get", return_value=mock_resp
        ):
            results = scout.measure_travel_times("Yelahanka")
            assert results == []


class TestComputeAccessibility:
    def _clear_cache(self):
        from scrapers.mobility_scout import _accessibility_cache

        _accessibility_cache.clear()

    def test_formula_correct_returns_expected_range(self):
        self._clear_cache()
        from scrapers.mobility_scout import compute_market_accessibility

        mock_rows = [
            ("Manyata Tech Park", 25.0),
            ("BIAL", 30.0),
            ("Hebbal ORR", 28.0),
            ("Whitefield ITPB", 55.0),
            ("Nagawara", 22.0),
        ]

        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchall.return_value = mock_rows
            score = compute_market_accessibility("Yelahanka")
            assert 0.4 <= score <= 0.55, f"Expected score in [0.4, 0.55], got {score}"

    def test_returns_zero_on_empty_db(self):
        self._clear_cache()
        from scrapers.mobility_scout import compute_market_accessibility

        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchall.return_value = []
            score = compute_market_accessibility("Yelahanka")
            assert score == 0.0

    def test_case_sensitive_market_match(self):
        self._clear_cache()
        from scrapers.mobility_scout import compute_market_accessibility

        mock_rows = [
            ("Manyata Tech Park", 25.0),
            ("BIAL", 30.0),
            ("Hebbal ORR", 28.0),
            ("Whitefield ITPB", 55.0),
            ("Nagawara", 22.0),
        ]

        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchall.return_value = mock_rows
            score = compute_market_accessibility("Yelahanka")
            assert mock_conn.execute.called, "DB should be queried (not cached)"
            executed_sql = (
                str(mock_conn.execute.call_args[0][0])
                if mock_conn.execute.call_args
                else ""
            )
            assert "market =" in executed_sql, "Should use exact match, not ILIKE"
            assert score > 0.0

    def test_accepts_existing_connection_parameter(self):
        self._clear_cache()
        from scrapers.mobility_scout import compute_market_accessibility

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Manyata Tech Park", 25.0),
            ("BIAL", 30.0),
            ("Hebbal ORR", 28.0),
            ("Whitefield ITPB", 55.0),
            ("Nagawara", 22.0),
        ]
        score = compute_market_accessibility("Yelahanka", conn=mock_conn)
        assert 0.4 <= score <= 0.55


class TestComputeRowComponent:
    def test_weighted_component_calculation(self):
        from scrapers.mobility_scout import _compute_row_component

        score = _compute_row_component("Manyata Tech Park", 25.0)
        expected = 0.30 * (1.0 - min(25.0 / 60.0, 1.0))
        assert score == round(expected, 4)

    def test_zero_for_unknown_destination(self):
        from scrapers.mobility_scout import _compute_row_component

        score = _compute_row_component("Unknown Place", 30.0)
        assert score == 0.0

    def test_travel_time_exceeds_hour_capped(self):
        from scrapers.mobility_scout import _compute_row_component

        score = _compute_row_component("Manyata Tech Park", 90.0)
        assert score == 0.0


class TestPersistResults:
    def test_persist_upserts_with_on_conflict(self):
        from scrapers.mobility_scout import _persist_results

        results = [
            {
                "destination_name": "Manyata Tech Park",
                "travel_time_min": 25.0,
                "distance_km": 14.0,
                "mode": "driving",
                "traffic_condition": "typical",
                "measured_at": "2026-06-08T00:00:00+00:00",
            }
        ]

        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            _persist_results("Yelahanka", results)
            assert mock_conn.execute.called
            sql_text = str(mock_conn.execute.call_args[0][0])
            assert "ON CONFLICT" in sql_text, "Should use upsert pattern"
            assert "AT TIME ZONE" in sql_text, "Should use timezone-aware date cast"
