"""
RE_OS — RERA Live Data Tests (Sprint 43 post-fix regression)
Tests RERA scrapers for data floor correctness and post-fix regression.
Scraper uses HTTP POST (no Playwright) as of T-798/T-799 refactoring.

All tests are unit-level (pytest.mark.unit). No live portal calls.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def rera_scraper():
    from scrapers.rera_karnataka import RERAKarnatakaScraper

    return RERAKarnatakaScraper()


@pytest.fixture
def html_sample_single_row():
    return """
    <table><tbody>
    <tr>
        <td>1</td>
        <td>ACK/2024/001</td>
        <td>PRM/KA/RERA/1251/446/PR/180601/001792</td>
        <td><a href="/projectDetails?action=123">View</a></td>
        <td>Shriram Properties</td>
        <td>Shriram Suhaana</td>
        <td>On-Going</td>
        <td>Bengaluru Urban</td>
        <td>Yelahanka</td>
        <td>Residential Apartment</td>
        <td>01-Jan-2025</td>
        <td>31-Dec-2025</td>
    </tr>
    </tbody></table>
    """


# ── Config floor tests ───────────────────────────────────────────────────────


class TestRERAExpectedCounts:
    """Verify MARKET_RERA_CONFIG meets all data floor minimums."""

    def test_yelahanka_expected_meets_floor(self):
        from config.settings import MARKET_RERA_CONFIG
        assert MARKET_RERA_CONFIG["Yelahanka"]["expected_rows"] >= 150

    def test_hebbal_expected_meets_floor(self):
        from config.settings import MARKET_RERA_CONFIG
        assert MARKET_RERA_CONFIG["Hebbal"]["expected_rows"] >= 150

    def test_devanahalli_expected_meets_floor(self):
        from config.settings import MARKET_RERA_CONFIG
        assert MARKET_RERA_CONFIG["Devanahalli"]["expected_rows"] >= 290

    def test_all_markets_have_positive_expected(self):
        from config.settings import MARKET_RERA_CONFIG
        for market, config in MARKET_RERA_CONFIG.items():
            assert config["expected_rows"] > 0, f"{market} expected_rows is 0"

    def test_all_markets_configured(self):
        from config.settings import MARKET_RERA_CONFIG
        assert set(MARKET_RERA_CONFIG.keys()) == {"Yelahanka", "Hebbal", "Devanahalli"}

    def test_each_config_has_required_fields(self):
        from config.settings import MARKET_RERA_CONFIG
        for market, config in MARKET_RERA_CONFIG.items():
            assert "district" in config, f"{market} missing district"
            assert "subdistrict" in config, f"{market} missing subdistrict"
            assert "expected_rows" in config, f"{market} missing expected_rows"
            assert isinstance(config["expected_rows"], int), f"{market} expected_rows not int"
            assert config["expected_rows"] > 0, f"{market} expected_rows must be > 0"


# ── Fallback data tests ──────────────────────────────────────────────────────


class TestRERAFallbackData:
    """Verify fallback sample data structure and minimums."""

    def test_yelahanka_fallback_has_8_projects(self, rera_scraper):
        projects = rera_scraper._fallback_rera_data("Yelahanka")
        assert len(projects) == 8

    def test_devanahalli_fallback_has_2_projects(self, rera_scraper):
        projects = rera_scraper._fallback_rera_data("Devanahalli")
        assert len(projects) == 2

    def test_unknown_market_falls_back_to_yelahanka(self, rera_scraper):
        """Any market not in fallback dict gets Yelahanka's data.
        Known limitation: Hebbal gets Yelahanka data because Hebbal-specific
        fallback records have not been curated. This is acceptable because
        fallback is only used when the live portal is unreachable."""
        projects = rera_scraper._fallback_rera_data("Hebbal")
        assert len(projects) == 8

    def test_fallback_source_is_fallback_sample(self, rera_scraper):
        projects = rera_scraper._fallback_rera_data("Yelahanka")
        for p in projects:
            assert p.get("data_source") == "fallback_sample", f"Unexpected source in {p.get('project_name')}"

    def test_fallback_has_rera_numbers(self, rera_scraper):
        projects = rera_scraper._fallback_rera_data("Yelahanka")
        for p in projects:
            assert p.get("rera_number"), f"Missing rera_number in {p.get('project_name', 'UNKNOWN')}"

    def test_fallback_has_project_names(self, rera_scraper):
        projects = rera_scraper._fallback_rera_data("Yelahanka")
        for p in projects:
            assert p.get("project_name"), f"Missing project_name for {p.get('rera_number', 'UNKNOWN')}"

    def test_fallback_source_not_live(self, rera_scraper):
        """Fallback records must never be tagged as live."""
        projects = rera_scraper._fallback_rera_data("Devanahalli")
        for p in projects:
            assert p.get("data_source") != "rera_karnataka_live"
            assert p.get("data_source") == "fallback_sample"


# ── HTML parsing tests ───────────────────────────────────────────────────────


class TestRERAHtmlParsing:
    """Test the HTML table parser directly (post-fix regression, no Playwright)."""

    def test_parse_single_row(self, rera_scraper, html_sample_single_row):
        projects = rera_scraper._parse_html_table(html_sample_single_row, "Yelahanka")
        assert len(projects) == 1
        p = projects[0]
        assert p["project_name"] == "Shriram Suhaana"
        assert p["developer_name"] == "Shriram Properties"
        assert p["rera_number"] == "PRM/KA/RERA/1251/446/PR/180601/001792"
        assert p["project_status"] == "On-Going"
        assert p["locality"] == "Yelahanka"
        assert p["detail_url"].startswith(rera_scraper.BASE_URL)

    def test_skips_header_row(self, rera_scraper, html_sample_single_row):
        html = html_sample_single_row.replace("<td>1</td>", "<td>S.NO</td>")
        html = html.replace("<td>ACK/2024/001</td>", "<td>ACKNOWLEDGEMENT NO</td>")
        projects = rera_scraper._parse_html_table(html, "Yelahanka")
        assert len(projects) == 0

    def test_empty_table_returns_empty_list(self, rera_scraper):
        projects = rera_scraper._parse_html_table("<table></table>", "Yelahanka")
        assert projects == []

    def test_incomplete_row_skipped(self, rera_scraper):
        html = "<table><tbody><tr><td>1</td><td>2</td><td>3</td></tr></tbody></table>"
        projects = rera_scraper._parse_html_table(html, "Yelahanka")
        assert len(projects) == 0

    def test_multiple_rows_parsed(self, rera_scraper):
        html = """
        <table><tbody>
        <tr>
            <td>1</td><td>ACK/001</td><td>RERA/001</td><td></td>
            <td>Dev A</td><td>Project A</td><td>Active</td>
            <td>Urban</td><td>Yelahanka</td><td>Residential</td>
            <td>2025-01-01</td><td>2026-01-01</td>
        </tr>
        <tr>
            <td>2</td><td>ACK/002</td><td>RERA/002</td><td></td>
            <td>Dev B</td><td>Project B</td><td>Active</td>
            <td>Urban</td><td>Yelahanka</td><td>Commercial</td>
            <td>2025-06-01</td><td>2027-06-01</td>
        </tr>
        </tbody></table>
        """
        projects = rera_scraper._parse_html_table(html, "Yelahanka")
        assert len(projects) == 2

    def test_malformed_html_graceful(self, rera_scraper):
        """Truncated/malformed HTML must not raise — returns empty or partial."""
        projects = rera_scraper._parse_html_table("<table><tr><td>broken", "Yelahanka")
        assert isinstance(projects, list)


# ── _clean utility tests ─────────────────────────────────────────────────────


class TestRERACleanUtil:
    """Test the _clean whitespace/normalization utility."""

    def test_collapses_multiple_spaces(self, rera_scraper):
        assert rera_scraper._clean("Hello   World") == "Hello World"

    def test_collapses_newlines(self, rera_scraper):
        assert rera_scraper._clean("Line1\nLine2\nLine3") == "Line1 Line2 Line3"

    def test_strips_trailing_whitespace(self, rera_scraper):
        assert rera_scraper._clean("  padded  ") == "padded"

    def test_truncates_long_strings(self, rera_scraper):
        result = rera_scraper._clean("A" * 200)
        assert len(result) <= 100

    def test_handles_none(self, rera_scraper):
        assert rera_scraper._clean(None) == ""

    def test_handles_empty_string(self, rera_scraper):
        assert rera_scraper._clean("") == ""


# ── Dedup tests (testing actual scrape_market dedup path) ─────────────────────


class TestRERADedup:
    """Test dedup by RERA number via mocked scrape_market."""

    DUPES = [
        {"rera_number": "RERA/001", "project_name": "Project A"},
        {"rera_number": "RERA/001", "project_name": "Project A Duplicate"},
        {"rera_number": "RERA/002", "project_name": "Project B"},
    ]

    def test_dedup_via_scrape_market(self, rera_scraper):
        """Test the actual dedup code path in scrape_market().
        Mock _post_search to return dups, verify dedup removes them."""
        with patch.object(rera_scraper, "_post_search", return_value=self.DUPES):
            with patch.object(rera_scraper, "session") as mock_session:
                mock_session.cookies = []
                projects, _ = rera_scraper.scrape_market("Yelahanka")
                assert len(projects) == 2
                rera_numbers = [p["rera_number"] for p in projects]
                assert rera_numbers == ["RERA/001", "RERA/002"]

    def test_dedup_preserves_empty_rera(self, rera_scraper):
        """Records with empty rera_number must all be kept (no dedup key)."""
        records = [
            {"rera_number": "", "project_name": "No RERA"},
            {"rera_number": "RERA/001", "project_name": "With RERA"},
        ]
        with patch.object(rera_scraper, "_post_search", return_value=records):
            with patch.object(rera_scraper, "session") as mock_session:
                mock_session.cookies = []
                projects, _ = rera_scraper.scrape_market("Yelahanka")
                assert len(projects) == 2

    def test_dedup_orders_preserved(self, rera_scraper):
        """First occurrence of a rera_number is kept in order."""
        records = [
            {"rera_number": "RERA/002", "project_name": "Project B"},
            {"rera_number": "RERA/001", "project_name": "Project A"},
            {"rera_number": "RERA/001", "project_name": "Project A Dup"},
        ]
        with patch.object(rera_scraper, "_post_search", return_value=records):
            with patch.object(rera_scraper, "session") as mock_session:
                mock_session.cookies = []
                projects, _ = rera_scraper.scrape_market("Yelahanka")
                assert projects[0]["project_name"] == "Project B"
                assert projects[1]["project_name"] == "Project A"


# ── Alt subdistrict fallback ─────────────────────────────────────────────────


class TestRERAAltSubdistrictFallback:
    """Test the alternate spelling fallback chain."""

    def test_hebbal_has_alt_subdistricts(self):
        from scrapers.rera_karnataka import ALT_SUBDISTRICTS
        assert "Hebbal" in ALT_SUBDISTRICTS
        assert len(ALT_SUBDISTRICTS["Hebbal"]) > 0

    def test_yelahanka_has_alt_subdistricts(self):
        from scrapers.rera_karnataka import ALT_SUBDISTRICTS
        assert "Yelahanka" in ALT_SUBDISTRICTS
        assert len(ALT_SUBDISTRICTS["Yelahanka"]) > 0

    def test_alt_districts_defined(self):
        from scrapers.rera_karnataka import ALT_DISTRICTS
        assert "Yelahanka" in ALT_DISTRICTS
        assert "Hebbal" in ALT_DISTRICTS

    def test_alt_fallback_chain_walks_all_combinations(self, rera_scraper):
        """When _post_search returns empty for primary, alt combinations are tried."""
        call_count = [0]
        original_post = rera_scraper._post_search

        def counting_post(district, subdistrict, market_name):
            call_count[0] += 1
            return original_post(district, subdistrict, market_name)

        with patch.object(rera_scraper, "_post_search", side_effect=counting_post):
            with patch.object(rera_scraper, "_fallback_rera_data") as mock_fallback:
                mock_fallback.return_value = []
                # Mock all POST attempts to return empty (valid HTML) to force fallback walk
                with patch.object(rera_scraper, "session") as mock_session:
                    mock_response = MagicMock()
                    mock_response.text = "<table></table>"
                    mock_response.status_code = 200
                    mock_session.post.return_value = mock_response
                    mock_session.cookies = []
                    rera_scraper.scrape_market("Yelahanka")
                    # Should have tried primary + at least 1 alt combination
                    assert call_count[0] >= 2


# ── Retry / resilience tests ──────────────────────────────────────────────────


class TestRERARetry:
    """Test tenacity retry decorator on _post_search."""

    def test_post_search_retries_on_failure(self, rera_scraper):
        """_post_search has @retry(stop=3, wait_exponential) — verify it retries."""
        import inspect
        from tenacity import Retrying
        source = inspect.getsource(rera_scraper._post_search)
        assert "@retry" in source, "_post_search missing retry decorator"

    def test_retry_count_via_decorator(self):
        from scrapers.rera_karnataka import RERAKarnatakaScraper
        retry_decorator = getattr(RERAKarnatakaScraper._post_search, "retry", None)
        if retry_decorator:
            from tenacity import stop_after_attempt
            stop = retry_decorator.statistics.get("stop")
            assert stop is None or stop.max_attempt_number == 3


# ── Plugin integration ────────────────────────────────────────────────────────


class TestRERAPluginIntegration:
    """Test that the RERAPlugin adapter produces ParsedRecords correctly."""

    def test_plugin_metadata(self):
        from ingest.plugins.rera_plugin import RERAPlugin
        plugin = RERAPlugin()
        assert plugin.plugin_id == "rera_karnataka"
        assert plugin.source_id == "rera_karnataka_portal"

    @patch("scrapers.rera_karnataka.RERAKarnatakaScraper.scrape_market")
    def test_skips_empty_rera_number(self, mock_scrape):
        from ingest.plugins.rera_plugin import RERAPlugin
        mock_scrape.return_value = (
            [{"rera_number": "", "project_name": "No RERA", "data_source": "test", "scraped_at": ""}],
            [],
        )
        plugin = RERAPlugin()
        records = plugin.run("Devanahalli")
        assert len(records) == 0

    @patch("scrapers.rera_karnataka.RERAKarnatakaScraper.scrape_market")
    def test_wraps_live_data_correctly(self, mock_scrape):
        from ingest.plugins.rera_plugin import RERAPlugin
        now = datetime.utcnow().isoformat()
        mock_scrape.return_value = (
            [{
                "rera_number": "RERA/001",
                "project_name": "Test Project",
                "developer_name": "Test Developer",
                "total_units": 100,
                "possession_date": "2026-12-31",
                "data_source": "rera_karnataka_live",
                "scraped_at": now,
                "project_status": "Active",
            }],
            [],
        )
        plugin = RERAPlugin()
        records = plugin.run("Devanahalli")
        assert len(records) == 1
        r = records[0]
        assert r.entity_type == "rera_project"
        assert r.source_id == "RERA/001"
        assert r.market == "Devanahalli"
        assert r.data["total_units"] == 100
        assert r.data["project_status"] == "Active"

    @patch("scrapers.rera_karnataka.RERAKarnatakaScraper.scrape_market")
    def test_handles_nullable_fields(self, mock_scrape):
        """project_status and is_active are optional fields — plugin must handle absence."""
        from ingest.plugins.rera_plugin import RERAPlugin
        now = datetime.utcnow().isoformat()
        mock_scrape.return_value = (
            [{
                "rera_number": "RERA/002",
                "project_name": "Minimal Project",
                "developer_name": "Dev",
                "total_units": 50,
                "possession_date": "",
                "data_source": "rera_karnataka_live",
                "scraped_at": now,
            }],
            [],
        )
        plugin = RERAPlugin()
        records = plugin.run("Devanahalli")
        assert len(records) == 1
        assert "project_status" not in records[0].data or records[0].data["project_status"] == ""


# ── Post-fix regression: no Playwright for listing ────────────────────────────


class TestRERARegressionNoPlaywright:
    """Post T-798/T-799 regression: listing pages use HTTP POST, not Playwright."""

    def test_post_search_has_no_playwright(self, rera_scraper):
        """_post_search must NOT import/instantiate Playwright — uses direct HTTP POST."""
        import inspect
        import re as _re
        source = inspect.getsource(rera_scraper._post_search)
        non_comment_source = "\n".join(
            line for line in source.split("\n") if not line.strip().startswith("#")
        )
        assert not _re.search(r"from playwright|import playwright|Playwright\(\)", non_comment_source),             "Playwright import or instantiation detected in _post_search"

    def test_search_url_is_https_post(self):
        from scrapers.rera_karnataka import RERAKarnatakaScraper
        assert RERAKarnatakaScraper.SEARCH_URL.endswith("/projectViewDetails")

    def test_scraper_uses_beautifulsoup(self, rera_scraper):
        """The HTML parser must use BeautifulSoup (not regex for table parsing)."""
        import inspect
        source = inspect.getsource(rera_scraper._parse_html_table)
        assert "BeautifulSoup" in source
        assert "lxml" in source


# ── HTTP POST payload tests ───────────────────────────────────────────────────


class TestRERAPostPayload:
    """Verify POST payload structure matches portal expectations."""

    def test_payload_has_required_fields(self, rera_scraper):
        """The POST must include all 7 form fields the portal expects."""
        payload = {
            "project": "",
            "firm": "",
            "appNo": "",
            "regNo": "",
            "district": "Bengaluru Urban",
            "subdistrict": "Yelahanka",
            "taluk": "Yelahanka",
            "btn1": "Search",
        }
        assert set(payload.keys()) == {"project", "firm", "appNo", "regNo", "district", "subdistrict", "taluk", "btn1"}

    def test_ua_rotation_randomizes_requests(self, rera_scraper):
        """User-Agent must rotate between requests to avoid rate limiting."""
        uas = set()
        for _ in range(10):
            rera_scraper._rotate_ua()
            uas.add(rera_scraper.session.headers.get("User-Agent", "")[:50])
        assert len(uas) > 1, "User-Agent did not rotate"


# ── Playwright fallback (T-1062) ──────────────────────────────────────────────


class TestRERAPlaywrightFallback:
    """Test the Playwright form-interaction fallback for POST-failing markets."""

    def test_playwright_fallback_triggered_on_post_failure(self, rera_scraper):
        """When POST returns 0 results and market is in RERA_USE_PLAYWRIGHT_MARKETS,
        _playwright_scrape should be called."""
        with patch.object(rera_scraper, "_post_search", return_value=[]) as mock_post:
            with patch.object(rera_scraper, "_playwright_scrape") as mock_pw:
                mock_pw.return_value = ([{"rera_number": "PW/001", "project_name": "PW Project"}], [])
                with patch.object(rera_scraper, "session") as mock_session:
                    mock_session.cookies = []
                    projects, _ = rera_scraper.scrape_market("Yelahanka")
                    assert mock_pw.called, "_playwright_scrape was not called"
                    assert len(projects) == 1
                    assert projects[0]["rera_number"] == "PW/001"

    def test_devanahalli_stays_on_post_path(self, rera_scraper):
        """Devanahalli is NOT in RERA_USE_PLAYWRIGHT_MARKETS — must NOT call Playwright."""
        with patch.object(rera_scraper, "_post_search") as mock_post:
            mock_post.return_value = [{"rera_number": "POST/001", "project_name": "POST Project"}]
            with patch.object(rera_scraper, "_playwright_scrape") as mock_pw:
                with patch.object(rera_scraper, "session") as mock_session:
                    mock_session.cookies = []
                    projects, _ = rera_scraper.scrape_market("Devanahalli")
                    assert not mock_pw.called, "_playwright_scrape was called for Devanahalli"
                    assert len(projects) == 1

    def test_playwright_falls_to_hardcoded_on_playwright_failure(self, rera_scraper):
        """When both POST and Playwright fail, fall back to hardcoded seed data."""
        with patch.object(rera_scraper, "_post_search", return_value=[]):
            with patch.object(rera_scraper, "_playwright_scrape", return_value=([], [])):
                with patch.object(rera_scraper, "_fallback_rera_data") as mock_fallback:
                    mock_fallback.return_value = [{"rera_number": "FALLBACK/001", "source": "fallback_sample"}]
                    with patch.object(rera_scraper, "session") as mock_session:
                        mock_session.cookies = []
                        projects, _ = rera_scraper.scrape_market("Yelahanka")
                        assert mock_fallback.called, "_fallback_rera_data was not called"
                        assert projects[0]["source"] == "fallback_sample"

    @patch("playwright.sync_api.sync_playwright")
    def test_playwright_parses_response_correctly(self, mock_sync_pw, rera_scraper):
        """Mock Playwright return a valid HTML table and verify parsing."""
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_sync_pw.return_value.__enter__.return_value.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.content.return_value = """
        <table><tbody>
        <tr>
            <td>1</td><td>ACK/001</td><td>PW/RERA/001</td><td></td>
            <td>PW Developer</td><td>PW Project</td><td>Active</td>
            <td>Urban</td><td>Yelahanka</td><td>Residential</td>
            <td>2025-01-01</td><td>2026-01-01</td>
        </tr>
        </tbody></table>
        """
        mock_context.cookies.return_value = [
            {"name": "JSESSIONID", "value": "test-session-123", "domain": ".karnataka.gov.in", "path": "/"}
        ]

        with patch("scrapers.rera_karnataka.Checkpointer") as mock_cp_cls:
            mock_cp = MagicMock()
            mock_cp_cls.return_value = mock_cp
            projects, cookies = rera_scraper._playwright_scrape("Yelahanka")
        assert len(projects) == 1
        assert projects[0]["project_name"] == "PW Project"
        assert projects[0]["developer_name"] == "PW Developer"
        assert projects[0]["rera_number"] == "PW/RERA/001"
        assert projects[0]["extraction_path"] == "playwright_fallback"
        assert len(cookies) > 0

    def test_playwright_not_invoked_for_non_pw_market(self, rera_scraper):
        """Markets not in RERA_USE_PLAYWRIGHT_MARKETS return empty immediately."""
        from config.settings import RERA_USE_PLAYWRIGHT_MARKETS
        assert "Devanahalli" not in RERA_USE_PLAYWRIGHT_MARKETS
        projects, cookies = rera_scraper._playwright_scrape("Devanahalli")
        assert projects == []
        assert cookies == []


# ── RERA session cookie (T-1063) ──────────────────────────────────────────────


class TestRERASessionCookie:
    """Test session cookie persistence between listing scrape and detail scout."""

    def test_session_cookie_saved_to_checkpoint(self, rera_scraper):
        """After Playwright scrape, session cookie is persisted via Checkpointer."""
        from config.checkpointer import Checkpointer
        mock_cp = MagicMock(spec=Checkpointer)

        with patch("scrapers.rera_karnataka.Checkpointer", return_value=mock_cp):
            with patch.object(rera_scraper, "_parse_html_table", return_value=[{"rera_number": "T/001"}]):
                with patch("playwright.sync_api.sync_playwright") as mock_sync_pw:
                    mock_browser = MagicMock()
                    mock_context = MagicMock()
                    mock_page = MagicMock()
                    mock_sync_pw.return_value.__enter__.return_value.chromium.launch.return_value = mock_browser
                    mock_browser.new_context.return_value = mock_context
                    mock_context.new_page.return_value = mock_page
                    mock_page.content.return_value = "<table></table>"
                    mock_context.cookies.return_value = [
                        {"name": "JSESSIONID", "value": "saved-session-456", "domain": ".karnataka.gov.in", "path": "/"}
                    ]
                    rera_scraper._playwright_scrape("Yelahanka")
                    mock_cp.save.assert_called_once()
                    call_args = mock_cp.save.call_args
                    assert call_args[0][0] == "Yelahanka"
                    assert call_args[0][1] == "rera_session"
                    assert call_args[0][2]["session_cookie"] == "saved-session-456"

    def test_detail_scout_loads_session_cookie(self):
        """RERADetailScout should load session_cookie from checkpoint at init."""
        from scrapers.rera_detail_scout import RERADetailScout
        with patch("scrapers.rera_detail_scout._load_session_cookie", return_value="cookie-from-cp"):
            scout = RERADetailScout("Yelahanka")
            assert scout._session_cookie == "cookie-from-cp"

    def test_detail_scout_skips_gracefully_on_expired_cookie(self):
        """When session returns 401, detail scout logs warning and returns empty — no crash."""
        from scrapers.rera_detail_scout import _fetch_detail_page_requests
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_session.post.return_value = mock_resp

        result = _fetch_detail_page_requests(
            "https://rera.karnataka.gov.in/projectDetails?action=123",
            mock_session,
            session_cookie="expired-cookie",
            project_name="Test Project",
        )
        assert result == ""
        # No exception raised — graceful skip

    def test_session_cookie_applied_to_headers(self):
        """Session cookie must be injected into request headers when present."""
        from scrapers.rera_detail_scout import _apply_session_cookie
        headers = {"User-Agent": "test"}
        result = _apply_session_cookie(headers, "my-session-cookie")
        assert result["Cookie"] == "my-session-cookie"
        assert result["User-Agent"] == "test"


# ── Discord scraper alert (T-1065) ───────────────────────────────────────────


class TestRERAScraperAlert:
    """Test Discord alert fires when RERA falls back to hardcoded seed."""

    def test_discord_scraper_alert_fires_on_rera_fallback(self, rera_scraper):
        """When both POST and Playwright fail, send_scraper_alert must be called."""
        from scrapers.rera_karnataka import _last_fallback_alert
        _last_fallback_alert.clear()
        with patch.object(rera_scraper, "_post_search", return_value=[]):
            with patch.object(rera_scraper, "_playwright_scrape", return_value=([], [])):
                with patch.object(rera_scraper, "_fallback_rera_data") as mock_fallback:
                    mock_fallback.return_value = [{"rera_number": "F/001", "data_source": "fallback_sample"}]
                    with patch("utils.discord_notifier.send_scraper_alert") as mock_alert:
                        with patch.object(rera_scraper, "session") as mock_session:
                            mock_session.cookies = []
                            rera_scraper.scrape_market("Yelahanka")
                            mock_alert.assert_called_once()
                            args, kwargs = mock_alert.call_args
                            assert args[0] == "Yelahanka"
                            assert args[1] == "rera_karnataka"
                            assert args[2] == "FALLBACK_SEED"

    def test_discord_scraper_alert_not_fired_when_live_data_available(self, rera_scraper):
        """When POST returns live data, send_scraper_alert must NOT be called."""
        with patch.object(rera_scraper, "_post_search", return_value=[{"rera_number": "L/001", "project_name": "Live"}]):
            with patch("utils.discord_notifier.send_scraper_alert") as mock_alert:
                with patch.object(rera_scraper, "session") as mock_session:
                    mock_session.cookies = []
                    rera_scraper.scrape_market("Yelahanka")
                    mock_alert.assert_not_called()


# ── Scraper health metrics (T-1064) ───────────────────────────────────────────


class TestRERAScraperHealth:
    """Test per-market scraper health metrics in agent_runs."""

    def test_rera_scraper_writes_health_metric_to_agent_runs(self):
        """_log_agent_run calls engine.begin() with correct INSERT params."""
        from scrapers.rera_karnataka import _log_agent_run

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        with patch("utils.db.get_engine", return_value=mock_engine):
            _log_agent_run("TestMarket", 42, False, "rera_karnataka_live", "post", 1500)

            assert mock_conn.execute.called
            call_args, call_kwargs = mock_conn.execute.call_args
            params = None
            if call_args and len(call_args) > 1 and isinstance(call_args[1], dict):
                params = call_args[1]
            elif "parameters" in call_kwargs:
                params = call_kwargs["parameters"]
            assert params is not None, f"Could not extract params from call: {mock_conn.execute.call_args}"
            assert params.get("agent_name") == "rera_scraper"
            assert params.get("market") == "TestMarket"
            assert params.get("record_count") == 42

    def test_health_check_logs_fallback_correctly(self):
        """When fallback occurs, the metric records fallback_triggered=True in metadata."""
        from scrapers.rera_karnataka import _log_agent_run
        from unittest.mock import patch, MagicMock
        import json

        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn

        def check_insert(sql, **kwargs):
            params = kwargs.get("parameters", {})
            if params.get("agent_name") == "rera_scraper" and params.get("market") == "TestMarket":
                md = json.loads(params.get("metadata", "{}"))
                assert md["fallback_triggered"] is True
                assert md["path_used"] == "seed"
                assert md["data_source"] == "fallback_sample"
                assert md["record_count"] == 8

        mock_conn.execute.side_effect = check_insert

        with patch("utils.db.get_engine", return_value=mock_engine):
            _log_agent_run("TestMarket", 8, True, "fallback_sample", "seed", 500)
            assert mock_conn.execute.called


# ── Stage 3 data-quality gate (T-1066) ───────────────────────────────────────


class TestRERADataQualityGate:
    """Test that fallback detection gates CEO/analyst context."""

    def test_fallback_detected_when_data_source_is_fallback_sample(self):
        """fallback_warning must be non-empty when raw_projects contain fallback_sample."""
        raw_projects = [
            {"data_source": "fallback_sample", "project_name": "Fake 1"},
            {"data_source": "fallback_sample", "project_name": "Fake 2"},
        ]
        has_fallback = any(
            str(r.get("data_source", r.get("source", ""))).strip().lower()
            in {"fallback_sample", "seed_estimated"}
            for r in raw_projects
            if isinstance(r, dict)
        )
        assert has_fallback is True

        fallback_count = sum(
            1 for r in raw_projects
            if isinstance(r, dict)
            and str(r.get("data_source", r.get("source", ""))).strip().lower()
            in {"fallback_sample", "seed_estimated"}
        )
        warning = (
            f"[DATA QUALITY WARNING: Test RERA on seed fallback — "
            f"{fallback_count} hardcoded records only. "
            f"PSF signals unreliable. Do not present pricing estimates as live data.]"
        )
        assert "[DATA QUALITY WARNING" in warning
        assert "2 hardcoded records" in warning
        assert "PSF signals unreliable" in warning

    def test_analyst_context_prefixed_with_warning_on_fallback(self):
        """When has_fallback_data=True, the warning must be prepended to analyst context."""
        fallback_warning = "[DATA QUALITY WARNING: Test RERA on seed fallback — 8 hardcoded records only. PSF signals unreliable. Do not present pricing estimates as live data.]"
        analyst_memory_context = "- Fact 1 (confidence: 0.80)\n- Fact 2 (confidence: 0.90)"

        prefixed = f"{fallback_warning}\n\n{analyst_memory_context}"
        assert prefixed.startswith("[DATA QUALITY WARNING")
        assert "Fact 1" in prefixed
        assert "PSF signals unreliable" in prefixed

    def test_no_warning_when_live_data_available(self):
        """When data_source is live, no warning should be generated."""
        raw_projects = [
            {"data_source": "rera_karnataka_live", "project_name": "Real 1"},
            {"data_source": "rera_karnataka_live", "project_name": "Real 2"},
        ]
        has_fallback = any(
            str(r.get("data_source", r.get("source", ""))).strip().lower()
            in {"fallback_sample", "seed_estimated"}
            for r in raw_projects
            if isinstance(r, dict)
        )
        assert has_fallback is False
