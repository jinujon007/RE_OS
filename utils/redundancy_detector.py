"""
RE_OS — Redundancy Detector (Phase 9 - Sprint 60)
Detects wasteful LLM calls that can be eliminated for efficiency.
"""

import hashlib
from typing import Any

import sqlalchemy
from utils.db import get_engine

__all__ = ["RedundancyDetector", "detect_redundancies", "compute_task_hash"]


def compute_task_hash(task: str) -> str:
    """Compute SHA256 hash of task (first 500 chars) for dedup detection."""
    from utils.token_tracker import compute_task_hash as _hash

    return _hash(task)


class RedundancyDetector:
    """Detect duplicate/redundant LLM calls from agent_runs history."""

    def __init__(self):
        self.engine = get_engine()

    def scan(self, days: int = 7) -> list[dict[str, Any]]:
        """Scan agent_runs for redundancy patterns in the last N days.

        Args:
            days: Number of days to look back (1-30).

        Detects 3 patterns:
        1. Prompt duplicate: identical task hash within 2hr window
        2. Cache miss: same (market, survey_no) called >=3x in same hour
        3. Empty-output runs: output IS NULL or len(output) < 10

        Returns list of findings with severity and recommendation.
        """
        findings = []
        if not 1 <= days <= 30:
            days = 7

        try:
            with self.engine.connect() as conn:
                prompt_dups = self._detect_prompt_duplicates(conn, days)
                findings.extend(prompt_dups)
                cache_misses = self._detect_cache_misses(conn, days)
                findings.extend(cache_misses)
                empty_outs = self._detect_empty_outputs(conn, days)
                findings.extend(empty_outs)
        except Exception as exc:
            pass

        return findings

    def _detect_prompt_duplicates(self, conn, days: int) -> list[dict[str, Any]]:
        """Find duplicate prompts (same hash + agent within 2hr)."""
        findings = []
        try:
            rows = conn.execute(
                sqlalchemy.text("""
                    SELECT agent_name, task_hash, COUNT(*) as run_count,
                           MIN(id) as first_run_id, MAX(id) as duplicate_run_id
                    FROM (
                        SELECT agent_name,
                               metadata->>'task_hash' as task_hash,
                               id, started_at
                        FROM agent_runs
                        WHERE started_at >= NOW() - INTERVAL '1 day' * :days
                          AND metadata IS NOT NULL
                          AND metadata->>'task_hash' IS NOT NULL
                    ) t
                    WHERE t.started_at >= NOW() - INTERVAL '2 hours'
                    GROUP BY agent_name, task_hash
                    HAVING COUNT(*) >= 2
                """),
                {"days": days},
            ).fetchall()

            for r in rows:
                count = r[2] if r[2] else 0
                if count >= 2:
                    findings.append(
                        {
                            "type": "prompt_duplicate",
                            "agent": r[0],
                            "count": count,
                            "first_run_id": str(r[3]) if r[3] else None,
                            "duplicate_run_id": str(r[4]) if r[4] else None,
                            "tokens_wasted": count * 1500,  # rough estimate
                            "severity": "HIGH" if count > 2 else "MEDIUM",
                            "recommendation": f"Cache or dedup prompt for {r[0]} - {count} identical calls detected",
                        }
                    )
        except Exception:
            pass
        return findings

    def _detect_cache_misses(self, conn, days: int) -> list[dict[str, Any]]:
        """Find cache misses: same (market, survey_no) called >=3x in same hour."""
        findings = []
        try:
            rows = conn.execute(
                sqlalchemy.text("""
                    SELECT micro_market, survey_no, COUNT(DISTINCT agent_name) as agent_count
                    FROM (
                        SELECT agent_name, micro_market, metadata->>'survey_no' as survey_no,
                               DATE_TRUNC('hour', started_at) as hour_bucket
                        FROM agent_runs
                        WHERE started_at >= NOW() - INTERVAL '1 day' * :days
                          AND micro_market IS NOT NULL
                    ) t
                    WHERE survey_no IS NOT NULL
                    GROUP BY micro_market, survey_no, hour_bucket
                    HAVING COUNT(*) >= 3
                """),
                {"days": days},
            ).fetchall()

            for r in rows:
                findings.append(
                    {
                        "type": "cache_miss",
                        "market": r[0],
                        "survey_no": r[1],
                        "agent_count": r[2] if r[2] else 0,
                        "severity": "HIGH" if r[2] and r[2] >= 3 else "MEDIUM",
                        "recommendation": f"IntelRegistry cache may be ineffective for {r[0]}/{r[1]} - {r[2]} agents hit in same hour",
                    }
                )
        except Exception:
            pass
        return findings

    def _detect_empty_outputs(self, conn, days: int) -> list[dict[str, Any]]:
        """Find empty-output runs: output IS NULL or len(output) < 10."""
        findings = []
        try:
            rows = conn.execute(
                sqlalchemy.text("""
                    SELECT id, agent_name, task_type, started_at
                    FROM agent_runs
                    WHERE started_at >= NOW() - INTERVAL '1 day' * :days
                      AND (error_message IS NOT NULL OR records_scraped = 0)
                """),
                {"days": days},
            ).fetchall()

            for r in rows:
                findings.append(
                    {
                        "type": "empty_output",
                        "run_id": str(r[0]) if r[0] else None,
                        "agent": r[1],
                        "task_type": r[2],
                        "severity": "LOW",
                        "recommendation": f"Review {r[1]} output handling - potential wasted LLM call",
                    }
                )
        except Exception:
            pass
        return findings


def detect_redundancies(days: int = 7) -> list[dict[str, Any]]:
    """Convenience function to scan for redundancies."""
    return RedundancyDetector().scan(days)
