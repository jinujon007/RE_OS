"""GATE-142 declaration — Telegram Intelligence Delivery.

13 assertions:
1.  send_message importable; returns False when token absent
2.  send_weekly_telegram_digest importable from config.scheduler
3.  Telegram wiring in board_room.py (grep for telegram_notifier import)
4.  Telegram wiring in assembly_detector.py (grep for telegram_notifier import)
5.  TELEGRAM_BOT_TOKEN= and TELEGRAM_CHAT_ID= present in .env.example
6.  send_message with empty token returns False without raising
7.  send_message truncates at 4096 chars and returns True (mocked API)
8.  send_message retries on 429 then returns False after exhaustion
9.  send_message recovers on 429 retry and returns True
10. _send_split sends multiple messages when text exceeds _TG_MSG_MAX
11. _send_split single message when text under limit
12. send_message returns False on non-429 HTTP error
13. Board Room decision_flag in GO/NO-GO includes full session_id
"""

import json
import os
import pathlib
import urllib.error
from unittest.mock import call, patch
import pytest

pytestmark = pytest.mark.unit


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=False)
def test_a1_send_message_returns_false_without_token():
    from utils.telegram_notifier import send_message
    assert send_message("test") is False


def test_a2_weekly_digest_importable():
    from config.scheduler.maintenance_jobs import send_weekly_telegram_digest
    assert callable(send_weekly_telegram_digest)


def test_a3_board_room_telegram_wiring():
    src = pathlib.Path("crews/board_room.py").read_text(encoding="utf-8")
    assert "telegram_notifier" in src


def test_a4_assembly_detector_telegram_wiring():
    src = pathlib.Path("utils/assembly_detector.py").read_text(encoding="utf-8")
    assert "telegram_notifier" in src


def test_a5_env_example_has_telegram_vars():
    content = pathlib.Path(".env.example").read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=" in content
    assert "TELEGRAM_CHAT_ID=" in content


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}, clear=False)
def test_a6_send_message_empty_token_no_raise():
    from utils.telegram_notifier import send_message
    assert send_message("test", parse_mode="Markdown") is False


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "fake"}, clear=False)
def test_a7_send_message_truncates_at_4096():
    from utils.telegram_notifier import send_message
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value.status = 200
        long_text = "x" * 5000
        result = send_message(long_text)
        assert result is True
        body = json.loads(mock_open.call_args[0][0].data)
        assert len(body["text"]) == 4096


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "fake"}, clear=False)
def test_a8_send_message_retries_429_then_fails():
    from utils.telegram_notifier import send_message
    with patch("urllib.request.urlopen") as mock_open:
        err = urllib.error.HTTPError("url", 429, "Too Many", {}, None)
        mock_open.side_effect = [err, err, err]
        result = send_message("test")
        assert result is False
        assert mock_open.call_count == 3


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "fake"}, clear=False)
def test_a9_send_message_recovers_after_429():
    from unittest.mock import MagicMock
    from utils.telegram_notifier import send_message
    with patch("urllib.request.urlopen") as mock_open:
        err = urllib.error.HTTPError("url", 429, "Too Many", {}, None)
        ok_response = MagicMock()
        ok_response.__enter__.return_value.status = 200
        mock_open.side_effect = [err, err, ok_response]
        result = send_message("test")
        assert result is True
        assert mock_open.call_count == 3


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "fake"}, clear=False)
def test_a10_send_message_returns_false_on_non_429_http_error():
    from utils.telegram_notifier import send_message
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.side_effect = urllib.error.HTTPError("url", 400, "Bad Request", {}, None)
        result = send_message("test")
        assert result is False
        assert mock_open.call_count == 1


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "fake"}, clear=False)
def test_a11_send_split_splits_long_text():
    from config.scheduler.maintenance_jobs import _send_split
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value.status = 200
        long_line = "a\n" * 5000
        _send_split(long_line)
        assert mock_open.call_count > 1


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "fake"}, clear=False)
def test_a12_send_split_single_message_short_text():
    from config.scheduler.maintenance_jobs import _send_split
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value.__enter__.return_value.status = 200
        _send_split("short")
        assert mock_open.call_count == 1


def test_a13_board_room_uses_full_session_id():
    src = pathlib.Path("crews/board_room.py").read_text(encoding="utf-8")
    tg_idx = src.find("telegram_notifier import send_message")
    tg_block = src[tg_idx:tg_idx + 800] if tg_idx >= 0 else ""
    assert tg_block, "telegram_notifier not found in board_room.py"
    assert "session_id[:8]" not in tg_block, "Board Room still sends truncated session_id"
    assert "session_id}" in tg_block, "Telegram notification does not include full session_id"
