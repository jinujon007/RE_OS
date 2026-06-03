"""
Unit tests for agent_memory.detect_conflicts() — T-803 Sprint 44
Tests conflict detection logic, numeric extraction, edge cases.
"""
import pytest
from unittest.mock import patch, MagicMock
import re

pytestmark = pytest.mark.unit


class TestNumericExtraction:
    """Test numeric value extraction from fact strings - unit tests."""
    
    def test_extracts_rupee_amounts_with_commas(self):
        """Should correctly parse ₹6,200 as 6200."""
        fact = "Avg PSF ₹6,200"
        nums = re.findall(r'₹?[\d,]+\.?\d*', fact)
        val = float(nums[0].replace('₹', '').replace(',', ''))
        assert val == 6200
    
    def test_handles_numbers_without_rupee_symbol(self):
        """Should extract plain numbers like 6000."""
        fact = "PSF 6000 observed"
        nums = re.findall(r'₹?[\d,]+\.?\d*', fact)
        val = float(nums[0].replace('₹', '').replace(',', ''))
        assert val == 6000
    
    def test_handles_decimal_values(self):
        """Should extract decimal values."""
        fact = "PSF ₹6,200.50"
        nums = re.findall(r'₹?[\d,]+\.?\d*', fact)
        val = float(nums[0].replace('₹', '').replace(',', ''))
        assert val == 6200.50
    
    def test_returns_empty_for_non_numeric_facts(self):
        """Should return empty list for facts without numbers."""
        fact = "Market is hot"
        nums = re.findall(r'₹?[\d,]+\.?\d*', fact)
        assert nums == []


from utils.agent_memory import detect_conflicts


class TestDetectConflictsErrorHandling:
    """Test error handling and edge cases."""
    
    def test_returns_empty_on_db_connection_error(self):
        """Should return empty list on DB error, not crash."""
        with patch("utils.agent_memory._get_engine") as mock_engine:
            mock_engine.return_value.connect.side_effect = Exception("DB unavailable")
            
            result = detect_conflicts("Yelahanka")
            assert result == []
    
    def test_handles_malformed_market_parameter(self):
        """Should handle special characters in market parameter."""
        with patch("utils.agent_memory._get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.__enter__ = lambda s: s
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_engine.return_value.connect.return_value = mock_conn
            
            result = detect_conflicts("Yelahanka'; DROP TABLE agent_memories;--")
            assert result == []
    
    def test_handles_empty_market_string(self):
        """Should handle empty market parameter gracefully."""
        with patch("utils.agent_memory._get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.__enter__ = lambda s: s
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_engine.return_value.connect.return_value = mock_conn
            
            result = detect_conflicts("")
            assert result == []
