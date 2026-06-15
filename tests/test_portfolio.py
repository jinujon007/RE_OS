"""Unit tests for LLS Portfolio (T-989 — Sprint 57 GATE-65)."""

import pytest
from unittest.mock import patch, MagicMock
import importlib

pytestmark = pytest.mark.unit


def _fresh_client():
    from dashboard import app_fastapi

    importlib.reload(app_fastapi)
    from starlette.testclient import TestClient

    return TestClient(app_fastapi.app)


def _mock_portfolio_row(idx: int = 0) -> tuple:
    from datetime import date, datetime

    return (
        f"u{idx}",
        f"Project {idx}",
        "Bangalore",
        "Yelahanka",
        "premium",
        500,
        480,
        date(2020, 1, 15),
        date(2024, 6, 30),
        50.00,
        300.00,
        18.50,
        "delivered",
        "RERA/123",
        "Promoter track record",
        datetime(2026, 6, 8, 0, 0, 0),
    )


def test_portfolio_endpoint_returns_200():
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _mock_portfolio_row(0),
            _mock_portfolio_row(1),
            _mock_portfolio_row(2),
        ]
        client = _fresh_client()
        resp = client.get("/api/portfolio", headers={"X-API-Key": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert len(data["data"]) == 3


def test_portfolio_summary_has_keys():
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        _call_idx = [0]

        def _side(*a, **kw):
            idx = _call_idx[0]
            _call_idx[0] += 1
            if idx == 0:
                m = MagicMock()
                m.fetchone.return_value = (4, 3, 18.2, 1800)
                return m
            m = MagicMock()
            m.fetchall.return_value = [("Yelahanka",), ("Devanahalli",)]
            return m

        mock_conn.execute.side_effect = _side
        client = _fresh_client()
        resp = client.get("/api/portfolio/summary", headers={"X-API-Key": "test"})
        assert resp.status_code == 200, resp.text[:300]
        data = resp.json()
        assert "total_projects" in data
        assert "delivered_count" in data
        assert "total_delivered_sqft_est" in data
        assert "avg_realized_irr_pct" in data
        assert "markets_covered" in data
        assert data["total_projects"] == 4
        assert data["delivered_count"] == 3


def test_portfolio_seeded_with_3_promoter_entries():
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = [
            _mock_portfolio_row(0),
            _mock_portfolio_row(1),
            _mock_portfolio_row(2),
            _mock_portfolio_row(3),
        ]
        client = _fresh_client()
        resp = client.get("/api/portfolio", headers={"X-API-Key": "test"})
        assert resp.status_code == 200
        assert len(resp.json()["data"]) >= 3


def test_portfolio_empty_returns_empty_list():
    """Edge case: no portfolio entries returns empty data array."""
    with patch("utils.db.get_engine") as mock_eng:
        mock_conn = MagicMock()
        mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchall.return_value = []
        client = _fresh_client()
        resp = client.get("/api/portfolio", headers={"X-API-Key": "test"})
        assert resp.status_code == 200
        assert resp.json()["data"] == []


def test_portfolio_summary_db_error_graceful():
    """Edge case: DB connection failure returns 500 with error key."""
    with patch("utils.db.get_engine", side_effect=Exception("Connection refused")):
        client = _fresh_client()
        resp = client.get("/api/portfolio/summary", headers={"X-API-Key": "test"})
        assert resp.status_code == 500
        assert "error" in resp.json()
