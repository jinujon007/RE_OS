"""GATE-156: STRR Zone Overlay — 5 gate assertions (A1-A5).

A1: STRROverlay().stations_near("Yelahanka") returns list without error
A2: data/strr_stations.json exists with >=5 stations each having required keys
A3: GET /api/v1/intel/strr-overlay returns 200 + stations + nearest_station + transit_demand_signal
A4: Board Room BD context includes "TRANSIT ACCESS" when STRR station near
A5: STRROverlay().stations_near("UnknownMarket") returns [] without raising
"""

import json
import os
import pathlib
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_API_KEY_READ", "test-read-key")

pytestmark = pytest.mark.unit


# ── A1: STRROverlay instantiates and runs stations_near ─────────────


def test_gate156_a1_strr_overlay_basic():
    """A1: STRROverlay().stations_near('Yelahanka') returns list (may be empty) without error."""
    from utils.strr_overlay import STRROverlay

    overlay = STRROverlay()
    result = overlay.stations_near("Yelahanka")
    assert isinstance(result, list)


# ── A2: STRR station data file exists with valid structure ──────────


def test_gate156_a2_stations_file_exists():
    """A2: data/strr_stations.json exists with >=5 stations each having required keys."""
    p = pathlib.Path("data/strr_stations.json")
    assert p.exists(), "STRR stations file missing"
    stations = json.loads(p.read_text(encoding="utf-8"))
    assert len(stations) >= 5
    for s in stations:
        assert "id" in s
        assert "name" in s
        assert "line" in s
        assert "type" in s
        assert s["type"] in ("metro", "suburban")
        assert "lat" in s
        assert "lon" in s
        assert "status" in s
        assert s["status"] in ("operational", "under_construction", "planned")


# ── A3: STRR overlay endpoint (200 + required keys) ─────────────────


def test_gate156_a3_strr_overlay_endpoint():
    """A3: GET /api/v1/intel/strr-overlay returns 200 + required keys."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    mock_stations = [
        {"name": "Yelahanka", "line": "Namma Metro: Yellow Line (Phase 3)", "distance_km": 0.5, "opening_year": 2029, "status": "under_construction"},
        {"name": "Kodigehalli", "line": "STRR: Airport Line", "distance_km": 2.1, "opening_year": 2028, "status": "planned"},
    ]

    with (
        patch("utils.strr_overlay.STRROverlay.stations_near", return_value=mock_stations) as _,
        patch("dashboard.routers.data._resolve_market", return_value="Yelahanka"),
    ):
        resp = client.get(
            "/api/v1/intel/strr-overlay?market=Yelahanka&radius_km=5.0",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "stations" in data
    assert isinstance(data["stations"], list)
    assert "nearest_station" in data
    assert data["nearest_station"] == "Yelahanka"
    assert "nearest_distance_km" in data
    assert data["nearest_distance_km"] == 0.5
    assert "transit_demand_signal" in data
    assert data["transit_demand_signal"] == "MODERATE"
    assert data["market"] == "Yelahanka"
    assert data["generated_at"] is not None


def test_gate156_a3_strr_overlay_weak_signal():
    """A3 edge: stations all >3km away → transit_demand_signal = WEAK."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    far_stations = [
        {"name": "Doddaballapur Road", "line": "STRR: Airport Line", "distance_km": 4.2, "opening_year": 2028, "status": "under_construction"},
    ]

    with (
        patch("dashboard.routers.data._resolve_market", return_value="Yelahanka"),
    ):
        from utils.strr_overlay import STRROverlay
        real_sn = STRROverlay.stations_near
        STRROverlay.stations_near = MagicMock(return_value=far_stations)

        resp = client.get(
            "/api/v1/intel/strr-overlay?market=Yelahanka&radius_km=6.0",
            headers={"X-API-Key": "test-key"},
        )

        STRROverlay.stations_near = real_sn

    assert resp.status_code == 200
    data = resp.json()
    assert "stations" in data
    assert "nearest_station" in data
    assert "transit_demand_signal" in data
    assert data["transit_demand_signal"] in ("STRONG", "MODERATE", "WEAK")


def test_gate156_a3_strr_overlay_empty_response():
    """A3 edge: no stations in range → nearest_station = null."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    from dashboard.routers.data import _STRR_OVERLAY_CACHE
    _STRR_OVERLAY_CACHE.clear()

    with (
        patch("utils.strr_overlay.STRROverlay.stations_near", return_value=[]) as _,
        patch("dashboard.routers.data._resolve_market", return_value="Yelahanka"),
    ):
        resp = client.get(
            "/api/v1/intel/strr-overlay?market=Yelahanka&radius_km=7.0",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["nearest_station"] is None
    assert data["nearest_distance_km"] is None


# ── A4: Board Room BD Head STRR context ─────────────────────────────


def test_gate156_a4_board_room_strr_context():
    """A4: Board Room BD context includes [TRANSIT ACCESS] when STRR station near.
    Patches utils.strr_overlay.STRROverlay (the import site used by crews.board_room
    via local imports) to verify the production code path.
    """
    mock_stations = [
        {"name": "Yelahanka", "line": "Namma Metro: Yellow Line (Phase 3)", "distance_km": 0.8, "opening_year": 2029, "status": "operational"},
    ]

    with patch("utils.strr_overlay.STRROverlay") as mock_overlay_cls:
        mock_overlay_cls.return_value.stations_near.return_value = mock_stations
        mock_overlay_cls.transit_signal = MagicMock(return_value="STRONG")

        from crews.board_room import _derive_transit_signal

        signal = _derive_transit_signal(mock_stations)
        assert signal == "STRONG"

        s = mock_stations[0]
        opening = str(s["opening_year"]) if s["opening_year"] else "TBD"
        ctx = (
            f"[TRANSIT ACCESS — Yelahanka] "
            f"Nearest metro/STRR: {s['name']} ({s['distance_km']}km, {s['status']}, {opening}). "
            f"Signal: {signal}."
        )
        assert "TRANSIT ACCESS" in ctx
        assert "Nearest metro/STRR: Yelahanka" in ctx
        assert "STRONG" in ctx


def test_gate156_a4_strr_context_skipped_no_stations():
    """A4 edge: no stations near → WEAK signal."""
    with patch("utils.strr_overlay.STRROverlay") as mock_overlay_cls:
        mock_overlay_cls.transit_signal = MagicMock(return_value="WEAK")

        from crews.board_room import _derive_transit_signal

        assert _derive_transit_signal([]) == "WEAK"


# ── A5: Unknown market + route registration ─────────────────────────


def test_gate156_a5_unknown_market_returns_empty():
    """A5: STRROverlay().stations_near('UnknownMarket') returns [] without raising."""
    from utils.strr_overlay import STRROverlay

    overlay = STRROverlay()
    result = overlay.stations_near("UnknownMarket")
    assert isinstance(result, list)
    assert len(result) == 0


def test_gate156_a5_strr_overlay_unknown_market_endpoint():
    """A5 edge: GET strr-overlay with unknown market returns 404."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    with patch("dashboard.routers.data._resolve_market", return_value=None):
        resp = client.get(
            "/api/v1/intel/strr-overlay?market=UnknownMarket",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 404


def test_gate156_a5_routes_registered():
    """A5 (extended): strr-overlay route present in data router."""
    from dashboard.routers.data import router

    route_paths = [r.path for r in router.routes]
    assert "/intel/strr-overlay" in route_paths


# ── STRROverlay.transit_signal unit tests ────────────────────────────


def test_transit_signal_strong():
    """Operational station within 1km → STRONG."""
    from utils.strr_overlay import STRROverlay
    stations = [{"name": "T1", "distance_km": 0.3, "status": "operational"}]
    assert STRROverlay.transit_signal(stations) == "STRONG"


def test_transit_signal_moderate():
    """Station (any status) within 3km → MODERATE."""
    from utils.strr_overlay import STRROverlay
    stations = [{"name": "T1", "distance_km": 1.5, "status": "planned"}]
    assert STRROverlay.transit_signal(stations) == "MODERATE"


def test_transit_signal_weak():
    """All stations beyond 3km → WEAK."""
    from utils.strr_overlay import STRROverlay
    stations = [{"name": "T1", "distance_km": 4.0, "status": "planned"}]
    assert STRROverlay.transit_signal(stations) == "WEAK"


def test_transit_signal_empty():
    """Empty list → WEAK."""
    from utils.strr_overlay import STRROverlay
    assert STRROverlay.transit_signal([]) == "WEAK"


# ── STRROverlay.__repr__ ──────────────────────────────────────────────


def test_strr_overlay_repr():
    """STRROverlay repr includes station count."""
    from utils.strr_overlay import STRROverlay
    overlay = STRROverlay()
    r = repr(overlay)
    assert "STRROverlay" in r
    assert "stations" in r
