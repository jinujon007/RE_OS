"""
RE_OS — DBOrganizer News Tests (T-930)
Tests headline→title fallback in _insert_news_article.
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestInsertNewsArticleHeadlineFallback:
    def test_headline_fallback_populates_title(self):
        from utils.db_organizer import DBOrganizer

        org = DBOrganizer.__new__(DBOrganizer)
        mock_conn = MagicMock()
        rec = {
            "cid": "test-cid-1",
            "headline": "Test headline article",
            "source": "news",
        }
        org._insert_news_article(mock_conn, rec)
        call_kwargs = mock_conn.execute.call_args[0][1]
        assert call_kwargs["title"] == "Test headline article"

    def test_title_takes_priority_over_headline(self):
        from utils.db_organizer import DBOrganizer

        org = DBOrganizer.__new__(DBOrganizer)
        mock_conn = MagicMock()
        rec = {
            "cid": "test-cid-2",
            "title": "Real Title",
            "headline": "Fallback Headline",
            "source": "news",
        }
        org._insert_news_article(mock_conn, rec)
        call_kwargs = mock_conn.execute.call_args[0][1]
        assert call_kwargs["title"] == "Real Title"
