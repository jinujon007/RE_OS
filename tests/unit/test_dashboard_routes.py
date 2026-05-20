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
