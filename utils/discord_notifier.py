"""
RE_OS — Discord Notifier (Phase 7 — Alerts)
Sends structured embed messages to Discord via webhooks.

All webhook URLs are optional — missing URL = skipped (not an error).
Exception: DISCORD_WEBHOOK_URL (general purpose) is REQUIRED in production.
When unset, send() raises ConfigurationError so tests and health checks catch misconfiguration early.

Discord channel map (set webhook URLs in .env):
  rera_yelahanka   → DISCORD_WEBHOOK_RERA_YELAHANKA
  rera_devanahalli → DISCORD_WEBHOOK_RERA_DEVANAHALLI
  rera_hebbal      → DISCORD_WEBHOOK_RERA_HEBBAL
  competitor       → DISCORD_WEBHOOK_COMPETITOR
  price            → DISCORD_WEBHOOK_PRICE
  intel            → DISCORD_WEBHOOK_INTEL
  system           → DISCORD_WEBHOOK_SYSTEM
  health           → DISCORD_WEBHOOK_SYSTEM  (alias)
  bd_opportunities → DISCORD_WEBHOOK_BD_OPPORTUNITIES
"""
import json
import os
from datetime import datetime, timezone

from loguru import logger


class ConfigurationError(Exception):
    """Raised when a required Discord webhook URL is not configured."""
    pass

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
    "health":           "DISCORD_WEBHOOK_SYSTEM",  # alias — maps to same webhook as system
    "bd_opportunities": "DISCORD_WEBHOOK_BD_OPPORTUNITIES",
    "gcc_intel":        "DISCORD_WEBHOOK_GCC_INTEL",
}

_VALID_CHANNELS = frozenset(_CHANNEL_ENV_MAP)


def _get_webhook_url(channel: str) -> str | None:
    env_key = _CHANNEL_ENV_MAP.get(channel)
    if not env_key:
        return None
    raw = (os.environ.get(env_key) or "").strip()
    return raw or None


def _get_required_webhook_url(channel: str) -> str:
    url = _get_webhook_url(channel)
    if url:
        return url
    # Fallback to general DISCORD_WEBHOOK_URL
    general = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
    if general:
        return general
    raise ConfigurationError(
        f"No Discord webhook configured for channel '{channel}'. "
        f"Set {_CHANNEL_ENV_MAP.get(channel, 'DISCORD_WEBHOOK_URL')} or DISCORD_WEBHOOK_URL in .env."
    )


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

    if channel not in _VALID_CHANNELS:
        logger.warning(f"[Discord] Unknown channel '{channel}' — valid: {sorted(_VALID_CHANNELS)}")
        return False

    # Health/system channels require a webhook — raise if missing so tests + alerts catch it
    require_webhook = channel in ("system", "health")
    if require_webhook:
        try:
            url = _get_required_webhook_url(channel)
        except ConfigurationError as exc:
            logger.error(f"[Discord] {exc}")
            _log_alert(channel, title, message, color, "skipped")
            raise
    else:
        url = _get_webhook_url(channel)
        if not url:
            logger.debug(f"[Discord] Channel '{channel}' not configured — skipping alert: {title}")
            _log_alert(channel, title, message, color, "skipped")
            return False

    # Discord embed description limit is 4096 chars; truncate at word boundary
    if message and len(message) > 4080:
        message = message[:4080].rsplit(" ", 1)[0] + "\n\n[Truncated — full details in agent_runs table]"

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
            headers={
                "Content-Type": "application/json",
                "User-Agent": "DiscordBot (RE_OS/1.0, LLS Intelligence)",
            },
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
    # 4-hour cooldown: one intel digest per market per half-day, suppresses dev-run spam
    try:
        from utils.db import get_engine
        from sqlalchemy import text
        with get_engine().connect() as _conn:
            _row = _conn.execute(
                text("""
                    SELECT id FROM alerts
                    WHERE channel = 'intel' AND title = :title
                      AND created_at > NOW() - INTERVAL '4 hours'
                    LIMIT 1
                """),
                {"title": title},
            ).fetchone()
        if _row:
            logger.debug("[Discord] Intel dedup: '{}' already sent within 4h — skip", title)
            return False
    except Exception as _exc:
        logger.debug("[Discord] Intel dedup check failed (allowing send): {}", _exc)
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


def send_opportunity_alert(survey_no: str, score: float, components: dict,
                           next_action: str, channel: str = "bd_opportunities") -> bool:
    """Send a structured opportunity alert to Discord bd-opportunities channel.
    
    Args:
        survey_no: Survey number (e.g. "45/2").
        score: Composite score in [0, 1].
        components: Dict with keys: irr, legal, timing, distress, exclusivity.
        next_action: Human-readable action string.
        channel: Discord channel key (default bd_opportunities).
    
    Returns:
        True if webhook POST succeeded, False otherwise.
    """
    title = f"URGENT — {survey_no}"
    message = (
        f"**{survey_no}**\n"
        f"Score: **{score:.4f}**\n"
        f"IRR: {components.get('irr', 0):.3f} | "
        f"Legal: {components.get('legal', 0):.3f} | "
        f"Timing: {components.get('timing', 0):.3f}\n"
        f"Action: {next_action}"
    )
    return send(channel, title, message, COLOR_GREEN if score >= 0.8 else COLOR_AMBER)


def format_deal_alert(stage: str, market: str, survey_no: str, ask_psf: float | None = None, area_acres: float | None = None) -> str:
    psf_str = f"₹{ask_psf:,.0f}/sqft" if ask_psf else "PSF TBD"
    area_str = f"{area_acres:.2f} acres" if area_acres else "Area TBD"
    return (
        f"**{stage.upper()}** — {market} | Survey {survey_no}\n"
        f"{area_str} | {psf_str}"
    )[:500]


def send_quality_alert(market: str, errors: list, warnings: list) -> bool:
    """Send a data quality alert to the health channel.
    
    Args:
        market: Market name (Yelahanka/Devanahalli/Hebbal).
        errors: List of error dicts, each with keys: table, column, expectation,
                bad_values (optional list), severity='ERROR'.
        warnings: List of warning dicts, same key structure, severity='WARN'.
    
    Returns:
        True if webhook POST succeeded, False otherwise.
    """
    title = f"Data Quality — {market}"
    parts = [f"**{len(errors)} error(s), {len(warnings)} warning(s)**"]
    if errors:
        parts.append("")
        parts.extend(f"❌ `{e['table']}.{e['column']}`: {e.get('expectation', '?')}" for e in errors[:5])
    if warnings:
        parts.append("")
        parts.extend(f"⚠️ `{w['table']}.{w['column']}`: {w.get('expectation', '?')}" for w in warnings[:5])
    return send("health", title, "\n".join(parts), COLOR_RED if errors else COLOR_AMBER)


def format_competitive_digest(pulse: dict) -> str:
    from datetime import datetime, timezone
    date_str = datetime.now(timezone.utc).strftime("%a %d %b %Y")
    lines = [f"**Competitive Intelligence Pulse — {date_str}**\n"]

    launches = pulse.get("new_launches", [])
    lines.append(f"🆕 **New Launches ({len(launches)})**")
    if launches:
        for la in launches[:10]:
            item = f"{la.get('project_name', '?')} — {la.get('developer_name', '?')} ({la.get('market', '?')}) {la.get('total_units', 0)}u"
            lines.append(f"• {item[:100]}")
    else:
        lines.append("None this week.")
    lines.append("")

    movers = pulse.get("psf_movers", [])
    lines.append(f"📈 **PSF Movers ({len(movers)})**")
    if movers:
        for m in movers[:10]:
            d = m.get("direction", "?")
            icon = "▲" if d == "UP" else "▼"
            item = f"{m.get('project_name', '?')} — {m.get('developer_name', '?')} ({m.get('market', '?')}) {icon}{abs(m.get('change_pct', 0)):.1f}%"
            lines.append(f"• {item[:100]}")
    else:
        lines.append("None this week.")
    lines.append("")

    absorbers = pulse.get("absorption_leaders", [])
    lines.append("🏆 **Absorption Leaders**")
    if absorbers:
        for a in absorbers[:5]:
            item = f"{a.get('project_name', '?')} — {a.get('developer_name', '?')} ({a.get('market', '?')}) {a.get('absorption_pct', 0):.0f}% sold"
            lines.append(f"• {item[:100]}")
    else:
        lines.append("None this week.")

    result = "\n".join(lines)
    if len(result) > 1500:
        result = result[:1497]
        while len(result.encode("utf-8")) > 1500:
            result = result[:-1]
        result += "..."
    return result


def send_competitive_digest(pulse: dict) -> None:
    msg = format_competitive_digest(pulse)
    try:
        send("bd_opportunities", "Competitive Intelligence Pulse", msg, COLOR_PURPLE)
    except Exception as exc:
        logger.warning("[Discord] send_competitive_digest failed: {}", exc)


def _safe_truncate(text: str | None, max_bytes: int = 100) -> str:
    """Truncate text at word boundary within byte limit.
    Ensures valid UTF-8 — never splits a multi-byte character."""
    if not text:
        return ""
    text = text.strip()
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    truncated = text[:max_bytes]
    while len(truncated.encode("utf-8")) > max_bytes:
        truncated = truncated[:-1]
    last_space = truncated.rfind(" ")
    if last_space > max_bytes // 2:
        truncated = truncated[:last_space]
    return truncated + "…"


def format_landowner_update(status: str, survey_no: str, market: str, owner_name: str,
                             ask_psf: float | None = None, notes: str | None = None) -> str:
    psf_str = f"₹{ask_psf:,.0f}/sqft" if ask_psf else "PSF TBD"
    note_str = f" | {_safe_truncate(notes)}" if notes else ""
    return (
        f"**{status.upper()}** — {market} | Survey {survey_no}\n"
        f"Owner: {owner_name} | {psf_str}{note_str}"
    )[:500]


def send_landowner_alert(status: str, survey_no: str, market: str, owner_name: str,
                          ask_psf: float | None = None, notes: str | None = None) -> bool:
    msg = format_landowner_update(status, survey_no, market, owner_name, ask_psf, notes)
    try:
        return send("bd_opportunities", f"Landowner {status.upper()}: {survey_no}", msg)
    except Exception as exc:
        logger.warning("[Discord] send_landowner_alert failed: {}", exc)
        return False


def send_gcc_alert(event: dict) -> bool:
    """Send a GCC demand signal alert to bd_opportunities and gcc_intel channels.

    Fires only for Level 1–2 events with gcc_signal_score ≥ 7.0 and
    north_bengaluru_impact_score ≥ 0.70. Color reflects maturity:
      Level 1 (pre-public) → GREEN  — genuine intelligence edge
      Level 2 (semi-public) → AMBER — still ahead of market consensus
    """
    maturity = int(event.get("signal_maturity_level") or 3)
    color = COLOR_GREEN if maturity == 1 else COLOR_AMBER

    company = event.get("company", "Unknown")
    corridor = (event.get("nearest_corridor") or "").replace("_", " ").title()
    score = event.get("gcc_signal_score", 0.0) or 0.0
    nb = (event.get("north_bengaluru_impact_score") or 0.0) * 100
    headcount = event.get("planned_headcount")
    ctc = event.get("median_ctc_l")
    segment = event.get("primary_housing_segment", "N/A")
    horizon = event.get("time_horizon", "N/A")
    source = event.get("source_name", "N/A")
    entrant = event.get("entrant_type", "N/A")
    sector = event.get("sector", "N/A")
    maturity_label = {1: "PRE-PUBLIC", 2: "SEMI-PUBLIC", 3: "PUBLIC", 4: "OPERATIONAL"}.get(
        maturity, str(maturity)
    )

    hc_str = f"{headcount:,}" if headcount else "N/A"
    ctc_str = f"₹{ctc}L" if ctc else "N/A"

    msg = (
        f"**Sector:** {sector}\n"
        f"**Entrant:** {entrant}\n"
        f"**Location:** {event.get('bengaluru_location', 'Bengaluru')}\n"
        f"**Corridor:** {corridor}\n"
        f"**Headcount:** {hc_str}\n"
        f"**CTC Median:** {ctc_str}\n"
        f"**Housing Segment:** {segment}\n"
        f"**Signal Score:** {score:.1f}/10.0\n"
        f"**NB Impact:** {nb:.0f}%\n"
        f"**Maturity:** Level {maturity} — {maturity_label}\n"
        f"**Time Horizon:** {horizon}\n"
        f"**Source:** {source}"
    )

    title = f"GCC Signal — {company} | {corridor}"
    try:
        # Primary: bd_opportunities (BD team sees this)
        send("bd_opportunities", title, msg, color)
        # Secondary: gcc_intel (dedicated channel, if configured)
        send("gcc_intel", title, msg, color)
        return True
    except Exception as exc:
        logger.warning("[Discord] send_gcc_alert failed: {}", exc)
        return False


def send_gcc_weekly_digest(events: list[dict], corridor_scores: dict[str, float]) -> bool:
    """Send weekly GCC pipeline digest to the intel channel."""
    if not events and not corridor_scores:
        return False

    lines = ["**North Bengaluru GCC Pipeline — Weekly Digest**\n"]

    if corridor_scores:
        lines.append("**Corridor Scores (gcc_north_norm):**")
        for corridor, norm in sorted(corridor_scores.items(), key=lambda x: -x[1]):
            bar = "▓" * int(norm * 10) + "░" * (10 - int(norm * 10))
            lines.append(f"`{corridor.replace('_', ' ').title():<28}` {bar} {norm:.3f}")
        lines.append("")

    if events:
        lines.append(f"**Top {min(10, len(events))} Signals This Week:**")
        for i, evt in enumerate(events[:10], 1):
            score = evt.get("gcc_signal_score", 0) or 0
            hc = evt.get("planned_headcount") or 0
            lines.append(
                f"{i}. **{evt.get('company', 'N/A')}** ({evt.get('sector', 'N/A')}) "
                f"— {evt.get('nearest_corridor', '').replace('_', ' ')} "
                f"| Score {score:.1f} | {hc:,} hires | {evt.get('time_horizon', 'N/A')}"
            )

    msg = "\n".join(lines)
    try:
        return send("intel", "GCC Weekly Digest — North Bengaluru", msg, COLOR_PURPLE)
    except Exception as exc:
        logger.warning("[Discord] send_gcc_weekly_digest failed: {}", exc)
        return False



