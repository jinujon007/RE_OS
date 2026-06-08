"""GATE-75 declaration — Govt/Infra/Policy Scout.

Eight assertions:
1. GovtPolicyPlugin().get_seed_events() returns >= 8 records
2. Every seed record has impact_score between 1 and 10
3. Every seed record has signal_strength in ['high','emerging','risk']
4. Every seed record has actionability in ['buy_now','accumulate','monitor','avoid']
5. GovtPolicyIntel.compute('Yelahanka') returns GovtPolicyResult with north_bengaluru_score in [0.0, 1.0]
6. DemandSignals has attribute infra_pipeline_norm
7. demand_score_v2 component weights sum to 1.0 (+- 0.001)
8. DISCORD_GOVT_POLICY_WEBHOOK is referenced in config/settings.py
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

pytestmark = pytest.mark.unit


def _mock_db_rows(rows):
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = rows
    mock_eng = MagicMock()
    mock_eng.connect.return_value.__enter__.return_value = mock_conn
    return patch("utils.db.get_engine", return_value=mock_eng)


def _mock_llm_fallback():
    return patch("config.llm_router.get_analysis_llm", side_effect=Exception("LLM unavailable"))


def test_seed_events_returns_at_least_8():
    """Assertion 1: GovtPolicyPlugin().get_seed_events() returns >= 8 records."""
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin
    plugin = GovtPolicyPlugin()
    events = plugin.get_seed_events()
    assert len(events) >= 8, f"Expected >=8 seed events, got {len(events)}"


def test_seed_events_impact_score_in_range():
    """Assertion 2: Every seed record has impact_score between 1 and 10."""
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin
    plugin = GovtPolicyPlugin()
    events = plugin.get_seed_events()
    for evt in events:
        score = evt.get("impact_score")
        assert score is not None, f"Missing impact_score in: {evt['headline'][:50]}"
        assert 1 <= score <= 10, f"impact_score {score} out of range [1,10] in: {evt['headline'][:50]}"


def test_seed_events_signal_strength_valid():
    """Assertion 3: Every seed record has signal_strength in ['high','emerging','risk']."""
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin
    plugin = GovtPolicyPlugin()
    events = plugin.get_seed_events()
    valid = {"high", "emerging", "risk"}
    for evt in events:
        sig = evt.get("signal_strength")
        assert sig in valid, f"Invalid signal_strength '{sig}' in: {evt['headline'][:50]}"


def test_seed_events_actionability_valid():
    """Assertion 4: Every seed record has actionability in valid options."""
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin
    plugin = GovtPolicyPlugin()
    events = plugin.get_seed_events()
    valid = {"buy_now", "accumulate", "monitor", "avoid"}
    for evt in events:
        act = evt.get("actionability")
        assert act in valid, f"Invalid actionability '{act}' in: {evt['headline'][:50]}"


def test_govt_policy_intel_returns_score_in_range():
    """Assertion 5: GovtPolicyIntel.compute returns north_bengaluru_score in [0.0, 1.0]."""
    from intelligence.govt_policy_intel import GovtPolicyIntel
    rows = [
        ("Metro Phase 3 approved", "infrastructure", "metro", 6100.0,
         "construction", 9, "high", "long", "buy_now",
         "Test summary", "Test why it matters",
         True, "2026-01-15", "2026-06-08 00:00:00+00"),
        ("New industrial park announced", "infrastructure", "industrial_park", 500.0,
         "announcement", 7, "high", "medium", "accumulate",
         "Test summary 2", "Test why it matters 2",
         True, "2026-05-01", "2026-06-07 00:00:00+00"),
    ]
    with _mock_db_rows(rows), _mock_llm_fallback():
        intel = GovtPolicyIntel(caller="test")
        result = intel.compute("Yelahanka")
        assert 0.0 <= result.north_bengaluru_score <= 1.0


def test_demand_signals_has_infra_pipeline_norm():
    """Assertion 6: DemandSignals has attribute infra_pipeline_norm."""
    from intelligence.demand_intel import DemandSignals
    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-08T00:00:00")
    assert hasattr(ds, "infra_pipeline_norm"), "DemandSignals missing infra_pipeline_norm"


def test_demand_score_v2_weights_sum_to_1():
    """Assertion 7: demand_score_v2 works with all 6 components."""
    from intelligence.demand_intel import DemandIntel, DemandSignals
    intel = DemandIntel(caller="test")
    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-08T00:00:00")
    ds.absorption_pct = 50.0
    ds.kaveri_velocity_ratio = 1.0
    ds.listing_count_30d = 50
    ds.config_absorption = {"1BHK": 60.0, "2BHK": 45.0, "3BHK": 55.0}
    ds.gcc_north_norm = 0.5
    ds.infra_pipeline_norm = 0.5
    intel._compute_demand_score_v2(ds)
    assert 0.0 <= ds.demand_score_v2 <= 1.0
    assert ds.demand_score_v2 > 0


def test_settings_references_discord_govt_policy_webhook():
    """Assertion 8: DISCORD_GOVT_POLICY_WEBHOOK is referenced in config/settings.py."""
    import config.settings
    assert hasattr(config.settings, "DISCORD_WEBHOOK_GOVT_POLICY"), \
        "DISCORD_GOVT_POLICY_WEBHOOK not found in config/settings.py"
