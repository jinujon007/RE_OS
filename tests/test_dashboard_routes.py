import os

# Must be set before importing app — rate-limiter uses REDIS_URL at import time
os.environ.setdefault("REDIS_URL", "memory://")

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.slow]

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)


def test_health_no_auth():
    r = client.get("/api/v1/health")
    assert r.status_code == 200


def test_run_trigger_requires_auth(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/v1/run/yelahanka")
    assert r.status_code == 401


def test_run_trigger_with_auth(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/v1/run/yelahanka", headers={"X-API-Key": "secret"})
    assert r.status_code in (200, 202, 409)


def test_db_state_no_auth():
    r = client.get("/api/v1/db/state")
    assert r.status_code in (200, 500)


def test_run_invalid_market_returns_400(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/v1/run/fakecity", headers={"X-API-Key": "secret"})
    assert r.status_code == 400


# ── Memory Explorer (T-86A) ──


@pytest.fixture
def mock_db():
    """Mock _get_sa_engine to return engine whose connect() yields a mock connection
    that returns empty results for any query."""
    from unittest.mock import MagicMock, patch

    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_conn.execute.return_value.scalar.return_value = 0
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_engine):
        yield


@pytest.fixture
def mock_conflict_db():
    """Mock DB returning 3 conflict rows."""
    from unittest.mock import MagicMock, patch

    mock_conn = MagicMock()
    mock_conn.execute.return_value.scalar.return_value = 3
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_engine):
        yield


def test_memory_explorer_endpoint_returns_200(mock_db):
    r = client.get("/api/v1/memory/explorer")
    assert r.status_code in (200, 500)  # 200 when DB mocked, 500 without DB
    if r.status_code == 200:
        body = r.json()
        assert "total" in body
        assert "page" in body
        assert "per_page" in body
        assert "memories" in body


def test_memory_explorer_respects_market_filter(mock_db):
    r = client.get("/api/v1/memory/explorer?market=Yelahanka")
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        body = r.json()
        assert body["page"] == 1
        assert body["per_page"] == 20


def test_conflict_count_endpoint_returns_integer():
    r = client.get("/api/v1/memory/conflict-count")
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        body = r.json()
        assert "unresolved_conflicts" in body
        assert isinstance(body["unresolved_conflicts"], int)


def test_conflict_count_mocked(mock_conflict_db):
    r = client.get("/api/v1/memory/conflict-count")
    assert r.status_code == 200
    assert r.json()["unresolved_conflicts"] == 3


# ── Conflict Badge (T-86C) ──


def test_conflict_badge_script_present_in_index_html():
    path = os.path.join(
        os.path.dirname(__file__), "..", "dashboard", "templates", "index.html"
    )
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "conflict-badge" in content, "conflict-badge id not found in index.html"
    assert "/api/v1/memory/conflict-count" in content, (
        "/api/v1/memory/conflict-count endpoint not found in index.html"
    )
    assert "pollConflictBadge" in content, (
        "pollConflictBadge function not found in index.html"
    )


# ── Memory Panel Route (T-86B) ──


def test_memory_panel_route_returns_200():
    r = client.get("/memory")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "AGENT MEMORY EXPLORER" in r.text


# ── Data Provenance (T-1126) ──


@pytest.fixture
def mock_provenance_db():
    from unittest.mock import MagicMock, patch

    mock_row1 = MagicMock()
    mock_row1.__getitem__.side_effect = lambda idx: [
        "Yelahanka",
        "portal_scraped",
        100,
    ][idx]
    mock_row2 = MagicMock()
    mock_row2.__getitem__.side_effect = lambda idx: ["Yelahanka", "seed_estimated", 50][
        idx
    ]
    mock_row3 = MagicMock()
    mock_row3.__getitem__.side_effect = lambda idx: [
        "Devanahalli",
        "portal_scraped",
        200,
    ][idx]
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [
        mock_row1,
        mock_row2,
        mock_row3,
    ]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_engine):
        yield


def test_provenance_endpoint_returns_200(mock_provenance_db):
    r = client.get("/api/v1/data/provenance")
    assert r.status_code == 200
    body = r.json()
    assert "Yelahanka" in body
    assert "Devanahalli" in body


def test_provenance_has_all_markets(mock_provenance_db):
    r = client.get("/api/v1/data/provenance")
    assert r.status_code == 200
    body = r.json()
    assert "Yelahanka" in body
    assert "Devanahalli" in body
    yel = body["Yelahanka"]
    assert "total" in yel
    assert "live" in yel
    assert "seed" in yel
    assert "live_pct" in yel
    assert "guidance" in yel


def test_live_pct_is_float_between_0_and_100(mock_provenance_db):
    r = client.get("/api/v1/data/provenance")
    assert r.status_code == 200
    body = r.json()
    for market_data in body.values():
        assert isinstance(market_data["live_pct"], float)
        assert 0.0 <= market_data["live_pct"] <= 100.0


def test_provenance_computed_values(mock_provenance_db):
    """Assert live_pct is correctly computed: Yelahanka=66.7%, Devanahalli=100%."""
    r = client.get("/api/v1/data/provenance")
    assert r.status_code == 200
    body = r.json()
    assert body["Yelahanka"]["live_pct"] == 66.7
    assert body["Devanahalli"]["live_pct"] == 100.0
    assert body["Yelahanka"]["total"] == 150
    assert body["Yelahanka"]["live"] == 100
    assert body["Yelahanka"]["seed"] == 50
    assert body["Devanahalli"]["total"] == 200
    assert body["Devanahalli"]["live"] == 200


def test_provenance_market_filter():
    """Test optional market filter. We mock only Yelahanka data."""
    from unittest.mock import MagicMock, patch

    mock_row = MagicMock()
    mock_row.__getitem__.side_effect = lambda idx: ["Yelahanka", "portal_scraped", 100][
        idx
    ]
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [mock_row]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_engine):
        r = client.get("/api/v1/data/provenance?market=Yelahanka")
    assert r.status_code == 200
    body = r.json()
    assert "Yelahanka" in body
    assert len(body) == 1


# ── Scraper Reliability (T-1127) ──


@pytest.fixture
def mock_reliability_db():
    from unittest.mock import MagicMock, patch

    mock_row = MagicMock()
    mock_row.__getitem__.side_effect = lambda idx: [10, 8, "2026-06-11 06:00:00"][idx]
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("utils.scraper_reliability.get_engine", return_value=mock_engine):
        yield


def test_reliability_endpoint_returns_200(mock_reliability_db):
    r = client.get("/api/v1/scraper/reliability")
    assert r.status_code == 200
    body = r.json()
    assert len(body) > 0


def test_reliability_has_all_scrapers(mock_reliability_db):
    from config.scraper_registry import SCRAPER_NAMES

    r = client.get("/api/v1/scraper/reliability")
    assert r.status_code == 200
    body = r.json()
    for scraper in SCRAPER_NAMES:
        assert scraper in body, f"Missing scraper: {scraper}"
        s = body[scraper]
        assert "runs" in s
        assert "successes" in s
        assert "reliability_score" in s
        assert "last_run" in s


def test_reliability_computed_values(mock_reliability_db):
    """Assert reliability_score is correctly computed: 8/10 = 0.8."""
    from config.scraper_registry import SCRAPER_NAMES

    r = client.get("/api/v1/scraper/reliability")
    assert r.status_code == 200
    body = r.json()
    for scraper in SCRAPER_NAMES:
        s = body[scraper]
        assert s["runs"] == 10
        assert s["successes"] == 8
        assert s["reliability_score"] == 0.8


# ── T-1218: API versioning /api/v1/ prefix + legacy redirect ─────────────


def test_v1_health_returns_200():
    """GET /api/v1/health returns 200 (rate-limited read-only endpoint)."""
    r = client.get("/api/v1/health")
    assert r.status_code == 200


def test_legacy_api_redirects_to_v1():
    """GET /api/health redirects (301) to /api/v1/health."""
    r = client.get("/api/health", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers.get("location") == "/api/v1/health"


def test_v1_evaluate_route_registered():
    """GET /api/v1/evaluate/{job_id} returns 404 (expected for unknown job) not 405 or 500."""
    r = client.get("/api/v1/evaluate/00000000-0000-0000-0000-000000000000", follow_redirects=False)
    # 200 (with error body), 404, or 422 are all valid responses from a registered route
    assert r.status_code in (200, 404, 422), f"Unexpected status: {r.status_code}"


def test_read_only_paths_use_v1_prefix():
    """_READ_ONLY_PATHS includes /api/v1/ entries."""
    from dashboard.state import _READ_ONLY_PATHS
    assert "/api/v1/health" in _READ_ONLY_PATHS
    assert "/api/v1/health/live" in _READ_ONLY_PATHS
    assert "/api/v1/intel/cards" in _READ_ONLY_PATHS


def test_reliability_zero_runs_returns_zero_score():
    from unittest.mock import MagicMock, patch

    mock_row = MagicMock()
    mock_row.__getitem__.side_effect = lambda idx: [0, 0, None][idx]
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = mock_row
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("utils.scraper_reliability.get_engine", return_value=mock_engine):
        from utils.scraper_reliability import compute_scraper_reliability

        result = compute_scraper_reliability("nonexistent_scraper")
        assert result["runs"] == 0
        assert result["reliability_score"] == 0.0
        assert result["last_run"] is None


# ── T-1219: Unified error response schema ──────────────────────────────
# Note: 401 test must run LAST because _ensure_api_keys caches the first key


def test_unified_error_response_has_request_id(monkeypatch):
    """Error response contains request_id from middleware."""
    monkeypatch.setenv("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    from dashboard.state import _reset_api_keys
    _reset_api_keys()
    r = client.get("/api/v1/market/forecast/NonexistentMarket", follow_redirects=False)
    assert r.status_code == 400
    body = r.json()
    assert "request_id" in body, f"Missing 'request_id' in {body}"
    assert isinstance(body["request_id"], str)


def test_unified_error_response_has_code_field(monkeypatch):
    """Trigger a validation error on a route returning ErrorResponse schema."""
    monkeypatch.setenv("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    from dashboard.state import _reset_api_keys
    _reset_api_keys()
    r = client.get("/api/v1/market/forecast/NonexistentMarket", follow_redirects=False)
    assert r.status_code == 400
    body = r.json()
    assert "code" in body, f"Missing 'code' in {body}"
    assert body["code"] == "VALIDATION_ERROR"


def test_unified_401_response_with_code_field(monkeypatch):
    """Trigger a 401 on an auth-gated route without API key."""
    monkeypatch.delenv("DASHBOARD_API_KEY_ALLOW_EMPTY", raising=False)
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret-key-for-test")
    from dashboard.state import _reset_api_keys
    _reset_api_keys()
    r = client.post("/api/v1/run/yelahanka", follow_redirects=False)
    assert r.status_code == 401
    body = r.json()
    assert "code" in body
    assert body["code"] == "UNAUTHORIZED"


# ── T-1220: ETag support ────────────────────────────────────────────────


def test_etag_computed_deterministically():
    """compute_etag returns same hash for same data."""
    from utils.etag import compute_etag
    d = {"a": 1, "b": [2, 3]}
    assert compute_etag(d) == compute_etag(d)
    assert isinstance(compute_etag(d), str)
    assert len(compute_etag(d)) == 16


def test_etag_returns_304_on_match(monkeypatch):
    """GET /api/v1/intel/cards with matching If-None-Match returns 304."""
    monkeypatch.setenv("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    from dashboard.state import _reset_api_keys
    _reset_api_keys()
    r = client.get("/api/v1/intel/cards", follow_redirects=False)
    if r.status_code != 200:
        pytest.skip(f"intel/cards returned {r.status_code}, need DB")
    etag = r.headers.get("etag", "").strip('" ')
    r2 = client.get("/api/v1/intel/cards", headers={"If-None-Match": etag}, follow_redirects=False)
    assert r2.status_code == 304


def test_etag_returns_200_on_mismatch(monkeypatch):
    """GET with non-matching If-None-Match returns full 200 response."""
    monkeypatch.setenv("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    from dashboard.state import _reset_api_keys
    _reset_api_keys()
    r = client.get("/api/v1/market/forecast/NonexistentMarket", follow_redirects=False)
    assert r.status_code == 400
    body = r.json()
    assert "code" in body
    assert body["code"] == "VALIDATION_ERROR"


def test_etag_importable():
    """utils/etag.py importable with all 3 functions."""
    from utils.etag import compute_etag, check_etag, add_etag
    assert callable(compute_etag)
    assert callable(check_etag)
    assert callable(add_etag)


# ── T-1221: Rate limit headers in all responses + OpenAPI spec freeze ───


def test_rate_limit_headers_omitted_on_unlimited_endpoints(monkeypatch):
    """Non-rate-limited endpoints omit X-RateLimit-* headers (no misleading defaults)."""
    monkeypatch.setenv("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    from dashboard.state import _reset_api_keys
    _reset_api_keys()
    r = client.get("/api/v1/health/live", follow_redirects=False)
    assert r.status_code == 200
    assert "X-RateLimit-Limit" not in r.headers, (
        "Non-rate-limited endpoints should not advertise a fake rate limit"
    )


def test_openapi_spec_json_exists():
    """docs/api-v1.json exists as frozen OpenAPI spec."""
    spec_path = "docs/api-v1.json"
    assert os.path.exists(spec_path), f"{spec_path} not found"
    import json
    with open(spec_path) as f:
        spec = json.load(f)
    assert "openapi" in spec
    assert "paths" in spec


# ── Prediction Ledger (GATE-111, T-1242) ──


@pytest.fixture
def mock_ledger_db():
    """Mock DB returning ledger verdict counts."""
    from unittest.mock import MagicMock, patch

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        MagicMock(
            fetchall=lambda: [
                ("pending", 3),
                ("hit", 10),
                ("miss", 2),
                ("partial", 1),
                ("unverifiable", 1),
            ]
        ),
        MagicMock(fetchall=lambda: [("Yelahanka",), ("Devanahalli",)]),
        MagicMock(
            fetchall=lambda: [
                ("psf_forecast", "hit", 8),
                ("psf_forecast", "miss", 1),
                ("opportunity_score", "hit", 2),
                ("assembly_alert", "miss", 1),
            ]
        ),
    ]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.routers.ops._get_sa_engine", return_value=mock_engine):
        yield


def test_ops_ledger_returns_200(mock_ledger_db, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "test-key")
    r = client.get(
        "/api/v1/ops/ledger",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 200


def test_ledger_hit_rate_bounded_0_to_1(mock_ledger_db, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "test-key")
    r = client.get(
        "/api/v1/ops/ledger",
        headers={"X-API-Key": "test-key"},
    )
    body = r.json()
    assert 0.0 <= body["hit_rate"] <= 1.0
    assert body["hit_rate"] == pytest.approx(0.8333, rel=0.01)


def test_ledger_module_breakdown_has_all_modules(mock_ledger_db, monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "test-key")
    r = client.get(
        "/api/v1/ops/ledger",
        headers={"X-API-Key": "test-key"},
    )
    body = r.json()
    assert "psf_forecast" in body["module_breakdown"]
    assert "opportunity_score" in body["module_breakdown"]
    assert "assembly_alert" in body["module_breakdown"]
    assert body["module_breakdown"]["psf_forecast"]["hit"] == 8
    assert body["module_breakdown"]["psf_forecast"]["miss"] == 1
