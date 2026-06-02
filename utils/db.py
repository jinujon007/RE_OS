"""Shared SQLAlchemy engine factory for RE_OS."""
import threading
from contextlib import contextmanager

from sqlalchemy import create_engine, text

from config.settings import DATABASE_URL

_engine = None
_lock = threading.Lock()


def get_engine(pool_size: int = 5, max_overflow: int = 2):
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
        with timed_query("v_market_brief"):
            result = conn.execute(text("SELECT ..."))
    """
    hist = _get_db_query_histogram()
    with hist.labels(query_name=query_name).time():
        yield
