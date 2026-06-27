"""T-1419: Assembly context injection into Finance Head Board Room."""
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class _MockRow:
    def __init__(self, values):
        self._values = values
    def __getitem__(self, idx):
        return self._values[idx]
    def __iter__(self):
        return iter(self._values)


class TestAssemblyBoardContext:
    def test_assembly_context_helper_importable(self):
        from crews.board_room import _build_assembly_context
        assert callable(_build_assembly_context)

    def test_assembly_context_returns_heading_with_rows(self):
        from crews.board_room import _build_assembly_context
        mock_rows = [
            _MockRow(["Test Buyer", "TV", 5, 0.85, 10000.0]),
        ]
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = mock_eng.return_value.connect.return_value.__enter__.return_value
            mock_conn.execute.return_value.fetchall.return_value = mock_rows
            result = _build_assembly_context("Yelahanka")
            assert "ACTIVE ASSEMBLY SIGNALS" in result
            assert "Test Buyer" in result

    def test_zero_rows_returns_no_assembly_message(self):
        from crews.board_room import _build_assembly_context
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = mock_eng.return_value.connect.return_value.__enter__.return_value
            mock_conn.execute.return_value.fetchall.return_value = []
            result = _build_assembly_context("Yelahanka")
            assert "No assembly signals" in result

    def test_build_assembly_context_exists(self):
        from crews.board_room import _build_assembly_context
        assert callable(_build_assembly_context)
