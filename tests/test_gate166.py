"""GATE-166: System Coverage Audit — 5 gate assertions (A1–A5).

Assertion summary
-----------------
A1  All INTEL route contracts (20) are registered in the FastAPI app.
A2  All OPS route contracts (10) are registered.
A3  All DEAL route contracts (9) are registered (method-aware).
A4  All DASHBOARD route contracts (18) are registered.
A5  Total route count >= 120 AND no unexpected duplicate (method, path) pairs.

All assertions use (method, path) tuples — "route contracts" — so that a
GET→POST change on any route is caught immediately.

Known intentional cross-router duplicates are documented in
``_route_registry.KNOWN_CROSS_ROUTER_DUPES`` and are exempted from A5.
"""
from __future__ import annotations

import pytest

from tests._route_registry import (
    INTEL_ROUTES,
    OPS_ROUTES,
    DEAL_ROUTES,
    DASHBOARD_ROUTES,
    KNOWN_CROSS_ROUTER_DUPES,
    registered_contracts,
    duplicate_contracts,
    missing_contracts,
    format_missing,
)

pytestmark = [pytest.mark.unit]


def _app():
    from dashboard.app_fastapi import app

    return app


def _contracts():
    return registered_contracts(_app())


# ═══════════════════════════════════════════════════════════════════════════
# A1 — 20 INTEL route contracts
# ═══════════════════════════════════════════════════════════════════════════


def test_gate166_a1_intel_routes():
    """A1: All 20 INTEL route contracts are registered (method+path)."""
    missing = missing_contracts(_app(), INTEL_ROUTES)
    assert not missing, (
        "A1 FAIL — " + format_missing(missing)
    )


# ═══════════════════════════════════════════════════════════════════════════
# A2 — 10 OPS route contracts
# ═══════════════════════════════════════════════════════════════════════════


def test_gate166_a2_ops_routes():
    """A2: All 10 OPS route contracts are registered (method+path)."""
    missing = missing_contracts(_app(), OPS_ROUTES)
    assert not missing, (
        "A2 FAIL — " + format_missing(missing)
    )


# ═══════════════════════════════════════════════════════════════════════════
# A3 — 9 DEAL route contracts  (GATE spec says "8 routes", expanded to 9
#     because POST+GET on same path are separate route contracts)
# ═══════════════════════════════════════════════════════════════════════════


def test_gate166_a3_deal_routes():
    """A3: All 9 DEAL route contracts are registered (method+path).

    Spec says "8 routes".  POST /deals + GET /deals are two distinct
    route contracts on the same path, giving 9 total.  This is correct
    behaviour — method-aware verification is stricter.
    """
    missing = missing_contracts(_app(), DEAL_ROUTES)
    assert not missing, (
        "A3 FAIL — " + format_missing(missing)
    )


# ═══════════════════════════════════════════════════════════════════════════
# A4 — 18 DASHBOARD HTML PANEL route contracts
# ═══════════════════════════════════════════════════════════════════════════


def test_gate166_a4_dashboard_routes():
    """A4: All 18 DASHBOARD route contracts are registered (method+path).

    Expanded from spec's "15+" to cover all panel-serving routes in data_router
    (includes data-quality, govt-policy, projects).
    """
    missing = missing_contracts(_app(), DASHBOARD_ROUTES)
    assert not missing, (
        "A4 FAIL — " + format_missing(missing)
    )


# ═══════════════════════════════════════════════════════════════════════════
# A5 — Route count >= 120 + no unexpected duplicates
# ═══════════════════════════════════════════════════════════════════════════


def test_gate166_a5_route_count_and_duplicates():
    """A5: Route count >= 120 AND no unexpected duplicate (method, path) pairs.

    The count threshold is set at 120 (current ~144) so a single accidentally
    removed router (8–20 routes) triggers failure.

    Known cross-router duplicates are exempted:
    - GET /api/v1/optimizer         (data_router + ops_router)
    - GET /api/v1/shareholders      (data_router + ops_router)
    - GET /api/v1/process-audit     (data_router + ops_router)
    - GET /api/v1/projects          (data_router + ops_router)
    - GET /api/v1/ops/slo           (ops_router x2 — different endpoints)
    """
    app = _app()

    # ── Count guard ──
    route_count = len(
        [r for r in app.routes if hasattr(r, "path") and hasattr(r, "methods")]
    )
    assert route_count >= 120, (
        f"A5 FAIL: only {route_count} route(s) with path+methods (need >= 120). "
        "A router may have been accidentally removed."
    )

    # ── Duplicate guard ──
    dups = duplicate_contracts(app)
    unexpected = [d for d in dups if d not in KNOWN_CROSS_ROUTER_DUPES]
    assert not unexpected, (
        f"A5 FAIL: {len(unexpected)} unexpected duplicate(s):\n"
        + "\n".join(f"  {d[0]:>6} {d[1]}" for d in unexpected)
    )
