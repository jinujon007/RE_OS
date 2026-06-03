"""
Tests for IGR Karnataka scraper (Sprint 42 — T-792, T-793).
Uses mocking for portal interactions; tests all fallback paths.
"""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestIGRTransactionScout:
    """Core scraper behaviour — rate limiting, fallback chain, row normalisation."""

    def _make_scout(self):
        from scrapers.igr_karnataka import IGRTransactionScout
        return IGRTransactionScout()

    def test_fallback_returns_list_for_known_market(self):
        from scrapers.igr_karnataka import _fallback_transactions
        fb = _fallback_transactions("Yelahanka")
        assert isinstance(fb, list)
        assert len(fb) >= 5

    def test_fallback_returns_empty_for_unknown_market(self):
        from scrapers.igr_karnataka import _fallback_transactions
        fb = _fallback_transactions("Unknown")
        assert fb == []

    def test_run_uses_fallback_when_portal_unreachable(self):
        scout = self._make_scout()
        with patch.object(scout, '_scrape_via_scrapling', return_value=[]):
            with patch.object(scout, '_scrape_via_post', return_value=[]):
                results = scout.run(market="Yelahanka", days_back=30)
        assert len(results) >= 5
        for r in results:
            assert r["source"] == "fallback"

    def test_run_returns_portal_post_records_when_available(self):
        fake_records = [
            {"survey_no": "100/1", "seller": "A", "buyer": "B",
             "consideration_amount": 1000000, "area_sqft": 1000,
             "registration_date": "2026-05-01", "sro_office": "Test",
             "source": "igr_portal"},
        ]
        scout = self._make_scout()
        with patch.object(scout, '_scrape_via_scrapling', return_value=[]):
            with patch.object(scout, '_scrape_via_post', return_value=fake_records):
                results = scout.run(market="Devanahalli")
        assert len(results) == 1
        assert results[0]["source"] == "igr_portal"

    def test_output_schema_has_required_keys(self):
        from scrapers.igr_karnataka import _fallback_transactions
        for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
            for rec in _fallback_transactions(market):
                for key in ("survey_no", "seller", "buyer", "consideration_amount",
                            "area_sqft", "registration_date", "sro_office", "source"):
                    assert key in rec, f"Missing key {key} in {market} fallback"

    def test_consideration_amount_positive(self):
        from scrapers.igr_karnataka import _fallback_transactions
        for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
            for rec in _fallback_transactions(market):
                assert rec["consideration_amount"] > 0

    def test_area_sqft_positive(self):
        from scrapers.igr_karnataka import _fallback_transactions
        for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
            for rec in _fallback_transactions(market):
                assert rec["area_sqft"] > 0

    def test_registration_date_format(self):
        from scrapers.igr_karnataka import _fallback_transactions
        import re
        for market in ["Yelahanka", "Devanahalli", "Hebbal"]:
            for rec in _fallback_transactions(market):
                assert re.match(r"\d{4}-\d{2}-\d{2}", rec["registration_date"])

    def test_rate_limiter_respects_interval(self):
        from scrapers.igr_karnataka import RateLimiter
        import time
        rl = RateLimiter(interval_s=0.05)
        t0 = time.time()
        rl.wait()
        rl.wait()
        elapsed = time.time() - t0
        assert elapsed >= 0.05

    def test_insert_transactions_empty_returns_zero_stats(self):
        scout = self._make_scout()
        stats = scout.insert_transactions([], market="Yelahanka")
        assert stats["inserted"] == 0
        assert stats["skipped"] == 0
        assert stats["failed"] == 0

    def test_run_with_unknown_market_returns_empty(self):
        scout = self._make_scout()
        results = scout.run(market="NonExistent")
        assert results == []

    def test_insert_transactions_dedup_on_second_call(self):
        scout = self._make_scout()
        records = [{"survey_no": "100/1", "seller": "A", "buyer": "B",
                    "consideration_amount": 1000000, "area_sqft": 1000,
                    "registration_date": "2026-05-01", "sro_office": "Test"}]
        from unittest.mock import patch
        with patch("utils.db.get_engine") as mock_ge:
            mock_conn = MagicMock()
            mock_engine = MagicMock()
            mock_engine.begin.return_value.__enter__.return_value = mock_conn
            mock_ge.return_value = mock_engine
            mock_result = MagicMock()
            mock_result.rowcount = 1
            mock_conn.execute.return_value = mock_result

            stats1 = scout.insert_transactions(records, market="Yelahanka")
            assert stats1["inserted"] == 1

            mock_result.rowcount = 0
            stats2 = scout.insert_transactions(records, market="Yelahanka")
            assert stats2["skipped"] == 1


class TestIGRScraplingPath:
    """Tests for Scrapling-based scraping path."""

    def test_scrapling_unavailable_graceful(self):
        from scrapers.igr_karnataka import IGRTransactionScout
        scout = IGRTransactionScout()
        with patch("scrapers.igr_karnataka._is_scrapling_available", return_value=False):
            results = scout._scrape_via_scrapling({}, "2026-04-01", "2026-05-01")
            assert results == []


class TestIGRPostPath:
    """Tests for direct POST path."""

    def test_post_fails_without_session(self):
        from scrapers.igr_karnataka import IGRTransactionScout
        scout = IGRTransactionScout()
        scout.session = None
        results = scout._scrape_via_post({}, "2026-04-01", "2026-05-01")
        assert results == []

    def test_post_non_200_returns_empty(self):
        from scrapers.igr_karnataka import IGRTransactionScout
        scout = IGRTransactionScout()
        scout.session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        scout.session.post.return_value = mock_resp
        results = scout._scrape_via_post({}, "2026-04-01", "2026-05-01")
        assert results == []

    def test_post_json_decode_error_returns_empty(self):
        from scrapers.igr_karnataka import IGRTransactionScout
        scout = IGRTransactionScout()
        scout.session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("bad json")
        scout.session.post.return_value = mock_resp
        results = scout._scrape_via_post({}, "2026-04-01", "2026-05-01")
        assert results == []
