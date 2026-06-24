"""GATE-130 — Firecrawl Integration: Replace Brittle Portal Scrapers.

5 assertions (all code-verifiable without Docker):
A1: firecrawl_client importable and scrape_url/search_query/_reset_count/_get_count callable
A2: graceful no-key path (None / []) without exception
A3: developer_scout has Firecrawl fallback in source code
A4: portal_scout has Firecrawl fallback in source code
A5: firecrawl_client test suite passes (imported via pytest)
"""

import pathlib

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_gate130_a1_importable():
    from utils.firecrawl_client import scrape_url, search_query, _reset_count, _get_count
    assert callable(scrape_url)
    assert callable(search_query)
    assert callable(_reset_count)
    assert callable(_get_count)


def test_gate130_a2_graceful_no_key(monkeypatch):
    monkeypatch.setattr("utils.firecrawl_client.FIRECRAWL_API_KEY", "")
    from utils.firecrawl_client import scrape_url, search_query, _reset_count
    _reset_count()
    assert scrape_url("https://example.com") is None
    assert search_query("test query") == []


def test_gate130_a3_developer_scout_fallback():
    src = pathlib.Path("scrapers/developer_scout.py").read_text()
    assert "Firecrawl fallback" in src, \
        "developer_scout.py must reference Firecrawl fallback"


def test_gate130_a4_portal_scout_fallback():
    src = pathlib.Path("scrapers/portal_scout.py").read_text()
    assert "Firecrawl fallback" in src, \
        "portal_scout.py must reference Firecrawl fallback"


def test_gate130_a5_firecrawl_tests_pass():
    result = __import__("pytest").main([
        "-q", "--no-header",
        str(pathlib.Path("tests/test_firecrawl_client.py")),
    ])
    assert result == 0 or result == pytest.ExitCode.OK, \
        f"firecrawl client tests failed with exit code {result}"
