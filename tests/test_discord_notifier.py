import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit

from utils.discord_notifier import (
    send, send_rera_alert, send_intel_alert,
    send_competitor_alert, send_price_alert, send_system_alert,
    COLOR_GREEN, COLOR_RED, COLOR_BLUE,
)


class TestSend:
    def test_skip_when_no_webhook(self):
        with patch.dict("os.environ", {}, clear=True):
            with patch("utils.discord_notifier._log_alert") as mock_log:
                result = send("rera_yelahanka", "Test", "body")
                assert result is False
                mock_log.assert_called_once_with("rera_yelahanka", "Test", "body", COLOR_BLUE, "skipped")

    def test_returns_true_on_204(self):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 204
        with patch.dict("os.environ", {"DISCORD_WEBHOOK_RERA_YELAHANKA": "https://discord.com/fake"}):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                with patch("utils.discord_notifier._log_alert"):
                    result = send("rera_yelahanka", "Test", "body")
                    assert result is True

    def test_returns_false_on_exception(self):
        with patch.dict("os.environ", {"DISCORD_WEBHOOK_RERA_YELAHANKA": "https://discord.com/fake"}):
            with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
                with patch("utils.discord_notifier._log_alert"):
                    result = send("rera_yelahanka", "Test", "body")
                    assert result is False

    def test_unknown_channel_returns_false(self):
        with patch("utils.discord_notifier._log_alert") as mock_log:
            result = send("nonexistent_channel", "Title", "msg")
            assert result is False
            mock_log.assert_not_called()


class TestFormatters:
    def test_rera_alert_structure(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_rera_alert("Yelahanka", 5, ["Brigade", "Prestige"])
            call = mock_send.call_args
            assert "rera_yelahanka" == call[0][0]
            assert "Yelahanka" in call[0][1]

    def test_rera_alert_singular_count(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_rera_alert("Hebbal", 1, ["Prestige"])
            call = mock_send.call_args
            assert "project" in call[0][1]
            assert "projects" not in call[0][1]

    def test_intel_alert_contains_run_id(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_intel_alert("Yelahanka", "20260530_071726", "Market cooling", 10791)
            call = mock_send.call_args
            assert "20260530_071726" in call[0][2]

    def test_intel_alert_none_psf(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_intel_alert("Yelahanka", "run_123", "Synopsis", None)
            call = mock_send.call_args
            assert "PSF unavailable" in call[0][2]

    def test_price_alert_color_red_on_decline(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_price_alert("Yelahanka", 10000, 9000)
            call = mock_send.call_args
            assert call[0][3] == COLOR_RED

    def test_price_alert_color_green_on_rise(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_price_alert("Yelahanka", 9000, 10000)
            call = mock_send.call_args
            assert call[0][3] == COLOR_GREEN

    def test_price_alert_zero_delta(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_price_alert("Yelahanka", 10000, 10000)
            call = mock_send.call_args
            assert "0.0%" in call[0][1]
            assert "—" in call[0][1]

    def test_system_alert_structure(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_system_alert("rera_yelahanka", "Connection refused")
            call = mock_send.call_args
            assert "system" == call[0][0]
            assert "Connection refused" in call[0][2]

    def test_competitor_alert_structure(self):
        with patch("utils.discord_notifier.send", return_value=True) as mock_send:
            send_competitor_alert("Brigade", "Brigade Insignia", "Yelahanka")
            call = mock_send.call_args
            assert "competitor" == call[0][0]
            assert "Brigade" in call[0][2]
