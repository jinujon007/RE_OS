import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


class TestConfigAbsorption:
    def test_config_absorption_returns_dict(self):
        from intelligence.demand_intel import DemandIntel

        di = DemandIntel(caller="test")
        mock_engine = MagicMock()
        with patch(
            "intelligence.demand_intel.validate_market",
            return_value={
                "id": "uuid",
                "name": "Yelahanka",
                "slug": "yelahanka",
            },
        ):
            with patch(
                "intelligence.demand_intel.sanitize_market", return_value="Yelahanka"
            ):
                with patch("utils.db.get_engine", return_value=mock_engine):
                    with patch.object(
                        di,
                        "_query_config_absorption",
                        return_value={
                            "1BHK": 75.0,
                            "2BHK": 60.0,
                            "3BHK": 45.0,
                        },
                    ):
                        result = di.get_config_absorption("Yelahanka")
                        assert isinstance(result, dict)
                        assert "1BHK" in result
                        assert "2BHK" in result
                        assert "3BHK" in result

    def test_config_absorption_returns_empty_on_invalid_market(self):
        from intelligence.demand_intel import DemandIntel

        with patch("intelligence.demand_intel.sanitize_market", return_value=""):
            di = DemandIntel(caller="test")
            result = di.get_config_absorption("")
            assert result == {}

    def test_config_absorption_graph_returns_all_three_bhk(self):
        from intelligence.demand_intel import DemandIntel

        di = DemandIntel(caller="test")
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("1BHK", 75.0),
            ("2BHK", 60.0),
            ("3BHK", 45.0),
        ]
        mi = {"id": "uuid", "name": "Yelahanka", "slug": "yelahanka"}
        result = di._query_config_absorption(mock_conn, mi)
        assert result == {"1BHK": 75.0, "2BHK": 60.0, "3BHK": 45.0}
        # Verify single query, not N+1
        assert mock_conn.execute.call_count == 1

    def test_config_absorption_skips_null_results(self):
        from intelligence.demand_intel import DemandIntel

        di = DemandIntel(caller="test")
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("1BHK", 75.0),
            ("OTHER", None),
        ]
        mi = {"id": "uuid", "name": "Yelahanka", "slug": "yelahanka"}
        result = di._query_config_absorption(mock_conn, mi)
        assert "OTHER" not in result
        assert result == {"1BHK": 75.0}


class TestDaysOnMarket:
    def test_days_on_market_returns_none_when_no_snapshots(self):
        from intelligence.demand_intel import DemandSignals

        ds = DemandSignals(market="Yelahanka", collected_at="now")
        assert ds.days_on_market_p50 is None

    def test_ticket_size_median_computes_from_listings(self):
        from intelligence.demand_intel import DemandIntel

        di = DemandIntel(caller="test")
        ds = MagicMock()
        mock_conn = MagicMock()
        mock_row = MagicMock()
        mock_row.__getitem__.return_value = 85.5
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        mi = {"id": "uuid", "name": "Yelahanka", "slug": "yelahanka"}
        di._load_ticket_size_median(mock_conn, ds, mi)
        assert ds.ticket_size_median_cr is not None

    def test_ticket_size_median_null_when_no_listings(self):
        from intelligence.demand_intel import DemandIntel

        di = DemandIntel(caller="test")
        ds = MagicMock()
        ds.ticket_size_median_cr = None
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mi = {"id": "uuid", "name": "Yelahanka", "slug": "yelahanka"}
        di._load_ticket_size_median(mock_conn, ds, mi)
        assert ds.ticket_size_median_cr is None


class TestDemandScoreV2:
    def test_demand_score_v2_bounded_0_to_1(self):
        from intelligence.demand_intel import DemandSignals, DemandIntel

        di = DemandIntel(caller="test")
        ds = DemandSignals(market="Yelahanka", collected_at="now")
        ds.absorption_pct = 60.0
        ds.kaveri_velocity_ratio = 0.8
        ds.listing_count_30d = 50
        ds.config_absorption = {"1BHK": 70.0, "2BHK": 50.0, "3BHK": 30.0}
        di._compute_demand_score_v2(ds)
        assert 0.0 <= ds.demand_score_v2 <= 1.0

    def test_demand_score_v2_falls_back_when_no_components(self):
        from intelligence.demand_intel import DemandSignals, DemandIntel

        di = DemandIntel(caller="test")
        ds = DemandSignals(market="Yelahanka", collected_at="now")
        ds.demand_score = 0.5
        di._compute_demand_score_v2(ds)
        assert 0.0 <= ds.demand_score_v2 <= 1.0
        assert ds.demand_score_v2 > 0

    def test_demand_score_v2_falls_back_when_negative_v1(self):
        from intelligence.demand_intel import DemandSignals, DemandIntel

        di = DemandIntel(caller="test")
        ds = DemandSignals(market="Yelahanka", collected_at="now")
        ds.demand_score = -5.0
        di._compute_demand_score_v2(ds)
        assert ds.demand_score_v2 >= 0.0

    def test_demand_score_v2_ceils_at_1(self):
        from intelligence.demand_intel import DemandSignals, DemandIntel

        di = DemandIntel(caller="test")
        ds = DemandSignals(market="Yelahanka", collected_at="now")
        ds.absorption_pct = 200.0
        ds.kaveri_velocity_ratio = 10.0
        ds.listing_count_30d = 500
        ds.config_absorption = {"1BHK": 70.0, "2BHK": 50.0, "3BHK": 30.0}
        di._compute_demand_score_v2(ds)
        assert ds.demand_score_v2 <= 1.0

    def test_demand_signals_str_includes_new_fields(self):
        from intelligence.demand_intel import DemandSignals

        ds = DemandSignals(market="Yelahanka", collected_at="now")
        ds.demand_score_v2 = 0.75
        ds.days_on_market_p50 = 120.0
        ds.ticket_size_median_cr = 65.5
        ds.config_absorption = {"1BHK": 70.0, "2BHK": 60.0}
        result = str(ds)
        assert "v2=" in result
        assert "DoM" in result
        assert "ticket" in result
        assert "config_abs" in result


class TestAbsorptionTrend:
    def test_absorption_trend_returns_list(self):
        from intelligence.demand_intel import DemandIntel

        di = DemandIntel(caller="test")
        mock_engine = MagicMock()
        with patch(
            "intelligence.demand_intel.validate_market",
            return_value={
                "id": "uuid",
                "name": "Yelahanka",
                "slug": "yelahanka",
            },
        ):
            with patch(
                "intelligence.demand_intel.sanitize_market", return_value="Yelahanka"
            ):
                with patch("utils.db.get_engine", return_value=mock_engine):
                    with patch.object(
                        di,
                        "_query_absorption_trend",
                        return_value=[
                            {
                                "month": "2026-01",
                                "avg_absorption_pct": 45.0,
                                "project_count": 5,
                            },
                            {
                                "month": "2026-02",
                                "avg_absorption_pct": 50.0,
                                "project_count": 6,
                            },
                        ],
                    ):
                        result = di.get_absorption_trend("Yelahanka")
                        assert isinstance(result, list)
                        assert len(result) == 2

    def test_absorption_trend_sorted_by_month(self):
        from intelligence.demand_intel import DemandIntel

        di = DemandIntel(caller="test")
        mock_engine = MagicMock()
        trend_data = [
            {"month": "2026-01", "avg_absorption_pct": 45.0, "project_count": 5},
            {"month": "2026-02", "avg_absorption_pct": 50.0, "project_count": 6},
        ]
        with patch(
            "intelligence.demand_intel.validate_market",
            return_value={
                "id": "uuid",
                "name": "Yelahanka",
                "slug": "yelahanka",
            },
        ):
            with patch(
                "intelligence.demand_intel.sanitize_market", return_value="Yelahanka"
            ):
                with patch("utils.db.get_engine", return_value=mock_engine):
                    with patch.object(
                        di, "_query_absorption_trend", return_value=trend_data
                    ):
                        result = di.get_absorption_trend("Yelahanka")
                        months = [r["month"] for r in result]
                        assert months == sorted(months)

    def test_absorption_trend_single_month(self):
        from intelligence.demand_intel import DemandIntel

        di = DemandIntel(caller="test")
        mock_engine = MagicMock()
        with patch(
            "intelligence.demand_intel.validate_market",
            return_value={
                "id": "uuid",
                "name": "Yelahanka",
                "slug": "yelahanka",
            },
        ):
            with patch(
                "intelligence.demand_intel.sanitize_market", return_value="Yelahanka"
            ):
                with patch("utils.db.get_engine", return_value=mock_engine):
                    with patch.object(
                        di,
                        "_query_absorption_trend",
                        return_value=[
                            {
                                "month": "2026-01",
                                "avg_absorption_pct": 50.0,
                                "project_count": 3,
                            },
                        ],
                    ):
                        result = di.get_absorption_trend("Yelahanka")
                        assert len(result) == 1
                        assert result[0]["project_count"] == 3

    def test_days_on_market_by_config_returns_dict(self):
        from intelligence.demand_intel import DemandIntel

        di = DemandIntel(caller="test")
        mock_engine = MagicMock()
        with patch(
            "intelligence.demand_intel.validate_market",
            return_value={
                "id": "uuid",
                "name": "Yelahanka",
                "slug": "yelahanka",
            },
        ):
            with patch(
                "intelligence.demand_intel.sanitize_market", return_value="Yelahanka"
            ):
                with patch("utils.db.get_engine", return_value=mock_engine):
                    with patch.object(
                        di,
                        "_query_days_on_market_by_config",
                        return_value={
                            "1BHK": 180.0,
                            "2BHK": 240.0,
                            "3BHK": 300.0,
                        },
                    ):
                        result = di.days_on_market_by_config("Yelahanka")
                        assert isinstance(result, dict)
                        assert "1BHK" in result

    def test_days_on_market_handles_empty_snapshots(self):
        from intelligence.demand_intel import DemandIntel

        di = DemandIntel(caller="test")
        mock_engine = MagicMock()
        with patch(
            "intelligence.demand_intel.validate_market",
            return_value={
                "id": "uuid",
                "name": "Yelahanka",
                "slug": "yelahanka",
            },
        ):
            with patch(
                "intelligence.demand_intel.sanitize_market", return_value="Yelahanka"
            ):
                with patch("utils.db.get_engine", return_value=mock_engine):
                    with patch.object(
                        di, "_query_days_on_market_by_config", return_value={}
                    ):
                        result = di.days_on_market_by_config("Yelahanka")
                        assert result == {}

    def test_days_on_market_by_config_single_query(self):
        from intelligence.demand_intel import DemandIntel

        di = DemandIntel(caller="test")
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("1BHK", 180.0),
            ("2BHK", 240.0),
        ]
        mi = {"id": "uuid", "name": "Yelahanka", "slug": "yelahanka"}
        result = di._query_days_on_market_by_config(mock_conn, mi)
        assert result == {"1BHK": 180.0, "2BHK": 240.0}
        assert mock_conn.execute.call_count == 1
