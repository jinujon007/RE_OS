from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest
import requests

from tests.integration.conftest import REPO_ROOT, integration

sys.path.insert(0, str(REPO_ROOT))

pytestmark = [integration]

BASE_URL = os.environ.get("RE_OS_API_BASE", "http://localhost:8050")
_REQUEST_TIMEOUT_S = 15


def _api_get(
    path: str,
    expect_status: int = 200,
    api_key: str = "",
) -> Any:
    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.get(url, headers=headers, timeout=_REQUEST_TIMEOUT_S)
    except requests.ConnectionError as exc:
        pytest.fail(f"GET {path} — connection refused: {exc}")
    except requests.Timeout as exc:
        pytest.fail(f"GET {path} — timed out after {_REQUEST_TIMEOUT_S}s: {exc}")

    assert resp.status_code == expect_status, (
        f"GET {path} returned {resp.status_code} (expected {expect_status}): "
        f"{resp.text[:500]}"
    )
    if resp.status_code == 204 or not resp.text.strip():
        return {}
    try:
        return resp.json()
    except ValueError as exc:
        pytest.fail(f"GET {path} returned non-JSON ({exc}): {resp.text[:500]}")
        return None  # unreachable


@pytest.mark.test_id("G164-A2-health")
@pytest.mark.integration
def test_health(dashboard_api_key: str) -> None:
    """``GET /api/health`` returns ``{"status": "healthy"}``."""
    data = _api_get("/api/health", api_key=dashboard_api_key)
    assert data.get("status") == "healthy", (
        f"Expected status='healthy', got: {data}"
    )


@pytest.mark.test_id("G172-A2-system-health")
@pytest.mark.integration
def test_system_health_endpoint(dashboard_api_key: str) -> None:
    """``GET /api/v1/ops/system-health`` returns valid health score."""
    data = _api_get("/api/v1/ops/system-health", api_key=dashboard_api_key)
    assert "score" in data, "Response must contain 'score'"
    assert "grade" in data, "Response must contain 'grade'"
    assert "components" in data, "Response must contain 'components'"
    assert 0 <= data["score"] <= 100, f"Score must be 0-100, got {data['score']}"
    assert data["grade"] in ("A", "B", "C", "D"), f"Invalid grade: {data['grade']}"
    assert isinstance(data["deed_throughput_on_track"], bool), (
        "deed_throughput_on_track must be boolean"
    )
    assert "generated_at" in data, "Response must contain 'generated_at'"
    for key in ("freshness", "deed_throughput", "scheduler", "api_latency", "scraper"):
        comp = data["components"].get(key)
        assert comp is not None, f"Missing component: {key}"
        assert "score" in comp, f"Component {key} missing 'score'"
        assert "weight" in comp, f"Component {key} missing 'weight'"


@pytest.mark.test_id("G164-A2-kill-criteria")
@pytest.mark.integration
def test_kill_criteria(dashboard_api_key: str) -> None:
    """``GET /api/v1/ops/kill-criteria`` returns deed_throughput + decision_journal."""
    data = _api_get("/api/v1/ops/kill-criteria", api_key=dashboard_api_key)
    assert "deed_throughput" in data, f"Missing deed_throughput key: {list(data.keys())}"
    assert "decision_journal" in data, f"Missing decision_journal key: {list(data.keys())}"
    dt = data["deed_throughput"]
    assert "status" in dt, f"deed_throughput missing status: {dt}"
    assert "current_avg_4wk" in dt, f"deed_throughput missing current_avg_4wk: {dt}"
    assert "deadline" in dt


@pytest.mark.test_id("G164-A2-calibration")
@pytest.mark.integration
def test_calibration(dashboard_api_key: str) -> None:
    """``GET /api/v1/ops/calibration`` returns a non-empty dict."""
    data = _api_get("/api/v1/ops/calibration", api_key=dashboard_api_key)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert len(data) > 0, "Expected non-empty calibration response"


@pytest.mark.test_id("G164-A2-deal-score")
@pytest.mark.integration
def test_deal_score(dashboard_api_key: str) -> None:
    """``GET /api/v1/intel/deal-score`` returns verdict + numeric overall_score."""
    data = _api_get(
        "/api/v1/intel/deal-score?market=Yelahanka&land_cost_cr=5.0&area_acres=1.5",
        api_key=dashboard_api_key,
    )
    assert "verdict" in data, f"Missing verdict key: {list(data.keys())}"
    assert "overall_score" in data
    assert isinstance(data["overall_score"], (int, float)), (
        f"Expected numeric overall_score, got {type(data['overall_score'])}"
    )


@pytest.mark.test_id("G164-A2-parcel-graph-stats")
@pytest.mark.integration
def test_parcel_graph_stats(dashboard_api_key: str) -> None:
    """``GET /api/v1/intel/parcel-graph/stats`` returns structure with int total_edges."""
    data = _api_get("/api/v1/intel/parcel-graph/stats", api_key=dashboard_api_key)
    for key in ("total_edges", "total_villages", "materialization_coverage_pct"):
        assert key in data, f"Missing key '{key}': {list(data.keys())}"
    assert isinstance(data["total_edges"], int), (
        f"Expected int total_edges, got {type(data['total_edges'])}"
    )


@pytest.mark.test_id("G164-A2-strr-overlay")
@pytest.mark.integration
def test_strr_overlay(dashboard_api_key: str) -> None:
    """``GET /api/v1/intel/strr-overlay`` returns transit signal or station list."""
    data = _api_get(
        "/api/v1/intel/strr-overlay?market=Yelahanka",
        api_key=dashboard_api_key,
    )
    has_signal = "transit_demand_signal" in data
    has_stations = isinstance(data.get("stations"), list)
    assert has_signal or has_stations, (
        f"Expected transit_demand_signal or stations key, "
        f"got keys: {list(data.keys())}"
    )


@pytest.mark.test_id("G164-A2-weekly-digest")
@pytest.mark.integration
def test_weekly_digest(dashboard_api_key: str) -> None:
    """``GET /api/v1/intel/investor/weekly-digest`` returns 200 (or 404 if never run)."""
    _api_get("/api/v1/intel/investor/weekly-digest", expect_status=200, api_key=dashboard_api_key)


@pytest.mark.test_id("G164-A2-download-guide")
@pytest.mark.integration
def test_download_guide(dashboard_api_key: str) -> None:
    """``GET /api/v1/deeds/download-guide`` returns dict with market/villages info."""
    data = _api_get(
        "/api/v1/deeds/download-guide?market=Yelahanka",
        api_key=dashboard_api_key,
    )
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert "villages" in data or "market" in data, (
        f"Expected 'villages' or 'market' key: {list(data.keys())}"
    )


@pytest.mark.test_id("G164-A2-assembly-alerts")
@pytest.mark.integration
def test_assembly_alerts(dashboard_api_key: str) -> None:
    """``GET /api/v1/intel/assembly-alerts`` returns a dict."""
    data = _api_get(
        "/api/v1/intel/assembly-alerts?market=Yelahanka",
        api_key=dashboard_api_key,
    )
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"


@pytest.mark.test_id("G164-A2-forecast-accuracy")
@pytest.mark.integration
def test_forecast_accuracy(dashboard_api_key: str) -> None:
    """``GET /api/v1/intel/forecast-accuracy`` returns a dict."""
    data = _api_get("/api/v1/intel/forecast-accuracy", api_key=dashboard_api_key)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"


@pytest.mark.test_id("G164-A2-v2-readiness")
@pytest.mark.integration
def test_v2_readiness(dashboard_api_key: str) -> None:
    """``GET /api/v1/ops/v2-readiness`` returns dict with declared/status."""
    data = _api_get("/api/v1/ops/v2-readiness", api_key=dashboard_api_key)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert "declared" in data or "status" in data, (
        f"Missing 'declared' or 'status': {list(data.keys())}"
    )


@pytest.mark.test_id("G164-A2-board-sessions")
@pytest.mark.integration
def test_board_sessions(dashboard_api_key: str) -> None:
    """``GET /api/v1/ops/board/sessions`` returns a list (may be empty)."""
    data = _api_get("/api/v1/ops/board/sessions", api_key=dashboard_api_key)
    assert isinstance(data, list), f"Expected list, got {type(data)}"


@pytest.mark.test_id("G164-A2-agents")
@pytest.mark.integration
def test_agents(dashboard_api_key: str) -> None:
    """``GET /api/v1/ops/registry`` returns agent list."""
    data = _api_get("/api/v1/ops/registry", api_key=dashboard_api_key)
    assert isinstance(data, list), f"Expected list, got {type(data)}"


@pytest.mark.test_id("G164-A2-intel-cards")
@pytest.mark.integration
def test_intel_cards(dashboard_api_key: str) -> None:
    """``GET /api/v1/intel/cards`` returns >=1 intel card."""
    data = _api_get("/api/v1/intel/cards", api_key=dashboard_api_key)
    cards = data if isinstance(data, list) else data.get("cards", [])
    assert len(cards) >= 1, (
        f"Expected >=1 intelligence card, got {len(cards)}"
    )


@pytest.mark.test_id("G164-A2-intel-search")
@pytest.mark.integration
def test_intel_search(dashboard_api_key: str) -> None:
    """``GET /api/v1/intel/search`` returns dict with results/query."""
    data = _api_get("/api/v1/intel/search?q=Yelahanka+land", api_key=dashboard_api_key)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert "results" in data or "query" in data, (
        f"Missing 'results' or 'query': {list(data.keys())}"
    )


@pytest.mark.test_id("G164-A2-inbox-progress")
@pytest.mark.integration
def test_inbox_progress(dashboard_api_key: str) -> None:
    """``GET /api/v1/deeds/inbox-progress`` returns deed inbox status dict."""
    data = _api_get("/api/v1/deeds/inbox-progress", api_key=dashboard_api_key)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"


@pytest.mark.test_id("G164-A2-backtest-accuracy")
@pytest.mark.integration
def test_backtest_accuracy(dashboard_api_key: str) -> None:
    """``GET /api/v1/corridors/backtest-accuracy`` returns corridor backtest dict."""
    data = _api_get("/api/v1/corridors/backtest-accuracy", api_key=dashboard_api_key)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"


@pytest.mark.test_id("G164-A2-vel-competitive-report")
@pytest.mark.integration
def test_vel_competitive_report(dashboard_api_key: str) -> None:
    """``GET /api/v1/intel/vel/competitive-report`` returns 200."""
    _api_get(
        "/api/v1/intel/vel/competitive-report",
        expect_status=200,
        api_key=dashboard_api_key,
    )


@pytest.mark.test_id("G164-A2-digest-quality")
@pytest.mark.integration
def test_digest_quality(dashboard_api_key: str) -> None:
    """``GET /api/v1/ops/digest-quality`` returns markets list + any_failures."""
    data = _api_get("/api/v1/ops/digest-quality", api_key=dashboard_api_key)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert "markets" in data, f"Missing 'markets' key: {list(data.keys())}"
    assert isinstance(data["markets"], list), (
        f"Expected list for 'markets', got {type(data['markets'])}"
    )


@pytest.mark.test_id("G164-A2-handover-doc")
@pytest.mark.integration
def test_handover_doc(dashboard_api_key: str) -> None:
    """``GET /api/v1/ops/handover-doc`` returns a non-empty dict."""
    data = _api_get("/api/v1/ops/handover-doc", api_key=dashboard_api_key)
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert len(data) > 0, "Expected non-empty handover document"
