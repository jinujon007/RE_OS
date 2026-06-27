"""
RE_OS — Telegram Notifier (GATE-142)
Sends text messages to a Telegram chat via Bot API.

Reads TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID from env.
Silent no-op (returns False) if either key is absent — same pattern as Discord.
Telegram Bot API rate limit: 30 msg/sec — simple exponential backoff on 429.
"""

import json
import os
import time
import urllib.error
import urllib.request

from loguru import logger

__all__ = ["send_message"]

_TEXT_MAX = 4096
_RETRY_429_WAIT = [1, 3, 5]  # seconds to wait on consecutive 429s


def send_message(text: str, parse_mode: str = "Markdown") -> bool:
    """Send a text message to the configured Telegram chat.

    Args:
        text: Message content (truncated to 4096 chars).
        parse_mode: Telegram parse mode — "Markdown" (default) or "HTML".

    Returns:
        True if the message was accepted by Telegram API, False otherwise
        (missing config, network error, rate limit, etc.).
    """
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        logger.info("[Telegram] Skipped — TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False

    truncated = text[:_TEXT_MAX]
    if len(text) > _TEXT_MAX:
        logger.warning("[Telegram] Truncated message from {} to {} chars", len(text), _TEXT_MAX)

    payload = json.dumps({
        "chat_id": chat_id,
        "text": truncated,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }).encode("utf-8")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    last_error: str | None = None

    for attempt, wait in enumerate(_RETRY_429_WAIT):
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "RE_OS/1.0 Telegram Notifier",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return True
                logger.warning("[Telegram] Unexpected status {}", resp.status)
                return False
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            if exc.code == 429:
                logger.warning("[Telegram] Rate limited (429) attempt {}/{} — waiting {}s",
                               attempt + 1, len(_RETRY_429_WAIT), wait)
                time.sleep(wait)
                last_error = f"429 {body}"
            else:
                logger.warning("[Telegram] HTTP {}: {}", exc.code, body)
                return False
        except Exception as exc:
            logger.warning("[Telegram] Send failed: {}", exc)
            return False

    logger.warning("[Telegram] Exhausted {} retries on 429: {}", len(_RETRY_429_WAIT), last_error)
    return False
