"""T-1082 — BD Head context includes Grade B pre-launch pipeline

Two assertions:
1. BD Head context has grade_b_pipeline key via _get_grade_b_pipeline
2. grade_b_pipeline returns empty list when DB returns empty
"""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestGradeBPipelineInBDHead:
    """T-1082: Grade B pre-launch pipeline in BD Head context."""

    def test_bd_head_context_has_grade_b_pipeline_key(self):
        """Assertion 1: _get_grade_b_pipeline returns Grade B projects from DB."""
        from crews.board_room_v2 import _get_grade_b_pipeline

        with patch("crews.board_room_v2.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchall.return_value = [
                MagicMock(
                    developer_name="Test Builder",
                    project_name="Green Enclave",
                    locality="Yelahanka",
                    total_units=120,
                    launch_status="new",
                ),
            ]
            result = _get_grade_b_pipeline("Yelahanka")

        assert isinstance(result, list), "Expected list result"
        assert len(result) >= 1, "Expected at least one pipeline entry"
        assert result[0]["developer_name"] == "Test Builder"
        assert result[0]["project_name"] == "Green Enclave"
        assert result[0]["launch_status"] == "new"

    def test_grade_b_pipeline_shows_none_when_db_empty(self):
        """Assertion 2: returns empty list when no Grade B pipeline projects exist."""
        from crews.board_room_v2 import _get_grade_b_pipeline

        with patch("crews.board_room_v2.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchall.return_value = []
            result = _get_grade_b_pipeline("Yelahanka")

        assert isinstance(result, list), "Expected list result"
        assert len(result) == 0, "Expected empty list when DB returns no results"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
