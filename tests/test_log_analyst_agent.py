"""T-1008 — LogAnalystAgent unit tests."""

import json
import pytest
from pathlib import Path
from utils.log_analyzer import PipelineRunAnalyzer
from agents.log_analyst_agent import (
    LogAnalystAgent, BottleneckReport,
    StageDurationTool, FailureRateTool, BottleneckFinderTool,
)

pytestmark = pytest.mark.unit


def _write_runs(path: Path, runs: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in runs:
            f.write(json.dumps(r) + "\n")


def test_log_analyst_returns_bottleneck_report(tmp_path):
    runs = [
        {"run_id": f"r{i}", "market": "A", "start_time": f"2026-01-{i+1:02d}T00:00:00",
         "duration_seconds": 100.0, "status": "success", "agents_completed": ["x"]}
        for i in range(15)
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    agent = LogAnalystAgent(analyzer=ana)
    result = agent.run()
    assert result["status"] == "done"
    report = result["report"]
    assert isinstance(report, dict)
    assert "report_date" in report
    assert "bottleneck_stage" in report
    assert "report_id" in report


def test_fallback_when_insufficient_runs(tmp_path):
    runs = [
        {"run_id": "r1", "start_time": "2026-01-01T00:00:00",
         "duration_seconds": 50.0, "status": "success", "agents_completed": ["a", "b"]}
        for _ in range(3)
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    agent = LogAnalystAgent(analyzer=ana)
    result = agent.run()
    report = result["report"]
    assert "Insufficient run history" in report["top_finding"]
    assert report["recommendation"]


def test_report_has_all_fields(tmp_path):
    runs = [
        {"run_id": f"r{i}", "market": "A", "start_time": f"2026-01-{i+1:02d}T00:00:00",
         "duration_seconds": 60.0, "status": "success", "agents_completed": ["a", "b", "c"]}
        for i in range(12)
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    agent = LogAnalystAgent(analyzer=ana)
    result = agent.run()
    fields = ["report_date", "bottleneck_stage", "bottleneck_reason",
              "avg_stage1_s", "avg_stage2_s", "avg_stage3_s",
              "failure_rate_pct", "top_finding", "recommendation"]
    for f in fields:
        assert f in result["report"], f"Missing field: {f}"


def test_top_finding_non_empty(tmp_path):
    runs = [
        {"run_id": f"r{i}", "market": "A", "start_time": f"2026-01-{i+1:02d}T00:00:00",
         "duration_seconds": 80.0, "status": "success", "agents_completed": ["x"]}
        for i in range(15)
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    agent = LogAnalystAgent(analyzer=ana)
    result = agent.run()
    assert result["report"]["top_finding"], "top_finding should not be empty"


def test_stage_duration_tool(tmp_path):
    runs = [
        {"run_id": "r1", "start_time": "2026-01-01T00:00:00",
         "duration_seconds": 90.0, "status": "success", "agents_completed": ["a"]}
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    tool = StageDurationTool(ana)
    out = tool.run(5)
    assert "stage1_duration_s" in out


def test_failure_rate_tool(tmp_path):
    runs = [
        {"run_id": f"r{i}", "status": "success" if i < 3 else "failed"}
        for i in range(5)
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    tool = FailureRateTool(ana)
    out = json.loads(tool.run(10))
    assert out["total"] == 5
    assert out["failed"] == 2


def test_bottleneck_report_empty_sentinel():
    empty = BottleneckReport.empty()
    assert empty.report_id
    assert empty.top_finding == "Insufficient data to generate report."
    assert empty.bottleneck_stage == "none"


def test_safe_extract_json_valid():
    from utils.process_automation import safe_extract_json
    result = safe_extract_json('{"top_finding": "test"}')
    assert result is not None
    assert result["top_finding"] == "test"


def test_safe_extract_json_invalid():
    from utils.process_automation import safe_extract_json
    assert safe_extract_json("not json") is None
    assert safe_extract_json("") is None


def test_safe_extract_json_embedded():
    from utils.process_automation import safe_extract_json
    raw = "Some text before ```json{\"key\": \"val\"}``` after"
    result = safe_extract_json(raw)
    assert result is not None
    assert result["key"] == "val"


def test_bottleneck_finder_tool(tmp_path):
    runs = [
        {"run_id": f"r{i}", "market": "A", "start_time": f"2026-01-{i+1:02d}T00:00:00",
         "duration_seconds": 100.0, "status": "success", "agents_completed": ["x"]}
        for i in range(12)
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    tool = BottleneckFinderTool(ana)
    out = json.loads(tool.run(10))
    assert out.get("bottleneck") == "scraping"
