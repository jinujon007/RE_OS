from __future__ import annotations

import os
import socket
import time
from pathlib import Path
from typing import Any, Generator

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def docker_stack_up(port: int = 5432, retries: int = 3, delay: float = 1.0) -> bool:
    for attempt in range(retries):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2.0):
                return True
        except (OSError, socket.error):
            if attempt < retries - 1:
                time.sleep(delay)
    return False


integration = pytest.mark.skipif(
    not docker_stack_up(),
    reason="Docker stack not running (port 5432 unreachable)",
)


@pytest.fixture(scope="module")
def db_engine() -> Any:
    from utils.db import get_engine

    return get_engine()


@pytest.fixture(autouse=True)
def _clean_stale_run_data(db_engine: Any) -> Generator[None, None, None]:
    from sqlalchemy import text

    try:
        with db_engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM agent_runs "
                    "WHERE micro_market ILIKE 'test_%' "
                    "OR (micro_market ILIKE 'yelahanka' AND created_at < NOW() - INTERVAL '1 hour')"
                )
            )
    except Exception:
        pass
    yield


@pytest.fixture(scope="module")
def dashboard_api_key() -> str:
    key = os.environ.get("DASHBOARD_API_KEY", "")
    if not key:
        allow_empty = os.environ.get("DASHBOARD_API_KEY_ALLOW_EMPTY", "").lower() in ("true", "1")
        if allow_empty:
            return ""
    return key
