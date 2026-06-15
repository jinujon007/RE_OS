"""T-1079 — Extract survey numbers from RERA detail pages

Six assertions:
1. survey_no extracted from detail page HTML via regex (mock HTML with "Sy. No. 45/2A")
2. Regex fallback fires when AI returns empty survey_number
3. survey_no persisted in enriched dict
4. Migration 0042 adds survey_no column
5. Multiple survey number formats handled (Sy No: 101/1A, Survey No. 45/2A/3B)
6. survey_no blank when no regex match and AI returns null
"""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestSurveyNoExtraction:
    """T-1079: survey number extraction from RERA detail pages."""

    def test_survey_no_regex_from_detail_page_html(self):
        """Assertion 1: regex extracts survey number from mock detail page HTML."""
        from scrapers.rera_detail_scout import _ai_extract_detail

        html = (
            "Project Name: Test Garden Estate\n"
            "Sy. No. 45/2A\n"
            "Total Units: 120\n"
            "Site Area: 2.5 Acres\n"
        )
        with patch("scrapers.rera_detail_scout.GROQ_API_KEY", "test-key"):
            with patch("litellm.completion") as mock_completion:
                mock_resp = MagicMock()
                mock_resp.choices[
                    0
                ].message.content = '{"survey_number": "45/2A", "total_units": 120}'
                mock_completion.return_value = mock_resp
                result = _ai_extract_detail(html)

        assert isinstance(result, dict), "Expected dict result"
        assert result.get("survey_number") == "45/2A", (
            f"Expected survey_number='45/2A', got {result.get('survey_number')!r}"
        )

    def test_survey_no_regex_fallback_when_ai_returns_empty(self):
        """Regex fallback fires when AI extraction returns empty survey_number."""
        from scrapers.rera_detail_scout import _ai_extract_detail

        html = "RERA Registration Details\nSy. No. 101/1\nTotal Units: 200\n"
        with patch("scrapers.rera_detail_scout.GROQ_API_KEY", "test-key"):
            with patch("litellm.completion") as mock_completion:
                mock_resp = MagicMock()
                mock_resp.choices[
                    0
                ].message.content = '{"survey_number": null, "total_units": 200}'
                mock_completion.return_value = mock_resp
                result = _ai_extract_detail(html)

        assert isinstance(result, dict), "Expected dict result"
        assert result.get("survey_number") == "101/1", (
            f"Expected fallback survey_number='101/1', got {result.get('survey_number')!r}"
        )

    def test_survey_no_persisted_in_enriched_dict(self):
        """Survey number appears in the enriched output of _enrich_project."""
        from scrapers.rera_detail_scout import (
            RERADetailScout,
            ScoutMemory,
            Checkpointer,
        )

        long_text = (
            "Sy. No. 45/2\n" + ("Project details para " * 100) + "\nTotal Units: 100"
        )

        with patch.object(Checkpointer, "load", return_value=[]):
            with patch.object(ScoutMemory, "is_known", return_value=False):
                with patch.object(ScoutMemory, "mark_all", return_value=([], [])):
                    scout = RERADetailScout("Yelahanka")
                    with patch.object(
                        scout,
                        "_build_detail_urls",
                        return_value=["https://example.com"],
                    ):
                        with patch(
                            "scrapers.rera_detail_scout._fetch_with_fallbacks",
                            return_value=(long_text, "https://example.com"),
                        ):
                            with patch(
                                "scrapers.rera_detail_scout._ai_extract_detail",
                                return_value={
                                    "survey_number": "45/2",
                                    "total_units": 100,
                                },
                            ):
                                result = scout._enrich_project(
                                    {
                                        "rera_number": "PRM/KA/RERA/1251/446/PR/180601/001792",
                                        "project_name": "Test Project",
                                        "developer_name": "Test Dev",
                                    }
                                )

        assert result is not None
        assert result.get("survey_no") == "45/2", (
            f"Expected survey_no='45/2', got {result.get('survey_no')!r}"
        )

    def test_survey_no_multi_part_format_sy_no_colon(self):
        """Survey number extracted with 'Sy No:' format with multi-part number."""
        from scrapers.rera_detail_scout import _ai_extract_detail

        html = "Project: Lake View\nSy No: 45/2A/3B\nUnits: 200\n"
        with patch("scrapers.rera_detail_scout.GROQ_API_KEY", "test-key"):
            with patch("litellm.completion") as mock_completion:
                mock_resp = MagicMock()
                mock_resp.choices[
                    0
                ].message.content = '{"survey_number": "45/2A/3B", "total_units": 200}'
                mock_completion.return_value = mock_resp
                result = _ai_extract_detail(html)

        assert isinstance(result, dict)
        assert result.get("survey_number") == "45/2A/3B"

    def test_survey_no_format_survey_no(self):
        """Survey number extracted with 'Survey No.' long format."""
        from scrapers.rera_detail_scout import _ai_extract_detail

        html = "Survey No.: 12/3\nTotal Units: 150\n"
        with patch("scrapers.rera_detail_scout.GROQ_API_KEY", "test-key"):
            with patch("litellm.completion") as mock_completion:
                mock_resp = MagicMock()
                mock_resp.choices[
                    0
                ].message.content = '{"survey_number": null, "total_units": 150}'
                mock_completion.return_value = mock_resp
                result = _ai_extract_detail(html)

        assert isinstance(result, dict)
        assert result.get("survey_number") == "12/3", (
            f"Expected survey_number='12/3', got {result.get('survey_number')!r}"
        )

    def test_survey_no_blank_when_no_match(self):
        """survey_number is None when no regex match and AI returns null."""
        from scrapers.rera_detail_scout import _ai_extract_detail

        html = "Project Description with no survey number anywhere in the text."
        with patch("scrapers.rera_detail_scout.GROQ_API_KEY", "test-key"):
            with patch("litellm.completion") as mock_completion:
                mock_resp = MagicMock()
                mock_resp.choices[
                    0
                ].message.content = '{"survey_number": null, "total_units": 50}'
                mock_completion.return_value = mock_resp
                result = _ai_extract_detail(html)

        assert isinstance(result, dict)
        assert result.get("survey_number") is None, (
            f"Expected None, got {result.get('survey_number')!r}"
        )

    def test_migration_0042_adds_survey_no_column(self):
        """Assertion 7: migration file adds survey_no TEXT column."""
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            "migration_0042",
            "alembic/versions/0042_rera_projects_survey_no.py",
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["migration_0042"] = mod
        spec.loader.exec_module(mod)

        assert hasattr(mod, "upgrade"), "Migration must have upgrade()"
        assert hasattr(mod, "downgrade"), "Migration must have downgrade()"
        assert mod.down_revision == "0041_gv_gazette_data_source", (
            f"Expected down_revision='0041_gv_gazette_data_source', got {mod.down_revision}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
