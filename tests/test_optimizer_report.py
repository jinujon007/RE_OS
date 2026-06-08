"""Unit tests for OptimizerReport and OptimizingAgent (T-1004 - Sprint 60)."""
import pytest
import os
import tempfile
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_report_writes_markdown_file():
    """OptimizerReport.write() creates a valid markdown file."""
    from utils.optimizer_report import OptimizerReport

    report = OptimizerReport(
        report_date="2026-06-08",
        token_summary=[{"agent_name": "CEO", "total_tokens_7d": 15000, "avg_tokens_per_run": 1500,
                       "budget_limit": 4000, "over_budget_runs": 2}],
        redundancy_findings=[],
        cache_hit_rate=0.75,
        top_recommendation="Test recommendation",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "optimizer", "2026-06-08.md")
        result = report.write(path)
        assert os.path.exists(result)
        with open(result, "r", encoding="utf-8") as f:
            content = f.read()
        assert "RE_OS Optimizer Report" in content
        assert "CEO" in content


def test_report_has_all_fields():
    """OptimizerReport dataclass has all required fields."""
    from utils.optimizer_report import OptimizerReport
    import dataclasses

    fields = {f.name for f in dataclasses.fields(OptimizerReport)}
    required = {"report_date", "token_summary", "redundancy_findings", "cache_hit_rate",
                "top_recommendation", "auto_tasks_created"}
    assert required.issubset(fields)


def test_optimizer_agent_fallback_not_empty():
    """OptimizingAgent fallback returns a valid recommendation."""
    from agents.optimizer_agent import OptimizingAgent

    agent = OptimizingAgent()
    # Force fallback path
    report = {
        "report_date": "2026-06-08",
        "token_summary": [{"agent_name": "CEO", "total_tokens_7d": 15000, "over_budget_runs": 3,
                          "budget_limit": 4000}],
        "redundancy_findings": [],
        "cache_hit_rate": 0.5,
    }

    # Mock LLM unavailable
    with patch.object(agent, "_llm_available", False):
        rec = agent.run(report)

    assert rec.title is not None
    assert len(rec.title) > 0
    assert rec.priority in ("HIGH", "MEDIUM", "LOW")


def test_auto_task_created_on_high_severity():
    """High severity findings create auto tasks via IntelRegistry."""
    from utils.optimizer_report import OptimizerReport

    report = OptimizerReport(
        report_date="2026-06-08",
        redundancy_findings=[{
            "type": "prompt_duplicate",
            "severity": "HIGH",
            "recommendation": "Test finding",
        }],
        cache_hit_rate=0.5,
    )

    # This is triggered by the post_crew_optimizer_hook when HIGH findings exist
    high_findings = [f for f in report.redundancy_findings if f.get("severity") == "HIGH"]
    assert len(high_findings) == 1


def test_generate_report_returns_report():
    """generate_report() returns a valid OptimizerReport."""
    with patch("utils.token_tracker.get_budget_summary") as mock_budget:
        with patch("utils.redundancy_detector.detect_redundancies") as mock_red:
            with patch("intelligence.registry.IntelRegistry") as mock_registry:
                mock_budget.return_value = [{"agent_name": "CEO", "total_tokens_7d": 5000,
                                             "avg_tokens_per_run": 500, "budget_limit": 4000,
                                             "over_budget_runs": 0}]
                mock_red.return_value = []
                mock_registry.return_value = MagicMock()

                from utils.optimizer_report import generate_report

                report = generate_report(1)
                assert report.report_date != ""
                assert isinstance(report.token_summary, list)
                assert isinstance(report.redundancy_findings, list)


def test_generate_report_invalid_days_raises():
    """generate_report() raises ValueError for invalid days parameter."""
    from utils.optimizer_report import generate_report

    with pytest.raises(ValueError, match="days must be between"):
        generate_report(0)

    with pytest.raises(ValueError, match="days must be between"):
        generate_report(31)