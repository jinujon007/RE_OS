"""BhoomiRTCParser unit tests — GATE-99, T-1186."""

import pytest
pytestmark = pytest.mark.unit

from scrapers.bhoomi_rtc_parser import BhoomiRTCParser

_SYNTHETIC_HTML_FULL = """
<html><body>
<table>
<tr><th>Khata No</th><td>KHA-1234</td></tr>
<tr><th>Holder Name</th><td>Venkatesh Gowda</td></tr>
<tr><th>Previous Holder</th><td>Muniswamy Reddy</td></tr>
</table>
<table>
<tr><th>Encumbrance</th><td>Mortgage of Rs 50000</td></tr>
</table>
Property Area: 2.5 Acres
Transfer Date: 15-03-2022
Government Acquisition Notice Pending
</body></html>
"""

_SYNTHETIC_HTML_MINIMAL = """
<html><body>
<p>No RTC data available for this survey number.</p>
</body></html>
"""

_SYNTHETIC_HTML_EMPTY = ""

_SYNTHETIC_HTML_GOVT_ACQ = """
<html><body>
<table>
<tr><th>Khata No</th><td>KHA-5678</td></tr>
<tr><th>Holder Name</th><td>Karnataka Industrial Areas Development Board</td></tr>
</table>
<p>KIADB Acquisition Notification No. 123/2023</p>
</body></html>
"""

_SYNTHETIC_HTML_ENCUMBRANCE = """
<html><body>
<table>
<tr><th>Khata No</th><td>KHA-9012</td></tr>
<tr><th>Holder Name</th><td>Ramesh S</td></tr>
</table>
<table>
<tr><th>Encumbrance</th><td>1. Court Attachment Order No. 45/2022</td></tr>
<tr><th>Encumbrance</th><td>2. Mortgage of Rs 200000</td></tr>
</table>
Area: 50 Cents
</body></html>
"""

_SYNTHETIC_HTML_GUNTAS = """
<html><body>
<table>
<tr><th>Khata No</th><td>KHA-3456</td></tr>
<tr><th>Holder Name</th><td>Mohan K</td></tr>
</table>
Area: 15 Guntas
Transfer Date: 2022-08-01
</body></html>
"""

_SYNTHETIC_HTML_COMPOUND_AREA = """
<html><body>
<table>
<tr><th>Khata No</th><td>KHA-7788</td></tr>
<tr><th>Holder Name</th><td>Gopal Reddy</td></tr>
</table>
Area: 1 Acre 20 Guntas
</body></html>
"""

_SYNTHETIC_HTML_YMD_DATE = """
<html><body>
<table>
<tr><th>Khata No</th><td>KHA-9900</td></tr>
<tr><th>Holder Name</th><td>Suresh</td></tr>
</table>
Transfer Date: 2023-06-15
</body></html>
"""

_SYNTHETIC_HTML_NONSENSE = (
    "This is not valid HTML at all just some random text with khata mentioned somewhere. "
    "Owner of the land is someone named Lakshmamma. That's all we have."
)


class TestBhoomiRTCParser:
    def setup_method(self):
        self.parser = BhoomiRTCParser()

    def test_rtc_parser_extracts_khata_no(self):
        result = self.parser.parse(_SYNTHETIC_HTML_FULL)
        assert result.get("khata_no") == "KHA-1234"

    def test_rtc_parser_extracts_owner_name(self):
        result = self.parser.parse(_SYNTHETIC_HTML_FULL)
        assert result.get("owner_name") == "Venkatesh Gowda"

    def test_rtc_parser_detects_govt_acquisition(self):
        result = self.parser.parse(_SYNTHETIC_HTML_GOVT_ACQ)
        assert result.get("govt_acquisition_notice") is True
        assert result.get("govt_acquisition_detail") is not None
        assert "KIADB" in result["govt_acquisition_detail"]

    def test_rtc_parser_tolerates_missing_table(self):
        result = self.parser.parse(_SYNTHETIC_HTML_MINIMAL)
        assert isinstance(result, dict)
        assert result.get("khata_no") is None
        assert result.get("encumbrance_flag") is False

    def test_rtc_parser_area_converts_cents_to_acres(self):
        result = self.parser.parse(_SYNTHETIC_HTML_ENCUMBRANCE)
        assert result.get("area_acres") is not None
        assert result.get("area_acres") == 0.5

    def test_rtc_parser_transfer_date_normalized_dmy(self):
        result = self.parser.parse(_SYNTHETIC_HTML_FULL)
        assert result.get("transfer_date") == "2022-03-15"

    def test_rtc_parser_transfer_date_normalized_ymd(self):
        result = self.parser.parse(_SYNTHETIC_HTML_YMD_DATE)
        assert result.get("transfer_date") == "2023-06-15"

    def test_rtc_parser_encumbrance_flag_and_detail(self):
        result = self.parser.parse(_SYNTHETIC_HTML_ENCUMBRANCE)
        assert result.get("encumbrance_flag") is True
        assert result.get("encumbrance_detail") is not None
        assert "Court Attachment" in result["encumbrance_detail"]

    def test_rtc_parser_empty_html_returns_defaults(self):
        result = self.parser.parse(_SYNTHETIC_HTML_EMPTY)
        assert isinstance(result, dict)
        assert result.get("encumbrance_flag") is False
        assert result.get("govt_acquisition_notice") is False
        assert result.get("parser_completeness_score") == 0.0

    def test_rtc_parser_guntas_conversion(self):
        result = self.parser.parse(_SYNTHETIC_HTML_GUNTAS)
        assert result.get("area_acres") is not None
        assert result.get("area_acres") == pytest.approx(0.375, rel=0.01)

    def test_rtc_parser_compound_area(self):
        result = self.parser.parse(_SYNTHETIC_HTML_COMPOUND_AREA)
        assert result.get("area_acres") is not None
        assert result.get("area_acres") == pytest.approx(1.5, rel=0.01)

    def test_rtc_parser_nonsense_does_not_crash(self):
        result = self.parser.parse(_SYNTHETIC_HTML_NONSENSE)
        assert isinstance(result, dict)

    def test_rtc_parser_completeness_score_full(self):
        result = self.parser.parse(_SYNTHETIC_HTML_FULL)
        assert result.get("parser_completeness_score", 0) >= 0.5

    def test_rtc_parser_completeness_score_minimal(self):
        result = self.parser.parse(_SYNTHETIC_HTML_MINIMAL)
        assert result.get("parser_completeness_score", 1.0) < 0.5
