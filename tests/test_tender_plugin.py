"""Tests for eProcurement Karnataka tender plugin (GATE-93, T-1149)."""

import pytest
from unittest.mock import patch

pytestmark = pytest.mark.unit


def test_tender_plugin_imports():
    """TenderPlugin can be imported and instantiated."""
    from ingest.plugins.tender_plugin import TenderPlugin

    plugin = TenderPlugin()
    assert plugin.plugin_id == "karnataka_eprocurement"
    assert plugin.source_id == "eproc_karnataka_tenders"


def test_tender_plugin_returns_seed_when_no_scrape():
    """TenderPlugin returns seed tenders when live scrape returns empty."""
    from ingest.plugins.tender_plugin import TenderPlugin

    with patch.object(TenderPlugin, "_scrape_portal", return_value=[]):
        plugin = TenderPlugin()
        records = plugin.run("Yelahanka")
        assert len(records) >= 5


def test_tender_plugin_dedup_on_tender_id():
    """TenderPlugin does not return duplicate tender_ids."""
    from ingest.plugins.tender_plugin import TenderPlugin

    plugin = TenderPlugin()
    records = plugin.run("Yelahanka")
    tids = [r.data["tender_id"] for r in records]
    assert len(tids) == len(set(tids))


def test_tender_validate_rejects_missing_tender_id():
    """validate returns False when tender_id is missing."""
    from ingest.plugins.tender_plugin import TenderPlugin
    from ingest.base import ParsedRecord

    plugin = TenderPlugin()
    record = ParsedRecord(
        entity_type="tender",
        source_id="test",
        market="Yelahanka",
        data={"title": "Test tender"},
    )
    assert not plugin.validate(record)


def test_tender_validate_accepts_valid_record():
    """validate returns True for complete tender record."""
    from ingest.plugins.tender_plugin import TenderPlugin
    from ingest.base import ParsedRecord

    plugin = TenderPlugin()
    record = ParsedRecord(
        entity_type="tender",
        source_id="test_123",
        market="Yelahanka",
        data={"tender_id": "BMRCL-001", "title": "Metro construction"},
    )
    assert plugin.validate(record)


def test_parse_value_indian_format():
    """_parse_value handles Indian number format."""
    from ingest.plugins.tender_plugin import TenderPlugin

    assert TenderPlugin._parse_value("1,50,00,000") == 15000000.0
    assert TenderPlugin._parse_value("45,00,00,000") == 450000000.0
    assert TenderPlugin._parse_value("") is None
    assert TenderPlugin._parse_value("N/A") is None


def test_parse_date_various_formats():
    """_parse_date handles DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD."""
    from ingest.plugins.tender_plugin import TenderPlugin

    assert TenderPlugin._parse_date("15-01-2026") == "2026-01-15"
    assert TenderPlugin._parse_date("01/02/2026") == "2026-02-01"
    assert TenderPlugin._parse_date("2026-03-15") == "2026-03-15"
    assert TenderPlugin._parse_date("") is None


def test_matches_keywords():
    """_matches_keywords detects NB keywords in text."""
    from ingest.plugins.tender_plugin import TenderPlugin

    plugin = TenderPlugin()
    assert plugin._matches_keywords("Yelahanka metro construction")
    assert plugin._matches_keywords("BWSSB water supply Hebbal")
    assert plugin._matches_keywords("STRR Phase 2 Devanahalli")
    assert not plugin._matches_keywords("Garbage collection in Mysore")


def test_make_record_creates_parsed_record():
    """_make_record creates ParsedRecord with correct entity_type."""
    from ingest.plugins.tender_plugin import TenderPlugin

    plugin = TenderPlugin()
    record = plugin._make_record(
        tender_id="TEST-001",
        title="Test tender project",
        dept="BBMP",
        value_inr=100000000.0,
        published_date="2026-01-01",
        close_date="2026-03-01",
        location_text="Hebbal",
        market_match="Hebbal",
        source_url="https://example.com",
    )
    assert record.entity_type == "tender"
    assert record.data["tender_id"] == "TEST-001"
    assert record.data["value_inr"] == 100000000.0
    assert record.market == "Hebbal"


def test_seed_tenders_have_all_required_fields():
    """All seed tenders have required fields populated."""
    from ingest.plugins.tender_plugin import _get_seed_tenders

    tenders = _get_seed_tenders()
    assert len(tenders) >= 10
    for t in tenders:
        assert t["tender_id"], f"Missing tender_id in {t}"
        assert t["title"], f"Missing title in {t['tender_id']}"
        assert t["dept"], f"Missing dept in {t['tender_id']}"
        assert t["value_inr"] is not None, f"Missing value in {t['tender_id']}"
        assert t["published_date"], f"Missing published_date in {t['tender_id']}"
        assert t["close_date"], f"Missing close_date in {t['tender_id']}"
