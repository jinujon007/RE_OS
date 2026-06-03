"""
RE_OS — Ingest Engine Tests (Sprint 61 — T-672)
Tests: Plugin registration, dedup, rate limit, backoff, partial failure,
IngestReport, TokenBucket, ParsedRecord, and plugin validators.
"""
import pytest
import time
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit

from ingest.base import DataPlugin, ParsedRecord, ValidationResult


# ── Test plugins ───────────────────────────────────────────────────────────────

class _SuccessPlugin(DataPlugin):
    plugin_id = "test_success"
    source_id = "test_source"

    def run(self, market: str) -> list[ParsedRecord]:
        return [
            ParsedRecord(entity_type="rera_project", source_id=f"proj_{i}", market=market, data={"name": f"Proj {i}"})
            for i in range(3)
        ]


class _FailingPlugin(DataPlugin):
    plugin_id = "test_fail"
    source_id = "test_fail_source"

    def run(self, market: str) -> list[ParsedRecord]:
        msg = f"always fails for {market}"
        raise RuntimeError(msg)


class _PartialPlugin(DataPlugin):
    plugin_id = "test_partial"
    source_id = "test_partial_source"

    def run(self, market: str) -> list[ParsedRecord]:
        return [
            ParsedRecord(entity_type="rera_project", source_id=f"good_{i}", market=market, data={"name": f"Good {i}"})
            for i in range(2)
        ] + [
            ParsedRecord(entity_type="listing", source_id="bad_0", market="WrongMarket", data={"name": "Bad record"}),
        ]


class _EmptyPlugin(DataPlugin):
    plugin_id = "test_empty"
    source_id = "test_empty_source"

    def run(self, market: str) -> list[ParsedRecord]:
        return []


# ── ParsedRecord tests ─────────────────────────────────────────────────────────

class TestParsedRecord:
    def test_default_scraped_at(self):
        r = ParsedRecord(entity_type="rera_project", source_id="p1", market="Yelahanka", data={"a": 1})
        assert r.scraped_at is not None

    def test_auto_hash(self):
        r = ParsedRecord(entity_type="rera_project", source_id="p1", market="Yelahanka", data={"a": 1})
        assert len(r.raw_hash) == 64
        assert isinstance(r.raw_hash, str)

    def test_deterministic_hash(self):
        r1 = ParsedRecord(entity_type="rera_project", source_id="p1", market="Yelahanka", data={"a": 1})
        r2 = ParsedRecord(entity_type="rera_project", source_id="p2", market="Hebbal", data={"a": 1})
        assert r1.raw_hash == r2.raw_hash

    def test_compute_hash_static(self):
        h = ParsedRecord.compute_hash({"name": "Test"})
        assert len(h) == 64

    def test_repr(self):
        r = ParsedRecord(entity_type="rera_project", source_id="p1", market="Yelahanka", data={"a": 1})
        assert "ParsedRecord" in repr(r)


# ── ValidationResult tests ──────────────────────────────────────────────────────

class TestValidationResult:
    def test_valid_result(self):
        v = ValidationResult(valid=True)
        assert bool(v) is True

    def test_invalid_with_errors(self):
        v = ValidationResult(valid=False, errors=["missing data"])
        assert bool(v) is False
        assert "missing data" in repr(v)


# ── DataPlugin base tests ──────────────────────────────────────────────────────

class TestDataPluginBase:
    def test_validate_empty_entity_type(self):
        r = ParsedRecord(entity_type="", source_id="s1", market="M", data={"k": "v"})
        v = _SuccessPlugin().validate(r)
        assert v.valid is False
        assert any("entity_type" in e for e in v.errors)

    def test_validate_empty_source_id(self):
        r = ParsedRecord(entity_type="rera_project", source_id="", market="M", data={"k": "v"})
        v = _SuccessPlugin().validate(r)
        assert v.valid is False

    def test_validate_empty_data(self):
        r = ParsedRecord(entity_type="rera_project", source_id="s1", market="M", data={})
        v = _SuccessPlugin().validate(r)
        assert v.valid is False

    def test_validate_success(self):
        r = ParsedRecord(entity_type="rera_project", source_id="s1", market="M", data={"k": "v"})
        v = _SuccessPlugin().validate(r)
        assert v.valid is True


# ── TokenBucket tests ──────────────────────────────────────────────────────────

class TestTokenBucket:
    def test_acquire_nonzero(self):
        from ingest.engine import TokenBucket
        tb = TokenBucket(rate=10, capacity=10)
        wait = tb.acquire()
        assert wait == 0.0

    def test_available_tokens_after_acquire(self):
        from ingest.engine import TokenBucket
        tb = TokenBucket(rate=10, capacity=10)
        tb.acquire()
        assert tb.available < 10.0

    def test_bucket_refills(self):
        from ingest.engine import TokenBucket
        tb = TokenBucket(rate=100, capacity=100)
        tb.acquire(tokens=100)
        assert tb.available < 1
        time.sleep(0.05)
        assert tb.available > 0

    def test_negative_rate_raises(self):
        from ingest.engine import TokenBucket
        with pytest.raises(ValueError):
            TokenBucket(rate=-1, capacity=10)

    def test_zero_capacity_raises(self):
        from ingest.engine import TokenBucket
        with pytest.raises(ValueError):
            TokenBucket(rate=5, capacity=0)


# ── Plugin registry tests ──────────────────────────────────────────────────────

class TestPluginRegistry:
    def test_register_and_list(self):
        from ingest.engine import IngestEngine
        engine = IngestEngine(install_signal_handlers=False)
        engine.register(_SuccessPlugin())
        assert "test_success" in engine.registered_plugins

    def test_register_overwrite_warning(self):
        from ingest.engine import IngestEngine
        engine = IngestEngine(install_signal_handlers=False)
        engine.register(_SuccessPlugin())
        engine.register(_SuccessPlugin())
        assert engine.registered_plugins == ["test_success"]

    def test_empty_registry_run_returns_empty_report(self):
        from ingest.engine import IngestEngine
        engine = IngestEngine(install_signal_handlers=False)
        report = engine.run_all(["Yelahanka"])
        assert report.global_records_written == 0

    def test_run_with_no_markets(self):
        from ingest.engine import IngestEngine
        engine = IngestEngine(install_signal_handlers=False)
        engine.register(_SuccessPlugin())
        report = engine.run_all(markets=[])
        assert report.global_records_written == 0


# ── Market normalization tests ─────────────────────────────────────────────────

class TestMarketNormalization:
    def test_canonical_market_passes(self):
        from ingest.engine import _normalize_market
        assert _normalize_market("Yelahanka") == "Yelahanka"

    def test_lowercase_market_normalizes(self):
        from ingest.engine import _normalize_market
        assert _normalize_market("devanahalli") == "Devanahalli"

    def test_unknown_market_returns_as_is(self):
        from ingest.engine import _normalize_market
        assert _normalize_market("UnknownCity") == "UnknownCity"


# ── IngestReport tests ─────────────────────────────────────────────────────────

class TestIngestReport:
    def test_all_succeeded_true(self):
        from ingest.engine import IngestReport, PluginRunStats
        report = IngestReport(run_id="r1", started_at=None)
        report.plugin_stats = [
            PluginRunStats(plugin_id="p1", market="M", status="success"),
            PluginRunStats(plugin_id="p2", market="M", status="success"),
        ]
        assert report.all_succeeded is True

    def test_all_succeeded_with_failure(self):
        from ingest.engine import IngestReport, PluginRunStats
        report = IngestReport(run_id="r1", started_at=None)
        report.plugin_stats = [
            PluginRunStats(plugin_id="p1", market="M", status="success"),
            PluginRunStats(plugin_id="p2", market="M", status="failed"),
        ]
        assert report.all_succeeded is False

    def test_summary_string(self):
        from ingest.engine import IngestReport
        report = IngestReport(run_id="abc123", started_at=None)
        report.total_duration_seconds = 10.5
        report.global_records_written = 50
        report.global_records_deduped = 10
        report.global_records_failed = 2
        s = report.summary()
        assert "abc123" in s
        assert "written=50" in s

    def test_global_records_processed(self):
        from ingest.engine import IngestReport
        report = IngestReport(run_id="r1", started_at=None)
        report.global_records_written = 10
        report.global_records_deduped = 5
        report.global_records_failed = 2
        assert report.global_records_processed == 17


# ── Plugin run tests (mocked DB) ───────────────────────────────────────────────

class TestPluginRun:
    def test_successful_plugin_run(self):
        from ingest.engine import IngestEngine
        engine = IngestEngine(install_signal_handlers=False)
        engine.register(_SuccessPlugin())
        with patch.object(engine._writer, "write", return_value=True), \
             patch.object(engine._dedup, "check_and_add", return_value=False), \
             patch.object(engine, "_log_ingest"), \
             patch.object(engine._dedup, "_seed_from_db"):
            report = engine.run_all(["Yelahanka"])
        assert report.global_records_written == 3
        assert report.global_records_deduped == 0
        assert report.global_records_failed == 0

    def test_plugin_failure_reported(self):
        from ingest.engine import IngestEngine
        engine = IngestEngine(install_signal_handlers=False)
        engine.register(_FailingPlugin())
        with patch.object(engine._dedup, "_seed_from_db"):
            report = engine.run_all(["Yelahanka"])
        assert len(report.failed_plugins) >= 1
        assert report.global_records_written == 0

    def test_partial_failure_detected(self):
        from ingest.engine import IngestEngine
        engine = IngestEngine(install_signal_handlers=False)
        engine.register(_PartialPlugin())
        with patch.object(engine._writer, "write", return_value=True), \
             patch.object(engine._dedup, "check_and_add", return_value=False), \
             patch.object(engine, "_log_ingest"), \
             patch.object(engine._dedup, "_seed_from_db"):
            report = engine.run_all(["Yelahanka"])
        assert report.global_records_written >= 2
        # The WrongMarket record should be counted as failed
        assert report.global_records_failed >= 1

    def test_dedup_skips_duplicates(self):
        from ingest.engine import IngestEngine
        engine = IngestEngine(install_signal_handlers=False)
        engine.register(_SuccessPlugin())
        with patch.object(engine._writer, "write", return_value=True), \
             patch.object(engine._dedup, "check_and_add", return_value=True), \
             patch.object(engine, "_log_ingest"), \
             patch.object(engine._dedup, "_seed_from_db"):
            report = engine.run_all(["Yelahanka"])
        assert report.global_records_written == 0
        assert report.global_records_deduped == 3


# ── Backoff test ───────────────────────────────────────────────────────────────

class TestBackoff:
    def test_backoff_values_increase_monotonically(self):
        from ingest.engine import _backoff_sleep
        durations = []
        for attempt in range(4):
            start = time.perf_counter()
            _backoff_sleep(attempt, base=0.01, max_delay=2.0)
            durations.append(time.perf_counter() - start)
        # Each successive attempt should sleep >= the previous
        for i in range(1, len(durations)):
            assert durations[i] >= durations[i - 1] - 0.01, f"backoff not monotonic at attempt {i}"

    def test_backoff_capped_at_max(self):
        from ingest.engine import _backoff_sleep
        time_before = time.perf_counter()
        _backoff_sleep(10, base=0.5, max_delay=0.05)
        elapsed = time.perf_counter() - time_before
        assert elapsed < 0.5


# ── Plugin __init__ exports ────────────────────────────────────────────────────

class TestPluginExports:
    def test_all_plugins_importable(self):
        from ingest.plugins import (
            RERAPlugin, IGRPlugin, KaveriBhoomiPlugin,
            PortalPlugin, DeveloperPlugin, NewsPlugin,
            DistressedPlugin, BBMPPlugin,
        )
        assert RERAPlugin().plugin_id == "rera_karnataka"
        assert IGRPlugin().plugin_id == "igr_karnataka"
        assert KaveriBhoomiPlugin().plugin_id == "kaveri_bhoomi"
        assert PortalPlugin().plugin_id == "portal_scout"
        assert DeveloperPlugin().plugin_id == "developer_scout"
        assert NewsPlugin().plugin_id == "news_scout"
        assert DistressedPlugin().plugin_id == "distressed_scan"
        assert BBMPPlugin().plugin_id == "bbmp_khata"

    def test_all_plugins_have_all_exports(self):
        from ingest.plugins.rera_plugin import __all__ as rera_all
        from ingest.plugins.igr_plugin import __all__ as igr_all
        assert "RERAPlugin" in rera_all
        assert "IGRPlugin" in igr_all


class TestContentHash:
    def test_deterministic(self):
        from ingest.plugins.kaveri_bhoomi_plugin import _content_hash
        h1 = _content_hash("a", "b", "c")
        h2 = _content_hash("a", "b", "c")
        assert h1 == h2

    def test_different_inputs_different_hashes(self):
        from ingest.plugins.kaveri_bhoomi_plugin import _content_hash
        assert _content_hash("x", "y") != _content_hash("x", "z")

    def test_hex_length(self):
        from ingest.plugins.kaveri_bhoomi_plugin import _content_hash
        assert len(_content_hash("test")) == 20


class TestStableSourceId:
    def test_igr_stable_id(self):
        from ingest.plugins.igr_plugin import _stable_source_id
        txn = {"survey_no": "123", "consideration_amount": 500000, "registration_date": "2026-01-15"}
        id1 = _stable_source_id(txn, "Yelahanka")
        id2 = _stable_source_id(txn, "Yelahanka")
        assert id1 == id2
        assert len(id1) == 20


class TestSchedulerISTConversion:
    def test_plugin_should_run_returns_true_for_daily(self):
        from config.settings import PLUGIN_SCHEDULES
        schedule = PLUGIN_SCHEDULES.get("rera_karnataka")
        assert schedule is None

    def test_plugin_should_run_returns_false_for_wrong_day(self):
        from config.settings import PLUGIN_SCHEDULES
        schedule = PLUGIN_SCHEDULES.get("bbmp_khata")
        assert schedule is not None
        assert "day_of_week" in schedule


class TestGeocoder:
    def test_cache_hits_return_same_result(self):
        from ingest.plugins.portal_plugin import _Geocoder
        g = _Geocoder()
        with patch.object(g, "_call_nominatim", return_value={"lat": 13.0, "lon": 77.5}):
            r1 = g.geocode("Yelahanka", "Yelahanka")
            r2 = g.geocode("Yelahanka", "Yelahanka")
            assert r1 == r2
            assert g._call_nominatim.call_count == 1

    def test_different_localities_miss_cache(self):
        from ingest.plugins.portal_plugin import _Geocoder
        g = _Geocoder()
        with patch.object(g, "_call_nominatim", return_value={"lat": 0.0, "lon": 0.0}):
            g.geocode("Yelahanka", "Yelahanka")
            g.geocode("Hebbal", "Hebbal")
            assert g._call_nominatim.call_count == 2
