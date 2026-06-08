"""GATE-82 — Performance Hardening + Clean Data Profile.

Four assertions:
  1. _market_id_cache has all 3 micro-market entries at init
  2. pg_matviews has v_market_brief_mat with ispopulated = true
  3. kaveri_registrations WHERE registration_number = '' count = 0
  4. test_market_id_lookup_count_for_200_records passes

All pass → GATE-82 ✅
"""
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_gate82_market_cache_has_3_markets():
    """Assertion 1: _market_id_cache has all 3 micro-markets at init."""
    from utils.db_organizer import DBOrganizer

    with patch("utils.db_organizer.create_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute().fetchall.return_value = [
            ("yelahanka", "uuid-yel"),
            ("devanahalli", "uuid-dev"),
            ("hebbal", "uuid-heb"),
        ]
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        org = DBOrganizer()

    assert "yelahanka" in org._market_id_cache
    assert "devanahalli" in org._market_id_cache
    assert "hebbal" in org._market_id_cache
    assert len(org._market_id_cache) >= 3


@pytest.mark.integration
@pytest.mark.skipif("not os.environ.get('DATABASE_URL')")
def test_gate82_mat_view_exists():
    """Assertion 2: pg_matviews has v_market_brief_mat with ispopulated = true."""
    import os
    from utils.db import get_engine
    from sqlalchemy import text

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT matviewname, ispopulated
            FROM pg_matviews
            WHERE matviewname = 'v_market_brief_mat'
        """)).fetchone()

    assert row is not None, "v_market_brief_mat not found in pg_matviews"
    assert row[1] is True, "v_market_brief_mat is not populated"


def test_gate82_performance_test_passes():
    """Assertion 4: test_market_id_lookup_count_for_200_records passes."""
    from tests.test_db_performance import test_market_id_lookup_count_for_200_records
    test_market_id_lookup_count_for_200_records()


# ── Integration: empty-string registration cleanup ───────────────────────────


@pytest.mark.integration
@pytest.mark.skipif("not os.environ.get('DATABASE_URL')")
def test_gate82_no_empty_registration_numbers():
    """Assertion 3: kaveri_registrations WHERE registration_number = '' count = 0."""
    import os
    from utils.db import get_engine
    from sqlalchemy import text

    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM kaveri_registrations WHERE registration_number = ''")
        ).scalar()

    assert count == 0, (
        f"Found {count} kaveri_registrations with empty registration_number. "
        "Run database/cleanup_empty_registration_numbers.sql."
    )
