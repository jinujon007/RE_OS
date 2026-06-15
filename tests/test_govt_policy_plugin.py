"""T-1047 unit tests — GovtPolicyPlugin."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock

pytestmark = pytest.mark.unit


def test_govt_policy_plugin_instantiates():
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin

    plugin = GovtPolicyPlugin()
    assert plugin.plugin_id == "govt_policy_scout"


def test_get_seed_events_returns_list():
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin

    plugin = GovtPolicyPlugin()
    events = plugin.get_seed_events()
    assert isinstance(events, list)
    assert len(events) >= 8


def test_seed_events_have_required_fields():
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin

    plugin = GovtPolicyPlugin()
    events = plugin.get_seed_events()
    required = {
        "headline",
        "category",
        "impact_score",
        "signal_strength",
        "actionability",
        "is_north_bengaluru",
    }
    for evt in events:
        missing = required - set(evt.keys())
        assert not missing, (
            f"Missing fields {missing} in: {evt.get('headline', '?')[:50]}"
        )


def test_seed_events_all_north_bengaluru():
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin

    plugin = GovtPolicyPlugin()
    events = plugin.get_seed_events()
    for evt in events:
        assert evt.get("is_north_bengaluru") is True, (
            f"Seed event not marked as north_bengaluru: {evt['headline'][:50]}"
        )


def test_run_returns_list():
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin

    plugin = GovtPolicyPlugin()
    records = plugin.run()
    assert isinstance(records, list)


def test_is_north_bengaluru_detection():
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin

    plugin = GovtPolicyPlugin()
    assert plugin._is_north_bengaluru("Yelahanka metro station approved", []) is True
    assert plugin._is_north_bengaluru("Devanahalli airport expansion", []) is True
    assert plugin._is_north_bengaluru("Hebbal flyover construction", []) is True
    assert plugin._is_north_bengaluru("JP Nagar park renovation", []) is False
    assert plugin._is_north_bengaluru("Electronic City road widening", []) is False


def test_basic_classify_fallback():
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin

    plugin = GovtPolicyPlugin()
    result = plugin._basic_classify(
        "Metro Phase 3 approved for Bengaluru", "2026-06-08", None
    )
    assert result is not None
    assert result["category"] == "infrastructure"
    assert result["subcategory"] == "metro"
    assert result["impact_score"] == 7


def test_basic_classify_policy():
    from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin

    plugin = GovtPolicyPlugin()
    result = plugin._basic_classify(
        "FSI revision proposed for North Bengaluru", "2026-06-08", None
    )
    assert result is not None
    assert result["category"] == "policy"
    assert result["subcategory"] == "fsi_revision"
