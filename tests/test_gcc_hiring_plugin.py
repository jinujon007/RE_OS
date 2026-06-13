"""Tests for GCC hiring snapshot ingest plugin (GATE-94, T-1152)."""

import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


def test_plugin_returns_parsed_records():
    from ingest.plugins.gcc_hiring_plugin import GccHiringPlugin
    from ingest.base import ParsedRecord
    plugin = GccHiringPlugin()
    with patch("scrapers.gcc_hiring_scraper.run_snapshot") as mock_scraper:
        mock_scraper.return_value = [
            {"employer": "NTT Data", "hub": "Manyata Tech Park", "posting_count": 45, "source": "naukri_search"},
            {"employer": "Cognizant", "hub": "Manyata Tech Park", "posting_count": 120, "source": "naukri_search"},
        ]
        with patch.object(plugin, "_check_wow_delta"):
            records = plugin.run("Yelahanka")
    assert len(records) == 2
    assert all(isinstance(r, ParsedRecord) for r in records)
    assert all(r.entity_type == "gcc_hiring_snapshot" for r in records)
    assert records[0].data["employer"] == "NTT Data"
    assert records[0].data["posting_count"] == 45


def test_plugin_handles_scraper_failure():
    from ingest.plugins.gcc_hiring_plugin import GccHiringPlugin
    plugin = GccHiringPlugin()
    with patch("scrapers.gcc_hiring_scraper.run_snapshot", side_effect=ConnectionError("timeout")):
        records = plugin.run("Hebbal")
    assert records == []


def test_plugin_validate_valid_record():
    from ingest.plugins.gcc_hiring_plugin import GccHiringPlugin
    from ingest.base import ParsedRecord
    plugin = GccHiringPlugin()
    rec = ParsedRecord(
        entity_type="gcc_hiring_snapshot",
        source_id="ghs_test_2026-06-13",
        market="Bengaluru",
        data={"employer": "NTT Data", "posting_count": 50, "snapshot_date": "2026-06-13"},
    )
    result = plugin.validate(rec)
    assert result.valid


def test_wow_delta_silent_on_first_run():
    """F6 fix: WoW check should not throw when there are no prior snapshots."""
    from ingest.plugins.gcc_hiring_plugin import GccHiringPlugin
    from ingest.base import ParsedRecord
    plugin = GccHiringPlugin()
    rec = ParsedRecord(
        entity_type="gcc_hiring_snapshot",
        source_id="ghs_test_first_run",
        market="Bengaluru",
        data={"employer": "NTT Data", "location": "Manyata", "posting_count": 45, "snapshot_date": "2026-06-13"},
    )
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None
        with patch("utils.discord_notifier.send") as mock_send:
            plugin._check_wow_delta([rec])
            mock_send.assert_not_called()


def test_plugin_validate_missing_employer():
    from ingest.plugins.gcc_hiring_plugin import GccHiringPlugin
    from ingest.base import ParsedRecord
    plugin = GccHiringPlugin()
    rec = ParsedRecord(
        entity_type="gcc_hiring_snapshot",
        source_id="ghs_bad",
        market="Bengaluru",
        data={"posting_count": 50},
    )
    result = plugin.validate(rec)
    assert not result.valid
    assert any("employer" in e for e in result.errors)
