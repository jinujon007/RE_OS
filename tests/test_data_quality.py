"""
RE_OS — Data Quality Tests (Sprint 45 — T-814)
Unit tests for GE checkpoint integration, alert formatting, error handling,
expectation definitions, and market-filtered SQL construction.
"""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit

import pandas as pd
from utils.data_quality import (
    ExpectationDef,
    FailedExpectation,
    DataQualityError,
    format_data_quality_alert,
    get_active_expectations,
    run_data_quality_checkpoint,
    _derive_projected_columns,
    _TABLE_MARKET_JOIN,
)


class TestExpectationDef:
    def test_to_dict_returns_correct_keys(self):
        exp = ExpectationDef(
            column="price_avg_psf",
            table="rera_projects",
            expectation_type="expect_column_values_to_be_between",
            kwargs={"min_value": 2000, "max_value": 25000},
            severity="ERROR",
            description="price_avg_psf BETWEEN 2000 AND 25000",
        )
        d = exp.to_dict()
        assert d["column"] == "price_avg_psf"
        assert d["table"] == "rera_projects"
        assert d["expectation_type"] == "expect_column_values_to_be_between"
        assert d["severity"] == "ERROR"
        assert d["description"] == "price_avg_psf BETWEEN 2000 AND 25000"


class TestFailedExpectation:
    def test_bad_values_truncated_to_five_in_to_dict(self):
        exp = ExpectationDef(column="c", table="t", expectation_type="e")
        fe = FailedExpectation(
            expectation=exp,
            message="10 bad values",
            bad_values=list(range(10)),
            unexpected_count=10,
        )
        assert len(fe.bad_values) == 10
        d = fe.to_dict()
        assert len(d["bad_values"]) == 5
        assert d["unexpected_count"] == 10

    def test_to_dict_with_empty_bad_values(self):
        exp = ExpectationDef(column="c", table="t", expectation_type="e")
        fe = FailedExpectation(expectation=exp, message="ok")
        d = fe.to_dict()
        assert d["bad_values"] == []
        assert d["unexpected_count"] == 0

    def test_to_dict_includes_message(self):
        exp = ExpectationDef(column="c", table="t", expectation_type="e")
        fe = FailedExpectation(expectation=exp, message="column out of range")
        d = fe.to_dict()
        assert d["message"] == "column out of range"


class TestDataQualityError:
    def test_init_with_dict_result(self):
        result = {
            "failed_expectations": [
                {
                    "column": "price_avg_psf",
                    "table": "rera_projects",
                    "severity": "ERROR",
                },
            ],
            "warnings": [],
        }
        err = DataQualityError("Yelahanka", result)
        assert err.market == "Yelahanka"
        assert "ERROR" in str(err)
        assert "Yelahanka" in str(err)

    def test_init_with_list_result_fallback(self):
        result = [{"column": "name", "table": "developers", "severity": "ERROR"}]
        err = DataQualityError("Devanahalli", result)
        assert err.market == "Devanahalli"
        assert "Devanahalli" in str(err)

    def test_init_with_empty_list(self):
        err = DataQualityError("Hebbal", [])
        assert err.market == "Hebbal"
        assert "0 expectation(s)" in str(err)

    def test_to_dict_with_dict_result(self):
        result = {
            "failed_expectations": [{"column": "price_avg_psf", "severity": "ERROR"}],
            "warnings": [{"column": "name", "severity": "WARN"}],
        }
        err = DataQualityError("Hebbal", result)
        d = err.to_dict()
        assert "failed_expectations" in d
        assert "warnings" in d
        assert len(d["failed_expectations"]) == 1


class TestFormatDataQualityAlert:
    def test_returns_empty_string_when_no_issues(self):
        result = {"failed_expectations": [], "warnings": []}
        assert format_data_quality_alert("Yelahanka", result) == ""

    def test_formats_error_messages(self):
        result = {
            "failed_expectations": [
                {
                    "column": "price_avg_psf",
                    "table": "rera_projects",
                    "expectation": "between",
                    "bad_values": [999, 30000],
                    "severity": "ERROR",
                },
            ],
            "warnings": [],
        }
        msg = format_data_quality_alert("Yelahanka", result)
        assert "Data Quality Check — Yelahanka" in msg
        assert "BLOCKED" in msg or "Error" in msg
        assert "price_avg_psf" in msg

    def test_formats_warning_messages(self):
        result = {
            "failed_expectations": [],
            "warnings": [
                {
                    "column": "name",
                    "table": "developers",
                    "expectation": "not_null",
                    "severity": "WARN",
                },
            ],
        }
        msg = format_data_quality_alert("Hebbal", result)
        assert "Warning" in msg
        assert "developers" in msg

    def test_includes_both_errors_and_warnings(self):
        result = {
            "failed_expectations": [
                {
                    "column": "price_avg_psf",
                    "table": "rera_projects",
                    "expectation": "between",
                    "bad_values": [999],
                    "severity": "ERROR",
                },
            ],
            "warnings": [
                {
                    "column": "name",
                    "table": "developers",
                    "expectation": "not_null",
                    "severity": "WARN",
                },
            ],
        }
        msg = format_data_quality_alert("Yelahanka", result)
        assert "Data Quality Check — Yelahanka" in msg
        assert "price_avg_psf" in msg

    def test_bad_values_appear_in_formatted_output(self):
        result = {
            "failed_expectations": [
                {
                    "column": "price_avg_psf",
                    "table": "rera_projects",
                    "expectation": "between",
                    "bad_values": [999, 9999, 30000],
                    "severity": "ERROR",
                },
            ],
            "warnings": [],
        }
        msg = format_data_quality_alert("Yelahanka", result)
        assert "30000" in msg
        assert "999" in msg

    def test_truncated_errors_capped_at_five(self):
        result = {
            "failed_expectations": [
                {
                    "column": f"col{i}",
                    "table": "t",
                    "expectation": "e",
                    "severity": "ERROR",
                }
                for i in range(10)
            ],
            "warnings": [],
        }
        msg = format_data_quality_alert("Yelahanka", result)
        assert "10 Error(s)" in msg
        assert msg.count("t.col") <= 5


class TestGetActiveExpectations:
    def test_returns_configured_expectations(self):
        exps = get_active_expectations()
        assert isinstance(exps, list)
        assert len(exps) >= 4
        for e in exps:
            assert "column" in e
            assert "table" in e
            assert "expectation_type" in e
            assert "severity" in e

    def test_includes_igr_expectation(self):
        exps = get_active_expectations()
        igr_exps = [e for e in exps if "igr_transactions" in e.get("table", "")]
        assert len(igr_exps) >= 1


class TestDeriveProjectedColumns:
    def test_covers_all_expectation_tables(self):
        cols = _derive_projected_columns()
        exps = get_active_expectations()
        exp_tables = set(e["table"] for e in exps)
        for t in exp_tables:
            assert t in cols, f"Missing projected columns for table {t}"

    def test_igr_transactions_included(self):
        cols = _derive_projected_columns()
        assert "igr_transactions" in cols
        assert "transaction_psf" in cols["igr_transactions"]

    def test_developers_included(self):
        cols = _derive_projected_columns()
        assert "developers" in cols
        assert "name" in cols["developers"]


class TestTableMarketJoin:
    def test_igr_transactions_in_market_join(self):
        assert "igr_transactions" in _TABLE_MARKET_JOIN

    def test_rera_projects_in_market_join(self):
        assert "rera_projects" in _TABLE_MARKET_JOIN

    def test_developers_not_in_market_join(self):
        assert "developers" not in _TABLE_MARKET_JOIN


class TestRunDataQualityCheckpoint:
    def test_runs_with_mocked_engine_empty_results(self):
        """Checkpoint runs with mocked engine and empty results — no errors."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_result.keys.return_value = []
        mock_conn.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("utils.data_quality.get_engine", return_value=mock_engine):
            result = run_data_quality_checkpoint("Yelahanka")
        assert result["success"] is True
        assert result.get("status") == "completed"

    def test_handles_db_connection_error_gracefully(self):
        from sqlalchemy.exc import OperationalError

        mock_conn = MagicMock()
        mock_conn.__enter__.side_effect = OperationalError("DB unreachable", None, None)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("utils.data_quality.get_engine", return_value=mock_engine):
            result = run_data_quality_checkpoint("Yelahanka")
        assert result["success"] is True
        assert result.get("status") == "db_error"
        assert "error" in result

    def test_skips_empty_table_no_expectations_fired(self):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_result.keys.return_value = []
        mock_conn.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("utils.data_quality.get_engine", return_value=mock_engine):
            result = run_data_quality_checkpoint("Yelahanka")

        assert result["success"] is True
        assert result.get("status") == "completed"
        assert result["failed_expectations"] == []

    def test_collects_failed_expectations_on_violation(self):
        import pandas as pd
        from sqlalchemy.engine import Result

        exp = ExpectationDef(
            column="price_avg_psf",
            table="rera_projects",
            expectation_type="expect_column_values_to_be_between",
            kwargs={"min_value": 0, "max_value": 100},
            severity="ERROR",
        )
        df = pd.DataFrame({"price_avg_psf": [50, 200, 75, 300, 25]})

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = list(df.itertuples(index=False, name=None))
        mock_result.keys.return_value = list(df.columns)
        mock_conn.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with (
            patch("utils.data_quality.get_engine", return_value=mock_engine),
            patch("utils.data_quality._dq_expectations", [exp]),
        ):
            result = run_data_quality_checkpoint("Yelahanka")

        assert result["success"] is False
        assert len(result["failed_expectations"]) >= 1

    def test_reuses_market_filter_in_sql(self):
        import pandas as pd

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(5000,)]
        mock_result.keys.return_value = ["price_avg_psf"]
        mock_conn.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("utils.data_quality.get_engine", return_value=mock_engine):
            run_data_quality_checkpoint("Yelahanka")

        sql_calls = [str(c[0][0]) for c in mock_conn.execute.call_args_list]
        market_filtered = any("mm.name ILIKE" in s for s in sql_calls)
        assert market_filtered, "Expected at least one market-filtered SQL query"

    def test_checkpoint_no_cursor_error(self):
        """Verifies the SA2.x compatible code path: conn.execute → pd.DataFrame."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(5000,)]
        mock_result.keys.return_value = ["price_avg_psf"]
        mock_conn.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("utils.data_quality.get_engine", return_value=mock_engine):
            result = run_data_quality_checkpoint("Yelahanka")

        assert result["success"] is True
        assert result.get("status") == "completed"
        assert "error" not in result or result.get("error") is None
        # Verify SA2.x compatible path was used (conn.execute, not pd.read_sql)
        assert mock_conn.execute.call_count >= 1, "conn.execute was never called"
        assert "pd.read_sql" not in str(type(result)), "pd.read_sql should not be used"

    def test_handles_empty_market_gracefully(self):
        result = run_data_quality_checkpoint("")
        assert result["success"] is True
        assert result.get("note") == "empty market"

    def test_handles_none_market_gracefully(self):
        result = run_data_quality_checkpoint(None)
        assert result["success"] is True
        assert result.get("note") == "empty market"

    def test_no_expectations_returns_skipped(self):
        """When _dq_expectations is empty, checkpoint returns status='skipped'."""
        mock_engine = MagicMock()
        with (
            patch("utils.data_quality.get_engine", return_value=mock_engine),
            patch("utils.data_quality._dq_expectations", []),
        ):
            result = run_data_quality_checkpoint("Yelahanka")
        assert result.get("status") == "skipped"
        assert result.get("note") == "no expectations configured"

    def test_all_nan_column_skipped(self):
        """When all values in a column are NaN, the check is skipped gracefully."""
        import pandas as pd

        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(float("nan"),)]
        mock_result.keys.return_value = ["price_avg_psf"]
        mock_conn.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("utils.data_quality.get_engine", return_value=mock_engine):
            result = run_data_quality_checkpoint("Yelahanka")
        assert result["success"] is True
        assert result.get("status") == "completed"

    def test_empty_series_column_skipped(self):
        """When a column has zero rows, the check is skipped gracefully."""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_result.keys.return_value = ["price_avg_psf"]
        mock_conn.execute.return_value = mock_result
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        with patch("utils.data_quality.get_engine", return_value=mock_engine):
            result = run_data_quality_checkpoint("Yelahanka")
        assert result["success"] is True
        assert result.get("status") == "completed"


# ── T-1072: GV freshness check ──────────────────────────────────────────────


class TestGVFreshness:
    def test_gv_freshness_check_alerts_when_stale(self):
        """check_gv_freshness alerts when gazette data is >18 months stale."""
        mock_conn = MagicMock()
        results = [MagicMock(), MagicMock()]
        results[0].fetchone.return_value = (2022,)  # gazette: stale
        results[1].fetchone.return_value = (None,)  # portal: none
        mock_conn.execute.side_effect = results
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        from utils.data_quality import DataQualityMonitor

        with (
            patch("utils.data_quality.get_engine", return_value=mock_engine),
            patch("utils.discord_notifier.send_scraper_alert") as mock_alert,
        ):
            result = DataQualityMonitor.check_gv_freshness("Yelahanka")

        assert result["alert_needed"] is True
        assert result["months_stale"] > 18
        assert result["gazette_year"] == 2022
        mock_alert.assert_called_once()

    def test_gv_freshness_check_silent_when_fresh(self):
        """check_gv_freshness is silent when gazette data is recent."""
        mock_conn = MagicMock()
        from datetime import date

        cy = date.today().year
        results = [MagicMock(), MagicMock()]
        results[0].fetchone.return_value = (cy,)  # gazette: fresh
        results[1].fetchone.return_value = (None,)  # portal: none
        mock_conn.execute.side_effect = results
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        from utils.data_quality import DataQualityMonitor

        with (
            patch("utils.data_quality.get_engine", return_value=mock_engine),
            patch("utils.discord_notifier.send_scraper_alert") as mock_alert,
        ):
            result = DataQualityMonitor.check_gv_freshness("Yelahanka")

        assert result["alert_needed"] is False
        assert result["gazette_year"] == cy
        mock_alert.assert_not_called()

    def test_gv_freshness_silent_when_portal_live_no_gazette(self):
        """No alert when gazette_pdf absent but portal_scraped data is fresh."""
        mock_conn = MagicMock()
        from datetime import date

        cy = date.today().year
        results = [MagicMock(), MagicMock()]
        results[0].fetchone.return_value = (None,)  # gazette: none
        results[1].fetchone.return_value = (cy,)  # portal: fresh
        mock_conn.execute.side_effect = results
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        from utils.data_quality import DataQualityMonitor

        with (
            patch("utils.data_quality.get_engine", return_value=mock_engine),
            patch("utils.discord_notifier.send_scraper_alert") as mock_alert,
        ):
            result = DataQualityMonitor.check_gv_freshness("Yelahanka")

        assert result["alert_needed"] is False
        assert result["gazette_year"] is None
        assert result["portal_year"] == cy
        mock_alert.assert_not_called()
