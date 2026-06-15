"""Unit tests for weekly competitive digest scheduler job (T-976)."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestCompetitiveScheduler:
    def test_weekly_digest_job_registered(self):
        from config.scheduler import weekly_competitive_digest

        assert callable(weekly_competitive_digest)

    def test_weekly_digest_job_sends_discord(self):
        from config.scheduler import weekly_competitive_digest

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
            with patch("utils.discord_notifier.send_competitive_digest") as mock_send:
                weekly_competitive_digest()
                mock_send.assert_called_once()

    def test_weekly_digest_logs_on_failure(self):
        from config.scheduler import weekly_competitive_digest

        with patch(
            "intelligence.competitive_intel.CompetitiveIntelEngine"
        ) as MockEngine:
            MockEngine.side_effect = Exception("Engine failure")
            with patch("config.scheduler.logger") as mock_log:
                weekly_competitive_digest()
                mock_log.warning.assert_called()
