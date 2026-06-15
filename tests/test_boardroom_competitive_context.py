"""Unit tests for Board Room BD Head competitive context (T-977)."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestBoardroomCompetitiveContext:
    def test_bd_head_task_includes_competitive_context(self):
        from intelligence.registry import IntelPackage
        from crews.board_room_v2 import _get_competitive_context

        pkg = IntelPackage(
            survey_no="45/2", market="Yelahanka", collected_at="2026-06-06T00:00:00"
        )

        with patch(
            "intelligence.competitive_intel.CompetitiveIntelEngine"
        ) as MockEngine:
            mock_instance = MagicMock()
            mock_instance.absorption_leaders.return_value = [
                {
                    "project_name": "Proj A",
                    "developer_name": "Builder X",
                    "absorption_pct": 85.0,
                },
            ]
            mock_instance.new_launches.return_value = [
                {
                    "project_name": "Proj B",
                    "developer_name": "Builder Y",
                    "total_units": 200,
                },
            ]
            MockEngine.return_value = mock_instance

            context = _get_competitive_context(pkg.market)
        assert "CompetitiveIntelEngine" not in context
        assert "Top absorbers" in context
        assert "Recent launches" in context
        assert "85" in context

    def test_competitive_context_skipped_on_engine_failure(self):
        from crews.board_room_v2 import _get_competitive_context

        with patch(
            "intelligence.competitive_intel.CompetitiveIntelEngine"
        ) as MockEngine:
            MockEngine.side_effect = Exception("DB down")
            context = _get_competitive_context("Yelahanka")
        assert context == ""
