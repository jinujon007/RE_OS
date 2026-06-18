"""Tests for T-1282: Grafana Prometheus datasource provisioning (R2)."""

import yaml
import pytest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent

DOCKER_COMPOSE = REPO_ROOT / "docker-compose.yml"
DATASOURCE_YAML = (
    REPO_ROOT / "config" / "grafana" / "provisioning" / "datasources" / "datasource.yml"
)


def test_grafana_datasource_yaml_exists():
    assert DATASOURCE_YAML.exists(), f"Missing: {DATASOURCE_YAML}"


def test_grafana_datasource_prometheus_url_matches_docker_compose():
    assert DATASOURCE_YAML.exists()
    with open(str(DATASOURCE_YAML), "r") as f:
        ds_cfg = yaml.safe_load(f)
    assert ds_cfg is not None, "YAML is empty"
    prometheus = None
    for ds in ds_cfg.get("datasources", []):
        if ds.get("type") == "prometheus":
            prometheus = ds
            break
    assert prometheus is not None, "No Prometheus datasource"
    assert prometheus.get("type") == "prometheus"
    assert "re_os_prometheus" in prometheus.get("url", ""), (
        f"URL '{prometheus.get('url')}' missing 're_os_prometheus'"
    )
    assert prometheus.get("access") == "proxy", "Datasource access must be 'proxy'"
    assert prometheus.get("isDefault") is True, "Datasource must be isDefault=true"
    # Verify docker-compose.yml Prometheus service name
    with open(str(DOCKER_COMPOSE), "r") as f:
        compose = yaml.safe_load(f)
    svc = compose.get("services", {}).get("prometheus", {})
    assert svc.get("container_name") == "re_os_prometheus", (
        f"Expected re_os_prometheus, got '{svc.get('container_name')}'"
    )


def test_grafana_volume_mount_exists():
    """Verify Grafana service has the provisioning volume mount."""
    with open(str(DOCKER_COMPOSE), "r") as f:
        compose = yaml.safe_load(f)
    grafana = compose.get("services", {}).get("grafana", {})
    volumes = grafana.get("volumes", [])
    provisioning_mount = any(
        "config/grafana/provisioning" in v and "/etc/grafana/provisioning" in v
        for v in volumes
    )
    assert provisioning_mount, (
        f"Grafana volumes {volumes} missing provisioning mount: "
        f"'./config/grafana/provisioning:/etc/grafana/provisioning'"
    )
