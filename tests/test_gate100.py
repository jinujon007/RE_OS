"""GATE-100 declaration — Corridor Scorer v2 PostGIS Spatial Join.

3 assertions:
  (1) Migration 0062 exists and contains corridor_boundaries.
  (2) CorridorScorerV2 imports without error.
  (3) /api/corridor/score route registered in FastAPI app.
"""

import pytest
import pathlib

pytestmark = pytest.mark.unit

MIG_PATH = pathlib.Path("alembic/versions/0062_corridor_boundaries.py")


def test_migration_0062_exists():
    """Assertion (1): migration file exists and contains corridor_boundaries."""
    assert MIG_PATH.exists(), "Migration 0062 file not found"
    content = MIG_PATH.read_text()
    assert "corridor_boundaries" in content
    assert "nh44" in content
    assert "hebbal_yelahanka" in content
    assert "doddaballapur" in content


def test_corridor_scorer_v2_importable():
    """Assertion (2): CorridorScorerV2 imports without error."""
    from utils.corridor_scorer_v2 import CorridorScorerV2, CorridorScoreV2
    assert CorridorScorerV2 is not None
    assert CorridorScoreV2 is not None


def test_corridor_score_route_registered():
    """Assertion (3): /api/corridor/score route registered in FastAPI app."""
    from dashboard.app_fastapi import app
    paths = [r.path for r in app.routes]
    assert "/api/corridor/score" in paths, (
        f"/api/corridor/score not found in registered routes. "
        f"Available paths containing 'corridor': "
        f"{[p for p in paths if 'corridor' in p.lower()] or 'NONE'}"
    )
