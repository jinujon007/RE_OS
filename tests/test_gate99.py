"""GATE-99 declaration — RTC Chain: Bhoomi Ownership History per Parcel.

Assertions:
    1. Migration 0061 exists and contains parcel_ownership_chain with UUID PK.
    2. BhoomiRTCParser imports and returns dict on minimal input (tolerant).
    3. ParcelLinker has enrich_ownership callable.
    4. GET /api/parcel/ownership route registered in FastAPI app (exact path match).
    5. run_parcel_ownership_enrichment registered in scheduler.
"""

import pytest
pytestmark = pytest.mark.unit


class TestGate99:
    def test_migration_0061_exists(self):
        import pathlib
        mig = pathlib.Path("alembic/versions/0061_parcel_ownership_chain.py")
        assert mig.exists()
        content = mig.read_text()
        assert "parcel_ownership_chain" in content
        assert "sa.UUID()" in content

    def test_bhoomi_rtc_parser_importable_and_tolerant(self):
        from scrapers.bhoomi_rtc_parser import BhoomiRTCParser
        parser = BhoomiRTCParser()
        result = parser.parse("<html></html>")
        assert isinstance(result, dict)
        assert "khata_no" in result
        assert "owner_name" in result
        assert "govt_acquisition_notice" in result
        assert "encumbrance_flag" in result
        assert "parser_completeness_score" in result
        assert result["parser_completeness_score"] == 0.0

    def test_parcel_linker_has_enrich_ownership(self):
        from utils.parcel_linker import enrich_ownership, enrich_all_parcels
        assert callable(enrich_ownership)
        assert callable(enrich_all_parcels)

    def test_ownership_route_registered_exact_path(self):
        from dashboard.app_fastapi import app
        routes = [r.path for r in app.routes]
        matched = [r for r in routes if r == "/api/parcel/ownership"]
        assert len(matched) == 1, f"Expected exactly 1 route '/api/parcel/ownership', found {len(matched)}: {matched}"

    def test_scheduler_job_registered(self):
        import pathlib
        maint = pathlib.Path("config/scheduler/maintenance_jobs.py")
        content = maint.read_text()
        assert "parcel_ownership_enrichment" in content
        assert "run_parcel_ownership_enrichment" in content
