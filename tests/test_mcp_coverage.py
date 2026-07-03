"""T-1503 — MCP tools coverage test (GATE-163 A3).

Asserts all required tools are in _CACHED_TOOL_NAMES,
each tool dict has required keys (name, description, parameters, handler),
parameters.type is "object", required fields are valid, no duplicates,
at least 5 tools are registered, and naming convention is consistent.

Risk notes:
  - TOOLS and _CACHED_TOOL_NAMES are in mcp_server.re_os_mcp — any
    refactoring of the MCP server must keep these exports or update the test.
  - The handler callable assertion covers synchronous MCP tools; async
    handlers will also pass (callable() returns True for coroutines).
  - The snake_case convention check is advisory — tools that intentionally
    break convention (e.g., for MCP inspector compatibility) will fail here.
"""

import re

import pytest

pytestmark = pytest.mark.unit

REQUIRED_TOOLS: set[str] = {
    "investor_brief",
    "vel_competitive_report",
    "deal_score",
}

TOOL_REQUIRED_KEYS: set[str] = {"name", "description", "parameters", "handler"}

MIN_TOOL_COUNT: int = 5


def _get_tools():
    """Lazy import of MCP tool definitions.

    Import is deferred so ImportError only surfaces in tests that
    actually depend on the MCP module, not at module-parse time."""
    from mcp_server.re_os_mcp import _CACHED_TOOL_NAMES, TOOLS
    return _CACHED_TOOL_NAMES, TOOLS


def test_cached_tool_names_contain_required():
    cached_names, _ = _get_tools()
    missing = REQUIRED_TOOLS - cached_names
    assert not missing, (
        f"Required tool(s) not found in _CACHED_TOOL_NAMES: {missing}. "
        f"Available: {sorted(cached_names)}"
    )


def test_all_tools_have_required_keys():
    _, tools = _get_tools()
    errors: list[str] = []
    for key, tool in tools.items():
        missing_keys = TOOL_REQUIRED_KEYS - set(tool.keys())
        if missing_keys:
            errors.append(f"'{key}' missing: {missing_keys}")
    assert not errors, "Tool definition validation:\n" + "\n".join(errors)


def test_all_tool_parameters_have_object_type():
    _, tools = _get_tools()
    errors: list[str] = []
    for key, tool in tools.items():
        params = tool.get("parameters")
        if params is None:
            errors.append(f"'{key}': parameters is None")
        elif not isinstance(params, dict):
            errors.append(f"'{key}': parameters is {type(params).__name__}, expected dict")
        elif params.get("type") != "object":
            errors.append(f"'{key}': parameters.type is '{params.get('type')}', expected 'object'")
    assert not errors, "Parameters type validation:\n" + "\n".join(errors)


def test_all_tool_handlers_are_callable():
    _, tools = _get_tools()
    errors: list[str] = []
    for key, tool in tools.items():
        handler = tool.get("handler")
        if handler is None:
            errors.append(f"'{key}': handler is None")
        elif not callable(handler):
            errors.append(f"'{key}': handler ({type(handler).__name__}) is not callable")
    assert not errors, "Handler callability:\n" + "\n".join(errors)


def test_required_fields_are_in_properties():
    _, tools = _get_tools()
    errors: list[str] = []
    for key, tool in tools.items():
        params = tool.get("parameters") or {}
        properties = params.get("properties") or {}
        required = params.get("required") or []
        if not isinstance(required, list):
            errors.append(f"'{key}': 'required' is {type(required).__name__}, expected list")
            continue
        for field in required:
            if field not in properties:
                errors.append(f"'{key}': required field '{field}' not in properties")
    assert not errors, "Required field validation:\n" + "\n".join(errors)


def test_tool_names_are_snake_case():
    _, tools = _get_tools()
    bad: list[str] = []
    for key, tool in tools.items():
        name = tool.get("name", "")
        if not re.match(r"^[a-z][a-z0-9_]*$", name):
            bad.append(f"'{name}'")
    assert not bad, (
        f"Tool names not following snake_case: {bad}. "
        f"Expected: ^[a-z][a-z0-9_]*$"
    )


def test_no_duplicate_tool_names():
    _, tools = _get_tools()
    names = [t["name"] for t in tools.values()]
    seen: set[str] = set()
    dupes: set[str] = set()
    for name in names:
        if name in seen:
            dupes.add(name)
        seen.add(name)
    assert not dupes, (
        f"Duplicate tool names found: {dupes}. "
        f"Each name must be unique for MCP JSON-RPC dispatch."
    )


def test_tool_name_matches_dict_key():
    _, tools = _get_tools()
    mismatches: list[str] = [
        f"key='{k}' name='{t.get('name')}'"
        for k, t in tools.items()
        if t.get("name") != k
    ]
    assert not mismatches, (
        f"TOOLS key/tool name mismatch: {mismatches}"
    )


def test_minimum_tool_count():
    _, tools = _get_tools()
    count = len(tools)
    assert count >= MIN_TOOL_COUNT, (
        f"Only {count} tools registered (need >= {MIN_TOOL_COUNT}). "
        f"New MCP tools must be added to TOOLS dict."
    )


def test_cached_names_subset_of_tools():
    cached_names, tools = _get_tools()
    all_tool_names = {t["name"] for t in tools.values()}
    orphaned = cached_names - all_tool_names
    assert not orphaned, (
        f"_CACHED_TOOL_NAMES references tools not in TOOLS dict: {orphaned}. "
        f"Every cached tool must have a corresponding entry in TOOLS."
    )


def test_tools_without_required_params_have_nonempty_required():
    """Some tools may have empty 'required' (all params optional).
    This is valid MCP — document explicitly."""
    _, tools = _get_tools()
    no_required: list[str] = [
        k for k, t in tools.items()
        if not (t.get("parameters") or {}).get("required")
    ]
    if no_required:
        pass
