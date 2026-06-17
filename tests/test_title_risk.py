"""Tests for TitleRiskChecklist (T-1195)."""

import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


def _build_mock_engine():
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    def side_effect(sql, params=None):
        text_s = str(sql)
        if "to_regclass" in text_s:
            r = MagicMock()
            r.scalar.return_value = "parcel_ownership_chain"
            return r
        return MagicMock()

    mock_conn.execute.side_effect = side_effect
    return mock_engine, mock_conn


class TestTitleRiskChecklist:
    def test_title_risk_high_on_govt_acquisition(self):
        from utils.title_risk import TitleRiskChecklist
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        def side_effect(sql, params=None):
            text_s = str(sql)
            if "parcel_ownership_chain" in text_s:
                result = MagicMock()
                result.fetchone.return_value = (True, False)
                return result
            elif "registered_transactions" in text_s:
                result = MagicMock()
                result.fetchone.return_value = (0, None)
                return result
            elif "dc_conversions" in text_s:
                result = MagicMock()
                result.fetchone.return_value = None
                return result
            elif "rera_projects" in text_s:
                result = MagicMock()
                result.fetchone.return_value = None
                return result
            return MagicMock()

        mock_conn.execute.side_effect = side_effect
        result = TitleRiskChecklist.from_parcel("45/2", "Yelahanka", engine=mock_engine)
        assert result.khata_status == "ALERT"
        assert result.overall_risk == "HIGH"

    def test_title_risk_low_on_clear_chain(self):
        from utils.title_risk import TitleRiskChecklist
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        def side_effect(sql, params=None):
            text_s = str(sql)
            if "parcel_ownership_chain" in text_s:
                result = MagicMock()
                result.fetchone.return_value = (False, False)
                return result
            elif "registered_transactions" in text_s:
                result = MagicMock()
                result.fetchone.return_value = (0, None)
                return result
            elif "dc_conversions" in text_s:
                result = MagicMock()
                result.fetchone.return_value = None
                return result
            elif "rera_projects" in text_s:
                result = MagicMock()
                result.fetchone.return_value = None
                return result
            return MagicMock()

        mock_conn.execute.side_effect = side_effect
        result = TitleRiskChecklist.from_parcel("45/2", "Yelahanka", engine=mock_engine)
        assert result.overall_risk == "LOW"
        assert result.khata_status == "CLEAR"

    def test_title_risk_unknown_when_no_chain(self):
        from utils.title_risk import TitleRiskChecklist
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        def side_effect(sql, params=None):
            text_s = str(sql)
            if "parcel_ownership_chain" in text_s:
                result = MagicMock()
                result.fetchone.return_value = None
                return result
            elif "registered_transactions" in text_s:
                result = MagicMock()
                result.fetchone.return_value = (0, None)
                return result
            elif "dc_conversions" in text_s:
                result = MagicMock()
                result.fetchone.return_value = None
                return result
            elif "rera_projects" in text_s:
                result = MagicMock()
                result.fetchone.return_value = None
                return result
            return MagicMock()

        mock_conn.execute.side_effect = side_effect
        result = TitleRiskChecklist.from_parcel("45/2", "Yelahanka", engine=mock_engine)
        assert result.khata_status == "UNKNOWN"
        assert result.overall_risk in ("LOW", "MEDIUM")

    def test_title_risk_empty_survey_returns_unknown(self):
        from utils.title_risk import TitleRiskChecklist
        result = TitleRiskChecklist.from_parcel("", "Yelahanka")
        assert result.overall_risk == "UNKNOWN"

    def test_title_risk_str_representation(self):
        from utils.title_risk import TitleRiskChecklist
        mock_engine, _ = _build_mock_engine()
        result = TitleRiskChecklist.from_parcel("45/2", "Yelahanka", engine=mock_engine)
        s = str(result)
        assert "TitleRisk" in s
        assert "Yelahanka" in s

    def test_title_risk_exact_survey_match(self):
        from utils.title_risk import TitleRiskChecklist
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        executed_sql: list[str] = []
        def side_effect(sql, params=None):
            text_s = str(sql)
            executed_sql.append(str(text_s))
            result = MagicMock()
            result.fetchone.return_value = None
            if "to_regclass" in text_s:
                r = MagicMock()
                r.scalar.return_value = "parcel_ownership_chain"
                return r
            if "registered_transactions" in text_s:
                result.fetchone.return_value = (0, None, None)
            return result

        mock_conn.execute.side_effect = side_effect
        TitleRiskChecklist.from_parcel("45/2", "Yelahanka", engine=mock_engine)
        survey_sqls = [s for s in executed_sql if "survey_no" in s or "survey_no_raw" in s]
        for sql in survey_sqls:
            assert "%" not in sql.split("survey_no")[-1].split("=")[0], f"Wildcard pattern found: {sql}"
            assert "ILIKE" not in sql, f"ILIKE found instead of exact match: {sql}"
