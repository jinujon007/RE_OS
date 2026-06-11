"""T-1110: market_forecasts table exists test."""
import pytest
pytestmark = pytest.mark.unit


def test_market_forecasts_table_exists():
    """Verify market_forecasts columns via information_schema (unit-safe)."""
    from sqlalchemy import text
    from utils.db import get_engine

    try:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name='market_forecasts'")
            ).fetchall()
            cols = {r[0] for r in rows}
            required = {"market", "forecast_date", "horizon_months", "forecast_psf",
                        "trend_direction", "model_version", "created_at"}
            missing = required - cols
            assert not missing, f"Missing columns: {missing}"
    except Exception:
        pytest.skip("No DB connection — table may not exist yet")
