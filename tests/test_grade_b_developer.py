"""T-1081 — Expand developer_scout.py with Grade B developer registry

Three assertions:
1. GRADE_B_DEVELOPER_URLS in settings.py has ≥10 entries
2. DeveloperScout.scout_grade_b processes a Grade B developer without error
3. Grade B projects are tagged with developer_grade='B'
"""
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestGradeBDeveloperRegistry:
    """T-1081: Grade B developer registry."""

    def test_grade_b_developer_urls_has_10_entries(self):
        """Assertion 1: GRADE_B_DEVELOPER_URLS has at least 10 developer entries."""
        from config.settings import GRADE_B_DEVELOPER_URLS

        assert isinstance(GRADE_B_DEVELOPER_URLS, dict), (
            "GRADE_B_DEVELOPER_URLS must be a dict"
        )
        assert len(GRADE_B_DEVELOPER_URLS) >= 10, (
            f"Expected ≥10 Grade B developers, got {len(GRADE_B_DEVELOPER_URLS)}"
        )

        # Verify all keys are non-empty strings
        for name, url in GRADE_B_DEVELOPER_URLS.items():
            assert name and name.strip(), "Developer name must be non-empty"
            assert url and url.strip(), f"URL for {name} must be non-empty"
            assert url.startswith("http"), f"URL for {name} must start with http"

    def test_developer_scout_processes_grade_b_developer(self):
        """Assertion 2: scout_grade_b processes a Grade B developer and returns findings."""
        from scrapers.developer_scout import DeveloperScout, ScoutMemory

        with patch.object(ScoutMemory, "is_known", return_value=False):
            with patch.object(ScoutMemory, "mark_all", return_value=([{"project_name": "Test", "cid": "abc"}], [])):
                scout = DeveloperScout.__new__(DeveloperScout)
                scout.market = "Yelahanka"
                scout.memory = ScoutMemory("Yelahanka")
                scout.session = MagicMock()

                with patch.object(scout, "_requests_fetch_raw", return_value="<html><body>" + "Project " * 200 + "</body></html>"):
                    with patch("scrapers.developer_scout._clean_html", return_value="Test Project Yelahanka 2 BHK starting 45 lakhs. " * 20):
                        with patch("scrapers.developer_scout._ai_extract_developer", return_value=[
                            {"project_name": "Test Garden", "locality": "Yelahanka", "status": "New Launch"}
                        ]):
                            results = scout._scout_grade_b_developer("Test Dev", "https://test.dev/projects")

        assert len(results) >= 1, "Expected at least one finding from Grade B developer"
        assert results[0].get("developer_grade") == "B", (
            f"Expected developer_grade='B', got {results[0].get('developer_grade')!r}"
        )

    def test_grade_b_projects_stored_with_grade_b_tag(self):
        """Assertion 3: all projects from scout_grade_b are tagged developer_grade='B'."""
        from scrapers.developer_scout import DeveloperScout, ScoutMemory

        with patch.object(ScoutMemory, "is_known", return_value=False):
            with patch.object(ScoutMemory, "mark_all", return_value=(
                [
                    {"project_name": "A", "cid": "a"},
                    {"project_name": "B", "cid": "b"},
                ], []
            )):
                scout = DeveloperScout.__new__(DeveloperScout)
                scout.market = "Hebbal"
                scout.memory = ScoutMemory("Hebbal")
                scout.session = MagicMock()

                with patch.object(scout, "_requests_fetch_raw", return_value="<html>" + "content " * 200 + "</html>"):
                    with patch("scrapers.developer_scout._clean_html", return_value="North Bangalore project. " * 20):
                        with patch("scrapers.developer_scout._ai_extract_developer", return_value=[
                            {"project_name": "Green Homes", "locality": "Yelahanka"},
                            {"project_name": "Lake View", "locality": "Hebbal"},
                        ]):
                            results = scout._scout_grade_b_developer("Builder Co", "https://builder.co/projects")

        assert len(results) >= 1
        for r in results:
            assert r.get("developer_grade") == "B", (
                f"All Grade B projects must have developer_grade='B', got {r.get('developer_grade')!r}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
