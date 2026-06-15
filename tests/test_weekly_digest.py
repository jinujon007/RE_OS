"""
Unit tests for agent_memory.generate_weekly_digest() — T-805 Sprint 44
Tests weekly digest generation, top-5 selection, conflict exclusion,
confidence boundary, error handling, None input, created_at format.
"""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit

from utils.agent_memory import generate_weekly_digest


@pytest.fixture
def mock_conn():
    """Standard mock DB connection with __enter__/__exit__."""
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    return conn


@pytest.fixture
def mock_engine(mock_conn):
    """Mock engine returning mock_conn from .connect()."""
    with patch("utils.agent_memory._get_engine") as me:
        me.return_value.connect.return_value = mock_conn
        yield me


class TestGenerateWeeklyDigest:
    def test_returns_top_5_facts(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("PSF ₹6,200", 0.95, "ceo", "Yelahanka", "2026-06-01"),
            ("PSF ₹6,100", 0.90, "analyst", "Yelahanka", "2026-05-30"),
            ("Demand up 15%", 0.85, "analyst", "Yelahanka", "2026-05-29"),
            ("New metro approved", 0.80, "ceo", "Yelahanka", "2026-05-28"),
            ("Supply 2000 units", 0.75, "analyst", "Yelahanka", "2026-05-27"),
        ]
        result = generate_weekly_digest("Yelahanka")
        assert len(result) == 5
        assert result[0]["fact"] == "PSF ₹6,200"
        assert result[0]["confidence"] == 0.95
        assert result[0]["agent_id"] == "ceo"
        assert result[0]["market"] == "Yelahanka"

    def test_returns_empty_on_db_error(self, mock_engine):
        mock_engine.return_value.connect.side_effect = Exception("DB unavailable")
        result = generate_weekly_digest("Yelahanka")
        assert result == []

    def test_returns_empty_for_empty_market(self, mock_engine):
        result = generate_weekly_digest("")
        assert result == []

    def test_returns_empty_for_none_market(self, mock_engine):
        result = generate_weekly_digest(None)
        assert result == []

    def test_returns_empty_for_non_string_market(self, mock_engine):
        result = generate_weekly_digest(12345)
        assert result == []

    def test_handles_sql_injection_attempt(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = []
        result = generate_weekly_digest("Yelahanka'; DROP TABLE agent_memories;--")
        assert result == []

    def test_excludes_conflict_facts(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("PSF ₹6,200", 0.95, "ceo", "Yelahanka", "2026-06-01"),
            ("Demand up 15%", 0.85, "analyst", "Yelahanka", "2026-05-29"),
        ]
        result = generate_weekly_digest("Yelahanka")
        assert len(result) == 2
        called_pattern = mock_conn.execute.call_args[0][1]["pattern"]
        assert "yelahanka" in called_pattern.lower()

    def test_filters_conflict_type_in_sql(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = []
        generate_weekly_digest("Hebbal")
        sql = mock_conn.execute.call_args[0][0].text
        assert "COALESCE(fact_type, 'fact') NOT IN ('conflict')" in sql

    def test_returns_less_than_5_when_few_facts(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("PSF ₹6,200", 0.95, "ceo", "Yelahanka", "2026-06-01"),
            ("Demand up 15%", 0.85, "analyst", "Yelahanka", "2026-05-29"),
        ]
        result = generate_weekly_digest("Yelahanka")
        assert len(result) == 2

    def test_facts_ordered_by_confidence_desc(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Fact A", 0.99, "ceo", "Yelahanka", "2026-06-01"),
            ("Fact B", 0.75, "analyst", "Yelahanka", "2026-05-30"),
            ("Fact C", 0.50, "analyst", "Yelahanka", "2026-05-29"),
        ]
        result = generate_weekly_digest("Yelahanka")
        confidences = [f["confidence"] for f in result]
        assert confidences == sorted(confidences, reverse=True)

    def test_confidence_boundary_at_0_4(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Fact A", 0.40, "analyst", "Yelahanka", "2026-06-01"),
        ]
        result = generate_weekly_digest("Yelahanka")
        assert len(result) == 1
        assert result[0]["confidence"] == 0.40

    def test_created_at_is_string(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Fact A", 0.90, "ceo", "Yelahanka", "2026-06-01T10:00:00"),
        ]
        result = generate_weekly_digest("Yelahanka")
        assert isinstance(result[0]["created_at"], str)
        assert len(result[0]["created_at"]) > 0

    def test_market_in_digest(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Fact A", 0.90, "ceo", "Devanahalli", "2026-06-01"),
        ]
        result = generate_weekly_digest("Devanahalli")
        assert result[0]["market"] == "Devanahalli"

    def test_uses_pattern_param_not_concat(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = []
        generate_weekly_digest("Yelahanka")
        params = mock_conn.execute.call_args[0][1]
        assert "pattern" in params
        assert (
            "%Yelahanka%" in params["pattern"]
            or "%yelahanka%" in params["pattern"].lower()
        )

    def test_max_fact_length_truncates(self, mock_conn, mock_engine):
        long_fact = "X" * 500
        mock_conn.execute.return_value.fetchall.return_value = [
            (long_fact, 0.90, "ceo", "Yelahanka", "2026-06-01"),
        ]
        result = generate_weekly_digest("Yelahanka", max_fact_length=50)
        assert len(result[0]["fact"]) <= 51  # 50 chars + possible ellipsis

    def test_max_fact_length_zero_no_truncation(self, mock_conn, mock_engine):
        long_fact = "X" * 500
        mock_conn.execute.return_value.fetchall.return_value = [
            (long_fact, 0.90, "ceo", "Yelahanka", "2026-06-01"),
        ]
        result = generate_weekly_digest("Yelahanka", max_fact_length=0)
        assert len(result[0]["fact"]) == 500

    def test_confidence_rounded_to_4_decimals(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Fact A", 0.12345678, "ceo", "Yelahanka", "2026-06-01"),
        ]
        result = generate_weekly_digest("Yelahanka")
        assert result[0]["confidence"] == 0.1235  # rounded to 4 dp

    def test_null_confidence_returns_zero(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Fact A", None, "ceo", "Yelahanka", "2026-06-01"),
        ]
        result = generate_weekly_digest("Yelahanka")
        assert result[0]["confidence"] == 0.0

    def test_null_fact_returns_empty_string(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            (None, 0.90, "ceo", "Yelahanka", "2026-06-01"),
        ]
        result = generate_weekly_digest("Yelahanka")
        assert result[0]["fact"] == ""

    def test_null_market_returns_empty_string_in_digest(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Fact A", 0.90, "ceo", None, "2026-06-01"),
        ]
        result = generate_weekly_digest("Yelahanka")
        assert result[0]["market"] == ""

    def test_sql_contains_order_by_confidence(self, mock_conn, mock_engine):
        """Property: SQL query orders by confidence DESC then created_at DESC.
        Validated via SQL text inspection since mock bypasses DB sorting."""
        mock_conn.execute.return_value.fetchall.return_value = []
        generate_weekly_digest("Yelahanka")
        sql = mock_conn.execute.call_args[0][0].text
        assert "ORDER BY confidence DESC" in sql
        assert "created_at DESC" in sql

    def test_sanitization_rejects_sql_injection(self, mock_engine):
        result = generate_weekly_digest("Yelahanka'; DROP SCHEMA public; --")
        assert result == []

    def test_sanitization_rejects_non_string(self, mock_engine):
        result = generate_weekly_digest(42)
        assert result == []

    def test_sanitization_rejects_none(self, mock_engine):
        result = generate_weekly_digest(None)
        assert result == []

    def test_sanitization_rejects_empty(self, mock_engine):
        result = generate_weekly_digest("")
        assert result == []

    def test_created_at_never_none(self, mock_conn, mock_engine):
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Fact A", 0.90, "ceo", "Yelahanka", None),
        ]
        result = generate_weekly_digest("Yelahanka")
        assert result[0]["created_at"] == ""
