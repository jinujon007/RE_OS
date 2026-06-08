"""
RE_OS — Decision Auditor (Phase 14 - Sprint 62)
Reviews past board decisions for quarterly shareholder review.
"""
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text

from utils.db import get_engine
from utils.performance_digest import parse_quarter, safe_query

logger = logging.getLogger(__name__)


def _board_decisions(start: date, end: date) -> list[dict[str, Any]]:
    rows = safe_query(
        "SELECT session_id, market, status, "
        "COALESCE(ceo_synthesis, '') AS ceo_synthesis, "
        "created_at "
        "FROM board_sessions "
        "WHERE created_at >= :start AND created_at < :end_date "
        "ORDER BY created_at DESC",
        {"start": start, "end_date": end + timedelta(days=1)},
    )
    return [
        {
            "session_id": str(r[0]),
            "market": r[1],
            "status": r[2],
            "board_verdict": _infer_verdict(r[3] or ""),
            "deal_memo_summary": (r[3] or "")[:200],
            "source": "board_session",
            "created_at": r[4].isoformat() if r[4] else None,
            "_created_ts": r[4],
        }
        for r in rows
    ]


def _deal_decisions(start: date, end: date) -> list[dict[str, Any]]:
    rows = safe_query(
        "SELECT d.id, d.deal_name, d.survey_no, d.deal_type, "
        "d.irr_base, d.verdict, d.created_at, "
        "COALESCE(dm.sections, '[]'::jsonb) AS sections "
        "FROM deals d "
        "LEFT JOIN deal_memos dm ON dm.deal_id = d.id "
        "WHERE d.created_at >= :start AND d.created_at < :end_date "
        "ORDER BY d.created_at DESC",
        {"start": start, "end_date": end + timedelta(days=1)},
    )
    results = []
    for r in rows:
        sections = r[7] if len(r) > 7 else []
        memo_text = ""
        if sections and isinstance(sections, list) and sections:
            memo_text = str(sections[0])[:200]
        results.append({
            "deal_id": str(r[0]),
            "deal_name": r[1],
            "survey_no": r[2],
            "deal_type": r[3],
            "irr_base_pct": float(r[4]) if r[4] is not None else None,
            "board_verdict": r[5] or "UNKNOWN",
            "deal_memo_summary": memo_text,
            "shareholder_verdicts": None,
            "source": "deal",
            "created_at": r[6].isoformat() if r[6] else None,
            "_created_ts": r[6],
        })
    return results


def _infer_verdict(synthesis: str) -> str:
    """Infer board verdict from CEO synthesis text using keyword matching."""
    s = synthesis.lower()
    if any(w in s for w in ["no-go", "reject", "decline", "pass"]):
        return "NO-GO"
    if any(w in s for w in ["conditional", "subject to", "pending"]):
        return "CONDITIONAL"
    if any(w in s for w in ["go", "approved", "proceed", "recommend"]):
        return "GO"
    return "UNKNOWN"


class DecisionAuditor:
    """Audits past board decisions for quarterly review."""

    @staticmethod
    def audit_quarter(quarter: str) -> list[dict[str, Any]]:
        """Returns all decisions in the quarter, sorted by date DESC."""
        start, end = parse_quarter(quarter)
        combined = _board_decisions(start, end) + _deal_decisions(start, end)
        combined.sort(
            key=lambda x: x.get("_created_ts") or "",
            reverse=True,
        )
        for d in combined:
            d.pop("_created_ts", None)
        return combined

    @staticmethod
    def get_contested(quarter: str) -> list[dict[str, Any]]:
        """Returns decisions with split shareholder verdicts."""
        decisions = DecisionAuditor.audit_quarter(quarter)
        contested = []
        for d in decisions:
            sv = d.get("shareholder_verdicts")
            if sv and isinstance(sv, list) and len(sv) >= 2:
                has_go = any(v.get("verdict") == "GO" for v in sv)
                has_nogo = any(v.get("verdict") == "NO-GO" for v in sv)
                if has_go and has_nogo:
                    contested.append(d)
        return contested
