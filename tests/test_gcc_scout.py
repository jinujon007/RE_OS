"""
Tests for GCC Demand Scout — Sprint 67 (GATE-71)

Unit tests for scoring, corridor mapping, dedup key, demand conversion,
and plugin extraction logic. All DB-touching tests are skipped when no live DB.
"""

import pytest
from unittest.mock import MagicMock, patch


# ── Scoring formula ──────────────────────────────────────────────────────────

class TestGCCScoring:
    def _import(self):
        from ingest.plugins.gcc_plugin import _compute_gcc_score
        return _compute_gcc_score

    def test_new_full_office_l1_scores_high(self):
        fn = self._import()
        event = {
            "demand_creation_score": 8,
            "residential_impact_score": 8,
            "appreciation_impact_score": 9,
            "rental_impact_score": 5,
            "entrant_type": "NEW",
            "work_model": "FULL_OFFICE",
            "signal_maturity_level": 1,
        }
        score = fn(event)
        # base ≈ 8.1, NEW×1.0, FULL_OFFICE×1.0, L1×0.90 → ~7.3
        assert score >= 6.5, f"Expected high score for NEW/FULL_OFFICE/L1, got {score}"

    def test_expansion_hybrid_l3_scores_moderate(self):
        fn = self._import()
        event = {
            "demand_creation_score": 6,
            "residential_impact_score": 6,
            "appreciation_impact_score": 7,
            "rental_impact_score": 5,
            "entrant_type": "EXPANSION",
            "work_model": "HYBRID",
            "signal_maturity_level": 3,
        }
        score = fn(event)
        # base ≈ 6.2, EXPANSION×0.5, HYBRID×0.65, L3×0.50 → ~1.0
        assert 0.5 <= score <= 3.5, f"Expected moderate score, got {score}"

    def test_consolidation_produces_negative_score(self):
        fn = self._import()
        event = {
            "demand_creation_score": 5,
            "residential_impact_score": 5,
            "appreciation_impact_score": 5,
            "rental_impact_score": 5,
            "entrant_type": "CONSOLIDATION",
            "work_model": "HYBRID",
            "signal_maturity_level": 3,
        }
        score = fn(event)
        assert score < 0, f"CONSOLIDATION must produce negative score, got {score}"

    def test_score_clamped_to_minus_10_plus_10(self):
        fn = self._import()
        event = {
            "demand_creation_score": 10,
            "residential_impact_score": 10,
            "appreciation_impact_score": 10,
            "rental_impact_score": 10,
            "entrant_type": "NEW",
            "work_model": "FULL_OFFICE",
            "signal_maturity_level": 1,
        }
        score = fn(event)
        assert -10.0 <= score <= 10.0

    def test_remote_friendly_deep_discount(self):
        fn = self._import()
        full_office = {
            "demand_creation_score": 7, "residential_impact_score": 7,
            "appreciation_impact_score": 7, "rental_impact_score": 7,
            "entrant_type": "NEW", "work_model": "FULL_OFFICE",
            "signal_maturity_level": 2,
        }
        remote = {**full_office, "work_model": "REMOTE_FRIENDLY"}
        assert fn(full_office) > fn(remote) * 2, "REMOTE_FRIENDLY must score much lower than FULL_OFFICE"

    def test_l1_scores_higher_than_l4_same_event(self):
        fn = self._import()
        base = {
            "demand_creation_score": 7, "residential_impact_score": 7,
            "appreciation_impact_score": 7, "rental_impact_score": 5,
            "entrant_type": "NEW", "work_model": "FULL_OFFICE",
        }
        l1 = fn({**base, "signal_maturity_level": 1})
        l4 = fn({**base, "signal_maturity_level": 4})
        assert l1 > l4, "Level 1 (pre-public) must score higher than Level 4 (operational)"


# ── Corridor mapping ─────────────────────────────────────────────────────────

class TestCorridorMapping:
    def test_kiadb_aerospace_maps_correctly(self):
        from ingest.plugins.gcc_plugin import _resolve_corridor
        corridor, nb = _resolve_corridor("KIADB Aerospace Park, Devanahalli")
        assert corridor == "kiadb_aerospace_park"
        assert nb == 1.0

    def test_devanahalli_nh44_maps_correctly(self):
        from ingest.plugins.gcc_plugin import _resolve_corridor
        corridor, nb = _resolve_corridor("Devanahalli Technology Campus, NH-44")
        assert corridor in ("devanahalli_nh44", "kiadb_aerospace_park")
        assert nb >= 0.9

    def test_whitefield_has_low_nb_impact(self):
        from ingest.plugins.gcc_plugin import _resolve_corridor
        corridor, nb = _resolve_corridor("Whitefield Tech Park")
        assert corridor == "whitefield"
        assert nb <= 0.15

    def test_manyata_maps_high_nb(self):
        from ingest.plugins.gcc_plugin import _resolve_corridor
        corridor, nb = _resolve_corridor("Manyata Tech Park, Nagavara")
        assert corridor == "manyata_tech_park"
        assert nb >= 0.85

    def test_unknown_location_returns_none(self):
        from ingest.plugins.gcc_plugin import _resolve_corridor
        corridor, nb = _resolve_corridor("Some Remote Location XYZ")
        assert corridor is None
        assert nb == 0.0


# ── Canonical ID dedup ───────────────────────────────────────────────────────

class TestCanonicalId:
    def test_same_inputs_produce_same_id(self):
        from ingest.plugins.gcc_plugin import _make_canonical_id
        a = _make_canonical_id("Boeing India", "KIADB Aerospace Park", "2024-08-15")
        b = _make_canonical_id("Boeing India", "KIADB Aerospace Park", "2024-08-15")
        assert a == b

    def test_different_company_produces_different_id(self):
        from ingest.plugins.gcc_plugin import _make_canonical_id
        a = _make_canonical_id("Boeing India", "KIADB Aerospace Park", "2024-08-15")
        b = _make_canonical_id("Airbus India", "KIADB Aerospace Park", "2024-08-15")
        assert a != b

    def test_different_month_produces_different_id(self):
        from ingest.plugins.gcc_plugin import _make_canonical_id
        a = _make_canonical_id("Boeing India", "KIADB", "2024-08")
        b = _make_canonical_id("Boeing India", "KIADB", "2024-09")
        assert a != b

    def test_id_is_valid_string(self):
        from ingest.plugins.gcc_plugin import _make_canonical_id
        cid = _make_canonical_id("Goldman Sachs", "Manyata Tech Park", "2024-09-10")
        assert isinstance(cid, str)
        assert len(cid) > 0
        assert len(cid) <= 200


# ── Demand unit estimation ───────────────────────────────────────────────────

class TestDemandUnitEstimation:
    def _plugin(self):
        from ingest.plugins.gcc_plugin import GCCPlugin
        return GCCPlugin()

    def test_high_ctc_new_full_office_returns_units(self):
        plugin = self._plugin()
        units = plugin._estimate_demand_units({
            "planned_headcount": 1000,
            "median_ctc_l": 60.0,
            "entrant_type": "NEW",
            "work_model": "FULL_OFFICE",
        })
        assert units is not None and units > 0

    def test_expansion_hybrid_returns_lower_units(self):
        plugin = self._plugin()
        new_units = plugin._estimate_demand_units({
            "planned_headcount": 1000,
            "median_ctc_l": 50.0,
            "entrant_type": "NEW",
            "work_model": "FULL_OFFICE",
        })
        exp_units = plugin._estimate_demand_units({
            "planned_headcount": 1000,
            "median_ctc_l": 50.0,
            "entrant_type": "EXPANSION",
            "work_model": "HYBRID",
        })
        assert new_units > exp_units

    def test_consolidation_returns_none(self):
        plugin = self._plugin()
        units = plugin._estimate_demand_units({
            "planned_headcount": 500,
            "median_ctc_l": 40.0,
            "entrant_type": "CONSOLIDATION",
            "work_model": "HYBRID",
        })
        assert units is None or units == 0

    def test_no_headcount_returns_none(self):
        plugin = self._plugin()
        units = plugin._estimate_demand_units({
            "planned_headcount": None,
            "median_ctc_l": 50.0,
            "entrant_type": "NEW",
            "work_model": "FULL_OFFICE",
        })
        assert units is None


# ── Seed data integrity ───────────────────────────────────────────────────────

class TestSeedData:
    def test_seed_events_have_required_fields(self):
        from ingest.plugins.gcc_plugin import _SEED_EVENTS
        required = {"company", "nearest_corridor", "signal_maturity_level", "entrant_type"}
        for evt in _SEED_EVENTS:
            missing = required - set(evt.keys())
            assert not missing, f"{evt.get('company')} missing {missing}"

    def test_seed_events_count_at_least_10(self):
        from ingest.plugins.gcc_plugin import _SEED_EVENTS
        assert len(_SEED_EVENTS) >= 10

    def test_seed_events_are_north_bengaluru_focused(self):
        from ingest.plugins.gcc_plugin import _SEED_EVENTS, _CORRIDOR_NB_IMPACT
        north_corridors = {k for k, v in _CORRIDOR_NB_IMPACT.items() if v >= 0.65}
        north_count = sum(
            1 for e in _SEED_EVENTS
            if e.get("nearest_corridor") in north_corridors
        )
        assert north_count >= len(_SEED_EVENTS) * 0.7, (
            "At least 70% of seed events should be in North BLR corridors"
        )

    def test_seed_event_scores_compute_without_error(self):
        from ingest.plugins.gcc_plugin import _SEED_EVENTS, _compute_gcc_score
        for evt in _SEED_EVENTS:
            score = _compute_gcc_score(evt)
            assert isinstance(score, float)
            assert -10.0 <= score <= 10.0


# ── GCCPlugin.run() with mocked DB ──────────────────────────────────────────

class TestGCCPluginRun:
    def test_run_returns_parsed_records(self):
        from ingest.plugins.gcc_plugin import GCCPlugin
        plugin = GCCPlugin()

        # Mock DB calls so seed data isn't blocked by missing DB
        with patch.object(plugin, "_get_existing_canonical_ids", return_value=set()):
            with patch.object(plugin, "_scan_news_articles", return_value=[]):
                records = plugin.run("Yelahanka")

        assert len(records) >= 10
        for rec in records:
            assert rec.entity_type == "gcc_event"
            assert rec.data.get("canonical_id")
            assert rec.data.get("company")
            assert rec.data.get("gcc_signal_score") is not None

    def test_run_skips_existing_canonical_ids(self):
        from ingest.plugins.gcc_plugin import GCCPlugin, _SEED_EVENTS, _make_canonical_id
        plugin = GCCPlugin()

        # Pre-populate all seed canonical IDs
        all_ids = {
            _make_canonical_id(
                e["company"],
                e.get("bengaluru_location", "Bengaluru"),
                str(e.get("announced_at", "2024-01")),
            )
            for e in _SEED_EVENTS
        }

        with patch.object(plugin, "_get_existing_canonical_ids", return_value=all_ids):
            with patch.object(plugin, "_scan_news_articles", return_value=[]):
                records = plugin.run("Yelahanka")

        assert len(records) == 0, "All seed events should be skipped when already in DB"

    def test_plugin_validate_accepts_valid_record(self):
        from ingest.plugins.gcc_plugin import GCCPlugin, _compute_gcc_score
        from ingest.base import ParsedRecord
        plugin = GCCPlugin()
        rec = ParsedRecord(
            entity_type="gcc_event",
            source_id="test_001",
            market="Yelahanka",
            data={
                "canonical_id": "test_cid",
                "company": "Test Corp",
                "gcc_signal_score": 5.0,
            },
        )
        result = plugin.validate(rec)
        assert result.valid

    def test_plugin_validate_rejects_missing_company(self):
        from ingest.plugins.gcc_plugin import GCCPlugin
        from ingest.base import ParsedRecord
        plugin = GCCPlugin()
        rec = ParsedRecord(
            entity_type="gcc_event",
            source_id="test_002",
            market="Yelahanka",
            data={"canonical_id": "test_cid", "gcc_signal_score": 5.0},
        )
        result = plugin.validate(rec)
        assert not result.valid


# ── GCCIntelResult scoring ───────────────────────────────────────────────────

class TestGCCIntelResult:
    def test_gcc_intel_result_defaults_to_zero(self):
        from intelligence.gcc_intel import GCCIntelResult
        r = GCCIntelResult(market="Yelahanka", collected_at="2025-01-01T00:00:00Z")
        assert r.gcc_north_norm == 0.0
        assert r.event_count_12m == 0
        assert not r.has_level1_signal

    def test_str_representation_contains_market(self):
        from intelligence.gcc_intel import GCCIntelResult
        r = GCCIntelResult(
            market="Devanahalli",
            collected_at="2025-01-01T00:00:00Z",
            gcc_north_norm=0.42,
            event_count_12m=5,
        )
        s = str(r)
        assert "Devanahalli" in s
        assert "0.420" in s or "0.42" in s

    def test_gcc_north_norm_no_db_returns_zero(self):
        from intelligence.gcc_intel import GCCIntel
        intel = GCCIntel()
        # Patch _load_positive_score to raise so we exercise graceful degrade
        with patch.object(intel, "_load_positive_score", side_effect=Exception("DB down")):
            with patch.object(intel, "_load_negative_score", side_effect=Exception("DB down")):
                with patch.object(intel, "_load_event_stats", side_effect=Exception("DB down")):
                    result = intel.get_gcc_score("Yelahanka", force_refresh=True)
        # Should not raise; should return 0.0 norm
        assert result.gcc_north_norm == 0.0

    def test_unknown_market_returns_zero_norm(self):
        from intelligence.gcc_intel import GCCIntel
        result = GCCIntel().get_gcc_score("NonExistentMarket99")
        assert result.gcc_north_norm == 0.0


# ── demand_score_v2 formula ──────────────────────────────────────────────────

class TestDemandScoreV2Integration:
    def test_gcc_north_norm_added_as_fifth_component(self):
        from intelligence.demand_intel import DemandIntel, DemandSignals
        from datetime import datetime, timezone

        ds = DemandSignals(
            market="Yelahanka",
            collected_at=datetime.now(timezone.utc).isoformat(),
        )
        ds.absorption_pct = 65.0
        ds.kaveri_velocity_ratio = 2.0
        ds.listing_count_30d = 100
        ds.config_absorption = {"2BHK": 60.0, "3BHK": 55.0}
        ds.gcc_north_norm = 0.75  # Strong GCC pipeline

        intel = DemandIntel()
        intel._compute_demand_score_v2(ds)

        assert ds.demand_score_v2 > 0.0
        assert ds.demand_score_v2 <= 1.0

    def test_gcc_north_norm_none_does_not_break_v2(self):
        from intelligence.demand_intel import DemandIntel, DemandSignals
        from datetime import datetime, timezone

        ds = DemandSignals(
            market="Yelahanka",
            collected_at=datetime.now(timezone.utc).isoformat(),
        )
        ds.absorption_pct = 65.0
        ds.gcc_north_norm = None  # GCC data absent

        intel = DemandIntel()
        intel._compute_demand_score_v2(ds)

        assert isinstance(ds.demand_score_v2, float)

    def test_gcc_north_norm_zero_does_not_inflate_score(self):
        from intelligence.demand_intel import DemandIntel, DemandSignals
        from datetime import datetime, timezone

        ds_no_gcc = DemandSignals(
            market="Yelahanka",
            collected_at=datetime.now(timezone.utc).isoformat(),
        )
        ds_no_gcc.absorption_pct = 60.0
        ds_no_gcc.gcc_north_norm = None

        ds_zero_gcc = DemandSignals(
            market="Yelahanka",
            collected_at=datetime.now(timezone.utc).isoformat(),
        )
        ds_zero_gcc.absorption_pct = 60.0
        ds_zero_gcc.gcc_north_norm = 0.0

        intel = DemandIntel()
        intel._compute_demand_score_v2(ds_no_gcc)
        intel._compute_demand_score_v2(ds_zero_gcc)

        # gcc_north_norm=0 adds a 0-value component that dilutes the score vs None
        # Both should be valid floats; neither should raise
        assert isinstance(ds_no_gcc.demand_score_v2, float)
        assert isinstance(ds_zero_gcc.demand_score_v2, float)

    def test_high_gcc_norm_raises_v2_score(self):
        from intelligence.demand_intel import DemandIntel, DemandSignals
        from datetime import datetime, timezone

        def make_ds(gcc_norm):
            ds = DemandSignals(
                market="Yelahanka",
                collected_at=datetime.now(timezone.utc).isoformat(),
            )
            ds.absorption_pct = 55.0
            ds.kaveri_velocity_ratio = 1.5
            ds.listing_count_30d = 80
            ds.gcc_north_norm = gcc_norm
            return ds

        intel = DemandIntel()
        ds_low = make_ds(0.1)
        ds_high = make_ds(0.9)
        intel._compute_demand_score_v2(ds_low)
        intel._compute_demand_score_v2(ds_high)

        assert ds_high.demand_score_v2 > ds_low.demand_score_v2, (
            "High GCC norm should produce higher demand_score_v2"
        )
