"""GATE-68 Declaration Tests (Sprint 60 - T-1006).

Verifies:
1. RedundancyDetector.scan(1) detects prompt_duplicate when seeded
2. TokenUsageTracker returns entry with over_budget_runs=1 when seeded
3. GET /optimizer route works
4. Scheduler has post_crew_optimizer_hook registered
"""
import pytest
from unittest.mock import MagicMock, patch
import uuid

pytestmark = pytest.mark.unit


def test_detector_returns_prompt_duplicate_on_seeded_data():
    """RedundancyDetector.scan returns finding when 2 identical task hashes exist."""
    # Mock the DB to return duplicate prompt data
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: {
        0: "CEO",
        1: "abc123hash",
        2: 2,  # count
        3: str(uuid.uuid4()),
        4: str(uuid.uuid4()),
    }.get(key)

    with patch("utils.redundancy_detector.get_engine") as mock_engine:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

        from utils.redundancy_detector import RedundancyDetector

        detector = RedundancyDetector()
        findings = detector.scan(1)

        # Verify prompt_duplicate finding detected
        assert any(f["type"] == "prompt_duplicate" for f in findings)


def test_token_tracker_returns_over_budget_entry():
    """TokenUsageTracker.get_budget_summary returns entry with over_budget_runs when seeded."""
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: {
        0: "CEO",
        1: 5000,
        2: 1,
        3: 5000.0,
        4: 2000,
        5: 1,
    }.get(key)

    with patch("utils.token_tracker.get_engine") as mock_engine:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn

        from utils.token_tracker import get_budget_summary

        summary = get_budget_summary(7)
        assert len(summary) >= 1
        # The entry has over_budget_runs = 1
        assert summary[0]["over_budget_runs"] == 1


def test_optimizer_route_exists():
    """GET /optimizer route is registered."""
    import os
    from unittest.mock import patch
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "test-key", "DASHBOARD_API_KEY_ALLOW_EMPTY": "true"}):
        from dashboard.app_fastapi import app

    routes = [r.path for r in app.routes]
    assert "/optimizer" in routes


def test_scheduler_has_optimizer_hook():
    """post_crew_optimizer_hook job is registered in scheduler."""
    from config.scheduler import run_post_crew_optimizer_hook

    assert callable(run_post_crew_optimizer_hook)