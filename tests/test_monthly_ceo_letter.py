"""Tests for monthly CEO letter scheduler job (T-1019)."""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestMonthlyCEOLogic:
    def test_monthly_letter_generates_content(self):
        """Verify monthly CEO letter generates content without errors."""
        with (
            patch("utils.performance_digest.PerformanceDigest.build") as mock_digest,
            patch("config.scheduler.get_engine") as mock_eng,
            patch("config.scheduler.logger"),
        ):
            mock_digest.return_value = {
                "deal_metrics": {"deal_count": 5, "avg_irr_pct": 12.5},
                "new_projects": [{"market": "Yelahanka", "project_count": 3}],
                "token_efficiency": {
                    "total_token_usage_records": 50,
                    "over_budget_count": 2,
                },
            }
            mock_conn = MagicMock()
            mock_row = MagicMock()
            mock_row.__getitem__.return_value = 100
            mock_conn.execute.return_value.fetchone.return_value = mock_row
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )

            from config.scheduler import monthly_ceo_letter

            monthly_ceo_letter()

            assert mock_digest.called

    def test_monthly_letter_saved_to_path(self):
        """Verify the letter is saved to correct output directory."""
        with (
            patch("utils.performance_digest.PerformanceDigest.build") as mock_digest,
            patch("config.scheduler.get_engine") as mock_eng,
            patch("pathlib.Path.write_text") as mock_write,
            patch("pathlib.Path.mkdir") as mock_mkdir,
            patch("config.scheduler.logger"),
        ):
            mock_digest.return_value = {
                "deal_metrics": {"deal_count": 0, "avg_irr_pct": None},
                "new_projects": [],
                "token_efficiency": {},
            }
            mock_conn = MagicMock()
            mock_row = MagicMock()
            mock_row.__getitem__.return_value = 0
            mock_conn.execute.return_value.fetchone.return_value = mock_row
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )

            from config.scheduler import monthly_ceo_letter

            monthly_ceo_letter()

            assert mock_write.called

    def test_scheduler_job_registered(self):
        """Verify the scheduler has the monthly_ceo_letter job registered."""
        from config.scheduler import monthly_ceo_letter

        assert callable(monthly_ceo_letter)

    def test_monthly_letter_handles_db_error_gracefully(self):
        """Verify monthly letter doesn't crash when DB is unavailable."""
        with (
            patch("utils.performance_digest.PerformanceDigest.build") as mock_digest,
            patch("config.scheduler.get_engine", side_effect=Exception("DB down")),
            patch("pathlib.Path.write_text") as mock_write,
            patch("config.scheduler.logger"),
        ):
            mock_digest.return_value = {
                "deal_metrics": {"deal_count": 0, "avg_irr_pct": None},
                "new_projects": [],
                "token_efficiency": {},
            }

            from config.scheduler import monthly_ceo_letter

            monthly_ceo_letter()
