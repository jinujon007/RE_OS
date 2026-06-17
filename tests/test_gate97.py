"""GATE-97: FastAPI Router Split — comprehensive validation.

Tests cover:
- Module importability for all 6 new modules
- Line count constraint (<= 500)
- Route registration completeness (>= 40 routes, all router groups present)
- HTTP-level endpoint reachability with mocked DB
- OpenAPI schema completeness
"""

import os
from unittest.mock import patch, MagicMock

import pytest

pytestmark = pytest.mark.unit

from starlette.testclient import TestClient

# ── Module Import Tests ──────────────────────────────────────────────────


def test_state_module_importable():
    from dashboard.state import VALID_MARKETS
    assert "Yelahanka" in VALID_MARKETS
    assert "Devanahalli" in VALID_MARKETS
    assert "Hebbal" in VALID_MARKETS


def test_health_router_importable():
    from dashboard.routers.health import router
    paths = [r.path for r in router.routes]
    assert "/api/health" in paths


def test_board_room_router_importable():
    from dashboard.routers.board_room import router
    paths = [r.path for r in router.routes]
    assert any("board/session" in p for p in paths)


def test_pipeline_router_importable():
    from dashboard.routers.pipeline import router
    paths = [r.path for r in router.routes]
    assert any("/api/run/" in p for p in paths)


def test_data_router_importable():
    from dashboard.routers.data import router
    paths = [r.path for r in router.routes]
    assert "/metrics" in paths


def test_ops_router_importable():
    from dashboard.routers.ops import router
    paths = [r.path for r in router.routes]
    assert "/api/tasks" in paths


# ── Line Count Constraint ────────────────────────────────────────────────


def test_app_fastapi_line_count_under_500():
    with open("dashboard/app_fastapi.py") as f:
        lines = f.readlines()
    assert len(lines) <= 500, f"app_fastapi.py has {len(lines)} lines (max 500)"


# ── App Import & Route Registration ──────────────────────────────────────


def test_app_importable_and_has_min_routes():
    from dashboard.app_fastapi import app
    routes = [r.path for r in app.routes]
    assert len(routes) >= 40, f"Only {len(routes)} routes registered"
    assert "/api/health" in routes
    assert any("/api/run/" in p for p in routes)
    assert any("/api/board" in p for p in routes)


def test_state_valid_markets():
    from dashboard.state import VALID_MARKETS
    assert "Yelahanka" in VALID_MARKETS
    assert "Devanahalli" in VALID_MARKETS
    assert "Hebbal" in VALID_MARKETS
    assert "all" in VALID_MARKETS


# ── HTTP-level endpoint reachability (mocked DB) ─────────────────────────


def _make_db_mock(return_values=None):
    """Create a SQLAlchemy engine mock that returns canned data."""
    engine = MagicMock()
    conn = MagicMock()
    conn.__enter__.return_value = conn
    if return_values:
        # Support both iterable and single-value return
        if isinstance(return_values, list) and not callable(return_values[0]):
            it = iter(return_values)
            conn.execute.return_value.fetchone = lambda: next(it)
            conn.execute.return_value.fetchall = lambda: list(it) if False else []
            conn.execute.return_value.scalar = lambda: return_values[0] if return_values else 0
        else:
            conn.execute.return_value = return_values
    engine.connect.return_value.__enter__.return_value = conn
    return engine


def test_health_endpoint_returns_200():
    """GET /api/health returns 200 with expected keys."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert "postgres" in data
    assert "redis" in data


def test_health_live_endpoint_returns_200():
    """GET /api/health/live returns 200."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get("/api/health/live")
    assert resp.status_code == 200


def test_root_endpoint_returns_html():
    """GET / returns HTML (dashboard index)."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_metrics_endpoint_returns_prometheus():
    """GET /metrics returns Prometheus text format."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers.get("content-type", "")


def test_openapi_schema_contains_route_groups():
    """OpenAPI schema includes all router groups."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    paths = schema.get("paths", {})
    # Verify key route groups exist
    assert "/api/health" in paths
    assert "/api/health/live" in paths
    assert "/api/db/state" in paths
    assert "/api/tasks" in paths
    assert "/api/registry" in paths
    assert "/api/board/session" in paths or "/api/board" in str(paths)
    assert "/" in paths  # root index route


def test_security_headers_present():
    """Security headers are set on every response."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Request-ID", "") != ""


def test_mocked_db_endpoint_returns_expected_shape():
    """DB-backed endpoint returns correct shape when DB is mocked."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_conn.execute.return_value.scalar.return_value = 0
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.routers.data._get_sa_engine", return_value=mock_engine):
        resp = client.get("/api/db/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "rera_projects" in data
    assert "listings" in data
    assert "markets" in data


def test_security_headers_present():
    """Security headers are set on every response."""
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Request-ID", "") != ""
