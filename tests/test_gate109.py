"""GATE-109 declaration — Intelligence Accuracy.

5 assertions:
1. CalibrationResult importable with status field
2. DEVELOPER_ALIASES has >=10 keys
3. DemandIntel._compute_nri_demand_score source does NOT contain news_articles as primary
4. corridor_boundaries migration 0065 has data_source column
5. CalibrationResult.status != "UNCALIBRATED" with synthetic strong-linear data
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit

# Seed data shared with test_demand_calibration.py: 5-year linear trend R²≈0.97
_LINEAR_SEED_DATA = [
    (2019, 500, 5500.0),
    (2020, 900, 5800.0),
    (2021, 930, 6000.0),
    (2022, 960, 6200.0),
    (2023, 990, 6500.0),
]


def test_calibration_result_importable_with_status():
    from utils.demand_calibration import CalibrationResult
    cr = CalibrationResult()
    assert hasattr(cr, "verdict")
    assert cr.verdict == "UNCALIBRATED"
    assert hasattr(cr, "coefficient")
    assert hasattr(cr, "confidence_pct")


def test_developer_aliases_has_at_least_10_keys():
    from config.settings import DEVELOPER_ALIASES
    assert len(DEVELOPER_ALIASES) >= 10, (
        f"Expected >=10 developer aliases, got {len(DEVELOPER_ALIASES)}"
    )


def test_nri_signal_not_using_news_articles_as_primary():
    from intelligence.demand_intel import DemandIntel
    source = DemandIntel._compute_nri_demand_score.__code__
    source_lines = source.co_code
    source_text = source.co_filename

    with open(source_text, encoding="utf-8") as f:
        lines = f.readlines()

    fn_start = source.co_firstlineno
    fn_lines = lines[fn_start - 1:fn_start + source.co_nlocals + 80]

    body = "".join(fn_lines)
    first_buyer_type = body.find("buyer_type")
    first_news = body.find("news_articles")
    if first_buyer_type >= 0 and first_news >= 0:
        assert first_buyer_type < first_news, (
            "news_articles appears before registered_transactions buyer_type "
            "in _compute_nri_demand_score — NRI signal should primary from deeds"
        )


def test_corridor_boundaries_migration_has_data_source():
    migration_path = (
        Path(__file__).resolve().parent.parent
        / "alembic/versions/0065_corridor_boundaries_v2.py"
    )
    assert migration_path.exists()
    text = migration_path.read_text()
    assert "data_source" in text, "Migration 0065 must define data_source column"


def test_calibration_verdict_not_uncalibrated_with_good_data():
    from utils.demand_calibration import run_manyata_backcast

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_conn.execute.return_value.fetchall.return_value = _LINEAR_SEED_DATA
    result = run_manyata_backcast(mock_engine)
    assert result.verdict != "UNCALIBRATED", (
        f"Expected CALIBRATED with good synthetic data, got {result.verdict}: {result.detail}"
    )
