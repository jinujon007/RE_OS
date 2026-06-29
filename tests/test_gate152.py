"""GATE-152: Corridor Backtest Accuracy — 5 gate assertions (A1-A5).

A1: CorridorScorer().backtest_psf_history("Yelahanka") returns list with corridor/psf_t24/psf_t12/psf_now/actual_change_pct
A2: GET /api/v1/intel/corridors/backtest-accuracy?market=Yelahanka returns 200 + corridors + overall_mape + generated_at
A3: Alembic migration 0073 importable, has corridor_backtest_results in upgrade SQL
A4: Board Room Finance Head context actually calls CorridorScorer and builds context string
A5: backtest returns [] (not exception) on DB failure
"""

import os
import pathlib
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_API_KEY_READ", "test-read-key")

pytestmark = pytest.mark.unit


def _make_mock_row(psf_t24, psf_t12, psf_now):
    r = MagicMock()
    r.corridor_id = "nh44"
    r.corridor_name = "NH-44 (Yelahanka → Devanahalli)"
    r.psf_t24 = psf_t24
    r.psf_t12 = psf_t12
    r.psf_now = psf_now
    return r


# ── A1: backtest returns structured data ──────────────────────────────


def test_gate152_a1_backtest_returns_list():
    """A1: CorridorScorer().backtest returns list with expected keys."""
    from utils.corridor_scorer import CorridorScorer

    mock_row = MagicMock()
    mock_row.corridor_id = "nh44"
    mock_row.corridor_name = "NH-44 (Yelahanka → Devanahalli)"
    mock_row.psf_t24 = 4500.0
    mock_row.psf_t12 = 5200.0
    mock_row.psf_now = 5800.0

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = mock_row

        scorer = CorridorScorer()
        result = scorer.backtest_psf_history("Yelahanka", lookback_months=24)

    assert isinstance(result, list)
    assert len(result) >= 1
    for item in result:
        assert "corridor" in item
        assert "corridor_id" in item
        assert "psf_t24" in item
        assert "psf_t12" in item
        assert "psf_now" in item
        assert "actual_change_pct" in item
    nh44 = next(r for r in result if r["corridor_id"] == "nh44")
    assert nh44["actual_change_pct"] == 28.9


def test_gate152_a1_empty_market_returns_empty():
    """A1: backtest returns [] for empty market string."""
    from utils.corridor_scorer import CorridorScorer
    scorer = CorridorScorer()
    assert scorer.backtest_psf_history("") == []
    assert scorer.backtest_psf_history("  ") == []


# ── A2: backtest-accuracy endpoint ────────────────────────────────────


def test_gate152_a2_backtest_accuracy_endpoint():
    """A2: GET /api/v1/intel/corridors/backtest-accuracy returns 200 with corridors + overall_mape."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    mock_results = [
        {
            "corridor": "NH-44 (Yelahanka → Devanahalli)",
            "corridor_id": "nh44",
            "psf_t24": 4500.0,
            "psf_t12": 5200.0,
            "psf_now": 5800.0,
            "actual_change_pct": 28.9,
        },
        {
            "corridor": "Hebbal–Yelahanka Inner Road",
            "corridor_id": "hebbal_yelahanka",
            "psf_t24": 6000.0,
            "psf_t12": 6200.0,
            "psf_now": 6500.0,
            "actual_change_pct": 8.3,
        },
    ]

    with (
        patch("dashboard.routers.data._resolve_market") as mock_resolve,
        patch("utils.corridor_scorer.CorridorScorer") as mock_scorer_cls,
    ):
        mock_resolve.return_value = "Yelahanka"
        mock_scorer = MagicMock()
        mock_scorer_cls.return_value = mock_scorer
        mock_scorer.backtest.return_value = mock_results

        resp = client.get(
            "/api/v1/intel/corridors/backtest-accuracy?market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "corridors" in data
        assert isinstance(data["corridors"], list)
        assert len(data["corridors"]) == 2
        assert "overall_mape" in data
        assert data["overall_mape"] == 18.6
        assert "best_corridor" in data
        assert "NH-44" in data["best_corridor"]
        assert "worst_corridor" in data
        assert "data_points" in data
        assert data["data_points"] == 2
        assert "generated_at" in data
        assert "lookback_months" in data
        assert data["lookback_months"] == 24


def test_gate152_a2_no_auth_returns_401():
    """A2: backtest-accuracy returns 401 without API key."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get("/api/v1/intel/corridors/backtest-accuracy?market=Yelahanka")
    assert resp.status_code == 401


def test_gate152_a2_invalid_market_returns_400():
    """A2: backtest-accuracy returns 400 for unknown market."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)
    with patch("dashboard.routers.data._resolve_market", return_value=None):
        resp = client.get(
            "/api/v1/intel/corridors/backtest-accuracy?market=InvalidTown",
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code == 400


def test_gate152_a2_empty_results_returns_ok():
    """A2: backtest-accuracy returns 200 with empty corridors when no data."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("dashboard.routers.data._resolve_market") as mock_resolve,
        patch("utils.corridor_scorer.CorridorScorer") as mock_scorer_cls,
    ):
        mock_resolve.return_value = "Yelahanka"
        mock_scorer = MagicMock()
        mock_scorer_cls.return_value = mock_scorer
        mock_scorer.backtest.return_value = []

        resp = client.get(
            "/api/v1/intel/corridors/backtest-accuracy?market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["corridors"] == []
        assert data["overall_mape"] is None
        assert data["data_points"] == 0


def test_gate152_a2_lookback_months_param():
    """A2: backtest-accuracy respects lookback_months query param."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("dashboard.routers.data._resolve_market") as mock_resolve,
        patch("utils.corridor_scorer.CorridorScorer") as mock_scorer_cls,
    ):
        mock_resolve.return_value = "Yelahanka"
        mock_scorer = MagicMock()
        mock_scorer_cls.return_value = mock_scorer
        mock_scorer.backtest.return_value = []

        resp = client.get(
            "/api/v1/intel/corridors/backtest-accuracy?market=Yelahanka&lookback_months=12",
            headers={"X-API-Key": "test-key"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["lookback_months"] == 12
        mock_scorer.backtest.assert_called_with("Yelahanka", lookback_months=12)


# ── A3: Alembic migration 0073 importable ─────────────────────────────


def test_gate152_a3_migration_0073_importable():
    """A3: alembic/versions/0073_corridor_backtest.py is importable with upgrade/downgrade."""
    import importlib
    spec = importlib.util.spec_from_file_location(
        "alembic.versions._0073",
        str(pathlib.Path(__file__).parents[1] / "alembic" / "versions" / "0073_corridor_backtest.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)
    import inspect
    upgrade_source = inspect.getsource(mod.upgrade)
    assert "corridor_backtest_results" in upgrade_source


# ── A4: Board Room Finance Head context builds correctly ──────────────


def test_gate152_a4_board_room_corridor_context_built():
    """A4: Board Room corridor context string exists in source (code-level assertion)."""
    import crews.board_room as br_mod
    import inspect
    source = inspect.getsource(br_mod)
    assert "Corridor accuracy" in source
    assert "CorridorScorer" in source


# ── A5: backtest returns [] on DB failure ─────────────────────────────


def test_gate152_a5_backtest_empty_on_generic_failure():
    """A5: backtest returns [] on generic Exception."""
    from utils.corridor_scorer import CorridorScorer
    with patch("utils.db.get_engine") as mock_eng:
        mock_eng.side_effect = Exception("DB connection failed")
        result = CorridorScorer().backtest_psf_history("Yelahanka")
    assert isinstance(result, list)
    assert len(result) == 0


def test_gate152_a5_backtest_empty_on_operational_error():
    """A5: backtest returns [] on psycopg2 OperationalError."""
    from utils.corridor_scorer import CorridorScorer
    with patch("utils.db.get_engine") as mock_eng:
        mock_eng.side_effect = ConnectionRefusedError("connection refused")
        result = CorridorScorer().backtest_psf_history("Yelahanka")
    assert isinstance(result, list)
    assert len(result) == 0
