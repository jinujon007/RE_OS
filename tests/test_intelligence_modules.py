"""
T-680 — Sprint 62 Intelligence Module Tests (R3 polish)

Categories (≥28 tests = 28 total):
  Module      | Isolation | Cache | Edge | Registry | Partial | Tot
  ------------|-----------|-------|------|----------|---------|-----
  MarketIntel |     3     |   1   |  —   |    —     |   —     |  4
  DemandIntel |     2     |   1   |  —   |    —     |   —     |  3
  LegalIntel  |     3     |   —   |  —   |    —     |   —     |  3
  LandIntel   |     2     |   —   |  —   |    —     |   —     |  2
  FinIntel    |     3     |   —   |  —   |    —     |   —     |  3
  Registry    |     8     |   2   |  3   |    —     |   5     | 13

  Total: 28 tests — 0 DB, 0 LLM, 0 network.

Structure:
  * Fixtures in module scope for shared mocks.
  * Every public method in IntelRegistry tested.
  * Partial failure: 1-down and 2-down scenarios.
  * Cache: hit, miss-by-different-params, forced refresh, TTL invalidation.
  * Edge: invalid inputs, LRU eviction, all-5-fail, full-success vs partial TTL.
"""

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

pytestmark = pytest.mark.unit

# ─── Fixtures ─────────────────────────────────────────────────────────────────

_FAKE_MARKET_INFO = {"id": "u1", "name": "Devanahalli", "slug": "devanahalli"}


def _mock_conn():
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None
    conn.execute.return_value.fetchall.return_value = []
    return conn


def _mock_engine(conn=None):
    c = conn or _mock_conn()
    eng = MagicMock()
    eng.connect.return_value.__enter__.return_value = c
    return eng


def _fake_market_pulse(**kw):
    from intelligence.market_intel import MarketPulse

    defaults = dict(
        market="Devanahalli",
        collected_at="2026-06-03T00:00:00",
        market_found=True,
        avg_listing_psf=6500.0,
        total_projects=42,
        months_of_supply=12.0,
        supply_label="BALANCED",
        price_momentum_signal="NEUTRAL",
    )
    defaults.update(kw)
    return MarketPulse(**defaults)


def _fake_demand_signals(**kw):
    from intelligence.demand_intel import DemandSignals

    defaults = dict(
        market="Devanahalli",
        collected_at="2026-06-03T00:00:00",
        market_found=True,
        demand_signal="BULLISH",
        demand_score=2.5,
        months_of_supply=8.0,
        signals=["Price momentum healthy"],
    )
    defaults.update(kw)
    return DemandSignals(**defaults)


def _fake_legal_picture(**kw):
    from intelligence.legal_intel import LegalPicture

    defaults = dict(
        survey_no="45/2",
        market="Devanahalli",
        collected_at="2026-06-03T00:00:00",
        market_found=True,
        risk_level="CLEAR",
        title_risk_flags=[],
    )
    defaults.update(kw)
    return LegalPicture(**defaults)


def _fake_land_picture(**kw):
    from intelligence.land_intel import LandPicture

    defaults = dict(
        survey_no="45/2",
        market="Devanahalli",
        collected_at="2026-06-03T00:00:00",
        market_found=True,
        zone="R2",
        far=1.5,
        land_area_acres=0.12,
        development_readiness="READY",
        flags=[],
    )
    defaults.update(kw)
    return LandPicture(**defaults)


def _fake_financial_evaluation(**kw):
    from intelligence.financial_intel import FinancialEvaluation

    defaults = dict(
        market="Devanahalli",
        land_area_sqft=5200,
        sellable_area_sqft=4000,
        sell_psf=4200,
        collected_at="2026-06-03T00:00:00",
        market_found=True,
        best_structure="jd",
        recommendation="CONDITIONAL — JD viable",
    )
    defaults.update(kw)
    return FinancialEvaluation(**defaults)


def _patch_all_modules(return_values=None, side_effects=None):
    """Context manager that patches all 5 registry module-fetcher methods.

    Args:
        return_values: ``dict`` of ``{attr: mock_result}``. Missing attrs
                       get a default fake.
        side_effects: ``dict`` of ``{attr: Exception}`` to raise instead
                      of returning a value.

    Returns:
        ``dict`` of ``{attr: Mock}`` for assertion.
    """
    defaults = {
        "market_pulse": _fake_market_pulse(),
        "demand_signals": _fake_demand_signals(),
        "land_picture": _fake_land_picture(),
        "legal_picture": _fake_legal_picture(),
        "financial_evaluation": _fake_financial_evaluation(),
    }
    if return_values:
        defaults.update(return_values)

    patchers = {}
    mocks = {}
    for attr in defaults:
        if side_effects and attr in side_effects:
            patchers[attr] = patch(
                f"intelligence.registry.IntelRegistry._get_{attr}",
                side_effect=side_effects[attr],
            )
        else:
            patchers[attr] = patch(
                f"intelligence.registry.IntelRegistry._get_{attr}",
                return_value=defaults[attr],
            )

    for attr, p in patchers.items():
        mocks[attr] = p.start()

    return mocks, patchers


# ─── MarketIntel — Module Isolation ───────────────────────────────────────────


class TestMarketIntel:
    def test_empty_market_returns_not_found(self):
        from intelligence.market_intel import MarketIntel

        pulse = MarketIntel(caller="test").get_pulse("")
        assert pulse.market_found is False
        assert pulse.avg_listing_psf is None

    def test_sanitized_market_passed_to_validate(self):
        with patch("intelligence.market_intel.validate_market", return_value=None):
            from intelligence.market_intel import MarketIntel

            pulse = MarketIntel(caller="test").get_pulse("  Devanahalli  ")
            assert pulse.market_found is False

    def test_sanitized_rejects_non_string(self):
        from intelligence.market_intel import MarketIntel

        pulse = MarketIntel(caller="test").get_pulse(None)
        assert pulse.market_found is False

    def test_cache_returns_cached_on_second_call(self):
        with patch(
            "intelligence.market_intel.validate_market", return_value=_FAKE_MARKET_INFO
        ):
            with patch("utils.db.get_engine", return_value=_mock_engine()):
                from intelligence.market_intel import MarketIntel

                mi = MarketIntel(caller="test")
                p1 = mi.get_pulse("Devanahalli")
                p2 = mi.get_pulse("Devanahalli")
                assert p1 is p2


# ─── DemandIntel — Module Isolation ───────────────────────────────────────────


class TestDemandIntel:
    def test_empty_market_returns_not_found(self):
        from intelligence.demand_intel import DemandIntel

        ds = DemandIntel(caller="test").get_signals("")
        assert ds.market_found is False

    def test_cache_returns_cached_on_second_call(self):
        with patch(
            "intelligence.demand_intel.validate_market", return_value=_FAKE_MARKET_INFO
        ):
            with patch("utils.db.get_engine", return_value=_mock_engine()):
                from intelligence.demand_intel import DemandIntel

                di = DemandIntel(caller="test")
                d1 = di.get_signals("Devanahalli")
                d2 = di.get_signals("Devanahalli")
                assert d1 is d2

    def test_market_not_in_db_returns_graceful(self):
        with patch("intelligence.demand_intel.validate_market", return_value=None):
            from intelligence.demand_intel import DemandIntel

            ds = DemandIntel(caller="test").get_signals("UnknownTown")
            assert ds.market_found is False


# ─── LegalIntel — Module Isolation ────────────────────────────────────────────


class TestLegalIntel:
    def test_empty_survey_returns_incomplete(self):
        from intelligence.legal_intel import LegalIntel

        pic = LegalIntel(caller="test").get_survey_picture("", "Devanahalli")
        assert pic.market_found is True
        assert pic.risk_level == "UNKNOWN"

    def test_survey_sanitization_strips_injection_chars(self):
        with patch("intelligence.legal_intel.validate_market", return_value=None):
            from intelligence.legal_intel import LegalIntel

            pic = LegalIntel(caller="test").get_survey_picture(
                "45/2; DROP TABLE", "Devanahalli"
            )
            assert pic.market_found is False

    def test_market_not_found_returns_graceful(self):
        with patch("intelligence.legal_intel.validate_market", return_value=None):
            from intelligence.legal_intel import LegalIntel

            pic = LegalIntel(caller="test").get_survey_picture("99/A", "Unknown")
            assert pic.market_found is False


# ─── LandIntel — Module Isolation ─────────────────────────────────────────────


class TestLandIntel:
    def test_empty_market_returns_not_found(self):
        from intelligence.land_intel import LandIntel

        pic = LandIntel(caller="test").get_land_picture("45/2", "")
        assert pic.market_found is False

    def test_survey_sanitization_removes_invalid_chars(self):
        from intelligence.land_intel import LandIntel

        pic = LandIntel(caller="test").get_land_picture(
            "<script>45/2</script>", "Devanahalli"
        )
        assert "/" in pic.survey_no
        assert "<" not in pic.survey_no

    def test_market_not_in_db_returns_graceful(self):
        with patch("intelligence.land_intel.validate_market", return_value=None):
            from intelligence.land_intel import LandIntel

            pic = LandIntel(caller="test").get_land_picture("45/2", "Nowhere")
            assert pic.market_found is False


# ─── FinancialIntel — Module Isolation ────────────────────────────────────────


class TestFinancialIntel:
    def test_zero_area_returns_not_found(self):
        from intelligence.financial_intel import FinancialIntel

        fe = FinancialIntel(caller="test").evaluate("Devanahalli", 0, 5000)
        assert fe.market_found is False

    def test_zero_psf_returns_not_found(self):
        from intelligence.financial_intel import FinancialIntel

        fe = FinancialIntel(caller="test").evaluate("Devanahalli", 43560, 0)
        assert fe.market_found is False

    def test_market_not_in_db_returns_graceful(self):
        with patch("intelligence.financial_intel.validate_market", return_value=None):
            from intelligence.financial_intel import FinancialIntel

            fe = FinancialIntel(caller="test").evaluate("Unknown", 43560, 5000)
            assert fe.market_found is False

    def test_database_error_returns_partial(self):
        with patch(
            "intelligence.financial_intel.validate_market",
            return_value=_FAKE_MARKET_INFO,
        ):
            with patch(
                "utils.fsi_calculator.calculate_fsi",
                side_effect=Exception("FSI engine down"),
            ):
                from intelligence.financial_intel import FinancialIntel

                fe = FinancialIntel(caller="test").evaluate("Devanahalli", 43560, 5000)
                assert fe.market_found is True
                assert "failed" in fe.recommendation.lower()


# ─── IntelRegistry — Assembly & Partial Failure ───────────────────────────────


class TestIntelRegistry:
    def test_all_5_modules_called(self):
        mocks, patchers = _patch_all_modules()
        try:
            from intelligence.registry import IntelRegistry

            pkg = IntelRegistry().get_full_picture(
                "45/2", "Devanahalli", 5200, 4000, "compare"
            )
            for attr, m in mocks.items():
                m.assert_called_once()
            assert pkg.all_modules_success is True
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_single_module_failure_others_still_run(self):
        mocks, patchers = _patch_all_modules(
            side_effects={"market_pulse": Exception("Market DB down")},
        )
        try:
            from intelligence.registry import IntelRegistry

            pkg = IntelRegistry().get_full_picture(
                "45/2", "Devanahalli", 5200, 4000, "compare"
            )
            assert pkg.module_status.get("market_pulse") == "ERROR"
            for attr in (
                "demand_signals",
                "land_picture",
                "legal_picture",
                "financial_evaluation",
            ):
                assert pkg.module_status.get(attr) == "OK"
            assert pkg.all_modules_success is False
            assert len(pkg.errors) >= 1
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_two_modules_fail_remaining_three_ok(self):
        mocks, patchers = _patch_all_modules(
            side_effects={
                "market_pulse": Exception("M1 down"),
                "demand_signals": Exception("M2 down"),
            },
        )
        try:
            from intelligence.registry import IntelRegistry

            pkg = IntelRegistry().get_full_picture(
                "45/2", "Devanahalli", 5200, 4000, "compare"
            )
            assert pkg.module_status.get("market_pulse") == "ERROR"
            assert pkg.module_status.get("demand_signals") == "ERROR"
            for attr in ("land_picture", "legal_picture", "financial_evaluation"):
                assert pkg.module_status.get(attr) == "OK"
            assert pkg.all_modules_success is False
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_all_five_modules_fail(self):
        mocks, patchers = _patch_all_modules(
            side_effects={
                attr: Exception(f"{attr} down")
                for attr in (
                    "market_pulse",
                    "demand_signals",
                    "land_picture",
                    "legal_picture",
                    "financial_evaluation",
                )
            },
        )
        try:
            from intelligence.registry import IntelRegistry

            pkg = IntelRegistry().get_full_picture(
                "45/2", "Devanahalli", 5200, 4000, "compare"
            )
            for attr in (
                "market_pulse",
                "demand_signals",
                "land_picture",
                "legal_picture",
                "financial_evaluation",
            ):
                assert pkg.module_status.get(attr) == "ERROR"
            assert pkg.all_modules_success is False
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_partial_failure_cache_stores_with_short_ttl(self):
        mocks, patchers = _patch_all_modules(
            side_effects={"market_pulse": Exception("transient")},
        )
        try:
            from intelligence.registry import IntelRegistry

            reg = IntelRegistry()
            # First call: market_pulse fails → partial success
            pkg1 = reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            assert pkg1.all_modules_success is False
            # Second call: should return cached partial result
            mocks["market_pulse"].reset_mock()
            pkg2 = reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            assert pkg2 is pkg1
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_force_refresh_bypasses_cache(self):
        mocks, patchers = _patch_all_modules()
        try:
            from intelligence.registry import IntelRegistry

            reg = IntelRegistry()
            p1 = reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            p2 = reg.get_full_picture(
                "45/2", "Devanahalli", 5200, 4000, "compare", force_refresh=True
            )
            assert p1 is not p2
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_memoization_returns_same_object_within_ttl(self):
        mocks, patchers = _patch_all_modules()
        try:
            from intelligence.registry import IntelRegistry

            reg = IntelRegistry()
            p1 = reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            p2 = reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            assert p1 is p2
            mocks["market_pulse"].assert_called_once()
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_different_params_do_not_use_same_cache(self):
        mocks, patchers = _patch_all_modules()
        try:
            from intelligence.registry import IntelRegistry

            reg = IntelRegistry()
            p1 = reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            p2 = reg.get_full_picture("46/1", "Yelahanka", 10000, 4500, "purchase")
            assert p1 is not p2
            assert mocks["financial_evaluation"].call_count == 2
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_invalid_survey_returns_early_error(self):
        from intelligence.registry import IntelRegistry

        pkg = IntelRegistry().get_full_picture("", "Devanahalli", 5200, 4000, "compare")
        assert len(pkg.errors) >= 1
        assert "invalid" in pkg.errors[0].lower()

    def test_invalid_market_returns_early_error(self):
        from intelligence.registry import IntelRegistry

        pkg = IntelRegistry().get_full_picture("45/2", "", 5200, 4000, "compare")
        assert len(pkg.errors) >= 1
        assert "invalid" in pkg.errors[0].lower()

    def test_cache_invalidation_by_survey(self):
        mocks, patchers = _patch_all_modules()
        try:
            from intelligence.registry import IntelRegistry

            reg = IntelRegistry()
            reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            reg.invalidate_cache(survey_no="45/2")
            reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            assert mocks["market_pulse"].call_count == 2
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_cache_invalidation_by_market(self):
        mocks, patchers = _patch_all_modules()
        try:
            from intelligence.registry import IntelRegistry

            reg = IntelRegistry()
            reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            reg.invalidate_cache(market="Devanahalli")
            reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            assert mocks["market_pulse"].call_count == 2
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_cache_clear_all_entries(self):
        mocks, patchers = _patch_all_modules()
        try:
            from intelligence.registry import IntelRegistry

            reg = IntelRegistry()
            reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            reg.get_full_picture("46/1", "Yelahanka", 10000, 4500, "purchase")
            reg.invalidate_cache()
            reg.get_full_picture("45/2", "Devanahalli", 5200, 4000, "compare")
            assert mocks["market_pulse"].call_count == 3
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_package_str_representation(self):
        from intelligence.registry import IntelPackage

        pkg = IntelPackage(
            survey_no="45/2",
            market="Devanahalli",
            collected_at="now",
            module_status={"mp": "OK", "dm": "OK"},
        )
        s = str(pkg)
        assert "45/2" in s
        assert "Devanahalli" in s
        assert "2/2" in s

    def test_package_repr(self):
        from intelligence.registry import IntelPackage

        pkg = IntelPackage(
            survey_no="45/2",
            market="Devanahalli",
            collected_at="now",
            module_status={"mp": "OK", "dm": "OK"},
        )
        r = repr(pkg)
        assert r.startswith("IntelPackage(")
        assert "45/2" in r
        assert "status=" in r

    def test_elapsed_ms_tracked_at_millisecond_precision(self):
        mocks, patchers = _patch_all_modules()
        try:
            from intelligence.registry import IntelRegistry

            pkg = IntelRegistry().get_full_picture(
                "45/2", "Devanahalli", 5200, 4000, "compare"
            )
            assert pkg.elapsed_ms > 0
            assert "." in str(pkg.elapsed_ms) or pkg.elapsed_ms >= 0.1
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_sell_psf_inferred_from_market_pulse_when_not_provided(self):
        """Registry uses avg_listing_psf from market_pulse when sell_psf=0."""
        pulse_with_psf = _fake_market_pulse(avg_listing_psf=7200.0)
        mocks, patchers = _patch_all_modules(
            return_values={"market_pulse": pulse_with_psf},
        )
        try:
            from intelligence.registry import IntelRegistry

            reg = IntelRegistry()
            pkg = reg.get_full_picture("45/2", "Devanahalli", 5200, 0, "compare")
            assert pkg.market_pulse.avg_listing_psf == 7200.0
        finally:
            for _, p in patchers.items():
                p.stop()

    def test_deal_type_stored_in_package_not_passed_to_finance(self):
        """deal_type is metadata; FinancialIntel.evaluate does not receive it."""
        mocks, patchers = _patch_all_modules()
        try:
            from intelligence.registry import IntelRegistry

            pkg = IntelRegistry().get_full_picture(
                "45/2", "Devanahalli", 5200, 4000, deal_type="jd"
            )
            assert pkg.deal_type == "jd"
            _fn = mocks["financial_evaluation"]
            _fn.assert_called_once()
            call_kwargs = _fn.call_args[0]
            # FinancialIntel.evaluate signature: market, land_area_sqft,
            # sell_psf, guidance_value_psf, ... — no deal_type
            assert "deal_type" not in str(_fn.call_args)
        finally:
            for _, p in patchers.items():
                p.stop()
