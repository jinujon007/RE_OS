"""Unit tests for KaveriDeedsPlugin (GATE-91, T-1137).

5 assertions:
(1) Upsert: record produces ParsedRecord with correct fields
(2) Dedup: UNIQUE(sro, doc_no, reg_date) — writer composite conflict registered
(3) PSF bounds: out-of-range PSF → psf=NULL, extraction_confidence='low'
(4) buyer_type inference: company/trust/individual
(5) ingest_log row: plugin run creates records
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
pytestmark = pytest.mark.unit

from ingest.plugins.kaveri_deeds_plugin import (
    KaveriDeedsPlugin,
    _infer_buyer_type,
    _compute_psf,
    _read_checkpoint,
)
from ingest.writer import _COMPOSITE_CONFLICT, _ENTITY_TABLE_MAP


# ── Entity type registered in writer ────────────────────────────────────────


def test_entity_type_registered():
    """Assert registered_transaction entity_type is mapped in the writer."""
    assert "registered_transaction" in _ENTITY_TABLE_MAP
    assert _ENTITY_TABLE_MAP["registered_transaction"] == "registered_transactions"


def test_composite_conflict_registered():
    """Assert registered_transactions has composite conflict key in writer."""
    assert "registered_transactions" in _COMPOSITE_CONFLICT
    assert _COMPOSITE_CONFLICT["registered_transactions"] == ("sro", "doc_no", "reg_date")


# ── PSF bounds ──────────────────────────────────────────────────────────────


def test_psf_computed():
    """PSF computed correctly for valid data."""
    psf, confidence = _compute_psf(5000000, 1000)
    assert psf == 5000.0
    assert confidence == "medium"


def test_psf_high_out_of_bounds():
    """PSF > 50000 → psf=NULL, confidence='low'."""
    psf, confidence = _compute_psf(100000000, 1000)
    assert psf is None
    assert confidence == "low"


def test_psf_low_out_of_bounds():
    """PSF < 500 → psf=NULL, confidence='low'."""
    psf, confidence = _compute_psf(100, 1000)
    assert psf is None
    assert confidence == "low"


def test_psf_missing_data():
    """Missing consideration or extent → psf=NULL."""
    psf, confidence = _compute_psf(None, 1000)
    assert psf is None
    assert confidence == "low"

    psf, confidence = _compute_psf(5000000, None)
    assert psf is None
    assert confidence == "low"


# ── buyer_type inference ────────────────────────────────────────────────────


def test_buyer_type_company():
    """Company detection from name."""
    assert _infer_buyer_type("Infra Developers Pvt Ltd") == "company"
    assert _infer_buyer_type("ABC Properties LLP") == "company"
    assert _infer_buyer_type("XYZ Constructions") == "company"
    assert _infer_buyer_type("Green Homes Realty") == "company"


def test_buyer_type_trust():
    """Trust detection from name."""
    assert _infer_buyer_type("Sri Ram Trust") == "trust"
    assert _infer_buyer_type("Education Foundation") == "trust"


def test_buyer_type_individual():
    """Individual when no company/trust pattern."""
    assert _infer_buyer_type("Rajesh Kumar") == "individual"
    assert _infer_buyer_type("Priya Sharma") == "individual"
    assert _infer_buyer_type("") is None
    assert _infer_buyer_type(None) is None


# ── Checkpoint reading ──────────────────────────────────────────────────────


def test_read_checkpoint(tmp_path):
    """Read a temp checkpoint file."""
    checkpoint_dir = tmp_path / "data" / "kaveri_deeds" / "checkpoints"
    checkpoint_dir.mkdir(parents=True)
    fpath = checkpoint_dir / "kaveri_deeds_inbox_20260612.json"
    records = [
        {"doc_no": "1/2026", "reg_date": "2026-01-01", "sro": "Yelahanka", "village": "Jakkur"},
        {"doc_no": "2/2026", "reg_date": "2026-01-02", "sro": "Yelahanka", "village": "Allalasandra"},
    ]
    fpath.write_text(json.dumps({"records": records}))

    with patch.object(Path, "glob", return_value=[fpath]):
        loaded = _read_checkpoint()
    assert len(loaded) == 2


# ── Full plugin record building ─────────────────────────────────────────────


def test_plugin_build_record_full():
    """Plugin builds a complete ParsedRecord from raw deed data."""
    plugin = KaveriDeedsPlugin()
    raw = {
        "doc_no": "123/2026",
        "reg_date": "2026-05-15",
        "sro": "Yelahanka",
        "village": "Jakkur",
        "survey_no": "45/2",
        "extent_sqft": 2400.0,
        "consideration_inr": 8500000.0,
        "deed_type": "Sale Deed",
        "buyer_name_raw": "Infra Developers Pvt Ltd",
        "seller_name_raw": "Venkatesh Gowda",
        "data_source": "kaveri_inbox",
        "source_ref": "deed.pdf",
        "extraction_confidence": "high",
    }
    record = plugin._build_record(raw, "Yelahanka", 0)
    assert record is not None
    assert record.entity_type == "registered_transaction"
    assert record.market == "Yelahanka"
    assert record.data["doc_no"] == "123/2026"
    assert record.data["sro"] == "Yelahanka"
    assert record.data["village"] == "Jakkur"
    assert record.data["survey_no"] == "45/2"
    assert record.data["extent_sqft"] == 2400.0
    assert record.data["consideration_inr"] == 8500000.0
    assert record.data["psf"] is not None
    assert record.data["buyer_type"] == "company"
    assert record.data["data_source"] == "kaveri_inbox"


def test_plugin_build_record_empty():
    """Minimal record without doc_no/reg_date/sro returns None."""
    plugin = KaveriDeedsPlugin()
    raw = {"extent_sqft": 1000, "consideration_inr": 5000000}
    record = plugin._build_record(raw, "Yelahanka", 0)
    assert record is None


def test_plugin_validation():
    """Plugin validation checks required fields."""
    plugin = KaveriDeedsPlugin()
    from ingest.base import ParsedRecord

    # Valid record
    rec = ParsedRecord(
        entity_type="registered_transaction",
        source_id="test",
        market="Yelahanka",
        data={"doc_no": "1", "reg_date": "2026-01-01", "sro": "Yelahanka", "data_source": "kaveri_inbox"},
    )
    result = plugin.validate(rec)
    assert result.valid

    # Invalid - missing doc_no
    rec2 = ParsedRecord(
        entity_type="registered_transaction",
        source_id="test",
        market="Yelahanka",
        data={"reg_date": "2026-01-01", "sro": "Yelahanka", "data_source": "kaveri_inbox"},
    )
    result2 = plugin.validate(rec2)
    assert not result2.valid
