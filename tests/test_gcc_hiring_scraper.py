"""Tests for GCC hiring snapshot scraper (GATE-94, T-1152)."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


def test_scraper_returns_list_for_all_employers():
    from scrapers.gcc_hiring_scraper import run_snapshot
    from config.settings import GCC_TRACKED_EMPLOYERS

    with patch("scrapers.gcc_hiring_scraper.HAS_HTTPX", True):
        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.return_value.status_code = 200
            mock_instance.get.return_value.text = "<html>45 jobs found</html>"
            mock_client.return_value.__enter__.return_value = mock_instance
            results = run_snapshot(employers=GCC_TRACKED_EMPLOYERS)
    assert len(results) == len(GCC_TRACKED_EMPLOYERS)
    assert all("employer" in r and "posting_count" in r for r in results)


def test_scraper_returns_zero_on_http_error():
    from scrapers.gcc_hiring_scraper import run_snapshot
    from config.settings import GCC_TRACKED_EMPLOYERS

    with patch("scrapers.gcc_hiring_scraper.HAS_HTTPX", True):
        with patch("httpx.Client") as mock_client:
            mock_instance = MagicMock()
            mock_instance.get.return_value.status_code = 403
            mock_instance.get.return_value.text = ""
            mock_client.return_value.__enter__.return_value = mock_instance
            results = run_snapshot(
                employers=[{"employer": "NTT Data", "hub": "Manyata"}]
            )
    assert len(results) == 1
    assert results[0]["posting_count"] == 0
    assert "error" in results[0]


def test_scraper_falls_back_to_inbox_mode():
    from scrapers.gcc_hiring_scraper import run_snapshot

    with patch("scrapers.gcc_hiring_scraper._parse_inbox_files") as mock_parse:
        mock_parse.return_value = [
            {
                "employer": "TestCo",
                "hub": "TestHub",
                "posting_count": 100,
                "source": "inbox",
            }
        ]
        results = run_snapshot(mode="inbox")
    assert len(results) == 1
    assert results[0]["posting_count"] == 100


def test_extract_job_count_various_patterns():
    from scrapers.gcc_hiring_scraper import _extract_job_count_from_html

    assert _extract_job_count_from_html("45 jobs found") == 45
    assert _extract_job_count_from_html("Showing 1-20 of 1,234 jobs") == 1234
    assert _extract_job_count_from_html('"totalCount":567') == 567
    assert _extract_job_count_from_html("no jobs") is None


def test_imports_employers_from_settings_by_default():
    """F5 fix: run_snapshot uses settings.GCC_TRACKED_EMPLOYERS when no employers arg."""
    from scrapers.gcc_hiring_scraper import run_snapshot

    with patch("scrapers.gcc_hiring_scraper.HAS_HTTPX", False):
        from config.settings import GCC_TRACKED_EMPLOYERS

        results = run_snapshot()
    assert len(results) == len(GCC_TRACKED_EMPLOYERS)


def test_inbox_parses_real_json_file(tmp_path):
    """F2 fix: test inbox parsing with actual file I/O."""
    import json
    from scrapers.gcc_hiring_scraper import _parse_inbox_files

    inbox_dir = tmp_path / "gcc_hiring" / "inbox"
    inbox_dir.mkdir(parents=True)
    fixture = [{"employer": "TestCo", "hub": "TestHub", "posting_count": 75}]
    with open(inbox_dir / "snapshot.json", "w") as f:
        json.dump(fixture, f)
    with patch("scrapers.gcc_hiring_scraper.os.path.isdir", return_value=True):
        with patch(
            "scrapers.gcc_hiring_scraper.os.listdir", return_value=["snapshot.json"]
        ):
            with patch(
                "scrapers.gcc_hiring_scraper.os.path.join",
                return_value=str(inbox_dir / "snapshot.json"),
            ):
                with patch("builtins.open", side_effect=open):
                    results = _parse_inbox_files()
    assert len(results) == 1
    assert results[0]["posting_count"] == 75
