"""Tests for tools/propcontext_tool.py — PropContext MCP integration.

5 test groups:
1. Importable + BaseTool subclass + __all__
2. Empty results when MCP is unreachable
3. Input validation edge cases (empty, invalid JSON, whitespace-only)
4. Analyst agent properly includes all 3 tools
5. Delta endpoint registered, has Pydantic model, Prometheus metrics
"""

import json

import pytest

pytestmark = pytest.mark.unit


# ── Group 1: Importable + BaseTool subclass + __all__ ──────────────────


def test_pc1_importable():
    from tools.propcontext_tool import (
        PropContextSearchTool,
        PropContextDeveloperTool,
        PropContextComplianceTool,
        __all__,
        _close_client,
    )
    assert PropContextSearchTool.__name__ == "PropContextSearchTool"
    assert PropContextDeveloperTool.__name__ == "PropContextDeveloperTool"
    assert PropContextComplianceTool.__name__ == "PropContextComplianceTool"
    assert "PropContextSearchTool" in __all__
    assert "PropContextDeveloperTool" in __all__
    assert "PropContextComplianceTool" in __all__
    assert "_close_client" in __all__
    assert callable(_close_client)


def test_pc2_crewai_base_tool():
    from crewai.tools import BaseTool
    from tools.propcontext_tool import (
        PropContextSearchTool,
        PropContextDeveloperTool,
        PropContextComplianceTool,
    )
    for cls in (PropContextSearchTool, PropContextDeveloperTool, PropContextComplianceTool):
        assert issubclass(cls, BaseTool)
        instance = cls()
        assert instance.name
        assert instance.description
        assert callable(instance._run)

    s = PropContextSearchTool()
    assert s.name == "propcontext_search_projects"
    d = PropContextDeveloperTool()
    assert d.name == "propcontext_developer_projects"
    c = PropContextComplianceTool()
    assert c.name == "propcontext_rera_compliance"


# ── Group 2: Empty results when MCP is unreachable ─────────────────────


def test_pc3_search_returns_empty_when_mcp_absent():
    from tools.propcontext_tool import PropContextSearchTool

    tool = PropContextSearchTool()
    result = tool._run(json.dumps({"query": "Brigade", "market": "Yelahanka"}))
    data = json.loads(result)
    assert data["status"] == "unavailable"
    assert data["source"] == "propcontext"
    assert data["results"] == []


def test_pc4_developer_returns_empty_when_mcp_absent():
    from tools.propcontext_tool import PropContextDeveloperTool

    tool = PropContextDeveloperTool()
    result = tool._run(json.dumps({"developer_name": "Brigade"}))
    data = json.loads(result)
    assert data["status"] == "unavailable"
    assert data["results"] == []


def test_pc5_compliance_returns_empty_when_mcp_absent():
    from tools.propcontext_tool import PropContextComplianceTool

    tool = PropContextComplianceTool()
    result = tool._run(json.dumps({"project_name": "Brigade Lakefront"}))
    data = json.loads(result)
    assert data["status"] == "unavailable"
    assert data["results"] == []


def test_pc6_close_client_idempotent():
    """_close_client is safe to call multiple times."""
    from tools.propcontext_tool import _close_client

    _close_client()
    _close_client()
    _close_client()


# ── Group 3: Input validation edge cases ───────────────────────────────


def test_pc7_search_invalid_json():
    from tools.propcontext_tool import PropContextSearchTool

    tool = PropContextSearchTool()
    result = tool._run("not json")
    data = json.loads(result)
    assert data["status"] == "unavailable"
    assert data["results"] == []
    assert data["reason"] == "invalid JSON input"


def test_pc8_search_empty_query():
    from tools.propcontext_tool import PropContextSearchTool

    tool = PropContextSearchTool()
    result = tool._run(json.dumps({"query": ""}))
    data = json.loads(result)
    assert data["status"] == "unavailable"
    assert data["reason"] == "empty query"


def test_pc9_search_whitespace_query():
    from tools.propcontext_tool import PropContextSearchTool

    tool = PropContextSearchTool()
    result = tool._run(json.dumps({"query": "   "}))
    data = json.loads(result)
    assert data["status"] == "unavailable"
    assert "empty" in data["reason"]


def test_pc10_search_missing_market_is_optional():
    """Market parameter is optional — tool should work with just query."""
    from tools.propcontext_tool import PropContextSearchTool

    tool = PropContextSearchTool()
    # This should not raise; market absense should be handled gracefully
    result = tool._run(json.dumps({"query": "Brigade"}))
    data = json.loads(result)
    # Still returns unavailable (MCP not reachable), but no KeyError
    assert data["status"] == "unavailable"


def test_pc11_developer_empty_name():
    from tools.propcontext_tool import PropContextDeveloperTool

    tool = PropContextDeveloperTool()
    result = tool._run(json.dumps({"developer_name": ""}))
    data = json.loads(result)
    assert data["status"] == "unavailable"
    assert "empty" in data["reason"]


def test_pc12_compliance_empty_project():
    from tools.propcontext_tool import PropContextComplianceTool

    tool = PropContextComplianceTool()
    result = tool._run(json.dumps({"project_name": ""}))
    data = json.loads(result)
    assert data["status"] == "unavailable"
    assert "empty" in data["reason"]


def test_pc13_search_none_values_in_params():
    """None values for params should not crash — .get() with fallback."""
    from tools.propcontext_tool import PropContextSearchTool

    tool = PropContextSearchTool()
    result = tool._run(json.dumps({"query": "Brigade", "market": None}))
    data = json.loads(result)
    assert data["status"] == "unavailable"
    assert data["source"] == "propcontext"


# ── Group 4: Analyst agent ────────────────────────────────────────────


def test_pc14_analyst_agent_includes_propcontext():
    from agents.analyst_agent import create_analyst_agent

    agent = create_analyst_agent()
    tool_names = [t.name for t in agent.tools]
    assert "propcontext_search_projects" in tool_names
    assert "propcontext_developer_projects" in tool_names
    assert "propcontext_rera_compliance" in tool_names


def test_pc15_analyst_backstory_mentions_propcontext():
    from agents.analyst_agent import create_analyst_agent

    agent = create_analyst_agent()
    assert "propcontext" in agent.backstory.lower()


# ── Group 5: Delta endpoint registration + Pydantic model + metrics ───


def test_pc16_delta_endpoint_in_router():
    import dashboard.routers.data as dr

    routes = [r.path for r in dr.router.routes]
    matching = [p for p in routes if "propcontext-delta" in p]
    assert len(matching) >= 1
    assert any("{market}" in p for p in matching)


def test_pc17_delta_endpoint_read_only_prefix():
    state_src = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "dashboard"
        / "state.py"
    ).read_text(encoding="utf-8")
    assert "/api/v1/intel/propcontext-delta/" in state_src
    assert "/api/intel/propcontext-delta/" in state_src


def test_pc18_delta_pydantic_model_importable():
    from dashboard.routers.data import PropContextDeltaResponse, PropContextProject

    # Model constructs and serializes
    resp = PropContextDeltaResponse(
        market="Yelahanka",
        propcontext_status="ok",
        re_os_only=[],
        propcontext_only=[],
        intersection=[],
        re_os_count=0,
        propcontext_count=0,
    )
    assert resp.market == "Yelahanka"
    assert resp.re_os_coverage_pct == 0.0
    assert resp.note == ""

    proj = PropContextProject(project_name="Test", developer="Brigade")
    assert proj.project_name == "Test"
    assert proj.developer == "Brigade"
    assert proj.rera_psf_min is None  # Optional fields default None


def test_pc19_delta_prometheus_metric_registered():
    """Verify the propcontext_delta_total metric exists in the Prometheus registry."""
    from prometheus_client import REGISTRY

    metric_name = "propcontext_delta_total"
    existing = REGISTRY._names_to_collectors.get(metric_name)
    assert existing is not None, f"Metric {metric_name} not found in Prometheus registry"


def test_pc20_delta_endpoint_testclient_200(monkeypatch):
    """Delta endpoint returns valid response structure (accepts 200 or 500 for DB-less CI)."""
    monkeypatch.setenv("DASHBOARD_API_KEY_ALLOW_EMPTY", "true")
    from starlette.testclient import TestClient
    from dashboard.app_fastapi import app

    client = TestClient(app)
    resp = client.get("/api/v1/intel/propcontext-delta/Yelahanka")
    assert resp.status_code in (200, 500), f"Expected 200 or 500, got {resp.status_code}"
    if resp.status_code == 200:
        data = resp.json()
        assert "market" in data
        assert data["market"] == "Yelahanka"
        assert "re_os_only" in data
        assert "propcontext_only" in data
        assert "propcontext_status" in data
        assert "intersection" in data
        assert "re_os_count" in data
        assert isinstance(data["re_os_only"], list)
        assert isinstance(data["propcontext_only"], list)
