"""Shared route contract inventory for GATE-166 and api_full_coverage tests.

Design decisions:
  - Lives outside test discovery (no test_ prefix) so both test files import
    it without the test-imports-test anti-pattern.
  - Every route is declared as a (HTTP_METHOD, PATH) tuple — "route contract".
    The test harness verifies method+path simultaneously, catching accidental
    GET→POST or POST→GET method changes that a path-only check would miss.
  - Contracts are grouped by domain (INTEL, OPS, DEAL, DASHBOARD, BOARD,
    PIPELINE, HEALTH) so failures pinpoint the affected domain immediately.
  - A module-level assertion fires at import time if any contract count
    deviates from the expected number, preventing silent drift.
"""
from __future__ import annotations

from typing import FrozenSet, List, Tuple

# ── Type alias ──────────────────────────────────────────────────────────────

RouteContract = Tuple[str, str]  # (HTTP_METHOD, PATH)


# ── Factory helpers ─────────────────────────────────────────────────────────


def _get(path: str) -> RouteContract:
    return ("GET", path)


def _post(path: str) -> RouteContract:
    return ("POST", path)


def _patch(path: str) -> RouteContract:
    return ("PATCH", path)


def _delete(path: str) -> RouteContract:
    return ("DELETE", path)


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT INVENTORIES
# ═══════════════════════════════════════════════════════════════════════════
#
# Every list is followed by a length assertion at import time so that an
# accidental addition or removal is caught immediately (not when the test
# suite runs 10 minutes later).
# ═══════════════════════════════════════════════════════════════════════════

# ── INTEL (20 contracts) ────────────────────────────────────────────────────
# Gate GATE-166 A1.
_INTEL = [
    _get("/api/v1/intel/cards"),
    _get("/api/v1/intel/search"),
    _get("/api/v1/intel/download"),
    _get("/api/v1/intel/propcontext-delta/{market}"),
    _get("/api/v1/intel/assembly-timeline"),
    _get("/api/v1/intel/digest/latest"),
    _get("/api/v1/intel/investor/compare"),
    _get("/api/v1/intel/investor/weekly-digest"),
    _post("/api/v1/intel/investor/export-obsidian"),
    _get("/api/v1/intel/vel/competitive-report"),
    _get("/api/v1/intel/vel/pricing-sensitivity"),
    _post("/api/v1/intel/vel/export-obsidian"),
    _get("/api/v1/intel/corridors/backtest-accuracy"),
    _get("/api/v1/intel/parcel-graph"),
    _get("/api/v1/intel/parcel-graph/summary"),
    _get("/api/v1/intel/parcel-graph/hotspot-alert"),
    _get("/api/v1/intel/parcel-graph/stats"),
    _get("/api/v1/intel/strr-overlay"),
    _get("/api/v1/intel/deal-score"),
    _get("/api/v1/intel/deal-score/history"),
]
assert len(_INTEL) == 20, f"INTEL_ROUTES: expected 20, got {len(_INTEL)}"

# ── OPS (10 contracts) ──────────────────────────────────────────────────────
# Gate GATE-166 A2.
_OPS = [
    _get("/api/v1/ops/kill-criteria"),
    _get("/api/v1/ops/calibration"),
    _get("/api/v1/ops/digest-quality"),
    _get("/api/v1/ops/slo"),
    _get("/api/v1/ops/v2-readiness"),
    _post("/api/v1/ops/v2-declare"),
    _get("/api/v1/ops/handover-doc"),
    _get("/api/v1/ops/ledger/full"),
    _get("/api/v1/ops/ledger/accuracy"),
    _get("/api/v1/ops/failed-records"),
]
assert len(_OPS) == 10, f"OPS_ROUTES: expected 10, got {len(_OPS)}"

# ── DEAL / PROJECT MANAGEMENT (9 contracts) ─────────────────────────────────
# Gate GATE-166 A3.  POST/GET on the same path are separate route contracts
# (e.g. POST /api/v1/deals vs GET /api/v1/deals).  The spec says "8 routes"
# but evaluating the individual method paths yields 9, which is correct.
_DEAL = [
    _post("/api/v1/evaluate"),
    _get("/api/v1/evaluate/{job_id}"),
    _get("/api/v1/opportunity/queue"),
    _post("/api/v1/deals"),
    _get("/api/v1/deals"),
    _post("/api/v1/projects"),
    _get("/api/v1/projects"),
    _post("/api/v1/landowners"),
    _get("/api/v1/landowners"),
]
assert len(_DEAL) == 9, f"DEAL_ROUTES: expected 9, got {len(_DEAL)}"

# ── DASHBOARD HTML PANELS (18 contracts) ────────────────────────────────────
# Gate GATE-166 A4.  Expanded from the spec's "15+" to the actual 18 panel
# routes served by data_router.
_DASH = [
    _get("/api/v1/parcel-graph"),
    _get("/api/v1/assembly-signals"),
    _get("/api/v1/deed-throughput"),
    _get("/api/v1/decision-journal"),
    _get("/api/v1/memory"),
    _get("/api/v1/demand"),
    _get("/api/v1/investor-brief"),
    _get("/api/v1/forecast-accuracy"),
    _get("/api/v1/parcel"),
    _get("/api/v1/optimizer"),
    _get("/api/v1/shareholders"),
    _get("/api/v1/content-studio"),
    _get("/api/v1/pr-studio"),
    _get("/api/v1/digest"),
    _get("/api/v1/process-audit"),
    _get("/api/v1/data-quality"),
    _get("/api/v1/govt-policy"),
    _get("/api/v1/projects"),
]
assert len(_DASH) == 18, f"DASHBOARD_ROUTES: expected 18, got {len(_DASH)}"

# ── BOARD ROOM (8 contracts) ────────────────────────────────────────────────
_BOARD = [
    _post("/api/v1/board/session"),
    _get("/api/v1/board/session/{session_id}"),
    _get("/api/v1/board/sessions"),
    _get("/api/v1/board/sessions/{session_id}/obsidian-export"),
    _get("/api/v1/engineering/brief"),
    _get("/api/v1/alerts"),
    _get("/api/v1/finance/brief"),
    _get("/api/v1/legal/brief"),
]
assert len(_BOARD) == 8, f"BOARD_ROUTES: expected 8, got {len(_BOARD)}"

# ── PIPELINE (8 contracts) ──────────────────────────────────────────────────
_PIPELINE = [
    _post("/api/v1/run/{market}"),
    _delete("/api/v1/run/{market}"),
    _get("/api/v1/status"),
    _get("/api/v1/agents"),
    _post("/api/v1/agents/{agent_id}/command"),
    _get("/api/v1/agents/{agent_id}/actions"),
    _get("/api/v1/sentinel/status"),
    _get("/api/v1/logs/stream"),
]
assert len(_PIPELINE) == 8, f"PIPELINE_ROUTES: expected 8, got {len(_PIPELINE)}"

# ── HEALTH (4 contracts) ────────────────────────────────────────────────────
_HEALTH = [
    _get("/api/v1/health"),
    _get("/api/v1/health/live"),
    _get("/api/v1/alert/test"),
    _get("/api/v1/mcp/health"),
]
assert len(_HEALTH) == 4, f"HEALTH_ROUTES: expected 4, got {len(_HEALTH)}"


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC EXPORTS — immutable view of inventories
# ═══════════════════════════════════════════════════════════════════════════

INTEL_ROUTES: List[RouteContract] = list(_INTEL)
OPS_ROUTES: List[RouteContract] = list(_OPS)
DEAL_ROUTES: List[RouteContract] = list(_DEAL)
DASHBOARD_ROUTES: List[RouteContract] = list(_DASH)
BOARD_ROUTES: List[RouteContract] = list(_BOARD)
PIPELINE_ROUTES: List[RouteContract] = list(_PIPELINE)
HEALTH_ROUTES: List[RouteContract] = list(_HEALTH)

# Path-only views (backward compat for path-level assertions)
INTEL_PATHS: List[str] = [p for _, p in _INTEL]
OPS_PATHS: List[str] = [p for _, p in _OPS]
DEAL_PATHS: List[str] = [p for _, p in _DEAL]
DASHBOARD_PATHS: List[str] = [p for _, p in _DASH]

# All 76 route contracts flattened — frozenset for O(1) membership checks
ALL_CONTRACTS: FrozenSet[RouteContract] = frozenset(
    _INTEL + _OPS + _DEAL + _DASH + _BOARD + _PIPELINE + _HEALTH
)

# All unique paths (useful for count validation)
ALL_PATHS: List[str] = sorted({p for _, p in ALL_CONTRACTS})

# Known cross-router duplicates (intentional — same panel served from
# data_router and ops_router).  The test suite asserts that only these
# (method, path) pairs are registered more than once.
KNOWN_CROSS_ROUTER_DUPES: FrozenSet[RouteContract] = frozenset({
    ("GET", "/api/v1/optimizer"),
    ("GET", "/api/v1/shareholders"),
    ("GET", "/api/v1/process-audit"),
    ("GET", "/api/v1/projects"),
    ("GET", "/api/v1/ops/slo"),
})


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS — used by both test files
# ═══════════════════════════════════════════════════════════════════════════


def _extract_routes(app) -> tuple[FrozenSet[RouteContract], List[Tuple[str, str]]]:
    """Extract registered route contracts and duplicates from a FastAPI app.

    Returns
        (all_contracts: FrozenSet[(method, path)], duplicates: List[(method, path)])
    """
    seen: dict[RouteContract, int] = {}
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if methods and path:
            for m in methods:
                key = (m, path)
                seen[key] = seen.get(key, 0) + 1
    all_contracts = frozenset(seen.keys())
    duplicates = [k for k, v in seen.items() if v > 1]
    return all_contracts, duplicates


def registered_contracts(app) -> FrozenSet[RouteContract]:
    """Return {(method, path)} from a FastAPI app instance."""
    contracts, _ = _extract_routes(app)
    return contracts


def registered_paths(app) -> FrozenSet[str]:
    """Return {path} from a FastAPI app instance."""
    return frozenset(
        getattr(r, "path", None) for r in app.routes if hasattr(r, "path")
    )


def duplicate_contracts(app) -> List[RouteContract]:
    """Return [(method, path)] pairs registered more than once."""
    _, duplicates = _extract_routes(app)
    return duplicates


def missing_contracts(
    app, expected: List[RouteContract]
) -> List[RouteContract]:
    """Return contracts in *expected* that are NOT registered in *app*."""
    existing = registered_contracts(app)
    return [c for c in expected if c not in existing]


def format_missing(missing: List[RouteContract]) -> str:
    """Format missing route contracts for assertion messages."""
    if not missing:
        return ""
    lines = [f"Missing {len(missing)} route contract(s):"]
    lines += [f"    {m[0]:>6} {m[1]}" for m in missing]
    return "\n".join(lines)
