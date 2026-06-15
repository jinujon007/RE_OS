"""
Tests for months_of_supply computation in v_market_brief (Sprint 39 — T-484, T-486, T-485).
Tests the view formula:
  COALESCE(
    ROUND(active_units / NULLIF(monthly_registrations*12,0)*12, 1),
    fallback_from_sold_units
  )
Labels: <9 UNDERSUPPLY, 9-18 BALANCED, >18 OVERSUPPLY, NULL -> INSUFFICIENT_DATA
Fallback: sold_units/36 months absorption when kaveri data absent

NOTE: These tests verify the formula logic in Python. The actual SQL view
(v_market_brief) includes PostgreSQL-specific behavior (NULL propagation,
division semantics, COALESCE). A future integration test should run the
view against a real or emulated PostgreSQL instance.
"""

import pytest
from dataclasses import dataclass

pytestmark = pytest.mark.unit


# ── Formula replicas (mirror v_market_brief logic) ──────────────────────────


def _compute_mos_kaveri(
    active_units: int, monthly_registrations: float | None
) -> float | None:
    """Primary formula: kaveri_registrations-based absorption.
    ROUND(active_units / NULLIF(monthly_registrations*12, 0) * 12, 1)."""
    if monthly_registrations is None or monthly_registrations <= 0:
        return None
    return round(active_units / (monthly_registrations * 12) * 12, 1)


def _compute_mos_fallback(active_units: int, total_sold: int) -> float | None:
    """Fallback formula: RERA sold_units / 36 months absorption.
    Used when kaveri_registrations data is unavailable."""
    if total_sold <= 0:
        return None
    return round(active_units / (total_sold / 36.0), 1)


def _supply_label(mos: float | None) -> str:
    """Classify months_of_supply into supply label."""
    if mos is None:
        return "INSUFFICIENT_DATA"
    if mos < 9:
        return "UNDERSUPPLY"
    if mos <= 18:
        return "BALANCED"
    return "OVERSUPPLY"


def _resolve_mos(
    active_units: int, total_sold: int, monthly_registrations: float | None
) -> tuple[float | None, str]:
    """Mirror COALESCE logic: kaveri formula first, fallback second."""
    mos = _compute_mos_kaveri(active_units, monthly_registrations)
    if mos is not None:
        return mos, _supply_label(mos)
    mos = _compute_mos_fallback(active_units, total_sold)
    return mos, _supply_label(mos)


# ── Threshold tests ─────────────────────────────────────────────────────────


class TestMonthsSupplyFormula:
    """Primary kaveri formula: threshold labels."""

    def test_undersupply_below_9(self):
        mos = _compute_mos_kaveri(400, 50)
        assert mos == 8.0
        assert _supply_label(mos) == "UNDERSUPPLY"

    def test_balanced_9_to_18_range(self):
        mos = _compute_mos_kaveri(600, 50)
        assert mos == 12.0
        assert _supply_label(mos) == "BALANCED"

    def test_balanced_at_18_boundary(self):
        mos = _compute_mos_kaveri(900, 50)
        assert mos == 18.0
        assert _supply_label(mos) == "BALANCED"

    def test_oversupply_just_above_18(self):
        mos = _compute_mos_kaveri(950, 50)
        assert mos == 19.0
        assert _supply_label(mos) == "OVERSUPPLY"


class TestMonthsSupplyNullGuard:
    """NULL and zero edge cases."""

    def test_null_monthly_registrations_returns_none(self):
        assert _compute_mos_kaveri(500, None) is None

    def test_zero_monthly_registrations_returns_none(self):
        assert _compute_mos_kaveri(500, 0) is None

    def test_negative_monthly_registrations_returns_none(self):
        assert _compute_mos_kaveri(500, -1) is None

    def test_zero_active_units_returns_zero(self):
        mos = _compute_mos_kaveri(0, 50)
        assert mos == 0.0
        assert _supply_label(mos) == "UNDERSUPPLY"


class TestMonthsSupplyFallback:
    """Fallback formula (sold_units/36) when kaveri data absent."""

    def test_fallback_returns_value(self):
        mos = _compute_mos_fallback(1000, 600)
        assert mos == 60.0  # 1000 / (600/36) = 1000 / 16.67 = 60
        assert _supply_label(mos) == "OVERSUPPLY"

    def test_fallback_zero_sold_returns_none(self):
        assert _compute_mos_fallback(1000, 0) is None

    def test_fallback_negative_sold_returns_none(self):
        assert _compute_mos_fallback(1000, -1) is None

    def test_fallback_zero_units_sold_returns_none(self):
        assert _compute_mos_fallback(0, 100) == 0.0


class TestMonthsSupplyCoalesceResolution:
    """COALESCE behavior: kaveri formula preferred; fallback used when NULL."""

    def test_kaveri_data_present_uses_kaveri(self):
        mos, label = _resolve_mos(600, 200, 50)
        assert mos == 12.0
        assert label == "BALANCED"

    def test_kaveri_null_falls_back_to_sold(self):
        mos, label = _resolve_mos(1000, 600, None)
        assert mos == 60.0
        assert label == "OVERSUPPLY"

    def test_both_null_returns_insufficient(self):
        mos, label = _resolve_mos(1000, 0, None)
        assert mos is None
        assert label == "INSUFFICIENT_DATA"

    def test_kaveri_zero_falls_back_to_sold(self):
        mos, label = _resolve_mos(1000, 600, 0)
        assert mos == 60.0
        assert label == "OVERSUPPLY"
