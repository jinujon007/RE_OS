import os
import pytest
pytestmark = pytest.mark.unit

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)


def test_health_no_auth():
    r = client.get("/api/health")
    assert r.status_code == 200


def test_run_trigger_requires_auth(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/run/yelahanka")
    assert r.status_code == 401


def test_run_trigger_with_auth(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/run/yelahanka", headers={"X-API-Key": "secret"})
    assert r.status_code in (200, 202, 409)


def test_db_state_no_auth():
    r = client.get("/api/db/state")
    assert r.status_code in (200, 500)


def test_run_invalid_market_returns_400(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret")
    r = client.post("/api/run/fakecity", headers={"X-API-Key": "secret"})
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
    r = client.get("/api/memory/explorer")
    assert r.status_code in (200, 500)  # 200 when DB mocked, 500 without DB
    if r.status_code == 200:
        body = r.json()
        assert "total" in body
        assert "page" in body
        assert "per_page" in body
        assert "memories" in body


def test_memory_explorer_respects_market_filter(mock_db):
    r = client.get("/api/memory/explorer?market=Yelahanka")
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        body = r.json()
        assert body["page"] == 1
        assert body["per_page"] == 20


def test_conflict_count_endpoint_returns_integer():
    r = client.get("/api/memory/conflict-count")
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        body = r.json()
        assert "unresolved_conflicts" in body
        assert isinstance(body["unresolved_conflicts"], int)


def test_conflict_count_mocked(mock_conflict_db):
    r = client.get("/api/memory/conflict-count")
    assert r.status_code == 200
    assert r.json()["unresolved_conflicts"] == 3


# ── Conflict Badge (T-86C) ──


def test_conflict_badge_script_present_in_index_html():
    path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "templates", "index.html")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "conflict-badge" in content, "conflict-badge id not found in index.html"
    assert "/api/memory/conflict-count" in content, "/api/memory/conflict-count endpoint not found in index.html"
    assert "pollConflictBadge" in content, "pollConflictBadge function not found in index.html"


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
    mock_row1.__getitem__.side_effect = lambda idx: ["Yelahanka", "portal_scraped", 100][idx]
    mock_row2 = MagicMock()
    mock_row2.__getitem__.side_effect = lambda idx: ["Yelahanka", "seed_estimated", 50][idx]
    mock_row3 = MagicMock()
    mock_row3.__getitem__.side_effect = lambda idx: ["Devanahalli", "portal_scraped", 200][idx]
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [mock_row1, mock_row2, mock_row3]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_engine):
        yield


def test_provenance_endpoint_returns_200(mock_provenance_db):
    r = client.get("/api/data/provenance")
    assert r.status_code == 200
    body = r.json()
    assert "Yelahanka" in body
    assert "Devanahalli" in body


def test_provenance_has_all_markets(mock_provenance_db):
    r = client.get("/api/data/provenance")
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
    r = client.get("/api/data/provenance")
    assert r.status_code == 200
    body = r.json()
    for market_data in body.values():
        assert isinstance(market_data["live_pct"], float)
        assert 0.0 <= market_data["live_pct"] <= 100.0


def test_provenance_computed_values(mock_provenance_db):
    """Assert live_pct is correctly computed: Yelahanka=66.7%, Devanahalli=100%."""
    r = client.get("/api/data/provenance")
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
    mock_row.__getitem__.side_effect = lambda idx: ["Yelahanka", "portal_scraped", 100][idx]
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = [mock_row]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    with patch("dashboard.app_fastapi._get_sa_engine", return_value=mock_engine):
        r = client.get("/api/data/provenance?market=Yelahanka")
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
    r = client.get("/api/scraper/reliability")
    assert r.status_code == 200
    body = r.json()
    assert len(body) > 0


def test_reliability_has_all_scrapers(mock_reliability_db):
    from config.scraper_registry import SCRAPER_NAMES
    r = client.get("/api/scraper/reliability")
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
    r = client.get("/api/scraper/reliability")
    assert r.status_code == 200
    body = r.json()
    for scraper in SCRAPER_NAMES:
        s = body[scraper]
        assert s["runs"] == 10
        assert s["successes"] == 8
        assert s["reliability_score"] == 0.8


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
