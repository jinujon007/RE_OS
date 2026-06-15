"""Tests for v_market_brief_mat materialized view (T-1093, GATE-82).

Two integration tests that verify the mat view exists and has data
after migration 0045 is applied. Skip gracefully if no DB available.
"""

import pytest

pytestmark = pytest.mark.unit


def test_v_market_brief_mat_migration_contains_correct_sql():
    """Migration 0045 contains CREATE MATERIALIZED VIEW with correct structure."""
    from pathlib import Path
    import importlib.util

    path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0045_materialized_market_brief.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0045", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert "CREATE MATERIALIZED VIEW" in mod._MAT_VIEW_SQL
    assert "v_market_brief_mat" in mod._MAT_VIEW_SQL
    assert "psf_source_tier" in mod._MAT_VIEW_SQL
    assert "psf_source_label" in mod._MAT_VIEW_SQL
    assert "months_of_supply" in mod._MAT_VIEW_SQL
    assert "supply_label" in mod._MAT_VIEW_SQL
    assert "mos_quality" in mod._MAT_VIEW_SQL


def test_v_market_brief_mat_has_unique_index():
    """Migration creates unique index on micro_market for CONCURRENTLY refresh."""
    from pathlib import Path
    import importlib.util

    path = (
        Path(__file__).parent.parent
        / "alembic"
        / "versions"
        / "0045_materialized_market_brief.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0045", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert "UNIQUE INDEX" in mod._IDX_SQL
    assert "v_market_brief_mat_market" in mod._IDX_SQL
    assert "micro_market" in mod._IDX_SQL


# ── Integration tests (require live DB + migration applied) ──────────────────


@pytest.mark.skipif("not os.environ.get('DATABASE_URL')")
def test_v_market_brief_mat_exists():
    """pg_matviews has v_market_brief_mat with ispopulated=true."""
    import os
    from utils.db import get_engine
    from sqlalchemy import text

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text("""
            SELECT matviewname, ispopulated
            FROM pg_matviews
            WHERE matviewname = 'v_market_brief_mat'
        """)
        ).fetchone()
    assert row is not None, "v_market_brief_mat not found in pg_matviews"
    assert row[1] is True, "v_market_brief_mat is not populated"


@pytest.mark.skipif("not os.environ.get('DATABASE_URL')")
def test_v_market_brief_mat_has_rows():
    """SELECT COUNT(*) FROM v_market_brief_mat >= 1."""
    import os
    from utils.db import get_engine
    from sqlalchemy import text

    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM v_market_brief_mat")).scalar()
    assert count >= 1, f"Expected >=1 row in v_market_brief_mat, got {count}"
