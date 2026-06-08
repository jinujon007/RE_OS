"""
RE_OS — Optimizing Agent (Phase 9 - Sprint 60)
Analyzes optimizer report and generates recommendations.
"""
from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = ["ImprovingRecommendation", "OptimizingAgent"]


@dataclass
class ImprovingRecommendation:
    """Output of the Optimizing Agent."""

    proposal_id: str
    title: str
    description: str
    target_file: str
    priority: str  # HIGH, MEDIUM, LOW
    estimated_token_saving_pct: float
    confidence: float


class OptimizingAgent:
    """Analyzes optimizer reports and produces improvement recommendations.

    Uses ANALYSIS LLM tier for synthesis. Falls back to rule-based recommendation
    if LLM unavailable.
    """

    _LLM_TIMEOUT_S = 30

    def __init__(self):
        self._llm_available = self._check_llm_available()

    def _check_llm_available(self) -> bool:
        try:
            from config.llm_router import get_analysis_llm
            return True
        except Exception:
            return False

    def _build_system_prompt(self) -> str:
        return (
            "You are the Tech Engineering Optimizer for RE_OS. Your role is to analyze "
            "the optimizer report and identify the single highest-impact improvement that "
            "would save the most compute resources. Focus on concrete code changes that "
            "reduce token waste, improve cache hit rates, or eliminate redundant calls. "
            "Recommend specific file + line locations where possible.\n\n"
            "Output a JSON object with keys: title (≤100 chars), description (200-500 words), "
            "target_file, priority (HIGH/MEDIUM/LOW), estimated_token_saving_pct (0-100), confidence (0-1)."
        )

    def _fallback_recommendation(self, report: dict[str, Any]) -> ImprovingRecommendation:
        """Rule-based fallback when LLM unavailable."""
        import uuid
        from datetime import datetime

        over_budget = [e for e in report.get("token_summary", []) if e.get("over_budget_runs", 0) > 0]
        if over_budget:
            agent = over_budget[0].get("agent_name", "unknown")
            over = over_budget[0].get("over_budget_runs", 0)
            return ImprovingRecommendation(
                proposal_id=str(uuid.uuid4()),
                title=f"Review token budget: {agent} over budget {over}x in last 7 days",
                description=f"Investigate {agent} agent token usage. {over} runs exceeded the budget limit. "
                           "Consider reducing prompt length, implementing caching for repeated queries, "
                           "or switching to a lighter LLM tier.",
                target_file="config/llm_router.py",
                priority="MEDIUM",
                estimated_token_saving_pct=15.0,
                confidence=0.6,
            )

        return ImprovingRecommendation(
            proposal_id=str(uuid.uuid4()),
            title="Review LLM token usage patterns",
            description="No over-budget agents detected, but regular monitoring recommended. "
                       "Check redundancy findings for optimization opportunities.",
            target_file="utils/optimizer_report.py",
            priority="LOW",
            estimated_token_saving_pct=5.0,
            confidence=0.5,
        )

    def run(self, report: dict[str, Any]) -> ImprovingRecommendation:
        """Analyze report and return top recommendation."""
        if not self._llm_available:
            return self._fallback_recommendation(report)

        try:
            from config.llm_router import get_analysis_llm
            import concurrent.futures
            import json
            import re

            llm = get_analysis_llm(temperature=0.2)

            # Build prompt with report summary
            summary_lines = []
            for entry in report.get("token_summary", [])[:3]:
                summary_lines.append(f"  - {entry.get('agent_name')}: {entry.get('total_tokens_7d', 0)} tokens, "
                                    f"{entry.get('over_budget_runs', 0)} over-budget")
            for finding in report.get("redundancy_findings", [])[:3]:
                summary_lines.append(f"  - {finding.get('type')}: {finding.get('recommendation', '')[:60]}")

            prompt = (
                f"Report date: {report.get('report_date')}\n"
                f"Cache hit rate: {report.get('cache_hit_rate', 0):.1%}\n"
                f"Key findings:\n" + "\n".join(summary_lines) + "\n\n"
                "Return the single highest-impact recommendation as JSON."
            )

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    llm.invoke,
                    [{"role": "system", "content": self._build_system_prompt()},
                     {"role": "user", "content": prompt}]
                )
                response = future.result(timeout=self._LLM_TIMEOUT_S)

            raw_text = ""
            if hasattr(response, "content"):
                raw_text = response.content
            elif isinstance(response, str):
                raw_text = response

            # Parse JSON
            try:
                data = json.loads(raw_text)
            except (json.JSONDecodeError, TypeError):
                # Try to extract JSON from response
                match = re.search(r"\{.*\}", raw_text, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                else:
                    return self._fallback_recommendation(report)

            return ImprovingRecommendation(
                proposal_id=data.get("proposal_id", ""),
                title=data.get("title", "")[:100],
                description=data.get("description", "")[:500],
                target_file=data.get("target_file", ""),
                priority=data.get("priority", "LOW")[:10],
                estimated_token_saving_pct=float(data.get("estimated_token_saving_pct", 0)),
                confidence=float(data.get("confidence", 0)),
            )

        except Exception:
            return self._fallback_recommendation(report)


if __name__ == "__main__":
    from utils.optimizer_report import generate_report

    report = generate_report(7)
    agent = OptimizingAgent()
    rec = agent.run(report.to_dict())
    print(f"Top recommendation: {rec.title}")
    print(f"Priority: {rec.priority}")
    print(f"Saving: {rec.estimated_token_saving_pct}%")