"""T-1501 — API route coverage test (GATE-163 A1).

Asserts all 13 target routes are registered as GET endpoints in the FastAPI app.
Validates CORS pre-flight returns non-5xx, regression guards for critical routes,
and total GET route count is in expected range.

Risk notes:
  - TARGET_ROUTES must be updated when routes are renamed or new routes added.
  - The CORS middleware check relies on introspection of app.user_middleware,
    which is stable across FastAPI 0.110+ but may differ in older versions.
  - The OPTIONS preflight test is a soft check (only flags >=500), because
    some route handlers may legitimately reject OPTIONS at the route level
    while CORS middleware handles preflights at the app level.
"""

import os

import pytest
from starlette.testclient import TestClient
from starlette.routing import Route, Mount

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
os.environ.setdefault("REDIS_URL", "memory://")

pytestmark = pytest.mark.unit

TARGET_ROUTES: list[str] = [
    "/api/v1/ops/calibration",
    "/api/v1/intel/deal-score",
    "/api/v1/intel/parcel-graph",
    "/api/v1/intel/parcel-graph/summary",
    "/api/v1/intel/parcel-graph/stats",
    "/api/v1/intel/parcel-graph/hotspot-alert",
    "/api/v1/intel/strr-overlay",
    "/api/v1/intel/investor/weekly-digest",
    "/api/v1/intel/deal-score/history",
    "/api/v1/ops/digest-quality",
    "/api/v1/intel/digest/latest",
    "/api/v1/ops/handover-doc",
    "/api/v1/parcel-graph",
]

REGRESSION_ROUTES: list[str] = [
    "/api/v1/health",
    "/api/v1/ops/kill-criteria",
]


def _get_routes_by_method(app) -> dict[str, set[str]]:
    """Build {method: {path}} from FastAPI/Starlette app routes.

    Traverses Mount() sub-apps recursively in case of nested prefixes.
    Starlette 0.40+ stores routes as Route/Mount objects with .methods.
    """
    by_method: dict[str, set[str]] = {}
    to_visit: list = list(app.routes)
    visited: set[int] = set()

    while to_visit:
        route = to_visit.pop()
        if id(route) in visited:
            continue
        visited.add(id(route))

        if isinstance(route, Mount):
            to_visit.extend(route.routes)
            continue
        if isinstance(route, Route):
            methods = route.methods or {"GET"}
            for method in methods:
                by_method.setdefault(method, set()).add(route.path)
    return by_method


def test_all_target_routes_registered():
    from dashboard.app_fastapi import app

    get_paths = _get_routes_by_method(app).get("GET", set())
    missing = [r for r in TARGET_ROUTES if r not in get_paths]
    assert not missing, (
        f"Missing GET route(s): {missing}"
    )


def test_regression_guards_present():
    from dashboard.app_fastapi import app

    get_paths = _get_routes_by_method(app).get("GET", set())
    missing = [r for r in REGRESSION_ROUTES if r not in get_paths]
    assert not missing, (
        f"Missing regression guard(s): {missing}"
    )


def test_regression_routes_are_get():
    from dashboard.app_fastapi import app

    by_method = _get_routes_by_method(app)
    for route in REGRESSION_ROUTES:
        assert route in by_method.get("GET", set()), (
            f"'{route}' is not registered as a GET endpoint"
        )


def test_unknown_routes_not_registered():
    from dashboard.app_fastapi import app

    all_paths = {r.path for r in app.routes}
    bad_paths = [
        "/api/v1/intel/nonexistent",
        "/api/v1/ops/nonexistent",
        "/api/v2/health",
    ]
    conflicts = [p for p in bad_paths if p in all_paths]
    assert not conflicts, (
        f"Unexpected route(s) found that should not exist: {conflicts}"
    )


def test_total_get_route_count_reasonable():
    from dashboard.app_fastapi import app

    get_paths = _get_routes_by_method(app).get("GET", set())
    assert len(get_paths) >= 50, (
        f"Only {len(get_paths)} GET routes — expected >= 50. "
        f"Verify TARGET_ROUTES and REGRESSION_ROUTES are still accurate."
    )


def test_options_no_server_errors():
    """OPTIONS preflight should never produce >=500.

    CORS middleware intercepts OPTIONS at the Starlette level before routing.
    Route-level 405 (Method Not Allowed) is acceptable — only server errors
    indicate broken middleware configuration."""
    from dashboard.app_fastapi import app

    has_cors = any(
        hasattr(m, "cls") and "CORSMiddleware" in m.cls.__name__
        for m in app.user_middleware
    )
    if not has_cors:
        pytest.skip("No CORS middleware configured — check app.add_middleware(CORSMiddleware, ...)")

    client = TestClient(app)
    failures: list[str] = [
        r for r in TARGET_ROUTES
        if client.options(r).status_code >= 500
    ]
    assert not failures, (
        "OPTIONS returned >=500 for: " + "; ".join(failures)
    )


def test_app_import_sets_env_vars():
    """Ensure env vars are set before app import to avoid rate-limiter
    connection errors and missing API key crashes.

    REDIS_URL: conftest setdefaults "memory://" for bare pytest runs; inside
    the agents container a real redis:// URL is injected by compose — both
    are valid, the invariant is that it is set to *something* at import time.
    """
    assert os.environ.get("REDIS_URL"), (
        "REDIS_URL must be set for unit tests (memory:// or a real redis URL)"
    )
    assert os.environ.get("DASHBOARD_API_KEY_ALLOW_EMPTY") == "true", (
        "DASHBOARD_API_KEY_ALLOW_EMPTY must be 'true' for unit tests"
    )
