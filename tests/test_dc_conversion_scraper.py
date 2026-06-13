"""Tests for DC conversion scraper (GATE-94, T-1153)."""

import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


def test_parse_dc_html_extracts_records():
    from scrapers.dc_conversion_scraper import _parse_dc_html
    html = """
    <table>
        <tr><th>App No</th><th>Village</th><th>Survey</th><th>Extent</th><th>From</th><th>To</th><th>Applicant</th><th>Status</th><th>Date</th></tr>
        <tr><td>DC/2024/001</td><td>Venkatala</td><td>45/2</td><td>1.5</td><td>Agri</td><td>Residential</td><td>John Doe</td><td>Approved</td><td>01-06-2024</td></tr>
    </table>
    """
    records = _parse_dc_html(html)
    assert len(records) == 1
    assert records[0]["application_no"] == "DC/2024/001"
    assert records[0]["village"] == "Venkatala"
    assert records[0]["survey_no"] == "45/2"
    assert records[0]["status"] == "Approved"


def test_parse_dc_html_empty_on_no_table():
    from scrapers.dc_conversion_scraper import _parse_dc_html
    records = _parse_dc_html("<html>No data</html>")
    assert records == []


def test_market_for_village():
    from scrapers.dc_conversion_scraper import market_for_village
    assert market_for_village("Venkatala") == "Yelahanka"
    assert market_for_village("Devanahalli") == "Devanahalli"
    assert market_for_village("Unknown") is None


def test_scraper_returns_empty_on_http_error():
    from scrapers.dc_conversion_scraper import run_scan
    with patch("scrapers.dc_conversion_scraper.HAS_HTTPX", True):
        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.post.return_value.status_code = 500
            mock_client.return_value.__enter__.return_value = mock_instance
            results = run_scan(villages=["Venkatala"])
    assert results == []
