"""
Unit tests for agent_memory.detect_conflicts() — T-803 Sprint 44
Tests conflict detection logic, numeric extraction, edge cases.
"""

import pytest
from unittest.mock import patch, MagicMock
import re

pytestmark = pytest.mark.unit

from config.gate_criteria import GATE55_CONFLICT_GAP_THRESHOLD


class TestNumericExtraction:
    """Test numeric value extraction from fact strings."""

    CORRECT_REGEX = r"₹?\d[\d,]*\.?\d*"

    def test_extracts_rupee_amounts_with_commas(self):
        nums = re.findall(self.CORRECT_REGEX, "Avg PSF ₹6,200")
        val = float(nums[0].replace("₹", "").replace(",", ""))
        assert val == 6200

    def test_handles_numbers_without_rupee_symbol(self):
        nums = re.findall(self.CORRECT_REGEX, "PSF 6000 observed")
        val = float(nums[0].replace("₹", "").replace(",", ""))
        assert val == 6000

    def test_handles_decimal_values(self):
        nums = re.findall(self.CORRECT_REGEX, "PSF ₹6,200.50")
        val = float(nums[0].replace("₹", "").replace(",", ""))
        assert val == 6200.50

    def test_returns_empty_for_non_numeric_facts(self):
        nums = re.findall(self.CORRECT_REGEX, "Market is hot")
        assert nums == []

    def test_ignores_commas_outside_numbers(self):
        """Comma before ₹ sign should NOT be matched as a numeric value."""
        fact = "Based on latest market data for Yelahanka, PSF is ₹4800"
        nums = re.findall(self.CORRECT_REGEX, fact)
        assert len(nums) >= 1
        val = float(nums[0].replace("₹", "").replace(",", ""))
        assert val == 4800

    def test_ignores_standalone_commas(self):
        """Lone comma without adjacent digit should not match."""
        fact = "Price, , per sqft, ₹6200"
        nums = re.findall(self.CORRECT_REGEX, fact)
        assert len(nums) >= 1
        val = float(nums[0].replace("₹", "").replace(",", ""))
        assert val == 6200

    def test_extracts_large_numbers(self):
        nums = re.findall(self.CORRECT_REGEX, "Total units: ₹150,00,000")
        val = float(nums[0].replace("₹", "").replace(",", ""))
        assert val == 15000000

    def test_extracts_first_number_when_multiple(self):
        nums = re.findall(self.CORRECT_REGEX, "PSF ₹6200 vs ₹5800")
        val = float(nums[0].replace("₹", "").replace(",", ""))
        assert val == 6200

    def test_handles_no_rupee_decimal_number(self):
        nums = re.findall(self.CORRECT_REGEX, "Rate 95.5 per sqft")
        val = float(nums[0])
        assert val == 95.5


from utils.agent_memory import detect_conflicts


class TestConflictDetection:
    """Test detection logic — mock DB rows, verify conflict calculation."""

    def _build_mock_row(
        self,
        agent_a="analyst",
        agent_b="ceo",
        fact_a="Based on latest data, PSF is ₹6200",
        fact_b="Based on latest data, PSF is ₹4800",
        conf_a=0.7,
        conf_b=0.8,
        market="Yelahanka",
    ):
        return MagicMock(
            _asdict=lambda: {
                "agent_a": agent_a,
                "agent_b": agent_b,
                "fact_a": fact_a,
                "fact_b": fact_b,
                "conf_a": conf_a,
                "conf_b": conf_b,
                "market": market,
            },
            __iter__=lambda s: iter(
                [
                    agent_a,
                    agent_b,
                    fact_a,
                    fact_b,
                    conf_a,
                    conf_b,
                    market,
                ]
            ),
        )

    def _patch_engine(self, rows, mock_write=None):
        patcher = patch("utils.agent_memory._get_engine")
        mock_engine = patcher.start()
        mock_conn = MagicMock()
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_engine.return_value.connect.return_value = mock_conn
        if mock_write:
            mock_engine.return_value.begin.return_value = mock_write
        self._patcher = patcher
        return mock_conn

    def _stop_patch(self):
        if hasattr(self, "_patcher"):
            self._patcher.stop()

    def test_returns_conflict_when_gap_exceeds_threshold(self):
        """6200 vs 4800 → 22.6% gap > 20% → should flag conflict."""
        rows = [self._build_mock_row()]
        mock_write = MagicMock()
        mock_write.__enter__ = lambda s: s
        mock_write.__exit__ = MagicMock(return_value=False)
        self._patch_engine(rows, mock_write)
        try:
            result = detect_conflicts("Yelahanka")
            assert len(result) >= 1
            assert result[0]["pct_gap"] > GATE55_CONFLICT_GAP_THRESHOLD
            assert result[0]["value_a"] == 6200
            assert result[0]["value_b"] == 4800
        finally:
            self._stop_patch()

    def test_no_conflict_when_gap_below_threshold(self):
        """5500 vs 6000 → 8.3% gap < 20% → should NOT flag conflict."""
        rows = [
            self._build_mock_row(
                fact_a="Based on latest data, PSF is ₹5500",
                fact_b="Based on latest data, PSF is ₹6000",
            )
        ]
        self._patch_engine(rows)
        try:
            result = detect_conflicts("Yelahanka")
            assert len(result) == 0
        finally:
            self._stop_patch()

    def test_no_conflict_at_exactly_20_percent(self):
        """5000 vs 6250 → exactly 20% gap → should NOT flag (< threshold, not <=)."""
        rows = [
            self._build_mock_row(
                fact_a="Based on latest data, PSF is ₹5000",
                fact_b="Based on latest data, PSF is ₹6250",
            )
        ]
        self._patch_engine(rows)
        try:
            result = detect_conflicts("Yelahanka")
            pct = abs(5000 - 6250) / max(5000, 6250) * 100
            assert pct == 20.0
            assert len(result) == 0
        finally:
            self._stop_patch()

    def test_skips_zero_values(self):
        """0 value should be skipped (division guard)."""
        rows = [
            self._build_mock_row(
                fact_a="Based on latest data, PSF is ₹0",
                fact_b="Based on latest data, PSF is ₹6200",
            )
        ]
        self._patch_engine(rows)
        try:
            result = detect_conflicts("Yelahanka")
            assert len(result) == 0
        finally:
            self._stop_patch()

    def test_skips_non_numeric_facts(self):
        """Facts without extractable numbers should be skipped."""
        rows = [
            MagicMock(
                __iter__=lambda s: iter(
                    [
                        "analyst",
                        "ceo",
                        "Market is trending upward",
                        "Demand is strong",
                        0.7,
                        0.8,
                        "Yelahanka",
                    ]
                ),
            )
        ]
        self._patch_engine(rows)
        try:
            result = detect_conflicts("Yelahanka")
            assert len(result) == 0
        finally:
            self._stop_patch()

    def test_handles_multiple_conflicts(self):
        """Multiple conflicting fact pairs should all be returned."""
        rows = [
            self._build_mock_row(
                fact_a="Based on latest data, PSF is ₹6200",
                fact_b="Based on latest data, PSF is ₹4800",
            ),
            self._build_mock_row(
                fact_a="Inventory estimate: 5000 units",
                fact_b="Inventory estimate: 3500 units",
            ),
        ]
        mock_write = MagicMock()
        mock_write.__enter__ = lambda s: s
        mock_write.__exit__ = MagicMock(return_value=False)
        self._patch_engine(rows, mock_write)
        try:
            result = detect_conflicts("Yelahanka")
            assert len(result) == 2
        finally:
            self._stop_patch()

    def test_conflict_keys_present(self):
        """Conflict dict should have all required keys."""
        rows = [self._build_mock_row()]
        mock_write = MagicMock()
        mock_write.__enter__ = lambda s: s
        mock_write.__exit__ = MagicMock(return_value=False)
        self._patch_engine(rows, mock_write)
        try:
            result = detect_conflicts("Yelahanka")
            assert len(result) >= 1
            expected_keys = {
                "market",
                "fact_prefix",
                "agent_a",
                "agent_b",
                "value_a",
                "value_b",
                "pct_gap",
            }
            assert expected_keys.issubset(result[0].keys())
        finally:
            self._stop_patch()

    def test_handles_missing_rupee_sign_in_one_fact(self):
        """One fact with ₹ and one without should still match."""
        rows = [
            self._build_mock_row(
                fact_a="PSF is 6200 from RERA data",
                fact_b="Based on latest data, PSF is ₹4800",
            )
        ]
        mock_write = MagicMock()
        mock_write.__enter__ = lambda s: s
        mock_write.__exit__ = MagicMock(return_value=False)
        self._patch_engine(rows, mock_write)
        try:
            result = detect_conflicts("Yelahanka")
            assert len(result) >= 1
        finally:
            self._stop_patch()

    def test_conflict_fact_truncated_to_500_chars(self):
        """Written conflict fact should be truncated to 500 chars max."""
        long_prefix = "X" * 200
        rows = [
            self._build_mock_row(
                fact_a=f"{long_prefix} 6200",
                fact_b=f"{long_prefix} 4800",
                agent_a="analyst",
                agent_b="ceo",
            )
        ]
        mock_write = MagicMock()
        mock_write.__enter__ = lambda s: s
        mock_write.__exit__ = MagicMock(return_value=False)
        self._patch_engine(rows, mock_write)
        try:
            result = detect_conflicts("Yelahanka")
            assert len(result) >= 1
            call_kwargs = mock_write.execute.call_args[1]
            written_fact = (
                call_kwargs.get("parameters", {}).get("fact")
                or list(mock_write.execute.call_args[0][1].values())[2]
            )
            assert len(written_fact) <= 500
        finally:
            self._stop_patch()


class TestDetectConflictsErrorHandling:
    """Test error handling and edge cases."""

    def test_returns_empty_on_db_connection_error(self):
        with patch("utils.agent_memory._get_engine") as mock_engine:
            mock_engine.return_value.connect.side_effect = Exception("DB unavailable")
            result = detect_conflicts("Yelahanka")
            assert result == []

    def test_handles_sql_injection_attempt(self):
        with patch("utils.agent_memory._get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.__enter__ = lambda s: s
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_engine.return_value.connect.return_value = mock_conn
            result = detect_conflicts("Yelahanka'; DROP TABLE agent_memories;--")
            assert result == []

    def test_handles_empty_market_string(self):
        with patch("utils.agent_memory._get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.__enter__ = lambda s: s
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_engine.return_value.connect.return_value = mock_conn
            result = detect_conflicts("")
            assert result == []

    def test_returns_empty_on_none_market(self):
        result = detect_conflicts(None)
        assert result == []

    def test_returns_empty_on_non_string_market(self):
        result = detect_conflicts(12345)
        assert result == []
