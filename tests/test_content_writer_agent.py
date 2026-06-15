"""Tests for Content Writer Agent (Sprint 53 — PR & Brand Department)."""

import pytest
from dataclasses import fields

pytestmark = pytest.mark.unit


class TestContentPackDataclass:
    def test_content_pack_is_dataclass(self):
        from agents.content_writer_agent import ContentPack

        pack = ContentPack(
            linkedin_post="Test post",
            instagram_caption="Test caption #test",
            project_brief_sections=[{"title": "Test", "body": "Body", "word_count": 2}],
            email_subject="Test subject",
        )
        assert isinstance(pack, ContentPack)
        assert len(fields(ContentPack)) == 4

    def test_linkedin_post_under_280_chars(self):
        from agents.content_writer_agent import ContentWriterAgent

        agent = ContentWriterAgent()
        pack = agent._fallback_content_pack()
        assert len(pack.linkedin_post) <= 280

    def test_instagram_caption_has_hashtags(self):
        from agents.content_writer_agent import ContentWriterAgent

        agent = ContentWriterAgent()
        pack = agent._fallback_content_pack()
        assert "#" in pack.instagram_caption

    def test_project_brief_has_7_sections(self):
        from agents.content_writer_agent import ContentWriterAgent

        agent = ContentWriterAgent()
        sections = agent._build_default_sections()
        assert len(sections) == 7
        for s in sections:
            assert "title" in s
            assert "body" in s
            assert "word_count" in s

    def test_email_subject_under_60_chars(self):
        from agents.content_writer_agent import ContentWriterAgent

        agent = ContentWriterAgent()
        pack = agent._fallback_content_pack()
        assert len(pack.email_subject) <= 60

    def test_section_names_are_defined(self):
        from agents.content_writer_agent import SECTION_NAMES

        expected = [
            "Overview",
            "Market Context",
            "Product Concept",
            "Financial Case",
            "Risk Landscape",
            "Team & Track Record",
            "Call to Action",
        ]
        assert SECTION_NAMES == expected

    def test_content_pack_to_dict(self):
        from agents.content_writer_agent import ContentPack

        pack = ContentPack(
            linkedin_post="Post",
            instagram_caption="Caption #test",
            project_brief_sections=[],
            email_subject="Subject",
        )
        d = pack.to_dict()
        assert isinstance(d, dict)
        assert d["linkedin_post"] == "Post"
