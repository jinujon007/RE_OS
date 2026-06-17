"""Migration 0062 — corridor_boundaries table tests (GATE-100, T-1190).

6 migration unit tests:
  - file exists
  - contains table and all 3 seed corridors
  - schema columns present (corridor_id, geom, seeded_at, gcc_hubs, updated_at)
  - GiST index on geom
  - geometry CHECK constraint
  - correct down_revision chain
"""

import pytest
import pathlib
import re
pytestmark = pytest.mark.unit

MIG_PATH = pathlib.Path("alembic/versions/0062_corridor_boundaries.py")


def test_migration_file_exists():
    assert MIG_PATH.exists(), "Migration file 0062_corridor_boundaries.py does not exist"


def test_migration_contains_table_name():
    content = MIG_PATH.read_text()
    assert "corridor_boundaries" in content


def test_migration_contains_seed_data():
    content = MIG_PATH.read_text()
    assert "nh44" in content
    assert "hebbal_yelahanka" in content
    assert "doddaballapur" in content
    assert "ST_MakeEnvelope" in content, "Must use ST_MakeEnvelope for bounding boxes"


def test_migration_has_required_columns():
    content = MIG_PATH.read_text()
    assert "corridor_id" in content
    assert "sa.String(50)" in content
    assert "postgresql.GEOMETRY" in content or "GEOMETRY" in content
    assert "4326" in content, "SRID 4326 required for WGS84"
    assert "seeded_at" in content
    assert "server_default" in content
    assert "gcc_hubs" in content
    assert "postgresql.ARRAY" in content
    assert "updated_at" in content


def test_migration_has_gist_index():
    content = MIG_PATH.read_text()
    assert "USING GIST" in content.upper() or "gist" in content.lower()
    assert "idx_corridor_boundaries_geom" in content


def test_migration_has_geom_validation():
    content = MIG_PATH.read_text()
    assert "ST_IsValid" in content, "Must have ST_IsValid CHECK constraint on geom"


def test_migration_correct_down_revision():
    content = MIG_PATH.read_text()
    match = re.search(r'down_revision[:\s\w,\[\]None]*=\s*"([^"]+)"', content)
    assert match, f"down_revision assignment not found in migration. Content snippet: {content[500:800]}"
    down_rev = match.group(1)
    assert down_rev == "0061_parcel_ownership_chain", (
        f"Expected down_revision='0061_parcel_ownership_chain', got '{down_rev}'"
    )
