"""
Tests for appreciation_model.py — forecast logic validation.
"""

import pytest

pytestmark = pytest.mark.unit


def test_get_appreciation_forecast_hoskote():
    """Test STRR node pincode 562114 returns infrastructure events and forecast."""
    import sys

    sys.path.insert(0, ".")
    from utils.appreciation_model import get_appreciation_forecast

    result = get_appreciation_forecast("562114")
    assert result["pincode"] == "562114"
    assert result["area"] == "Hoskote Town"
    assert result["investment_tier"] == "Tier1_Industrial_Growth"
    assert result["water_risk"] == "Medium"
    assert len(result["infrastructure_events"]) >= 1
    assert "forecast" in result
    assert "3yr_appreciation_pct" in result["forecast"]
    assert "5yr_appreciation_pct" in result["forecast"]
    assert "10yr_appreciation_pct" in result["forecast"]


def test_get_appreciation_forecast_yelahanka():
    """Test Yelahanka pincode 560009 returns forecast (no infra events for this pincode)."""
    import sys

    sys.path.insert(0, ".")
    from utils.appreciation_model import get_appreciation_forecast

    result = get_appreciation_forecast("560009")
    assert result["pincode"] == "560009"
    assert result["area"] == "Yelahanka Old Town"
    assert "forecast" in result


def test_get_pincodes_for_market():
    """Test that Devanahalli and Yelahanka returns correct pincodes."""
    import sys

    sys.path.insert(0, ".")
    from utils.appreciation_model import get_pincodes_for_market

    yelahanka_pins = get_pincodes_for_market("Yelahanka")
    assert len(yelahanka_pins) >= 1
    assert "560009" in yelahanka_pins

    devanahalli_pins = get_pincodes_for_market("Devanahalli")
    assert len(devanahalli_pins) >= 1
    assert "562110" in devanahalli_pins
