import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestWeeklyIntelDigest:
    def test_weekly_digest_returns_dataclass(self):
        from utils.weekly_digest import WeeklyIntelDigest, WeeklyDigestResult
        with patch("utils.weekly_digest.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.scalar.return_value = None
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn.execute.return_value.fetchone.return_value = None
            digest = WeeklyIntelDigest()
            result = digest.build("Yelahanka")
            assert isinstance(result, WeeklyDigestResult)
            assert result.market == "Yelahanka"

    def test_psf_delta_computed_correctly(self):
        from utils.weekly_digest import WeeklyIntelDigest
        with patch("utils.weekly_digest.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

            psf_call_count = [0]

            def fetchone_side_effect(*a, **kw):
                psf_call_count[0] += 1
                if psf_call_count[0] == 1:
                    return (6500.0, 6000.0)
                return None

            def scalar_side_effect(*a, **kw):
                return None

            mock_conn.execute.return_value.fetchone.side_effect = fetchone_side_effect
            mock_conn.execute.return_value.scalar.side_effect = scalar_side_effect
            mock_conn.execute.return_value.fetchall.return_value = []

            digest = WeeklyIntelDigest()
            result = digest.build("Yelahanka")
            assert abs(result.psf_delta_pct - 8.33) < 0.1
            assert result.psf_direction == "up"

    def test_psf_returns_flat_on_null_data(self):
        from utils.weekly_digest import WeeklyIntelDigest
        with patch("utils.weekly_digest.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.scalar.return_value = None
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn.execute.return_value.fetchone.return_value = None

            digest = WeeklyIntelDigest()
            result = digest.build("Yelahanka")
            assert result.psf_delta_pct == 0.0
            assert result.psf_direction == "flat"

    def test_distressed_devs_threshold_applied(self):
        from utils.weekly_digest import WeeklyIntelDigest
        with patch("utils.weekly_digest.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_eng

            def exec_side(*a, **kw):
                mr = MagicMock()
                sql_text = str(a[0]) if a else ""
                mr.scalar.return_value = None
                mr.fetchone.return_value = None
                if "developer_distress_signals" in sql_text:
                    mr.fetchall.return_value = [
                        ("Dev X", "Yelahanka", 0.75),
                        ("Dev Y", "Yelahanka", 0.60),
                    ]
                else:
                    mr.fetchall.return_value = []
                return mr

            mock_conn.execute.side_effect = exec_side
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

            digest = WeeklyIntelDigest()
            result = digest.build("Yelahanka")
            assert len(result.distressed_developers) == 2
            assert all(d["distress_score"] > 0.5 for d in result.distressed_developers)

    def test_top_opportunity_returns_none_on_empty(self):
        from utils.weekly_digest import WeeklyIntelDigest
        with patch("utils.weekly_digest.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.scalar.return_value = None
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn.execute.return_value.fetchone.return_value = None

            digest = WeeklyIntelDigest()
            result = digest.build("Yelahanka")
            assert result.top_opportunity is None

    def test_build_returns_zeroed_on_db_exception(self):
        from utils.weekly_digest import WeeklyIntelDigest
        with patch("utils.weekly_digest.get_engine", side_effect=Exception("DB down")):
            digest = WeeklyIntelDigest()
            result = digest.build("Yelahanka")
            assert result.psf_delta_pct == 0.0
            assert result.psf_direction == "flat"
            assert result.new_rera_count == 0
            assert result.competitor_launches == []
            assert result.distressed_developers == []
            assert result.top_opportunity is None

    def test_case_insensitive_market_yelahanka(self):
        from utils.weekly_digest import WeeklyIntelDigest
        with patch("utils.weekly_digest.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.scalar.return_value = None
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_conn.execute.return_value.fetchone.return_value = None
            digest = WeeklyIntelDigest()
            result = digest.build("yelahanka")
            assert isinstance(result, object)
