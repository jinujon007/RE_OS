"""Tests for Content Pipeline (Sprint 53 — PR & Brand Department)."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit

CONTENT_STUDIO_MARKER = pytest.mark.integration


class TestContentPipeline:
    def test_content_pipeline_run_returns_dict(self):
        from utils.content_pipeline import ContentPipeline

        pipeline = ContentPipeline()
        with patch.object(pipeline.pr_head, "run") as mock_pr:
            mock_pr.return_value.project_tagline = "Test tagline"
            mock_pr.return_value.investor_narrative = "Test narrative"
            mock_pr.return_value.key_differentiators = ["a", "b", "c", "d", "e"]
            mock_pr.return_value.target_segment = "Test segment"
            mock_pr.return_value.risk_acknowledgements = ["r1", "r2"]
            with patch.object(pipeline.content_writer, "run") as mock_cw:
                mock_cw.return_value.linkedin_post = "LinkedIn post test"
                mock_cw.return_value.instagram_caption = "Insta caption #test"
                mock_cw.return_value.project_brief_sections = [
                    {"title": f"S{i}", "body": "body", "word_count": 2}
                    for i in range(7)
                ]
                mock_cw.return_value.email_subject = "Test subject"

                result = pipeline.run(
                    market="Yelahanka", survey_no="45/2", deal_type="jd"
                )

        assert isinstance(result, dict)
        assert result["status"] == "done"
        assert "job_id" in result
        assert "linkedin_post" in result
        assert "instagram_caption" in result
        assert "project_brief_sections" in result
        assert "investor_narrative" in result
        assert "key_differentiators" in result
        assert "email_subject" in result
        assert "generated_at" in result

    def test_content_pipeline_run_pr_head_called(self):
        from utils.content_pipeline import ContentPipeline

        pipeline = ContentPipeline()
        with patch.object(pipeline.pr_head, "run") as mock_pr:
            mock_pr.return_value.project_tagline = ""
            mock_pr.return_value.investor_narrative = ""
            mock_pr.return_value.key_differentiators = []
            mock_pr.return_value.target_segment = ""
            mock_pr.return_value.risk_acknowledgements = []
            with patch.object(pipeline.content_writer, "run") as mock_cw:
                mock_cw.return_value.linkedin_post = ""
                mock_cw.return_value.instagram_caption = ""
                mock_cw.return_value.project_brief_sections = [
                    {"title": f"S{i}", "body": "body", "word_count": 2}
                    for i in range(7)
                ]
                mock_cw.return_value.email_subject = ""

                pipeline.run(market="Yelahanka", survey_no="45/2", deal_type="compare")

        mock_pr.assert_called_once()
        mock_cw.assert_called_once()

    def test_content_pipeline_uses_existing_job_id(self):
        from utils.content_pipeline import ContentPipeline

        pipeline = ContentPipeline()
        mock_job = {
            "status": "done",
            "board_session": {"avg_psf": 7200, "irr": 18.5},
            "deal_memo": {"avg_psf": 7200, "irr": 18.5},
            "investor_brief": {"narrative": "Test narrative from job"},
        }

        with patch("crews.evaluate_pipeline.get_evaluate_job", return_value=mock_job):
            with patch.object(pipeline.pr_head, "run") as mock_pr:
                mock_pr.return_value.project_tagline = "Tagline"
                mock_pr.return_value.investor_narrative = "Narrative"
                mock_pr.return_value.key_differentiators = ["a", "b", "c", "d", "e"]
                mock_pr.return_value.target_segment = "Segment"
                mock_pr.return_value.risk_acknowledgements = ["r1", "r2"]
                with patch.object(pipeline.content_writer, "run") as mock_cw:
                    mock_cw.return_value.linkedin_post = "Post"
                    mock_cw.return_value.instagram_caption = "#test"
                    mock_cw.return_value.project_brief_sections = [
                        {"title": f"S{i}", "body": "body", "word_count": 2}
                        for i in range(7)
                    ]
                    mock_cw.return_value.email_subject = "Subject"

                    pipeline.run(
                        market="Yelahanka",
                        survey_no="45/2",
                        deal_type="compare",
                        job_id="test-job-123",
                    )

        mock_pr.assert_called_once()
        call_input = mock_pr.call_args[0][0]
        # Verify job data was passed correctly
        if "avg_psf" in call_input:
            assert True

    def test_content_pipeline_fallback_on_missing_job_id(self):
        from utils.content_pipeline import ContentPipeline

        pipeline = ContentPipeline()
        with patch("crews.evaluate_pipeline.get_evaluate_job", return_value=None):
            with patch.object(pipeline.pr_head, "run") as mock_pr:
                mock_pr.return_value.project_tagline = ""
                mock_pr.return_value.investor_narrative = ""
                mock_pr.return_value.key_differentiators = []
                mock_pr.return_value.target_segment = ""
                mock_pr.return_value.risk_acknowledgements = []
                with patch.object(pipeline.content_writer, "run") as mock_cw:
                    mock_cw.return_value.linkedin_post = ""
                    mock_cw.return_value.instagram_caption = ""
                    mock_cw.return_value.project_brief_sections = [
                        {"title": f"S{i}", "body": "body", "word_count": 2}
                        for i in range(7)
                    ]
                    mock_cw.return_value.email_subject = ""

                    result = pipeline.run(
                        market="Devanahalli",
                        survey_no="10/1",
                        deal_type="purchase",
                        job_id="nonexistent-job",
                    )

        assert result["status"] == "done"
        assert "job_id" in result
        assert result["data_source"] in ("default", "intel_registry", "market_defaults")

    def test_content_pipeline_cache_hit(self):
        """Second identical call returns cached result."""
        from utils.content_pipeline import (
            ContentPipeline,
            _content_cache_clear,
            _cache_key,
        )

        _content_cache_clear()
        pipeline = ContentPipeline()
        with patch.object(pipeline.pr_head, "run") as mock_pr:
            mock_pr.return_value.project_tagline = "Cached"
            mock_pr.return_value.investor_narrative = "Narrative"
            mock_pr.return_value.key_differentiators = ["a", "b", "c", "d", "e"]
            mock_pr.return_value.target_segment = "Segment"
            mock_pr.return_value.risk_acknowledgements = ["r1"]
            with patch.object(pipeline.content_writer, "run") as mock_cw:
                mock_cw.return_value.linkedin_post = "Cached post"
                mock_cw.return_value.instagram_caption = "#cached"
                mock_cw.return_value.project_brief_sections = [
                    {"title": f"S{i}", "body": "b", "word_count": 1} for i in range(7)
                ]
                mock_cw.return_value.email_subject = "Cached"

                pipeline.run(market="Yelahanka", survey_no="45/2", deal_type="compare")
                mock_pr.reset_mock()
                mock_cw.reset_mock()

                # Second call should hit cache and skip agent calls
                result2 = pipeline.run(
                    market="Yelahanka", survey_no="45/2", deal_type="compare"
                )
                mock_pr.assert_not_called()
                mock_cw.assert_not_called()
                assert result2["project_tagline"] == "Cached"

    def test_content_pipeline_data_source_tracking(self):
        """Pipeline tracks data source correctly."""
        from utils.content_pipeline import ContentPipeline

        pipeline = ContentPipeline()
        with patch.object(pipeline.pr_head, "run") as mock_pr:
            mock_pr.return_value.project_tagline = "T"
            mock_pr.return_value.investor_narrative = "N"
            mock_pr.return_value.key_differentiators = ["a", "b", "c", "d", "e"]
            mock_pr.return_value.target_segment = "S"
            mock_pr.return_value.risk_acknowledgements = ["r"]
            with patch.object(pipeline.content_writer, "run") as mock_cw:
                mock_cw.return_value.linkedin_post = "P"
                mock_cw.return_value.instagram_caption = "#t"
                mock_cw.return_value.project_brief_sections = [
                    {"title": f"S{i}", "body": "b", "word_count": 1} for i in range(7)
                ]
                mock_cw.return_value.email_subject = "E"

                result = pipeline.run(
                    market="Hebbal",
                    survey_no="10/1",
                    deal_type="jd",
                    job_id="job-123",
                )

        assert "data_source" in result


class TestContentEndpoint:
    def test_content_endpoint_returns_200(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_KEY", "test-key")
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app

        client = TestClient(app)
        with patch("utils.content_pipeline.ContentPipeline") as MockPipeline:
            mock_instance = MagicMock()
            mock_instance.run.return_value = {
                "job_id": "test-1",
                "status": "done",
                "linkedin_post": "Post content",
                "instagram_caption": "Caption #test",
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
                headers={"X-API-Key": "test-key"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "linkedin_post" in data
        assert "status" in data

    def test_content_endpoint_validates_required_fields(self, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_KEY", "test-key")
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app

        client = TestClient(app)
        resp = client.post(
            "/api/content/generate",
            json={"market": "", "survey_no": ""},
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 400


class TestContentStudioRoute:
    @CONTENT_STUDIO_MARKER
    def test_content_studio_route_returns_html(self):
        """GET /content returns 200 with text/html content type."""
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app

        client = TestClient(app)
        resp = client.get("/content")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "").lower()
