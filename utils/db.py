"""Shared SQLAlchemy engine factory for RE_OS."""
import threading

from sqlalchemy import create_engine

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
