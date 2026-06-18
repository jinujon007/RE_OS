"""Tests for 3-tier API key RBAC — T-1223."""

import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_keys():
    from dashboard import state as _st
    _st._API_KEY = None
    _st._API_KEY_READ = None
    _st._API_KEY_ADMIN = None
    yield


def _client():
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app
    return TestClient(app, raise_server_exceptions=False)


def _make_env(w="w", r="r", a="a", allow=""):
    return {"DASHBOARD_API_KEY": w, "DASHBOARD_API_KEY_READ": r,
            "DASHBOARD_API_KEY_ADMIN": a, "DASHBOARD_API_KEY_ALLOW_EMPTY": allow}


def _env_patch(env):
    return patch.object(os.environ, "get",
                        side_effect=lambda k, d=None: env.get(k, d or ""))


def _reset_globals():
    from dashboard import state as _st
    _st._API_KEY = None
    _st._API_KEY_READ = None
    _st._API_KEY_ADMIN = None


def _scope(method, path, key_val=None):
    hdrs = [(b"x-api-key", key_val.encode())] if key_val else []
    return {"type": "http", "method": method, "path": path,
            "headers": hdrs, "query_string": b"",
            "server": ("test", 80), "client": ("test", 1), "scheme": "http"}


def test_role_read():
    from dashboard.state import _get_request_role, _has_role
    from fastapi import Request
    with _env_patch(_make_env()):
        _reset_globals()
        role = _get_request_role(Request(_scope("GET", "/api/v1/health/live", "r")))
    assert role == "read"
    assert _has_role(role, "read") is True
    assert _has_role(role, "write") is False


def test_role_write():
    from dashboard.state import _get_request_role, _has_role
    from fastapi import Request
    with _env_patch(_make_env()):
        _reset_globals()
        role = _get_request_role(Request(_scope("POST", "/api/v1/evaluate", "w")))
    assert role == "write"
    assert _has_role(role, "read") is True
    assert _has_role(role, "write") is True
    assert _has_role(role, "admin") is False


def test_role_admin():
    from dashboard.state import _get_request_role, _has_role
    from fastapi import Request
    with _env_patch(_make_env()):
        _reset_globals()
        role = _get_request_role(Request(_scope("GET", "/api/v1/ops/kill-criteria", "a")))
    assert role == "admin"
    assert _has_role(role, "admin") is True


def test_role_none():
    from dashboard.state import _get_request_role
    from fastapi import Request
    with _env_patch(_make_env()):
        _reset_globals()
        role = _get_request_role(Request(_scope("POST", "/api/v1/evaluate")))
    assert role is None


def test_role_admin_dev_mode():
    from dashboard.state import _get_request_role
    from fastapi import Request
    with _env_patch(_make_env(w="", r="", a="", allow="true")):
        _reset_globals()
        role = _get_request_role(Request(_scope("GET", "/api/v1/health/live")))
    assert role == "admin"


def test_middleware_401():
    client = _client()
    with _env_patch(_make_env(w="secret")), patch("dashboard.app_fastapi._write_audit_log"):
        resp = client.post("/api/v1/evaluate", json={})
    assert resp.status_code == 401


def test_middleware_403_read_to_admin():
    client = _client()
    with _env_patch(_make_env()), patch("dashboard.app_fastapi._write_audit_log"):
        resp = client.get("/api/v1/ops/kill-criteria", headers={"X-API-Key": "r"})
    assert resp.status_code == 403


def test_middleware_403_write_to_admin():
    client = _client()
    with _env_patch(_make_env()), patch("dashboard.app_fastapi._write_audit_log"):
        resp = client.get("/api/v1/ops/kill-criteria", headers={"X-API-Key": "w"})
    assert resp.status_code == 403


def test_middleware_200_health_read():
    client = _client()
    with _env_patch(_make_env()), patch("dashboard.app_fastapi._write_audit_log"):
        resp = client.get("/api/v1/health/live", headers={"X-API-Key": "r"})
    assert resp.status_code == 200


def test_options_passthrough():
    """OPTIONS requests bypass auth unconditionally (route may still 405)."""
    client = _client()
    with _env_patch(_make_env()):
        resp = client.options("/api/v1/health")
    assert resp.status_code not in (401, 403)


def test_metrics_passthrough():
    """/metrics endpoint bypasses auth."""
    client = _client()
    with _env_patch(_make_env()):
        resp = client.get("/metrics")
    assert resp.status_code in (200, 404)


def test_legacy_telegram_reachable():
    """v1 telegram webhook is reachable without API key (should NOT 401/403)."""
    client = _client()
    import config.settings as _cfg
    with _env_patch(_make_env(w="secret")), \
         patch("dashboard.routers.ops._send_telegram_message"), \
         patch.object(_cfg, "TELEGRAM_WEBHOOK_SECRET", ""):
        resp = client.post("/api/v1/telegram/webhook", json={"message": {"text": "test",
                           "chat": {"id": 1}}})
    assert resp.status_code not in (401, 403)


def test_write_key_on_write_path():
    """Write key → 200 on write path."""
    client = _client()
    with _env_patch(_make_env()), patch("dashboard.app_fastapi._write_audit_log"):
        resp = client.post("/api/v1/board/session", json={},
                           headers={"X-API-Key": "w"})
    assert resp.status_code not in (401, 403)


def test_prev_key_backward_compat():
    """DASHBOARD_API_KEY_PREV still works via _is_run_api_authorized."""
    from dashboard.state import _is_run_api_authorized
    from fastapi import Request
    from unittest.mock import patch as _patch
    import os as _os
    env = {"DASHBOARD_API_KEY": "new-key", "DASHBOARD_API_KEY_PREV": "old-key",
           "DASHBOARD_API_KEY_READ": "r", "DASHBOARD_API_KEY_ADMIN": "a",
           "DASHBOARD_API_KEY_ALLOW_EMPTY": ""}
    with _patch.object(_os.environ, "get", side_effect=lambda k, d=None: env.get(k, d or "")):
        from dashboard import state as _st
        _st._API_KEY = None
        _st._API_KEY_READ = None
        _st._API_KEY_ADMIN = None
        scope = {"type": "http", "method": "POST", "path": "/api/v1/evaluate",
                 "headers": [(b"x-api-key", b"old-key")],
                 "query_string": b"", "server": ("test", 80), "client": ("test", 1),
                 "scheme": "http"}
        result = _is_run_api_authorized(Request(scope))
    assert result is True
