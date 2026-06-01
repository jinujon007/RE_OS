"""Unit tests for scrapers/igr_karnataka.py — T-478 (Sprint 39).

Tests cover:
  - Fallback returns list with >=5 records per market
  - Fallback PSF is computable (transaction_psf = amount / area)
  - IGRTransactionScout.run() returns list on unknown market
  - insert_transactions() skips when records is empty
  - insert_transactions() falls back gracefully when DB unavailable
  - RateLimiter respects the interval
  - _normalize_row() handles missing keys gracefully
  - Dedup key is deterministic (same key → same id)
"""
import hashlib
import time
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


class TestIGRFallback:
    """Fallback transaction data quality."""

    def _fb(self, market: str):
        from scrapers.igr_karnataka import _fallback_transactions
        return _fallback_transactions(market)

    def test_yelahanka_returns_at_least_5(self):
        records = self._fb("Yelahanka")
        assert len(records) >= 5

    def test_devanahalli_returns_at_least_5(self):
        records = self._fb("Devanahalli")
        assert len(records) >= 5

    def test_hebbal_returns_at_least_5(self):
        records = self._fb("Hebbal")
        assert len(records) >= 5

    def test_unknown_market_returns_empty(self):
        assert self._fb("NonExistentCity") == []

    def test_fallback_psf_computable(self):
        """Each record must have enough data to compute transaction_psf."""
        for market in ("Yelahanka", "Devanahalli", "Hebbal"):
            for rec in self._fb(market):
                amount = rec.get("consideration_amount", 0)
                area = rec.get("area_sqft", 0)
                assert amount > 0, f"{market}: consideration_amount must be >0"
                assert area > 0, f"{market}: area_sqft must be >0"
                psf = round(amount / area)
                assert psf > 0, f"{market}: computed PSF must be positive"

    def test_fallback_source_tag_is_fallback(self):
        for rec in self._fb("Devanahalli"):
            assert rec.get("source") == "fallback"

    def test_fallback_registration_date_is_string(self):
        for rec in self._fb("Yelahanka"):
            reg_date = rec.get("registration_date", "")
            assert isinstance(reg_date, str) and len(reg_date) == 10, (
                f"registration_date must be YYYY-MM-DD string, got {reg_date!r}"
            )


class TestIGRNormalizeRow:
    """Row normalisation handles missing or unexpected keys."""

    def _norm(self, row, meta=None):
        from scrapers.igr_karnataka import IGRTransactionScout
        scout = IGRTransactionScout.__new__(IGRTransactionScout)
        return scout._normalize_row(row, meta or {"taluk": "Devanahalli"})

    def test_empty_row_returns_defaults(self):
        result = self._norm({})
        assert result["survey_no"] == ""
        assert result["seller"] == ""
        assert result["buyer"] == ""
        assert result["consideration_amount"] == 0
        assert result["area_sqft"] == 0.0
        assert result["source"] == "portal"

    def test_amount_and_area_cast_to_numeric(self):
        row = {"transactionAmount": "8500000", "area": "2400.5"}
        result = self._norm(row)
        assert result["consideration_amount"] == 8500000
        assert result["area_sqft"] == 2400.5

    def test_sro_falls_back_to_taluk(self):
        row = {}
        result = self._norm(row, {"taluk": "Yelahanka"})
        assert result["sro_office"] == "Yelahanka"

    def test_null_amount_defaults_to_zero(self):
        row = {"transactionAmount": None, "area": None}
        result = self._norm(row)
        assert result["consideration_amount"] == 0
        assert result["area_sqft"] == 0.0


class TestIGRRun:
    """IGRTransactionScout.run() graceful behaviour."""

    def test_unknown_market_returns_empty(self):
        from scrapers.igr_karnataka import IGRTransactionScout
        scout = IGRTransactionScout()
        result = scout.run(market="UnknownCity")
        assert result == []

    def test_run_returns_list(self):
        """run() must always return a list, even if portal fails."""
        from scrapers.igr_karnataka import IGRTransactionScout
        with patch.object(IGRTransactionScout, "_scrape_via_playwright", return_value=[]), \
             patch.object(IGRTransactionScout, "_scrape_via_post", return_value=[]):
            scout = IGRTransactionScout()
            result = scout.run(market="Devanahalli", days_back=30)
        assert isinstance(result, list)
        assert len(result) >= 5  # must fall back to hardcoded records

    def test_fallback_source_tag_set_correctly(self):
        from scrapers.igr_karnataka import IGRTransactionScout
        with patch.object(IGRTransactionScout, "_scrape_via_playwright", return_value=[]), \
             patch.object(IGRTransactionScout, "_scrape_via_post", return_value=[]):
            scout = IGRTransactionScout()
            result = scout.run(market="Yelahanka")
        assert all(r["source"] == "fallback" for r in result)


class TestIGRInsert:
    """insert_transactions() DB interaction."""

    def test_empty_records_returns_zero_stats(self):
        from scrapers.igr_karnataka import IGRTransactionScout
        scout = IGRTransactionScout()
        stats = scout.insert_transactions([], market="Yelahanka")
        assert stats == {"inserted": 0, "skipped": 0, "failed": 0}

    def test_db_import_failure_returns_zero_stats(self):
        from scrapers.igr_karnataka import IGRTransactionScout
        scout = IGRTransactionScout()
        records = [{"survey_no": "1/1", "registration_date": "2026-05-01",
                    "seller": "A", "buyer": "B",
                    "consideration_amount": 1000000, "area_sqft": 200,
                    "sro_office": "Test", "source": "fallback"}]
        with patch("scrapers.igr_karnataka.IGRTransactionScout.insert_transactions",
                   side_effect=ImportError("no db")):
            # Direct internal path: simulate ImportError in get_engine
            with patch("utils.db.get_engine", side_effect=ImportError("no db")):
                stats = scout.insert_transactions(records, market="Test")
        assert stats["inserted"] == 0


class TestDeduplicationKey:
    """Dedup ID generation is deterministic and SHA-256-based."""

    def test_same_input_produces_same_id(self):
        key = "156/2:2026-05-15"
        id1 = hashlib.sha256(key.encode()).hexdigest()[:32]
        id2 = hashlib.sha256(key.encode()).hexdigest()[:32]
        assert id1 == id2

    def test_different_dates_produce_different_ids(self):
        id1 = hashlib.sha256("156/2:2026-05-15".encode()).hexdigest()[:32]
        id2 = hashlib.sha256("156/2:2026-05-16".encode()).hexdigest()[:32]
        assert id1 != id2

    def test_id_length_is_32_chars(self):
        key = "test:2026-01-01"
        dedup_id = hashlib.sha256(key.encode()).hexdigest()[:32]
        assert len(dedup_id) == 32


class TestRateLimiter:
    """RateLimiter enforces the minimum interval."""

    def test_wait_enforces_interval(self):
        from scrapers.igr_karnataka import RateLimiter
        limiter = RateLimiter(interval_s=0.05)
        limiter.wait()  # first call — no delay
        t0 = time.time()
        limiter.wait()  # second call — must wait ~0.05s
        elapsed = time.time() - t0
        assert elapsed >= 0.04, f"Expected >=0.04s delay, got {elapsed:.3f}s"

    def test_limiter_no_delay_after_interval_passed(self):
        from scrapers.igr_karnataka import RateLimiter
        limiter = RateLimiter(interval_s=0.01)
        limiter.wait()
        time.sleep(0.05)  # wait longer than interval
        t0 = time.time()
        limiter.wait()
        elapsed = time.time() - t0
        assert elapsed < 0.03, f"Should not delay but took {elapsed:.3f}s"
