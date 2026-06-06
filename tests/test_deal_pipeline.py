"""T-961: Deal pipeline Discord alerts hardening tests."""
import os
from unittest.mock import MagicMock, PropertyMock, patch
import pytest
pytestmark = pytest.mark.unit

os.environ.setdefault("REDIS_URL", "memory://")

from starlette.testclient import TestClient
from dashboard.app_fastapi import app

client = TestClient(app)


def _fake_row(values):
    m = MagicMock()
    m.__getitem__.side_effect = lambda i: values[i]
    m.__iter__.return_value = iter(values)
    return m


class TestDealPipeline:

    def _setup_db_mock(self, mock_eng, stage="loi", notes=None):
        mock_conn = MagicMock()
        mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
        mock_eng.return_value.begin.return_value.__exit__ = MagicMock(return_value=None)
        mock_conn.execute.return_value.fetchone.side_effect = [
            ["m-uuid-1"],
            _fake_row(["d-uuid", "45/2", stage, 0.82, None, None, None, notes, None, None]),
        ]
        return mock_conn

    def test_create_deal_loi(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng:
                self._setup_db_mock(mock_eng, "loi", "test notes")
                with patch("utils.discord_notifier.send") as mock_send:
                    r = client.post("/api/deals", json={
                        "survey_no": "45/2", "market": "Devanahalli",
                        "stage": "loi", "ask_psf": 8500.0, "area_acres": 5.0, "notes": "test"
                    }, headers={"X-API-Key": "test-key"})
        assert r.status_code == 201

    def test_create_deal_signed(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng:
                self._setup_db_mock(mock_eng, "signed", "test notes")
                with patch("utils.discord_notifier.send") as mock_send:
                    r = client.post("/api/deals", json={
                        "survey_no": "45/2", "market": "Devanahalli",
                        "stage": "signed", "ask_psf": 8500.0, "area_acres": 5.0
                    }, headers={"X-API-Key": "test-key"})
        assert r.status_code == 201

    def test_deal_discord_fires_on_loi(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng:
                self._setup_db_mock(mock_eng, "loi")
                with patch("utils.discord_notifier.send") as mock_send:
                    client.post("/api/deals", json={
                        "survey_no": "45/2", "market": "Devanahalli",
                        "stage": "loi"
                    }, headers={"X-API-Key": "test-key"})
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "bd_opportunities"
        assert mock_send.call_args[0][1] == "Deal LOI: 45/2"

    def test_deal_discord_fires_on_signed(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng:
                self._setup_db_mock(mock_eng, "signed")
                with patch("utils.discord_notifier.send") as mock_send:
                    client.post("/api/deals", json={
                        "survey_no": "45/2", "market": "Devanahalli",
                        "stage": "signed"
                    }, headers={"X-API-Key": "test-key"})
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "bd_opportunities"
        assert mock_send.call_args[0][1] == "Deal SIGNED: 45/2"

    def test_patch_deal_discord_fires_on_signed(self):
        DEAL_UUID = "00000000-0000-0000-0000-000000000001"
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            with patch("dashboard.app_fastapi._get_sa_engine") as mock_eng:
                mock_conn = MagicMock()
                mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
                mock_eng.return_value.begin.return_value.__exit__ = MagicMock(return_value=None)
                existing = _fake_row([DEAL_UUID, "45/2", "prospecting", 0.82, "Devanahalli"])
                mock_conn.execute.return_value.fetchone.side_effect = [
                    existing,
                    _fake_row([DEAL_UUID, "45/2", "signed", 0.82, None, None, None, None, None, None]),
                ]
                with patch("utils.discord_notifier.send") as mock_send:
                    client.patch(f"/api/deals/{DEAL_UUID}", json={
                        "stage": "signed"
                    }, headers={"X-API-Key": "test-key"})
        mock_send.assert_called_once()
        assert mock_send.call_args[0][0] == "bd_opportunities"

    def test_deal_invalid_stage_rejected(self):
        with patch.dict("os.environ", {"DASHBOARD_API_KEY": "test-key"}):
            r = client.post("/api/deals", json={
                "survey_no": "45/2", "market": "Devanahalli",
                "stage": "invalid_stage"
            }, headers={"X-API-Key": "test-key"})
        assert r.status_code == 400
        assert "invalid stage" in r.json().get("error", "")
