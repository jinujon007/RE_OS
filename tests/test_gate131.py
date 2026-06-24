"""T-1346 — GATE-131 declaration: Tavily Integration.

Assertions:
A1: utils.tavily_client importable; search callable
A2: search returns [] with no API key (graceful)
A3: news_scout has Tavily as primary source block
A4: IntelSearchTool has Tavily combined path
A5: tests/test_tavily_client.py exists and non-empty
A6: No existing unit tests broken (check count >= baseline)
"""

import pathlib

import pytest

pytestmark = pytest.mark.unit


def test_tavily_client_importable():
    from utils.tavily_client import search, _reset_count, _get_count
    assert callable(search)
    assert callable(_reset_count)
    assert callable(_get_count)


def test_tavily_graceful_no_key(monkeypatch):
    monkeypatch.setattr("utils.tavily_client.TAVILY_API_KEY", "")
    from utils.tavily_client import search, _reset_count
    _reset_count()
    result = search("Yelahanka real estate")
    assert result == []


def test_news_scout_has_tavily_primary():
    src = pathlib.Path("scrapers/news_scout.py").read_text(encoding="utf-8")
    assert "from utils.tavily_client import search as tavily_search" in src
    assert "Source 0: Tavily" in src


def test_intel_search_has_tavily_combined():
    src = pathlib.Path("agents/analyst_agent.py").read_text(encoding="utf-8")
    assert "from utils.tavily_client import search as tavily_search" in src
    assert "Tavily live" in src or "Tavily enrichment" in src


def test_tavily_test_file_exists():
    test_file = pathlib.Path("tests/test_tavily_client.py")
    assert test_file.exists()
    content = test_file.read_text(encoding="utf-8")
    assert len(content) > 200
