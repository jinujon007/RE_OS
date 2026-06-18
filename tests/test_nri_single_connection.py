"""Tests for T-1285: NRI single-connection fix (R2).

Verifies _compute_nri_demand_score accepts conn as first parameter and
contains zero engine.connect() calls.
"""

import inspect
from intelligence.demand_intel import DemandIntel


def test_nri_share_accepts_conn_first_parameter():
    """Method signature must be (self, conn, ds, mi) — conn is first real param."""
    sig = inspect.signature(DemandIntel._compute_nri_demand_score)
    params = list(sig.parameters.keys())
    assert params == ["self", "conn", "ds", "mi"], (
        f"Expected (self, conn, ds, mi), got {params}. "
        "Caller must be able to pass existing DB connection."
    )


def test_nri_share_no_engine_connect():
    """Method must not call engine.connect() — uses caller's connection."""
    source = inspect.getsource(DemandIntel._compute_nri_demand_score)
    connect_count = source.count("engine.connect()")
    assert connect_count == 0, (
        f"Found {connect_count} engine.connect() calls. "
        "Method should use the caller-provided `conn` parameter, not open its own."
    )


def test_nri_share_no_get_engine():
    """Method must not call get_engine() — uses caller's connection."""
    source = inspect.getsource(DemandIntel._compute_nri_demand_score)
    assert "get_engine" not in source, (
        "Method should not import or call get_engine — uses caller-provided connection."
    )
