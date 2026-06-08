"""Unit tests for CompetitiveIntelEngine (T-973). All mocked DB."""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit


class TestNewLaunches:
    def test_new_launches_returns_list(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = [
                ("Project A", "Builder X", "A", "Yelahanka", 100, 5000, 7000, "RERA/123"),
            ]
            result = engine.new_launches()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["project_name"] == "Project A"

    def test_new_launches_filters_by_market(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = [
                ("Project A", "Builder X", "A", "Devanahalli", 100, 5000, 7000, "RERA/123"),
            ]
            result = engine.new_launches(market="Devanahalli", days=365)
        assert len(result) == 1
        assert result[0]["market"] == "Devanahalli"


class TestPSFMovers:
    def test_psf_movers_applies_threshold(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = [
                ("Project A", "Builder X", "Yelahanka", 5000.0, 6000.0, 0.20, "A"),
            ]
            result = engine.psf_movers(threshold_pct=15.0)
        assert len(result) == 1
        assert result[0]["change_pct"] == 20.0
        assert result[0]["direction"] == "UP"

    def test_psf_movers_direction_flat_for_zero_change(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = [
                ("Project A", "Builder X", "Yelahanka", 5000.0, 5000.0, 0.0, "A"),
            ]
            result = engine.psf_movers(threshold_pct=1.0)
        assert len(result) == 1
        assert result[0]["direction"] == "FLAT"

    def test_psf_movers_skips_insufficient_snapshots(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = []
            result = engine.psf_movers()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_psf_movers_includes_developer_grade(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = [
                ("Project A", "Builder X", "Yelahanka", 5000.0, 6000.0, 0.20, "A+"),
            ]
            result = engine.psf_movers(threshold_pct=15.0)
        assert result[0]["developer_grade"] == "A+"


class TestAbsorptionLeaders:
    def test_absorption_leaders_sorted_desc(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = [
                ("Proj A", "Builder X", "A", "Yelahanka", 80.0, 200, 40, "2026-12-01"),
                ("Proj B", "Builder Y", "B", "Yelahanka", 60.0, 100, 40, "2027-03-01"),
            ]
            result = engine.absorption_leaders()
        assert len(result) == 2
        assert result[0]["absorption_pct"] >= result[1]["absorption_pct"]

    def test_absorption_leaders_respects_min_units(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchall.return_value = []
            result = engine.absorption_leaders(min_units=200)
        assert isinstance(result, list)
        assert len(result) == 0


class TestPulse:
    def test_pulse_returns_dict_with_all_keys(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch.object(engine, "new_launches", return_value=[{"project_name": "A"}]):
            with patch.object(engine, "psf_movers", return_value=[]):
                with patch.object(engine, "absorption_leaders", return_value=[]):
                    result = engine.pulse(market="Yelahanka", days=7, top_n=5)
        assert isinstance(result, dict)
        assert result["market_filter"] == "Yelahanka"
        assert result["days_window"] == 7
        assert len(result["new_launches"]) == 1
        assert "generated_at" in result

    def test_pulse_passes_params_to_sub_methods(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch.object(engine, "new_launches", return_value=[]) as mock_nl:
            with patch.object(engine, "psf_movers", return_value=[]) as mock_pm:
                with patch.object(engine, "absorption_leaders", return_value=[]) as mock_al:
                    engine.pulse(market="Hebbal", days=30, top_n=3)
        mock_nl.assert_called_with("Hebbal", 30)
        mock_pm.assert_called_with("Hebbal")
        mock_al.assert_called_with("Hebbal", 3)


class TestErrorHandling:
    def test_new_launches_handles_db_error_gracefully(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.side_effect = Exception("DB down")
            result = engine.new_launches()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_psf_movers_handles_db_error_gracefully(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.side_effect = Exception("DB down")
            result = engine.psf_movers()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_absorption_leaders_handles_db_error_gracefully(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine()
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.side_effect = Exception("DB down")
            result = engine.absorption_leaders()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_engine_has_caller_param(self):
        from intelligence.competitive_intel import CompetitiveIntelEngine
        engine = CompetitiveIntelEngine(caller="test-caller")
        assert engine._caller == "test-caller"
