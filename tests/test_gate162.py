"""GATE-162: Audit Residuals + System Hardening — 5 gate assertions (A1-A5).

A1: stations_near tries DB centroid first, falls back to hardcoded dict
A2: _load_stations enforces 1-hour TTL cap on station reload
A3: GET /api/v1/intel/parcel-graph/stats returns 200 + total_edges + materialization_coverage_pct
A4: Migration chain 0074->0075->0076->0077 is valid, all 4 files have correct down_revision
A5: New routes registered in FastAPI route list
"""

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ["DASHBOARD_API_KEY_ALLOW_EMPTY"] = "true"
os.environ["DASHBOARD_API_KEY"] = "test-key"
os.environ["DASHBOARD_API_KEY_READ"] = "test-read-key"
os.environ["DASHBOARD_API_KEY_ADMIN"] = "test-admin-key"

pytestmark = pytest.mark.unit


# ── Helpers ────────────────────────────────────────────────


def _make_engine(conn: MagicMock) -> MagicMock:
    eng = MagicMock()
    eng.connect.return_value.__enter__.return_value = conn
    return eng


def _one_station() -> list[dict]:
    return [{"name": "S1", "line": "Red", "lat": 13.1, "lon": 77.6, "status": "operational"}]


# ── A1: DB centroid ——————————————————————————————————————


def test_gate162_a1_db_centroid_used_when_available():
    """A1: DB centroid used when micro_markets row exists."""
    from utils.strr_overlay import STRROverlay

    mock_conn = MagicMock()
    # Return coords near the test station (13.1, 77.6) so it's within 5km radius
    mock_conn.execute.return_value.fetchone.return_value = (13.101, 77.595)
    mock_engine = _make_engine(mock_conn)

    with (
        patch("utils.db.get_engine", return_value=mock_engine),
        patch("utils.strr_overlay._MARKET_COORDS", {}),  # empty → hardcoded fallback unusable
        patch("utils.strr_overlay._load_stations", return_value=_one_station()),
    ):
        stations = STRROverlay().stations_near("Yelahanka", radius_km=5.0)
        assert len(stations) == 1
        assert stations[0]["name"] == "S1"


def test_gate162_a1_db_centroid_fallback_on_failure():
    """A1: hardcoded fallback used when DB fails."""
    from utils.strr_overlay import STRROverlay

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = Exception("DB unavailable")
    mock_engine = _make_engine(mock_conn)

    with (
        patch("utils.db.get_engine", return_value=mock_engine),
        patch("utils.strr_overlay._load_stations", return_value=_one_station()),
    ):
        stations = STRROverlay().stations_near("Yelahanka", radius_km=5.0)
        assert len(stations) == 1


def test_gate162_a1_db_centroid_none_fallback():
    """A1: hardcoded fallback used when DB returns None row."""
    from utils.strr_overlay import STRROverlay, _MARKET_COORDS

    original_yelahanka = _MARKET_COORDS.get("yelahanka")
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None

    with (
        patch("utils.db.get_engine", return_value=_make_engine(mock_conn)),
        patch("utils.strr_overlay._load_stations", return_value=_one_station()),
    ):
        stations = STRROverlay().stations_near("Yelahanka", radius_km=5.0)
        assert len(stations) == 1


def test_gate162_a1_unknown_market_returns_empty():
    """A1: unknown market with no DB row and no hardcoded fallback returns []."""
    from utils.strr_overlay import STRROverlay

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None

    with (
        patch("utils.db.get_engine", return_value=_make_engine(mock_conn)),
        patch("utils.strr_overlay._load_stations", return_value=_one_station()),
    ):
        stations = STRROverlay().stations_near("NonExistent", radius_km=5.0)
        assert stations == []


# ── A2: TTL cap —————————————————————————————————————————


def test_gate162_a2_ttl_expiry_discards_stale():
    """A2: stale _STATIONS discarded when TTL exceeded, fresh data loaded."""
    from utils.strr_overlay import _load_stations, _STATIONS_RELOAD_INTERVAL
    import time as _time

    fresh_data = [{"name": "FreshStation", "line": "Green", "lat": 13.0, "lon": 77.5, "status": "operational"}]
    mock_path = MagicMock()
    mock_path.exists.return_value = True
    mock_path.stat.return_value.st_mtime = _time.time() + 1
    mock_path.read_text.return_value = "[]"
    base_time = _time.time() + _STATIONS_RELOAD_INTERVAL + 10

    with (
        patch("utils.strr_overlay._STATIONS", [{"name": "stale"}]),
        patch("utils.strr_overlay._STATIONS_MTIME", _time.time()),
        patch("utils.strr_overlay.time.time", return_value=base_time),
        patch("utils.strr_overlay._STATIONS_PATH", mock_path),
        patch("utils.strr_overlay.json.loads", return_value=fresh_data),
    ):
        result = _load_stations()
        assert len(result) == 1
        assert result[0]["name"] == "FreshStation"


def test_gate162_a2_ttl_not_expired_returns_cached():
    """A2: cached data returned when TTL not exceeded."""
    from utils.strr_overlay import _load_stations
    import time as _time

    cached = [{"name": "CachedStation", "line": "Red", "lat": 13.0, "lon": 77.5, "status": "operational"}]
    base_time = _time.time()  # same time as _MTIME → TTL not exceeded

    with (
        patch("utils.strr_overlay._STATIONS", cached),
        patch("utils.strr_overlay._STATIONS_MTIME", base_time),
        patch("utils.strr_overlay.time.time", return_value=base_time),
        patch("utils.strr_overlay._STATIONS_PATH") as mock_path,
    ):
        mock_path.stat.return_value.st_mtime = base_time  # file unchanged
        result = _load_stations()
        assert len(result) == 1
        assert result[0]["name"] == "CachedStation"


# ── A3: Parcel graph stats endpoint ———————————————————


def test_gate162_a3_stats_empty_tables():
    """A3: Stats endpoint returns 0s when tables missing (graceful degradation)."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    def fail_side_effect(*args, **kwargs):
        mock_result = MagicMock()
        mock_result.scalar.side_effect = Exception("relation does not exist")
        return mock_result

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = fail_side_effect
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with (
        patch("dashboard.routers.data._get_sa_engine", return_value=mock_engine),
        patch("dashboard.routers.data._PARCEL_GRAPH_STATS_CACHE", {}),
    ):
        resp = client.get(
            "/api/v1/intel/parcel-graph/stats",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_edges"] == 0
    assert data["total_villages"] == 0
    assert data["last_materialized"] is None
    assert data["materialization_coverage_pct"] == 0.0


def test_gate162_a3_parcel_graph_stats_endpoint():
    """A3: GET /api/v1/intel/parcel-graph/stats returns 200 + keys."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    def execute_side_effect(*args, **kwargs):
        query_text = " ".join(str(a) for a in args) if args else ""
        mock_result = MagicMock()
        if "parcel_graph_edges" in query_text:
            if "COUNT(*)" in query_text and "DISTINCT" not in query_text:
                mock_result.scalar.return_value = 42
            elif "DISTINCT village" in query_text:
                mock_result.scalar.return_value = 5
            elif "MAX(computed_at)" in query_text:
                mock_result.scalar.return_value = "2026-06-29T12:00:00+00:00"
            else:
                mock_result.scalar.return_value = 0
        elif "v_deed_village_priority" in query_text:
            mock_result.scalar.return_value = 10
        else:
            mock_result.scalar.return_value = 0
        return mock_result

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = execute_side_effect
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    with (
        patch("dashboard.routers.data._get_sa_engine", return_value=mock_engine),
        patch("dashboard.routers.data._PARCEL_GRAPH_STATS_CACHE", {}),
    ):
        resp = client.get(
            "/api/v1/intel/parcel-graph/stats",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert "total_edges" in data
    assert data["total_edges"] == 42
    assert "materialization_coverage_pct" in data
    assert data["materialization_coverage_pct"] == 50.0
    assert "total_villages" in data


def test_gate162_a3_parcel_graph_stats_route_registered():
    """A3: parcel-graph/stats route registered in data router."""
    from dashboard.routers.data import router

    route_paths = [r.path for r in router.routes]
    assert "/intel/parcel-graph/stats" in route_paths


# ── A4: Migration chain ———————————————————————————————


def _parse_migration_revisions():
    """Parse all migration files in alembic/versions/ into {revision: down_revision}."""
    import pathlib
    import re
    migration_dir = pathlib.Path(__file__).resolve().parent.parent / "alembic" / "versions"
    chain: dict[str, str | None] = {}
    for fpath in sorted(migration_dir.glob("*.py")):
        content = fpath.read_text(encoding="utf-8")
        rev = None
        down = None
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("revision"):
                m = re.search(r'"([^"]+)"', stripped)
                if m:
                    rev = m.group(1)
            elif stripped.startswith("down_revision"):
                m = re.search(r'"([^"]+)"', stripped)
                if m:
                    down = m.group(1)
        if rev:
            chain[rev] = down
    return chain


def test_gate162_a4_migration_chain_0074():
    """A4: Migration 0074 has down_revision pointing to 0073."""
    chain = _parse_migration_revisions()
    assert "0074_deed_village_priority" in chain
    assert chain["0074_deed_village_priority"] == "0073_corridor_backtest"


def test_gate162_a4_migration_chain_0075():
    """A4: Migration 0075 has down_revision pointing to 0074."""
    chain = _parse_migration_revisions()
    assert "0075_parcel_graph_edges" in chain
    assert chain["0075_parcel_graph_edges"] == "0074_deed_village_priority"


def test_gate162_a4_migration_chain_0076():
    """A4: Migration 0076 has down_revision pointing to 0075."""
    chain = _parse_migration_revisions()
    assert "0076_calibration_snapshots" in chain
    assert chain["0076_calibration_snapshots"] == "0075_parcel_graph_edges"


def test_gate162_a4_migration_chain_0077():
    """A4: Migration 0077 has down_revision pointing to 0076."""
    chain = _parse_migration_revisions()
    assert "0077_deal_score_log" in chain
    assert chain["0077_deal_score_log"] == "0076_calibration_snapshots"


def test_gate162_a4_no_circular_references():
    """A4: No circular references in migration chain 0070-0077."""
    chain = _parse_migration_revisions()
    visited: set[str] = set()
    current: str | None = "0077_deal_score_log"
    while current:
        assert current not in visited, f"Circular reference detected at {current}"
        visited.add(current)
        current = chain.get(current)
    assert "0073_corridor_backtest" in visited, "Chain does not reach 0073"


def test_gate162_a4_migration_file_syntax():
    """A4: All migration files compile (syntax check)."""
    import pathlib
    migration_dir = pathlib.Path(__file__).resolve().parent.parent / "alembic" / "versions"
    for fpath in migration_dir.glob("007[0-7]*.py"):
        compile(fpath.read_text(encoding="utf-8"), fpath.name, "exec")


# ── A5: Route registration ———————————————————————————


def test_gate162_a5_routes_registered():
    """A5: Sprint 162 + recent routes registered in FastAPI route list."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    route_paths = [r.path for r in app.routes]

    assert "/api/v1/intel/parcel-graph/stats" in route_paths
    assert "/api/v1/intel/investor/weekly-digest" in route_paths
