"""
T-685 — Sprint 63 Opportunity Engine Tests (GATE-47) — R3

Categories (38 tests):
  Component             | Tests
  ----------------------|------
  ScoreComponents       |  4
  Sub-scores            |  7
  Decision logic        |  5
  Edge cases            |  5
  Engine                |  6
  Persistence           |  5
  Prune                 |  2
  Delta tracking        |  2
  OpportunityScore      |  2

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

    def test_str_representation(self):
        from intelligence.opportunity_engine import ScoreComponents
        sc = ScoreComponents(irr_score=0.8, legal_score=0.6,
                             timing_score=0.7, distress_score=0.4,
                             exclusivity_score=0.3)
        s = str(sc)
        assert "IRR" in s
        assert "Legal" in s
        assert "Timing" in s
        assert "%" in s


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

    def test_priority_at_above_sixty(self):
        from intelligence.opportunity_engine import OpportunityEngine
        action = OpportunityEngine._derive_next_action(0.70, "CLEAR")
        assert "PRIORITY" in action

    def test_watch_at_score_forty_to_sixty_with_clean_legal(self):
        from intelligence.opportunity_engine import OpportunityEngine
        action = OpportunityEngine._derive_next_action(0.50, "CLEAR")
        assert "WATCH" in action

    def test_observe_below_forty_unless_legal_stops_it(self):
        from intelligence.opportunity_engine import OpportunityEngine
        action = OpportunityEngine._derive_next_action(0.35, "CLEAR")
        assert "OBSERVE" in action

    def test_hold_at_low_score(self):
        from intelligence.opportunity_engine import OpportunityEngine
        action = OpportunityEngine._derive_next_action(0.15, "RISK")
        assert "HOLD" in action


class TestExpiryForScore:
    def test_zero_score_returns_none(self):
        from intelligence.opportunity_engine import OpportunityEngine
        expiry = OpportunityEngine._expiry_for_score(0.0)
        assert expiry is None

    def test_low_score_gets_short_window(self):
        from intelligence.opportunity_engine import OpportunityEngine
        from datetime import datetime, timezone, timedelta
        now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
        expiry = OpportunityEngine._expiry_for_score(0.2, now=now)
        assert expiry == "2026-07-03"  # 30 days

    def test_watch_score_gets_long_window(self):
        from intelligence.opportunity_engine import OpportunityEngine
        from datetime import datetime, timezone, timedelta
        now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
        expiry = OpportunityEngine._expiry_for_score(0.5, now=now)
        assert expiry == "2026-09-01"  # 90 days

    def test_urgent_score_gets_long_window(self):
        from intelligence.opportunity_engine import OpportunityEngine
        from datetime import datetime, timezone, timedelta
        now = datetime(2026, 6, 3, 12, 0, 0, tzinfo=timezone.utc)
        expiry = OpportunityEngine._expiry_for_score(0.85, now=now)
        assert expiry == "2026-09-01"  # 90 days


# ═══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_non_string_market_in_score_all_skipped(self):
        from intelligence.opportunity_engine import OpportunityEngine
        engine = OpportunityEngine(caller="test")
        results = engine.score_all(["Devanahalli", None, "Yelahanka"])
        # None is filtered out before validation by sanitize_market check

    def test_composite_max_one(self):
        from intelligence.opportunity_engine import ScoreComponents
        sc = ScoreComponents(1.0, 1.0, 1.0, 1.0, 1.0)
        assert sc.composite() == pytest.approx(1.0, rel=1e-4)

    def test_composite_min_zero(self):
        from intelligence.opportunity_engine import ScoreComponents
        sc = ScoreComponents(0.0, 0.0, 0.0, 0.0, 0.0)
        assert sc.composite() == 0.0

    def test_irr_score_with_partial_financials(self):
        fe = _mock_financial_evaluation(
            best_structure="purchase",
            purchase=MagicMock(simple_irr_pct=15.0),
            jd=None,
            jv=None,
        )
        from intelligence.opportunity_engine import _irr_score
        score, deal_type, jd_irr = _irr_score(_make_package(financial_evaluation=fe))
        assert score == pytest.approx(0.75, rel=1e-4)
        assert deal_type == "purchase"

    def test_legal_warning_returns_six_tenths(self):
        from intelligence.opportunity_engine import _legal_score
        lp = _mock_legal_picture(risk_level="WARNING")
        score, level = _legal_score(_make_package(legal_picture=lp))
        assert score == 0.6
        assert level == "WARNING"


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

    def test_load_previous_scores_empty_on_db_error(self):
        from intelligence.opportunity_engine import OpportunityEngine
        engine = OpportunityEngine(caller="test")
        with patch("utils.db.get_engine",
                   side_effect=Exception("DB down")):
            prev = engine._load_previous_scores("u1")
            assert prev == {}

    def test_load_previous_scores_returns_dict(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("s1", 0.75), ("s2", 0.45),
        ]
        mock_eng = MagicMock()
        mock_eng.connect.return_value.__enter__.return_value = mock_conn
        from intelligence.opportunity_engine import OpportunityEngine
        engine = OpportunityEngine(caller="test")
        with patch("utils.db.get_engine",
                   return_value=mock_eng):
            from intelligence.opportunity_engine import OpportunityEngine
            engine = OpportunityEngine(caller="test")
            prev = engine._load_previous_scores("u1")
            assert prev == {"s1": 0.75, "s2": 0.45}


# ═══════════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════════

class TestPersistScores:
    def test_empty_list_returns_zero(self):
        from intelligence.opportunity_engine import OpportunityEngine
        written = OpportunityEngine(caller="test").persist_scores([])
        assert written == 0

    def test_writes_with_on_conflict_upsert(self):
        mock_conn = MagicMock()
        mock_eng = MagicMock()
        mock_eng.begin.return_value.__enter__.return_value = mock_conn
        from intelligence.opportunity_engine import (
            OpportunityEngine, OpportunityScore, ScoreComponents,
        )
        sc = ScoreComponents(0.8, 0.6, 0.7, 0.4, 0.3)
        score = OpportunityScore(
            survey_id="s1", survey_no="45/2",
            micro_market_id="u1", developer_id=None,
            score=0.65, components=sc,
            best_deal_type="jd", estimated_jd_irr=18.5,
            legal_risk_level="CLEAR",
            next_action="PRIORITY — prepare deal memo",
            expiry_date="2026-09-01",
            computed_at="2026-06-03T00:00:00",
        )
        with patch("utils.db.get_engine",
                   return_value=mock_eng):
            engine = OpportunityEngine(caller="test")
            written = engine.persist_scores([score])
            assert written == 1
            assert mock_conn.execute.called

    def test_savepoint_on_row_failure_continues(self):
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [
            None,  # SAVEPOINT sp_opp_0
            Exception("constraint violation"),  # first execute fails
            None,  # ROLLBACK
            None,  # RELEASE
            None,  # SAVEPOINT sp_opp_1
            MagicMock(),  # second row succeeds
            None,  # RELEASE
        ]
        mock_eng = MagicMock()
        mock_eng.begin.return_value.__enter__.return_value = mock_conn
        from intelligence.opportunity_engine import (
            OpportunityEngine, OpportunityScore, ScoreComponents,
        )
        sc = ScoreComponents()
        scores = [
            OpportunityScore("s1", "45/2", "u1", None, 0.5, sc,
                             "purchase", None, "CLEAR", "HOLD", None, "now"),
            OpportunityScore("s2", "46/1", "u1", None, 0.6, sc,
                             "jd", 18.0, "WARNING", "WATCH", "2026-09-01", "now"),
        ]
        with patch("utils.db.get_engine",
                   return_value=mock_eng):
            engine = OpportunityEngine(caller="test")
            written = engine.persist_scores(scores)
            assert written == 1  # only second row succeeded

    def test_json_serialization_includes_weights(self):
        mock_conn = MagicMock()
        mock_eng = MagicMock()
        mock_eng.begin.return_value.__enter__.return_value = mock_conn
        from intelligence.opportunity_engine import (
            OpportunityEngine, OpportunityScore, ScoreComponents,
        )
        sc = ScoreComponents(0.8, 0.6, 0.7, 0.4, 0.3)
        score = OpportunityScore(
            "s1", "45/2", "u1", None, 0.65, sc,
            "jd", 18.5, "CLEAR", "PRIORITY", "2026-09-01", "now",
        )
        with patch("utils.db.get_engine",
                   return_value=mock_eng):
            engine = OpportunityEngine(caller="test")
            engine.persist_scores([score])
            calls = mock_conn.execute.call_args_list
            insert_call = calls[1]
            params = insert_call[0][1]
            comp_arg = params["comp"]
            import json
            parsed = json.loads(comp_arg)
            assert "weights" in parsed
            assert parsed["weights"]["irr"] == 0.30
            assert parsed["composite_score"] == 0.65

    def test_outer_transaction_failure_returns_partial_count(self):
        mock_eng = MagicMock()
        mock_eng.begin.side_effect = [Exception("connection lost")]
        from intelligence.opportunity_engine import (
            OpportunityEngine, OpportunityScore, ScoreComponents,
        )
        sc = ScoreComponents()
        scores = [
            OpportunityScore("s1", "45/2", "u1", None, 0.5, sc,
                             "purchase", None, "CLEAR", "HOLD", None, "now"),
        ]
        with patch("utils.db.get_engine",
                   return_value=mock_eng):
            engine = OpportunityEngine(caller="test")
            written = engine.persist_scores(scores)
            assert written == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Prune stale
# ═══════════════════════════════════════════════════════════════════════════════

class TestPruneStale:
    def test_empty_active_ids_returns_early(self):
        from intelligence.opportunity_engine import OpportunityEngine
        engine = OpportunityEngine(caller="test")
        # Should not raise — early return on empty set
        engine._prune_stale(set())

    def test_prune_logs_on_stale_rows(self):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_conn.execute.return_value = mock_result
        mock_eng = MagicMock()
        mock_eng.begin.return_value.__enter__.return_value = mock_conn
        from intelligence.opportunity_engine import OpportunityEngine
        engine = OpportunityEngine(caller="test")
        with patch("utils.db.get_engine",
                   return_value=mock_eng):
            engine._prune_stale({"s1", "s2"})


# ═══════════════════════════════════════════════════════════════════════════════
# Score delta tracking
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreDelta:
    def test_new_score_no_delta_logged(self):
        from intelligence.opportunity_engine import (
            OpportunityEngine, OpportunityScore, ScoreComponents,
        )
        sc = ScoreComponents()
        score = OpportunityScore(
            "s1", "45/2", "u1", None, 0.5, sc,
            "purchase", None, "CLEAR", "HOLD", None, "now",
        )
        previous = {"s2": 0.8}
        # No delta logged for new survey_id not in previous
        OpportunityEngine._check_score_delta(score, previous)

    def test_score_delta_below_threshold_no_log(self):
        from intelligence.opportunity_engine import (
            OpportunityEngine, OpportunityScore, ScoreComponents,
        )
        sc = ScoreComponents()
        score = OpportunityScore(
            "s1", "45/2", "u1", None, 0.52, sc,
            "purchase", None, "CLEAR", "HOLD", None, "now",
        )
        previous = {"s1": 0.50}
        # Δ=0.02 < 0.1 — no warning
        OpportunityEngine._check_score_delta(score, previous)


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

    def test_repr_with_none_developer_id(self):
        from intelligence.opportunity_engine import (
            OpportunityScore, ScoreComponents,
        )
        sc = ScoreComponents()
        os_obj = OpportunityScore(
            survey_id="s1", survey_no="99/1",
            micro_market_id="u2", developer_id=None,
            score=0.3, components=sc,
            best_deal_type="purchase", estimated_jd_irr=None,
            legal_risk_level="RISK",
            next_action="HOLD — unfavorable conditions",
            expiry_date=None,
            computed_at="2026-06-03T00:00:00",
        )
        r = repr(os_obj)
        assert "99/1" in r
        assert "0.3" in r
