"""GATE-67: Social Media Agent / Brand Monitor / PR Panel / Scheduler."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestGate67:
    def test_social_media_agent_generates_calendar(self):
        with patch("agents.social_media_agent._LLM_IMPORTED", False):
            from agents.social_media_agent import SocialMediaAgent

            agent = SocialMediaAgent()
            cal = agent.generate_week("VEL", "Yelahanka")
            li_posts = [
                p for w in cal.weeks for p in w.posts if p.channel == "linkedin"
            ]
            ig_posts = [
                p for w in cal.weeks for p in w.posts if p.channel == "instagram"
            ]
        assert len(li_posts) >= 2
        assert len(ig_posts) >= 3

    def test_social_media_agent_with_brief(self):
        """With PRBrief provided, calendar should still produce ≥5 posts."""
        with patch("agents.social_media_agent._LLM_IMPORTED", False):
            from agents.social_media_agent import SocialMediaAgent
            from agents.pr_head_agent import PRBrief

            agent = SocialMediaAgent()
            brief = PRBrief(
                project_tagline="Premium living, naturally.",
                investor_narrative="This is a test investment narrative for verification.",
                key_differentiators=["Quality", "Design", "Transparency"],
                target_segment="Premium buyers",
                risk_acknowledgements=["Market risk"],
            )
            cal = agent.generate_week("VEL", "Yelahanka", brief)
            li_posts = [
                p for w in cal.weeks for p in w.posts if p.channel == "linkedin"
            ]
            ig_posts = [
                p for w in cal.weeks for p in w.posts if p.channel == "instagram"
            ]
        assert len(li_posts) + len(ig_posts) >= 5

    def test_brand_monitor_scan_returns_list(self):
        from utils.brand_monitor import BrandMentionMonitor

        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchall.return_value = []
            monitor = BrandMentionMonitor()
            result = monitor.scan_mentions("LLS", 7)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_weekly_pr_job_registered_in_scheduler(self):
        import inspect
        import config.scheduler as sched_mod

        source = inspect.getsource(sched_mod)
        assert "weekly_pr_brief" in source
        assert 'id="weekly_pr_brief"' in source or "id='weekly_pr_brief'" in source

    def test_pr_panel_returns_200(self):
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app

        client = TestClient(app)
        resp = client.get("/pr")
        assert resp.status_code == 200
