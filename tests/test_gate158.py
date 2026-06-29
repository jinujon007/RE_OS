"""GATE-158: Intelligence Digest Quality — 5 gate assertions (A1-A5).

A1: validate_digest returns dict with all 5 keys + verdict in {PASS,WARN,FAIL}
A2: run_digest_quality_check importable from config.scheduler.maintenance_jobs
A3: run_digest_quality_check fires Discord DIGEST_QUALITY_FAIL on FAIL verdict
A4: GET /api/v1/ops/digest-quality returns 200 + markets + any_failures
A5: GET /api/v1/intel/digest/latest?market=X returns 200 + digest_text
"""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

os.environ.setdefault("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_API_KEY_READ", "test-read-key")
os.environ.setdefault("DASHBOARD_API_KEY_ADMIN", "test-admin-key")

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_mock_conn(execute_return_values):
    """Build a mock connection from a list of per-call return values.

    Each element in execute_return_values is either a tuple (for fetchone
    to return) or None. The mock returns a MagicMock whose fetchone returns
    that value.
    """
    mock_conn = MagicMock()
    side_effects = []
    for val in execute_return_values:
        m = MagicMock()
        if val is None:
            m.fetchone.return_value = None
        else:
            m.fetchone.return_value = val
        side_effects.append(m)
    mock_conn.execute.side_effect = side_effects
    return mock_conn


# ── A1: validate_digest returns dict with all 5 keys ———————————————


def test_gate158_a1_validate_digest_all_pass():
    """A1: validate_digest('Yelahanka') returns dict with all 5 keys."""
    from utils.digest_validator import validate_digest

    mock_conn = _make_mock_conn([
        (1,),
        (10,),
        (5, 0.85),
    ])

    with patch("utils.digest_validator.get_engine") as mock_eng:
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        result = validate_digest("Yelahanka")

    assert isinstance(result, dict)
    assert "market_coverage" in result
    assert "freshness_ok" in result
    assert "signal_count" in result
    assert "avg_confidence_pct" in result
    assert "verdict" in result
    assert result["verdict"] in {"PASS", "WARN", "FAIL"}
    assert result["market_coverage"] is True
    assert result["freshness_ok"] is True
    assert result["signal_count"] == 5
    assert result["avg_confidence_pct"] == 85.0
    assert result["verdict"] == "PASS"


def test_gate158_a1_validate_digest_fail():
    """A1 edge: no coverage → verdict=FAIL."""
    from utils.digest_validator import validate_digest

    mock_conn = _make_mock_conn([None, (0,), (0, 0.0)])

    with patch("utils.digest_validator.get_engine") as mock_eng:
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        result = validate_digest("UnknownMarket")

    assert result["market_coverage"] is False
    assert result["freshness_ok"] is False
    assert result["verdict"] == "FAIL"


def test_gate158_a1_validate_digest_warn():
    """A1 edge: coverage but no freshness → verdict=WARN."""
    from utils.digest_validator import validate_digest

    mock_conn = _make_mock_conn([(1,), (0,), (0, 0.0)])

    with patch("utils.digest_validator.get_engine") as mock_eng:
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        result = validate_digest("Yelahanka")

    assert result["market_coverage"] is True
    assert result["freshness_ok"] is False
    assert result["signal_count"] == 0
    assert result["verdict"] == "WARN"


def test_gate158_a1_db_failure_returns_defaults():
    """A1 edge: DB failure returns dict with defaults, no raise."""
    from utils.digest_validator import validate_digest

    with patch("utils.digest_validator.get_engine") as mock_eng:
        mock_eng.return_value.connect.side_effect = Exception("connection refused")
        result = validate_digest("Yelahanka")

    assert isinstance(result, dict)
    assert result["market_coverage"] is False
    assert result["freshness_ok"] is False
    assert result["signal_count"] == 0
    assert result["verdict"] == "FAIL"


def test_gate158_a1_empty_market_returns_defaults():
    """A1 edge: empty market string returns FAIL without DB call."""
    from utils.digest_validator import validate_digest

    with patch("utils.digest_validator.get_engine") as mock_eng:
        result = validate_digest("")

    assert result["verdict"] == "FAIL"
    assert result["market_coverage"] is False
    mock_eng.assert_not_called()


def test_gate158_a1_partial_db_failure():
    """A1 edge: second query fails, first query's result preserved."""
    from utils.digest_validator import validate_digest

    mock_conn = MagicMock()
    m1 = MagicMock()
    m1.fetchone.return_value = (1,)
    m2 = MagicMock()
    m2.fetchone.side_effect = Exception("rera_projects table not found")
    m3 = MagicMock()
    m3.fetchone.return_value = (3, 0.75)

    mock_conn.execute.side_effect = [m1, m2, m3]

    with patch("utils.digest_validator.get_engine") as mock_eng:
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        result = validate_digest("Yelahanka")

    assert result["market_coverage"] is True
    assert result["freshness_ok"] is False
    assert result["signal_count"] == 3
    assert result["verdict"] == "WARN"


def test_gate158_a1_confidence_column_fallback():
    """A1 edge: schema with 'confidence' column (not 'confidence_score') works."""
    from utils.digest_validator import validate_digest, _CONFIDENCE_COL

    assert "COALESCE" in _CONFIDENCE_COL
    assert "confidence_score" in _CONFIDENCE_COL
    assert "confidence" in _CONFIDENCE_COL

    mock_conn = _make_mock_conn([(1,), (10,), (5, 0.9)])

    with patch("utils.digest_validator.get_engine") as mock_eng:
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        result = validate_digest("Yelahanka")

    assert result["avg_confidence_pct"] == 90.0


# ── A2: run_digest_quality_check importable from maintenance_jobs ————


def test_gate158_a2_digest_quality_check_importable():
    """A2: run_digest_quality_check importable + in __all__."""
    from config.scheduler.maintenance_jobs import run_digest_quality_check, __all__

    assert callable(run_digest_quality_check)
    assert "run_digest_quality_check" in __all__


# ── A3: run_digest_quality_check fires Discord on FAIL —————————————


def test_gate158_a3_digest_quality_check_fires_discord():
    """A3: run_digest_quality_check fires DIGEST_QUALITY_FAIL on FAIL verdict."""
    from config.scheduler.maintenance_jobs import run_digest_quality_check

    mock_result = {
        "verdict": "FAIL",
        "market_coverage": False,
        "freshness_ok": False,
        "signal_count": 0,
        "avg_confidence_pct": 0.0,
    }

    with (
        patch("config.scheduler.maintenance_jobs.TARGET_MARKETS", ["Yelahanka"]),
        patch("utils.digest_validator.validate_digest", return_value=mock_result),
        patch("utils.discord_notifier.send_ops_alert") as mock_discord,
        patch("config.scheduler.maintenance_jobs._ops_already_alerted", return_value=False),
    ):
        run_digest_quality_check()

    mock_discord.assert_called_once()
    args, _ = mock_discord.call_args
    assert "DIGEST_QUALITY_FAIL" in args


def test_gate158_a3_digest_quality_no_fail_no_alert():
    """A3 edge: all PASS → no Discord alert."""
    from config.scheduler.maintenance_jobs import run_digest_quality_check

    mock_result = {
        "verdict": "PASS",
        "market_coverage": True,
        "freshness_ok": True,
        "signal_count": 5,
        "avg_confidence_pct": 85.0,
    }

    with (
        patch("config.scheduler.maintenance_jobs.TARGET_MARKETS", ["Yelahanka"]),
        patch("utils.digest_validator.validate_digest", return_value=mock_result),
        patch("utils.discord_notifier.send_ops_alert") as mock_discord,
    ):
        run_digest_quality_check()

    mock_discord.assert_not_called()


def test_gate158_a3_overlap_guard_skips():
    """A3 edge: concurrent invocation is skipped."""
    from config.scheduler.maintenance_jobs import run_digest_quality_check

    with (
        patch("config.scheduler.maintenance_jobs._DIGEST_QUALITY_RUNNING", True),
        patch("utils.digest_validator.validate_digest") as mock_validate,
    ):
        run_digest_quality_check()

    mock_validate.assert_not_called()


# ── A4: Digest quality endpoint ————————————————————————————————


def test_gate158_a4_digest_quality_endpoint():
    """A4: GET /api/v1/ops/digest-quality returns 200 + markets + any_failures."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    mock_conn = _make_mock_conn([(1,), (5,), (3, 0.75)])

    with (
        patch("dashboard.routers.ops._get_sa_engine") as mock_eng,
        patch("config.settings.TARGET_MARKETS", ["Yelahanka", "Devanahalli", "Hebbal"]),
    ):
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        resp = client.get(
            "/api/v1/ops/digest-quality",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "markets" in data
    assert "any_failures" in data
    assert "generated_at" in data
    assert len(data["markets"]) == 3
    assert data["markets"][0]["avg_confidence_pct"] == 75.0


def test_gate158_a4_digest_quality_db_failure():
    """A4 edge: DB failure returns markets list without 500."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    with (
        patch("dashboard.routers.ops._get_sa_engine") as mock_eng,
        patch("config.settings.TARGET_MARKETS", ["Yelahanka", "Devanahalli", "Hebbal"]),
    ):
        mock_eng.return_value.connect.side_effect = Exception("connection refused")

        resp = client.get(
            "/api/v1/ops/digest-quality",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["markets"]) == 3
    assert all(m["verdict"] == "FAIL" for m in data["markets"])


# ── A5: Latest digest endpoint —————————————————————————————————


def test_gate158_a5_digest_latest_endpoint():
    """A5: GET /api/v1/intel/digest/latest returns 200 + digest_text."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    mock_conn = _make_mock_conn([("Test digest summary", datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc))])

    with patch("dashboard.routers.data._get_sa_engine") as mock_eng:
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        resp = client.get(
            "/api/v1/intel/digest/latest?market=Yelahanka",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "digest_text" in data
    assert data["digest_text"] == "Test digest summary"
    assert "generated_at" in data
    assert "market" in data


def test_gate158_a5_digest_latest_no_data():
    """A5 edge: no digest found returns note: 'No digest found'."""
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    mock_conn = _make_mock_conn([None])

    with patch("dashboard.routers.data._get_sa_engine") as mock_eng:
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn

        resp = client.get(
            "/api/v1/intel/digest/latest?market=Unknown",
            headers={"X-API-Key": "test-key"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["digest_text"] is None
    assert data["note"] == "No digest found"


# ── Route registration checks ———————————————————————————————


def test_gate158_a5_digest_quality_route_registered():
    """Digest-quality route registered in ops router."""
    from dashboard.routers.ops import router
    route_paths = [r.path for r in router.routes]
    assert "/ops/digest-quality" in route_paths


def test_gate158_a5_digest_latest_route_registered():
    """Digest/latest route registered in data router."""
    from dashboard.routers.data import router
    route_paths = [r.path for r in router.routes]
    assert "/intel/digest/latest" in route_paths


# ── Constants / module-level correctness —————————————————————


def test_gate158_digest_validator_constants():
    """Module-level constants are positive integers."""
    from utils.digest_validator import (
        _FRESHNESS_MIN_PROJECTS,
        _FRESHNESS_WINDOW_DAYS,
        _COVERAGE_WINDOW_DAYS,
        _SIGNAL_WINDOW_DAYS,
    )
    assert isinstance(_FRESHNESS_MIN_PROJECTS, int) and _FRESHNESS_MIN_PROJECTS > 0
    assert isinstance(_FRESHNESS_WINDOW_DAYS, int) and _FRESHNESS_WINDOW_DAYS > 0
    assert isinstance(_COVERAGE_WINDOW_DAYS, int) and _COVERAGE_WINDOW_DAYS > 0
    assert isinstance(_SIGNAL_WINDOW_DAYS, int) and _SIGNAL_WINDOW_DAYS > 0
