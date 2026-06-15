"""GATE-74 declaration — Mobility/Accessibility Scout.

6 assertions verified:
  1. MobilityScout().measure_travel_times(Yelahanka) returns list without raising
  2. run_mobility_scout() handles 3 markets without error (simulated)
  3. compute_market_accessibility(Yelahanka) returns float in [0.4, 0.55]
  4. InfrastructureProximity has accessibility_score field
  5. Mock infra.accessibility_score=1.0 -> _exclusivity_score() bonus >= 0.14
  6. GET /api/market/accessibility?market=Yelahanka returns 200 + JSON with destinations key
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestGate74:
    def test_mobility_scout_returns_list(self):
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
                            "distance": {"value": 14000},
                        }
                    ]
                }
            ],
        }

        with patch(
            "scrapers.mobility_scout.requests.Session.get", return_value=mock_resp
        ):
            results = scout.measure_travel_times("Yelahanka")
            assert isinstance(results, list)
            assert len(results) == 5, "Should measure all 5 destinations"

    def test_run_mobility_scout_handles_all_markets(self, monkeypatch):
        from scrapers.mobility_scout import run_mobility_scout

        monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test_key")
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "status": "OK",
            "rows": [
                {
                    "elements": [
                        {
                            "status": "OK",
                            "duration": {"value": 1500},
                            "distance": {"value": 14000},
                        }
                    ]
                }
            ],
        }

        mock_session = MagicMock()
        mock_session.get.return_value = ok_resp

        with (
            patch("utils.db.get_engine") as mock_eng,
            patch("scrapers.mobility_scout.requests.Session") as mock_session_cls,
            patch("scrapers.mobility_scout.time.sleep"),
            patch("scrapers.mobility_scout.scraper_runs_total"),
        ):
            mock_session_cls.return_value = mock_session
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            run_mobility_scout()
            assert mock_conn.execute.call_count >= 3, (
                "Should insert for at least 3 markets"
            )

    def test_compute_market_accessibility_yelahanka_in_range(self):
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
            assert 0.4 <= score <= 0.55

    def test_infrastructure_proximity_has_accessibility_score(self):
        from intelligence.land_intel import InfrastructureProximity

        infra = InfrastructureProximity()
        assert hasattr(infra, "accessibility_score")
        assert infra.accessibility_score == 0.0

        infra2 = InfrastructureProximity(accessibility_score=0.78)
        assert infra2.accessibility_score == 0.78

    def test_exclusivity_bonus_continuous_from_accessibility(self):
        from intelligence.opportunity_engine import _exclusivity_score

        pkg = MagicMock()
        pkg.market_pulse = None
        land = MagicMock()
        infra = MagicMock()
        infra.accessibility_score = 1.0
        land.infrastructure = infra
        pkg.land_picture = land

        score = _exclusivity_score(pkg, 5, encumbrance_clear=False, is_aggregated=True)
        expected_base = 0.5
        expected_acc_bonus = round(1.0 * 0.15, 4)
        expected_agg_bonus = 0.05
        expected = min(expected_base + expected_acc_bonus + expected_agg_bonus, 1.0)
        assert score >= 0.69, f"Expected score >= 0.69 with acc=1.0, got {score}"

    def test_exclusivity_backward_compat_no_accessibility_field(self):
        from intelligence.opportunity_engine import _exclusivity_score

        pkg = MagicMock()
        pkg.market_pulse = None
        land = MagicMock()
        infra = MagicMock()
        del infra.accessibility_score
        land.infrastructure = infra
        pkg.land_picture = land

        score = _exclusivity_score(pkg, 3, encumbrance_clear=True, is_aggregated=False)
        expected_base = 0.7
        expected_bonus = 0.10
        expected = min(expected_base + expected_bonus, 1.0)
        assert score == expected, (
            f"Expected {expected}, got {score} — backward compat failed"
        )

    def test_accessibility_endpoint_returns_correct_structure(self):
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app

        client = TestClient(app)
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_rows = [
                ("Manyata Tech Park", 25.0, 14.0, "2026-06-08T00:00:00+00:00", 0.1750),
                ("BIAL", 30.0, 20.0, "2026-06-08T00:00:00+00:00", 0.1250),
                ("Hebbal ORR", 28.0, 16.0, "2026-06-08T00:00:00+00:00", 0.1067),
                ("Whitefield ITPB", 55.0, 34.0, "2026-06-08T00:00:00+00:00", 0.0125),
                ("Nagawara", 22.0, 12.0, "2026-06-08T00:00:00+00:00", 0.0633),
            ]
            mock_conn.execute.return_value.fetchall.return_value = mock_rows
            resp = client.get("/api/market/accessibility?market=Yelahanka")
            assert resp.status_code == 200
            data = resp.json()
            assert "destinations" in data
            assert isinstance(data["destinations"], list)
            assert len(data["destinations"]) == 5
            assert "accessibility_score" in data
            assert isinstance(data["accessibility_score"], float)
            assert data["last_updated"] is not None

    def test_accessibility_endpoint_returns_404_when_no_data(self):
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app

        client = TestClient(app)
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchall.return_value = []
            resp = client.get("/api/market/accessibility?market=Yelahanka")
            assert resp.status_code == 404
            assert "error" in resp.json()
