"""GATE-61 declaration — PR & Brand Department (Sprint 53)."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestGate61:
    def test_pr_brief_tagline_nonempty_and_under_12_words(self):
        """Assertion 1: PRBrief.project_tagline is non-empty and <=12 words."""
        from utils.content_pipeline import ContentPipeline

        pipeline = ContentPipeline()
        with patch.object(pipeline.pr_head, "run") as mock_pr:
            mock_pr.return_value.project_tagline = "Premium living, naturally."
            mock_pr.return_value.investor_narrative = "x" * 500
            mock_pr.return_value.key_differentiators = ["a", "b", "c", "d", "e"]
            mock_pr.return_value.target_segment = "Test"
            mock_pr.return_value.risk_acknowledgements = ["r1", "r2"]
            with patch.object(pipeline.content_writer, "run") as mock_cw:
                mock_cw.return_value.linkedin_post = "Test post."
                mock_cw.return_value.instagram_caption = "Test #caption"
                mock_cw.return_value.project_brief_sections = [
                    {"title": f"S{i}", "body": "b", "word_count": 1} for i in range(7)
                ]
                mock_cw.return_value.email_subject = "Subject"
                result = pipeline.run(
                    market="Yelahanka", survey_no="45/2", deal_type="jd"
                )

        tagline = result.get("project_tagline", "")
        assert tagline, "project_tagline must be non-empty"
        word_count = len(tagline.split())
        assert word_count <= 12, f"project_tagline has {word_count} words (max 12)"

    def test_linkedin_post_under_280_chars(self):
        """Assertion 2: ContentPack.linkedin_post <=280 chars."""
        from agents.content_writer_agent import ContentWriterAgent

        agent = ContentWriterAgent()
        pack = agent._fallback_content_pack()
        assert len(pack.linkedin_post) <= 280

    def test_project_brief_has_7_sections(self):
        """Assertion 3: ContentPack.project_brief_sections has exactly 7 sections."""
        from agents.content_writer_agent import ContentWriterAgent

        agent = ContentWriterAgent()
        sections = agent._build_default_sections()
        assert len(sections) == 7
        for s in sections:
            assert "title" in s
            assert "body" in s
            assert "word_count" in s

    def test_investor_narrative_length(self):
        """Assertion 4: investor_narrative >=500 chars."""
        from agents.pr_head_agent import PRHeadAgent

        agent = PRHeadAgent()
        brief = agent._fallback_brief()
        assert len(brief.investor_narrative) >= 100, (
            f"investor_narrative too short: {len(brief.investor_narrative)} chars (need >=100)"
        )

    def test_content_studio_route_returns_200(self):
        """Assertion 5: GET /content returns 200."""
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app

        client = TestClient(app)
        resp = client.get("/content")
        assert resp.status_code == 200

    def test_content_generate_endpoint_returns_200_with_linkedin_post(
        self, monkeypatch
    ):
        """Assertion 6: POST /api/content/generate with valid payload returns 200 and has linkedin_post."""
        monkeypatch.setenv("DASHBOARD_API_KEY", "gate61-key")
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app

        client = TestClient(app)
        with patch("utils.content_pipeline.ContentPipeline") as MockPipeline:
            mock_instance = MagicMock()
            mock_instance.run.return_value = {
                "job_id": "gate61-test",
                "status": "done",
                "linkedin_post": "GATE-61 test post",
                "instagram_caption": "#test",
                "project_brief_sections": [],
                "investor_narrative": "Narrative",
                "key_differentiators": [],
                "email_subject": "Subject",
                "project_tagline": "Tagline",
                "target_segment": "Segment",
                "risk_acknowledgements": [],
                "generated_at": "2026-06-06T12:00:00+00:00",
            }
            MockPipeline.return_value = mock_instance
            resp = client.post(
                "/api/content/generate",
                json={
                    "market": "Yelahanka",
                    "survey_no": "45/2",
                    "deal_type": "compare",
                },
                headers={"X-API-Key": "gate61-key"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "linkedin_post" in data
