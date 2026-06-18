"""Unit tests for decision journal API (GATE-118, T-1280)."""
import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

_V1 = "/api/v1/ops/decision-journal"


def _make_client():
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    return TestClient(app)


def test_decision_journal_post_201():
    from datetime import datetime, timezone
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "test-key"}, clear=False):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__enter__.return_value = mock_conn
        created_dt = datetime(2026, 6, 18, 14, 0, 0, tzinfo=timezone.utc)
        row = (1, created_dt)
        mock_conn.execute.return_value.fetchone.return_value = row

        with patch("dashboard.routers.ops._get_sa_engine", return_value=mock_engine):
            client = _make_client()
            resp = client.post(
                _V1,
                headers={"X-API-Key": "test-key"},
                json={
                    "entry_date": "2026-06-18",
                    "decision_type": "land_acquisition",
                    "market": "Yelahanka",
                    "intel_used": "PSF trend showed 8% upside",
                    "outcome": "acted",
                    "notes": "Acquired 2 acres in Yelahanka",
                },
            )
            assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "id" in body
            assert "created_at" in body


def test_decision_journal_invalid_type_422():
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "test-key"}, clear=False):
        client = _make_client()
        resp = client.post(
            _V1,
            headers={"X-API-Key": "test-key"},
            json={
                "entry_date": "2026-06-18",
                "decision_type": "invalid_type",
                "market": "Yelahanka",
            },
        )
        assert resp.status_code == 422
        body = resp.json()
        assert "invalid decision_type" in body.get("error", "")


def test_decision_journal_get_200():
    from datetime import datetime, timezone
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "test-key"}, clear=False):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = 1
        entry_date = date(2026, 6, 18)
        created_dt = datetime(2026, 6, 18, 14, 0, 0, tzinfo=timezone.utc)
        row = (1, entry_date, "land_acquisition", "Yelahanka", "PSF trend", "acted", "notes", created_dt)
        mock_conn.execute.return_value.fetchall.return_value = [row]

        with patch("dashboard.routers.ops._get_sa_engine", return_value=mock_engine):
            client = _make_client()
            resp = client.get(
                _V1,
                headers={"X-API-Key": "test-key"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert "total" in body
            assert "entries" in body
            assert body["total"] >= 1


def test_decision_journal_get_paginated():
    with patch.dict(os.environ, {"DASHBOARD_API_KEY": "test-key"}, clear=False):
        mock_conn = MagicMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = 5
        mock_conn.execute.return_value.fetchall.return_value = []

        with patch("dashboard.routers.ops._get_sa_engine", return_value=mock_engine):
            client = _make_client()
            resp = client.get(
                f"{_V1}?limit=10&offset=0",
                headers={"X-API-Key": "test-key"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 5
            assert isinstance(body["entries"], list)
