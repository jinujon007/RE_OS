"""KillCriteriaAuditor — automated kill-criteria checkpoint (GATE-102).

Three falsifiable criteria from V2 audit:
1. Deed throughput — AT_RISK if avg <10/week, TRIGGER if 4+ consecutive zero-deed weeks.
2. Corridor accuracy — TRIGGER if backtest verdict == FAIL.
3. Decision journal — TRIGGER if 0 entries by 2026-12-01.

Each method returns dict with unified ``status`` key.
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from prometheus_client import Counter
from sqlalchemy import text
from sqlalchemy.engine import Engine

from config.metrics import _counter
from utils.corridor_scorer_v2 import CorridorScorerV2

_KILL_CRITERIA_TOTAL = _counter(
    "kill_criteria_total",
    "Total kill-criteria evaluations by criterion and status",
    ["criterion", "status"],
)

_TRIGGER_DATE = date(2026, 12, 1)
_WEEK_WINDOW = 4
_MIN_DEED_WEEKLY = 10
_CONSECUTIVE_ZERO_TRIGGER = 4
_CORRELATION_THRESHOLD = 0.67


class KillCriteriaAuditor:
    """Evaluate all three kill criteria and return structured verdicts."""

    def __init__(self, engine: Engine | None = None):
        from utils.db import get_engine

        self._engine = engine or get_engine()

    # ── Shared ──────────────────────────────────────────────────────────────

    @staticmethod
    def compute_overall(results: list[dict[str, Any]]) -> str:
        """Aggregate individual criterion statuses into a single overall verdict.

        Rules:
        - Any TRIGGER → overall TRIGGER
        - Any AT_RISK or ERROR → overall AT_RISK
        - All OK → overall OK
        """
        statuses = [r["status"] for r in results]
        if "TRIGGER" in statuses:
            return "TRIGGER"
        if "AT_RISK" in statuses or "ERROR" in statuses:
            return "AT_RISK"
        return "OK"

    @staticmethod
    def _parse_decision_date(heading: str) -> str | None:
        """Extract date portion from a '## YYYY-MM-DD — title' heading.

        Handles both em-dash (U+2014) and hyphen-minus separators.
        """
        date_part = heading.replace("## ", "", 1).strip()
        EM_DASH = "\u2014"
        EN_DASH = "\u2013"
        for sep in (EM_DASH, EN_DASH, "-"):
            if sep in date_part:
                date_part = date_part.split(sep)[0].strip()
                break
        return date_part if date_part else None

    # ── 1. Deed throughput ──────────────────────────────────────────────────

    def check_deed_throughput(
        self, engine: Engine | None = None, as_of: date | None = None
    ) -> dict[str, Any]:
        engine = engine or self._engine
        as_of = as_of or date.today()
        since = as_of - timedelta(weeks=_WEEK_WINDOW)

        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT
                            date_trunc('week', reg_date)::date AS week_start,
                            COUNT(*)::int AS deeds
                        FROM registered_transactions
                        WHERE reg_date >= :since
                          AND reg_date <= :as_of
                        GROUP BY 1
                        ORDER BY 1
                    """),
                    {"since": since, "as_of": as_of},
                ).fetchall()
        except Exception as exc:
            verdict = f"DB query failed: {exc}"
            _KILL_CRITERIA_TOTAL.labels(criterion="deed_throughput", status="ERROR").inc()
            return _deed_result("ERROR", 0, 0.0, verdict)

        if not rows:
            verdict = "0 deeds in last 4 weeks — deed pipeline has stalled. Manual intervention required."
            _KILL_CRITERIA_TOTAL.labels(criterion="deed_throughput", status="TRIGGER").inc()
            return _deed_result("TRIGGER", 0, 0.0, verdict)

        weeks_with_data = len(rows)
        total_deeds = sum(r[1] for r in rows)
        avg = total_deeds / max(weeks_with_data, 1)

        # Consecutive zero-week detection: scan the sorted weekly rows for
        # a run of _CONSECUTIVE_ZERO_TRIGGER or more weeks with 0 deeds.
        consecutive_zero_run = 0
        max_consecutive_zero = 0
        for r in rows:
            if r[1] == 0:
                consecutive_zero_run += 1
                if consecutive_zero_run > max_consecutive_zero:
                    max_consecutive_zero = consecutive_zero_run
            else:
                consecutive_zero_run = 0

        if max_consecutive_zero >= _CONSECUTIVE_ZERO_TRIGGER:
            status = "TRIGGER"
            verdict = (
                f"{max_consecutive_zero} consecutive weeks with 0 new deeds. "
                "Deed pipeline has stalled — manual intervention required."
            )
        elif avg < _MIN_DEED_WEEKLY:
            status = "AT_RISK"
            verdict = (
                f"Avg {avg:.1f} deeds/week over {weeks_with_data} weeks — "
                f"below {_MIN_DEED_WEEKLY}/week threshold. "
                "Monitor deed ingestion velocity."
            )
        else:
            status = "OK"
            verdict = (
                f"Avg {avg:.1f} deeds/week over {weeks_with_data} weeks — "
                f"above {_MIN_DEED_WEEKLY}/week threshold."
            )

        _KILL_CRITERIA_TOTAL.labels(criterion="deed_throughput", status=status).inc()
        return _deed_result(status, weeks_with_data, round(avg, 1), verdict)

    # ── 2. Corridor accuracy ────────────────────────────────────────────────

    def check_corridor_accuracy(
        self, engine: Engine | None = None
    ) -> dict[str, Any]:
        engine = engine or self._engine
        try:
            scorer = CorridorScorerV2(engine)
            bt = scorer.backtest()
            verdict = bt.get("verdict", "INSUFFICIENT_DATA")
            tau_proxy = bt.get("rank_correlation")
            accuracy_note = bt.get("accuracy_note") or ""
            notes = [accuracy_note] if accuracy_note else []

            if verdict == "FAIL":
                status = "TRIGGER"
            elif verdict == "PASS":
                status = "OK"
            else:
                status = "INSUFFICIENT_DATA"

            _KILL_CRITERIA_TOTAL.labels(criterion="corridor_accuracy", status=status).inc()
            return _corridor_result(status, verdict, tau_proxy, notes)
        except Exception as exc:
            _KILL_CRITERIA_TOTAL.labels(criterion="corridor_accuracy", status="ERROR").inc()
            return _corridor_result(
                "ERROR", "EXCEPTION", None, [f"CorridorScorerV2.backtest() raised: {exc}"]
            )

    # ── 3. Decision journal ─────────────────────────────────────────────────

    def check_decision_journal(
        self, journal_path: str | Path | None = None
    ) -> dict[str, Any]:
        path = Path(journal_path) if journal_path else Path("docs/decision_journal.md")
        if not path.exists():
            _KILL_CRITERIA_TOTAL.labels(criterion="decision_journal", status="TRIGGER").inc()
            return _journal_result("TRIGGER", 0, None, f"Decision journal not found at {path}.")

        text_content = path.read_text(encoding="utf-8")
        entries_section = text_content.split("## Entries")[-1] if "## Entries" in text_content else ""

        entry_count = 0
        last_entry_date: str | None = None
        for line in entries_section.splitlines():
            stripped = line.strip()
            if stripped.startswith("## ") and not stripped.startswith("## Entries"):
                entry_count += 1
                parsed = self._parse_decision_date(stripped)
                if parsed:
                    last_entry_date = parsed

        today = date.today()
        if entry_count == 0 and today >= _TRIGGER_DATE:
            status = "TRIGGER"
            verdict = (
                "0 entries by 2026-12-01 — product hypothesis fails. "
                "RE_OS is intelligence theatre, not an intelligence product."
            )
        elif entry_count == 0:
            status = "OK"
            verdict = "0 entries but before 2026-12-01 deadline."
        else:
            status = "OK"
            verdict = f"{entry_count} entries logged. Last entry: {last_entry_date or 'unknown'}."

        _KILL_CRITERIA_TOTAL.labels(criterion="decision_journal", status=status).inc()
        return _journal_result(status, entry_count, last_entry_date, verdict)


# ── Factory helpers for return dicts ─────────────────────────────────────────


def _deed_result(
    status: str, weeks_with_data: int, avg_deeds_per_week: float, verdict: str
) -> dict[str, Any]:
    return {
        "status": status,
        "weeks_with_data": weeks_with_data,
        "avg_deeds_per_week": avg_deeds_per_week,
        "verdict": verdict,
    }


def _corridor_result(
    status: str,
    verdict: str,
    tau_proxy: float | None,
    notes: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "verdict": verdict,
        "tau_proxy": tau_proxy,
        "notes": notes,
    }


def _journal_result(
    status: str, entry_count: int, last_entry_date: str | None, verdict: str
) -> dict[str, Any]:
    return {
        "status": status,
        "entry_count": entry_count,
        "last_entry_date": last_entry_date,
        "verdict": verdict,
    }
