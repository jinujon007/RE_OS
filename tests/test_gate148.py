"""
GATE-148 — Investor Brief Production (Sprint 148)

5 assertions (A1-A5):
A1: GET /api/v1/intel/investor/compare returns 200 with market/avg_psf/board_verdict keys
A2: GET /dashboard/investor-brief returns 200 (mock TemplateResponse)
A3: POST /api/v1/intel/investor/export-obsidian returns 200 with obsidian_path key
A4: GET /api/v1/intel/investor/vel-analysis returns 200 with key metrics
A5: All 4 new routes exist in FastAPI app route list
"""

import os
os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_API_KEY_READ", "test-read-key")

import json
import pytest
from fastapi.responses import HTMLResponse
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit

_TEST_MARKETS = "Yelahanka,Devanahalli"
_API_HEADER = {"X-API-Key": "test-key"}


def _make_row(values):
    r = MagicMock()
    r.__getitem__ = lambda self, i: values[i]
    r.__len__ = lambda: len(values)
    return r


# ── A1: Multi-market compare endpoint ──────────────────────────────────


def test_gate148_a1_compare_endpoint():
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    mock_brief = MagicMock()
    mock_brief.market_overview = {"avg_psf": 6500, "psf_min": 5000, "psf_max": 8000}
    mock_brief.board_verdict = {"decision_flag": "GO", "status": "found"}
    mock_brief.assembly_alerts = [{"buyer": "Test", "parcel_count": 2}]

    with patch(
        "utils.investor_brief_generator.InvestorBriefGenerator"
    ) as mock_gen_cls:
        mock_gen = MagicMock()
        mock_gen.generate.return_value = mock_brief
        mock_gen_cls.return_value = mock_gen

        client = TestClient(app)
        resp = client.get(
            f"/api/v1/intel/investor/compare?markets={_TEST_MARKETS}",
            headers=_API_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "markets" in data
        assert len(data["markets"]) == 2
        for m in data["markets"]:
            assert "market" in m
            assert "avg_psf" in m
            assert "board_verdict" in m


# ── A2: Dashboard panel route ──────────────────────────────────────────


def test_gate148_a2_dashboard_panel():
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    mock_resp = HTMLResponse(content="<html>mock</html>", status_code=200)
    with patch(
        "dashboard.routers.data.templates.TemplateResponse",
        return_value=mock_resp,
    ):
        client = TestClient(app)
        resp = client.get("/api/v1/investor-brief", headers=_API_HEADER)
        assert resp.status_code == 200


# ── A3: Export to Obsidian endpoint ────────────────────────────────────


def test_gate148_a3_export_obsidian():
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    mock_brief = MagicMock()
    mock_brief.market_overview = {"avg_psf": 6500}
    mock_brief.board_verdict = {"decision_flag": "GO", "status": "found"}
    mock_brief.assembly_alerts = []
    mock_brief.competitive_landscape = {"grade_a_count": 3}
    mock_brief.financial_summary = {"status": "insufficient_inputs"}
    mock_brief.supply_risk = {"pipeline_units": 500, "weeks_of_inventory": 24}
    mock_brief.to_dict.return_value = {
        "market": "Yelahanka",
        "generated_at": "2026-06-27T00:00:00",
        "market_overview": {"avg_psf": 6500},
        "board_verdict": {"decision_flag": "GO", "status": "found"},
        "assembly_alerts": [],
        "competitive_landscape": {"grade_a_count": 3},
        "financial_summary": {"status": "insufficient_inputs"},
        "supply_risk": {"pipeline_units": 500, "weeks_of_inventory": 24},
    }

    with patch(
        "utils.investor_brief_generator.InvestorBriefGenerator"
    ) as mock_gen_cls:
        mock_gen = MagicMock()
        mock_gen.generate.return_value = mock_brief
        mock_gen_cls.return_value = mock_gen

        mock_write = MagicMock(return_value="/mock/path.md")
        with patch(
            "dashboard.routers.data.write_investor_brief", mock_write, create=True
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/intel/investor/export-obsidian",
                json={"market": "Yelahanka"},
                headers=_API_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "obsidian_path" in data
            assert "generated_at" in data


# ── A4: VEL analysis endpoint ──────────────────────────────────────────


def test_gate148_a4_vel_analysis():
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    mock_rows = [
        _make_row(("Yelahanka", 6500.0)),
        _make_row(("Devanahalli", 5500.0)),
        _make_row(("Hebbal", 7500.0)),
    ]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value.execute.return_value.fetchall.return_value = (
        mock_rows
    )
    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn

    with patch("utils.db.get_engine", return_value=mock_engine):
        mock_irr_result = MagicMock()
        mock_irr_result.simple_irr_pct = 22.5
        with patch("utils.irr_model.calc_irr", return_value=mock_irr_result):
            client = TestClient(app)
            resp = client.get(
                "/api/v1/intel/investor/vel-analysis?land_cost_cr=5&area_acres=1&target_psf=9000",
                headers=_API_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "competitor_gap_pct" in data
            assert "irr_at_target_psf" in data
            assert "entry_recommendation" in data


# ── A5: Route registration check ───────────────────────────────────────


def test_gate148_a5_routes_registered():
    from dashboard.routers.data import router

    route_paths = [r.path for r in router.routes]
    required = [
        "/intel/investor/compare",
        "/intel/investor/vel-analysis",
        "/intel/investor/export-obsidian",
        "/investor-brief",
    ]
    for r in required:
        assert r in route_paths, f"Route {r} not found in data router"
