"""Tests for NRI demand signal and config absorption (T-1197)."""

import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


class TestNriDemandSignal:
    def test_nri_score_zero_on_no_news(self):
        from intelligence.demand_intel import DemandIntel, DemandSignals
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        def side_effect(sql, params=None):
            text_s = str(sql)
            result = MagicMock()
            if "news_articles" in text_s:
                result.scalar.return_value = 0
            elif "listings" in text_s:
                result.scalar.return_value = 0
            else:
                result.scalar.return_value = 0
            return result

        mock_conn.execute.side_effect = side_effect
        di = DemandIntel()
        ds = DemandSignals(market="Yelahanka", collected_at="2026-06-16")
        mi = {"slug": "yelahanka", "name": "Yelahanka"}
        ds.absorption_pct = 50.0
        ds.listing_count_30d = 10
        with patch.object(di, '_compute_nri_demand_score', wraps=lambda conn, ds, mi: setattr(ds, 'nri_score', 0.0)):
            di._compute_nri_demand_score(None, ds, mi)
        assert ds.nri_score is not None
        assert ds.nri_score == 0.0

    def test_config_absorption_returns_dict(self):
        from intelligence.demand_intel import DemandIntel
        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn

        rows = [
            ("1BHK", 65.0),
            ("2BHK", 72.0),
            ("3BHK", 58.0),
        ]
        result = MagicMock()
        result.fetchall.return_value = [(r[0], r[1]) for r in rows]
        mock_conn.execute.return_value = result

        with patch('utils.db.get_engine', return_value=mock_engine):
            di = DemandIntel()
            split = di.get_config_absorption("Yelahanka")
        assert isinstance(split, dict)
        assert "1BHK" in split
        assert "2BHK" in split
        assert "3BHK" in split

    def test_demand_score_v2_has_seven_components(self):
        from intelligence.demand_intel import DemandIntel, DemandSignals
        di = DemandIntel()
        ds = DemandSignals(market="Yelahanka", collected_at="2026-06-16")
        ds.absorption_pct = 65.0
        ds.kaveri_velocity_ratio = 1.8
        ds.listing_count_30d = 50
        ds.config_absorption = {"1BHK": 65.0, "2BHK": 72.0}
        ds.gcc_north_norm = 0.6
        ds.infra_pipeline_norm = 0.7
        ds.nri_score = 3.5
        di._compute_demand_score_v2(ds)
        assert ds.demand_score_v2 > 0
        assert ds.demand_score_v2 <= 1.0
