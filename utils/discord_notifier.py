"""
RE_OS — Discord Notifier (Phase 7 — Alerts)
Sends structured embed messages to Discord via webhooks.
All webhook URLs are optional — missing URL = skipped (not an error).

Discord channel map (set webhook URLs in .env):
  rera_yelahanka   → DISCORD_WEBHOOK_RERA_YELAHANKA
  rera_devanahalli → DISCORD_WEBHOOK_RERA_DEVANAHALLI
  rera_hebbal      → DISCORD_WEBHOOK_RERA_HEBBAL
  competitor       → DISCORD_WEBHOOK_COMPETITOR
  price            → DISCORD_WEBHOOK_PRICE
  intel            → DISCORD_WEBHOOK_INTEL
  system           → DISCORD_WEBHOOK_SYSTEM
"""
import json
import os
from datetime import datetime, timezone

from loguru import logger

COLOR_GREEN  = 3066993
COLOR_RED    = 15158332
COLOR_AMBER  = 16750848
COLOR_BLUE   = 3447003
COLOR_PURPLE = 10181046

_CHANNEL_ENV_MAP = {
    "rera_yelahanka":   "DISCORD_WEBHOOK_RERA_YELAHANKA",
    "rera_devanahalli": "DISCORD_WEBHOOK_RERA_DEVANAHALLI",
    "rera_hebbal":      "DISCORD_WEBHOOK_RERA_HEBBAL",
    "competitor":       "DISCORD_WEBHOOK_COMPETITOR",
    "price":            "DISCORD_WEBHOOK_PRICE",
    "intel":            "DISCORD_WEBHOOK_INTEL",
    "system":           "DISCORD_WEBHOOK_SYSTEM",
}


def _get_webhook_url(channel: str) -> str | None:
    env_key = _CHANNEL_ENV_MAP.get(channel)
    if not env_key:
        return None
    raw = (os.environ.get(env_key) or "").strip()
    return raw or None


def _log_alert(channel: str, title: str, message: str, color: int, status: str) -> None:
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        with get_engine().begin() as conn:
            conn.execute(
                text("""
                INSERT INTO alerts (channel, title, message, color, status)
                VALUES (:channel, :title, :message, :color, :status)
                """),
                {"channel": channel, "title": title,
                 "message": message[:2000] if message else None,
                 "color": color, "status": status},
            )
    except Exception as exc:
        logger.warning(f"[Discord] Failed to log alert to DB: {exc}")


def send(channel: str, title: str, message: str = "", color: int = COLOR_BLUE) -> bool:
    import urllib.request
    import urllib.error

    url = _get_webhook_url(channel)
    if not url:
        logger.debug(f"[Discord] Channel '{channel}' not configured — skipping alert: {title}")
        _log_alert(channel, title, message, color, "skipped")
        return False

    payload = json.dumps({
        "embeds": [{
            "title": title[:256],
            "description": message[:4096] if message else "",
            "color": color,
            "footer": {"text": "RE_OS · LLS Intelligence"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status in (200, 204):
                logger.info(f"[Discord] Sent to #{channel}: {title}")
                _log_alert(channel, title, message, color, "sent")
                return True
            logger.warning(f"[Discord] Unexpected status {resp.status} for #{channel}")
            _log_alert(channel, title, message, color, "failed")
            return False
    except Exception as exc:
        logger.warning(f"[Discord] Failed to send to #{channel}: {exc}")
        _log_alert(channel, title, message, color, "failed")
        return False


def send_rera_alert(market: str, new_count: int, developers: list[str]) -> bool:
    channel = f"rera_{market.lower()}"
    title   = f"New RERA project{'s' if new_count != 1 else ''} — {market}"
    devs    = ", ".join(developers[:5]) + ("…" if len(developers) > 5 else "")
    message = f"**{new_count}** new RERA registration{'s' if new_count != 1 else ''} detected in **{market}**.\nDevelopers: {devs}"
    return send(channel, title, message, COLOR_GREEN)


def send_intel_alert(market: str, run_id: str, synopsis: str, avg_psf: int | None) -> bool:
    psf_str = f"₹{avg_psf:,}/sqft" if avg_psf else "PSF unavailable"
    title   = f"Intel report ready — {market}"
    message = f"**Run:** `{run_id}`\n**Avg PSF:** {psf_str}\n\n{synopsis[:400]}"
    return send("intel", title, message, COLOR_BLUE)


def send_competitor_alert(developer: str, project: str, market: str) -> bool:
    title   = f"New competitor project — {market}"
    message = f"**{developer}** has launched **{project}** in {market}."
    return send("competitor", title, message, COLOR_PURPLE)


def send_price_alert(market: str, old_psf: float, new_psf: float) -> bool:
    delta = ((new_psf - old_psf) / max(old_psf, 1)) * 100
    if delta > 0:
        direction = "▲"
    elif delta < 0:
        direction = "▼"
    else:
        direction = "—"
    title   = f"Price movement {direction} {abs(delta):.1f}% — {market}"
    message = (
        f"**{market}** avg listing PSF moved from ₹{old_psf:,.0f} to ₹{new_psf:,.0f} "
        f"({direction}{abs(delta):.1f}%)."
    )
    color = COLOR_RED if delta < 0 else COLOR_GREEN
    return send("price", title, message, color)


def send_system_alert(job_name: str, error: str) -> bool:
    title   = f"Scheduler error — {job_name}"
    message = f"**Job:** `{job_name}`\n**Error:** {error[:500]}"
    return send("system", title, message, COLOR_RED)
