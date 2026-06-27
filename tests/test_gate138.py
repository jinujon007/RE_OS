"""GATE-138: MCP Server Auth + Rate Limiting — 5 assertions."""
import pytest
pytestmark = pytest.mark.unit


def test_mcp_api_key_referenced():
    """Assert 1: MCP_API_KEY referenced in mcp_server/re_os_mcp.py."""
    import inspect
    from mcp_server import re_os_mcp
    src = inspect.getsource(re_os_mcp)
    assert "MCP_API_KEY" in src, "MCP_API_KEY must be referenced in re_os_mcp.py"


def test_clear_mcp_cache_importable():
    """Assert 2: _clear_mcp_cache importable from mcp_server.re_os_mcp."""
    from mcp_server.re_os_mcp import _clear_mcp_cache
    assert callable(_clear_mcp_cache)
    _clear_mcp_cache()


def test_rate_limiter_structure():
    """Assert 3: _rate_limiter dict exists in mcp_server module."""
    import mcp_server.re_os_mcp as mcp
    assert hasattr(mcp, "_RATE_LIMITER"), "_RATE_LIMITER not found in mcp_server.re_os_mcp"
    assert hasattr(mcp, "_check_rate_limit"), "_check_rate_limit not found"
    assert callable(mcp._check_rate_limit)


def test_mcp_health_route_registered():
    """Assert 4: /api/v1/mcp/health route registered in dashboard routers.

    The route lives under the health router mounted at /api/v1/ prefix,
    making it accessible at /api/v1/mcp/health. Legacy /api/mcp/health
    is redirected via the legacy API redirect handler.
    """
    from dashboard.app_fastapi import app
    found = False
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if "/api/v1/mcp/health" in path and "GET" in methods:
            found = True
            break
    assert found, "/api/v1/mcp/health GET route not found in FastAPI app"


def test_env_example_has_mcp_api_key():
    """Assert 5: MCP_API_KEY= present in .env.example."""
    import pathlib
    env_example = pathlib.Path(".env.example").read_text(encoding="utf-8")
    assert "MCP_API_KEY=" in env_example, ".env.example must contain MCP_API_KEY="
