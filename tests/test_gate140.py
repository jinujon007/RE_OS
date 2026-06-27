"""GATE-140 declaration — Assembly Detection Engine.

5 assertions:
1. AssemblyDetector importable; detect_clusters callable
2. score_confidence returns float in [0, 1] for known inputs
3. Migration 0069_assembly_signals_v2 exists in alembic/versions/
4. run_assembly_detection importable from config.scheduler
5. /api/v1/intel/assembly-alerts route registered in dashboard routers
"""

import pathlib
import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


class TestGate140:
    def test_assembly_detector_importable(self):
        from utils.assembly_detector import AssemblyDetector
        detector = AssemblyDetector()
        assert hasattr(detector, "detect_clusters")
        assert callable(detector.detect_clusters)

    def test_score_confidence_returns_float_in_range(self):
        from utils.assembly_detector import AssemblyDetector
        detector = AssemblyDetector()
        score = detector.score_confidence(parcel_count=5, days_span=30, area_sqm=3000)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_score_confidence_formula_high_parcels_short_span(self):
        from utils.assembly_detector import AssemblyDetector
        detector = AssemblyDetector()
        high = detector.score_confidence(10, 10, 10000)
        low = detector.score_confidence(2, 365, 100)
        assert high > low
        assert high >= 0.5
        assert low < 0.3

    def test_migration_0069_exists(self):
        versions = pathlib.Path("alembic/versions")
        matching = list(versions.glob("0069_assembly_signals*"))
        assert len(matching) >= 1, "Migration 0069_assembly_signals_v2 not found in alembic/versions/"

    def test_run_assembly_detection_importable(self):
        # Try config.scheduler first (Docker); fall back to direct module
        try:
            from config.scheduler import run_assembly_detection
        except ImportError:
            from config.scheduler.deed_jobs import run_assembly_detection
        assert callable(run_assembly_detection)

    def test_assembly_alerts_route_registered(self):
        import pathlib
        data_py = pathlib.Path("dashboard/routers/data.py").read_text(encoding="utf-8")
        assert "/intel/assembly-alerts" in data_py, \
               "/intel/assembly-alerts route not found in dashboard/routers/data.py"

    def test_score_confidence_edge_cases(self):
        from utils.assembly_detector import AssemblyDetector
        detector = AssemblyDetector()
        assert detector.score_confidence(0, 0, 0) == 0.0
        assert detector.score_confidence(-1, -30, -100) == 0.0
        assert detector.score_confidence(100, 0, 100000) <= 1.0
        assert detector.score_confidence(3, 90, 2500) > 0
        assert detector.score_confidence(1, 200, 100) == 0.0

    def test_detect_clusters_empty_market(self):
        from utils.assembly_detector import AssemblyDetector
        from unittest.mock import patch
        detector = AssemblyDetector()
        with patch("utils.assembly_detector.get_engine") as mock_eng:
            mock_conn = mock_eng.return_value.connect.return_value.__enter__.return_value
            mock_conn.execute.return_value.fetchall.return_value = []
            result = detector.detect_clusters("TestMarket", window_months=1, min_parcels=3)
            assert isinstance(result, list)
            assert len(result) == 0

    def test_detect_clusters_invalid_params_clamped(self):
        from utils.assembly_detector import AssemblyDetector, get_engine
        from unittest.mock import patch
        detector = AssemblyDetector()
        with patch("utils.assembly_detector.get_engine") as mock_eng:
            mock_conn = mock_eng.return_value.connect.return_value.__enter__.return_value
            mock_conn.execute.return_value.fetchall.return_value = []
            result = detector.detect_clusters("Any", window_months=0, min_parcels=0)
            assert isinstance(result, list)
            assert len(result) == 0

    def test_v1_run_assembly_detection_importable(self):
        from utils.assembly_detector import run_assembly_detection as v1_run
        assert callable(v1_run)

    def test_market_parameter_sql_injection_safe(self):
        from utils.assembly_detector import AssemblyDetector
        detector = AssemblyDetector()
        with patch("utils.assembly_detector.get_engine") as mock_eng:
            mock_conn = mock_eng.return_value.connect.return_value.__enter__.return_value
            mock_conn.execute.return_value.fetchall.return_value = []
            try:
                detector.detect_clusters("'; DROP TABLE registered_transactions --", window_months=1)
            except Exception:
                pass
            mock_conn.execute.assert_called_once()
            call_args = mock_conn.execute.call_args[1]
            assert "; DROP TABLE" not in str(call_args)

    @pytest.mark.parametrize("parcels,span,area,expected_tier", [
        (10, 10, 10000, "high"),
        (6, 10, 5000, "medium"),
        (10, 30, 3000, "medium"),
        (3, 90, 2500, "low"),
        (2, 365, 100, "low"),
        (1, 200, 100, "low"),
    ])
    def test_score_tier_boundaries(self, parcels, span, area, expected_tier):
        from utils.assembly_detector import AssemblyDetector
        detector = AssemblyDetector()
        score = detector.score_confidence(parcels, span, area)
        from config.scheduler.deed_jobs import _get_tier
        tier = _get_tier(score)
        assert tier == expected_tier, \
            f"score={score:.3f} for p={parcels} s={span} a={area} → tier={tier}, expected={expected_tier}"

    def test_score_confidence_monotonic_properties(self):
        from utils.assembly_detector import AssemblyDetector
        detector = AssemblyDetector()
        base = detector.score_confidence(5, 30, 3000)
        more_parcels = detector.score_confidence(10, 30, 3000)
        shorter_span = detector.score_confidence(5, 15, 3000)
        larger_area = detector.score_confidence(5, 30, 6000)
        assert more_parcels >= base
        assert shorter_span >= base
        assert larger_area >= base
