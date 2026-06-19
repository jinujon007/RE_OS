"""Tests for prediction ledger accuracy endpoint + degradation check (GATE-126, T-1317→T-1320)."""

import pytest
from unittest.mock import MagicMock, patch, ANY

pytestmark = pytest.mark.unit

# The degradation check function uses module-level aliases:
#   _compute_accuracy_summary = compute_accuracy_summary
#   _send_ops_alert_accuracy  = send_ops_alert
# So we patch the underlying module, not the alias.


# ── Shared autouse fixture: reset module-level mutable state ──────────────────


@pytest.fixture(autouse=True)
def _reset_accuracy_streak():
    """Reset _ACCURACY_MISS_STREAK before each test (F5 fix — test isolation).
    Prevents streak state leaking between tests when run in any order.
    """
    import config.scheduler.kaveri_jobs as _kj

    _kj._ACCURACY_MISS_STREAK.clear()
    yield


# ── compute_accuracy_summary tests ───────────────────────────────────────────


def test_accuracy_summary_schema():
    """compute_accuracy_summary returns correct schema with mocked DB rows."""
    from utils.prediction_ledger import compute_accuracy_summary

    mock_rows = [
        ("psf_forecast", "hit", 10),
        ("psf_forecast", "miss", 3),
        ("psf_forecast", "unverifiable", 2),
        ("opportunity_score", "hit", 5),
        ("opportunity_score", "miss", 5),
    ]

    with patch("utils.prediction_ledger.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        result = compute_accuracy_summary(weeks=12)

    assert result["window_weeks"] == 12
    assert "overall" in result
    assert "by_module" in result
    assert "psf_forecast" in result["by_module"]
    assert "opportunity_score" in result["by_module"]

    pf = result["by_module"]["psf_forecast"]
    assert pf["hits"] == 10
    assert pf["misses"] == 3
    assert pf["total"] == 15
    assert round(pf["hit_rate"], 4) == round(10 / 13, 4)

    assert result["overall"]["total_resolved"] == 23
    assert result["overall"]["total_unverifiable"] == 2


def test_accuracy_summary_zero_data():
    """compute_accuracy_summary returns zeros/empty when no data."""
    from utils.prediction_ledger import compute_accuracy_summary

    with patch("utils.prediction_ledger.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        result = compute_accuracy_summary(weeks=52)

    assert result["overall"]["hit_rate"] == 0.0
    assert result["overall"]["total_resolved"] == 0
    assert result["by_module"] == {}


def test_accuracy_summary_db_error_returns_zeros():
    """compute_accuracy_summary returns safe defaults on DB error."""
    from utils.prediction_ledger import compute_accuracy_summary

    with patch("utils.prediction_ledger.get_engine") as mock_eng:
        mock_eng.return_value.connect.side_effect = Exception("DB down")

        result = compute_accuracy_summary(weeks=12)

    assert result["overall"]["hit_rate"] == 0.0
    assert result["by_module"] == {}


# ── run_accuracy_degradation_check tests ─────────────────────────────────────


def test_degradation_check_fires_on_3_streak():
    """run_accuracy_degradation_check fires Discord alert after 3 consecutive misses."""
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


def test_degradation_check_fires_once_for_multiple_modules():
    """run_accuracy_degradation_check fires ONE alert when multiple modules degraded."""
    from config.scheduler.kaveri_jobs import run_accuracy_degradation_check

    mock_data = {
        "by_module": {
            "psf_forecast": {"hit_rate": 0.25, "total": 20, "hit": 5, "miss": 15, "partial": 0, "unverifiable": 0},
            "opportunity_score": {"hit_rate": 0.20, "total": 10, "hit": 2, "miss": 8, "partial": 0, "unverifiable": 0},
        }
    }

    with patch("config.scheduler.kaveri_jobs._compute_accuracy_summary", return_value=mock_data):
        with patch("config.scheduler.kaveri_jobs._send_ops_alert_accuracy") as mock_alert:
            run_accuracy_degradation_check()
            run_accuracy_degradation_check()
            run_accuracy_degradation_check()

    assert mock_alert.call_count == 1, f"Expected 1 alert for 2 degraded modules, got {mock_alert.call_count}"


def test_degradation_check_no_fire_below_threshold():
    """run_accuracy_degradation_check does NOT fire on first miss (streak < 3)."""
    from config.scheduler.kaveri_jobs import run_accuracy_degradation_check, _ACCURACY_MISS_STREAK

    mock_data = {
        "by_module": {
            "psf_forecast": {"hit_rate": 0.25, "total": 20, "hit": 5, "miss": 15, "partial": 0, "unverifiable": 0},
        }
    }

    with patch("config.scheduler.kaveri_jobs._compute_accuracy_summary", return_value=mock_data):
        with patch("config.scheduler.kaveri_jobs._send_ops_alert_accuracy") as mock_alert:
            run_accuracy_degradation_check()

    mock_alert.assert_not_called()


def test_degradation_check_skips_low_volume():
    """run_accuracy_degradation_check skips modules with fewer than 5 total verdicts."""
    from config.scheduler.kaveri_jobs import run_accuracy_degradation_check, _ACCURACY_MISS_STREAK

    mock_data = {
        "by_module": {
            "psf_forecast": {"hit_rate": 0.0, "total": 3, "hit": 0, "miss": 3, "partial": 0, "unverifiable": 0},
        }
    }

    with patch("config.scheduler.kaveri_jobs._compute_accuracy_summary", return_value=mock_data):
        with patch("config.scheduler.kaveri_jobs._send_ops_alert_accuracy") as mock_alert:
            run_accuracy_degradation_check()
            run_accuracy_degradation_check()
            run_accuracy_degradation_check()

    assert _ACCURACY_MISS_STREAK.get("psf_forecast", 0) == 0
    mock_alert.assert_not_called()


def test_degradation_check_streak_resets_on_improvement():
    """Streak resets to 0 when hit_rate recovers above threshold."""
    from config.scheduler.kaveri_jobs import run_accuracy_degradation_check, _ACCURACY_MISS_STREAK

    mock_bad = {
        "by_module": {
            "psf_forecast": {"hit_rate": 0.25, "total": 20, "hit": 5, "miss": 15, "partial": 0, "unverifiable": 0},
        }
    }
    mock_good = {
        "by_module": {
            "psf_forecast": {"hit_rate": 0.80, "total": 20, "hit": 16, "miss": 4, "partial": 0, "unverifiable": 0},
        }
    }

    with patch("config.scheduler.kaveri_jobs._send_ops_alert_accuracy") as mock_alert:
        with patch("config.scheduler.kaveri_jobs._compute_accuracy_summary") as mock_summary:
            mock_summary.return_value = mock_bad
            run_accuracy_degradation_check()
            run_accuracy_degradation_check()

            mock_summary.return_value = mock_good
            run_accuracy_degradation_check()

    assert _ACCURACY_MISS_STREAK.get("psf_forecast", 0) == 0
    mock_alert.assert_not_called()
