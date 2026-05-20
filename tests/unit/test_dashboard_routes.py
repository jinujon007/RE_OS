import io
import sys
import types
from unittest.mock import patch

import pytest

pytest.importorskip("flask")

if "psycopg2" not in sys.modules:
    sys.modules["psycopg2"] = types.ModuleType("psycopg2")

import dashboard.app as dashboard_app


def _client():
    dashboard_app.app.config["TESTING"] = True
    return dashboard_app.app.test_client()


def test_reports_rejects_path_traversal_market():
    client = _client()
    resp = client.get("/api/reports/../../etc/passwd")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid market"


def test_reports_rejects_all_market():
    client = _client()
    resp = client.get("/api/reports/all")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid market"


def test_reports_uses_canonical_slug_not_raw_path():
    client = _client()
    captured = {}

    def fake_glob(pattern):
        captured["pattern"] = pattern
        return ["/app/outputs/yelahanka/intel_report_20260101_0000.txt"]

    with (
        patch("dashboard.app.glob.glob", side_effect=fake_glob),
        patch("builtins.open", return_value=io.StringIO("ok-report")),
    ):
        resp = client.get("/api/reports/YeLaHaNkA")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["content"] == "ok-report"
    assert body["file"] == "intel_report_20260101_0000.txt"
    assert captured["pattern"] == "/app/outputs/yelahanka/intel_report_*.txt"


def test_run_invalid_market_returns_400():
    client = _client()
    resp = client.post("/api/run/atlantis")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid market"


def test_run_valid_market_starts():
    client = _client()
    with patch("dashboard.app.subprocess.Popen") as mock_popen:
        mock_proc = mock_popen.return_value
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        resp = client.post("/api/run/Yelahanka")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] in {"started", "already_running"}
    assert body["market"] == "Yelahanka"


def test_run_requires_api_key_when_configured_rejects_missing_key(monkeypatch):
    client = _client()
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret123")
    resp = client.post("/api/run/Yelahanka")
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "unauthorized"


def test_run_requires_api_key_when_configured_accepts_header_key(monkeypatch):
    client = _client()
    monkeypatch.setenv("DASHBOARD_API_KEY", "secret123")
    with patch("dashboard.app.subprocess.Popen") as mock_popen:
        mock_proc = mock_popen.return_value
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        resp = client.post("/api/run/Yelahanka", headers={"X-API-Key": "secret123"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] in {"started", "already_running"}
    assert body["market"] == "Yelahanka"


def test_unknown_agent_command_returns_404():
    client = _client()
    resp = client.post(
        "/api/agents/does_not_exist/command",
        json={"prompt": "run Yelahanka"},
        content_type="application/json",
    )
    assert resp.status_code == 404


def test_health_returns_200():
    client = _client()
    with patch("dashboard.app._get_db", side_effect=Exception("no db in test")):
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "agents" in body
    assert body["agents"] == "ok"
    assert "last_run" in body  # field always present (None when DB unreachable)


def test_health_last_run_populated_from_db():
    """When DB is reachable and agent_runs has rows, last_run is populated."""
    import sys
    import types
    from datetime import datetime
    from unittest.mock import MagicMock

    client = _client()

    fake_conn = MagicMock()
    fake_cur = MagicMock()
    fake_conn.cursor.return_value = fake_cur
    ts = datetime(2026, 5, 20, 2, 30, 0)
    # postgres check: _get_db() + _release_db() only — no cursor/fetchone
    # last_run query: cursor + execute + fetchone (one call)
    fake_cur.fetchone.return_value = ("Yelahanka", "success", ts, 182)

    # redis and httpx are imported locally inside health() — patch at sys.modules level
    fake_redis_mod = types.ModuleType("redis")
    fake_redis_instance = MagicMock()
    fake_redis_instance.ping.return_value = True
    fake_redis_mod.from_url = MagicMock(return_value=fake_redis_instance)

    fake_httpx_mod = types.ModuleType("httpx")
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_httpx_mod.get = MagicMock(return_value=fake_response)

    with (
        patch("dashboard.app._get_db", return_value=fake_conn),
        patch("dashboard.app._release_db"),
        patch.dict(sys.modules, {"redis": fake_redis_mod, "httpx": fake_httpx_mod}),
    ):
        resp = client.get("/api/health")

    assert resp.status_code == 200
    body = resp.get_json()
    last = body.get("last_run")
    assert last is not None
    assert last["market"] == "Yelahanka"
    assert last["status"] == "success"
    assert last["duration_seconds"] == 182


def test_metrics_endpoint_exposes_prometheus_payload():
    client = _client()
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in (resp.headers.get("Content-Type") or "")
    body = resp.get_data(as_text=True)
    assert "pipeline_runs_total" in body
