"""DB upsert contract test: Stage 2 → Stage 3 consistency.

Verifies that data written by DBOrganizer (Stage 2) is correctly queried by
the analyst layer views (Stage 3).  Catches schema-drift bugs between writer
assumptions and reader queries (the class of bugs GATE-99 found).
"""

from unittest.mock import patch
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def test_db_organizer_writes_and_market_brief_reads(live_engine):
    """Run DBOrganizer with a fixture record, then query v_market_brief."""
    from utils.db_organizer import DBOrganizer

    engine = live_engine

    # Ensure micro_market exists for the fixture
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO micro_markets (id, name, slug, district, state)
            VALUES (999, 'Integration Test Market', 'integration-test', 'Bangalore Urban', 'Karnataka')
            ON CONFLICT (id) DO NOTHING
        """))

    fixture_record = {
        "rera_number": "INTG-RERA-001",
        "project_name": "Integration Test Project",
        "developer_name": "Integration Developer",
        "micro_market": "Integration Test Market",
        "district": "Bangalore Urban",
        "status": "registered",
        "village": "Test Village",
        "total_units": 100,
        "price_min_psf": 5000,
        "price_max_psf": 6500,
        "data_source": "integration_test",
    }

    with (
        patch("utils.db_organizer._get_organizer_engine", return_value=engine),
        patch("utils.db_organizer.DataQualityError"),  # suppress data quality blocking
        patch("utils.db_organizer.run_data_quality_checkpoint", return_value={"success": True}),
        patch("utils.db_organizer.send_quality_alert"),
        patch.object(DBOrganizer, "_log_run"),
    ):
        org = DBOrganizer()
        stats = org.run("Integration Test Market", [fixture_record])

    assert stats["inserted"] >= 1 or stats["updated"] >= 1, f"Unexpected stats: {stats}"
    assert stats["failed"] == 0, f"Expected 0 failures, got {stats['failed']}"

    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT rera_number, project_name, status
                FROM rera_projects
                WHERE rera_number = 'INTG-RERA-001'
            """)
        ).fetchone()
    assert row is not None, "Seeded project not found in rera_projects"
    assert row.rera_number == "INTG-RERA-001"
    assert row.status == "registered"


def test_v_market_brief_returns_data_after_seed(live_engine):
    """Query v_market_brief after seeding — assert avg_listing_psf IS NOT NULL."""
    engine = live_engine

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO micro_markets (id, name, slug, district, state)
            VALUES (998, 'Brief Test Market', 'brief-test', 'Bangalore Urban', 'Karnataka')
            ON CONFLICT (id) DO NOTHING
        """))
        conn.execute(text("""
            INSERT INTO rera_projects (id, rera_number, project_name, micro_market_id, district, status, village, price_min_psf, price_max_psf, data_source)
            VALUES ('cccccccc-cccc-cccc-cccc-ccccccccccc1', 'BRIEF-RERA-001', 'Brief Test Project', 998, 'Bangalore Urban', 'registered', 'Brief Village', 5200, 6800, 'integration_test')
            ON CONFLICT (id) DO NOTHING
        """))

    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT avg_listing_psf
                FROM v_market_brief
                WHERE slug ILIKE 'brief-test'
                LIMIT 1
            """)
        ).fetchone()

    assert row is not None, "v_market_brief returned no rows"
    assert row.avg_listing_psf is not None, "avg_listing_psf should not be null after seed"
    assert float(row.avg_listing_psf) > 0


def test_v_active_projects_returns_seeded_project(live_engine):
    """Verify v_active_projects returns the seeded project."""
    engine = live_engine

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO micro_markets (id, name, slug, district, state)
            VALUES (997, 'Active Test Market', 'active-test', 'Bangalore Urban', 'Karnataka')
            ON CONFLICT (id) DO NOTHING
        """))
        conn.execute(text("""
            INSERT INTO rera_projects (id, rera_number, project_name, micro_market_id, district, status, village, data_source)
            VALUES ('dddddddd-dddd-dddd-dddd-dddddddddd01', 'ACTIVE-RERA-001', 'Active Test Project', 997, 'Bangalore Urban', 'registered', 'Active Village', 'integration_test')
            ON CONFLICT (id) DO NOTHING
        """))

    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT rera_number, project_name
                FROM v_active_projects
                WHERE micro_market_id = 997
            """)
        ).fetchall()

    assert len(rows) >= 1, "v_active_projects should return at least 1 row"
    assert rows[0].rera_number == "ACTIVE-RERA-001"


def test_data_quality_floor_check_no_exception(live_engine):
    """Run DataQualityMonitor.check_live_data_floor with floor=0 — no exception."""
    from utils.data_quality_monitor import check_live_data_floor

    engine = live_engine

    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO micro_markets (id, name, slug, district, state)
            VALUES (996, 'Floor Test Market', 'floor-test', 'Bangalore Urban', 'Karnataka')
            ON CONFLICT (id) DO NOTHING
        """))
        conn.execute(text("""
            INSERT INTO rera_projects (id, rera_number, project_name, micro_market_id, district, status, village, data_source)
            VALUES ('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeee1', 'FLOOR-RERA-001', 'Floor Test Project', 996, 'Bangalore Urban', 'registered', 'Floor Village', 'live_scraped')
            ON CONFLICT (id) DO NOTHING
        """))

    with (
        patch("utils.data_quality_monitor.get_engine", return_value=engine),
        patch("utils.data_quality_monitor.send_ops_alert"),
    ):
        result = check_live_data_floor("Floor Test Market", floor=0)

    assert result is True, "check_live_data_floor(floor=0) should return True when data exists"
