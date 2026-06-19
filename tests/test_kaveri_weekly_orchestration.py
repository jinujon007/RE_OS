"""Smoke tests for Kaveri weekly orchestration job (T-1312→T-1313).

Five core tests + 3 edge cases:
1. orchestration_returns_required_keys — return dict has all 5 keys
2. step1_failure_does_not_block_step3 — isolation guarantee
3. discord_summary_fires — KAVERI_WEEKLY sent
4. deed_weekly_avg_mocked — throughput value propagates to Discord
5. job_registered_in_scheduler — job ID present in __init__.py
6. empty_scan_result_does_not_crash — scan_result missing keys
7. discord_failure_does_not_propagate — send_ops_alert raise absorbed
8. multi_step_failure_accumulates_errors — 2 failing steps produce 2 errors
"""
import pathlib
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


def test_orchestration_returns_required_keys():
    """Return dict has form17_scanned, deeds_upserted, assembly_signals_checked, deed_weekly_avg, errors."""
    from config.scheduler.kaveri_jobs import run_kaveri_weekly_orchestration

    with patch("config.scheduler.maintenance_jobs.run_form17_inbox_scan") as mock_scan:
        mock_scan.return_value = {"new_pdfs": 2, "records_written": 15}
        with patch("utils.assembly_detector.run_assembly_detection"):
            with patch("config.scheduler.kaveri_jobs._compute_deed_weekly_avg", return_value=12.5):
                with patch("utils.discord_notifier.send_ops_alert"):
                    with patch("config.scheduler.kaveri_jobs.get_engine"):
                        result = run_kaveri_weekly_orchestration()

    assert isinstance(result, dict)
    assert result["form17_scanned"] == 2
    assert result["deeds_upserted"] == 15
    assert result["assembly_signals_checked"] == 1
    assert result["deed_weekly_avg"] == 12.5
    assert result["errors"] == []


def test_step1_failure_does_not_block_step3():
    """Step 1 raises; step 3 (assembly) still runs; step 1 error recorded."""
    from config.scheduler.kaveri_jobs import run_kaveri_weekly_orchestration

    with patch("config.scheduler.maintenance_jobs.run_form17_inbox_scan", side_effect=RuntimeError("inbox down")):
        with patch("utils.assembly_detector.run_assembly_detection"):
            with patch("config.scheduler.kaveri_jobs._compute_deed_weekly_avg", return_value=0.0):
                with patch("utils.discord_notifier.send_ops_alert"):
                    with patch("config.scheduler.kaveri_jobs.get_engine"):
                        result = run_kaveri_weekly_orchestration()

    assert result["assembly_signals_checked"] == 1, "Step 3 (assembly) must run despite step 1 failure"
    assert any("Form17 scan" in e for e in result["errors"]), "Form17 scan error must be in errors list"


def test_discord_summary_fires():
    """send_ops_alert called with KAVERI_WEEKLY event type."""
    from config.scheduler.kaveri_jobs import run_kaveri_weekly_orchestration

    with patch("config.scheduler.maintenance_jobs.run_form17_inbox_scan", return_value={"new_pdfs": 1, "records_written": 5}):
        with patch("utils.assembly_detector.run_assembly_detection"):
            with patch("config.scheduler.kaveri_jobs._compute_deed_weekly_avg", return_value=10.0):
                with patch("config.scheduler.kaveri_jobs.get_engine"):
                    with patch("utils.discord_notifier.send_ops_alert") as mock_alert:
                        run_kaveri_weekly_orchestration()

    mock_alert.assert_called_once()
    event_type = mock_alert.call_args[0][0]
    message = mock_alert.call_args[0][1]
    assert event_type == "KAVERI_WEEKLY"
    assert "Deed throughput (4-week avg): 10.0/week" in message


def test_deed_weekly_avg_mocked():
    """Mock throughput 37.5 propagates into Discord message."""
    from config.scheduler.kaveri_jobs import run_kaveri_weekly_orchestration

    with patch("config.scheduler.maintenance_jobs.run_form17_inbox_scan", return_value={"new_pdfs": 0, "records_written": 0}):
        with patch("utils.assembly_detector.run_assembly_detection"):
            with patch("config.scheduler.kaveri_jobs._compute_deed_weekly_avg", return_value=37.5):
                with patch("config.scheduler.kaveri_jobs.get_engine"):
                    with patch("utils.discord_notifier.send_ops_alert") as mock_alert:
                        run_kaveri_weekly_orchestration()

    assert "37.5/week" in mock_alert.call_args[0][1]


def test_job_registered_in_scheduler():
    """kaveri_weekly_orchestration exported from __init__.py."""
    content = pathlib.Path("config/scheduler/__init__.py").read_text(encoding="utf-8")
    assert "run_kaveri_weekly_orchestration" in content


def test_empty_scan_result_does_not_crash():
    """scan_result missing expected keys uses .get() defaults without raising."""
    from config.scheduler.kaveri_jobs import run_kaveri_weekly_orchestration

    with patch("config.scheduler.maintenance_jobs.run_form17_inbox_scan") as mock_scan:
        mock_scan.return_value = {"status": "uptodate"}  # no new_pdfs / records_written keys
        with patch("utils.assembly_detector.run_assembly_detection"):
            with patch("config.scheduler.kaveri_jobs._compute_deed_weekly_avg", return_value=0.0):
                with patch("utils.discord_notifier.send_ops_alert"):
                    with patch("config.scheduler.kaveri_jobs.get_engine"):
                        result = run_kaveri_weekly_orchestration()

    assert result["form17_scanned"] == 0
    assert result["deeds_upserted"] == 0
    assert result["errors"] == []


def test_discord_failure_does_not_propagate():
    """send_ops_alert raising does not propagate; function still returns results."""
    from config.scheduler.kaveri_jobs import run_kaveri_weekly_orchestration

    with patch("config.scheduler.maintenance_jobs.run_form17_inbox_scan", return_value={"new_pdfs": 0, "records_written": 0}):
        with patch("utils.assembly_detector.run_assembly_detection"):
            with patch("config.scheduler.kaveri_jobs._compute_deed_weekly_avg", return_value=0.0):
                with patch("utils.discord_notifier.send_ops_alert", side_effect=RuntimeError("webhook down")):
                    with patch("config.scheduler.kaveri_jobs.get_engine"):
                        result = run_kaveri_weekly_orchestration()

    assert isinstance(result, dict)
    assert result["errors"] == [], "Discord failure should NOT be added to pipeline errors"


def test_multi_step_failure_accumulates_errors():
    """Two steps failing produces 2 separate error entries."""
    from config.scheduler.kaveri_jobs import run_kaveri_weekly_orchestration

    with patch("config.scheduler.maintenance_jobs.run_form17_inbox_scan", side_effect=RuntimeError("scan failed")):
        with patch("utils.assembly_detector.run_assembly_detection", side_effect=RuntimeError("assembly failed")):
            with patch("config.scheduler.kaveri_jobs._compute_deed_weekly_avg", return_value=0.0):
                with patch("utils.discord_notifier.send_ops_alert"):
                    with patch("config.scheduler.kaveri_jobs.get_engine"):
                        result = run_kaveri_weekly_orchestration()

    assert len(result["errors"]) == 2, f"Expected 2 errors, got {result['errors']}"
    assert any("Form17 scan" in e for e in result["errors"])
    assert any("Assembly detect" in e for e in result["errors"])
