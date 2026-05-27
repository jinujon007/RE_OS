"""Utility functions for sending alerts via Telegram bot.

This module defines :func:`send_alert` which sends a message to a preconfigured Telegram bot.

Environment variables required:
- ``TELEGRAM_BOT_TOKEN`` – Bot authentication token.
- ``TELEGRAM_CHAT_ID``   – Chat / channel ID to send messages to.

If either variable is missing, :func:`send_alert` will return ``False`` to indicate the alert was not sent.
"""

import os
import json
import urllib.request
from typing import Any

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def _post(url: str, data: bytes) -> Any:
    """Post raw JSON data to the specified URL.

    Returns the decoded JSON response or raises an exception.
    """
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_alert(message: str, level: str) -> bool:
    """Send a Telegram message.

    Parameters
    ----------
    message:
        The message body.
    level:
        Severity level, e.g., ``INFO``, ``WARN``, ``ERROR``.

    Returns
    -------
    bool
        ``True`` if the message was delivered successfully, ``False`` otherwise.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"[{level}] {message}",
        "parse_mode": "MarkdownV2",
    }
    try:
        _post(url, json.dumps(payload).encode("utf-8"))
        return True
    except Exception:
        return False
