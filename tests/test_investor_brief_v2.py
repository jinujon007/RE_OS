"""Unit tests for InvestorBriefGenerator v2 (T-991 — Sprint 57 GATE-65)."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


def _make_pkg(peer_benchmark=None):
    from datetime import datetime, timezone
    from intelligence.registry import IntelPackage

    from unittest.mock import MagicMock

    def _make_simple(name="purchase"):
        s = MagicMock()
        s.structure = name
        s.bear_irr_pct = 14.5
        s.simple_irr_pct = 22.0
        s.verdict = "PURSUE"
        s.equity_required = 5000000
        s.gross_development_value = 45000000
        s.payback_months = 36
        return s

    _Feval = MagicMock()
    _Feval.sell_psf = 7500
    _Feval.best_structure = "JV"
    _Feval.psf_source_quality = "live_listing"
    _Feval.igr_median_psf = 4800
    _Feval.igr_record_count = 25
    _Feval.land_area_sqft = 217800
    _Feval.sellable_area_sqft = 130680
    _Feval.scenarios = "Bull: 22% | Base: 18% | Bear: 12%"
    _Feval.recommendation = "PURSUE — strong financial case"
    _Feval.purchase = _make_simple("purchase")
    _Feval.jd = _make_simple("jd")
    _Feval.jv = _make_simple("jv")

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

    pkg = IntelPackage(
        survey_no="45/2",
        market="Devanahalli",
        collected_at=datetime.now(timezone.utc).isoformat(),
        module_status={},
        deal_type="compare",
    )
    pkg.market_pulse = _Mpulse
    pkg.legal_picture = _Llegal
    pkg.land_picture = _Lpicture
    pkg.financial_evaluation = _Feval
    pkg.demand_signals = _Demand
    pkg.peer_benchmark = peer_benchmark
    pkg.all_modules_success = True
    return pkg


def _mock_pedigree_db(fetchone_tuple=(4, 3, 1500, 18.2), fetchall_list=None):
    """Set up mock_conn.execute to return fetchone for first call, fetchall for second."""
    if fetchall_list is None:
        fetchall_list = [("Yelahanka",)]
    call_idx = [0]

    def _side(*a, **kw):
        idx = call_idx[0]
        call_idx[0] += 1
        if idx == 0:
            m = MagicMock()
            m.fetchone.return_value = fetchone_tuple
            return m
        m = MagicMock()
        m.fetchall.return_value = fetchall_list
        return m

    return _side


def test_section_6_pedigree_non_empty():
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = _mock_pedigree_db()

        from utils.investor_brief_v2 import generate_investor_brief

        pkg = _make_pkg()
        result = generate_investor_brief(pkg)
        sections = result["sections"]
        sec6 = [s for s in sections if "LLS Pedigree" in s["title"]]
        assert len(sec6) == 1
        body = sec6[0]["body"]
        assert len(body) > 50
        assert "16+ years" in body or "track record" in body


def test_section_7_includes_psf_comparison():
    from intelligence.peer_benchmark import PeerBenchmarkResult

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

    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = _mock_pedigree_db()

        from utils.investor_brief_v2 import generate_investor_brief

        pkg = _make_pkg(peer_benchmark=pb)
        result = generate_investor_brief(pkg)
        sections = result["sections"]
        sec7 = [s for s in sections if "Market Position" in s["title"]]
        assert len(sec7) == 1
        body = sec7[0]["body"]
        assert "7500" in body or "PSF" in body
        assert "COMPETITIVE" in body or "positioning" in body
        assert "5 projects" in body or "5" in body


def test_lls_pedigree_db_fallback_on_error():
    """Edge case: when lls_portfolio query fails, _lls_pedigree falls back to constants."""
    with patch("utils.db.get_engine", side_effect=Exception("DB unavailable")):
        from utils.investor_brief_v2 import generate_investor_brief

        pkg = _make_pkg()
        pkg.all_modules_success = True
        result = generate_investor_brief(pkg)
        sections = result["sections"]
        sec6 = [s for s in sections if "LLS Pedigree" in s["title"]]
        assert len(sec6) == 1
        body = sec6[0]["body"]
        assert "16+ years" in body
        assert "1,800" in body or "2,160" in body or "sqft" in body


def test_all_7_sections_non_empty():
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = _mock_pedigree_db()

        from utils.investor_brief_v2 import generate_investor_brief

        pkg = _make_pkg()
        result = generate_investor_brief(pkg)
        sections = result["sections"]
        assert len(sections) == 7
        for s in sections:
            assert len(s["body"]) > 0, f"Section {s['title']} is empty"
