"""GATE-60 declaration — QLoRA RERA extractor + Telegram webhook live."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


def test_gate60_rera_extractor_regex_fallback():
    from utils.rera_extractor import RERAExtractor

    ext = RERAExtractor()
    ext._model_available = False
    ext._model_last_check = 0
    text = (
        "Project: Green Valley Enclave\n"
        "Developer: Brigade Group\n"
        "RERA No: PR/KA/RERA/123/456/2024\n"
        "Total Units: 120\n"
        "Launch Date: 2024-01-15\n"
        "Completion Date: 2025-12-31\n"
        "Status: On-Going\n"
        "Market: Yelahanka"
    )
    result = ext.extract(text)
    assert result["project_name"] == "Green Valley Enclave"
    assert result["developer_name"] == "Brigade Group"
    assert result["survey_no"] == "PR/KA/RERA/123/456/2024"
    assert result["units"] == 120
    assert result["status"] == "On-Going"
    assert result["market"] == "Yelahanka"


def test_gate60_rera_extractor_empty_input():
    from utils.rera_extractor import RERAExtractor

    ext = RERAExtractor()
    ext._model_available = False
    result = ext.extract("")
    assert result["project_name"] == ""
    assert result["units"] == 0


def test_gate60_training_data_generates_jsonl():
    mock_rows = [
        MagicMock(
            project_name=f"Project {i}",
            developer_name="Brigade",
            rera_number=f"RERA/{i:03d}",
            total_units=100 + i,
            launch_date="2024-01-15",
            completion_date="2025-12-31",
            status="On-Going",
            market="Yelahanka",
        )
        for i in range(150)
    ]
    with patch("utils.db.get_engine") as mock_engine:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = mock_rows
        mock_engine.return_value.connect.return_value.__enter__.return_value = mock_conn
        from scripts.generate_rera_training_data import generate_training_data

        records = generate_training_data("Yelahanka")
        assert len(records) >= 100


def test_gate60_telegram_webhook_returns_200():
    import config.settings as _cfg
    from fastapi.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app, raise_server_exceptions=False)
    update = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "text": "Yelahanka 2 acres compare",
            "chat": {"id": 12345, "type": "private"},
            "from": {"id": 12345, "first_name": "Test"},
        },
    }
    with (
        patch.object(_cfg, "TELEGRAM_WEBHOOK_SECRET", "test_secret_123"),
        patch("dashboard.app_fastapi._send_telegram_message"),
    ):
        resp = client.post(
            "/api/telegram/webhook",
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "test_secret_123"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
