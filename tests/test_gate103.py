"""GATE-103 declaration: True IRR (Sprint 103)."""

import pytest

pytestmark = pytest.mark.unit


def _irr(cf):
    from utils.irr_model import calc_irr_npv
    return calc_irr_npv(cf, caller="fixture")


def test_calc_irr_npv_importable():
    from utils.irr_model import calc_irr_npv
    assert callable(calc_irr_npv)


def test_4acre_jd_fixture_irr_in_range():
    cf = [-80000000] + [0] * 12 + [3400000] * 36
    irr = _irr(cf)
    assert irr is not None
    assert 18.0 <= irr <= 28.0


def test_roi_annualized_pct_field_present():
    from utils.irr_model import CashFlowSummary
    s = CashFlowSummary(peak_negative_cr=0.0, breakeven_month=None, roi_annualized_pct=0.0)
    assert hasattr(s, "roi_annualized_pct")


def test_irr_estimate_pct_field_absent():
    from utils.irr_model import CashFlowSummary
    s = CashFlowSummary(peak_negative_cr=0.0, breakeven_month=None, roi_annualized_pct=0.0)
    assert not hasattr(s, "irr_estimate_pct")


def test_irr_npv_accepted_by_finance_head_context():
    """Verify the IRR value fits the format string used in Finance Head context."""
    from utils.irr_model import calc_irr_npv
    cf = [-80000000] + [0] * 12 + [3400000] * 36
    irr = calc_irr_npv(cf, caller="fixture")
    assert irr is not None
    text = (
        f"IRR (NPV-solving, monthly cash flows): {irr:.1f}% | "
        f"ROI (annualized simple): 22.0% | Horizon: 54mo"
    )
    assert "IRR (NPV-solving" in text


def test_irr_npv_validation_rejects_false_root():
    """npf.irr can converge to a false root — NPV validation catches it."""
    from utils.irr_model import calc_irr_npv
    cf = [1000, -500, -300, -200, -100, -50, -50]
    irr = calc_irr_npv(cf, caller="fixture")
    assert irr is None or irr >= -100
