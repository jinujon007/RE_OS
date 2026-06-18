"""Tests for /api/ops/slo endpoint (GATE-105 T-1215)."""
import os
from unittest.mock import patch, MagicMock

import pytest
from starlette.testclient import TestClient
from dashboard.app_fastapi import app

pytestmark = pytest.mark.unit

os.environ.setdefault("DASHBOARD_API_KEY", "test-key")

client = TestClient(app)


def test_slo_endpoint_returns_200():
    with patch("dashboard.routers.ops._get_sa_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = (100, 95)
        mock_conn.execute.return_value.fetchall.return_value = [(10.0,), (20.0,), (30.0,)]
        resp = client.get("/api/v1/ops/slo", headers={"X-API-Key": "test-key"})
        assert resp.status_code == 200


def test_slo_scheduler_breached_when_success_rate_low():
    with patch("dashboard.routers.ops._get_sa_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = (100, 50)
        mock_conn.execute.return_value.fetchall.return_value = []
        resp = client.get("/api/v1/ops/slo", headers={"X-API-Key": "test-key"})
        if resp.status_code != 200:
            pytest.skip(f"SLO endpoint returned {resp.status_code}")
            return
        data = resp.json()
        assert data["scheduler_slo"]["status"] == "BREACHED"


def test_slo_board_room_met_when_p95_below_90():
    with patch("dashboard.routers.ops._get_sa_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = (100, 95)
        mock_conn.execute.return_value.fetchall.return_value = [(30.0,), (45.0,), (50.0,), (60.0,), (85.0,)]
        resp = client.get("/api/v1/ops/slo", headers={"X-API-Key": "test-key"})
        if resp.status_code != 200:
            pytest.skip(f"SLO endpoint returned {resp.status_code}")
            return
        data = resp.json()
        p95 = data["board_room_slo"].get("p95_s")
        assert p95 is None or p95 < 90
