"""GATE-147: Prediction ledger maturity — short-horizon + MAPE panel + all-module view.

5 gate assertions (A1-A5):
(1) _do_update_actuals calls record_prediction with horizon_weeks=4 (mock PSFForecaster)
(2) /api/v1/intel/forecast-accuracy returns mape_4wk + mape_26wk keys (mock)
(3) /api/v1/ops/ledger/full returns 200 with claim_type grouping (mock)
(4) POST /api/v1/ops/ledger/verdict route registered
(5) run_accuracy_threshold_review importable from config.scheduler.forecast_jobs; registered in scheduler
"""

import pytest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
pytestmark = pytest.mark.unit


# ── A1: _do_update_actuals calls record_prediction with horizon_weeks=4 ────


def test_gate147_a1_short_horizon_recorded():
    """A1: _do_update_actuals calls record_prediction twice per market (26wk + 4wk)."""
    from config.scheduler.forecast_jobs import _do_update_actuals
    mock_fc = MagicMock()
    mock_fc.status = "ok"
    mock_fc.data_points = 6
    mock_fc.forecast_6m = 8500.0
    mock_fc.current_psf = 8200.0
    mock_fc.model_version = "linear_v1"

    with (
        patch("utils.psf_forecaster.PSFForecaster") as mock_forecaster_cls,
        patch("utils.prediction_tracker.record_prediction", return_value=42) as mock_rec,
        patch("utils.prediction_tracker.update_actuals", return_value=3),
    ):
        mock_forecaster_cls.return_value.forecast.return_value = mock_fc
        _do_update_actuals()

    # At least 2 calls per market (short + long)
    assert mock_rec.call_count >= 4

    short_calls = [c for c in mock_rec.call_args_list if c.kwargs.get("horizon_weeks") == 4]
    long_calls = [c for c in mock_rec.call_args_list if c.kwargs.get("horizon_weeks") == 26]
    assert len(short_calls) >= 1, "No short-horizon (4wk) calls made"
    assert len(long_calls) >= 1, "No long-horizon (26wk) calls made"

    for call in short_calls:
        assert call.kwargs["psf"] == 8200.0
        assert call.kwargs["model_version"] == "v1_4wk"
        assert call.kwargs["horizon_months"] == 1

    for call in long_calls:
        assert call.kwargs["psf"] == 8500.0
        assert call.kwargs["model_version"] == "linear_v1"
        assert call.kwargs["horizon_months"] == 6


# ── A2: forecast-accuracy endpoint returns mape_4wk + mape_26wk ────────────


def test_gate147_a2_forecast_accuracy_has_mape_tiers():
    """A2: /api/v1/intel/forecast-accuracy returns mape_4wk + mape_26wk keys."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    # forecast_accuracy endpoint does `from utils.prediction_tracker import compute_mape`
    # and `from config.settings import TARGET_MARKETS` at runtime
    with (
        patch("utils.prediction_tracker.compute_mape", return_value=None),
        patch("dashboard.routers.data._get_sa_engine") as mock_db,
        patch("utils.db.get_engine") as mock_audit_db,
    ):
        mock_conn = MagicMock()
        mock_db.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_audit_db.return_value.begin.return_value.__enter__.return_value = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (0, [])

        resp = client.get("/api/v1/intel/forecast-accuracy")

    assert resp.status_code == 200
    data = resp.json()
    for market_key in data:
        assert "mape_4wk" in data[market_key], f"{market_key} missing mape_4wk"
        assert "mape_26wk" in data[market_key], f"{market_key} missing mape_26wk"


# ── A3: /api/v1/ops/ledger/full returns 200 with claim_type grouping ──────


def test_gate147_a3_ledger_full_endpoint():
    """A3: /api/v1/ops/ledger/full returns 200 with claim_type grouping."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    # The endpoint reads rows by index (r[0]=claim_type, r[1]=market, r[2]=total, r[3]=hit, r[4]=miss, r[5]=pending)
    mock_row = ("psf_forecast", "Yelahanka", 3, 1, 0, 2)

    with (
        patch("dashboard.routers.ops._get_sa_engine") as mock_db,
        patch("utils.db.get_engine") as mock_audit_db,
    ):
        mock_conn = MagicMock()
        mock_db.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_audit_db.return_value.begin.return_value.__enter__.return_value = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [mock_row]

        resp = client.get("/api/v1/ops/ledger/full")

    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "as_of" in data
    assert isinstance(data["items"], list)


# ── A4: POST /api/v1/ops/ledger/verdict route registered ─────────────────


def test_gate147_a4_verdict_route_registered():
    """A4: POST /api/v1/ops/ledger/verdict route registered."""
    from dashboard.app_fastapi import app
    routes = [(r.path, list(r.methods)) for r in app.routes if "ops/ledger/verdict" in r.path]
    matching = [(p, m) for p, m in routes if "POST" in m]
    assert matching, "POST /ops/ledger/verdict route not found"
    _, methods = matching[0]
    assert "POST" in methods


# ── A5: run_accuracy_threshold_review importable + registered in scheduler ─


def test_gate147_a5_accuracy_review_importable_and_registered():
    """A5: run_accuracy_threshold_review importable from forecast_jobs; scheduled."""
    import inspect as _inspect
    from config.scheduler.forecast_jobs import run_accuracy_threshold_review, register_jobs
    assert callable(run_accuracy_threshold_review)

    # Verify the job is registered in the scheduler by inspecting register_jobs source
    src = _inspect.getsource(register_jobs)
    assert "'accuracy_threshold_review'" in src or '"accuracy_threshold_review"' in src, \
        "accuracy_threshold_review not found in register_jobs source"
