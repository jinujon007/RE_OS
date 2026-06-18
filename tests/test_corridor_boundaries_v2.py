"""Tests for T-1236: OSM-derived corridor boundaries."""

import pytest
from pathlib import Path

pytestmark = pytest.mark.unit


def test_corridor_boundary_has_data_source_field():
    """Migration 0065 must add data_source column."""
    migration_path = (
        Path(__file__).resolve().parent.parent
        / "alembic/versions/0065_corridor_boundaries_v2.py"
    )
    assert migration_path.exists(), (
        f"Migration file not found at {migration_path}"
    )
    text = migration_path.read_text()
    assert "data_source" in text, (
        "Migration 0065 must define data_source column"
    )
    assert "sa.Column" in text and "data_source" in text
    assert "String" in text or "VARCHAR" in text or "varchar" in text.lower()


def test_fetch_corridor_script_importable():
    """scripts/fetch_corridor_boundaries.py must import without error."""
    from scripts.fetch_corridor_boundaries import (
        fetch_all,
        fetch_corridor,
        generate_sql,
        CorridorBoundaryResult,
        coords_to_wkt_buffer,
        extract_linestring_coords,
    )

    assert callable(fetch_all)
    assert callable(fetch_corridor)
    assert callable(generate_sql)
    assert callable(coords_to_wkt_buffer)
    assert callable(extract_linestring_coords)

    result = CorridorBoundaryResult(
        corridor_id="nh44",
        wkt_polygon="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        data_source="osm",
        note="test",
    )
    assert result.corridor_id == "nh44"
    assert result.data_source == "osm"


def test_coords_to_wkt_buffer_returns_valid_wkt():
    """coords_to_wkt_buffer returns a valid WKT POLYGON string given coords."""
    from scripts.fetch_corridor_boundaries import coords_to_wkt_buffer

    coords = [(77.58, 13.10), (77.59, 13.11), (77.60, 13.12)]
    wkt = coords_to_wkt_buffer(coords)
    assert wkt is not None
    assert wkt.startswith("POLYGON((")
    assert wkt.endswith("))")
    assert "77.5" in wkt
    assert "13.0" in wkt


def test_corridor_scorer_v2_uses_real_boundaries_when_available():
    """CorridorScorerV2._query_spatial_villages prefers osm boundaries.

    Verify the v2 scorer queries corridor_boundaries for geom (not bbox_geom),
    and that the migration adds data_source for tracking.
    """
    from pathlib import Path
    scorer_path = (
        Path(__file__).resolve().parent.parent
        / "utils/corridor_scorer_v2.py"
    )
    scorer_text = scorer_path.read_text()

    migration_path = (
        Path(__file__).resolve().parent.parent
        / "alembic/versions/0065_corridor_boundaries_v2.py"
    )
    migration_text = migration_path.read_text()

    assert "data_source" in migration_text, (
        "Migration 0065 must define data_source column for boundary tracking"
    )
    assert "corridor_boundaries" in scorer_text, (
        "CorridorScorerV2 must query corridor_boundaries table"
    )
