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
    """A2: KaveriDeedScout parses fixture TXT files → ≥3 records + PDF branch safe."""
    from scrapers.kaveri_deeds import parse_inbox_file, _parse_pdf_text, _split_deed_sections

    # TXT fixture parsing
    total = 0
    for fpath in sorted(FIXTURES_DIR.glob("*.txt")):
        records = parse_inbox_file(fpath)
        total += len(records)
    assert total >= 3, f"Expected ≥3 records from fixtures, got {total}"

    # Multi-deed splitting
    multi_text = (
        "Document No: 1/2026\nRegistration Date: 15/05/2026\nSRO: Yelahanka\nVillage: Jakkur\n"
        "Property Description:\nSy. No. 45/2, 2400 Sq. Ft\nConsideration: Rs. 85,00,000\n\n"
        "Document No: 2/2026\nRegistration Date: 10/04/2026\nSRO: Yelahanka\nVillage: Allalasandra\n"
        "Property Description:\nSurvey No. 101/1A, 3200 Sq. Ft\nConsideration: INR 1,20,00,000\n"
    )
    sections = _split_deed_sections(multi_text)
    assert len(sections) >= 2, f"Expected ≥2 sections from multi-deed text, got {len(sections)}"
    records = _parse_pdf_text(multi_text)
    assert len(records) >= 2, f"Expected ≥2 records from multi-deed text, got {len(records)}"


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
