"""Shared SQLAlchemy engine factory for RE_OS."""

import logging
import threading
import time as _time_mod
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text

from config.settings import DATABASE_URL

_engine = None
_lock = threading.Lock()
_pool_exhaustion_lock = threading.Lock()
_pool_is_exhausted = False

# ── DB connection pool Prometheus gauges (T-1248) ────────────────────────────
# Metrics updated via pool event listeners — no polling, no health endpoint
# dual-write. The gauge imports are lazy to avoid circular imports with
# config.metrics when this module is loaded during app startup.
# Pool wait time histogram added per industry standard for scalability monitoring.


def _wire_pool_metrics(engine_ref):
    """Attach pool event listeners for Prometheus gauges.

    Pool wait time is tracked by wrapping pool._do_get via monkey-patch
    (see _patch_pool_wait_time). Gauges update on connect/checkout/checkin.
    """
    try:
        from config.metrics import db_pool_size, db_pool_checkedout, db_pool_overflow

        @event.listens_for(engine_ref.pool, "connect")
        def _pool_connect(dbapi_con, con_record):
            db_pool_size.set(engine_ref.pool.size())
            db_pool_overflow.set(engine_ref.pool.overflow())

        @event.listens_for(engine_ref.pool, "checkout")
        def _pool_checkout(dbapi_con, con_record, con_proxy):
            db_pool_checkedout.set(engine_ref.pool.checkedout())
            db_pool_overflow.set(engine_ref.pool.overflow())
            _check_pool_exhaustion(engine_ref)

        @event.listens_for(engine_ref.pool, "checkin")
        def _pool_checkin(dbapi_con, con_record):
            db_pool_checkedout.set(engine_ref.pool.checkedout())
    except Exception:
        pass


def _check_pool_exhaustion(engine_ref):
    """T-1263: Fire Discord alert when pool is fully saturated.

    Uses AlertSuppressor for dedup (4-hour cooldown consistent with other alerts).
    _pool_is_exhausted flag prevents redundant work while already suppressed (R1.7).
    _pool_exhaustion_lock protects state transitions (R1.8).
    """
    global _pool_is_exhausted
    if _pool_is_exhausted:
        return
    pool = engine_ref.pool
    max_connections = pool.size() + pool.overflow()
    checked_out = pool.checkedout()
    if checked_out >= max_connections and max_connections > 0:
        with _pool_exhaustion_lock:
            if _pool_is_exhausted:
                return
            try:
                from utils.discord_notifier import AlertSuppressor, send_ops_alert
                if not AlertSuppressor.suppress("db_pool_exhausted", cooldown_hours=4):
                    send_ops_alert(
                        "db_pool_exhausted",
                        f"DB connection pool exhausted — {checked_out}/{max_connections} checked out. "
                        f"Consider increasing pool_size or reducing concurrent requests.",
                    )
                _pool_is_exhausted = True
            except Exception:
                logging.getLogger("re_os.db").warning(
                    "Pool exhausted (%d/%d) but Discord alert failed",
                    checked_out, max_connections,
                )
    else:
        _pool_is_exhausted = False


def _patch_pool_wait_time(pool):
    """Monkey-patch pool._do_get to record pool_wait_seconds histogram.

    Industry-standard practice for connection pool saturation monitoring.
    Wraps the original _do_get with a timing decorator.
    """
    try:
        from config.metrics import db_pool_wait_seconds
        import time as _time_mod

        original_do_get = pool._do_get

        def _timed_do_get():
            t0 = _time_mod.perf_counter()
            try:
                return original_do_get()
            finally:
                db_pool_wait_seconds.observe(_time_mod.perf_counter() - t0)

        pool._do_get = _timed_do_get
    except Exception:
        pass


def get_engine(pool_size: int = 10, max_overflow: int = 5):
    """Return the shared SQLAlchemy engine. Thread-safe singleton."""
    global _engine
    if _engine is None:
        with _lock:
            if _engine is None:
                _engine = create_engine(
                    DATABASE_URL,
                    pool_pre_ping=True,
                    pool_size=pool_size,
                    max_overflow=max_overflow,
                )
                _wire_pool_metrics(_engine)
                _patch_pool_wait_time(_engine.pool)
    return _engine


# ── Query timing histogram ─────────────────────────────────────────────────


def _get_db_query_histogram():
    """Lazy-import to avoid circular import at module level on app start."""
    from config.metrics import db_query_duration_seconds

    return db_query_duration_seconds


@contextmanager
def timed_query(query_name: str):
    """Context manager that records query duration to Prometheus.
    Usage:
        with timed_query("v_market_brief_mat"):
            result = conn.execute(text("SELECT ..."))
    """
    hist = _get_db_query_histogram()
    with hist.labels(query_name=query_name).time():
        yield
