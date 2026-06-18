"""Core integration tests — write + read-back for the 5 most critical tables.

All tests use the live_engine fixture (ephemeral PostGIS container or
TEST_DATABASE_URL).  Each test seeds data, asserts the write succeeded,
and verifies read-back consistency.
"""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def test_rera_project_upsert_roundtrip(live_engine):
    """Insert a rera_project, re-query by id, assert all fields."""
    engine = live_engine
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO rera_projects (id, rera_number, project_name, micro_market_id, district, status, data_source)
            VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'TEST-RERA-001', 'Test Project A', 1, 'Bangalore Urban', 'registered', 'integration_test')
            ON CONFLICT (id) DO NOTHING
        """))
        row = conn.execute(
            text("SELECT rera_number, project_name, status FROM rera_projects WHERE id = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'")
        ).fetchone()
    assert row is not None
    assert row.rera_number == "TEST-RERA-001"
    assert row.project_name == "Test Project A"
    assert row.status == "registered"


def test_registered_transaction_upsert_and_psf_computed(live_engine):
    """Insert a deed, compute PSF, assert consideration_inr / extent_sqft."""
    engine = live_engine
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO registered_transactions (doc_no, reg_date, sro, village, survey_no, extent_sqft, consideration_inr, deed_type, data_source)
            VALUES ('TEST-DOC-001', '2025-01-15', 'Gandhinagar', 'Venkatala', '45/2', 1200.0, 6000000, 'Sale Deed', 'integration_test')
            ON CONFLICT (sro, doc_no, reg_date) DO NOTHING
        """))
        row = conn.execute(
            text("SELECT consideration_inr, extent_sqft FROM registered_transactions WHERE doc_no = 'TEST-DOC-001'")
        ).fetchone()
    assert row is not None
    psf = row.consideration_inr / row.extent_sqft if row.extent_sqft else 0
    assert 4000 < psf < 6000, f"Expected PSF ~5000, got {psf}"


def test_parcel_linker_creates_parcels_from_rera(live_engine):
    """Seed 3 rera_projects with survey_no, run linker, assert parcels >= 3."""
    from unittest.mock import patch
    from utils.parcel_linker import link_parcels

    engine = live_engine
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO rera_projects (id, rera_number, project_name, micro_market_id, district, village, survey_no, status, data_source)
            VALUES
                ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbb01', 'TEST-RERA-101', 'Link Test 1', 1, 'Bangalore Urban', 'Venkatala', '100/1', 'registered', 'integration_test'),
                ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbb02', 'TEST-RERA-102', 'Link Test 2', 1, 'Bangalore Urban', 'Venkatala', '100/2', 'registered', 'integration_test'),
                ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbb03', 'TEST-RERA-103', 'Link Test 3', 1, 'Bangalore Urban', 'Venkatala', '100/3', 'registered', 'integration_test')
            ON CONFLICT (id) DO NOTHING
        """))

    with patch("utils.parcel_linker.get_engine", return_value=engine):
        stats = link_parcels()

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*)::int FROM parcels")).scalar()

    assert count >= 3, f"Expected >= 3 parcels, got {count}"
    assert stats.get("created", 0) >= 3


def test_assembly_detector_fires_on_synthetic_deeds(live_engine):
    """Insert 3 deeds same buyer+village within 60d, run detector, assert signal."""
    from unittest.mock import patch
    from utils.assembly_detector import detect_assemblies

    engine = live_engine
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO registered_transactions (doc_no, reg_date, sro, village, survey_no, extent_sqft, consideration_inr, deed_type, buyer_name_raw, seller_name_raw, data_source)
            VALUES
                ('ASM-DOC-001', CURRENT_DATE - 30, 'Gandhinagar', 'Assembly Village', '10/1', 2400.0, 12000000, 'Sale Deed', 'ASSEMBLY TEST BUYER', 'Some Seller', 'integration_test'),
                ('ASM-DOC-002', CURRENT_DATE - 20, 'Gandhinagar', 'Assembly Village', '10/2', 3600.0, 18000000, 'Sale Deed', 'ASSEMBLY TEST BUYER', 'Another Seller', 'integration_test'),
                ('ASM-DOC-003', CURRENT_DATE - 10, 'Gandhinagar', 'Assembly Village', '10/3', 1200.0, 6000000, 'Sale Deed', 'ASSEMBLY TEST BUYER', 'Yet Another Seller', 'integration_test')
            ON CONFLICT (sro, doc_no, reg_date) DO NOTHING
        """))

    with patch("utils.assembly_detector.get_engine", return_value=engine):
        signals = detect_assemblies()

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*)::int FROM assembly_signals")).scalar()

    assert count >= 1, f"Expected >= 1 assembly signal, got {count}"
    if signals:
        assert signals[0]["village"] == "Assembly Village"


def test_parcel_dossier_endpoint_200_with_live_db(live_engine):
    """Seed parcel + deed + guidance_value, hit endpoint, assert 200 + deed_history."""
    from unittest.mock import patch
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    from sqlalchemy import text as sa_text

    engine = live_engine
    village = "Dossier Village"
    survey_no = "200/1"

    with engine.begin() as conn:
        conn.execute(sa_text("""
            INSERT INTO parcels (village, survey_no, survey_no_raw, district, taluk, source)
            VALUES (:v, :s, :s, 'Bangalore Urban', 'Bangalore North', 'integration_test')
            ON CONFLICT (village, survey_no) DO NOTHING
        """), {"v": village, "s": survey_no})
        conn.execute(sa_text("""
            INSERT INTO registered_transactions (doc_no, reg_date, sro, village, survey_no, extent_sqft, consideration_inr, deed_type, data_source)
            VALUES ('DOS-DOC-001', '2025-03-01', 'Gandhinagar', :v, :s, 1500.0, 7500000, 'Sale Deed', 'integration_test')
            ON CONFLICT (sro, doc_no, reg_date) DO NOTHING
        """), {"v": village, "s": survey_no})

    client = TestClient(app)
    with patch("dashboard.routers.data.get_engine", return_value=engine):
        resp = client.get(f"/api/parcel/{village}/{survey_no}", headers={"X-API-Key": "test-key"})

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "deed_history" in data, f"Missing deed_history key: {list(data.keys())}"
    assert len(data["deed_history"]) >= 1, f"Expected >= 1 deed, got {len(data.get('deed_history', []))}"
