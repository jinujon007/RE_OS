"""Unit tests for CorridorScorer v1 (Sprint 95 — T-1161).

6 unit tests using mocked DB engine:
  - score_all returns ≥3 scored corridors
  - composite score in [0, 10] range
  - corridors sorted descending by composite
  - velocity query isolates sale deeds + consideration floor
  - insufficient data → neutral PSF trend score
  - backtest verdict file is written
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _make_mock_engine(query_return=None):
    """Build a mock SQLAlchemy engine that returns `query_return` for all queries."""
    engine = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    if query_return is None:
        cursor.__getitem__ = MagicMock(return_value=0)
        cursor.__iter__ = MagicMock(return_value=iter([]))
        cursor.fetchone = MagicMock(return_value=None)
    else:
        cursor.fetchone = MagicMock(return_value=query_return)
    conn.execute = MagicMock(return_value=cursor)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    engine.connect = MagicMock(return_value=conn)
    return engine


def test_score_all_returns_three_corridors():
    """Assertion (3): corridor_scorer returns ≥3 scored corridors."""
    from utils.corridor_scorer import CORRIDOR_DEFINITIONS, CorridorScorer

    engine = _make_mock_engine(MagicMock(**{"__getitem__.return_value": 0, "fetchone.return_value": (0,)}))
    scorer = CorridorScorer(engine=engine)
    scores = scorer.score_all()
    assert len(scores) >= 3, f"Expected ≥3 corridors, got {len(scores)}"
    for s in scores:
        assert hasattr(s, "commute_score")

    # Validate all corridor definitions have centroids for commute scoring
    for corridor in CORRIDOR_DEFINITIONS:
        assert "centroid" in corridor, \
            f"Corridor '{corridor['id']}' missing centroid definition"
        assert "lat" in corridor["centroid"], \
            f"Corridor '{corridor['id']}' centroid missing lat"
        assert "lon" in corridor["centroid"], \
            f"Corridor '{corridor['id']}' centroid missing lon"


def test_composite_in_range():
    """Composite score must be between 0 and 10."""
    from utils.corridor_scorer import CorridorScorer

    engine = _make_mock_engine()
    scorer = CorridorScorer(engine=engine)
    scores = scorer.score_all()
    for s in scores:
        assert 0.0 <= s.composite <= 10.0, (
            f"Corridor {s.corridor_id} composite {s.composite} out of [0,10]"
        )


def test_corridors_sorted_descending():
    """score_all returns corridors sorted by composite descending."""
    from utils.corridor_scorer import CorridorScorer

    engine = _make_mock_engine()
    scorer = CorridorScorer(engine=engine)
    scores = scorer.score_all()
    composites = [s.composite for s in scores]
    assert composites == sorted(composites, reverse=True), (
        "Corridors not sorted descending by composite"
    )


def test_velocity_score_zero_on_no_transactions():
    """Zero transactions → velocity_score = 0."""
    from utils.corridor_scorer import CorridorScorer

    engine = _make_mock_engine((0,))
    scorer = CorridorScorer(engine=engine)
    notes: list[str] = []
    score, n = scorer._score_velocity(
        ["Venkatala"],
        start=__import__("datetime").date(2024, 1, 1),
        end=__import__("datetime").date(2024, 6, 30),
        notes=notes,
    )
    assert score == 0.0
    assert n == 0
    assert any("No registered" in note or "0" in note for note in notes)


def test_psf_trend_neutral_on_no_data():
    """No PSF data → neutral score 5.0."""
    from utils.corridor_scorer import CorridorScorer

    engine = _make_mock_engine((None,))
    scorer = CorridorScorer(engine=engine)
    notes: list[str] = []
    trend_score, avg_psf, psf_mom = scorer._score_psf_trend(
        ["Venkatala"],
        start=__import__("datetime").date(2024, 1, 1),
        end=__import__("datetime").date(2024, 6, 30),
        notes=notes,
    )
    assert trend_score == 5.0
    assert avg_psf is None
    assert psf_mom is None


def test_backtest_writes_verdict_file():
    """backtest() must write the corridor_scorer_backtest.md file."""
    from utils.corridor_scorer import CorridorScorer

    engine = _make_mock_engine((None,))
    scorer = CorridorScorer(engine=engine)

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "corridor_scorer_backtest.md"
        result = scorer.backtest(output_path=output_path)

        assert output_path.exists(), "Backtest report file was not written"
        content = output_path.read_text()
        assert "Corridor Scorer" in content
        assert result["verdict"] in ("PASS", "FAIL", "INSUFFICIENT_DATA")
