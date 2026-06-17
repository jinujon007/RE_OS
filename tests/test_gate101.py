"""GATE-101 declaration — Domain Gap Closures (Finance / Legal / RERA / Demand).

4 assertions:
1. build_cash_flow importable; call with defaults returns list >=36 dicts
2. DEVELOPER_ALIASES has 'Brigade' key with >=5 variants
3. /api/finance/cashflow route registered in FastAPI app
4. /api/demand/config-split route registered in FastAPI app
"""

import pytest

pytestmark = pytest.mark.unit


def test_cashflow_importable():
    from utils.irr_model import build_cash_flow
    result = build_cash_flow(land_cost_cr=10.0, gdc_cr=25.0, construction_cost_cr=15.0)
    assert len(result.schedule) >= 36
    assert result.summary.peak_negative_cr < 0
    assert result.summary.roi_annualized_pct is not None


def test_developer_aliases_configured():
    from config.settings import DEVELOPER_ALIASES
    assert "Brigade" in DEVELOPER_ALIASES
    assert len(DEVELOPER_ALIASES["Brigade"]) >= 5


def test_cashflow_route_registered():
    from dashboard.app_fastapi import app
    routes = [r.path for r in app.routes]
    assert "/api/finance/cashflow" in routes


def test_config_split_route_registered():
    from dashboard.app_fastapi import app
    routes = [r.path for r in app.routes]
    assert "/api/demand/config-split" in routes
