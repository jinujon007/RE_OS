"""GATE-135 — RE_OS as MCP Server: Intelligence Tools Exposed.

5 assertions (all code-verifiable without Docker):
A1: mcp_server.re_os_mcp importable; TOOLS dict has 4 entries; app is Starlette
A2: All 4 tools register in tools/list response with inputSchema
A3: docker-compose.yml has re_os_mcp service on port 8051 + healthcheck
A4: .claude/settings.json has re_os MCP entry (type: sse, url: .../sse)
A5: rera_search produces structured output with status + count + results keys
"""

import json
import pathlib

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_gate135_a1_importable():
    from mcp_server.re_os_mcp import TOOLS, app, _rera_search, _is_authorized

    assert isinstance(TOOLS, dict)
    assert len(TOOLS) >= 4
    assert callable(_rera_search)
    assert callable(_is_authorized)

    assert hasattr(app, "routes")

    for name in ("rera_search", "psf_forecast", "quick_feasibility", "corridor_score"):
        assert name in TOOLS, f"Missing tool: {name}"
        tool = TOOLS[name]
        assert "name" in tool
        assert "description" in tool
        assert "handler" in tool
        assert callable(tool["handler"])
        assert "parameters" in tool


def test_gate135_a2_tools_list():
    from mcp_server.re_os_mcp import _handle_jsonrpc

    resp = _handle_jsonrpc({"method": "tools/list", "id": 1, "params": {}})
    assert "result" in resp
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    for name in ("rera_search", "psf_forecast", "quick_feasibility", "corridor_score"):
        assert name in tool_names, f"tools/list missing {name}"

    for t in tools:
        assert "inputSchema" in t, f"{t['name']}: missing inputSchema"
        assert "properties" in t["inputSchema"], f"{t['name']}: inputSchema missing properties"
        assert isinstance(t["inputSchema"]["properties"], dict)


def test_gate135_a3_docker_compose():
    dc_path = REPO_ROOT / "docker-compose.yml"
    raw = dc_path.read_text(encoding="utf-8")

    # Parse yaml-like block: find the re_os_mcp service section
    assert "re_os_mcp:" in raw, "docker-compose.yml missing re_os_mcp service"

    # Extract lines between "re_os_mcp:" and the next top-level service or end
    lines = raw.splitlines()
    mcp_start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("re_os_mcp:"))
    mcp_block = []
    for ln in lines[mcp_start + 1:]:
        if not ln or ln.startswith("  "):  # indented = still in same service block
            mcp_block.append(ln)
        else:
            break

    block_text = "\n".join(mcp_block)
    assert "8051:8051" in block_text, "re_os_mcp missing port mapping 8051:8051"
    assert "mcp_server/re_os_mcp.py" in block_text, "re_os_mcp missing command"
    assert "healthcheck" in block_text, "re_os_mcp missing healthcheck"
    assert "urlopen" in block_text, "re_os_mcp healthcheck missing connectivity test"
    assert "python" in block_text, "re_os_mcp healthcheck must use python"


def test_gate135_a4_claude_settings():
    settings_path = REPO_ROOT / ".claude" / "settings.json"
    content = settings_path.read_text(encoding="utf-8")
    settings = json.loads(content)

    mcp_servers = settings.get("mcpServers", {})
    assert "re_os" in mcp_servers, ".claude/settings.json missing re_os MCP entry"

    entry = mcp_servers["re_os"]
    assert entry.get("type") == "sse", "re_os MCP should use SSE transport"
    assert "/sse" in entry.get("url", ""), "re_os MCP URL should point to /sse"
    assert "8051" in entry.get("url", ""), "re_os MCP URL should use port 8051"


def test_gate135_a5_rera_search_structured():
    from mcp_server.re_os_mcp import _rera_search

    result = _rera_search(query="Brigade", market="Yelahanka")
    data = json.loads(result)
    assert "status" in data, "rera_search result must have status key"
    assert data["status"] in ("ok", "error", "validation_error")

    if data["status"] == "ok":
        assert "count" in data
        assert isinstance(data["count"], int)
        assert "results" in data
        assert isinstance(data["results"], list)
        if data["count"] > 0:
            first = data["results"][0]
            assert "project_name" in first
            assert "rera_reg_no" in first
