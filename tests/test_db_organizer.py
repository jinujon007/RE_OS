"""
Tests for utils/db_organizer.py

Covers: _safe_date (valid, invalid month, None, empty, too short, other format),
DBOrganizer._compute_grade (known brand, unit thresholds, case-insensitive),
_insert_news_article raises on empty cid, run_portal_scout with empty list.

DB connection is mocked via unittest.mock — no live Postgres needed.
"""

import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit

# Import the module-level helpers directly
from utils.db_organizer import _safe_date, DBOrganizer


# ── _safe_date ─────────────────────────────────────────────────────────────────


def test_safe_date_valid():
    assert _safe_date("2024-06-15") == "2024-06-15"


def test_safe_date_valid_with_extra():
    # Only first 10 chars used — datetime data after the date should be stripped
    assert _safe_date("2024-06-15 10:30:00") == "2024-06-15"


def test_safe_date_invalid_month():
    # Month 99 is not a real month
    assert _safe_date("2024-99-01") is None


def test_safe_date_invalid_day():
    assert _safe_date("2024-02-30") is None


def test_safe_date_none():
    assert _safe_date(None) is None


def test_safe_date_empty_string():
    assert _safe_date("") is None


def test_safe_date_too_short():
    # Fewer than 10 chars — can't be a valid YYYY-MM-DD
    assert _safe_date("2024-06") is None


def test_safe_date_wrong_separator():
    # Slash-separated — doesn't match %Y-%m-%d
    assert _safe_date("2024/06/15") is None


def test_safe_date_non_date_string():
    assert _safe_date("not-a-date") is None


def test_safe_date_integer_input():
    # Non-string inputs should not crash — returns None since int has no date meaning
    assert _safe_date(20240615) is None


# ── DBOrganizer._compute_grade ─────────────────────────────────────────────────


@pytest.fixture
def org():
    """DBOrganizer with a mocked engine so no DB connection is attempted."""
    with patch("utils.db_organizer.create_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        return DBOrganizer()


def test_compute_grade_known_brand_prestige(org):
    assert org._compute_grade("Prestige Group", 10) == "A"


def test_compute_grade_known_brand_brigade(org):
    assert org._compute_grade("Brigade Enterprises", 50) == "A"


def test_compute_grade_known_brand_case_insensitive(org):
    assert org._compute_grade("SOBHA Limited", 10) == "A"


def test_compute_grade_large_units_a(org):
    # ≥500 units → Grade A even if not a known brand
    assert org._compute_grade("Unknown Builder", 500) == "A"


def test_compute_grade_medium_units_b(org):
    # 100–499 units → Grade B
    assert org._compute_grade("Small Builder", 200) == "B"


def test_compute_grade_small_units_c(org):
    # <100 units → Grade C
    assert org._compute_grade("Tiny Developer", 50) == "C"


def test_compute_grade_zero_units_c(org):
    assert org._compute_grade("No Units Builder", 0) == "C"


def test_compute_grade_exactly_500_a(org):
    assert org._compute_grade("Boundary Dev", 500) == "A"


def test_compute_grade_exactly_100_b(org):
    assert org._compute_grade("Boundary Dev", 100) == "B"


def test_compute_grade_499_units_b(org):
    # "Apex Constructions" has no substring matching GRADE_A_DEVELOPERS (avoids "dl" in "middle")
    assert org._compute_grade("Apex Constructions", 499) == "B"


# ── _insert_news_article raises on empty cid ──────────────────────────────────


def test_insert_news_article_empty_cid_raises(org):
    mock_conn = MagicMock()
    with pytest.raises(ValueError, match="missing cid"):
        org._insert_news_article(mock_conn, {"title": "Test Article", "cid": ""})


def test_insert_news_article_no_cid_key_raises(org):
    mock_conn = MagicMock()
    with pytest.raises(ValueError, match="missing cid"):
        org._insert_news_article(mock_conn, {"title": "No CID Here"})


def test_insert_news_article_whitespace_cid_raises(org):
    mock_conn = MagicMock()
    with pytest.raises(ValueError, match="missing cid"):
        org._insert_news_article(mock_conn, {"cid": "   ", "title": "Spaces Only"})


# ── run_portal_scout with empty list ──────────────────────────────────────────


def _make_ctx_manager(conn):
    """Build a context manager mock that returns conn on __enter__."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=conn)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def test_run_portal_scout_empty_list_returns_zero_stats(org):
    mock_conn = MagicMock()
    with patch.object(org, "engine") as mock_engine:
        mock_engine.begin.return_value = _make_ctx_manager(mock_conn)
        stats = org.run_portal_scout("Yelahanka", [])
        assert stats["total"] == 0
        assert stats["upserted"] == 0
        assert stats["failed"] == 0


# ── DBOrganizer.run() with empty records ──────────────────────────────────────


def test_run_empty_records_returns_zero_stats(org):
    """run() with empty list: no DB iterations, stats all zero, _log_run silent failure OK."""
    mock_conn = MagicMock()
    with patch.object(org, "engine") as mock_engine:
        mock_engine.begin.return_value = _make_ctx_manager(mock_conn)
        stats = org.run("Yelahanka", [])

    assert stats["market"] == "Yelahanka"
    assert stats["total"] == 0
    assert stats["inserted"] == 0
    assert stats["updated"] == 0
    assert stats["failed"] == 0
    assert "duration_seconds" in stats


def test_run_returns_correct_market(org):
    mock_conn = MagicMock()
    with patch.object(org, "engine") as mock_engine:
        mock_engine.begin.return_value = _make_ctx_manager(mock_conn)
        stats = org.run("Devanahalli", [])
    assert stats["market"] == "Devanahalli"


def test_run_log_run_exception_does_not_raise(org):
    """_log_run wraps in try/except — engine failure must not abort run()."""
    mock_conn = MagicMock()
    with patch.object(org, "engine") as mock_engine:
        mock_engine.begin.side_effect = Exception("DB unavailable")
        # run() calls engine.begin() twice (once for the batch, once for _log_run)
        # Make first call work, second call fail
        mock_engine.begin.side_effect = [
            _make_ctx_manager(mock_conn),
            Exception("log DB unavailable"),
        ]
        stats = org.run("Hebbal", [])
    assert stats["total"] == 0


# ── run_news_scout with empty list ────────────────────────────────────────────


def test_run_news_scout_empty_list_skips_on_missing_table(org):
    """If news_articles table missing, run_news_scout returns immediately without failing."""
    mock_conn = MagicMock()
    mock_conn.execute.return_value.scalar.return_value = None  # table absent

    with patch.object(org, "engine") as mock_engine:
        mock_engine.begin.return_value = _make_ctx_manager(mock_conn)
        stats = org.run_news_scout("Yelahanka", [{"cid": "n1", "title": "t"}])

    assert stats["inserted"] == 0


def test_run_developer_scout_empty_list(org):
    mock_conn = MagicMock()
    with patch.object(org, "engine") as mock_engine:
        mock_engine.begin.return_value = _make_ctx_manager(mock_conn)
        stats = org.run_developer_scout("Yelahanka", [])
    assert stats["total"] == 0
    assert stats["upserted"] == 0


# ── DBOrganizer.run() with a failing record ────────────────────────────────────


def test_run_with_failing_record_counts_failed(org):
    """When _upsert_developer raises, the except branch runs and failed==1."""
    mock_conn = MagicMock()
    with patch.object(org, "_upsert_developer", side_effect=ValueError("bad")), \
         patch.object(org, "engine") as mock_engine:
        # First begin() for the main batch; second for _log_run (which catches exception)
        mock_engine.begin.side_effect = [
            _make_ctx_manager(mock_conn),
            Exception("log unavailable"),
        ]
        stats = org.run("Yelahanka", [{"rera_number": "KA/01/1", "project_name": "X"}])

    assert stats["total"] == 1
    assert stats["failed"] == 1
    assert stats["inserted"] == 0


def test_run_grade_batch_failure_is_non_fatal(org):
    """If _batch_update_developer_grades raises, run() still completes and returns stats."""
    mock_conn = MagicMock()
    with patch.object(org, "_batch_update_developer_grades", side_effect=Exception("grade fail")), \
         patch.object(org, "engine") as mock_engine:
        mock_engine.begin.side_effect = [
            _make_ctx_manager(mock_conn),
            Exception("log unavailable"),
        ]
        stats = org.run("Devanahalli", [])
    # Should return normally (grade failure is non-fatal)
    assert stats["total"] == 0


# ── run_portal_scout with a failing record ─────────────────────────────────────


def test_run_portal_scout_failing_record_counts_failed(org):
    """When _upsert_listing_by_cid raises, failed count increments."""
    mock_conn = MagicMock()
    with patch.object(org, "_get_market_id_by_name", return_value="market-id-1"), \
         patch.object(org, "_upsert_listing_by_cid", side_effect=ValueError("bad cid")), \
         patch.object(org, "engine") as mock_engine:
        mock_engine.begin.return_value = _make_ctx_manager(mock_conn)
        stats = org.run_portal_scout("Yelahanka", [{"cid": "p1", "source": "portal"}])

    assert stats["total"] == 1
    assert stats["failed"] == 1
    assert stats["upserted"] == 0


# ── run_developer_scout with a failing record ─────────────────────────────────


def test_run_developer_scout_failing_record_counts_failed(org):
    mock_conn = MagicMock()
    with patch.object(org, "_get_market_id_by_name", return_value="market-id-1"), \
         patch.object(org, "_upsert_listing_by_cid", side_effect=ValueError("bad")), \
         patch.object(org, "engine") as mock_engine:
        mock_engine.begin.return_value = _make_ctx_manager(mock_conn)
        stats = org.run_developer_scout("Yelahanka", [{"cid": "d1", "source": "brigade"}])

    assert stats["total"] == 1
    assert stats["failed"] == 1


# ── utils/db.py singleton ──────────────────────────────────────────────────────


def test_get_engine_returns_engine():
    """get_engine() returns a non-None engine without hitting the DB."""
    with patch("utils.db.create_engine") as mock_ce:
        mock_ce.return_value = MagicMock(name="mock_engine")
        import utils.db as db_mod
        db_mod._engine = None  # reset singleton for test isolation
        engine = db_mod.get_engine()
        assert engine is not None
        db_mod._engine = None  # clean up
