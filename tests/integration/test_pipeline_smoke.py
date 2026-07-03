from __future__ import annotations

import subprocess
import sys
import time as _time
from pathlib import Path
from typing import Any

import pytest

from tests.integration.conftest import REPO_ROOT, integration

pytestmark = [integration, pytest.mark.slow]

_CREW_TIMEOUT_S = 300
_DB_LOOKBACK_WINDOW = "10 minutes"


@pytest.mark.test_id("G164-A1")
@pytest.mark.integration
def test_pipeline_yelahanka_smoke(db_engine: Any) -> None:
    """Run market_intel_crew for Yelahanka via subprocess, verify DB side-effects.

    Preconditions:
    - Docker stack up (DB + agents containers reachable).
    - ``crews/market_intel_crew.py`` exists at the expected path.

    Postconditions:
    - Subprocess exits 0 within 300s.
    - ``agent_runs`` table has >=1 row for ``yelahanka`` within the
      ``_DB_LOOKBACK_WINDOW`` from test start.
    - ``micro_markets`` table has a row matching ``yelahanka`` with non-empty slug.

    Edge cases covered:
    - Crew script missing (explicit AssertionError with path).
    - Subprocess timeout (pytest-timeout or subprocess.TimeoutExpired).
    - DB row created by a *different* run in the lookback window (acceptable:
      at least one run happened).
    """
    crew_script = REPO_ROOT / "crews" / "market_intel_crew.py"
    assert crew_script.exists(), (
        f"Pipeline crew script not found at expected path: {crew_script}"
    )

    start_ts = _time.time()
    result = subprocess.run(
        [sys.executable, str(crew_script), "--market", "Yelahanka"],
        capture_output=True,
        text=True,
        timeout=_CREW_TIMEOUT_S,
    )
    elapsed = _time.time() - start_ts

    assert result.returncode == 0, (
        f"Pipeline exited with code {result.returncode} after {elapsed:.0f}s.\n"
        f"STDOUT (last 2KB): {result.stdout[-2048:]}\n"
        f"STDERR (last 2KB): {result.stderr[-2048:]}"
    )

    from sqlalchemy import text

    with db_engine.connect() as conn:
        agent_count = conn.execute(
            text(
                "SELECT COUNT(*) FROM agent_runs "
                "WHERE micro_market ILIKE 'yelahanka' "
                "AND created_at > (NOW() - INTERVAL :window)::timestamp"
            ),
            {"window": _DB_LOOKBACK_WINDOW},
        ).scalar()
        assert agent_count is not None and agent_count >= 1, (
            f"Expected >=1 agent_runs row for Yelahanka within "
            f"{_DB_LOOKBACK_WINDOW}, got {agent_count}"
        )

        mm_row = conn.execute(
            text(
                "SELECT id, name, slug FROM micro_markets "
                "WHERE name ILIKE 'yelahanka' LIMIT 1"
            )
        ).fetchone()
        assert mm_row is not None, (
            "micro_markets table has no row matching 'yelahanka'"
        )
        _id, name, slug = mm_row
        assert "yelahanka" in name.lower(), (
            f"Expected name containing 'yelahanka', got '{name}' (id={_id})"
        )
        assert slug, (
            f"Expected non-empty slug for market '{name}', got '{slug}'"
        )
