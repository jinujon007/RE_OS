"""
RE_OS — Token Usage Tracker (Phase 9 - Sprint 60)
Per-agent token budget tracking with database persistence.
"""
import hashlib
from typing import Any

from sqlalchemy import text as _sa_text

from utils.db import get_engine
from config.settings import TOKEN_BUDGETS

__all__ = ["TokenUsageTracker", "record", "get_budget_summary", "compute_task_hash"]


def _get_budget_for_agent(agent_name: str) -> int:
    """Get token budget for an agent, defaulting to 2000 if unknown."""
    return TOKEN_BUDGETS.get(agent_name, 2000)


def record(agent_name: str, tokens_used: int, model: str, run_id: str) -> str:
    """Record token usage for an agent run. Returns the usage record ID."""
    engine = get_engine()
    budget_limit = _get_budget_for_agent(agent_name)
    with engine.begin() as conn:
        result = conn.execute(
            _sa_text("""
                INSERT INTO token_usage (agent_name, model, tokens_used, budget_limit, run_id, recorded_at)
                VALUES (:agent_name, :model, :tokens_used, :budget_limit, :run_id, NOW())
                ON CONFLICT (run_id) DO UPDATE SET
                    tokens_used = EXCLUDED.tokens_used,
                    budget_limit = EXCLUDED.budget_limit,
                    recorded_at = NOW()
                RETURNING id
            """),
            {
                "agent_name": agent_name,
                "model": model,
                "tokens_used": tokens_used,
                "budget_limit": budget_limit,
                "run_id": str(run_id),
            },
        )
        record_id = str(result.fetchone()[0])
    return record_id


def get_budget_summary(days: int = 7) -> list[dict[str, Any]]:
    """Get token budget summary for all agents in the last N days."""
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            _sa_text("""
                SELECT agent_name,
                       SUM(tokens_used) AS total_tokens,
                       COUNT(*) AS run_count,
                       AVG(tokens_used) AS avg_tokens,
                       MAX(budget_limit) AS budget_limit,
                       COUNT(CASE WHEN over_budget THEN 1 END) AS over_budget_runs
                FROM token_usage
                WHERE recorded_at >= NOW() - INTERVAL '1 day' * :days
                GROUP BY agent_name
                ORDER BY over_budget_runs DESC NULLS LAST
            """),
            {"days": days},
        ).fetchall()
    result = []
    for r in rows:
        agent = r[0]
        total = r[1] or 0
        runs = r[2] or 0
        avg = r[3] or 0
        budget = r[4] or 2000
        over = r[5] or 0
        pct = round(over / runs * 100, 1) if runs > 0 else 0.0
        result.append({
            "agent_name": agent,
            "total_tokens_7d": int(total),
            "avg_tokens_per_run": round(avg, 1),
            "budget_limit": int(budget),
            "over_budget_runs": int(over),
            "over_budget_pct": pct,
        })
    return result


def compute_task_hash(task: str) -> str:
    """Compute SHA256 hash of task (first 500 chars) for dedup detection."""
    return hashlib.sha256(task[:500].encode("utf-8")).hexdigest()


class TokenUsageTracker:
    """Per-agent token budget tracking class."""

    def __init__(self):
        self.engine = get_engine()

    def record_usage(
        self,
        agent_name: str,
        tokens_used: int,
        model: str = "unknown",
        run_id: str = "",
    ) -> str:
        """Record token usage for an agent."""
        return record(agent_name, tokens_used, model, run_id)

    def get_summary(self, days: int = 7) -> list[dict[str, Any]]:
        """Get budget summary for all agents."""
        return get_budget_summary(days)