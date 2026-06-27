"""GATE-141: Developer Pricing Time-Series — 5 gate + 5 edge-case tests.

Gate assertions (A1-A5):
  A1: Migration file 0071_developer_pricing_history exists
  A2: detect_price_moves and get_pricing_history importable
  A3: detect_price_moves returns empty list for threshold > 100 (DB-aware)
  A4: run_check_developer_price_moves importable from config.scheduler
  A5: utils.pricing_tracker module importable with __all__

Edge-case assertions (E1-E5):
  E1: _upsert_dev_pricing_history handles empty findings list
  E2: Pricing tracker returns empty list for unknown developer+market
  E3: __all__ exports match public functions
  E4: Prometheus counters registered in config.metrics
  E5: Thread-safety: concurrent detect_price_moves calls don't raise
"""
import pathlib
import pytest

pytestmark = pytest.mark.unit


def _db_available() -> bool:
    """Quick check: can we connect to the database?"""
    try:
        from utils.db import get_engine
        with get_engine().connect() as _conn:
            _conn.execute(pathlib.__import__("sqlalchemy").text("SELECT 1"))
        return True
    except Exception:
        return False


# ── Gate assertions ──────────────────────────────────────────────────────────


def test_a1_migration_file_exists():
    """Assert 0071_developer_pricing_history migration exists."""
    mig_dir = pathlib.Path("alembic/versions")
    files = [f.name for f in mig_dir.glob("0071_*.py") if f.is_file()]
    assert any("developer_pricing_history" in f for f in files), (
        f"No 0071_developer_pricing_history migration found in {mig_dir}"
    )


def test_a2_detect_price_moves_importable():
    """Assert detect_price_moves and get_pricing_history importable."""
    from utils.pricing_tracker import detect_price_moves, get_pricing_history

    assert callable(detect_price_moves)
    assert callable(get_pricing_history)


def test_a3_detect_price_moves_high_threshold_returns_empty():
    """Assert detect_price_moves returns empty list for improbable threshold.

    Requires live DB — skip gracefully when DB unavailable so CI
    without a running Docker stack doesn't fail.
    """
    if not _db_available():
        pytest.skip("No live DB — skipping DB-dependent assertion")
    from utils.pricing_tracker import detect_price_moves

    result = detect_price_moves("Yelahanka", threshold_pct=100.0, lookback_days=7)
    assert isinstance(result, list)
    assert len(result) == 0


def test_a4_check_developer_price_moves_importable():
    """Assert run_check_developer_price_moves importable from config.scheduler."""
    from config.scheduler import run_check_developer_price_moves

    assert callable(run_check_developer_price_moves)


def test_a5_pricing_tracker_module_has_all():
    """Assert utils.pricing_tracker has __all__ with both public functions."""
    import utils.pricing_tracker as pt

    assert hasattr(pt, "__all__")
    assert "detect_price_moves" in pt.__all__
    assert "get_pricing_history" in pt.__all__


# ── Edge-case assertions ─────────────────────────────────────────────────────


def test_e1_upsert_empty_findings():
    """Assert _upsert_dev_pricing_history handles empty list."""
    from scrapers.developer_scout import _upsert_dev_pricing_history

    count = _upsert_dev_pricing_history([], "Yelahanka")
    assert count == 0


def test_e2_pricing_tracker_returns_empty_for_unknown_market():
    """Assert detect_price_moves returns empty list for unknown market."""
    from utils.pricing_tracker import detect_price_moves

    result = detect_price_moves("NonexistentMarket", threshold_pct=3.0, lookback_days=7)
    assert isinstance(result, list)
    assert len(result) == 0


def test_e3_all_exports_match_public_functions():
    """Assert __all__ exports match actual public functions in pricing_tracker."""
    import utils.pricing_tracker as pt

    expected = {"detect_price_moves", "get_pricing_history"}
    actual = set(pt.__all__)
    assert expected == actual, f"__all__ mismatch: {actual} vs expected {expected}"
    # Verify each name is actually a callable
    for name in expected:
        assert callable(getattr(pt, name)), f"{name} not callable"
    # No private functions leaked
    for name in actual:
        assert not name.startswith("_"), f"Private function {name} leaked into __all__"


def test_e4_prometheus_counters_registered():
    """Assert pricing tracker Prometheus counters exist in config.metrics."""
    from config.metrics import pricing_tracker_runs_total, price_move_alerts_total

    # _counter() factory strips _total suffix (Prometheus convention appends it)
    assert pricing_tracker_runs_total._name in ("pricing_tracker_runs", "pricing_tracker_runs_total")
    assert "market" in pricing_tracker_runs_total._labelnames
    assert price_move_alerts_total._name in ("price_move_alerts", "price_move_alerts_total")
    assert "market" in price_move_alerts_total._labelnames


def test_e5_concurrent_calls_dont_raise():
    """Assert concurrent detect_price_moves calls complete without error.

    Uses threading to simulate concurrent scheduler invocations.
    Errors only — results may be empty (depends on DB state).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from utils.pricing_tracker import detect_price_moves

    markets = ["Yelahanka", "Devanahalli", "Hebbal"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut = {pool.submit(detect_price_moves, m, 10.0, 7): m for m in markets}
        for f in as_completed(fut):
            m = fut[f]
            exc = f.exception()
            assert exc is None, f"detect_price_moves({m}) raised: {exc}"
            result = f.result()
            assert isinstance(result, list)
