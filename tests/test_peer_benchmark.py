"""Unit tests for PeerBenchmarkEngine (T-990 — Sprint 57 GATE-65)."""
import pytest
from unittest.mock import patch, MagicMock
import importlib
pytestmark = pytest.mark.unit


def test_peer_benchmark_computes_positioning():
    from intelligence.peer_benchmark import PeerBenchmarkEngine

    mock_rows = [
        (7500.0, 9500.0, 8500.0, 65.0, 400, "Project A", "DevCo"),
        (7200.0, 9200.0, 8200.0, 55.0, 350, "Project B", "BuildCorp"),
        (7000.0, 9000.0, 8000.0, 70.0, 500, "Project C", "ConstrCo"),
    ]
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        result = PeerBenchmarkEngine.compute("TestMarket", 6500.0)
        assert result.grade_a_count == 3
        assert result.avg_psf_grade_a > 0
        assert result.positioning in ("PREMIUM", "COMPETITIVE", "VALUE")
        assert result.as_of is not None


def test_peer_benchmark_insufficient_data_when_few_grade_a():
    from intelligence.peer_benchmark import PeerBenchmarkEngine

    mock_rows = [
        (7500.0, 9500.0, 8500.0, 65.0, 400, "Project A", "DevCo"),
    ]
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        result = PeerBenchmarkEngine.compute("EmptyMarket", 7500.0)
        assert result.positioning == "INSUFFICIENT_DATA"
        assert result.grade_a_count == 1
        assert result.avg_psf_grade_a == 0.0


def test_psf_pct_formula():
    from intelligence.peer_benchmark import PeerBenchmarkEngine

    mock_rows = [
        (8000.0, 10000.0, 9000.0, 60.0, 300, "Proj A", "DevCo"),
        (7800.0, 9800.0, 8800.0, 50.0, 250, "Proj B", "BuildCo"),
        (7600.0, 9600.0, 8600.0, 70.0, 450, "Proj C", "ConCo"),
        (7400.0, 9400.0, 8400.0, 55.0, 350, "Proj D", "DevLlC"),
        (7200.0, 9200.0, 8200.0, 65.0, 500, "Proj E", "ReCo"),
    ]
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        result = PeerBenchmarkEngine.compute("Yelahanka", 0.0)
        assert result.avg_psf_grade_a > 0
        assert result.grade_a_count == 5
        assert result.lls_vs_grade_a_pct == 0.0
        assert result.positioning == "INSUFFICIENT_DATA"

        result2 = PeerBenchmarkEngine.compute("Yelahanka", 10000.0)
        assert result2.lls_vs_grade_a_pct != 0.0
        assert result2.positioning in ("PREMIUM", "COMPETITIVE", "VALUE")


def test_peer_benchmark_handles_db_error():
    from intelligence.peer_benchmark import PeerBenchmarkEngine

    with patch("utils.db.get_engine", side_effect=Exception("DB down")):
        result = PeerBenchmarkEngine.compute("Yelahanka", 7500.0)
        assert result.positioning == "INSUFFICIENT_DATA"
        assert result.error is not None


def test_intel_registry_attaches_peer_benchmark():
    with patch("intelligence.peer_benchmark.PeerBenchmarkEngine.compute") as mock_compute:
        from intelligence.registry import IntelRegistry, IntelPackage
        pkg = IntelPackage(survey_no="45/2", market="Yelahanka", collected_at="now")
        assert hasattr(pkg, "peer_benchmark")
        assert pkg.peer_benchmark is None

        reg = IntelRegistry()
        assert hasattr(reg, "_get_peer_benchmark")


def test_peer_benchmark_positioning_premium():
    from intelligence.peer_benchmark import PeerBenchmarkEngine

    mock_rows = [
        (7000.0, 9000.0, 8000.0, 60.0, 300, "Proj A", "DevCo"),
        (6800.0, 8800.0, 7800.0, 50.0, 250, "Proj B", "BuildCo"),
        (6600.0, 8600.0, 7600.0, 70.0, 450, "Proj C", "ConCo"),
    ]
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows

        result = PeerBenchmarkEngine.compute("Test", 9000.0)
        assert result.positioning == "PREMIUM"


def test_peer_benchmark_positioning_value():
    from intelligence.peer_benchmark import PeerBenchmarkEngine

    mock_rows = [
        (7000.0, 9000.0, 8000.0, 60.0, 300, "Proj A", "DevCo"),
        (6800.0, 8800.0, 7800.0, 50.0, 250, "Proj B", "BuildCo"),
        (6600.0, 8600.0, 7600.0, 70.0, 450, "Proj C", "ConCo"),
    ]
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = mock_rows
        result = PeerBenchmarkEngine.compute("Test", 5000.0)
        assert result.positioning == "VALUE"
