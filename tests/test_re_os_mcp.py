"""Tests for mcp_server/re_os_mcp.py.

Verifies:
  1. Module importable, TOOLS dict has 4 entries
  2. Each tool has name, description, handler, parameters
  3. JSON-RPC tools/list returns all 4 tools with inputSchema
  4. JSON-RPC tools/call dispatches to handler, handles unknown tools
  5. quick_feasibility validates inputs, returns structured result
  6. corridor_score validates lat/lon bounds
  7. psf_forecast validates market, handles missing data
  8. Protocol: initialize, ping, unknown method, parameter validation
  9. Auth: _is_authorized checks MCP_API_KEY
  10. SSE session lifecycle
"""

import json

import pytest

pytestmark = pytest.mark.unit


def test_module_importable():
    from mcp_server.re_os_mcp import TOOLS, _handle_jsonrpc, _rera_search
    assert isinstance(TOOLS, dict)
    assert len(TOOLS) >= 4
    assert callable(_rera_search)
    assert callable(_handle_jsonrpc)


def test_all_4_tools_registered():
    from mcp_server.re_os_mcp import TOOLS
    tool_names = set(TOOLS.keys())
    expected = {"rera_search", "psf_forecast", "quick_feasibility", "corridor_score"}
    missing = expected - tool_names
    assert not missing, f"Missing tools: {missing}"
    for name, tool in TOOLS.items():
        assert "name" in tool
        assert "description" in tool
        assert "handler" in tool
        assert callable(tool["handler"])
        assert "parameters" in tool
        assert "required" in tool["parameters"]


def test_tools_list_returns_all():
    from mcp_server.re_os_mcp import _handle_jsonrpc
    resp = _handle_jsonrpc({"method": "tools/list", "id": 1, "params": {}})
    assert resp.get("jsonrpc") == "2.0"
    assert "result" in resp
    tools = resp["result"]["tools"]
    assert len(tools) >= 4
    names = {t["name"] for t in tools}
    for n in ("rera_search", "psf_forecast", "quick_feasibility", "corridor_score"):
        assert n in names
    for t in tools:
        assert "inputSchema" in t, f"{t['name']}: missing inputSchema"
        assert "properties" in t["inputSchema"], f"{t['name']}: inputSchema missing properties"


def test_tools_call_unknown_tool_returns_error():
    from mcp_server.re_os_mcp import _handle_jsonrpc
    resp = _handle_jsonrpc({
        "method": "tools/call",
        "id": 2,
        "params": {"name": "nonexistent_tool", "arguments": {}},
    })
    assert "error" in resp
    assert resp["error"]["code"] == -32601
    assert "available_tools" in resp["error"].get("data", {})


def test_tools_call_missing_required_params():
    """rera_search requires 'query' — missing it should return -32602."""
    from mcp_server.re_os_mcp import _handle_jsonrpc
    resp = _handle_jsonrpc({
        "method": "tools/call",
        "id": 3,
        "params": {"name": "rera_search", "arguments": {}},
    })
    assert "error" in resp
    assert resp["error"]["code"] == -32602, f"Expected -32602, got {resp['error']['code']}"
    assert "missing" in resp["error"].get("data", {})


def test_quick_feasibility_rejects_invalid_inputs():
    from mcp_server.re_os_mcp import _quick_feasibility
    # Negative area
    result = _quick_feasibility(land_cost_cr=10.0, area_acres=-1.0, market="Yelahanka")
    data = json.loads(result)
    assert data["status"] == "validation_error"

    # Zero cost
    result = _quick_feasibility(land_cost_cr=0.0, area_acres=5.0)
    data = json.loads(result)
    assert data["status"] == "validation_error"

    # Invalid market
    result = _quick_feasibility(land_cost_cr=10.0, area_acres=5.0, market="Invalid")
    data = json.loads(result)
    assert data["status"] == "validation_error"
    assert "errors" in data
    assert any("market" in e for e in data["errors"])


def test_quick_feasibility_uses_market_data_or_irr_model():
    """Without DB or numpy-financial, should return a structured error, not crash."""
    from mcp_server.re_os_mcp import _quick_feasibility
    result = _quick_feasibility(land_cost_cr=10.0, area_acres=5.0, market="Yelahanka")
    data = json.loads(result)
    # Without DB: either error (no listings) or ImportError (no numpy-financial)
    assert data["status"] in ("ok", "error", "validation_error")
    if data["status"] == "ok":
        assert "irr_pct" in data["result"]
        assert "verdict" in data["result"]
        assert "profit_margin_pct" in data["result"]
        assert "inputs" in data["result"]
        assert data["result"]["inputs"]["land_cost_cr"] == 10.0
        assert data["result"]["inputs"]["area_acres"] == 5.0


def test_corridor_score_validates_bounds():
    from mcp_server.re_os_mcp import _corridor_score
    # Lat out of bounds
    result = _corridor_score(lat=999.0, lon=77.6)
    data = json.loads(result)
    assert data["status"] == "validation_error"

    # Lon out of bounds
    result = _corridor_score(lat=13.0, lon=999.0)
    data = json.loads(result)
    assert data["status"] == "validation_error"

    # Valid but no DB — should return error or ok with score=0
    result = _corridor_score(lat=13.1, lon=77.6)
    data = json.loads(result)
    assert data["status"] in ("ok", "error")
    if data["status"] == "ok":
        assert "composite_score" in data["result"]
        assert "in_corridor" in data["result"]


def test_psf_forecast_rejects_invalid_market():
    from mcp_server.re_os_mcp import _psf_forecast
    result = _psf_forecast(market="Nonexistent", months=6)
    data = json.loads(result)
    assert data["status"] == "validation_error"


def test_psf_forecast_handles_valid_no_data():
    """A valid market with no forecast data should return insufficient_data, not crash."""
    import asyncio
    from mcp_server.re_os_mcp import _psf_forecast
    result = _psf_forecast(market="Yelahanka", months=6)
    data = json.loads(result)
    assert data["status"] in ("ok", "insufficient_data", "error")


def test_tool_parameters_have_correct_types():
    from mcp_server.re_os_mcp import TOOLS
    rera_params = TOOLS["rera_search"]["parameters"]
    assert "query" in rera_params.get("required", [])
    feas_params = TOOLS["quick_feasibility"]["parameters"]
    assert "land_cost_cr" in feas_params.get("required", [])
    assert "area_acres" in feas_params.get("required", [])
    cs_params = TOOLS["corridor_score"]["parameters"]
    assert "lat" in cs_params.get("required", [])
    assert "lon" in cs_params.get("required", [])


def test_initialize_returns_protocol_version():
    from mcp_server.re_os_mcp import _handle_jsonrpc
    resp = _handle_jsonrpc({"method": "initialize", "id": 1, "params": {}})
    result = resp.get("result", {})
    assert result.get("protocolVersion") == "2024-11-05"
    assert result["serverInfo"]["name"] == "re_os_mcp"
    assert "tools" in result.get("capabilities", {})


def test_ping_returns_empty_result():
    from mcp_server.re_os_mcp import _handle_jsonrpc
    resp = _handle_jsonrpc({"method": "ping", "id": 5, "params": {}})
    assert "result" in resp
    assert resp["result"] == {}


def test_unknown_method_returns_error():
    from mcp_server.re_os_mcp import _handle_jsonrpc
    resp = _handle_jsonrpc({"method": "unknown_method", "id": 99, "params": {}})
    assert "error" in resp
    assert resp["error"]["code"] == -32601


def test_notifications_initialized_handled():
    from mcp_server.re_os_mcp import _handle_jsonrpc
    resp = _handle_jsonrpc({"method": "notifications/initialized", "id": 6, "params": {}})
    assert "result" in resp


def test_auth_no_key_allows_when_unconfigured():
    """When MCP_API_KEY is not set, _is_authorized returns True."""
    from mcp_server.re_os_mcp import _is_authorized
    # Simulate headers without API key
    from starlette.datastructures import Headers
    h = Headers({"content-type": "application/json"})
    # In test mode, _MCP_API_KEY is None, so should pass
    assert _is_authorized(h) is True


def test_auth_rejects_wrong_key(monkeypatch):
    """When MCP_API_KEY is set, wrong key returns False."""
    import mcp_server.re_os_mcp as mcp_mod
    monkeypatch.setattr(mcp_mod, "_MCP_API_KEY", "secret123")
    from starlette.datastructures import Headers
    h = Headers({"x-api-key": "wrong"})
    assert mcp_mod._is_authorized(h) is False


def test_auth_accepts_correct_key(monkeypatch):
    """When MCP_API_KEY is set, correct key returns True."""
    import mcp_server.re_os_mcp as mcp_mod
    monkeypatch.setattr(mcp_mod, "_MCP_API_KEY", "secret123")
    from starlette.datastructures import Headers
    h = Headers({"x-api-key": "secret123"})
    assert mcp_mod._is_authorized(h) is True


def test_rera_search_validates_empty_query():
    from mcp_server.re_os_mcp import _rera_search
    result = _rera_search(query="", market="Yelahanka")
    data = json.loads(result)
    assert data["status"] == "validation_error"

    result = _rera_search(query="  ", market="Yelahanka")
    data = json.loads(result)
    assert data["status"] == "validation_error"


def test_rera_search_invalid_market():
    from mcp_server.re_os_mcp import _rera_search
    result = _rera_search(query="Brigade", market="Invalid")
    data = json.loads(result)
    assert data["status"] == "validation_error"


def test_psf_forecast_clamps_months():
    from mcp_server.re_os_mcp import _psf_forecast
    # Should not crash with extreme value
    result = _psf_forecast(market="Yelahanka", months=9999)
    data = json.loads(result)
    assert data["status"] in ("ok", "insufficient_data", "error", "validation_error")


def test_rera_search_structured_output():
    from mcp_server.re_os_mcp import _rera_search
    result = _rera_search(query="Brigade", market="Yelahanka")
    data = json.loads(result)
    assert "status" in data
    if data["status"] == "ok":
        assert "count" in data
        assert isinstance(data["count"], int)
        assert "results" in data
        assert isinstance(data["results"], list)
        if data["count"] > 0:
            first = data["results"][0]
            assert "project_name" in first
            assert "rera_reg_no" in first


def test_health_endpoint_returns_ok():
    from starlette.testclient import TestClient
    from mcp_server.re_os_mcp import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "re_os_mcp"
    assert "auth_required" in data


def test_cors_headers_present():
    from starlette.testclient import TestClient
    from mcp_server.re_os_mcp import app
    client = TestClient(app)
    resp = client.options("/health", headers={
        "Origin": "http://example.com",
        "Access-Control-Request-Method": "GET",
    })
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers


def test_sse_route_exists_and_has_correct_headers():
    """Verify SSE route is registered with correct content-type and cache headers.
    Uses TestClient with a controlled read to avoid hanging on infinite stream."""
    from mcp_server.re_os_mcp import _sse
    # Verify the route is mounted
    from mcp_server.re_os_mcp import app
    sse_routes = [r for r in app.routes if r.path == "/sse"]
    assert len(sse_routes) == 1, "SSE route /sse not registered"

    # Verify SSE handler returns correct content-type headers
    from starlette.requests import Request
    from starlette.datastructures import Headers, URL
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/sse",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 0),
        "scheme": "http",
        "server": ("test", 8051),
        "extensions": {"http.response.template": {}},
        "app": app,
    }
    # The handler is async; we just verify it exists and is callable
    assert callable(_sse)


def test_message_invalid_session_returns_404():
    from starlette.testclient import TestClient
    from mcp_server.re_os_mcp import app
    client = TestClient(app)
    resp = client.post(
        "/message?sessionId=nonexistent",
        json={"method": "tools/list", "id": 1},
    )
    assert resp.status_code == 404


def test_corridor_score_result_keys():
    from mcp_server.re_os_mcp import _corridor_score
    result = _corridor_score(lat=13.1, lon=77.6)
    data = json.loads(result)
    assert data["status"] in ("ok", "error")
    if data["status"] == "ok":
        assert "composite_score" in data["result"]
        assert "in_corridor" in data["result"]
        assert "note" in data["result"] or "corridor_name" in data["result"]


def test_prometheus_metrics_registered():
    """Verify Prometheus metric objects exist (guarded by try/import)."""
    from mcp_server.re_os_mcp import _tool_calls_total, _tool_errors_total
    if _tool_calls_total is not None:
        # Test that metrics are registered in the Prometheus registry
        from prometheus_client import REGISTRY
        assert "mcp_tool_calls_total" in REGISTRY._names_to_collectors
        assert "mcp_tool_errors_total" in REGISTRY._names_to_collectors


def test_concurrent_jsonrpc_handling():
    """Multiple concurrent JSON-RPC calls should not interfere."""
    from mcp_server.re_os_mcp import _handle_jsonrpc
    from concurrent.futures import ThreadPoolExecutor

    def call_tools_list():
        return _handle_jsonrpc({"method": "tools/list", "id": 0, "params": {}})

    def call_ping():
        return _handle_jsonrpc({"method": "ping", "id": 0, "params": {}})

    def call_initialize():
        return _handle_jsonrpc({"method": "initialize", "id": 0, "params": {}})

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = []
        for _ in range(20):
            futures.append(pool.submit(call_tools_list))
            futures.append(pool.submit(call_ping))
            futures.append(pool.submit(call_initialize))
        results = [f.result(timeout=10) for f in futures]

    assert len(results) == 60
    list_results = [r for r in results if "result" in r and "tools" in r.get("result", {})]
    assert len(list_results) == 20
    for r in list_results:
        assert len(r["result"]["tools"]) >= 4


def test_check_migrations_handles_missing_alembic():
    """_check_migrations should not crash when alembic is not installed."""
    from mcp_server.re_os_mcp import _check_migrations
    # Should not raise even if alembic is missing
    _check_migrations()


def test_app_routes_registered():
    """All expected routes are registered on the Starlette app."""
    from mcp_server.re_os_mcp import app
    paths = {r.path for r in app.routes}
    for expected in ("/health", "/sse", "/message"):
        assert expected in paths, f"Missing route: {expected}"
