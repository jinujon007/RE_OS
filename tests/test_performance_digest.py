"""Tests for PerformanceDigest — quarterly performance aggregator."""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

from utils.performance_digest import (
    PerformanceDigest,
    _deal_metrics,
    _new_projects,
    parse_quarter,
    _token_efficiency,
)


class TestQuarterParsing:
    def test_q1_2026(self):
        start, end = parse_quarter("Q1-2026")
        assert start.isoformat() == "2026-01-01"
        assert end.isoformat() == "2026-03-31"

    def test_q2_2026(self):
        start, end = parse_quarter("Q2-2026")
        assert start.isoformat() == "2026-04-01"
        assert end.isoformat() == "2026-06-30"

    def test_q4_2025(self):
        start, end = parse_quarter("Q4-2025")
        assert start.isoformat() == "2025-10-01"
        assert end.isoformat() == "2025-12-31"

    def test_q3_2024(self):
        start, end = parse_quarter("Q3-2024")
        assert start.isoformat() == "2024-07-01"
        assert end.isoformat() == "2024-09-30"

    def test_invalid_quarter_raises(self):
        with pytest.raises(ValueError, match="Invalid quarter format"):
            parse_quarter("not-a-quarter")
        with pytest.raises(ValueError):
            parse_quarter("Q5-2026")
        with pytest.raises(ValueError):
            parse_quarter("")


def _make_mock_conn(seq_results: list[list]) -> MagicMock:
    mock_conn = MagicMock()
    call_idx = [0]

    def _side(*args, **kwargs):
        idx = call_idx[0]
        call_idx[0] += 1
        if idx < len(seq_results):
            data = seq_results[idx]
        else:
            data = []
        mock_result = MagicMock()
        mock_result.fetchall.return_value = data
        return mock_result

    mock_conn.execute.side_effect = _side
    return mock_conn


class TestPerformanceDigest:
    @patch("utils.performance_digest.get_engine")
    def test_has_all_sections(self, mock_eng):
        mock_conn = _make_mock_conn([
            [(3, 12.5)],
            [("Yelahanka", 5)],
            [(2, 45.0)],
            [("mou", "signed", 30.0)],
            [(2, 10)],
        ])
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        digest = PerformanceDigest.build("Q2-2026")
        assert "quarter" in digest
        assert "period" in digest
        assert "deal_metrics" in digest
        assert "new_projects" in digest
        assert "absorption_trend" in digest
        assert "deal_velocity_summary" in digest
        assert "token_efficiency" in digest
        assert digest["quarter"] == "Q2-2026"
        assert digest["deal_metrics"]["deal_count"] == 3
        assert digest["deal_metrics"]["avg_irr_pct"] == 12.5
        assert len(digest["new_projects"]) == 1
        assert digest["absorption_trend"]["avg_absorption_pct"] == 45.0

    def test_handles_no_evaluate_jobs(self):
        result = _deal_metrics(date(1970, 1, 1), date(1970, 1, 2))
        assert result["deal_count"] == 0
        assert result["avg_irr_pct"] is None

    @patch("utils.performance_digest.get_engine")
    def test_computes_avg_irr(self, mock_eng):
        mock_conn = _make_mock_conn([[(3, 15.2)]])
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        result = _deal_metrics(date(2026, 4, 1), date(2026, 6, 30))
        assert result["deal_count"] == 3
        assert result["avg_irr_pct"] == 15.2

    @patch("utils.performance_digest.get_engine")
    def test_new_projects_parsed(self, mock_eng):
        mock_conn = _make_mock_conn([[("Yelahanka", 5)]])
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        projects = _new_projects(date(2026, 4, 1), date(2026, 6, 30))
        assert len(projects) == 1
        assert projects[0]["market"] == "Yelahanka"
        assert projects[0]["project_count"] == 5

    @patch("utils.performance_digest.get_engine")
    def test_token_efficiency_computed(self, mock_eng):
        mock_conn = _make_mock_conn([[(2, 10)]])
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        result = _token_efficiency(date(2026, 4, 1), date(2026, 6, 30))
        assert result["total_token_usage_records"] == 10
        assert result["over_budget_count"] == 2
        assert result["over_budget_pct"] == 20.0
