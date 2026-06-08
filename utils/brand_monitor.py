"""
RE_OS — Brand Mention Monitor (Sprint 59 — PR Dept Completion)
Scans news_articles for brand mentions and returns structured results.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any
from loguru import logger

__all__ = ["BrandMentionMonitor", "format_pr_brief_digest"]

_BRAND_PATTERNS_CACHE: dict[str, list[str]] = {}
_MONITOR_RUNS_TOTAL: dict[str, int] = {"ok": 0, "fail": 0}


def _brand_sql_patterns(brand: str) -> list[str]:
    cached = _BRAND_PATTERNS_CACHE.get(brand)
    if cached:
        return cached
    if brand.upper() == "LLS":
        patterns = [
            "%LLS%",
            "%Land and LifeSpace%",
            "%Land & Life Space%",
            "%Vyoma%",
        ]
    else:
        patterns = [f"%{brand}%"]
    _BRAND_PATTERNS_CACHE[brand] = patterns
    return patterns


def _classify_mention_text(text: str, brand: str) -> str:
    tl = text.lower()
    if brand.upper() == "LLS":
        if "launch" in tl or "new project" in tl or "upcoming" in tl:
            return "project_launch"
        if "award" in tl or "recognition" in tl or "ranking" in tl:
            return "award_recognition"
        if "partner" in tl or "collaboration" in tl or "tie-up" in tl or "alliance" in tl:
            return "partnership"
        if "price" in tl or "rate" in tl or "valuation" in tl:
            return "pricing_news"
        if "interview" in tl or "quote" in tl or "said" in tl:
            return "executive_press"
    return "general_mention"


def _format_dt(dt_val: Any) -> str:
    if dt_val is None:
        return ""
    if isinstance(dt_val, str):
        return dt_val
    if hasattr(dt_val, "isoformat"):
        return dt_val.isoformat()
    return str(dt_val)


def _try_emit_metrics(success: bool) -> None:
    try:
        from config.metrics import scraper_runs_total
        scraper_runs_total.labels(
            source="brand_monitor",
            market="system",
            status="ok" if success else "fail",
        ).inc()
    except Exception:
        pass


def _collect_brand_mentions(brand: str = "LLS", days: int = 7) -> list[dict]:
    """Query news_articles for brand mentions.

    Returns list of dicts with keys: article_id, title, sentiment_label,
    mention_type, published_at, source. Empty list on any DB error.
    Never raises. Thread-safe.

    Args:
        brand: Brand name to search for (default LLS)
        days: Lookback window in days

    Returns:
        list[dict]: Structured mention results, possibly empty
    """
    results: list[dict] = []
    correlation_id = str(uuid.uuid4())[:8]
    try:
        from utils.db import get_engine
        from sqlalchemy import text

        patterns = _brand_sql_patterns(brand)
        if not patterns:
            logger.debug("[BrandMonitor:{}] No patterns for brand '{}'", correlation_id, brand)
            return results

        filtered_since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        params: dict[str, Any] = {"since": filtered_since.isoformat()}
        or_clauses = " OR ".join(f"content ILIKE :p{i}" for i, _ in enumerate(patterns))
        for i, pat in enumerate(patterns):
            params[f"p{i}"] = pat

        sql = f"""
            SELECT id, title, content, sentiment_label, sentiment_score,
                   source, published_at, created_at
            FROM news_articles
            WHERE ({or_clauses})
              AND created_at >= :since
            ORDER BY created_at DESC
            LIMIT 200
        """
        with get_engine().connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()

        for row in rows:
            content = row[2] or ""
            mention_type = _classify_mention_text(content, brand)
            results.append({
                "article_id": str(row[0]),
                "title": row[1] or "",
                "sentiment_label": row[3] or "unscored",
                "mention_type": mention_type,
                "published_at": _format_dt(row[6]),
                "source": row[5] or row[4] or "unknown",
            })

        _MONITOR_RUNS_TOTAL["ok"] += 1
        _try_emit_metrics(True)
        logger.debug("[BrandMonitor:{}] Found {} mentions for '{}' ({}d)", correlation_id, len(results), brand, days)

    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        logger.warning("[BrandMonitor:{}] Scan failed for '{}': {}", correlation_id, brand, exc)
        _MONITOR_RUNS_TOTAL["fail"] += 1
        _try_emit_metrics(False)

    return results


class BrandMentionMonitor:
    """Scans news_articles for brand mentions.

    Usage:
        monitor = BrandMentionMonitor()
        mentions = monitor.scan_mentions('LLS', days=7)

    Thread-safe. Never raises. Empty list on DB error.
    Idempotent — multiple calls with same params return same data (assuming DB unchanged).
    """

    def scan_mentions(self, brand: str = "LLS", days: int = 7) -> list[dict[str, Any]]:
        days = max(1, min(365, int(days)))
        return _collect_brand_mentions(brand, days)


def _truncate_utf8_safe(text: str, max_bytes: int) -> str:
    """Truncate text at utf-8 byte boundary, never splitting multi-byte characters.
    Returns original text unchanged if within byte limit."""
    if len(text.encode("utf-8")) <= max_bytes:
        return text
    result = text[:max_bytes]
    while len(result.encode("utf-8")) > max_bytes:
        result = result[:-1]
    max_bytes_suffix = "..."
    result = result[:max(0, max_bytes - len(max_bytes_suffix))]
    while len((result + max_bytes_suffix).encode("utf-8")) > max_bytes:
        result = result[:-1]
    return result + max_bytes_suffix


def format_pr_brief_digest(mentions: list[dict], launches: list[dict],
                            linkedin_preview: str = "") -> str:
    """Format a PR brief digest for Discord (≤1500 bytes).

    Args:
        mentions: List of brand mention dicts from BrandMentionMonitor
        launches: List of competitor launch dicts from CompetitiveIntelEngine
        linkedin_preview: Up to 100 chars of LinkedIn post text

    Returns:
        Discord-formatted string ≤1500 bytes utf-8 safe
    """
    date_str = datetime.now(timezone.utc).strftime("%a %d %b %Y")
    lines = [f"**PR Brief — {date_str}**\n"]

    mention_count = len(mentions) if mentions else 0
    lines.append(f"**Brand Mentions ({mention_count})**")
    if mention_count > 0:
        pos = sum(1 for m in mentions if m.get("sentiment_label") == "positive")
        neg = sum(1 for m in mentions if m.get("sentiment_label") == "negative")
        neut = mention_count - pos - neg
        neut_label = "Neutral" if neut > 0 else ""
        parts = [f"Positive: {pos}", f"Negative: {neg}"]
        if neut > 0:
            parts.append(f"Neutral: {neut}")
        lines.append(" | ".join(parts))
        for m in mentions[:5]:
            title = (m.get("title") or "")[:80]
            src = m.get("source") or "?"
            lines.append(f"• {title} ({src})")
    else:
        lines.append("No brand mentions this week.")
    lines.append("")

    launch_count = len(launches) if launches else 0
    lines.append(f"**Competitor Launches ({launch_count})**")
    if launch_count > 0:
        for la in launches[:5]:
            name = la.get("project_name") or "?"
            dev = la.get("developer_name") or "?"
            lines.append(f"• {name} — {dev}")
    else:
        lines.append("None this week.")
    lines.append("")

    if linkedin_preview:
        preview = (linkedin_preview or "").strip()[:100]
        if preview:
            lines.append("**LinkedIn Draft Preview:**")
            lines.append(f"_{preview}..._")
        lines.append("")

    result = "\n".join(lines)
    return _truncate_utf8_safe(result, 1500)
