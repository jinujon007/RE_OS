"""GATE-107 declaration — Security: RBAC + Audit Log + Webhook Verification.

5 assertions:
1. DASHBOARD_API_KEY_READ appears in dashboard/state.py
2. api_audit_log migration file exists under alembic/versions/
3. /api/telegram/webhook handler contains TELEGRAM_WEBHOOK_SECRET check string
4. .secrets.baseline file exists
5. Read key returns 403 on /api/v1/board/session (mocked auth check)
"""

import os


def test_gate107_dashboard_state_has_read_key():
    """Assert DASHBOARD_API_KEY_READ in dashboard/state.py."""
    path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "state.py")
    with open(path) as f:
        content = f.read()
    assert "DASHBOARD_API_KEY_READ" in content


def test_gate107_audit_log_migration_exists():
    """Assert api_audit_log migration file exists."""
    path = os.path.join(os.path.dirname(__file__), "..", "alembic", "versions",
                        "0063_api_audit_log.py")
    assert os.path.exists(path)


def test_gate107_telegram_webhook_hmac_check():
    """Assert telegram webhook handler contains TELEGRAM_WEBHOOK_SECRET check."""
    path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "routers", "ops.py")
    with open(path) as f:
        content = f.read()
    assert "TELEGRAM_WEBHOOK_SECRET" in content
    assert "hmac.compare_digest" in content


def test_gate107_secrets_baseline_exists():
    """Assert .secrets.baseline file exists."""
    path = os.path.join(os.path.dirname(__file__), "..", ".secrets.baseline")
    assert os.path.exists(path)
    assert os.path.getsize(path) > 0


def test_gate107_read_key_rejected_on_mutating_endpoint():
    """Read key → 403 on /api/v1/board/session (mutating endpoint)."""
    from dashboard import state as _st
    _st._API_KEY = None
    _st._API_KEY_READ = None
    _st._API_KEY_ADMIN = None
    from fastapi.testclient import TestClient
    from dashboard.app_fastapi import app
    client = TestClient(app, raise_server_exceptions=False)
    import os as _os
    from unittest.mock import patch
    with (
        patch.object(_os.environ, "get", side_effect=lambda k, d=None: {
            "DASHBOARD_API_KEY": "write-key",
            "DASHBOARD_API_KEY_READ": "read-key",
            "DASHBOARD_API_KEY_ADMIN": "admin-key",
            "DASHBOARD_API_KEY_ALLOW_EMPTY": "",
        }.get(k, d or "")),
    ):
        resp = client.post("/api/v1/board/session", json={}, headers={"X-API-Key": "read-key"})
    assert resp.status_code == 403
    body = resp.json()
    assert body["required"] in ("write", "admin")
