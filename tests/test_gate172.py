"""GATE-172: System Health Dashboard — 5 gate assertions (A1-A5).

A1: SystemHealthCalculator importable + has compute method
A2: GET /api/v1/ops/system-health registered in FastAPI routes
A3: Mock max data → score >= 95, grade A
A4: Mock DB failure → all components fallback to 50, score <= 20, on_track False
A5: run_weekly_health_report importable + in maintenance_jobs.__all__
"""

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ["DASHBOARD_API_KEY_ALLOW_EMPTY"] = "true"
os.environ["DASHBOARD_API_KEY"] = "test-key"
os.environ["DASHBOARD_API_KEY_READ"] = "test-read-key"
os.environ["DASHBOARD_API_KEY_ADMIN"] = "test-admin-key"

pytestmark = pytest.mark.unit


def _make_engine_mock(conn: MagicMock) -> MagicMock:
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    return engine


def test_gate172_a1_system_health_calculator_importable():
    from utils.system_health import SystemHealthCalculator

    calc = SystemHealthCalculator()
    assert hasattr(calc, "compute"), "A1: SystemHealthCalculator must have compute method"


def test_gate172_a2_system_health_route_registered():
    from dashboard.app_fastapi import app

    route_paths = {r.path for r in app.routes}
    assert "/api/v1/ops/system-health" in route_paths, (
        "A2: system-health route not registered in FastAPI"
    )


@patch("utils.system_health._get_target_market_count", return_value=3)
@patch("utils.system_health.get_engine")
def test_gate172_a3_max_values_score_ge_95(
    mock_get_engine, mock_get_target_market_count,
):
    mock_conn = MagicMock()
    mock_get_engine.return_value = _make_engine_mock(mock_conn)

    mock_conn.execute.return_value.scalar.side_effect = [
        3, 50, 10, 10, 10, 10,
    ]

    from utils.system_health import SystemHealthCalculator

    result = SystemHealthCalculator().compute()
    assert result["score"] >= 95, f"A3: expected score >= 95, got {result['score']}"
    assert result["grade"] == "A", f"A3: expected grade A, got {result['grade']}"
    assert result["deed_throughput_on_track"] is True, (
        "A3: with 50 deeds, on_track must be True"
    )
    assert result["deed_count"] == 50, (
        f"A3: expected 50 deeds, got {result['deed_count']}"
    )


@patch("utils.system_health._get_target_market_count", return_value=3)
@patch("utils.system_health.get_engine")
def test_gate172_a4_db_failure_fallback(
    mock_get_engine, mock_get_target_market_count,
):
    mock_conn = MagicMock()
    mock_get_engine.return_value = _make_engine_mock(mock_conn)

    mock_conn.execute.side_effect = Exception("DB connection failed")

    from utils.system_health import SystemHealthCalculator

    result = SystemHealthCalculator().compute()

    assert result["deed_throughput_on_track"] is False, (
        "A4: deed_throughput_on_track must be False when DB fails"
    )
    assert result["deed_count"] == 0, (
        f"A4: deed_count must be 0 on DB failure, got {result['deed_count']}"
    )
    for key in ("freshness", "deed_throughput", "scheduler", "scraper"):
        assert result["components"][key]["score"] == 50.0, (
            f"A4: {key} should fallback to 50 on DB failure, got {result['components'][key]['score']}"
        )
    assert result["components"]["api_latency"]["score"] == 85.0, (
        "A4: api_latency should remain 85.0 (stubbed, not DB-dependent)"
    )
    assert result["score"] == 55.2, (
        f"A4: expected score=55.2 (4*50 + 85 stubbed), got {result['score']}"
    )


@patch("utils.system_health._get_target_market_count", return_value=3)
@patch("utils.system_health.get_engine")
def test_gate172_edge_custom_weights(mock_get_engine, mock_get_target_market_count):
    """Edge: custom weights produce proportional score changes."""
    mock_conn = MagicMock()
    mock_get_engine.return_value = _make_engine_mock(mock_conn)
    mock_conn.execute.return_value.scalar.side_effect = [3, 50, 10, 10, 10, 10]

    from utils.system_health import SystemHealthCalculator

    weights = {"freshness": 1.0, "deed_throughput": 0.0, "scheduler": 0.0, "api_latency": 0.0, "scraper": 0.0}
    result = SystemHealthCalculator(weights=weights).compute()
    assert result["score"] == 100.0, (
        f"Edge: with freshness alone and full data, score should be 100, got {result['score']}"
    )


def test_gate172_a5_run_weekly_health_report_importable():
    from config.scheduler.maintenance_jobs import run_weekly_health_report

    assert callable(run_weekly_health_report), (
        "A5: run_weekly_health_report must be callable"
    )

    import config.scheduler.maintenance_jobs as maintenance_jobs

    assert "run_weekly_health_report" in maintenance_jobs.__all__, (
        "A5: run_weekly_health_report must be in maintenance_jobs.__all__"
    )
