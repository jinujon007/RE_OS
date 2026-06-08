import pytest
pytestmark = pytest.mark.unit


def test_stage1_crew_task_names_excludes_scrape_listings():
    """scrape_listings Task must not be in the Stage 1 data crew task list."""
    from crews.market_intel_crew import _build_data_crew
    crew = _build_data_crew("Yelahanka")
    task_descriptions = [t.description for t in crew.tasks]
    for desc in task_descriptions:
        assert "listings_scraper" not in desc, (
            f"Found listings_scraper reference in task: {desc[:80]}"
        )
    task_names_combined = "\n".join(task_descriptions)
    assert "listings_scraper" not in task_names_combined
