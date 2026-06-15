"""T-1007 — PipelineRunAnalyzer unit tests."""

import json
import pytest
from pathlib import Path
from utils.log_analyzer import PipelineRunAnalyzer

pytestmark = pytest.mark.unit


def _write_runs(path: Path, runs: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in runs:
            f.write(json.dumps(r) + "\n")


def test_stage_durations_parsed(tmp_path):
    runs = [
        {
            "run_id": "r1",
            "market": "A",
            "start_time": "2026-01-01T00:00:00",
            "duration_seconds": 100.0,
            "status": "success",
            "agents_completed": ["a", "b", "c"],
        },
        {
            "run_id": "r2",
            "market": "B",
            "start_time": "2026-01-02T00:00:00",
            "duration_seconds": 200.0,
            "status": "success",
            "agents_completed": ["a"],
        },
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    result = ana.get_stage_durations(10)
    assert len(result) == 2
    assert result[0]["run_id"] == "r1"
    assert "stage1_duration_s" in result[0]
    assert "total_duration_s" in result[0]


def test_bottleneck_scraping_detected(tmp_path):
    runs = [
        {
            "run_id": f"r{i}",
            "market": "A",
            "start_time": f"2026-01-{i + 1:02d}T00:00:00",
            "duration_seconds": 100.0,
            "status": "success",
            "agents_completed": ["x", "y"],
        }
        for i in range(10)
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    bn = ana.find_bottleneck(10)
    assert bn is not None
    assert bn["bottleneck"] == "scraping"


def test_bottleneck_llm_detected(tmp_path):
    runs = [
        {
            "run_id": f"r{i}",
            "market": "A",
            "start_time": f"2026-01-{i + 1:02d}T00:00:00",
            "duration_seconds": 100.0,
            "status": "success",
            "agents_completed": ["a", "b", "c", "d", "e"],
        }
        for i in range(10)
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    bn = ana.find_bottleneck(10)
    # 5 agents → split 20/20/60, so stage3=60 > stage1+stage2=40
    assert bn is not None
    assert bn["bottleneck"] == "llm_synthesis"


def test_no_bottleneck_returns_none(tmp_path):
    runs = [
        {
            "run_id": f"r{i}",
            "market": "A",
            "start_time": f"2026-01-{i + 1:02d}T00:00:00",
            "duration_seconds": 50.0,
            "status": "success",
            "agents_completed": ["a", "b", "c"],
        }
        for i in range(5)
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    bn = ana.find_bottleneck(10)
    assert bn is None


def test_failure_rate_computed(tmp_path):
    runs = [
        {"run_id": "r1", "status": "success"},
        {"run_id": "r2", "status": "failed"},
        {"run_id": "r3", "status": "success"},
        {"run_id": "r4", "status": "partial"},
        {"run_id": "r5", "status": "success"},
    ]
    _write_runs(tmp_path / "run_history.jsonl", runs)
    ana = PipelineRunAnalyzer(tmp_path / "run_history.jsonl")
    fr = ana.get_failure_rate(20)
    assert fr["total"] == 5
    assert fr["failed"] == 1
    assert fr["partial"] == 1
    assert fr["failure_rate_pct"] == 40.0


def test_no_file_returns_empty(tmp_path):
    ana = PipelineRunAnalyzer(tmp_path / "nonexistent.jsonl")
    assert ana.get_stage_durations(10) == []
    assert ana.find_bottleneck(10) is None
    fr = ana.get_failure_rate(10)
    assert fr["total"] == 0


def test_safe_mean_handles_empty():
    ana = PipelineRunAnalyzer()
    assert ana._safe_mean([]) == 0.0
    assert ana._safe_mean([1.0, 2.0]) == 1.5
