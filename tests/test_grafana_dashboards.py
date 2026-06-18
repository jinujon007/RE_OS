"""Tests for Grafana dashboard JSON files (GATE-105 T-1214)."""
import pytest
import json
from pathlib import Path

pytestmark = pytest.mark.unit

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "config" / "grafana" / "provisioning" / "dashboards"
DASHBOARD_NAMES = ["pipeline_health.json", "intelligence_quality.json", "system_health.json"]


class TestGrafanaDashboards:
    def test_dashboard_files_exist(self):
        for name in DASHBOARD_NAMES:
            assert (DASHBOARD_DIR / name).exists(), f"Missing dashboard: {name}"

    def test_dashboards_are_valid_json_with_required_fields(self):
        for name in DASHBOARD_NAMES:
            content = (DASHBOARD_DIR / name).read_text(encoding="utf-8")
            data = json.loads(content)
            assert "title" in data, f"Missing title in {name}"
            assert "panels" in data, f"Missing panels in {name}"
            assert len(data["panels"]) >= 3, f"Too few panels in {name}: {len(data['panels'])}"
            assert "uid" in data, f"Missing uid in {name}"
            assert "schemaVersion" in data, f"Missing schemaVersion in {name}"

    def test_dashboards_have_tags_and_description(self):
        for name in DASHBOARD_NAMES:
            data = json.loads((DASHBOARD_DIR / name).read_text(encoding="utf-8"))
            assert "tags" in data and len(data["tags"]) >= 1, f"Missing tags in {name}"
            assert "description" in data and data["description"], f"Missing description in {name}"

    def test_dashboard_panels_have_targets(self):
        for name in DASHBOARD_NAMES:
            data = json.loads((DASHBOARD_DIR / name).read_text(encoding="utf-8"))
            for i, panel in enumerate(data["panels"]):
                assert "targets" in panel, f"Panel {i} in {name} missing targets"
                assert len(panel["targets"]) > 0, f"Panel {i} in {name} has empty targets"
                assert "expr" in panel["targets"][0], f"Panel {i} in {name} first target missing expr"
                assert "datasource" in panel, f"Panel {i} in {name} missing datasource"
