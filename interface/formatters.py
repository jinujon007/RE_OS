"""
RE_OS — Telegram Formatters (Sprint 65 — Interface Layer)
Format election verdicts into compact 1200-char Telegram messages.
"""

from typing import Any
from loguru import logger


def format_telegram_verdict(
    market: str,
    survey_no: str,
    score: float,
    components: dict[str, float],
    legal_risk: str,
    next_action: str,
    deal_memo: dict | None = None,
    investor_brief: dict | None = None,
) -> str:
    """Format a compact 1200-char verdict for Telegram.

    Layout:
    HEADER
    Finance  | Legal     | Timing    | Distress  | Exclusivity
    SCORE badge
    RECOMMENDATION badge
    Next action
    """
    lines = []

    # Header
    header = f"{market} — {survey_no}"
    lines.append(f"\u2554\u2558\u2558\u2558 {header} \u2558\u2558\u2558")
    lines.append("\u2551")

    # Department one-liners
    dept_lines = []
    irr = components.get("irr", 0)
    legal = components.get("legal", 0)
    timing = components.get("timing", 0)
    distress = components.get("distress", 0)
    exclusivity = components.get("exclusivity", 0)

    dept_lines.append(f"\u2551 FINANCE    \u2502 IRR {irr:.0%}")
    dept_lines.append(f"\u2551 LEGAL      \u2502 {legal:.0%} ({legal_risk})")
    dept_lines.append(f"\u2551 TIMING     \u2502 {timing:.0%}")
    dept_lines.append(f"\u2551 DISTRESS   \u2502 {distress:.0%}")
    dept_lines.append(f"\u2551 EXCLUSIVITY \u2502 {exclusivity:.0%}")
    lines.extend(dept_lines)

    lines.append("\u2551")

    # Composite score badge
    score_pct = score * 100
    if score >= 0.8:
        score_badge = "\u2588\u2588 URGENT \u2588\u2588"
    elif score >= 0.6:
        score_badge = "\u2588\u2588 PRIORITY \u2588\u2588"
    elif score >= 0.4:
        score_badge = "\u2013\u2013 WATCH \u2013\u2013"
    else:
        score_badge = "\u00b7\u00b7 OBSERVE \u00b7\u00b7"

    lines.append(f"\u2551 SCORE: {score:.1%} {score_badge}")
    lines.append(f"\u2551 NEXT: {next_action[:60]}")

    # Recommendation badge
    if score >= 0.8:
        rec = "\u2605\u2605\u2605\u2605\u2605 STRONG BUY"
    elif score >= 0.6:
        rec = "\u2605\u2605\u2605\u2605\u2606 BUY"
    elif score >= 0.4:
        rec = "\u2605\u2605\u2606\u2606\u2606 CAUTIOUS"
    else:
        rec = "\u2605\u2606\u2606\u2606\u2606 HOLD"
    lines.append(f"\u2551 RECOMMENDATION: {rec}")

    lines.append("\u255a" + "\u2550" * 30)

    # Deal memo summary if available
    if deal_memo:
        lines.append("")
        lines.append("\ud83d\udccb Deal Memo")
        summary = deal_memo.get("summary", "") or deal_memo.get("recommendation", "")
        if summary:
            lines.append(summary[:200])

    # Investor brief
    if investor_brief:
        lines.append("")
        lines.append("\ud83d\udcca Investor Brief")
        key_metrics = investor_brief.get(
            "key_metrics", investor_brief.get("highlights", "")
        )
        if key_metrics:
            metrics_str = str(key_metrics)[:200]
            lines.append(metrics_str)

    verdict = "\n".join(lines)

    # Truncate to 1200 chars at word boundary
    if len(verdict) > 1200:
        verdict = verdict[:1197].rsplit(" ", 1)[0] + "\u2026"

    logger.debug(f"[Formatter] Verdict {len(verdict)} chars for {market}/{survey_no}")
    return verdict


def format_opportunity_alert(
    survey_no: str, score: float, market: str, next_action: str
) -> str:
    """Compact one-line opportunity alert for Telegram."""
    icon = "\U0001f7e2" if score >= 0.8 else "\U0001f7e1" if score >= 0.6 else "\u26aa"
    return f"{icon} {market} {survey_no}: {score:.0%} \u2014 {next_action[:50]}"


def format_error(message: str) -> str:
    """Format an error message for Telegram."""
    return f"\u274c Error: {message[:200]}"
