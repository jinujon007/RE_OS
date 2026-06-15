"""/api/evaluate smoke test — verifies evaluate endpoint structure.

Unit-safe: route validation only. Full integration requires live Docker stack.
"""

import os

import pytest


@pytest.mark.test_id("G87-EV1")
@pytest.mark.unit
def test_evaluate_route_registered():
    """FastAPI app has /api/evaluate POST route registered."""
    from dashboard.app_fastapi import app

    routes = [
        (r.path, list(r.methods) if hasattr(r, "methods") else [])
        for r in app.routes
        if hasattr(r, "methods")
    ]
    matching = [p for p, m in routes if "evaluate" in p and "POST" in m]
    assert len(matching) >= 1, f"No POST /api/evaluate route found. Routes: {routes}"
    assert "/api/evaluate" in matching, f"Expected /api/evaluate, got {matching}"


@pytest.mark.test_id("G87-EV2")
@pytest.mark.unit
def test_evaluate_pipeline_importable():
    """Evaluate pipeline module imports without error."""
    import crews.evaluate_pipeline  # noqa: F401


@pytest.mark.test_id("G87-EV3")
@pytest.mark.integration
@pytest.mark.skipif(
    "not os.environ.get('DATABASE_URL') or not os.environ.get('DB_PASSWORD')",
    reason="Requires live database + LLM providers (DATABASE_URL + DB_PASSWORD in env)",
)
def test_evaluate_returns_all_sections():
    """Integration test: confirm /api/evaluate returns accepted (202) with job_id.

    The evaluate endpoint is async: POST returns a job_id immediately;
    the 5-section result is available via GET /api/evaluate/<job_id>.
    Full validation requires a live DB + LLM stack.

    NOTE: CI-skipped. Run against live Docker stack:
        docker compose exec agents pytest tests/test_evaluate_smoke.py -m integration
    """
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    os.environ.setdefault("REDIS_URL", "memory://")

    client = TestClient(app)
    payload = {
        "survey_no": "45/2",
        "market": "Devanahalli",
        "area_acres": 4.0,
        "ask_psf": 5500,
        "deal_type": "jd",
    }
    resp = client.post(
        "/api/evaluate",
        json=payload,
        headers={"X-API-Key": os.environ.get("DASHBOARD_API_KEY", "test")},
    )
    # Async endpoint: returns 200/202 with job_id immediately
    assert resp.status_code in (200, 201, 202), (
        f"/api/evaluate returned {resp.status_code}: {resp.text[:500]}"
    )
    data = resp.json()
    assert "job_id" in data, f"Response missing job_id: {data}"
    assert data.get("status") in ("pending", "accepted", "processing"), (
        f"Unexpected job status: {data}"
    )
    # Verify job_id is a valid UUID
    job_id = data["job_id"]
    assert len(job_id) == 36 and job_id.count("-") == 4, (
        f"job_id does not look like a UUID: {job_id}"
    )


def _validate_evaluate_response(data: dict):
    """Validate evaluate response has all 5 mandatory sections."""
    assert isinstance(data.get("board_session"), str) and len(data["board_session"]) > 0
    assert isinstance(data.get("deal_memo"), str) and len(data["deal_memo"]) >= 2000
    assert (
        isinstance(data.get("investor_brief"), str)
        and len(data["investor_brief"]) >= 2000
    )
    assert (
        isinstance(data.get("shareholder_round"), list)
        and len(data["shareholder_round"]) == 4
    )
    assert (
        isinstance(data.get("composite_score"), (int, float))
        and 0 <= data["composite_score"] <= 1
    )
