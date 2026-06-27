"""
RE_OS — Obsidian Sync (Sprint 133 GATE-133)

Writes Board Room verdicts, weekly digests, and PSF forecasts as Obsidian
markdown files with LLS CLAUDE.md standard frontmatter.

Public API:
    write_board_verdict(market, md, decision_flag="CONDITIONAL") -> str
    write_weekly_digest(market, md_or_result) -> str
    write_psf_forecast(market, forecast) -> str

Return value conventions:
    Non-empty str: absolute path to the written file (success).
    "" (empty str): write was attempted but failed (disk full, permissions,
        content too large, or I/O error).  The caller should NOT retry without
        intervention.
    None: write was not attempted because the sync path is not mounted or
        does not exist.  The caller MAY retry on a subsequent call without
        intervention (e.g. after the volume mount becomes available).

Args on all three functions:
    market: str — market name, used in filename and frontmatter.
    md / md_or_result / forecast: str | WeeklyDigestResult | dict — content.

Raises: Never raises.  All I/O and formatting errors are caught and logged.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from utils.weekly_digest import WeeklyDigestResult

__all__ = [
    "write_board_verdict",
    "write_weekly_digest",
    "write_psf_forecast",
    "write_decision_journal_entry",
    "write_investor_brief",
]

_VALID_DECISION_FLAGS: frozenset[str] = frozenset({"GO", "NO-GO", "CONDITIONAL"})
_MAX_CONTENT_BYTES: int = 5 * 1024 * 1024
_MIN_DISK_FREE_BYTES: int = 1 * 1024 * 1024

_FRONTMATTER_TEMPLATE: str = """---
type: crystallization
area: lls
ai_generated: true
generated_at: {timestamp}
date: {date_str}
market: {market}
source: {source}
status: active
confidence: {confidence}
last_confirmed: {date_str}
---"""

_FORECAST_DISPLAY_KEYS: list[tuple[str, str]] = [
    ("trend_direction", "Trend"),
    ("current_psf", "Current PSF"),
    ("forecast_3m", "3-Month Forecast"),
    ("forecast_6m", "6-Month Forecast"),
    ("forecast_12m", "12-Month Forecast"),
    ("data_points", "Data Points"),
    ("mae_pct", "MAE"),
    ("status", "Status"),
]


def _sync_path() -> str:
    return os.environ.get("OBSIDIAN_SYNC_PATH", "/app/obsidian_sync")


def _ensure_sync_dir() -> bool:
    p = _sync_path()
    if not os.path.isdir(p):
        logger.info("[ObsidianSync] Path not mounted — skipping")
        return False
    return True


def _check_disk_space(path: str) -> None:
    try:
        usage = shutil.disk_usage(os.path.dirname(path) or ".")
        if usage.free < _MIN_DISK_FREE_BYTES:
            raise OSError(
                f"Only {usage.free} bytes free on {os.path.dirname(path)} "
                f"(min {_MIN_DISK_FREE_BYTES})"
            )
    except OSError:
        raise
    except Exception as exc:
        logger.debug(f"[ObsidianSync] disk_usage unavailable: {exc}")


def _log_write_audit(filename: str, path: str, content: str) -> None:
    size = len(content.encode("utf-8"))
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    logger.info(
        f"[ObsidianSync] Audit: {filename}, {size}B, sha256={digest}, path={path}"
    )


def _write_md(filename: str, content: str) -> Optional[str]:
    p = _sync_path()
    try:
        os.makedirs(p, exist_ok=True)
    except Exception as exc:
        logger.warning(f"[ObsidianSync] mkdir failed {p}: {exc}")
        return None

    if not content:
        logger.warning("[ObsidianSync] Empty content — skipping write")
        return ""

    encoded = content.encode("utf-8")
    if len(encoded) > _MAX_CONTENT_BYTES:
        logger.warning(
            f"[ObsidianSync] Content too large: {len(encoded)}B "
            f"(max {_MAX_CONTENT_BYTES}B)"
        )
        return ""

    filepath = os.path.join(p, filename)

    try:
        _check_disk_space(filepath)
    except OSError as exc:
        logger.warning(f"[ObsidianSync] Disk space check failed: {exc}")
        return ""

    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=p, prefix=".obsidian_tmp_")
        with os.fdopen(fd, "wb") as f:
            f.write(encoded)
        os.replace(tmp, filepath)
        tmp = None
        _log_write_audit(filename, filepath, content)
        from config.metrics import obsidian_export_total, obsidian_bytes_total
        obsidian_export_total.labels(source="obsidian_sync").inc()
        obsidian_bytes_total.labels(source="obsidian_sync").inc(len(encoded))
        return filepath
    except Exception as exc:
        logger.warning(f"[ObsidianSync] Failed to write {filename}: {exc}")
        return ""
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except Exception:
                pass


def _format_currency(val: object) -> str:
    if val is None:
        return "\u2014"
    try:
        num = int(val)
        return f"\u20b9{num:,}" if num else "\u20b90"
    except (ValueError, TypeError):
        return str(val)


def _format_pct(val: object) -> str:
    if val is None:
        return "\u2014"
    try:
        return f"{float(val):.1f}%"
    except (ValueError, TypeError):
        return str(val)


def write_board_verdict(
    market: str,
    md: str,
    decision_flag: str = "CONDITIONAL",
) -> Optional[str]:
    """Write a Board Room verdict as an Obsidian note.

    Args:
        market: Micro-market name (Yelahanka, Devanahalli, Hebbal).
        md: Markdown body of the verdict.
        decision_flag: GO / NO-GO / CONDITIONAL.  Invalid values default to
            CONDITIONAL with a warning log.

    Returns:
        File path on success, ``None`` if sync path not mounted, ``""`` on
        write failure.  See module docstring for caller guidance.
    """
    if not _ensure_sync_dir():
        return None
    if decision_flag not in _VALID_DECISION_FLAGS:
        logger.warning(
            f"[ObsidianSync] Invalid decision_flag={decision_flag!r} — "
            f"defaulting to CONDITIONAL"
        )
        decision_flag = "CONDITIONAL"
    now = datetime.now(timezone.utc)
    ts = now.isoformat(timespec="seconds")
    date_str = now.strftime("%Y-%m-%d")
    fm = _FRONTMATTER_TEMPLATE.format(
        timestamp=ts,
        date_str=date_str,
        market=market,
        source="board_room",
        confidence=0.85,
    )
    content = (
        f"{fm}\n\n"
        f"# Board Room Verdict - {market}\n\n"
        f"**Decision Flag:** {decision_flag}\n\n"
        f"{md}\n"
    )
    filename = f"(AI) Board Room Verdict {market} {date_str}.md"
    return _write_md(filename, content)


def write_weekly_digest(
    market: str,
    md_or_result: str | WeeklyDigestResult,
) -> Optional[str]:
    """Write a weekly market digest as an Obsidian note.

    Args:
        market: Micro-market name.
        md_or_result: Either a raw markdown string (backward-compatible) or a
            ``WeeklyDigestResult`` dataclass instance (structured).  When a
            dataclass is passed the frontmatter confidence is derived from the
            number of populated fields.

    Returns:
        File path on success, ``None`` if sync path not mounted, ``""`` on
        write failure.  See module docstring for caller guidance.
    """
    if not _ensure_sync_dir():
        return None
    now = datetime.now(timezone.utc)
    ts = now.isoformat(timespec="seconds")
    date_str = now.strftime("%Y-%m-%d")

    if isinstance(md_or_result, WeeklyDigestResult):
        r = md_or_result
        populated = sum(1 for f in [r.psf_delta_pct, r.new_rera_count,
                                    r.competitor_launches, r.distressed_developers,
                                    r.top_opportunity] if f)
        confidence = round(0.5 + populated * 0.08, 2)
        lines = [
            f"## {r.market}",
            "",
            f"**PSF Delta:** {r.psf_delta_pct:+.2f}% ({r.psf_direction})",
            f"**New RERA:** {r.new_rera_count}",
            f"**Competitor Launches:** {len(r.competitor_launches)}",
            f"**Distressed Developers:** {len(r.distressed_developers)}",
            "",
        ]
        if r.top_opportunity:
            t = r.top_opportunity
            lines.append(
                f"**Top Opportunity:** {t['survey_no']} — "
                f"composite {t['composite_score']:.4f}"
            )
        for c in r.competitor_launches[:5]:
            lines.append(
                f"- {c['developer_name']} — {c['project_name']} "
                f"(Grade {c['grade']}, {c['units']} units)"
            )
        for d in r.distressed_developers[:5]:
            lines.append(
                f"- {d['developer_name']} (score: {d['distress_score']:.2f})"
            )
        body = "\n".join(lines)
    else:
        body = str(md_or_result)
        confidence = 0.80

    fm = _FRONTMATTER_TEMPLATE.format(
        timestamp=ts,
        date_str=date_str,
        market=market,
        source="weekly_digest",
        confidence=confidence,
    )
    content = (
        f"{fm}\n\n"
        f"# Weekly Market Digest - {market}\n\n"
        f"{body}\n"
    )
    filename = f"(AI) Weekly Digest {market} {date_str}.md"
    return _write_md(filename, content)


def write_psf_forecast(
    market: str,
    forecast: dict,
) -> Optional[str]:
    """Write a PSF forecast snapshot as an Obsidian note.

    Args:
        market: Micro-market name.
        forecast: dict with keys matching ``ForecastResult`` dataclass fields:
            tregion_direction, current_psf, forecast_3m, forecast_6m,
            forecast_12m, data_points, mae_pct, status.  Missing keys render
            as "\u2014" (em dash) in the table.

    Returns:
        File path on success, ``None`` if sync path not mounted, ``""`` on
        write failure.  See module docstring for caller guidance.
    """
    if not _ensure_sync_dir():
        return None
    now = datetime.now(timezone.utc)
    ts = now.isoformat(timespec="seconds")
    date_str = now.strftime("%Y-%m-%d")
    dp = forecast.get("data_points", 0) or 0
    confidence = round(min(0.95, 0.5 + int(dp) * 0.05), 2)

    table_rows: list[str] = []
    for key, label in _FORECAST_DISPLAY_KEYS:
        raw = forecast.get(key)
        if key in ("mae_pct",):
            val = _format_pct(raw)
        elif key in ("current_psf", "forecast_3m", "forecast_6m", "forecast_12m"):
            val = _format_currency(raw)
        else:
            val = str(raw) if raw is not None else "\u2014"
        table_rows.append(f"| {label} | {val} |")

    current = forecast.get("current_psf", 0) or 0
    f6m = forecast.get("forecast_6m", 0) or 0
    if current and f6m:
        mom = ((f6m - current) / current) * 100
        table_rows.append(f"| 6-Mo Change | {mom:+.1f}% |")

    body = "\n".join(table_rows)

    fm = _FRONTMATTER_TEMPLATE.format(
        timestamp=ts,
        date_str=date_str,
        market=market,
        source="psf_forecaster",
        confidence=confidence,
    )
    content = (
        f"{fm}\n\n"
        f"# PSF Forecast - {market}\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"{body}\n"
    )
    filename = f"(AI) PSF Forecast {market} {date_str}.md"
    return _write_md(filename, content)


def write_decision_journal_entry(entry: dict) -> Optional[str]:
    if not _ensure_sync_dir():
        return None
    now = datetime.now(timezone.utc)
    ts = now.isoformat(timespec="seconds")
    date_str = now.strftime("%Y-%m-%d")
    market = entry.get("market", "Unknown")
    decision_flag = entry.get("decision_flag", "NEUTRAL")
    context = entry.get("context_summary", "")
    board_session_id = entry.get("board_session_id")
    frontmatter_lines = [
        "---",
        "type: decision",
        "area: lls",
        "ai_generated: true",
        f"generated_at: {ts}",
        f"date: {date_str}",
        f"market: {market}",
        f"decision_flag: {decision_flag}",
        f"confidence: {0.85 if decision_flag in ('GO', 'NO-GO') else 0.65}",
    ]
    if board_session_id:
        frontmatter_lines.append(f"board_session_id: {board_session_id}")
    frontmatter_lines.append("---")
    body = context or "No context summary available."
    content = "\n".join(frontmatter_lines) + f"\n\n# Decision Journal — {market}\n\n{body}\n"
    safe_market = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in market)
    safe_flag = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in decision_flag)
    filename = f"(AI) {date_str}-{safe_market}-{safe_flag}.md"
    return _write_md(filename, content)


def write_investor_brief(
    market: str,
    brief_md: str,
    project_name: str = "RE_OS",
    land_cost_cr: float = 0.0,
    area_acres: float = 0.0,
) -> Optional[str]:
    """Write an investor brief as an Obsidian note under the VEL or RE_market project.

    Args:
        market: Micro-market name.
        brief_md: Formatted markdown body.
        project_name: Project name for the brief (default RE_OS).
        land_cost_cr: Land cost in crores (for filename context).
        area_acres: Land area in acres (for filename context).

    Returns:
        File path on success, ``None`` if sync path not mounted, ``""`` on write failure.
    """
    if not _ensure_sync_dir():
        return None
    now = datetime.now(timezone.utc)
    ts = now.isoformat(timespec="seconds")
    date_str = now.strftime("%Y-%m-%d")

    is_vel = market.lower() in ("yelahanka", "devanahalli")
    subdir = "VEL" if is_vel else "RE_market"
    vault_base = _sync_path()
    project_dir = os.path.join(vault_base, "03 LLS", "02 Projects", subdir)
    os.makedirs(project_dir, exist_ok=True)

    safe_market = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in market)
    safe_project = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in project_name)

    fm_lines = [
        "---",
        "type: wiki",
        "area: lls",
        f"project: {subdir}",
        "ai_generated: true",
        f"generated_at: {ts}",
        f"date: {date_str}",
        f"market: {market}",
        f"project_name: {project_name}",
        f"land_cost_cr: {land_cost_cr}",
        f"area_acres: {area_acres}",
        "confidence: 0.8",
        "---",
    ]
    frontmatter = "\n".join(fm_lines)
    content = f"{frontmatter}\n\n{brief_md}\n"
    filename = f"(AI) {date_str}-Market-Brief-{safe_market}-{safe_project}.md"
    filepath = os.path.join(project_dir, filename)

    try:
        from config.metrics import obsidian_export_total, obsidian_bytes_total
        encoded = content.encode("utf-8")
        with open(filepath, "wb") as f:
            f.write(encoded)
        _log_write_audit(filename, filepath, content)
        obsidian_export_total.labels(source="investor_brief").inc()
        obsidian_bytes_total.labels(source="investor_brief").inc(len(encoded))
        return filepath
    except Exception as exc:
        logger.warning(f"[ObsidianSync] Failed to write investor brief {filename}: {exc}")
        return ""
