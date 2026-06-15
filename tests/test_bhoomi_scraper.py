"""Unit tests for BhoomiScraper (T-985 — Sprint 56 Land Intelligence)."""

import pytest
import urllib.error
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestBhoomiScraper:
    def test_bhoomi_parses_valid_response(self):
        from scrapers.bhoomi_scraper import _parse_response

        body = {
            "owner_name": "Venkatesh Gowda",
            "land_nature": "agricultural",
            "khata_no": "KH-1234",
            "area_guntas": 2.5,
        }
        result = _parse_response(body, "45/2", "Devanahalli")
        assert result["bhoomi_status"] == "live"
        assert result["owner_name"] == "Venkatesh Gowda"
        assert result["land_nature"] == "agricultural"
        assert result["khata_no"] == "KH-1234"

    def test_bhoomi_sets_land_nature(self):
        from scrapers.bhoomi_scraper import _parse_response

        body = {"owner_name": "Test", "land_nature": "revenue"}
        result = _parse_response(body, "10/1", "Yelahanka")
        assert result["land_nature"] == "revenue"

        body2 = {"owner_name": "Test2", "land_nature": "unknown_type"}
        result2 = _parse_response(body2, "10/2", "Yelahanka")
        assert result2["land_nature"] == "unknown"

    def test_bhoomi_handles_404_gracefully(self):
        from scrapers.bhoomi_scraper import fetch

        with patch(
            "urllib.request.urlopen", side_effect=Exception("Connection refused")
        ):
            result = fetch("99/99", "Nonexistent")
            assert result["bhoomi_status"] == "unavailable"

    def test_bhoomi_retries_on_transient_failure(self):
        from scrapers.bhoomi_scraper import fetch, _MAX_RETRIES

        call_count = 0

        def _fail_then_succeed(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= _MAX_RETRIES:
                raise ConnectionError("Transient failure")
            mock_resp = MagicMock()
            mock_resp.read.return_value = (
                b'{"owner_name":"Retry Success","land_nature":"revenue"}'
            )
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=_fail_then_succeed):
            result = fetch("10/1", "Yelahanka")
            assert result["bhoomi_status"] == "live"
            assert result["owner_name"] == "Retry Success"
            assert call_count == _MAX_RETRIES + 1

    def test_bhoomi_parse_encumbrances_string(self):
        from scrapers.bhoomi_scraper import _parse_response

        body = {
            "owner_name": "Test",
            "encumbrances": '[{"type":"mortgage","amount":500000}]',
        }
        result = _parse_response(body, "10/1", "Yelahanka")
        assert isinstance(result["encumbrances"], list)
        assert len(result["encumbrances"]) == 1

    def test_bhoomi_parse_missing_owner_name(self):
        from scrapers.bhoomi_scraper import _parse_response

        body = {"land_nature": "agricultural"}
        result = _parse_response(body, "10/1", "Yelahanka")
        assert result["owner_name"] == ""

    def test_bhoomi_rejects_invalid_survey_format(self):
        from scrapers.bhoomi_scraper import fetch

        result = fetch("invalid", "Yelahanka")
        assert result["bhoomi_status"] == "unavailable"
        assert "invalid survey_no" in result.get("error", "")

    def test_bhoomi_handles_rate_limit(self):
        from scrapers.bhoomi_scraper import fetch

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "http://test", 429, "Too Many", {}, None
            ),
        ):
            result = fetch("45/2", "Yelahanka")
            assert result["bhoomi_status"] == "unavailable"
