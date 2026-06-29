"""GATE-154: VEL Intelligence Pack — 5 gate assertions (A1-A5).

A1: GET /api/v1/intel/vel/competitive-report returns 200 + required keys
A2: GET /api/v1/intel/vel/pricing-sensitivity returns 200 + required keys
A3: POST /api/v1/intel/vel/export-obsidian returns 200 + obsidian_path
A4: TOOLS dict in mcp_server.re_os_mcp contains "vel_competitive_report"
A5: All 3 new routes present in data router
"""

import os
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_API_KEY_READ", "test-read-key")

pytestmark = pytest.mark.unit


def _mock_grade_a_rows():
    return [
        ("Brigade Group", 3),
        ("Prestige Group", 2),
        ("Sobha Ltd", 1),
    ]


def _mock_psf_value(val):
    mock = MagicMock()
    mock.scalar.return_value = val
    return mock


def _mock_fetchall(mock_conn, rows):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_conn.execute.return_value = mock_cursor


# ── A1: VEL competitive report endpoint ─────────────────────────────


def test_gate154_a1_vel_competitive_report():
    """A1: GET /api/v1/intel/vel/competitive-report returns 200 + required keys."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("dashboard.routers.data._get_sa_engine") as mock_eng,
    ):
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        # Grade A query
        grade_mock = MagicMock()
        grade_mock.fetchall.return_value = _mock_grade_a_rows()
        # PSF trend queries
        current_mock = MagicMock()
        current_mock.scalar.return_value = 6500.0
        prior_mock = MagicMock()
        prior_mock.scalar.return_value = 6200.0
        # Pipeline query
        pipeline_mock = MagicMock()
        pipeline_mock.scalar.return_value = 450
        # Absorption query
        abs_mock = MagicMock()
        abs_mock.scalar.return_value = 12.5

        mock_conn.execute.side_effect = [
            grade_mock,
            current_mock,
            prior_mock,
            pipeline_mock,
            abs_mock,
        ]

        resp = client.get(
            "/api/v1/intel/vel/competitive-report?target_market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "grade_a_competitors" in data
    assert "psf_trend_3m" in data
    assert "recommendation" in data
    assert isinstance(data["grade_a_competitors"], list)
    assert "absorption_rate" in data
    assert "launch_pipeline_units" in data
    assert "generated_at" in data


# ── A2: VEL pricing sensitivity endpoint ────────────────────────────


def test_gate154_a2_vel_pricing_sensitivity():
    """A2: GET /api/v1/intel/vel/pricing-sensitivity returns 200 + required keys."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with patch("dashboard.routers.data._get_sa_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        psf_mock = MagicMock()
        psf_rows = [(float(v),) for v in [3000, 4000, 4500, 5000, 5500, 6000, 6500, 7000, 7500, 8000]]
        psf_mock.fetchall.return_value = psf_rows
        mock_conn.execute.return_value = psf_mock

        resp = client.get(
            "/api/v1/intel/vel/pricing-sensitivity?market=Yelahanka&target_psf=8500",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "absorption_shift_psf" in data
    assert "risk_band" in data
    assert "p25" in data
    assert "p50" in data
    assert "p75" in data
    assert "premium_over_median_pct" in data
    assert data["risk_band"] in ("LOW", "MODERATE", "HIGH")


# ── A3: VEL Obsidian export endpoint ────────────────────────────────


def test_gate154_a3_vel_export_obsidian():
    """A3: POST /api/v1/intel/vel/export-obsidian returns 200 + obsidian_path."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("utils.obsidian_sync.write_vel_pack") as mock_write,
        patch("dashboard.routers.data._get_sa_engine") as mock_eng,
        patch("utils.investor_brief_generator.InvestorBriefGenerator") as mock_gen,
        patch("utils.investor_brief_generator.format_markdown", return_value="# Mock Investor Brief"),
    ):
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        grade_mock = MagicMock()
        grade_mock.fetchall.return_value = []
        psf_mock = MagicMock()
        psf_mock.fetchall.return_value = []
        mock_conn.execute.side_effect = [grade_mock, psf_mock]

        mock_brief = MagicMock()
        mock_brief.to_dict.return_value = {"market": "Yelahanka", "generated_at": "2026-06-29T00:00:00"}
        mock_gen.return_value.generate.return_value = mock_brief

        mock_write.return_value = "/fake/path/03 LLS/02 Projects/VEL/(AI) VEL Intel Pack Yelahanka 2026-06-29.md"

        resp = client.post(
            "/api/v1/intel/vel/export-obsidian",
            headers={"X-API-Key": "test-key", "Content-Type": "application/json"},
            json={"target_market": "Yelahanka"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "obsidian_path" in data


# ── A4: MCP tool registered in TOOLS registry ───────────────────────


def test_gate154_a4_mcp_tool_registered():
    """A4: vel_competitive_report is registered in TOOLS dict."""
    from mcp_server.re_os_mcp import TOOLS

    assert "vel_competitive_report" in TOOLS
    tool = TOOLS["vel_competitive_report"]
    assert tool["name"] == "vel_competitive_report"
    assert "description" in tool
    assert "handler" in tool
    assert callable(tool["handler"])


# ── A5: All 3 new routes present in data router ─────────────────────


def test_gate154_a5_routes_registered():
    """A5: All 3 VEL routes are present in the data router."""
    from dashboard.routers.data import router

    route_paths = [r.path for r in router.routes]
    assert "/intel/vel/competitive-report" in route_paths
    assert "/intel/vel/pricing-sensitivity" in route_paths
    assert "/intel/vel/export-obsidian" in route_paths


# ── A1 edge case: DB failure fallback ───────────────────────────────


def test_gate154_a1_competitive_report_db_failure():
    """A1 edge: DB failure in competitive report returns 500 gracefully."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    from dashboard.routers.data import _VEL_COMPETITIVE_REPORT_CACHE
    client = TestClient(app)

    _VEL_COMPETITIVE_REPORT_CACHE.clear()
    with patch("dashboard.routers.data._get_sa_engine") as mock_eng:
        mock_eng.side_effect = Exception("DB connection refused")
        resp = client.get(
            "/api/v1/intel/vel/competitive-report?target_market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )
    assert resp.status_code >= 400


# ── A2 edge case: insufficient PSF data (fallback values) ────────────


def test_gate154_a2_pricing_sensitivity_insufficient_data():
    """A2 edge: <3 PSF data points uses fallback estimates, returns 200."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with patch("dashboard.routers.data._get_sa_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        psf_mock = MagicMock()
        psf_mock.fetchall.return_value = [(5500.0,)]
        mock_conn.execute.return_value = psf_mock

        resp = client.get(
            "/api/v1/intel/vel/pricing-sensitivity?market=Yelahanka&target_psf=8500",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "note" in data
    assert data["note"] != ""
    assert data["data_points"] < 3
    assert data["risk_band"] in ("LOW", "MODERATE", "HIGH")


# ── A3 edge case: write_vel_pack returns None (vault not mounted) ────


def test_gate154_a3_export_obsidian_vault_not_mounted():
    """A3 edge: write_vel_pack returns None → placeholder path returned."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app)

    with (
        patch("utils.obsidian_sync.write_vel_pack", return_value=None) as mock_write,
        patch("dashboard.routers.data._get_sa_engine") as mock_eng,
        patch("utils.investor_brief_generator.InvestorBriefGenerator") as mock_gen,
        patch("utils.investor_brief_generator.format_markdown", return_value="# Mock"),
    ):
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        grade_mock = MagicMock()
        grade_mock.fetchall.return_value = []
        psf_mock = MagicMock()
        psf_mock.fetchall.return_value = []
        mock_conn.execute.side_effect = [grade_mock, psf_mock]
        mock_gen.return_value.generate.return_value = MagicMock()

        resp = client.post(
            "/api/v1/intel/vel/export-obsidian",
            headers={"X-API-Key": "test-key", "Content-Type": "application/json"},
            json={"target_market": "Yelahanka"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "obsidian_path" in data
    assert "note" in data
    mock_write.assert_called_once()
