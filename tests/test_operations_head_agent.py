"""Unit tests for OperationsHeadAgent (T-994)."""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestTaskDelegator:
    def test_task_delegator_creates_row(self):
        from agents.operations_head_agent import _task_delegator_tool
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = (
                "t1", "Test task", "legal", "todo"
            )
            result = _task_delegator_tool("p1", "Test task", "legal")
        assert result.task_id == "t1"
        assert result.title == "Test task"
        assert result.dept == "legal"
        assert result.status == "todo"

    def test_task_delegator_handles_db_error(self):
        from agents.operations_head_agent import _task_delegator_tool
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.begin.side_effect = Exception("DB down")
            result = _task_delegator_tool("p1", "Test", "ops")
        assert result.status == "error"


class TestDecomposeActions:
    def test_empty_actions_returns_empty(self):
        from agents.operations_head_agent import OperationsHeadAgent
        agent = OperationsHeadAgent()
        result = agent.decompose_actions([], "p1")
        assert result == []

    def test_fallback_decompose_creates_tasks(self):
        from agents.operations_head_agent import OperationsHeadAgent
        agent = OperationsHeadAgent()
        with patch("agents.operations_head_agent._task_delegator_tool") as mock_tool:
            mock_tool.return_value.status = "todo"
            result = agent._fallback_decompose(["Legal review needed", "Call landowner"], "p1")
        assert len(result) == 2
