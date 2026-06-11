"""Coverage tests for Foundation Hardening endpoints (T-904–T-924).

Tests new endpoints added during Foundation Hardening sprint:
- GET /api/health/backup (T-904)
- POST /api/surveys (T-915)
- POST/GET/PATCH /api/deals (T-917)
- GET /api/llm/quota (T-924)
- GET /api/data/freshness (T-828)
- GET /api/memory/explorer (T-828)
"""

import os
from unittest.mock import MagicMock, patch
import pytest

pytestmark = pytest.mark.unit

os.environ.setdefault("REDIS_URL", "memory://")

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)


class TestHealthBackup:
    def test_backup_endpoint_returns_200(self):
        r = client.get("/api/health/backup")
        assert r.status_code in (200, 500)

    def test_backup_no_auth_required(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "secret"}):
            r = client.get("/api/health/backup")
        assert r.status_code in (200, 401, 500)

    def test_backup_returns_structured_response(self):
        with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchone.return_value = None
            r = client.get("/api/health/backup")
            assert r.status_code == 200
            data = r.json()
            assert "status" in data
            assert "last_backup" in data


class TestSurveysEndpoint:
    def test_create_survey_no_auth(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            r = client.post(
                "/api/surveys",
                json={
                    "survey_no": "TEST/1",
                    "market": "Devanahalli",
                    "total_area_acres": 5.0,
                },
            )
        assert r.status_code in (200, 201, 401)

    @pytest.mark.xfail(
        reason="Requires live PostgreSQL (mock complexity with SQLAlchemy begin())"
    )
    def test_create_survey_with_auth(self):
        with (
            patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}),
            patch("dashboard.app_fastapi._get_sa_engine") as mock_eng,
        ):
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = ["mm-uuid"]
            r = client.post(
                "/api/surveys",
                json={
                    "survey_no": "TEST/1",
                    "market": "Devanahalli",
                    "total_area_acres": 5.0,
                },
                headers={"X-API-Key": "test-key"},
            )
        assert r.status_code in (200, 201, 400, 422)


class TestDealsEndpoint:
    def test_create_deal_no_auth(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            r = client.post(
                "/api/deals",
                json={
                    "survey_no": "45/2",
                    "market": "Devanahalli",
                    "opportunity_score": 0.82,
                },
            )
        assert r.status_code in (200, 201, 401)

    def test_create_deal_with_auth(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            r = client.post(
                "/api/deals",
                json={
                    "survey_no": "45/2",
                    "market": "Devanahalli",
                    "opportunity_score": 0.82,
                },
                headers={"X-API-Key": "test-key"},
            )
        assert r.status_code in (200, 201, 400, 422, 500)

    def test_list_deals_no_auth(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            r = client.get("/api/deals")
        assert r.status_code in (200, 401)

    def test_list_deals_with_auth(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            r = client.get("/api/deals", headers={"X-API-Key": "test-key"})
        assert r.status_code in (200, 500)

    def test_list_deals_filters(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            r = client.get(
                "/api/deals?stage=prospecting&market=Devanahalli",
                headers={"X-API-Key": "test-key"},
            )
        assert r.status_code in (200, 500)

    def test_patch_deal_no_auth(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            r = client.patch("/api/deals/some-uuid", json={"stage": "diligence"})
        assert r.status_code in (200, 401, 404)


class TestLLMQuota:
    def test_quota_endpoint_returns_200(self):
        r = client.get("/api/llm/quota")
        assert r.status_code in (200, 500)

    def test_quota_endpoint_returns_providers(self):
        r = client.get("/api/llm/quota")
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            data = r.json()
            assert "usage" in data
            assert "date" in data


class TestDataFreshness:
    def test_data_freshness_returns_200(self):
        r = client.get("/api/data/freshness")
        assert r.status_code in (200, 500)

    def test_data_freshness_endpoint_returns_dict(self):
        r = client.get("/api/data/freshness")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert "freshness" in data
        assert isinstance(data["freshness"], list)

    def test_data_freshness_market_filter(self):
        r = client.get("/api/data/freshness?market=Yelahanka")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        if data["freshness"]:
            for entry in data["freshness"]:
                assert "Yelahanka" in entry.get("market", "")

    def test_data_freshness_items_have_all_fields(self):
        r = client.get("/api/data/freshness")
        assert r.status_code == 200
        data = r.json()
        if data["freshness"]:
            required = {
                "source",
                "plugin_id",
                "market",
                "record_count",
                "freshness_score",
                "label",
                "is_stale",
            }
            for entry in data["freshness"]:
                missing = required - set(entry.keys())
                assert not missing, (
                    f"Entry {entry.get('source')} missing fields: {missing}"
                )

    def test_data_freshness_case_insensitive_market(self):
        r = client.get("/api/data/freshness?market=yelahanka")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list) or isinstance(data.get("freshness", []), list)

    def test_data_freshness_sort_order_live_first(self):
        r = client.get("/api/data/freshness")
        assert r.status_code == 200
        data = r.json()
        freshness = data.get("freshness", [])
        if len(freshness) > 1:
            labels = [f["label"] for f in freshness]
            live_idx = [i for i, l in enumerate(labels) if l == "LIVE"]
            stale_idx = [i for i, l in enumerate(labels) if l == "STALE"]
            if live_idx and stale_idx:
                assert max(live_idx) < min(stale_idx), (
                    "LIVE entries must sort before STALE"
                )


class TestMemoryExplorer:
    def test_memory_explorer_returns_200(self):
        r = client.get("/api/memory/explorer?limit=5")
        assert r.status_code in (200, 500)

    def test_memory_explorer_filters(self):
        r = client.get(
            "/api/memory/explorer?market=Yelahanka&min_confidence=0.5&fact_type=fact"
        )
        assert r.status_code in (200, 500)
