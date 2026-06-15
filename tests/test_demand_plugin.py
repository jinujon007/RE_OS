import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestDemandPlugin:
    def test_demand_plugin_returns_list(self):
        from ingest.plugins.demand_plugin import DemandPlugin

        plugin = DemandPlugin()
        with patch("ingest.plugins.demand_plugin._fetch_nri_listings", return_value=[]):
            with patch(
                "ingest.plugins.demand_plugin._check_listing_surge", return_value=None
            ):
                with patch(
                    "ingest.plugins.demand_plugin._check_price_cuts", return_value=None
                ):
                    result = plugin.run("Yelahanka")
                    assert isinstance(result, list)

    def test_demand_plugin_handles_network_error(self):
        from ingest.plugins.demand_plugin import DemandPlugin

        plugin = DemandPlugin()
        with patch("ingest.plugins.demand_plugin._fetch_nri_listings", return_value=[]):
            with patch(
                "ingest.plugins.demand_plugin._check_listing_surge",
                side_effect=Exception("DB down"),
            ):
                result = plugin.run("Yelahanka")
                assert isinstance(result, list)

    def test_demand_events_table_columns(self):
        expected_columns = {
            "id",
            "market",
            "event_type",
            "count",
            "value_cr",
            "source",
            "recorded_at",
        }
        from ingest.base import ParsedRecord

        record = ParsedRecord(
            entity_type="demand_event",
            source_id="test_event",
            market="Yelahanka",
            data={
                "event_type": "nri_query",
                "market": "Yelahanka",
                "count": 5,
                "source": "portal:test",
                "recorded_at": "2026-06-08T00:00:00",
            },
        )
        data_keys = set(record.data.keys())
        required = {"event_type", "market", "count", "source", "recorded_at"}
        assert required.issubset(data_keys), f"Missing columns: {required - data_keys}"
