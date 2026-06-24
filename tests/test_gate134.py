"""GATE-134 — PropContext: Cross-Reference RERA Data Quality.

5 assertions (all code-verifiable without Docker):
A1: PropContextSearchTool importable; _run returns dict with status key
A2: All 3 PropContext tools return status='unavailable' when MCP absent
A3: Analyst agent tool list includes all 3 propcontext tools + backstory
A4: PropContextDeltaResponse model has re_os_only + propcontext_only keys
A5: propcontext-delta route in data router + _READ_ONLY_PREFIXES +
    Prometheus metric registered
"""

import json
import pathlib

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_gate134_a1_importable():
    from tools.propcontext_tool import (
        PropContextSearchTool,
        PropContextDeveloperTool,
        PropContextComplianceTool,
        __all__,
        _close_client,
    )
    assert callable(PropContextSearchTool)
    assert callable(PropContextDeveloperTool)
    assert callable(PropContextComplianceTool)
    assert callable(_close_client)
    assert "PropContextSearchTool" in __all__

    s = PropContextSearchTool()
    assert s.name == "propcontext_search_projects"
    assert callable(s._run)


def test_gate134_a2_graceful_absent():
    from tools.propcontext_tool import (
        PropContextSearchTool,
        PropContextDeveloperTool,
        PropContextComplianceTool,
    )

    for tool_cls, payload in [
        (PropContextSearchTool, {"query": "Brigade", "market": "Yelahanka"}),
        (PropContextDeveloperTool, {"developer_name": "Brigade"}),
        (PropContextComplianceTool, {"project_name": "Brigade Lakefront"}),
    ]:
        tool = tool_cls()
        result = tool._run(json.dumps(payload))
        data = json.loads(result)
        assert data["status"] == "unavailable", (
            f"{tool_cls.__name__}: expected unavailable, got {data['status']}"
        )
        assert data["results"] == [], f"{tool_cls.__name__}: expected empty results"
        assert data["source"] == "propcontext"


def test_gate134_a3_analyst_integration():
    from agents.analyst_agent import create_analyst_agent

    agent = create_analyst_agent()
    tool_names = [t.name for t in agent.tools]
    for name in (
        "propcontext_search_projects",
        "propcontext_developer_projects",
        "propcontext_rera_compliance",
    ):
        assert name in tool_names, f"Analyst agent missing tool: {name}"

    assert "propcontext" in agent.backstory.lower(), (
        "Analyst agent backstory must reference PropContext tools"
    )


def test_gate134_a4_delta_model_keys():
    from dashboard.routers.data import PropContextDeltaResponse

    resp = PropContextDeltaResponse(
        market="Yelahanka",
        propcontext_status="ok",
        re_os_only=[],
        propcontext_only=[],
        intersection=[],
        re_os_count=0,
        propcontext_count=0,
    )
    model = resp.model_dump()
    assert "re_os_only" in model
    assert "propcontext_only" in model
    assert "intersection" in model
    assert "market" in model
    assert "propcontext_status" in model
    assert "re_os_count" in model
    assert "intersection_count" in model
    assert "re_os_coverage_pct" in model

    # Verify default values
    assert resp.re_os_coverage_pct == 0.0
    assert resp.intersection_count == 0


def test_gate134_a5_routes_and_metrics():
    """Check route registration + read-only prefix + Prometheus metric."""
    router_src = (REPO_ROOT / "dashboard" / "routers" / "data.py").read_text(encoding="utf-8")
    assert "propcontext-delta" in router_src, "data.py missing propcontext-delta route"

    state_src = (REPO_ROOT / "dashboard" / "state.py").read_text(encoding="utf-8")
    assert "/api/v1/intel/propcontext-delta/" in state_src, "state.py missing v1 prefix"
    assert "/api/intel/propcontext-delta/" in state_src, "state.py missing legacy prefix"

    from prometheus_client import REGISTRY

    # Counter metric name registered as "propcontext_delta"
    # (Prometheus appends _total at exposition time, but the canonical name
    # is stored without the suffix in the Counter constructor)
    metric_name = "propcontext_delta"
    metric = REGISTRY._names_to_collectors.get(metric_name)
    assert metric is not None, f"Prometheus metric '{metric_name}' not registered"
    assert metric._name == metric_name
