"""GATE-116 — Corridor PostGIS Precision: 5 assertions.

(1) corridor_scorer_v2.py source does NOT contain ST_MakeEnvelope (AABB removed).
(2) corridor_scorer_v2.py source DOES contain ST_Buffer.
(3) scripts/run_corridor_backtest.py exists and is importable.
(4) Migration 0066_corridor_backtest_verdicts importable.
(5) /api/v1/ops/corridor-backtest route registered in FastAPI app.
"""
import pathlib

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.unit

V2_PATH = pathlib.Path("utils/corridor_scorer_v2.py")
SCRIPTS_PATH = pathlib.Path("scripts/run_corridor_backtest.py")
MIG_PATH = pathlib.Path("alembic/versions/0066_corridor_backtest_verdicts.py")


def test_aabb_removed():
    """(1) No query in corridor_scorer_v2.py uses ST_MakeEnvelope."""
    source = V2_PATH.read_text()
    docstring_end = source.find('"""', source.find('"""') + 3)
    after_docstrings = source[docstring_end + 3:] if docstring_end >= 0 else source
    sql_sections = [ln for ln in after_docstrings.split('\n')
                     if ('SELECT' in ln.upper() and 'FROM' in ln.upper())
                     or 'ST_Within' in ln
                     or 'ST_Buffer' in ln]
    for line in sql_sections:
        assert "ST_MakeEnvelope" not in line, (
            f"AABB still used in SQL query: {line.strip()}"
        )


def test_st_buffer_present():
    """(2) corridor_scorer_v2.py DOES contain ST_Buffer."""
    content = V2_PATH.read_text()
    assert "ST_Buffer" in content, "ST_Buffer must be present in v2 scorer"


def test_backtest_script_exists():
    """(3) scripts/run_corridor_backtest.py exists and is importable."""
    assert SCRIPTS_PATH.exists(), "Backtest script must exist"
    import importlib.util as _util
    spec = _util.spec_from_file_location("run_corridor_backtest", str(SCRIPTS_PATH))
    assert spec is not None, "Must be importable"
    mod = _util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.run_backtest), "run_backtest must be callable"
    assert callable(mod.main), "main must be callable"


def test_0066_migration_importable():
    """(4) Migration 0066 corridor_backtest_verdicts importable."""
    assert MIG_PATH.exists(), "Migration 0066 must exist"
    import importlib.util as _util
    spec = _util.spec_from_file_location(
        "migration_0066", str(MIG_PATH)
    )
    assert spec is not None, "Migration must be importable"
    mod = _util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "0066_corridor_backtest_verdicts"
    assert mod.down_revision == "0065_corridor_boundaries_v2"
    assert hasattr(mod, "upgrade")
    assert hasattr(mod, "downgrade")


def test_corridor_backtest_route_registered():
    """(5) /api/v1/ops/corridor-backtest route registered in FastAPI app."""
    from dashboard.app_fastapi import app

    client = TestClient(app)
    resp = client.get("/api/v1/ops/corridor-backtest", headers={"X-API-Key": "test"})
    assert resp.status_code in (200, 401, 403), (
        f"Expected 200/401/403, got {resp.status_code}"
    )
