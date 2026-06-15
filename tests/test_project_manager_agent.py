"""Unit tests for ProjectManagerAgent (T-994)."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestProjectStatusReport:
    def test_status_report_returns_keys(self):
        from agents.project_manager_agent import _get_project_status

        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.side_effect = [
                MagicMock(fetchone=lambda: ("p1", "Test Project", "lead", None)),
                MagicMock(fetchall=lambda: [("todo", 3), ("done", 1)]),
                MagicMock(scalar=lambda: 1),
                MagicMock(fetchone=lambda: None),
            ]
            report = _get_project_status("p1")
        assert report.project_id == "p1"
        assert report.project_name == "Test Project"
        assert report.status == "lead"
        assert report.open_task_count == 3
        assert report.done_task_count == 1
        assert report.overdue_count == 1

    def test_status_report_nonexistent_project(self):
        from agents.project_manager_agent import _get_project_status

        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchone.return_value = None
            report = _get_project_status("nonexistent")
        assert report.status == "not_found"

    def test_weekly_brief_non_empty(self):
        from agents.project_manager_agent import ProjectManagerAgent

        agent = ProjectManagerAgent()
        with patch("agents.project_manager_agent._get_project_status") as mock_status:
            mock_report = MagicMock()
            mock_report.status = "lead"
            mock_report.project_id = "p1"
            mock_report.project_name = "Test"
            mock_report.days_in_stage = 10
            mock_report.open_task_count = 2
            mock_report.done_task_count = 1
            mock_report.overdue_count = 0
            mock_report.next_task = "Do something"
            mock_status.return_value = mock_report
            brief = agent._fallback_brief(mock_report)
        assert len(brief) > 50
        assert "Test" in brief

    def test_pm_handles_nonexistent_project(self):
        from agents.project_manager_agent import ProjectManagerAgent

        agent = ProjectManagerAgent()
        with patch("agents.project_manager_agent._get_project_status") as mock_status:
            mock_report = MagicMock()
            mock_report.status = "not_found"
            mock_status.return_value = mock_report
            brief = agent.weekly_brief("nonexistent")
        assert "not_found" in brief
