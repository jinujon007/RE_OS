"""
Unit tests for agent_memory.write_memory() — T-945/GATE-55 audit finding C3.
Tests insert, upsert, confidence clamping, row cap pruning, error paths.
"""

import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import text

pytestmark = pytest.mark.unit

from utils.agent_memory import write_memory


class TestWriteMemoryCore:
    """Happy-path write_memory behavior."""

    def _mock_engine_with_counts(self, initial_count=0, execute_returns=None):
        patcher = patch("utils.agent_memory._get_engine")
        mock_engine = patcher.start()
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)

        if execute_returns:
            mock_conn.execute.side_effect = execute_returns
        else:
            count_mock = MagicMock()
            count_mock.fetchone.return_value = (initial_count,)
            mock_conn.execute.return_value = count_mock

        mock_engine.return_value.begin.return_value = mock_conn
        self._patcher = patcher
        return mock_conn

    def _stop(self):
        if hasattr(self, "_patcher"):
            self._patcher.stop()

    def test_writes_successfully(self):
        self._mock_engine_with_counts(initial_count=1)
        try:
            result = write_memory(
                "ceo", "Yelahanka", "Test fact ₹6,200", confidence=0.7
            )
            assert result is True
        finally:
            self._stop()

    def test_confidence_clamped_to_1_0(self):
        """Confidence >1.0 should be clamped to 1.0."""
        self._mock_engine_with_counts(initial_count=1)
        try:
            result = write_memory("ceo", "Yelahanka", "Fact", confidence=1.5)
            assert result is True
        finally:
            self._stop()

    def test_confidence_clamped_to_0_0(self):
        """Confidence <0.0 should be clamped to 0.0."""
        self._mock_engine_with_counts(initial_count=1)
        try:
            result = write_memory("ceo", "Yelahanka", "Fact", confidence=-0.5)
            assert result is True
        finally:
            self._stop()

    def test_returns_false_for_empty_fact(self):
        result = write_memory("ceo", "Yelahanka", "", confidence=0.7)
        assert result is False

    def test_returns_false_for_whitespace_only_fact(self):
        result = write_memory("ceo", "Yelahanka", "   ", confidence=0.7)
        assert result is False

    def test_strips_whitespace_from_fact(self):
        self._mock_engine_with_counts(initial_count=1)
        try:
            result = write_memory(
                "ceo", "Yelahanka", "  Fact with padding  ", confidence=0.7
            )
            assert result is True
        finally:
            self._stop()

    def test_returns_false_on_db_error(self):
        with patch("utils.agent_memory._get_engine") as mock_engine:
            mock_engine.return_value.begin.side_effect = Exception("DB unavailable")
            result = write_memory("ceo", "Yelahanka", "Fact", confidence=0.7)
            assert result is False


class TestWriteMemoryRowCap:
    """Row cap pruning logic (T-297)."""

    def _mock_with_row_count_sequence(self, counts_after_insert):
        """
        counts_after_insert: the row count that the COUNT query returns,
        which determines whether pruning triggers.
        """
        patcher = patch("utils.agent_memory._get_engine")
        mock_engine = patcher.start()
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)

        count_mock = MagicMock()
        count_mock.fetchone.return_value = (counts_after_insert,)
        mock_conn.execute.return_value = count_mock
        mock_engine.return_value.begin.return_value = mock_conn
        self._patcher = patcher
        return mock_conn

    def _stop(self):
        if hasattr(self, "_patcher"):
            self._patcher.stop()

    def test_row_cap_not_triggered_below_limit(self):
        mock_conn = self._mock_with_row_count_sequence(100)
        try:
            write_memory("ceo", "Yelahanka", "Fact under cap", confidence=0.7)
            calls = mock_conn.execute.mock_calls
            excess_calls = [
                c
                for c in calls
                if len(c.args) >= 2
                and isinstance(c.args[1], dict)
                and "excess" in c.args[1]
            ]
            assert len(excess_calls) == 0
        finally:
            self._stop()

    def test_row_cap_triggers_at_limit(self):
        mock_conn = self._mock_with_row_count_sequence(501)
        try:
            write_memory("ceo", "Yelahanka", "Fact at cap+1", confidence=0.7)
            calls = mock_conn.execute.mock_calls
            execute_calls_with_excess = [
                c
                for c in calls
                if len(c.args) >= 2
                and isinstance(c.args[1], dict)
                and "excess" in c.args[1]
            ]
            assert len(execute_calls_with_excess) == 1, (
                f"Expected 1 DELETE call with excess param, found "
                f"{len(execute_calls_with_excess)} in {len(calls)} total calls"
            )
        finally:
            self._stop()

    def test_row_cap_empty_count_does_not_crash(self):
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchone.return_value = None
        patcher = patch("utils.agent_memory._get_engine")
        mock_engine = patcher.start()
        mock_engine.return_value.begin.return_value = mock_conn
        try:
            result = write_memory(
                "ceo", "Yelahanka", "Fact with null count", confidence=0.7
            )
            assert result is True
        finally:
            patcher.stop()
