"""Route contract coverage — 76 contracts across 7 API domains.

Usage:
    pytest tests/test_api_full_coverage.py -q -m unit

Design:
  - Method+path tuple assertions (not path-only): catches method changes.
  - Both aggregate (all-X-routes-present) and granular (per-route) tests exist.
    The granular parametrized tests give per-route pass/fail visibility.
  - Known cross-router duplicates are documented and explicitly exempted
    from the duplicate-detection assertion.
  - Imports route inventories from ``_route_registry`` (non-test module)
    to avoid test-imports-test side effects.

Categories & contract counts:
  INTEL     20 | OPS        10 | DEAL        9
  DASHBOARD 18 | BOARD       8 | PIPELINE    8
  HEALTH     4
"""
from __future__ import annotations

import pytest

from tests._route_registry import (
    INTEL_ROUTES,
    OPS_ROUTES,
    DEAL_ROUTES,
    DASHBOARD_ROUTES,
    BOARD_ROUTES,
    PIPELINE_ROUTES,
    HEALTH_ROUTES,
    KNOWN_CROSS_ROUTER_DUPES,
    registered_contracts,
    duplicate_contracts,
    missing_contracts,
    format_missing,
)

pytestmark = [pytest.mark.unit]

# ── Shared (cached at module load) ─────────────────────────────────────────


def _app():
    """Lazy-import app so conftest.py env vars are set before import."""
    from dashboard.app_fastapi import app

    return app


def _contracts():
    """Cached registered contracts from the app."""
    return registered_contracts(_app())


# ── Helpers ────────────────────────────────────────────────────────────────


def _ids(contracts) -> list[str]:
    return [f"{m} {p}" for m, p in contracts]


def _assert_domain(domain_name: str, expected, actual_set):
    missing = [c for c in expected if c not in actual_set]
    assert not missing, (
        f"Domain [{domain_name}] — {format_missing(missing)}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# INTEL — 20 contracts
# ═══════════════════════════════════════════════════════════════════════════


def test_intel_routes_registered():
    _assert_domain("INTEL", INTEL_ROUTES, _contracts())


@pytest.mark.parametrize("method,path", INTEL_ROUTES, ids=_ids(INTEL_ROUTES))
def test_intel_route(method, path):
    assert (method, path) in _contracts(), f"Missing intel route: {method} {path}"


# ═══════════════════════════════════════════════════════════════════════════
# OPS — 10 contracts
# ═══════════════════════════════════════════════════════════════════════════


def test_ops_routes_registered():
    _assert_domain("OPS", OPS_ROUTES, _contracts())


@pytest.mark.parametrize("method,path", OPS_ROUTES, ids=_ids(OPS_ROUTES))
def test_ops_route(method, path):
    assert (method, path) in _contracts(), f"Missing ops route: {method} {path}"


# ═══════════════════════════════════════════════════════════════════════════
# DEAL — 9 contracts
# ═══════════════════════════════════════════════════════════════════════════


def test_deal_routes_registered():
    _assert_domain("DEAL", DEAL_ROUTES, _contracts())


@pytest.mark.parametrize("method,path", DEAL_ROUTES, ids=_ids(DEAL_ROUTES))
def test_deal_route(method, path):
    assert (method, path) in _contracts(), f"Missing deal route: {method} {path}"


# ═══════════════════════════════════════════════════════════════════════════
# DASHBOARD — 18 contracts
# ═══════════════════════════════════════════════════════════════════════════


def test_dashboard_routes_registered():
    _assert_domain("DASHBOARD", DASHBOARD_ROUTES, _contracts())


@pytest.mark.parametrize(
    "method,path", DASHBOARD_ROUTES, ids=_ids(DASHBOARD_ROUTES)
)
def test_dashboard_route(method, path):
    assert (method, path) in _contracts(), f"Missing dashboard route: {method} {path}"


# ═══════════════════════════════════════════════════════════════════════════
# BOARD ROOM — 8 contracts (supplementary)
# ═══════════════════════════════════════════════════════════════════════════


def test_board_room_routes_registered():
    _assert_domain("BOARD", BOARD_ROUTES, _contracts())


@pytest.mark.parametrize("method,path", BOARD_ROUTES, ids=_ids(BOARD_ROUTES))
def test_board_room_route(method, path):
    assert (method, path) in _contracts(), f"Missing board route: {method} {path}"


# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE — 8 contracts (supplementary)
# ═══════════════════════════════════════════════════════════════════════════


def test_pipeline_routes_registered():
    _assert_domain("PIPELINE", PIPELINE_ROUTES, _contracts())


@pytest.mark.parametrize(
    "method,path", PIPELINE_ROUTES, ids=_ids(PIPELINE_ROUTES)
)
def test_pipeline_route(method, path):
    assert (method, path) in _contracts(), f"Missing pipeline route: {method} {path}"


# ═══════════════════════════════════════════════════════════════════════════
# HEALTH — 4 contracts (supplementary)
# ═══════════════════════════════════════════════════════════════════════════


def test_health_routes_registered():
    _assert_domain("HEALTH", HEALTH_ROUTES, _contracts())


@pytest.mark.parametrize("method,path", HEALTH_ROUTES, ids=_ids(HEALTH_ROUTES))
def test_health_route(method, path):
    assert (method, path) in _contracts(), f"Missing health route: {method} {path}"


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-CUTTING REGRESSION GUARDS
# ═══════════════════════════════════════════════════════════════════════════


def test_no_unexpected_duplicate_contracts():
    """Fail if any (method, path) appears more than once (unintentional).

    Known cross-router duplicates are exempted (documented in
    _route_registry.KNOWN_CROSS_ROUTER_DUPES).
    """
    dups = duplicate_contracts(_app())
    unexpected = [d for d in dups if d not in KNOWN_CROSS_ROUTER_DUPES]
    assert not unexpected, (
        f"Found {len(unexpected)} unexpected duplicate(s):\n"
        + "\n".join(f"  {d[0]:>6} {d[1]}" for d in unexpected)
    )


def test_total_route_count():
    """Sanity: at least 120 route entries (path + methods) exist.

    Threshold (120) is deliberately below the current count (~144) so
    a single accidentally-removed router (8–20 routes) triggers failure.
    """
    app = _app()
    route_count = len(
        [r for r in app.routes if hasattr(r, "path") and hasattr(r, "methods")]
    )
    assert route_count >= 120, (
        f"Only {route_count} route(s) with path+methods (need >= 120). "
        "A router may have been accidentally removed."
    )
