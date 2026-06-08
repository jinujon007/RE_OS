"""T-1010 — RunbookDocumenterAgent unit tests."""

import pytest
from pathlib import Path
from agents.runbook_documenter_agent import RunbookDocumenterAgent, _resolve_path, _fallback_runbook

pytestmark = pytest.mark.unit


def test_runbook_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.runbook_documenter_agent._SOLUTIONS_DIR", tmp_path)
    agent = RunbookDocumenterAgent()
    result = agent.run(
        bottleneck_report={
            "bottleneck_stage": "scraping",
            "bottleneck_reason": "Stage1 is 2x Stage2",
            "recommendation": "Add rate-limit backoff",
        },
        improvement_proposal={
            "title": "Fix scraping",
            "description": "Add backoff to portal_scout.py",
            "target_file": "scrapers/portal_scout.py",
            "priority": "HIGH",
            "estimated_token_saving_pct": 0.0,
        },
    )
    assert result["status"] == "done"
    assert result["path"]
    path = Path(result["path"])
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "scraping" in content


def test_runbook_does_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.runbook_documenter_agent._SOLUTIONS_DIR", tmp_path)
    agent = RunbookDocumenterAgent()
    r1 = agent.run(bottleneck_report={"bottleneck_stage": "scraping", "bottleneck_reason": "x", "recommendation": "y"})
    r2 = agent.run(bottleneck_report={"bottleneck_stage": "scraping", "bottleneck_reason": "x", "recommendation": "y"})
    p1 = Path(r1["path"])
    p2 = Path(r2["path"])
    assert p1.exists()
    assert p2.exists()
    assert p1 != p2, "Should not overwrite — should create _v2 file"


def test_runbook_frontmatter_valid(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.runbook_documenter_agent._SOLUTIONS_DIR", tmp_path)
    agent = RunbookDocumenterAgent()
    result = agent.run(
        bottleneck_report={
            "bottleneck_stage": "llm_synthesis",
            "bottleneck_reason": "Stage3 exceeds Stage1+Stage2",
            "recommendation": "Cache LLM outputs",
        },
        improvement_proposal={
            "title": "Cache synthesis",
            "description": "Cache by survey_no+market hash",
            "target_file": "crews/evaluate_pipeline.py",
            "priority": "HIGH",
            "estimated_token_saving_pct": 60.0,
        },
    )
    content = Path(result["path"]).read_text(encoding="utf-8")
    assert "# Runbook" in content
    assert "Problem Type" in content
    assert "Tags" in content
    assert "Solution" in content


def test_resolve_path_creates_v2(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.runbook_documenter_agent._SOLUTIONS_DIR", tmp_path)
    first = _resolve_path("2026-06-08", "test_stage")
    first.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("original")
    second = _resolve_path("2026-06-08", "test_stage")
    assert "_v2" in second.name
    assert second != first


def test_fallback_runbook_writes_content(tmp_path):
    path = tmp_path / "test_runbook.md"
    result = _fallback_runbook(path, {"bottleneck_stage": "test", "bottleneck_reason": "reason", "recommendation": "fix it"})
    assert result == path
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "test" in content
