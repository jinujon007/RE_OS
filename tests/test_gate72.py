from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from dashboard.app_fastapi import app

pytestmark = pytest.mark.unit


def test_gate72_distressed_plugin_run_returns_list():
    from ingest.plugins.distressed_plugin import DistressedPlugin

    plugin = DistressedPlugin()
    with patch("ingest.plugins.distressed_plugin.get_engine") as mock_engine, \
         patch("utils.distressed_developer.scan_distressed_developers", return_value=[]), \
         patch.object(plugin, "_persist_distress_signals", return_value=0):
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = []
        mock_engine.return_value.connect.return_value.__enter__.return_value = conn
        records = plugin.run("Yelahanka")
    assert isinstance(records, list)


def test_gate72_table_has_distress_score_column():
    migration_path = Path("alembic/versions/0034_developer_distress_signals.py")
    src = migration_path.read_text(encoding="utf-8")
    assert "distress_score" in src


def test_gate72_distress_blend_0730():
    from intelligence.opportunity_engine import _distress_score

    lp = SimpleNamespace(development_readiness="CONSTRAINED", flood_risk="CLEAR", overlay_count=0, flags=[])
    pkg = SimpleNamespace(land_picture=lp, market="Yelahanka", developer_id=None)
    with patch("intelligence.opportunity_engine.get_engine") as mock_engine:
        conn = MagicMock()
        conn.execute.return_value.scalar.return_value = 0.2285714286
        mock_engine.return_value.connect.return_value.__enter__.return_value = conn
        score = _distress_score(pkg)
    assert score == pytest.approx(0.73, rel=1e-4)


def test_gate72_distress_endpoint_returns_json_list():
    client = TestClient(app)
    with patch("dashboard.app_fastapi._get_sa_engine") as mock_engine:
        conn = MagicMock()
        row = SimpleNamespace(
            developer_name="Brigade",
            market="Yelahanka",
            signal_type="computed",
            stall_count=2,
            stall_ratio=0.5,
            mention_count=1,
            distress_score=0.6,
            detected_at=None,
        )
        conn.execute.return_value.fetchall.return_value = [row]
        mock_engine.return_value.connect.return_value.__enter__.return_value = conn
        resp = client.get("/api/distress/signals?market=Yelahanka")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["market"] == "Yelahanka"
    assert isinstance(payload["signals"], list)


def test_gate72_distress_endpoint_rejects_blank_market():
    client = TestClient(app)
    resp = client.get("/api/distress/signals?market=")
    assert resp.status_code == 400


def test_bd_head_context_includes_jdv_targets():
    from crews.board_room_v2 import _get_jdv_jv_targets

    with patch("crews.board_room_v2.get_engine") as mock_engine:
        conn = MagicMock()
        conn.execute.return_value.fetchall.return_value = [SimpleNamespace(developer_name="Brigade")]
        mock_engine.return_value.connect.return_value.__enter__.return_value = conn
        targets = _get_jdv_jv_targets("Yelahanka")
    assert targets == ["Brigade"]
