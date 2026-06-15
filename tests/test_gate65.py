"""GATE-65 declaration — Investor Readiness (Sprint 57).

Verification criteria:
1. GET /api/portfolio returns 200 with >= 3 projects
2. GET /api/portfolio/summary has total_projects, delivered_count, markets_covered
3. PeerBenchmarkEngine.compute() returns avg_psf_grade_a > 0 (mocked w/ Grade A data)
4. InvestorBrief Section 6 (LLS Pedigree) non-empty
"""

import pytest
from unittest.mock import patch, MagicMock
import importlib

pytestmark = pytest.mark.unit


def _fresh_client():
    from dashboard import app_fastapi

    importlib.reload(app_fastapi)
    from starlette.testclient import TestClient

    return TestClient(app_fastapi.app)


def test_gate65_portfolio_endpoint_returns_projects():
    """Assertion 1: GET /api/portfolio returns 200 and >= 3 projects."""
    from datetime import date, datetime

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            (
                "u1",
                "Project A",
                "Bangalore",
                "Yelahanka",
                "premium",
                500,
                480,
                date(2020, 1, 15),
                date(2024, 6, 30),
                50.0,
                300.0,
                18.5,
                "delivered",
                "R/1",
                "note",
                datetime(2026, 6, 8),
            ),
            (
                "u2",
                "Project B",
                "Bangalore",
                "Devanahalli",
                "mid_market",
                300,
                290,
                date(2019, 3, 1),
                date(2023, 12, 15),
                35.0,
                180.0,
                15.2,
                "delivered",
                "R/2",
                "note",
                datetime(2026, 6, 8),
            ),
            (
                "u3",
                "Project C",
                "Bangalore",
                "Yelahanka",
                "premium",
                200,
                185,
                date(2018, 6, 20),
                date(2022, 3, 31),
                25.0,
                140.0,
                21.4,
                "delivered",
                "R/3",
                "note",
                datetime(2026, 6, 8),
            ),
            (
                "u4",
                "Project D",
                "Bangalore",
                None,
                "luxury",
                350,
                340,
                date(2021, 1, 10),
                date(2025, 6, 30),
                95.0,
                620.0,
                17.8,
                "delivered",
                "R/4",
                "note",
                datetime(2026, 6, 8),
            ),
        ]
        client = _fresh_client()
        resp = client.get("/api/portfolio", headers={"X-API-Key": "test"})
        assert resp.status_code == 200
        data = resp.json().get("data", [])
        assert len(data) >= 3, f"Expected >=3 projects, got {len(data)}"


def test_gate65_portfolio_summary_has_keys():
    """Assertion 2: GET /api/portfolio/summary has required keys."""
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        _call_idx = [0]

        def _side(*a, **kw):
            idx = _call_idx[0]
            _call_idx[0] += 1
            if idx == 0:
                m = MagicMock()
                m.fetchone.return_value = (4, 3, 18.2, 1350)
                return m
            m = MagicMock()
            m.fetchall.return_value = [("Yelahanka",), ("Devanahalli",)]
            return m

        mock_conn.execute.side_effect = _side
        client = _fresh_client()
        resp = client.get("/api/portfolio/summary", headers={"X-API-Key": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "total_projects" in data
        assert "delivered_count" in data
        assert "markets_covered" in data
        assert data["total_projects"] == 4
        assert data["delivered_count"] == 3
        assert len(data["markets_covered"]) >= 1


def test_gate65_peer_benchmark_returns_avg_psf():
    """Assertion 3: PeerBenchmarkEngine.compute() returns avg_psf_grade_a > 0."""
    from intelligence.peer_benchmark import PeerBenchmarkEngine

    mock_rows = [
        (7500.0, 9500.0, 8500.0, 65.0, 400, "Proj A", "DevCo"),
        (7200.0, 9200.0, 8200.0, 55.0, 350, "Proj B", "BuildCo"),
        (7000.0, 9000.0, 8000.0, 70.0, 500, "Proj C", "ConstCo"),
    ]
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows
        result = PeerBenchmarkEngine.compute("Yelahanka", 7500)
        assert result.avg_psf_grade_a > 0
        assert result.grade_a_count >= 3
        assert result.avg_psf_grade_a > 0


def test_gate65_investor_brief_section_6_non_empty():
    """Assertion 4: InvestorBrief Section 6 (LLS Pedigree) is non-empty."""
    from datetime import datetime, timezone
    from intelligence.registry import IntelPackage
    from unittest.mock import MagicMock, patch

    pkg = IntelPackage(
        survey_no="45/2",
        market="Devanahalli",
        collected_at=datetime.now(timezone.utc).isoformat(),
        module_status={},
        deal_type="compare",
    )
    _Mpulse = MagicMock()
    _Mpulse.avg_listing_psf = 7800
    _Mpulse.median_igr_psf = 5200.0
    _Mpulse.months_of_supply = 8
    _Mpulse.price_momentum_signal = "STABLE"
    _Mpulse.supply_label = "MODERATE"
    _Mpulse.avg_absorption_pct = 18
    _Mpulse.unique_developers = 12
    _Mpulse.grade_a_developers = 4
    _Mpulse.total_units = 3200
    _Mpulse.total_projects = 18
    pkg.market_pulse = _Mpulse

    _Feval = MagicMock()
    _Feval.sell_psf = 7500
    _Feval.best_structure = "JV"
    _Feval.psf_source_quality = "live_listing"
    _Feval.igr_median_psf = 4800
    _Feval.igr_record_count = 25
    _Feval.land_area_sqft = 217800
    _Feval.sellable_area_sqft = 130680
    _Feval.recommendation = "PURSUE"
    _Feval.scenarios = ""
    s = MagicMock()
    s.structure = "purchase"
    s.simple_irr_pct = 22.0
    s.verdict = "PURSUE"
    s.equity_required = 5000000
    s.gross_development_value = 45000000
    s.payback_months = 36
    _Feval.purchase = s
    _Feval.jd = s
    _Feval.jv = s
    pkg.financial_evaluation = _Feval

    _Llegal = MagicMock()
    _Llegal.risk_level = "LOW"
    _Llegal.zone = "R3"
    _Llegal.zone_risk_level = "LOW"
    _Llegal.guidance_value_psf = 4500
    _Llegal.litigation_risk = "NONE"
    _Llegal.land_use_conversion_needed = False
    _Llegal.inheritance_risk = "NONE"
    _Llegal.title_risk_flags = []
    _Llegal.overlay_risks = []
    pkg.legal_picture = _Llegal

    _Lpicture = MagicMock()
    _Lpicture.land_area_acres = 5.0
    _Lpicture.zone = "R3"
    _Lpicture.far = 1.75
    _Lpicture.buildable_area_sqft = 150000
    _Lpicture.sellable_area_sqft = 130000
    _Lpicture.max_floors = 5
    _Lpicture.green_pct = 35
    _Lpicture.meets_bda_minimum = True
    _Lpicture.development_readiness = "HIGH"
    _Lpicture.flood_risk = "LOW"
    _Lpicture.flags = []
    pkg.land_picture = _Lpicture

    _Demand = MagicMock()
    _Demand.demand_signal = "STABLE"
    _Demand.demand_score = 0.65
    _Demand.price_momentum_signal = "STABLE"
    _Demand.new_rera_launches_90d = 3
    _Demand.listing_trend_90d_pct = 5.0
    _Demand.developer_confidence_pct = 75.0
    _Demand.absorption_pct = 18.0
    _Demand.listing_trend_30d_pct = 2.5
    _Demand.signals = []
    pkg.demand_signals = _Demand
    pkg.all_modules_success = True

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        def _side(*a, **kw):
            _call_idx = [0]

            def _inner(*a2, **kw2):
                idx = _call_idx[0]
                _call_idx[0] += 1
                if idx == 0:
                    m = MagicMock()
                    m.fetchone.return_value = (4, 3, 1500, 18.2)
                    return m
                m = MagicMock()
                m.fetchall.return_value = [("Yelahanka",)]
                return m

            return _inner(*a, **kw)

        mock_conn.execute.side_effect = _side
        from utils.investor_brief_v2 import generate_investor_brief

        result = generate_investor_brief(pkg)
        sections = result["sections"]
        sec6 = [s for s in sections if "LLS Pedigree" in s["title"]]
        assert len(sec6) == 1
        assert len(sec6[0]["body"]) > 50


def test_gate65_investor_brief_section_7_market_position():
    """Assertion 5: InvestorBrief Section 7 (Market Position) non-empty with PSF text."""
    from datetime import datetime, timezone
    from intelligence.registry import IntelPackage
    from intelligence.peer_benchmark import PeerBenchmarkResult
    from unittest.mock import MagicMock, patch

    pb = PeerBenchmarkResult(
        market="Devanahalli",
        as_of="2026-06-08T00:00:00",
        grade_a_count=5,
        avg_psf_grade_a=7200.0,
        median_absorption_pct_grade_a=60.0,
        avg_units_grade_a=350.0,
        lls_target_psf=7500.0,
        lls_vs_grade_a_pct=4.17,
        positioning="COMPETITIVE",
    )
    pkg = IntelPackage(
        survey_no="45/2",
        market="Devanahalli",
        collected_at=datetime.now(timezone.utc).isoformat(),
        module_status={},
        deal_type="compare",
    )
    _Mpulse = MagicMock()
    _Mpulse.avg_listing_psf = 7800
    _Mpulse.median_igr_psf = 5200.0
    _Mpulse.months_of_supply = 8
    _Mpulse.price_momentum_signal = "STABLE"
    _Mpulse.supply_label = "MODERATE"
    _Mpulse.avg_absorption_pct = 18
    _Mpulse.unique_developers = 12
    _Mpulse.grade_a_developers = 4
    _Mpulse.total_units = 3200
    _Mpulse.total_projects = 18
    pkg.market_pulse = _Mpulse
    _Feval = MagicMock()
    _Feval.sell_psf = 7500
    _Feval.best_structure = "JV"
    _Feval.psf_source_quality = "live_listing"
    _Feval.igr_median_psf = 4800
    _Feval.igr_record_count = 25
    _Feval.land_area_sqft = 217800
    _Feval.sellable_area_sqft = 130680
    _Feval.recommendation = "PURSUE"
    _Feval.scenarios = ""
    s = MagicMock()
    s.structure = "purchase"
    s.simple_irr_pct = 22.0
    s.verdict = "PURSUE"
    s.equity_required = 5000000
    s.gross_development_value = 45000000
    s.payback_months = 36
    _Feval.purchase = s
    _Feval.jd = s
    _Feval.jv = s
    pkg.financial_evaluation = _Feval
    _Llegal = MagicMock()
    _Llegal.risk_level = "LOW"
    _Llegal.zone = "R3"
    _Llegal.zone_risk_level = "LOW"
    _Llegal.guidance_value_psf = 4500
    _Llegal.litigation_risk = "NONE"
    _Llegal.land_use_conversion_needed = False
    _Llegal.inheritance_risk = "NONE"
    _Llegal.title_risk_flags = []
    _Llegal.overlay_risks = []
    pkg.legal_picture = _Llegal
    _Lpicture = MagicMock()
    _Lpicture.land_area_acres = 5.0
    _Lpicture.zone = "R3"
    _Lpicture.far = 1.75
    _Lpicture.buildable_area_sqft = 150000
    _Lpicture.sellable_area_sqft = 130000
    _Lpicture.max_floors = 5
    _Lpicture.green_pct = 35
    _Lpicture.meets_bda_minimum = True
    _Lpicture.development_readiness = "HIGH"
    _Lpicture.flood_risk = "LOW"
    _Lpicture.flags = []
    pkg.land_picture = _Lpicture
    _Demand = MagicMock()
    _Demand.demand_signal = "STABLE"
    _Demand.demand_score = 0.65
    _Demand.price_momentum_signal = "STABLE"
    _Demand.new_rera_launches_90d = 3
    _Demand.listing_trend_90d_pct = 5.0
    _Demand.developer_confidence_pct = 75.0
    _Demand.absorption_pct = 18.0
    _Demand.listing_trend_30d_pct = 2.5
    _Demand.signals = []
    pkg.demand_signals = _Demand
    pkg.peer_benchmark = pb
    pkg.all_modules_success = True

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        _call_idx = [0]

        def _side(*a, **kw):
            idx = _call_idx[0]
            _call_idx[0] += 1
            if idx == 0:
                m = MagicMock()
                m.fetchone.return_value = (4, 3, 1500, 18.2)
                return m
            m = MagicMock()
            m.fetchall.return_value = [("Yelahanka",)]
            return m

        mock_conn.execute.side_effect = _side
        from utils.investor_brief_v2 import generate_investor_brief

        result = generate_investor_brief(pkg)
        sections = result["sections"]
        sec7 = [s for s in sections if "Market Position" in s["title"]]
        assert len(sec7) == 1
        body = sec7[0]["body"]
        assert "7,500" in body or "PSF" in body
        assert "COMPETITIVE" in body
