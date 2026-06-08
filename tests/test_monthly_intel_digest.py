import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestMonthlyIntelDigest:
    def test_monthly_digest_returns_dataclass(self):
        from utils.monthly_digest import MonthlyIntelDigest, MonthlyDigestResult
        with patch("utils.monthly_digest.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.scalar.return_value = None
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn.execute.return_value.fetchone.return_value = None

            with patch.object(MonthlyIntelDigest, "_generate_synthesis", return_value=""):
                digest = MonthlyIntelDigest()
                result = digest.build("Yelahanka")
                assert isinstance(result, MonthlyDigestResult)
                assert result.market == "Yelahanka"

    def test_psf_mom_computed_correctly(self):
        from utils.monthly_digest import MonthlyIntelDigest
        with patch("utils.monthly_digest.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

            call_idx = [0]

            def fetchone_side_effect(*a, **kw):
                call_idx[0] += 1
                if call_idx[0] == 1:
                    return (6800.0, 6500.0)
                return None

            def scalar_side_effect(*a, **kw):
                return None

            mock_conn.execute.return_value.fetchone.side_effect = fetchone_side_effect
            mock_conn.execute.return_value.scalar.side_effect = scalar_side_effect
            mock_conn.execute.return_value.fetchall.return_value = []

            with patch.object(MonthlyIntelDigest, "_generate_synthesis", return_value=""):
                digest = MonthlyIntelDigest()
                result = digest.build("Yelahanka")
                assert abs(result.psf_mom_pct - 4.62) < 0.1

    def test_absorption_trend_accelerating(self):
        from utils.monthly_digest import MonthlyIntelDigest
        with patch("utils.monthly_digest.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

            results = [(None, None), (65.0, 50.0)]

            def fetchone_side_effect(*a, **kw):
                return results.pop(0) if results else None

            def scalar_side_effect(*a, **kw):
                return None

            mock_conn.execute.return_value.fetchone.side_effect = fetchone_side_effect
            mock_conn.execute.return_value.scalar.side_effect = scalar_side_effect
            mock_conn.execute.return_value.fetchall.return_value = []

            with patch.object(MonthlyIntelDigest, "_generate_synthesis", return_value=""):
                digest = MonthlyIntelDigest()
                result = digest.build("Yelahanka")
                assert result.absorption_trend == "accelerating"

    def test_absorption_trend_decelerating(self):
        from utils.monthly_digest import MonthlyIntelDigest
        with patch("utils.monthly_digest.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

            results = [(None, None), (40.0, 55.0)]

            def fetchone_side_effect(*a, **kw):
                return results.pop(0) if results else None

            def scalar_side_effect(*a, **kw):
                return None

            mock_conn.execute.return_value.fetchone.side_effect = fetchone_side_effect
            mock_conn.execute.return_value.scalar.side_effect = scalar_side_effect
            mock_conn.execute.return_value.fetchall.return_value = []

            with patch.object(MonthlyIntelDigest, "_generate_synthesis", return_value=""):
                digest = MonthlyIntelDigest()
                result = digest.build("Yelahanka")
                assert result.absorption_trend == "decelerating"

    def test_pipeline_supply_aggregated(self):
        from utils.monthly_digest import MonthlyIntelDigest
        with patch("utils.monthly_digest.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.scalar.return_value = 450
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn.execute.return_value.fetchone.return_value = None

            with patch.object(MonthlyIntelDigest, "_generate_synthesis", return_value=""):
                digest = MonthlyIntelDigest()
                result = digest.build("Yelahanka")
                assert result.pipeline_supply_added == 450

    def test_llm_synthesis_returns_empty_string_on_failure(self):
        from utils.monthly_digest import MonthlyIntelDigest
        with patch("utils.monthly_digest.get_engine") as mock_eng, \
             patch.object(MonthlyIntelDigest, "_generate_synthesis", return_value=""):
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.scalar.return_value = None
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn.execute.return_value.fetchone.return_value = None

            digest = MonthlyIntelDigest()
            result = digest.build("Yelahanka")
            assert result.llm_synthesis == ""

    def test_build_returns_zeroed_on_db_exception(self):
        from utils.monthly_digest import MonthlyIntelDigest
        with patch("utils.monthly_digest.get_engine", side_effect=Exception("DB down")):
            digest = MonthlyIntelDigest()
            with patch.object(MonthlyIntelDigest, "_generate_synthesis", return_value=""):
                result = digest.build("Yelahanka")
                assert result.psf_mom_pct == 0.0
                assert result.absorption_trend == "flat"
                assert result.pipeline_supply_added == 0
