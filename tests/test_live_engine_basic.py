"""Basic health checks for the live_engine integration-test fixture.

Verifies the fixture can connect to a real PostgreSQL instance and that
the expected schema tables exist after Alembic migrations.
"""

import pytest
from sqlalchemy import inspect, text

pytestmark = pytest.mark.integration


def test_live_engine_connects(live_engine):
    """Assert live_engine yields a working connection."""
    with live_engine.connect() as conn:
        result = conn.execute(text("SELECT 1 AS ok")).fetchone()
    assert result is not None
    assert result[0] == 1, f"Expected 1, got {result[0]}"


def test_live_engine_tables_exist(live_engine):
    """Assert core tables exist after Alembic migrations."""
    inspector = inspect(live_engine)
    table_names = set(inspector.get_table_names())

    required_tables = {
        "rera_projects",
        "registered_transactions",
        "parcels",
        "micro_markets",
        "assembly_signals",
    }
    missing = required_tables - table_names
    assert not missing, (
        f"Required tables missing after alembic upgrade: {missing}. "
        f"Available: {sorted(table_names)}"
    )
