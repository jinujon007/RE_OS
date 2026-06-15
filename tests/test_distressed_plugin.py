from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _mock_engine_with_rows(rows):
    engine = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = rows
    engine.connect.return_value.__enter__.return_value = conn
    engine.begin.return_value.__enter__.return_value = conn
    return engine, conn


def test_rera_stall_detection_returns_records():
    from ingest.plugins.distressed_plugin import DistressedPlugin

    row = MagicMock(
        developer_name="Brigade", market="Yelahanka", stall_count=2, stall_ratio=0.5
    )
    engine, _ = _mock_engine_with_rows([row])
    with patch("ingest.plugins.distressed_plugin.get_engine", return_value=engine):
        results = DistressedPlugin()._detect_rera_stalls("Yelahanka")

    assert len(results) == 1
    assert results[0]["developer_name"] == "Brigade"
    assert results[0]["signal_type"] == "rera_stall"


def test_stall_ratio_capped_at_1():
    from ingest.plugins.distressed_plugin import DistressedPlugin

    row = MagicMock(
        developer_name="Prestige", market="Yelahanka", stall_count=5, stall_ratio=1.0
    )
    engine, _ = _mock_engine_with_rows([row])
    with patch("ingest.plugins.distressed_plugin.get_engine", return_value=engine):
        results = DistressedPlugin()._detect_rera_stalls("Yelahanka")

    assert results[0]["stall_ratio"] <= 1.0


def test_empty_market_returns_no_stalls():
    from ingest.plugins.distressed_plugin import DistressedPlugin

    engine, _ = _mock_engine_with_rows([])
    with patch("ingest.plugins.distressed_plugin.get_engine", return_value=engine):
        results = DistressedPlugin()._detect_rera_stalls("Unknown")

    assert results == []


def test_nclt_detection_groups_by_developer():
    from ingest.plugins.distressed_plugin import DistressedPlugin

    row = MagicMock(developer_name="Sobha", mention_count=3)
    engine, _ = _mock_engine_with_rows([row])
    with patch("ingest.plugins.distressed_plugin.get_engine", return_value=engine):
        results = DistressedPlugin()._detect_nclt_from_news("Yelahanka")

    assert results == [
        {
            "developer_name": "Sobha",
            "mention_count": 3,
            "signal_type": "nclt_news",
            "market": "Yelahanka",
        }
    ]


def test_nclt_returns_empty_when_no_matching_news():
    from ingest.plugins.distressed_plugin import DistressedPlugin

    engine, _ = _mock_engine_with_rows([])
    with patch("ingest.plugins.distressed_plugin.get_engine", return_value=engine):
        results = DistressedPlugin()._detect_nclt_from_news("Hebbal")

    assert results == []


def test_run_generates_computed_signal_records():
    from ingest.plugins.distressed_plugin import DistressedPlugin

    plugin = DistressedPlugin()
    with (
        patch("utils.distressed_developer.scan_distressed_developers", return_value=[]),
        patch.object(
            plugin,
            "_detect_rera_stalls",
            return_value=[
                {
                    "developer_name": "Brigade",
                    "market": "Yelahanka",
                    "stall_count": 2,
                    "stall_ratio": 0.5,
                    "signal_type": "rera_stall",
                }
            ],
        ),
        patch.object(plugin, "_detect_nclt_from_news", return_value=[]),
        patch.object(plugin, "_persist_distress_signals", return_value=1),
        patch.object(
            plugin,
            "_compute_and_persist_scores",
            return_value=[
                {
                    "developer_name": "Brigade",
                    "market": "Yelahanka",
                    "signal_type": "computed",
                    "distress_score": 0.625,
                }
            ],
        ),
    ):
        records = plugin.run("Yelahanka")

    assert any(rec.data.get("signal_type") == "computed" for rec in records)
