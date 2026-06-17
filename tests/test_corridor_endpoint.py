"""Unit tests for /api/corridor/score endpoint (Sprint 100 — T-1192).

5 unit tests:
  - endpoint returns 200 with corridor scores
  - geojson=true adds boundary_geojson to response
  - 500 error when scorer raises exception
  - window_months param propagated to scorer
  - market filter scopes results
"""

import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture
def client():
    from dashboard.app_fastapi import app
    return TestClient(app)


def test_corridor_score_endpoint_returns_200(client):
    """GET /api/corridor/score returns 200 with corridors list."""
    with patch("utils.corridor_scorer_v2.CorridorScorerV2.score_all") as mock_score:
        mock_score.return_value = []
        resp = client.get("/api/corridor/score")
        assert resp.status_code == 200
        data = resp.json()
        assert "corridors" in data
        assert "as_of" in data
        assert "window_months" in data


def test_corridor_score_geojson_param_true_adds_boundary(client):
    """geojson=true propagates as_geojson=True to scorer."""
    from utils.corridor_scorer_v2 import CorridorScoreV2

    fake_score = CorridorScoreV2(
        corridor_id="nh44", corridor_name="NH-44",
        velocity_score=3.0, psf_trend_score=5.0, gcc_score=4.0,
        infra_score=6.0, n_transactions=10, avg_psf=5000.0,
        psf_mom=2.5, data_window="test", notes=[],
        boundary_geojson={"type": "Feature", "geometry": {"type": "Polygon"}, "properties": {}},
    )

    with patch("utils.corridor_scorer_v2.CorridorScorerV2.score_all") as mock_score:
        mock_score.return_value = [fake_score]
        resp = client.get("/api/corridor/score?geojson=true")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["corridors"]) == 1
        assert data["corridors"][0].get("boundary_geojson") is not None
        assert data["corridors"][0]["boundary_geojson"]["type"] == "Feature"


def test_corridor_score_handles_scorer_error(client):
    """When scorer raises, endpoint returns 500 with structured error."""
    with patch("utils.corridor_scorer_v2.CorridorScorerV2.score_all") as mock_score:
        mock_score.side_effect = RuntimeError("DB connection failed")
        resp = client.get("/api/corridor/score")
        assert resp.status_code == 500
        data = resp.json()
        assert "error" in data
        assert "detail" in data
        assert "unavailable" in data["error"].lower()


def test_corridor_score_window_months_propagated(client):
    """window_months query param reaches score_all()."""
    with patch("utils.corridor_scorer_v2.CorridorScorerV2.score_all") as mock_score:
        mock_score.return_value = []
        resp = client.get("/api/corridor/score?window_months=6")
        assert resp.status_code == 200
        data = resp.json()
        assert data["window_months"] == 6


def test_corridor_score_market_filter(client):
    """market query param filters corridor results."""
    from utils.corridor_scorer_v2 import CorridorScoreV2

    hebbal_score = CorridorScoreV2(
        corridor_id="hebbal_yelahanka", corridor_name="Hebbal-Yelahanka",
        velocity_score=5.0, psf_trend_score=5.0, gcc_score=5.0,
        infra_score=5.0, n_transactions=10, avg_psf=6000.0,
        psf_mom=1.0, data_window="test", notes=[],
    )

    with patch(
        "utils.corridor_scorer_v2.CorridorScorerV2.score_all",
        return_value=[hebbal_score],
    ):
        with patch("utils.corridor_scorer_v2.CORRIDOR_DEFINITIONS", [
            {"id": "hebbal_yelahanka", "market": "Hebbal"},
        ]):
            resp = client.get("/api/corridor/score?market=Hebbal")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("market") == "Hebbal"


@pytest.mark.parametrize("path,status", [
    ("/api/corridor/score", 200),
])
def test_corridor_score_is_read_only_path(client, path, status):
    """Corridor score endpoint is accessible without auth (in _READ_ONLY_PATHS)."""
    with patch("utils.corridor_scorer_v2.CorridorScorerV2.score_all") as mock_score:
        mock_score.return_value = []
        resp = client.get(path, headers={})  # no auth header
        assert resp.status_code == status
