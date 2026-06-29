"""
RE_OS — Deed Pipeline Progress Tracker (GATE-145, T-1412/T-1413)
───────────────────────────────────────────────────────────────
Scans inbox PDFs, tracks ingested vs pending, and computes
throughput projection against the 50/week kill-criteria deadline.

Public API:
  - get_inbox_progress(market?) → inbox/ingest/pending stats
  - compute_throughput_projection() → rolling avg + verdict
  - get_priority_villages(market?, top_n) → ranked download guide
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import TypedDict

from loguru import logger
from sqlalchemy import text

from utils.db import get_engine

__all__ = [
    "get_inbox_progress",
    "compute_throughput_projection",
    "get_priority_villages",
]

_INBOX_BASE = Path("data/kaveri_deeds/inbox")
_FORM17_DIR = _INBOX_BASE / "form17"
_DEADLINE = date(2026, 8, 15)

_PRIORITY_TOP_N_MAX = 100
_PRIORITY_TOP_N_MIN = 1


class PriorityVillage(TypedDict):
    village: str
    market: str
    assembly_signal_count: int
    max_confidence: float
    last_deed_ingested: str | None
    priority_score: float
    kaveri_url_hint: str


def get_inbox_progress(market: str | None = None) -> dict:
    """Scan inbox PDFs and compare against registered_transactions to compute
    progress stats.

    Args:
        market: Optional market filter. If provided, limits `this_week_new_rows`
                to rows whose village/hobli matches the market. If None, counts
                all markets.

    Returns:
        dict with total_pdfs, ingested, pending, pending_files,
        last_ingested_at (ISO str or None), this_week_new_rows (int).
    """
    all_pdfs: list[Path] = []
    for d in [_INBOX_BASE, _FORM17_DIR]:
        if d.exists():
            all_pdfs.extend(sorted(d.glob("*.pdf")))

    total_pdfs = len(all_pdfs)
    pdf_names = {p.name for p in all_pdfs}

    ingested_pdf_names: set[str] = set()
    last_ingested_dt: datetime | None = None
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT rt.source_ref, MAX(rt.created_at) AS last_created
                    FROM registered_transactions rt
                    WHERE rt.created_at IS NOT NULL
                    GROUP BY rt.source_ref
                """),
            ).fetchall()

        for ref, created in rows:
            if ref:
                ref_basename = ref.split("/")[-1].split("\\")[-1]
                if ref_basename in pdf_names:
                    ingested_pdf_names.add(ref_basename)
            if created:
                if isinstance(created, datetime):
                    c_dt = created
                elif isinstance(created, str):
                    try:
                        c_dt = datetime.fromisoformat(created)
                    except (ValueError, TypeError):
                        continue
                else:
                    continue
                if last_ingested_dt is None or c_dt > last_ingested_dt:
                    last_ingested_dt = c_dt

    except Exception as exc:
        logger.warning("[DeedProgress] DB query failed: {}", exc)

    ingested = len(ingested_pdf_names)
    pending = total_pdfs - ingested
    pending_files = sorted(pdf_names - ingested_pdf_names)
    last_ingested_at = last_ingested_dt.isoformat() if last_ingested_dt else None

    this_week_new_rows = 0
    week_start = date.today() - timedelta(days=date.today().weekday())
    try:
        with get_engine().connect() as conn:
            market_join = ""
            params: dict[str, object] = {"ws": week_start}
            if market:
                market_join = " AND rt.village ILIKE :mkt"
                params["mkt"] = f"%{market}%"
            r = conn.execute(
                text(f"""
                    SELECT COUNT(*) FROM registered_transactions rt
                    WHERE rt.created_at >= :ws{market_join}
                """),
                params,
            ).scalar()
            this_week_new_rows = r or 0
    except Exception as exc:
        logger.warning("[DeedProgress] Weekly count query failed: {}", exc)

    return {
        "total_pdfs": total_pdfs,
        "ingested": ingested,
        "pending": pending,
        "pending_files": pending_files,
        "last_ingested_at": last_ingested_at,
        "this_week_new_rows": this_week_new_rows,
    }


def compute_throughput_projection() -> dict:
    """Compute throughput projection against the 50/week kill-criteria target.

    Queries v_deed_throughput_weekly for last 4 weeks, computes rolling
    average, and returns a projection verdict.

    Returns:
        dict with:
          - avg_4wk: float — 4-week rolling average deeds/week
          - weeks_remaining: int — weeks until 2026-08-15
          - required_rate: int — 50 (kill criteria target)
          - projection_verdict: str — 'on_track' / 'at_risk' / 'will_miss'
          - weeks_to_target: int | None — estimated weeks to reach 50/week
          - deadline: str — ISO date of kill-criteria deadline
    """
    avg_4wk = 0.0
    fetched = False
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT week_start, deed_count
                    FROM v_deed_throughput_weekly
                    ORDER BY week_start DESC
                    LIMIT 4
                """),
            ).fetchall()
        fetched = True
        if rows:
            counts = [int(r[1]) if r[1] else 0 for r in rows]
            avg_4wk = sum(counts) / len(counts)
    except Exception as exc:
        method = logger.warning if fetched else logger.warning
        method("[DeedProgress] Throughput query failed{}: {}", " (view missing)" if not fetched else "", exc)

    today = date.today()
    weeks_remaining = max(0, (_DEADLINE - today).days // 7)
    required_rate = 50

    if avg_4wk >= 50:
        projection_verdict = "on_track"
        weeks_to_target = None
    elif avg_4wk * 1.2 >= 50:
        projection_verdict = "at_risk"
        weeks_to_target = math.ceil(50 / avg_4wk) if avg_4wk > 0 else None
    else:
        projection_verdict = "will_miss"
        weeks_to_target = None

    return {
        "avg_4wk": round(avg_4wk, 1),
        "weeks_remaining": weeks_remaining,
        "required_rate": required_rate,
        "projection_verdict": projection_verdict,
        "weeks_to_target": weeks_to_target,
        "deadline": _DEADLINE.isoformat(),
    }


def _format_date(raw_date: object) -> str | None:
    """Safely format a DB date value to ISO string."""
    if raw_date is None:
        return None
    if hasattr(raw_date, "isoformat"):
        return raw_date.isoformat()
    if isinstance(raw_date, str):
        return raw_date
    return str(raw_date)


def _parse_village_row(row) -> PriorityVillage:
    """Map a DB row from v_deed_village_priority to a PriorityVillage dict."""
    m = row._mapping
    village = str(m["village"] or "")
    return PriorityVillage(
        village=village,
        market=str(m["market"] or ""),
        assembly_signal_count=int(m["assembly_signal_count"]) if m["assembly_signal_count"] else 0,
        max_confidence=float(m["max_confidence"]) if m["max_confidence"] else 0.0,
        last_deed_ingested=_format_date(m["last_deed_ingested"]),
        priority_score=float(m["priority_score"]) if m["priority_score"] else 0.0,
        kaveri_url_hint=(
            f"https://kaverionline.karnataka.gov.in → "
            f"Form 17 Index II → Village: {village}"
        ),
    )


def get_priority_villages(
    market: str | None = None,
    top_n: int = 5,
) -> list[PriorityVillage]:
    """Query v_deed_village_priority for villages ranked by assembly signal density.

    Priority score = (signal_count × max_confidence) - days_since_last_deed.
    Higher score → more intelligence value in downloading this week.

    Args:
        market: Optional case-insensitive substring filter (e.g., "Yelahanka").
        top_n:  Max results (default 5, clamped to [{_PRIORITY_TOP_N_MIN}, {_PRIORITY_TOP_N_MAX}]).

    Returns:
        List of PriorityVillage dicts sorted by descending priority_score.
        Empty list on DB failure — caller should handle gracefully.
    """
    top_n = max(_PRIORITY_TOP_N_MIN, min(top_n, _PRIORITY_TOP_N_MAX))
    try:
        with get_engine().connect() as conn:
            # SAFETY: where is either "WHERE 1=1" or "WHERE asm.market ILIKE :market"
            # — only two hardcoded values, never user interpolation.
            where = "WHERE 1=1"
            params: dict[str, object] = {}
            if market:
                where = "WHERE asm.market ILIKE :market"
                params["market"] = f"%{market}%"
            rows = conn.execute(
                text(f"""
                    SELECT village, market, assembly_signal_count,
                           max_confidence, last_deed_ingested, priority_score
                    FROM v_deed_village_priority asm
                    {where}
                    ORDER BY priority_score DESC
                    LIMIT :limit
                """),
                {"limit": top_n, **params},
            ).fetchall()
    except Exception as exc:
        logger.warning("[DeedProgress] get_priority_villages failed: {}", exc)
        return []

    return [_parse_village_row(row) for row in rows]
