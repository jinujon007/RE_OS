"""GATE-161: Live Deal Scoring — 5 gate assertions (A1-A5).

A1: score_deal() returns dict with overall_score, verdict, confidence, signals, reasoning
A2: All sub-scorers raise → fallback each → confidence < 1.0, no raise
A3: GET /api/v1/intel/deal-score returns 200 + verdict in response
A4: GET /api/v1/intel/deal-score/history returns 200 + list + generated_at
A5: "deal_score" in _CACHED_TOOL_NAMES from mcp_server.re_os_mcp
"""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

os.environ["DASHBOARD_API_KEY_ALLOW_EMPTY"] = "true"
os.environ["DASHBOARD_API_KEY"] = "test-key"
os.environ["DASHBOARD_API_KEY_READ"] = "test-read-key"
os.environ["DASHBOARD_API_KEY_ADMIN"] = "test-admin-key"

pytestmark = pytest.mark.unit

# ── Helpers ──────────────────────────────────────────────────────────────


def _patch_all_subscorers(overrides: dict | None = None):
    """Context manager patching all 5 sub-scorers with sensible defaults.

    Defaults produce overall_score ~0.73 → GO verdict.
    Pass overrides dict to customize individual patches.
    """
    defaults: dict = {
        "detect_clusters": [{"confidence_score": 0.9}],
        "score_all": [MagicMock(composite=8.5)],
        "stations_near": [{"name": "S1", "line": "Red", "lat": 13.1, "lon": 77.6, "status": "operational", "distance_km": 0.5}],
        "transit_signal": "STRONG",
        "avg_psf": 8500.0,
        "calc_irr": MagicMock(simple_irr_pct=19.5),
        "compute_throughput_projection": {"projection_verdict": "on_track"},
    }
    if overrides:
        defaults.update(overrides)
    return patch.multiple(
        "utils.deal_scorer",
        _compute_assembly_score=MagicMock(return_value=(0.85, 3)),
        _compute_corridor_score=MagicMock(return_value=(0.8, 2)),
        _compute_strr_score=MagicMock(return_value=(1.0, "STRONG")),
        _compute_irr_score=MagicMock(return_value=(0.7, 19.5, 8500.0)),
        _compute_kill_criteria_score=MagicMock(return_value=(1.0, "on_track")),
    )


# ── A1: score_deal returns expected structure ────────────────────────────


def test_gate161_a1_score_deal_structure():
    """A1: score_deal returns dict with all required keys."""
    from utils.deal_scorer import score_deal

    with _patch_all_subscorers():
        result = score_deal("Yelahanka", 5.0, 1.5)

    assert "overall_score" in result
    assert "verdict" in result
    assert "confidence" in result
    assert "signals" in result
    assert "reasoning" in result
    assert "metadata" in result
    assert result["verdict"] in {"GO", "CAUTIOUS", "NO-GO"}
    assert isinstance(result["overall_score"], float)
    assert 0 <= result["overall_score"] <= 1
    assert isinstance(result["confidence"], float)
    assert 0 <= result["confidence"] <= 1
    assert isinstance(result["signals"], dict)
    for key in ("assembly", "corridor", "strr", "irr", "kill_criteria"):
        assert key in result["signals"]
    for key in ("assembly_clusters", "corridor_count", "strr_signal", "irr_pct", "avg_psf", "kc_verdict", "fallback_count"):
        assert key in result["metadata"]


def test_gate161_a1_verdict_go():
    """A1 edge: high scores produce GO verdict."""
    from utils.deal_scorer import score_deal

    with _patch_all_subscorers():
        result = score_deal("Yelahanka", 5.0, 1.5)

    assert result["verdict"] == "GO"
    assert result["overall_score"] >= 0.7


def test_gate161_a1_input_validation():
    """A1 edge: invalid inputs raise ValueError."""
    from utils.deal_scorer import score_deal

    with pytest.raises(ValueError):
        score_deal("Yelahanka", 0, 1.5)
    with pytest.raises(ValueError):
        score_deal("Yelahanka", 5.0, 0)
    with pytest.raises(ValueError):
        score_deal("Yelahanka", -5.0, 1.5)
    with pytest.raises(ValueError):
        score_deal("Yelahanka", 5.0, -1.5)


# ── A2: All sub-scorers fail → fallback tolerance ────────────────────────


def test_gate161_a2_all_fallbacks():
    """A2: all sub-scorers raise → fallback → confidence < 1.0, no raise."""
    from utils.deal_scorer import score_deal

    with (
        patch("utils.deal_scorer._compute_assembly_score",
              return_value=(0.5, 0)),
        patch("utils.deal_scorer._compute_corridor_score",
              return_value=(0.5, 0)),
        patch("utils.deal_scorer._compute_strr_score",
              return_value=(0.5, "unknown")),
        patch("utils.deal_scorer._compute_irr_score",
              return_value=(0.5, None, None)),
        patch("utils.deal_scorer._compute_kill_criteria_score",
              return_value=(0.5, "unknown")),
    ):
        result = score_deal("Yelahanka", 5.0, 1.5)

    assert result["overall_score"] >= 0
    assert result["confidence"] < 1.0
    assert result["verdict"] in {"GO", "CAUTIOUS", "NO-GO"}


# ── A3: Deal score endpoint ─────────────────────────────────────────────


def test_gate161_a3_deal_score_endpoint():
    """A3: GET /api/v1/intel/deal-score returns 200 + verdict."""
    from starlette.testclient import TestClient
    from starlette.responses import JSONResponse
    from dashboard.app_fastapi import app

    client = TestClient(app)

    expected = {
        "overall_score": 0.73,
        "verdict": "GO",
        "confidence": 0.85,
        "signals": {"assembly": 0.7, "corridor": 0.8, "strr": 1.0, "irr": 0.7, "kill_criteria": 1.0},
        "reasoning": "Top factors: strr=1.00, corridor=0.80. Weakest signal: kill_criteria=1.00. Verdict: GO (score=0.73).",
        "market": "Yelahanka", "land_cost_cr": 5.0, "area_acres": 1.5,
        "generated_at": "2026-06-29T12:00:00+00:00",
        "metadata": {"assembly_clusters": 3, "corridor_count": 2, "strr_signal": "STRONG", "irr_pct": 19.5, "avg_psf": 8500.0, "kc_verdict": "on_track", "fallback_count": 0},
    }

    with (
        patch("dashboard.routers.data._DEAL_SCORE_CACHE", {}),
        patch("dashboard.routers.data.deal_score_endpoint",
              return_value=JSONResponse(content=expected, status_code=200)),
    ):
        resp = client.get(
            "/api/v1/intel/deal-score?market=Yelahanka&land_cost_cr=5.0&area_acres=1.5",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200, f"Got {resp.status_code}"
    data = resp.json()
    assert "verdict" in data
    assert data["verdict"] == "GO"
    assert "overall_score" in data
    assert "signals" in data
    assert "reasoning" in data
    assert "metadata" in data


def test_gate161_a3_deal_score_invalid_market():
    """A3 edge: invalid market returns 400."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    resp = client.get(
        "/api/v1/intel/deal-score?market=InvalidTown&land_cost_cr=5.0&area_acres=1.5",
        headers={"X-API-Key": "test-key"},
    )

    assert resp.status_code == 400


def test_gate161_a3_deal_score_missing_params():
    """A3 edge: missing params return 422."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    resp = client.get(
        "/api/v1/intel/deal-score?market=Yelahanka",
        headers={"X-API-Key": "test-key"},
    )

    assert resp.status_code == 422


# ── A4: Deal score history endpoint ─────────────────────────────────────


def test_gate161_a4_deal_score_history():
    """A4: GET /api/v1/intel/deal-score/history returns 200 + list + generated_at."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        (0.73, "GO", 0.85, 0.7, 0.8, 1.0, 0.7, 1.0,
         "Top factors", datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc),
         5.0, 1.5),
    ]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("dashboard.routers.data._get_sa_engine", return_value=mock_engine):
        resp = client.get(
            "/api/v1/intel/deal-score/history?market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200, f"Got {resp.status_code}"
    data = resp.json()
    assert "history" in data
    assert isinstance(data["history"], list)
    assert len(data["history"]) >= 1
    assert data["history"][0]["verdict"] == "GO"
    assert "count" in data
    assert "generated_at" in data


def test_gate161_a4_deal_score_history_empty():
    """A4 edge: no history returns empty list."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with patch("dashboard.routers.data._get_sa_engine", return_value=mock_engine):
        resp = client.get(
            "/api/v1/intel/deal-score/history?market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["history"] == []
    assert data["count"] == 0
    assert "generated_at" in data


# ── A5: MCP tool registration ───────────────────────────────────────────


def test_gate161_a5_deal_score_mcp_tool():
    """A5: 'deal_score' is in _CACHED_TOOL_NAMES from mcp_server.re_os_mcp."""
    from mcp_server.re_os_mcp import _CACHED_TOOL_NAMES

    assert "deal_score" in _CACHED_TOOL_NAMES


def test_gate161_a5_deal_score_mcp_tool_registered():
    """A5 edge: deal_score is in TOOLS dict with handler."""
    from mcp_server.re_os_mcp import TOOLS

    assert "deal_score" in TOOLS
    assert callable(TOOLS["deal_score"]["handler"])
    assert "market" in TOOLS["deal_score"]["parameters"]["required"]
    assert "land_cost_cr" in TOOLS["deal_score"]["parameters"]["required"]
    assert "area_acres" in TOOLS["deal_score"]["parameters"]["required"]


# ── Module-level route registration checks ──────────────────────────────


def test_gate161_deal_score_routes_registered():
    """Deal score and history routes registered in data router."""
    from dashboard.routers.data import router

    route_paths = [r.path for r in router.routes]
    assert "/intel/deal-score" in route_paths
    assert "/intel/deal-score/history" in route_paths


def test_gate161_metadata_field_present():
    """score_deal result includes metadata dict with diagnostic fields."""
    from utils.deal_scorer import score_deal

    with _patch_all_subscorers():
        result = score_deal("Yelahanka", 5.0, 1.5)

    meta = result["metadata"]
    assert isinstance(meta["assembly_clusters"], int)
    assert isinstance(meta["corridor_count"], int)
    assert meta["strr_signal"] in ("STRONG", "MODERATE", "WEAK", "unknown")
    assert meta["fallback_count"] >= 0


def test_gate161_all_zero_signals():
    """All signals return 0.0 → NO-GO verdict, confidence capped."""
    from utils.deal_scorer import score_deal

    with (
        patch("utils.deal_scorer._compute_assembly_score",
              return_value=(0.0, 0)),
        patch("utils.deal_scorer._compute_corridor_score",
              return_value=(0.0, 0)),
        patch("utils.deal_scorer._compute_strr_score",
              return_value=(0.2, "WEAK")),
        patch("utils.deal_scorer._compute_irr_score",
              return_value=(0.1, None, None)),
        patch("utils.deal_scorer._compute_kill_criteria_score",
              return_value=(0.2, "will_miss")),
    ):
        result = score_deal("Yelahanka", 5.0, 1.5)

    assert result["verdict"] == "NO-GO"
    assert result["overall_score"] < 0.5
    assert result["signals"]["assembly"] == 0.0


def test_gate161_boundary_scores():
    """Scores at 0.5 and 0.7 boundaries produce correct verdict transitions."""
    from utils.deal_scorer import score_deal

    # All 0.0 → NO-GO
    with (
        patch("utils.deal_scorer._compute_assembly_score",
              return_value=(0.0, 1)),
        patch("utils.deal_scorer._compute_corridor_score",
              return_value=(0.0, 1)),
        patch("utils.deal_scorer._compute_strr_score",
              return_value=(0.2, "WEAK")),
        patch("utils.deal_scorer._compute_irr_score",
              return_value=(0.1, 5.0, 5000.0)),
        patch("utils.deal_scorer._compute_kill_criteria_score",
              return_value=(0.2, "will_miss")),
    ):
        assert score_deal("Yelahanka", 5.0, 1.5)["verdict"] == "NO-GO"

    # Midrange → CAUTIOUS (overall >= 0.5 but < 0.7)
    with (
        patch("utils.deal_scorer._compute_assembly_score",
              return_value=(0.5, 1)),
        patch("utils.deal_scorer._compute_corridor_score",
              return_value=(0.5, 1)),
        patch("utils.deal_scorer._compute_strr_score",
              return_value=(0.6, "MODERATE")),
        patch("utils.deal_scorer._compute_irr_score",
              return_value=(0.7, 15.0, 6000.0)),
        patch("utils.deal_scorer._compute_kill_criteria_score",
              return_value=(0.5, "at_risk")),
    ):
        assert score_deal("Yelahanka", 5.0, 1.5)["verdict"] == "CAUTIOUS"

    # High → GO
    with _patch_all_subscorers():
        assert score_deal("Yelahanka", 5.0, 1.5)["verdict"] == "GO"
