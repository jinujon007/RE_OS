"""
GATE-71 — GCC Demand Scout integration assertions (Sprint 67)

8 pass criteria (all must pass simultaneously):

1.  GCCPlugin imported and has correct plugin_id
2.  GCCPlugin is exported from ingest/plugins/__init__.py
3.  GCCPlugin.run() returns ≥10 ParsedRecords from seed data (mocked DB)
4.  gcc_signal_score is present and in [-10.0, 10.0] on every seed record
5.  GCCIntelResult has gcc_north_norm field [0.0, 1.0] (no DB required)
6.  DemandSignals has gcc_north_norm field (Sprint 67 addition)
7.  _compute_demand_score_v2 uses 5-component formula (gcc weight present)
8.  Discord notifier has gcc_intel channel registered
"""

import pytest
from unittest.mock import patch


# 1 ── GCCPlugin identity ─────────────────────────────────────────────────────


def test_gate71_gcc_plugin_importable():
    from ingest.plugins.gcc_plugin import GCCPlugin

    assert GCCPlugin.plugin_id == "gcc_scout"
    assert GCCPlugin.source_id == "gcc_demand_scout"


# 2 ── Plugin registry ────────────────────────────────────────────────────────


def test_gate71_gcc_plugin_in_registry():
    from ingest.plugins import GCCPlugin

    assert GCCPlugin is not None
    assert hasattr(GCCPlugin, "run")


# 3 ── Seed data ≥10 records ──────────────────────────────────────────────────


def test_gate71_seed_data_at_least_10_records():
    from ingest.plugins.gcc_plugin import GCCPlugin

    plugin = GCCPlugin()
    with patch.object(plugin, "_get_existing_canonical_ids", return_value=set()):
        with patch.object(plugin, "_scan_news_articles", return_value=[]):
            records = plugin.run("Yelahanka")
    assert len(records) >= 10, f"Expected ≥10 seed records, got {len(records)}"
    assert all(r.entity_type == "gcc_event" for r in records)


# 4 ── gcc_signal_score on every record ──────────────────────────────────────


def test_gate71_gcc_signal_score_present_and_in_range():
    from ingest.plugins.gcc_plugin import GCCPlugin

    plugin = GCCPlugin()
    with patch.object(plugin, "_get_existing_canonical_ids", return_value=set()):
        with patch.object(plugin, "_scan_news_articles", return_value=[]):
            records = plugin.run("Yelahanka")

    for rec in records:
        score = rec.data.get("gcc_signal_score")
        assert score is not None, (
            f"gcc_signal_score missing on {rec.data.get('company')}"
        )
        assert -10.0 <= float(score) <= 10.0, (
            f"gcc_signal_score {score} out of range on {rec.data.get('company')}"
        )


# 5 ── GCCIntelResult has gcc_north_norm ─────────────────────────────────────


def test_gate71_gcc_intel_result_has_norm_field():
    from intelligence.gcc_intel import GCCIntelResult

    r = GCCIntelResult(market="Yelahanka", collected_at="2025-01-01T00:00:00Z")
    assert hasattr(r, "gcc_north_norm")
    assert 0.0 <= r.gcc_north_norm <= 1.0


# 6 ── DemandSignals has gcc_north_norm ──────────────────────────────────────


def test_gate71_demand_signals_has_gcc_north_norm():
    from intelligence.demand_intel import DemandSignals
    from datetime import datetime, timezone

    ds = DemandSignals(
        market="Yelahanka",
        collected_at=datetime.now(timezone.utc).isoformat(),
    )
    assert hasattr(ds, "gcc_north_norm"), (
        "DemandSignals must have gcc_north_norm field (Sprint 67 addition)"
    )


# 7 ── demand_score_v2 uses 5 components ──────────────────────────────────────


def test_gate71_demand_score_v2_uses_gcc_component():
    """Verify that gcc_north_norm=0.9 raises v2 score vs gcc_north_norm=0.0."""
    from intelligence.demand_intel import DemandIntel, DemandSignals
    from datetime import datetime, timezone

    def _make(gcc_norm):
        ds = DemandSignals(
            market="Yelahanka",
            collected_at=datetime.now(timezone.utc).isoformat(),
        )
        ds.absorption_pct = 60.0
        ds.kaveri_velocity_ratio = 1.5
        ds.listing_count_30d = 100
        ds.gcc_north_norm = gcc_norm
        return ds

    intel = DemandIntel()
    ds_low = _make(0.0)
    ds_high = _make(0.9)
    intel._compute_demand_score_v2(ds_low)
    intel._compute_demand_score_v2(ds_high)

    assert ds_high.demand_score_v2 > ds_low.demand_score_v2, (
        "gcc_north_norm=0.9 must raise demand_score_v2 above gcc_north_norm=0.0"
    )


# 8 ── Discord gcc_intel channel registered ───────────────────────────────────


def test_gate71_discord_gcc_intel_channel_registered():
    from utils.discord_notifier import _CHANNEL_ENV_MAP, _VALID_CHANNELS

    assert "gcc_intel" in _CHANNEL_ENV_MAP, (
        "gcc_intel channel must be in _CHANNEL_ENV_MAP"
    )
    assert "gcc_intel" in _VALID_CHANNELS, (
        "gcc_intel channel must be in _VALID_CHANNELS"
    )
    assert _CHANNEL_ENV_MAP["gcc_intel"] == "DISCORD_WEBHOOK_GCC_INTEL"
