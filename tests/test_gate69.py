"""GATE-69 declaration — Sprint 61 Process Automation."""
import json
import pytest
from pathlib import Path
from utils.log_analyzer import PipelineRunAnalyzer
from agents.log_analyst_agent import LogAnalystAgent
from agents.efficiency_optimizer_agent import EfficiencyOptimizerAgent
from agents.runbook_documenter_agent import RunbookDocumenterAgent
from starlette.testclient import TestClient
from dashboard.app_fastapi import app

pytestmark = pytest.mark.unit
client = TestClient(app)
_TEST_KEY = "test-api-key"


def _write_runs(path: Path, runs: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in runs:
            f.write(json.dumps(r) + "\n")


def test_bottleneck_detected_from_10_runs(tmp_path):
    """(1) Seed 10 runs with stage1 > 2× stage2 → find_bottleneck returns scraping."""
    runs = [
        {"run_id": f"r{i}", "market": "A", "start_time": f"2026-01-{i+1:02d}T00:00:00",
         "duration_seconds": 100.0, "status": "success", "agents_completed": ["scraper"]}
        for i in range(10)
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    bn = ana.find_bottleneck(10)
    assert bn is not None, "Bottleneck should be detected from 10 scraping-heavy runs"
    assert bn["bottleneck"] == "scraping", f"Expected 'scraping', got {bn['bottleneck']}"


def test_log_analyst_top_finding_non_empty(tmp_path):
    """(2) LogAnalystAgent returns BottleneckReport with top_finding non-empty."""
    runs = [
        {"run_id": f"r{i}", "market": "A", "start_time": f"2026-01-{i+1:02d}T00:00:00",
         "duration_seconds": 100.0, "status": "success", "agents_completed": ["scraper"]}
        for i in range(15)
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    agent = LogAnalystAgent(analyzer=ana)
    result = agent.run()
    assert result["status"] == "done"
    assert result["report"]["top_finding"], "top_finding must be non-empty"


def test_efficiency_optimizer_returns_priority(tmp_path):
    """(3) EfficiencyOptimizer returns ImprovementProposal with valid priority."""
    report = {
        "bottleneck_stage": "scraping",
        "bottleneck_reason": "Stage1 avg 65s is 2x Stage2",
        "avg_stage1_s": 65.0,
        "avg_stage2_s": 25.0,
        "avg_stage3_s": 10.0,
        "failure_rate_pct": 5.0,
        "top_finding": "Bottleneck: scraping",
        "recommendation": "Add rate-limit backoff",
    }
    agent = EfficiencyOptimizerAgent()
    result = agent.run(bottleneck_report=report)
    assert result["status"] == "done"
    assert result["proposal"]["priority"] in ("HIGH", "MEDIUM", "LOW")


def test_runbook_documenter_creates_file(tmp_path, monkeypatch):
    """(4) RunbookDocumenter creates file in docs/solutions/process-automation/."""
    monkeypatch.setattr("agents.runbook_documenter_agent._SOLUTIONS_DIR", tmp_path)
    agent = RunbookDocumenterAgent()
    result = agent.run(
        bottleneck_report={
            "bottleneck_stage": "scraping",
            "bottleneck_reason": "Reason",
            "recommendation": "Fix it",
        },
        improvement_proposal={
            "title": "Test proposal",
            "description": "Test description",
            "target_file": "test.py",
            "priority": "HIGH",
            "estimated_token_saving_pct": 30.0,
        },
    )
    assert result["status"] == "done"
    path = Path(result["path"])
    assert path.exists(), f"Runbook file should exist: {path}"


def test_process_audit_panel_returns_200():
    """(5) GET /process-audit returns 200."""
    resp = client.get("/process-audit", headers={"X-API-Key": _TEST_KEY})
    assert resp.status_code == 200
