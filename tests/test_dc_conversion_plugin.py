"""Tests for DC conversion ingest plugin (GATE-94, T-1153)."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


def test_plugin_returns_parsed_records():
    with patch("ingest.plugins.dc_conversion_plugin.run_scan") as mock_scan:
        mock_scan.return_value = [
            {
                "application_no": "DC/001",
                "village": "Venkatala",
                "survey_no": "45/2",
                "to_use": "Residential",
                "from_use": "Agri",
                "status": "Approved",
            },
            {
                "application_no": "DC/002",
                "village": "Byatarayanapura",
                "survey_no": "10/1",
                "to_use": "Commercial",
                "from_use": "Agri",
                "status": "Pending",
            },
        ]
        from ingest.plugins.dc_conversion_plugin import DCConversionPlugin
        from ingest.base import ParsedRecord

        plugin = DCConversionPlugin()
        with patch.object(plugin, "_send_batched_alerts"):
            records = plugin.run("Yelahanka")
    assert len(records) == 2
    assert all(isinstance(r, ParsedRecord) for r in records)
    assert records[0].data["application_no"] == "DC/001"
    assert records[0].data["survey_no"] == "45/2"


def test_plugin_skips_records_without_app_no():
    with patch("ingest.plugins.dc_conversion_plugin.run_scan") as mock_scan:
        mock_scan.return_value = [
            {"application_no": "", "village": "Test", "status": "Pending"},
            {"application_no": "DC/003", "village": "Test", "status": "Approved"},
        ]
        from ingest.plugins.dc_conversion_plugin import DCConversionPlugin

        plugin = DCConversionPlugin()
        with patch.object(plugin, "_send_batched_alerts"):
            records = plugin.run("Hebbal")
    assert len(records) == 1
    assert records[0].data["application_no"] == "DC/003"


def test_plugin_falls_back_to_inbox():
    with patch("ingest.plugins.dc_conversion_plugin.run_scan") as mock_scan:
        mock_scan.side_effect = [
            Exception("live failed"),
            [
                {
                    "application_no": "DC/010",
                    "village": "Jakkur",
                    "survey_no": "5/1",
                    "status": "Approved",
                }
            ],
        ]
        from ingest.plugins.dc_conversion_plugin import DCConversionPlugin
        from ingest.base import ParsedRecord

        plugin = DCConversionPlugin()
        with patch.object(plugin, "_send_batched_alerts"):
            records = plugin.run("Hebbal")
    assert len(records) == 1
    assert mock_scan.call_count == 2


def test_plugin_validate_valid_record():
    from ingest.plugins.dc_conversion_plugin import DCConversionPlugin
    from ingest.base import ParsedRecord

    plugin = DCConversionPlugin()
    rec = ParsedRecord(
        entity_type="dc_conversion",
        source_id="dc_DC/001",
        market="Yelahanka",
        data={"application_no": "DC/001", "village": "Venkatala"},
    )
    result = plugin.validate(rec)
    assert result.valid
