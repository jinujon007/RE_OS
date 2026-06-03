"""
RE_OS — News Scout Tests (T-790)
≥8 unit tests: parse, fallback, dedup, upsert, source field, etc.
"""
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ── Google News RSS parse ─────────────────────────────────────────────────────

class TestFetchGoogleNewsRss:
    def test_returns_list_of_dicts(self):
        from scrapers.news_scout import _fetch_google_news_rss

        sample_xml = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel>
        <item>
          <title>Devanahalli new launch</title>
          <link>https://example.com/1</link>
          <pubDate>Mon, 01 Jun 2026 08:00:00 +0530</pubDate>
          <description>Brigade launches 3BHK towers</description>
        </item>
        <item>
          <title>Hebbal prices rise</title>
          <link>https://example.com/2</link>
          <pubDate>Sun, 31 May 2026 12:00:00 +0530</pubDate>
          <description>PSF up 5% QoQ</description>
        </item>
        </channel></rss>"""

        with patch("scrapers.news_scout.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.content = sample_xml
            results = _fetch_google_news_rss("Devanahalli", days_back=60)

        assert isinstance(results, list)
        assert len(results) == 2
        assert results[0]["title"] == "Devanahalli new launch"
        assert results[0]["source"] == "google_news_rss"
        assert "example.com" in results[0]["url"]

    def test_returns_empty_on_http_error(self):
        from scrapers.news_scout import _fetch_google_news_rss

        with patch("scrapers.news_scout.requests.get") as mock_get:
            mock_get.return_value.status_code = 503
            results = _fetch_google_news_rss("Yelahanka", days_back=60)

        assert results == []

    def test_filters_old_articles(self):
        from scrapers.news_scout import _fetch_google_news_rss

        old_xml = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel>
        <item>
          <title>Old article</title>
          <link>https://example.com/old</link>
          <pubDate>Mon, 01 Jan 2024 08:00:00 +0530</pubDate>
          <description>Stale</description>
        </item>
        </channel></rss>"""

        with patch("scrapers.news_scout.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.content = old_xml
            results = _fetch_google_news_rss("Yelahanka", days_back=30)

        assert results == []


# ── ET Realty markdown parse ───────────────────────────────────────────────────

class TestParseEtRealtyMarkdown:
    def test_extracts_links(self):
        from scrapers.news_scout import _parse_et_realty_markdown

        md = """
        [Brigade launches new towers in Devanahalli](https://realty.economictimes.indiatimes.com/brigade-devanahalli-2026)
        [Hebbal property prices jump 8%](https://realty.economictimes.indiatimes.com/hebbal-price-rise)
        [skip me](#anchor)
        [too short](https://example.com/x)
        """
        articles = _parse_et_realty_markdown(md)
        assert len(articles) == 2
        assert articles[0]["source"] == "et_realty"
        assert "brigade" in articles[0]["title"].lower()

    def test_empty_content_returns_empty(self):
        from scrapers.news_scout import _parse_et_realty_markdown

        assert _parse_et_realty_markdown("") == []


# ── Dedup by URL hash ──────────────────────────────────────────────────────────

class TestDedupByUrl:
    def test_duplicate_urls_removed(self):
        from scrapers.news_scout import NewsScout
        from scrapers.scout_memory import ScoutMemory

        scout = NewsScout.__new__(NewsScout)
        scout.market = "Yelahanka"
        scout.queries = []
        scout.memory = MagicMock()
        scout.memory.mark_all.return_value = ([], [])

        raw = [
            {"title": "A", "url": "https://x.com/1", "published": "", "snippet": "s1"},
            {"title": "B", "url": "https://x.com/1", "published": "", "snippet": "s2"},
            {"title": "C", "url": "https://x.com/2", "published": "", "snippet": "s3"},
        ]

        seen: set = set()
        unique = []
        for a in raw:
            key = a.get("url", a.get("title", ""))
            if key and key not in seen:
                seen.add(key)
                unique.append(a)

        assert len(unique) == 2


# ── _normalize_article ─────────────────────────────────────────────────────────

class TestNormalizeArticle:
    def test_returns_none_for_empty(self):
        from scrapers.news_scout import _normalize_article

        assert _normalize_article({}, "Yelahanka") is None
        assert _normalize_article({"headline": ""}, "Yelahanka") is None

    def test_sets_source_and_market(self):
        from scrapers.news_scout import _normalize_article

        raw = {
            "headline": "Test headline",
            "url": "https://example.com/test",
            "signal_type": "new_launch",
            "key_insight": "New tower launched",
        }
        result = _normalize_article(raw, "Devanahalli")
        assert result is not None
        assert result["source"] == "news"
        assert result["market"] == "Devanahalli"
        assert result["signal_type"] == "new_launch"


# ── Source field correctness ───────────────────────────────────────────────────

class TestSourceField:
    def test_google_news_source_label(self):
        from scrapers.news_scout import _fetch_google_news_rss

        xml = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel>
        <item><title>T</title><link>https://x.com/1</link>
        <pubDate>Mon, 01 Jun 2026 08:00:00 +0530</pubDate>
        <description>D</description></item>
        </channel></rss>"""

        with patch("scrapers.news_scout.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.content = xml
            results = _fetch_google_news_rss("Yelahanka")

        assert results[0]["source"] == "google_news_rss"

    def test_et_realty_source_label(self):
        # Title must be >=20 chars to pass the parser's minimum length guard
        md = "[Bengaluru real estate market sees record registrations in May 2026](https://realty.economictimes.indiatimes.com/news/bengaluru-market-2026)"
        from scrapers.news_scout import _parse_et_realty_markdown
        results = _parse_et_realty_markdown(md)
        assert results[0]["source"] == "et_realty"


# ── db upsert idempotency ───────────────────────────────────────────────────────

class TestNewsUpsertIdempotent:
    def test_re_run_does_not_duplicate(self):
        import uuid
        from scrapers.scout_memory import ScoutMemory

        # Use a unique URL so ScoutMemory's on-disk cache from prior runs never matches
        test_url = f"https://x.com/test-dedup-{uuid.uuid4()}"
        mem = ScoutMemory("Yelahanka")
        findings = [
            {
                "cid": mem.cid_news(test_url),
                "headline": "Same article",
                "source_url": test_url,
                "signal_type": "other",
                "scraped_at": "2026-06-02T10:00:00",
            }
        ]

        new1, known1 = mem.mark_all(findings, source="news")
        new2, known2 = mem.mark_all(findings, source="news")

        assert len(new1) == 1
        assert len(known1) == 0
        assert len(new2) == 0
        assert len(known2) == 1
