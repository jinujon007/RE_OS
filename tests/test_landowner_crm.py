"""Unit tests for Landowner CRM (T-986 — Sprint 56).

NOTE: FastAPI TestClient tests require a fresh module import per test to avoid
cached _get_sa_engine references. Each test function calling TestClient MUST
patch BEFORE importing app_fastapi.
"""

import pytest
from unittest.mock import patch, MagicMock
import importlib

pytestmark = pytest.mark.unit


def _fresh_client():
    """Return a TestClient with a freshly-imported app module under patch context.
    Call inside a `with patch("utils.db.get_engine")` block."""
    from dashboard import app_fastapi

    importlib.reload(app_fastapi)
    from starlette.testclient import TestClient

    return TestClient(app_fastapi.app)


class TestLandownerCRM:
    def test_create_landowner_returns_201(self):
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = (
                "u1",
                "45/2",
                "Devanahalli",
                "Venkatesh Gowda",
                "9876543210",
                "primary",
                "cold",
                None,
                None,
                None,
                None,
            )
            client = _fresh_client()
            resp = client.post(
                "/api/landowners",
                json={
                    "survey_no": "45/2",
                    "market": "Devanahalli",
                    "owner_name": "Venkatesh Gowda",
                    "contact_phone": "9876543210",
                },
                headers={"X-API-Key": "test-key"},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["survey_no"] == "45/2"
            assert data["approach_status"] == "cold"

    def test_create_landowner_rejects_invalid_contact_type(self):
        with patch("utils.db.get_engine"):
            client = _fresh_client()
            resp = client.post(
                "/api/landowners",
                json={
                    "survey_no": "45/2",
                    "market": "Devanahalli",
                    "owner_name": "Test",
                    "contact_type": "invalid_type",
                },
                headers={"X-API-Key": "test-key"},
            )
            assert resp.status_code == 400
            assert "invalid contact_type" in resp.text

    def test_list_returns_paginated(self):
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.scalar.return_value = 1
            mock_conn.execute.return_value.fetchall.return_value = [
                (
                    "u1",
                    "45/2",
                    "Devanahalli",
                    "Owner1",
                    None,
                    "primary",
                    "cold",
                    None,
                    None,
                    None,
                    None,
                ),
            ]
            client = _fresh_client()
            resp = client.get(
                "/api/landowners?market=Devanahalli", headers={"X-API-Key": "test-key"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)
            assert "data" in data
            assert "pagination" in data
            assert data["pagination"]["page"] == 1

    def test_list_filters_by_market(self):
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.scalar.return_value = 1
            mock_conn.execute.return_value.fetchall.return_value = [
                (
                    "u1",
                    "45/2",
                    "Devanahalli",
                    "Owner1",
                    None,
                    "primary",
                    "cold",
                    None,
                    None,
                    None,
                    None,
                ),
            ]
            client = _fresh_client()
            resp = client.get(
                "/api/landowners?market=Devanahalli", headers={"X-API-Key": "test-key"}
            )
            assert resp.status_code == 200

    def test_update_approach_status_returns_200(self):
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.side_effect = [
                ("u1", "45/2", "Devanahalli", "Venkatesh Gowda", "cold", None),
                (
                    "u1",
                    "45/2",
                    "Devanahalli",
                    "Venkatesh Gowda",
                    None,
                    "primary",
                    "warm",
                    None,
                    None,
                    None,
                    None,
                ),
            ]
            client = _fresh_client()
            resp = client.patch(
                "/api/landowners/00000000-0000-0000-0000-000000000001",
                json={
                    "approach_status": "warm",
                },
                headers={"X-API-Key": "test-key"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["approach_status"] == "warm"

    def test_pipeline_summary_has_counts(self):
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = (
                mock_conn
            )
            mock_conn.execute.return_value.fetchall.side_effect = [
                [("cold", 5), ("warm", 3)],
                [("Devanahalli", 4, 7500.0)],
            ]
            client = _fresh_client()
            resp = client.get(
                "/api/landowners/pipeline", headers={"X-API-Key": "test-key"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "by_status" in data
            assert "by_market" in data
            assert data["by_status"]["cold"] == 5

    def test_discord_fires_on_mou(self):
        with patch("utils.discord_notifier.send") as mock_send:
            mock_send.return_value = True
            from utils.discord_notifier import format_landowner_update

            msg = format_landowner_update(
                "mou", "45/2", "Devanahalli", "Venkatesh Gowda", 7500
            )
            assert "MOU" in msg
            assert "₹7,500" in msg
            assert len(msg) <= 500

    def test_discord_fires_on_mou_via_send_alert(self):
        with patch("utils.discord_notifier.send") as mock_send:
            mock_send.return_value = True
            from utils.discord_notifier import send_landowner_alert

            result = send_landowner_alert(
                "loi", "45/2", "Devanahalli", "Test Owner", 8000
            )
            assert result is True
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert "LOI" in args[1]
