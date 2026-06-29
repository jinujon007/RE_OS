"""GATE-151: Assembly Intelligence Time-Series — 5 gate assertions (A1-A5).

A1: AssemblyDetector().detect_time_series returns list with week_start/cluster_count/avg_confidence
A2: Alembic migration 0072 importable, has upgrade/downgrade functions
A3: GET /api/v1/intel/assembly-timeline?market=Yelahanka returns 200 with timeline list
A4: assembly_signals.html contains "assemblyTimeline" canvas id
A5: detect_time_series returns empty list (not exception) on DB failure
"""

import os
import pathlib
import re
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_API_KEY_READ", "test-read-key")

pytestmark = pytest.mark.unit


# ── A1: detect_time_series returns structured data ──────────────────────


def _make_mock_row(confidence_score):
    r = MagicMock()
    r.confidence_score = confidence_score
    return r


def test_gate151_a1_detect_time_series_returns_list():
    """A1: AssemblyDetector.detect_time_series returns list with expected keys and values."""
    from utils.assembly_detector import AssemblyDetector

    mock_rows = [
        _make_mock_row(0.85),
        _make_mock_row(0.92),
        _make_mock_row(0.45),
    ]

    with patch("utils.assembly_detector.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        detector = AssemblyDetector()
        result = detector.detect_time_series("Yelahanka", lookback_months=3)

    assert isinstance(result, list)
    assert len(result) >= 1
    min_expected = (date.today() - timedelta(days=120)).isoformat()
    for item in result:
        assert "week_start" in item
        assert item["week_start"] >= min_expected, (
            f"{item['week_start']} should be >= {min_expected} (within lookback)"
        )
        assert "cluster_count" in item
        assert isinstance(item["cluster_count"], int)
        assert "avg_confidence" in item
        assert isinstance(item["avg_confidence"], float)
        assert 0.0 <= item["avg_confidence"] <= 1.0
        assert "high_confidence_count" in item
        assert isinstance(item["high_confidence_count"], int)
    assert result[0]["cluster_count"] == 3
    assert result[0]["high_confidence_count"] == 2
    # avg_confidence = mean([0.85, 0.92, 0.45]) = 0.74
    assert result[0]["avg_confidence"] == 0.74


# ── A2: Alembic migration 0072 importable ──────────────────────────────


def test_gate151_a2_migration_0072_importable():
    """A2: alembic/versions/0072_assembly_weekly_trend.py is importable with upgrade/downgrade."""
    import importlib
    spec = importlib.util.spec_from_file_location(
        "alembic.versions._0072",
        str(pathlib.Path(__file__).parents[1] / "alembic" / "versions" / "0072_assembly_weekly_trend.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)


# ── A3: assembly-timeline endpoint ──────────────────────────────────────


def test_gate151_a3_assembly_timeline_endpoint():
    """A3: GET /api/v1/intel/assembly-timeline returns 200 with timeline list."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    mock_rows = [
        MagicMock(week_start="2026-06-01", cluster_count=3, avg_confidence=0.78, high_confidence_count=2),
        MagicMock(week_start="2026-06-08", cluster_count=5, avg_confidence=0.82, high_confidence_count=4),
    ]

    with (
        patch("dashboard.routers.data._get_sa_engine") as mock_eng,
        patch("dashboard.routers.data._resolve_market") as mock_resolve,
    ):
        mock_resolve.return_value = "Yelahanka"
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        resp = client.get(
            "/api/v1/intel/assembly-timeline?market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "timeline" in data
        assert isinstance(data["timeline"], list)
        assert len(data["timeline"]) == 2
        for entry in data["timeline"]:
            assert "week_start" in entry
            assert "cluster_count" in entry
        assert "market" in data
        assert data["market"] == "Yelahanka"
        assert "total_weeks" in data


def test_gate151_a3_no_auth_returns_401():
    """A3: assembly-timeline returns 401 without valid API key."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get("/api/v1/intel/assembly-timeline?market=Yelahanka")
    assert resp.status_code == 401


def test_gate151_a3_invalid_market_returns_400():
    """A3: assembly-timeline returns 400 for unknown market."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get(
        "/api/v1/intel/assembly-timeline?market=InvalidTown",
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 400


def test_gate151_a3_empty_market_returns_422():
    """A3: assembly-timeline returns 422 for empty market string (FastAPI validation)."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)
    resp = client.get(
        "/api/v1/intel/assembly-timeline?market=",
        headers={"X-API-Key": "test-key"},
    )
    assert resp.status_code == 422


def test_gate151_a3_empty_timeline_returns_ok_with_zero_weeks():
    """A3: returns 200 with total_weeks=0 when no data exists."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("dashboard.routers.data._get_sa_engine") as mock_eng,
        patch("dashboard.routers.data._resolve_market") as mock_resolve,
    ):
        mock_resolve.return_value = "Yelahanka"
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []

        resp = client.get(
            "/api/v1/intel/assembly-timeline?market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_weeks"] == 0
    assert data["source"] == "detector"


def test_gate151_a3_fallback_on_view_failure():
    """A3: falls back to detect_time_series when view query fails."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("dashboard.routers.data._get_sa_engine") as mock_eng,
        patch("dashboard.routers.data._resolve_market") as mock_resolve,
    ):
        mock_resolve.return_value = "Yelahanka"
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = Exception("view not found")

        resp = client.get(
            "/api/v1/intel/assembly-timeline?market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "detector"


# ── A4: assembly_signals.html contains assemblyTimeline canvas id ───────


def test_gate151_a4_assembly_timeline_canvas_exists():
    """A4: assembly_signals.html contains <canvas id='assemblyTimeline'> in the timeline panel."""
    html_path = pathlib.Path(__file__).parents[1] / "dashboard" / "templates" / "assembly_signals.html"
    content = html_path.read_text(encoding="utf-8")
    assert re.search(
        r'<canvas\s+id="assemblyTimeline"',
        content,
    ), "<canvas id='assemblyTimeline'> missing from template"
    assert 'loadTimeline()' in content, "loadTimeline() JS function missing"
    assert 'class="timeline-panel"' in content or 'id="timeline-panel"' in content, "timeline panel element missing"


# ── A5: detect_time_series returns empty list on DB failure ─────────────


def test_gate151_a5_detect_time_series_empty_on_failure():
    """A5: detect_time_series returns [] (not exception) on DB failure."""
    from utils.assembly_detector import AssemblyDetector

    with patch("utils.assembly_detector.get_engine") as mock_eng:
        mock_eng.side_effect = Exception("DB connection failed")
        detector = AssemblyDetector()
        result = detector.detect_time_series("Yelahanka")

    assert isinstance(result, list)
    assert len(result) == 0
