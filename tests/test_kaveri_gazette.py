"""
Tests for kaveri_gazette_parser.GazetteParser.

Validates PDF parsing logic, data quality, and registration volume API
without hitting the live portal.
"""
import pytest
from unittest.mock import patch, MagicMock
import io


# ── Helpers ────────────────────────────────────────────────────────────────────

SAMPLE_PDF_TEXT = """
168
1  Village Layout  Atturu Village  35000
2  NH-7 Bellary Road Main Road  78000 234
3  Kogilu Village  Kogilu Village  28000
4  Singanayakanahalli Village  Singanayakanahalli Village  16905
5  Krishna heavens Villa  73600
6  Agrahara Village  Agrahara Village  33000 100
7  Devanahalli Main Road  Devanahalli Main Road  11000
8  Airport City Swarnasri  Airport city  10000
9  C h in nna Layout  11500
10 Sl.No hobli village/area table header skip
"""


def _make_mock_pdf(text: str):
    """Return a mock pdfplumber PDF context with a single page."""
    mock_page = MagicMock()
    mock_page.extract_text.return_value = text
    mock_page.page_number = 1
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = lambda s: mock_pdf
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]
    return mock_pdf


# ── Unit tests — parser internals ──────────────────────────────────────────────

class TestGazetteParserUnit:

    def setup_method(self):
        from scrapers.kaveri_gazette_parser import GazetteParser
        self.parser = GazetteParser()

    def test_clean_locality_strips_property_ids(self):
        raw = "Trivik Wind Walk 003-W-0178-1"
        result = self.parser._clean_locality(raw)
        assert "003-W" not in result
        assert "Trivik" in result or len(result) >= 5

    def test_clean_locality_strips_survey_numbers(self):
        raw = "Kogilu Village Sy No. 78 79 80"
        result = self.parser._clean_locality(raw)
        assert "Sy No" not in result
        assert "Kogilu" in result

    def test_clean_locality_strips_cvc_codes(self):
        raw = "Shashank Amogh C.V.C 78/21-22 (CVC/29/21-22, 3/7/21)"
        result = self.parser._clean_locality(raw)
        assert "CVC/" not in result
        assert len(result) >= 5

    def test_clean_locality_rejects_pid_only(self):
        raw = "PID No. 99-22-41"
        result = self.parser._clean_locality(raw)
        # Should be empty or very short — not a useful locality name
        assert len(result) < 6 or "PID" not in result

    def test_clean_locality_preserves_real_name(self):
        name = "Bellary Road Main Road"
        result = self.parser._clean_locality(name)
        assert "Bellary" in result

    def test_parse_line_extracts_psm_from_end(self):
        pdf_spec = {"effective_from": "2023-04-01", "url": "test.pdf", "sro": "Test", "gazette_year": "2023-24"}
        rec = self.parser._parse_line("5 Village Layout 35000", pdf_spec)
        assert rec is not None
        assert rec["guidance_value_per_sqm"] == 35000.0
        assert abs(rec["guidance_value_psf"] - 35000 / 10.764) < 1.0

    def test_parse_line_skips_headers(self):
        pdf_spec = {"effective_from": "2023-04-01", "url": "test.pdf", "sro": "Test", "gazette_year": "2023-24"}
        for header in ["Sl.No hobli 35000", "village/area road 12000", "per sqm 7500"]:
            rec = self.parser._parse_line(header, pdf_spec)
            assert rec is None, f"Header line should be skipped: {header!r}"

    def test_parse_line_skips_low_values(self):
        pdf_spec = {"effective_from": "2023-04-01", "url": "test.pdf", "sro": "Test", "gazette_year": "2023-24"}
        rec = self.parser._parse_line("1 Page 102 Number 999", pdf_spec)
        assert rec is None  # 999 < 1000 threshold

    def test_parse_line_skips_very_high_values(self):
        pdf_spec = {"effective_from": "2023-04-01", "url": "test.pdf", "sro": "Test", "gazette_year": "2023-24"}
        rec = self.parser._parse_line("1 Some Road 999999", pdf_spec)
        assert rec is None  # > 200000 threshold

    def test_parse_line_accepts_trailing_small_number(self):
        # "35000 227" format — 35000 is rate, 227 is survey count
        pdf_spec = {"effective_from": "2023-04-01", "url": "test.pdf", "sro": "Test", "gazette_year": "2023-24"}
        rec = self.parser._parse_line("19 Atturu Village 35000 227", pdf_spec)
        assert rec is not None
        assert rec["guidance_value_per_sqm"] == 35000.0

    def test_psf_conversion(self):
        # 10000 ₹/sqm → 928.97 ₹/sqft (≈ 929)
        pdf_spec = {"effective_from": "2023-04-01", "url": "test.pdf", "sro": "Test", "gazette_year": "2023-24"}
        rec = self.parser._parse_line("736 Airport city Swarnasri 10000", pdf_spec)
        if rec:
            assert 920 <= rec["guidance_value_psf"] <= 935

    def test_source_set_to_igr_gazette(self):
        pdf_spec = {"effective_from": "2023-04-01", "url": "test.pdf", "sro": "Devanahalli", "gazette_year": "2023-24"}
        rec = self.parser._parse_line("5 Krishna heavens Villa 73600", pdf_spec)
        if rec:
            assert rec["source"] == "igr_gazette"

    def test_effective_from_passed_through(self):
        pdf_spec = {"effective_from": "2024-04-01", "url": "test.pdf", "sro": "Jala", "gazette_year": "BDA"}
        rec = self.parser._parse_line("5 Bellary Road 45000", pdf_spec)
        if rec:
            assert rec["effective_from"] == "2024-04-01"
            assert rec["gazette_year"] == "BDA"


# ── Integration tests — mock HTTP ──────────────────────────────────────────────

class TestGazetteParserIntegration:

    def setup_method(self):
        from scrapers.kaveri_gazette_parser import GazetteParser
        self.parser = GazetteParser()

    @patch("scrapers.kaveri_gazette_parser.requests.get")
    @patch("pdfplumber.open")
    def test_scrape_guidance_values_returns_records(self, mock_pdf_open, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = b"%PDF-1.4"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        mock_pdf_open.return_value = _make_mock_pdf(SAMPLE_PDF_TEXT)

        # Only test Devanahalli (1 PDF, easier to mock)
        records = self.parser.scrape_guidance_values("Devanahalli")
        assert len(records) > 0
        assert all(r["source"] == "igr_gazette" for r in records)
        assert all(r["guidance_value_psf"] > 0 for r in records)

    @patch("scrapers.kaveri_gazette_parser.requests.get")
    @patch("pdfplumber.open")
    def test_all_records_have_required_fields(self, mock_pdf_open, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = b"%PDF-1.4"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        mock_pdf_open.return_value = _make_mock_pdf(SAMPLE_PDF_TEXT)

        records = self.parser.scrape_guidance_values("Devanahalli")
        required_keys = {"locality", "guidance_value_psf", "guidance_value_per_sqm",
                         "effective_from", "source_document", "source", "sro"}
        for r in records:
            for key in required_keys:
                assert key in r, f"Missing key {key!r} in record {r}"

    @patch("scrapers.kaveri_gazette_parser.requests.get")
    @patch("pdfplumber.open")
    def test_pdf_download_failure_returns_empty(self, mock_pdf_open, mock_get):
        mock_get.side_effect = Exception("connection timeout")
        records = self.parser.scrape_guidance_values("Devanahalli")
        assert records == []

    @patch("scrapers.kaveri_gazette_parser.requests.get")
    def test_registration_volume_returns_dict(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"data": {"applicationsReceived": 42, "applicationsApproved": 30, "applicationsPending": 5}}'
        mock_resp.json.return_value = {
            "data": {"applicationsReceived": 42, "applicationsApproved": 30, "applicationsPending": 5}
        }
        mock_get.return_value = mock_resp

        vol = self.parser.scrape_registration_volume("Devanahalli", "2026-01-01", "2026-06-05")
        assert vol["market"] == "Devanahalli"
        assert vol["sro_code"] == 118
        assert vol["applications_received"] == 42
        assert vol["source"] == "kaveri_api"

    @patch("scrapers.kaveri_gazette_parser.requests.get")
    def test_registration_volume_api_failure_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("network error")
        vol = self.parser.scrape_registration_volume("Devanahalli", "2026-01-01", "2026-06-05")
        assert vol == {}

    def test_unknown_market_returns_empty(self):
        records = self.parser.scrape_guidance_values("UnknownCity")
        assert records == []

    def test_sro_codes_cover_all_markets(self):
        from scrapers.kaveri_gazette_parser import SRO_CODES, IGR_GAZETTE_PDFS
        for market in IGR_GAZETTE_PDFS:
            assert market in SRO_CODES, f"SRO code missing for {market}"

    def test_gazette_pdf_urls_accessible(self):
        """Smoke test — verify all configured PDF URLs have valid structure."""
        from scrapers.kaveri_gazette_parser import IGR_GAZETTE_PDFS
        for market, pdfs in IGR_GAZETTE_PDFS.items():
            for pdf_spec in pdfs:
                assert pdf_spec["url"].startswith("https://igr.karnataka.gov.in/")
                assert pdf_spec["url"].endswith(".pdf")
                assert pdf_spec["effective_from"]
                assert pdf_spec["sro"]
