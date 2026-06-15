"""T-1009 — EfficiencyOptimizerAgent unit tests."""

import pytest
from agents.efficiency_optimizer_agent import (
    EfficiencyOptimizerAgent,
    ImprovementProposal,
    _fallback_proposal,
    _auto_create_task,
)
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


def test_proposal_has_all_fields():
    p = ImprovementProposal(
        proposal_id="test-id",
        title="Test improvement",
        description="A test description for the proposal",
        target_file="utils/test.py",
        priority="HIGH",
        estimated_token_saving_pct=25.0,
        confidence=0.8,
    )
    d = p.to_dict()
    assert d["proposal_id"] == "test-id"
    assert d["title"] == "Test improvement"
    assert d["target_file"] == "utils/test.py"
    assert d["priority"] == "HIGH"
    assert isinstance(d["estimated_token_saving_pct"], float)
    assert isinstance(d["confidence"], float)


def test_priority_assignment():
    agent = EfficiencyOptimizerAgent()
    result = agent.run(
        bottleneck_report={"bottleneck_stage": "scraping", "avg_stage1_s": 120.0},
    )
    assert result["status"] == "done"
    assert result["proposal"]["priority"] in ("HIGH", "MEDIUM", "LOW")


@pytest.mark.parametrize(
    "priority,expected_call",
    [
        ("HIGH", True),
        ("MEDIUM", True),
        ("LOW", False),
    ],
)
@patch("agents.efficiency_optimizer_agent._httpx")
def test_auto_task_created_on_medium_or_high(mock_httpx, priority, expected_call):
    mock_httpx.post.return_value = MagicMock(status_code=201)
    p = ImprovementProposal(
        proposal_id="test",
        title="Test",
        description="desc",
        target_file="f.py",
        priority=priority,
        estimated_token_saving_pct=10.0,
        confidence=0.7,
    )
    result = _auto_create_task(p)
    if expected_call:
        assert result is True
        mock_httpx.post.assert_called_once()
    else:
        assert result is False
        mock_httpx.post.assert_not_called()


def test_fallback_not_empty():
    p = _fallback_proposal()
    assert p.title
    assert p.description
    assert p.target_file
    assert p.priority == "LOW"
    assert p.confidence > 0


def test_scraping_bottleneck_proposal():
    agent = EfficiencyOptimizerAgent()
    result = agent.run(
        bottleneck_report={"bottleneck_stage": "scraping", "avg_stage1_s": 120.0},
    )
    assert result["proposal"]["priority"] == "HIGH"
    assert "scraping" in result["proposal"]["title"].lower()


def test_failure_rate_proposal():
    agent = EfficiencyOptimizerAgent()
    result = agent.run(
        bottleneck_report={
            "bottleneck_stage": "none",
            "failure_rate_pct": 35.0,
            "avg_stage3_s": 0.0,
        },
    )
    assert result["proposal"]["priority"] == "MEDIUM"
    assert (
        "failure" in result["proposal"]["title"].lower()
        or "investigate" in result["proposal"]["title"].lower()
    )
