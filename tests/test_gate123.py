"""GATE-123 declaration — Kill Criteria + Prediction Ledger + Moat.

Five assertions — all code-verifiable without live DB:
1. Corridor backtest job registered + kill-criteria endpoint queries corridor_backtest_verdicts
2. docs/moat.md exists + contains assembly detection + Zapkey + kill criterion
3. CLAUDE.md moat correction: Form17/assembly detection appears; uncontested is negated near deed data
4. Kill criteria reminder job registered
5. Ledger unverifiable case: registered_transactions NULL returns unverifiable without raise
"""
import pathlib
from unittest.mock import patch, MagicMock

import pytest

pytestmark = pytest.mark.unit


def test_gate123_corridor_backtest_job_and_endpoint():
    """(1) corridor_backtest_monthly registered; kill-criteria corridor reads rank_correlation."""
    scheduler_path = pathlib.Path("config/scheduler/maintenance_jobs.py")
    scheduler_content = scheduler_path.read_text(encoding="utf-8")
    assert 'id="corridor_backtest_monthly"' in scheduler_content, (
        "corridor_backtest_monthly job not registered"
    )

    ops_path = pathlib.Path("dashboard/routers/ops.py")
    ops_content = ops_path.read_text(encoding="utf-8")
    assert "rank_correlation" in ops_content, (
        "kill_criteria endpoint must query rank_correlation from corridor_backtest_verdicts"
    )
    assert "corridor_backtest_verdicts" in ops_content, (
        "kill_criteria endpoint must query from corridor_backtest_verdicts table"
    )


def test_gate123_moat_doc():
    """(2) docs/moat.md exists with required content."""
    path = pathlib.Path("docs/moat.md")
    assert path.exists(), "docs/moat.md must exist"
    content = path.read_text(encoding="utf-8")
    assert "assembly detection" in content.lower()
    assert "Zapkey" in content
    assert "kill criteria" in content.lower() or "Kill Criteria" in content or "Kill Criterion" in content


def test_gate123_claude_md_moat_correction():
    """(3) CLAUDE.md moat: Form17/assembly detection present; uncontested is qualified."""
    path = pathlib.Path("CLAUDE.md")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    moat_context_found = "assembly detection" in content or "Form17 parcel" in content or "Form17" in content
    assert moat_context_found, (
        "CLAUDE.md must mention assembly detection or Form17 parcel in moat context"
    )
    assert "uncontested" in content, (
        "uncontested should appear in the moat correction context"
    )
    deed_uncontested_lines = [ln for ln in content.split("\n") if "uncontested" in ln]
    for line in deed_uncontested_lines:
        if "uncontested" in line:
            assert "NOT" in line or "not" in line, (
                f"uncontested must be negated near 'deed data': {line.strip()}"
            )


def test_gate123_kill_criteria_reminder():
    """(4) kill_criteria_weekly_reminder job registered; function defined."""
    scheduler_path = pathlib.Path("config/scheduler/maintenance_jobs.py")
    content = scheduler_path.read_text(encoding="utf-8")
    assert 'id="kill_criteria_weekly_reminder"' in content, (
        "kill_criteria_weekly_reminder job not registered"
    )
    assert "def run_kill_criteria_reminder" in content, (
        "run_kill_criteria_reminder function must be defined in maintenance_jobs.py"
    )


def test_gate123_ledger_unverifiable():
    """(5) ledger psf_forecast: when registered_transactions returns NULL, function returns None without raise."""
    from utils.prediction_ledger import _get_market_median_psf_for_month
    from datetime import date

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = (None,)
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("utils.prediction_ledger.get_engine", return_value=mock_engine):
        result = _get_market_median_psf_for_month("Yelahanka", date(2026, 7, 1))

    assert result is None, "Should return None when registered_transactions has no data for that month"
