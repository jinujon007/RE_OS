"""GATE-105 declaration — Observability: Grafana + Alerting Rules (Sprint 105).

5 assertions:
(1) docker-compose.yml contains 're_os_grafana' service.
(2) prometheus/alerts.yml exists with >=5 alert rules using existing metrics.
(3) grafana/dashboards/pipeline_health.json parseable.
(4) GET /api/v1/ops/slo returns 200 with scheduler_slo key (mocked DB).
(5) AlertSuppressor.suppress('TEST', cooldown_hours=1) returns False on first call.
"""
import os
import pytest
import json
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit
os.environ.setdefault("DASHBOARD_API_KEY", "test-key")

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestGate105:
    def test_docker_compose_has_grafana_service(self):
        dc = REPO_ROOT / "docker-compose.yml"
        content = dc.read_text(encoding="utf-8")
        assert "re_os_grafana" in content

    def test_prometheus_alerts_file_exists_with_5_rules(self):
        alerts = REPO_ROOT / "prometheus" / "alerts.yml"
        assert alerts.exists()
        content = alerts.read_text(encoding="utf-8")
        alert_names = re.findall(r"alert:\s*(\w+)", content)
        assert len(alert_names) >= 5, f"Found {len(alert_names)} alert rules, need >=5"
        for name in alert_names:
            assert name[0].isupper(), f"Alert name '{name}' should be PascalCase"

    def test_grafana_dashboard_json_parseable(self):
        dashboard = REPO_ROOT / "config" / "grafana" / "provisioning" / "dashboards" / "pipeline_health.json"
        assert dashboard.exists()
        data = json.loads(dashboard.read_text(encoding="utf-8"))
        assert "title" in data
        assert "panels" in data
        assert len(data["panels"]) >= 3

    def test_slo_endpoint_returns_200_with_slo_key(self):
        from starlette.testclient import TestClient
        from dashboard.app_fastapi import app
        client = TestClient(app)
        with patch("dashboard.routers.ops._get_sa_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = (100, 95)
            mock_conn.execute.return_value.fetchall.return_value = [(30.0,), (45.0,)]
            resp = client.get("/api/v1/ops/slo", headers={"X-API-Key": "test-key"})
            assert resp.status_code == 200
            data = resp.json()
            assert "scheduler_slo" in data

    def test_alert_suppressor_first_fire_returns_false(self):
        from utils.discord_notifier import AlertSuppressor
        AlertSuppressor._IN_MEMORY.clear()
        with patch("utils.db.get_engine") as mock_eng:
            mock_conn = MagicMock()
            mock_eng.return_value.connect.return_value.__enter__.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = None
            result = AlertSuppressor.suppress("TEST_SUPPRESS", cooldown_hours=1)
            assert result is False

    def test_alert_suppressor_wired_into_send_ops_alert(self):
        from utils.discord_notifier import send_ops_alert, AlertSuppressor
        AlertSuppressor._IN_MEMORY.clear()
        with patch("utils.discord_notifier.AlertSuppressor.suppress") as mock_suppress:
            mock_suppress.return_value = True
            with patch("utils.db.get_engine") as mock_eng:
                mock_conn = MagicMock()
                mock_eng.return_value.begin.return_value.__enter__.return_value = mock_conn
                result = send_ops_alert("TEST_FIRE", "test detail")
                mock_suppress.assert_called_once()
                assert result is False

    def test_all_grafana_dashboards_have_panels(self):
        names = ["pipeline_health.json", "intelligence_quality.json", "system_health.json"]
        for name in names:
            path = REPO_ROOT / "config" / "grafana" / "provisioning" / "dashboards" / name
            assert path.exists(), f"Missing dashboard: {name}"
            data = json.loads(path.read_text(encoding="utf-8"))
            assert len(data.get("panels", [])) >= 3, f"Too few panels in {name}: {len(data.get('panels', []))}"

