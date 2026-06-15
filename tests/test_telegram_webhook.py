"""Tests for Telegram webhook endpoint — T-966."""

from unittest.mock import MagicMock, patch

import config.settings as _cfg


def _make_update(text="Yelahanka 2 acres 4500 PSF JD", chat_id=12345):
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "text": text,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "first_name": "Test"},
        },
    }


def _client():
    from fastapi.testclient import TestClient
    from dashboard.app_fastapi import app

    return TestClient(app, raise_server_exceptions=False)


def test_telegram_webhook_rejects_invalid_secret():
    """Wrong secret → 403."""
    client = _client()
    with patch.object(_cfg, "TELEGRAM_WEBHOOK_SECRET", "test_secret_123"):
        resp = client.post(
            "/api/telegram/webhook",
            json=_make_update(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong_secret"},
        )
    assert resp.status_code == 403
    assert resp.json()["error"] == "unauthorized"


def test_telegram_webhook_validates_secret():
    """Valid secret → 200."""
    client = _client()
    with (
        patch.object(_cfg, "TELEGRAM_WEBHOOK_SECRET", "test_secret_123"),
        patch("dashboard.app_fastapi._send_telegram_message"),
    ):
        resp = client.post(
            "/api/telegram/webhook",
            json=_make_update(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret_123"},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_telegram_webhook_parses_message():
    """Valid update → parse_message called, returns 200."""
    client = _client()
    low_conf = MagicMock(
        market="Yelahanka",
        confidence=0.3,
        area_acres=0.0,
        ask_psf=0.0,
        deal_type="compare",
    )
    with (
        patch.object(_cfg, "TELEGRAM_WEBHOOK_SECRET", "test_secret_123"),
        patch(
            "interface.telegram_bot.parse_message", return_value=low_conf
        ) as mock_parse,
        patch("dashboard.app_fastapi._send_telegram_message"),
    ):
        resp = client.post(
            "/api/telegram/webhook",
            json=_make_update("hello"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret_123"},
        )
    assert resp.status_code == 200
    mock_parse.assert_called_once_with("hello")


def test_telegram_webhook_dispatches_on_high_confidence():
    """High-confidence parse → dispatch_evaluation called + reply sent."""
    client = _client()
    high_conf = MagicMock(
        market="Yelahanka",
        confidence=0.85,
        area_acres=2.0,
        ask_psf=4500.0,
        deal_type="jd",
    )
    with (
        patch.object(_cfg, "TELEGRAM_WEBHOOK_SECRET", "test_secret_123"),
        patch("interface.telegram_bot.parse_message", return_value=high_conf),
        patch(
            "interface.telegram_bot.dispatch_evaluation",
            return_value={"status": "running", "job_id": "job-abc"},
        ) as mock_dispatch,
        patch("dashboard.app_fastapi._send_telegram_message") as mock_send,
    ):
        resp = client.post(
            "/api/telegram/webhook",
            json=_make_update("Yelahanka 2 acres 4500 PSF JD"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret_123"},
        )
    assert resp.status_code == 200
    mock_dispatch.assert_called_once()
    mock_send.assert_called_once()
    reply_text = mock_send.call_args[0][1]
    assert "Yelahanka" in reply_text
