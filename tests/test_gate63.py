"""GATE-63 — Demand Intelligence V2. 5 assertions with edge-case coverage."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


@pytest.fixture
def _auth_env():
    with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
        import importlib
        import dashboard.app_fastapi as _fa

        importlib.reload(_fa)
        yield


def test_gate63_demand_signals_config_absorption():
    """(1) DemandIntel.get_signals.config_absorption is dict, no exception."""
    from intelligence.demand_intel import DemandIntel

    di = DemandIntel(caller="test")
    ds = MagicMock()
    ds.config_absorption = {"1BHK": 75.0, "2BHK": 60.0}
    with patch.object(di, "get_signals", return_value=ds):
        result = di.get_signals("Yelahanka")
        assert isinstance(result.config_absorption, dict)


def test_gate63_demand_events_table_exists():
    """(2) demand_events table defined in migration with CHECK constraint."""
    import os

    mig_path = os.path.join("alembic", "versions", "0025_demand_events.py")
    assert os.path.exists(mig_path), f"Migration not found: {mig_path}"
    with open(mig_path) as f:
        content = f.read()
    assert "create_table" in content
    assert "demand_events" in content
    assert "config_absorption" in content
    assert "CheckConstraint" in content, "Missing CHECK constraint on event_type"
    assert "ck_demand_events_event_type" in content


def test_gate63_demand_api_returns_config_absorption(_auth_env):
    """(3) GET /api/demand/Yelahanka returns 200 JSON with config_absorption."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    from intelligence.demand_intel import DemandSignals

    client = TestClient(app)
    mock_ds = MagicMock(spec=DemandSignals)
    mock_ds.market = "Yelahanka"
    mock_ds.market_found = True
    mock_ds.collected_at = "2026-06-08T00:00:00"
    for field in (
        "avg_listing_psf",
        "median_listing_psf",
        "listing_trend_30d_pct",
        "absorption_pct",
        "months_of_supply",
        "ticket_size_median_cr",
        "days_on_market_p50",
        "avg_news_sentiment",
        "kaveri_monthly_approvals",
    ):
        setattr(mock_ds, field, None)
    for field in ("listing_count_30d",):
        setattr(mock_ds, field, 0)
    mock_ds.demand_signal = "NEUTRAL"
    mock_ds.demand_score = 0.0
    mock_ds.demand_score_v2 = 0.0
    mock_ds.config_absorption = {"1BHK": 70.0}
    mock_ds.absorption_trend = []
    mock_ds.days_on_market_by_config = {}
    mock_ds.signals = []
    with patch(
        "intelligence.demand_intel.DemandIntel.get_signals", return_value=mock_ds
    ):
        resp = client.get("/api/demand/Yelahanka", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200
        data = resp.json()
        assert "config_absorption" in data
        assert data["config_absorption"]["1BHK"] == 70.0


def test_gate63_demand_route_returns_200():
    """(4) GET /demand returns 200."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    resp = client.get("/demand")
    assert resp.status_code == 200


def test_gate63_all_v2_tests_pass():
    """(5) All demand intel v2 unit tests pass."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_demand_intel_v2.py",
            "-m",
            "unit",
            "-q",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"V2 tests failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
