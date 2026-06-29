"""GATE-157: Intelligence Calibration — 5 gate assertions (A1-A5).

A1: run_calibration_check returns dict with all 6 keys
A2: Migration 0076 importable + calibration_snapshots in upgrade SQL
A3: run_weekly_calibration importable from config.scheduler.forecast_jobs
A4: GET /api/v1/ops/calibration returns 200 + markets + overall_health
A5: run_calibration_check("UnknownMarket") returns dict without raising
"""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_API_KEY_READ", "test-read-key")
os.environ.setdefault("DASHBOARD_API_KEY_ADMIN", "test-admin-key")

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────────


def _mock_three_markets():
    return ["Yelahanka", "Devanahalli", "Hebbal"]


def _make_mock_conn(execute_return_values):
    """Build a mock connection from a list of per-call return values.

    Each element in execute_return_values is either a tuple (for fetchone
    to return) or None. The mock returns a MagicMock whose fetchone returns
    that value.
    """
    mock_conn = MagicMock()
    side_effects = []
    for val in execute_return_values:
        m = MagicMock()
        if val is None:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = val
        side_effects.append(m)
    mock_conn.execute.side_effect = side_effects
    return mock_conn


# ── A1: run_calibration_check returns all 6 keys ─────────────────────


def test_gate157_a1_calibration_check_returns_dict():
    """A1: run_calibration_check('Yelahanka') returns dict with all 6 keys."""
    from utils.intelligence_calibrator import run_calibration_check

    with (
        patch("utils.prediction_tracker.compute_mape", return_value=12.5) as _,
        patch("utils.intelligence_calibrator._query_mape_trend", return_value="stable"),
        patch("utils.intelligence_calibrator._query_confidence_distribution",
              return_value={"high": 10, "medium": 5, "low": 2}),
        patch("utils.intelligence_calibrator._query_stale_memory_count", return_value=3),
        patch("utils.intelligence_calibrator._query_news_coverage_pct", return_value=75.0),
    ):
        result = run_calibration_check("Yelahanka")

    assert isinstance(result, dict)
    assert "mape_4wk" in result
    assert "mape_26wk" in result
    assert "mape_trend" in result
    assert "confidence_distribution" in result
    assert "stale_memory_count" in result
    assert "news_coverage_pct" in result
    assert result["mape_4wk"] == 12.5
    assert result["mape_trend"] == "stable"
    assert result["confidence_distribution"] == {"high": 10, "medium": 5, "low": 2}
    assert result["stale_memory_count"] == 3
    assert result["news_coverage_pct"] == 75.0


def test_gate157_a1_compute_mape_uses_model_version():
    """A1 edge: mape_4wk uses model_version='v1_4wk', mape_26wk uses default."""
    from utils.intelligence_calibrator import run_calibration_check

    call_log = []

    def _tracking_compute_mape(market, min_samples=2, model_version=None, conn=None):
        call_log.append({"market": market, "model_version": model_version})
        return 10.0

    with (
        patch("utils.intelligence_calibrator._query_mape_trend", return_value="stable"),
        patch("utils.intelligence_calibrator._query_confidence_distribution", return_value={}),
        patch("utils.intelligence_calibrator._query_stale_memory_count", return_value=0),
        patch("utils.intelligence_calibrator._query_news_coverage_pct", return_value=None),
        patch("utils.prediction_tracker.compute_mape", side_effect=_tracking_compute_mape),
    ):
        run_calibration_check("Hebbal")

    assert len(call_log) == 2
    assert call_log[0]["model_version"] == "v1_4wk"
    assert call_log[1]["model_version"] is None


def test_gate157_a1_check_empty_market_returns_dict():
    """A1 edge: empty market string returns empty dict without raising."""
    from utils.intelligence_calibrator import run_calibration_check

    result = run_calibration_check("")

    assert isinstance(result, dict)
    assert result["mape_4wk"] is None
    assert result["mape_26wk"] is None
    assert result["mape_trend"] == "unknown"
    assert result["confidence_distribution"] == {}


# ── A2: Migration 0076 structure ─────────────────────────────────────


def test_gate157_a2_migration_0076_structure():
    """A2: Migration 0076 importable + calibration_snapshots in upgrade SQL."""
    import importlib.util
    from pathlib import Path
    migration_path = Path("alembic/versions/0076_calibration_snapshots.py")
    assert migration_path.exists(), "Migration file not found"

    spec = importlib.util.spec_from_file_location("migration_0076", migration_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")
    assert mod.down_revision == "0075_parcel_graph_edges"

    import inspect
    upgrade_src = inspect.getsource(mod.upgrade)
    assert "calibration_snapshots" in upgrade_src
    assert "mape_4wk" in upgrade_src
    assert "ck_calibration_mape_trend" in upgrade_src


# ── A3: run_weekly_calibration importable from forecast_jobs ──────────


def test_gate157_a3_weekly_calibration_importable():
    """A3: run_weekly_calibration importable + in __all__."""
    from config.scheduler.forecast_jobs import run_weekly_calibration, __all__

    assert callable(run_weekly_calibration)
    assert "run_weekly_calibration" in __all__


# ── A4: Calibration endpoint returns 200 + required keys ──────────────


def test_gate157_a4_calibration_endpoint():
    """A4: GET /api/v1/ops/calibration returns 200 + markets + overall_health."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    ts = datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)
    mock_conn = _make_mock_conn([
        (12.5, "stable", 3, ts),
        (14.0, "stable", 1, ts),
        None,
    ])

    with (
        patch("dashboard.routers.ops._get_sa_engine") as mock_eng,
        patch("dashboard.routers.ops._calibration_markets", return_value=_mock_three_markets()),
    ):
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        resp = client.get(
            "/api/v1/ops/calibration",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "markets" in data
    assert "overall_health" in data
    assert "generated_at" in data
    assert len(data["markets"]) == 3
    assert data["markets"][0]["market"] == "Yelahanka"
    assert data["markets"][0]["mape_4wk"] == 12.5
    assert data["markets"][0]["mape_trend"] == "stable"
    assert data["markets"][1]["market"] == "Devanahalli"
    assert data["markets"][2]["market"] == "Hebbal"
    assert data["markets"][2]["mape_4wk"] is None
    assert data["overall_health"] == "good"


def test_gate157_a4_overall_health_degrading():
    """A4 edge: degrading trend produces overall_health='degrading'."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    ts = datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)
    mock_conn = _make_mock_conn([
        (18.0, "degrading", 3, ts),
        (12.5, "stable", 1, ts),
        None,
    ])

    with (
        patch("dashboard.routers.ops._get_sa_engine") as mock_eng,
        patch("dashboard.routers.ops._calibration_markets", return_value=_mock_three_markets()),
    ):
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        resp = client.get(
            "/api/v1/ops/calibration",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    assert resp.json()["overall_health"] == "degrading"


def test_gate157_a4_overall_health_high_mape():
    """A4 edge: mape_4wk > 25 produces overall_health='degrading'."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    ts = datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)
    mock_conn = _make_mock_conn([
        (30.0, "stable", 3, ts),
        None,
        None,
    ])

    with (
        patch("dashboard.routers.ops._get_sa_engine") as mock_eng,
        patch("dashboard.routers.ops._calibration_markets", return_value=_mock_three_markets()),
    ):
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        resp = client.get(
            "/api/v1/ops/calibration",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    assert resp.json()["overall_health"] == "degrading"


def test_gate157_a4_overall_health_no_data():
    """A4 edge: no data for any market → overall_health='unknown'."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    mock_conn = _make_mock_conn([None, None, None])

    with (
        patch("dashboard.routers.ops._get_sa_engine") as mock_eng,
        patch("dashboard.routers.ops._calibration_markets", return_value=_mock_three_markets()),
    ):
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        resp = client.get(
            "/api/v1/ops/calibration",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    assert resp.json()["overall_health"] == "unknown"


def test_gate157_a4_db_failure_returns_partial():
    """A4 edge: DB connection failure returns markets list (all empty) without 500."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    with (
        patch("dashboard.routers.ops._get_sa_engine") as mock_eng,
        patch("dashboard.routers.ops._calibration_markets", return_value=_mock_three_markets()),
    ):
        mock_eng.return_value.connect.side_effect = Exception("connection refused")

        resp = client.get(
            "/api/v1/ops/calibration",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["markets"]) == 3
    assert data["overall_health"] == "unknown"


# ── A5: Unknown market returns dict without raising ──────────────────


def test_gate157_a5_unknown_market_returns_dict():
    """A5: run_calibration_check('UnknownMarket') returns dict without raising."""
    from utils.intelligence_calibrator import run_calibration_check

    with (
        patch("utils.prediction_tracker.compute_mape", return_value=None),
        patch("utils.intelligence_calibrator._query_mape_trend", return_value="unknown"),
        patch("utils.intelligence_calibrator._query_confidence_distribution", return_value={}),
        patch("utils.intelligence_calibrator._query_stale_memory_count", return_value=0),
        patch("utils.intelligence_calibrator._query_news_coverage_pct", return_value=None),
    ):
        result = run_calibration_check("UnknownMarket")

    assert isinstance(result, dict)
    assert result["mape_4wk"] is None
    assert result["mape_26wk"] is None
    assert result["mape_trend"] == "unknown"
    assert result["confidence_distribution"] == {}
    assert result["stale_memory_count"] == 0
    assert result["news_coverage_pct"] is None


# ── Direct _compute_overall_health unit test (C7) ────────────────────


def test_compute_overall_health_good():
    """_compute_overall_health: all ≤15 MAPE, no degrading → good."""
    from dashboard.routers.ops import _compute_overall_health, CalibrationMarketItem

    items = [
        CalibrationMarketItem(market="Y", mape_4wk=10.0, mape_trend="stable"),
        CalibrationMarketItem(market="D", mape_4wk=12.5, mape_trend="improving"),
        CalibrationMarketItem(market="H", mape_4wk=14.9, mape_trend="stable"),
    ]
    assert _compute_overall_health(items) == "good"


def test_compute_overall_health_degrading_trend():
    """_compute_overall_health: any degrading → degrading."""
    from dashboard.routers.ops import _compute_overall_health, CalibrationMarketItem

    items = [
        CalibrationMarketItem(market="Y", mape_4wk=10.0, mape_trend="degrading"),
        CalibrationMarketItem(market="D", mape_4wk=5.0, mape_trend="stable"),
    ]
    assert _compute_overall_health(items) == "degrading"


def test_compute_overall_health_high_mape():
    """_compute_overall_health: any mape >25 → degrading."""
    from dashboard.routers.ops import _compute_overall_health, CalibrationMarketItem

    items = [
        CalibrationMarketItem(market="Y", mape_4wk=26.0, mape_trend="stable"),
    ]
    assert _compute_overall_health(items) == "degrading"


def test_compute_overall_health_empty():
    """_compute_overall_health: empty list → unknown."""
    from dashboard.routers.ops import _compute_overall_health

    assert _compute_overall_health([]) == "unknown"


def test_compute_overall_health_no_data_in_markets():
    """_compute_overall_health: all mape_4wk=None in all markets → unknown."""
    from dashboard.routers.ops import _compute_overall_health, CalibrationMarketItem

    items = [
        CalibrationMarketItem(market="Y"),
        CalibrationMarketItem(market="D", mape_4wk=None, mape_trend=None),
    ]
    assert _compute_overall_health(items) == "unknown"


def test_compute_overall_health_partial_data():
    """_compute_overall_health: some with data, some without → uses only data-bearing markets."""
    from dashboard.routers.ops import _compute_overall_health, CalibrationMarketItem

    items = [
        CalibrationMarketItem(market="Y", mape_4wk=10.0, mape_trend="stable"),
        CalibrationMarketItem(market="D"),
    ]
    assert _compute_overall_health(items) == "good"


# ── Route registration helper ────────────────────────────────────────


def test_gate157_a5_calibration_route_registered():
    """A5 supplement: calibration route registered in ops router."""
    from dashboard.routers.ops import router
    route_paths = [r.path for r in router.routes]
    assert "/ops/calibration" in route_paths
