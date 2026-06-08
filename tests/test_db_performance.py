"""Performance tests for Sprint 82 (GATE-82) — T-1096.

Unit test:
  - market_id_lookup_count_for_200_records: mock 200 records, assert ≤3 micro_markets SELECTs

Integration test:
  - v_market_brief_mat_query_time: mat view query < 100ms
"""
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_market_id_lookup_count_for_200_records():
    """200 Yelahanka records → ≤3 SELECT on micro_markets total (cache load + 0 lookups)."""
    import utils.db_organizer as _dbo

    _dbo._SHARED_ENGINE = None
    from tests.test_db_organizer import _make_ctx_manager
    from utils.db_organizer import DBOrganizer

    with patch.object(_dbo, "create_engine") as mock_engine:
        mock_engine.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute().fetchall.return_value = [
            ("yelahanka", "uuid-yel"),
            ("devanahalli", "uuid-dev"),
            ("hebbal", "uuid-heb"),
        ]
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        org = DBOrganizer()
        mock_conn.execute.reset_mock()
        mock_conn.reset_mock()

        records = [{"locality": "Yelahanka New Town", "taluk": "", "rera_number": f"RERA/2024/{i}"} for i in range(200)]

        with patch.object(org, "_run_quality_check", return_value={"success": True}):
            with patch.object(org, "engine") as mock_engine_begin:
                mock_engine_begin.begin.return_value = _make_ctx_manager(mock_conn)
                try:
                    org.run("Yelahanka", records)
                except Exception:
                    pass

    micro_markets_selects = [
        c for c in mock_conn.execute.call_args_list
        if c.args and "SELECT" in str(c.args[0]).upper()
        and "micro_markets" in str(c.args[0]).lower()
        and "_market_id_cache" not in str(c.args[0])
    ]
    assert len(micro_markets_selects) <= 3, (
        f"Expected ≤3 SELECT on micro_markets, got {len(micro_markets_selects)} "
        f"for 200 records (should be 0 cache lookups + 1 cache load + ≤2 other). "
        f"Calls: {[str(c.args[0])[:80] for c in micro_markets_selects]}"
    )


@pytest.mark.integration
@pytest.mark.skipif("not os.environ.get('DATABASE_URL')")
def test_v_market_brief_mat_query_time():
    """SELECT * FROM v_market_brief_mat must complete < 100ms."""
    import os
    import time
    from utils.db import get_engine
    from sqlalchemy import text

    engine = get_engine()
    with engine.connect() as conn:
        t0 = time.time()
        rows = conn.execute(text("SELECT * FROM v_market_brief_mat")).fetchall()
        elapsed_ms = (time.time() - t0) * 1000

    assert elapsed_ms < 100, (
        f"v_market_brief_mat query took {elapsed_ms:.1f}ms (expected < 100ms). "
        f"Check that the unique index exists."
    )
    assert len(rows) >= 1, f"Expected >=1 row, got {len(rows)}"
