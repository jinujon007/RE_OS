from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class _Row:
    def __init__(self, **kwargs):
        self._data = kwargs
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getitem__(self, i):
        if isinstance(i, str):
            return self._data[i]
        keys = list(self._data.keys())
        return self._data[keys[i]]

    def __iter__(self):
        return iter(self._data.values())


def _mock_engine_with_rows(rows):
    engine = MagicMock()
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = rows
    conn.execute.return_value.fetchone.return_value = rows[0] if rows else None
    engine.connect.return_value.__enter__.return_value = conn
    engine.begin.return_value.__enter__.return_value = conn
    return engine, conn


def test_land_supply_plugin_instantiates():
    from ingest.plugins.land_supply_plugin import LandSupplyPlugin
    plugin = LandSupplyPlugin()
    assert plugin.plugin_id == "land_supply"
    assert plugin.source_id == "land_supply_scout"


def test_rera_phase_returns_records_for_seeded_market():
    from ingest.plugins.land_supply_plugin import LandSupplyPlugin

    rows = [
        _Row(
            record_id="abc-123",
            project_name="Test Project A",
            developer_name="Test Builder",
            total_units=100,
            launch_date=None,
            expected_completion_date=None,
            status="registered",
        ),
        _Row(
            record_id="def-456",
            project_name="Test Project B",
            developer_name="Another Builder",
            total_units=250,
            launch_date=None,
            expected_completion_date=None,
            status="pre-registration",
        ),
    ]
    engine, _ = _mock_engine_with_rows(rows)
    with patch("ingest.plugins.land_supply_plugin.get_engine", return_value=engine):
        results = LandSupplyPlugin()._rera_pipeline_phase("Yelahanka")

    assert len(results) == 2
    assert results[0].entity_type == "supply_pipeline"
    assert results[0].data["estimated_units"] == 100
    assert results[1].data["estimated_units"] == 250
    assert results[1].data["status"] == "pre-registration"


def test_rera_phase_empty_market_returns_no_records():
    from ingest.plugins.land_supply_plugin import LandSupplyPlugin

    engine, _ = _mock_engine_with_rows([])
    with patch("ingest.plugins.land_supply_plugin.get_engine", return_value=engine):
        results = LandSupplyPlugin()._rera_pipeline_phase("UnknownMarket")

    assert results == []


def test_kiadb_scraper_returns_empty_on_network_error():
    from ingest.plugins.land_supply_plugin import LandSupplyPlugin

    with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
        results = LandSupplyPlugin()._scrape_kiadb_tenders("Yelahanka")

    assert results == []


def test_bda_news_extraction_finds_unit_count():
    from ingest.plugins.land_supply_plugin import LandSupplyPlugin

    row = _Row(
        id="1", title="BDA approves 500 plots in new layout",
        content="BDA layout near Yelahanka with 500 plots",
        published_at=None,
    )
    engine, _ = _mock_engine_with_rows([row])
    with patch("ingest.plugins.land_supply_plugin.get_engine", return_value=engine):
        results = LandSupplyPlugin()._detect_supply_from_news("Yelahanka")

    assert len(results) == 1
    assert results[0].data["estimated_units"] == 500
    assert results[0].data["source"] == "bda_news"


def test_bda_news_returns_empty_for_unknown_market():
    from ingest.plugins.land_supply_plugin import LandSupplyPlugin

    engine, _ = _mock_engine_with_rows([])
    with patch("ingest.plugins.land_supply_plugin.get_engine", return_value=engine):
        results = LandSupplyPlugin()._detect_supply_from_news("UnknownMarket")

    assert results == []


def test_run_aggregates_all_phases():
    from ingest.plugins.land_supply_plugin import LandSupplyPlugin

    plugin = LandSupplyPlugin()
    with patch.object(plugin, "_rera_pipeline_phase", return_value=[MagicMock()]):
        with patch.object(plugin, "_scrape_kiadb_tenders", return_value=[MagicMock()]):
            with patch.object(plugin, "_detect_supply_from_news", return_value=[MagicMock()]):
                results = plugin.run("Yelahanka")

    assert len(results) == 3
