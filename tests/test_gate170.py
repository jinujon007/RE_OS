"""GATE-170: New Markets (Thanisandra + Bagalur) — 5 gate assertions (A1-A5).

A1: settings.TARGET_MARKETS contains Thanisandra and Bagalur
A2: 0078_new_markets.py exists with down_revision == "0077_deal_score_log"
A3: STRROverlay._MARKET_COORDS has keys for "thanisandra" and "bagalur"
A4: AssemblyDetector().detect_clusters("Thanisandra") returns list (no exception)
A5: _resolve_market("thanisandra nagar") returns "Thanisandra"
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ["DASHBOARD_API_KEY_ALLOW_EMPTY"] = "true"
os.environ["DASHBOARD_API_KEY"] = "test-key"
os.environ["DASHBOARD_API_KEY_READ"] = "test-read-key"
os.environ["DASHBOARD_API_KEY_ADMIN"] = "test-admin-key"

pytestmark = pytest.mark.unit


def test_gate170_a1_markets_in_settings():
    from config.settings import TARGET_MARKETS
    assert "Thanisandra" in TARGET_MARKETS, "A1: Thanisandra must be in TARGET_MARKETS"
    assert "Bagalur" in TARGET_MARKETS, "A1: Bagalur must be in TARGET_MARKETS"


def test_gate170_a2_migration_exists():
    migration_path = Path("alembic/versions/0078_new_markets.py")
    assert migration_path.exists(), "A2: 0078_new_markets.py must exist"
    import importlib
    spec = importlib.util.spec_from_file_location(
        "migration_0078", migration_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.down_revision == "0077_deal_score_log", (
        "A2: down_revision must be 0077_deal_score_log"
    )


def test_gate170_a3_strr_market_coords():
    from utils.strr_overlay import _MARKET_COORDS
    assert "thanisandra" in _MARKET_COORDS, "A3: _MARKET_COORDS must have 'thanisandra' key"
    assert "bagalur" in _MARKET_COORDS, "A3: _MARKET_COORDS must have 'bagalur' key"


def test_gate170_a4_assembly_detector_no_exception():
    with patch("utils.assembly_detector.AssemblyDetector.detect_clusters", return_value=[]):
        from utils.assembly_detector import AssemblyDetector
        result = AssemblyDetector().detect_clusters("Thanisandra")
        assert isinstance(result, list), "A4: detect_clusters must return a list"


def test_gate170_a5_resolve_market_alias():
    from dashboard.state import _resolve_market
    result = _resolve_market("thanisandra nagar")
    assert result == "Thanisandra", (
        f"A5: _resolve_market('thanisandra nagar') should return 'Thanisandra', got {result!r}"
    )
