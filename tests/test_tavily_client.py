"""T-1345 — Tavily client unit tests.

Coverage:
A1: Importable without error
A2: search returns [] with no API key
A3: Req cap stops HTTP calls after limit
A4: news_scout imports tavily_client
A5: IntelSearchTool has Tavily path
A6: search returns results on mock success
A7: 429 rate-limit returns []
A8: monthly_quota_remaining returns None without key
A9: search returns [] when monthly quota exhausted
"""

import pathlib
import unittest.mock

import pytest

pytestmark = pytest.mark.unit


def test_importable():
    from utils.tavily_client import search, _reset_count, _get_count
    assert callable(search)
    assert callable(_reset_count)
    assert callable(_get_count)


def test_search_empty_without_key(monkeypatch):
    monkeypatch.setattr("utils.tavily_client.TAVILY_API_KEY", "")
    from utils.tavily_client import search, _reset_count
    _reset_count()
    result = search("test query")
    assert result == []


def test_search_respects_req_cap(monkeypatch):
    monkeypatch.setattr("utils.tavily_client.TAVILY_API_KEY", "test-key")
    from utils.tavily_client import search, _reset_count, _get_count
    _reset_count()
    monkeypatch.setattr(
        "utils.tavily_client._do_search",
        lambda *a, **kw: {"results": [{"title": "Test", "url": "http://example.com", "content": "test", "published_date": "2026-01-01"}]},
    )
    for i in range(12):
        search(f"query {i}")
    assert _get_count() <= 10


def test_search_returns_results_on_success(monkeypatch):
    monkeypatch.setattr("utils.tavily_client.TAVILY_API_KEY", "test-key")
    from utils.tavily_client import search, _reset_count
    _reset_count()
    monkeypatch.setattr(
        "utils.tavily_client._do_search",
        lambda *a, **kw: {"results": [{"title": "Test Article", "url": "https://example.com/article", "content": "Real estate news content", "published_date": "2026-01-15"}]},
    )
    results = search("real estate Yelahanka", market="Yelahanka")
    assert len(results) == 1
    assert results[0]["title"] == "Test Article"
    assert results[0]["url"] == "https://example.com/article"
    assert results[0]["content"] == "Real estate news content"
    assert results[0]["published_date"] == "2026-01-15"


def test_news_scout_has_tavily_primary_block():
    src = pathlib.Path("scrapers/news_scout.py").read_text(encoding="utf-8")
    assert "from utils.tavily_client import search as tavily_search" in src
    assert "_reset_count as _tavily_reset" in src


def test_intel_search_tool_has_tavily_combined_path():
    src = pathlib.Path("agents/analyst_agent.py").read_text(encoding="utf-8")
    assert "from utils.tavily_client import search as tavily_search" in src
    assert "Tavily live" in src or "Tavily enrichment" in src


def test_429_retry_then_returns_empty(monkeypatch):
    monkeypatch.setattr("utils.tavily_client.TAVILY_API_KEY", "test-key")
    from utils.tavily_client import search, _reset_count
    _reset_count()
    call_count = 0

    def _failing_search(*a, **kw):
        nonlocal call_count
        call_count += 1
        return None

    monkeypatch.setattr("utils.tavily_client._do_search", _failing_search)
    result = search("https://example.com")
    assert result == []
    assert call_count == 2


def test_monthly_quota_remaining_none_without_key(monkeypatch):
    monkeypatch.setattr("utils.tavily_client.TAVILY_API_KEY", "")
    from utils.tavily_client import monthly_quota_remaining
    assert monthly_quota_remaining() is None


def test_monthly_quota_stops_search_when_exhausted(monkeypatch):
    monkeypatch.setattr("utils.tavily_client.TAVILY_API_KEY", "test-key")
    monkeypatch.setattr("utils.tavily_client._MONTHLY_STOP_AT", 5)
    monkeypatch.setattr("utils.tavily_client._read_monthly_count", lambda: 5)
    from utils.tavily_client import search, _reset_count
    _reset_count()
    result = search("test query")
    assert result == []
