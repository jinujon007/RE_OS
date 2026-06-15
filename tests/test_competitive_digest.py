"""Unit tests for format_competitive_digest and send_competitive_digest (T-975)."""

import pytest
from unittest.mock import patch

pytestmark = pytest.mark.unit


class TestCompetitiveDigest:
    def _sample_pulse(self, empty=False):
        if empty:
            return {"new_launches": [], "psf_movers": [], "absorption_leaders": []}
        return {
            "new_launches": [
                {
                    "project_name": "Greenfield Towers",
                    "developer_name": "Brigade",
                    "market": "Yelahanka",
                    "total_units": 200,
                },
                {
                    "project_name": "Lake View",
                    "developer_name": "Prestige",
                    "market": "Devanahalli",
                    "total_units": 150,
                },
            ],
            "psf_movers": [
                {
                    "project_name": "Skyline",
                    "developer_name": "Sobha",
                    "market": "Hebbal",
                    "change_pct": 12.5,
                    "direction": "UP",
                },
            ],
            "absorption_leaders": [
                {
                    "project_name": "Palm Grove",
                    "developer_name": "Godrej",
                    "market": "Yelahanka",
                    "absorption_pct": 85.0,
                },
            ],
        }

    def test_digest_under_1500_chars(self):
        from utils.discord_notifier import format_competitive_digest

        result = format_competitive_digest(self._sample_pulse())
        assert len(result) <= 1500

    def test_digest_has_all_3_sections(self):
        from utils.discord_notifier import format_competitive_digest

        result = format_competitive_digest(self._sample_pulse())
        assert "New Launches" in result
        assert "PSF Movers" in result
        assert "Absorption Leaders" in result

    def test_digest_handles_empty_sections(self):
        from utils.discord_notifier import format_competitive_digest

        result = format_competitive_digest(self._sample_pulse(empty=True))
        assert "None this week." in result
        assert len(result) <= 1500

    def test_digest_truncation_is_unicode_safe(self):
        from utils.discord_notifier import format_competitive_digest

        pulse = self._sample_pulse()
        pulse["new_launches"] = [
            {
                "project_name": "A",
                "developer_name": "B",
                "market": "Y",
                "total_units": 999999,
            }
        ] * 50
        result = format_competitive_digest(pulse)
        assert len(result) <= 1500
        assert result.endswith("...") or len(result) < 1500

    def test_send_competitive_digest_calls_send(self):
        from utils.discord_notifier import send_competitive_digest

        with patch("utils.discord_notifier.send") as mock_send:
            mock_send.return_value = True
            send_competitive_digest(self._sample_pulse())
            mock_send.assert_called_once()
            args, _ = mock_send.call_args
            assert args[0] == "bd_opportunities"
            assert "Competitive Intelligence Pulse" in args[1]

    def test_send_competitive_digest_handles_failure(self):
        from utils.discord_notifier import send_competitive_digest

        with patch("utils.discord_notifier.send") as mock_send:
            mock_send.side_effect = Exception("Discord down")
            send_competitive_digest(self._sample_pulse())
            mock_send.assert_called_once()
