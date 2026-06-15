"""T-1124: Board Room response time logging (R9) — unit tests."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit


def test_board_pitch_response_includes_timing():
    """Assert POST /api/board/session response contains response_time_s key."""
    import os

    os.environ["REDIS_URL"] = "memory://"

    import sys

    if "dashboard.app_fastapi" in sys.modules:
        import importlib
        import dashboard.app_fastapi  # noqa: F811

        importlib.reload(dashboard.app_fastapi)

    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)

    with patch("crews.board_room.run_board_session") as mock_run:
        mock_run.return_value = {
            "session_id": "test-session-id",
            "status": "pending",
            "market": "Yelahanka",
            "message": "Session created",
        }
        resp = client.post(
            "/api/board/session",
            json={"pitch": "5-acre site at Yelahanka", "market": "Yelahanka"},
            headers={"X-API-Key": "test-api-key"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "response_time_s" in data
    assert isinstance(data["response_time_s"], (int, float))
    assert data["response_time_s"] >= 0, (
        f"response_time_s must be non-negative, got {data['response_time_s']}"
    )


def test_board_session_timing_migration_column_present():
    """Assert migration 0052 defines response_time_s column."""
    with open("alembic/versions/0052_board_session_timing.py") as f:
        content = f.read()
    assert "response_time_s" in content
    assert "sa.Column" in content
    assert "board_sessions" in content
