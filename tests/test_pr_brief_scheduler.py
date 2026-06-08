"""Unit tests for weekly PR brief scheduler job (Sprint 59, T-999)."""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestWeeklyPRBriefJob:
    def test_weekly_pr_job_registered(self):
        """Verify the weekly_pr_brief job is registered in scheduler by
        checking job id appears in scheduler source with correct cron."""
        import inspect
        import config.scheduler as sched_mod
        source = inspect.getsource(sched_mod)
        assert "weekly_pr_brief" in source
        assert "day_of_week=\"mon\", hour=2, minute=0" in source or \
               "day_of_week='mon', hour=2, minute=0" in source

    def test_weekly_pr_brief_runs_without_error(self):
        """Run the job function with mocks — no exception."""
        from config.scheduler import weekly_pr_brief
        with patch("utils.brand_monitor.BrandMentionMonitor") as mock_monitor, \
             patch("intelligence.competitive_intel.CompetitiveIntelEngine") as mock_engine, \
             patch("utils.discord_notifier.send") as mock_send:
            mock_monitor_instance = MagicMock()
            mock_monitor_instance.scan_mentions.return_value = []
            mock_monitor.return_value = mock_monitor_instance
            mock_engine_instance = MagicMock()
            mock_engine_instance.new_launches.return_value = []
            mock_engine.return_value = mock_engine_instance
            weekly_pr_brief()
        assert mock_send.called

    def test_weekly_pr_brief_handles_content_pipeline_failure(self):
        """ContentPipeline failure should not prevent digest from sending."""
        from config.scheduler import weekly_pr_brief
        with patch("utils.brand_monitor.BrandMentionMonitor") as mock_monitor, \
             patch("intelligence.competitive_intel.CompetitiveIntelEngine") as mock_engine, \
             patch("utils.discord_notifier.send") as mock_send, \
             patch("utils.content_pipeline.ContentPipeline") as mock_pipeline:
            mock_monitor_instance = MagicMock()
            mock_monitor_instance.scan_mentions.return_value = [
                {"title": "LLS", "sentiment_label": "positive", "source": "News"}
            ]
            mock_monitor.return_value = mock_monitor_instance
            mock_engine_instance = MagicMock()
            mock_engine_instance.new_launches.return_value = []
            mock_engine.return_value = mock_engine_instance
            mock_pipeline.side_effect = Exception("Pipeline down")
            weekly_pr_brief()
        assert mock_send.called

    def test_weekly_pr_brief_handles_empty_mentions_gracefully(self):
        """Empty mentions should still produce a valid digest (not crash)."""
        from config.scheduler import weekly_pr_brief
        with patch("utils.brand_monitor.BrandMentionMonitor") as mock_monitor, \
             patch("intelligence.competitive_intel.CompetitiveIntelEngine") as mock_engine, \
             patch("utils.discord_notifier.send") as mock_send:
            mock_monitor_instance = MagicMock()
            mock_monitor_instance.scan_mentions.return_value = []
            mock_monitor.return_value = mock_monitor_instance
            mock_engine_instance = MagicMock()
            mock_engine_instance.new_launches.return_value = []
            mock_engine.return_value = mock_engine_instance
            weekly_pr_brief()
        assert mock_send.called
