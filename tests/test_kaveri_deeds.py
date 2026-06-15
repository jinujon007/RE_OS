"""Unit tests for KaveriDeedScout — EC Form 15 inbox parser (T-1156).

Tests field extraction, header detection, multi-page continuation stitching,
and end-to-end parsing with synthetic EC Form 15 table fixtures.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

pytestmark = pytest.mark.unit

from scrapers.kaveri_deeds import (
    _extract_doc_no,
    _extract_date,
    _extract_deed_type,
    _extract_market_value,
    _extract_consideration,
    _extract_village,
    _extract_hobli,
    _extract_survey_no,
    _normalize_survey_no,
    _extract_extent,
    _extract_parties,
    _extract_psf,
    _is_header_row,
    _is_header_artifact,
    _parse_ec_form15_rows,
    _extract_sro_from_doc_no,
    parse_pdf_file,
    parse_inbox_file,
    parse_inbox_all,
    write_checkpoint,
    read_latest_checkpoint,
    _INBOX_DIR,
    _CHECKPOINT_DIR,
)

# ── Synthetic EC Form 15 table fixtures ────────────────────────────────────

_HEADER_ROWS = [
    # Row 0: Kannada header
    [
        "\u0c95\u0caa\u0ccd\u0cb0(cid:18)(cid:4)\u0cb8\u0c82\u0c95",
        "(ಎ) ಆಸಿಸ್ತಿ ವಿವರ",
        "ನಿವರ್ನಾಹ\nದಿನಾಂಕ",
        "(ಬಿ) ದಸ್ತಿನೇಜನ ಸಸ್ವರಮೂ\nಹಣ ಮೌಲ್ಯೆ\n(₹)",
        "ಕಕ್ಷಿದಾರರ ಹೆಸರು",
        "",
        "ಸಸಂ",
        "ಪುಟ",
        "ದಸ್ತಿನೇಜನ ಉಲೆಲ್ಲಿನೇಖ",
    ],
    # Row 1: Sub-header
    [None, None, None, None, "ಬರೆದು ಕೊಟ್ಟವರು", "ಬರೆಯಿಸಿಕೊಂಡವರು", None, None, None],
    # Row 2: Column numbers
    ["1", "2", "3", "4", "5", "6", "7", "8", "9"],
]

# Row 3+ = data

# Transaction 1 — Surrender of Lease, ₹1, Venkatala (3.pdf page 1 row 3)
_TXN1_ROW = [
    "1",
    "[LAND MARK] Department / Property Type: BBMP , Index-II Village: Venkatala, "
    "Ward Name: BBMP Ward No. 1, Hobli Name: Yalahanka 1, "
    "Measurement: 1 Sq.Feet",
    "03-03-2023",
    "Article Name:\nSurrender of Lease;;\nMarket Value:0;\nConsideration\nAmount:1",
    "M/S Sashidha Ventures Private Ltd rep by its Authorised representative",
    "Sri K L Shalivahan Tejaswi",
    "7",
    "BYPD1335",
    "BYP-1-14551-2022-23",
]
# Continuation of TXN1 — more property description
_TXN1_CONT_ROW = [
    None,
    "in all measuring 28311 Sq ft, and more property description",
    None,
    None,
    None,
    None,
    None,
    None,
    None,
]

# Transaction 2 — Discharge Deed, ₹20,00,000, Venkatala (3.pdf page 2 row 4)
_TXN2_ROW = [
    "2",
    "[LAND MARK] Index-II Village: Venkatala, Hobli Name: Yalahanka 1, "
    "Measurement: 1200 Sq.Feet",
    "15-02-2021",
    "Article Name:\nDischarge Deed;;\nMarket Value:0;\nConsideration Amount\n:2000000",
    "Sri.Vittal Souharda Credit Co-Operative Limited",
    "ಎ.ಎನ್. ಪ್ರನೇನಿಸ್ ಬಿನ್ ಎ.ಸಿ. ಗಜ ನಗಿ",
    "6",
    "YAND1209",
    "YAN-1-06807-2020-21",
]

# Transaction 3 — Sale Deed with survey number
_TXN3_ROW = [
    "3",
    "Sy No 45/2A, Index-II Village: Jakkur, Hobli Name: Yalahanka 1, "
    "in all measuring 2400 Sq ft",
    "15-05-2026",
    "Article Name:\nSale Deed;;\nMarket Value:8500000;\nConsideration Amount\n:8500000",
    "Venkatesh Gowda",
    "Infra Developers Pvt Ltd",
    "8",
    "BYPD1400",
    "BYP-1-14552-2022-23",
]

# Transaction 4 — Sale Deed with hyphen survey, across villages
_TXN4_ROW = [
    "4",
    "Sy. No. 45/2-A, Index-II Village: Allalasandra, Measurement: 1800 Sq.Feet",
    "22-03-2026",
    "Article Name:\nSale Deed;;\nMarket Value:6500000;\nConsideration Amount\n:6500000",
    "Muniyappa S/o Late Chikkaiah",
    "Priya Sharma D/o Ramesh Sharma",
    "9",
    "BYPD1401",
    "BYP-1-14553-2022-23",
]

# Transaction 5 — Minimal row with only doc_no, date, and consideration
_TXN5_ROW = [
    "5",
    "[LAND MARK] Sy. No. 26, Index-II Village: Mavallipura, measuring 1 Acre 0 Guntas",
    "07-12-2005",
    "Article Name:\nSale;;\nMarket Value:365000;\nConsideration Amount\n:365000",
    "Some Seller",
    "Some Buyer",
    "1",
    "YAND9999",
    "YAN-1-14052-2004-05",
]

# Header artifact row (Kannada overflow — "F\ny" in col3)
_HEADER_ARTIFACT_ROW = [
    None,
    None,
    "F\ny",
    None,
    None,
    None,
    None,
    None,
    None,
]

# ── Field extraction tests ──────────────────────────────────────────────────


def test_extract_doc_no_valid():
    assert _extract_doc_no("BYP-1-14551-2022-23") == "BYP-1-14551-2022-23"
    assert _extract_doc_no("YAN-1-06807-2020-21") == "YAN-1-06807-2020-21"
    assert _extract_doc_no("HSR-1-01290-2025-26") == "HSR-1-01290-2025-26"
    assert _extract_doc_no("HBB-1-05139-2014-15") == "HBB-1-05139-2014-15"
    assert _extract_doc_no("BYP-1-00167-2022-23") == "BYP-1-00167-2022-23"


def test_extract_doc_no_none():
    assert _extract_doc_no("") is None
    assert _extract_doc_no(None) is None
    assert _extract_doc_no("No document number here") is None
    assert _extract_doc_no("ABC-123") is None  # invalid format


def test_extract_doc_no_from_full_column():
    """Extract doc_no from embedded text (col9 often has extra chars)."""
    assert _extract_doc_no("BYP-1-14551-2022-23\n") == "BYP-1-14551-2022-23"


def test_extract_date_valid_dd_mm_yyyy():
    assert _extract_date("03-03-2023") == "2023-03-03"
    assert _extract_date("15-02-2021") == "2021-02-15"
    assert _extract_date("15-05-2026") == "2026-05-15"


def test_extract_date_with_overflow():
    """Date with leading 'F\ny' overflow from Kannada header."""
    assert _extract_date("F\ny15-02-2021") == "2021-02-15"
    assert _extract_date("F\ny30-01-2026") == "2026-01-30"


def test_extract_date_none():
    assert _extract_date("") is None
    assert _extract_date("invalid-date") is None


def test_extract_deed_type():
    assert (
        _extract_deed_type("Article Name:\nSurrender of Lease;;")
        == "Surrender of Lease"
    )
    assert _extract_deed_type("Article Name:\nDischarge Deed;;") == "Discharge Deed"
    assert _extract_deed_type("Article Name:\nSale Deed;;") == "Sale Deed"
    assert _extract_deed_type("Article Name:\nRelease deed ;;") == "Release deed"
    assert _extract_deed_type("") == ""
    assert _extract_deed_type("No article here") == ""


def test_extract_market_value():
    assert _extract_market_value("Market Value:0") == 0.0
    assert _extract_market_value("Market Value:8500000") == 8500000.0
    assert _extract_market_value("Market Value:null") is None
    assert _extract_market_value("") is None


def test_extract_consideration():
    assert _extract_consideration("Consideration\nAmount:1") == 1.0
    assert _extract_consideration("Consideration Amount\n:2000000") == 2000000.0
    assert _extract_consideration("Consideration Amount:8500000") == 8500000.0
    assert _extract_consideration("Consideration\nAmount:0") == 0.0
    assert _extract_consideration("") is None
    assert _extract_consideration("No consideration here") is None


def test_extract_village():
    assert _extract_village("Index-II Village: Venkatala") == "Venkatala"
    assert _extract_village("Index-II Village: Jakkur") == "Jakkur"
    assert _extract_village("Index-II Village: Mavallipura") == "Mavallipura"
    assert _extract_village("Property Number : 26**") == ""
    assert _extract_village("") == ""


def test_extract_hobli():
    assert _extract_hobli("Hobli Name: Yalahanka 1") == "Yalahanka 1"
    assert _extract_hobli("") == ""
    assert _extract_hobli("No hobli here") == ""


def test_extract_survey_no_standard():
    """Survey number from 'Sy No 3'."""
    result, confidence = _extract_survey_no("Sy No 3, situated at Venkatala")
    assert result == "3"
    assert confidence == "high"


def test_extract_survey_no_with_slash():
    """Survey number with slash: 'Sy. No. 45/2'."""
    result, confidence = _extract_survey_no("Sy. No. 45/2")
    assert result == "45/2"
    assert confidence == "high"


def test_extract_survey_no_with_hyphen():
    """Survey number with hyphen-A: 'Sy No: 45/2-A' → 45/2A."""
    result, confidence = _extract_survey_no("Sy. No. 45/2-A")
    assert result == "45/2A"
    assert confidence == "high"


def test_extract_survey_no_survey_no_prefix():
    """'Survey No. 101/1A'."""
    result, confidence = _extract_survey_no("Survey No. 101/1A")
    assert result == "101/1A"
    assert confidence == "high"


def test_extract_survey_no_none():
    """No survey number → None."""
    result, confidence = _extract_survey_no("Property without survey number")
    assert result is None
    assert confidence == "low"


def test_extract_survey_no_kannada():
    """Kannada text → confidence='low'."""
    result, confidence = _extract_survey_no(
        "Sy No 3 \u0c85\u0cb8\u0ccd\u0cb8\u0ca4\u0cbf"
    )
    assert result == "3"
    assert confidence == "low"


def test_normalize_survey_no():
    assert _normalize_survey_no("45/2-A") == "45/2A"
    assert _normalize_survey_no("  45/2  ") == "45/2"
    assert _normalize_survey_no("101/1A") == "101/1A"
    assert _normalize_survey_no("") is None
    assert _normalize_survey_no("N/A") is None
    assert _normalize_survey_no("NIL") is None


def test_extract_extent_in_all_measuring():
    """Prefer 'in all measuring' pattern."""
    assert _extract_extent("in all measuring 28311 Sq ft") == 28311.0
    assert _extract_extent("in all measuring 2400 Sq.ft") == 2400.0


def test_extract_extent_measurement_fallback():
    """Fallback to 'Measurement: N Sq.Feet'."""
    assert _extract_extent("Measurement: 1200 Sq.Feet") == 1200.0


def test_extract_extent_acres_guntas():
    """Extent in acres/guntas → convert to sqft."""
    result = _extract_extent("measuring 1 Acre 0 Guntas")
    assert result == 43560.0
    result = _extract_extent("1 Acre 10 Guntas")
    assert result == 43560.0 + 10890.0


def test_extract_extent_none():
    assert _extract_extent("") is None
    assert _extract_extent("No extent here") is None


def test_extract_extent_prefers_in_all():
    """'in all measuring' overrides 'Measurement:'."""
    text = "Measurement: 1 Sq.Feet, in all measuring 28311 Sq ft"
    assert _extract_extent(text) == 28311.0


def test_extract_parties_clean():
    """Clean ASCII buyer/seller → medium confidence."""
    seller, buyer, conf = _extract_parties(
        "Venkatesh Gowda", "Infra Developers Pvt Ltd"
    )
    assert seller == "Venkatesh Gowda"
    assert buyer == "Infra Developers Pvt Ltd"
    assert conf == "medium"


def test_extract_parties_with_cid():
    """(cid:N) text → extracted but low confidence."""
    seller, buyer, conf = _extract_parties(
        "Clean Seller",
        "ಎ.ಎನ್. (cid:133)iಪ್ರನೇನಿ(cid:118)ಸ್ ಬಿನ್",
    )
    assert conf == "low"


def test_extract_parties_kannada():
    """Kannada party names → low confidence."""
    seller, buyer, conf = _extract_parties(
        "Clean Seller",
        "\u0c8e.\u0c8e\u0ca8\u0ccd. \u0caa\u0ccd\u0cb0\u0ca8\u0cc7\u0ca8\u0cbf\u0cb8\u0ccd",
    )
    assert conf == "low"


def test_extract_psf():
    psf, conf = _extract_psf(5000000, 1000)
    assert psf == 5000.0
    assert conf == "medium"


def test_extract_psf_out_of_bounds():
    psf, conf = _extract_psf(100, 1000)
    assert psf is None
    assert conf == "low"
    psf, conf = _extract_psf(100000000, 1000)
    assert psf is None
    assert conf == "low"


def test_extract_psf_missing():
    psf, conf = _extract_psf(None, 1000)
    assert psf is None
    assert conf == "low"
    psf, conf = _extract_psf(5000000, None)
    assert psf is None
    assert conf == "low"


# ── Header detection tests ──────────────────────────────────────────────────


def test_is_header_row_row0():
    assert _is_header_row(_HEADER_ROWS[0]) is True


def test_is_header_row_row2():
    assert _is_header_row(_HEADER_ROWS[2]) is True


def test_is_header_row_data():
    """Data rows should NOT be headers."""
    assert _is_header_row(_TXN1_ROW) is False
    assert _is_header_row(_TXN2_ROW) is False


def test_is_header_artifact():
    """'F\\ny' row with no doc_no → artifact."""
    assert _is_header_artifact(_HEADER_ARTIFACT_ROW) is True


def test_is_header_artifact_data():
    """Real data row → not artifact."""
    assert _is_header_artifact(_TXN1_ROW) is False
    assert _is_header_artifact(_TXN3_ROW) is False


# ── SRO extraction ──────────────────────────────────────────────────────────


def test_extract_sro_from_doc_no():
    assert _extract_sro_from_doc_no("BYP-1-14551-2022-23") == "Gandhinagar"
    assert _extract_sro_from_doc_no("YAN-1-06807-2020-21") == "Gandhinagar"
    assert _extract_sro_from_doc_no("HBB-1-05139-2014-15") == "Rajajinagar"
    assert _extract_sro_from_doc_no("") is None
    assert _extract_sro_from_doc_no(None) is None


# ── Full table parsing tests ────────────────────────────────────────────────


def test_parse_ec_form15_single_transaction():
    """Single transaction → 1 record."""
    rows = _HEADER_ROWS + [_TXN3_ROW]
    records = _parse_ec_form15_rows(rows)
    assert len(records) == 1
    assert records[0]["doc_no"] == "BYP-1-14552-2022-23"
    assert records[0]["village"] == "Jakkur"
    assert records[0]["survey_no"] == "45/2A"
    assert records[0]["deed_type"] == "Sale Deed"


def test_parse_ec_form15_multi_transaction():
    """Multiple transactions → multiple records."""
    rows = _HEADER_ROWS + [_TXN1_ROW, _TXN2_ROW]
    records = _parse_ec_form15_rows(rows)
    assert len(records) == 2
    assert records[0]["doc_no"] == "BYP-1-14551-2022-23"
    assert records[0]["deed_type"] == "Surrender of Lease"
    assert records[0]["consideration_inr"] == 1.0
    assert records[1]["doc_no"] == "YAN-1-06807-2020-21"
    assert records[1]["deed_type"] == "Discharge Deed"
    assert records[1]["consideration_inr"] == 2000000.0


def test_parse_ec_form15_continuation():
    """Continuation row stitched to previous transaction."""
    rows = _HEADER_ROWS + [_TXN1_ROW, _TXN1_CONT_ROW, _TXN2_ROW]
    records = _parse_ec_form15_rows(rows)
    assert len(records) == 2
    # TXN1 should have the stitched property description including continuation
    desc = records[0].get("property_description", "")
    assert "in all measuring 28311 Sq ft" in desc
    # Extent should be from the 'in all measuring' pattern (preferred)
    assert records[0]["extent_sqft"] == 28311.0


def test_parse_ec_form15_header_artifacts():
    """Header artifacts should be filtered out."""
    rows = _HEADER_ROWS + [_HEADER_ARTIFACT_ROW, _TXN2_ROW]
    records = _parse_ec_form15_rows(rows)
    assert len(records) == 1
    assert records[0]["doc_no"] == "YAN-1-06807-2020-21"


def test_parse_ec_form15_empty():
    """No data rows → empty list."""
    records = _parse_ec_form15_rows([])
    assert records == []
    records = _parse_ec_form15_rows(_HEADER_ROWS)
    assert records == []


def test_parse_ec_form15_acres_extent():
    """Extent in acres → converted to sqft."""
    rows = _HEADER_ROWS + [_TXN5_ROW]
    records = _parse_ec_form15_rows(rows)
    assert len(records) == 1
    assert records[0]["doc_no"] == "YAN-1-14052-2004-05"
    assert records[0]["survey_no"] == "26"
    assert records[0]["extent_sqft"] == 43560.0


# ── pdfplumber integration tests ────────────────────────────────────────────


def test_parse_pdf_file_mocked():
    """Mock pdfplumber to return synthetic table data."""
    mock_rows = _HEADER_ROWS + [_TXN3_ROW, _TXN4_ROW]

    mock_page = MagicMock()
    mock_page.extract_tables.return_value = [mock_rows]

    mock_pdf = MagicMock()
    mock_pdf.__enter__.return_value = mock_pdf
    mock_pdf.pages = [mock_page]

    with patch("pdfplumber.open", return_value=mock_pdf):
        records = parse_pdf_file(Path("test.pdf"))

    assert len(records) == 2
    assert records[0]["doc_no"] == "BYP-1-14552-2022-23"
    assert records[1]["doc_no"] == "BYP-1-14553-2022-23"
    assert records[0]["data_source"] == "kaveri_inbox"
    assert records[0]["source_ref"] == "test.pdf"


def test_parse_pdf_file_empty():
    """Empty PDF → empty records."""
    mock_page = MagicMock()
    mock_page.extract_tables.return_value = [[]]
    mock_pdf = MagicMock()
    mock_pdf.__enter__.return_value = mock_pdf
    mock_pdf.pages = [mock_page]

    with patch("pdfplumber.open", return_value=mock_pdf):
        records = parse_pdf_file(Path("empty.pdf"))
    assert records == []


# ── Inbox file parsing tests ────────────────────────────────────────────────


def test_parse_inbox_file_pdf_mocked():
    """Parse inbox PDF file via mocked pdfplumber."""
    mock_rows = _HEADER_ROWS + [_TXN3_ROW]
    mock_page = MagicMock()
    mock_page.extract_tables.return_value = [mock_rows]
    mock_pdf = MagicMock()
    mock_pdf.__enter__.return_value = mock_pdf
    mock_pdf.pages = [mock_page]

    fpath = Path("data/kaveri_deeds/inbox/test_deed.pdf")
    with patch("pdfplumber.open", return_value=mock_pdf):
        records = parse_inbox_file(fpath)
    assert len(records) == 1
    assert records[0]["doc_no"] == "BYP-1-14552-2022-23"
    assert records[0]["data_source"] == "kaveri_inbox"
    assert records[0]["source_ref"] == "test_deed.pdf"


def test_parse_inbox_file_unsupported():
    """Unsupported file type → empty."""
    from pathlib import Path

    records = parse_inbox_file(Path("test.txt"))
    assert records == []
    records = parse_inbox_file(Path("test.html"))
    assert records == []
    records = parse_inbox_file(Path("test.xyz"))
    assert records == []


# ── Inbox all parsing tests ─────────────────────────────────────────────────


def test_parse_inbox_all_empty_dir():
    """Empty inbox directory returns empty list."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        inbox = Path(tmp)
        with patch("scrapers.kaveri_deeds._INBOX_DIR", inbox):
            records = parse_inbox_all()
    assert records == []


def test_parse_inbox_all_non_pdf_ignored():
    """Non-PDF files in inbox are ignored."""
    with tempfile.TemporaryDirectory() as tmp:
        inbox = Path(tmp)
        inbox.mkdir(parents=True, exist_ok=True)
        txt_file = inbox / "notes.txt"
        txt_file.write_text("not a pdf")
        with patch("scrapers.kaveri_deeds._INBOX_DIR", inbox):
            records = parse_inbox_all()
    assert records == []


def test_parse_inbox_all_mocked():
    """Parse all inbox files with mocked pdfplumber."""
    mock_rows = _HEADER_ROWS + [_TXN3_ROW]
    mock_page = MagicMock()
    mock_page.extract_tables.return_value = [mock_rows]
    mock_pdf = MagicMock()
    mock_pdf.__enter__.return_value = mock_pdf
    mock_pdf.pages = [mock_page]

    # Create a temp dir mimicking inbox
    with tempfile.TemporaryDirectory() as tmp:
        inbox = Path(tmp) / "inbox"
        inbox.mkdir(parents=True)
        pdf_file = inbox / "test1.pdf"
        pdf_file.write_text("dummy")

        with patch("scrapers.kaveri_deeds._INBOX_DIR", inbox):
            with patch("pdfplumber.open", return_value=mock_pdf):
                records = parse_inbox_all()
    assert len(records) >= 1


# ── Checkpoint tests ────────────────────────────────────────────────────────


def test_write_and_read_checkpoint():
    """Write then read checkpoint round-trip."""
    records = [
        {
            "doc_no": "BYP-1-14551-2022-23",
            "reg_date": "2023-03-03",
            "village": "Venkatala",
        },
        {
            "doc_no": "YAN-1-06807-2020-21",
            "reg_date": "2021-02-15",
            "village": "Venkatala",
        },
    ]
    fpath = write_checkpoint(records, "inbox")
    assert fpath.exists()
    loaded = read_latest_checkpoint()
    assert loaded is not None
    assert len(loaded) == 2
    assert loaded[0]["doc_no"] == "BYP-1-14551-2022-23"
    fpath.unlink()


# ── Real PDF parsing tests (integration) ────────────────────────────────────


@pytest.mark.integration
def test_3pdf_parses():
    """3.pdf → exactly 2 records with correct fields."""
    fpath = Path("data/kaveri_deeds/samples/3.pdf")
    if not fpath.exists():
        pytest.skip("3.pdf not found")
    records = parse_pdf_file(fpath)
    assert len(records) == 2
    assert records[0]["doc_no"] == "BYP-1-14551-2022-23"
    assert records[0]["reg_date"] == "2023-03-03"
    assert records[0]["deed_type"] == "Surrender of Lease"
    assert records[0]["consideration_inr"] == 1.0
    assert records[0]["village"] == "Venkatala"
    assert records[1]["doc_no"] == "YAN-1-06807-2020-21"
    assert records[1]["reg_date"] == "2021-02-15"
    assert records[1]["deed_type"] == "Discharge Deed"
    assert records[1]["consideration_inr"] == 2000000.0
    assert records[1]["village"] == "Venkatala"


@pytest.mark.integration
def test_26pdf_no_validation_errors():
    """26.pdf parses with 0 validation errors."""
    fpath = Path("data/kaveri_deeds/samples/26.pdf")
    if not fpath.exists():
        pytest.skip("26.pdf not found")
    records = parse_pdf_file(fpath)
    assert len(records) > 0
    for r in records:
        assert r["doc_no"], "Missing doc_no in record"
        assert r["reg_date"], f"Missing reg_date in record {r['doc_no']}"


@pytest.mark.integration
def test_62pdf_no_validation_errors():
    """62.pdf parses with 0 validation errors."""
    fpath = Path("data/kaveri_deeds/samples/62.pdf")
    if not fpath.exists():
        pytest.skip("62.pdf not found")
    records = parse_pdf_file(fpath)
    assert len(records) > 0
    for r in records:
        assert r["doc_no"], "Missing doc_no in record"
        assert r["reg_date"], f"Missing reg_date in record {r['doc_no']}"
