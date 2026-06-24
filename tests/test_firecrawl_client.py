"""T-1340 — Firecrawl client unit tests.

Coverage:
A1: Importable without error
A2: scrape_url returns None with no API key
A3: search_query returns [] with no API key
A4: Req cap stops HTTP calls after limit (mock _safe_post)
A5: developer_scout imports firecrawl module
A6: portal_scout imports firecrawl module
A7: scrape_url returns None on empty content
A8: 429 rate-limit returns None
"""

import pathlib
import unittest.mock

import pytest

pytestmark = pytest.mark.unit


def test_importable():
    from utils.firecrawl_client import scrape_url, search_query, _reset_count, _get_count
    assert callable(scrape_url)
    assert callable(search_query)
    assert callable(_reset_count)
    assert callable(_get_count)


def test_scrape_url_none_without_key(monkeypatch):
    monkeypatch.setattr("utils.firecrawl_client.FIRECRAWL_API_KEY", "")
    from utils.firecrawl_client import scrape_url, _reset_count
    _reset_count()
    result = scrape_url("https://example.com")
    assert result is None


def test_search_query_empty_without_key(monkeypatch):
    monkeypatch.setattr("utils.firecrawl_client.FIRECRAWL_API_KEY", "")
    from utils.firecrawl_client import search_query, _reset_count
    _reset_count()
    result = search_query("test query")
    assert result == []


def test_scrape_url_respects_req_cap(monkeypatch):
    monkeypatch.setattr("utils.firecrawl_client.FIRECRAWL_API_KEY", "test-key")
    from utils.firecrawl_client import scrape_url, _reset_count, _get_count
    _reset_count()
    monkeypatch.setattr(
        "utils.firecrawl_client._safe_post",
        lambda *a, **kw: {"data": {"markdown": "content"}},
    )
    for i in range(12):
        scrape_url(f"https://example.com/{i}")
    assert _get_count() <= 10


def test_scrape_url_empty_content_returns_none(monkeypatch):
    monkeypatch.setattr("utils.firecrawl_client.FIRECRAWL_API_KEY", "test-key")
    from utils.firecrawl_client import scrape_url, _reset_count
    _reset_count()
    monkeypatch.setattr(
        "utils.firecrawl_client._safe_post",
        lambda *a, **kw: {"data": {"markdown": ""}},
    )
    result = scrape_url("https://example.com")
    assert result is None


def test_developer_scout_imports_firecrawl():
    src = pathlib.Path("scrapers/developer_scout.py").read_text()
    assert "firecrawl_client" in src
    assert "Firecrawl fallback" in src


def test_portal_scout_imports_firecrawl():
    src = pathlib.Path("scrapers/portal_scout.py").read_text()
    assert "firecrawl_client" in src
    assert "Firecrawl fallback" in src


def test_429_retry_then_returns_none(monkeypatch):
    monkeypatch.setattr("utils.firecrawl_client.FIRECRAWL_API_KEY", "test-key")
    from utils.firecrawl_client import scrape_url, _reset_count
    _reset_count()
    call_count = 0

    def _failing_safe_post(*a, **kw):
        nonlocal call_count
        call_count += 1
        return None

    monkeypatch.setattr("utils.firecrawl_client._safe_post", _failing_safe_post)
    result = scrape_url("https://example.com")
    assert result is None
    assert call_count == 2
