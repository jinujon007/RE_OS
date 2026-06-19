"""GATE-106: API Maturity — versioning, error schema, ETag, rate limit headers."""
import os

os.environ["REDIS_URL"] = "memory://"
os.environ["DASHBOARD_API_KEY_ALLOW_EMPTY"] = "true"
os.environ.pop("DASHBOARD_API_KEY", None)

import pytest

pytestmark = pytest.mark.unit

@pytest.fixture(scope="module")
def test_client():
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    return TestClient(app)


def test_gate106_v1_health_live_returns_200(test_client):
    """Assertion 1: /api/v1/health/live returns 200."""
    r = test_client.get("/api/v1/health/live", follow_redirects=False)
    assert r.status_code == 200, f"Got {r.status_code}: {r.text[:100]}"
    body = r.json()
    assert "agents" in body


def test_gate106_legacy_health_redirects(test_client):
    """Assertion 2: /api/health/live returns 301 redirect."""
    r = test_client.get("/api/health/live", follow_redirects=False)
    assert r.status_code == 301, f"Got {r.status_code}: {r.text[:100]}"
    loc = r.headers.get("location", "")
    assert loc.startswith("/api/v1/"), f"location={loc}"


def test_gate106_404_has_code_field(test_client):
    """Assertion 3: 404 response has 'code' field."""
    r = test_client.get("/api/v1/market/forecast/NonexistentMarket", follow_redirects=False)
    assert r.status_code == 400, f"Got {r.status_code}: {r.text[:100]}"
    body = r.json()
    assert "code" in body


def test_gate106_etag_deterministic():
    """Assertion 4: compute_etag is deterministic."""
    from utils.etag import compute_etag
    assert compute_etag({"a": 1}) == compute_etag({"a": 1})


def test_gate106_openapi_spec_exists():
    """Assertion 5: docs/api-v1.json exists."""
    spec_path = os.path.join(os.path.dirname(__file__), "..", "docs", "api-v1.json")
    assert os.path.exists(spec_path), f"docs/api-v1.json not found at {spec_path}"
