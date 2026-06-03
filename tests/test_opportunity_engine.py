"""
T-685 — Sprint 63 Opportunity Engine Tests (GATE-47)

Categories (18 tests):
  Component        | Tests
  -----------------|------
  ScoreComponents  |  3
  Sub-scores       |  7
  Decision logic   |  2
  Engine           |  4
  Persistence      |  2

Structure: 0 DB, 0 LLM, 0 network. All pure logic or fully mocked.
"""
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

pytestmark = pytest.mark.unit


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _mock_financial_evaluation(**kw):
    from intelligence.financial_intel import FinancialEvaluation
    defaults = dict(market="Devanahalli", land_area_sqft=5200,
                    sellable_area_sqft=4000, sell_psf=4200,
                    collected_at="2026-06-03T00:00:00", market_found=True,
                    best_structure="jd",
                    recommendation="CONDITIONAL — JD viable")
    defaults.update(kw)
    return FinancialEvaluation(**defaults)


def _mock_market_pulse(**kw):
    from intelligence.market_intel import MarketPulse
    defaults = dict(market="Devanahalli", collected_at="2026-06-03T00:00:00",
                    market_found=True, avg_listing_psf=6500.0, total_projects=42,
                    months_of_supply=12.0, supply_label="BALANCED",
                    price_momentum_signal="NEUTRAL")
    defaults.update(kw)
    return MarketPulse(**defaults)


def _mock_legal_picture(**kw):
    from intelligence.legal_intel import LegalPicture
    defaults = dict(survey_no="45/2", market="Devanahalli",
                    collected_at="2026-06-03T00:00:00", market_found=True,
                    risk_level="CLEAR", title_risk_flags=[])
    defaults.update(kw)
    return LegalPicture(**defaults)


def _mock_land_picture(**kw):
    from intelligence.land_intel import LandPicture
    defaults = dict(survey_no="45/2", market="Devanahalli",
                    collected_at="2026-06-03T00:00:00", market_found=True,
                    zone="R2", far=1.5, land_area_acres=0.12,
                    development_readiness="READY", flags=[])
    defaults.update(kw)
    return LandPicture(**defaults)


def _make_package(**kw):
    from intelligence.registry import IntelPackage
    defaults = dict(survey_no="45/2", market="Devanahalli",
                    collected_at="2026-06-03T00:00:00",
                    module_status={})
    defaults.update(kw)
    return IntelPackage(**defaults)


# ═══════════════════════════════════════════════════════════════════════════════
# ScoreComponents
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreComponents:
    def test_default_init_all_zero(self):
        from intelligence.opportunity_engine import ScoreComponents
        sc = ScoreComponents()
        assert sc.irr_score == 0.0
        assert sc.legal_score == 0.0
        assert sc.timing_score == 0.0
        assert sc.distress_score == 0.0
        assert sc.exclusivity_score == 0.0
        assert sc.composite() == 0.0

    def test_clamps_out_of_range_values(self):
        from intelligence.opportunity_engine import ScoreComponents
        sc = ScoreComponents(irr_score=2.5, legal_score=-0.5)
        assert sc.irr_score == 1.0
        assert sc.legal_score == 0.0

    def test_composite_weighted_calculation(self):
        from intelligence.opportunity_engine import ScoreComponents
        sc = ScoreComponents(irr_score=0.8, legal_score=0.9,
                             timing_score=0.7, distress_score=0.5,
                             exclusivity_score=0.6)
        c = sc.composite()
        expected = 0.8*0.30 + 0.9*0.20 + 0.7*0.20 + 0.5*0.15 + 0.6*0.15
        assert c == pytest.approx(expected, rel=1e-4)
        assert sc._composite == c


# ═══════════════════════════════════════════════════════════════════════════════
# Sub-score functions
# ═══════════════════════════════════════════════════════════════════════════════

class TestIrScore:
    def test_full_score_at_20pct_go_threshold(self):
        fe = _mock_financial_evaluation(
            best_structure="jd",
            jd=MagicMock(simple_irr_pct=25.0),
            purchase=MagicMock(simple_irr_pct=10.0),
        )
        from intelligence.opportunity_engine import _irr_score
        score, deal_type, jd_irr = _irr_score(_make_package(financial_evaluation=fe))
        assert score == pytest.approx(1.0, rel=1e-4)
        assert deal_type == "jd"

    def test_zero_when_no_financial_evaluation(self):
        from intelligence.opportunity_engine import _irr_score
        score, deal_type, jd_irr = _irr_score(_make_package())
        assert score == 0.0
        assert deal_type == "purchase"
        assert jd_irr is None


class TestLegalScore:
    def test_clear_level_returns_one(self):
        from intelligence.opportunity_engine import _legal_score
        lp = _mock_legal_picture(risk_level="CLEAR")
        score, level = _legal_score(_make_package(legal_picture=lp))
        assert score == 1.0
        assert level == "CLEAR"

    def test_risk_level_returns_point_two(self):
        from intelligence.opportunity_engine import _legal_score
        lp = _mock_legal_picture(risk_level="RISK")
        score, level = _legal_score(_make_package(legal_picture=lp))
        assert score == 0.2
        assert level == "RISK"

    def test_no_legal_picture_returns_unknown_zero(self):
        from intelligence.opportunity_engine import _legal_score
        score, level = _legal_score(_make_package(legal_picture=None))
        assert score == 0.0
        assert level == "UNKNOWN"


class TestTimingScore:
    def test_low_supply_returns_one(self):
        from intelligence.opportunity_engine import _timing_score
        mp = _mock_market_pulse(months_of_supply=6.0)
        score = _timing_score(_make_package(market_pulse=mp))
        assert score == 1.0

    def test_high_supply_returns_zero_point_one(self):
        from intelligence.opportunity_engine import _timing_score
        mp = _mock_market_pulse(months_of_supply=48.0)
        score = _timing_score(_make_package(market_pulse=mp))
        assert score == 0.1

    def test_no_market_pulse_returns_neutral(self):
        from intelligence.opportunity_engine import _timing_score
        score = _timing_score(_make_package(market_pulse=None))
        assert score == 0.5


class TestDistressScore:
    def test_constrained_readiness_returns_one(self):
        from intelligence.opportunity_engine import _distress_score
        lp = _mock_land_picture(development_readiness="CONSTRAINED")
        score = _distress_score(_make_package(land_picture=lp))
        assert score == 1.0

    def test_no_land_picture_returns_low(self):
        from intelligence.opportunity_engine import _distress_score
        score = _distress_score(_make_package(land_picture=None))
        assert score == 0.1


class TestExclusivityScore:
    def test_single_survey_returns_one(self):
        from intelligence.opportunity_engine import _exclusivity_score
        score = _exclusivity_score(_make_package(), total_surveys_in_market=1)
        assert score == 1.0

    def test_many_surveys_returns_low(self):
        from intelligence.opportunity_engine import _exclusivity_score
        score = _exclusivity_score(_make_package(), total_surveys_in_market=15)
        assert score == 0.2


# ═══════════════════════════════════════════════════════════════════════════════
# Decision logic
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeriveNextAction:
    def test_urgent_at_high_score(self):
        from intelligence.opportunity_engine import OpportunityEngine
        action = OpportunityEngine._derive_next_action(0.85, "CLEAR")
        assert "URGENT" in action

    def test_hold_at_low_score(self):
        from intelligence.opportunity_engine import OpportunityEngine
        action = OpportunityEngine._derive_next_action(0.15, "RISK")
        assert "HOLD" in action


# ═══════════════════════════════════════════════════════════════════════════════
# Engine
# ═══════════════════════════════════════════════════════════════════════════════

class TestOpportunityEngine:
    def test_empty_markets_list_returns_empty(self):
        from intelligence.opportunity_engine import OpportunityEngine
        engine = OpportunityEngine(caller="test")
        results = engine.score_all([])
        assert results == []

    def test_invalid_market_name_returns_empty(self):
        with patch("intelligence.opportunity_engine.sanitize_market",
                   return_value=""):
            from intelligence.opportunity_engine import OpportunityEngine
            engine = OpportunityEngine(caller="test")
            results = engine.score_all(["  "])
            assert results == []

    def test_market_not_in_db_skips(self):
        with patch("intelligence.opportunity_engine.validate_market",
                   return_value=None):
            from intelligence.opportunity_engine import OpportunityEngine
            engine = OpportunityEngine(caller="test")
            results = engine.score_all(["Unknown"])
            assert results == []

    def test_database_error_on_load_surveys_skips_market(self):
        from intelligence.opportunity_engine import OpportunityEngine
        with patch("intelligence.opportunity_engine.validate_market",
                   return_value={"id": "u1", "name": "Devanahalli"}):
            with patch.object(OpportunityEngine, "_load_surveys",
                              side_effect=Exception("DB timeout")):
                engine = OpportunityEngine(caller="test")
                results = engine.score_all(["Devanahalli"])
                assert results == []

    def test_persist_scores_empty_returns_zero(self):
        from intelligence.opportunity_engine import OpportunityEngine
        written = OpportunityEngine(caller="test").persist_scores([])
        assert written == 0


# ═══════════════════════════════════════════════════════════════════════════════
# OpportunityScore dataclass
# ═══════════════════════════════════════════════════════════════════════════════

class TestOpportunityScore:
    def test_repr_contains_key_fields(self):
        from intelligence.opportunity_engine import (
            OpportunityScore, ScoreComponents,
        )
        sc = ScoreComponents()
        os_obj = OpportunityScore(
            survey_id="s1", survey_no="45/2",
            micro_market_id="u1", developer_id=None,
            score=0.75, components=sc,
            best_deal_type="jd", estimated_jd_irr=18.5,
            legal_risk_level="CLEAR",
            next_action="URGENT — initiate DD",
            expiry_date="2026-09-01",
            computed_at="2026-06-03T00:00:00",
        )
        r = repr(os_obj)
        assert "45/2" in r
        assert "0.75" in r
        assert "URGENT" in r
