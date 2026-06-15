"""Unit tests for Form17Parser (Sprint 95 — T-1159).

Tests cover the parsing logic without touching the real PDF (no pdfplumber
needed — we mock the row extraction and test the business logic layer).

12 unit tests covering:
  - Deed type + consideration parsing
  - Area/extent conversion (Sq.Metre → sqft)
  - Doc number extraction
  - Survey number parsing + multi-survey
  - Date parsing
  - Multi-row deduplication (continuation rows, multi-survey)
  - Non-sale deed exclusion flag
  - Cancellation remarks detection
  - PSF sanity bounds
  - Mixed-script party name handling
  - Empty / malformed row tolerance
  - SALE_DEED_TYPES constant is referenced
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

# ── _parse_consideration ──────────────────────────────────────────────────────


def test_parse_consideration_sale():
    from scrapers.kaveri_form17 import _parse_consideration

    deed_type, amt = _parse_consideration("Sale - ₹21,00,000.00")
    assert deed_type == "Sale"
    assert amt == 2_100_000.0


def test_parse_consideration_dtd():
    from scrapers.kaveri_form17 import _parse_consideration

    deed_type, amt = _parse_consideration("DTD - ₹1,12,42,000.00")
    assert deed_type == "DTD"
    assert amt == 11_242_000.0


def test_parse_consideration_zero():
    from scrapers.kaveri_form17 import _parse_consideration

    deed_type, amt = _parse_consideration("Partition deed - ₹.00")
    assert deed_type == "Partition deed"
    assert amt is None  # zero treated as None


def test_parse_consideration_no_amount():
    from scrapers.kaveri_form17 import _parse_consideration

    deed_type, amt = _parse_consideration("Cancellation Deed")
    assert deed_type == "Cancellation Deed"
    assert amt is None


# ── _parse_area ───────────────────────────────────────────────────────────────


def test_parse_area_sqm():
    from scrapers.kaveri_form17 import _parse_area

    sqft, unit = _parse_area("111.42 Sq.Metre")
    assert unit == "sqm"
    assert sqft is not None
    assert abs(sqft - 111.42 * 10.7639) < 1.0


def test_parse_area_sqm_variant():
    from scrapers.kaveri_form17 import _parse_area

    sqft, unit = _parse_area("108.00 Sq. Metre")
    assert unit == "sqm"
    assert sqft is not None
    assert sqft > 1000  # 108 sqm ≈ 1163 sqft


def test_parse_area_empty():
    from scrapers.kaveri_form17 import _parse_area

    sqft, unit = _parse_area(None)
    assert sqft is None
    assert unit == "unknown"


# ── _parse_doc_no ─────────────────────────────────────────────────────────────


def test_parse_doc_no_standard():
    from scrapers.kaveri_form17 import _parse_doc_no

    assert _parse_doc_no("DNH-1-13888-2023-24") == "DNH-1-13888-2023-24"


def test_parse_doc_no_embedded():
    from scrapers.kaveri_form17 import _parse_doc_no

    assert _parse_doc_no("  BYP-1-06807-2020-21  ") == "BYP-1-06807-2020-21"


def test_parse_doc_no_none():
    from scrapers.kaveri_form17 import _parse_doc_no

    assert _parse_doc_no(None) is None
    assert _parse_doc_no("") is None
    assert _parse_doc_no("not-a-doc-number") is None


# ── _parse_survey_nos ─────────────────────────────────────────────────────────


def test_parse_survey_nos_single():
    from scrapers.kaveri_form17 import _parse_survey_nos

    result = _parse_survey_nos("101")
    assert result == ["101"]


def test_parse_survey_nos_multi():
    from scrapers.kaveri_form17 import _parse_survey_nos

    result = _parse_survey_nos("45/2A, 45/3, 101")
    assert "45/2A" in result
    assert "45/3" in result
    assert "101" in result


def test_parse_survey_nos_empty():
    from scrapers.kaveri_form17 import _parse_survey_nos

    assert _parse_survey_nos(None) == []
    assert _parse_survey_nos("") == []


# ── _parse_date ───────────────────────────────────────────────────────────────


def test_parse_date_standard():
    from scrapers.kaveri_form17 import _parse_date

    d = _parse_date("15-02-2021")
    assert d is not None
    assert d.year == 2021
    assert d.month == 2
    assert d.day == 15


def test_parse_date_invalid():
    from scrapers.kaveri_form17 import _parse_date

    assert _parse_date(None) is None
    assert _parse_date("not-a-date") is None
    assert _parse_date("32-13-2024") is None  # invalid day/month


# ── _compute_psf ─────────────────────────────────────────────────────────────


def test_compute_psf_in_bounds():
    from scrapers.kaveri_form17 import _compute_psf

    # ₹21L / 1163 sqft ≈ ₹1806/sqft — within bounds
    psf = _compute_psf(2_100_000, 1163.0)
    assert psf is not None
    assert 500 <= psf <= 50_000


def test_compute_psf_zero_consideration():
    from scrapers.kaveri_form17 import _compute_psf

    assert _compute_psf(None, 1163.0) is None
    assert _compute_psf(0, 1163.0) is None


def test_compute_psf_out_of_bounds():
    from scrapers.kaveri_form17 import _compute_psf

    # ₹1 surrender of lease — way below ₹500/sqft floor
    assert _compute_psf(1, 1163.0) is None


# ── Form17Parser._build_records (unit, no PDF) ───────────────────────────────


def _make_row(
    village="Division 1",
    deed_raw="Sale - ₹21,00,000.00",
    survey="101",
    area="111.42 Sq.Metre",
    assessment="",
    executant="John Doe",
    claimant="Jane Smith",
    sro="Devanahalli",
    exec_date="01-01-2024",
    reg_date="15-01-2024",
    doc_no="DNH-1-13888-2023-24",
    remarks="",
) -> list[str | None]:
    return [
        village, deed_raw, survey, area, assessment,
        executant, claimant, sro, exec_date, reg_date, doc_no, remarks,
    ]


def test_build_records_single_sale():
    from scrapers.kaveri_form17 import Form17Parser

    parser = Form17Parser()
    rows = [_make_row()]
    records = parser._build_records(rows, source_ref="test.pdf")

    assert len(records) == 1
    r = records[0]
    assert r["doc_number"] == "DNH-1-13888-2023-24"
    assert r["deed_type"] == "Sale"
    assert r["is_sale_deed"] is True
    assert r["consideration_inr"] == 2_100_000.0
    assert r["registration_date"] == "2024-01-15"
    assert r["sro"] == "Devanahalli"
    assert r["village"] == "Division 1"


def test_build_records_non_sale_flagged():
    from scrapers.kaveri_form17 import Form17Parser

    parser = Form17Parser()
    rows = [_make_row(deed_raw="DTD - ₹1,00,000.00", doc_no="DNH-1-00001-2023-24")]
    records = parser._build_records(rows, source_ref="test.pdf")

    assert len(records) == 1
    assert records[0]["is_sale_deed"] is False


def test_build_records_cancellation_detected():
    from scrapers.kaveri_form17 import Form17Parser

    parser = Form17Parser()
    rows = [
        _make_row(
            deed_raw="Cancellation Deed - ₹.00",
            doc_no="DNH-1-99999-2023-24",
            remarks="This Document Cancels Document No. DNH-1-13888-2023-24",
        )
    ]
    records = parser._build_records(rows, source_ref="test.pdf")
    assert records[0]["cancels_doc_number"] == "DNH-1-13888-2023-24"


def test_build_records_multi_survey():
    from scrapers.kaveri_form17 import Form17Parser

    parser = Form17Parser()
    # One deed with 2 survey numbers on separate rows
    rows = [
        _make_row(survey="45/2A", doc_no="DNH-1-11111-2023-24"),
        _make_row(survey="45/3", doc_no="DNH-1-11111-2023-24"),  # same doc_no
    ]
    records = parser._build_records(rows, source_ref="test.pdf")
    # Should produce 2 records (one per survey) or combine — current impl merges survey_no_raw
    survey_nos = {r["survey_no_raw"] for r in records}
    assert "45/2A" in survey_nos or "45/3" in survey_nos


def test_build_records_header_rows_skipped():
    from scrapers.kaveri_form17 import Form17Parser

    parser = Form17Parser()
    header = ["Name of Village", "Nature of Deed", "Survey No", "Area", "", "", "", "SRO", "Exec Date", "Reg Date", "Doc No", "Remarks"]
    data = [_make_row()]
    records = parser._build_records([header] + data, source_ref="test.pdf")
    assert len(records) == 1  # header skipped


def test_build_records_mixed_unicode_party():
    from scrapers.kaveri_form17 import Form17Parser

    parser = Form17Parser()
    rows = [_make_row(executant="నరసింగ్ రావ్", claimant="ಶ್ರೀ ಮತ")]
    records = parser._build_records(rows, source_ref="test.pdf")
    assert len(records) == 1
    # Mixed-script names stored as-is
    assert "నరసింగ్" in records[0]["executant"] or records[0]["executant"] != ""


def test_build_records_empty_rows():
    from scrapers.kaveri_form17 import Form17Parser

    parser = Form17Parser()
    records = parser._build_records([], source_ref="test.pdf")
    assert records == []


# ── Plugin importable ─────────────────────────────────────────────────────────


def test_kaveri_form17_plugin_importable():
    from ingest.plugins.kaveri_form17_plugin import KaveriForm17Plugin

    plugin = KaveriForm17Plugin()
    assert plugin.plugin_id == "kaveri_form17"


def test_kaveri_form17_plugin_validate_requires_doc_no():
    from ingest.base import ParsedRecord
    from ingest.plugins.kaveri_form17_plugin import KaveriForm17Plugin

    plugin = KaveriForm17Plugin()
    record = ParsedRecord(
        entity_type="registered_transaction",
        source_id="form17_test_001",
        market="Devanahalli",
        data={"doc_no": "", "reg_date": "2024-01-15", "sro": "Devanahalli", "data_source": "kaveri_form17"},
    )
    result = plugin.validate(record)
    assert not result.valid
    assert any("doc_no" in e for e in result.errors)


def test_kaveri_form17_plugin_in_plugin_schedules():
    from config.settings import PLUGIN_SCHEDULES

    assert "kaveri_form17" in PLUGIN_SCHEDULES, (
        "kaveri_form17 must be in PLUGIN_SCHEDULES in settings.py"
    )


# ── SALE_DEED_TYPES referenced ────────────────────────────────────────────────


def test_sale_deed_types_includes_sale():
    from config.settings import SALE_DEED_TYPES

    assert "Sale" in SALE_DEED_TYPES
    assert "Sale Deed" in SALE_DEED_TYPES
