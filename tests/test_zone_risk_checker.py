import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit

_SAMPLE_ROW = (3.0, 24.0, 60.0, 4.5, 1.5, 1.5)


class TestCheckZoneRisk:
    def _make_result(self, market="Devanahalli", zone="R2"):
        from utils.zone_risk_checker import check_zone_risk
        return check_zone_risk(market, zone)

    def test_empty_market_returns_unknown(self):
        with patch("utils.db.get_engine"):
            r = self._make_result("", "R2")
        assert r.risk_level == "UNKNOWN"
        assert r.far is None
        assert "Market name is empty" in r.overlay_risks

    def test_zone_found_with_data(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = _SAMPLE_ROW
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Devanahalli", "R2")
        assert r.far == 3.0
        assert r.max_height_m == 24.0
        assert r.ground_coverage_pct == 60.0
        assert r.setback_front_m == 4.5
        assert r.setback_side_m == 1.5
        assert r.setback_rear_m == 1.5
        assert r.risk_level == "LOW"

    def test_zone_not_found_returns_unknown(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = None
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Nonexistent", "R2")
        assert r.risk_level == "UNKNOWN"
        assert r.far is None

    def test_overlay_risk_triggers_medium_level(self):
        # Patch _load_zones_gdf to return (None, None) — forces SQL fallback path.
        # Without this, GeoPandas path runs first and consumes the side_effect entries
        # before _fallback_sql_query can use them.
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = [
            MagicMock(fetchone=lambda: _SAMPLE_ROW),
            MagicMock(),
            MagicMock(fetchall=lambda: [("airport_funnel", "Airport funnel zone")]),
            MagicMock(),
        ]
        with patch("utils.db.get_engine") as mock_eng, \
             patch("utils.zone_risk_checker._load_zones_gdf", return_value=(None, None)):
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Devanahalli", "R2")
        assert r.risk_level == "MEDIUM"
        assert len(r.overlay_risks) == 1

    def test_multiple_overlay_risks_high_level(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.execute.side_effect = [
            MagicMock(fetchone=lambda: _SAMPLE_ROW),
            MagicMock(),
            MagicMock(fetchall=lambda: [
                ("airport_funnel", "Zone A"),
                ("green_belt", "Green belt"),
            ]),
            MagicMock(),
        ]
        with patch("utils.db.get_engine") as mock_eng, \
             patch("utils.zone_risk_checker._load_zones_gdf", return_value=(None, None)):
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Devanahalli", "R2")
        assert r.risk_level == "HIGH"
        assert len(r.overlay_risks) == 2

    def test_case_insensitive_market(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = _SAMPLE_ROW
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("devanahalli", "r2")
        assert r.far == 3.0
        assert r.zone == "R2"

    def test_db_failure_graceful(self):
        with patch("utils.db.get_engine", side_effect=Exception("DB down")):
            r = self._make_result("Devanahalli", "R2")
        assert r.risk_level == "UNKNOWN"
        assert len(r.overlay_risks) == 1
        assert "DB query failed" in r.overlay_risks[0]

    def test_overlay_spatial_fallback_global_scan(self):
        # First SQL execute (zone query) succeeds; all subsequent fail (simulating
        # ST_Intersects unavailable). _load_zones_gdf patched to (None, None) so
        # the side_effect counter starts at 0 for the SQL fallback path.
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        call_count = [0]
        def side_effect(*a, **kw):
            call_count[0] += 1
            if call_count[0] <= 1:
                return MagicMock(fetchone=lambda: _SAMPLE_ROW)
            raise Exception("ST_Intersects failed")
        mock_conn.execute.side_effect = side_effect
        with patch("utils.db.get_engine") as mock_eng, \
             patch("utils.zone_risk_checker._load_zones_gdf", return_value=(None, None)):
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Devanahalli", "R2")
        assert r.far == 3.0
        assert r.risk_level == "LOW"

    def test_rear_setback_in_result(self):
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = (3.0, 24.0, 60.0, 4.5, 1.5, 1.5)
        with patch("utils.db.get_engine") as mock_eng:
            mock_eng.return_value.connect.return_value = mock_conn
            r = self._make_result("Devanahalli", "R2")
        assert r.setback_rear_m == 1.5
