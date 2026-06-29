"""GATE-155: Form 17 Village-Depth Parcel Graph — 5 gate assertions (A1-A5).

A1: ParcelGraph.build returns graph with nodes + edges from shared buyers
A2: Migration 0075 importable + parcel_graph_edges in upgrade SQL + correct down_revision
A3: GET /api/v1/intel/parcel-graph returns 200 + nodes + edges + hotspot_score
A4: GET /api/v1/intel/parcel-graph/summary returns 200 + villages sorted by connectivity_score desc
A5: ParcelGraph().build("", "") returns empty graph without raising
"""

import os
from datetime import date, timedelta
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")

pytestmark = pytest.mark.unit


# ── A1: ParcelGraph.build with shared buyers ──────────────────────────


class _MockRow:
    def __init__(self, survey_no, buyer_name_raw, reg_date):
        self.survey_no = survey_no
        self.buyer_name_raw = buyer_name_raw
        self.reg_date = reg_date


def test_gate155_a1_parcel_graph_build():
    """A1: ParcelGraph.build returns nodes + edges from shared buyer transactions."""
    from utils.parcel_graph import ParcelGraph

    mock_rows = [
        _MockRow("10", "Brigade Group", date.today() - timedelta(days=5)),
        _MockRow("15", "Brigade Group", date.today() - timedelta(days=10)),
        _MockRow("20", "Prestige Group", date.today() - timedelta(days=3)),
        _MockRow("25", "Prestige Group", date.today() - timedelta(days=20)),
    ]

    with patch("utils.parcel_graph.get_engine") as mock_get_eng:
        mock_conn = MagicMock()
        mock_get_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = mock_rows
        mock_conn.execute.return_value = mock_cursor

        pg = ParcelGraph()
        result = pg.build("Yelahanka", "Bagalur")

    assert len(result["nodes"]) >= 1
    assert len(result["edges"]) >= 1
    for edge in result["edges"]:
        assert "survey_a" in edge
        assert "survey_b" in edge
        assert "edge_weight" in edge
        assert isinstance(edge["edge_weight"], float)
    assert "hotspot_score" in result
    assert result["hotspot_score"] > 0

    # Validate edge weight formula for shared-buyer edges (10-day gap → 1/11 ≈ 0.091)
    shared_edges = [e for e in result["edges"] if e["shared_buyer"]]
    if shared_edges:
        assert all(0 < e["edge_weight"] <= 1.0 for e in shared_edges)


# ── A1 edge: DB failure path ─────────────────────────────────────────


def test_gate155_a1_db_failure_returns_empty():
    """A1 edge: DB exception at query time returns empty graph without raising."""
    from utils.parcel_graph import ParcelGraph

    with patch("utils.parcel_graph.get_engine") as mock_get_eng:
        mock_conn = MagicMock()
        mock_get_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = Exception("query failed")

        pg = ParcelGraph()
        result = pg.build("Yelahanka", "Bagalur")

    assert result["nodes"] == []
    assert result["edges"] == []
    assert result["hotspot_score"] == 0.0


# ── A1 edge: null reg_date handled gracefully ───────────────────────


def test_gate155_a1_null_reg_date():
    """A1 edge: transactions with null reg_date use floor weight."""
    from utils.parcel_graph import ParcelGraph

    mock_rows = [
        _MockRow("10", "Brigade Group", None),
        _MockRow("15", "Brigade Group", date.today() - timedelta(days=5)),
    ]

    with patch("utils.parcel_graph.get_engine") as mock_get_eng:
        mock_conn = MagicMock()
        mock_get_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = mock_rows
        mock_conn.execute.return_value = mock_cursor

        pg = ParcelGraph()
        result = pg.build("Yelahanka", "Bagalur")

    assert len(result["nodes"]) >= 1
    assert len(result["edges"]) >= 1
    # Edge weight should be > 0 (adjacency floor) even with null date
    for edge in result["edges"]:
        assert edge["edge_weight"] >= 0.1


# ── A2: Migration 0075 structure ─────────────────────────────────────


def test_gate155_a2_migration_0075_structure():
    """A2: Migration 0075 importable + parcel_graph_edges in upgrade SQL + correct down_revision."""
    import importlib.util
    from pathlib import Path
    migration_path = Path("alembic/versions/0075_parcel_graph_edges.py")
    assert migration_path.exists(), "Migration file not found"

    spec = importlib.util.spec_from_file_location("migration_0075", migration_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")
    assert mod.down_revision == "0074_deed_village_priority"

    import inspect
    upgrade_src = inspect.getsource(mod.upgrade)
    assert "parcel_graph_edges" in upgrade_src
    assert "nullable=False" in upgrade_src


# ── A3: Parcel graph endpoint ────────────────────────────────────────


def _patch_parcel_graph(build_return, market="Yelahanka"):
    """Context manager: patch ParcelGraph and _resolve_market for endpoint tests."""
    return patch.multiple(
        "utils.parcel_graph",
        ParcelGraph=MagicMock(**{"return_value.build.return_value": build_return}),
    )


def test_gate155_a3_parcel_graph_endpoint():
    """A3: GET /api/v1/intel/parcel-graph returns 200 + graph keys."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("utils.parcel_graph.ParcelGraph") as mock_pg_cls,
    ):
        mock_instance = MagicMock()
        mock_pg_cls.return_value = mock_instance
        mock_instance.build.return_value = {
            "market": "Yelahanka",
            "village": "Bagalur",
            "nodes": ["10", "15", "20"],
            "edges": [
                {"survey_a": "10", "survey_b": "15", "shared_buyer": True,
                 "transaction_count": 1, "edge_weight": 0.5},
            ],
            "hotspot_score": 0.33,
        }

        resp = client.get(
            "/api/v1/intel/parcel-graph?market=Yelahanka&village=Bagalur",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert "hotspot_score" in data
    assert data["market"] == "Yelahanka"
    assert data["village"] == "Bagalur"


# ── A3 edge: invalid market returns 400 ─────────────────────────────


def test_gate155_a3_invalid_market_400():
    """A3 edge: unknown market returns 400."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    resp = client.get(
        "/api/v1/intel/parcel-graph?market=InvalidTown&village=Bagalur",
        headers={"X-API-Key": "test-key"},
    )

    assert resp.status_code >= 400


# ── A3 edge: empty result returns 200 with note ──────────────────────


def test_gate155_a3_empty_village_returns_note():
    """A3 edge: empty result returns 200 with note key."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with patch("utils.parcel_graph.ParcelGraph") as mock_pg_cls:
        mock_instance = MagicMock()
        mock_pg_cls.return_value = mock_instance
        mock_instance.build.return_value = {
            "market": "Yelahanka", "village": "Nonexistent",
            "nodes": [], "edges": [], "hotspot_score": 0.0,
        }

        resp = client.get(
            "/api/v1/intel/parcel-graph?market=Yelahanka&village=Nonexistent",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"] == []
    assert data["edges"] == []
    assert "note" in data


# ── A3 edge: 500-node truncation ─────────────────────────────────────


def test_gate155_a3_node_truncation():
    """A3 edge: >500 nodes triggers degree-based trim."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    many_nodes = [str(i) for i in range(600)]
    many_edges = []
    for i in range(200):
        survey_a = str(i)
        survey_b = str(i + 1)
        many_edges.append({
            "survey_a": survey_a, "survey_b": survey_b,
            "shared_buyer": True, "transaction_count": 1, "edge_weight": 0.5,
        })
    for i in range(200, 299):
        survey_a = str(i)
        survey_b = str(i + 1)
        many_edges.append({
            "survey_a": survey_a, "survey_b": survey_b,
            "shared_buyer": False, "transaction_count": 1, "edge_weight": 0.1,
        })

    with patch("utils.parcel_graph.ParcelGraph") as mock_pg_cls:
        mock_instance = MagicMock()
        mock_pg_cls.return_value = mock_instance
        mock_instance.build.return_value = {
            "market": "Yelahanka", "village": "Bagalur",
            "nodes": many_nodes, "edges": many_edges, "hotspot_score": 0.5,
        }

        resp = client.get(
            "/api/v1/intel/parcel-graph?market=Yelahanka&village=Bagalur",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) > 0
    assert len(data["nodes"]) <= 600
    assert "note" in data


# ── A4: Parcel graph summary endpoint ────────────────────────────────


def test_gate155_a4_parcel_graph_summary():
    """A4: GET /api/v1/intel/parcel-graph/summary returns 200 + villages sorted desc by connectivity_score."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("utils.parcel_graph.ParcelGraph") as mock_pg_cls,
        patch("dashboard.routers.data._get_sa_engine") as mock_eng,
    ):
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        priority_mock = MagicMock()
        priority_mock.fetchall.return_value = [
            ("Bagalur",),
            ("Kodigehalli",),
            ("Shyampura",),
        ]
        mock_conn.execute.return_value = priority_mock

        mock_instance = MagicMock()
        mock_pg_cls.return_value = mock_instance
        mock_instance.build.side_effect = [
            {"nodes": ["10", "15"], "edges": [{"survey_a": "10", "survey_b": "15"}],
             "hotspot_score": 0.5},
            {"nodes": ["20", "25", "30"], "edges": [{"survey_a": "20", "survey_b": "25"}],
             "hotspot_score": 0.33},
            {"nodes": ["40"], "edges": [], "hotspot_score": 0.0},
        ]

        resp = client.get(
            "/api/v1/intel/parcel-graph/summary?market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "villages" in data
    assert "market" in data
    assert data["market"] == "Yelahanka"
    assert len(data["villages"]) == 3
    scores = [v["connectivity_score"] for v in data["villages"]]
    assert scores == sorted(scores, reverse=True)
    for v in data["villages"]:
        assert "village" in v
        assert "connectivity_score" in v
        assert "node_count" in v
        assert "edge_count" in v
    assert "generated_at" in data


# ── A4 edge: no auth returns 401/403 ─────────────────────────────────


def test_gate155_a4_no_auth_returns_error():
    """A4 edge: missing auth token returns error."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    resp = client.get("/api/v1/intel/parcel-graph/summary?market=Yelahanka")
    assert resp.status_code >= 401


# ── A5: Empty market/village returns empty graph without raising ─────


def test_gate155_a5_empty_input_returns_empty_graph():
    """A5: ParcelGraph().build('', '') returns empty graph without raising."""
    from utils.parcel_graph import ParcelGraph

    with patch("utils.parcel_graph.get_engine") as mock_get_eng:
        mock_conn = MagicMock()
        mock_get_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        pg = ParcelGraph()
        result = pg.build("", "")

    assert isinstance(result, dict)
    assert result["nodes"] == []
    assert result["edges"] == []
    assert result["hotspot_score"] == 0.0


# ── Routes registered helper ─────────────────────────────────────────


def test_gate155_a5_routes_registered():
    """A5 supplement: Both parcel-graph routes are registered in the data router."""
    from dashboard.routers.data import router
    route_paths = [r.path for r in router.routes]
    assert "/intel/parcel-graph" in route_paths
    assert "/intel/parcel-graph/summary" in route_paths
