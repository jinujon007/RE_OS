"""GATE-159: Parcel Graph Visualisation — 5 gate assertions (A1-A5).

A1: parcel_graph.html exists + contains cytoscape/parcel-graph-canvas + GET /parcel-graph 200
A2: mock ParcelGraph.build → GET /api/v1/intel/parcel-graph returns 200 + nodes + hotspot_score
A3: run_parcel_graph_materialize importable from config.scheduler.maintenance_jobs + in __all__
A4: mock parcel_graph_edges rows → GET /api/v1/intel/parcel-graph/hotspot-alert → 200 + hotspot_villages + new_since_last_run
A5: A4 mock with 0 rows → hotspot_villages == [] + Discord NOT called
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_API_KEY_READ", "test-read-key")
os.environ.setdefault("DASHBOARD_API_KEY_ADMIN", "test-admin-key")

import pytest

pytestmark = pytest.mark.unit


# ── A1: Template exists + contains cytoscape + canvas id + route 200 ———


def test_gate159_a1_template_exists():
    """A1: parcel_graph.html exists, contains cytoscape + parcel-graph-canvas."""
    template = Path(__file__).parents[1] / "dashboard" / "templates" / "parcel_graph.html"
    assert template.exists(), "parcel_graph.html template not found"

    content = template.read_text(encoding="utf-8")
    assert "cytoscape" in content, "Template must reference cytoscape"
    assert "parcel-graph-canvas" in content, "Template must contain parcel-graph-canvas id"


def test_gate159_a1_parcel_graph_route_200():
    """A1: GET /parcel-graph returns 200."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    with patch("dashboard.app_fastapi._write_audit_log"):
        resp = client.get("/api/v1/parcel-graph", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200


# ── A2: Parcel graph API endpoint ———————————————————————————————


def test_gate159_a2_parcel_graph_endpoint():
    """A2: mock ParcelGraph.build → GET /api/v1/intel/parcel-graph returns 200 + nodes + hotspot_score."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    mock_result = {
        "market": "Yelahanka",
        "village": "Doddajala",
        "nodes": ["10", "15", "20"],
        "edges": [
            {"survey_a": "10", "survey_b": "15", "shared_buyer": True, "transaction_count": 2, "edge_weight": 0.8},
            {"survey_a": "15", "survey_b": "20", "shared_buyer": False, "transaction_count": 1, "edge_weight": 0.1},
        ],
        "hotspot_score": 0.67,
    }

    with patch("utils.parcel_graph.ParcelGraph") as mock_pg_cls:
        mock_instance = MagicMock()
        mock_pg_cls.return_value = mock_instance
        mock_instance.build.return_value = mock_result

        resp = client.get(
            "/api/v1/intel/parcel-graph?market=Yelahanka&village=Doddajala",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert len(data["nodes"]) == 3
    assert "hotspot_score" in data
    assert data["hotspot_score"] == 0.67
    assert data["market"] == "Yelahanka"
    assert data["village"] == "Doddajala"
    assert len(data["edges"]) == 2


# ── A3: Materialization job importable ———————————————————————————


def test_gate159_a3_materialize_importable():
    """A3: run_parcel_graph_materialize importable from config.scheduler.maintenance_jobs + in __all__."""
    from config.scheduler.maintenance_jobs import (
        run_parcel_graph_materialize,
        __all__,
    )

    assert callable(run_parcel_graph_materialize)
    assert "run_parcel_graph_materialize" in __all__


# ── A4: Hotspot alert endpoint ————————————————————————————————


def test_gate159_a4_hotspot_alert_endpoint():
    """A4: mock parcel_graph_edges rows → GET /api/v1/intel/parcel-graph/hotspot-alert → 200 + hotspot_villages + new_since_last_run."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    with (
        patch("dashboard.routers.data._get_sa_engine") as mock_eng,
        patch("dashboard.routers.data._parcel_hotspot_last_run", {"parcel_hotspot_check": set()}),
    ):
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            ("Yelahanka", "Doddajala", 0.75, 5),
            ("Yelahanka", "Bagalur", 0.62, 3),
        ]

        resp = client.get(
            "/api/v1/intel/parcel-graph/hotspot-alert",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "hotspot_villages" in data
    assert len(data["hotspot_villages"]) == 2
    assert "new_since_last_run" in data
    assert data["new_since_last_run"] == 2
    first = data["hotspot_villages"][0]
    assert "market" in first
    assert "village" in first
    assert "avg_edge_weight" in first
    assert "edge_count" in first


# ── A5: Hotspot alert with 0 rows —————————————————————————————


def test_gate159_a5_hotspot_alert_empty():
    """A5: mock 0 rows → hotspot_villages == [] + Discord NOT called."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    with (
        patch("dashboard.routers.data._get_sa_engine") as mock_eng,
        patch("utils.discord_notifier.send_ops_alert") as mock_discord,
    ):
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        resp = client.get(
            "/api/v1/intel/parcel-graph/hotspot-alert",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["hotspot_villages"] == []
    assert data["new_since_last_run"] == 0
    mock_discord.assert_not_called()


# ── A2 edge: no auth returns error —————————————————————————


def test_gate159_a2_no_auth_returns_error():
    """A2 edge: missing API key returns 401."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    with patch("utils.parcel_graph.ParcelGraph"):
        resp = client.get(
            "/api/v1/intel/parcel-graph?market=Yelahanka&village=Doddajala",
        )
    assert resp.status_code == 401


# ── Routes registered ———————————————————————————————————————


def test_gate159_a5_routes_registered():
    """A5 supplement: All new routes are registered."""
    from dashboard.routers.data import router

    route_paths = [r.path for r in router.routes]
    assert "/parcel-graph" in route_paths
    assert "/intel/parcel-graph/hotspot-alert" in route_paths
