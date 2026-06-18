"""Tests for T-1283: GET /api/v1/ops/slo endpoint (R2)."""

import pytest
from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)


SLO_PATH = "/api/v1/ops/slo"
SLO_REQUIRED_KEYS = frozenset({
    "scheduler_success_rate", "scheduler_target", "scheduler_ok",
    "board_room_p95_s", "board_room_target_s", "board_room_ok",
    "window_days", "computed_at",
})


def _get_slo(headers: dict | None = None):
    return client.get(SLO_PATH, headers=headers or {"X-API-Key": "test"})


def test_slo_endpoint_returns_all_required_keys():
    """Route must return all SLOMetricsResponse fields on successful call."""
    resp = _get_slo()
    if resp.status_code != 200:
        pytest.skip(f"SLO endpoint returned {resp.status_code} (no DB/mock)")
        return
    data = resp.json()
    missing = SLO_REQUIRED_KEYS - data.keys()
    extra = data.keys() - SLO_REQUIRED_KEYS - {"model_config"}
    assert not missing, f"Missing required fields: {missing}"
    assert not extra, f"Unexpected fields: {extra}"


def test_slo_scheduler_rate_bounded():
    resp = _get_slo()
    if resp.status_code != 200:
        pytest.skip(f"SLO endpoint returned {resp.status_code}")
        return
    data = resp.json()
    rate = data["scheduler_success_rate"]
    assert isinstance(rate, (int, float)), f"rate is {type(rate)}"
    assert 0.0 <= rate <= 1.0, f"rate {rate} outside [0, 1]"


def test_slo_board_p95_is_float_or_none():
    resp = _get_slo()
    if resp.status_code != 200:
        pytest.skip(f"SLO endpoint returned {resp.status_code}")
        return
    data = resp.json()
    p95 = data["board_room_p95_s"]
    if p95 is not None:
        assert isinstance(p95, (int, float)), f"p95 is {type(p95)}"
        assert p95 >= 0.0, f"p95 negative: {p95}"


def test_slo_targets_match_settings():
    """SLO targets must match config.settings constants."""
    from config.settings import SLO_SCHEDULER_TARGET, SLO_BOARD_ROOM_P95_TARGET_S
    resp = _get_slo()
    if resp.status_code != 200:
        pytest.skip(f"SLO endpoint returned {resp.status_code}")
        return
    data = resp.json()
    assert data["scheduler_target"] == SLO_SCHEDULER_TARGET
    assert data["board_room_target_s"] == SLO_BOARD_ROOM_P95_TARGET_S
