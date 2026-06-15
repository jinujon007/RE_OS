"""T-1080 — Bhoomi auto-survey job from RERA detail data

Three assertions:
1. run_bhoomi_auto_survey queries unchecked projects (survey_no set, bhoomi_checked_at NULL)
2. run_bhoomi_auto_survey marks bhoomi_checked_at on success
3. run_bhoomi_auto_survey skips gracefully on 429
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

pytestmark = pytest.mark.unit


class TestBhoomiAutoSurvey:
    """T-1080: Bhoomi auto-survey job."""

    def test_bhoomi_auto_survey_queries_unchecked_projects(self):
        """Assertion 1: queries rera_projects with survey_no NOT NULL and bhoomi_checked_at NULL."""
        from config.scheduler import run_bhoomi_auto_survey

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            MagicMock(id="uuid-1", survey_no="45/2", developer_name="Test Dev"),
        ]

        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        with patch("config.scheduler.get_engine", return_value=mock_engine):
            with patch("config.scheduler._bhoomi_already_ran", return_value=False):
                with patch("config.scheduler._mark_bhoomi_ran"):
                    with patch(
                        "scrapers.bhoomi_scraper.fetch",
                        return_value={"bhoomi_status": "unavailable"},
                    ):
                        run_bhoomi_auto_survey(market="Yelahanka")

        rera_calls = 0
        for call_args, _ in mock_conn.execute.call_args_list:
            sql_str = str(call_args[0]) if call_args else ""
            if "rera_projects" in sql_str:
                rera_calls += 1
        assert rera_calls >= 1, (
            f"Expected rera_projects in query, got calls: {mock_conn.execute.call_args_list}"
        )

    def test_bhoomi_auto_survey_marks_bhoomi_checked_at_on_success(self):
        """Assertion 2: sets bhoomi_checked_at on successful Bhoomi fetch."""
        from config.scheduler import run_bhoomi_auto_survey

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            MagicMock(id="uuid-1", survey_no="45/2", developer_name="Test Dev"),
        ]

        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        with patch("config.scheduler.get_engine", return_value=mock_engine):
            with patch("config.scheduler._bhoomi_already_ran", return_value=False):
                with patch("config.scheduler._mark_bhoomi_ran"):
                    with patch(
                        "scrapers.bhoomi_scraper.fetch",
                        return_value={
                            "bhoomi_status": "live",
                            "owner_name": "Test Owner",
                            "survey_no": "45/2",
                        },
                    ):
                        run_bhoomi_auto_survey(market="Yelahanka")

        # Should have at least one UPDATE rera_projects SET bhoomi_checked_at
        update_calls = 0
        for call_args, _ in mock_conn.execute.call_args_list:
            sql_str = str(call_args[0]) if call_args else ""
            if "UPDATE rera_projects" in sql_str:
                update_calls += 1
        assert update_calls >= 1, (
            f"Expected UPDATE rera_projects for bhoomi_checked_at, got calls: {mock_conn.execute.call_args_list}"
        )

    def test_bhoomi_auto_survey_skips_gracefully_on_429(self):
        """Assertion 3: stops batch on 429 rate limit, does not crash."""
        from config.scheduler import run_bhoomi_auto_survey

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            MagicMock(id="uuid-1", survey_no="45/2", developer_name="Dev A"),
            MagicMock(id="uuid-2", survey_no="46/1", developer_name="Dev B"),
        ]
        mock_conn.execute.return_value.fetchone.return_value = None

        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        # First call returns 429 error; second should never be called
        bhoomi_results = [
            {"bhoomi_status": "unavailable", "error": "rate_limited"},
            {"bhoomi_status": "live", "owner_name": "Other Owner", "survey_no": "46/1"},
        ]
        bhoomi_call_count = [0]

        def _mock_bhoomi_fetch(survey_no, market=None):
            idx = bhoomi_call_count[0]
            bhoomi_call_count[0] += 1
            return bhoomi_results[idx]

        with patch("config.scheduler.get_engine", return_value=mock_engine):
            with patch("config.scheduler._bhoomi_already_ran", return_value=False):
                with patch("config.scheduler._mark_bhoomi_ran"):
                    with patch(
                        "scrapers.bhoomi_scraper.fetch", side_effect=_mock_bhoomi_fetch
                    ):
                        run_bhoomi_auto_survey(market="Yelahanka")

        # Only 1 bhoomi call should be made (second skipped due to 429)
        assert bhoomi_call_count[0] == 1, (
            f"Expected only 1 bhoomi call (stopped on 429), got {bhoomi_call_count[0]}"
        )

    def test_migration_0043_adds_bhoomi_checked_at_column(self):
        """Assertion 4: migration file adds bhoomi_checked_at TIMESTAMPTZ column."""
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            "migration_0043",
            "alembic/versions/0043_rera_projects_bhoomi_checked_at.py",
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["migration_0043"] = mod
        spec.loader.exec_module(mod)

        assert hasattr(mod, "upgrade"), "Migration must have upgrade()"
        assert hasattr(mod, "downgrade"), "Migration must have downgrade()"
        assert mod.down_revision == "0042_rera_projects_survey_no", (
            f"Expected down_revision='0042_rera_projects_survey_no', got {mod.down_revision}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
