"""T-1049 unit tests — demand_score_v2 6th component (infra_pipeline_norm)."""

import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def test_demand_score_v2_has_6_components():
    from intelligence.demand_intel import DemandIntel, DemandSignals

    intel = DemandIntel(caller="test")
    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-08T00:00:00")
    ds.absorption_pct = 50.0
    ds.kaveri_velocity_ratio = 1.5
    ds.listing_count_30d = 100
    ds.config_absorption = {"1BHK": 60.0, "2BHK": 45.0, "3BHK": 55.0}
    ds.gcc_north_norm = 0.6
    ds.infra_pipeline_norm = 0.7
    intel._compute_demand_score_v2(ds)
    assert ds.demand_score_v2 > 0.3, f"demand_score_v2 too low: {ds.demand_score_v2}"


def test_infra_pipeline_norm_in_demand_signals():
    from intelligence.demand_intel import DemandSignals

    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-08T00:00:00")
    assert hasattr(ds, "infra_pipeline_norm")
    ds.infra_pipeline_norm = 0.5
    assert ds.infra_pipeline_norm == 0.5


def test_demand_score_without_infra_pipeline():
    from intelligence.demand_intel import DemandIntel, DemandSignals

    intel = DemandIntel(caller="test")
    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-08T00:00:00")
    ds.absorption_pct = 50.0
    ds.kaveri_velocity_ratio = 1.5
    ds.listing_count_30d = 100
    ds.config_absorption = {"1BHK": 60.0, "2BHK": 45.0, "3BHK": 55.0}
    ds.gcc_north_norm = 0.6
    ds.infra_pipeline_norm = None
    intel._compute_demand_score_v2(ds)
    assert ds.demand_score_v2 > 0, (
        f"demand_score_v2 too low without infra: {ds.demand_score_v2}"
    )


def test_infra_pipeline_norm_fallback_on_error():
    """Test that _load_govt_pipeline_signal sets 0.5 on GovtPolicyIntel error."""
    from intelligence.demand_intel import DemandIntel, DemandSignals

    intel = DemandIntel(caller="test")
    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-08T00:00:00")

    with patch("intelligence.govt_policy_intel.GovtPolicyIntel") as MockIntel:
        MockIntel.side_effect = Exception("GovtPolicyIntel unavailable")
        intel._load_govt_pipeline_signal(ds, {"name": "Yelahanka", "slug": "yelahanka"})

    assert ds.infra_pipeline_norm == 0.5, "Fallback to 0.5 on error"
