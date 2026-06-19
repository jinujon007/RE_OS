"""GATE-126 — PSF hit rate monitoring: ledger accuracy gate.

5 assertions:
A1: /api/v1/ops/ledger/accuracy endpoint registered
A2: compute_accuracy_summary importable + returns valid shape
A3: accuracy_degradation_check job registered in scheduler
A4: degradation check fires Discord on 3rd consecutive miss
A5: endpoint response schema includes window_weeks key
"""

import pytest
from unittest.mock import MagicMock, patch, ANY

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_accuracy_streak():
    """Reset _ACCURACY_MISS_STREAK before each test (F5 fix — test isolation)."""
    import config.scheduler.kaveri_jobs as _kj
    _kj._ACCURACY_MISS_STREAK.clear()
    yield


def test_gate126_a1_accuracy_endpoint_registered():
    """A1: /api/v1/ops/ledger/accuracy endpoint registered in routes."""
    from dashboard.app_fastapi import app

    routes = [r.path for r in app.routes]
    matches = [p for p in routes if "ledger/accuracy" in p]
    assert len(matches) >= 1, f"No route containing 'ledger/accuracy' found in {routes}"
    assert any("ledger" in p and "accuracy" in p for p in matches)


def test_gate126_a2_compute_accuracy_summary_importable():
    """A2: compute_accuracy_summary importable, callable, returns expected shape."""
    from utils.prediction_ledger import compute_accuracy_summary

    assert callable(compute_accuracy_summary)

    with patch("utils.prediction_ledger.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            ("test_module", "hit", 5),
        ]

        result = compute_accuracy_summary(weeks=8)

    assert "overall" in result
    assert "by_module" in result
    assert "test_module" in result["by_module"]


def test_gate126_a3_degradation_job_registered():
    """A3: accuracy_degradation_check job ID present in scheduler __init__.py."""
    import pathlib

    src = pathlib.Path("config/scheduler/__init__.py").read_text()
    assert "accuracy_degradation_check" in src, (
        "accuracy_degradation_check job ID not found in scheduler __init__.py"
    )


def test_gate126_a4_degradation_check_fires_on_streak():
    """A4: run_accuracy_degradation_check fires Discord on 3rd consecutive miss."""
    from config.scheduler.kaveri_jobs import run_accuracy_degradation_check, _ACCURACY_MISS_STREAK

    mock_data = {
        "by_module": {
            "psf_forecast": {"hit_rate": 0.25, "total": 20, "hit": 5, "miss": 15, "partial": 0, "unverifiable": 0},
        }
    }

    with patch("config.scheduler.kaveri_jobs._compute_accuracy_summary", return_value=mock_data):
        with patch("config.scheduler.kaveri_jobs._send_ops_alert_accuracy") as mock_alert:
            run_accuracy_degradation_check()
            run_accuracy_degradation_check()
            run_accuracy_degradation_check()

    mock_alert.assert_called_once_with("LEDGER_ACCURACY_DEGRADED", ANY)


def test_gate126_a4b_degradation_check_fails_fires_discord():
    """A4b: run_accuracy_degradation_check fires Discord OPS alert on its own failure."""
    from config.scheduler.kaveri_jobs import run_accuracy_degradation_check

    with patch("config.scheduler.kaveri_jobs._compute_accuracy_summary", side_effect=RuntimeError("DB timeout")):
        with patch("config.scheduler.kaveri_jobs._send_ops_alert_accuracy") as mock_alert:
            run_accuracy_degradation_check()

    mock_alert.assert_called_once_with("ACCURACY_CHECK_FAILED", ANY)


def test_gate126_a5_endpoint_window_weeks():
    """A5: endpoint response schema includes window_weeks."""
    from utils.prediction_ledger import compute_accuracy_summary

    with patch("utils.prediction_ledger.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        result = compute_accuracy_summary(weeks=12)

    assert result["window_weeks"] == 12
