import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestCheckEncumbrance:
    def _make_result(self, market="Yelahanka", survey_no=None, window_days=180):
        from utils.kaveri_encumbrance import check_encumbrance
        return check_encumbrance(market, survey_no=survey_no, window_days=window_days)

    def test_empty_market_returns_unavailable(self):
        with patch("utils.db.get_engine"):
            r = self._make_result("")
        assert r.data_source == "unavailable"
        assert "Market name is empty" in r.risk_flags

    def test_market_not_found_in_db(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Nonexistent")
        assert r.data_source == "unavailable"
        assert "Market not found in DB" in r.risk_flags

    def test_db_returns_guidance_values(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mm_row = (MagicMock(), "Yelahanka")
        mock_conn.execute.return_value.fetchone.return_value = mm_row
        mock_conn.execute.return_value.scalar.side_effect = [3500.0, 45, 4200.0]
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Yelahanka")
        assert r.avg_guidance_value_psf == 3500.0
        assert r.registration_count_180d == 45
        assert r.avg_transaction_psf == 4200.0
        assert r.data_source == "db"

    def test_guidance_gap_above_threshold_flagged(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mm_row = (MagicMock(), "Yelahanka")
        mock_conn.execute.return_value.fetchone.return_value = mm_row
        mock_conn.execute.return_value.scalar.side_effect = [2000.0, 30, 3000.0]
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Yelahanka")
        assert r.guidance_gap_pct == 50.0
        assert any("Guidance gap" in f for f in r.risk_flags)

    def test_survey_number_filtering(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mm_row = (MagicMock(), "Yelahanka")
        mock_conn.execute.return_value.fetchone.return_value = mm_row
        mock_conn.execute.return_value.scalar.side_effect = [3500.0, 5, 4100.0]
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Yelahanka", survey_no="123")
        assert r.survey_no == "123"
        assert r.avg_guidance_value_psf == 3500.0

    def test_no_registrations_triggers_risk_flag(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mm_row = (MagicMock(), "Yelahanka")
        mock_conn.execute.return_value.fetchone.return_value = mm_row
        mock_conn.execute.return_value.scalar.side_effect = [3500.0, 0, None]
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Yelahanka")
        assert r.registration_count_180d == 0
        assert any("No registrations" in f for f in r.risk_flags)

    def test_db_failure_graceful(self):
        with patch("utils.db.get_engine", side_effect=Exception("DB down")):
            r = self._make_result("Yelahanka")
        assert r.data_source == "unavailable"
        assert r.avg_guidance_value_psf is None

    def test_portal_cache_invalidation(self):
        from utils.kaveri_encumbrance import _invalidate_portal_cache
        _invalidate_portal_cache("yelahanka")

    def test_portal_fallback_noop_when_db_has_data(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mm_row = (MagicMock(), "Yelahanka")
        mock_conn.execute.return_value.fetchone.return_value = mm_row
        mock_conn.execute.return_value.scalar.side_effect = [3500.0, 10, 3800.0]
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Yelahanka")
        assert r.data_source == "db"
        assert r.avg_guidance_value_psf == 3500.0
