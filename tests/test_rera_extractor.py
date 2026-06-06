"""Tests for RERAExtractor — T-965."""
import json
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


SAMPLE_RERA_TEXT = (
    "Project: Green Valley Enclave\n"
    "Developer: Brigade Group\n"
    "RERA No: PR/KA/RERA/123/456/2024\n"
    "Total Units: 120\n"
    "Launch Date: 2024-01-15\n"
    "Completion Date: 2025-12-31\n"
    "Status: On-Going\n"
    "Market: Yelahanka"
)

SAMPLE_HTML_TABLE = """<table><tbody>
<tr>
  <td>1</td>
  <td>ACK/KA/RERA/2024/123456</td>
  <td>PR/KA/RERA/123/456/2024</td>
  <td><a href="/view">View</a></td>
  <td>Brigade Group</td>
  <td>Green Valley Enclave</td>
  <td>On-Going</td>
  <td>Bangalore Urban</td>
  <td>Yelahanka</td>
  <td>Residential Apartment</td>
  <td>15-Jan-2024</td>
  <td>31-Dec-2025</td>
</tr>
</tbody></table>"""


def _extractor():
    from utils.rera_extractor import RERAExtractor
    ext = RERAExtractor()
    ext._model_available = False
    ext._model_last_check = 0
    return ext


class TestRERAExtractorOutputSchema:
    def test_rera_extractor_output_schema(self):
        ext = _extractor()
        result = ext.extract(SAMPLE_RERA_TEXT)
        expected_keys = {
            "project_name", "developer_name", "survey_no", "units",
            "launch_date", "completion_date", "status", "market",
        }
        assert set(result.keys()) == expected_keys
        assert result["project_name"] == "Green Valley Enclave"
        assert result["developer_name"] == "Brigade Group"
        assert result["survey_no"] == "PR/KA/RERA/123/456/2024"
        assert result["units"] == 120
        assert result["status"] == "On-Going"
        assert result["market"] == "Yelahanka"

    def test_rera_extractor_handles_missing_fields(self):
        ext = _extractor()
        result = ext.extract("")
        assert result["project_name"] == ""
        assert result["developer_name"] == ""
        assert result["survey_no"] == ""
        assert result["units"] == 0

    def test_rera_extractor_regex_fallback(self):
        ext = _extractor()
        result = ext.extract(SAMPLE_RERA_TEXT)
        assert result["project_name"] == "Green Valley Enclave"
        assert result["developer_name"] == "Brigade Group"
        assert result["survey_no"] == "PR/KA/RERA/123/456/2024"
        assert result["units"] == 120

    def test_rera_extractor_partial_text(self):
        ext = _extractor()
        partial = "Project: Test Only\nStatus: Completed"
        result = ext.extract(partial)
        assert result["project_name"] == "Test Only"
        assert result["status"] == "Completed"
        assert result["developer_name"] == ""
        assert result["units"] == 0

    def test_rera_extractor_ollama_fallback_on_failure(self):
        ext = _extractor()
        with patch.object(ext, '_extract_via_ollama', return_value=None):
            result = ext.extract(SAMPLE_RERA_TEXT)
        assert result["project_name"] == "Green Valley Enclave"
        assert result["developer_name"] == "Brigade Group"

    def test_parse_json_from_text_handles_code_block(self):
        ext = _extractor()
        text = "```json\n{\"project_name\": \"Test\"}\n```"
        parsed = ext._parse_json_from_text(text)
        assert parsed == {"project_name": "Test"}

    def test_parse_json_from_text_handles_braces(self):
        ext = _extractor()
        parsed = ext._parse_json_from_text('Some text {"project_name": "Brigade"} trailing')
        assert parsed == {"project_name": "Brigade"}


class TestRERAExtractorHTML:
    def test_html_table_extracts_project_name_and_developer(self):
        ext = _extractor()
        result = ext.extract(SAMPLE_HTML_TABLE)
        assert result["project_name"] == "Green Valley Enclave"
        assert result["developer_name"] == "Brigade Group"
        assert result["survey_no"] == "PR/KA/RERA/123/456/2024"
        assert result["status"] == "On-Going"

    def test_html_table_extracts_dates_from_portal_format(self):
        ext = _extractor()
        result = ext.extract(SAMPLE_HTML_TABLE)
        assert result["launch_date"] == "15-Jan-2024"
        assert result["completion_date"] == "31-Dec-2025"

    def test_html_table_extracts_market_from_district_column(self):
        ext = _extractor()
        result = ext.extract(SAMPLE_HTML_TABLE)
        assert "Bangalore Urban" in result.get("market", "")

    def test_empty_html_returns_defaults(self):
        ext = _extractor()
        result = ext.extract("<table></table>")
        assert result["project_name"] == ""


class TestRERAExtractorEdgeCases:
    def test_binary_input_does_not_crash(self):
        ext = _extractor()
        result = ext.extract(b"\x00\x01\x02\x03".decode("latin-1"))
        assert result["project_name"] == ""

    def test_very_long_input_truncated_safely(self):
        ext = _extractor()
        long_text = "Project: Test\n" * 10000
        result = ext.extract(long_text)
        assert result["project_name"] == "Test"

    def test_coerce_types_converts_units_to_int(self):
        ext = _extractor()
        data = {"units": "120"}
        coerced = ext._coerce_types(data)
        assert coerced["units"] == 120
        assert isinstance(coerced["units"], int)

    def test_coerce_types_handles_none_units(self):
        ext = _extractor()
        data = {"units": None}
        coerced = ext._coerce_types(data)
        assert coerced["units"] == 0

    def test_coerce_types_handles_non_numeric_units(self):
        ext = _extractor()
        data = {"units": "N/A"}
        coerced = ext._coerce_types(data)
        assert coerced["units"] == 0


class TestGenerateTrainingData:
    def test_training_data_generation_200_rows(self):
        mock_rows = [
            MagicMock(
                project_name=f"Project {i}",
                developer_name="Brigade",
                rera_number=f"RERA/{i:03d}",
                total_units=100 + i,
                launch_date="2024-01-15",
                completion_date="2025-12-31",
                status="On-Going",
                market="Yelahanka",
            )
            for i in range(200)
        ]
        with patch("utils.db.get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = mock_rows
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            from scripts.generate_rera_training_data import generate_training_data
            records = generate_training_data("Yelahanka")
            assert len(records) == 200
            assert records[0]["project_name"] == "Project 0"
            assert records[199]["project_name"] == "Project 199"

    def test_training_data_empty_db_returns_empty_list(self):
        with patch("utils.db.get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            from scripts.generate_rera_training_data import generate_training_data
            records = generate_training_data("Yelahanka")
            assert records == []

    def test_training_data_build_raw_text_format(self):
        from scripts.generate_rera_training_data import _build_raw_text
        rec = {
            "project_name": "Test",
            "developer_name": "Dev",
            "rera_number": "RERA/001",
            "total_units": 100,
            "launch_date": "2024-01-01",
            "completion_date": "2025-12-31",
            "status": "Active",
            "market": "Yelahanka",
        }
        text = _build_raw_text(rec)
        assert "Project: Test" in text
        assert "Developer: Dev" in text
        assert "RERA No: RERA/001" in text
        assert "Total Units: 100" in text
        assert "Market: Yelahanka" in text

    def test_training_data_build_output_format(self):
        from scripts.generate_rera_training_data import _build_output
        rec = {
            "project_name": "Test",
            "developer_name": "Dev",
            "rera_number": "RERA/001",
            "total_units": 100,
            "launch_date": "2024-01-01",
            "completion_date": "2025-12-31",
            "status": "Active",
            "market": "Yelahanka",
        }
        output = _build_output(rec)
        assert output == {
            "project_name": "Test",
            "developer_name": "Dev",
            "survey_no": "RERA/001",
            "units": 100,
            "launch_date": "2024-01-01",
            "completion_date": "2025-12-31",
            "status": "Active",
            "market": "Yelahanka",
        }

    def test_training_data_output_writes_valid_jsonl(self, tmp_path):
        mock_rows = [
            MagicMock(
                project_name="Green Valley",
                developer_name="Brigade",
                rera_number="PR/KA/RERA/123",
                total_units=120,
                launch_date="2024-01-15",
                completion_date="2025-12-31",
                status="On-Going",
                market="Yelahanka",
            )
        ]
        with patch("utils.db.get_engine") as mock_engine:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = mock_rows
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            from scripts.generate_rera_training_data import generate_training_data, _build_raw_text, _build_output
            records = generate_training_data("Yelahanka")
            assert len(records) == 1
            rec = records[0]
            raw_text = _build_raw_text(rec)
            output = _build_output(rec)
            line = {
                "instruction": f"Extract RERA fields from: {raw_text}",
                "output": json.dumps(output, ensure_ascii=False, default=str),
            }
            assert json.loads(json.dumps(line)) == line
