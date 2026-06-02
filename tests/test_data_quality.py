import pytest
from unittest.mock import patch, MagicMock, ANY
import pandas as pd

pytestmark = pytest.mark.unit


class TestExpectationDef:
    def test_minimal_config(self):
        from utils.data_quality import ExpectationDef
        e = ExpectationDef(column="name", table="developers", expectation_type="expect_column_values_to_not_be_null")
        assert e.severity == "ERROR"
        assert e.kwargs == {}

    def test_custom_severity(self):
        from utils.data_quality import ExpectationDef
        e = ExpectationDef(column="name", table="developers", expectation_type="expect_column_values_to_not_be_null", severity="WARN")
        assert e.severity == "WARN"

    def test_to_dict_includes_fields(self):
        from utils.data_quality import ExpectationDef
        e = ExpectationDef(column="price_avg_psf", table="rera_projects", expectation_type="expect_column_values_to_be_between", kwargs={"min_value": 2000})
        d = e.to_dict()
        assert d["column"] == "price_avg_psf"
        assert d["table"] == "rera_projects"
        assert d["severity"] == "ERROR"


class TestDataQualityError:
    def test_accepts_dict_result(self):
        from utils.data_quality import DataQualityError
        err = DataQualityError("Yelahanka", {"failed_expectations": [{"expectation": "test"}], "warnings": []})
        assert err.market == "Yelahanka"
        assert "Stage 3 skipped" in str(err)

    def test_to_dict_roundtrip(self):
        from utils.data_quality import DataQualityError
        result = {"failed_expectations": [{"expectation": "x", "severity": "ERROR"}], "warnings": []}
        err = DataQualityError("Devanahalli", result)
        d = err.to_dict()
        assert d["failed_expectations"] == result["failed_expectations"]

    def test_accepts_list_legacy_format(self):
        from utils.data_quality import DataQualityError
        failed = [{"expectation": "test"}]
        err = DataQualityError("Hebbal", failed)
        assert err.market == "Hebbal"


class TestFormatDataQualityAlert:
    def test_empty_result_returns_empty_string(self):
        from utils.data_quality import format_data_quality_alert
        assert format_data_quality_alert("test", {"failed_expectations": [], "warnings": []}) == ""

    def test_errors_included_in_output(self):
        from utils.data_quality import format_data_quality_alert
        result = {
            "failed_expectations": [{"expectation": "PSF range", "table": "rera_projects", "column": "price_avg_psf", "bad_values": [30000]}],
            "warnings": [],
        }
        out = format_data_quality_alert("Yelahanka", result)
        assert "Yelahanka" in out
        assert "PSF range" in out
        assert "BLOCKED" in out

    def test_warnings_separate_from_errors(self):
        from utils.data_quality import format_data_quality_alert
        result = {
            "failed_expectations": [],
            "warnings": [{"expectation": "null name", "table": "developers", "column": "name", "bad_values": []}],
        }
        out = format_data_quality_alert("Hebbal", result)
        assert "Warning" in out
        assert "BLOCKED" not in out


class TestRunDataQualityCheckpoint:
    def test_returns_expected_structure(self):
        from utils.data_quality import run_data_quality_checkpoint
        result = run_data_quality_checkpoint("check_structure")
        assert isinstance(result, dict)
        assert "success" in result
        assert "failed_expectations" in result
        assert "warnings" in result

    def test_returns_success_on_empty_table(self):
        mock_ge = MagicMock()
        mock_ge.from_pandas = MagicMock()
        with patch("utils.data_quality._lazy_import_ge", return_value=mock_ge), \
             patch("utils.data_quality.get_engine") as mock_engine, \
             patch("pandas.read_sql", return_value=pd.DataFrame()):
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            from utils.data_quality import run_data_quality_checkpoint
            result = run_data_quality_checkpoint("Devanahalli")
            assert result["success"] is True

    def test_psf_out_of_range_triggers_error(self):
        mock_ge = MagicMock()
        mock_gdf = MagicMock()
        mock_gdf.expect_column_values_to_be_between.return_value = {"success": False}
        mock_gdf.expect_column_values_to_match_regex.return_value = {"success": True}
        mock_ge.from_pandas.return_value = mock_gdf
        df = pd.DataFrame({"price_avg_psf": [10148, 5500, 30000], "rera_number": ["PRM/2024/001", "PRM/2024/002", "PRM/2024/003"]})

        with patch("utils.data_quality._lazy_import_ge", return_value=mock_ge), \
             patch("utils.data_quality.get_engine") as mock_engine, \
             patch("pandas.read_sql", return_value=df):
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            from utils.data_quality import run_data_quality_checkpoint
            result = run_data_quality_checkpoint("Devanahalli")
            assert result["success"] is False
            assert len(result["failed_expectations"]) > 0

    def test_regex_mismatch_triggers_warning_only(self):
        mock_ge = MagicMock()
        mock_gdf = MagicMock()
        mock_gdf.expect_column_values_to_be_between.return_value = {"success": True}
        mock_gdf.expect_column_values_to_match_regex.return_value = {"success": False}
        mock_ge.from_pandas.return_value = mock_gdf

        df = pd.DataFrame({
            "price_avg_psf": [5000],
            "rera_number": ["INVALID_FORMAT"],
        })

        with patch("utils.data_quality._lazy_import_ge", return_value=mock_ge), \
             patch("utils.data_quality.get_engine") as mock_engine, \
             patch("pandas.read_sql", return_value=df):
            mock_conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
            from utils.data_quality import run_data_quality_checkpoint
            result = run_data_quality_checkpoint("Hebbal")
            assert result["success"] is True

    def test_db_error_returns_success_with_error_field(self):
        mock_ge = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("Connection lost")
        with patch("utils.data_quality._lazy_import_ge", return_value=mock_ge), \
             patch("utils.data_quality.get_engine") as mock_engine:
            mock_engine.return_value.connect.return_value.__enter__.side_effect = Exception("DB connection failed")
            from utils.data_quality import run_data_quality_checkpoint
            result = run_data_quality_checkpoint("ErrorMarket")
            assert result["success"] is True
            assert "error" in result


class TestGetActiveExpectations:
    def test_returns_list_of_dicts(self):
        from utils.data_quality import get_active_expectations
        expectations = get_active_expectations()
        assert len(expectations) >= 1
        assert all("column" in e for e in expectations)
        assert all("table" in e for e in expectations)
        assert all("severity" in e for e in expectations)
