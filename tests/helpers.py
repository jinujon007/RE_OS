"""Shared test utilities — no conftest side effects, pure functions.

Public API
----------
db_reachable
    Socket-level PostgreSQL availability check.  Returns ``True`` when a TCP
    connection to the resolved DATABASE_URL host:port succeeds within the
    configured timeout.  Pure function — no side effects, thread-safe.

make_mock_engine
    Build a mock SQLAlchemy ``Engine`` that surfaces *rows* via its
    ``.execute()`` path.  Used by multiple test modules to unit-test
    DB-access logic without a live database.

``tests.helpers`` was created in Sprint 84 (T-1106) to consolidate the
``db_reachable`` logic that was duplicated across two test files.
``make_mock_engine`` was previously anonymous (defined inline in
``test_distressed_developer.py``); Sprint 84 Round 2 audit promoted it
here for reuse.
"""

from __future__ import annotations

import os
import socket
from typing import Any, List, Optional
from unittest.mock import MagicMock
from urllib.parse import urlparse


def _resolve_db_url() -> Optional[str]:
    """Resolve the PostgreSQL URL using the same logic as ``alembic/env.py``.

    Precedence
    ----------
    1. ``DATABASE_URL`` environment variable (full connection string).
    2. ``DB_PASSWORD`` environment variable — constructs
       ``postgresql://re_os_user:{password}@localhost:5432/re_os``.
    3. ``None`` — no DB configuration found.

    Returns
    -------
    str or None
        A ``postgresql://`` URL, or ``None`` if neither variable is set.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    db_password = os.environ.get("DB_PASSWORD", "")
    if db_password:
        return f"postgresql://re_os_user:{db_password}@localhost:5432/re_os"
    return None


def db_reachable(timeout: float = 2.0) -> bool:
    """Check whether PostgreSQL is accepting TCP connections.

    Parses ``DATABASE_URL`` (or its ``DB_PASSWORD`` fallback) with
    ``urllib.parse.urlparse`` to extract the host and port, then attempts a
    TCP socket handshake.

    Why socket instead of a full client hello?
      - Zero dependencies beyond the stdlib.
      - Works even when ``psycopg2`` is not installed (common in CI).
      - Completes in *timeout* seconds instead of waiting for a driver-level
        connection timeout (which can be 30+ seconds).

    Parameters
    ----------
    timeout : float, optional
        Socket timeout in seconds (default 2.0).

    Returns
    -------
    bool
        ``True`` if the TCP handshake succeeded; ``False`` if no DB URL is
        configured, the host cannot be resolved, or the connection timed out.
    """
    url = _resolve_db_url()
    if not url:
        return False

    parsed = urlparse(url)
    host: str = parsed.hostname or "localhost"
    port: int = parsed.port or 5432

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def make_mock_engine(rows: List[Any]) -> MagicMock:
    """Build a mock SQLAlchemy Engine whose ``.execute()`` returns *rows*.

    The returned ``MagicMock`` simulates the minimal Engine surface used by
    RE_OS's DB-access layer:

    .. code-block:: python

        engine = make_mock_engine([("foo", 42)])
        with engine.begin() as conn:
            result = conn.execute(text("SELECT ..."))
            assert result.fetchall() == [("foo", 42)]

    Parameters
    ----------
    rows : list
        Sequence of row tuples (or ``SimpleNamespace`` objects, etc.) that
        ``fetchall()`` should return.  An empty list ``[]`` is valid.

    Returns
    -------
    MagicMock
        Engine mock whose ``.connect().__enter__().execute()`` returns a
        result mock with ``fetchall``, ``scalar``, and ``fetchone``.
    """
    result_mock = MagicMock()
    result_mock.fetchall.return_value = rows
    result_mock.fetchone.return_value = rows[0] if rows else None
    result_mock.scalar.return_value = rows[0][0] if rows else None

    conn_mock = MagicMock()
    conn_mock.__enter__.return_value.execute.return_value = result_mock

    engine_mock = MagicMock()
    engine_mock.connect.return_value = conn_mock
    engine_mock.begin.return_value.__enter__.return_value = conn_mock
    return engine_mock
