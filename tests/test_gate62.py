"""GATE-62: Competitive Intelligence Pulse — all 6 criteria."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestGate62CompetitiveIntel:
    def test_new_launches_returns_list_not_exception(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine

        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchall.return_value = []
            result = engine.new_launches("Yelahanka", days=365)
        assert isinstance(result, list)

    def test_absorption_leaders_have_absorption_pct_field(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine

        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchall.return_value = [
                (
                    "Proj A",
                    "Builder X",
                    "A",
                    "Devanahalli",
                    75.0,
                    100,
                    25,
                    "2026-12-01",
                ),
            ]
            result = engine.absorption_leaders("Devanahalli", top_n=3)
        assert isinstance(result, list)
        assert len(result) <= 3
        assert "absorption_pct" in result[0]
        assert result[0]["absorption_pct"] == 75.0

    def test_competitive_pulse_endpoint_returns_200_and_keys(self):
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app, _pulse_cache, _pulse_cache_lock

        with _pulse_cache_lock:
            _pulse_cache.clear()
        client = TestClient(app)
        with patch(
            "intelligence.competitive_intel.CompetitiveIntelEngine"
        ) as MockEngine:
            mock_instance = MagicMock()
            mock_instance.pulse.return_value = {
                "new_launches": [],
                "psf_movers": [],
                "absorption_leaders": [],
                "generated_at": "2026-06-06T12:00:00",
                "market_filter": None,
                "days_window": 7,
            }
            MockEngine.return_value = mock_instance
            resp = client.get("/api/competitive/pulse")
        assert resp.status_code == 200
        data = resp.json()
        assert "new_launches" in data
        assert "psf_movers" in data
        assert "absorption_leaders" in data

    def test_competitive_digest_under_1500_chars(self):
        from utils.discord_notifier import format_competitive_digest

        pulse = {
            "new_launches": [
                {
                    "project_name": "A",
                    "developer_name": "B",
                    "market": "Y",
                    "total_units": 100,
                }
            ],
            "psf_movers": [
                {
                    "project_name": "C",
                    "developer_name": "D",
                    "market": "H",
                    "change_pct": 10.0,
                    "direction": "UP",
                }
            ],
            "absorption_leaders": [
                {
                    "project_name": "E",
                    "developer_name": "F",
                    "market": "D",
                    "absorption_pct": 80.0,
                }
            ],
        }
        result = format_competitive_digest(pulse)
        assert len(result) <= 1500

    def test_scheduler_has_competitive_pulse_job(self):
        from config.scheduler import weekly_competitive_digest

        assert callable(weekly_competitive_digest)

    def test_board_room_bd_head_gets_competitive_context(self):
        from crews.board_room_v2 import _get_competitive_context

        with patch(
            "intelligence.competitive_intel.CompetitiveIntelEngine"
        ) as MockEngine:
            mock_instance = MagicMock()
            mock_instance.absorption_leaders.return_value = []
            mock_instance.new_launches.return_value = []
            MockEngine.return_value = mock_instance
            context = _get_competitive_context("Yelahanka")
        assert isinstance(context, str)
        assert "Top absorbers" in context or context == ""
