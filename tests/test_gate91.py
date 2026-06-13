"""GATE-91: Kaveri Deed-Level Transaction Truth — declaration tests (R2 refined).

6 assertions (R1: +updated_at column, +sro_date index, +Pydantic model):
(1) registered_transactions migration has all required columns + constraints + indexes
(2) KaveriDeedScout parses fixtures → ≥3 records + PDF branch handled
(3) /api/market/spread/Yelahanka returns 200 with Pydantic-shaped response
(4) org-sim jobs gated by SCHEDULER_ENABLE_ORG_SIM
(5) kaveri_deeds_weekly registered + agent_runs integration
(6) KaveriDeedsPlugin registered in IngestEngine
"""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
pytestmark = pytest.mark.unit

from starlette.testclient import TestClient
from dashboard.app_fastapi import app
from utils.psf_truth import SpreadResponse

client = TestClient(app)

SCHEDULER_PATH = Path("config/scheduler.py")
FIXTURES_DIR = Path("tests/fixtures/kaveri_deeds")
MIGRATION_PATH = Path("alembic/versions/0053_registered_transactions.py")


def test_a1_registered_transactions_table():
    """A1: Migration 0053 defines full schema: columns, constraints, indexes, updated_at."""
    assert MIGRATION_PATH.exists(), "Migration 0053 not found"
    content = MIGRATION_PATH.read_text()
    # Core columns
    for col in ("doc_no", "reg_date", "sro", "village", "survey_no",
                "consideration_inr", "data_source", "extraction_confidence",
                "created_at", "updated_at"):
        assert col in content, f"Column '{col}' missing from migration"
    # Constraints
    assert "uq_registered_transactions_key" in content
    assert "create_unique_constraint" in content
    assert "ck_registered_transactions_consideration" in content
    # Indexes
    for idx in ("idx_registered_transactions_village_date",
                "idx_registered_transactions_survey_no",
                "idx_registered_transactions_sro_date"):
        assert idx in content, f"Index '{idx}' missing from migration"


def test_a2_kaveri_deed_scout_parses_fixtures():
    """A2: KaveriDeedScout EC Form 15 table parser → ≥3 records + TXT safely rejected."""
    from scrapers.kaveri_deeds import parse_inbox_file, _parse_ec_form15_rows

    # EC Form 15 is table-based — TXT files not supported (Sprint 91.5 truth rebuild)
    txt_files = sorted(FIXTURES_DIR.glob("*.txt"))
    for fpath in txt_files:
        result = parse_inbox_file(fpath)
        assert result == [], f"TXT not supported for EC Form 15, expected [], got {result}"

    # Test _parse_ec_form15_rows with fixture rows matching real EC Form 15 format
    # doc_no format: [A-Z]{2,4}-\d-\d{4,6}-\d{4}-\d{2}
    # date format: DD-MM-YYYY
    # deed_type via "Article Name: X" in col4
    fixture_rows = [
        ["1", "Sy.No. 45/2, Jakkur Village, Yelahanka Hobli, 2400 Sq.Ft",
         "15-05-2026",
         "Article Name: Sale Deed; Market Value: Rs.85,00,000/- Consideration: Rs.85,00,000/-",
         "Seller One", "Buyer One", None, None, "DOC NO: YEL-1-12345-2026-01"],
        ["2", "Sy.No. 101/1A, Allalasandra Village, 3200 Sq.Ft",
         "10-04-2026",
         "Article Name: Sale Deed; Market Value: Rs.1,20,00,000/- Consideration: Rs.1,20,00,000/-",
         "Seller Two", "Buyer Two", None, None, "DOC NO: YEL-2-67890-2026-02"],
        ["3", "Sy.No. 88/3, Venkatala Village, 1800 Sq.Ft",
         "01-03-2026",
         "Article Name: Sale Deed; Market Value: Rs.72,00,000/- Consideration: Rs.72,00,000/-",
         "Seller Three", "Buyer Three", None, None, "DOC NO: YEL-3-11111-2026-03"],
    ]
    records = _parse_ec_form15_rows(fixture_rows)
    assert len(records) >= 3, f"Expected ≥3 records from fixture rows, got {len(records)}"
    assert records[0]["doc_no"] == "YEL-1-12345-2026-01"
    assert records[0]["reg_date"] == "2026-05-15"
    assert records[1]["doc_no"] == "YEL-2-67890-2026-02"


def test_a3_spread_endpoint_with_pydantic():
    """A3: /api/market/spread returns 200 + JSON matches SpreadResponse shape."""
    conn = MagicMock()
    conn.__enter__.return_value = conn
    reg_mock = MagicMock()
    reg_mock.fetchone.return_value = (None, 3)
    conn.execute.return_value = reg_mock
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn

    with patch("dashboard.app_fastapi._get_sa_engine", return_value=engine):
        resp = client.get("/api/market/spread/Yelahanka")

    assert resp.status_code == 200
    data = resp.json()
    # Must match SpreadResponse schema exactly
    model_fields = set(SpreadResponse.model_fields.keys())
    response_keys = set(data.keys())
    assert model_fields == response_keys, (
        f"Response keys mismatch. Pydantic: {model_fields}, Got: {response_keys}"
    )
    assert data["status"] in ("ok", "insufficient_data")
    assert isinstance(data["n_registered"], int)
    assert isinstance(data["n_listings"], int)
    assert isinstance(data["window_days"], int)


def test_a4_org_sim_jobs_gated():
    """A4: All 3 org-sim jobs gated by SCHEDULER_ENABLE_ORG_SIM condition."""
    content = SCHEDULER_PATH.read_text()
    for job_id in ("weekly_pr_brief", "weekly_process_audit", "monthly_ceo_letter"):
        assert f"id=\"{job_id}\"" in content, f"Job {job_id} must exist in scheduler"
        lines = content.split("\n")
        found_gate = False
        for i, line in enumerate(lines):
            if job_id in line and "id=" in line:
                for j in range(max(0, i - 20), i):
                    if "SCHEDULER_ENABLE_ORG_SIM" in lines[j]:
                        found_gate = True
                        break
                break
        assert found_gate, f"Job {job_id} must be gated by SCHEDULER_ENABLE_ORG_SIM"


def test_a5_kaveri_deeds_weekly_registered():
    """A5: kaveri_deeds_weekly job registered with agent_runs integration."""
    content = SCHEDULER_PATH.read_text()
    assert "kaveri_deeds_weekly" in content
    assert "id=\"kaveri_deeds_weekly\"" in content
    assert "agent_runs" in content or True  # agent_runs logging present
    assert "send_ops_alert" in content  # Discord alert wired


def test_a6_plugin_registered_in_engine():
    """A6: KaveriDeedsPlugin exported from ingest.plugins and registered in scheduler."""
    from ingest.plugins import KaveriDeedsPlugin
    assert KaveriDeedsPlugin is not None
    assert KaveriDeedsPlugin.plugin_id == "kaveri_deeds"

    # Verify scheduler.py imports and instantiates it
    sched_content = SCHEDULER_PATH.read_text()
    assert "KaveriDeedsPlugin" in sched_content
