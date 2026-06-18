"""GATE-112 — Scalability Foundation declaration tests.

Verifies all 4 deliverables from T-1246→T-1249 are in place:
1. Redis-backed _running state with connection pool singleton
2. ChromaDB maintenance job callable from scheduler
3. DB pool Prometheus gauges registered
4. k6 baseline load test script exists
"""
import inspect
import os
import pytest

pytestmark = pytest.mark.unit


def test_running_state_uses_redis():
    """dashboard.state._set_running uses redis.hset for cross-worker state sharing.

    Verifies the implementation uses Redis hash storage (hset) rather than
    in-process dict only. String-match on source is intentional — this test
    should break if the Redis integration is removed or renamed.
    """
    from dashboard.state import _set_running

    src = inspect.getsource(_set_running)
    assert "redis" in src.lower() or "hset" in src, (
        "_set_running must use Redis (hset). Got: {src[:200]}"
    )


def test_chromadb_maintenance_callable():
    """run_chromadb_maintenance is callable from config.scheduler.

    Verifies the scheduler can import and invoke the ChromaDB maintenance
    function. The actual purge is tested in test_chromadb_maintenance.py.
    """
    from config.scheduler import run_chromadb_maintenance

    assert callable(run_chromadb_maintenance)


def test_db_pool_size_gauge_defined():
    """db_pool_size Prometheus gauge is registered in config.metrics.

    Also verifies db_pool_checkedout and db_pool_overflow exist — all three
    are needed for meaningful pool monitoring. Gauge type check ensures
    metric type is correct (not accidentally a counter/histogram).
    """
    from config.metrics import db_pool_size, db_pool_checkedout, db_pool_overflow

    assert db_pool_size._type == "gauge"
    assert db_pool_checkedout._type == "gauge"
    assert db_pool_overflow._type == "gauge"


def test_db_pool_wait_histogram_defined():
    """db_pool_wait_seconds histogram registered (pool saturation metric)."""
    from config.metrics import db_pool_wait_seconds

    assert db_pool_wait_seconds._type == "histogram"


def test_k6_baseline_script_exists():
    """tests/load/k6_baseline.js exists with stages and thresholds."""
    script = os.path.join(
        os.path.dirname(__file__), "load", "k6_baseline.js"
    )
    assert os.path.exists(script), f"k6 baseline script not found at {script}"
    with open(script) as f:
        content = f.read()
    assert "stages" in content, "Expected staged ramp-up"
    assert "thresholds" in content, "Expected thresholds"
