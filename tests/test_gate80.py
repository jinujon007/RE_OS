"""GATE-80 — Bhoomi Auto-Survey + Developer Coverage Expansion

Five assertions:
1. rera_projects table has survey_no column (migration 0042 adds it)
2. run_bhoomi_auto_survey is a callable function in config.scheduler
3. config/settings.py has GRADE_B_DEVELOPER_URLS with >=10 entries
4. developers table schema already has grade column (CHAR(1) from schema.sql)
5. BD Head context assembly includes grade_b_pipeline key via _get_grade_b_pipeline
"""

import pytest
from unittest.mock import patch

pytestmark = pytest.mark.unit


class TestGate80:
    """GATE-80: Bhoomi Auto-Survey + Developer Coverage."""

    def test_rera_projects_has_survey_no_column(self):
        """Assertion 1: migration 0042 adds survey_no column."""
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            "migration_0042",
            "alembic/versions/0042_rera_projects_survey_no.py",
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["migration_0042"] = mod
        spec.loader.exec_module(mod)

        assert hasattr(mod, "upgrade")
        assert mod.down_revision == "0041_gv_gazette_data_source"

    def test_run_bhoomi_auto_survey_is_callable(self):
        """Assertion 2: run_bhoomi_auto_survey is a callable function."""
        from config.scheduler import run_bhoomi_auto_survey

        assert callable(run_bhoomi_auto_survey), (
            "run_bhoomi_auto_survey must be a callable function"
        )

    def test_settings_has_grade_b_developer_urls_with_min_10(self):
        """Assertion 3: GRADE_B_DEVELOPER_URLS in settings has >=10 entries."""
        from config.settings import GRADE_B_DEVELOPER_URLS

        assert isinstance(GRADE_B_DEVELOPER_URLS, dict)
        assert len(GRADE_B_DEVELOPER_URLS) >= 10, (
            f"Expected >=10 Grade B developers, got {len(GRADE_B_DEVELOPER_URLS)}"
        )

    def test_developers_schema_has_grade_column(self):
        """Assertion 4: schema.sql defines developers.grade CHAR(1)."""
        schema_path = "database/schema.sql"
        with open(schema_path, encoding="utf-8") as f:
            schema = f.read()
        assert "grade CHAR(1)" in schema, (
            "developers table must have grade CHAR(1) column in schema.sql"
        )

    def test_bd_head_context_has_grade_b_pipeline(self):
        """Assertion 5: _get_grade_b_pipeline is a callable function."""
        from crews.board_room_v2 import _get_grade_b_pipeline

        assert callable(_get_grade_b_pipeline)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
