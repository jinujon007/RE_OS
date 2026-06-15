import pytest

pytestmark = pytest.mark.unit


def test_demand_signals_str_with_none_fields():
    from intelligence.demand_intel import DemandSignals

    ds = DemandSignals(market="Yelahanka", collected_at="2026-06-05T00:00:00")
    result = str(ds)
    assert "DemandSignals" in result
    assert "UNKNOWN" in result or "0.0" in result
