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
import time as _time
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
    "govt_policy_scout": "DISCORD_WEBHOOK_GOVT_POLICY",
    "intel_reports": "DISCORD_WEBHOOK_INTEL_REPORTS",
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


def send_scraper_alert(market: str, scraper_name: str, alert_type: str,
                       cooldown_hours: int = 1, **kwargs) -> bool:
    """Send a scraper-level alert to the system channel.

    Uses SQL cooldown dedup: same (title, channel) within cooldown_hours is skipped.
    Total message truncated at 300 chars to fit Discord embed limits.
    First kwargs are most important — ordering matters for truncation.

    Args:
        market: Market name (e.g. 'Yelahanka')
        scraper_name: Scraper identifier (e.g. 'kaveri_gv', 'rera_karnataka')
        alert_type: Alert type code (e.g. 'STALE_GV', 'FALLBACK_SEED')
        cooldown_hours: Suppress duplicate alerts within this window (default 1h).
        **kwargs: Extra detail fields for the message. Truncated at 300 chars total.
    """
    title = f"{alert_type} — {scraper_name} / {market}"
    try:
        from utils.db import get_engine
        from sqlalchemy import text as _sa_text
        with get_engine().connect() as _conn:
            _row = _conn.execute(
                _sa_text("""
                    SELECT id FROM alerts
                    WHERE channel = 'system' AND title = :title
                      AND created_at > NOW() - (:hrs || ' hours')::interval
                    LIMIT 1
                """),
                {"title": title, "hrs": cooldown_hours},
            ).fetchone()
        if _row:
            logger.debug("[Discord] Scraper alert dedup: '{}' already sent within {}h — skip", title, cooldown_hours)
            return False
    except Exception as _exc:
        logger.debug("[Discord] Scraper alert dedup check failed (allowing send): {}", _exc)

    details = " | ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    message = f"⚠ **[{scraper_name}] {market}**: {alert_type}.\n{details}\nCheck portal connectivity."
    if len(message) > 300:
        message = message[:297] + "..."
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


def format_govt_policy_alert(event: dict) -> str:
    """Format a single govt/policy/infra event as a Discord alert.

    Format:
        🏗️ [EMOJI] HEADLINE
        📍 LOCATION | 💰 INVESTMENT | 📊 STAGE
        🎯 Impact: N/10 | ⏱️ HORIZON | ✅ ACTION
        💡 WHY IT MATTERS (truncated to 200 chars)
    """
    headline = event.get("headline", "Unknown event")
    location = event.get("location_text") or event.get("location", "N/A")
    investment = event.get("investment_cr")
    inv_str = f"₹{investment:,.0f}Cr" if investment else "N/A"
    stage = event.get("stage", "N/A")
    impact = event.get("impact_score", 0) or 0
    horizon = event.get("time_horizon", "N/A")
    action = event.get("actionability", "monitor")
    why = event.get("why_it_matters", "")
    if len(why) > 200:
        why = why[:197] + "..."

    signal = event.get("signal_strength", "emerging")
    if signal == "high":
        signal_emoji = "🟢"
    elif signal == "risk":
        signal_emoji = "🔴"
    else:
        signal_emoji = "🟡"

    if action == "buy_now":
        action_emoji = "⚡"
    elif action == "accumulate":
        action_emoji = "📈"
    elif action == "avoid":
        action_emoji = "⛔"
    else:
        action_emoji = "👁️"

    lines = [
        f"{signal_emoji} **{headline}**",
        f"📍 {location} | 💰 {inv_str} | 📊 {stage}",
        f"🎯 Impact: {impact}/10 | ⏱️ {horizon} | {action_emoji} {action.upper()}",
    ]
    if why:
        lines.append(f"💡 {why}")
    return "\n".join(lines)


def format_govt_policy_weekly_digest(result) -> str:
    """Format weekly govt/policy digest for Discord.

    Args:
        result: GovtPolicyResult dataclass instance or similar dict-like object.
    """
    score = getattr(result, "north_bengaluru_score", 0.0) or 0.0
    high_count = getattr(result, "high_opportunity_count", 0)
    risk_count = getattr(result, "risk_count", 0)
    top_infra = getattr(result, "top_infra_events", []) or []
    top_policy = getattr(result, "top_policy_events", []) or []
    digest = getattr(result, "weekly_digest", "")

    bar_count = min(int(score * 10), 10)
    bar = "█" * bar_count + "░" * (10 - bar_count)

    lines = [
        "**North Bengaluru Govt/Infra/Policy — Weekly Digest**",
        "",
        f"**North Bengaluru Score:** {bar} {score:.3f}",
        f"**High Opportunity:** {high_count} | **Risk Flags:** {risk_count}",
        "",
    ]

    if top_infra:
        lines.append("**Top Infrastructure Events:**")
        for evt in top_infra:
            headline = evt.get("headline", "N/A")[:80]
            impact = evt.get("impact_score", 0) or 0
            stage = evt.get("stage", "N/A")
            lines.append(f"• {headline} | Impact {impact}/10 | {stage}")
        lines.append("")

    if top_policy:
        lines.append("**Top Policy Events:**")
        for evt in top_policy:
            headline = evt.get("headline", "N/A")[:80]
            impact = evt.get("impact_score", 0) or 0
            lines.append(f"• {headline} | Impact {impact}/10")
        lines.append("")

    if digest:
        lines.append(f"**Weekly Digest:**\n{digest[:500]}")

    return "\n".join(lines)


def send_govt_policy_alert(event: dict) -> bool:
    """Send a single govt/policy alert to the govt_policy_scout channel."""
    try:
        msg = format_govt_policy_alert(event)
        signal = event.get("signal_strength", "emerging")
        color = COLOR_GREEN if signal == "high" else (COLOR_RED if signal == "risk" else COLOR_AMBER)
        title = f"Govt/Infra Alert — {event.get('headline', '')[:60]}"
        send("govt_policy_scout", title, msg, color)
        return True
    except Exception as exc:
        logger.warning("[Discord] send_govt_policy_alert failed: {}", exc)
        return False


def send_govt_policy_digest(result) -> bool:
    """Send weekly govt/policy digest to the govt_policy_scout channel."""
    try:
        msg = format_govt_policy_weekly_digest(result)
        send("govt_policy_scout", "Govt/Infra/Policy Weekly Digest", msg, COLOR_BLUE)
        return True
    except Exception as exc:
        logger.warning("[Discord] send_govt_policy_digest failed: {}", exc)
        return False


def format_weekly_digest(result) -> str:
    """Format a single weekly digest result as a Discord embed message. ≤400 chars."""
    market = result.market
    psf_dir = "▲" if result.psf_direction == "up" else ("▼" if result.psf_direction == "down" else "—")
    psf_line = f"PSF: {psf_dir} {result.psf_delta_pct:+.2f}%" if result.psf_delta_pct != 0 else "PSF: no change"
    rera_line = f"New RERA: {result.new_rera_count}"
    comps = result.competitor_launches or []
    if comps:
        names = ", ".join(c["developer_name"] for c in comps[:3])
        comp_line = f"Competitors: {names}" + ("…" if len(comps) > 3 else "")
    else:
        comp_line = "Competitors: none"
    dists = result.distressed_developers or []
    if dists:
        dist_line = "Distressed: " + ", ".join(f"{d['developer_name']}({d['distress_score']:.2f})" for d in dists[:3])
    else:
        dist_line = "Distressed: none"
    top = result.top_opportunity
    if top:
        opp_line = f"Top opp: {top['survey_no']} (score {top['composite_score']:.4f})"
    else:
        opp_line = "Top opp: none"
    msg = f"**{market}**\n{psf_line}\n{rera_line}\n{comp_line}\n{dist_line}\n{opp_line}"
    return msg[:400]


def format_monthly_digest(results: list) -> str:
    """Format all monthly digest results as one combined message. ≤800 chars."""
    date_str = datetime.now(timezone.utc).strftime("%d %b %Y")
    lines = [f"**Monthly Intelligence Digest — {date_str}**\n"]
    for r in results:
        lines.append(f"__{r.market}__")
        lines.append(f"PSF MoM: {r.psf_mom_pct:+.2f}% | Absorption: {r.absorption_trend}")
        lines.append(f"Pipeline: {r.pipeline_supply_added}u | GCC: {r.gcc_events_count} | Gov: {r.govt_policy_events_count}")
        if r.llm_synthesis:
            syn = r.llm_synthesis[:600]
            lines.append(f"> {syn}")
        lines.append("")
    msg = "\n".join(lines)
    if len(msg) > 800:
        msg = msg[:797] + "…"
    return msg


def format_forecast_digest(results: list) -> str:
    """Format PSF forecast digest — one line per market, ≤300 chars total."""
    from loguru import logger as _log
    lines = []
    for r in results:
        try:
            if hasattr(r, "status") and r.status == "ok":
                lines.append(
                    f"{r.market}: {r.trend_direction} | "
                    f"₹{int(r.current_psf):,} → ₹{int(r.forecast_6m):,} (6m) | "
                    f"MAE {r.mae_pct:.1f}%"
                )
            else:
                direction = getattr(r, "trend_direction", "unknown")
                cur = getattr(r, "current_psf", 0)
                lines.append(f"{r.market}: {direction} | ₹{int(cur):,} (insufficient data)")
        except Exception as exc:
            _log.warning("[Discord] format_forecast_digest item failed: {}", exc)
    msg = "\n".join(lines)
    return msg[:297] + "…" if len(msg) > 300 else msg


def send_forecast_digest(results: list) -> None:
    """Send PSF forecast digest to intel_reports channel."""
    from loguru import logger as _log
    try:
        msg = format_forecast_digest(results)
        send("intel_reports", "PSF Forecast Update", msg, COLOR_BLUE)
    except Exception as exc:
        _log.warning("[Discord] send_forecast_digest failed: {}", exc)


def send_weekly_digest(results: list) -> None:
    """Send weekly digest — one embed per market to intel_reports channel."""
    from loguru import logger as _log
    for r in results:
        try:
            msg = format_weekly_digest(r)
            send("intel_reports", f"Weekly Digest — {r.market}", msg, COLOR_GREEN)
        except Exception as exc:
            _log.warning("[Discord] send_weekly_digest failed for {}: {}", r.market, exc)


def send_monthly_digest(results: list) -> None:
    """Send monthly digest — single combined embed to intel_reports channel."""
    from loguru import logger as _log
    try:
        msg = format_monthly_digest(results)
        send("intel_reports", "Monthly Intelligence Digest", msg, COLOR_BLUE)
    except Exception as exc:
        _log.warning("[Discord] send_monthly_digest failed: {}", exc)


_OPS_ALERT_COOLDOWN: dict[str, float] = {}
_OPS_ALERT_COOLDOWN_S = 300


def send_ops_alert(alert_type: str, detail: str) -> bool:
    """Send an OPS alert to the system Discord channel.

    Uses a 5-minute cooldown per alert_type to prevent alert storms.
    Returns True if sent, False if throttled or failed.

    Args:
        alert_type: Machine-readable alert code (e.g. 'DB_BACKUP_FAILED').
        detail: Human-readable description (truncated to 200 chars).
    """
    from loguru import logger as _log
    from datetime import datetime, timezone

    now = _time.time()
    last = _OPS_ALERT_COOLDOWN.get(alert_type, 0.0)
    if now - last < _OPS_ALERT_COOLDOWN_S:
        _log.debug("[Discord] OPS alert '{}' throttled ({}s cooldown)", alert_type, _OPS_ALERT_COOLDOWN_S)
        return False
    _OPS_ALERT_COOLDOWN[alert_type] = now

    try:
        msg = f"{alert_type}: {detail[:200]}\nTime: {datetime.now(timezone.utc).isoformat()}"
        result = send("system", f"⚠ {alert_type}", msg, COLOR_RED)
        return result
    except Exception as exc:
        _log.warning("[Discord] send_ops_alert failed: {}", exc)
        return False

