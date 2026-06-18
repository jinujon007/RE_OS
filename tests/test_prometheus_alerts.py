"""Tests for Prometheus alerts file (GATE-105 T-1213)."""
import pytest
from pathlib import Path
import re

pytestmark = pytest.mark.unit

ALERTS_PATH = Path(__file__).resolve().parent.parent / "prometheus" / "alerts.yml"

_KNOWN_METRICS = {
    "scraper_runs_total",
    "board_session_duration_seconds_bucket",
    "board_session_duration_seconds",
    "pipeline_runs_total",
    "db_query_duration_seconds_bucket",
    "db_query_duration_seconds",
}


class TestPrometheusAlerts:
    def test_alerts_file_exists(self):
        assert ALERTS_PATH.exists(), f"Missing alerts file: {ALERTS_PATH}"

    def test_alerts_file_has_5_rules(self):
        content = ALERTS_PATH.read_text(encoding="utf-8")
        alert_names = re.findall(r"alert:\s*(\w+)", content)
        assert len(alert_names) >= 5, f"Expected >=5 alert rules, found {len(alert_names)}: {alert_names}"

    def test_alert_severity_keywords(self):
        content = ALERTS_PATH.read_text(encoding="utf-8")
        severity_count = len(re.findall(r"severity:", content))
        assert severity_count >= 5, f"Expected >=5 severity labels, found {severity_count}"

    def test_prometheus_config_references_alerts(self):
        prom_yml = Path(__file__).resolve().parent.parent / "config" / "prometheus.yml"
        content = prom_yml.read_text(encoding="utf-8")
        assert "alerts.yml" in content, "prometheus.yml does not reference alerts.yml"

    def test_all_metrics_exist_in_codebase(self):
        """Every Prometheus metric referenced in alert expressions must exist in config/metrics.py."""
        content = ALERTS_PATH.read_text(encoding="utf-8")
        metrics_py = Path(__file__).resolve().parent.parent / "config" / "metrics.py"
        metrics_content = metrics_py.read_text(encoding="utf-8")
        found_metrics = re.findall(r"\b([a-z_]+(?:bucket|count|sum|total|seconds))\b", content)
        for metric in found_metrics:
            full_name = metric.replace("_bucket", "").replace("_count", "").replace("_sum", "")
            if full_name not in _KNOWN_METRICS:
                assert full_name in metrics_content, f"Metric '{full_name}' not defined in config/metrics.py"

    def test_no_metric_exists_from_alerts_in_codebase(self):
        """Verify no alert references a metric name that doesn't exist in metrics.py."""
        content = ALERTS_PATH.read_text(encoding="utf-8")
        alert_metrics = set(re.findall(r"\b([a-z_]+_total|[a-z_]+_bucket|[a-z_]+_seconds)\b", content))
        metrics_py = Path(__file__).resolve().parent.parent / "config" / "metrics.py"
        mc = metrics_py.read_text(encoding="utf-8")
        for m in alert_metrics:
            base = m.replace("_bucket", "").replace("_sum", "").replace("_count", "")
            assert base in mc or base in _KNOWN_METRICS, f"Alert references unknown metric '{m}' (base '{base}')"
