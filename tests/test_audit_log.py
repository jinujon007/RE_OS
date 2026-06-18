"""Tests for API audit log — T-1224."""

from unittest.mock import patch, MagicMock


def _client():
    from fastapi.testclient import TestClient
    from dashboard.app_fastapi import app
    return TestClient(app, raise_server_exceptions=False)


def test_audit_log_migration_creates_table():
    """Assert migration 0063 creates api_audit_log table."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions",
                        "0063_api_audit_log.py")
    assert os.path.exists(path), "Migration 0063 file not found"
    with open(path) as f:
        content = f.read()
    assert "api_audit_log" in content
    assert "create_table" in content


def test_authenticated_request_logged():
    """Authenticated request (write key) → audit row written."""
    from dashboard import state as _st
    _st._API_KEY = None
    _st._API_KEY_READ = None
    _st._API_KEY_ADMIN = None
    write_mock = MagicMock()
    client = _client()
    import os as _os
    with (
        patch.object(_os.environ, "get", side_effect=lambda k, d=None: {
            "DASHBOARD_API_KEY": "write-key",
            "DASHBOARD_API_KEY_READ": "read-key",
            "DASHBOARD_API_KEY_ADMIN": "admin-key",
            "DASHBOARD_API_KEY_ALLOW_EMPTY": "",
        }.get(k, d or "")),
        patch("dashboard.app_fastapi._write_audit_log", write_mock),
    ):
        client.get("/api/v1/health/live", headers={"X-API-Key": "read-key"})
    write_mock.assert_called_once()


def test_unauthenticated_request_not_logged():
    """No auth header → no audit row (role is None, middleware skips)."""
    from dashboard import state as _st
    _st._API_KEY = None
    _st._API_KEY_READ = None
    _st._API_KEY_ADMIN = None
    write_mock = MagicMock()
    client = _client()
    import os as _os
    with (
        patch.object(_os.environ, "get", side_effect=lambda k, d=None: {
            "DASHBOARD_API_KEY": "write-key",
            "DASHBOARD_API_KEY_READ": "read-key",
            "DASHBOARD_API_KEY_ADMIN": "admin-key",
            "DASHBOARD_API_KEY_ALLOW_EMPTY": "",
        }.get(k, d or "")),
        patch("dashboard.app_fastapi._write_audit_log", write_mock),
    ):
        client.get("/api/v1/health/live")
    write_mock.assert_not_called()


def test_audit_log_endpoint_requires_admin():
    """Audit log endpoint returns 403 for read key (mock role check)."""
    from dashboard import state as _st
    _st._API_KEY = None
    _st._API_KEY_READ = None
    _st._API_KEY_ADMIN = None
    client = _client()
    import os as _os
    with (
        patch.object(_os.environ, "get", side_effect=lambda k, d=None: {
            "DASHBOARD_API_KEY": "write-key",
            "DASHBOARD_API_KEY_READ": "read-key",
            "DASHBOARD_API_KEY_ADMIN": "admin-key",
            "DASHBOARD_API_KEY_ALLOW_EMPTY": "",
        }.get(k, d or "")),
    ):
        resp = client.get("/api/v1/audit/log", headers={"X-API-Key": "read-key"})
    assert resp.status_code == 403
