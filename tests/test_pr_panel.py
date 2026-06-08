"""Unit tests for PR Studio dashboard panel (Sprint 59, T-1000)."""
import pytest
from unittest.mock import patch, MagicMock
pytestmark = pytest.mark.unit

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

_SESSION_DATA: dict = {}


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestPRPanel:
    def test_pr_panel_returns_200(self, client):
        resp = client.get("/pr")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_pr_panel_has_brand_mentions_section(self, client):
        resp = client.get("/pr")
        html = resp.text
        assert "Brand Mentions" in html
        assert "Content Calendar" in html
        assert "Competitor Moves" in html

    def test_pr_mentions_returns_200(self, client):
        with patch("intelligence.competitive_intel.CompetitiveIntelEngine") as mock_engine, \
             patch("utils.db.get_engine") as mock_db:
            mock_db.return_value.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []
            mock_engine_instance = MagicMock()
            mock_engine_instance.new_launches.return_value = []
            mock_engine.return_value = mock_engine_instance
            resp = client.get("/api/pr/mentions?days=7", headers={"X-API-Key": "test"})
            assert resp.status_code == 200
            data = resp.json()
            assert "mentions" in data
            assert "competitor_launches" in data
            assert "mention_count" in data

    def test_pr_mentions_defaults_to_7_days(self, client):
        with patch("intelligence.competitive_intel.CompetitiveIntelEngine") as mock_engine, \
             patch("utils.db.get_engine") as mock_db:
            mock_db.return_value.connect.return_value.__enter__.return_value.execute.return_value.fetchall.return_value = []
            mock_engine_instance = MagicMock()
            mock_engine_instance.new_launches.return_value = []
            mock_engine.return_value = mock_engine_instance
            resp = client.get("/api/pr/mentions", headers={"X-API-Key": "test"})
            assert resp.status_code == 200
            assert resp.json()["days_window"] == 7

    def test_pr_mentions_handles_db_error(self, client):
        with patch("intelligence.competitive_intel.CompetitiveIntelEngine") as mock_engine, \
             patch("utils.db.get_engine") as mock_db:
            mock_db.return_value.connect.side_effect = Exception("DB error")
            mock_engine_instance = MagicMock()
            mock_engine_instance.new_launches.return_value = []
            mock_engine.return_value = mock_engine_instance
            resp = client.get("/api/pr/mentions", headers={"X-API-Key": "test"})
            assert resp.status_code == 200
            data = resp.json()
            assert "mentions" in data
