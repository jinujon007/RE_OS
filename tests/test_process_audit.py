"""T-1011 — Process Audit panel + scheduler tests."""

import pytest
from starlette.testclient import TestClient
from dashboard.app_fastapi import app

pytestmark = pytest.mark.unit

client = TestClient(app)

_TEST_KEY = "test-key"


def test_process_audit_route_returns_200():
    resp = client.get("/process-audit", headers={"X-API-Key": _TEST_KEY})
    assert resp.status_code == 200
    assert "Process Audit" in resp.text or "process" in resp.text.lower()


def test_process_audit_report_endpoint():
    resp = client.get("/api/process-audit/report", headers={"X-API-Key": _TEST_KEY})
    assert resp.status_code == 200
    data = resp.json()
    assert "report" in data
    assert "proposal" in data


def test_weekly_process_audit_job_registered():
    from config.scheduler import weekly_process_audit

    assert callable(weekly_process_audit)


def test_process_audit_health_no_auth():
    resp = client.get("/process-audit")
    assert resp.status_code in (200, 403)


def test_process_automation_metrics_import():
    from config.metrics import (
        process_audit_reports_total,
        process_audit_bottlenecks_total,
        process_audit_runbooks_total,
        process_audit_llm_calls_total,
        process_audit_tasks_created_total,
    )

    assert process_audit_reports_total._type == "counter"
    assert process_audit_bottlenecks_total._type == "counter"
