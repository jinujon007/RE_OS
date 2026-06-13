"""Tests for demand coefficient calibration (GATE-94, T-1154)."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date
pytestmark = pytest.mark.unit


def test_calibration_returns_result_dataclass():
    from utils.demand_calibration import DemandCalibration, CalibrationResult
    cal = DemandCalibration()
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []
        result = cal.run()
    assert isinstance(result, CalibrationResult)
    assert result.verdict == "UNCALIBRATED"
    assert result.last_checked == date.today().isoformat()


def test_calibration_returns_uncertain_on_few_points():
    from utils.demand_calibration import DemandCalibration
    cal = DemandCalibration()
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            (2023, 50, 5000.0),
        ]
        result = cal.run()
    assert result.verdict == "UNCALIBRATED"
    assert "Only 1" in result.detail


def test_calibration_computes_coefficient():
    from utils.demand_calibration import DemandCalibration
    cal = DemandCalibration()
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            (2020, 200, 4500.0),
            (2021, 350, 4800.0),
            (2022, 500, 5200.0),
            (2023, 700, 5800.0),
        ]
        result = cal.run()
    assert result.data_points >= 2
    assert result.coefficient > 0
    assert result.verdict in ("CALIBRATED", "UNCALIBRATED")


def test_apply_calibration_status_uncallibrated():
    from utils.demand_calibration import DemandCalibration, CalibrationResult
    from intelligence.demand_intel import DemandSignals
    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-13")
    assert ds.calibration_status == "UNCALIBRATED"
    cal = DemandCalibration()
    cal.apply_calibration_status(ds)
    assert ds.calibration_status == "UNCALIBRATED"


def test_coefficient_computation_with_synthetic_data():
    """F13 fix: test _compute_coefficient with synthetic data directly."""
    from utils.demand_calibration import DemandCalibration, CalibrationResult
    cal = DemandCalibration()
    result = CalibrationResult()
    synthetic_rows = [
        (2020, 200, 4500.0),
        (2021, 350, 4800.0),
        (2022, 500, 5200.0),
        (2023, 700, 5800.0),
    ]
    cal._compute_coefficient(synthetic_rows, result)
    assert result.data_points == 4
    assert result.coefficient > 0
    assert result.detail != ""


def test_get_calibration_status_returns_string():
    from utils.demand_calibration import get_calibration_status
    with patch("utils.demand_calibration.DemandCalibration.run") as mock_run:
        mock_result = MagicMock()
        mock_result.verdict = "UNCALIBRATED"
        mock_run.return_value = mock_result
        status = get_calibration_status()
    assert status == "UNCALIBRATED"
