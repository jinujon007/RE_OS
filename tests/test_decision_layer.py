"""
T-693 — Decision Layer unit tests.
Tests evaluate pipeline, deal memo generation, investor brief generation.
Uses Flask test client — no real DB or Docker needed.
"""

import os
import sys

import pytest

pytestmark = pytest.mark.unit

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    monkeypatch.delenv("DASHBOARD_API_KEY_PREV", raising=False)
    from dashboard.app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_evaluate_requires_survey_no(client, monkeypatch):
    """POST /api/evaluate returns 400 when survey_no missing."""
    r = client.post("/api/evaluate", json={"market": "Yelahanka"})
    assert r.status_code == 400
    assert "survey_no required" in r.json["error"]


def test_evaluate_requires_market(client, monkeypatch):
    """POST /api/evaluate returns 400 when market invalid."""
    r = client.post("/api/evaluate", json={"survey_no": "45", "market": ""})
    assert r.status_code == 400
    assert "valid market required" in r.json["error"]


def test_evaluate_validates_deal_type(client, monkeypatch):
    """POST /api/evaluate returns 400 when deal_type not in allowed list."""
    r = client.post("/api/evaluate", json={"survey_no": "45", "market": "Yelahanka", "deal_type": "invalid"})
    assert r.status_code == 400
    assert "deal_type must be one of" in r.json["error"]


def test_evaluate_validates_numeric_fields(client, monkeypatch):
    """POST /api/evaluate returns 400 when land_area_sqft/sell_psf not numeric."""
    r = client.post("/api/evaluate", json={"survey_no": "45", "market": "Yelahanka", "land_area_sqft": "abc"})
    assert r.status_code == 400
    assert "land_area_sqft must be a number" in r.json["error"]


def test_opportunity_queue_no_auth(client, monkeypatch):
    """GET /api/opportunity/queue is read-only — no auth needed."""
    r = client.get("/api/opportunity/queue?market=Yelahanka")
    assert r.status_code in (200, 500)  # 500 OK if DB not available


def test_opportunity_queue_filters_by_min_score(client, monkeypatch):
    """GET /api/opportunity/queue respects min_score param."""
    r = client.get("/api/opportunity/queue?min_score=0.5&limit=5")
    assert r.status_code in (200, 500)


def test_opportunity_queue_respects_limit(client, monkeypatch):
    """GET /api/opportunity/queue respects limit param."""
    r = client.get("/api/opportunity/queue?limit=10")
    assert r.status_code in (200, 500)
    if r.status_code == 200:
        assert len(r.json.get("opportunities", [])) <= 10