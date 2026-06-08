"""Unit tests for Social Media Agent and Brand Mention Monitor (Sprint 59)."""
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
pytestmark = pytest.mark.unit


class TestBrandMentionMonitor:
    def test_scan_mentions_returns_list(self):
        from utils.brand_monitor import BrandMentionMonitor
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = [
                ("id-1", "LLS Launches", "content about LLS launch", "positive", 0.9,
                 "NewsSite", "2026-06-01T00:00:00", "2026-06-01T00:00:00")
            ]
            monitor = BrandMentionMonitor()
            result = monitor.scan_mentions("LLS", 7)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["article_id"] == "id-1"
        assert result[0]["mention_type"] == "project_launch"

    def test_scan_mentions_handles_db_error(self):
        from utils.brand_monitor import BrandMentionMonitor
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.side_effect = Exception("DB down")
            monitor = BrandMentionMonitor()
            result = monitor.scan_mentions("LLS", 7)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_scan_with_custom_days(self):
        from utils.brand_monitor import BrandMentionMonitor
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = []
            monitor = BrandMentionMonitor()
            result = monitor.scan_mentions("LLS", 30)
        assert isinstance(result, list)


class TestContentCalendarGenerator:
    def test_calendar_has_4_weeks(self):
        from agents.social_media_agent import ContentCalendarGenerator
        gen = ContentCalendarGenerator()
        cal = gen.generate("June 2026", ["VEL"])
        assert len(cal.weeks) == 4
        for w in cal.weeks:
            assert len(w.posts) > 0

    def test_calendar_has_default_project(self):
        from agents.social_media_agent import ContentCalendarGenerator
        gen = ContentCalendarGenerator()
        cal = gen.generate("June 2026")
        assert len(cal.weeks) == 4
        post_count = sum(len(w.posts) for w in cal.weeks)
        assert post_count == 20

    def test_week_plan_to_dict(self):
        from agents.social_media_agent import WeekPlan
        plan = WeekPlan(week_label="W1", posts=[])
        d = plan.to_dict()
        assert d["week_label"] == "W1"


class TestPostFormatter:
    def test_linkedin_under_1300(self):
        from agents.social_media_agent import PostFormatter
        fmt = PostFormatter()
        long_text = "A" * 2000
        result = fmt.format(long_text, "linkedin")
        assert len(result) <= 1300

    def test_instagram_under_2200(self):
        from agents.social_media_agent import PostFormatter
        fmt = PostFormatter()
        long_text = "A" * 3000
        result = fmt.format(long_text, "instagram")
        assert len(result) <= 2200

    def test_unknown_channel_returns_unchanged(self):
        from agents.social_media_agent import PostFormatter
        fmt = PostFormatter()
        result = fmt.format("hello", "twitter")
        assert result == "hello"

    def test_empty_content_returns_empty(self):
        from agents.social_media_agent import PostFormatter
        fmt = PostFormatter()
        result = fmt.format("", "linkedin")
        assert result == ""


class TestSocialMediaAgent:
    def test_system_prompt_has_brand_voice(self):
        from agents.social_media_agent import SocialMediaAgent
        agent = SocialMediaAgent()
        prompt = agent._build_system_prompt()
        assert "zero defect" in prompt.lower()
        assert "nature as architecture" in prompt.lower()
        assert "no hidden information" in prompt.lower()

    def test_generate_week_returns_calendar(self):
        with patch("agents.social_media_agent._LLM_IMPORTED", False):
            from agents.social_media_agent import SocialMediaAgent
            agent = SocialMediaAgent()
            cal = agent.generate_week("VEL", "Yelahanka")
        assert len(cal.weeks) == 4
        assert cal.month
        post_count = sum(len(w.posts) for w in cal.weeks)
        assert post_count > 0

    def test_generate_week_uses_brief_when_provided(self):
        with patch("agents.social_media_agent._LLM_IMPORTED", False):
            from agents.social_media_agent import SocialMediaAgent
            from agents.pr_head_agent import PRBrief
            agent = SocialMediaAgent()
            brief = PRBrief(project_tagline="Test", investor_narrative="Narrative", target_segment="Test")
            cal = agent.generate_week("VEL", "Yelahanka", brief)
        assert len(cal.weeks) > 0

    def test_run_returns_dict(self):
        with patch("agents.social_media_agent._LLM_IMPORTED", False):
            from agents.social_media_agent import SocialMediaAgent
            agent = SocialMediaAgent()
            result = agent.run({"project_label": "VEL", "market": "Yelahanka"})
        assert result["status"] == "done"
        assert "calendar" in result
        assert result["post_count"] > 0

    def test_run_with_brief_dict(self):
        with patch("agents.social_media_agent._LLM_IMPORTED", False):
            from agents.social_media_agent import SocialMediaAgent
            agent = SocialMediaAgent()
            result = agent.run({
                "project_label": "VEL",
                "market": "Yelahanka",
                "pr_brief": {
                    "project_tagline": "Premium by Nature",
                    "investor_narrative": "Test narrative here",
                    "key_differentiators": ["Quality", "Design"],
                    "risk_acknowledgements": ["Risk 1"],
                }
            })
        assert result["status"] == "done"

    def test_to_dict_roundtrip(self):
        with patch("agents.social_media_agent._LLM_IMPORTED", False):
            from agents.social_media_agent import SocialMediaAgent
            agent = SocialMediaAgent()
            cal = agent.generate_week("VEL", "Yelahanka")
            d = cal.to_dict()
        assert "month" in d
        assert len(d["weeks"]) == 4


class TestFormatPRBriefDigest:
    def test_digest_under_1500_chars(self):
        from utils.brand_monitor import format_pr_brief_digest
        mentions = [{"title": "LLS Launch", "sentiment_label": "positive", "source": "TNIE"}]
        launches = [{"project_name": "Test", "developer_name": "Brigade"}]
        digest = format_pr_brief_digest(mentions, launches, "LinkedIn preview text here")
        assert len(digest.encode("utf-8")) <= 1500
        assert "PR Brief" in digest

    def test_digest_empty_mentions(self):
        from utils.brand_monitor import format_pr_brief_digest
        digest = format_pr_brief_digest([], [])
        assert "No brand mentions" in digest or "None this week" in digest
        assert len(digest.encode("utf-8")) <= 1500

    def test_digest_empty_launches(self):
        from utils.brand_monitor import format_pr_brief_digest
        digest = format_pr_brief_digest(
            [{"title": "Mention", "sentiment_label": "positive", "source": "S"}],
            [],
        )
        assert "None this week" in digest

    def test_digest_includes_linkedin_preview_when_provided(self):
        from utils.brand_monitor import format_pr_brief_digest
        digest = format_pr_brief_digest([], [], "LinkedIn preview")
        assert "LinkedIn Draft Preview" in digest

    def test_digest_handles_large_utf8(self):
        from utils.brand_monitor import format_pr_brief_digest
        mentions = [{"title": "x" * 200, "sentiment_label": "positive", "source": "S"}] * 20
        digest = format_pr_brief_digest(mentions, [], "p" * 100)
        assert len(digest.encode("utf-8")) <= 1500
